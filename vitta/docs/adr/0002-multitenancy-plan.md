# 0002 — Multi-tenancy migration plan

Date: 2026-09-05
Status: Proposed (Phase 1 — not yet implemented)

## Context

Every data table (`accounts`, `transactions`, `merchant_dictionary`,
`contacts`) has no `user_id` column. The only access control is
`ALLOWED_EMAIL` in `.env` — a lock on the front door for one person, not
tenant isolation. This is fine for personal use; it is disqualifying for
a SaaS product with more than one user.

## Decision (planned)

1. Migration adds `user_id INTEGER NOT NULL REFERENCES users(id)` to
   every data table, backfilled to the current single user, plus a
   composite index `(user_id, txn_date DESC)` on `transactions`.
2. Every query in `routes/*.py` is updated to filter by the authenticated
   user's id — no endpoint may read or write a row it didn't scope by
   `user_id`.
3. A new integration test suite proves isolation directly: seed two
   users, assert every endpoint returns disjoint data for each. This is
   the acceptance gate for Phase 1, not a nice-to-have.
4. SQLite stays for local dev; Postgres becomes the default for
   staging/prod once this migration lands (SQLite's single-writer model
   is fine for one user, not for concurrent tenants).

## Consequences (expected)

- Every existing endpoint's SQL changes (adds a `WHERE user_id = ?`
  clause or equivalent join condition).
- `ALLOWED_EMAIL` gate is retired in favor of open signup (Phase 2 also
  covers password reset / email verification, done at the same time
  since both touch `auth.py`).
- This is the highest-risk migration in the whole roadmap — it touches
  every table and every query — so it ships behind its own test suite
  and is reviewed as a single, focused PR rather than folded into
  feature work.
