"""Google OAuth2 login for Vitta.

This is a personal-use app, not a multi-tenant one — there's exactly one
set of financial data in the DB and it belongs to one person. So this
isn't access control between users; it's a lock on the front door. Only
the Google account matching ALLOWED_EMAIL can complete sign-in. Anyone
else who reaches the OAuth screen and authenticates as themselves gets
a 403, not a new account.

Uses Authlib for the OAuth2 Authorization Code flow — state generation,
CSRF protection, and ID-token/JWKS verification are handled by a vetted
library instead of hand-rolled here. The resulting session is a signed,
httponly cookie via Starlette's SessionMiddleware (added in main.py); no
token is ever exposed to frontend JS.

IMPORTANT — localhost vs 127.0.0.1: the session cookie is SameSite=Lax,
which browsers withhold from cross-site *subresource* requests (fetch).
SameSite is computed from scheme+host and ignores the port, so serving
the frontend at http://localhost:5757 while calling the API at
http://localhost:8001 counts as same-site and the cookie flows. Mixing
spellings (frontend on localhost, API on 127.0.0.1, or vice versa) makes
them cross-site: every authenticated fetch would silently 401. Keep both
on 'localhost'.
"""

from __future__ import annotations

import os
import time

import bcrypt
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import RedirectResponse

from db import get_conn

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
ALLOWED_EMAIL = os.environ.get("ALLOWED_EMAIL", "").strip().lower()
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5757/app.html#/app")

oauth = OAuth()
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def is_configured() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def is_email_allowed(email: str) -> bool:
    """True if this email may sign in. With ALLOWED_EMAIL unset, sign-in
    is open to whoever completes Google's OAuth flow — fine for local
    dev, but ALLOWED_EMAIL should always be set before this is deployed
    anywhere reachable by someone other than you."""
    if not ALLOWED_EMAIL:
        return True
    return email.strip().lower() == ALLOWED_EMAIL


