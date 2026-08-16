"""
app/recipe_shopping.py  -  V2.8 RecipeShoppingPlan

Builds the structured shopping plan for one dish (Section 21-29): per
ingredient AVAILABLE/ALREADY_SATISFIED/NOT_AVAILABLE/OPTIONAL/UNKNOWN_MAPPING
status, coverage metrics kept separate (Section 22/23), basket satisfaction
(Section 56/57), and serving/package math that only ever activates on real
structured quantities (Section 24/25/29 - see docs/recipe-knowledge-audit.md:
no current Foodland recipe carries one, so this machinery is implemented and
tested but dormant against live data today).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil

from app.feed import Product
from app.ingredients import ParsedQuantity, convert_to_base_unit, scale_quantity
from app.product_normalizer import NormalizedProduct
from app.recipe_graph import (
    CATALOG_AVAILABLE,
    RecipeGraphIndex,
    resolve_ingredient_products,
)
from app.taxonomy import ProductTaxonomy

STATUS_AVAILABLE = "AVAILABLE"
STATUS_ALREADY_SATISFIED = "ALREADY_SATISFIED"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
STATUS_OPTIONAL = "OPTIONAL"
STATUS_UNKNOWN_MAPPING = "UNKNOWN_MAPPING"


@dataclass(frozen=True)
class PlanIngredient:
    ingredient_concept_id: str
    raw_text: str
    role: str
    requirement: str
    status: str
    selected_product_id: str | None = None
    candidate_product_ids: tuple[str, ...] = ()
    confidence: str = "UNKNOWN"
    quantity: ParsedQuantity | None = None
    package_count: int | None = None


@dataclass(frozen=True)
class RecipeShoppingPlan:
    dish_id: str
    dish_title: str
    recipe_id: str | None
    requested_servings: int | None
    ingredients: tuple[PlanIngredient, ...]
    not_available_ingredients: tuple[str, ...]
    ingredient_mapping_coverage: float
    required_ingredient_mapping_coverage: float
    catalog_product_coverage: float
    recipe_shopping_coverage: float
    missing_required_count: int
    optional_count: int


def build_recipe_shopping_plan(
    graph: RecipeGraphIndex,
    dish_id: str,
    products: list[Product],
    taxonomy_index: dict[str, ProductTaxonomy],
    normalized_index: dict[str, NormalizedProduct],
    *,
    servings: int | None = None,
    basket_product_ids: frozenset[str] = frozenset(),
) -> RecipeShoppingPlan | None:
    """Section 21 - returns None only when the dish itself isn't in the
    graph (caller should fall back to legacy recipe handling, Section 123)."""
    dish = graph.dishes_by_id.get(dish_id)
    recipe_ingredients = graph.recipe_ingredients_by_dish.get(dish_id)
    if dish is None or not recipe_ingredients:
        return None

    plan_ingredients: list[PlanIngredient] = []
    for recipe_ingredient in recipe_ingredients:
        resolution = resolve_ingredient_products(
            graph, recipe_ingredient.ingredient_concept_id, products, taxonomy_index, normalized_index,
        )
        satisfied_by_basket = bool(basket_product_ids & set(resolution.matching_product_ids))

        if satisfied_by_basket:
            status = STATUS_ALREADY_SATISFIED
        elif resolution.catalog_status == CATALOG_AVAILABLE:
            status = STATUS_AVAILABLE
        elif resolution.matching_product_ids:
            status = STATUS_UNKNOWN_MAPPING
        else:
            status = STATUS_NOT_AVAILABLE

        # Section 21/25/28 - no current Foodland recipe carries a structured
        # quantity (docs/recipe-knowledge-audit.md), so quantity/package_count
        # stay None for every real dish. scale_plan_quantities() and
        # package_count_for() implement the arithmetic and are exercised
        # directly against synthetic fixtures in tests/test_recipe_shopping.py.
        parsed_quantity = None
        package_count = None

        plan_ingredients.append(
            PlanIngredient(
                ingredient_concept_id=recipe_ingredient.ingredient_concept_id,
                raw_text=recipe_ingredient.raw_text,
                role=recipe_ingredient.role,
                requirement=recipe_ingredient.requirement,
                status=status,
                selected_product_id=resolution.matching_product_ids[0] if resolution.matching_product_ids else None,
                candidate_product_ids=resolution.matching_product_ids,
                confidence=resolution.confidence,
                quantity=parsed_quantity,
                package_count=package_count,
            )
        )

    not_available_text = graph.not_available_by_dish.get(dish_id, ())

    required = [ing for ing in plan_ingredients if ing.requirement == "REQUIRED"]
    optional = [ing for ing in plan_ingredients if ing.requirement != "REQUIRED"]
    mapped = [ing for ing in plan_ingredients if ing.status != STATUS_UNKNOWN_MAPPING]
    required_mapped = [ing for ing in required if ing.status != STATUS_UNKNOWN_MAPPING]
    in_catalog = [ing for ing in plan_ingredients if ing.status in {STATUS_AVAILABLE, STATUS_ALREADY_SATISFIED}]
    required_in_catalog = [ing for ing in required if ing.status in {STATUS_AVAILABLE, STATUS_ALREADY_SATISFIED}]
    missing_required = [ing for ing in required if ing.status == STATUS_NOT_AVAILABLE]

    total = len(plan_ingredients) or 1
    total_required = len(required) or 1

    recipe_id = dish.recipe_ids[0] if dish.recipe_ids else None

    return RecipeShoppingPlan(
        dish_id=dish_id,
        dish_title=dish.title,
        recipe_id=recipe_id,
        requested_servings=servings,
        ingredients=tuple(plan_ingredients),
        not_available_ingredients=tuple(not_available_text),
        ingredient_mapping_coverage=len(mapped) / total,
        required_ingredient_mapping_coverage=len(required_mapped) / total_required,
        catalog_product_coverage=len(in_catalog) / total,
        recipe_shopping_coverage=len(required_in_catalog) / total_required,
        missing_required_count=len(missing_required),
        optional_count=len(optional),
    )


def scale_plan_quantities(plan: RecipeShoppingPlan, target_servings: int) -> RecipeShoppingPlan:
    """Section 24 - only touches ingredients with a real structured numeric
    quantity (Section 25); everything else passes through unchanged. Given
    current recipe data (see docs/recipe-knowledge-audit.md), this is a
    no-op for every real dish today, but is tested against synthetic
    quantities to prove the arithmetic (tests/test_recipe_shopping.py)."""
    if not plan.requested_servings:
        return plan
    scaled: list[PlanIngredient] = []
    for ingredient in plan.ingredients:
        if ingredient.quantity and ingredient.quantity.is_numeric:
            scaled_value = scale_quantity(ingredient.quantity.quantity, plan.requested_servings, target_servings)
            new_quantity = ParsedQuantity(
                quantity=scaled_value, unit=ingredient.quantity.unit, is_numeric=True, raw_text=ingredient.quantity.raw_text,
            )
            scaled.append(_replace_quantity(ingredient, new_quantity))
        else:
            scaled.append(ingredient)
    return RecipeShoppingPlan(
        dish_id=plan.dish_id,
        dish_title=plan.dish_title,
        recipe_id=plan.recipe_id,
        requested_servings=target_servings,
        ingredients=tuple(scaled),
        not_available_ingredients=plan.not_available_ingredients,
        ingredient_mapping_coverage=plan.ingredient_mapping_coverage,
        required_ingredient_mapping_coverage=plan.required_ingredient_mapping_coverage,
        catalog_product_coverage=plan.catalog_product_coverage,
        recipe_shopping_coverage=plan.recipe_shopping_coverage,
        missing_required_count=plan.missing_required_count,
        optional_count=plan.optional_count,
    )


def _replace_quantity(ingredient: PlanIngredient, quantity: ParsedQuantity) -> PlanIngredient:
    return PlanIngredient(
        ingredient_concept_id=ingredient.ingredient_concept_id,
        raw_text=ingredient.raw_text,
        role=ingredient.role,
        requirement=ingredient.requirement,
        status=ingredient.status,
        selected_product_id=ingredient.selected_product_id,
        candidate_product_ids=ingredient.candidate_product_ids,
        confidence=ingredient.confidence,
        quantity=quantity,
        package_count=ingredient.package_count,
    )


def package_count_for(required: ParsedQuantity, package: NormalizedProduct) -> int | None:
    """Section 29 - ceil(required / package size), only when both convert
    to the same base unit (ml or g) and the package size is structured.
    Returns None (never a fabricated count) otherwise."""
    if not required.is_numeric or required.unit is None:
        return None
    package_size = getattr(package, "package_size", None)
    if package_size is None or not package_size.is_structured or package_size.value is None or not package_size.unit:
        return None
    required_base = convert_to_base_unit(required.quantity, required.unit)
    package_base = convert_to_base_unit(package_size.value, package_size.unit)
    if required_base is None or package_base is None:
        return None
    required_value, required_unit_class = required_base
    package_value, package_unit_class = package_base
    if required_unit_class != package_unit_class or package_value <= 0:
        return None
    return ceil(required_value / package_value)


_SECTION_BY_STATUS = {
    STATUS_AVAILABLE: "RECIPE_REQUIRED",
    STATUS_UNKNOWN_MAPPING: "RECIPE_REQUIRED",
    STATUS_ALREADY_SATISFIED: "RECIPE_ALREADY_HAVE",
    STATUS_NOT_AVAILABLE: "RECIPE_NOT_AVAILABLE",
    STATUS_OPTIONAL: "RECIPE_OPTIONAL",
}


def summarize_plan(plan: RecipeShoppingPlan) -> dict:
    """Section 82/94/96/136 - the one JSON-safe shape app.main's /chat
    response exposes for a RecipeShoppingPlan. Grouped by section
    (RECIPE_REQUIRED/RECIPE_OPTIONAL/RECIPE_ALREADY_HAVE/RECIPE_NOT_AVAILABLE)
    so the client can render "shop the recipe" without re-deriving status
    logic (Section 82). Structured facts only - no customer-facing prose
    (Section 77 - that's app.answer_composer's job)."""
    sections: dict[str, list[dict]] = {
        "RECIPE_REQUIRED": [],
        "RECIPE_OPTIONAL": [],
        "RECIPE_ALREADY_HAVE": [],
        "RECIPE_NOT_AVAILABLE": [],
    }
    for ingredient in plan.ingredients:
        section = _SECTION_BY_STATUS.get(ingredient.status, "RECIPE_REQUIRED")
        sections[section].append({
            "ingredient_concept_id": ingredient.ingredient_concept_id,
            "raw_text": ingredient.raw_text,
            "role": ingredient.role,
            "requirement": ingredient.requirement,
            "status": ingredient.status,
            "selected_product_id": ingredient.selected_product_id,
            "candidate_product_ids": list(ingredient.candidate_product_ids),
            "confidence": ingredient.confidence,
        })
    for raw_text in plan.not_available_ingredients:
        sections["RECIPE_NOT_AVAILABLE"].append({
            "ingredient_concept_id": None,
            "raw_text": raw_text,
            "role": None,
            "requirement": "REQUIRED",
            "status": STATUS_NOT_AVAILABLE,
            "selected_product_id": None,
            "candidate_product_ids": [],
            "confidence": "UNKNOWN",
        })
    return {
        "dish_id": plan.dish_id,
        "dish_title": plan.dish_title,
        "recipe_id": plan.recipe_id,
        "requested_servings": plan.requested_servings,
        "sections": sections,
        "coverage": {
            "ingredient_mapping_coverage": round(plan.ingredient_mapping_coverage, 3),
            "required_ingredient_mapping_coverage": round(plan.required_ingredient_mapping_coverage, 3),
            "catalog_product_coverage": round(plan.catalog_product_coverage, 3),
            "recipe_shopping_coverage": round(plan.recipe_shopping_coverage, 3),
        },
        "missing_required_count": plan.missing_required_count,
        "optional_count": plan.optional_count,
    }


def basket_concept_ids(
    graph: RecipeGraphIndex,
    products: list[Product],
    taxonomy_index: dict[str, ProductTaxonomy],
    normalized_index: dict[str, NormalizedProduct],
    basket_product_ids: frozenset[str],
) -> frozenset[str]:
    """Section 48/53 reverse mapping: basket SKUs -> ingredient concepts,
    used by app.cross_sell to know what's already satisfied (Section 56).
    Cheap membership scan over the (small) concept table - no per-request
    catalog scan (Section 87)."""
    satisfied: set[str] = set()
    for concept_id in graph.ingredient_concepts:
        resolution = resolve_ingredient_products(graph, concept_id, products, taxonomy_index, normalized_index)
        if basket_product_ids & set(resolution.matching_product_ids):
            satisfied.add(concept_id)
    return frozenset(satisfied)
