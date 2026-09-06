"""Merchant dictionary — aggregated spend per merchant, and the Tier 2
"tag once, remember forever" endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from auth import require_auth
from db import dict_from_row, get_conn

router = APIRouter(tags=["merchants"])


@router.get("/api/merchants")
def api_merchants(_user: dict = Depends(require_auth)):
    conn = get_conn()
    rows = conn.execute("""
        SELECT
          t.merchant_clean          AS name,
          t.merchant_raw            AS raw,
          COUNT(*)                  AS n,
          SUM(t.amount)             AS total,
          MAX(t.category)           AS category,
          MAX(t.txn_date)           AS last_seen,
          MAX(CASE WHEN d.id IS NOT NULL THEN 1 ELSE 0 END) AS is_tagged
        FROM transactions t
        LEFT JOIN merchant_dictionary d ON LOWER(d.merchant_key) = LOWER(t.merchant_raw)
        WHERE t.direction = 'debit'
        GROUP BY t.merchant_clean
        ORDER BY total DESC
    """).fetchall()
    conn.close()
    return [dict_from_row(r) for r in rows]


@router.post("/api/merchants/tag")
def api_merchant_tag(payload: dict = Body(...), _user: dict = Depends(require_auth)):
    merchant_raw = payload.get("merchant_raw", "").strip()
    category = payload.get("category", "").strip()
    if not merchant_raw or not category:
        raise HTTPException(400, "merchant_raw and category required")

    conn = get_conn()
    conn.execute(
        """
        INSERT INTO merchant_dictionary (merchant_key, category, is_user_tagged, applied_count)
        VALUES (?, ?, 1, 0)
        ON CONFLICT(merchant_key) DO UPDATE SET
          category = excluded.category,
          is_user_tagged = 1
    """,
        (merchant_raw.lower(), category),
    )

    cur = conn.execute(
        "UPDATE transactions SET category = ? WHERE LOWER(merchant_raw) = LOWER(?)",
        (category, merchant_raw),
    )
    updated = cur.rowcount

    conn.execute(
        "UPDATE merchant_dictionary SET applied_count = ? WHERE merchant_key = ?",
        (updated, merchant_raw.lower()),
    )
    conn.commit()
    conn.close()
    return {"merchant_raw": merchant_raw, "category": category, "applied_to": updated}
