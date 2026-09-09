"""AI insights — real facts computed from the user's transactions, phrased
by the LLM when a key is configured. See insights.py for the computation;
this module is just the HTTP surface."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from auth import require_auth
from insights import compute_insights, latest_month_with_data, narrate_insights
from llm import is_available as llm_available

router = APIRouter(tags=["insights"])


@router.get("/api/insights")
def api_insights(
    month: Optional[str] = Query(None, description="YYYY-MM; defaults to the latest month that has data"),
    user: dict = Depends(require_auth),
):
    user_id = user["id"]
    resolved = month or latest_month_with_data(user_id)
    cards = compute_insights(user_id, month)
    cards = narrate_insights(cards)
    return {
        "month": resolved,
        "count": len(cards),
        "llm_narrated": llm_available(),
        "insights": cards,
    }
