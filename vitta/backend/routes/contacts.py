"""Google Contacts CSV import + listing. Business logic (CSV parsing, VPA
phone-number matching) lives in the top-level contacts.py module — this
file is the HTTP layer only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from auth import require_auth
from contacts import import_contacts, parse_google_contacts_csv
from db import dict_from_row, get_conn

router = APIRouter(tags=["contacts"])


@router.post("/api/contacts/import")
async def api_contacts_import(file: UploadFile = File(...), user: dict = Depends(require_auth)):
    """Upload a Google Contacts CSV export. Extracts name + phone numbers
    so future UPI transactions from those numbers resolve to real names."""
    user_id = user["id"]
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(400, "Only CSV files accepted (Google Contacts export).")

    content = await file.read()
    try:
        parsed = parse_google_contacts_csv(content)
    except Exception as e:
        raise HTTPException(500, f"Failed to parse contacts CSV: {e}")

    if not parsed:
        return {
            "rows_in_csv": 0,
            "total_contacts": _count_contacts(user_id),
            "note": "No usable name+phone rows found.",
        }

    return import_contacts(parsed, user_id)


@router.get("/api/contacts")
def api_contacts_list(user: dict = Depends(require_auth)):
    user_id = user["id"]
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM contacts WHERE user_id = ? ORDER BY display_name", (user_id,)
    ).fetchall()
    conn.close()
    return [dict_from_row(r) for r in rows]


def _count_contacts(user_id: int) -> int:
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) AS c FROM contacts WHERE user_id = ?", (user_id,)).fetchone()["c"]
    conn.close()
    return n
