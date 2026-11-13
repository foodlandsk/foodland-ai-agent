"""
tests/test_grounded_recipe_scaling_v2_30c.py  -  V2.30c Grounded Recipe
Scaling Pilot Activation.

Follows V2.30b.1 (authoring), V2.30b.1a (Foodland source ingestion),
V2.30b.2 (approved-data readiness validation). This sprint wires the
already-APPROVED subset of data/editorial/recipe_quantity_authoring_
v2_30b1.json into app.recipe_shopping.build_recipe_shopping_plan() via
the new, fail-closed app.recipe_quantities loader.

Covers: the loader's own validation/fail-closed behavior against
synthetic fixtures (never the live catalog, so these don't drift with
future editorial edits), the real-dataset integration (dynamically
derived from the dataset file, never hardcoded historical counts), the
real production-function wiring (scale_quantity/package_count_for
against real pad_thai/tom_kha/sushi/kimchi_ramen data and the real
catalog), non-pilot immutability, unapproved-row isolation, unsupported-
unit safety, session persistence, and the direct-search/informational
routing boundaries.
"""
from __future__ import annotations

import json
import os
import sys
from math import ceil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m  # noqa: E402
from app.ingredients import convert_to_base_unit  # noqa: E402
from app.recipe_quantities import (  # noqa: E402
    AUTHORING_DATASET_PATH,
    ApprovedIngredientQuantity,
    _load,
    _validate_and_build,
    get_approved_ingredient_quantity,
    get_base_servings,
)
from app.recipe_shopping import best_fit_package_count, build_recipe_shopping_plan, package_count_for  # noqa: E402
from app.session_state import get_active_recipe  # noqa: E402

PILOT_DISHES = ("pad_thai", "tom_kha", "sushi", "tom_yum", "kimchi_ramen")


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, limit: int = 6) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


def _minimal_dish(**overrides) -> dict:
    dish = {
        "dish_id": "pad_thai",
        "approval_status": "APPROVED",
        "base_servings": 2,
        "ingredients": [
            {
                "ingredient_concept_id": "rice_noodles",
                "author_status": "APPROVED",
                "quantity": 250,
                "unit": "g",
                "source_reference": "https://www.foodland.sk/recepty/pad-thai/",
                "source_type": "FOODLAND_RECIPE_ARTICLE",
            },
        ],
    }
    dish.update(overrides)
    return dish


