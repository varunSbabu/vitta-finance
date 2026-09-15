"""Tests for auth — open signup, email verification, password reset, lockout.

Full Google OAuth can't be exercised without a real Google account and
browser, so these cover what's actually ours to get right: the session
management, password auth, email verification flow, password reset flow,
and that every data endpoint is wired to require_auth.
"""

import importlib
import os
import pathlib
import tempfile


def _reload_auth_with_env(**env):
    for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "FRONTEND_URL"):
        os.environ.pop(k, None)
    os.environ.update(env)
    import auth

    importlib.reload(auth)
    return auth


def _fresh_app(**env):
    """Reload db + auth against a throwaway DB file, with a clean
    in-memory lockout table. Returns (auth module, TestClient, db_path)."""
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()

    import db

    db.DB_PATH = pathlib.Path(tmp_db.name)
    db.init_db()

    auth = _reload_auth_with_env(**env)
    auth._failed_attempts.clear()

    os.environ.setdefault(
        "SESSION_SECRET_KEY",
        "test-only-key-for-auth",  # pragma: allowlist secret
    )
    import main

    importlib.reload(main)

    from fastapi.testclient import TestClient

    return auth, TestClient(main.app), tmp_db.name


# ── Basic auth plumbing ─────────────────────────────────────────────


def test_is_configured_false_without_credentials():
    auth = _reload_auth_with_env()
    assert auth.is_configured() is False
    print("  OK is_configured() false with no client id/secret")


def test_is_configured_true_with_credentials():
    auth = _reload_auth_with_env(GOOGLE_CLIENT_ID="x", GOOGLE_CLIENT_SECRET="y")
    assert auth.is_configured() is True
    print("  OK is_configured() true once both client id and secret are set")


def test_require_auth_raises_without_session():
    auth = _reload_auth_with_env()
    from fastapi import HTTPException

    class FakeRequest:
        session = {}

    try:
        auth.require_auth(FakeRequest())
        assert False, "should have raised"
    except HTTPException as e:
        assert e.status_code == 401
    print("  OK require_auth raises 401 with empty session")


def test_require_auth_returns_user_with_session():
    auth = _reload_auth_with_env()

    class FakeRequest:
        session = {"user": {"id": 1, "email": "varun@example.com", "email_verified": True}}

    result = auth.require_auth(FakeRequest())
    assert result["email"] == "varun@example.com"
    print("  OK require_auth returns the session user when present")


def test_require_verified_rejects_unverified():
    auth = _reload_auth_with_env()
    from fastapi import HTTPException

    class FakeRequest:
        session = {"user": {"id": 1, "email": "x@y.com", "email_verified": False}}

    try:
        auth.require_verified(FakeRequest())
        assert False, "should have raised"
    except HTTPException as e:
        assert e.status_code == 403
    print("  OK require_verified raises 403 for unverified user")


def test_require_verified_allows_verified():
    auth = _reload_auth_with_env()

    class FakeRequest:
        session = {"user": {"id": 1, "email": "x@y.com", "email_verified": True}}

    result = auth.require_verified(FakeRequest())
    assert result["email"] == "x@y.com"
    print("  OK require_verified passes for verified user")


def test_all_data_endpoints_are_gated():
    """Every route except / and /api/auth/* must depend on require_auth."""
    os.environ.setdefault(
        "SESSION_SECRET_KEY",
        "test-only-key",  # pragma: allowlist secret
    )
    import main

    importlib.reload(main)

    from auth import require_auth

    exempt_paths = {
        "/",
        "/api/auth/login",
        "/api/auth/callback",
        "/api/auth/me",
        "/api/auth/logout",
        "/api/auth/password-status",
        "/api/auth/signup",
        "/api/auth/login-password",
        "/api/auth/verify-email",
        "/api/auth/resend-verification",
        "/api/auth/forgot-password",
        "/api/auth/reset-password",
        "/api/contacts/google/callback",
        "/api/health",
    }

    ungated = []
    for route in main.app.routes:
        path = getattr(route, "path", None)
        if path is None or path in exempt_paths or not path.startswith("/api/"):
            continue
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        dep_calls = {d.call for d in dependant.dependencies}
        if require_auth not in dep_calls:
            ungated.append(path)

    assert not ungated, f"Endpoints missing auth: {ungated}"
    print(
        f"  OK all {sum(1 for r in main.app.routes if getattr(r, 'path', '').startswith('/api/') and r.path not in exempt_paths)} data endpoints require auth"
    )


