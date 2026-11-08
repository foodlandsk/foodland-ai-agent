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


FOODLAND_URL_PREFIX = "https://www.foodland.sk/"


class TestDatasetTopLevel:
    def test_file_exists_and_parses(self, dataset):
        assert dataset["schema_version"] == 1
        assert dataset["created_for_sprint"] == "V2.30b.1"

    def test_status_is_partial_not_fully_approved(self, dataset):
        # V2.30b.1a grounded some rows against real Foodland recipe pages
        # (PENDING_HUMAN_REVIEW); a human reviewer (Foodland editorial) then
        # approved the rows/dishes that were unambiguous, moving the
        # dataset to PARTIALLY_APPROVED_PENDING_FULL_AUTHORING. The exact
        # literal string "APPROVED"/"PRODUCTION"/"READY" must still never
        # be the whole-dataset status - full approval is a future state.
        assert dataset["status"] == "PARTIALLY_APPROVED_PENDING_FULL_AUTHORING"
        assert dataset["status"] not in ("APPROVED", "PRODUCTION", "READY")

    def test_production_eligible_is_false(self, dataset):
        assert dataset["production_eligible"] is False

    def test_pilot_dish_count_in_range(self, dataset):
        n = len(dataset["pilot_dishes"])
        assert 3 <= n <= 5, f"expected 3-5 pilot dishes, got {n}"

    def test_source_manifest_entries_are_valid_foodland_urls(self, dataset):
        manifest = dataset["source_manifest"]
        dish_ids = {d["dish_id"] for d in dataset["pilot_dishes"]}
        seen = set()
        for entry in manifest:
            assert entry["dish_id"] in dish_ids
            seen.add(entry["dish_id"])
            url = entry["source_url"]
            assert url.startswith(FOODLAND_URL_PREFIX), f"non-Foodland source URL: {url}"
            assert entry["source_type"] == "FOODLAND_RECIPE_ARTICLE"
        assert seen == dish_ids, "every pilot dish must have a source_manifest entry"

    def test_unmapped_foodland_ingredients_reference_known_dishes_and_urls(self, dataset):
        dish_ids = {d["dish_id"] for d in dataset["pilot_dishes"]}
        for row in dataset["unmapped_foodland_recipe_ingredients"]:
            assert row["dish_id"] in dish_ids
            assert row["foodland_url"].startswith(FOODLAND_URL_PREFIX)
            assert row["source_ingredient"]
            assert row["reason_not_mapped"]


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
        # Hard safety rule (Section 5/15) - a non-null base_servings is only
        # legitimate when it is grounded by a recorded base_servings_source
        # that itself points at an official Foodland page. V2.30b.1a grounds
        # pad_thai and tom_yum this way; every other dish stays null,
        # including tom_kha, whose source states conflicting serving counts
        # ("4 osoby / 8 porcií") and must not be silently resolved.
        for dish in dataset["pilot_dishes"]:
            if dish["base_servings"] is None:
                continue
            assert isinstance(dish["base_servings"], int) and dish["base_servings"] > 0
            source = dish["base_servings_source"]
            assert source, f"{dish['dish_id']}: non-null base_servings requires base_servings_source"
            assert FOODLAND_URL_PREFIX in source, (
                f"{dish['dish_id']}: base_servings_source must reference an official Foodland URL"
            )

    def test_servings_conflict_dishes_stay_null_and_are_flagged(self, dataset):
        for dish in dataset["pilot_dishes"]:
            note = dish.get("editorial_review_note")
            if note and "SERVINGS_SOURCE_CONFLICT" in note:
                assert dish["base_servings"] is None, (
                    f"{dish['dish_id']}: flagged SERVINGS_SOURCE_CONFLICT must keep base_servings null"
                )

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
        # Hard safety rule (Section 5/9/15), updated for V2.30b.1a: a
        # non-null quantity is only legitimate when author_status is
        # AUTHORED (never a bare NEEDS_AUTHORING guess) AND it carries a
        # source_reference that is an official Foodland recipe-article URL
        # with source_type FOODLAND_RECIPE_ARTICLE. This is still the single
        # most important assertion in this file - it is what stops a
        # fabricated/LLM-inferred/non-Foodland number from ever landing here.
        for dish in dataset["pilot_dishes"]:
            for ing in dish["ingredients"]:
                if ing["quantity"] is None:
                    assert ing["unit"] is None, (
                        f"{dish['dish_id']}/{ing['ingredient_concept_id']}: unit must be null alongside a null quantity"
                    )
                    continue
                assert ing["author_status"] in ("AUTHORED", "REVIEWED", "APPROVED"), (
                    f"{dish['dish_id']}/{ing['ingredient_concept_id']}: non-null quantity requires an "
                    f"AUTHORED/REVIEWED/APPROVED status (never NEEDS_AUTHORING/REJECTED), got {ing['author_status']!r}"
                )
                assert ing["unit"], (
                    f"{dish['dish_id']}/{ing['ingredient_concept_id']}: non-null quantity requires a unit"
                )
                assert ing["source_type"] == "FOODLAND_RECIPE_ARTICLE", (
                    f"{dish['dish_id']}/{ing['ingredient_concept_id']}: authored quantity requires source_type FOODLAND_RECIPE_ARTICLE"
                )
                ref = ing["source_reference"]
                assert ref and ref.startswith(FOODLAND_URL_PREFIX), (
                    f"{dish['dish_id']}/{ing['ingredient_concept_id']}: authored quantity requires an official Foodland source_reference"
                )
                assert ing["source_quantity_text"], (
                    f"{dish['dish_id']}/{ing['ingredient_concept_id']}: authored quantity requires traceable source_quantity_text"
                )

    def test_authored_rows_have_high_confidence_mapping(self, dataset):
        for dish in dataset["pilot_dishes"]:
            for ing in dish["ingredients"]:
                if ing["author_status"] in ("AUTHORED", "REVIEWED", "APPROVED") and ing["quantity"] is not None:
                    assert ing["mapping_confidence"] in ("EXACT", "HIGH"), (
                        f"{dish['dish_id']}/{ing['ingredient_concept_id']}: only EXACT/HIGH mapping confidence "
                        f"may auto-populate a row (got {ing['mapping_confidence']!r})"
                    )

    def test_mapping_confidence_values_valid(self, dataset):
        allowed = {"EXACT", "HIGH", "AMBIGUOUS", "NO_MATCH", None}
        for dish in dataset["pilot_dishes"]:
            for ing in dish["ingredients"]:
                assert ing.get("mapping_confidence") in allowed, ing

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

    def test_authoring_file_now_has_populated_quantities(self, dataset):
        # Sanity check that this test module is actually exercising the
        # post-ingestion state, not a stale/empty draft (Section 48).
        authored = [
            ing
            for dish in dataset["pilot_dishes"]
            for ing in dish["ingredients"]
            if ing["quantity"] is not None
        ]
        assert len(authored) >= 10, "expected the V2.30b.1a ingestion to have authored several rows"

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
