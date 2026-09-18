"""Debts — track who owes you and who you owe.

Endpoints:
  GET    /api/debts           — list all debts with totals
  POST   /api/debts           — create a debt (optionally linked to a transaction)
  POST   /api/debts/{id}/settle — settle fully or partially
  DELETE /api/debts/{id}      — remove a debt
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException

from auth import require_auth
from db import dict_from_row, get_conn

router = APIRouter(tags=["debts"])


@router.get("/api/debts")
def api_debts_list(user: dict = Depends(require_auth)):
    uid = user["id"]
    conn = get_conn()

    rows = conn.execute(
        "SELECT * FROM debts WHERE user_id = ? ORDER BY status ASC, created_at DESC",
        (uid,),
    ).fetchall()
    conn.close()

    debts = [dict_from_row(r) for r in rows]

    pending = [d for d in debts if d["status"] != "settled"]
    they_owe = sum(d["amount"] - d["settled_amount"] for d in pending if d["direction"] == "they_owe")
    i_owe = sum(d["amount"] - d["settled_amount"] for d in pending if d["direction"] == "i_owe")

    return {
        "debts": debts,
        "summary": {
            "they_owe_total": round(they_owe, 2),
            "i_owe_total": round(i_owe, 2),
            "net": round(they_owe - i_owe, 2),
            "pending_count": len(pending),
        },
    }


@router.post("/api/debts")
def api_debt_create(payload: dict = Body(...), user: dict = Depends(require_auth)):
    uid = user["id"]
    contact_name = (payload.get("contact_name") or "").strip()
    amount = payload.get("amount", 0)
    direction = payload.get("direction", "")
    reason = (payload.get("reason") or "").strip()
    txn_id = payload.get("txn_id")

    if not contact_name:
        raise HTTPException(400, "Contact name is required.")
    if amount <= 0:
        raise HTTPException(400, "Amount must be positive.")
    if direction not in ("they_owe", "i_owe"):
        raise HTTPException(400, "Direction must be 'they_owe' or 'i_owe'.")

    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO debts (user_id, contact_name, amount, direction, reason, txn_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (uid, contact_name, amount, direction, reason, txn_id),
    )
    conn.commit()
    debt_id = cur.lastrowid
    conn.close()
    return {"ok": True, "id": debt_id}


@router.post("/api/debts/{debt_id}/settle")
def api_debt_settle(debt_id: int, payload: dict = Body(...), user: dict = Depends(require_auth)):
    uid = user["id"]
    conn = get_conn()

    row = conn.execute("SELECT * FROM debts WHERE id = ? AND user_id = ?", (debt_id, uid)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Debt not found.")

    debt = dict_from_row(row)
    settle_amount = payload.get("amount", debt["amount"] - debt["settled_amount"])
    new_settled = debt["settled_amount"] + settle_amount
    remaining = debt["amount"] - new_settled

    if remaining <= 0.01:
        status = "settled"
        settled_at = datetime.now().isoformat()
    else:
        status = "partial"
        settled_at = None

    conn.execute(
        "UPDATE debts SET settled_amount = ?, status = ?, settled_at = ? WHERE id = ? AND user_id = ?",
        (round(new_settled, 2), status, settled_at, debt_id, uid),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "status": status, "remaining": round(max(0, remaining), 2)}


@router.delete("/api/debts/{debt_id}")
def api_debt_delete(debt_id: int, user: dict = Depends(require_auth)):
    conn = get_conn()
    conn.execute("DELETE FROM debts WHERE id = ? AND user_id = ?", (debt_id, user["id"]))
    conn.commit()
    conn.close()
    return {"ok": True}
