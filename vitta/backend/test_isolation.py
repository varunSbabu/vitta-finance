"""Two-user tenant isolation tests — the Phase 1 acceptance gate.

Seeds two users (Alice and Bob), gives each their own data, and verifies
that every data-returning endpoint returns strictly disjoint results.
If any endpoint ever leaks one user's data to another, this suite catches it.

Uses FastAPI TestClient with password-auth sessions, one per user.
"""

import importlib
import os
import pathlib
import tempfile

import pytest


def _make_app():
    """Stand up a fresh app + DB with two authenticated sessions."""
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()

    import db

    db.DB_PATH = pathlib.Path(tmp_db.name)
    db.init_db()

    os.environ["SESSION_SECRET_KEY"] = "isolation-test-key"  # pragma: allowlist secret
    os.environ["ALLOWED_EMAIL"] = ""

    import auth

    importlib.reload(auth)
    import main

    importlib.reload(main)

    from fastapi.testclient import TestClient

    alice = TestClient(main.app)
    alice.post(
        "/api/auth/signup",
        json={
            "email": "alice@test.com",
            "password": "password123",  # pragma: allowlist secret
            "name": "Alice",
        },
    )

    bob = TestClient(main.app)
    bob.post(
        "/api/auth/signup",
        json={
            "email": "bob@test.com",
            "password": "password456",  # pragma: allowlist secret
            "name": "Bob",
        },
    )

    return alice, bob, tmp_db.name, db


def _seed_transactions(client, merchant, category, date="2026-08-15"):
    """Add a manual cash transaction for this user."""
    r = client.post(
        "/api/transactions/manual",
        json={
            "date": date,
            "amount": 500,
            "merchant": merchant,
            "direction": "debit",
            "category": category,
        },
    )
    assert r.status_code == 200, f"seed failed: {r.text}"
    return r.json()


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def env():
    alice, bob, dbfile, db_mod = _make_app()
    yield alice, bob, db_mod
    os.unlink(dbfile)


# ── Tests ────────────────────────────────────────────────────────────


def test_transactions_isolated(env):
    alice, bob, _ = env
    _seed_transactions(alice, "Alice Shop", "Shopping")
    _seed_transactions(bob, "Bob Cafe", "Food")

    a_txns = alice.get("/api/transactions").json()
    b_txns = bob.get("/api/transactions").json()

    assert a_txns["total"] == 1
    assert b_txns["total"] == 1
    assert a_txns["transactions"][0]["merchant_clean"] == "Alice Shop"
    assert b_txns["transactions"][0]["merchant_clean"] == "Bob Cafe"


def test_accounts_isolated(env):
    alice, bob, _ = env
    _seed_transactions(alice, "Alice Shop", "Shopping")
    _seed_transactions(bob, "Bob Cafe", "Food")

    a_accs = alice.get("/api/accounts").json()
    b_accs = bob.get("/api/accounts").json()

    assert len(a_accs) == 1
    assert len(b_accs) == 1
    a_ids = {a["id"] for a in a_accs}
    b_ids = {b["id"] for b in b_accs}
    assert a_ids.isdisjoint(b_ids)


def test_summary_isolated(env):
    alice, bob, _ = env
    _seed_transactions(alice, "Alice Shop", "Shopping")
    _seed_transactions(bob, "Bob Cafe", "Food")
    _seed_transactions(bob, "Bob Cafe 2", "Food")

    a_sum = alice.get("/api/summary?month=2026-08").json()
    b_sum = bob.get("/api/summary?month=2026-08").json()

    assert a_sum["n_transactions"] == 1
    assert b_sum["n_transactions"] == 2
    assert a_sum["spent"] == 500
    assert b_sum["spent"] == 1000


def test_merchants_isolated(env):
    alice, bob, _ = env
    _seed_transactions(alice, "Alice Shop", "Shopping")
    _seed_transactions(bob, "Bob Cafe", "Food")

    a_merch = alice.get("/api/merchants").json()
    b_merch = bob.get("/api/merchants").json()

    a_names = {m["name"] for m in a_merch}
    b_names = {m["name"] for m in b_merch}

    assert "Alice Shop" in a_names
    assert "Bob Cafe" not in a_names
    assert "Bob Cafe" in b_names
    assert "Alice Shop" not in b_names


def test_merchant_tag_isolated(env):
    alice, bob, _ = env
    _seed_transactions(alice, "shared merchant", "Shopping")
    _seed_transactions(bob, "shared merchant", "Shopping")

    alice.post("/api/merchants/tag", json={"merchant_raw": "shared merchant", "category": "Entertainment"})

    a_txns = alice.get("/api/transactions").json()
    b_txns = bob.get("/api/transactions").json()

    assert a_txns["transactions"][0]["category"] == "Entertainment"
    assert b_txns["transactions"][0]["category"] == "Shopping"


