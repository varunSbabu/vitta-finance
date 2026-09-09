"""Tests for Ask Vitta's text-to-SQL layer.

The SQL-generation and narration steps call an LLM, so those are exercised
with `chat` monkeypatched — no network, no key needed. The security-critical
piece (`_validate_sql`) and the read-only executor are pure and are tested
directly and hardest, since they're the guarantee that a generated query
can neither mutate data nor read the users/password table.
"""

# ruff: noqa: E402 — db.DB_PATH must point at a scratch file before import db.
import os
import pathlib
import sqlite3
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()

import db

db.DB_PATH = pathlib.Path(_tmp_db.name)
db.init_db()

import text_to_sql  # noqa: E402
from text_to_sql import _validate_sql, answer_question  # noqa: E402

TEST_USER_ID = 1


@pytest.fixture(autouse=True)
def _scratch_db():
    db.DB_PATH = pathlib.Path(_tmp_db.name)
    text_to_sql.DB_PATH = pathlib.Path(_tmp_db.name)
    db.init_db()
    _ensure_test_user()
    yield


def _ensure_test_user():
    conn = db.get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO users (id, email, name) VALUES (?, 'test@example.com', 'Test')",
        (TEST_USER_ID,),
    )
    conn.commit()
    conn.close()


def _seed():
    conn = db.get_conn()
    conn.execute("DELETE FROM transactions")
    conn.execute("DELETE FROM accounts")
    conn.execute(
        "INSERT INTO accounts (user_id, bank_name, account_last4) VALUES (?, 'Indian Bank', '7318')",
        (TEST_USER_ID,),
    )
    acc = conn.execute("SELECT id FROM accounts WHERE user_id = ?", (TEST_USER_ID,)).fetchone()["id"]
    rows = [
        ("2026-08-01", 500, "debit", "Swiggy", "Food"),
        ("2026-08-02", 1500, "debit", "Flipkart", "Shopping"),
        ("2026-08-03", 200, "debit", "Auto", "Transport"),
        ("2026-08-04", 70000, "credit", "Payroll", "Income"),
    ]
    for d, amt, direction, m, cat in rows:
        conn.execute(
            "INSERT INTO transactions (user_id, account_id, txn_date, amount, direction, merchant_raw, merchant_clean, source, category) "
            "VALUES (?,?,?,?,?,?,?, 'bank_pdf', ?)",
            (TEST_USER_ID, acc, d, amt, direction, m, m, cat),
        )
    conn.commit()
    conn.close()


# ── _validate_sql: the security gate ────────────────────────────────


def test_validate_accepts_plain_select():
    ok, _ = _validate_sql("SELECT SUM(amount) FROM transactions WHERE user_id = :uid AND direction='debit'")
    assert ok is True
    print("  OK plain SELECT accepted")


def test_validate_accepts_cte():
    ok, _ = _validate_sql(
        "WITH x AS (SELECT amount FROM transactions WHERE user_id = :uid) SELECT SUM(amount) FROM x"
    )
    assert ok is True
    print("  OK WITH/CTE accepted")


def test_validate_rejects_non_select():
    for sql in [
        "DELETE FROM transactions",
        "UPDATE transactions SET amount=0",
        "INSERT INTO transactions (amount) VALUES (1)",
        "DROP TABLE transactions",
    ]:
        ok, reason = _validate_sql(sql)
        assert ok is False, f"should have rejected: {sql}"
    print("  OK mutating statements all rejected")


def test_validate_rejects_stacked_statements():
    ok, _ = _validate_sql("SELECT 1 FROM transactions; DELETE FROM transactions")
    assert ok is False
    print("  OK stacked second statement rejected")


def test_validate_rejects_users_table():
    for sql in [
        "SELECT * FROM users WHERE user_id = :uid",
        "SELECT password_hash FROM users WHERE user_id = :uid",
        "SELECT t.amount FROM transactions t JOIN users u ON 1=1 WHERE t.user_id = :uid",
    ]:
        ok, reason = _validate_sql(sql)
        assert ok is False, f"should have rejected users access: {sql}"
    print("  OK any reference to the users table is refused")


def test_validate_rejects_sqlite_internals_and_pragma():
    for sql in [
        "SELECT name FROM sqlite_master",
        "SELECT * FROM transactions; PRAGMA table_info(users)",
        "PRAGMA query_only=OFF",
    ]:
        ok, _ = _validate_sql(sql)
        assert ok is False, f"should have rejected: {sql}"
    print("  OK sqlite_ internals and PRAGMA rejected")


def test_validate_rejects_unknown_table():
    ok, reason = _validate_sql("SELECT * FROM secrets WHERE user_id = :uid")
    assert ok is False
    assert "secrets" in reason
    print("  OK query against an unknown table rejected")


def test_validate_rejects_empty():
    ok, _ = _validate_sql("   ")
    assert ok is False
    print("  OK empty query rejected")


def test_validate_rejects_missing_uid():
    ok, reason = _validate_sql("SELECT SUM(amount) FROM transactions WHERE direction='debit'")
    assert ok is False
    assert "uid" in reason
    print("  OK query without :uid is rejected")


# ── read-only execution ─────────────────────────────────────────────


def test_readonly_connection_blocks_writes():
    _seed()
    with pytest.raises(sqlite3.OperationalError):
        text_to_sql._run_readonly("DELETE FROM transactions", TEST_USER_ID)
    conn = db.get_conn()
    n = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    conn.close()
    assert n == 4
    print("  OK read-only connection refuses writes at the driver level")


