"""Tests for manually-logged (cash) transactions.

Cash spending has no statement trail, so /api/transactions/manual is the
only way it enters the system. These tests cover: validation, auto-
categorization via the same Tier 1 rules as parsed transactions, the
virtual Cash account being created lazily and reused (not duplicated),
and that the delete endpoint can undo a manual entry but is refused for
anything statement-derived.
"""

import importlib
import os
import pathlib
import tempfile


def _fresh_app():
    """Reload db + main against a throwaway DB file with an authenticated
    TestClient session already established via password login."""
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()

    import db

    db.DB_PATH = pathlib.Path(tmp_db.name)
    db.init_db()

    os.environ["SESSION_SECRET_KEY"] = "test-only-key-for-manual-cash"
    os.environ["ALLOWED_EMAIL"] = ""  # open mode — any email may sign up in tests
    import auth

    importlib.reload(auth)
    import main

    importlib.reload(main)

    from fastapi.testclient import TestClient

    client = TestClient(main.app)
    client.post("/api/auth/signup", json={"email": "test@example.com", "password": "testpassword123"})

    return main, client, tmp_db.name


def test_add_cash_expense_auto_categorizes_via_rules():
    main, client, dbfile = _fresh_app()
    r = client.post(
        "/api/transactions/manual",
        json={
            "date": "2026-08-20",
            "amount": 60,
            "merchant": "Auto driver",
            "direction": "debit",
            "remark": "auto ride to station",
        },
    )
    assert r.status_code == 200
    assert r.json()["category"] == "Transport"
    os.unlink(dbfile)
    print("  OK cash expense runs through Tier 1 rules (remark 'auto ride' -> Transport)")


def test_add_cash_expense_falls_back_to_cash_category():
    main, client, dbfile = _fresh_app()
    r = client.post(
        "/api/transactions/manual",
        json={
            "date": "2026-08-20",
            "amount": 200,
            "merchant": "Local vendor",
            "direction": "debit",
        },
    )
    assert r.status_code == 200
    # No rule matches "Local vendor" with no remark — debit cash entries
    # default to 'Cash' rather than sitting fully Uncategorized, since the
    # user explicitly told us it was a cash spend.
    assert r.json()["category"] == "Cash"
    os.unlink(dbfile)
    print("  OK unmatched cash debit defaults to 'Cash' instead of Uncategorized")


def test_explicit_category_overrides_rules():
    main, client, dbfile = _fresh_app()
    r = client.post(
        "/api/transactions/manual",
        json={
            "date": "2026-08-20",
            "amount": 100,
            "merchant": "Swiggy",  # would normally rule-match Food
            "direction": "debit",
            "category": "Entertainment",
        },
    )
    assert r.status_code == 200
    assert r.json()["category"] == "Entertainment"
    os.unlink(dbfile)
    print("  OK caller-supplied category takes priority over rule matching")


def test_credit_direction_does_not_default_to_cash():
    main, client, dbfile = _fresh_app()
    r = client.post(
        "/api/transactions/manual",
        json={
            "date": "2026-08-20",
            "amount": 500,
            "merchant": "Birthday gift",
            "direction": "credit",
        },
    )
    assert r.status_code == 200
    # The 'default to Cash' fallback only makes sense for debits (money
    # leaving as cash spend) — a credit with no rule match should stay
    # genuinely Uncategorized, not be mislabeled as a cash expense.
    assert r.json()["category"] == "Uncategorized"
    os.unlink(dbfile)
    print("  OK unmatched credit stays Uncategorized, doesn't inherit the cash default")


def test_rejects_missing_amount():
    main, client, dbfile = _fresh_app()
    r = client.post("/api/transactions/manual", json={"date": "2026-08-20", "merchant": "Test"})
    assert r.status_code == 400
    os.unlink(dbfile)
    print("  OK missing amount rejected")


def test_rejects_negative_or_zero_amount():
    main, client, dbfile = _fresh_app()
    for amt in (0, -50):
        r = client.post(
            "/api/transactions/manual", json={"date": "2026-08-20", "amount": amt, "merchant": "Test"}
        )
        assert r.status_code == 400
    os.unlink(dbfile)
    print("  OK zero and negative amounts rejected")


def test_rejects_malformed_date():
    main, client, dbfile = _fresh_app()
    r = client.post("/api/transactions/manual", json={"date": "20-08-2026", "amount": 50, "merchant": "Test"})
    assert r.status_code == 400
    os.unlink(dbfile)
    print("  OK non-ISO date rejected")


def test_rejects_missing_merchant():
    main, client, dbfile = _fresh_app()
    r = client.post("/api/transactions/manual", json={"date": "2026-08-20", "amount": 50})
    assert r.status_code == 400
    os.unlink(dbfile)
    print("  OK missing merchant rejected")


def test_rejects_invalid_direction():
    main, client, dbfile = _fresh_app()
    r = client.post(
        "/api/transactions/manual",
        json={
            "date": "2026-08-20",
            "amount": 50,
            "merchant": "Test",
            "direction": "sideways",
        },
    )
    assert r.status_code == 400
    os.unlink(dbfile)
    print("  OK invalid direction value rejected")


