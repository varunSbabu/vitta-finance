"""Statement ingest: upload a PDF, get back parsed + categorized
transactions (not yet saved), then bulk-import the ones the user confirms.

Categorization tiers, applied in /api/parse, in order:
  1. Rules       — deterministic merchant/remark keyword match (categorization.py)
  2. User dict   — exact merchant_raw match from past manual tags
  3. LLM         — Groq fallback for what's left uncategorized (needs GROQ_API_KEY)
Contacts resolve VPA -> display name (Tier 2, orthogonal to category assignment).
"""

from __future__ import annotations

import json
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile

from auth import require_auth
from categorization import rule_categorize
from contacts import resolve_contacts_batch
from db import get_conn
from llm_categorize import CONFIDENCE_THRESHOLD, categorize_batch
from llm_categorize import is_available as llm_available
from parsers.bank_statement import parse as parse_bank
from parsers.gpay import parse as parse_gpay

router = APIRouter(tags=["ingest"])


@router.post("/api/parse")
async def api_parse(
    file: UploadFile = File(...),
    source: str = Query("gpay_pdf", description="gpay_pdf, bank_pdf, phonepe_pdf, cc_pdf"),
    password: Optional[str] = Query(None, description="PDF password (banks use DDMMYYYY DOB)"),
    user: dict = Depends(require_auth),
):
    """Parse an uploaded PDF and return preview transactions (not yet saved)."""
    user_id = user["id"]

    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files accepted for now.")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        tf.write(await file.read())
        tmp_path = tf.name

    try:
        if source == "gpay_pdf":
            txns = parse_gpay(tmp_path)
        elif source == "bank_pdf":
            txns = parse_bank(tmp_path, password=password)
        else:
            raise HTTPException(400, f"Parser for source={source!r} not implemented yet.")
    except Exception as e:
        if "password" in str(e).lower() or "encrypted" in str(e).lower():
            raise HTTPException(
                422,
                "This PDF is password-protected. Indian banks typically use your "
                "date of birth in DDMMYYYY format as the password. "
                "Pass it as the 'password' query parameter.",
            )
        raise HTTPException(500, f"Parse failed: {e}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    # Tier 2a: resolve person-to-person VPAs against imported contacts so
    # "9876543210@ybl" shows up as "Amma" instead of a bank-registered blob.
    vpas = [t.get("vpa") for t in txns if t.get("vpa")]
    contact_matches = resolve_contacts_batch(vpas, user_id) if vpas else {}
    for t in txns:
        vpa = t.get("vpa")
        if vpa and vpa in contact_matches:
            t["merchant"] = contact_matches[vpa]
            t["matched_contact"] = True

    # Tier 1 + Tier 2b: rules, then user dictionary (exact merchant_raw match)
    conn = get_conn()
    dict_rows = conn.execute(
        "SELECT merchant_key, category FROM merchant_dictionary WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    conn.close()
    user_dict = {r["merchant_key"].lower(): r["category"] for r in dict_rows}

    for t in txns:
        key = (t["merchant_raw"] or "").lower()
        if key in user_dict:
            t["category"] = user_dict[key]
            t["tag_source"] = "user_dict"
        else:
            cat = rule_categorize(t.get("merchant") or t["merchant_raw"], t.get("remark"))
            t["category"] = cat
            t["tag_source"] = "rules" if cat != "Uncategorized" else "none"

    # Tier 3: LLM fallback for whatever's still Uncategorized. One batched
    # call per statement, not one per transaction. Skipped silently if
    # GROQ_API_KEY isn't set — those stay Uncategorized for manual tagging.
    still_uncategorized = [t for t in txns if t["category"] == "Uncategorized"]
    if still_uncategorized:
        llm_results = categorize_batch(
            [
                {
                    "merchant": t.get("merchant") or t["merchant_raw"],
                    "remark": t.get("remark", ""),
                    "txn_type": t.get("txn_type", ""),
                    "amount": t["amount"],
                }
                for t in still_uncategorized
            ]
        )
        for t, (cat, conf) in zip(still_uncategorized, llm_results):
            if conf >= CONFIDENCE_THRESHOLD:
                t["category"] = cat
                t["tag_source"] = "llm"
                t["llm_confidence"] = round(conf, 2)

    total_debit = sum(t["amount"] for t in txns if t["direction"] == "debit")
    total_credit = sum(t["amount"] for t in txns if t["direction"] == "credit")
    auto = [t for t in txns if t["category"] != "Uncategorized"]
    pct = round(len(auto) / max(1, len(txns)) * 100)

    accounts = sorted({(t["bank_name"], t["account_last4"]) for t in txns if t["bank_name"]})

    # Stats specific to bank statements
    txn_types: defaultdict = defaultdict(int)
    for t in txns:
        txn_types[t.get("txn_type", "other")] += 1

    with_vpa = sum(1 for t in txns if t.get("vpa"))
    with_remark = sum(1 for t in txns if t.get("remark"))
    contacts_resolved = sum(1 for t in txns if t.get("matched_contact"))
    llm_tagged = sum(1 for t in txns if t.get("tag_source") == "llm")

    return {
        "source": source,
        "count": len(txns),
        "debits_total": total_debit,
        "credits_total": total_credit,
        "auto_categorized_pct": pct,
        "accounts_detected": [{"bank": bank, "last4": last4} for bank, last4 in accounts],
        "txn_types": dict(txn_types),
        "with_vpa": with_vpa,
        "with_remark": with_remark,
        "contacts_resolved": contacts_resolved,
        "llm_tagged": llm_tagged,
        "llm_available": llm_available(),
        "transactions": txns,
    }


@router.post("/api/import")
def api_import(txns: list[dict] = Body(..., embed=False), user: dict = Depends(require_auth)):
    """Bulk-insert transactions. Skips duplicates by upi_ref."""
    user_id = user["id"]
    conn = get_conn()
    inserted = 0
    skipped_dup = 0
    accounts_by_key: dict[tuple[str, str], int] = {}

    for row in conn.execute(
        "SELECT id, bank_name, account_last4 FROM accounts WHERE user_id = ?", (user_id,)
    ):
        accounts_by_key[(row["bank_name"], row["account_last4"])] = row["id"]

    for t in txns:
        bank = t.get("bank_name") or ""
        last4 = t.get("account_last4") or ""
        key = (bank, last4)
        if key not in accounts_by_key:
            cur = conn.execute(
                "INSERT INTO accounts (user_id, bank_name, account_last4) VALUES (?, ?, ?)",
                (user_id, bank, last4),
            )
            accounts_by_key[key] = cur.lastrowid
        account_id = accounts_by_key[key]

        upi_ref = t.get("upi_ref") or None

        if not upi_ref:
            existing = conn.execute(
                """
                SELECT id FROM transactions
                WHERE user_id = ? AND account_id = ? AND txn_date = ? AND amount = ?
                  AND direction = ? AND merchant_raw = ?
                """,
                (user_id, account_id, t["date"], t["amount"], t["direction"], t["merchant_raw"]),
            ).fetchone()
            if existing:
                skipped_dup += 1
                continue

        try:
            conn.execute(
                """
                INSERT INTO transactions
                  (user_id, account_id, txn_date, txn_time, amount, direction,
                   merchant_raw, merchant_clean, upi_ref, vpa, remark,
                   source, category, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    account_id,
                    t["date"],
                    t.get("time"),
                    t["amount"],
                    t["direction"],
                    t["merchant_raw"],
                    t.get("merchant") or t["merchant_raw"],
                    upi_ref,
                    t.get("vpa", ""),
                    t.get("remark", ""),
                    t.get("source", "unknown"),
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
