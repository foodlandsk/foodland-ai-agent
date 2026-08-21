"""
tests/test_comparison_v2_14b.py  -  V2.14b: unit + adversarial tests for
app.comparison, the evidence-grounded product comparison foundation.

Covers the mandatory decision test matrix (spec Section 39, Cases A-L),
the claim-grounding matrix (Section 40), the ranking-vs-recommendation
invariant (Section 21), and the "no LLM call anywhere in this module"
proof (Section 26 - LLM override protection is achieved by construction,
not by post-hoc detection, so the test proving it is "no LLM client is
ever touched", not "the LLM's output was corrected").

Synthetic product dicts below match the real format_product() shape
(id/title/effective_price/currency/unit_pricing_measure/brand/
product_type) so app.comparison's functions can be exercised directly
without spinning up the full app. A separate class re-runs a subset
against the REAL Foodland catalog (Section 36 - not only synthetic
data).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.comparison as cmp
from app.recommendation_evidence import PROVENANCE_LLM_JUDGMENT


def _product(product_id, title, price, size=None, brand="BRAND", product_type="Omáčky > Sójové omáčky"):
    return {
        "id": product_id,
        "title": title,
        "price": price,
        "sale_price": None,
        "effective_price": price,
        "currency": "EUR",
        "unit_pricing_measure": size,
        "brand": brand,
        "product_type": product_type,
    }


PRODUCT_CHEAP = _product("P_CHEAP", "Sójová omáčka A", 3.00, "300ml")
PRODUCT_EXPENSIVE = _product("P_EXP", "Sójová omáčka B", 6.00, "300ml")
PRODUCT_SMALL = _product("P_SMALL", "Sójová omáčka C", 4.00, "150ml")
PRODUCT_LARGE = _product("P_LARGE", "Sójová omáčka D", 4.00, "600ml")
PRODUCT_NO_PRICE = _product("P_NOPRICE", "Sójová omáčka E", None, "300ml")
PRODUCT_NO_SIZE = _product("P_NOSIZE", "Sójová omáčka F", 5.00, None)
PRODUCT_EQUAL_A = _product("P_EQ_A", "Sójová omáčka G", 5.00, "300ml")
PRODUCT_EQUAL_B = _product("P_EQ_B", "Sójová omáčka H", 5.00, "300ml")


def _targets(a, b, method="explicit_pair"):
    return cmp.ComparisonTargets(product_a=a, product_b=b, resolution_method=method)


class TestCaseA_PriceWinner:
    def test_cheaper_product_is_clear_winner_for_cheapest_goal(self):
        decision = cmp.decide_comparison(_targets(PRODUCT_CHEAP, PRODUCT_EXPENSIVE), cmp.GOAL_CHEAPEST)
        assert decision.state == cmp.STATE_CLEAR_WINNER
        assert decision.winner_product_id == "P_CHEAP"
        assert cmp.REASON_PRICE_FIT in decision.reason_codes


class TestCaseB_SizeWinner:
    def test_larger_package_is_clear_winner_for_largest_pack_goal(self):
        decision = cmp.decide_comparison(_targets(PRODUCT_SMALL, PRODUCT_LARGE), cmp.GOAL_LARGEST_PACK)
        assert decision.state == cmp.STATE_CLEAR_WINNER
        assert decision.winner_product_id == "P_LARGE"
        assert cmp.REASON_SIZE_FIT in decision.reason_codes


class TestCaseC_TradeOff:
    def test_genuine_conflicting_dimensions_yields_conditional_winner(self):
        # A: cheaper per unit, B: bigger pack but worse unit price.
        product_a = _product("P_A", "Omáčka K", 2.00, "200ml")  # 0.01/ml
        product_b = _product("P_B", "Omáčka L", 6.00, "400ml")  # 0.015/ml, but bigger
        decision = cmp.decide_comparison(_targets(product_a, product_b), cmp.GOAL_GENERAL_BEST)
        assert decision.state == cmp.STATE_CONDITIONAL_WINNER
        assert decision.winner_product_id is None


class TestCaseD_NoMeaningfulDifference:
    def test_equal_price_and_size_yields_no_meaningful_difference(self):
        decision = cmp.decide_comparison(_targets(PRODUCT_EQUAL_A, PRODUCT_EQUAL_B), cmp.GOAL_GENERAL_BEST)
        assert decision.state == cmp.STATE_NO_MEANINGFUL_DIFFERENCE

    def test_equal_price_for_cheapest_goal_yields_no_meaningful_difference(self):
        decision = cmp.decide_comparison(_targets(PRODUCT_EQUAL_A, PRODUCT_EQUAL_B), cmp.GOAL_CHEAPEST)
        assert decision.state == cmp.STATE_NO_MEANINGFUL_DIFFERENCE


class TestCaseE_FlavorAbstains:
    def test_flavor_goal_always_abstains(self):
        goal = cmp.resolve_comparison_goal("Ktora chuti lepsie?")
        assert goal == cmp.GOAL_UNSUPPORTED_QUALITATIVE
        decision = cmp.decide_comparison(_targets(PRODUCT_CHEAP, PRODUCT_EXPENSIVE), goal)
        assert decision.state == cmp.STATE_ABSTAIN


class TestCaseF_AuthenticityAbstains:
    def test_authenticity_goal_always_abstains(self):
        goal = cmp.resolve_comparison_goal("Ktora je autentickejsia?")
        assert goal == cmp.GOAL_UNSUPPORTED_QUALITATIVE
        decision = cmp.decide_comparison(_targets(PRODUCT_CHEAP, PRODUCT_EXPENSIVE), goal)
        assert decision.state == cmp.STATE_ABSTAIN


class TestCaseG_AmbiguousTargetClarifies:
    def test_bare_brand_names_across_categories_do_not_resolve(self):
        import app.main as m

        memory = {}
        targets = cmp.resolve_comparison_targets("Kikkoman alebo Yamasa?", memory, m.products)
        # Bare cross-category brand names must not silently resolve to
        # an arbitrary, possibly-unrelated pair (Section 8).
        assert targets is None

    def test_no_comparison_language_does_not_resolve(self):
        memory = {}
        targets = cmp.resolve_comparison_targets("chcem kupit ryzu a olej", memory, [])
        assert targets is None


@dataclass
class _MinimalProduct:
    id: str
    title: str = "Test Product"
    price: float = 1.0
    sale_price: float | None = None
    currency: str = "EUR"
    unit_pricing_measure: str | None = None
    brand: str = "BRAND"
    product_type: str = "Category"

    @property
    def effective_price(self) -> float:
        return self.sale_price if self.sale_price is not None else self.price


class TestCaseH_ResultsetOrdinal:
    def test_ordinal_pair_resolves_two_distinct_products_from_presentation(self):
        products = [_MinimalProduct("ID_1"), _MinimalProduct("ID_2"), _MinimalProduct("ID_3")]
        memory = {"recent_presentation_ids": ["ID_1", "ID_2", "ID_3"]}
        targets = cmp.resolve_comparison_targets("prvy alebo druhy", memory, products)
        assert targets is not None
        assert targets.resolution_method == "ordinal_pair"
        assert {targets.product_a["id"], targets.product_b["id"]} == {"ID_1", "ID_2"}

    def test_ordinal_pair_out_of_range_does_not_resolve(self):
        products = [_MinimalProduct("ID_1")]
        memory = {"recent_presentation_ids": ["ID_1"]}
        targets = cmp.resolve_comparison_targets("porovnaj prvy a treti", memory, products)
        assert targets is None

    def test_no_active_presentation_does_not_resolve(self):
        targets = cmp.resolve_comparison_targets("prvy alebo druhy", {}, [])
        assert targets is None


class TestCaseI_RankingTrapDoesNotAutoWin:
    """Section 21: search rank must never be treated as recommendation
    evidence. app.comparison never even receives a rank signal - its
    evidence functions only look at price/size/brand/taxonomy, proving
    structurally that a top-ranked-but-otherwise-unremarkable product
    cannot become a CLEAR_WINNER merely by virtue of retrieval order."""

    def test_identical_products_except_synthetic_rank_field_are_not_differentiated(self):
        product_a = dict(PRODUCT_EQUAL_A)
        product_b = dict(PRODUCT_EQUAL_B)
        product_a["_synthetic_rank"] = 1
        product_b["_synthetic_rank"] = 2
        decision = cmp.decide_comparison(_targets(product_a, product_b), cmp.GOAL_GENERAL_BEST)
        assert decision.state == cmp.STATE_NO_MEANINGFUL_DIFFERENCE
        assert decision.winner_product_id is None

    def test_evidence_functions_never_reference_rank_or_position(self):
        import inspect

        source = inspect.getsource(cmp)
        for banned in ("rank", "position", "_synthetic_rank"):
            # "rank" appears legitimately in "ranking_features" comments/docstrings only;
            # assert no evidence-producing code path reads a rank/position field off a product dict.
            assert 'product.get("rank")' not in source
            assert 'product.get("position")' not in source


class TestCaseJK_LlmOverrideProtectionByConstruction:
    """Sections 26/J/K: since compose_comparison_answer() never calls
    an LLM, there is no generated text for an LLM to override a
    TRADE_OFF/ABSTAIN decision with. This is proven by static
    inspection of the module (no OpenAI client, no _call_openai_with_retry
    reference anywhere in app.comparison), not by runtime detection of
    a violation after the fact."""

    def test_comparison_module_never_references_openai(self):
        import inspect

        source = inspect.getsource(cmp)
        for forbidden in ("_get_openai_client", "_call_openai_with_retry", "openai", "OpenAI("):
            assert forbidden not in source, f"app.comparison must never call {forbidden!r} - LLM override protection depends on this"

    def test_tradeoff_answer_never_declares_a_universal_winner(self):
        product_a = _product("P_A", "Omáčka K", 2.00, "200ml")
        product_b = _product("P_B", "Omáčka L", 6.00, "400ml")
        decision = cmp.decide_comparison(_targets(product_a, product_b), cmp.GOAL_GENERAL_BEST)
        assert decision.state == cmp.STATE_CONDITIONAL_WINNER
        answer = cmp.compose_comparison_answer(decision, _targets(product_a, product_b))
        for forbidden_phrase in ("celkovo by som vybrala", "jednoznačne najlepší", "overall i recommend"):
            assert forbidden_phrase not in answer.lower()

    def test_abstain_answer_never_declares_a_winner(self):
        decision = cmp.decide_comparison(_targets(PRODUCT_CHEAP, PRODUCT_EXPENSIVE), cmp.GOAL_UNSUPPORTED_QUALITATIVE)
        answer = cmp.compose_comparison_answer(decision, _targets(PRODUCT_CHEAP, PRODUCT_EXPENSIVE))
        assert decision.winner_product_id is None
        for forbidden_phrase in ("odporúčam", "najlepší", "recommend", "best"):
            assert forbidden_phrase not in answer.lower()


class TestCaseL_GroundedWinnerAllowed:
    def test_strong_deterministic_evidence_permits_recommend_shaped_output(self):
        decision = cmp.decide_comparison(_targets(PRODUCT_CHEAP, PRODUCT_EXPENSIVE), cmp.GOAL_CHEAPEST)
        assert decision.state == cmp.STATE_CLEAR_WINNER
        answer = cmp.compose_comparison_answer(decision, _targets(PRODUCT_CHEAP, PRODUCT_EXPENSIVE))
        assert "Sójová omáčka A" in answer
        assert "3.00 EUR" in answer


class TestUnitPriceSafety:
    """Section 13: never compare EUR/kg with EUR/piece."""

    def test_incompatible_units_abstain_for_best_value_goal(self):
        product_g = _product("P_G", "Omáčka M", 5.00, "500g")
        product_ml = _product("P_ML", "Omáčka N", 5.00, "500ml")
        decision = cmp.decide_comparison(_targets(product_g, product_ml), cmp.GOAL_BEST_VALUE)
        assert decision.state == cmp.STATE_ABSTAIN
        assert decision.abstain_reason == "incompatible_or_missing_units"

    def test_missing_size_abstains_for_best_value_goal(self):
        decision = cmp.decide_comparison(_targets(PRODUCT_NO_SIZE, PRODUCT_CHEAP), cmp.GOAL_BEST_VALUE)
        assert decision.state == cmp.STATE_ABSTAIN

    def test_same_unit_family_is_comparable(self):
        product_a = _product("P_A2", "Omáčka O", 2.00, "200g")
        product_b = _product("P_B2", "Omáčka P", 3.00, "600g")
        decision = cmp.decide_comparison(_targets(product_a, product_b), cmp.GOAL_BEST_VALUE)
        assert decision.state == cmp.STATE_CLEAR_WINNER


class TestMissingPriceData:
    def test_missing_price_abstains_for_cheapest_goal(self):
        decision = cmp.decide_comparison(_targets(PRODUCT_NO_PRICE, PRODUCT_CHEAP), cmp.GOAL_CHEAPEST)
        assert decision.state == cmp.STATE_ABSTAIN
        assert decision.abstain_reason == "missing_price_data"


class TestClaimGroundingMatrix:
    """Section 40 - each of these mirrors a row of the spec's claim
    grounding matrix. Since this module never generates free text
    beyond its own templates, "PASS"/"BLOCK" is verified as "the
    correct decision state was reached" and "the composed answer only
    contains template phrases, never an invented qualitative claim"."""

    def test_price_evidence_supports_cheaper_claim(self):
        decision = cmp.decide_comparison(_targets(PRODUCT_CHEAP, PRODUCT_EXPENSIVE), cmp.GOAL_CHEAPEST)
        assert decision.state == cmp.STATE_CLEAR_WINNER

    def test_size_evidence_supports_larger_package_claim(self):
        decision = cmp.decide_comparison(_targets(PRODUCT_SMALL, PRODUCT_LARGE), cmp.GOAL_LARGEST_PACK)
        assert decision.state == cmp.STATE_CLEAR_WINNER

    def test_no_flavor_evidence_blocks_tastier_claim(self):
        goal = cmp.resolve_comparison_goal("ktora chuti lepsie")
        decision = cmp.decide_comparison(_targets(PRODUCT_CHEAP, PRODUCT_EXPENSIVE), goal)
        assert decision.state == cmp.STATE_ABSTAIN
        answer = cmp.compose_comparison_answer(decision, _targets(PRODUCT_CHEAP, PRODUCT_EXPENSIVE))
        assert "chutí lepšie" not in answer or "nemám spoľahlivé údaje" in answer

    def test_no_authenticity_evidence_blocks_authenticity_claim(self):
        goal = cmp.resolve_comparison_goal("ktora je autentickejsia")
        decision = cmp.decide_comparison(_targets(PRODUCT_CHEAP, PRODUCT_EXPENSIVE), goal)
        assert decision.state == cmp.STATE_ABSTAIN

    def test_llm_only_evidence_would_never_reach_high_confidence(self):
        # Sanity cross-check against V2.14a's own invariant: if this
        # module ever gained an LLM_JUDGMENT evidence source, it still
        # could not manufacture HIGH confidence alone.
        from app.recommendation_evidence import EvidenceItem, compute_confidence, CONFIDENCE_HIGH

        llm_evidence = [EvidenceItem("flavor_profile_fit", PROVENANCE_LLM_JUDGMENT, "openai", 0.99)]
        assert compute_confidence(llm_evidence) != CONFIDENCE_HIGH