# ---------------------------------------------------------------------------
# Loader validation - synthetic fixtures only (Section 49).
# ---------------------------------------------------------------------------
class TestLoaderValidation:
    def test_valid_dataset_builds_expected_lookups(self):
        raw = {"pilot_dishes": [_minimal_dish()]}
        result = _validate_and_build(raw)
        assert result.base_servings_by_dish == {"pad_thai": 2}
        assert result.ingredient_quantities == {
            ("pad_thai", "rice_noodles"): ApprovedIngredientQuantity(
                quantity=250.0, unit="g",
                source_reference="https://www.foodland.sk/recepty/pad-thai/",
                source_type="FOODLAND_RECIPE_ARTICLE",
            ),
        }

    def test_duplicate_ingredient_concept_raises(self):
        dish = _minimal_dish()
        dish["ingredients"].append(dict(dish["ingredients"][0]))
        with pytest.raises(ValueError, match="duplicate"):
            _validate_and_build({"pilot_dishes": [dish]})

    def test_approved_row_missing_quantity_is_skipped_not_fabricated(self):
        dish = _minimal_dish()
        dish["ingredients"][0]["quantity"] = None
        result = _validate_and_build({"pilot_dishes": [dish]})
        assert result.ingredient_quantities == {}
        # the dish itself is still dish-level approved with a real base_servings
        assert result.base_servings_by_dish == {"pad_thai": 2}

    def test_approved_row_missing_source_reference_is_skipped(self):
        dish = _minimal_dish()
        dish["ingredients"][0]["source_reference"] = None
        result = _validate_and_build({"pilot_dishes": [dish]})
        assert result.ingredient_quantities == {}

    def test_approved_row_missing_unit_is_skipped(self):
        dish = _minimal_dish()
        dish["ingredients"][0]["unit"] = None
        result = _validate_and_build({"pilot_dishes": [dish]})
        assert result.ingredient_quantities == {}

    @pytest.mark.parametrize("bad_base_servings", [None, 0, -1, "4", 4.5, True])
    def test_invalid_base_servings_disables_scaling_for_that_dish_only(self, bad_base_servings):
        dish = _minimal_dish(base_servings=bad_base_servings)
        result = _validate_and_build({"pilot_dishes": [dish]})
        assert result.base_servings_by_dish == {}
        # the ingredient row is still a legitimately APPROVED row; a
        # missing base_servings alone must not also erase its quantity -
        # app.recipe_shopping is the layer that additionally gates on
        # base_servings before using it (Section 6).
        assert ("pad_thai", "rice_noodles") in result.ingredient_quantities

    def test_dish_not_dish_level_approved_yields_no_lookups_even_with_approved_rows(self):
        dish = _minimal_dish(approval_status="AUTHORED")
        result = _validate_and_build({"pilot_dishes": [dish]})
        assert result.base_servings_by_dish == {}
        assert result.ingredient_quantities == {}

    @pytest.mark.parametrize("author_status", ["NEEDS_AUTHORING", "AUTHORED", "REVIEWED", "REJECTED"])
    def test_non_approved_author_status_never_populates_a_quantity(self, author_status):
        dish = _minimal_dish()
        dish["ingredients"][0]["author_status"] = author_status
        result = _validate_and_build({"pilot_dishes": [dish]})
        assert result.ingredient_quantities == {}

    @pytest.mark.parametrize("bad_quantity", [0, -5, True, "250"])
    def test_invalid_quantity_values_are_skipped(self, bad_quantity):
        dish = _minimal_dish()
        dish["ingredients"][0]["quantity"] = bad_quantity
        result = _validate_and_build({"pilot_dishes": [dish]})
        assert result.ingredient_quantities == {}


