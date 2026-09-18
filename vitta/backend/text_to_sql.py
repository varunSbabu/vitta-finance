"""Ask Vitta — natural-language questions answered by text-to-SQL.

Flow: the user asks a question in plain English → the LLM writes ONE
read-only SQL query against the schema below → the backend validates and
runs that query on a read-only connection → the LLM narrates the returned
rows in one sentence. The LLM never computes a total itself; SQLite does
the arithmetic and the LLM only phrases the result. This is the same
"LLM never does math" invariant the categorization tiers hold.

Multi-tenancy: the LLM is told to always filter by `user_id = :uid`.
Validation rejects any query that doesn't contain this filter. At
execution time, `:uid` is bound to the authenticated user's id — the LLM
never sees the actual value and can't forge a different one.

Security model (defense in depth — each layer alone would suffice, all
are applied):

  1. Static validation of the generated SQL (`_validate_sql`): the string
     must be a single SELECT/WITH statement; any mutating keyword,
     multiple statements, PRAGMA/ATTACH, sqlite_* internals, or a
     reference to the `users` table (which holds password_hash) is
     refused before execution.
  2. User-id scoping: the query must contain `:uid` and the actual value
     is bound by the backend, not interpolated by the LLM.
  3. A genuinely read-only connection (`?mode=ro` URI + PRAGMA
     query_only=ON): even if validation were bypassed, the driver itself
     rejects any write.
  4. A progress handler that aborts a runaway query after a fixed VM-step
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

ALLOWED_TABLES = {
    "transactions",
    "accounts",
    "merchant_dictionary",
    "contacts",
    "income_sources",
    "obligations",
    "budget_plans",
    "savings_goals",
    "debts",
}

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
FORBIDDEN_SUBSTRINGS = ("sqlite_", "load_extension", "readfile", "writefile", "edit(")

FORBIDDEN_TABLE_TOKENS = {"users"}

MAX_ROWS = 200
PROGRESS_STEP_BUDGET = 1_000_000

_WORD_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")
_TABLE_REF_RE = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)
_CTE_NAME_RE = re.compile(r"(?:\bwith|,)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+as\s*\(", re.IGNORECASE)


SCHEMA_DESCRIPTION = f"""You are writing SQLite SQL for a multi-tenant personal expense tracker. Only these tables exist:

