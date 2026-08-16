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
from app.ingredients import ParsedQuantity, convert_to_base_unit, extract_requested_servings_lenient, scale_quantity
from app.product_normalizer import NormalizedProduct
from app.recipe_graph import (
    CATALOG_AVAILABLE,
    RecipeGraphIndex,
    resolve_ingredient_products,
)
from app.session_state import (
    TurnSignals,
    get_active_recipe,
    get_last_recipe_ingredient_concept,
    get_selected_ingredient_products,
    mark_ingredient_selected,
    rank_by_price_direction,
    set_last_recipe_ingredient_concept,
    set_recipe_servings,
    track_presentation,
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


# ---------------------------------------------------------------------------
# V2.9 - recipe conversation continuity (Section 16/17/18/53). Owns WHICH
# recipe is active and how a follow-up question about it resolves;
# app.recipe_graph/app.recipe_shopping's own ingredient/plan semantics
# (Section 39) are reused as-is, never duplicated.
# ---------------------------------------------------------------------------

_STOPWORDS_FOR_RECIPE_MATCH = frozenset({
    "ake", "aky", "aka", "aku", "a", "co", "ten", "ta", "to", "mate", "mas",
    "este", "aj", "na", "do", "s", "so", "z", "zo", "je", "su",
})

# Words that name a whole grocery CATEGORY rather than a specific
# ingredient - too generic to safely identify one of the active recipe's
# ~5 ingredients on their own. Without this, "kikkoman sojova omacka 1000
# ml" (a specific, unrelated branded product search) matched Pad Thai's
# fish_sauce purely because "omacka" ("sauce") is shared with "rybacia
# omacka" - a real regression caught by the V2.8 regression suite
# (tests/test_recipe_shopping.py::test_context_switch_away_from_recipe_does_not_leak_plan).
# Stripped from BOTH sides before scoring, so a message still matches via
# any more specific word it shares with the concept (e.g. "rybacia").
_GENERIC_CATEGORY_WORDS = frozenset({
    "omacka", "omacky", "omacku", "omackou", "pasta", "pasty", "pastu",
    "korenie", "korenia", "olej", "oleja", "muka", "muky",
})


def _strip_generic_category_words(tokens: set[str]) -> set[str]:
    return {t for t in tokens if t not in _GENERIC_CATEGORY_WORDS}


_MIN_STEM_LENGTH = 4  # shared-prefix length treated as "same word" across Slovak noun case endings


def _stem_overlap(message_tokens: set[str], concept_tokens: set[str]) -> int:
    """Slovak noun case endings vary ("rybacia omáčka" nominative vs "a
    rybaciu omáčku?" accusative) and app.search.raw_tokens does not stem -
    a shared-prefix check of >= _MIN_STEM_LENGTH chars is a cheap,
    deterministic stand-in for real morphological analysis, scoped to a
    small (~5-concept) candidate set so a coincidental short prefix match
    can only ever pick among THIS recipe's own ingredients (Section 47 -
    deterministic first, no LLM needed for this)."""
    count = 0
    for m_token in message_tokens:
        for c_token in concept_tokens:
            prefix_len = min(len(m_token), len(c_token), _MIN_STEM_LENGTH)
            if prefix_len >= _MIN_STEM_LENGTH and m_token[:prefix_len] == c_token[:prefix_len]:
                count += 1
                break
    return count


def _match_recipe_ingredient_by_tokens(message: str, graph: RecipeGraphIndex, recipe_concept_ids: set[str]) -> str | None:
    from app.search import raw_tokens
    message_tokens = _strip_generic_category_words(raw_tokens(message) - _STOPWORDS_FOR_RECIPE_MATCH)
    if not message_tokens:
        return None
    best_concept_id: str | None = None
    best_score = 0
    for concept_id in recipe_concept_ids:
        concept = graph.ingredient_concepts.get(concept_id)
        if concept is None:
            continue
        concept_tokens: set[str] = set()
        for alias in concept.aliases:
            concept_tokens |= raw_tokens(alias)
        concept_tokens |= raw_tokens(concept.display_name)
        concept_tokens = _strip_generic_category_words(concept_tokens)
        score = _stem_overlap(message_tokens, concept_tokens)
        if score > best_score:
            best_score = score
            best_concept_id = concept_id
    return best_concept_id if best_score > 0 else None


RECIPE_FOLLOWUP_INGREDIENT = "ingredient_candidates"
RECIPE_FOLLOWUP_SELECTED = "selected"
RECIPE_FOLLOWUP_CLARIFICATION = "clarification_needed"
RECIPE_FOLLOWUP_PLAN_UPDATE = "plan_update"


@dataclass(frozen=True)
class RecipeFollowupResult:
    kind: str
    dish_id: str
    plan: RecipeShoppingPlan | None = None
    concept_id: str | None = None
    candidate_product_ids: tuple[str, ...] = ()
    selected_product_id: str | None = None


def resolve_recipe_followup(
    message: str,
    memory: dict,
    graph: RecipeGraphIndex,
    products: list[Product],
    taxonomy_index: dict[str, ProductTaxonomy],
    normalized_index: dict[str, NormalizedProduct],
) -> RecipeFollowupResult | None:
    """Section 16/17/18/53 - resolves a follow-up turn against the ACTIVE
    recipe tracked in session state, without re-detecting the dish from
    scratch (Section 39 - V2.9 owns continuity, V2.8 owns recipe
    semantics). Returns None when the message does not read as a
    continuation of the active recipe at all - the caller then treats it
    as a hard switch (Section 27) and clears the active recipe."""
    active_recipe_id, servings = get_active_recipe(memory)
    if not active_recipe_id or active_recipe_id not in graph.dishes_by_id:
        return None

    signals = TurnSignals(message, memory)
    selected = frozenset(get_selected_ingredient_products(memory).values())

    requested_servings = extract_requested_servings_lenient(message)
    if requested_servings:
        set_recipe_servings(memory, requested_servings)
        servings = requested_servings

    # Ordinal reference against whatever ingredient's candidates were most
    # recently shown ("aké rezance?" -> "tie druhé") - Section 11/53.
    last_concept_id = get_last_recipe_ingredient_concept(memory)
    if signals.ordinal_product_id and last_concept_id:
        mark_ingredient_selected(memory, last_concept_id, signals.ordinal_product_id)
        plan = build_recipe_shopping_plan(
            graph, active_recipe_id, products, taxonomy_index, normalized_index,
            servings=servings, basket_product_ids=selected | {signals.ordinal_product_id},
        )
        return RecipeFollowupResult(
            kind=RECIPE_FOLLOWUP_SELECTED, dish_id=active_recipe_id, plan=plan,
            concept_id=last_concept_id, selected_product_id=signals.ordinal_product_id,
        )
    if signals.ordinal_needs_clarification:
        return RecipeFollowupResult(kind=RECIPE_FOLLOWUP_CLARIFICATION, dish_id=active_recipe_id)

    # Explicit ingredient mention ("a rybaciu omáčku?" / "aké rezance?") -
    # must belong to THIS recipe's own ingredient list, not just any known
    # concept (Section 18 - never introduces an unrelated role). Matched by
    # token overlap against the recipe's own (small, ~5) ingredient
    # concepts rather than the graph-wide alias index: a short follow-up
    # ("aké rezance?") often shares only one word with the full curated
    # display name ("ryžové rezance") or required-term ("rezance"), so a
    # full-phrase substring match against the whole alias index is too
    # strict here - restricting the candidate set to this recipe first
    # keeps that looser token match safe (Section 18/141 - can only ever
    # resolve to an ingredient this exact recipe actually calls for).
    recipe_concept_ids = {ing.ingredient_concept_id for ing in graph.recipe_ingredients_by_dish[active_recipe_id]}
    mentioned_concept_id = _match_recipe_ingredient_by_tokens(message, graph, recipe_concept_ids)
    if mentioned_concept_id and mentioned_concept_id in recipe_concept_ids:
        resolution = resolve_ingredient_products(graph, mentioned_concept_id, products, taxonomy_index, normalized_index)
        candidates = list(resolution.matching_product_ids)
        if signals.price_direction and candidates:
            products_by_id = {p.id: p for p in products}
            ranked = rank_by_price_direction([products_by_id[pid] for pid in candidates if pid in products_by_id], signals.price_direction)
            candidates = [p.id for p in ranked]
        set_last_recipe_ingredient_concept(memory, mentioned_concept_id)
        track_presentation(memory, candidates)
        return RecipeFollowupResult(
            kind=RECIPE_FOLLOWUP_INGREDIENT, dish_id=active_recipe_id,
            concept_id=mentioned_concept_id, candidate_product_ids=tuple(candidates),
        )

    # Price refinement on the ingredient just discussed, with no new
    # concept named ("niečo lacnejšie" right after "aké rezance?").
    if signals.price_direction and last_concept_id:
        resolution = resolve_ingredient_products(graph, last_concept_id, products, taxonomy_index, normalized_index)
        products_by_id = {p.id: p for p in products}
        ranked = rank_by_price_direction(
            [products_by_id[pid] for pid in resolution.matching_product_ids if pid in products_by_id],
            signals.price_direction,
        )
        candidates = [p.id for p in ranked]
        track_presentation(memory, candidates)
        return RecipeFollowupResult(
            kind=RECIPE_FOLLOWUP_INGREDIENT, dish_id=active_recipe_id,
            concept_id=last_concept_id, candidate_product_ids=tuple(candidates),
        )

    # Generic continuation question ("čo ešte potrebujem?") or a servings
    # change alone - rebuild the plan, preserving selected roles (Section 17/18).
    if signals.is_recipe_followup or requested_servings:
        plan = build_recipe_shopping_plan(
            graph, active_recipe_id, products, taxonomy_index, normalized_index,
            servings=servings, basket_product_ids=selected,
        )
        return RecipeFollowupResult(kind=RECIPE_FOLLOWUP_PLAN_UPDATE, dish_id=active_recipe_id, plan=plan)

    return None


def compose_recipe_followup_answer(
    result: RecipeFollowupResult,
    graph: RecipeGraphIndex,
    products_by_id: dict[str, Product],
    lang: str = "sk",
) -> str:
    """Section 77/78 - deterministic template, no LLM (matches
    app.answer_composer's discipline). Consumes only structured facts
    already decided by resolve_recipe_followup(); never picks a mapping
    itself."""
    dish = graph.dishes_by_id.get(result.dish_id)
    dish_title = dish.title if dish else result.dish_id

    if result.kind == RECIPE_FOLLOWUP_CLARIFICATION:
        if lang == "en":
            return "Sorry, which one do you mean? I don't have a recent list to refer to."
        return "Prepáčte, ktorý presne máte na mysli? Naposledy som Vám nič nezobrazila, na čo by som mohla odkázať."

    if result.kind == RECIPE_FOLLOWUP_INGREDIENT:
        concept = graph.ingredient_concepts.get(result.concept_id)
        ingredient_label = concept.display_name if concept else result.concept_id
        if lang == "en":
            return f"Here are the options for {ingredient_label} for {dish_title}:"
        return f"Tu sú možnosti na {ingredient_label} pre {dish_title}:"

    if result.kind == RECIPE_FOLLOWUP_SELECTED:
        product = products_by_id.get(result.selected_product_id)
        title = product.title if product else result.selected_product_id
        if lang == "en":
            return f"Added {title} to your {dish_title} shopping list."
        return f"Pridala som {title} do vášho nákupného zoznamu na {dish_title}."

    if result.kind == RECIPE_FOLLOWUP_PLAN_UPDATE and result.plan is not None:
        remaining = [ing for ing in result.plan.ingredients if ing.status == STATUS_AVAILABLE]
        satisfied = [ing for ing in result.plan.ingredients if ing.status == STATUS_ALREADY_SATISFIED]
        servings_note = f" pre {result.plan.requested_servings} porcií" if result.plan.requested_servings else ""
        if lang == "en":
            if not remaining:
                return f"You already have everything needed for {dish_title}{servings_note}."
            return f"For {dish_title}{servings_note} you still need: " + ", ".join(
                graph.ingredient_concepts[i.ingredient_concept_id].display_name for i in remaining
            ) + "."
        if not remaining:
            return f"Na {dish_title}{servings_note} už máte všetko potrebné." + (
                f" Už vybraté: {', '.join(graph.ingredient_concepts[i.ingredient_concept_id].display_name for i in satisfied)}." if satisfied else ""
            )
        return f"Na {dish_title}{servings_note} ešte potrebujete: " + ", ".join(
            graph.ingredient_concepts[i.ingredient_concept_id].display_name for i in remaining
        ) + "."

    return "" if lang == "en" else ""
