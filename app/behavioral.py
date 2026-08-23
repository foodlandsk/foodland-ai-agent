"""Behavioral ranking: a small CTR-based score adjustment computed from
real customer engagement events (impression/click/add_to_cart), so
products people actually click and buy more often rank slightly higher
than equally keyword-relevant alternatives.

Deliberately self-contained (own JSONL reader, no dependency on
app.main) for the same reason as app.merchandising: search.py depends
on this module, so importing back would create a circular import.

Two independent safeguards keep this from reacting to noise:

1. A hard minimum-total-impressions gate (BEHAVIORAL_MIN_TOTAL_IMPRESSIONS,
   default 1000): while the catalog-wide impression count logged so far
   is below this, load_behavioral_rankings() returns empty scores and the
   signal is a no-op everywhere. This was added after a real incident: with
   only ~20 total impressions (mostly this developer's own manual endpoint
   testing rather than organic traffic), a single product with 1 impression
   and 1 click produced a smoothed CTR far enough above the (also tiny and
   noisy) baseline to visibly reorder search results. Per-product Bayesian
   smoothing alone was not enough to prevent that with so little data -
   this gate is the actual fix.
2. Once past that gate, a Bayesian prior still smooths each individual
   product's CTR toward the pooled catalog baseline, and the baseline
   itself is the *pooled* click/impression ratio (sum of all clicks over
   sum of all impressions) rather than an average of per-product ratios,
   so it isn't dominated by a handful of low-sample outliers either.
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter
from pathlib import Path

from app.storage_paths import resolve_path

# V2.15b: resolved through the single FOODLAND_DATA_DIR knob instead of
# an independently-hardcoded tempdir default (app.storage_paths has no
# dependency on app.main/app.search, so this does not reintroduce the
# circular-import risk this module's docstring warns about). Explicit
# EVENTS_LOG_PATH still wins, unchanged for any deployment that already
# sets it.
EVENTS_PATH = str(resolve_path("EVENTS_LOG_PATH", "events.jsonl"))
DEFAULT_PRIOR_CLICKS = 1.0
DEFAULT_PRIOR_IMPRESSIONS = 40.0
DEFAULT_MIN_TOTAL_IMPRESSIONS = int(os.getenv("BEHAVIORAL_MIN_TOTAL_IMPRESSIONS", "1000"))


def _read_events(days: int = 30, path: str | None = None) -> list[dict]:
    resolved_path = Path(path or EVENTS_PATH)
    if not resolved_path.exists():
        return []
    now = int(time.time())
    since = now - max(1, days) * 86400
    events: list[dict] = []
    try:
        with resolved_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = int(record.get("ts", 0) or 0)
                # V2.15d.3 (docs/event-execution-context-isolation-v2.15d.3.md)
                # - exclude synthetic/admin verification traffic from the
                # behavioral CTR signal. Missing execution_context means the
                # record predates this field (V2.15d.2 and earlier) - treated
                # as CUSTOMER since /events had no non-customer path before.
                if ts >= since and record.get("execution_context") in (None, "CUSTOMER"):
                    events.append(record)
    except OSError:
        return []
    return events


def total_impressions(events: list[dict]) -> int:
    """Total SKU-level impressions across all events - the denominator that
    matters for deciding whether there's enough volume to trust any CTR
    computed from it, regardless of how many distinct products it's spread
    across."""
    total = 0
    for event in events:
        if event.get("event_type") == "impression":
            total += len(event.get("product_skus") or [])
    return total


def compute_engagement_scores(
    events: list[dict],
    prior_clicks: float = DEFAULT_PRIOR_CLICKS,
    prior_impressions: float = DEFAULT_PRIOR_IMPRESSIONS,
) -> dict[str, dict]:
    impressions: Counter = Counter()
    clicks: Counter = Counter()
    add_to_carts: Counter = Counter()

    for event in events:
        event_type = event.get("event_type")
        if event_type == "impression":
            for sku in event.get("product_skus") or []:
                impressions[sku] += 1
        elif event_type == "click":
            sku = event.get("product_sku")
            if sku:
                clicks[sku] += 1
        elif event_type == "add_to_cart":
            sku = event.get("product_sku")
            if sku:
                add_to_carts[sku] += 1

    all_skus = set(impressions) | set(clicks) | set(add_to_carts)
    scores: dict[str, dict] = {}
    for sku in all_skus:
        imp = impressions.get(sku, 0)
        clk = clicks.get(sku, 0)
        atc = add_to_carts.get(sku, 0)
        smoothed_ctr = (clk + prior_clicks) / (imp + prior_impressions)
        scores[sku] = {"impressions": imp, "clicks": clk, "add_to_cart": atc, "ctr": smoothed_ctr}
    return scores


def baseline_ctr(
    scores: dict[str, dict],
    prior_clicks: float = DEFAULT_PRIOR_CLICKS,
    prior_impressions: float = DEFAULT_PRIOR_IMPRESSIONS,
) -> float:
    """Pooled click/impression ratio across all scored products (sum of
    clicks over sum of impressions), not an average of individual products'
    ratios - the latter weights a product with 1 impression the same as one
    with 10,000, which is exactly the kind of low-sample noise this
    function needs to be resistant to."""
    if not scores:
        return prior_clicks / prior_impressions if prior_impressions else 0.0
    total_clicks = sum(entry["clicks"] for entry in scores.values())
    total_impr = sum(entry["impressions"] for entry in scores.values())
    return (total_clicks + prior_clicks) / (total_impr + prior_impressions)


def behavioral_multiplier(
    product_id: str,
    scores: dict[str, dict],
    baseline: float,
    weight: float = 1.0,
    min_ratio: float = 0.5,
    max_ratio: float = 2.0,
) -> float:
    """1.0 = no effect. A product's smoothed CTR relative to the catalog
    baseline is clamped to [min_ratio, max_ratio] before being applied, so a
    single unusually good/bad performer can't swing scoring unboundedly."""
    entry = scores.get(product_id)
    if not entry or baseline <= 0:
        return 1.0
    ratio = entry["ctr"] / baseline
    ratio = max(min_ratio, min(ratio, max_ratio))
    return 1.0 + weight * (ratio - 1.0)


def load_behavioral_rankings(
    days: int = 30,
    path: str | None = None,
    min_total_impressions: int | None = None,
) -> dict:
    min_total = DEFAULT_MIN_TOTAL_IMPRESSIONS if min_total_impressions is None else min_total_impressions
    events = _read_events(days, path)
    total_impr = total_impressions(events)

    if total_impr < min_total:
        # Not enough catalog-wide volume yet to trust any CTR computed from
        # it - stay a strict no-op rather than let a handful of events (e.g.
        # a developer's own manual testing) swing real search results.
        return {"scores": {}, "baseline_ctr": 0.0, "total_impressions": total_impr, "active": False}

    scores = compute_engagement_scores(events)
    return {
        "scores": scores,
        "baseline_ctr": baseline_ctr(scores),
        "total_impressions": total_impr,
        "active": True,
    }
