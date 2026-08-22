"""
app/learning_events.py  -  V2.12 Controlled Auto-Learning: normalized
LearningEvent model over the REAL, already-collected event stream.

Ground truth (Section 1 audit, do not invent data sources): Foodland
already has a genuine, end-to-end wired telemetry pipeline predating this
sprint - `app.widget.js: fireEvent()` -> `POST /events` -> `EventRequest`
(`app/main.py`) -> `log_event()` -> `EVENTS_LOG_PATH` (JSONL, same file
`app.behavioral`/`app.fbt` already read). Its real event_type vocabulary
is exactly: impression, click, add_to_cart, no_result, autocomplete_select,
search_submit, conversion (schema-defined but currently never fired by
the widget - dead today), feedback.

This module does NOT invent a second, richer event schema requiring new
frontend instrumentation (Section 1: "Do not invent data sources"). It
normalizes the REAL stream into an explicit, validated `LearningEvent`
and is honest about what is NOT available from it today:

  - `ranking_config_version` is not stamped by the current widget/backend
    write path - always None here. A future EventRequest/log_event
    extension could add it (additive, backward compatible); out of scope
    for this sprint (Section 1/6 - report gaps, do not fabricate).
  - `query_class`/canonical concept is NOT stored on the raw event either
    - it is DERIVED at read time by re-parsing `query` through the real
      V2.4 `app.query_constraints.parse_structured_query()` (Section 19 -
      semantic segmentation reuses existing infra, no new instrumentation
      needed).
  - Higher-level event types the spec's Section 6 lists conceptually
    (CROSS_SELL_SHOWN, RECIPE_OPENED, QUERY_REFORMULATED, SESSION_CONTEXT_
    SWITCH, ...) are not raw event types the system emits - they are
    DERIVED patterns computed over sequences of the real 8 event types
    (see app.learning_signals's reformulation detection). Section 6 itself
    says "support only events actually observable by the system."
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from app.storage_paths import resolve_path

# V2.15b: resolved through the single FOODLAND_DATA_DIR knob instead of
# an independently-hardcoded tempdir default, closing the V2.15a-documented
# risk that this reader could silently desync from app.main.log_event()'s
# writer if EVENTS_LOG_PATH's own explicit override were ever removed.
EVENTS_PATH = str(resolve_path("EVENTS_LOG_PATH", "events.jsonl"))

# Exactly EventRequest.event_type's Literal values (app/main.py) - the
# real, observable vocabulary. Do not add types the system cannot emit.
KNOWN_EVENT_TYPES = frozenset({
    "impression", "click", "add_to_cart", "no_result",
    "autocomplete_select", "search_submit", "conversion", "feedback",
})

# Section 27/89 - queries carrying an explicit brand/size/dietary
# constraint are treated as "specific" so downstream signal weighting can
# shrink behavioral influence for them (app.learning_signals).
MAX_QUERY_LEN = 300
MAX_SESSION_ID_LEN = 64
MAX_SKU_LEN = 64


@dataclass(frozen=True)
class LearningEvent:
    """Section 5 - normalized event, backed entirely by real fields the
    system actually writes (see module docstring for the honest gap
    list). `dedup_key` is a deterministic hash of the fields that make an
    event distinct - NOT a true source-issued event_id (the real pipeline
    does not stamp one today), so it only catches exact-duplicate log
    lines (e.g. a retried POST), not semantically-equivalent events."""
    dedup_key: str
    event_type: str
    ts: int
    session_id: str
    product_sku: str | None
    product_skus: tuple[str, ...]
    query: str | None
    position: int | None
    rating: int | None

    @property
    def all_product_skus(self) -> tuple[str, ...]:
        if self.product_sku:
            return (self.product_sku,) if not self.product_skus else (self.product_sku, *self.product_skus)
        return self.product_skus


@dataclass(frozen=True)
class EventValidationStats:
    total_raw: int
    valid: int
    rejected_malformed: int
    rejected_unknown_product: int
    rejected_missing_session: int
    duplicates_dropped: int


def _read_raw_events(days: int, path: str | None = None) -> list[dict]:
    """Self-contained reader (Section 1 - same pattern as app.behavioral/
    app.fbt's own `_read_events()`, deliberately not importing app.main to
    avoid the same circular-import problem those modules document)."""
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


def _dedup_key(record: dict) -> str:
    basis = "|".join(str(record.get(field, "")) for field in (
        "ts", "session_id", "event_type", "product_sku", "position", "query",
    ))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def normalize_events(
    raw_events: list[dict],
    *,
    known_product_ids: frozenset[str] | None = None,
) -> tuple[list[LearningEvent], EventValidationStats]:
    """Section 8 - validate and normalize. Rejects malformed events
    (unknown event_type, missing/oversized session_id) and events
    referencing a product_sku that does not exist in the current catalog
    (Section 8: "Unknown product IDs must not silently enter learning
    data") - dropped, not raised, since a stale/foreign sku in old log
    lines is expected after catalog changes, not a hard error. Section 16
    - deduplicates by `_dedup_key` before returning."""
    valid: list[LearningEvent] = []
    seen_keys: set[str] = set()
    rejected_malformed = 0
    rejected_unknown_product = 0
    rejected_missing_session = 0
    duplicates_dropped = 0

    for record in raw_events:
        event_type = record.get("event_type")
        if event_type not in KNOWN_EVENT_TYPES:
            rejected_malformed += 1
            continue

        session_id = str(record.get("session_id") or "")
        if not session_id or len(session_id) > MAX_SESSION_ID_LEN:
            rejected_missing_session += 1
            continue

        ts = record.get("ts")
        if not isinstance(ts, (int, float)) or ts <= 0:
            rejected_malformed += 1
            continue

        position = record.get("position")
        if position is not None and (not isinstance(position, int) or position < 0):
            rejected_malformed += 1
            continue

        product_sku = record.get("product_sku")
        product_skus_raw = record.get("product_skus") or []
        if not isinstance(product_skus_raw, list):
            rejected_malformed += 1
            continue

        if known_product_ids is not None:
            skus_to_check = [s for s in ([product_sku] if product_sku else []) + list(product_skus_raw) if s]
            if skus_to_check and not any(sku in known_product_ids for sku in skus_to_check):
                rejected_unknown_product += 1
                continue

        key = _dedup_key(record)
        if key in seen_keys:
            duplicates_dropped += 1
            continue
        seen_keys.add(key)

        query = record.get("query")
        if isinstance(query, str) and len(query) > MAX_QUERY_LEN:
            query = query[:MAX_QUERY_LEN]

        valid.append(LearningEvent(
            dedup_key=key,
            event_type=event_type,
            ts=int(ts),
            session_id=session_id,
            product_sku=str(product_sku)[:MAX_SKU_LEN] if product_sku else None,
            product_skus=tuple(str(s)[:MAX_SKU_LEN] for s in product_skus_raw[:50]),
            query=query,
            position=position,
            rating=record.get("rating"),
        ))

    stats = EventValidationStats(
        total_raw=len(raw_events),
        valid=len(valid),
        rejected_malformed=rejected_malformed,
        rejected_unknown_product=rejected_unknown_product,
        rejected_missing_session=rejected_missing_session,
        duplicates_dropped=duplicates_dropped,
    )
    return valid, stats


def load_learning_events(
    days: int = 30,
    path: str | None = None,
    known_product_ids: frozenset[str] | None = None,
) -> tuple[list[LearningEvent], EventValidationStats]:
    """Entry point mirroring `app.behavioral.load_behavioral_rankings()`/
    `app.fbt.load_fbt_data()`'s `_read_events()` + gate shape (Section 1 -
    reuse the established pattern, do not invent a new one)."""
    raw = _read_raw_events(days, path)
    return normalize_events(raw, known_product_ids=known_product_ids)
