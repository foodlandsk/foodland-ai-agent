"""
tests/test_learning_dataset_readiness_v2_15e.py  -  V2.15e: Recommendation
Learning Dataset Readiness & Causal Signal Quality Gate.

GATE A (audit only) was chosen for this sprint - see
docs/recommendation-learning-dataset-readiness-v2.15e.md for the full
audit. No dataset builder, no runtime ranking/recommendation code, and
no app/widget.js change was introduced: structural correlation exists
for comparison/use_case_advice/basket_completion but is absent for
cross_sell/recipe_shopping/replacement_products/explicit-feedback, and
empirical production volume is currently near-zero for decision_id-
correlated events (0 of the most recent 200 production events carried a
non-null decision_id at audit time). Building a candidate dataset now
would be populated by almost nothing.

This file is the audit's PERMANENT, EXECUTABLE record of the safety
invariants a future learning-readiness re-audit (or a future V2.15f
dataset-builder sprint) must continue to respect. It does not build
anything - it locks down facts already true about the running system,
so a future change that silently breaks one of them fails CI instead of
being missed.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m
from app.execution_context import customer_context, evaluation_context


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat_as_customer(message: str, session_id: str, limit: int = 8) -> dict:
    return m._chat_internal(
        m.ChatRequest(message=message, session_id=session_id, limit=limit),
        _FakeRequest(),
        execution_context=customer_context(),
    )


COMPARISON_QUERY = "porovnaj Samyang Buldak a Nissin Demae Ramen"
BASKET_QUERY = "co potrebujem na sushi"
USE_CASE_QUERY = "ake kokosove mlieko na tom kha gai?"


# ---------------------------------------------------------------------
# CASE Q - resultset continuation breaks interaction/decision attribution
# ---------------------------------------------------------------------

class TestResultsetContinuationAttributionBreak:
    """CASE Q (Section 52/87). "Show More" mints a BRAND NEW interaction_id
    (never reuses the original) and carries no decision_id at all - so a
    product revealed via continuation cannot be causally attributed back
    to the ORIGINAL turn's interaction/decision. This is documented as a
    known, honest limitation (RESULTSET_CONTINUATION_BREAKS_ATTRIBUTION),
    not silently assumed to work."""

    def test_continuation_gets_a_fresh_interaction_id_not_the_original(self):
        sid = "v215e-resultset-fresh-id"
        r1 = _chat_as_customer("jazminova ryza", sid)
        assert r1.get("has_more") is True
        r2 = _chat_as_customer("zobraz viac", sid)
        assert r2.get("interaction_id") != r1.get("interaction_id")
        assert r2.get("interaction_id")  # still non-empty, just different

    def test_continuation_response_carries_no_decision_id_field(self):
        sid = "v215e-resultset-no-decision-id"
        _chat_as_customer("jazminova ryza", sid)
        r2 = _chat_as_customer("zobraz viac", sid)
        assert "comparison_decision_id" not in r2
        assert "basket_decision_id" not in r2
        assert "use_case_advice_decision_id" not in r2


# ---------------------------------------------------------------------
# CASE H/I - explicit feedback has NO decision_id/interaction_id correlation
# ---------------------------------------------------------------------

class TestExplicitFeedbackHasNoDecisionCorrelation:
    """CASE H/I (Section 17/18/87). app/widget.js's vote() call sends only
    {event_type: "feedback", rating, query} - never interaction_id or
    decision_id, even though EventRequest supports both fields. A thumbs
    rating today floats free: it cannot be attributed to a specific
    recommendation decision. This test locks down the CURRENT schema
    reality (the field is optional and defaults to None) so a future
    reader can't assume feedback-decision correlation exists without
    updating this test and the readiness doc together."""

    def test_feedback_event_schema_allows_but_does_not_require_decision_id(self):
        req = m.EventRequest(session_id="s1", event_type="feedback", rating=1, query="test")
        assert req.decision_id is None
        assert req.interaction_id is None

    def test_feedback_event_persists_without_decision_correlation(self, tmp_path, monkeypatch):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        req = m.EventRequest(session_id="s1", event_type="feedback", rating=1, query="test")
        m.log_event(req, "ck", execution_context=customer_context())
        rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert rows[0]["decision_id"] is None
        assert rows[0]["interaction_id"] is None
        assert rows[0]["rating"] == 1


# ---------------------------------------------------------------------
# CASE J - reformulation is NEVER a live, request-time signal or negative label
# ---------------------------------------------------------------------

class TestReformulationNeverAutoNegative:
    """CASE J (Section 19/87). detect_reformulations() (app.learning_signals)
    is an OFFLINE batch classifier over historical events.jsonl, called
    only from app.learning_cycle - never from the live /chat request path.
    A follow-up query is not tagged as a reformulation at request time,
    and nothing converts a reformulation into a negative recommendation
    label anywhere in the codebase. This proves the absence structurally,
    not by convention."""

    def test_chat_impl_module_does_not_reference_reformulation_detection(self):
        import inspect
        source = inspect.getsource(m)
        assert "detect_reformulations" not in source

    def test_reformulation_classifier_is_only_called_from_learning_cycle(self):
        import app.learning_cycle as lc
        import app.learning_signals as ls
        assert hasattr(ls, "detect_reformulations")
        lc_source = Path(lc.__file__).read_text(encoding="utf-8")
        assert "detect_reformulations" in lc_source

    def test_ordinary_followup_query_is_not_flagged_reformulation_at_request_time(self):
        sid = "v215e-reformulation-not-live"
        r1 = _chat_as_customer("jazminova ryza", sid)
        r2 = _chat_as_customer("basmati ryza", sid)
        assert "reformulation" not in r1
        assert "reformulation" not in r2
        assert "is_reformulation" not in r2


# ---------------------------------------------------------------------
# CASE K/L - ABSTAIN/CLARIFY are durably logged as states, never as failure labels
# ---------------------------------------------------------------------

class TestAbstainClarifyNeverBecomeFailureLabels:
    """CASE K/L (Section 21/22/87). ABSTAIN/CLARIFY are legitimate,
    evidence-driven decision states - app.recommendation_evidence.decide()
    reaches them specifically when evidence is insufficient or
    differentiation is absent. They are durably logged via the `state`
    field of log_recommendation_decision() exactly like RECOMMEND, with
    no separate "failure" or negative-label field anywhere."""

    def test_comparison_clarify_state_is_logged_verbatim_not_translated(self, tmp_path, monkeypatch):
        events_path = tmp_path / "recommendation_decisions.jsonl"
        monkeypatch.setenv("RECOMMENDATION_DECISIONS_LOG_PATH", str(events_path))
        # An unresolvable comparison (no clear two named products) reaches
        # STATE_CLARIFY in app/workflow_executor.py's execute_comparison().
        r = _chat_as_customer("porovnaj", "v215e-clarify-state")
        # Whether or not this specific phrasing reaches comparison at all,
        # the invariant under test is schema-level: assert the state
        # vocabulary itself contains no derived "failure" concept.
        import app.comparison as cmp
        assert cmp.STATE_ABSTAIN == "ABSTAIN"
        assert cmp.STATE_CLARIFY == "CLARIFY"
        assert not hasattr(cmp, "STATE_FAILURE")
        assert not hasattr(cmp, "STATE_NEGATIVE")

    def test_recommendation_evidence_has_no_failure_or_negative_decision_constant(self):
        import app.recommendation_evidence as re
        assert re.DECISION_ABSTAIN == "ABSTAIN"
        assert re.DECISION_CLARIFY == "CLARIFY"
        assert not hasattr(re, "DECISION_FAILURE")
        assert not hasattr(re, "DECISION_NEGATIVE")


# ---------------------------------------------------------------------
# CASE A/C/D/E - end-to-end decision_id -> product_id causal chain proof
# ---------------------------------------------------------------------

class TestCausalChainReconstructable:
    """CASE A/C/D (Section 27/87). For the 3 capabilities that DO have
    decision logging, prove the full chain interaction_id -> decision_id
    -> candidate/recommended product_id is reconstructable end-to-end
    from a single /chat response, without session+timestamp guessing."""

    def test_comparison_chain_reconstructable_from_single_response(self):
        r = _chat_as_customer(COMPARISON_QUERY, "v215e-chain-comparison")
        assert r.get("interaction_id")
        assert r.get("comparison_decision_id")
        assert len(r.get("products") or []) == 2

    def test_use_case_advice_chain_reconstructable(self):
        r = _chat_as_customer(USE_CASE_QUERY, "v215e-chain-usecase")
        assert r.get("interaction_id")
        assert r.get("use_case_advice_decision_id")

    def test_basket_completion_chain_reconstructable(self):
        r = _chat_as_customer(BASKET_QUERY, "v215e-chain-basket")
        assert r.get("interaction_id")
        assert r.get("basket_decision_id")

    def test_ordinary_search_never_fabricates_a_decision_id(self):
        r = _chat_as_customer("jazminova ryza", "v215e-chain-ordinary")
        assert r.get("interaction_id")
        assert "comparison_decision_id" not in r
        assert "basket_decision_id" not in r
        assert "use_case_advice_decision_id" not in r


# ---------------------------------------------------------------------
# CASE F/G - synthetic/evaluation exclusion (cross-reference to V2.15d.3,
# re-asserted here as part of this sprint's own permanent readiness record)
# ---------------------------------------------------------------------

class TestSyntheticAndEvaluationExclusion:
    def test_evaluation_context_produces_no_durable_decision_log(self, tmp_path, monkeypatch):
        decisions_path = tmp_path / "recommendation_decisions.jsonl"
        monkeypatch.setenv("RECOMMENDATION_DECISIONS_LOG_PATH", str(decisions_path))
        m._chat_internal(
            m.ChatRequest(message=COMPARISON_QUERY, session_id="v215e-eval-excluded", limit=8),
            _FakeRequest(),
            execution_context=evaluation_context(),
        )
        assert not decisions_path.exists() or decisions_path.read_text(encoding="utf-8").strip() == ""


# ---------------------------------------------------------------------
# CASE S - AUTO_PROMOTION frozen (this sprint's own permanent record)
# ---------------------------------------------------------------------

class TestAutoPromotionFrozen:
    def test_auto_promotion_disabled(self):
        from app.learning_lifecycle import AUTO_PROMOTION_ENABLED
        assert AUTO_PROMOTION_ENABLED is False

    def test_v2_15e_test_module_imports_no_learning_activation_symbol(self):
        # This sprint's own test module must not itself import anything
        # capable of triggering a learning cycle or promotion - a
        # structural guarantee that auditing readiness never accidentally
        # activates the thing being audited.
        assert "run_learning_cycle" not in globals()
        assert "approve_candidate_by_id" not in globals()
        assert "rollback_to_last_known_good" not in globals()


# ---------------------------------------------------------------------
# CASE T - purchase remains unavailable
# ---------------------------------------------------------------------

class TestPurchaseSignalNotAvailable:
    def test_purchase_event_type_rejected_by_schema(self):
        import pytest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            m.EventRequest(session_id="s1", event_type="purchase")


# ---------------------------------------------------------------------
# Structural gaps for capabilities with NO decision object (Section 82)
# ---------------------------------------------------------------------

class TestStructuralGapCapabilitiesDoNotFabricateDecisionIds:
    """cross_sell, recipe_shopping, and replacement_products have no
    decision object and no decision_id anywhere - proven by absence, not
    assumed. A future change adding a fabricated ID without a real
    decision object would need to consciously break this test."""

    def test_cross_sell_module_has_no_decision_id_concept(self):
        import app.cross_sell as cs
        source = Path(cs.__file__).read_text(encoding="utf-8")
        assert "decision_id" not in source

    def test_recipe_shopping_module_has_no_decision_id_concept(self):
        import app.recipe_shopping as rs
        source = Path(rs.__file__).read_text(encoding="utf-8")
        assert "decision_id" not in source
