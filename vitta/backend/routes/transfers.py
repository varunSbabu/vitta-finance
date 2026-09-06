"""Self-transfer detection between the user's own accounts."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from auth import require_auth
from self_transfer import detect_self_transfers

router = APIRouter(tags=["transfers"])


@router.post("/api/detect-transfers")
def api_detect_transfers(_user: dict = Depends(require_auth)):
    """Scan transactions for debit/credit pairs across the user's own
    accounts and flag them as self-transfers so they're excluded from
    spend/income totals. Safe to call repeatedly (idempotent)."""
    return detect_self_transfers()
