"""Tests for self-transfer detection."""

# ruff: noqa: E402 — db.DB_PATH must be pointed at a scratch file before
# `import db` triggers anything that opens a connection.
import os
import pathlib
import tempfile

import pytest

# Point db.py at a scratch DB before importing modules that use it.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()

import db

db.DB_PATH = pathlib.Path(_tmp_db.name)
db.init_db()

from self_transfer import detect_self_transfers  # noqa: E402


@pytest.fixture(autouse=True)
def _scratch_db():
    """See the identical fixture in test_contacts.py for why this is
    needed: pytest collects (imports) every test file before running any
    test function, and other files in this suite also reassign the shared
    db.DB_PATH global at import time. Re-asserting it here, immediately
    before each test, makes this file's tests correct regardless of
    collection order."""
    db.DB_PATH = pathlib.Path(_tmp_db.name)
    db.init_db()
    yield


def _reset():
    conn = db.get_conn()
    conn.execute("DELETE FROM transactions")
    conn.execute("DELETE FROM accounts")
    conn.commit()
    conn.close()


def _make_account(bank: str, last4: str) -> int:
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO accounts (bank_name, account_last4) VALUES (?, ?)",
        (bank, last4),
    )
    conn.commit()
    acc_id = cur.lastrowid
    conn.close()
    return acc_id


def _make_txn(account_id: int, txn_date: str, amount: float, direction: str, merchant: str = "X") -> int:
    conn = db.get_conn()
    cur = conn.execute(
        """
        INSERT INTO transactions (account_id, txn_date, amount, direction, merchant_raw, merchant_clean, source, category)
        VALUES (?, ?, ?, ?, ?, ?, 'test', 'Uncategorized')
        """,
        (account_id, txn_date, amount, direction, merchant, merchant),
    )
    conn.commit()
    txn_id = cur.lastrowid
    conn.close()
    return txn_id


def _flags():
    conn = db.get_conn()
    rows = conn.execute("SELECT id, is_self_transfer FROM transactions ORDER BY id").fetchall()
    conn.close()
    return {r["id"]: r["is_self_transfer"] for r in rows}


def test_basic_pair_matches():
    _reset()
    a = _make_account("Indian Bank", "7318")
    b = _make_account("HDFC Bank", "4521")
    _make_txn(a, "2026-08-01", 20000, "debit")
    _make_txn(b, "2026-08-01", 20000, "credit")

    result = detect_self_transfers()
    assert result["pairs_found"] == 1
    assert all(v == 1 for v in _flags().values())
    print("  OK basic pair matches")


def test_same_account_does_not_match():
    _reset()
    a = _make_account("Indian Bank", "7318")
    _make_txn(a, "2026-08-01", 5000, "debit")
    _make_txn(a, "2026-08-01", 5000, "credit")

    result = detect_self_transfers()
    assert result["pairs_found"] == 0
    assert all(v == 0 for v in _flags().values())
    print("  OK same-account pair is NOT flagged (not a real cross-account transfer)")


def test_amount_mismatch_does_not_match():
    _reset()
    a = _make_account("Indian Bank", "7318")
    b = _make_account("HDFC Bank", "4521")
    _make_txn(a, "2026-08-01", 5000, "debit")
    _make_txn(b, "2026-08-01", 5001, "credit")

    result = detect_self_transfers()
    assert result["pairs_found"] == 0
    print("  OK amount mismatch does not match")


def test_within_window_matches():
    _reset()
    a = _make_account("Indian Bank", "7318")
    b = _make_account("HDFC Bank", "4521")
    _make_txn(a, "2026-08-01", 5000, "debit")
    _make_txn(b, "2026-08-03", 5000, "credit")  # exactly 2 days later

    result = detect_self_transfers()
    assert result["pairs_found"] == 1
    print("  OK match at exact window boundary (2 days)")


def test_outside_window_does_not_match():
    _reset()
    a = _make_account("Indian Bank", "7318")
    b = _make_account("HDFC Bank", "4521")
    _make_txn(a, "2026-08-01", 5000, "debit")
    _make_txn(b, "2026-08-05", 5000, "credit")  # 4 days later

    result = detect_self_transfers()
    assert result["pairs_found"] == 0
    print("  OK no match outside window (4 days)")


def test_picks_nearest_date_among_candidates():
    _reset()
    a = _make_account("Indian Bank", "7318")
    b = _make_account("HDFC Bank", "4521")
    debit_id = _make_txn(a, "2026-08-01", 5000, "debit")
    _make_txn(b, "2026-08-03", 5000, "credit")  # 2 days away
    near_credit_id = _make_txn(b, "2026-08-01", 5000, "credit")  # 0 days away — should win

    result = detect_self_transfers()
    assert result["pairs_found"] == 1
    matched_debit, matched_credit = result["pairs"][0]
    assert matched_debit == debit_id
    assert matched_credit == near_credit_id
    print("  OK nearest-date candidate wins over farther one")


def test_idempotent_on_rerun():
    _reset()
    a = _make_account("Indian Bank", "7318")
    b = _make_account("HDFC Bank", "4521")
    _make_txn(a, "2026-08-01", 5000, "debit")
    _make_txn(b, "2026-08-01", 5000, "credit")

    r1 = detect_self_transfers()
    r2 = detect_self_transfers()
    assert r1["pairs_found"] == 1
    assert r2["pairs_found"] == 0
    print("  OK idempotent — second run finds nothing already-flagged")


def test_real_expense_untouched():
    _reset()
    a = _make_account("Indian Bank", "7318")
    _make_txn(a, "2026-08-01", 350, "debit", "Swiggyinstamart")

    result = detect_self_transfers()
    assert result["pairs_found"] == 0
    assert all(v == 0 for v in _flags().values())
    print("  OK lone debit with no matching credit stays untouched")


if __name__ == "__main__":
    tests = [
        test_basic_pair_matches,
        test_same_account_does_not_match,
        test_amount_mismatch_does_not_match,
        test_within_window_matches,
        test_outside_window_does_not_match,
        test_picks_nearest_date_among_candidates,
        test_idempotent_on_rerun,
        test_real_expense_untouched,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  FAIL {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    os.unlink(_tmp_db.name)
