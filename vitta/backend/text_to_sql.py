"""Ask Vitta — natural-language questions answered by text-to-SQL.

Flow: the user asks a question in plain English → the LLM writes ONE
read-only SQL query against the schema below → the backend validates and
runs that query on a read-only connection → the LLM narrates the returned
rows in one sentence. The LLM never computes a total itself; SQLite does
the arithmetic and the LLM only phrases the result. This is the same
"LLM never does math" invariant the categorization tiers hold.

Security model (defense in depth — each layer alone would suffice, all
three are applied):

  1. Static validation of the generated SQL (`_validate_sql`): the string
     must be a single SELECT/WITH statement; any mutating keyword,
     multiple statements, PRAGMA/ATTACH, sqlite_* internals, or a
     reference to the `users` table (which holds password_hash) is
     refused before execution.
  2. A genuinely read-only connection (`?mode=ro` URI + PRAGMA
     query_only=ON): even if validation were bypassed, the driver itself
     rejects any write.
  3. A progress handler that aborts a runaway query after a fixed VM-step
     budget, and a hard row cap, so a pathological but "valid" SELECT
     can't hang the process or return unbounded data.

If GROQ_API_KEY is unset, the whole feature reports unavailable and the
route returns a clear "not configured" message instead of guessing.
"""

from __future__ import annotations

import json
import re
import sqlite3

from categorization import CATEGORIES
from db import DB_PATH
from llm import chat, is_available

# Tables the generated SQL may reference. `users` is deliberately absent:
# it holds password_hash and Google subject ids, and nothing a spending
# question needs is in it.
ALLOWED_TABLES = {"transactions", "accounts", "merchant_dictionary", "contacts"}

# Whole-word matches that make a query non-read-only or otherwise unsafe.
FORBIDDEN_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "replace",
    "truncate",
    "attach",
    "detach",
    "pragma",
    "vacuum",
    "reindex",
    "grant",
    "revoke",
    "commit",
    "rollback",
    "begin",
    "savepoint",
    "trigger",
}
# Substrings that must never appear (SQLite internals + file/extension I/O).
FORBIDDEN_SUBSTRINGS = ("sqlite_", "load_extension", "readfile", "writefile", "edit(")

# The `users` table holds password_hash + Google subject ids. No spending
# question ever needs the word "users", and rejecting the bare token
# outright (not just as a FROM/JOIN target) closes the subtle case where a
# CTE named `users` could shadow — or a self-referencing CTE body could
# reach — the real table. No column in the allowed tables contains this
# token, so this never produces a false positive on a legitimate query.
FORBIDDEN_TABLE_TOKENS = {"users"}

MAX_ROWS = 200
PROGRESS_STEP_BUDGET = 1_000_000  # abort a query that burns more VM steps than this

_WORD_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")
_TABLE_REF_RE = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)
# CTE names declared by `WITH name AS (...)` or `, name AS (...)`. These are
# query-local aliases, not real tables, so they're allowed as FROM targets.
_CTE_NAME_RE = re.compile(r"(?:\bwith|,)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+as\s*\(", re.IGNORECASE)


SCHEMA_DESCRIPTION = f"""You are writing SQLite SQL for a personal expense tracker. Only these tables exist:

transactions(
  id, account_id, txn_date TEXT 'YYYY-MM-DD', txn_time TEXT, amount REAL (always positive),
  direction TEXT ('debit' = money out, 'credit' = money in),
  merchant_raw, merchant_clean (display name — prefer this),
  upi_ref, vpa, remark (user's own note on the payment, e.g. 'coconut', 'rent'),
  source ('bank_pdf', 'gpay_pdf', 'manual_cash'),
  category (one of: {", ".join(c for c in CATEGORIES)}),
  is_self_transfer (1 = a transfer between the user's own accounts; exclude these from spend/income totals),
  txn_date is the column to filter/group by month with substr(txn_date,1,7)
)
accounts(id, bank_name, account_last4, account_type)
merchant_dictionary(merchant_key, category)  -- user's saved merchant->category tags
contacts(phone_last10, display_name)

Rules:
- Almost every question about spending/income should include "WHERE is_self_transfer = 0".
- "spent" / "spending" = direction='debit'. "received" / "income" = direction='credit'.
- Amounts are rupees. Use ROUND(SUM(amount), 2) for money.
- Group months with substr(txn_date, 1, 7).
- Return a small result — aggregate rather than dumping raw rows when the question is a total/count/ranking.
"""


def is_configured() -> bool:
    return is_available()


def _validate_sql(sql: str) -> tuple[bool, str]:
    """Return (ok, reason). Refuses anything that isn't a single, plainly
    read-only SELECT/WITH over the allowed tables."""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        return False, "empty query"

    # Single statement only — no stacking a write after a SELECT.
    if ";" in cleaned:
        return False, "multiple statements are not allowed"

    lowered = cleaned.lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        return False, "only SELECT queries are allowed"

    for bad in FORBIDDEN_SUBSTRINGS:
        if bad in lowered:
            return False, f"disallowed token: {bad!r}"

    words = set(_WORD_RE.findall(lowered))
    hit = words & FORBIDDEN_KEYWORDS
    if hit:
        return False, f"disallowed keyword: {sorted(hit)[0]!r}"

    forbidden_tbl = words & FORBIDDEN_TABLE_TOKENS
    if forbidden_tbl:
        return False, f"query references a protected table: {sorted(forbidden_tbl)[0]!r}"

    # Every table referenced after FROM/JOIN must be a base table in the
    # allowlist or a CTE name declared in this same query.
    cte_names = {n.lower() for n in _CTE_NAME_RE.findall(lowered)}
    allowed = ALLOWED_TABLES | cte_names
    for tbl in _TABLE_REF_RE.findall(lowered):
        if tbl not in allowed:
            return False, f"query references a table that isn't allowed: {tbl!r}"

    return True, ""