def test_requires_auth():
    main, client, dbfile = _fresh_app()
    client.cookies.clear()
    r = client.post("/api/transactions/manual", json={"date": "2026-08-20", "amount": 50, "merchant": "Test"})
    assert r.status_code == 401
    os.unlink(dbfile)
    print("  OK manual entry endpoint requires a session")


def test_cash_account_created_once_and_reused():
    main, client, dbfile = _fresh_app()
    client.post("/api/transactions/manual", json={"date": "2026-08-20", "amount": 15, "merchant": "Chai"})
    client.post("/api/transactions/manual", json={"date": "2026-08-21", "amount": 60, "merchant": "Auto"})

    accounts = client.get("/api/accounts").json()
    cash_accounts = [a for a in accounts if a["bank_name"] == "Cash"]
    assert len(cash_accounts) == 1
    assert cash_accounts[0]["account_type"] == "cash"
    assert cash_accounts[0]["txn_count"] == 2
    os.unlink(dbfile)
    print("  OK virtual Cash account is created once and reused across entries")


def test_manual_entries_appear_in_transactions_and_summary():
    main, client, dbfile = _fresh_app()
    client.post(
        "/api/transactions/manual",
        json={
            "date": "2026-08-20",
            "amount": 100,
            "merchant": "Chai",
            "remark": "chai",
        },
    )
    txns = client.get("/api/transactions").json()
    assert txns["total"] == 1
    assert txns["transactions"][0]["source"] == "manual_cash"

    summary = client.get("/api/summary?month=2026-08").json()
    assert summary["spent"] == 100
    os.unlink(dbfile)
    print("  OK manual cash entries flow into /api/transactions and /api/summary")


def test_delete_manual_entry_succeeds():
    main, client, dbfile = _fresh_app()
    created = client.post(
        "/api/transactions/manual",
        json={
            "date": "2026-08-20",
            "amount": 50,
            "merchant": "Test",
        },
    ).json()
    r = client.delete(f"/api/transactions/{created['id']}")
    assert r.status_code == 200
    txns = client.get("/api/transactions").json()
    assert txns["total"] == 0
    os.unlink(dbfile)
    print("  OK deleting a manual entry removes it")


def test_delete_nonexistent_returns_404():
    main, client, dbfile = _fresh_app()
    r = client.delete("/api/transactions/99999")
    assert r.status_code == 404
    os.unlink(dbfile)
    print("  OK deleting a nonexistent id returns 404")


def test_delete_refuses_statement_sourced_transaction():
    main, client, dbfile = _fresh_app()
    import db

    conn = db.get_conn()
    # Look up the test user created by _fresh_app's signup call
    test_user = conn.execute("SELECT id FROM users WHERE email='test@example.com'").fetchone()
    uid = test_user["id"]
    conn.execute(
        "INSERT INTO accounts (user_id, bank_name, account_last4) VALUES (?, 'Test Bank', '9999')",
        (uid,),
    )
    acc_id = conn.execute(
        "SELECT id FROM accounts WHERE bank_name='Test Bank' AND user_id=?", (uid,)
    ).fetchone()["id"]
    conn.execute(
        """
        INSERT INTO transactions (user_id, account_id, txn_date, amount, direction, merchant_raw, merchant_clean, source, category)
        VALUES (?, ?, '2026-08-01', 500, 'debit', 'Real Merchant', 'Real Merchant', 'bank_pdf', 'Shopping')
    """,
        (uid, acc_id),
    )
    conn.commit()
    txn_id = conn.execute("SELECT id FROM transactions WHERE merchant_raw='Real Merchant'").fetchone()["id"]
    conn.close()

    r = client.delete(f"/api/transactions/{txn_id}")
    assert r.status_code == 403

    # Confirm it's genuinely untouched, not just an error with a side effect.
    txns = client.get("/api/transactions").json()
    assert txns["total"] == 1
    os.unlink(dbfile)
    print("  OK statement-sourced transactions cannot be deleted via this endpoint")


def test_delete_requires_auth():
    main, client, dbfile = _fresh_app()
    created = client.post(
        "/api/transactions/manual",
        json={
            "date": "2026-08-20",
            "amount": 50,
            "merchant": "Test",
        },
    ).json()
    client.cookies.clear()
    r = client.delete(f"/api/transactions/{created['id']}")
    assert r.status_code == 401
    os.unlink(dbfile)
    print("  OK delete endpoint requires a session")


if __name__ == "__main__":
    tests = [
        test_add_cash_expense_auto_categorizes_via_rules,
        test_add_cash_expense_falls_back_to_cash_category,
        test_explicit_category_overrides_rules,
        test_credit_direction_does_not_default_to_cash,
        test_rejects_missing_amount,
        test_rejects_negative_or_zero_amount,
        test_rejects_malformed_date,
        test_rejects_missing_merchant,
        test_rejects_invalid_direction,
        test_requires_auth,
        test_cash_account_created_once_and_reused,
        test_manual_entries_appear_in_transactions_and_summary,
        test_delete_manual_entry_succeeds,
        test_delete_nonexistent_returns_404,
        test_delete_refuses_statement_sourced_transaction,
        test_delete_requires_auth,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  FAIL {t.__name__}: {e!r}")
    print(f"\n{passed}/{len(tests)} tests passed")