@router.get("/login")
async def login(request: Request):
    if not is_configured():
        raise HTTPException(
            500,
            "Google OAuth isn't configured yet — set GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET in backend/.env.",
        )
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/callback", name="auth_callback")
async def callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        raise HTTPException(400, f"Google sign-in failed: {e}")

    userinfo = token.get("userinfo")
    if not userinfo:
        raise HTTPException(400, "Google did not return profile info.")

    email = (userinfo.get("email") or "").strip().lower()
    if not email or not userinfo.get("email_verified", False):
        raise HTTPException(403, "Google account email is not verified.")

    if not is_email_allowed(email):
        raise HTTPException(
            403,
            "This app is set up for a single personal account. "
            "Sign in with the Google account it's registered to.",
        )

    sub = userinfo["sub"]
    name = userinfo.get("name", "")
    picture = userinfo.get("picture", "")

    conn = get_conn()
    conn.execute(
        """
        INSERT INTO users (google_sub, email, name, picture)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(google_sub) DO UPDATE SET
          email = excluded.email, name = excluded.name, picture = excluded.picture
        """,
        (sub, email, name, picture),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM users WHERE google_sub = ?", (sub,)).fetchone()
    conn.close()

    request.session["user"] = {
        "id": row["id"],
        "email": email,
        "name": name,
        "picture": picture,
    }
    return RedirectResponse(url=FRONTEND_URL)


@router.get("/me")
def me(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(401, "Not signed in.")
    return user


@router.post("/logout")
def logout(request: Request):
    request.session.pop("user", None)
    return {"ok": True}


def require_auth(request: Request) -> dict:
    """FastAPI dependency — raise 401 unless a valid session is present."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(401, "Not signed in.")
    return user


# ===================================================================== #
# Email + password login — fallback path while Google OAuth credentials
# aren't set up yet. Same single-account gate (ALLOWED_EMAIL) and same
# session mechanism as the Google flow; this is a second door into the
# same house, not a separate access-control model.
# ===================================================================== #

MIN_PASSWORD_LENGTH = 8

# In-memory brute-force lockout. Resets on process restart — fine here,
# since a restart already requires filesystem access to this machine.
# Keyed by email; bcrypt's own cost factor is the primary defense, this
# is a cheap second layer against many rapid guesses over the network.
_LOCKOUT_THRESHOLD = 5
_LOCKOUT_SECONDS = 300
_failed_attempts: dict[str, list] = {}  # email -> [count, locked_until_ts]


def _check_lockout(email: str) -> None:
    entry = _failed_attempts.get(email)
    if entry and entry[1] > time.time():
        remaining = int(entry[1] - time.time())
        raise HTTPException(429, f"Too many failed attempts. Try again in {remaining}s.")


def _record_failure(email: str) -> None:
    entry = _failed_attempts.setdefault(email, [0, 0])
    entry[0] += 1
    if entry[0] >= _LOCKOUT_THRESHOLD:
        entry[1] = time.time() + _LOCKOUT_SECONDS


def _record_success(email: str) -> None:
    _failed_attempts.pop(email, None)


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False  # malformed stored hash — fail closed, not open


def _set_session(request: Request, row) -> dict:
    user = {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"] or row["email"].split("@")[0],
        "picture": row["picture"] or "",
    }
    request.session["user"] = user
    return user


@router.get("/password-status")
def password_status():
    """Does the single allowed account already have a password set? Lets
    the frontend show 'create a password' vs 'enter your password'."""
    email = ALLOWED_EMAIL or None
    conn = get_conn()
    row = (
        conn.execute("SELECT password_hash FROM users WHERE email = ?", (email,)).fetchone()
        if email
        else None
    )
    conn.close()
    return {"has_password": bool(row and row["password_hash"]), "email_locked": bool(ALLOWED_EMAIL)}


@router.post("/signup")
def signup(request: Request, payload: dict = Body(...)):
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    name = (payload.get("name") or "").strip()

    if not email or not password:
        raise HTTPException(400, "Email and password are required.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if not is_email_allowed(email):
        raise HTTPException(
            403,
            "This app is set up for a single personal account. Use the email address it's registered to.",
        )

    conn = get_conn()
    existing = conn.execute("SELECT id, password_hash FROM users WHERE email = ?", (email,)).fetchone()
    if existing and existing["password_hash"]:
        conn.close()
        raise HTTPException(409, "An account with this email already has a password. Sign in instead.")

    password_hash = _hash_password(password)
    if existing:
        conn.execute(
            "UPDATE users SET password_hash = ?, name = COALESCE(NULLIF(?, ''), name) WHERE id = ?",
            (password_hash, name, existing["id"]),
        )
        user_id = existing["id"]
    else:
        cur = conn.execute(
            "INSERT INTO users (email, name, password_hash) VALUES (?, ?, ?)",
            (email, name or email.split("@")[0], password_hash),
        )
        user_id = cur.lastrowid
    conn.commit()
    row = conn.execute("SELECT id, email, name, picture FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()

    return _set_session(request, row)


@router.post("/login-password")
def login_password(request: Request, payload: dict = Body(...)):
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    if not email or not password:
        raise HTTPException(400, "Email and password are required.")

    _check_lockout(email)

    conn = get_conn()
    row = conn.execute(
        "SELECT id, email, name, picture, password_hash FROM users WHERE email = ?", (email,)
    ).fetchone()
    conn.close()

    # Same generic error for "no such account" and "wrong password" —
    # don't give an attacker a way to enumerate which emails have accounts.
    if not row or not row["password_hash"] or not _verify_password(password, row["password_hash"]):
        _record_failure(email)
        raise HTTPException(401, "Invalid email or password.")

    if not is_email_allowed(email):
        raise HTTPException(403, "This app is set up for a single personal account.")

    _record_success(email)
    return _set_session(request, row)
