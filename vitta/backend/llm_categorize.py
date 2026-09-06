"""Tier 3 categorization — LLM fallback for transactions that Tier 1 rules
and Tier 2 (user dictionary / contacts) can't resolve.

The model only ever picks a label from the fixed CATEGORIES list — it
never computes totals or does arithmetic of any kind. All transactions
in one statement upload are batched into a single prompt (chunked at
MAX_ITEMS_PER_CALL) to keep this to one API call per import instead of
one per transaction.

Requires GROQ_API_KEY in the environment. If it's unset, or the call
fails for any reason (network, rate limit, bad response), this tier is
skipped entirely and transactions stay 'Uncategorized' for the user to
tag manually — that manual tag then becomes a Tier 2 dictionary entry,
so the LLM is never asked about that merchant again.
"""

from __future__ import annotations

import json
import os
import re

import requests

from categorization import CATEGORIES

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
# Groq's Llama 3.1 lineup was retired; gpt-oss-20b is the current
# fast/cheap tier and follows the strict-JSON-only instruction reliably.
GROQ_MODEL = "openai/gpt-oss-20b"
CONFIDENCE_THRESHOLD = 0.6
MAX_ITEMS_PER_CALL = 40
REQUEST_TIMEOUT_S = 20


def is_available() -> bool:
    return bool(os.environ.get("GROQ_API_KEY"))


def _build_prompt(items: list[dict]) -> str:
    cats = ", ".join(c for c in CATEGORIES if c != "Uncategorized")
    lines = []
    for i, it in enumerate(items):
        parts = [f'merchant="{it.get("merchant", "")}"']
        if it.get("remark"):
            parts.append(f'remark="{it["remark"]}"')
        if it.get("txn_type"):
            parts.append(f"type={it['txn_type']}")
        parts.append(f"amount={it.get('amount', 0)}")
        lines.append(f"{i}: " + ", ".join(parts))
    items_block = "\n".join(lines)

    return f"""You are categorizing personal expense transactions for an Indian user.
Pick exactly one category from this list for each transaction: {cats}

Use "Transfers" for plain person-to-person UPI payments with no business
signal. If genuinely unclear, return confidence below 0.5 rather than guessing.

Transactions:
{items_block}

Respond with ONLY a JSON array, one object per transaction in the same order:
[{{"category": "...", "confidence": 0.0}}, ...]
No other text, no markdown fences."""


def categorize_batch(items: list[dict]) -> list[tuple[str, float]]:
    """items: list of {merchant, remark, txn_type, amount}.
    Returns list of (category, confidence) in the same order, one per item.
    Falls back to ('Uncategorized', 0.0) for every item on any failure."""
    if not items:
        return []
    if not is_available():
        return [("Uncategorized", 0.0) for _ in items]

    results: list[tuple[str, float]] = []
    for start in range(0, len(items), MAX_ITEMS_PER_CALL):
        chunk = items[start : start + MAX_ITEMS_PER_CALL]
        results.extend(_call_groq(chunk))
    return results


def _call_groq(chunk: list[dict]) -> list[tuple[str, float]]:
    fallback = [("Uncategorized", 0.0) for _ in chunk]
    try:
        resp = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {os.environ['GROQ_API_KEY']}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": _build_prompt(chunk)}],
                "temperature": 0,
                "max_tokens": 4000,
            },
            timeout=REQUEST_TIMEOUT_S,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = _extract_json_array(content)
    except Exception:
        return fallback

    out: list[tuple[str, float]] = []
    for i in range(len(chunk)):
        if i >= len(parsed) or not isinstance(parsed[i], dict):
            out.append(("Uncategorized", 0.0))
            continue
        cat = parsed[i].get("category", "Uncategorized")
        try:
            conf = float(parsed[i].get("confidence", 0))
        except (TypeError, ValueError):
            conf = 0.0
        if cat not in CATEGORIES:
            cat, conf = "Uncategorized", 0.0
        out.append((cat, conf))
    return out


def _extract_json_array(text: str) -> list:
    text = text.strip()
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
