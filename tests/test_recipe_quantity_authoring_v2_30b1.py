"""
tests/test_recipe_quantity_authoring_v2_30b1.py  -  V2.30b.1 editorial
authoring-pack validation + production-isolation proof.

This file validates the STRUCTURE of the draft authoring dataset
(data/editorial/recipe_quantity_authoring_v2_30b1.json) - it never
asserts any quantity value, because every quantity in the draft is
intentionally null (V2.30a found 0/50 dishes have an authoritative
Foodland quantity source; V2.30b.1 prepares the pack for a human editor
to fill in, it does not fabricate data). The second half of this file
proves the draft is NOT loaded by the production app - editorial
authoring data and production runtime are structurally isolated.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

AUTHORING_PATH = ROOT / "data" / "editorial" / "recipe_quantity_authoring_v2_30b1.json"

ALLOWED_AUTHOR_STATUS = {"NEEDS_AUTHORING", "AUTHORED", "REVIEWED", "APPROVED", "REJECTED"}
ALLOWED_APPROVAL_STATUS = {"PENDING", "AUTHORED", "REVIEWED", "APPROVED", "REJECTED"}
ALLOWED_REQUIREMENT = {"REQUIRED", "OPTIONAL"}


@pytest.fixture(scope="module")
def dataset() -> dict:
    return json.loads(AUTHORING_PATH.read_text(encoding="utf-8"))


class TestDatasetTopLevel:
    def test_file_exists_and_parses(self, dataset):
        assert dataset["schema_version"] == 1
        assert dataset["created_for_sprint"] == "V2.30b.1"

    def test_status_is_draft_not_approved(self, dataset):
        assert dataset["status"] == "DRAFT_FOR_HUMAN_AUTHORING"
        assert dataset["status"] not in ("APPROVED", "PRODUCTION", "READY")

    def test_production_eligible_is_false(self, dataset):
        assert dataset["production_eligible"] is False

    def test_pilot_dish_count_in_range(self, dataset):
        n = len(dataset["pilot_dishes"])
        assert 3 <= n <= 5, f"expected 3-5 pilot dishes, got {n}"


class TestDishLevelIntegrity:
    def test_dish_ids_unique(self, dataset):
        ids = [d["dish_id"] for d in dataset["pilot_dishes"]]
        assert len(ids) == len(set(ids)), f"duplicate dish_id(s): {ids}"

    def test_dish_ids_are_known_recipe_shopping_dishes(self, dataset):
        import app.main as m

        known = set(m.RECIPE_SHOPPING_CORE_QUERIES.keys())
        for dish in dataset["pilot_dishes"]:
            assert dish["dish_id"] in known, f"{dish['dish_id']} is not a canonical RECIPE_SHOPPING_CORE_QUERIES dish"

    def test_no_fabricated_base_servings(self, dataset):
        # Hard safety rule (Section 5/15) - every draft row must stay null
        # unless a real source already grounded it. This sprint grounded
        # none, so every dish's base_servings must currently be null.
        for dish in dataset["pilot_dishes"]:
            assert dish["base_servings"] is None, f"{dish['dish_id']} has a non-null base_servings with no source"

    def test_pending_dish_has_no_approval_fields(self, dataset):
        for dish in dataset["pilot_dishes"]:
            if dish["approval_status"] == "PENDING":
                assert dish["approved_by"] is None
                assert dish["approved_at"] is None

    def test_approval_status_valid(self, dataset):
        for dish in dataset["pilot_dishes"]:
            assert dish["approval_status"] in ALLOWED_APPROVAL_STATUS

    def test_approved_dish_requires_full_metadata(self, dataset):
        # Strictness gate (Section 33) - exercised defensively even though
        # no dish is APPROVED today, so a future hand-edit can't silently
        # skip required fields.
        for dish in dataset["pilot_dishes"]:
            if dish["approval_status"] == "APPROVED":
                assert dish["base_servings"] is not None, f"{dish['dish_id']}: APPROVED requires base_servings"
                assert isinstance(dish["base_servings"], int) and dish["base_servings"] > 0
                assert dish["base_servings_source"], f"{dish['dish_id']}: APPROVED requires base_servings_source"
                assert dish["approved_by"], f"{dish['dish_id']}: APPROVED requires approved_by"
                assert dish["approved_at"], f"{dish['dish_id']}: APPROVED requires approved_at"


class TestIngredientLevelIntegrity:
    def test_every_canonical_ingredient_present_exactly_once(self, dataset):
        import app.main as m

        for dish in dataset["pilot_dishes"]:
            dish_id = dish["dish_id"]
            canonical = [q for q, _, _ in m.RECIPE_SHOPPING_CORE_QUERIES[dish_id]]
            plan = m._build_recipe_shopping_plan(
                m.recipe_graph_index, dish_id, m.products, m.product_taxonomy_index, m.normalized_product_index,
            )
            canonical_concepts = {ing.ingredient_concept_id for ing in plan.ingredients}
            authored_concepts = [ing["ingredient_concept_id"] for ing in dish["ingredients"]]
            assert len(authored_concepts) == len(set(authored_concepts)), (
                f"{dish_id}: duplicate ingredient_concept_id(s) in authoring pack"
            )
            assert set(authored_concepts) == canonical_concepts, (
                f"{dish_id}: authoring pack concepts {set(authored_concepts)} != canonical {canonical_concepts}"
            )

    def test_requirement_values_valid(self, dataset):
        for dish in dataset["pilot_dishes"]:
            for ing in dish["ingredients"]:
                assert ing["requirement"] in ALLOWED_REQUIREMENT, ing

    def test_author_status_valid(self, dataset):
        for dish in dataset["pilot_dishes"]:
            for ing in dish["ingredients"]:
                assert ing["author_status"] in ALLOWED_AUTHOR_STATUS, ing

    def test_no_fabricated_quantities(self, dataset):
        # Hard safety rule (Section 5/9/15) - every ingredient quantity in
        # this draft must be null. This is the single most important
        # assertion in this file.
        for dish in dataset["pilot_dishes"]:
            for ing in dish["ingredients"]:
                assert ing["quantity"] is None, (
                    f"{dish['dish_id']}/{ing['ingredient_concept_id']}: quantity must be null in this draft "
                    f"(no authoritative source grounded it)"
                )
                assert ing["unit"] is None, (
                    f"{dish['dish_id']}/{ing['ingredient_concept_id']}: unit must be null alongside a null quantity"
                )

    def test_needs_authoring_rows_have_no_source_reference(self, dataset):
        for dish in dataset["pilot_dishes"]:
            for ing in dish["ingredients"]:
                if ing["author_status"] == "NEEDS_AUTHORING":
                    assert ing["source_reference"] is None

    def test_quantity_positive_if_populated(self, dataset):
        # Defensive check for future hand-edits (Section 30/33) - exercised
        # vacuously today since all quantities are null.
        for dish in dataset["pilot_dishes"]:
            for ing in dish["ingredients"]:
                if ing["quantity"] is not None:
                    assert isinstance(ing["quantity"], (int, float)) and ing["quantity"] > 0

    def test_approved_quantity_requires_unit_and_source(self, dataset):
        for dish in dataset["pilot_dishes"]:
            for ing in dish["ingredients"]:
                if ing["author_status"] == "APPROVED" and ing["quantity"] is not None:
                    assert ing["unit"], f"{dish['dish_id']}/{ing['ingredient_concept_id']}: APPROVED quantity requires unit"
                    assert ing["source_reference"], (
                        f"{dish['dish_id']}/{ing['ingredient_concept_id']}: APPROVED quantity requires source_reference"
                    )

    def test_scaling_unit_readiness_values_valid(self, dataset):
        allowed = {"MASS_VOLUME_READY", "COUNT_UNIT_UNSUPPORTED", "CULINARY_MEASURE_UNSUPPORTED", "UNGROUNDED"}
        for dish in dataset["pilot_dishes"]:
            for ing in dish["ingredients"]:
                assert ing["scaling_unit_readiness"] in allowed, ing

    def test_package_size_readiness_values_valid(self, dataset):
        allowed = {"PACKAGE_SIZE_READY", "PARTIAL_PACKAGE_SIZE", "NO_STRUCTURED_PACKAGE_SIZE", "COUNT_UNIT_BLOCKED"}
        for dish in dataset["pilot_dishes"]:
            for ing in dish["ingredients"]:
                assert ing["package_size_readiness"] in allowed, ing


class TestProductionIsolation:
    """Proves editorial authoring data and production runtime are
    structurally separate - the single most important guarantee in this
    sprint (Section 35/36)."""

    def test_no_production_module_references_the_authoring_file(self):
        app_dir = ROOT / "app"
        needle_variants = ("recipe_quantity_authoring_v2_30b1", "data/editorial", "data\\editorial")
        hits = []
        for path in app_dir.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for needle in needle_variants:
                if needle in text:
                    hits.append((path.name, needle))
        assert not hits, f"production code references the editorial draft: {hits}"

    def test_real_dishes_still_have_null_quantity_and_package_count(self):
        import app.main as m

        for dish_id in ("pad_thai", "tom_kha", "sushi", "tom_yum", "kimchi_ramen"):
            plan = m._build_recipe_shopping_plan(
                m.recipe_graph_index, dish_id, m.products, m.product_taxonomy_index, m.normalized_product_index,
                servings=6,
            )
            for ing in plan.ingredients:
                assert ing.quantity is None, f"{dish_id}/{ing.ingredient_concept_id}: quantity unexpectedly populated"
                assert ing.package_count is None, f"{dish_id}/{ing.ingredient_concept_id}: package_count unexpectedly populated"

    def test_chat_behavior_unaffected_for_pilot_dishes(self):
        # Note: app.recipe_shopping.summarize_plan()'s JSON shape never
        # includes "quantity"/"package_count" keys at all (checked
        # directly against its source) - those stay PlanIngredient-level
        # only, so this test checks the one thing the JSON layer actually
        # carries: routing/workflow/plan presence is unaffected by this
        # sprint's draft file existing on disk. The PlanIngredient-level
        # quantity/package_count check lives in the test above, against
        # the real dataclass fields.
        import app.main as m

        class _FakeRequest:
            class client:
                host = "127.0.0.1"
            headers: dict = {}

        r = m.chat(
            m.ChatRequest(message="Aké suroviny na sushi predávate?", session_id="v230b1-isolation-check", limit=8),
            _FakeRequest(),
        )
        assert r.get("intent") == "recipe_to_products"
        assert r.get("workflow_id") == "RECIPE_SHOPPING"
        assert r.get("recipe_shopping_plan") is not None
        assert r.get("products")
