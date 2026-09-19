"""Anomaly detection — flag unusually large transactions and category-
month spikes based on the user's own history.

  GET /api/anomalies?month=YYYY-MM  — defaults to current month
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from anomalies import detect_anomalies
from auth import require_auth

router = APIRouter(tags=["anomalies"])


@router.get("/api/anomalies")
def api_anomalies(
    month: Optional[str] = Query(None, description="YYYY-MM; defaults to current month"),
    user: dict = Depends(require_auth),
):
    return detect_anomalies(user["id"], month)
