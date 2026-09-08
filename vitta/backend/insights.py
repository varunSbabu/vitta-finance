"""Insights — real facts computed from the database, optionally phrased by
the LLM.

Every number in every insight is computed by SQL here (SUM/COUNT/GROUP BY),
never by the model. The LLM's only job, if a key is configured, is to
rewrite the plain templated sentence into something more natural using the
exact figures it's handed — the same "LLM never does arithmetic" rule the
categorization tiers follow. With no key, the templated sentences ship
as-is, so insights work fully offline; they just read a little more robotic.

Each insight is a card: {id, icon, title, body, ...raw fields}. The raw
fields are kept on the card so the frontend (or a future test) can assert
against the computed numbers directly rather than parsing prose.
"""

from __future__ import annotations

import json
from datetime import date

from db import get_conn
from llm import chat, is_available


def _resolve_month(conn, month: str | None) -> str:
    """Pick which month to report on. An explicit month wins. Otherwise use
    the latest month that actually has transactions — a user opening Insights
    right after uploading a statement wants to see that statement's month,
    not an empty current calendar month. Falls back to the current month
    only when there's no data at all."""
    if month:
        return month
    row = conn.execute(
        "SELECT MAX(substr(txn_date,1,7)) FROM transactions WHERE is_self_transfer=0"
    ).fetchone()
    if row and row[0]:
        return row[0]
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


def _prev_month(this: str) -> str:
    y, m = int(this[:4]), int(this[5:7])
    pm, py = (m - 1, y) if m > 1 else (12, y - 1)
    return f"{py:04d}-{pm:02d}"


def latest_month_with_data() -> str | None:
    """The most recent 'YYYY-MM' that has non-transfer transactions, or None
    if there are none. The route uses this to label which month it reported."""
    conn = get_conn()
    row = conn.execute(
        "SELECT MAX(substr(txn_date,1,7)) FROM transactions WHERE is_self_transfer=0"
    ).fetchone()
    conn.close()
    return row[0] if row and row[0] else None


