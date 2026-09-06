"""Self-transfer detection.

Since every account in this DB belongs to one person (personal-use app),
a debit from account A and a credit into account B of the same amount
within a short window is almost certainly the user moving their own
money — not real spending or income. Flagging these keeps dashboard
totals honest (a ₹20,000 transfer to your own savings account shouldn't
show up as ₹20,000 of "spend").

Matching heuristic:
  - opposite directions (one debit, one credit)
  - different accounts
  - amounts equal (within a paise-rounding epsilon)
  - dates within WINDOW_DAYS of each other
  - greedy nearest-date pairing, each transaction used at most once
"""

from __future__ import annotations

from datetime import date

from db import get_conn

WINDOW_DAYS = 2
AMOUNT_EPSILON = 0.01


def detect_self_transfers() -> dict:
    """Scan all not-yet-flagged transactions and mark matching debit/credit
    pairs across different accounts as self-transfers. Idempotent — running
    it again only looks at transactions still marked is_self_transfer = 0."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, account_id, txn_date, amount, direction
        FROM transactions
        WHERE is_self_transfer = 0
        ORDER BY txn_date
    """).fetchall()

    debits = [dict(r) for r in rows if r["direction"] == "debit"]
    credits = [dict(r) for r in rows if r["direction"] == "credit"]

    matched_credit_ids: set[int] = set()
    pairs: list[tuple[int, int]] = []

    for d in debits:
        d_date = date.fromisoformat(d["txn_date"])
        best = None
        best_diff = None

        for c in credits:
            if c["id"] in matched_credit_ids:
                continue
            if c["account_id"] == d["account_id"]:
                continue
            if abs(c["amount"] - d["amount"]) > AMOUNT_EPSILON:
                continue

            c_date = date.fromisoformat(c["txn_date"])
            diff = abs((c_date - d_date).days)
            if diff > WINDOW_DAYS:
                continue

            if best is None or diff < best_diff:
                best = c
                best_diff = diff

        if best:
            matched_credit_ids.add(best["id"])
            pairs.append((d["id"], best["id"]))

    if pairs:
        ids = [i for pair in pairs for i in pair]
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE transactions SET is_self_transfer = 1 WHERE id IN ({placeholders})",
            ids,
        )
        conn.commit()

    conn.close()
    return {
        "pairs_found": len(pairs),
        "transactions_marked": len(pairs) * 2,
        "pairs": pairs,
    }
