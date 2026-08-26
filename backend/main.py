"""Vitta backend — FastAPI + SQLite.

Endpoints:
  POST /api/parse         Upload a PDF, get parsed transactions (not saved).
  POST /api/import        Bulk-insert transactions (after user reviews parse).
  GET  /api/accounts      List connected accounts.
  GET  /api/transactions  List with filters (?category=&account_id=&limit=).
  GET  /api/summary       Dashboard stat tiles + category breakdown.
  GET  /api/merchants     Merchant dictionary (aggregated + rules).
  POST /api/merchants/tag Tag a merchant with a category (applies to all past + future).
  POST /api/reset         Clear all data (dev).

Run: uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import json
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from db import get_conn, init_db, dict_from_row
from parsers.gpay import parse as parse_gpay
from categorization import rule_categorize

app = FastAPI(title="Vitta API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # localhost dev — tighten for prod
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


# ------------------------------------------------------------------ #
# Parse
# ------------------------------------------------------------------ #
@app.post("/api/parse")
async def api_parse(
    file: UploadFile = File(...),
    source: str = Query("gpay_pdf", description="gpay_pdf, phonepe_pdf, bank_pdf, cc_pdf"),
):
    """Parse an uploaded PDF and return preview transactions (not yet saved)."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files accepted for now.")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        tf.write(await file.read())
        tmp_path = tf.name

    try:
        if source == "gpay_pdf":
            txns = parse_gpay(tmp_path)
        else:
            raise HTTPException(400, f"Parser for source={source!r} not implemented yet.")
    except Exception as e:
        raise HTTPException(500, f"Parse failed: {e}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    # Auto-categorize each (Tier 1 rules, then user dictionary)
    conn = get_conn()
    dict_rows = conn.execute("SELECT merchant_key, category FROM merchant_dictionary").fetchall()
    conn.close()
    user_dict = {r["merchant_key"].lower(): r["category"] for r in dict_rows}

    for t in txns:
        key = (t["merchant_raw"] or "").lower()
        if key in user_dict:
            t["category"] = user_dict[key]
            t["tag_source"] = "user_dict"
        else:
            t["category"] = rule_categorize(t["merchant"], t.get("remark"))
            t["tag_source"] = "rules" if t["category"] != "Uncategorized" else "none"

    # Summarise
    total_debit  = sum(t["amount"] for t in txns if t["direction"] == "debit")
    total_credit = sum(t["amount"] for t in txns if t["direction"] == "credit")
    auto = [t for t in txns if t["category"] != "Uncategorized"]
    pct  = round(len(auto) / max(1, len(txns)) * 100)

    accounts = sorted({(t["bank_name"], t["account_last4"]) for t in txns if t["bank_name"]})

    return {
        "source": source,
        "count": len(txns),
        "debits_total": total_debit,
        "credits_total": total_credit,
        "auto_categorized_pct": pct,
        "accounts_detected": [{"bank": b, "last4": l} for b, l in accounts],
        "transactions": txns,
    }


# ------------------------------------------------------------------ #
# Import (bulk insert after user reviews the parse)
# ------------------------------------------------------------------ #
@app.post("/api/import")
def api_import(txns: list[dict] = Body(..., embed=False)):
    """Bulk-insert transactions. Skips duplicates by upi_ref."""
    conn = get_conn()
    inserted = 0
    skipped_dup = 0
    accounts_by_key: dict[tuple[str, str], int] = {}

    # Preload existing accounts
    for row in conn.execute("SELECT id, bank_name, account_last4 FROM accounts"):
        accounts_by_key[(row["bank_name"], row["account_last4"])] = row["id"]

    for t in txns:
        bank = t.get("bank_name") or ""
        last4 = t.get("account_last4") or ""
        key = (bank, last4)
        if key not in accounts_by_key:
            cur = conn.execute(
                "INSERT INTO accounts (bank_name, account_last4) VALUES (?, ?)",
                (bank, last4),
            )
            accounts_by_key[key] = cur.lastrowid
        account_id = accounts_by_key[key]

        try:
            conn.execute(
                """
                INSERT INTO transactions
                  (account_id, txn_date, txn_time, amount, direction,
                   merchant_raw, merchant_clean, upi_ref, source, category, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_id, t["date"], t.get("time"),
                    t["amount"], t["direction"],
                    t["merchant_raw"], t.get("merchant") or t["merchant_raw"],
                    t.get("upi_ref"), t.get("source", "unknown"),
                    t.get("category") or "Uncategorized",
                    json.dumps(t, ensure_ascii=False),
                ),
            )
            inserted += 1
        except Exception as e:
            if "UNIQUE" in str(e):
                skipped_dup += 1
            else:
                conn.close()
                raise HTTPException(500, f"Insert failed: {e}")

    conn.commit()
    conn.close()
    return {"inserted": inserted, "skipped_duplicates": skipped_dup}


# ------------------------------------------------------------------ #
# Accounts
# ------------------------------------------------------------------ #
@app.get("/api/accounts")
def api_accounts():
    conn = get_conn()
    rows = conn.execute("""
        SELECT a.*,
          (SELECT COUNT(*) FROM transactions WHERE account_id = a.id) AS txn_count,
          (SELECT MAX(txn_date) FROM transactions WHERE account_id = a.id) AS last_txn
        FROM accounts a
        ORDER BY txn_count DESC
    """).fetchall()
    conn.close()
    return [dict_from_row(r) for r in rows]


# ------------------------------------------------------------------ #
# Transactions
# ------------------------------------------------------------------ #
@app.get("/api/transactions")
def api_transactions(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = 0,
    category: Optional[str] = None,
    account_id: Optional[int] = None,
    direction: Optional[str] = None,
    q: Optional[str] = None,
):
    where, params = [], []
    if category:
        where.append("category = ?"); params.append(category)
    if account_id:
        where.append("account_id = ?"); params.append(account_id)
    if direction:
        where.append("direction = ?"); params.append(direction)
    if q:
        where.append("(merchant_clean LIKE ? OR merchant_raw LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])

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


# ------------------------------------------------------------------ #
# Summary (dashboard stat tiles + category breakdown)
# ------------------------------------------------------------------ #
@app.get("/api/summary")
def api_summary(month: Optional[str] = Query(None, description="YYYY-MM")):
    conn = get_conn()
    where = "WHERE is_self_transfer = 0"
    params: list = []
    if month:
        where += " AND txn_date LIKE ?"
        params.append(f"{month}%")

    row = conn.execute(f"""
        SELECT
          SUM(CASE WHEN direction='debit'  THEN amount ELSE 0 END) AS total_spent,
          SUM(CASE WHEN direction='credit' THEN amount ELSE 0 END) AS total_received,
          SUM(CASE WHEN direction='debit'  THEN 1 ELSE 0 END)      AS n_debits,
          SUM(CASE WHEN direction='credit' THEN 1 ELSE 0 END)      AS n_credits,
          SUM(CASE WHEN category != 'Uncategorized' AND direction='debit' THEN 1 ELSE 0 END) AS n_auto,
          SUM(CASE WHEN direction='debit'  THEN 1 ELSE 0 END)      AS n_total_debits
        FROM transactions {where}
    """, params).fetchone()

    cats = conn.execute(f"""
        SELECT category, SUM(amount) AS total, COUNT(*) AS n
        FROM transactions
        {where} AND direction = 'debit'
        GROUP BY category ORDER BY total DESC
    """, params).fetchall()

    top_merch = conn.execute(f"""
        SELECT merchant_clean, category, SUM(amount) AS total, COUNT(*) AS n
        FROM transactions
        {where} AND direction = 'debit'
        GROUP BY merchant_clean ORDER BY total DESC LIMIT 10
    """, params).fetchall()

    conn.close()

    auto_pct = round((row["n_auto"] or 0) / max(1, row["n_total_debits"] or 1) * 100)
    return {
        "month": month,
        "spent":            row["total_spent"] or 0,
        "received":         row["total_received"] or 0,
        "auto_categorized": auto_pct,
        "n_transactions":   (row["n_debits"] or 0) + (row["n_credits"] or 0),
        "categories":       [dict_from_row(r) for r in cats],
        "top_merchants":    [dict_from_row(r) for r in top_merch],
    }


# ------------------------------------------------------------------ #
# Merchants dictionary
# ------------------------------------------------------------------ #
@app.get("/api/merchants")
def api_merchants():
    conn = get_conn()
    # Aggregate merchants from transactions + join with dictionary
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


@app.post("/api/merchants/tag")
def api_merchant_tag(payload: dict = Body(...)):
    """Tag a merchant. Applies to all past + future transactions with same merchant_raw."""
    merchant_raw = payload.get("merchant_raw", "").strip()
    category = payload.get("category", "").strip()
    if not merchant_raw or not category:
        raise HTTPException(400, "merchant_raw and category required")

    conn = get_conn()
    # Upsert dictionary
    conn.execute("""
        INSERT INTO merchant_dictionary (merchant_key, category, is_user_tagged, applied_count)
        VALUES (?, ?, 1, 0)
        ON CONFLICT(merchant_key) DO UPDATE SET
          category = excluded.category,
          is_user_tagged = 1
    """, (merchant_raw.lower(), category))

    # Apply to past
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


# ------------------------------------------------------------------ #
# Reset (dev)
# ------------------------------------------------------------------ #
@app.post("/api/reset")
def api_reset():
    conn = get_conn()
    conn.execute("DELETE FROM transactions")
    conn.execute("DELETE FROM accounts")
    conn.execute("DELETE FROM merchant_dictionary")
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/")
def root():
    return {"name": "Vitta API", "version": "0.1.0", "docs": "/docs"}
