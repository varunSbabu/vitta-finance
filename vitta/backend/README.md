# Vitta backend

FastAPI + SQLite. Serves the `app.html` SPA (not the `src/` React app —
that was a separate experiment and is unused).

Endpoints live in `routes/*.py`, one module per resource — `main.py` only
wires middleware and includes routers. See
`docs/adr/0001-router-split-and-tooling.md` for why.

## Setup

Dependencies, dev tooling, and lint/type/test config all live in
`pyproject.toml` — no bare `requirements.txt` anymore. Everything installs
into a project-local virtualenv, never system/global Python:

```bash
cd vitta                                    # repo root for this project
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-lock.txt
cd backend
cp .env.example .env      # then fill it in — see below
../.venv/bin/uvicorn main:app --reload --port 8001
```

`requirements-lock.txt` is a pinned, reproducible install list generated
via `pip freeze` from that same venv — regenerate it after changing
`pyproject.toml`'s `dependencies`:

```bash
.venv/bin/pip install -e ".[dev]" --no-deps -q  # or just re-pip-install the new dep
.venv/bin/pip freeze > backend/requirements-lock.txt
```

Frontend, in a second terminal:

```bash
python3 serve.py          # http://localhost:5757
```

Open **http://localhost:5757** — not `127.0.0.1`. See the SameSite note below.

## .env

| Key | Needed for | Notes |
|---|---|---|
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Sign-in | From Google Cloud Console, below |
| `SESSION_SECRET_KEY` | Sign-in | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `ALLOWED_EMAIL` | Sign-in | Only this Google account may sign in |
| `FRONTEND_URL` | Sign-in | Where to land after OAuth |
| `ALLOWED_ORIGINS` | CORS | Comma-separated |
| `GROQ_API_KEY` | Tier 3 categorization | Optional — free key at console.groq.com/keys |

`uvicorn --reload` only watches `*.py`, **not `.env`** — restart the server
by hand after editing it.

## Google OAuth setup

1. [console.cloud.google.com](https://console.cloud.google.com) → new project.
2. **APIs & Services → OAuth consent screen** → External, app name "Vitta",
   your email. "Testing" mode is fine for personal use — no Google review needed.
3. **Credentials → Create Credentials → OAuth client ID** → Web application.
   Authorized redirect URI: `http://localhost:8001/api/auth/callback`
4. Copy the client ID and secret into `.env`, restart the backend.

## localhost vs 127.0.0.1

The session cookie is `SameSite=Lax`, which browsers withhold from
cross-site *subresource* requests (i.e. `fetch`). SameSite compares
scheme + host and **ignores the port**, so:

- frontend `localhost:5757` → API `localhost:8001` = same-site, cookie sent ✅
- frontend `localhost:5757` → API `127.0.0.1:8001` = cross-site, cookie dropped ❌

Both must use the same spelling. `app.html` hardcodes `localhost:8001`
for this reason — don't "fix" it to `127.0.0.1`.

## Auth model

Single-account gate, not multi-tenancy. There is one set of financial data
in `vitta.db` and it belongs to one person; `ALLOWED_EMAIL` is a lock on the
front door. Anyone else who completes Google's flow gets a 403, not an
account. Every `/api/*` route except `/api/auth/*` requires a session
(`Depends(require_auth)`), enforced by a test that walks the live FastAPI
route graph so a new endpoint can't ship ungated.

## Categorization tiers

Applied in order inside `POST /api/parse`:

1. **Rules** (`categorization.py`) — merchant + payment-remark keywords.
2. **User dictionary** — anything tagged before, matched on `merchant_raw`.
3. **LLM** (`llm_categorize.py`) — one batched Groq call for whatever's left,
   restricted to the fixed `CATEGORIES` list, applied only above a 0.6
   confidence threshold. Skipped entirely without `GROQ_API_KEY`.

Contacts (`contacts.py`) are orthogonal: they resolve a VPA's embedded phone
number to a real name, so `9876543210@ybl` shows as "Amma" rather than a
bank-registered name blob.

## Tests, lint, types

```bash
../.venv/bin/pytest              # 82 tests, one process, one pytest session
../.venv/bin/ruff check .        # lint — must be clean
../.venv/bin/ruff format --check .
../.venv/bin/mypy .              # advisory only for now — see the ADR
```

Also runs automatically via `pre-commit` (repo root `.pre-commit-config.yaml`):
formatting, ruff, and `detect-secrets` block a commit; mypy runs manually only
(`pre-commit run mypy --hook-stage manual --all-files`).