class TestLoaderFailClosed:
    """Whole-file fail-closed behavior (Section 12/44) - missing file,
    malformed JSON. Each test clears the module-level lru_cache before and
    after so it never leaks a stale/empty result into other tests."""

    @pytest.fixture(autouse=True)
    def _clear_cache_around_test(self):
        _load.cache_clear()
        yield
        _load.cache_clear()

    def test_missing_file_fails_closed(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.recipe_quantities.AUTHORING_DATASET_PATH", tmp_path / "does_not_exist.json")
        assert get_base_servings("pad_thai") is None
        assert get_approved_ingredient_quantity("pad_thai", "rice_noodles") is None

    def test_malformed_json_fails_closed(self, monkeypatch, tmp_path):
        bad_file = tmp_path / "broken.json"
        bad_file.write_text("{not valid json", encoding="utf-8")
        monkeypatch.setattr("app.recipe_quantities.AUTHORING_DATASET_PATH", bad_file)
        assert get_base_servings("pad_thai") is None
        assert get_approved_ingredient_quantity("pad_thai", "rice_noodles") is None

    def test_duplicate_concept_in_real_file_shape_fails_the_whole_load_closed(self, monkeypatch, tmp_path):
        dish = _minimal_dish()
        dish["ingredients"].append(dict(dish["ingredients"][0]))
        corrupt_file = tmp_path / "corrupt.json"
        corrupt_file.write_text(json.dumps({"pilot_dishes": [dish]}), encoding="utf-8")
        monkeypatch.setattr("app.recipe_quantities.AUTHORING_DATASET_PATH", corrupt_file)
        # the whole file fails closed (not just the duplicated dish) -
        # a duplicate concept id means the dataset itself is untrustworthy.
        assert get_base_servings("pad_thai") is None
        assert get_approved_ingredient_quantity("pad_thai", "rice_noodles") is None

    def test_recipe_shopping_plan_still_builds_when_loader_fails_closed(self, monkeypatch, tmp_path):
        """Section 44 - recipe shopping itself must survive a broken
        quantity dataset; only enrichment is disabled."""
        monkeypatch.setattr("app.recipe_quantities.AUTHORING_DATASET_PATH", tmp_path / "missing.json")
        plan = build_recipe_shopping_plan(
            m.recipe_graph_index, "pad_thai", m.products, m.product_taxonomy_index, m.normalized_product_index,
            servings=6,
        )
        assert plan is not None
        assert plan.base_servings is None
        for ing in plan.ingredients:
            assert ing.quantity is None
            assert ing.package_count is None


class TestLoaderUnknownDish:
    def test_unknown_dish_returns_none_for_both_lookups(self):
        assert get_base_servings("not_a_real_dish") is None
        assert get_approved_ingredient_quantity("not_a_real_dish", "anything") is None

    def test_known_dish_unknown_ingredient_returns_none(self):
        assert get_approved_ingredient_quantity("pad_thai", "not_a_real_ingredient") is None


# ---------------------------------------------------------------------------
# Real-dataset integration - values re-derived from the live file at test
# time, never hardcoded historical counts (Section 59).
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def dataset() -> dict:
    return json.loads(AUTHORING_DATASET_PATH.read_text(encoding="utf-8"))


class TestLoaderAgainstRealDataset:
    def test_base_servings_matches_dataset_for_every_pilot_dish(self, dataset):
        for dish in dataset["pilot_dishes"]:
            expected = dish["base_servings"] if dish["approval_status"] == "APPROVED" else None
            if expected is not None and not (isinstance(expected, int) and expected > 0):
                expected = None
            assert get_base_servings(dish["dish_id"]) == expected

    def test_approved_ingredient_quantities_match_dataset(self, dataset):
        for dish in dataset["pilot_dishes"]:
            dish_approved = dish["approval_status"] == "APPROVED"
            for ing in dish["ingredients"]:
                looked_up = get_approved_ingredient_quantity(dish["dish_id"], ing["ingredient_concept_id"])
                is_eligible = (
                    dish_approved
                    and ing["author_status"] == "APPROVED"
                    and ing["quantity"] is not None
                    and ing["unit"] is not None
                    and ing["source_reference"]
                )
                if is_eligible:
                    assert looked_up is not None, f"{dish['dish_id']}/{ing['ingredient_concept_id']}"
                    assert looked_up.quantity == float(ing["quantity"])
                    assert looked_up.unit == ing["unit"]
                    assert looked_up.source_reference == ing["source_reference"]
                else:
                    assert looked_up is None, f"{dish['dish_id']}/{ing['ingredient_concept_id']}: expected no lookup"

    def test_every_pilot_dish_is_currently_dish_level_approved_with_base_servings(self, dataset):
        # Documents the current ground truth this sprint activates against
        # (Section 9/59) - not a requirement of the loader itself (the
        # loader handles the opposite case too, per TestLoaderValidation).
        for dish in dataset["pilot_dishes"]:
            assert dish["approval_status"] == "APPROVED"
            assert get_base_servings(dish["dish_id"]) == dish["base_servings"]


# ---------------------------------------------------------------------------
# Real wiring into build_recipe_shopping_plan() - true recipe base_servings
# scaling, against real catalog products (Sections 17/20/22/23/24/26).
# ---------------------------------------------------------------------------
class TestGroundedScalingPadThai:
    """pad_thai: base_servings=2, rice_noodles APPROVED 250 g (MASS_VOLUME_READY)."""

    def _rice_noodles(self, servings):
        plan = build_recipe_shopping_plan(
            m.recipe_graph_index, "pad_thai", m.products, m.product_taxonomy_index, m.normalized_product_index,
            servings=servings,
        )
        assert plan.base_servings == 2
        return next(ing for ing in plan.ingredients if ing.ingredient_concept_id == "rice_noodles")

    def test_no_requested_servings_retains_base_quantity(self):
        # Section 21 - no fabricated target; retain the recipe's own
        # base-servings quantity.
        ing = self._rice_noodles(None)
        assert ing.quantity.quantity == 250.0
        assert ing.quantity.unit == "g"

    def test_scale_up(self):
        # Section 22 - requested (6) > base (2).
        ing = self._rice_noodles(6)
        assert ing.quantity.quantity == 750.0  # 250 * 6 / 2

    def test_scale_down(self):
        # Section 23 - requested (1) < base (2).
        ing = self._rice_noodles(1)
        assert ing.quantity.quantity == 125.0  # 250 * 1 / 2

    def test_same_servings_as_base_is_numerically_identical(self):
        # Section 24 - requested == base.
        ing = self._rice_noodles(2)
        assert ing.quantity.quantity == 250.0

    def test_mass_package_count_exact_ceil(self):
        # Section 54 - real approved quantity + real candidate products,
        # verified against the actual production function (V2.30e:
        # best_fit_package_count() over all real candidates, not just
        # selected_product_id's own package - see the tom_kha volume test
        # below for a case where those two differ; here several 400 g
        # candidates (including the selected one) tie for the minimum
        # total purchased, so the selected product's own package happens
        # to also be the best fit).
        ing = self._rice_noodles(6)  # 750 g
        assert ing.selected_product_id is not None
        candidates = [m.normalized_product_index[pid] for pid in ing.candidate_product_ids if pid in m.normalized_product_index]
        expected = best_fit_package_count(ing.quantity, candidates)
        assert expected == 2  # pinned real value: ceil(750/400)
        assert ing.package_count == expected

    def test_unsupported_culinary_unit_rows_scale_numerically_but_never_get_a_package_count(self):
        # Section 29 - tamarind_pasta (3 PL) and fish_sauce (2 PL) are
        # APPROVED with a culinary unit: quantity IS populated and scales
        # proportionally, but package_count must always stay None, at
        # every servings level, with no conversion attempted.
        for servings in (None, 1, 6):
            plan = build_recipe_shopping_plan(
                m.recipe_graph_index, "pad_thai", m.products, m.product_taxonomy_index, m.normalized_product_index,
                servings=servings,
            )
            for concept_id, base_quantity in (("tamarind_pasta", 3.0), ("fish_sauce", 2.0)):
                ing = next(i for i in plan.ingredients if i.ingredient_concept_id == concept_id)
                assert ing.quantity is not None and ing.quantity.unit == "PL"
                expected = base_quantity if not servings else base_quantity * servings / 2
                assert ing.quantity.quantity == expected
                assert ing.package_count is None

    def test_needs_authoring_rows_stay_null_regardless_of_servings(self):
        # Section 51 - palmovy_cukor/arasidy never reached APPROVED.
        plan = build_recipe_shopping_plan(
            m.recipe_graph_index, "pad_thai", m.products, m.product_taxonomy_index, m.normalized_product_index,
            servings=6,
        )
        for concept_id in ("palmovy_cukor", "arasidy"):
            ing = next(i for i in plan.ingredients if i.ingredient_concept_id == concept_id)
            assert ing.quantity is None
            assert ing.package_count is None


class TestGroundedScalingTomKha:
    """tom_kha: base_servings=4, coconut_milk APPROVED 800 ml (MASS_VOLUME_READY)."""

    def _coconut_milk(self, servings):
        plan = build_recipe_shopping_plan(
            m.recipe_graph_index, "tom_kha", m.products, m.product_taxonomy_index, m.normalized_product_index,
            servings=servings,
        )
        assert plan.base_servings == 4
        return next(ing for ing in plan.ingredients if ing.ingredient_concept_id == "coconut_milk")

    def test_scale_up(self):
        ing = self._coconut_milk(8)
        assert ing.quantity.quantity == 1600.0  # 800 * 8 / 4

    def test_scale_down(self):
        ing = self._coconut_milk(2)
        assert ing.quantity.quantity == 400.0  # 800 * 2 / 4

    def test_same_servings_as_base(self):
        ing = self._coconut_milk(4)
        assert ing.quantity.quantity == 800.0

    def test_volume_package_count_exact_ceil(self):
        # Section 55 - real approved VOLUME (ml) quantity + real candidate
        # product with a structured ml package size.
        #
        # V2.30e - package_count is now the BEST FIT across all of this
        # ingredient's real candidates (minimizing total ml purchased),
        # not necessarily selected_product_id's own package: among the 8
        # real coconut_milk candidates, a 400 ml AROY-D product gives an
        # EXACT 1600 ml / 400 ml = 4 with zero waste, beating the
        # selected/recommended 1000 ml product's 1600/1000 -> ceil = 2
        # (which would leave 400 ml of waste). selected_product_id itself
        # is untouched - only the internal package_count number changed.
        ing = self._coconut_milk(8)  # 1600 ml
        selected_product = m.normalized_product_index[ing.selected_product_id]
        assert ing.selected_product_id == "FL_10217"  # recommendation unchanged
        assert package_count_for(ing.quantity, selected_product) == 2  # old (pre-V2.30e) number

        candidates = [m.normalized_product_index[pid] for pid in ing.candidate_product_ids if pid in m.normalized_product_index]
        expected = best_fit_package_count(ing.quantity, candidates)
        assert expected == 4  # pinned real value: the 400 ml product, exact fit
        assert ing.package_count == expected

    def test_dish_level_approval_covers_all_five_ingredients(self):
        # tom_kha is the one pilot dish with 5/5 ingredient rows APPROVED
        # (Section 9) - every row gets a real (possibly culinary-unit,
        # package-count-less) quantity, none stay null.
        plan = build_recipe_shopping_plan(
            m.recipe_graph_index, "tom_kha", m.products, m.product_taxonomy_index, m.normalized_product_index,
        )
        assert len(plan.ingredients) == 5
        for ing in plan.ingredients:
            assert ing.quantity is not None, f"tom_kha/{ing.ingredient_concept_id} unexpectedly null"


class TestPartialGroundingSushi:
    """sushi: base_servings=2, only sushi_rice/rice_vinegar APPROVED
    (2 of 6 ingredient rows) - the clearest real partial-grounding case
    (Section 25)."""

    def test_approved_rows_scale_unapproved_rows_stay_null(self):
        plan = build_recipe_shopping_plan(
            m.recipe_graph_index, "sushi", m.products, m.product_taxonomy_index, m.normalized_product_index,
            servings=6,
        )
        assert plan.base_servings == 2
        by_concept = {ing.ingredient_concept_id: ing for ing in plan.ingredients}

        assert by_concept["sushi_rice"].quantity.quantity == 1200.0  # 400 * 6 / 2
        assert by_concept["sushi_rice"].package_count is not None
        assert by_concept["rice_vinegar"].quantity.quantity == 240.0  # 80 * 6 / 2
        assert by_concept["rice_vinegar"].package_count is not None

        for concept_id in ("wasabi", "nori", "nakladany_zazvor", "sojova_omacka"):
            assert by_concept[concept_id].quantity is None
            assert by_concept[concept_id].package_count is None


class TestPackageCountNoMatch:
    def test_approved_quantity_against_product_without_structured_package_size_is_none(self):
        # Section 56 - a real approved quantity, paired with a product
        # that has no structured package size, must yield None.
        approved = get_approved_ingredient_quantity("sushi", "sushi_rice")
        assert approved is not None
        from app.ingredients import ParsedQuantity
        from app.product_normalizer import PackageSize

        required = ParsedQuantity(quantity=approved.quantity, unit=approved.unit, is_numeric=True, raw_text="400 g")
        unstructured_product = type("FakeProduct", (), {"package_size": PackageSize(raw="neurcite")})()
        assert package_count_for(required, unstructured_product) is None


class TestNonPilotImmutability:
    """Section 50 - representative non-pilot dishes must behave exactly
    as before this sprint: quantity/package_count always None."""

    @pytest.mark.parametrize("dish_id", ["kung_pao", "pho", "ramen", "curry", "tacos"])
    def test_non_pilot_dish_quantity_and_package_count_stay_null(self, dish_id):
        graph = m.recipe_graph_index
        if dish_id not in graph.dishes_by_id:
            pytest.skip(f"{dish_id} not present in current recipe graph")
        plan = build_recipe_shopping_plan(
            graph, dish_id, m.products, m.product_taxonomy_index, m.normalized_product_index, servings=6,
        )
        assert plan is not None
        assert plan.base_servings is None
        for ing in plan.ingredients:
            assert ing.quantity is None, f"{dish_id}/{ing.ingredient_concept_id}"
            assert ing.package_count is None, f"{dish_id}/{ing.ingredient_concept_id}"


class TestSessionPersistence:
    """Section 37 - requested servings and the active recipe persist
    across turns; since the servings/dish_id tuple is what drives
    build_recipe_shopping_plan()'s scaling, persisting that tuple is what
    guarantees "scaled quantities remain consistent" turn to turn."""

    def test_pad_thai_servings_persist_across_a_followup_turn(self):
        sid = "v230c-session-1"
        r1 = _chat("Chcem robit Pad Thai pre 6. Co potrebujem?", sid)
        assert r1.get("recipe_shopping_plan") is not None
        assert r1["recipe_shopping_plan"]["dish_id"] == "pad_thai"
        memory = m.get_session_memory(sid)
        dish_id, servings = get_active_recipe(memory)
        assert dish_id == "pad_thai"
        assert servings == 6

        r2 = _chat("co este potrebujem?", sid)
        assert r2.get("recipe_shopping_plan") is not None
        assert r2["recipe_shopping_plan"]["dish_id"] == "pad_thai"
        dish_id_2, servings_2 = get_active_recipe(memory)
        assert (dish_id_2, servings_2) == (dish_id, servings)

        # Consistency: both turns' internal plans are a pure function of
        # (dish_id, servings) - rebuilding directly proves what both
        # turns actually scaled to, since summarize_plan() never exposes
        # quantity in the chat JSON (Section 42/43).
        plan = build_recipe_shopping_plan(
            m.recipe_graph_index, dish_id_2, m.products, m.product_taxonomy_index, m.normalized_product_index,
            servings=servings_2,
        )
        rice_noodles = next(i for i in plan.ingredients if i.ingredient_concept_id == "rice_noodles")
        assert rice_noodles.quantity.quantity == 750.0  # 250 * 6 / 2


class TestRoutingAndProductSearchBoundaries:
    """Sections 38/39/40/41 - this sprint only enriches the already-
    existing RECIPE_SHOPPING plan-building path; it must not change
    intent/workflow routing anywhere, and must never reach direct
    product-search or purely-informational recipe queries at all."""

    def test_direct_product_search_never_touches_recipe_shopping(self):
        r = _chat("Chcem sushi ryzu.", "v230c-boundary-1")
        assert r.get("recipe_shopping_plan") is None

    def test_informational_recipe_query_never_builds_a_plan(self):
        r = _chat("Co je Pad Thai?", "v230c-boundary-2")
        assert r.get("intent") == "recipe"
        assert r.get("recipe_shopping_plan") is None

    def test_recipe_instruction_query_never_builds_a_plan(self):
        r = _chat("Ako urobit Pad Thai?", "v230c-boundary-3")
        assert r.get("intent") == "recipe"
        assert r.get("recipe_shopping_plan") is None

    def test_pad_thai_shopping_query_routing_unchanged(self):
        # Mirrors tests/test_recipe_shopping.py's pre-existing assertion -
        # confirms 0 routing drift from this sprint.
        r = _chat("Chcem robit Pad Thai. Co potrebujem?", "v230c-boundary-4")
        assert r.get("intent") == "recipe_to_products"
        assert r.get("workflow_id") == "RECIPE_SHOPPING"
        assert r.get("workflow_confidence") == 0.9
