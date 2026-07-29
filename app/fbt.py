"""Frequently-bought-together (FBT): product pairs derived from real
add_to_cart co-occurrence within the same session, so basket recommendations
can reflect what customers actually buy together instead of relying only on
editorial CrossSell/Alternatives knowledge records.

Deliberately self-contained (own JSONL reader, no dependency on app.main)
for the same reason as app.behavioral: main.py depends on this module.

A session's add_to_cart events define a "basket" - every distinct sku a
session added within the lookback window is treated as bought together.

Two safeguards, applied from the start rather than discovered the hard way
a second time (see app/behavioral.py's incident notes for the first time):

1. A hard minimum-add_to_cart-events gate (FBT_MIN_ADD_TO_CART_EVENTS,
   default 200): below that catalog-wide volume, load_fbt_data() returns
   empty pairs and the signal is a no-op everywhere.
2. A minimum co-occurrence count per pair (FBT_MIN_PAIR_COUNT, default 3):
   a single basket's coincidence should not surface as a "recommendation".
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

EVENTS_PATH = os.getenv(
    "EVENTS_LOG_PATH",
    str(Path(tempfile.gettempdir()) / "foodland-ai-agent" / "events.jsonl"),
)
DEFAULT_MIN_ADD_TO_CART_EVENTS = int(os.getenv("FBT_MIN_ADD_TO_CART_EVENTS", "200"))
DEFAULT_MIN_PAIR_COUNT = int(os.getenv("FBT_MIN_PAIR_COUNT", "3"))
DEFAULT_MAX_BASKET_SIZE = 25


def _read_events(days: int = 60, path: str | None = None) -> list[dict]:
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


def build_baskets(
    events: list[dict],
    max_basket_size: int = DEFAULT_MAX_BASKET_SIZE,
) -> list[set[str]]:
    """Groups add_to_cart events by session_id. Sessions with only one
    distinct sku carry no pairwise signal and are dropped; an unreasonably
    large basket (bot/test traffic) is dropped too rather than fanning out
    into O(n^2) noisy pairs."""
    by_session: dict[str, set[str]] = defaultdict(set)
    for event in events:
        if event.get("event_type") != "add_to_cart":
            continue
        session_id = event.get("session_id")
        sku = event.get("product_sku")
        if session_id and sku:
            by_session[session_id].add(sku)
    return [skus for skus in by_session.values() if 2 <= len(skus) <= max_basket_size]


def compute_pair_counts(baskets: list[set[str]]) -> Counter:
    pair_counts: Counter = Counter()
    for basket in baskets:
        items = sorted(basket)
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                pair_counts[(items[i], items[j])] += 1
    return pair_counts


def pairs_by_sku(
    pair_counts: Counter,
    min_pair_count: int = DEFAULT_MIN_PAIR_COUNT,
) -> dict[str, list[tuple[str, int]]]:
    result: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for (sku_a, sku_b), count in pair_counts.items():
        if count < min_pair_count:
            continue
        result[sku_a].append((sku_b, count))
        result[sku_b].append((sku_a, count))
    for sku in result:
        result[sku].sort(key=lambda item: item[1], reverse=True)
    return dict(result)


def load_fbt_data(
    days: int = 60,
    path: str | None = None,
    min_add_to_cart_events: int | None = None,
    min_pair_count: int | None = None,
) -> dict:
    min_events = (
        DEFAULT_MIN_ADD_TO_CART_EVENTS if min_add_to_cart_events is None else min_add_to_cart_events
    )
    min_pair = DEFAULT_MIN_PAIR_COUNT if min_pair_count is None else min_pair_count

    events = _read_events(days, path)
    total_add_to_cart = sum(1 for event in events if event.get("event_type") == "add_to_cart")

    if total_add_to_cart < min_events:
        # Not enough add_to_cart volume yet to trust any co-occurrence
        # computed from it - stay a strict no-op rather than let a handful
        # of baskets (e.g. a developer's own manual testing) invent pairs.
        return {"pairs": {}, "total_add_to_cart_events": total_add_to_cart, "active": False}

    baskets = build_baskets(events)
    pair_counts = compute_pair_counts(baskets)
    pairs = pairs_by_sku(pair_counts, min_pair)
    return {"pairs": pairs, "total_add_to_cart_events": total_add_to_cart, "active": True}


def fbt_recommendations(sku: str, fbt_data: dict, limit: int) -> list[str]:
    """Returns co-purchased sku ids for `sku`, ranked by co-occurrence
    count, or an empty list while the gate keeps fbt_data inactive."""
    if not fbt_data.get("active"):
        return []
    entries = fbt_data.get("pairs", {}).get(sku, [])
    return [candidate_sku for candidate_sku, _count in entries[:limit]]
