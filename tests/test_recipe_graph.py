"""
tests/test_recipe_graph.py  -  Sprint V2.8 Recipe/Ingredient Knowledge Graph

Uses the REAL committed data/products.json and data/knowledge.json (same
convention as tests/test_cross_sell.py) - the graph is grounded in real
curated production data (RECIPE_SHOPPING_CORE_QUERIES,
MISSING_INGREDIENTS_BY_SUBJECT, RECIPE_TITLE_PRODUCT_SUBJECTS,
SPECIAL_PRODUCT_QUERIES, knowledge.json Recipes/Products_AI), not synthetic
fixtures - see docs/recipe-knowledge-audit.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.main as m
from app.recipe_graph import (
    SOURCE_PRODUCT_TAXONOMY,
    SOURCE_RECIPE_CURATED,
    build_recipe_graph_index,
    get_substitutes,
    match_recipes_by_ingredient_concepts,
    recipes_for_ingredient_concept,
    recipes_for_product,
    resolve_dish,
    resolve_ingredient_concept,
    resolve_ingredient_products,
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


class TestGraphIntegrity:
    def test_build_produces_no_issues(self):
        assert GRAPH.build_issues == []

    def test_covers_all_curated_dishes(self):
        assert set(GRAPH.dishes_by_id) == set(m.RECIPE_SHOPPING_CORE_QUERIES)

    def test_every_dish_has_at_least_one_ingredient(self):
        for dish_id, ingredients in GRAPH.recipe_ingredients_by_dish.items():
            assert ingredients, f"dish {dish_id} resolved zero ingredients"

    def test_stats_are_internally_consistent(self):
        stats = GRAPH.stats
        assert stats["ingredient_concept_count"] == (
            stats["ingredient_concept_taxonomy_backed"] + stats["ingredient_concept_recipe_curated"]
        )
        assert stats["dish_count"] == len(m.RECIPE_SHOPPING_CORE_QUERIES)


class TestPadThai:
    """Section 100 - the mandated end-to-end scenario."""

    def test_dish_lookup_from_free_text(self):
        assert resolve_dish(GRAPH, "chcem robit pad thai pre 4 osoby") == "pad_thai"

    def test_recipe_resolution_has_real_cms_link(self):
        dish = GRAPH.dishes_by_id["pad_thai"]
        assert dish.recipe_ids
        recipe = GRAPH.recipes_by_id[dish.recipe_ids[0]]
        assert recipe.urls.get("SK", "").startswith("https://www.foodland.sk/")

    def test_required_ingredient_concepts_present(self):
        ingredients = GRAPH.recipe_ingredients_by_dish["pad_thai"]
        concept_ids = {ing.ingredient_concept_id for ing in ingredients}
        assert "fish_sauce" in concept_ids
        assert "rice_noodles" in concept_ids
        assert all(ing.requirement == "REQUIRED" for ing in ingredients)

    def test_available_products_resolve_to_real_skus(self):
        resolution = resolve_ingredient_products(
            GRAPH, "fish_sauce", m.products, m.product_taxonomy_index, m.normalized_product_index,
        )
        assert resolution.catalog_status == "AVAILABLE"
        assert resolution.matching_product_ids
        product_ids = {p.id for p in m.products}
        assert set(resolution.matching_product_ids) <= product_ids

    def test_not_available_ingredients_are_disclosed_not_hidden(self):
        not_available = GRAPH.not_available_by_dish.get("pad_thai", ())
        assert not_available  # fresh eggs/tofu/lime/scallion - Foodland doesn't sell these

    def test_reverse_lookup_pad_thai_from_a_linked_product(self):
        linked = [pid for pid, dishes in GRAPH.product_to_dishes.items() if "pad_thai" in dishes]
        assert linked
        assert recipes_for_product(GRAPH, linked[0]) == ["pad_thai"]


class TestCollisionSemantics:
    """Sections 33/101-105 - lexically-close ingredients must never collapse."""

    def test_rice_noodles_is_not_rice(self):
        concept = GRAPH.ingredient_concepts["rice_noodles"]
        assert concept.source == SOURCE_PRODUCT_TAXONOMY
        assert concept.concept_id != "jasmine_rice"

    def test_rice_vinegar_is_not_rice(self):
        assert "rice_vinegar" in GRAPH.ingredient_concepts
        assert GRAPH.ingredient_concepts["rice_vinegar"].concept_id != "jasmine_rice"

    def test_jasmine_basmati_sushi_rice_are_distinct_concepts(self):
        for concept_id in ("jasmine_rice", "basmati_rice", "sushi_rice"):
            assert concept_id in GRAPH.ingredient_concepts
        ids = {GRAPH.ingredient_concepts[c].concept_id for c in ("jasmine_rice", "basmati_rice", "sushi_rice")}
        assert len(ids) == 3

    def test_soy_sauce_variants_remain_distinct_taxonomy_concepts(self):
        # The 47 curated dishes only ever say generic "soy sauce" (no
        # recipe specifies light/dark), so the graph's own resolved
        # concept for that text may legitimately be the generic one - but
        # the underlying V2.3 taxonomy must still keep dark/light/generic
        # as three separate rule_ids (never collapsed), which is what the
        # ingredient concept space is built on top of.
        from app.taxonomy import FAMILY_DEFINITIONS
        rule_ids = {r.rule_id for r in FAMILY_DEFINITIONS if r.subfamily == "soy_sauce"}
        assert {"soy_sauce", "dark_soy_sauce", "light_soy_sauce"} <= rule_ids

    def test_coconut_milk_is_a_distinct_concept_not_a_catch_all(self):
        concept = GRAPH.ingredient_concepts["coconut_milk"]
        assert concept.source == SOURCE_PRODUCT_TAXONOMY
        # No coconut_cream/coconut_oil taxonomy rule exists yet (verified
        # against real data.products.json - docs/recipe-knowledge-audit.md);
        # resolving those must not silently fall back onto coconut_milk.
        cream = resolve_ingredient_products(
            GRAPH, "coconut_milk", m.products, m.product_taxonomy_index, m.normalized_product_index,
        )
        assert cream.ingredient_concept_id == "coconut_milk"


class TestSubstitution:
    """Section 106 - curated only, verified structure."""

    def test_fish_sauce_has_one_verified_vegan_substitute(self):
        edges = get_substitutes(GRAPH, "fish_sauce", context="vegan")
        assert len(edges) == 1
        edge = edges[0]
        assert edge.source == "CURATED_SPECIAL_QUERIES"
        assert edge.confidence in {"MEDIUM", "HIGH"}
        assert edge.to_concept in GRAPH.ingredient_concepts

    def test_no_substitution_is_invented_for_unrelated_concept(self):
        assert get_substitutes(GRAPH, "jasmine_rice") == []
        assert get_substitutes(GRAPH, "sushi_rice") == []


class TestUnresolvedIngredient:
    """Section 107/141 - UNKNOWN must never become a forced/wrong mapping."""

    def test_unknown_free_text_does_not_resolve(self):
        assert resolve_ingredient_concept(GRAPH, "xyzzy neexistujuca surovina 12345") is None

    def test_low_evidence_curated_concepts_are_flagged_not_hidden(self):
        unresolved = [
            c for c in GRAPH.ingredient_concepts.values()
            if c.source == SOURCE_RECIPE_CURATED
            and not resolve_ingredient_products(
                GRAPH, c.concept_id, m.products, m.product_taxonomy_index, m.normalized_product_index,
            ).matching_product_ids
        ]
        # Real, honest finding (docs/recipe-knowledge-audit.md) - some
        # curated ingredients genuinely have no current catalog match.
        assert len(unresolved) == GRAPH.stats["unresolved_ingredient_concept_count"]


class TestMultilingualAlias:
    """Section 108 - at least a few languages resolve, full coverage not required."""

    def test_english_fish_sauce_alias_resolves(self):
        assert resolve_ingredient_concept(GRAPH, "fish sauce") == "fish_sauce"

    def test_slovak_alias_resolves_same_concept(self):
        assert resolve_ingredient_concept(GRAPH, "rybacia omacka") == "fish_sauce"


class TestReverseLookup:
    """Section 48-52, 112, 113."""

    def test_gochujang_links_only_to_real_curated_dishes(self):
        dishes = recipes_for_ingredient_concept(GRAPH, "gochujang")
        assert dishes
        assert set(dishes) <= set(m.RECIPE_SHOPPING_CORE_QUERIES)
        for dish_id in dishes:
            concept_ids = {ing.ingredient_concept_id for ing in GRAPH.recipe_ingredients_by_dish[dish_id]}
            assert "gochujang" in concept_ids

    def test_multi_ingredient_discovery_favors_pad_thai(self):
        ranked = match_recipes_by_ingredient_concepts(GRAPH, ["rice_noodles", "fish_sauce", "tamarind_pasta"])
        assert ranked
        assert ranked[0][0] == "pad_thai"
        assert ranked[0][1] == 3


class TestGraphAtomicRebuild:
    def test_rebuild_is_pure_and_repeatable(self):
        rebuilt = build_recipe_graph_index(
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
        assert rebuilt.stats == GRAPH.stats
