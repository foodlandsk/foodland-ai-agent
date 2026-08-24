"""
tests/test_feedback_decision_correlation_v2_15e_2.py  -  V2.15e.2:
Explicit Feedback -> Recommendation Decision Correlation & Signal
Integrity Closure.

GATE B (minimal widget propagation, ZERO backend schema change).

Audit finding (docs/feedback-decision-correlation-v2.15e.2.md):
app/widget.js's addFeedbackControls()/vote() fires
`{event_type: "feedback", rating, query}` only - it never sends
interaction_id/decision_id/result_set_id, even though EventRequest
(app/main.py) has ALREADY carried all three as generic, event_type-
agnostic optional fields since V2.15d/V2.15e.1, and log_event() ALREADY
persists them unconditionally for every event_type including "feedback".
The gap this sprint closes is purely that app/widget.js never populated
them for the feedback vote - there is no backend change here at all.

These tests characterize the BACKEND HALF of the correlation: the exact
data (comparison_decision_id/basket_decision_id/use_case_advice_decision_id/
result_set_id/interaction_id) that a /chat response exposes and that
app/widget.js's vote() now reads from the SAME response-local scope
that already computes `decisionId` for product-click correlation
(V2.15d.2) - see tests/js/widget.test.mjs for the frontend-side static
source-inspection proof that vote() actually propagates these values.

Feedback semantics are NOT redefined by this sprint: a thumbs vote rates
the just-rendered assistant response as a whole (existing UX copy:
"Bola tato odpoved uzitocna?"), not a specific product. decision_id is
attached ONLY when that exact response legitimately owns a recommendation
decision (comparison/use_case_advice/basket_completion) - never
fabricated for ordinary search, FAQ, or store_location.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import pytest
from pydantic import ValidationError

import app.main as m
from app.execution_context import customer_context, evaluation_context, admin_test_context


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat_as_customer(message: str, session_id: str, limit: int = 3) -> dict:
    return m._chat_internal(
        m.ChatRequest(message=message, session_id=session_id, limit=limit),
        _FakeRequest(),
        execution_context=customer_context(),
    )


def _decision_id_of(response: dict) -> str | None:
    # Mirrors app/widget.js's own resolution exactly (V2.15d.2):
    # data.comparison_decision_id || data.basket_decision_id ||
    # data.use_case_advice_decision_id || null
    return (
        response.get("comparison_decision_id")
        or response.get("basket_decision_id")
        or response.get("use_case_advice_decision_id")
        or None
    )


SEARCH_QUERY = "jazminova ryza"
COMPARISON_QUERY = "porovnaj Samyang Buldak a Nissin Demae Ramen"
BASKET_QUERY = "co potrebujem na sushi"
USE_CASE_QUERY = "ake kokosove mlieko na tom kha gai?"


# ---------------------------------------------------------------------
# A/B/C - legitimate decision-bearing capabilities expose a correlatable
# decision_id that the frontend vote() can now attach to feedback
# ---------------------------------------------------------------------

class TestLegitimateDecisionCorrelation:
    def test_comparison_response_exposes_decision_id(self):
        r = _chat_as_customer(COMPARISON_QUERY, "v215e2-a-comparison")
        assert r.get("intent") == "product_comparison"
        assert _decision_id_of(r)
        assert r.get("interaction_id")

    def test_use_case_advice_response_exposes_decision_id(self):
        r = _chat_as_customer(USE_CASE_QUERY, "v215e2-c-usecase")
        assert r.get("intent") == "use_case_advice"
        assert _decision_id_of(r)

    def test_basket_completion_response_exposes_decision_id(self):
        r = _chat_as_customer(BASKET_QUERY, "v215e2-d-basket")
        assert r.get("intent") == "basket_completion"
        assert _decision_id_of(r)


# ---------------------------------------------------------------------
# D/E/F - ordinary search / FAQ / store_location never fabricate one
# ---------------------------------------------------------------------

class TestNoFabricatedDecisionId:
    def test_ordinary_search_has_no_decision_id(self):
        r = _chat_as_customer(SEARCH_QUERY, "v215e2-e-ordinary")
        assert r.get("intent") == "product_search"
        assert _decision_id_of(r) is None
        assert r.get("interaction_id")

    def test_store_location_faq_has_no_decision_id(self):
        r = _chat_as_customer("Kde sa nachadza kamenna predajna?", "v215e2-f-store")
        assert r.get("intent") == "faq"
        assert _decision_id_of(r) is None
        assert r.get("interaction_id")


# ---------------------------------------------------------------------
# G - continuation ("Show More") feedback: honest result_set_id + fresh
# interaction_id, decision_id remains null (continuation is always
# ordinary product_search, which never legitimately owns a decision)
# ---------------------------------------------------------------------

class TestContinuationFeedbackAttribution:
    def test_continuation_response_has_stable_result_set_id_and_null_decision_id(self):
        sid = "v215e2-g-continuation"
        r1 = _chat_as_customer(SEARCH_QUERY, sid)
        r2 = _chat_as_customer("zobraz viac", sid)
        assert r2.get("intent") == "product_search"
        assert r2.get("result_set_id") == r1.get("result_set_id")
        assert r2.get("interaction_id") != r1.get("interaction_id")
        assert _decision_id_of(r2) is None


# ---------------------------------------------------------------------
# H/I - hard topic switch / multiple recommendation turns: each response
# is independently sourced, so a later feedback vote cannot inherit an
# earlier response's decision_id merely by being in the same session
# ---------------------------------------------------------------------

class TestNoStaleDecisionAcrossResponses:
    def test_hard_topic_switch_does_not_carry_previous_decision_id(self):
        sid = "v215e2-h-hardswitch"
        r1 = _chat_as_customer(COMPARISON_QUERY, sid)
        r2 = _chat_as_customer(SEARCH_QUERY, sid)
        assert _decision_id_of(r1)
        assert _decision_id_of(r2) is None

    def test_wrong_decision_negative_control_two_comparisons_get_distinct_ids(self):
        # CASE K (spec Sec.42): decision D1 then D2 in the same session -
        # feedback on the SECOND response must never be able to resolve
        # to the FIRST decision's id.
        sid = "v215e2-k-wrongdecision"
        r1 = _chat_as_customer(COMPARISON_QUERY, sid)
        r2 = _chat_as_customer("porovnaj Heinz kecup a Hellmans majonezu", sid)
        d1 = _decision_id_of(r1)
        d2 = _decision_id_of(r2)
        assert d1 and d2
        assert d1 != d2


# ---------------------------------------------------------------------
# J - reset: no correlation metadata survives
# ---------------------------------------------------------------------

class TestResetClearsAttribution:
    def test_reset_then_new_response_has_no_leftover_decision_id(self):
        sid = "v215e2-j-reset"
        _chat_as_customer(COMPARISON_QUERY, sid)
        _chat_as_customer("Zacnime odznova", sid)
        r3 = _chat_as_customer(SEARCH_QUERY, sid)
        assert _decision_id_of(r3) is None


# ---------------------------------------------------------------------
# Cross-session isolation
# ---------------------------------------------------------------------

class TestCrossSessionIsolation:
    def test_two_sessions_never_share_decision_id_or_interaction_id(self):
        r1 = _chat_as_customer(COMPARISON_QUERY, "v215e2-isolation-a")
        r2 = _chat_as_customer(COMPARISON_QUERY, "v215e2-isolation-b")
        assert _decision_id_of(r1) != _decision_id_of(r2)
        assert r1.get("interaction_id") != r2.get("interaction_id")


# ---------------------------------------------------------------------
# L/M - EventRequest backward compatibility + malformed optional IDs
# ---------------------------------------------------------------------

class TestEventRequestFeedbackCompatibility:
    def test_legacy_feedback_event_without_any_correlation_fields_still_valid(self):
        req = m.EventRequest(session_id="s1", event_type="feedback", rating=1)
        assert req.interaction_id is None
        assert req.decision_id is None
        assert req.result_set_id is None

    def test_feedback_event_accepts_full_correlation_triplet(self):
        req = m.EventRequest(
            session_id="s1",
            event_type="feedback",
            rating=-1,
            interaction_id="abc123",
            decision_id="def456",
            result_set_id="ghi789",
        )
        assert req.interaction_id == "abc123"
        assert req.decision_id == "def456"
        assert req.result_set_id == "ghi789"

    def test_rating_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            m.EventRequest(session_id="s1", event_type="feedback", rating=2)

    def test_overlong_decision_id_rejected_not_silently_truncated(self):
        with pytest.raises(ValidationError):
            m.EventRequest(session_id="s1", event_type="feedback", decision_id="x" * 33)

    def test_malformed_but_in_range_decision_id_accepted_without_crash(self):
        # The backend never validates decision_id AGAINST a real decision
        # record at write time - it is opaque correlation metadata, not
        # a foreign key. A garbage-but-length-valid string must not crash.
        req = m.EventRequest(session_id="s1", event_type="feedback", decision_id="not-a-real-decision-id")
        assert req.decision_id == "not-a-real-decision-id"


# ---------------------------------------------------------------------
# N/O/P - execution-context isolation for feedback specifically
# ---------------------------------------------------------------------

class TestExecutionContextIsolationForFeedback:
    def test_customer_feedback_is_durably_logged(self, tmp_path, monkeypatch):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        req = m.EventRequest(session_id="s1", event_type="feedback", rating=1, decision_id="d1")
        m.log_event(req, "ck", execution_context=customer_context())
        rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert rows[0]["event_type"] == "feedback"
        assert rows[0]["decision_id"] == "d1"
        assert rows[0]["execution_context"] == "CUSTOMER"
        assert rows[0]["learning_eligible"] is True

    def test_evaluation_context_feedback_never_durably_logged(self, tmp_path, monkeypatch):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        req = m.EventRequest(session_id="s1", event_type="feedback", rating=1)
        m.log_event(req, "ck", execution_context=evaluation_context())
        assert not events_path.exists() or events_path.read_text(encoding="utf-8").strip() == ""

    def test_admin_test_feedback_logged_but_marked_learning_ineligible(self, tmp_path, monkeypatch):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        req = m.EventRequest(session_id="s1", event_type="feedback", rating=1, decision_id="d1")
        m.log_event(req, "ck", execution_context=admin_test_context())
        rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert rows[0]["execution_context"] == "ADMIN_TEST"
        assert rows[0]["learning_eligible"] is False


# ---------------------------------------------------------------------
# Q/R - AUTO_PROMOTION freeze + storage failure isolation
# ---------------------------------------------------------------------

class TestAutoPromotionUnchanged:
    def test_auto_promotion_still_disabled(self):
        from app.learning_lifecycle import AUTO_PROMOTION_ENABLED
        assert AUTO_PROMOTION_ENABLED is False


class TestFeedbackStorageFailureIsolation:
    def test_unwritable_events_path_does_not_raise_for_feedback_event(self, monkeypatch):
        monkeypatch.setenv("EVENTS_LOG_PATH", "Z:\\definitely\\not\\writable\\events.jsonl")
        req = m.EventRequest(session_id="s1", event_type="feedback", rating=1, decision_id="d1")
        m.log_event(req, "ck", execution_context=customer_context())  # must not raise


# ---------------------------------------------------------------------
# Permanent regression controls (unchanged from V2.15e.1)
# ---------------------------------------------------------------------

class TestControlRegressionMatrix:
    def test_rt0004_related_products_protected(self):
        r = _chat_as_customer("súvisiace produkty k sushi ryži", "v215e2-rt0004")
        assert r.get("intent") == "related_products"

    def test_rt0010_allergen_safety_protected(self):
        r = _chat_as_customer("sójová omáčka bez sóje", "v215e2-rt0010")
        assert r.get("intent") == "allergen_safety"

    def test_rt0011_no_session_contamination(self):
        sid = "v215e2-rt0011"
        query = "mám rád nepálivé jedlo, čo odporúčaš?"
        first = _chat_as_customer(query, sid)
        second = _chat_as_customer(query, sid)
        assert first.get("intent") == "product_search"
        assert second.get("intent") == "product_search"

    def test_rt0013_replacement_products_protected(self):
        r = _chat_as_customer("náhrada za rybiu omáčku vegan", "v215e2-rt0013")
        assert r.get("intent") == "replacement_products"

    def test_v2_15c_store_location_followup_still_live(self):
        sid = "v215e2-store-followup"
        _chat_as_customer("Kde sa nachadza kamenna predajna?", sid)
        r = _chat_as_customer("Prilož mi Google link na adresu.", sid)
        assert r.get("intent") == "faq"
        assert "maps.app.goo.gl" in (r.get("answer") or "")

    def test_v2_15e_1_resultset_continuation_still_correct(self):
        sid = "v215e2-resultset-control"
        r1 = _chat_as_customer(SEARCH_QUERY, sid)
        r2 = _chat_as_customer("zobraz viac", sid)
        assert r2.get("result_set_id") == r1.get("result_set_id")
        assert r2.get("interaction_id") != r1.get("interaction_id")
