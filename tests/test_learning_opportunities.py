"""
tests/test_learning_opportunities.py  -  V2.12 Section 111: opportunity
detector - synthetic repeated failure produces an opportunity; insufficient
sample produces none.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.learning_events import normalize_events
from app.learning_opportunities import (
    MIN_SUPPORT_RANKING_ANOMALY,
    MIN_SUPPORT_REFORMULATION,
    MIN_SUPPORT_TAXONOMY_GAP,
    MIN_SUPPORT_ZERO_RESULT,
    TYPE_HIGH_REFORMULATION_RATE,
    TYPE_HIGH_ZERO_RESULT,
    TYPE_RANKING_POSITION_ANOMALY,
    TYPE_TAXONOMY_GAP_CANDIDATE,
    detect_all_opportunities,
    detect_high_reformulation_rate,
    detect_high_zero_result,
    detect_ranking_position_anomalies,
    detect_taxonomy_gap_candidates,
)
from app.learning_signals import compute_query_product_signals, detect_reformulations

KNOWN = frozenset({"FL_A", "FL_B", "FL_C"})


def _normalize(raw):
    events, _ = normalize_events(raw, known_product_ids=KNOWN)
    return events


def _mixed_position_anomaly_events(n_impressions: int) -> list[dict]:
    raw = []
    for i in range(1, n_impressions + 1):
        order = ["FL_A", "FL_B"] if i % 2 == 0 else ["FL_B", "FL_A"]
        raw.append({"ts": i, "session_id": f"s{i}", "event_type": "impression", "product_skus": order, "query": "ryza"})
        if i % 3 != 0:
            pos = order.index("FL_B")
            raw.append({"ts": i, "session_id": f"s{i}", "event_type": "click", "product_sku": "FL_B", "position": pos, "query": "ryza"})
    return raw


class TestRankingPositionAnomalyMinimumSupport:
    def test_below_minimum_support_no_opportunity(self):
        raw = _mixed_position_anomaly_events(n_impressions=10)  # well under MIN_SUPPORT_RANKING_ANOMALY
        signals = compute_query_product_signals(_normalize(raw))
        opportunities = detect_ranking_position_anomalies(signals)
        assert opportunities == []

    def test_above_minimum_support_with_real_disagreement_produces_opportunity(self):
        raw = _mixed_position_anomaly_events(n_impressions=max(200, MIN_SUPPORT_RANKING_ANOMALY))
        signals = compute_query_product_signals(_normalize(raw))
        opportunities = detect_ranking_position_anomalies(signals)
        assert len(opportunities) == 1
        assert opportunities[0].type == TYPE_RANKING_POSITION_ANOMALY
        assert opportunities[0].scope == "rice"
        assert opportunities[0].proposed_action_type == "RANKING_WEIGHT_ADJUSTMENT"

    def test_no_disagreement_no_opportunity(self):
        """Section 33/34 - detection creates evidence only when the
        CURRENT rank order actually disagrees with behavioral lift; when
        they already agree there is nothing to propose."""
        raw = []
        for i in range(1, 300):
            raw.append({"ts": i, "session_id": f"s{i}", "event_type": "impression", "product_skus": ["FL_A", "FL_B"], "query": "ryza"})
            raw.append({"ts": i, "session_id": f"s{i}", "event_type": "click", "product_sku": "FL_A", "position": 0, "query": "ryza"})
        signals = compute_query_product_signals(_normalize(raw))
        assert detect_ranking_position_anomalies(signals) == []


class TestHighReformulationRate:
    def test_repeated_failure_pattern_produces_opportunity(self):
        raw = []
        for i in range(MIN_SUPPORT_REFORMULATION + 5):
            base = i * 10
            raw.append({"ts": base + 1, "session_id": f"reform{i}", "event_type": "search_submit", "query": "basmati ryza"})
            raw.append({"ts": base + 2, "session_id": f"reform{i}", "event_type": "search_submit", "query": "jazminova ryza"})
        events = _normalize(raw)
        reformulations = detect_reformulations(events)
        opportunities = detect_high_reformulation_rate(reformulations)
        assert len(opportunities) == 1
        assert opportunities[0].type == TYPE_HIGH_REFORMULATION_RATE
        assert opportunities[0].proposed_action_type == "REVIEW_REQUIRED"

    def test_below_minimum_support_no_opportunity(self):
        raw = [
            {"ts": 1, "session_id": "r1", "event_type": "search_submit", "query": "basmati ryza"},
            {"ts": 2, "session_id": "r1", "event_type": "search_submit", "query": "jazminova ryza"},
        ]
        reformulations = detect_reformulations(_normalize(raw))
        assert detect_high_reformulation_rate(reformulations) == []

    def test_single_reformulation_never_labeled_a_failure_pattern(self):
        """Section 21 - one instance is never enough to call it a
        recurring pattern, regardless of classification."""
        raw = [
            {"ts": 1, "session_id": "solo", "event_type": "search_submit", "query": "basmati ryza"},
            {"ts": 2, "session_id": "solo", "event_type": "search_submit", "query": "jazminova ryza"},
        ]
        reformulations = detect_reformulations(_normalize(raw))
        assert len(reformulations) == 1
        assert detect_high_reformulation_rate(reformulations) == []


class TestHighZeroResult:
    def test_recurring_zero_result_query_produces_opportunity(self):
        raw = [{"ts": i, "session_id": f"z{i}", "event_type": "no_result", "query": "produkt xyz"} for i in range(1, MIN_SUPPORT_ZERO_RESULT + 3)]
        events = _normalize(raw)
        opportunities = detect_high_zero_result(events)
        assert len(opportunities) == 1
        assert opportunities[0].type == TYPE_HIGH_ZERO_RESULT
        assert opportunities[0].proposed_action_type == "REVIEW_REQUIRED"

    def test_below_minimum_support_no_opportunity(self):
        raw = [{"ts": 1, "session_id": "z1", "event_type": "no_result", "query": "produkt xyz"}]
        assert detect_high_zero_result(_normalize(raw)) == []


class TestTaxonomyGapCandidate:
    def test_recurring_unparseable_query_produces_review_required_opportunity(self):
        raw = []
        for i in range(1, MIN_SUPPORT_TAXONOMY_GAP + 3):
            raw.append({"ts": i, "session_id": f"tg{i}", "event_type": "search_submit", "query": "asdkjaslkdj nonsense query"})
            raw.append({"ts": i, "session_id": f"tg{i}", "event_type": "no_result", "query": "asdkjaslkdj nonsense query"})
        opportunities = detect_taxonomy_gap_candidates(_normalize(raw))
        assert len(opportunities) == 1
        assert opportunities[0].type == TYPE_TAXONOMY_GAP_CANDIDATE
        assert opportunities[0].proposed_action_type == "REVIEW_REQUIRED"

    def test_recognized_family_query_never_flagged_as_gap(self):
        raw = [{"ts": i, "session_id": f"r{i}", "event_type": "search_submit", "query": "jazminova ryza"} for i in range(1, 20)]
        assert detect_taxonomy_gap_candidates(_normalize(raw)) == []

    def test_unparseable_query_without_corroborating_no_result_is_not_flagged(self):
        """Real false-positive found via a production audit: 'family is
        None' alone is not evidence of a customer-facing gap - the legacy
        lexical/FAQ fallback can still answer it perfectly well ("cajove
        sety" -> 6 real tea-set products, never a no_result event)."""
        raw = [
            {"ts": i, "session_id": f"tg{i}", "event_type": "search_submit", "query": "cajove sety"}
            for i in range(1, MIN_SUPPORT_TAXONOMY_GAP + 3)
        ]
        assert detect_taxonomy_gap_candidates(_normalize(raw)) == []


class TestDetectAllOpportunitiesRanking:
    def test_ranked_by_confidence_then_sample_size_not_by_revenue(self):
        raw = _mixed_position_anomaly_events(n_impressions=max(200, MIN_SUPPORT_RANKING_ANOMALY))
        events = _normalize(raw)
        signals = compute_query_product_signals(events)
        reformulations = detect_reformulations(events)
        opportunities = detect_all_opportunities(signals, reformulations, events)
        confidences = [o.confidence for o in opportunities]
        rank = {"HIGH": 2, "MEDIUM": 1, "LOW": 0}
        assert confidences == sorted(confidences, key=lambda c: -rank.get(c, 0))
