"""Admin-only endpoints — user management, gated by ADMIN_EMAIL env var.

Only requests whose session user's email matches ADMIN_EMAIL (case-
insensitive, exact match) are allowed. If ADMIN_EMAIL isn't set, every
admin endpoint refuses with 503 so a misconfigured deploy can't leak
user data by accident.

Endpoints:
  GET    /api/admin/users        — list every user + their data counts
  POST   /api/admin/users        — create a user (email + password)
  DELETE /api/admin/users/{id}   — hard-delete user and every row they own
"""

from __future__ import annotations

import os
from datetime import datetime

import bcrypt
from fastapi import APIRouter, Body, Depends, HTTPException, Request

from auth import MIN_PASSWORD_LENGTH, require_auth
from db import dict_from_row, get_conn

router = APIRouter(tags=["admin"])


ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip().lower()

# Same set as auth.delete_me — kept in sync so admin delete cascades
# through every user-scoped table. A schema addition has to be added
# here explicitly, so an orphan table can't silently leak rows.
_USER_TABLES = (
    "transactions",
    "accounts",
    "merchant_dictionary",
    "contacts",
    "income_sources",
    "obligations",
    "budget_plans",
    "savings_goals",
    "debts",
    "password_reset_tokens",
)


def require_admin(user: dict = Depends(require_auth)) -> dict:
    """FastAPI dependency — refuse unless the signed-in user is the admin."""
    if not ADMIN_EMAIL:
        raise HTTPException(
            503,
            "Admin API is disabled: set ADMIN_EMAIL in backend/.env to enable it.",
        )
    if (user.get("email") or "").strip().lower() != ADMIN_EMAIL:
        raise HTTPException(403, "Admin access only.")
    return user


@router.get("/api/admin/users")
def api_admin_list_users(_: dict = Depends(require_admin)):
    """Every user + their key counts. Passwords are never returned."""
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT
          u.id, u.email, u.name, u.picture, u.email_verified,
          u.created_at,
          u.google_sub IS NOT NULL AS has_google,
          u.password_hash IS NOT NULL AS has_password,
          (SELECT COUNT(*) FROM transactions WHERE user_id = u.id) AS txn_count,
          (SELECT COUNT(*) FROM accounts    WHERE user_id = u.id) AS account_count,
          (SELECT COUNT(*) FROM contacts    WHERE user_id = u.id) AS contact_count,
          (SELECT MAX(txn_date) FROM transactions WHERE user_id = u.id) AS last_txn_date
        FROM users u
        ORDER BY u.created_at DESC
        """
    ).fetchall()
    conn.close()
    return {
        "admin_email": ADMIN_EMAIL,
        "count": len(rows),
        "users": [dict_from_row(r) for r in rows],
    }


@router.post("/api/admin/users")
def api_admin_create_user(
    payload: dict = Body(...),
    _: dict = Depends(require_admin),
):
    """Create a password-based user. Sets email_verified=1 immediately since
    an admin creating an account has already vouched for the address."""
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    name = (payload.get("name") or "").strip()

    if "@" not in email or "." not in email:
        raise HTTPException(400, "Valid email required.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    conn = get_conn()
    try:
        cur = conn.execute(
            """
            INSERT INTO users (email, name, password_hash, email_verified, created_at)
            VALUES (?, ?, ?, 1, ?)
            """,
            (email, name or email.split("@")[0], password_hash, datetime.utcnow().isoformat()),
        )
        conn.commit()
        user_id = cur.lastrowid
    except Exception as e:
        conn.close()
        # UNIQUE(email) is the expected failure mode.
        if "UNIQUE" in str(e).upper():
            raise HTTPException(409, f"A user with email {email!r} already exists.")
        raise HTTPException(500, f"Create failed: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return {"ok": True, "id": user_id, "email": email}


@router.delete("/api/admin/users/{user_id}")
def api_admin_delete_user(
    user_id: int,
    request: Request,
    admin: dict = Depends(require_admin),
):
    """Hard-delete a user and every row they own. Refuses to delete the
    admin's own account here — the admin can do that from Settings if
    they really mean it, so a misclick in the admin table can't nuke
    their own access mid-session."""
    if user_id == admin.get("id"):
        raise HTTPException(
            400,
            "Refusing to delete your own admin account from this UI. "
            "Use Settings → Danger zone if you really mean it.",
        )

    conn = get_conn()
    row = conn.execute("SELECT id, email FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "User not found.")

    counts = {}
    for table in _USER_TABLES:
        counts[table] = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "deleted_email": row["email"], "cascaded": counts}