def test_readonly_runs_real_aggregate():
    _seed()
    rows = text_to_sql._run_readonly(
        "SELECT SUM(amount) AS total FROM transactions WHERE user_id = :uid AND direction='debit'",
        TEST_USER_ID,
    )
    assert rows == [{"total": 2200}]
    print("  OK read-only executor returns correct aggregate (₹2,200 debit)")


def test_readonly_row_cap():
    _seed()
    rows = text_to_sql._run_readonly("SELECT * FROM transactions WHERE user_id = :uid", TEST_USER_ID)
    assert len(rows) <= text_to_sql.MAX_ROWS
    print("  OK row cap enforced")


# ── full flow with a monkeypatched LLM ──────────────────────────────


def test_answer_question_happy_path(monkeypatch):
    _seed()
    calls = {"n": 0}

    def fake_chat(messages, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return "SELECT SUM(amount) AS total FROM transactions WHERE user_id = :uid AND direction='debit' AND is_self_transfer=0"
        return "You've spent ₹2,200 so far."

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(text_to_sql, "chat", fake_chat)
    monkeypatch.setattr(text_to_sql, "is_available", lambda: True)

    result = answer_question("how much have I spent?", TEST_USER_ID)
    assert result["error"] is None
    assert result["rows"] == [{"total": 2200}]
    assert "2,200" in result["answer"]
    print("  OK full ask flow: generate SQL -> run -> narrate")


def test_answer_question_blocks_unsafe_generated_sql(monkeypatch):
    _seed()

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(text_to_sql, "chat", lambda messages, **kw: "DELETE FROM transactions")
    monkeypatch.setattr(text_to_sql, "is_available", lambda: True)

    result = answer_question("delete everything", TEST_USER_ID)
    assert result["error"].startswith("unsafe_sql")
    assert result["rows"] == []
    conn = db.get_conn()
    n = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    conn.close()
    assert n == 4
    print("  OK a generated write is caught by validation before it runs")


def test_answer_question_not_configured(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(text_to_sql, "is_available", lambda: False)
    result = answer_question("anything", TEST_USER_ID)
    assert result["error"] == "not_configured"
    print("  OK reports not_configured cleanly without a key")


def test_answer_question_empty():
    result = answer_question("   ", TEST_USER_ID)
    assert result["error"] == "empty"
    print("  OK empty question handled")


def test_null_scalar_result_reads_as_zero_not_null(monkeypatch):
    _seed()
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(
        text_to_sql,
        "chat",
        lambda messages, **kw: (
            "SELECT SUM(amount) AS total FROM transactions WHERE user_id = :uid AND category='Nonexistent'"
        ),
    )
    monkeypatch.setattr(text_to_sql, "is_available", lambda: True)
    result = answer_question("how much did I spend on nonexistent things?", TEST_USER_ID)
    assert result["error"] is None
    assert "null" not in result["answer"].lower()
    assert "0" in result["answer"]
    print("  OK null-sum result narrates as ₹0, not 'null'")


def test_is_empty_result_helper():
    assert text_to_sql._is_empty_result([]) is True
    assert text_to_sql._is_empty_result([{"total": None}]) is True
    assert text_to_sql._is_empty_result([{"n": 0}]) is True
    assert text_to_sql._is_empty_result([{"total": 100}]) is False
    print("  OK _is_empty_result treats null/zero single-row as empty")


if __name__ == "__main__":
    import sys

    class _MP:
        def __init__(self):
            self._env = {}
            self._attrs = []

        def setenv(self, k, v):
            self._env[k] = os.environ.get(k)
            os.environ[k] = v

        def delenv(self, k, raising=False):
            self._env[k] = os.environ.get(k)
            os.environ.pop(k, None)

        def setattr(self, obj, name, val):
            self._attrs.append((obj, name, getattr(obj, name)))
            setattr(obj, name, val)

        def undo(self):
            for obj, name, old in reversed(self._attrs):
                setattr(obj, name, old)
            for k, v in self._env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    tests = [
        test_validate_accepts_plain_select,
        test_validate_accepts_cte,
        test_validate_rejects_non_select,
        test_validate_rejects_stacked_statements,
        test_validate_rejects_users_table,
        test_validate_rejects_sqlite_internals_and_pragma,
        test_validate_rejects_unknown_table,
        test_validate_rejects_empty,
        test_validate_rejects_missing_uid,
        test_readonly_connection_blocks_writes,
        test_readonly_runs_real_aggregate,
        test_readonly_row_cap,
        test_answer_question_happy_path,
        test_answer_question_blocks_unsafe_generated_sql,
        test_answer_question_not_configured,
        test_answer_question_empty,
        test_null_scalar_result_reads_as_zero_not_null,
        test_is_empty_result_helper,
    ]
    passed = 0
    for t in tests:
        mp = _MP()
        try:
            db.DB_PATH = pathlib.Path(_tmp_db.name)
            text_to_sql.DB_PATH = pathlib.Path(_tmp_db.name)
            db.init_db()
            _ensure_test_user()
            if "monkeypatch" in t.__code__.co_varnames[: t.__code__.co_argcount]:
                t(mp)
            else:
                t()
            passed += 1
        except Exception as e:
            print(f"  FAIL {t.__name__}: {e!r}")
        finally:
            mp.undo()
    print(f"\n{passed}/{len(tests)} tests passed")
    os.unlink(_tmp_db.name)
    sys.exit(0 if passed == len(tests) else 1)
