"""Tests for the auth gate.

Full Google OAuth can't be exercised without a real Google account and
browser, so these cover what's actually ours to get right: the
single-account allowlist, the require_auth dependency, and that every
data endpoint is actually wired to it (not just some of them).
"""

import importlib
import os


def _reload_auth_with_env(**env):
    for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "ALLOWED_EMAIL", "FRONTEND_URL"):
        os.environ.pop(k, None)
    os.environ.update(env)
    import auth

    importlib.reload(auth)
    return auth


def test_allowed_email_exact_match():
    auth = _reload_auth_with_env(ALLOWED_EMAIL="varun@twenty20sys.com")
    assert auth.is_email_allowed("varun@twenty20sys.com") is True
    print("  OK exact email match allowed")


def test_allowed_email_case_insensitive():
    auth = _reload_auth_with_env(ALLOWED_EMAIL="Varun@Twenty20Sys.com")
    assert auth.is_email_allowed("varun@twenty20sys.com") is True
    assert auth.is_email_allowed("VARUN@TWENTY20SYS.COM") is True
    print("  OK email match is case-insensitive")


def test_disallowed_email_rejected():
    auth = _reload_auth_with_env(ALLOWED_EMAIL="varun@twenty20sys.com")
    assert auth.is_email_allowed("someone.else@gmail.com") is False
    print("  OK non-matching email rejected")


def test_no_allowlist_configured_allows_anyone():
    # Documents current behavior: unset ALLOWED_EMAIL == open sign-in.
    # This is a deliberate local-dev fallback, not something to rely on
    # once deployed — .env.example calls this out explicitly.
    auth = _reload_auth_with_env(ALLOWED_EMAIL="")
    assert auth.is_email_allowed("anyone@example.com") is True
    print("  OK unset ALLOWED_EMAIL falls back to open (dev-only) — by design")


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
        session = {"user": {"id": 1, "email": "varun@twenty20sys.com"}}

    result = auth.require_auth(FakeRequest())
    assert result["email"] == "varun@twenty20sys.com"
    print("  OK require_auth returns the session user when present")


def test_all_data_endpoints_are_gated():
    """Every route except / and /api/auth/* must depend on require_auth.
    This is the test that would have caught forgetting Depends() on a
    new endpoint — it inspects the live FastAPI app, not a hand-maintained
    list."""
    os.environ.setdefault("SESSION_SECRET_KEY", "test-only-key")
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
        # Deliberately unauthenticated: Docker healthchecks and uptime
        # monitors can't carry a session cookie, and it touches no data.
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


# ===================================================================== #
# Password auth — hashing, endpoints, lockout. Uses a scratch DB so these
# don't touch the real vitta.db, matching test_self_transfer.py / test_contacts.py.
# ===================================================================== #


def _fresh_password_auth(**env):
    """Reload db + auth against a throwaway DB file, with a clean
    in-memory lockout table. Returns (auth module, TestClient)."""
    import pathlib
    import tempfile

    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()

    import db

    db.DB_PATH = pathlib.Path(tmp_db.name)
    db.init_db()

    auth = _reload_auth_with_env(**env)
    auth._failed_attempts.clear()

    os.environ.setdefault("SESSION_SECRET_KEY", "test-only-key-for-password-auth")
    import main

    importlib.reload(main)

    from fastapi.testclient import TestClient

    return auth, TestClient(main.app), tmp_db.name


def test_password_hash_roundtrip():
    auth = _reload_auth_with_env()
    h = auth._hash_password("correcthorsebattery")
    assert h != "correcthorsebattery"  # never store plaintext
    assert auth._verify_password("correcthorsebattery", h) is True
    assert auth._verify_password("wrongpassword", h) is False
    print("  OK password hash roundtrips and rejects wrong password")


def test_verify_password_malformed_hash_fails_closed():
    auth = _reload_auth_with_env()
    assert auth._verify_password("anything", "not-a-real-bcrypt-hash") is False
    print("  OK malformed stored hash fails closed instead of raising")


def test_signup_rejects_short_password():
    auth, client, dbfile = _fresh_password_auth(ALLOWED_EMAIL="varun@twenty20sys.com")
    r = client.post("/api/auth/signup", json={"email": "varun@twenty20sys.com", "password": "short"})
    assert r.status_code == 400
    os.unlink(dbfile)
    print("  OK signup rejects password under the minimum length")


def test_signup_rejects_disallowed_email():
    auth, client, dbfile = _fresh_password_auth(ALLOWED_EMAIL="varun@twenty20sys.com")
    r = client.post("/api/auth/signup", json={"email": "attacker@evil.com", "password": "longenoughpassword"})
    assert r.status_code == 403
    os.unlink(dbfile)
    print("  OK signup rejects an email that isn't the allowed account")


def test_signup_then_me_is_authenticated():
    auth, client, dbfile = _fresh_password_auth(ALLOWED_EMAIL="varun@twenty20sys.com")
    r = client.post(
        "/api/auth/signup", json={"email": "varun@twenty20sys.com", "password": "correcthorsebattery"}
    )
    assert r.status_code == 200
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "varun@twenty20sys.com"
    os.unlink(dbfile)
    print("  OK signup immediately establishes an authenticated session")


def test_signup_twice_rejected_second_time():
    auth, client, dbfile = _fresh_password_auth(ALLOWED_EMAIL="varun@twenty20sys.com")
    client.post(
        "/api/auth/signup", json={"email": "varun@twenty20sys.com", "password": "correcthorsebattery"}
    )
    r2 = client.post(
        "/api/auth/signup", json={"email": "varun@twenty20sys.com", "password": "differentpassword"}
    )
    assert r2.status_code == 409
    os.unlink(dbfile)
    print("  OK second signup with an existing password is rejected, not overwritten")


