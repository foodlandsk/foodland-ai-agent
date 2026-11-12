"""
app/recipe_quantities.py  -  V2.30c Grounded Recipe Scaling Pilot Activation

Fail-closed, read-only loader for the human-approved subset of
data/editorial/recipe_quantity_authoring_v2_30b1.json (authored in
V2.30b.1, source-grounded in V2.30b.1a, readiness-audited in V2.30b.2).
Exposes exactly two lookups - get_base_servings() and
get_approved_ingredient_quantity() - that app.recipe_shopping uses to
populate PlanIngredient.quantity/package_count for the pilot dishes.
Every other dish, and every non-APPROVED row within a pilot dish, is
untouched: both lookups return None for anything outside the approved
subset, by construction.

Production eligibility is enforced per-dish/per-row here, not via the
dataset's top-level `production_eligible` flag (left False - see
docs/recipe-quantity-authoring-guide-v2.30b1.md). That flag describes
whether EVERY row in the file has finished authoring (13/30 rows are
still NEEDS_AUTHORING), not whether the already-APPROVED subset is safe
to read; a row only ever reaches this module's output when:

    dish.approval_status == "APPROVED"
    AND dish.base_servings is a positive int
    AND ingredient.author_status == "APPROVED"
    AND ingredient.quantity / unit / source_reference are all present

- the exact bar tests/test_recipe_quantity_authoring_v2_30b1.py already
enforces structurally on the dataset itself.

Fails closed: any load/parse/schema problem (missing file, malformed
JSON, a duplicate ingredient_concept_id within one dish, an APPROVED row
missing a required field, a non-positive base_servings) disables
quantity enrichment for the WHOLE file - both lookups just return None,
RecipeShoppingPlan still builds normally with quantity=None, and the
rest of the AI service is unaffected. This module never writes back to
the authoring file.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

AUTHORING_DATASET_PATH = Path(__file__).resolve().parent.parent / "data" / "editorial" / "recipe_quantity_authoring_v2_30b1.json"

_PRODUCTION_ELIGIBLE_AUTHOR_STATUSES = frozenset({"APPROVED"})


@dataclass(frozen=True)
class ApprovedIngredientQuantity:
    quantity: float
    unit: str
    source_reference: str
    source_type: str | None


@dataclass(frozen=True)
class _ApprovedRecipeQuantities:
    base_servings_by_dish: dict[str, int]
    ingredient_quantities: dict[tuple[str, str], ApprovedIngredientQuantity]


_EMPTY = _ApprovedRecipeQuantities(base_servings_by_dish={}, ingredient_quantities={})


def _validate_and_build(raw: dict) -> _ApprovedRecipeQuantities:
    """Pure schema validation + filtering - raises on anything structurally
    unsafe (duplicate concept ids, bad types) so the caller's try/except
    can fail closed; silently SKIPS (does not raise for) an individual
    APPROVED row that is missing a required field, since that is an
    editorial-data gap, not a reason to disable the whole file."""
    base_servings_by_dish: dict[str, int] = {}
    ingredient_quantities: dict[tuple[str, str], ApprovedIngredientQuantity] = {}

    for dish in raw["pilot_dishes"]:
        dish_id = dish["dish_id"]
        dish_approved = dish.get("approval_status") == "APPROVED"
        base_servings = dish.get("base_servings")
        if dish_approved and isinstance(base_servings, int) and not isinstance(base_servings, bool) and base_servings > 0:
            base_servings_by_dish[dish_id] = base_servings

        seen_concept_ids: set[str] = set()
        for ing in dish["ingredients"]:
            concept_id = ing["ingredient_concept_id"]
            if concept_id in seen_concept_ids:
                raise ValueError(f"duplicate ingredient_concept_id {concept_id!r} in dish {dish_id!r}")
            seen_concept_ids.add(concept_id)

            if not dish_approved or ing.get("author_status") not in _PRODUCTION_ELIGIBLE_AUTHOR_STATUSES:
                continue

            quantity = ing.get("quantity")
            unit = ing.get("unit")
            source_reference = ing.get("source_reference")
            if quantity is None or unit is None or not source_reference:
                continue
            if isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or quantity <= 0:
                continue

            ingredient_quantities[(dish_id, concept_id)] = ApprovedIngredientQuantity(
                quantity=float(quantity),
                unit=str(unit),
                source_reference=str(source_reference),
                source_type=ing.get("source_type"),
            )

    return _ApprovedRecipeQuantities(
        base_servings_by_dish=base_servings_by_dish,
        ingredient_quantities=ingredient_quantities,
    )


@lru_cache(maxsize=1)
def _load() -> _ApprovedRecipeQuantities:
    try:
        raw = json.loads(AUTHORING_DATASET_PATH.read_text(encoding="utf-8"))
        return _validate_and_build(raw)
    except Exception:
        logger.exception(
            "app.recipe_quantities: failed to load/validate %s - recipe quantity "
            "enrichment disabled for this process (recipe shopping itself is unaffected)",
            AUTHORING_DATASET_PATH,
        )
        return _EMPTY


def get_base_servings(dish_id: str) -> int | None:
    """Section 15/6 - a positive base_servings only for a dish that is
    dish-level APPROVED with a sourced base_servings; None for every other
    dish (not dish-level approved, base_servings still null, or not a
    pilot dish at all). Callers must treat None as "scaling disabled"."""
    return _load().base_servings_by_dish.get(dish_id)


def get_approved_ingredient_quantity(dish_id: str, ingredient_concept_id: str) -> ApprovedIngredientQuantity | None:
    """Section 16/10 - a value only when the owning dish is dish-level
    APPROVED AND this exact ingredient row is author_status==APPROVED with
    quantity/unit/source_reference all present; None for every other row
    (NEEDS_AUTHORING/AUTHORED/REVIEWED/REJECTED, any non-pilot dish, or a
    pilot dish that isn't dish-level APPROVED)."""
    return _load().ingredient_quantities.get((dish_id, ingredient_concept_id))
