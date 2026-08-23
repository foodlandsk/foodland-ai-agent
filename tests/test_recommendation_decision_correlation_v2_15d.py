"""
tests/test_recommendation_decision_correlation_v2_15d.py  -  V2.15d:
durable recommendation decision logging & frontend conversion
correlation (GATE A).

Hard safety boundary (unchanged, verified here): no ranking change, no
learning activation, no AUTO_PROMOTION change, no customer-facing
recommendation/retrieval behavior change. This sprint is OBSERVABILITY
ONLY.

Repository-reality audit (4 parallel Explore agents) found that
comparison_decision_id / use_case_advice_decision_id / basket_decision_id
already existed (V2.15b), were already returned to the frontend, but
were - per the code's own comment - "generated and returned, not yet
persisted anywhere on its own". Separately, interaction_id (also V2.15b)
was generated once per /chat request but never threaded into the 3
V2.14 workflow executors' own log_question() calls, so their durable
question_analytics.jsonl rows always carried an empty interaction_id
despite the response payload carrying a real one.

This sprint closes both gaps with the smallest safe mechanism:

1. app.main.log_recommendation_decision() - a new, separate durable
   JSONL stream (recommendation_decisions.jsonl, via
   app.storage_paths.resolve_path() per the V2.15b normalization
   convention) correlating interaction_id + decision_id + candidate/
   recommended product ids + reason_codes/confidence + execution
   context. Called from app.workflow_executor's execute_comparison/
   execute_use_case_advice/execute_basket_completion, gated on a new
   `should_log_decision` flag (True for CUSTOMER and ADMIN_TEST only -
   never EVALUATION/LEARNING/SHADOW, which run at test-suite scale and
   must not be written to disk on every call, mirroring the existing
   emit_customer_analytics precedent). Every record carries an explicit
   `learning_eligible` flag, True only for genuine CUSTOMER traffic -
   ADMIN_TEST smoke-test records are logged (so a live production
   verification can be read back durably) but always tagged
   learning_eligible=False, so no event becomes a training label merely
   by existing (Section 32 of the closure spec).

2. interaction_id is now passed through to the 3 executors' existing
   log_question() calls, so question_analytics.jsonl rows for
   comparison/use_case_advice/basket_completion turns now correlate to
   the same interaction_id already present in the response.

GATE DECISION: frontend product-click/add-to-cart correlation
(app/widget.js) is explicitly NOT_SAFE_TO_IMPLEMENT_THIS_SPRINT - there
is no JavaScript test infrastructure in this repository (confirmed: no
package.json, no *.test.js) AND no Node.js runtime is available in this
environment to even syntax-check a change to the 2041-line, customer-
facing, production widget file. EventRequest/log_event were still
extended with optional (default-None, backward-compatible)
interaction_id/decision_id/event_id fields so a FUTURE sprint with
proper JS tooling can wire the frontend without a breaking schema
change - app/widget.js itself is untouched, consistent with the same
call made in V2.15b.
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
from app.execution_context import admin_test_context, customer_context, evaluation_context


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat_as(message: str, session_id: str, execution_context, limit: int = 8) -> dict:
    return m._chat_internal(
        m.ChatRequest(message=message, session_id=session_id, limit=limit),
        _FakeRequest(),
        execution_context=execution_context,
    )


COMPARISON_QUERY = "porovnaj Samyang Buldak a Nissin Demae Ramen"
BASKET_QUERY = "co potrebujem na sushi"
USE_CASE_QUERY = "ake kokosove mlieko na tom kha gai?"


def _read_decisions(data_dir: Path) -> list[dict]:
    path = data_dir / "recommendation_decisions.jsonl"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class TestDecisionLoggingComparison:
    def test_customer_comparison_logs_a_decision(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FOODLAND_DATA_DIR", str(tmp_path))
        r = _chat_as(COMPARISON_QUERY, "v215d-cmp-a", customer_context())
        assert r.get("intent") == "product_comparison"
        records = _read_decisions(tmp_path)
        assert len(records) == 1
        rec = records[0]
        assert rec["decision_type"] == "comparison"
        assert rec["decision_id"] == r["comparison_decision_id"]
        assert rec["interaction_id"] == r["interaction_id"]
        assert rec["learning_eligible"] is True
        assert rec["state"] == r["comparison_decision"]
        assert len(rec["candidate_product_ids"]) == 2


class TestDecisionLoggingBasketCompletion:
    def test_customer_basket_logs_a_decision(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FOODLAND_DATA_DIR", str(tmp_path))
        r = _chat_as(BASKET_QUERY, "v215d-basket-a", customer_context())
        assert r.get("intent") == "basket_completion"
        records = _read_decisions(tmp_path)
        assert len(records) == 1
        rec = records[0]
        assert rec["decision_type"] == "basket_completion"
        assert rec["decision_id"] == r["basket_decision_id"]
        assert rec["interaction_id"] == r["interaction_id"]
        assert rec["use_case"] == r["basket_use_case"]
        assert rec["learning_eligible"] is True


class TestDecisionLoggingUseCaseAdvice:
    def test_customer_use_case_advice_logs_a_decision(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FOODLAND_DATA_DIR", str(tmp_path))
        r = _chat_as(USE_CASE_QUERY, "v215d-usecase-a", customer_context())
        assert r.get("intent") == "use_case_advice"
        records = _read_decisions(tmp_path)
        assert len(records) == 1
        rec = records[0]
        assert rec["decision_type"] == "use_case_advice"
        assert rec["decision_id"] == r["use_case_advice_decision_id"]
        assert rec["interaction_id"] == r["interaction_id"]
        assert rec["learning_eligible"] is True


class TestExecutionContextIsolation:
    """Section 28/29/32 of the closure spec - EVALUATION/LEARNING/SHADOW
    must never write to this stream at all (test-suite-scale volume);
    ADMIN_TEST DOES write (so live production smoke traffic can be read
    back durably) but is always tagged learning_eligible=False - no
    smoke/internal traffic is ever misclassified as customer learning
    data."""

    def test_evaluation_context_does_not_log(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FOODLAND_DATA_DIR", str(tmp_path))
        r = _chat_as(COMPARISON_QUERY, "v215d-eval-a", evaluation_context())
        assert r.get("intent") == "product_comparison"
        assert _read_decisions(tmp_path) == []

    def test_admin_test_context_logs_but_not_learning_eligible(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FOODLAND_DATA_DIR", str(tmp_path))
        r = _chat_as(COMPARISON_QUERY, "v215d-admin-a", admin_test_context())
        assert r.get("intent") == "product_comparison"
        records = _read_decisions(tmp_path)
        assert len(records) == 1
        assert records[0]["learning_eligible"] is False
        assert records[0]["interaction_id"] == r["interaction_id"]


class TestInteractionIdPropagationFix:
    """Before V2.15d, the 3 V2.14 executors' log_question() calls never
    received interaction_id at all - question_analytics.jsonl rows for
    comparison/use_case_advice/basket_completion turns always carried an
    empty string despite the response payload carrying a real one. This
    is the fix, proven directly against the durable file."""

    def test_comparison_question_analytics_row_has_matching_interaction_id(self, tmp_path, monkeypatch):
        qa_path = tmp_path / "question_analytics.jsonl"
        monkeypatch.setenv("ANALYTICS_LOG_PATH", str(qa_path))
        r = _chat_as(COMPARISON_QUERY, "v215d-qa-cmp", customer_context())
        rows = [json.loads(line) for line in qa_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        matching = [row for row in rows if row["session_id"] == "v215d-qa-cmp"]
        assert matching
        assert matching[-1]["interaction_id"] == r["interaction_id"]
        assert matching[-1]["interaction_id"] != ""


class TestFailureIsolation:
    """Section 44/45 of the closure spec - a durable-logging failure
    must never break the customer-facing response."""

    def test_unwritable_decision_log_path_does_not_break_chat(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FOODLAND_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("RECOMMENDATION_DECISIONS_LOG_PATH", "Z:\\definitely\\not\\writable\\recdec.jsonl")
        r = _chat_as(COMPARISON_QUERY, "v215d-failtest", customer_context())
        assert r.get("intent") == "product_comparison"
        assert r.get("comparison_decision_id")


class TestNoFabricatedDecisionIds:
    """Section 11 of the closure spec - decision IDs must represent real
    decision objects. An ordinary product_search turn (no comparison/
    use_case/basket decision at all) must produce zero rows in the new
    decision-log stream."""

    def test_ordinary_product_search_logs_no_decision(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FOODLAND_DATA_DIR", str(tmp_path))
        r = _chat_as("jazminova ryza", "v215d-plain-search", customer_context())
        assert r.get("intent") == "product_search"
        assert _read_decisions(tmp_path) == []


class TestAutoPromotionUnchanged:
    """Section 63 of the closure spec - a hard release gate."""

    def test_auto_promotion_still_disabled(self):
        from app.learning_lifecycle import AUTO_PROMOTION_ENABLED
        assert AUTO_PROMOTION_ENABLED is False


class TestEventRequestBackwardCompatibility:
    """Section 27 - additive schema evolution only. Existing /events
    payloads (no interaction_id/decision_id/event_id at all - the
    current, unmodified app/widget.js never sends them) must remain
    valid, and the new fields default to None."""

    def test_event_request_without_new_fields_still_valid(self):
        req = m.EventRequest(session_id="s1", event_type="click", product_sku="SKU1")
        assert req.interaction_id is None
        assert req.decision_id is None
        assert req.event_id is None

    def test_event_request_accepts_new_optional_fields(self):
        req = m.EventRequest(
            session_id="s1", event_type="click", product_sku="SKU1",
            interaction_id="abc123", decision_id="def456", event_id="ghi789",
        )
        assert req.interaction_id == "abc123"
        assert req.decision_id == "def456"
        assert req.event_id == "ghi789"

    def test_log_event_persists_new_optional_fields(self, tmp_path, monkeypatch):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        req = m.EventRequest(
            session_id="s1", event_type="click", product_sku="SKU1",
            interaction_id="abc123", decision_id="def456", event_id="ghi789",
        )
        m.log_event(req, "client-key-1")
        rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert rows[-1]["interaction_id"] == "abc123"
        assert rows[-1]["decision_id"] == "def456"
        assert rows[-1]["event_id"] == "ghi789"


class TestControlRegressionMatrix:
    """Section 51 of the closure spec - must-preserve controls,
    unaffected by this purely-additive observability sprint."""

    def test_rt0004_related_products_protected(self):
        r = m.chat(m.ChatRequest(message="súvisiace produkty k sushi ryži", session_id="v215d-rt0004"), _FakeRequest())
        assert r.get("intent") == "related_products"

    def test_rt0010_allergen_safety_protected(self):
        r = m.chat(m.ChatRequest(message="sójová omáčka bez sóje", session_id="v215d-rt0010"), _FakeRequest())
        assert r.get("intent") == "allergen_safety"

    def test_rt0011_no_session_contamination(self):
        sid = "v215d-rt0011"
        query = "mám rád nepálivé jedlo, čo odporúčaš?"
        first = m.chat(m.ChatRequest(message=query, session_id=sid), _FakeRequest())
        second = m.chat(m.ChatRequest(message=query, session_id=sid), _FakeRequest())
        assert first.get("intent") == "product_search"
        assert second.get("intent") == "product_search"

    def test_rt0013_replacement_products_protected(self):
        r = m.chat(m.ChatRequest(message="náhrada za rybiu omáčku vegan", session_id="v215d-rt0013"), _FakeRequest())
        assert r.get("intent") == "replacement_products"

    def test_v2_15c_store_location_followup_still_live(self):
        sid = "v215d-store-followup"
        m.chat(m.ChatRequest(message="Kde sa nachadza kamenna predajna?", session_id=sid), _FakeRequest())
        r = m.chat(m.ChatRequest(message="Prilož mi Google link na adresu.", session_id=sid), _FakeRequest())
        assert r.get("intent") == "faq"
        assert r.get("products") == []

    def test_v2_15c_hard_switch_still_protected(self):
        sid = "v215d-store-hardswitch"
        m.chat(m.ChatRequest(message="Kde sa nachadza kamenna predajna?", session_id=sid), _FakeRequest())
        r = m.chat(m.ChatRequest(message="Poslite mi Kikkoman sojovu omacku", session_id=sid), _FakeRequest())
        assert r.get("intent") == "product_search"

    def test_comparison_still_returns_decision_fields(self):
        r = m.chat(m.ChatRequest(message=COMPARISON_QUERY, session_id="v215d-ctrl-cmp"), _FakeRequest())
        assert r.get("intent") == "product_comparison"
        assert r.get("comparison_decision_id")

    def test_basket_completion_still_returns_decision_fields(self):
        r = m.chat(m.ChatRequest(message=BASKET_QUERY, session_id="v215d-ctrl-basket"), _FakeRequest())
        assert r.get("intent") == "basket_completion"
        assert r.get("basket_decision_id")
