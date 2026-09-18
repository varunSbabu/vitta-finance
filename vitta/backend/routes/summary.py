"""Dashboard stat tiles + category/merchant breakdown."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query

from auth import require_auth
from db import dict_from_row, get_conn

router = APIRouter(tags=["summary"])


@router.get("/api/summary")
def api_summary(
    month: Optional[str] = Query(None, description="YYYY-MM"), user: dict = Depends(require_auth)
):
    user_id = user["id"]
    conn = get_conn()
    where = "WHERE user_id = ? AND is_self_transfer = 0"
    params: list = [user_id]
    if month:
        where += " AND txn_date LIKE ?"
        params.append(f"{month}%")

    row = conn.execute(
        f"""
        SELECT
          SUM(CASE WHEN direction='debit'  THEN amount ELSE 0 END) AS total_spent,
          SUM(CASE WHEN direction='credit' THEN amount ELSE 0 END) AS total_received,
          SUM(CASE WHEN direction='debit'  THEN 1 ELSE 0 END)      AS n_debits,
          SUM(CASE WHEN direction='credit' THEN 1 ELSE 0 END)      AS n_credits,
          SUM(CASE WHEN category != 'Uncategorized' AND direction='debit' THEN 1 ELSE 0 END) AS n_auto,
          SUM(CASE WHEN direction='debit'  THEN 1 ELSE 0 END)      AS n_total_debits
        FROM transactions {where}
    """,
        params,
    ).fetchone()

    cats = conn.execute(
        f"""
        SELECT category, SUM(amount) AS total, COUNT(*) AS n
        FROM transactions
        {where} AND direction = 'debit'
        GROUP BY category ORDER BY total DESC
    """,
        params,
    ).fetchall()

    top_merch = conn.execute(
        f"""
        SELECT merchant_clean, category, SUM(amount) AS total, COUNT(*) AS n
        FROM transactions
        {where} AND direction = 'debit'
        GROUP BY merchant_clean ORDER BY total DESC LIMIT 10
    """,
        params,
    ).fetchall()

    conn.close()

    auto_pct = round((row["n_auto"] or 0) / max(1, row["n_total_debits"] or 1) * 100)
    return {
        "month": month,
        "spent": row["total_spent"] or 0,
        "received": row["total_received"] or 0,
        "auto_categorized": auto_pct,
        "n_transactions": (row["n_debits"] or 0) + (row["n_credits"] or 0),
        "categories": [dict_from_row(r) for r in cats],
        "top_merchants": [dict_from_row(r) for r in top_merch],
    }


@router.get("/api/spending-trend")
def api_spending_trend(
    weeks: int = Query(24, ge=4, le=52),
    user: dict = Depends(require_auth),
):
    """Weekly spending totals for the trend chart."""
    user_id = user["id"]
    today = date.today()
    # Start from the Monday `weeks` weeks ago
    start_monday = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)

    conn = get_conn()
    rows = conn.execute(
        """
        SELECT
          date(txn_date, 'weekday 0', '-6 days') AS week_start,
          ROUND(SUM(CASE WHEN direction='debit' THEN amount ELSE 0 END), 0) AS spent,
          ROUND(SUM(CASE WHEN direction='credit' THEN amount ELSE 0 END), 0) AS received,
          COUNT(*) AS n
        FROM transactions
        WHERE user_id = ? AND is_self_transfer = 0
          AND txn_date >= ?
        GROUP BY week_start
        ORDER BY week_start
        """,
        (user_id, start_monday.isoformat()),
    ).fetchall()
    conn.close()

    # Build a dense array with zeros for weeks with no transactions
    week_map = {r["week_start"]: dict_from_row(r) for r in rows}
    result = []
    cursor = start_monday
    while cursor <= today:
        key = cursor.isoformat()
        if key in week_map:
            result.append(week_map[key])
        else:
            result.append({"week_start": key, "spent": 0, "received": 0, "n": 0})
        cursor += timedelta(weeks=1)

    return {"weeks": result}