# ── Password hashing ────────────────────────────────────────────────


def test_password_hash_roundtrip():
    auth = _reload_auth_with_env()
    h = auth._hash_password("correcthorsebattery")
    assert h != "correcthorsebattery"
    assert auth._verify_password("correcthorsebattery", h) is True
    assert auth._verify_password("wrongpassword", h) is False
    print("  OK password hash roundtrips and rejects wrong password")


def test_verify_password_malformed_hash_fails_closed():
    auth = _reload_auth_with_env()
    assert auth._verify_password("anything", "not-a-real-bcrypt-hash") is False
    print("  OK malformed stored hash fails closed instead of raising")


# ── Open signup ─────────────────────────────────────────────────────


def test_signup_open_to_any_email():
    _, client, dbfile = _fresh_app()
    r = client.post(
        "/api/auth/signup",
        json={
            "email": "anyone@example.com",
            "password": "longenoughpassword",  # pragma: allowlist secret
        },
    )
    assert r.status_code == 200
    assert r.json()["email"] == "anyone@example.com"
    os.unlink(dbfile)
    print("  OK signup is open to any email address")


def test_signup_rejects_short_password():
    _, client, dbfile = _fresh_app()
    r = client.post(
        "/api/auth/signup",
        json={
            "email": "test@example.com",
            "password": "short",  # pragma: allowlist secret
        },
    )
    assert r.status_code == 400
    os.unlink(dbfile)
    print("  OK signup rejects password under the minimum length")


def test_signup_then_me_is_authenticated():
    _, client, dbfile = _fresh_app()
    r = client.post(
        "/api/auth/signup",
        json={
            "email": "user@example.com",
            "password": "correcthorsebattery",  # pragma: allowlist secret
        },
    )
    assert r.status_code == 200
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "user@example.com"
    assert me.json()["email_verified"] is False
    os.unlink(dbfile)
    print("  OK signup establishes session, user is unverified")


def test_signup_twice_rejected_second_time():
    _, client, dbfile = _fresh_app()
    client.post(
        "/api/auth/signup",
        json={
            "email": "user@example.com",
            "password": "correcthorsebattery",  # pragma: allowlist secret
        },
    )
    r2 = client.post(
        "/api/auth/signup",
        json={
            "email": "user@example.com",
            "password": "differentpassword",  # pragma: allowlist secret
        },
    )
    assert r2.status_code == 409
    os.unlink(dbfile)
    print("  OK second signup with existing password is rejected")