def compute_insights(month: str | None = None) -> list[dict]:
    """Compute the insight facts. Pure SQL + Python; no LLM. Returns cards
    with a default templated `body` that narrate_insights() may later
    rewrite."""
    conn = get_conn()
    this_month = _resolve_month(conn, month)
    prev_month = _prev_month(this_month)

    def scalar(sql, params=()):
        row = conn.execute(sql, params).fetchone()
        return row[0] if row and row[0] is not None else 0

    # Real (non-transfer) spend this month and last month.
    spent_this = scalar(
        "SELECT SUM(amount) FROM transactions WHERE is_self_transfer=0 AND direction='debit' AND substr(txn_date,1,7)=?",
        (this_month,),
    )
    spent_prev = scalar(
        "SELECT SUM(amount) FROM transactions WHERE is_self_transfer=0 AND direction='debit' AND substr(txn_date,1,7)=?",
        (prev_month,),
    )
    received_this = scalar(
        "SELECT SUM(amount) FROM transactions WHERE is_self_transfer=0 AND direction='credit' AND substr(txn_date,1,7)=?",
        (this_month,),
    )

    cards: list[dict] = []

    # 1. Top spending category this month.
    top_cat = conn.execute(
        """
        SELECT category, SUM(amount) AS total, COUNT(*) AS n
        FROM transactions
        WHERE is_self_transfer=0 AND direction='debit' AND substr(txn_date,1,7)=?
          AND category != 'Uncategorized'
        GROUP BY category ORDER BY total DESC LIMIT 1
        """,
        (this_month,),
    ).fetchone()
    if top_cat and spent_this:
        share = round(top_cat["total"] / spent_this * 100)
        cards.append(
            {
                "id": "top_category",
                "icon": "trophy",
                "title": "Top spending category",
                "category": top_cat["category"],
                "amount": round(top_cat["total"], 2),
                "share_pct": share,
                "count": top_cat["n"],
                "body": f"{top_cat['category']} was your biggest category this month at "
                f"₹{top_cat['total']:,.0f} across {top_cat['n']} transactions "
                f"({share}% of your spending).",
            }
        )

    # 2. Month-over-month spend change.
    if spent_prev:
        change = (spent_this - spent_prev) / spent_prev * 100
        direction = "more" if change >= 0 else "less"
        cards.append(
            {
                "id": "mom_change",
                "icon": "trend",
                "title": "Vs last month",
                "spent_this": round(spent_this, 2),
                "spent_prev": round(spent_prev, 2),
                "change_pct": round(change, 1),
                "body": f"You've spent ₹{spent_this:,.0f} this month — "
                f"{abs(change):.0f}% {direction} than last month's ₹{spent_prev:,.0f}.",
            }
        )

    # 3. Net position this month.
    net = received_this - spent_this
    if spent_this or received_this:
        if net >= 0:
            body = f"You're net positive this month: ₹{received_this:,.0f} in, ₹{spent_this:,.0f} out — a ₹{net:,.0f} surplus."
        else:
            body = f"You're spending more than you received this month: ₹{spent_this:,.0f} out vs ₹{received_this:,.0f} in, a ₹{abs(net):,.0f} gap."
        cards.append(
            {
                "id": "net_position",
                "icon": "balance",
                "title": "Net this month",
                "received": round(received_this, 2),
                "spent": round(spent_this, 2),
                "net": round(net, 2),
                "body": body,
            }
        )

    # 4. Biggest single expense this month.
    biggest = conn.execute(
        """
        SELECT merchant_clean, amount, txn_date, category
        FROM transactions
        WHERE is_self_transfer=0 AND direction='debit' AND substr(txn_date,1,7)=?
        ORDER BY amount DESC LIMIT 1
        """,
        (this_month,),
    ).fetchone()
    if biggest:
        cards.append(
            {
                "id": "biggest_expense",
                "icon": "alert",
                "title": "Biggest expense",
                "merchant": biggest["merchant_clean"],
                "amount": round(biggest["amount"], 2),
                "category": biggest["category"],
                "date": biggest["txn_date"],
                "body": f"Your largest single expense this month was ₹{biggest['amount']:,.0f} "
                f"to {biggest['merchant_clean']} ({biggest['category']}).",
            }
        )

    # 5. Likely recurring merchants — since is_recurring isn't populated yet,
    #    infer it: a merchant paid (as a debit) in 2+ distinct months is a
    #    subscription/recurring candidate. This is all-time, not this-month.
    recurring = conn.execute(
        """
        SELECT merchant_clean,
               COUNT(DISTINCT substr(txn_date,1,7)) AS months,
               ROUND(AVG(amount), 0) AS avg_amount
        FROM transactions
        WHERE is_self_transfer=0 AND direction='debit' AND merchant_clean IS NOT NULL
        GROUP BY merchant_clean
        HAVING months >= 2
        ORDER BY months DESC, avg_amount DESC
        LIMIT 5
        """
    ).fetchall()
    if recurring:
        names = ", ".join(r["merchant_clean"] for r in recurring[:3])
        cards.append(
            {
                "id": "recurring",
                "icon": "repeat",
                "title": "Looks recurring",
                "merchants": [
                    {"merchant": r["merchant_clean"], "months": r["months"], "avg_amount": r["avg_amount"]}
                    for r in recurring
                ],
                "body": f"These look like recurring payments: {names}. "
                f"Worth checking they're all subscriptions you still want.",
            }
        )

    # 6. Uncategorized nudge.
    uncat = conn.execute(
        """
        SELECT COUNT(*) AS n, SUM(amount) AS total
        FROM transactions
        WHERE is_self_transfer=0 AND direction='debit' AND category='Uncategorized'
          AND substr(txn_date,1,7)=?
        """,
        (this_month,),
    ).fetchone()
    if uncat and uncat["n"]:
        cards.append(
            {
                "id": "uncategorized",
                "icon": "tag",
                "title": "Needs a label",
                "count": uncat["n"],
                "amount": round(uncat["total"] or 0, 2),
                "body": f"{uncat['n']} transactions worth ₹{(uncat['total'] or 0):,.0f} are still "
                f"uncategorized. Tag them once and Vitta remembers for next time.",
            }
        )

    conn.close()
    return cards


def narrate_insights(cards: list[dict]) -> list[dict]:
    """If an LLM key is configured, rewrite each card's `body` into a more
    natural sentence — in ONE batched call — using the exact numbers already
    computed. The model may not change any figure; if its output is missing
    or malformed for a card, that card keeps its templated body."""
    if not cards or not is_available():
        return cards

    payload = [
        {
            "id": c["id"],
            "title": c["title"],
            "facts": {k: v for k, v in c.items() if k not in ("icon", "title", "body")},
        }
        for c in cards
    ]

    content = chat(
        [
            {
                "role": "system",
                "content": (
                    "You rewrite personal-finance insight blurbs to sound natural and "
                    "encouraging, for an Indian user. You are given each insight's exact "
                    "computed facts. Use ONLY those numbers — never invent, round "
                    "differently, or recompute. Keep each to one or two short sentences. "
                    "Format rupee amounts like ₹1,234. Respond with ONLY a JSON array of "
                    '{"id": "...", "body": "..."} objects, one per insight, no markdown.'
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
        ],
        temperature=0.4,
        max_tokens=1200,
    )
    if not content:
        return cards

    import re

    m = re.search(r"\[.*\]", content, re.DOTALL)
    if not m:
        return cards
    try:
        rewritten = json.loads(m.group(0))
    except json.JSONDecodeError:
        return cards

    by_id = {r["id"]: r["body"] for r in rewritten if isinstance(r, dict) and r.get("id") and r.get("body")}
    for c in cards:
        if c["id"] in by_id and isinstance(by_id[c["id"]], str):
            c["body"] = by_id[c["id"]].strip()
    return cards
