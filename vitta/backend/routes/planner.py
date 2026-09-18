"""Expense Planner — income, obligations, savings goals, and category budgets.

The planner tracks the full money flow:
  Income → Fixed obligations → Savings goal → Free-to-spend (category budgets)
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException

from auth import require_auth
from db import dict_from_row, get_conn

router = APIRouter(tags=["planner"])


# ── Read the full plan ─────────────────────────────────────────────


@router.get("/api/planner")
def api_planner_get(user: dict = Depends(require_auth)):
    """Return the user's full expense plan + actuals for the current month."""
    user_id = user["id"]
    month = date.today().strftime("%Y-%m")
    conn = get_conn()

    income = [
        dict_from_row(r)
        for r in conn.execute(
            "SELECT * FROM income_sources WHERE user_id = ? AND is_active = 1 ORDER BY amount DESC",
            (user_id,),
        ).fetchall()
    ]

    obligations = [
        dict_from_row(r)
        for r in conn.execute(
            "SELECT * FROM obligations WHERE user_id = ? AND is_active = 1 ORDER BY amount DESC",
            (user_id,),
        ).fetchall()
    ]

    savings = [
        dict_from_row(r)
        for r in conn.execute(
            "SELECT * FROM savings_goals WHERE user_id = ? AND is_active = 1",
            (user_id,),
        ).fetchall()
    ]

    budgets = [
        dict_from_row(r)
        for r in conn.execute(
            "SELECT * FROM budget_plans WHERE user_id = ? AND month = ? ORDER BY limit_amount DESC",
            (user_id, month),
        ).fetchall()
    ]

    # Actuals: spending by category this month (excluding self-transfers)
    actuals = {}
    for r in conn.execute(
        """
        SELECT category, ROUND(SUM(amount), 0) AS spent, COUNT(*) AS n
        FROM transactions
        WHERE user_id = ? AND direction = 'debit' AND is_self_transfer = 0
          AND txn_date LIKE ?
        GROUP BY category
        """,
        (user_id, f"{month}%"),
    ).fetchall():
        actuals[r["category"] or "Uncategorized"] = {
            "spent": r["spent"],
            "n": r["n"],
        }

    total_income = sum(i["amount"] for i in income)
    total_obligations = sum(o["amount"] for o in obligations)
    total_savings = sum(s["target"] for s in savings)
    total_budgeted = sum(b["limit_amount"] for b in budgets)
    free_to_spend = total_income - total_obligations - total_savings
    total_spent = sum(v["spent"] for v in actuals.values())

    conn.close()

    return {
        "month": month,
        "income": income,
        "obligations": obligations,
        "savings": savings,
        "budgets": budgets,
        "actuals": actuals,
        "totals": {
            "income": total_income,
            "obligations": total_obligations,
            "savings_target": total_savings,
            "budgeted": total_budgeted,
            "free_to_spend": free_to_spend,
            "unallocated": max(0, free_to_spend - total_budgeted),
            "total_spent": total_spent,
        },
    }


# ── Income sources ─────────────────────────────────────────────────


@router.post("/api/planner/income")
def api_income_upsert(payload: dict = Body(...), user: dict = Depends(require_auth)):
    conn = get_conn()
    uid = user["id"]
    item_id = payload.get("id")
    name = (payload.get("name") or "").strip()
    amount = payload.get("amount", 0)
    if not name or amount <= 0:
        raise HTTPException(400, "Name and positive amount required.")

    if item_id:
        conn.execute(
            "UPDATE income_sources SET name=?, amount=?, frequency=? WHERE id=? AND user_id=?",
            (name, amount, payload.get("frequency", "monthly"), item_id, uid),
        )
    else:
        conn.execute(
            "INSERT INTO income_sources (user_id, name, amount, frequency) VALUES (?,?,?,?)",
            (uid, name, amount, payload.get("frequency", "monthly")),
        )
    conn.commit()
    conn.close()
    return {"ok": True}


@router.delete("/api/planner/income/{item_id}")
def api_income_delete(item_id: int, user: dict = Depends(require_auth)):
    conn = get_conn()
    conn.execute("DELETE FROM income_sources WHERE id=? AND user_id=?", (item_id, user["id"]))
    conn.commit()
    conn.close()
    return {"ok": True}


# ── Obligations ────────────────────────────────────────────────────


