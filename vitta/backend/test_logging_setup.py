"""Tests for the request-ID middleware + sanitizer.

Structural checks, not log-content checks — asserting on rendered log
output is brittle (color codes, timestamps, structlog config drift) and
buys little. What matters is that:

  1. An inbound X-Request-ID header round-trips back on the response.
  2. Missing inbound -> a fresh id is generated and echoed.
  3. A malicious inbound is sanitized before it can pollute a log line.
  4. current_request_id() returns the same id inside a handler.
"""

from __future__ import annotations

import importlib
import os
import pathlib
import tempfile

import pytest


@pytest.fixture
def app_with_logging():
    """Reload db + main against a scratch DB so this doesn't touch the
    real vitta.db, matching the pattern used by test_manual_cash.py."""
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()

    import db

    db.DB_PATH = pathlib.Path(tmp_db.name)
    db.init_db()

    os.environ["SESSION_SECRET_KEY"] = "test-only-key-for-logging"
    os.environ.setdefault("ALLOWED_EMAIL", "")
    import auth

    importlib.reload(auth)
    import main

    importlib.reload(main)

    from fastapi.testclient import TestClient

    return main, TestClient(main.app), tmp_db.name


def test_request_id_generated_when_absent(app_with_logging):
    _main, client, _dbfile = app_with_logging
    r = client.get("/api/health")
    assert r.status_code == 200
    rid = r.headers.get("X-Request-ID")
    assert rid and len(rid) >= 8 and all(c in "0123456789abcdef" for c in rid)


def test_request_id_round_trips_inbound(app_with_logging):
    _main, client, _dbfile = app_with_logging
    r = client.get("/api/health", headers={"X-Request-ID": "corr-abc-123"})
    assert r.status_code == 200
    assert r.headers.get("X-Request-ID") == "corr-abc-123"


def test_request_id_sanitizes_malicious_inbound(app_with_logging):
    _main, client, _dbfile = app_with_logging
    # Attempt to inject a newline + long control-char blob. Sanitizer
    # should strip everything that isn't alnum/-/_ and cap at 64 chars.
    hostile = "abc\n\rDELETE FROM users;\x00" + ("x" * 200)
    r = client.get("/api/health", headers={"X-Request-ID": hostile})
    returned = r.headers.get("X-Request-ID")
    assert returned is not None
    assert len(returned) <= 64
    assert "\n" not in returned
    assert "\r" not in returned
    assert "\x00" not in returned
    assert " " not in returned


def test_current_request_id_available_inside_handler(app_with_logging):
    main, client, _dbfile = app_with_logging
    from logging_setup import current_request_id

    captured: dict[str, str | None] = {}

    @main.app.get("/api/_test/rid")
    def _rid():
        captured["rid"] = current_request_id()
        return {"ok": True}

    r = client.get("/api/_test/rid", headers={"X-Request-ID": "known-id-xyz"})
    assert r.status_code == 200
    assert captured["rid"] == "known-id-xyz"
