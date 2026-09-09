"""Connected accounts (bank/UPI accounts detected from statement imports,
plus the virtual Cash account — see routes/transactions.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

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
