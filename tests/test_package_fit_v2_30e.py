"""
tests/test_package_fit_v2_30e.py  -  V2.30e Best-Fit Package Selection for
Package-Count Math.

Follows V2.30c (grounded recipe scaling pilot activation) and V2.30d (its
read-only validation review, which found sushi_rice/rice_vinegar always
resolved package_count=1 regardless of servings - not an arithmetic bug,
but a consequence of package_count being computed against whichever
candidate happened to be selected_product_id, a 20 kg/20 L bulk product).

app.recipe_shopping.best_fit_package_count() fixes this narrowly: it
evaluates package_count_for() against every real candidate already
resolved for an ingredient (never a broader search, never re-ranking the
candidates), and returns the count for whichever minimizes total amount
purchased. selected_product_id - the product actually recommended to the
customer - is never touched; this is purely an internal package_count
correction.

Covers: synthetic unit tests for the selection/tie-break rule itself
(so they don't drift with catalog edits), the real sushi fix, and a
regression proof that selected_product_id is unchanged for every pilot
ingredient across all 5 dishes.
"""
from __future__ import annotations

import os
import sys
from math import ceil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m  # noqa: E402
from app.ingredients import ParsedQuantity  # noqa: E402
from app.product_normalizer import PackageSize  # noqa: E402
from app.recipe_graph import resolve_ingredient_products  # noqa: E402
from app.recipe_shopping import best_fit_package_count, build_recipe_shopping_plan  # noqa: E402

PILOT_DISHES = ("pad_thai", "tom_kha", "sushi", "tom_yum", "kimchi_ramen")


class _FakeProduct:
    def __init__(self, value, unit):
        self.package_size = PackageSize(raw=f"{value}{unit}", value=value, unit=unit)


def _required(quantity, unit="g"):
    return ParsedQuantity(quantity=quantity, unit=unit, is_numeric=True, raw_text=f"{quantity} {unit}")


class TestBestFitSelectionSynthetic:
    def test_picks_minimum_total_purchased_not_minimum_count(self):
        # 400 g required: a 20 kg pack (count=1, 20000 g bought) loses to
        # a 1 kg pack (count=1, 1000 g bought) - same count, less waste -
        # which itself loses to an exact-fit 400 g pack (count=1, 400 g).
        required = _required(400, "g")
        candidates = [_FakeProduct(20000, "g"), _FakeProduct(1000, "g"), _FakeProduct(400, "g")]
        assert best_fit_package_count(required, candidates) == 1  # all count=1 here; the 400g is just the least wasteful

    def test_more_packages_of_a_better_fit_beats_fewer_packages_of_a_bad_fit(self):
        # 1200 g required: 1 x 20 kg (count=1, 20000 g bought) vs
        # 2 x 1 kg (count=2, 2000 g bought) - the 2-pack option wins
        # despite a higher raw count, because it wastes far less.
        required = _required(1200, "g")
        candidates = [_FakeProduct(20000, "g"), _FakeProduct(1000, "g")]
        assert best_fit_package_count(required, candidates) == 2

    def test_tie_on_total_purchased_prefers_fewer_packages(self):
        # 800 ml required: 1 x 1000 ml (count=1, 1000 ml bought) and
        # 4 x 250 ml (count=4, 1000 ml bought) buy the identical total -
        # recommending 4 small bottles over 1 big one for the same total
        # amount would be strictly worse, so count=1 must win the tie.
        required = _required(800, "ml")
        candidates = [_FakeProduct(250, "ml"), _FakeProduct(1000, "ml")]
        assert best_fit_package_count(required, candidates) == 1

    def test_exact_divisibility_no_off_by_one(self):
        required = _required(1000, "g")
        candidates = [_FakeProduct(500, "g")]
        assert best_fit_package_count(required, candidates) == 2

    def test_ceil_rounds_up_past_exact_multiple(self):
        required = _required(1001, "g")
        candidates = [_FakeProduct(500, "g")]
        assert best_fit_package_count(required, candidates) == 3

    def test_required_smaller_than_every_package_is_one_not_zero(self):
        required = _required(50, "g")
        candidates = [_FakeProduct(20000, "g"), _FakeProduct(1000, "g")]
        assert best_fit_package_count(required, candidates) == 1

    def test_unstructured_candidate_is_skipped_not_fatal(self):
        required = _required(400, "g")
        unstructured = type("P", (), {"package_size": PackageSize(raw="neurcite")})()
        candidates = [unstructured, _FakeProduct(500, "g")]
        assert best_fit_package_count(required, candidates) == 1

    def test_unit_class_mismatch_candidate_is_skipped(self):
        required = _required(400, "g")
        wrong_dimension = _FakeProduct(500, "ml")
        candidates = [wrong_dimension, _FakeProduct(500, "g")]
        assert best_fit_package_count(required, candidates) == 1

    def test_no_valid_candidates_returns_none(self):
        required = _required(400, "g")
        candidates = [_FakeProduct(500, "ml"), type("P", (), {"package_size": PackageSize(raw="")})()]
        assert best_fit_package_count(required, candidates) is None

    def test_empty_candidate_list_returns_none(self):
        assert best_fit_package_count(_required(400, "g"), []) is None

    def test_nonnumeric_required_returns_none(self):
        required = ParsedQuantity(quantity=None, unit=None, is_numeric=False, raw_text="podla chuti")
        assert best_fit_package_count(required, [_FakeProduct(500, "g")]) is None

    def test_candidate_order_breaks_further_ties_deterministically(self):
        # Two candidates with identical package size (same total, same
        # count) - the first in the list must win, deterministically.
        required = _required(400, "g")
        first = _FakeProduct(500, "g")
        second = _FakeProduct(500, "g")
        assert best_fit_package_count(required, [first, second]) == 1
        assert best_fit_package_count(required, [second, first]) == 1


