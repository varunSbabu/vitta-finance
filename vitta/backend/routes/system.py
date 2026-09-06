"""Root info endpoint, health check, and the dev-only full data reset."""

from __future__ import annotations

from fastapi import APIRouter, Depends

import auth
from auth import require_auth
from db import get_conn
from llm_categorize import is_available as llm_available

router = APIRouter(tags=["system"])


@router.get("/")
def root():
    return {
        "name": "Vitta API",
        "version": "0.5.0",
        "docs": "/docs",
        # Lets the frontend tell "backend down" apart from "OAuth not set up
        # yet" and show the right message instead of navigating to a raw error.
        "auth_configured": auth.is_configured(),
        "llm_configured": llm_available(),
    }


@router.get("/api/health")
def health():
    """Liveness/readiness check for local dev, Docker healthchecks, and
    uptime monitoring — deliberately unauthenticated and DB-independent so
    it reflects whether the process itself is up, not whether the database
    happens to be reachable."""
    return {"status": "ok"}


@router.post("/api/reset")
def api_reset(_user: dict = Depends(require_auth)):
    conn = get_conn()
    conn.execute("DELETE FROM transactions")
    conn.execute("DELETE FROM accounts")
    conn.execute("DELETE FROM merchant_dictionary")
    conn.commit()
    conn.close()
    return {"ok": True}
