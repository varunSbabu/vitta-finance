"""Anomaly detection — flag transactions and category-month totals that
are unusually large for the user, using their own history as baseline.

Statistical rather than deep-learning: personal-finance data per user is
too small (typically 100–500 txns) to train a useful model. A robust
z-score against the user's own per-category history gives interpretable,
day-one results with no training step, no external calls, no GPU.

Two kinds of anomalies are detected:

  1. Transaction outliers — a single debit whose amount is far above the
     user's typical spend in that category. Baseline is the last 90 days
     of debit transactions in the same category (excluding self-transfers
     and the txn itself). Requires at least 5 baseline points to be
     stable; skipped otherwise.

  2. Category-month spikes — the current month's total spend in a
     category is far above the trailing 3-month average for that
     category. Requires 3 months of history with data.

Every flagged anomaly carries a reason string with concrete numbers so
the UI can show *why* it was flagged, not just that it was.
"""

from __future__ import annotations

import statistics
from datetime import date

from db import get_conn

# Flag when a transaction is this many standard deviations above the
# category mean. 2.0 is the classic outlier threshold and flags roughly
# the top ~2.5% of a normal distribution — few enough to be actionable,
# many enough to catch real spikes.
Z_THRESHOLD = 2.0

# Below this, mean/std aren't meaningful. Skip the category rather than
# flag noise.
MIN_BASELINE_POINTS = 5

# Also flag when a transaction is at least this multiple of the category
# mean, to catch cases where std is tiny (e.g. only rent-like fixed
# amounts) and a z-score would otherwise never trigger.
ABS_MULTIPLIER = 3.0

# For month-over-baseline spike detection.
SPIKE_MULTIPLIER = 1.5
MIN_BASELINE_MONTHS = 3

MAX_ANOMALIES = 20


def _current_month() -> str:
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


def _detect_txn_outliers(conn, user_id: int, month: str) -> list[dict]:
    """Flag debit transactions in `month` that are far above the user's
    typical spend for that category over the trailing 90 days."""

    # Group the trailing 90 days of debits by category, keeping amounts as
    # arrays. Doing this in Python (rather than one massive SQL) keeps the
    # z-score logic readable and lets us skip low-data categories cleanly.
    rows = conn.execute(
        """
        SELECT id, txn_date, amount, category, merchant_clean, merchant_raw
        FROM transactions
        WHERE user_id = ?
          AND direction = 'debit'
          AND is_self_transfer = 0
          AND txn_date >= date('now', '-90 days')
        """,
        (user_id,),
    ).fetchall()

    by_cat: dict[str, list[dict]] = {}
    for r in rows:
        cat = r["category"] or "Uncategorized"
        by_cat.setdefault(cat, []).append(dict(r))

    anomalies: list[dict] = []
    for cat, txns in by_cat.items():
        # Skip Uncategorized — mixing unlike merchants makes the baseline
        # meaningless (a large rent txn compared against tiny coffee txns
        # gets flagged every time).
        if cat == "Uncategorized":
            continue

        # Baseline = everything except txns in the target month, so the
        # month's own spend doesn't skew its own baseline.
        baseline = [t["amount"] for t in txns if not t["txn_date"].startswith(month)]
        if len(baseline) < MIN_BASELINE_POINTS:
            continue

        mean = statistics.fmean(baseline)
        # `pstdev` (population std) is fine here — we're describing the
        # user's own distribution, not sampling from a wider one.
        sd = statistics.pstdev(baseline) if len(baseline) > 1 else 0.0

        for t in txns:
            if not t["txn_date"].startswith(month):
                continue

            amt = t["amount"]
            z = (amt - mean) / sd if sd > 0 else 0.0
            multiple = amt / mean if mean > 0 else 0.0

            if z >= Z_THRESHOLD or multiple >= ABS_MULTIPLIER:
                anomalies.append(
                    {
                        "kind": "txn_outlier",
                        "txn_id": t["id"],
                        "date": t["txn_date"],
                        "amount": amt,
                        "category": cat,
                        "merchant": t["merchant_clean"] or t["merchant_raw"] or "Unknown",
                        "baseline_mean": round(mean, 2),
                        "z_score": round(z, 2),
                        "multiple": round(multiple, 2),
                        "reason": _format_txn_reason(amt, mean, multiple),
                    }
                )

    # Highest multiple first — the biggest spikes are what a user cares
    # about most when they scan the list.
    anomalies.sort(key=lambda a: a["multiple"], reverse=True)
    return anomalies


def _format_txn_reason(amount: float, mean: float, multiple: float) -> str:
    if multiple >= 5:
        return f"₹{amount:,.0f} — {multiple:.1f}× your typical ₹{mean:,.0f}"
    if multiple >= 2:
        return f"₹{amount:,.0f} — {multiple:.1f}× above your usual ₹{mean:,.0f}"
    return f"₹{amount:,.0f} — well above your usual ₹{mean:,.0f}"


def _detect_category_spikes(conn, user_id: int, month: str) -> list[dict]:
    """Flag categories whose spend in `month` is far above the trailing
    3-month average."""

    rows = conn.execute(
        """
        SELECT substr(txn_date, 1, 7) AS m, category, SUM(amount) AS total
        FROM transactions
        WHERE user_id = ?
          AND direction = 'debit'
          AND is_self_transfer = 0
          AND txn_date >= date('now', '-4 months')
        GROUP BY m, category
        """,
        (user_id,),
    ).fetchall()

    # {category: {month: total}}
    by_cat: dict[str, dict[str, float]] = {}
    for r in rows:
        cat = r["category"] or "Uncategorized"
        by_cat.setdefault(cat, {})[r["m"]] = r["total"]

    spikes: list[dict] = []
    for cat, months in by_cat.items():
        if cat == "Uncategorized":
            continue

        current = months.get(month, 0.0)
        if current <= 0:
            continue

        baseline_months = [m for m in months if m != month]
        if len(baseline_months) < MIN_BASELINE_MONTHS:
            continue

        baseline_totals = [months[m] for m in baseline_months]
        baseline_avg = statistics.fmean(baseline_totals)
        if baseline_avg <= 0:
            continue

        multiple = current / baseline_avg
        if multiple >= SPIKE_MULTIPLIER:
            spikes.append(
                {
                    "kind": "category_spike",
                    "category": cat,
                    "current_total": round(current, 2),
                    "baseline_avg": round(baseline_avg, 2),
                    "multiple": round(multiple, 2),
                    "reason": (
                        f"₹{current:,.0f} this month — {multiple:.1f}× your usual ₹{baseline_avg:,.0f}"
                    ),
                }
            )

    spikes.sort(key=lambda s: s["multiple"], reverse=True)
    return spikes


def detect_anomalies(user_id: int, month: str | None = None) -> dict:
    """Full anomaly detection pass for a single user + month. Returns
    both kinds together, capped at MAX_ANOMALIES for the transaction
    outliers so an unusually noisy month doesn't drown the UI."""
    resolved = month or _current_month()
    conn = get_conn()
    try:
        txn_outliers = _detect_txn_outliers(conn, user_id, resolved)
        category_spikes = _detect_category_spikes(conn, user_id, resolved)
    finally:
        conn.close()

    return {
        "month": resolved,
        "transaction_outliers": txn_outliers[:MAX_ANOMALIES],
        "category_spikes": category_spikes,
        "total_count": len(txn_outliers) + len(category_spikes),
    }
