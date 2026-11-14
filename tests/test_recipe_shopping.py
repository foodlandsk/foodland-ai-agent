"""
tests/test_recipe_shopping.py  -  Sprint V2.8 RecipeShoppingPlan

Plan building against real production data (docs/recipe-knowledge-audit.md),
plus quantity/serving/package arithmetic against small synthetic fixtures
(clearly labeled - no current Foodland recipe carries a structured
quantity, so that machinery is exercised directly rather than through the
graph). End-to-end chat() integration tests close the file (Section
99/114/115/116/117 regressions).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.main as m
from app.ingredients import ParsedQuantity, extract_requested_servings, parse_quantity_text, scale_quantity
from app.recipe_graph import build_recipe_graph_index
from app.recipe_shopping import (
    RECIPE_FOLLOWUP_PLAN_UPDATE,
    STATUS_ALREADY_SATISFIED,
    STATUS_AVAILABLE,
    RecipeFollowupResult,
    build_recipe_shopping_plan,
    compose_recipe_followup_answer,
    package_count_for,
    scale_plan_quantities,
    summarize_plan,
)

GRAPH = build_recipe_graph_index(
    products=m.products,
    taxonomy_index=m.product_taxonomy_index,
    normalized_index=m.normalized_product_index,
    recipe_shopping_core_queries=m.RECIPE_SHOPPING_CORE_QUERIES,
    missing_ingredients_by_subject=m.MISSING_INGREDIENTS_BY_SUBJECT,
    recipe_title_product_subjects=m.RECIPE_TITLE_PRODUCT_SUBJECTS,
    cms_recipes=m.knowledge.get("sections", {}).get("Recipes", []),
    products_ai=m.knowledge.get("sections", {}).get("Products_AI", []),
    special_product_queries=m.SPECIAL_PRODUCT_QUERIES,
)


class TestPlanBuilding:
    def test_pad_thai_plan_fully_covers_curated_ingredients(self):
        plan = build_recipe_shopping_plan(GRAPH, "pad_thai", m.products, m.product_taxonomy_index, m.normalized_product_index)
        assert plan is not None
        assert plan.recipe_shopping_coverage == 1.0
        assert plan.missing_required_count == 0
        for ing in plan.ingredients:
            assert ing.status in {STATUS_AVAILABLE, STATUS_ALREADY_SATISFIED}
            assert ing.selected_product_id is not None

    def test_not_available_text_carried_through_from_curated_data(self):
        plan = build_recipe_shopping_plan(GRAPH, "pad_thai", m.products, m.product_taxonomy_index, m.normalized_product_index)
        assert plan.not_available_ingredients == tuple(m.MISSING_INGREDIENTS_BY_SUBJECT["pad_thai"])

    def test_unknown_dish_returns_none(self):
        assert build_recipe_shopping_plan(GRAPH, "not_a_real_dish", m.products, m.product_taxonomy_index, m.normalized_product_index) is None


class TestBasketSatisfaction:
    """Section 56/57/111."""

    def test_basket_item_marks_ingredient_already_satisfied(self):
        baseline = build_recipe_shopping_plan(GRAPH, "pad_thai", m.products, m.product_taxonomy_index, m.normalized_product_index)
        fish_sauce_ing = next(i for i in baseline.ingredients if i.ingredient_concept_id == "fish_sauce")
        basket = frozenset([fish_sauce_ing.selected_product_id])

        plan = build_recipe_shopping_plan(
            GRAPH, "pad_thai", m.products, m.product_taxonomy_index, m.normalized_product_index,
            basket_product_ids=basket,
        )
        satisfied = next(i for i in plan.ingredients if i.ingredient_concept_id == "fish_sauce")
        assert satisfied.status == STATUS_ALREADY_SATISFIED

        others = [i for i in plan.ingredients if i.ingredient_concept_id != "fish_sauce"]
        assert all(i.status != STATUS_ALREADY_SATISFIED for i in others)

    def test_unrelated_basket_item_does_not_satisfy_anything(self):
        unrelated_product = next(p for p in m.products if p.id not in {
            pid for pid in _all_candidate_ids()
        })
        plan = build_recipe_shopping_plan(
            GRAPH, "pad_thai", m.products, m.product_taxonomy_index, m.normalized_product_index,
            basket_product_ids=frozenset([unrelated_product.id]),
        )
        assert all(i.status != STATUS_ALREADY_SATISFIED for i in plan.ingredients)


def _all_candidate_ids():
    plan = build_recipe_shopping_plan(GRAPH, "pad_thai", m.products, m.product_taxonomy_index, m.normalized_product_index)
    ids = set()
    for ing in plan.ingredients:
        ids.update(ing.candidate_product_ids)
    return ids


class TestSummarizePlan:
    def test_sections_are_json_safe_and_grouped(self):
        plan = build_recipe_shopping_plan(GRAPH, "pad_thai", m.products, m.product_taxonomy_index, m.normalized_product_index)
        summary = summarize_plan(plan)
        assert set(summary["sections"]) == {"RECIPE_REQUIRED", "RECIPE_OPTIONAL", "RECIPE_ALREADY_HAVE", "RECIPE_NOT_AVAILABLE"}
        assert len(summary["sections"]["RECIPE_REQUIRED"]) == 5
        assert len(summary["sections"]["RECIPE_NOT_AVAILABLE"]) == len(m.MISSING_INGREDIENTS_BY_SUBJECT["pad_thai"])
        assert summary["coverage"]["recipe_shopping_coverage"] == 1.0

    def test_every_item_in_every_section_carries_quantity_and_package_count_keys(self):
        # V2.30f (Customer-Facing Quantity Exposure, Phase 1) - additive,
        # uniform shape across every section, including the
        # not_available_ingredients synthetic entries.
        plan = build_recipe_shopping_plan(GRAPH, "pad_thai", m.products, m.product_taxonomy_index, m.normalized_product_index)
        summary = summarize_plan(plan)
        assert "base_servings" in summary
        for section_items in summary["sections"].values():
            for item in section_items:
                assert "quantity" in item
                assert "package_count" in item

    def test_grounded_pilot_ingredient_exposes_real_quantity_and_package_count(self):
        # pad_thai's rice_noodles is dish/ingredient-level APPROVED,
        # base_servings=2, MASS_VOLUME_READY (V2.30c/e) - confirms the
        # already-computed value is now actually JSON-visible.
        plan = build_recipe_shopping_plan(
            GRAPH, "pad_thai", m.products, m.product_taxonomy_index, m.normalized_product_index, servings=6,
        )
        summary = summarize_plan(plan)
        assert summary["base_servings"] == 2
        rice_noodles = next(
            item for item in summary["sections"]["RECIPE_REQUIRED"] if item["ingredient_concept_id"] == "rice_noodles"
        )
        assert rice_noodles["quantity"] == {"value": 750.0, "unit": "g"}  # 250 * 6 / 2
        assert rice_noodles["package_count"] == 2

    def test_culinary_unit_ingredient_exposes_quantity_but_null_package_count(self):
        plan = build_recipe_shopping_plan(GRAPH, "pad_thai", m.products, m.product_taxonomy_index, m.normalized_product_index)
        summary = summarize_plan(plan)
        tamarind = next(
            item for item in summary["sections"]["RECIPE_REQUIRED"] if item["ingredient_concept_id"] == "tamarind_pasta"
        )
        assert tamarind["quantity"] == {"value": 3.0, "unit": "PL"}
        assert tamarind["package_count"] is None

    def test_unapproved_pilot_ingredient_exposes_null_quantity_and_package_count(self):
        plan = build_recipe_shopping_plan(GRAPH, "pad_thai", m.products, m.product_taxonomy_index, m.normalized_product_index)
        summary = summarize_plan(plan)
        arasidy = next(
            item for item in summary["sections"]["RECIPE_REQUIRED"] if item["ingredient_concept_id"] == "arasidy"
        )
        assert arasidy["quantity"] is None
        assert arasidy["package_count"] is None

    def test_non_pilot_dish_exposes_null_quantity_package_count_and_base_servings(self):
        plan = build_recipe_shopping_plan(GRAPH, "kung_pao", m.products, m.product_taxonomy_index, m.normalized_product_index)
        summary = summarize_plan(plan)
        assert summary["base_servings"] is None
        for section_items in summary["sections"].values():
            for item in section_items:
                assert item["quantity"] is None
                assert item["package_count"] is None

    def test_not_available_synthetic_entries_also_carry_null_quantity_fields(self):
        plan = build_recipe_shopping_plan(GRAPH, "pad_thai", m.products, m.product_taxonomy_index, m.normalized_product_index)
        summary = summarize_plan(plan)
        assert summary["sections"]["RECIPE_NOT_AVAILABLE"]
        for item in summary["sections"]["RECIPE_NOT_AVAILABLE"]:
            assert item["quantity"] is None
            assert item["package_count"] is None


class TestFollowupAnswerQuantitySuffix:
    """V2.30g (Customer-Facing Quantity Exposure, Phase 2) -
    compose_recipe_followup_answer()'s PLAN_UPDATE branch appends a
    " (value unit)" suffix for grounded remaining ingredients only."""

    def _plan_update_result(self, dish_id, servings=None):
        plan = build_recipe_shopping_plan(
            GRAPH, dish_id, m.products, m.product_taxonomy_index, m.normalized_product_index, servings=servings,
        )
        return plan, RecipeFollowupResult(kind=RECIPE_FOLLOWUP_PLAN_UPDATE, dish_id=dish_id, plan=plan)

    def test_grounded_ingredient_gets_quantity_suffix_sk(self):
        _, result = self._plan_update_result("pad_thai", servings=6)
        answer = compose_recipe_followup_answer(result, GRAPH, {}, lang="sk")
        assert "rezance (750 g)" in answer  # 250 * 6 / 2

    def test_grounded_ingredient_gets_quantity_suffix_en(self):
        _, result = self._plan_update_result("pad_thai", servings=6)
        answer = compose_recipe_followup_answer(result, GRAPH, {}, lang="en")
        assert "(750 g)" in answer

    def test_unapproved_ingredient_gets_no_suffix(self):
        plan, result = self._plan_update_result("pad_thai", servings=6)
        answer = compose_recipe_followup_answer(result, GRAPH, {}, lang="sk")
        arasidy_label = GRAPH.ingredient_concepts["arasidy"].display_name
        assert f"{arasidy_label}." in answer or f"{arasidy_label}," in answer
        assert f"{arasidy_label} (" not in answer

    def test_culinary_unit_ingredient_shows_unit_verbatim(self):
        _, result = self._plan_update_result("pad_thai", servings=6)
        answer = compose_recipe_followup_answer(result, GRAPH, {}, lang="sk")
        assert "(9 PL)" in answer  # tamarind_pasta: 3 PL * 6 / 2, unit shown as-is, no conversion

    def test_no_requested_servings_uses_base_quantity(self):
        _, result = self._plan_update_result("pad_thai", servings=None)
        answer = compose_recipe_followup_answer(result, GRAPH, {}, lang="sk")
        assert "(250 g)" in answer

    def test_non_pilot_dish_text_has_no_quantity_suffix_at_all(self):
        _, result = self._plan_update_result("kung_pao", servings=6)
        answer = compose_recipe_followup_answer(result, GRAPH, {}, lang="sk")
        assert "(" not in answer

    def test_already_have_everything_branch_unaffected(self):
        plan = build_recipe_shopping_plan(GRAPH, "pad_thai", m.products, m.product_taxonomy_index, m.normalized_product_index)
        required_product_ids = frozenset(
            ing.selected_product_id for ing in plan.ingredients if ing.requirement == "REQUIRED" and ing.selected_product_id
        )
        full_plan = build_recipe_shopping_plan(
            GRAPH, "pad_thai", m.products, m.product_taxonomy_index, m.normalized_product_index,
            basket_product_ids=required_product_ids,
        )
        result = RecipeFollowupResult(kind=RECIPE_FOLLOWUP_PLAN_UPDATE, dish_id="pad_thai", plan=full_plan)
        answer = compose_recipe_followup_answer(result, GRAPH, {}, lang="sk")
        assert "uz mate vsetko potrebne" in answer.lower() or "už máte všetko potrebné" in answer
        assert "(" not in answer


class TestQuantityParsing:
    """Section 9/25 - synthetic text, pure parser logic."""

    def test_numeric_quantity_parses(self):
        parsed = parse_quantity_text("30 ml")
        assert parsed.is_numeric
        assert parsed.quantity == 30.0
        assert parsed.unit == "ml"

    def test_tablespoon_abbreviation_normalizes(self):
        parsed = parse_quantity_text("2 PL")
        assert parsed.is_numeric
        assert parsed.unit == "tbsp"

    def test_nonnumeric_phrase_never_parses_as_numeric(self):
        for phrase in ("podľa chuti", "na ozdobu", "podla potreby", "na dochutenie"):
            parsed = parse_quantity_text(phrase)
            assert not parsed.is_numeric
            assert parsed.quantity is None


class TestServingsExtraction:
    """Section 134-F."""

    def test_extracts_servings_from_natural_phrasing(self):
        assert extract_requested_servings("Chcem robit Pad Thai pre 8 ludi. Co mam kupit?") == 8
        assert extract_requested_servings("recept na kung pao pre 4 osoby") == 4

    def test_no_servings_phrase_returns_none(self):
        assert extract_requested_servings("Co potrebujem na Pad Thai?") is None

    def test_out_of_range_servings_ignored(self):
        assert extract_requested_servings("pre 999 osob") is None


class TestServingScaling:
    """Section 24/25 - synthetic RecipeShoppingPlan, arithmetic only."""

    def test_numeric_quantity_scales_linearly(self):
        assert scale_quantity(30.0, 4, 8) == 60.0
        assert scale_quantity(100.0, 4, 2) == 50.0

    def test_scale_plan_quantities_only_touches_numeric_ingredients(self):
        # V2.30c (Grounded Recipe Scaling Pilot Activation) grounds 3 of
        # pad_thai's 5 ingredients (APPROVED: rice_noodles/tamarind_pasta/
        # fish_sauce) in real data, so this is no longer a universal no-op
        # for this dish - it now proves scale_plan_quantities()'s own
        # arithmetic contract (pivoting off whatever requested_servings
        # this synthetic plan carries, not the recipe's true
        # base_servings=2) against every real numeric ingredient, while
        # the 2 still-NEEDS_AUTHORING ingredients (palmovy_cukor/arasidy)
        # stay untouched exactly as before.
        plan = build_recipe_shopping_plan(GRAPH, "pad_thai", m.products, m.product_taxonomy_index, m.normalized_product_index)
        real_plan_with_servings = plan.__class__(
            dish_id=plan.dish_id, dish_title=plan.dish_title, recipe_id=plan.recipe_id,
            requested_servings=4, ingredients=plan.ingredients,
            not_available_ingredients=plan.not_available_ingredients,
            ingredient_mapping_coverage=plan.ingredient_mapping_coverage,
            required_ingredient_mapping_coverage=plan.required_ingredient_mapping_coverage,
            catalog_product_coverage=plan.catalog_product_coverage,
            recipe_shopping_coverage=plan.recipe_shopping_coverage,
            missing_required_count=plan.missing_required_count, optional_count=plan.optional_count,
            base_servings=plan.base_servings,
        )
        scaled = scale_plan_quantities(real_plan_with_servings, 8)
        assert scaled.requested_servings == 8

        numeric_concept_ids = {"rice_noodles", "tamarind_pasta", "fish_sauce"}
        original_by_concept = {ing.ingredient_concept_id: ing for ing in plan.ingredients}
        for scaled_ing in scaled.ingredients:
            original = original_by_concept[scaled_ing.ingredient_concept_id]
            if scaled_ing.ingredient_concept_id in numeric_concept_ids:
                assert original.quantity is not None and original.quantity.is_numeric
                assert scaled_ing.quantity.quantity == original.quantity.quantity * 2  # 8 / 4
                assert scaled_ing.quantity.unit == original.quantity.unit
            else:
                assert scaled_ing.quantity is None, (
                    f"{scaled_ing.ingredient_concept_id}: expected to remain unapproved/untouched"
                )


class TestPackageCount:
    """Section 28/29/110 - synthetic PackageSize fixtures."""

    def test_matching_units_compute_package_count(self):
        required = ParsedQuantity(quantity=800.0, unit="ml", is_numeric=True, raw_text="800 ml")
        package = types.SimpleNamespace(package_size=types.SimpleNamespace(value=400.0, unit="ml", is_structured=True))
        assert package_count_for(required, package) == 2

    def test_exact_match_needs_one_package(self):
        required = ParsedQuantity(quantity=400.0, unit="ml", is_numeric=True, raw_text="400 ml")
        package = types.SimpleNamespace(package_size=types.SimpleNamespace(value=400.0, unit="ml", is_structured=True))
        assert package_count_for(required, package) == 1

    def test_incompatible_units_return_none(self):
        required = ParsedQuantity(quantity=400.0, unit="ml", is_numeric=True, raw_text="400 ml")
        package = types.SimpleNamespace(package_size=types.SimpleNamespace(value=200.0, unit="g", is_structured=True))
        assert package_count_for(required, package) is None

    def test_unknown_package_size_returns_none(self):
        required = ParsedQuantity(quantity=400.0, unit="ml", is_numeric=True, raw_text="400 ml")
        package = types.SimpleNamespace(package_size=types.SimpleNamespace(value=None, unit=None, is_structured=False))
        assert package_count_for(required, package) is None

    def test_nonnumeric_quantity_never_computes_a_count(self):
        required = ParsedQuantity(quantity=None, unit=None, is_numeric=False, raw_text="podla chuti")
        package = types.SimpleNamespace(package_size=types.SimpleNamespace(value=400.0, unit="ml", is_structured=True))
        assert package_count_for(required, package) is None


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers = {}


class TestChatIntegration:
    """Section 99/100/114/115/116/117 - real end-to-end chat() calls."""

    def test_pad_thai_shopping_query_uses_v28_plan(self):
        cr = m.ChatRequest(message="Chcem robit Pad Thai. Co potrebujem?", session_id="v28-t-1", limit=8)
        response = m.chat(cr, _FakeRequest())
        assert response.get("intent") == "recipe_to_products"
        assert response.get("workflow_id") == "RECIPE_SHOPPING"
        assert response.get("workflow_confidence") == 0.9
        plan = response.get("recipe_shopping_plan")
        assert plan is not None
        assert plan["dish_id"] == "pad_thai"
        assert plan["coverage"]["recipe_shopping_coverage"] == 1.0
        assert response.get("missing_ingredients")

    def test_dish_outside_graph_falls_back_to_legacy_safely(self):
        cr = m.ChatRequest(message="recept na vindaloo, co potrebujem", session_id="v28-t-2", limit=6)
        response = m.chat(cr, _FakeRequest())
        assert response.get("intent") == "recipe_to_products"
        assert response.get("recipe_shopping_plan") is None
        assert response.get("products")  # legacy path still returns real recommendations

    def test_context_switch_away_from_recipe_does_not_leak_plan(self):
        """Section 114 - Pad Thai shopping, then an unrelated product
        lookup must not carry the recipe plan or workflow forward."""
        session = "v28-t-3"
        cr1 = m.ChatRequest(message="Chcem robit Pad Thai. Co potrebujem?", session_id=session, limit=6)
        r1 = m.chat(cr1, _FakeRequest())
        assert r1.get("recipe_shopping_plan") is not None

        cr2 = m.ChatRequest(message="kikkoman sojova omacka 1000 ml", session_id=session, limit=6)
        r2 = m.chat(cr2, _FakeRequest())
        assert r2.get("recipe_shopping_plan") is None
        assert r2.get("workflow_id") != "RECIPE_SHOPPING"

    def test_cross_sell_still_separate_from_recipe_products(self):
        """Section 115 - V2.6 regression: cross-sell (when present) must
        never duplicate the primary recipe_shopping product list."""
        cr = m.ChatRequest(message="Chcem robit Pad Thai. Co potrebujem?", session_id="v28-t-4", limit=6)
        response = m.chat(cr, _FakeRequest())
        primary_ids = {p.get("id") for p in response.get("products", [])}
        cross_sell_ids = {c.get("product_id") for c in (response.get("cross_sell") or [])}
        assert not (primary_ids & cross_sell_ids)

    def test_show_more_show_all_unaffected(self):
        """Section 116 - V2.5 regression, unrelated structured query."""
        cr = m.ChatRequest(message="ryza", session_id="v28-t-5", limit=2)
        response = m.chat(cr, _FakeRequest())
        assert "has_more" in response

    def test_kung_pao_recipe_shopping_plan_resolves_real_products(self):
        """A second, independently curated V2.8-covered dish end-to-end."""
        cr = m.ChatRequest(message="recept na kung pao, co potrebujem", session_id="v28-t-6", limit=8)
        response = m.chat(cr, _FakeRequest())
        plan = response.get("recipe_shopping_plan")
        assert plan is not None
        assert plan["dish_id"] == "kung_pao"
        required_ids = {item["selected_product_id"] for item in plan["sections"]["RECIPE_REQUIRED"]}
        assert None not in required_ids or len(required_ids) > 1


class TestPrimaryTurnQuantitySentence:
    """V2.30h (Customer-Facing Quantity Exposure, Phase 3) -
    app.main.recipe_products_answer()'s optional appended sentence."""

    def test_no_plan_appends_nothing(self):
        answer = m.recipe_products_answer("pad_thai", recipes=[{"id": "r1"}], lang="sk", plan=None)
        assert answer == (
            "Pripravila som nákupný zoznam pre pad thai: najprv produkty z Foodland.sk, potom zvlášť veci, "
            "ktoré si treba doplniť mimo e-shopu. Produkty sú zoradené od kľúčových surovín po doplnky."
        )

    def test_grounded_plan_appends_exact_amounts_sentence_sk(self):
        plan = build_recipe_shopping_plan(GRAPH, "pad_thai", m.products, m.product_taxonomy_index, m.normalized_product_index, servings=6)
        answer = m.recipe_products_answer("pad_thai", recipes=[], lang="sk", plan=plan)
        assert answer.endswith("Presné množstvá: ryzove rezance (750 g), tamarind pasta (9 PL), rybacia omacka (6 PL).")

    def test_grounded_plan_appends_exact_amounts_sentence_en(self):
        plan = build_recipe_shopping_plan(GRAPH, "pad_thai", m.products, m.product_taxonomy_index, m.normalized_product_index, servings=6)
        answer = m.recipe_products_answer("pad_thai", recipes=[], lang="en", plan=plan)
        assert "Exact amounts: " in answer
        assert "(750 g)" in answer

    def test_non_pilot_plan_appends_nothing(self):
        plan = build_recipe_shopping_plan(GRAPH, "kung_pao", m.products, m.product_taxonomy_index, m.normalized_product_index)
        answer = m.recipe_products_answer("kung_pao", recipes=[], lang="sk", plan=plan)
        assert "Presné množstvá" not in answer
        assert "(" not in answer

    def test_chat_level_pad_thai_primary_answer_contains_quantities(self):
        cr = m.ChatRequest(message="Chcem robit Pad Thai pre 6. Co potrebujem?", session_id="v230h-t-1", limit=8)
        response = m.chat(cr, _FakeRequest())
        assert "(750 g)" in response.get("answer", "")

    def test_chat_level_kung_pao_primary_answer_unaffected(self):
        cr = m.ChatRequest(message="recept na kung pao, co potrebujem", session_id="v230h-t-2", limit=8)
        response = m.chat(cr, _FakeRequest())
        assert "(" not in response.get("answer", "")