def test_signup_different_emails_create_separate_accounts():
    _, client, dbfile = _fresh_app()
    r1 = client.post(
        "/api/auth/signup",
        json={
            "email": "alice@example.com",
            "password": "password123abc",  # pragma: allowlist secret
        },
    )
    from fastapi.testclient import TestClient

    import main

    client2 = TestClient(main.app)
    r2 = client2.post(
        "/api/auth/signup",
        json={
            "email": "bob@example.com",
            "password": "password456def",  # pragma: allowlist secret
        },
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["id"] != r2.json()["id"]
    os.unlink(dbfile)
    print("  OK different emails create separate accounts")


# ── Password login ──────────────────────────────────────────────────


def test_login_password_wrong_password_generic_error():
    _, client, dbfile = _fresh_app()
    client.post(
        "/api/auth/signup",
        json={
            "email": "user@example.com",
            "password": "correcthorsebattery",  # pragma: allowlist secret
        },
    )
    r = client.post(
        "/api/auth/login-password",
        json={
            "email": "user@example.com",
            "password": "wrongpassword",  # pragma: allowlist secret
        },
    )
    assert r.status_code == 401
    assert "invalid" in r.json()["detail"].lower()
    os.unlink(dbfile)
    print("  OK wrong password returns generic 401")


def test_login_password_unknown_email_same_generic_error():
    _, client, dbfile = _fresh_app()
    client.post(
        "/api/auth/signup",
        json={
            "email": "user@example.com",
            "password": "correcthorsebattery",  # pragma: allowlist secret
        },
    )
    r_unknown = client.post(
        "/api/auth/login-password",
        json={
            "email": "nosuchuser@example.com",
            "password": "whatever12345",  # pragma: allowlist secret
        },
    )
    r_wrong = client.post(
        "/api/auth/login-password",
        json={
            "email": "user@example.com",
            "password": "wrongpassword",  # pragma: allowlist secret
        },
    )
    assert r_unknown.status_code == r_wrong.status_code == 401
    assert r_unknown.json()["detail"] == r_wrong.json()["detail"]
    os.unlink(dbfile)
    print("  OK unknown-email and wrong-password responses are indistinguishable")


def test_login_password_correct_credentials_succeed():
    _, client, dbfile = _fresh_app()
    client.post(
        "/api/auth/signup",
        json={
            "email": "user@example.com",
            "password": "correcthorsebattery",  # pragma: allowlist secret
        },
    )
    client.cookies.clear()
    r = client.post(
        "/api/auth/login-password",
        json={
            "email": "user@example.com",
            "password": "correcthorsebattery",  # pragma: allowlist secret
        },
    )
    assert r.status_code == 200
    assert r.json()["email"] == "user@example.com"
    os.unlink(dbfile)
    print("  OK correct email + password logs in successfully")


def test_login_password_lockout_after_threshold():
    auth, client, dbfile = _fresh_app()
    client.post(
        "/api/auth/signup",
        json={
            "email": "user@example.com",
            "password": "correcthorsebattery",  # pragma: allowlist secret
        },
    )

    statuses = []
    for _ in range(auth._LOCKOUT_THRESHOLD):
        r = client.post(
            "/api/auth/login-password",
            json={
                "email": "user@example.com",
                "password": "wrongpassword",  # pragma: allowlist secret
            },
        )
        statuses.append(r.status_code)
    assert statuses == [401] * auth._LOCKOUT_THRESHOLD

    r_locked = client.post(
        "/api/auth/login-password",
        json={
            "email": "user@example.com",
            "password": "correcthorsebattery",  # pragma: allowlist secret
        },
    )
    assert r_locked.status_code == 429
    os.unlink(dbfile)
    print("  OK lockout kicks in after repeated failures")


def test_password_status_reflects_state():
    _, client, dbfile = _fresh_app()
    before = client.get("/api/auth/password-status").json()
    assert before["signed_in"] is False
    client.post(
        "/api/auth/signup",
        json={
            "email": "user@example.com",
            "password": "correcthorsebattery",  # pragma: allowlist secret
        },
    )
    after = client.get("/api/auth/password-status").json()
    assert after["has_password"] is True
    assert after["signed_in"] is True
    os.unlink(dbfile)
    print("  OK password-status reflects sign-in and password state")


# ── Email verification ──────────────────────────────────────────────


def test_signup_sends_verification_and_verify_works():
    _, client, dbfile = _fresh_app()
    client.post(
        "/api/auth/signup",
        json={
            "email": "verify@example.com",
            "password": "correcthorsebattery",  # pragma: allowlist secret
        },
    )

    me = client.get("/api/auth/me").json()
    assert me["email_verified"] is False

    import db

    conn = db.get_conn()
    row = conn.execute(
        "SELECT email_verify_token FROM users WHERE email = ?", ("verify@example.com",)
    ).fetchone()
    conn.close()
    token = row["email_verify_token"]
    assert token is not None

    r = client.post("/api/auth/verify-email", json={"token": token})
    assert r.status_code == 200
    assert r.json()["ok"] is True

    me2 = client.get("/api/auth/me").json()
    assert me2["email_verified"] is True
    os.unlink(dbfile)
    print("  OK signup creates verification token, verify-email endpoint works")


def test_verify_email_invalid_token_rejected():
    _, client, dbfile = _fresh_app()
    r = client.post("/api/auth/verify-email", json={"token": "bogus-nonexistent-token"})
    assert r.status_code == 400
    os.unlink(dbfile)
    print("  OK invalid verification token is rejected")


def test_verify_email_expired_token_rejected():
    _, client, dbfile = _fresh_app()
    client.post(
        "/api/auth/signup",
        json={
            "email": "expire@example.com",
            "password": "correcthorsebattery",  # pragma: allowlist secret
        },
    )

    import db

    conn = db.get_conn()
    conn.execute(
        "UPDATE users SET email_verify_expires = '2020-01-01T00:00:00+00:00' WHERE email = ?",
        ("expire@example.com",),
    )
    conn.commit()
    token = conn.execute(
        "SELECT email_verify_token FROM users WHERE email = ?", ("expire@example.com",)
    ).fetchone()["email_verify_token"]
    conn.close()

    r = client.post("/api/auth/verify-email", json={"token": token})
    assert r.status_code == 400
    assert "expired" in r.json()["detail"].lower()
    os.unlink(dbfile)
    print("  OK expired verification token is rejected")


def test_resend_verification():
    _, client, dbfile = _fresh_app()
    client.post(
        "/api/auth/signup",
        json={
            "email": "resend@example.com",
            "password": "correcthorsebattery",  # pragma: allowlist secret
        },
    )

    import db

    conn = db.get_conn()
    old_token = conn.execute(
        "SELECT email_verify_token FROM users WHERE email = ?", ("resend@example.com",)
    ).fetchone()["email_verify_token"]
    conn.close()

    r = client.post("/api/auth/resend-verification")
    assert r.status_code == 200

    conn = db.get_conn()
    new_token = conn.execute(
        "SELECT email_verify_token FROM users WHERE email = ?", ("resend@example.com",)
    ).fetchone()["email_verify_token"]
    conn.close()

    assert new_token != old_token
    os.unlink(dbfile)
    print("  OK resend-verification generates a new token")


# ── Password reset ──────────────────────────────────────────────────


def test_forgot_password_always_returns_200():
    _, client, dbfile = _fresh_app()
    r_real = client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
    assert r_real.status_code == 200
    os.unlink(dbfile)
    print("  OK forgot-password returns 200 even for unknown email (no enumeration)")


def test_forgot_and_reset_password_flow():
    _, client, dbfile = _fresh_app()
    client.post(
        "/api/auth/signup",
        json={
            "email": "reset@example.com",
            "password": "oldpassword123",  # pragma: allowlist secret
        },
    )
    client.post("/api/auth/logout")

    client.post("/api/auth/forgot-password", json={"email": "reset@example.com"})

    import db

    conn = db.get_conn()
    row = conn.execute("SELECT token FROM password_reset_tokens ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    reset_token = row["token"]

    r = client.post(
        "/api/auth/reset-password",
        json={
            "token": reset_token,
            "password": "newpassword456",  # pragma: allowlist secret
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    client.cookies.clear()
    r_login = client.post(
        "/api/auth/login-password",
        json={
            "email": "reset@example.com",
            "password": "newpassword456",  # pragma: allowlist secret
        },
    )
    assert r_login.status_code == 200

    r_old = client.post(
        "/api/auth/login-password",
        json={
            "email": "reset@example.com",
            "password": "oldpassword123",  # pragma: allowlist secret
        },
    )
    assert r_old.status_code == 401
    os.unlink(dbfile)
    print("  OK forgot -> reset -> login with new password works, old password rejected")


def test_reset_password_marks_email_verified():
    _, client, dbfile = _fresh_app()
    client.post(
        "/api/auth/signup",
        json={
            "email": "verify-via-reset@example.com",
            "password": "oldpassword123",  # pragma: allowlist secret
        },
    )

    import db

    conn = db.get_conn()
    verified_before = conn.execute(
        "SELECT email_verified FROM users WHERE email = ?", ("verify-via-reset@example.com",)
    ).fetchone()["email_verified"]
    conn.close()
    assert verified_before == 0

    client.post("/api/auth/forgot-password", json={"email": "verify-via-reset@example.com"})

    conn = db.get_conn()
    reset_token = conn.execute("SELECT token FROM password_reset_tokens ORDER BY id DESC LIMIT 1").fetchone()[
        "token"
    ]
    conn.close()

    client.post(
        "/api/auth/reset-password",
        json={
            "token": reset_token,
            "password": "newpassword456",  # pragma: allowlist secret
        },
    )

    conn = db.get_conn()
    verified_after = conn.execute(
        "SELECT email_verified FROM users WHERE email = ?", ("verify-via-reset@example.com",)
    ).fetchone()["email_verified"]
    conn.close()
    assert verified_after == 1
    os.unlink(dbfile)
    print("  OK password reset also verifies the email")


def test_reset_password_invalid_token_rejected():
    _, client, dbfile = _fresh_app()
    r = client.post(
        "/api/auth/reset-password",
        json={
            "token": "bogus-token",
            "password": "newpassword456",  # pragma: allowlist secret
        },
    )
    assert r.status_code == 400
    os.unlink(dbfile)
    print("  OK invalid reset token is rejected")


def test_reset_password_used_token_rejected():
    _, client, dbfile = _fresh_app()
    client.post(
        "/api/auth/signup",
        json={
            "email": "reuse@example.com",
            "password": "oldpassword123",  # pragma: allowlist secret
        },
    )
    client.post("/api/auth/forgot-password", json={"email": "reuse@example.com"})

    import db

    conn = db.get_conn()
    reset_token = conn.execute("SELECT token FROM password_reset_tokens ORDER BY id DESC LIMIT 1").fetchone()[
        "token"
    ]
    conn.close()

    r1 = client.post(
        "/api/auth/reset-password",
        json={
            "token": reset_token,
            "password": "newpassword456",  # pragma: allowlist secret
        },
    )
    assert r1.status_code == 200

    r2 = client.post(
        "/api/auth/reset-password",
        json={
            "token": reset_token,
            "password": "anotherpassword789",  # pragma: allowlist secret
        },
    )
    assert r2.status_code == 400
    os.unlink(dbfile)
    print("  OK used reset token cannot be reused")


def test_reset_password_expired_token_rejected():
    _, client, dbfile = _fresh_app()
    client.post(
        "/api/auth/signup",
        json={
            "email": "expiry@example.com",
            "password": "oldpassword123",  # pragma: allowlist secret
        },
    )
    client.post("/api/auth/forgot-password", json={"email": "expiry@example.com"})

    import db

    conn = db.get_conn()
    reset_token = conn.execute("SELECT token FROM password_reset_tokens ORDER BY id DESC LIMIT 1").fetchone()[
        "token"
    ]
    conn.execute(
        "UPDATE password_reset_tokens SET expires_at = '2020-01-01T00:00:00+00:00' WHERE token = ?",
        (reset_token,),
    )
    conn.commit()
    conn.close()

    r = client.post(
        "/api/auth/reset-password",
        json={
            "token": reset_token,
            "password": "newpassword456",  # pragma: allowlist secret
        },
    )
    assert r.status_code == 400
    assert "expired" in r.json()["detail"].lower()
    os.unlink(dbfile)
    print("  OK expired reset token is rejected")


# ── Schema compat ───────────────────────────────────────────────────


def test_password_and_google_users_can_coexist_in_schema():
    _, client, dbfile = _fresh_app()
    r = client.post(
        "/api/auth/signup",
        json={
            "email": "anyone@example.com",
            "password": "correcthorsebattery",  # pragma: allowlist secret
        },
    )
    assert r.status_code == 200
    os.unlink(dbfile)
    print("  OK password-only user (null google_sub) inserts without violating schema")
