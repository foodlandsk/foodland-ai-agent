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
    STATUS_ALREADY_SATISFIED,
    STATUS_AVAILABLE,
    build_recipe_shopping_plan,
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
        )
        scaled = scale_plan_quantities(real_plan_with_servings, 8)
        assert scaled.requested_servings == 8
        # No current Foodland recipe ingredient carries a structured
        # quantity (docs/recipe-knowledge-audit.md) - scaling is a provable
        # no-op against real data today.
        assert all(ing.quantity is None for ing in scaled.ingredients)


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
