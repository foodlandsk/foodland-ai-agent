"""
tests/test_learning_events.py  -  V2.12 Section 106: LearningEvent
validation - valid event, invalid product ID, duplicate event, missing
session, invalid rank/position, unknown event type.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.learning_events import EventValidationStats, normalize_events

KNOWN = frozenset({"FL_A", "FL_B", "FL_C"})


def _event(**overrides) -> dict:
    base = {"ts": 1_700_000_000, "session_id": "s1", "event_type": "click", "product_sku": "FL_A", "position": 0, "query": "ryza"}
    base.update(overrides)
    return base


class TestValidEvent:
    def test_well_formed_event_is_accepted(self):
        events, stats = normalize_events([_event()], known_product_ids=KNOWN)
        assert len(events) == 1
        assert stats.valid == 1
        assert events[0].event_type == "click"
        assert events[0].product_sku == "FL_A"


class TestUnknownEventType:
    def test_unrecognized_event_type_rejected(self):
        events, stats = normalize_events([_event(event_type="purchase_completed")], known_product_ids=KNOWN)
        assert events == []
        assert stats.rejected_malformed == 1


class TestMissingSession:
    def test_empty_session_id_rejected(self):
        events, stats = normalize_events([_event(session_id="")], known_product_ids=KNOWN)
        assert events == []
        assert stats.rejected_missing_session == 1

    def test_oversized_session_id_rejected(self):
        events, stats = normalize_events([_event(session_id="x" * 100)], known_product_ids=KNOWN)
        assert events == []
        assert stats.rejected_missing_session == 1


class TestUnknownProduct:
    def test_product_sku_not_in_catalog_rejected(self):
        events, stats = normalize_events([_event(product_sku="FL_DOES_NOT_EXIST")], known_product_ids=KNOWN)
        assert events == []
        assert stats.rejected_unknown_product == 1

    def test_impression_with_no_known_products_rejected(self):
        events, stats = normalize_events(
            [_event(event_type="impression", product_sku=None, product_skus=["FL_X", "FL_Y"])],
            known_product_ids=KNOWN,
        )
        assert events == []
        assert stats.rejected_unknown_product == 1

    def test_no_catalog_check_when_known_product_ids_omitted(self):
        events, stats = normalize_events([_event(product_sku="FL_DOES_NOT_EXIST")], known_product_ids=None)
        assert len(events) == 1


class TestInvalidPosition:
    def test_negative_position_rejected(self):
        events, stats = normalize_events([_event(position=-1)], known_product_ids=KNOWN)
        assert events == []
        assert stats.rejected_malformed == 1

    def test_non_integer_position_rejected(self):
        events, stats = normalize_events([_event(position="first")], known_product_ids=KNOWN)
        assert events == []
        assert stats.rejected_malformed == 1

    def test_missing_position_is_allowed(self):
        events, stats = normalize_events([_event(position=None)], known_product_ids=KNOWN)
        assert len(events) == 1


class TestInvalidTimestamp:
    def test_zero_or_missing_ts_rejected(self):
        events, stats = normalize_events([_event(ts=0)], known_product_ids=KNOWN)
        assert events == []
        assert stats.rejected_malformed == 1


class TestDuplicateEvent:
    def test_exact_duplicate_dropped(self):
        raw = [_event(), _event()]
        events, stats = normalize_events(raw, known_product_ids=KNOWN)
        assert len(events) == 1
        assert stats.duplicates_dropped == 1

    def test_events_differing_only_in_ts_are_not_duplicates(self):
        raw = [_event(ts=1000), _event(ts=1001)]
        events, stats = normalize_events(raw, known_product_ids=KNOWN)
        assert len(events) == 2
        assert stats.duplicates_dropped == 0


class TestBatchStatsAddUp:
    def test_stats_total_matches_input(self):
        raw = [
            _event(),
            _event(event_type="bogus"),
            _event(session_id=""),
            _event(product_sku="FL_UNKNOWN"),
            _event(),  # duplicate of the first
        ]
        events, stats = normalize_events(raw, known_product_ids=KNOWN)
        assert stats.total_raw == 5
        assert stats.valid == len(events)
        assert (
            stats.valid + stats.rejected_malformed + stats.rejected_missing_session
            + stats.rejected_unknown_product + stats.duplicates_dropped
        ) == stats.total_raw
