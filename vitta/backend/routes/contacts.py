"""Google Contacts import (CSV upload + direct API fetch) + listing.

Two import paths:
  1. POST /api/contacts/import — CSV file upload (existing)
  2. GET  /api/contacts/google  — starts OAuth for contacts.readonly scope
     GET  /api/contacts/google/callback — fetches contacts via People API

Business logic (CSV parsing, People API fetch, VPA phone-number matching)
lives in the top-level contacts.py module — this file is the HTTP layer only.
"""

from __future__ import annotations

import os

import structlog
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import RedirectResponse
from starlette.requests import Request

from auth import require_auth
from contacts import fetch_google_contacts, import_contacts, parse_google_contacts_csv
from db import dict_from_row, get_conn

log = structlog.get_logger()

router = APIRouter(tags=["contacts"])

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5757/app.html#/app")

# Separate OAuth registration for contacts — same client credentials but
# requests the contacts.readonly scope instead of openid/email/profile.
_contacts_oauth = OAuth()
_contacts_oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "https://www.googleapis.com/auth/contacts.readonly"},
)


# ── CSV upload (existing) ───────────────────────────────────────────


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


# ── Google People API (new) ─────────────────────────────────────────


@router.get("/api/contacts/google")
async def api_contacts_google_auth(request: Request, user: dict = Depends(require_auth)):
    """Start OAuth flow to fetch contacts directly from Google."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(500, "Google OAuth not configured.")
    redirect_uri = str(request.url_for("contacts_google_callback"))
    return await _contacts_oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/api/contacts/google/callback", name="contacts_google_callback")
async def api_contacts_google_callback(request: Request):
    """Handle OAuth callback — fetch contacts from People API and import."""
    # Session must exist (user started the flow while logged in)
    user = request.session.get("user")
    if not user or not user.get("id"):
        return _redirect_with_error("Session expired. Please sign in and try again.")
    user_id = user["id"]

    try:
        token = await _contacts_oauth.google.authorize_access_token(request)
    except Exception as e:
        log.error("contacts_oauth_failed", error=str(e))
        return _redirect_with_error(f"Google authorization failed: {e}")

    access_token = token.get("access_token")
    if not access_token:
        return _redirect_with_error("No access token received from Google.")

    try:
        parsed = fetch_google_contacts(access_token)
    except RuntimeError as e:
        log.error("people_api_fetch_failed", error=str(e))
        return _redirect_with_error(str(e))

    if not parsed:
        settings_url = FRONTEND_URL.split("#")[0] + "#/app/settings?contacts=empty"
        return RedirectResponse(url=settings_url)

    result = import_contacts(parsed, user_id)
    log.info("google_contacts_imported", user_id=user_id, count=result["total_contacts"])

    settings_url = (
        FRONTEND_URL.split("#")[0]
        + f"#/app/settings?contacts=ok&imported={result['rows_in_csv']}&total={result['total_contacts']}"
    )
    return RedirectResponse(url=settings_url)


# ── Listing + helpers ───────────────────────────────────────────────


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


def _redirect_with_error(msg: str) -> RedirectResponse:
    """Redirect back to frontend settings with an error message."""
    from urllib.parse import quote

    settings_url = FRONTEND_URL.split("#")[0] + f"#/app/settings?contacts=error&msg={quote(msg)}"
    return RedirectResponse(url=settings_url)
