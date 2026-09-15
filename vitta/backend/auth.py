"""Authentication for Vitta — open signup with email verification.

Supports two sign-in paths:
  1. Google OAuth2 (Authlib) — email is auto-verified via Google.
  2. Email + password — user must verify email before accessing data.

Sessions are signed, httponly cookies via Starlette's SessionMiddleware
(added in main.py); no token is ever exposed to frontend JS.

IMPORTANT — localhost vs 127.0.0.1: the session cookie is SameSite=Lax.
SameSite is computed from scheme+host and ignores the port, so serving
the frontend at http://localhost:5757 while calling the API at
http://localhost:8001 counts as same-site and the cookie flows. Mixing
spellings (frontend on localhost, API on 127.0.0.1, or vice versa) makes
them cross-site. Keep both on 'localhost'.
"""

from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timedelta, timezone

import bcrypt
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import RedirectResponse

from db import get_conn
from email_service import send_password_reset_email, send_verification_email

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
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

MIN_PASSWORD_LENGTH = 8
VERIFY_TOKEN_HOURS = 24
RESET_TOKEN_MINUTES = 60

# In-memory brute-force lockout. Resets on process restart — fine for
# local dev since bcrypt's own cost factor is the primary defense; this
# is a cheap second layer against many rapid guesses over the network.
_LOCKOUT_THRESHOLD = 5
_LOCKOUT_SECONDS = 300
_failed_attempts: dict[str, list] = {}


def is_configured() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


# ── Helpers ─────────────────────────────────────────────────────────


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
        return False


def _set_session(request: Request, row) -> dict:
    user = {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"] or row["email"].split("@")[0],
        "picture": row["picture"] or "",
        "email_verified": bool(row["email_verified"]),
    }
    request.session["user"] = user
    return user


def _generate_token() -> str:
    return secrets.token_urlsafe(32)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ── Google OAuth ────────────────────────────────────────────────────


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

    sub = userinfo["sub"]
    name = userinfo.get("name", "")
    picture = userinfo.get("picture", "")

    conn = get_conn()
    conn.execute(
        """
        INSERT INTO users (google_sub, email, name, picture, email_verified)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(google_sub) DO UPDATE SET
          email = excluded.email, name = excluded.name,
          picture = excluded.picture, email_verified = 1
        """,
        (sub, email, name, picture),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, email, name, picture, email_verified FROM users WHERE google_sub = ?", (sub,)
    ).fetchone()
    conn.close()

    return RedirectResponse(url=FRONTEND_URL, headers={"X-User": str(_set_session(request, row))})


# ── Session ─────────────────────────────────────────────────────────


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


def require_verified(request: Request) -> dict:
    """FastAPI dependency — require a signed-in AND email-verified user."""
    user = require_auth(request)
    if not user.get("email_verified"):
        raise HTTPException(403, "Please verify your email address before accessing this resource.")
    return user


# ── Password signup ─────────────────────────────────────────────────


