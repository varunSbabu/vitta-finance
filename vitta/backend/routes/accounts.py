"""Connected accounts (bank/UPI accounts detected from statement imports,
plus the virtual Cash account — see routes/transactions.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from auth import require_auth
from db import dict_from_row, get_conn

router = APIRouter(tags=["accounts"])


@router.get("/api/accounts")
def api_accounts(user: dict = Depends(require_auth)):
    user_id = user["id"]
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT a.*,
          (SELECT COUNT(*) FROM transactions WHERE account_id = a.id AND user_id = ?) AS txn_count,
          (SELECT MAX(txn_date) FROM transactions WHERE account_id = a.id AND user_id = ?) AS last_txn
        FROM accounts a
        WHERE a.user_id = ?
        ORDER BY txn_count DESC
        """,
        (user_id, user_id, user_id),
    ).fetchall()
    conn.close()
    return [dict_from_row(r) for r in rows]


@router.delete("/api/accounts/{account_id}")
def api_account_delete(account_id: int, user: dict = Depends(require_auth)):
    """Delete an account and all its transactions. Both the account row
    and its transactions are scoped by user_id so a caller can't delete
    another user's data even if they guess an account id."""
    user_id = user["id"]
    conn = get_conn()
    owned = conn.execute(
        "SELECT id FROM accounts WHERE id = ? AND user_id = ?", (account_id, user_id)
    ).fetchone()
    if not owned:
        conn.close()
        raise HTTPException(404, "Account not found.")

    txn_count = conn.execute(
        "SELECT COUNT(*) AS c FROM transactions WHERE account_id = ? AND user_id = ?",
        (account_id, user_id),
    ).fetchone()["c"]

    conn.execute("DELETE FROM transactions WHERE account_id = ? AND user_id = ?", (account_id, user_id))
    conn.execute("DELETE FROM accounts WHERE id = ? AND user_id = ?", (account_id, user_id))
    conn.commit()
    conn.close()
    return {"ok": True, "deleted_transactions": txn_count}
