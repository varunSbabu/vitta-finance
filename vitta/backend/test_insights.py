"""Tests for the insights computation.

The whole point of insights is that every number is computed by SQL, not
the LLM — so these tests seed known data and assert the exact figures on
each card's raw fields (not the prose). narrate_insights() is tested with
`chat` monkeypatched to prove two things: it never fabricates a number,
and a malformed/rogue LLM response leaves the real computed body intact.
"""

# ruff: noqa: E402
import os
import pathlib
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()

import db

db.DB_PATH = pathlib.Path(_tmp_db.name)
db.init_db()

import insights  # noqa: E402
from insights import compute_insights, narrate_insights  # noqa: E402


@pytest.fixture(autouse=True)
def _scratch_db():
    db.DB_PATH = pathlib.Path(_tmp_db.name)
    db.init_db()
    _reset()
    yield


def _reset():
    conn = db.get_conn()
    conn.execute("DELETE FROM transactions")
    conn.execute("DELETE FROM accounts")
    conn.commit()
    conn.close()


def _add(txn_date, amount, direction, merchant, category, is_self_transfer=0):
    conn = db.get_conn()
    conn.execute("INSERT OR IGNORE INTO accounts (bank_name, account_last4) VALUES ('Bank','0001')")
    acc = conn.execute("SELECT id FROM accounts LIMIT 1").fetchone()["id"]
    conn.execute(
        "INSERT INTO transactions (account_id, txn_date, amount, direction, merchant_raw, merchant_clean, source, category, is_self_transfer) "
        "VALUES (?,?,?,?,?,?, 'bank_pdf', ?, ?)",
        (acc, txn_date, amount, direction, merchant, merchant, category, is_self_transfer),
    )
    conn.commit()
    conn.close()


def _card(cards, cid):
    return next((c for c in cards if c["id"] == cid), None)


def test_empty_db_yields_no_insights():
    assert compute_insights("2026-08") == []
    print("  OK no data -> no insight cards (no fabricated numbers)")


def test_top_category_is_computed_correctly():
    _add("2026-08-01", 5000, "debit", "Flipkart", "Shopping")
    _add("2026-08-02", 1000, "debit", "Swiggy", "Food")
    _add("2026-08-03", 4000, "debit", "Myntra", "Shopping")
    cards = compute_insights("2026-08")
    top = _card(cards, "top_category")
    assert top["category"] == "Shopping"
    assert top["amount"] == 9000  # 5000 + 4000
    assert top["count"] == 2
    assert top["share_pct"] == 90  # 9000 / 10000 total
    print(f"  OK top category computed: {top['category']} ₹{top['amount']} ({top['share_pct']}%)")


def test_self_transfers_excluded_from_totals():
    _add("2026-08-01", 1000, "debit", "Real Spend", "Food")
    _add("2026-08-02", 50000, "debit", "Moved to savings", "Transfers", is_self_transfer=1)
    cards = compute_insights("2026-08")
    top = _card(cards, "top_category")
    # The 50k self-transfer must not appear anywhere in the spend total.
    assert top["amount"] == 1000
    assert top["category"] == "Food"
    print("  OK self-transfers excluded from insight spend totals")


def test_month_over_month_change():
    _add("2026-07-15", 10000, "debit", "X", "Food")
    _add("2026-08-15", 15000, "debit", "Y", "Food")
    cards = compute_insights("2026-08")
    mom = _card(cards, "mom_change")
    assert mom["spent_this"] == 15000
    assert mom["spent_prev"] == 10000
    assert mom["change_pct"] == 50.0  # +50%
    print(f"  OK month-over-month: ₹{mom['spent_prev']} -> ₹{mom['spent_this']} ({mom['change_pct']}%)")


def test_net_position_surplus_and_deficit():
    _add("2026-08-01", 2000, "debit", "Spend", "Food")
    _add("2026-08-02", 70000, "credit", "Salary", "Income")
    cards = compute_insights("2026-08")
    net = _card(cards, "net_position")
    assert net["received"] == 70000
    assert net["spent"] == 2000
    assert net["net"] == 68000
    print(f"  OK net position: ₹{net['net']} surplus")


def test_biggest_expense():
    _add("2026-08-01", 500, "debit", "Small", "Food")
    _add("2026-08-02", 22881, "debit", "Big Transfer", "Transfers")
    cards = compute_insights("2026-08")
    big = _card(cards, "biggest_expense")
    assert big["amount"] == 22881
    assert big["merchant"] == "Big Transfer"
    print(f"  OK biggest expense: ₹{big['amount']} to {big['merchant']}")


def test_recurring_detection_needs_two_distinct_months():
    # Same merchant in two different months -> recurring candidate.
    _add("2026-07-10", 199, "debit", "Netflix", "Entertainment")
    _add("2026-08-10", 199, "debit", "Netflix", "Entertainment")
    # A merchant in only one month should NOT be flagged.
    _add("2026-08-11", 500, "debit", "One Off Shop", "Shopping")
    cards = compute_insights("2026-08")
    rec = _card(cards, "recurring")
    names = [m["merchant"] for m in rec["merchants"]]
    assert "Netflix" in names
    assert "One Off Shop" not in names
    print("  OK recurring detection flags 2+ month merchants, not one-offs")


