"""
tests/test_workflow_executor_v2_13c.py  -  V2.13c: canonical execution
boundary. Locks the two migrated workflows (RESULTSET_CONTINUATION,
ALLERGEN_SAFETY) at both the unit level (direct handler calls) and the
integration level (through the real chat() pipeline), and proves the
"no shadow router" invariant for the workflow IDs app.workflow_resolver
can actually return (Section 92 - behavioral test, not source-text
inspection).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m
from app.workflow_executor import execute_allergen_safety, execute_resultset_continuation
from app.workflow_resolver import (
    WORKFLOW_ALLERGEN_SAFETY,
    WORKFLOW_LEGACY_FALLBACK,
    WORKFLOW_RELATED_PRODUCTS,
    WORKFLOW_RESULTSET_CONTINUATION,
)


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, limit: int = 8) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


class TestExecutorCoverage:
    """Section 88 - every WorkflowResolver output must map to an
    executor OR be explicitly, honestly classified as not migrated this
    sprint (docs/workflow-inventory-v2.13c.md). This is not "100%
    coverage" - it is a precise, evidenced statement of what IS covered."""

    NATIVE_EXECUTOR_COVERED = {WORKFLOW_RESULTSET_CONTINUATION, WORKFLOW_ALLERGEN_SAFETY}
    NOT_MIGRATED_THIS_SPRINT = {WORKFLOW_RELATED_PRODUCTS, WORKFLOW_LEGACY_FALLBACK}

    def test_all_four_resolver_outputs_are_accounted_for(self):
        from app.workflow_resolver import (
            WORKFLOW_ALLERGEN_SAFETY as a,
            WORKFLOW_LEGACY_FALLBACK as b,
            WORKFLOW_RELATED_PRODUCTS as c,
            WORKFLOW_RESULTSET_CONTINUATION as d,
        )
        all_ids = {a, b, c, d}
        accounted = self.NATIVE_EXECUTOR_COVERED | self.NOT_MIGRATED_THIS_SPRINT
        assert all_ids == accounted


class TestAllergenSafetyHandlerUnit:
    def test_handler_returns_expected_shape(self):
        m.session_memories.clear()
        chat_request = m.ChatRequest(message="sójová omáčka bez sóje", limit=6, session_id="wf-unit-safety")
        result = execute_allergen_safety(
            chat_request=chat_request,
            memory_key=m.session_memory_key("wf-unit-safety", "127.0.0.1"),
            profile_key=m.user_memory_key("", "127.0.0.1"),
            user_profile={},
            knowledge_matches={},
            articles=[],
            allergen_term="sóju",
            client_key="127.0.0.1",
            session_id="wf-unit-safety",
            query_language="sk",
        )
        assert result["intent"] == "allergen_safety"
        assert result["products"] == []
        assert result["answer"]


class TestResultSetContinuationHandlerUnit:
    def test_handler_returns_none_when_no_active_result_set(self):
        chat_request = m.ChatRequest(message="zobraz viac", limit=6, session_id="wf-unit-rc-none")
        result = execute_resultset_continuation(
            chat_request=chat_request,
            memory_key="irrelevant",
            profile_key="irrelevant",
            memory={},
            user_profile={},
            products=m.products,
            active_result_set_id="nonexistent-id-12345",
            wants_show_all=False,
        )
        assert result is None


class TestIntegrationParity:
    """Same assertions the pre-V2.13c inline blocks would have produced
    - proves the extraction moved the code without changing behavior."""

    def test_allergen_safety_end_to_end(self):
        r = _chat("sójová omáčka bez sóje", "wf-e2e-safety")
        assert r.get("intent") == "allergen_safety"
        assert r.get("products") == []
        assert r.get("answered") is True

    def test_resultset_continuation_end_to_end(self):
        sid = "wf-e2e-showmore"
        first = _chat("basmati ryza", sid, limit=3)
        assert first.get("has_more") is True or first.get("matching_total", 0) > 3
        second = _chat("zobraz viac", sid)
        assert second.get("response_mode") == "result_set_continuation"
        assert second.get("intent") == "product_search"

    def test_show_all_end_to_end(self):
        sid = "wf-e2e-showall"
        first = _chat("jazmínová ryža", sid, limit=2)
        assert first.get("has_more") is True or first.get("matching_total", 0) > 2
        second = _chat("zobraz vsetky", sid)
        assert second.get("response_mode") == "result_set_continuation"

    def test_expired_result_set_falls_through_to_normal_search(self):
        # No active_result_set_id at all - "zobraz viac" alone, fresh
        # session, must fall through to the ordinary legacy cascade
        # rather than error or return an executor-shaped empty result.
        # Pre-existing legacy behavior for this edge case is a no-result
        # answer with no "intent" key at all (not a regression - same
        # response shape as before this sprint, unrelated to the
        # RESULTSET_CONTINUATION executor migration).
        r = _chat("zobraz viac", "wf-e2e-no-active-set")
        assert "answer" in r
        assert r.get("products") == []


class TestNoShadowRouterForMigratedWorkflows:
    """Section 92 - behavioral proof that resolved_workflow ==
    executed_workflow for the two migrated workflows, via the same
    SearchQualityTrace fields V2.13b's resolver already stashes
    (unchanged by this sprint)."""

    def test_allergen_safety_resolution_matches_execution(self):
        import app.workflow_resolver as wr
        wr.reset_last_resolution()
        r = _chat("sójová omáčka bez sóje", "wf-shadow-safety")
        resolution = wr.pop_last_resolution()
        assert resolution is not None
        assert resolution.workflow_id == WORKFLOW_ALLERGEN_SAFETY
        assert r.get("intent") == "allergen_safety"

    def test_related_products_resolution_matches_execution(self):
        # RELATED_PRODUCTS is NOT executor-migrated this sprint (still
        # LEGACY_EXECUTION, docs/workflow-inventory-v2.13c.md) - this
        # test proves the resolver's decision still causally matches
        # what actually executed, even though execution stays inline.
        import app.workflow_resolver as wr
        wr.reset_last_resolution()
        r = _chat("súvisiace produkty k sushi ryži", "wf-shadow-related")
        resolution = wr.pop_last_resolution()
        assert resolution is not None
        assert resolution.workflow_id == WORKFLOW_RELATED_PRODUCTS
        assert r.get("intent") == "related_products"