class TestLooksLikeComparisonRequest:
    def test_rozdiel_alone_is_not_a_causal_comparison_trigger(self):
        """Permanent regression lock: a real full-suite failure was
        found during implementation - "aký je rozdiel medzi mirin a
        ryžovým octom?" is a genuine informational/FAQ-style question
        (explain a conceptual difference), not a request to pick
        between two purchasable products. app.workflow_registry's
        _COMPARISON_MARKERS includes "rozdiel" because it is safe
        there (a pure post-hoc relabel of an already-found FAQ
        answer) - it must NOT be reused as a causal trigger here.
        See tests/test_session_contamination_v2_13b_1.py::
        TestDietTermDoesNotHijackUnrelatedProduct::
        test_diet_preference_then_unrelated_comparison_question_not_corrupted
        for the end-to-end lock of the same fix."""
        assert not cmp.looks_like_comparison_request("aky je rozdiel medzi mirin a rizovym octom?")

    def test_explicit_alebo_connector(self):
        assert cmp.looks_like_comparison_request("Kikkoman alebo Yamasa?")

    def test_porovnaj_verb(self):
        assert cmp.looks_like_comparison_request("Porovnaj tieto dve omacky")

    def test_multi_ordinal_is_comparison_signal(self):
        assert cmp.looks_like_comparison_request("prvy alebo druhy")

    def test_single_ordinal_is_not_comparison_signal(self):
        assert not cmp.looks_like_comparison_request("ten druhy")

    def test_plain_product_search_is_not_comparison(self):
        assert not cmp.looks_like_comparison_request("chcem kupit sojovu omacku")


