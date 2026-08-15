"""
tests/test_workflow_registry.py  -  Sprint V2.7 Workflow & Orchestration
Migration.

Two layers: (1) app.workflow_registry.select_workflow() tested directly
against synthetic-but-realistic RoutingSignals (Section 44's mandatory
scenarios, precedence, routing conflicts); (2) a handful of real
end-to-end app.main.chat() calls confirming the wiring actually labels
production turns correctly without changing their existing behavior
(Section 20 - shadow-safe by construction).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.workflow_registry import (  # noqa: E402
    ATTRIBUTE_SEARCH,
    CATEGORY_BROWSE,
    COMPARISON,
    FAQ_INFORMATIONAL,
    LEGACY,
    LEGACY_FALLBACK,
    MIGRATED,
    ORDER_TRACKING,
    PRODUCT_LOOKUP,
    RECIPE_SHOPPING,
    REPLACEMENT,
    SHADOW,
    SUPPORT_ESCALATION,
    USE_CASE_ADVICE,
    WORKFLOWS,
    RoutingSignals,
    select_workflow,
)


class TestRequiredScenarios:
    """Section 44 - the mandatory mapping table, verbatim."""

    def test_jazminova_ryza_is_attribute_search(self):
        signals = RoutingSignals(
            message="jazmínová ryža",
            structured_answer_strategy="FILTERED_PRODUCT_LIST",
            structured_has_explicit_attributes=True,
        )
        result = select_workflow(signals)
        assert result.workflow_id == ATTRIBUTE_SEARCH

    def test_aku_ryzu_na_sushi_is_use_case(self):
        signals = RoutingSignals(
            message="akú ryžu na sushi?",
            structured_answer_strategy="FILTERED_PRODUCT_LIST",
            structured_has_explicit_attributes=True,
            cross_sell_context_type="USE_CASE_COMPLETION",
        )
        result = select_workflow(signals)
        assert result.workflow_id == USE_CASE_ADVICE

    def test_jazminova_alebo_basmati_is_comparison(self):
        signals = RoutingSignals(message="jazmínová alebo basmati?", faq_answer_found=True)
        result = select_workflow(signals)
        assert result.workflow_id == COMPARISON

    def test_alternativa_kikkoman_is_replacement(self):
        signals = RoutingSignals(message="alternatíva Kikkoman", replacement_subject="sojova_omacka")
        result = select_workflow(signals)
        assert result.workflow_id == REPLACEMENT

    def test_pad_thai_shopping_is_recipe_shopping(self):
        signals = RoutingSignals(message="čo potrebujem na Pad Thai?", recipe_subject="pad_thai")
        result = select_workflow(signals)
        assert result.workflow_id == RECIPE_SHOPPING

    def test_co_je_miso_is_faq(self):
        signals = RoutingSignals(message="čo je miso?", faq_answer_found=True)
        result = select_workflow(signals)
        assert result.workflow_id == FAQ_INFORMATIONAL

    def test_broad_ryza_is_category_browse(self):
        signals = RoutingSignals(message="ryža", structured_answer_strategy="GROUPED_DISCOVERY")
        result = select_workflow(signals)
        assert result.workflow_id == CATEGORY_BROWSE

    def test_exact_brand_size_is_product_lookup(self):
        signals = RoutingSignals(message="FOODLAND jazmínová ryža 5 kg", structured_answer_strategy="EXACT_MATCH")
        result = select_workflow(signals)
        assert result.workflow_id == PRODUCT_LOOKUP


class TestFallback:
    """Section 47 - unknown/unsupported query safely falls back."""

    def test_unrecognized_message_falls_back(self):
        signals = RoutingSignals(message="xyz totally unrecognized nonsense")
        result = select_workflow(signals)
        assert result.workflow_id == LEGACY_FALLBACK

    def test_out_of_domain_falls_back(self):
        signals = RoutingSignals(message="aky je najlepsi film?", out_of_domain=True)
        result = select_workflow(signals)
        assert result.workflow_id == LEGACY_FALLBACK


class TestPrecedence:
    """Section 49 - deterministic precedence derived from the actual
    app/main.py cascade order, highest-priority signal wins."""

    def test_replacement_outranks_related_subject(self):
        """Section 48 routing conflict: "akú alternatívu ku Kikkoman na
        sushi?" carries BOTH a replacement signal and sushi/use-case
        context - replacement_subject is checked earlier in the real
        cascade, so it must win."""
        signals = RoutingSignals(
            message="aku alternativu ku kikkoman na sushi",
            replacement_subject="sojova_omacka",
            related_subject="sushi",
            structured_answer_strategy="FILTERED_PRODUCT_LIST",
            cross_sell_context_type="USE_CASE_COMPLETION",
        )
        result = select_workflow(signals)
        assert result.workflow_id == REPLACEMENT

    def test_recipe_subject_outranks_category_discovery(self):
        signals = RoutingSignals(recipe_subject="pad_thai", is_category_discovery=True)
        result = select_workflow(signals)
        assert result.workflow_id == RECIPE_SHOPPING

    def test_allergen_outranks_faq(self):
        signals = RoutingSignals(allergen_term="lepok", faq_answer_found=True)
        result = select_workflow(signals)
        assert result.workflow_id == FAQ_INFORMATIONAL
        assert result.reason == "allergen_safety_question"

    def test_special_subject_plain_rice_uses_structured_strategy(self):
        signals = RoutingSignals(
            special_subject="plain_rice",
            structured_answer_strategy="FILTERED_PRODUCT_LIST",
            structured_has_explicit_attributes=True,
        )
        result = select_workflow(signals)
        assert result.workflow_id == ATTRIBUTE_SEARCH

    def test_other_special_subject_stays_legacy(self):
        signals = RoutingSignals(special_subject="kimchi_product")
        result = select_workflow(signals)
        assert result.workflow_id == LEGACY_FALLBACK
        assert "kimchi_product" in result.reason


class TestDeterminism:
    """Section 34 - same signals always select the same workflow."""

    def test_repeated_calls_are_identical(self):
        signals = RoutingSignals(message="jazminova ryza", structured_answer_strategy="FILTERED_PRODUCT_LIST", structured_has_explicit_attributes=True)
        first = select_workflow(signals)
        second = select_workflow(signals)
        assert first.workflow_id == second.workflow_id
        assert first.confidence == second.confidence
        assert first.reason == second.reason


class TestOrderSupportNeverCrossSell:
    """Section 18/45 - order/support workflows must never enable cross-sell,
    even though Foodland has no such capability implemented yet (Section 80 -
    do not invent it; the contract still declares the safe default)."""

    def test_order_tracking_cross_sell_disabled(self):
        assert WORKFLOWS[ORDER_TRACKING].cross_sell_policy == "disabled"
        assert WORKFLOWS[ORDER_TRACKING].migration_status == LEGACY

    def test_support_escalation_cross_sell_disabled(self):
        assert WORKFLOWS[SUPPORT_ESCALATION].cross_sell_policy == "disabled"
        assert WORKFLOWS[SUPPORT_ESCALATION].migration_status == LEGACY


class TestWorkflowContractIntegrity:
    def test_every_workflow_has_complete_contract(self):
        for workflow_id, contract in WORKFLOWS.items():
            assert contract.workflow_id == workflow_id
            assert contract.migration_status in {MIGRATED, SHADOW, LEGACY}
            assert contract.cross_sell_policy in {"conservative", "enabled", "suppressed", "disabled"}
            assert contract.supported_intents
            assert contract.retrieval_strategy
            assert contract.presentation_strategy
            assert contract.grounding
            assert contract.fallback_behavior

    def test_migrated_workflows_are_exactly_the_first_activation_set(self):
        """Section 67 - PRODUCT_LOOKUP/CATEGORY_BROWSE/ATTRIBUTE_SEARCH
        first, nothing else claims MIGRATED yet this sprint."""
        migrated = {wf_id for wf_id, c in WORKFLOWS.items() if c.migration_status == MIGRATED}
        assert migrated == {PRODUCT_LOOKUP, CATEGORY_BROWSE, ATTRIBUTE_SEARCH}

    def test_comparison_and_replacement_suppress_cross_sell(self):
        """Section 14/15/38."""
        assert WORKFLOWS[COMPARISON].cross_sell_policy == "suppressed"
        assert WORKFLOWS[REPLACEMENT].cross_sell_policy == "suppressed"

    def test_faq_suppresses_cross_sell(self):
        """Section 17/39."""
        assert WORKFLOWS[FAQ_INFORMATIONAL].cross_sell_policy == "suppressed"


class TestRealChatIntegration:
    """End-to-end: the wiring in app/main.py actually labels real turns
    without changing what they return (Section 20 shadow-safety)."""

    @staticmethod
    def _chat():
        import app.main as m
        return m

    class _FakeRequest:
        class client:
            host = "127.0.0.1"
        headers = {}

    def test_jazminova_ryza_labeled_attribute_search_live(self):
        m = self._chat()
        cr = m.ChatRequest(message="jazminova ryza", session_id="wf-test-1", limit=4)
        response = m.chat(cr, self._FakeRequest())
        assert response.get("workflow_id") == ATTRIBUTE_SEARCH
        assert response.get("products")  # primary results still returned normally

    def test_broad_ryza_labeled_category_browse_live(self):
        m = self._chat()
        cr = m.ChatRequest(message="ryza", session_id="wf-test-2", limit=4)
        response = m.chat(cr, self._FakeRequest())
        assert response.get("workflow_id") == CATEGORY_BROWSE

    def test_sushi_use_case_labeled_live(self):
        m = self._chat()
        cr = m.ChatRequest(message="ryza na sushi", session_id="wf-test-3", limit=4)
        response = m.chat(cr, self._FakeRequest())
        assert response.get("workflow_id") == USE_CASE_ADVICE

    def test_show_all_continuation_has_no_workflow_id(self):
        """Section 44/55 - continuation bypasses workflow selection
        entirely, it is not a fresh workflow decision."""
        m = self._chat()
        cr1 = m.ChatRequest(message="jazminova ryza", session_id="wf-test-4", limit=4)
        m.chat(cr1, self._FakeRequest())
        cr2 = m.ChatRequest(message="zobraz vsetky", session_id="wf-test-4", limit=4)
        response2 = m.chat(cr2, self._FakeRequest())
        assert response2.get("response_mode") == "result_set_continuation"
        assert "workflow_id" not in response2

    def test_context_switch_does_not_leak_workflow(self):
        """Section 32/46 - switching topic must not preserve a stale
        USE_CASE_ADVICE/attribute label from an unrelated earlier turn."""
        m = self._chat()
        cr1 = m.ChatRequest(message="ryza na sushi", session_id="wf-test-5", limit=4)
        r1 = m.chat(cr1, self._FakeRequest())
        assert r1.get("workflow_id") == USE_CASE_ADVICE

        cr2 = m.ChatRequest(message="kikkoman sojova omacka 1000 ml", session_id="wf-test-5", limit=4)
        r2 = m.chat(cr2, self._FakeRequest())
        assert r2.get("workflow_id") == PRODUCT_LOOKUP