def test_login_password_wrong_password_generic_error():
    auth, client, dbfile = _fresh_password_auth(ALLOWED_EMAIL="varun@twenty20sys.com")
    client.post(
        "/api/auth/signup", json={"email": "varun@twenty20sys.com", "password": "correcthorsebattery"}
    )
    r = client.post(
        "/api/auth/login-password", json={"email": "varun@twenty20sys.com", "password": "wrongpassword"}
    )
    assert r.status_code == 401
    assert "invalid" in r.json()["detail"].lower()
    os.unlink(dbfile)
    print("  OK wrong password returns generic 401")


def test_login_password_unknown_email_same_generic_error():
    # Same message/status as a wrong password on a real account — don't
    # let the error response reveal whether an account exists at all.
    auth, client, dbfile = _fresh_password_auth(ALLOWED_EMAIL="varun@twenty20sys.com")
    client.post(
        "/api/auth/signup", json={"email": "varun@twenty20sys.com", "password": "correcthorsebattery"}
    )
    r_unknown = client.post(
        "/api/auth/login-password", json={"email": "nosuchuser@example.com", "password": "whatever1"}
    )
    r_wrong = client.post(
        "/api/auth/login-password", json={"email": "varun@twenty20sys.com", "password": "wrongpassword"}
    )
    assert r_unknown.status_code == r_wrong.status_code == 401
    assert r_unknown.json()["detail"] == r_wrong.json()["detail"]
    os.unlink(dbfile)
    print("  OK unknown-email and wrong-password responses are indistinguishable")


def test_login_password_correct_credentials_succeed():
    auth, client, dbfile = _fresh_password_auth(ALLOWED_EMAIL="varun@twenty20sys.com")
    client.post(
        "/api/auth/signup", json={"email": "varun@twenty20sys.com", "password": "correcthorsebattery"}
    )
    client.cookies.clear()  # separate session from signup, like a real re-login
    r = client.post(
        "/api/auth/login-password", json={"email": "varun@twenty20sys.com", "password": "correcthorsebattery"}
    )
    assert r.status_code == 200
    assert r.json()["email"] == "varun@twenty20sys.com"
    os.unlink(dbfile)
    print("  OK correct email + password logs in successfully")


def test_login_password_lockout_after_threshold():
    auth, client, dbfile = _fresh_password_auth(ALLOWED_EMAIL="varun@twenty20sys.com")
    client.post(
        "/api/auth/signup", json={"email": "varun@twenty20sys.com", "password": "correcthorsebattery"}
    )

    # Exactly _LOCKOUT_THRESHOLD failed attempts are allowed through (each
    # still reported as a normal 401) — the lock is armed by the Nth
    # failure but only takes effect starting with request N+1.
    statuses = []
    for _ in range(auth._LOCKOUT_THRESHOLD):
        r = client.post(
            "/api/auth/login-password", json={"email": "varun@twenty20sys.com", "password": "wrongpassword"}
        )
        statuses.append(r.status_code)
    assert statuses == [401] * auth._LOCKOUT_THRESHOLD

    # The next attempt is locked out — even with the CORRECT password.
    r_locked = client.post(
        "/api/auth/login-password", json={"email": "varun@twenty20sys.com", "password": "correcthorsebattery"}
    )
    assert r_locked.status_code == 429
    os.unlink(dbfile)
    print("  OK lockout kicks in after repeated failures, blocks even the correct password")


def test_password_status_reflects_state():
    auth, client, dbfile = _fresh_password_auth(ALLOWED_EMAIL="varun@twenty20sys.com")
    before = client.get("/api/auth/password-status").json()
    assert before["has_password"] is False
    client.post(
        "/api/auth/signup", json={"email": "varun@twenty20sys.com", "password": "correcthorsebattery"}
    )
    after = client.get("/api/auth/password-status").json()
    assert after["has_password"] is True
    os.unlink(dbfile)
    print("  OK password-status flips true after signup")


def test_password_and_google_users_can_coexist_in_schema():
    # Regression check for the google_sub NOT NULL migration — a
    # password-only user (no google_sub) must be insertable.
    auth, client, dbfile = _fresh_password_auth(ALLOWED_EMAIL="")
    r = client.post(
        "/api/auth/signup", json={"email": "anyone@example.com", "password": "correcthorsebattery"}
    )
    assert r.status_code == 200
    os.unlink(dbfile)
    print("  OK password-only user (null google_sub) inserts without violating schema")


if __name__ == "__main__":
    tests = [
        test_allowed_email_exact_match,
        test_allowed_email_case_insensitive,
        test_disallowed_email_rejected,
        test_no_allowlist_configured_allows_anyone,
        test_is_configured_false_without_credentials,
        test_is_configured_true_with_credentials,
        test_require_auth_raises_without_session,
        test_require_auth_returns_user_with_session,
        test_all_data_endpoints_are_gated,
        test_password_hash_roundtrip,
        test_verify_password_malformed_hash_fails_closed,
        test_signup_rejects_short_password,
        test_signup_rejects_disallowed_email,
        test_signup_then_me_is_authenticated,
        test_signup_twice_rejected_second_time,
        test_login_password_wrong_password_generic_error,
        test_login_password_unknown_email_same_generic_error,
        test_login_password_correct_credentials_succeed,
        test_login_password_lockout_after_threshold,
        test_password_status_reflects_state,
        test_password_and_google_users_can_coexist_in_schema,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  FAIL {t.__name__}: {e!r}")
    print(f"\n{passed}/{len(tests)} tests passed")
