"""Listing transactions, and manually-logged (cash) transactions.

Cash spending has no statement trail — an ATM withdrawal shows up in a
bank statement as a single lump debit (already categorized 'Cash' by
categorization.py), but what that cash actually got spent ON is
invisible to any parser. /api/transactions/manual lets the user log it
directly, into a dedicated virtual "Cash" account so it flows through the
same categorization/summary/insights pipeline as everything else.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from auth import require_auth
from categorization import rule_categorize
from db import dict_from_row, get_conn

router = APIRouter(tags=["transactions"])

CASH_ACCOUNT_BANK_NAME = "Cash"
CASH_ACCOUNT_LAST4 = ""


@router.get("/api/transactions")
def api_transactions(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = 0,
    category: Optional[str] = None,
    account_id: Optional[int] = None,
    direction: Optional[str] = None,
    q: Optional[str] = None,
    _user: dict = Depends(require_auth),
):
    where: list = []
    params: list = []
    if category:
        where.append("category = ?")
        params.append(category)
    if account_id:
        where.append("account_id = ?")
        params.append(account_id)
    if direction:
        where.append("direction = ?")
        params.append(direction)
    if q:
        where.append("(merchant_clean LIKE ? OR merchant_raw LIKE ? OR remark LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

    sql = "SELECT t.*, a.bank_name, a.account_last4 FROM transactions t LEFT JOIN accounts a ON t.account_id = a.id"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY txn_date DESC, id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    conn = get_conn()
    rows = conn.execute(sql, params).fetchall()
    total = conn.execute("SELECT COUNT(*) AS c FROM transactions").fetchone()["c"]
    conn.close()
    return {"total": total, "count": len(rows), "transactions": [dict_from_row(r) for r in rows]}


def _parse_manual_date(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _get_or_create_cash_account(conn) -> int:
    conn.execute(
        "INSERT OR IGNORE INTO accounts (bank_name, account_last4, account_type) VALUES (?, ?, 'cash')",
        (CASH_ACCOUNT_BANK_NAME, CASH_ACCOUNT_LAST4),
    )
    row = conn.execute(
        "SELECT id FROM accounts WHERE bank_name = ? AND account_last4 = ?",
        (CASH_ACCOUNT_BANK_NAME, CASH_ACCOUNT_LAST4),
    ).fetchone()
    return row["id"]


@router.post("/api/transactions/manual")
def api_add_manual_transaction(payload: dict = Body(...), _user: dict = Depends(require_auth)):
    """Log a transaction with no statement trail — cash spend, a cash gift
    received, etc. Always attached to the virtual Cash account (created on
    first use). Runs merchant text through the same Tier 1 rules as parsed
    transactions unless the caller supplies a category directly."""
    date = (payload.get("date") or "").strip()
    merchant = (payload.get("merchant") or "").strip()
    direction = (payload.get("direction") or "debit").strip()
    remark = (payload.get("remark") or "").strip()
    category = (payload.get("category") or "").strip()

    if not date or not merchant:
        raise HTTPException(400, "date and merchant are required")
    if direction not in ("debit", "credit"):
        raise HTTPException(400, "direction must be 'debit' or 'credit'")
    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        raise HTTPException(400, "amount must be a number")
    if amount <= 0:
        raise HTTPException(400, "amount must be positive")
    if not _parse_manual_date(date):
        raise HTTPException(400, "date must be YYYY-MM-DD")

    if not category:
        category = rule_categorize(merchant, remark)
        if category == "Uncategorized" and direction == "debit":
            # No rule matched a hand-typed description — cash purchases
            # skew toward everyday small spend, a safer default than
            # leaving the whole entry uncategorized when the user is
            # clearly telling us what it was for.
            category = "Cash"

    conn = get_conn()
    account_id = _get_or_create_cash_account(conn)
    cur = conn.execute(
        """
        INSERT INTO transactions
          (account_id, txn_date, amount, direction, merchant_raw, merchant_clean,
           remark, source, category)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'manual_cash', ?)
        """,
        (account_id, date, amount, direction, merchant, merchant, remark, category),
    )
    conn.commit()
    txn_id = cur.lastrowid
    conn.close()
    return {"id": txn_id, "account_id": account_id, "category": category}


@router.delete("/api/transactions/{txn_id}")
def api_delete_manual_transaction(txn_id: int, _user: dict = Depends(require_auth)):
    """Undo a manual entry. Scoped to source='manual_cash' only — this
    endpoint is for fixing a typo'd cash entry, not a general delete-any-
    transaction API for statement-derived history."""
    conn = get_conn()
    row = conn.execute("SELECT source FROM transactions WHERE id = ?", (txn_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Transaction not found")
    if row["source"] != "manual_cash":
        conn.close()
        raise HTTPException(403, "Only manually-entered transactions can be deleted here.")
    conn.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))
    conn.commit()
    conn.close()
    return {"ok": True}
