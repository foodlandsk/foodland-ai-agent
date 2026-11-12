"""
tests/test_recipe_quantity_approval_readiness_v2_30b2.py  -  V2.30b.2
approved-data validation sprint.

Validates scripts/recipe_quantity_approval_readiness_audit_v2_30b2.py:
the classification logic against synthetic fixtures (so these assertions
don't drift with the live catalog), the full audit against the real
V2.30b.1 dataset (sanity against current approved rows), and - the single
most important guarantee, matching every prior sprint in this family -
that this new audit/report stays structurally isolated from production:
no app/ module references it, and it never claims production_eligible.
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

from scripts.recipe_quantity_approval_readiness_audit_v2_30b2 import (  # noqa: E402
    AUTHORING_PATH,
    NOT_QUANTIFIED,
    QUANTITY_READY_NO_PACKAGE_DATA,
    QUANTITY_UNIT_UNSUPPORTED,
    REPORT_PATH,
    SCALING_READY_TODAY,
    _classify_ingredient,
    audit_approved_rows,
    build_report,
)


def _base_ingredient(**overrides) -> dict:
    row = {
        "_dish_id": "pad_thai",
        "ingredient_concept_id": "rice_noodles",
        "requirement": "REQUIRED",
        "quantity": None,
        "unit": None,
        "scaling_unit_readiness": "UNGROUNDED",
        "source_quantity_text": None,
    }
    row.update(overrides)
    return row


class _FakePackageSize:
    def __init__(self, value, unit):
        self.value = value
        self.unit = unit
        self.is_structured = value is not None and unit is not None


class _FakeNormalizedProduct:
    def __init__(self, package_size):
        self.package_size = package_size


class TestClassifyIngredientSynthetic:
    def test_null_quantity_is_not_quantified(self):
        result = _classify_ingredient(_base_ingredient(), (), {})
        assert result.readiness == NOT_QUANTIFIED
        assert result.self_report_matches_real_behavior is True

    def test_culinary_unit_is_unsupported_regardless_of_catalog(self):
        ing = _base_ingredient(quantity=2, unit="PL", scaling_unit_readiness="CULINARY_MEASURE_UNSUPPORTED")
        result = _classify_ingredient(ing, ("p1",), {"p1": _FakeNormalizedProduct(_FakePackageSize(500, "g"))})
        assert result.readiness == QUANTITY_UNIT_UNSUPPORTED
        assert result.self_report_matches_real_behavior is True

    def test_convertible_quantity_with_no_structured_candidate_package(self):
        ing = _base_ingredient(quantity=300, unit="g", scaling_unit_readiness="MASS_VOLUME_READY")
        normalized_index = {"p1": _FakeNormalizedProduct(_FakePackageSize(None, None))}
        result = _classify_ingredient(ing, ("p1",), normalized_index)
        assert result.readiness == QUANTITY_READY_NO_PACKAGE_DATA
        assert result.sample_package_counts == {}

    def test_convertible_quantity_with_structured_candidate_package_is_scaling_ready(self):
        ing = _base_ingredient(quantity=300, unit="g", scaling_unit_readiness="MASS_VOLUME_READY")
        normalized_index = {"p1": _FakeNormalizedProduct(_FakePackageSize(500, "g"))}
        result = _classify_ingredient(ing, ("p1",), normalized_index)
        assert result.readiness == SCALING_READY_TODAY
        assert result.sample_package_counts == {"p1": 1}

    def test_unit_class_mismatch_between_approved_quantity_and_candidate_package_is_not_scaling_ready(self):
        # Approved quantity is a mass (g); the only candidate's package size
        # is a volume (ml) - package_count_for must refuse to mix classes.
        ing = _base_ingredient(quantity=300, unit="g", scaling_unit_readiness="MASS_VOLUME_READY")
        normalized_index = {"p1": _FakeNormalizedProduct(_FakePackageSize(500, "ml"))}
        result = _classify_ingredient(ing, ("p1",), normalized_index)
        assert result.readiness == QUANTITY_READY_NO_PACKAGE_DATA

    def test_self_report_mismatch_is_detected(self):
        # A row that claims MASS_VOLUME_READY but is actually an unsupported
        # culinary unit must be flagged, not trusted.
        ing = _base_ingredient(quantity=2, unit="PL", scaling_unit_readiness="MASS_VOLUME_READY")
        result = _classify_ingredient(ing, (), {})
        assert result.readiness == QUANTITY_UNIT_UNSUPPORTED
        assert result.self_report_matches_real_behavior is False

    def test_only_first_three_candidates_are_sampled(self):
        ing = _base_ingredient(quantity=300, unit="g", scaling_unit_readiness="MASS_VOLUME_READY")
        normalized_index = {
            f"p{i}": _FakeNormalizedProduct(_FakePackageSize(500, "g")) for i in range(1, 6)
        }
        result = _classify_ingredient(ing, tuple(normalized_index.keys()), normalized_index)
        assert len(result.sample_package_counts) == 3


@pytest.fixture(scope="module")
def dataset() -> dict:
    return json.loads(AUTHORING_PATH.read_text(encoding="utf-8"))


class TestAuditAgainstRealDataset:
    def test_audits_every_approved_row_exactly_once(self, dataset):
        ingredient_results, _ = audit_approved_rows(dataset)
        expected = [
            (dish["dish_id"], ing["ingredient_concept_id"])
            for dish in dataset["pilot_dishes"]
            for ing in dish["ingredients"]
            if ing["author_status"] == "APPROVED"
        ]
        actual = [(r.dish_id, r.ingredient_concept_id) for r in ingredient_results]
        assert sorted(actual) == sorted(expected)
        assert len(actual) == len(set(actual)), "duplicate ingredient audited"

    def test_dish_results_cover_every_pilot_dish(self, dataset):
        _, dish_results = audit_approved_rows(dataset)
        assert {d.dish_id for d in dish_results} == {d["dish_id"] for d in dataset["pilot_dishes"]}

    def test_every_ingredient_readiness_is_a_known_value(self, dataset):
        ingredient_results, _ = audit_approved_rows(dataset)
        allowed = {NOT_QUANTIFIED, QUANTITY_UNIT_UNSUPPORTED, QUANTITY_READY_NO_PACKAGE_DATA, SCALING_READY_TODAY}
        for r in ingredient_results:
            assert r.readiness in allowed

    def test_dish_blocked_reason_consistent_with_required_coverage(self, dataset):
        _, dish_results = audit_approved_rows(dataset)
        for dish in dish_results:
            if dish.required_ingredients_approved < dish.required_ingredient_count:
                assert dish.activation_blocked_reason is not None

    def test_build_report_is_never_a_production_authorization(self, dataset):
        report = build_report(dataset)
        assert report["production_eligible_recommendation"] is False
        assert report["self_report_mismatches"] == [
            ing for ing in report["ingredients"] if not ing["self_report_matches_real_behavior"]
        ]


class TestProductionIsolation:
    """Mirrors tests/test_recipe_quantity_authoring_v2_30b1.py's isolation
    class - the audit/report introduced in this sprint must stay just as
    unreachable from production as the underlying draft data."""

    def test_no_production_module_references_the_audit_or_report(self):
        app_dir = ROOT / "app"
        needle_variants = (
            "recipe_quantity_approval_readiness_audit_v2_30b2",
            "recipe_quantity_approval_readiness_v2_30b2",
        )
        hits = []
        for path in app_dir.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for needle in needle_variants:
                if needle in text:
                    hits.append((path.name, needle))
        assert not hits, f"production code references the V2.30b.2 audit/report: {hits}"

    def test_report_path_lives_under_editorial_not_app_data(self):
        assert "editorial" in REPORT_PATH.parts
        assert REPORT_PATH.suffix == ".json"

    def test_unapproved_pilot_rows_still_have_null_quantity_and_package_count(self, dataset):
        # V2.30c (Grounded Recipe Scaling Pilot Activation) deliberately
        # populates quantity/package_count for APPROVED rows - narrowed
        # from "every ingredient" accordingly; see
        # tests/test_recipe_quantity_authoring_v2_30b1.py's identically
        # narrowed sibling test and tests/test_grounded_recipe_scaling_
        # v2_30c.py for the positive activation proof.
        import app.main as m

        approved_concepts_by_dish = {
            dish["dish_id"]: {
                ing["ingredient_concept_id"] for ing in dish["ingredients"] if ing["author_status"] == "APPROVED"
            }
            for dish in dataset["pilot_dishes"]
        }
        for dish_id in ("pad_thai", "tom_kha", "sushi", "tom_yum", "kimchi_ramen"):
            plan = m._build_recipe_shopping_plan(
                m.recipe_graph_index, dish_id, m.products, m.product_taxonomy_index, m.normalized_product_index,
                servings=6,
            )
            approved_concepts = approved_concepts_by_dish[dish_id]
            for ing in plan.ingredients:
                if ing.ingredient_concept_id in approved_concepts:
                    continue
                assert ing.quantity is None, f"{dish_id}/{ing.ingredient_concept_id}: quantity unexpectedly populated"
                assert ing.package_count is None, f"{dish_id}/{ing.ingredient_concept_id}: package_count unexpectedly populated"