@router.post("/api/planner/obligation")
def api_obligation_upsert(payload: dict = Body(...), user: dict = Depends(require_auth)):
    conn = get_conn()
    uid = user["id"]
    item_id = payload.get("id")
    name = (payload.get("name") or "").strip()
    amount = payload.get("amount", 0)
    category = (payload.get("category") or "").strip()
    if not name or amount <= 0:
        raise HTTPException(400, "Name and positive amount required.")

    if item_id:
        conn.execute(
            "UPDATE obligations SET name=?, category=?, amount=?, due_day=? WHERE id=? AND user_id=?",
            (name, category, amount, payload.get("due_day"), item_id, uid),
        )
    else:
        conn.execute(
            "INSERT INTO obligations (user_id, name, category, amount, due_day) VALUES (?,?,?,?,?)",
            (uid, name, category, amount, payload.get("due_day")),
        )
    conn.commit()
    conn.close()
    return {"ok": True}


@router.delete("/api/planner/obligation/{item_id}")
def api_obligation_delete(item_id: int, user: dict = Depends(require_auth)):
    conn = get_conn()
    conn.execute("DELETE FROM obligations WHERE id=? AND user_id=?", (item_id, user["id"]))
    conn.commit()
    conn.close()
    return {"ok": True}


# ── Savings goals ──────────────────────────────────────────────────


@router.post("/api/planner/savings")
def api_savings_upsert(payload: dict = Body(...), user: dict = Depends(require_auth)):
    conn = get_conn()
    uid = user["id"]
    item_id = payload.get("id")
    target = payload.get("target", 0)
    name = (payload.get("name") or "Savings").strip()

    if item_id:
        conn.execute(
            "UPDATE savings_goals SET name=?, target=? WHERE id=? AND user_id=?",
            (name, target, item_id, uid),
        )
    else:
        conn.execute(
            "INSERT INTO savings_goals (user_id, name, target) VALUES (?,?,?)",
            (uid, name, target),
        )
    conn.commit()
    conn.close()
    return {"ok": True}


@router.delete("/api/planner/savings/{item_id}")
def api_savings_delete(item_id: int, user: dict = Depends(require_auth)):
    conn = get_conn()
    conn.execute("DELETE FROM savings_goals WHERE id=? AND user_id=?", (item_id, user["id"]))
    conn.commit()
    conn.close()
    return {"ok": True}


# ── Category budgets ───────────────────────────────────────────────


@router.post("/api/planner/budgets")
def api_budgets_save(payload: dict = Body(...), user: dict = Depends(require_auth)):
    """Save all category budgets for a month. Payload: {month, budgets: [{category, limit}]}."""
    uid = user["id"]
    month = payload.get("month") or date.today().strftime("%Y-%m")
    items = payload.get("budgets") or []
    conn = get_conn()
    conn.execute("DELETE FROM budget_plans WHERE user_id=? AND month=?", (uid, month))
    for b in items:
        cat = (b.get("category") or "").strip()
        limit_amt = b.get("limit", 0)
        if cat and limit_amt > 0:
            conn.execute(
                "INSERT INTO budget_plans (user_id, month, category, limit_amount) VALUES (?,?,?,?)",
                (uid, month, cat, limit_amt),
            )
    conn.commit()
    conn.close()
    return {"ok": True}


# ── Smart suggest budgets from history ─────────────────────────────


@router.get("/api/planner/suggest")
def api_planner_suggest(user: dict = Depends(require_auth)):
    """Suggest category budgets based on last 3 months average spending."""
    uid = user["id"]
    conn = get_conn()

    rows = conn.execute(
        """
        SELECT category,
               ROUND(AVG(monthly_total), 0) AS avg_spend,
               COUNT(DISTINCT month) AS months_seen
        FROM (
            SELECT category, substr(txn_date, 1, 7) AS month,
                   SUM(amount) AS monthly_total
            FROM transactions
            WHERE user_id = ? AND direction = 'debit' AND is_self_transfer = 0
              AND txn_date >= date('now', '-3 months')
            GROUP BY category, month
        )
        GROUP BY category
        ORDER BY avg_spend DESC
        """,
        (uid,),
    ).fetchall()

    # Also detect likely income (recurring credits)
    income_rows = conn.execute(
        """
        SELECT merchant_clean, ROUND(AVG(amount), 0) AS avg_amount,
               COUNT(*) AS occurrences
        FROM transactions
        WHERE user_id = ? AND direction = 'credit' AND is_self_transfer = 0
          AND txn_date >= date('now', '-3 months')
          AND amount > 5000
        GROUP BY merchant_clean
        HAVING occurrences >= 2
        ORDER BY avg_amount DESC
        """,
        (uid,),
    ).fetchall()

    conn.close()

    return {
        "suggested_budgets": [
            {"category": r["category"] or "Uncategorized", "avg_spend": r["avg_spend"]}
            for r in rows
            if r["avg_spend"] and r["avg_spend"] > 0
        ],
        "detected_income": [
            {"source": r["merchant_clean"], "avg_amount": r["avg_amount"]} for r in income_rows
        ],
    }
