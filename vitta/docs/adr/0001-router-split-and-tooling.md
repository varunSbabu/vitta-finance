# 0001 — Split main.py into routers; adopt pyproject/ruff/mypy/pytest

Date: 2026-09-05
Status: Accepted

## Context

`backend/main.py` had grown to ~650 lines covering ten unrelated
endpoints (ingest, transactions, accounts, summary, merchants, contacts,
transfers, reset). Dependencies (`fastapi`, `pdfplumber`, etc.) were
tracked in a bare `requirements.txt` with no pinned dev tooling, no
lint/type-check config, and the test suite (`test_*.py`) was designed to
run one file per process (`python3 test_x.py`), not under a single
`pytest` session.

This is Phase 0 of the SDLC hardening plan: a clean foundation before any
new feature work (multi-tenancy, PhonePe/CC parsers, real insights).

## Decision

- Split `main.py` into `routes/{ingest,accounts,transactions,summary,
  merchants,contacts,transfers,system}.py` — one FastAPI router per
  resource, same endpoints, same behavior. `main.py` now only wires
  middleware and includes routers (82 lines).
- Added `/api/health` (unauthenticated, DB-independent) for Docker
  healthchecks and uptime monitoring — the only new endpoint in this
  change.
- Adopted `pyproject.toml` as the single source of dependency + tool
  config (ruff, mypy, pytest), with `requirements-lock.txt` (pip freeze
  from a project-local `.venv`) as the reproducible install list.
- Fixed a real test-isolation bug: `test_contacts.py` and
  `test_self_transfer.py` mutated the shared `db.DB_PATH` global at
  **import time**. Under `pytest`, all test files are collected (imported)
  before any test function runs, so whichever file imports last during
  collection silently won every other file's database out from under it.
  Fixed with an autouse pytest fixture that re-asserts the scratch DB path
  immediately before each test function, instead of relying on import
  order.

## Consequences

- `pytest` now runs the full suite (82 tests) in one process, green, and
  is the CI gate (Phase 0 exit criteria).
- `ruff check .` is clean. A handful of pre-existing style issues (E402
  for intentional import-after-setup in two test files and `main.py`,
  a few semicolon-joined statements, one ambiguous `l` variable) were
  either fixed or given a documented `# ruff: noqa` with the reason.
- `mypy .` still reports 18 pre-existing type errors, concentrated in
  `parsers/bank_statement.py` (an 800-line, previously untyped PDF
  parser — several `Optional[float]` values flow into fields typed
  `float`, which is worth a real look but not a safe blind edit under
  Phase 0 time pressure) and `self_transfer.py`. mypy is wired into CI as
  **advisory** (reported, not blocking) until this backlog is paid down
  — tracked as follow-up, not silently ignored.
- `docs/adr/` established as the place for decisions like this one, so
  the "why" behind cross-cutting changes survives past the PR that made
  them.
