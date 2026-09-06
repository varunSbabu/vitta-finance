"""Vitta backend — FastAPI + SQLite.

This module owns app-level wiring only (session/CORS middleware, router
mounting, startup). Endpoints live in routes/*.py, one module per
resource — see each module's docstring for its endpoints.

All endpoints except /api/auth/* and /api/health require a signed-in
session — see auth.py. This is a personal-use app: sign-in is gated to
one Google account (ALLOWED_EMAIL in .env), not general multi-user access
control — see docs/adr/0002-multitenancy-plan.md for the planned change.

Run: uvicorn main:app --reload --host 0.0.0.0 --port 8001
"""

# ruff: noqa: E402 — load_dotenv() must run before importing auth/routes,
# since several of them read env vars (GOOGLE_CLIENT_ID, GROQ_API_KEY...)
# at import time, not lazily inside a function.
from __future__ import annotations

import os
import secrets

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

import auth
from db import init_db
from routes import accounts, contacts, ingest, merchants, summary, system, transactions, transfers

app = FastAPI(title="Vitta API", version="0.5.0")

SESSION_SECRET_KEY = os.environ.get("SESSION_SECRET_KEY")
if not SESSION_SECRET_KEY:
    SESSION_SECRET_KEY = secrets.token_hex(32)
    print(
        "WARNING: SESSION_SECRET_KEY not set in .env — using a random key "
        "for this process only. Every restart will invalidate existing "
        "sessions. Set SESSION_SECRET_KEY in backend/.env for real use."
    )

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY,
    same_site="lax",
    https_only=False,  # set True once served over HTTPS
)

# app.html is served by serve.py on :5757. Note the frontend MUST be opened
# as http://localhost:5757 (not 127.0.0.1) and must call the API as
# http://localhost:8001 — see the SameSite note in auth.py. Both spellings
# are allowed here so a mistake surfaces as an auth failure rather than an
# opaque CORS error.
DEFAULT_ORIGINS = "http://localhost:5757,http://127.0.0.1:5757,http://localhost:5173"
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", DEFAULT_ORIGINS).split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    # Wildcard origins are incompatible with credentialed (cookie-based)
    # requests — browsers refuse it. Session auth requires explicit origins.
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(ingest.router)
app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(summary.router)
app.include_router(merchants.router)
app.include_router(contacts.router)
app.include_router(transfers.router)
app.include_router(system.router)


@app.on_event("startup")
def startup():
    init_db()