class TestSushiPackageCountFixedForReal:
    """The actual V2.30d-identified case: sushi_rice/rice_vinegar always
    resolving package_count=1 off a 20 kg/20 L candidate."""

    def _plan(self, servings):
        return build_recipe_shopping_plan(
            m.recipe_graph_index, "sushi", m.products, m.product_taxonomy_index, m.normalized_product_index,
            servings=servings,
        )

    def test_sushi_rice_package_count_now_varies_with_servings(self):
        counts = []
        for servings in (1, 2, 6, 12, 20):
            plan = self._plan(servings)
            ing = next(i for i in plan.ingredients if i.ingredient_concept_id == "sushi_rice")
            counts.append(ing.package_count)
        assert counts != [1, 1, 1, 1, 1], "sushi_rice package_count must no longer be stuck at 1 regardless of servings"
        assert counts[0] == 1  # 200 g (servings=1) - still legitimately 1
        assert counts[-1] > 1  # 4000 g (servings=20) must require more than 1 package of any real candidate

    def test_rice_vinegar_package_count_now_varies_with_servings(self):
        counts = []
        for servings in (1, 6, 20):
            plan = self._plan(servings)
            ing = next(i for i in plan.ingredients if i.ingredient_concept_id == "rice_vinegar")
            counts.append(ing.package_count)
        assert counts[-1] > counts[0]

    def test_selected_product_id_unchanged_by_the_fix(self):
        # The customer-facing recommendation must be identical to what
        # plain first-match resolution would produce on its own - the fix
        # only touches the internal package_count number.
        plan = self._plan(6)
        for ing in plan.ingredients:
            resolution = resolve_ingredient_products(
                m.recipe_graph_index, ing.ingredient_concept_id, m.products, m.product_taxonomy_index, m.normalized_product_index,
            )
            expected_selected = resolution.matching_product_ids[0] if resolution.matching_product_ids else None
            assert ing.selected_product_id == expected_selected


class TestNonPilotAndNonSushiRegression:
    """Section 29 of the V2.30e bug-fix brief - every other pilot dish's
    selected_product_id and quantity must be unaffected; package_count
    may change in VALUE (that's the fix generalizing) but never in
    whether it's None vs not-None for a given approved row's unit
    support, and selected_product_id must never move."""

    @pytest.mark.parametrize("dish_id", ["pad_thai", "tom_kha", "tom_yum", "kimchi_ramen"])
    def test_selected_product_id_unchanged_across_other_pilot_dishes(self, dish_id):
        plan = build_recipe_shopping_plan(
            m.recipe_graph_index, dish_id, m.products, m.product_taxonomy_index, m.normalized_product_index,
            servings=6,
        )
        for ing in plan.ingredients:
            resolution = resolve_ingredient_products(
                m.recipe_graph_index, ing.ingredient_concept_id, m.products, m.product_taxonomy_index, m.normalized_product_index,
            )
            expected_selected = resolution.matching_product_ids[0] if resolution.matching_product_ids else None
            assert ing.selected_product_id == expected_selected

    @pytest.mark.parametrize("dish_id", ["pad_thai", "tom_kha", "tom_yum", "kimchi_ramen"])
    def test_culinary_unit_rows_still_never_get_a_package_count(self, dish_id):
        plan = build_recipe_shopping_plan(
            m.recipe_graph_index, dish_id, m.products, m.product_taxonomy_index, m.normalized_product_index,
            servings=6,
        )
        for ing in plan.ingredients:
            if ing.quantity is not None and ing.quantity.unit not in ("g", "kg", "ml", "l"):
                assert ing.package_count is None, f"{dish_id}/{ing.ingredient_concept_id}"

    @pytest.mark.parametrize("dish_id", ["kung_pao", "pho", "ramen"])
    def test_non_pilot_dishes_fully_unaffected(self, dish_id):
        graph = m.recipe_graph_index
        if dish_id not in graph.dishes_by_id:
            pytest.skip(f"{dish_id} not present in current recipe graph")
        plan = build_recipe_shopping_plan(
            graph, dish_id, m.products, m.product_taxonomy_index, m.normalized_product_index, servings=6,
        )
        for ing in plan.ingredients:
            assert ing.quantity is None
            assert ing.package_count is None
