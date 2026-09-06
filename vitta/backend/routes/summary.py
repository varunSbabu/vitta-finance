"""Dashboard stat tiles + category/merchant breakdown."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from auth import require_auth
from db import dict_from_row, get_conn

router = APIRouter(tags=["summary"])


@router.get("/api/summary")
def api_summary(
    month: Optional[str] = Query(None, description="YYYY-MM"), _user: dict = Depends(require_auth)
):
    conn = get_conn()
    where = "WHERE is_self_transfer = 0"
    params: list = []
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