transactions(
  id, user_id INTEGER, account_id, txn_date TEXT 'YYYY-MM-DD', txn_time TEXT, amount REAL (always positive),
  direction TEXT ('debit' = money out, 'credit' = money in),
  merchant_raw, merchant_clean (display name — prefer this),
  upi_ref, vpa, remark (user's own note on the payment, e.g. 'coconut', 'rent'),
  source ('bank_pdf', 'gpay_pdf', 'manual_cash'),
  category (one of: {", ".join(c for c in CATEGORIES)}),
  is_self_transfer (1 = a transfer between the user's own accounts; exclude these from spend/income totals),
  txn_date is the column to filter/group by month with substr(txn_date,1,7)
)
accounts(id, user_id INTEGER, bank_name, account_last4, account_type)
merchant_dictionary(user_id INTEGER, merchant_key, category)  -- user's saved merchant->category tags
contacts(user_id INTEGER, phone_last10, display_name)

Rules:
- CRITICAL: Every table you query MUST be filtered by `user_id = :uid`. Use `:uid` as the parameter — never a literal number.
- Almost every question about spending/income should include "WHERE is_self_transfer = 0".
- "spent" / "spending" = direction='debit'. "received" / "income" = direction='credit'.
- Amounts are rupees. Use ROUND(SUM(amount), 2) for money.
- Group months with substr(txn_date, 1, 7).
- Return a small result — aggregate rather than dumping raw rows when the question is a total/count/ranking.
"""

VITTA_SYSTEM_PROMPT = f"""You are Vitta, a friendly and smart personal finance assistant for Indian users.
You have access to the user's real transaction database and can query it to answer questions.

When the user asks a FACTUAL question that requires looking up data (totals, counts, lists, comparisons, specific transactions), respond with ONLY a SQL query prefixed by "SQL:" on the first line, like:
SQL: SELECT ...

When the user asks for ADVICE, tips, explanations, opinions, or anything conversational that cannot be answered by a single SQL query, respond with a helpful answer prefixed by "ANSWER:" on the first line. Use the financial context provided to give specific, personalized advice — reference their real categories, merchants, and amounts. Keep advice to 3-5 sentences. Use ₹ for Indian rupee amounts.

DATABASE SCHEMA:
{SCHEMA_DESCRIPTION}

IMPORTANT:
- For SQL responses: write ONLY the SQL query after "SQL:", no explanation. Single SELECT statement only.
- For ANSWER responses: write plain text, no markdown, no bold, no asterisks. Be warm, specific, and actionable.
- When unsure if data is needed, prefer to query the data first and then advise.
- You remember the conversation history — refer back to previous questions and answers naturally.
"""


def is_configured() -> bool:
    return is_available()


def _validate_sql(sql: str) -> tuple[bool, str]:
    """Return (ok, reason). Refuses anything that isn't a single, plainly
    read-only SELECT/WITH over the allowed tables, with user_id scoping."""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        return False, "empty query"

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

    cte_names = {n.lower() for n in _CTE_NAME_RE.findall(lowered)}
    allowed = ALLOWED_TABLES | cte_names
    for tbl in _TABLE_REF_RE.findall(lowered):
        if tbl not in allowed:
            return False, f"query references a table that isn't allowed: {tbl!r}"

    if ":uid" not in lowered:
        return False, "query must filter by user_id = :uid"

    return True, ""


def _run_readonly(sql: str, user_id: int) -> list[dict]:
    """Execute a pre-validated SELECT on a read-only connection with a
    runaway-query guard and a row cap. Binds :uid to the authenticated user."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON")

        steps = {"n": 0}

        def _guard():
            steps["n"] += 1
            return 1 if steps["n"] > (PROGRESS_STEP_BUDGET // 1000) else 0

        conn.set_progress_handler(_guard, 1000)
        cur = conn.execute(sql, {"uid": user_id})
        rows = cur.fetchmany(MAX_ROWS)
        return [dict(r) for r in rows]
    finally:
        conn.set_progress_handler(None, 1000)
        conn.close()


def _generate_response(question: str, history: list[dict] | None, context: str) -> tuple[str, str | None]:
    """Ask the LLM to either produce SQL or a direct answer.
    Returns (type, content) where type is 'sql' or 'answer'."""
    system = VITTA_SYSTEM_PROMPT
    if context:
        system += f"\n\nUSER'S CURRENT FINANCIAL CONTEXT:\n{context}"

    messages = [{"role": "system", "content": system}]
    if history:
        for h in history[-10:]:
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": question})

    content = chat(messages, temperature=0.2, max_tokens=800)
    if not content:
        return ("answer", None)

    content = content.strip()
    content = re.sub(r"^```(?:sql)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)

    if content.upper().startswith("SQL:"):
        sql = content[4:].strip().rstrip(";").strip()
        sql = re.sub(r"^```(?:sql)?\s*", "", sql)
        sql = re.sub(r"\s*```$", "", sql)
        return ("sql", sql)
    if content.upper().startswith("ANSWER:"):
        return ("answer", content[7:].strip())
    if re.match(r"(?i)^(SELECT|WITH)\b", content):
        return ("sql", content.rstrip(";").strip())
    return ("answer", content)


def _is_empty_result(rows: list[dict]) -> bool:
    if not rows:
        return True
    if len(rows) == 1:
        vals = list(rows[0].values())
        if all(v is None or v == 0 for v in vals):
            return True
    return False


def _narrate(question: str, rows: list[dict]) -> str:
    """Turn the query result into one plain-English sentence."""
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
        return re.sub(r"\*{1,2}", "", narration).strip()

    if len(rows) == 1 and len(rows[0]) == 1:
        val = next(iter(rows[0].values()))
        if isinstance(val, (int, float)):
            return f"₹{val:,.0f}"
        return str(val)
    return f"Found {len(rows)} result row(s)."


def _fetch_spending_context(user_id: int) -> str:
    """Fetch a summary of the user's spending to give the LLM context."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON")

        monthly = conn.execute(
            "SELECT substr(txn_date,1,7) AS month, "
            "ROUND(SUM(CASE WHEN direction='debit' AND is_self_transfer=0 THEN amount ELSE 0 END),0) AS spent, "
            "ROUND(SUM(CASE WHEN direction='credit' AND is_self_transfer=0 THEN amount ELSE 0 END),0) AS income "
            "FROM transactions WHERE user_id = ? "
            "GROUP BY month ORDER BY month DESC LIMIT 3",
            (user_id,),
        ).fetchall()

        by_category = conn.execute(
            "SELECT category, ROUND(SUM(amount),0) AS total, COUNT(*) AS n "
            "FROM transactions "
            "WHERE user_id = ? AND direction='debit' AND is_self_transfer=0 "
            "AND substr(txn_date,1,7) = substr(date('now'),1,7) "
            "GROUP BY category ORDER BY total DESC LIMIT 10",
            (user_id,),
        ).fetchall()

        top_merchants = conn.execute(
            "SELECT merchant_clean, ROUND(SUM(amount),0) AS total, COUNT(*) AS n "
            "FROM transactions "
            "WHERE user_id = ? AND direction='debit' AND is_self_transfer=0 "
            "AND substr(txn_date,1,7) = substr(date('now'),1,7) "
            "GROUP BY merchant_clean ORDER BY total DESC LIMIT 10",
            (user_id,),
        ).fetchall()

        parts = []
        if monthly:
            parts.append("Monthly summary (recent):")
            for r in monthly:
                parts.append(f"  {r['month']}: spent ₹{r['spent']:,.0f}, income ₹{r['income']:,.0f}")

        if by_category:
            parts.append("\nThis month's spending by category:")
            for r in by_category:
                parts.append(f"  {r['category'] or 'Uncategorized'}: ₹{r['total']:,.0f} ({r['n']} txns)")

        if top_merchants:
            parts.append("\nThis month's top merchants:")
            for r in top_merchants:
                parts.append(f"  {r['merchant_clean'] or 'Unknown'}: ₹{r['total']:,.0f} ({r['n']} txns)")

        return "\n".join(parts) if parts else ""
    finally:
        conn.close()


def answer_question(question: str, user_id: int, history: list[dict] | None = None) -> dict:
    """Full Ask Vitta flow — single-pass LLM decides whether to write SQL or
    give a direct answer. Returns {answer, sql, rows, error}."""
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

    context = _fetch_spending_context(user_id)
    resp_type, content = _generate_response(question, history, context)

    if resp_type == "answer":
        if not content:
            return {
                "answer": "I'm having trouble right now — try again in a moment.",
                "sql": None,
                "rows": [],
                "error": "llm_failed",
            }
        return {"answer": content, "sql": None, "rows": [], "error": None}

    sql = content
    if not sql:
        return {
            "answer": "I couldn't figure that out — try rephrasing your question.",
            "sql": None,
            "rows": [],
            "error": "generation_failed",
        }

    ok, reason = _validate_sql(sql)
    if not ok:
        return {
            "answer": "I can only run read-only queries on your own transactions. Try asking differently.",
            "sql": sql,
            "rows": [],
            "error": f"unsafe_sql: {reason}",
        }

    try:
        rows = _run_readonly(sql, user_id)
    except Exception as e:
        return {
            "answer": "That query didn't run cleanly — try asking a simpler question.",
            "sql": sql,
            "rows": [],
            "error": f"execution_failed: {e}",
        }

    return {"answer": _narrate(question, rows), "sql": sql, "rows": rows, "error": None}