@router.post("/signup")
def signup(request: Request, payload: dict = Body(...)):
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    name = (payload.get("name") or "").strip()

    if not email or not password:
        raise HTTPException(400, "Email and password are required.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    conn = get_conn()
    existing = conn.execute("SELECT id, password_hash FROM users WHERE email = ?", (email,)).fetchone()
    if existing and existing["password_hash"]:
        conn.close()
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")

    password_hash = _hash_password(password)
    verify_token = _generate_token()
    verify_expires = _iso(_utc_now() + timedelta(hours=VERIFY_TOKEN_HOURS))

    if existing:
        conn.execute(
            """UPDATE users SET password_hash = ?, name = COALESCE(NULLIF(?, ''), name),
               email_verify_token = ?, email_verify_expires = ?
               WHERE id = ?""",
            (password_hash, name, verify_token, verify_expires, existing["id"]),
        )
        user_id = existing["id"]
    else:
        cur = conn.execute(
            """INSERT INTO users (email, name, password_hash, email_verify_token, email_verify_expires)
               VALUES (?, ?, ?, ?, ?)""",
            (email, name or email.split("@")[0], password_hash, verify_token, verify_expires),
        )
        user_id = cur.lastrowid
    conn.commit()
    row = conn.execute(
        "SELECT id, email, name, picture, email_verified FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()

    send_verification_email(to=email, token=verify_token)

    return _set_session(request, row)


# ── Password login ──────────────────────────────────────────────────


@router.post("/login-password")
def login_password(request: Request, payload: dict = Body(...)):
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    if not email or not password:
        raise HTTPException(400, "Email and password are required.")

    _check_lockout(email)

    conn = get_conn()
    row = conn.execute(
        "SELECT id, email, name, picture, password_hash, email_verified FROM users WHERE email = ?",
        (email,),
    ).fetchone()
    conn.close()

    if not row or not row["password_hash"] or not _verify_password(password, row["password_hash"]):
        _record_failure(email)
        raise HTTPException(401, "Invalid email or password.")

    _record_success(email)
    return _set_session(request, row)


# ── Email verification ──────────────────────────────────────────────


@router.post("/verify-email")
def verify_email(request: Request, payload: dict = Body(...)):
    """Consume a verification token and mark the user's email as verified."""
    token = (payload.get("token") or "").strip()
    if not token:
        raise HTTPException(400, "Verification token is required.")

    conn = get_conn()
    row = conn.execute(
        "SELECT id, email, name, picture, email_verified, email_verify_token, email_verify_expires FROM users WHERE email_verify_token = ?",
        (token,),
    ).fetchone()

    if not row:
        conn.close()
        raise HTTPException(400, "Invalid or expired verification link.")

    if row["email_verified"]:
        conn.close()
        user = request.session.get("user")
        if user and user["id"] == row["id"]:
            user["email_verified"] = True
            request.session["user"] = user
        return {"ok": True, "message": "Email already verified."}

    expires = row["email_verify_expires"]
    if expires and _utc_now() > datetime.fromisoformat(expires):
        conn.close()
        raise HTTPException(400, "Verification link has expired. Request a new one.")

    conn.execute(
        "UPDATE users SET email_verified = 1, email_verify_token = NULL, email_verify_expires = NULL WHERE id = ?",
        (row["id"],),
    )
    conn.commit()

    updated = conn.execute(
        "SELECT id, email, name, picture, email_verified FROM users WHERE id = ?", (row["id"],)
    ).fetchone()
    conn.close()

    user = request.session.get("user")
    if user and user["id"] == row["id"]:
        _set_session(request, updated)

    return {"ok": True, "message": "Email verified successfully."}


@router.post("/resend-verification")
def resend_verification(request: Request):
    """Resend the verification email for the currently signed-in user."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(401, "Not signed in.")
    if user.get("email_verified"):
        return {"ok": True, "message": "Email already verified."}

    conn = get_conn()
    row = conn.execute("SELECT id, email, email_verified FROM users WHERE id = ?", (user["id"],)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "User not found.")
    if row["email_verified"]:
        conn.close()
        user["email_verified"] = True
        request.session["user"] = user
        return {"ok": True, "message": "Email already verified."}

    verify_token = _generate_token()
    verify_expires = _iso(_utc_now() + timedelta(hours=VERIFY_TOKEN_HOURS))
    conn.execute(
        "UPDATE users SET email_verify_token = ?, email_verify_expires = ? WHERE id = ?",
        (verify_token, verify_expires, row["id"]),
    )
    conn.commit()
    conn.close()

    send_verification_email(to=row["email"], token=verify_token)
    return {"ok": True, "message": "Verification email sent."}


# ── Password reset ──────────────────────────────────────────────────


@router.post("/forgot-password")
def forgot_password(payload: dict = Body(...)):
    """Generate a password reset token and send the reset email.
    Always returns 200 to avoid email enumeration."""
    email = (payload.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "Email is required.")

    conn = get_conn()
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if row:
        token = _generate_token()
        expires = _iso(_utc_now() + timedelta(minutes=RESET_TOKEN_MINUTES))
        conn.execute(
            "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
            (row["id"], token, expires),
        )
        conn.commit()
        send_password_reset_email(to=email, token=token)
    conn.close()

    return {"ok": True, "message": "If that email is registered, a reset link has been sent."}


@router.post("/reset-password")
def reset_password(request: Request, payload: dict = Body(...)):
    """Consume a reset token and set a new password."""
    token = (payload.get("token") or "").strip()
    password = payload.get("password") or ""

    if not token:
        raise HTTPException(400, "Reset token is required.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    conn = get_conn()
    row = conn.execute(
        "SELECT id, user_id, expires_at, used FROM password_reset_tokens WHERE token = ?",
        (token,),
    ).fetchone()

    if not row or row["used"]:
        conn.close()
        raise HTTPException(400, "Invalid or already-used reset link.")

    if _utc_now() > datetime.fromisoformat(row["expires_at"]):
        conn.close()
        raise HTTPException(400, "Reset link has expired. Request a new one.")

    password_hash = _hash_password(password)
    conn.execute(
        "UPDATE users SET password_hash = ?, email_verified = 1 WHERE id = ?", (password_hash, row["user_id"])
    )
    conn.execute("UPDATE password_reset_tokens SET used = 1 WHERE id = ?", (row["id"],))
    conn.commit()

    user_row = conn.execute(
        "SELECT id, email, name, picture, email_verified FROM users WHERE id = ?", (row["user_id"],)
    ).fetchone()
    conn.close()

    return {"ok": True, "message": "Password reset successfully.", "user": _set_session(request, user_row)}


# ── Status endpoint ─────────────────────────────────────────────────


@router.get("/password-status")
def password_status(request: Request):
    """Check if the current user (by session or email param) has a password set."""
    user = request.session.get("user")
    if not user:
        return {"has_password": False, "signed_in": False}
    conn = get_conn()
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
    conn.close()
    return {"has_password": bool(row and row["password_hash"]), "signed_in": True}
