"""
tests/test_learning_signals.py  -  V2.12 Section 107/108/109/110:
signal aggregation correctness, position bias, cold start, popularity loop.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.learning_events import normalize_events
from app.learning_signals import (
    MAX_EVENTS_PER_SESSION_PRODUCT,
    POSITION_LIFT_MAX_RATIO,
    POSITION_LIFT_MIN_RATIO,
    compute_autocomplete_signals,
    compute_query_product_signals,
    confidence_tier,
    detect_reformulations,
    rollup_family_signals,
)

KNOWN = frozenset({"FL_A", "FL_B", "FL_C"})


def _normalize(raw):
    events, _ = normalize_events(raw, known_product_ids=KNOWN)
    return events


class TestAggregationCorrectness:
    def test_impressions_clicks_add_to_cart_counted_correctly(self):
        raw = [
            {"ts": 1, "session_id": "s1", "event_type": "impression", "product_skus": ["FL_A", "FL_B"], "query": "ryza"},
            {"ts": 2, "session_id": "s1", "event_type": "click", "product_sku": "FL_A", "position": 0, "query": "ryza"},
            {"ts": 3, "session_id": "s1", "event_type": "add_to_cart", "product_sku": "FL_A", "query": "ryza"},
        ]
        signals = compute_query_product_signals(_normalize(raw))
        by_id = {s.product_id: s for s in signals}
        assert by_id["FL_A"].impressions == 1
        assert by_id["FL_A"].clicks == 1
        assert by_id["FL_A"].add_to_cart == 1
        assert by_id["FL_B"].impressions == 1
        assert by_id["FL_B"].clicks == 0

    def test_negative_events_counted_per_pattern(self):
        raw = [
            {"ts": 1, "session_id": "s1", "event_type": "no_result", "query": "ryza"},
            {"ts": 2, "session_id": "s2", "event_type": "impression", "product_skus": ["FL_A"], "query": "ryza"},
        ]
        signals = compute_query_product_signals(_normalize(raw))
        assert signals[0].negative_events == 1

    def test_family_rollup_sums_correctly(self):
        raw = [
            {"ts": 1, "session_id": "s1", "event_type": "impression", "product_skus": ["FL_A", "FL_B"], "query": "ryza"},
            {"ts": 2, "session_id": "s2", "event_type": "click", "product_sku": "FL_A", "position": 0, "query": "ryza"},
        ]
        rollups = rollup_family_signals(compute_query_product_signals(_normalize(raw)))
        rice = next(r for r in rollups if r.family == "rice")
        assert rice.total_impressions == 2
        assert rice.total_clicks == 1
        assert rice.distinct_products == 2


class TestConfidenceTiers:
    def test_low_medium_high_thresholds(self):
        assert confidence_tier(5) == "LOW"
        assert confidence_tier(50) == "MEDIUM"
        assert confidence_tier(500) == "HIGH"


class TestMinimumSupport:
    def test_signal_confidence_reflects_sample_count(self):
        raw = [{"ts": i, "session_id": f"s{i}", "event_type": "impression", "product_skus": ["FL_A"], "query": "ryza"} for i in range(1, 6)]
        signals = compute_query_product_signals(_normalize(raw))
        assert signals[0].confidence == "LOW"
        assert signals[0].impressions == 5


class TestPositionBias:
    def test_raw_top_position_clicks_do_not_automatically_dominate(self):
        """Section 108 - a product shown ONLY at position 0 with an
        average CTR should not automatically outrank one shown ONLY at
        position 1 with a genuinely higher engagement rate, once
        normalized by the catalog-wide expected CTR at each position."""
        raw = []
        # Position mixing across two products so the position-expected-CTR
        # baseline is independent of either product's own clicks.
        for i in range(1, 201):
            order = ["FL_A", "FL_B"] if i % 2 == 0 else ["FL_B", "FL_A"]
            raw.append({"ts": i, "session_id": f"s{i}", "event_type": "impression", "product_skus": order, "query": "ryza"})
            # FL_B gets clicked far more often than its position would predict.
            if i % 3 != 0:
                pos = order.index("FL_B")
                raw.append({"ts": i, "session_id": f"s{i}", "event_type": "click", "product_sku": "FL_B", "position": pos, "query": "ryza"})

        signals = {s.product_id: s for s in compute_query_product_signals(_normalize(raw))}
        assert signals["FL_A"].avg_position == signals["FL_B"].avg_position  # symmetric impression order
        assert signals["FL_B"].position_normalized_lift > signals["FL_A"].position_normalized_lift

    def test_lift_is_bounded(self):
        raw = [{"ts": i, "session_id": f"s{i}", "event_type": "impression", "product_skus": ["FL_A"], "query": "ryza"} for i in range(1, 301)]
        raw += [{"ts": i, "session_id": f"s{i}", "event_type": "click", "product_sku": "FL_A", "position": 0, "query": "ryza"} for i in range(1, 301)]
        signals = compute_query_product_signals(_normalize(raw))
        assert signals[0].position_normalized_lift <= POSITION_LIFT_MAX_RATIO
        assert signals[0].position_normalized_lift >= POSITION_LIFT_MIN_RATIO


class TestColdStart:
    def test_new_product_with_zero_events_produces_no_signal(self):
        """Section 109 - a product with no behavioral history simply has
        no QueryProductSignal entry at all (not a zero/negative score) -
        callers (app.learning_candidates) never see it as 'worse', it is
        just absent from behavioral consideration, letting semantic
        ranking (app.ranking's L1-L4 tuple) decide entirely."""
        raw = [{"ts": 1, "session_id": "s1", "event_type": "impression", "product_skus": ["FL_A"], "query": "ryza"}]
        signals = {s.product_id: s for s in compute_query_product_signals(_normalize(raw))}
        assert "FL_C" not in signals  # never impressed/clicked - no signal manufactured for it


class TestPopularityLoopGuard:
    def test_extreme_ctr_still_capped_at_max_ratio(self):
        """Section 79 - FL_A and FL_C both compete for position 0 across
        different impressions (so the position-0 expected-CTR baseline is
        genuinely independent of FL_A's own clicks, unlike a scenario
        where FL_A is the ONLY product ever shown at position 0 - that
        would make 'expected CTR at position 0' circularly equal to FL_A's
        own CTR and always yield lift=1.0, proving nothing). FL_A is
        clicked on almost every impression; FL_C never is - as extreme a
        disparity as real data gets - and the resulting lift must still
        never exceed POSITION_LIFT_MAX_RATIO."""
        raw = []
        for i in range(1, 501):
            if i % 2 == 0:
                raw.append({"ts": i, "session_id": f"s{i}", "event_type": "impression", "product_skus": ["FL_A", "FL_B"], "query": "ryza"})
                raw.append({"ts": i, "session_id": f"s{i}", "event_type": "click", "product_sku": "FL_A", "position": 0, "query": "ryza"})
            else:
                raw.append({"ts": i, "session_id": f"s{i}", "event_type": "impression", "product_skus": ["FL_C", "FL_B"], "query": "ryza"})
        signals = {s.product_id: s for s in compute_query_product_signals(_normalize(raw))}
        # The cap itself is the invariant under test - even this extreme a
        # disparity (clicked on literally every impression vs. never) must
        # never push the lift past POSITION_LIFT_MAX_RATIO.
        assert signals["FL_A"].position_normalized_lift <= POSITION_LIFT_MAX_RATIO
        assert signals["FL_A"].position_normalized_lift > 1.5  # genuinely elevated, not a no-op
        assert signals["FL_C"].position_normalized_lift < signals["FL_A"].position_normalized_lift


class TestBotAnomalyGuard:
    def test_single_session_repeated_events_capped(self):
        """Section 15/124 - hundreds of repeated events from ONE session
        against the SAME product must not multiply into hundreds of
        clicks in the aggregate signal."""
        raw = [{"ts": i, "session_id": "bot-session", "event_type": "click", "product_sku": "FL_A", "position": 0, "query": "ryza"} for i in range(1, 501)]
        raw.append({"ts": 999, "session_id": "bot-session", "event_type": "impression", "product_skus": ["FL_A"], "query": "ryza"})
        signals = {s.product_id: s for s in compute_query_product_signals(_normalize(raw))}
        assert signals["FL_A"].clicks <= MAX_EVENTS_PER_SESSION_PRODUCT

    def test_normal_multi_session_volume_not_capped(self):
        raw = [{"ts": i, "session_id": f"s{i}", "event_type": "click", "product_sku": "FL_A", "position": 0, "query": "ryza"} for i in range(1, 51)]
        signals = {s.product_id: s for s in compute_query_product_signals(_normalize(raw))}
        assert signals["FL_A"].clicks == 50


class TestReformulationClassification:
    def test_successful_refinement_detected(self):
        raw = [
            {"ts": 1, "session_id": "s1", "event_type": "search_submit", "query": "ryza"},
            {"ts": 2, "session_id": "s1", "event_type": "search_submit", "query": "jazminova ryza"},
            {"ts": 3, "session_id": "s1", "event_type": "click", "product_sku": "FL_A", "position": 0, "query": "jazminova ryza"},
        ]
        results = detect_reformulations(_normalize(raw))
        assert len(results) == 1
        assert results[0].classification == "SUCCESSFUL_REFINEMENT"

    def test_engaged_first_query_is_not_a_reformulation(self):
        raw = [
            {"ts": 1, "session_id": "s1", "event_type": "search_submit", "query": "ryza"},
            {"ts": 2, "session_id": "s1", "event_type": "click", "product_sku": "FL_A", "position": 0, "query": "ryza"},
            {"ts": 3, "session_id": "s1", "event_type": "search_submit", "query": "sojova omacka"},
        ]
        results = detect_reformulations(_normalize(raw))
        assert results == []

    def test_failure_reformulation_same_family_no_engagement(self):
        raw = [
            {"ts": 1, "session_id": "s1", "event_type": "search_submit", "query": "basmati ryza"},
            {"ts": 2, "session_id": "s1", "event_type": "search_submit", "query": "jazminova ryza"},
        ]
        results = detect_reformulations(_normalize(raw))
        assert len(results) == 1
        assert results[0].classification == "FAILURE_REFORMULATION"


class TestAutocompleteSignal:
    def test_selection_frequency_counted(self):
        raw = [{"ts": i, "session_id": f"s{i}", "event_type": "autocomplete_select", "query": "jazminova ryza"} for i in range(1, 4)]
        signals = compute_autocomplete_signals(_normalize(raw))
        assert signals[0].query_text == "jazminova ryza"
        assert signals[0].selections == 3