def test_contacts_isolated(env):
    alice, bob, _ = env

    import io

    csv_alice = b"Name,Phone 1 - Value\nAlice Friend,9876543210\n"
    csv_bob = b"Name,Phone 1 - Value\nBob Friend,9123456789\n"

    alice.post("/api/contacts/import", files={"file": ("contacts.csv", io.BytesIO(csv_alice), "text/csv")})
    bob.post("/api/contacts/import", files={"file": ("contacts.csv", io.BytesIO(csv_bob), "text/csv")})

    a_contacts = alice.get("/api/contacts").json()
    b_contacts = bob.get("/api/contacts").json()

    assert len(a_contacts) == 1
    assert a_contacts[0]["display_name"] == "Alice Friend"
    assert len(b_contacts) == 1
    assert b_contacts[0]["display_name"] == "Bob Friend"


def test_insights_isolated(env):
    alice, bob, _ = env
    _seed_transactions(alice, "Alice Expense", "Shopping")
    _seed_transactions(bob, "Bob Expense", "Food")
    _seed_transactions(bob, "Bob Expense 2", "Food")

    a_insights = alice.get("/api/insights?month=2026-08").json()
    b_insights = bob.get("/api/insights?month=2026-08").json()

    def _card(cards, cid):
        return next((c for c in cards if c["id"] == cid), None)

    a_top = _card(a_insights["insights"], "top_category")
    b_top = _card(b_insights["insights"], "top_category")

    if a_top:
        assert a_top["category"] == "Shopping"
        assert a_top["amount"] == 500
    if b_top:
        assert b_top["category"] == "Food"
        assert b_top["amount"] == 1000


def test_delete_cannot_reach_other_users_transaction(env):
    alice, bob, _ = env
    a_txn = _seed_transactions(alice, "Alice Only", "Shopping")

    r = bob.delete(f"/api/transactions/{a_txn['id']}")
    assert r.status_code == 404

    a_txns = alice.get("/api/transactions").json()
    assert a_txns["total"] == 1


def test_reset_only_affects_own_data(env):
    alice, bob, _ = env
    _seed_transactions(alice, "Alice Data", "Shopping")
    _seed_transactions(bob, "Bob Data", "Food")

    alice.post("/api/reset")

    a_txns = alice.get("/api/transactions").json()
    b_txns = bob.get("/api/transactions").json()

    assert a_txns["total"] == 0
    assert b_txns["total"] == 1


def test_self_transfer_detection_isolated(env):
    alice, bob, db_mod = env

    alice_me = alice.get("/api/auth/me").json()
    bob_me = bob.get("/api/auth/me").json()

    conn = db_mod.get_conn()

    # Alice: two accounts, matching debit/credit
    conn.execute(
        "INSERT INTO accounts (user_id, bank_name, account_last4) VALUES (?, 'Bank A', '1111')",
        (alice_me["id"],),
    )
    conn.execute(
        "INSERT INTO accounts (user_id, bank_name, account_last4) VALUES (?, 'Bank B', '2222')",
        (alice_me["id"],),
    )
    a_acc1 = conn.execute(
        "SELECT id FROM accounts WHERE user_id=? AND account_last4='1111'", (alice_me["id"],)
    ).fetchone()["id"]
    a_acc2 = conn.execute(
        "SELECT id FROM accounts WHERE user_id=? AND account_last4='2222'", (alice_me["id"],)
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO transactions (user_id, account_id, txn_date, amount, direction, merchant_raw, source, category) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (alice_me["id"], a_acc1, "2026-08-01", 10000, "debit", "Transfer", "bank_pdf", "Transfers"),
    )
    conn.execute(
        "INSERT INTO transactions (user_id, account_id, txn_date, amount, direction, merchant_raw, source, category) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (alice_me["id"], a_acc2, "2026-08-01", 10000, "credit", "Transfer", "bank_pdf", "Transfers"),
    )

    # Bob: one debit of same amount, different account
    conn.execute(
        "INSERT INTO accounts (user_id, bank_name, account_last4) VALUES (?, 'Bank C', '3333')",
        (bob_me["id"],),
    )
    b_acc = conn.execute(
        "SELECT id FROM accounts WHERE user_id=? AND account_last4='3333'", (bob_me["id"],)
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO transactions (user_id, account_id, txn_date, amount, direction, merchant_raw, source, category) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (bob_me["id"], b_acc, "2026-08-01", 10000, "debit", "Real Expense", "bank_pdf", "Shopping"),
    )
    conn.commit()
    conn.close()

    a_result = alice.post("/api/detect-transfers").json()
    b_result = bob.post("/api/detect-transfers").json()

    assert a_result["pairs_found"] == 1
    assert b_result["pairs_found"] == 0


if __name__ == "__main__":
    tests = [
        test_transactions_isolated,
        test_accounts_isolated,
        test_summary_isolated,
        test_merchants_isolated,
        test_merchant_tag_isolated,
        test_contacts_isolated,
        test_insights_isolated,
        test_delete_cannot_reach_other_users_transaction,
        test_reset_only_affects_own_data,
        test_self_transfer_detection_isolated,
    ]
    passed = 0
    for t in tests:
        alice, bob, dbfile, db_mod = _make_app()
        try:
            t((alice, bob, db_mod))
            passed += 1
            print(f"  OK {t.__name__}")
        except Exception as e:
            print(f"  FAIL {t.__name__}: {e!r}")
        finally:
            os.unlink(dbfile)
    print(f"\n{passed}/{len(tests)} isolation tests passed")