def _run_readonly(sql: str) -> list[dict]:
    """Execute a pre-validated SELECT on a read-only connection with a
    runaway-query guard and a row cap."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON")

        steps = {"n": 0}

        def _guard():
            steps["n"] += 1
            # Returning non-zero from the progress handler aborts the query.
            return 1 if steps["n"] > (PROGRESS_STEP_BUDGET // 1000) else 0

        # Handler fires every ~1000 VM steps; budget above is in raw steps.
        conn.set_progress_handler(_guard, 1000)
        cur = conn.execute(sql)
        rows = cur.fetchmany(MAX_ROWS)
        return [dict(r) for r in rows]
    finally:
        conn.set_progress_handler(None, 1000)
        conn.close()


def _generate_sql(question: str) -> str | None:
    content = chat(
        [
            {"role": "system", "content": SCHEMA_DESCRIPTION},
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n\n"
                    "Reply with ONLY the SQL query — a single SELECT statement, "
                    "no explanation, no markdown fences, no trailing semicolon."
                ),
            },
        ],
        temperature=0,
        max_tokens=400,
    )
    if not content:
        return None
    # Strip markdown fences the model sometimes adds despite instructions.
    content = content.strip()
    content = re.sub(r"^```(?:sql)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    return content.strip()


def _is_empty_result(rows: list[dict]) -> bool:
    """A count/sum question that matched nothing comes back not as an empty
    list but as a single row whose every value is NULL (SUM over zero rows
    is NULL, COUNT is 0). Treat that as 'nothing found' so the answer reads
    like ₹0 / no transactions instead of the literal 'null'."""
    if not rows:
        return True
    if len(rows) == 1:
        vals = list(rows[0].values())
        if all(v is None or v == 0 for v in vals):
            return True
    return False


def _narrate(question: str, rows: list[dict]) -> str:
    """Turn the query result into one plain-English sentence. The model
    only ever sees already-computed rows — it phrases, it does not calculate."""
    if _is_empty_result(rows):
        return "I couldn't find any transactions matching that — the total there is ₹0."

    result_json = json.dumps(rows[:50], ensure_ascii=False, default=str)
    narration = chat(
        [
            {
                "role": "system",
                "content": (
                    "You answer a personal-finance question from an already-computed "
                    "SQL result. State the numbers from the result exactly as given — "
                    "never invent or recompute a figure. Amounts are Indian rupees; "
                    "write them like ₹1,234. Answer in 1-2 short sentences of plain "
                    "text — no markdown, no bold, no asterisks."
                ),
            },
            {"role": "user", "content": f"Question: {question}\nResult rows (JSON): {result_json}"},
        ],
        temperature=0.2,
        max_tokens=300,
    )
    if narration:
        # Strip any markdown emphasis the model adds despite instructions —
        # the chat UI renders plain text, so **x** would show literally.
        return re.sub(r"\*{1,2}", "", narration).strip()

    # LLM narration failed but we still have real rows — show them plainly
    # rather than erroring.
    if len(rows) == 1 and len(rows[0]) == 1:
        val = next(iter(rows[0].values()))
        if isinstance(val, (int, float)):
            return f"₹{val:,.0f}"
        return str(val)
    return f"Found {len(rows)} result row(s)."


def answer_question(question: str) -> dict:
    """Full Ask Vitta flow. Returns a dict the route serializes directly:
    {answer, sql, rows, error}. `error` is set (and answer is a friendly
    message) whenever the question can't be safely answered."""
    question = (question or "").strip()
    if not question:
        return {"answer": "Ask me something about your spending.", "sql": None, "rows": [], "error": "empty"}
    if not is_configured():
        return {
            "answer": "Ask Vitta needs an LLM key to work — set GROQ_API_KEY in backend/.env and restart.",
            "sql": None,
            "rows": [],
            "error": "not_configured",
        }

    sql = _generate_sql(question)
    if not sql:
        return {
            "answer": "I couldn't turn that into a query — try rephrasing it.",
            "sql": None,
            "rows": [],
            "error": "generation_failed",
        }

    ok, reason = _validate_sql(sql)
    if not ok:
        return {
            "answer": "I can only answer read-only questions about your own transactions, and that one didn't qualify. Try asking about your spending, categories, or merchants.",
            "sql": sql,
            "rows": [],
            "error": f"unsafe_sql: {reason}",
        }

    try:
        rows = _run_readonly(sql)
    except Exception as e:
        return {
            "answer": "That query didn't run cleanly — try asking a simpler question.",
            "sql": sql,
            "rows": [],
            "error": f"execution_failed: {e}",
        }

    return {"answer": _narrate(question, rows), "sql": sql, "rows": rows, "error": None}
