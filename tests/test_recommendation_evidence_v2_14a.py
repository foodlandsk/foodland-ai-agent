"""
tests/test_recommendation_evidence_v2_14a.py  -  V2.14a: tests for
app.recommendation_evidence, the new evidence/confidence/decision
foundation. This module is NOT wired into any customer-facing path
(docs/recommendation-intelligence-v2.14a.md, GATE A scope) - these
tests are pure unit tests against the module itself, not end-to-end
chat() calls.

Evidence values used below are grounded in the V2.14a catalog audit
(docs/recommendation-intelligence-v2.14a.md), not arbitrary: taxonomy
HIGH-tier family match (24.8% of catalog, category-path-backed) is a
realistic strong DATA_DERIVED signal; cross_sell role-match is a
realistic INFERRED signal; an unstructured "tastes more authentic"
claim is a realistic LLM_JUDGMENT signal with no catalog field behind
it (origin/authenticity data audited at ~0.05% coverage - effectively
none).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from app.recommendation_evidence import (
    CONFIDENCE_HIGH,
    CONFIDENCE_INSUFFICIENT,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    DECISION_ABSTAIN,
    DECISION_CLARIFY,
    DECISION_RECOMMEND,
    PROVENANCE_DATA_DERIVED,
    PROVENANCE_INFERRED,
    PROVENANCE_LLM_JUDGMENT,
    EvidenceItem,
    compute_confidence,
    decide,
)


def _taxonomy_high_evidence(strength: float = 0.9) -> EvidenceItem:
    return EvidenceItem(
        reason_code="product_type_fit",
        provenance=PROVENANCE_DATA_DERIVED,
        source="app.taxonomy:HIGH_tier_category_match",
        strength=strength,
    )


def _cross_sell_role_evidence(strength: float = 0.6) -> EvidenceItem:
    return EvidenceItem(
        reason_code="use_case_fit",
        provenance=PROVENANCE_INFERRED,
        source="app.cross_sell:USE_CASE_COMPLETION_role_match",
        strength=strength,
    )


def _llm_authenticity_evidence(strength: float = 0.8) -> EvidenceItem:
    return EvidenceItem(
        reason_code="authenticity",
        provenance=PROVENANCE_LLM_JUDGMENT,
        source="openai:qualitative_claim",
        strength=strength,
    )


class TestEvidenceItemValidation:
    def test_rejects_invalid_provenance(self):
        with pytest.raises(ValueError):
            EvidenceItem(reason_code="x", provenance="MAYBE", source="s", strength=0.5)

    def test_rejects_out_of_range_strength(self):
        with pytest.raises(ValueError):
            EvidenceItem(reason_code="x", provenance=PROVENANCE_DATA_DERIVED, source="s", strength=1.5)

    def test_rejects_empty_reason_code(self):
        with pytest.raises(ValueError):
            EvidenceItem(reason_code="", provenance=PROVENANCE_DATA_DERIVED, source="s", strength=0.5)


class TestConfidenceCaseA_StrongDeterministicEvidenceAllowsHigh:
    """Case A (spec Section 43): strong deterministic evidence -> HIGH allowed."""

    def test_two_strong_data_derived_items_yield_high(self):
        evidence = [_taxonomy_high_evidence(0.9), _cross_sell_role_evidence(0.8)]
        assert compute_confidence(evidence) == CONFIDENCE_HIGH

    def test_single_very_strong_item_yields_high(self):
        evidence = [_taxonomy_high_evidence(0.95)]
        assert compute_confidence(evidence) == CONFIDENCE_HIGH

    def test_high_confidence_recommends(self):
        evidence = [_taxonomy_high_evidence(0.9), _cross_sell_role_evidence(0.8)]
        assert decide(evidence) == DECISION_RECOMMEND


class TestConfidenceCaseB_PartialDeterministicEvidenceYieldsMediumOrLow:
    """Case B: partial deterministic evidence -> MEDIUM/LOW."""

    def test_one_medium_strength_data_derived_item_yields_medium(self):
        evidence = [_taxonomy_high_evidence(0.6)]
        assert compute_confidence(evidence) == CONFIDENCE_MEDIUM

    def test_one_weak_data_derived_item_yields_low(self):
        evidence = [EvidenceItem(reason_code="size_fit", provenance=PROVENANCE_DATA_DERIVED, source="s", strength=0.2)]
        assert compute_confidence(evidence) == CONFIDENCE_LOW

    def test_medium_confidence_still_recommends_when_differentiated(self):
        evidence = [_taxonomy_high_evidence(0.6)]
        assert decide(evidence) == DECISION_RECOMMEND


class TestConfidenceCaseC_LlmJudgmentOnlyForbidsHigh:
    """Case C (Section 12, the critical invariant): LLM judgment only -> HIGH forbidden."""

    def test_single_llm_item_never_high(self):
        evidence = [_llm_authenticity_evidence(0.99)]
        assert compute_confidence(evidence) != CONFIDENCE_HIGH
        assert compute_confidence(evidence) == CONFIDENCE_LOW

    def test_many_llm_items_never_high(self):
        evidence = [_llm_authenticity_evidence(0.95) for _ in range(10)]
        assert compute_confidence(evidence) != CONFIDENCE_HIGH

    def test_llm_only_property_exhaustive_strength_sweep(self):
        """No strength value, however high, lets LLM_JUDGMENT-only
        evidence reach HIGH - the invariant must hold for every input,
        not just the examples above."""
        for strength_hundredths in range(0, 101):
            strength = strength_hundredths / 100.0
            evidence = [_llm_authenticity_evidence(strength)]
            assert compute_confidence(evidence) != CONFIDENCE_HIGH, f"failed at strength={strength}"

    def test_llm_only_evidence_abstains_rather_than_recommends(self):
        evidence = [_llm_authenticity_evidence(0.9)]
        assert decide(evidence) == DECISION_ABSTAIN

    def test_mixed_llm_and_weak_data_derived_still_not_high(self):
        evidence = [_llm_authenticity_evidence(0.99), EvidenceItem(
            reason_code="brand_fit", provenance=PROVENANCE_DATA_DERIVED, source="s", strength=0.3,
        )]
        assert compute_confidence(evidence) in (CONFIDENCE_LOW, CONFIDENCE_MEDIUM)
        assert compute_confidence(evidence) != CONFIDENCE_HIGH

    def test_mixed_llm_and_strong_data_derived_can_reach_medium_not_high_alone(self):
        # A single strong grounded item alone (no second strong item) is
        # MEDIUM, not HIGH - HIGH requires >=2 strong grounded items or
        # one very-strong (>=0.9) grounded item; adding LLM_JUDGMENT
        # noise must never push it over that line by itself.
        evidence = [_llm_authenticity_evidence(0.99), _taxonomy_high_evidence(0.8)]
        assert compute_confidence(evidence) == CONFIDENCE_MEDIUM


class TestConfidenceCaseD_InsufficientEvidenceAbstainsOrClarifies:
    """Case D: insufficient evidence -> ABSTAIN or CLARIFY."""

    def test_no_evidence_is_insufficient(self):
        assert compute_confidence([]) == CONFIDENCE_INSUFFICIENT

    def test_no_evidence_abstains(self):
        assert decide([]) == DECISION_ABSTAIN

    def test_no_meaningful_differentiation_abstains_even_with_high_confidence(self):
        evidence = [_taxonomy_high_evidence(0.95)]
        assert decide(evidence, has_meaningful_differentiation=False) == DECISION_ABSTAIN


class TestConfidenceCaseE_MissingUseCaseClarifies:
    """Case E: missing use-case where use-case materially changes the
    recommendation -> CLARIFY. Grounded in the audit finding that only
    ONE use_case value ("sushi") is wired end-to-end today
    (app.cross_sell._USE_CASE_TO_SOURCE_KEYS) - a bare "aku ryzu
    odporucas?" query has no resolved use_case and must not silently
    guess one."""

    def test_missing_customer_info_clarifies_even_with_some_evidence(self):
        evidence = [_taxonomy_high_evidence(0.9)]
        assert decide(evidence, missing_customer_info=True) == DECISION_CLARIFY

    def test_clarify_takes_precedence_over_recommend(self):
        evidence = [_taxonomy_high_evidence(0.95), _cross_sell_role_evidence(0.8)]
        assert compute_confidence(evidence) == CONFIDENCE_HIGH
        assert decide(evidence, missing_customer_info=True) == DECISION_CLARIFY

    def test_missing_customer_info_with_zero_evidence_still_abstains_not_clarify(self):
        # CLARIFY implies "I could answer if you told me X" - with truly
        # zero evidence there is nothing a clarifying answer would help
        # complete, so ABSTAIN is the honest outcome, not CLARIFY.
        assert decide([], missing_customer_info=True) == DECISION_ABSTAIN


class TestDeterministicRepeatability:
    def test_same_evidence_always_yields_same_confidence(self):
        evidence = [_taxonomy_high_evidence(0.8), _cross_sell_role_evidence(0.6), _llm_authenticity_evidence(0.9)]
        results = {compute_confidence(list(evidence)) for _ in range(20)}
        assert len(results) == 1

    def test_order_independence(self):
        a = [_taxonomy_high_evidence(0.9), _cross_sell_role_evidence(0.8)]
        b = list(reversed(a))
        assert compute_confidence(a) == compute_confidence(b)


class TestUnsupportedClaimHandling:
    """A candidate with only unsupported (LLM_JUDGMENT) claims must
    never be presented with the same confidence as one backed by real
    catalog data - direct regression test for Section 21 claim safety."""

    def test_llm_claim_alone_is_strictly_weaker_than_data_derived_alone(self):
        llm_only = compute_confidence([_llm_authenticity_evidence(0.9)])
        data_only = compute_confidence([_taxonomy_high_evidence(0.9)])
        _rank = {CONFIDENCE_INSUFFICIENT: 0, CONFIDENCE_LOW: 1, CONFIDENCE_MEDIUM: 2, CONFIDENCE_HIGH: 3}
        assert _rank[llm_only] < _rank[data_only]