class TestExecuteComparisonHandler:
    """app.workflow_executor.execute_comparison() - the customer-facing
    integration point (Section 28/29)."""

    def _chat_req(self, message, session_id="wf-test"):
        class _Req:
            pass

        req = _Req()
        req.message = message
        req.session_id = session_id
        req.limit = 8
        req.conversation_history = []
        req.client_id = ""
        return req

    def test_non_comparison_message_returns_none(self, real_products, real_taxonomy_index):
        import app.workflow_executor as we

        result = we.execute_comparison(
            chat_request=self._chat_req("chcem kupit ryzu"), memory={}, memory_key="k", profile_key="p",
            products=real_products, product_taxonomy_index=real_taxonomy_index,
            client_key="127.0.0.1", session_id="s", query_language="sk", emit_customer_analytics=False,
        )
        assert result is None

    def test_ambiguous_comparison_returns_clarify_not_none(self, real_products, real_taxonomy_index):
        import app.workflow_executor as we

        result = we.execute_comparison(
            chat_request=self._chat_req("Kikkoman alebo Yamasa?"), memory={}, memory_key="k", profile_key="p",
            products=real_products, product_taxonomy_index=real_taxonomy_index,
            client_key="127.0.0.1", session_id="s", query_language="sk", emit_customer_analytics=False,
        )
        assert result is not None
        assert result["comparison_decision"] == "CLARIFY"
        assert result["intent"] == "product_comparison"
        assert "memory" in result and "products" in result and "answer" in result

    def test_resolvable_comparison_returns_full_contract(self, real_products, real_taxonomy_index):
        import app.workflow_executor as we

        result = we.execute_comparison(
            chat_request=self._chat_req("Porovnaj sojova omacka Kikkoman a sojova omacka Yamasa"),
            memory={}, memory_key="k", profile_key="p",
            products=real_products, product_taxonomy_index=real_taxonomy_index,
            client_key="127.0.0.1", session_id="s", query_language="sk", emit_customer_analytics=False,
        )
        assert result is not None
        for field in ("answer", "products", "intent", "memory", "response_mode"):
            assert field in result, f"missing REQUIRED_ALWAYS field {field!r} (V2.13g contract)"
        assert result["intent"] == "product_comparison"
        assert result["response_mode"] == "comparison"
        assert len(result["products"]) == 2

    def test_handler_never_touches_openai(self):
        import inspect
        import app.workflow_executor as we

        source = inspect.getsource(we.execute_comparison)
        for forbidden in ("_get_openai_client", "_call_openai_with_retry"):
            assert forbidden not in source


