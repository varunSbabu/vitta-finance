"""Shared low-level Groq chat client.

Both the insights narrator (insights.py) and the text-to-SQL layer
(text_to_sql.py) need a plain "send messages, get a string back" call.
That lives here so there's one place that knows the endpoint, the model,
the auth header, and the timeout — llm_categorize.py predates this and
keeps its own specialized batched caller on purpose (it's load-bearing
and well-tested; not worth the churn of rewiring).

Every call fails soft: any error (no key, network, rate limit, malformed
response) returns None, and every caller must treat None as "LLM
unavailable" and fall back to a non-LLM path. Nothing here ever raises.
"""

from __future__ import annotations

import os

import requests

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"
REQUEST_TIMEOUT_S = 30


def is_available() -> bool:
    return bool(os.environ.get("GROQ_API_KEY"))


def chat(
    messages: list[dict],
    *,
    temperature: float = 0.0,
    max_tokens: int = 1500,
    model: str | None = None,
) -> str | None:
    """Send chat messages to Groq, return the assistant's text content.
    Returns None on any failure — callers fall back rather than surfacing
    an error, so the feature degrades instead of breaking."""
    if not is_available():
        return None
    try:
        resp = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {os.environ['GROQ_API_KEY']}",
                "Content-Type": "application/json",
            },
            json={
                "model": model or GROQ_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=REQUEST_TIMEOUT_S,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return content if isinstance(content, str) else None
    except Exception:
        return None
