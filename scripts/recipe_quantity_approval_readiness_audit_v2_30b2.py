"""
scripts/recipe_quantity_approval_readiness_audit_v2_30b2.py  -  V2.30b.2
Approved-data validation sprint.

V2.30b.1/b.1a built a draft editorial authoring pack and got a human
reviewer to APPROVE a subset of its rows (5/5 dishes dish-level APPROVED,
17/30 ingredient rows APPROVED - see docs/recipe-quantity-authoring-guide-
v2.30b1.md). None of that touched production: app/ has never read the
authoring file, and production_eligible stays false on disk.

This script answers the next, still read-only question: "if a future
sprint (V2.30c) were to wire the APPROVED rows into production today,
what would actually happen?" It runs the REAL production functions
(app.ingredients.convert_to_base_unit, app.recipe_shopping.
package_count_for) against the APPROVED quantities and the REAL current
catalog's candidate products for each ingredient concept - not a
simulation of the logic, the actual logic - and reports, per row and per
dish, whether the approved data would support real package-count math
today, or only the scaled quantity, or neither.

It also cross-checks each row's own self-reported `scaling_unit_readiness`
field against what the real conversion function actually does, so a
drifted or wrong self-assessment shows up as a mismatch rather than being
trusted blindly.

Nothing here writes back to the authoring file, flips production_eligible,
or changes app/. The output report is a new, separate file - a production
sprint reads it as a recommendation, never as authorization.

Usage:
    python scripts/recipe_quantity_approval_readiness_audit_v2_30b2.py
    python scripts/recipe_quantity_approval_readiness_audit_v2_30b2.py --no-write
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

AUTHORING_PATH = ROOT / "data" / "editorial" / "recipe_quantity_authoring_v2_30b1.json"
REPORT_PATH = ROOT / "data" / "editorial" / "recipe_quantity_approval_readiness_v2_30b2.json"

NOT_QUANTIFIED = "NOT_QUANTIFIED"
QUANTITY_UNIT_UNSUPPORTED = "QUANTITY_UNIT_UNSUPPORTED"
QUANTITY_READY_NO_PACKAGE_DATA = "QUANTITY_READY_NO_PACKAGE_DATA"
SCALING_READY_TODAY = "SCALING_READY_TODAY"

_SELF_REPORT_EXPECTATIONS = {
    NOT_QUANTIFIED: {"UNGROUNDED"},
    QUANTITY_UNIT_UNSUPPORTED: {"CULINARY_MEASURE_UNSUPPORTED", "COUNT_UNIT_UNSUPPORTED"},
    QUANTITY_READY_NO_PACKAGE_DATA: {"MASS_VOLUME_READY"},
    SCALING_READY_TODAY: {"MASS_VOLUME_READY"},
}

BLOCKED_NO_BASE_SERVINGS = "NO_BASE_SERVINGS"
BLOCKED_INCOMPLETE_REQUIRED_APPROVAL = "INCOMPLETE_REQUIRED_INGREDIENT_APPROVAL"
BLOCKED_NO_PACKAGE_MATH_READY = "NO_INGREDIENT_HAS_PACKAGE_MATH_READY"


@dataclass(frozen=True)
class IngredientReadiness:
    dish_id: str
    ingredient_concept_id: str
    requirement: str
    quantity: float | None
    unit: str | None
    readiness: str
    self_reported_scaling_unit_readiness: str
    self_report_matches_real_behavior: bool
    sample_package_counts: dict[str, int]


@dataclass(frozen=True)
class DishReadiness:
    dish_id: str
    approval_status: str
    base_servings: int | None
    required_ingredient_count: int
    required_ingredients_approved: int
    required_ingredient_approval_coverage: float
    scaling_ready_today_count: int
    activation_blocked_reason: str | None


def _classify_ingredient(
    ing: dict,
    candidate_product_ids: tuple[str, ...],
    normalized_product_index: dict,
) -> IngredientReadiness:
    from app.ingredients import ParsedQuantity, convert_to_base_unit
    from app.recipe_shopping import package_count_for

    quantity = ing["quantity"]
    unit = ing["unit"]
    self_reported = ing["scaling_unit_readiness"]
    sample_counts: dict[str, int] = {}

    if quantity is None:
        readiness = NOT_QUANTIFIED
    else:
        converted = convert_to_base_unit(float(quantity), unit)
        if converted is None:
            readiness = QUANTITY_UNIT_UNSUPPORTED
        else:
            parsed = ParsedQuantity(
                quantity=float(quantity), unit=unit, is_numeric=True,
                raw_text=ing.get("source_quantity_text") or "",
            )
            for product_id in candidate_product_ids[:3]:
                normalized = normalized_product_index.get(product_id)
                if normalized is None:
                    continue
                count = package_count_for(parsed, normalized)
                if count is not None:
                    sample_counts[product_id] = count
            readiness = SCALING_READY_TODAY if sample_counts else QUANTITY_READY_NO_PACKAGE_DATA

    return IngredientReadiness(
        dish_id=ing["_dish_id"],
        ingredient_concept_id=ing["ingredient_concept_id"],
        requirement=ing["requirement"],
        quantity=quantity,
        unit=unit,
        readiness=readiness,
        self_reported_scaling_unit_readiness=self_reported,
        self_report_matches_real_behavior=self_reported in _SELF_REPORT_EXPECTATIONS[readiness],
        sample_package_counts=sample_counts,
    )


def audit_approved_rows(dataset: dict) -> tuple[list[IngredientReadiness], list[DishReadiness]]:
    """Runs the real app.ingredients/app.recipe_shopping functions against
    every APPROVED ingredient row in `dataset`. Import is deferred so this
    module stays importable (e.g. by tests) without loading the full
    catalog unless an audit actually runs."""
    import app.main as m
    from app.recipe_shopping import build_recipe_shopping_plan

    ingredient_results: list[IngredientReadiness] = []
    dish_results: list[DishReadiness] = []

    for dish in dataset["pilot_dishes"]:
        dish_id = dish["dish_id"]
        plan = build_recipe_shopping_plan(
            m.recipe_graph_index, dish_id, m.products, m.product_taxonomy_index, m.normalized_product_index,
        )
        candidates_by_concept = (
            {ing.ingredient_concept_id: ing.candidate_product_ids for ing in plan.ingredients} if plan else {}
        )

        approved_ings = [ing for ing in dish["ingredients"] if ing["author_status"] == "APPROVED"]
        dish_ingredient_results: list[IngredientReadiness] = []
        for ing in approved_ings:
            tagged = {**ing, "_dish_id": dish_id}
            result = _classify_ingredient(
                tagged, candidates_by_concept.get(ing["ingredient_concept_id"], ()), m.normalized_product_index,
            )
            dish_ingredient_results.append(result)
        ingredient_results.extend(dish_ingredient_results)

        required_approved = [r for r in dish_ingredient_results if r.requirement == "REQUIRED"]
        required_total = sum(1 for ing in dish["ingredients"] if ing["requirement"] == "REQUIRED")
        scaling_ready = sum(1 for r in dish_ingredient_results if r.readiness == SCALING_READY_TODAY)

        if dish["base_servings"] is None:
            blocked_reason = BLOCKED_NO_BASE_SERVINGS
        elif required_total == 0 or len(required_approved) < required_total:
            blocked_reason = BLOCKED_INCOMPLETE_REQUIRED_APPROVAL
        elif scaling_ready == 0:
            blocked_reason = BLOCKED_NO_PACKAGE_MATH_READY
        else:
            blocked_reason = None

        dish_results.append(
            DishReadiness(
                dish_id=dish_id,
                approval_status=dish["approval_status"],
                base_servings=dish["base_servings"],
                required_ingredient_count=required_total,
                required_ingredients_approved=len(required_approved),
                required_ingredient_approval_coverage=(len(required_approved) / required_total) if required_total else 0.0,
                scaling_ready_today_count=scaling_ready,
                activation_blocked_reason=blocked_reason,
            )
        )

    return ingredient_results, dish_results


def build_report(dataset: dict) -> dict:
    ingredient_results, dish_results = audit_approved_rows(dataset)
    mismatches = [r for r in ingredient_results if not r.self_report_matches_real_behavior]
    return {
        "schema_version": 1,
        "created_for_sprint": "V2.30b.2",
        "audited_source": "data/editorial/recipe_quantity_authoring_v2_30b1.json",
        "note": (
            "Advisory only - this report never changes production_eligible or app/. "
            "A future sprint (V2.30c) reads this as a recommendation, not an authorization."
        ),
        "production_eligible_recommendation": False,
        "dishes": [asdict(d) for d in dish_results],
        "ingredients": [asdict(r) for r in ingredient_results],
        "self_report_mismatches": [asdict(r) for r in mismatches],
    }


def _print_summary(report: dict) -> None:
    print("=== V2.30b.2 Approved-Data Validation (read-only) ===")
    print(f"production_eligible_recommendation: {report['production_eligible_recommendation']}")
    print()
    print("=== Dish-level activation readiness ===")
    for dish in report["dishes"]:
        print(
            f" - {dish['dish_id']}: approval_status={dish['approval_status']} "
            f"base_servings={dish['base_servings']} "
            f"required_approved={dish['required_ingredients_approved']}/{dish['required_ingredient_count']} "
            f"scaling_ready_today={dish['scaling_ready_today_count']} "
            f"blocked_reason={dish['activation_blocked_reason']}"
        )
    print()
    print("=== Approved-ingredient readiness breakdown ===")
    counts: dict[str, int] = {}
    for ing in report["ingredients"]:
        counts[ing["readiness"]] = counts.get(ing["readiness"], 0) + 1
    for readiness, count in sorted(counts.items()):
        print(f" - {readiness}: {count}")
    print()
    mismatches = report["self_report_mismatches"]
    print(f"=== Self-report mismatches: {len(mismatches)} ===")
    for m_row in mismatches:
        print(
            f" - {m_row['dish_id']}/{m_row['ingredient_concept_id']}: "
            f"self_reported={m_row['self_reported_scaling_unit_readiness']!r} "
            f"actual={m_row['readiness']!r}"
        )
    if not mismatches:
        print(" (none - every approved row's self-reported readiness matches real app behavior)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true", help="print the summary only, do not write the report file")
    args = parser.parse_args()

    dataset = json.loads(AUTHORING_PATH.read_text(encoding="utf-8"))
    report = build_report(dataset)
    _print_summary(report)

    if not args.no_write:
        REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print()
        print(f"Report written to {REPORT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
