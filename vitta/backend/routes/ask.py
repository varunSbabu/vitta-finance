"""Ask Vitta — natural-language questions over the user's transactions,
answered via safe read-only text-to-SQL. See text_to_sql.py for the
generation, validation, and execution guards; this is just the HTTP
surface."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from auth import require_auth
from text_to_sql import answer_question, is_configured

router = APIRouter(tags=["ask"])


@router.post("/api/ask")
def api_ask(payload: dict = Body(...), _user: dict = Depends(require_auth)):
    question = (payload.get("question") or "").strip()
    result = answer_question(question)
    # `sql` and `rows` are returned so the UI can optionally show its work;
    # `error` is a machine-readable tag (None on success), `answer` is always
    # a user-facing string.
    return {
        "question": question,
        "answer": result["answer"],
        "sql": result["sql"],
        "rows": result["rows"],
        "error": result["error"],
        "llm_configured": is_configured(),
    }