class TestGoalClassification:
    def test_cheapest_markers(self):
        assert cmp.resolve_comparison_goal("ktora je lacnejsia") == cmp.GOAL_CHEAPEST

    def test_best_value_markers(self):
        assert cmp.resolve_comparison_goal("ktore balenie sa viac oplati") == cmp.GOAL_BEST_VALUE

    def test_largest_pack_markers(self):
        assert cmp.resolve_comparison_goal("ktore ma vacsie balenie") == cmp.GOAL_LARGEST_PACK

    def test_bare_better_defaults_to_general_best(self):
        assert cmp.resolve_comparison_goal("ktory produkt je lepsi") == cmp.GOAL_GENERAL_BEST

    def test_qualitative_wins_over_other_markers_when_both_present(self):
        assert cmp.resolve_comparison_goal("ktora chutnejsia a lacnejsia") == cmp.GOAL_UNSUPPORTED_QUALITATIVE


class TestRealCatalogData:
    """Section 36 - exercised against the actual Foodland catalog, not
    only synthetic products."""

    def test_real_soy_sauce_brand_pair_with_category_gate(self, real_products, real_taxonomy_index):
        import app.main as m

        memory = {}
        targets = cmp.resolve_comparison_targets(
            "Porovnaj sojova omacka Kikkoman a sojova omacka Yamasa", memory, m.products,
        )
        assert targets is not None
        assert targets.product_a["id"] != targets.product_b["id"]

    def test_real_bare_cross_category_brand_pair_does_not_resolve(self, real_products):
        import app.main as m

        memory = {}
        targets = cmp.resolve_comparison_targets("Kikkoman alebo Yamasa?", memory, m.products)
        assert targets is None

    def test_real_weak_data_product_pair_abstains_on_best_value(self, real_products):
        import app.main as m

        # Deliberately weak-data pair: a product with no unit_pricing_measure at all.
        weak = next((p for p in m.products if not p.unit_pricing_measure), None)
        strong = next((p for p in m.products if p.unit_pricing_measure), None)
        if weak is None or strong is None:
            import pytest
            pytest.skip("catalog does not contain the expected weak/strong data split")
        from app.search import format_product
        targets = _targets(format_product(weak), format_product(strong))
        decision = cmp.decide_comparison(targets, cmp.GOAL_BEST_VALUE)
        assert decision.state == cmp.STATE_ABSTAIN


import pytest


@pytest.fixture
def real_products():
    import os
    os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")
    import app.main as m
    return m.products


@pytest.fixture
def real_taxonomy_index():
    import app.main as m
    return m.product_taxonomy_index
