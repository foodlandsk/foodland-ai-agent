"""Behavioral ranking: a small CTR-based score adjustment computed from
real customer engagement events (impression/click/add_to_cart), so
products people actually click and buy more often rank slightly higher
than equally keyword-relevant alternatives.

Deliberately self-contained (own JSONL reader, no dependency on
app.main) for the same reason as app.merchandising: search.py depends
on this module, so importing back would create a circular import.

Uses Bayesian-smoothed CTR - a prior that pulls low-sample products
toward the catalog-wide average - rather than a hard "minimum
impressions" cutoff. This means the signal safely has near-zero effect
on ranking while event volume is still small (every product's smoothed
CTR sits close to the same prior-dominated baseline), and gradually
differentiates products as real event data accumulates over time - no
code changes or redeploy needed as that happens.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from collections import Counter
from pathlib import Path

EVENTS_PATH = os.getenv(
    "EVENTS_LOG_PATH",
    str(Path(tempfile.gettempdir()) / "foodland-ai-agent" / "events.jsonl"),
)
DEFAULT_PRIOR_CLICKS = 1.0
DEFAULT_PRIOR_IMPRESSIONS = 40.0


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
                if ts >= since:
                    events.append(record)
    except OSError:
        return []
    return events


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
    if not scores:
        return prior_clicks / prior_impressions if prior_impressions else 0.0
    return sum(entry["ctr"] for entry in scores.values()) / len(scores)


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


def load_behavioral_rankings(days: int = 30, path: str | None = None) -> dict:
    events = _read_events(days, path)
    scores = compute_engagement_scores(events)
    return {"scores": scores, "baseline_ctr": baseline_ctr(scores)}