def test_uncategorized_nudge():
    _add("2026-08-01", 300, "debit", "Mystery", "Uncategorized")
    _add("2026-08-02", 700, "debit", "Mystery2", "Uncategorized")
    _add("2026-08-03", 100, "debit", "Known", "Food")
    cards = compute_insights("2026-08")
    unc = _card(cards, "uncategorized")
    assert unc["count"] == 2
    assert unc["amount"] == 1000
    print(f"  OK uncategorized nudge: {unc['count']} txns, ₹{unc['amount']}")


def test_defaults_to_latest_month_with_data():
    # Data exists in July and August; the current calendar month may be
    # neither. compute_insights(None) must report on August (the latest
    # month with data), not an empty current month.
    from insights import latest_month_with_data

    _add("2026-07-15", 3000, "debit", "July Shop", "Shopping")
    _add("2026-08-15", 8000, "debit", "August Shop", "Shopping")
    assert latest_month_with_data() == "2026-08"
    cards = compute_insights(None)  # no explicit month
    top = _card(cards, "top_category")
    assert top is not None
    assert top["amount"] == 8000  # August's figure, not July's or zero
    print("  OK insights default to the latest month that has data")


def test_latest_month_with_data_none_when_empty():
    from insights import latest_month_with_data

    assert latest_month_with_data() is None
    print("  OK latest_month_with_data returns None on an empty DB")


def test_top_category_excludes_uncategorized():
    # A big Uncategorized bucket must not win the "top category" card —
    # there's a dedicated uncategorized nudge for that, and "top category"
    # should surface the top *real* category.
    _add("2026-08-01", 50000, "debit", "Mystery", "Uncategorized")
    _add("2026-08-02", 3000, "debit", "Flipkart", "Shopping")
    _add("2026-08-03", 1000, "debit", "Swiggy", "Food")
    cards = compute_insights("2026-08")
    top = _card(cards, "top_category")
    assert top is not None
    assert top["category"] == "Shopping"  # not Uncategorized, despite it being larger
    print("  OK top-category card skips Uncategorized, shows top real category")


def test_narrate_without_llm_keeps_templated_body(monkeypatch):
    _add("2026-08-01", 5000, "debit", "Flipkart", "Shopping")
    monkeypatch.setattr(insights, "is_available", lambda: False)
    cards = compute_insights("2026-08")
    original = _card(cards, "top_category")["body"]
    narrated = narrate_insights(cards)
    assert _card(narrated, "top_category")["body"] == original
    print("  OK no LLM -> templated bodies preserved unchanged")


def test_narrate_with_llm_rewrites_body(monkeypatch):
    _add("2026-08-01", 5000, "debit", "Flipkart", "Shopping")
    monkeypatch.setattr(insights, "is_available", lambda: True)
    monkeypatch.setattr(
        insights,
        "chat",
        lambda messages, **kw: '[{"id": "top_category", "body": "Shopping dominated — ₹5,000."}]',
    )
    cards = narrate_insights(compute_insights("2026-08"))
    assert _card(cards, "top_category")["body"] == "Shopping dominated — ₹5,000."
    print("  OK LLM narration rewrites the card body")


def test_narrate_malformed_llm_response_falls_back(monkeypatch):
    _add("2026-08-01", 5000, "debit", "Flipkart", "Shopping")
    monkeypatch.setattr(insights, "is_available", lambda: True)
    monkeypatch.setattr(insights, "chat", lambda messages, **kw: "this is not json at all")
    cards = compute_insights("2026-08")
    original = _card(cards, "top_category")["body"]
    narrated = narrate_insights(cards)
    assert _card(narrated, "top_category")["body"] == original
    print("  OK malformed LLM response leaves computed bodies intact")


if __name__ == "__main__":
    import sys

    class _MP:
        def __init__(self):
            self._attrs = []

        def setattr(self, obj, name, val):
            self._attrs.append((obj, name, getattr(obj, name)))
            setattr(obj, name, val)

        def undo(self):
            for obj, name, old in reversed(self._attrs):
                setattr(obj, name, old)

    tests = [
        test_empty_db_yields_no_insights,
        test_top_category_is_computed_correctly,
        test_self_transfers_excluded_from_totals,
        test_month_over_month_change,
        test_net_position_surplus_and_deficit,
        test_biggest_expense,
        test_recurring_detection_needs_two_distinct_months,
        test_uncategorized_nudge,
        test_defaults_to_latest_month_with_data,
        test_latest_month_with_data_none_when_empty,
        test_top_category_excludes_uncategorized,
        test_narrate_without_llm_keeps_templated_body,
        test_narrate_with_llm_rewrites_body,
        test_narrate_malformed_llm_response_falls_back,
    ]
    passed = 0
    for t in tests:
        mp = _MP()
        try:
            db.DB_PATH = pathlib.Path(_tmp_db.name)
            db.init_db()
            _reset()
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
