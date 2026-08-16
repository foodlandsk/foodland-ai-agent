"""
app/recipe_graph.py  -  V2.8 Recipe / Product Knowledge Graph

Lightweight, in-memory, read-mostly index (Section 64 - no graph database).
Built once at startup/refresh from data ALREADY curated and in production
use (Section 3 - existing recipe knowledge is not replaced):

    app.main.RECIPE_SHOPPING_CORE_QUERIES     -> RecipeIngredient ground truth
    app.main.MISSING_INGREDIENTS_BY_SUBJECT   -> NOT_AVAILABLE ingredient text
    app.main.RECIPE_TITLE_PRODUCT_SUBJECTS    -> Dish alias index
    knowledge["sections"]["Recipes"]          -> Dish/Recipe entity metadata
    knowledge["sections"]["Products_AI"]      -> curated product->recipe links
    app.main.SPECIAL_PRODUCT_QUERIES          -> the one curated substitution

See docs/recipe-knowledge-audit.md for why these are the real ground truth
(the CMS Recipes collection itself carries no ingredient/quantity data).

Central invariant (Section 140/141): every ingredient concept is either
PRODUCT_TAXONOMY-backed (resolved through the real V2.4 structured
retrieval pipeline, app.structured_search.retrieve_products_for_query) or
RECIPE_CURATED (resolved through the exact required/excluded lexical terms
already curated in production). Never a third, invented path. UNKNOWN is
always preferred over a forced/wrong mapping.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.feed import Product
from app.ingredients import (
    ROLE_BY_TAXONOMY_FAMILY,
    infer_lexical_role,
    lexical_candidates,
    slugify_concept_id,
)
from app.product_normalizer import NormalizedProduct
from app.ranking import rank_candidates
from app.retrieval import get_structured_index
from app.search import normalize
from app.structured_search import retrieve_products_for_query
from app.taxonomy import FAMILY_DEFINITIONS, ProductTaxonomy

GRAPH_VERSION = 1

SOURCE_PRODUCT_TAXONOMY = "PRODUCT_TAXONOMY"
SOURCE_RECIPE_CURATED = "RECIPE_CURATED"
SOURCE_PRODUCTS_AI_CURATED = "PRODUCTS_AI_CURATED"
SOURCE_CURATED_SPECIAL_QUERIES = "CURATED_SPECIAL_QUERIES"
SOURCE_INFERRED = "INFERRED"

_FAMILY_BY_RULE_ID = {rule.rule_id: rule.family for rule in FAMILY_DEFINITIONS}

# A very small, explicitly-labeled set of standard-dictionary translation
# aliases (Section 7/108) for the highest commercial-value concepts. These
# are language facts (how the word is spelled in another language), not
# culinary claims - unlike substitutions, translating a word is not
# "inventing" anything. No live product/recipe text in this catalog
# actually contains these strings (verified - see docs/recipe-knowledge-audit.md),
# so they exist purely to let a customer type the ingredient in another
# supported language and still resolve to the right canonical concept.
_EXTRA_MULTILINGUAL_ALIASES: dict[str, tuple[str, ...]] = {
    "fish_sauce": ("fish sauce", "nuoc mam", "fischsauce"),
    "soy_sauce": ("soy sauce", "sojasauce"),
    "coconut_milk": ("coconut milk", "kokosmilch"),
    "rice_vinegar": ("rice vinegar", "reisessig"),
}


@dataclass(frozen=True)
class IngredientConcept:
    concept_id: str
    display_name: str
    role: str
    source: str
    confidence: str
    aliases: tuple[str, ...] = ()
    lexical_required_terms: tuple[str, ...] = ()
    lexical_excluded_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecipeIngredient:
    dish_id: str
    ingredient_concept_id: str
    raw_text: str
    role: str
    requirement: str = "REQUIRED"


@dataclass(frozen=True)
class Dish:
    dish_id: str
    title: str
    cuisine: str | None
    recipe_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecipeRecord:
    recipe_id: str
    dish_id: str
    title: str
    cuisine: str | None
    urls: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SubstitutionEdge:
    from_concept: str
    to_concept: str
    context: str
    confidence: str
    source: str
    notes: str


@dataclass
class RecipeGraphIndex:
    version: int
    dishes_by_id: dict[str, Dish]
    dish_alias_index: dict[str, str]
    recipes_by_id: dict[str, RecipeRecord]
    ingredient_concepts: dict[str, IngredientConcept]
    ingredient_alias_index: dict[str, str]
    recipe_ingredients_by_dish: dict[str, list[RecipeIngredient]]
    ingredient_to_dishes: dict[str, list[str]]
    not_available_by_dish: dict[str, tuple[str, ...]]
    substitution_edges: dict[str, list[SubstitutionEdge]]
    product_to_dishes: dict[str, list[str]]
    build_issues: list[str]
    stats: dict[str, int]
    catalog_version: int = 0


def _record_value(record: dict, key_contains: str) -> str:
    for key, value in record.items():
        if key_contains in normalize(str(key)) and value and str(value).strip() not in {"", "-"}:
            return str(value).strip()
    return ""


def _record_locale_urls(record: dict) -> dict[str, str]:
    urls: dict[str, str] = {}
    for key, value in record.items():
        normalized_key = normalize(str(key))
        if normalized_key.endswith("_url") and value:
            lang = normalized_key[: -len("_url")].upper()
            urls[lang] = str(value).strip()
    return urls


def _resolve_taxonomy_concept(
    display_name_sk: str,
    products: list[Product],
    taxonomy_index: dict[str, ProductTaxonomy],
    normalized_index: dict[str, NormalizedProduct],
) -> tuple[str, str] | None:
    """Section 18 resolver, taxonomy branch. Delegates entirely to the real
    V2.4 structured retrieval pipeline - never hand-asserts a rule_id.
    Returns (concept_id, confidence) only when every matched product agrees
    on the same taxonomy concept_id (ambiguous agreement -> None, so the
    caller falls back to the lexical branch instead of forcing a guess -
    Section 92/141)."""
    try:
        result = retrieve_products_for_query(display_name_sk, products, taxonomy_index, normalized_index)
    except Exception:
        return None
    candidate_ids = result.exact_match_ids or result.nearest_match_ids
    if not candidate_ids:
        return None
    concept_ids = {
        taxonomy_index[pid].concept_id
        for pid in candidate_ids
        if pid in taxonomy_index and taxonomy_index[pid].concept_id
    }
    if len(concept_ids) != 1:
        return None
    return concept_ids.pop(), result.confidence


def _register_concept(
    concepts: dict[str, IngredientConcept],
    *,
    concept_id: str,
    display_name: str,
    role: str,
    source: str,
    confidence: str,
    required_terms: tuple[str, ...] = (),
    excluded_terms: tuple[str, ...] = (),
) -> None:
    existing = concepts.get(concept_id)
    alias_candidates = {normalize(display_name)} | {normalize(term) for term in required_terms}
    alias_candidates.update(_EXTRA_MULTILINGUAL_ALIASES.get(concept_id, ()))
    if existing is None:
        concepts[concept_id] = IngredientConcept(
            concept_id=concept_id,
            display_name=display_name,
            role=role,
            source=source,
            confidence=confidence,
            aliases=tuple(sorted(alias_candidates)),
            lexical_required_terms=required_terms,
            lexical_excluded_terms=excluded_terms,
        )
    else:
        merged_aliases = tuple(sorted(set(existing.aliases) | alias_candidates))
        concepts[concept_id] = IngredientConcept(
            concept_id=existing.concept_id,
            display_name=existing.display_name,
            role=existing.role,
            source=existing.source,
            confidence=existing.confidence,
            aliases=merged_aliases,
            lexical_required_terms=existing.lexical_required_terms or required_terms,
            lexical_excluded_terms=existing.lexical_excluded_terms or excluded_terms,
        )


def build_recipe_graph_index(
    *,
    products: list[Product],
    taxonomy_index: dict[str, ProductTaxonomy],
    normalized_index: dict[str, NormalizedProduct],
    recipe_shopping_core_queries: dict[str, list[tuple[str, tuple[str, ...], tuple[str, ...]]]],
    missing_ingredients_by_subject: dict[str, list[str]],
    recipe_title_product_subjects: tuple[tuple[str, str], ...],
    cms_recipes: list[dict],
    products_ai: list[dict],
    special_product_queries: dict[str, list[str]],
    catalog_version: int = 0,
) -> RecipeGraphIndex:
    """Atomic build (Section 66) - returns one complete, internally
    consistent RecipeGraphIndex. Caller swaps the module-level reference
    only after this returns (see app.main wiring), so a rebuild in
    progress never exposes a partially-built graph."""
    build_issues: list[str] = []

    # --- dish alias index (Section 42/45) -----------------------------
    markers_by_dish: dict[str, list[str]] = {}
    for marker, dish_id in recipe_title_product_subjects:
        if dish_id in recipe_shopping_core_queries:
            markers_by_dish.setdefault(dish_id, []).append(normalize(marker))

    # --- CMS recipe records, matched to dishes by marker (Section 41/73/74) ---
    recipes_by_id: dict[str, RecipeRecord] = {}
    recipe_ids_by_dish: dict[str, list[str]] = {}
    for record in cms_recipes:
        title = _record_value(record, "recept") or _record_value(record, "nazov")
        if not title:
            continue
        normalized_title = normalize(title)
        matched_dish_id = None
        for dish_id, markers in markers_by_dish.items():
            if any(marker in normalized_title for marker in markers):
                matched_dish_id = dish_id
                break
        if matched_dish_id is None:
            continue
        recipe_id = slugify_concept_id(title)
        cuisine = _record_value(record, "kuchy") or None
        recipes_by_id[recipe_id] = RecipeRecord(
            recipe_id=recipe_id,
            dish_id=matched_dish_id,
            title=title,
            cuisine=cuisine,
            urls=_record_locale_urls(record),
        )
        recipe_ids_by_dish.setdefault(matched_dish_id, []).append(recipe_id)

    # --- dishes (Section 41/43/44) -------------------------------------
    dishes_by_id: dict[str, Dish] = {}
    dish_alias_index: dict[str, str] = {}
    for dish_id in recipe_shopping_core_queries:
        dish_recipe_ids = tuple(recipe_ids_by_dish.get(dish_id, ()))
        if dish_recipe_ids:
            representative = recipes_by_id[dish_recipe_ids[0]]
            title = representative.title
            cuisine = representative.cuisine
        else:
            title = dish_id.replace("_", " ").title()
            cuisine = None
            build_issues.append(f"dish '{dish_id}' has no matching CMS Recipes record")
        dishes_by_id[dish_id] = Dish(dish_id=dish_id, title=title, cuisine=cuisine, recipe_ids=dish_recipe_ids)
        dish_alias_index[normalize(dish_id.replace("_", " "))] = dish_id
        dish_alias_index[normalize(title)] = dish_id
        for marker in markers_by_dish.get(dish_id, ()):
            dish_alias_index[marker] = dish_id

    # --- ingredient concepts + recipe ingredients (Section 6/13/15/16/18) ---
    ingredient_concepts: dict[str, IngredientConcept] = {}
    recipe_ingredients_by_dish: dict[str, list[RecipeIngredient]] = {}
    ingredient_to_dishes: dict[str, list[str]] = {}

    for dish_id, entries in recipe_shopping_core_queries.items():
        recipe_ingredients_by_dish[dish_id] = []
        for display_name, required_terms, excluded_terms in entries:
            resolved = _resolve_taxonomy_concept(display_name, products, taxonomy_index, normalized_index)
            if resolved:
                concept_id, confidence = resolved
                role = ROLE_BY_TAXONOMY_FAMILY.get(_FAMILY_BY_RULE_ID.get(concept_id), infer_lexical_role(display_name))
                _register_concept(
                    ingredient_concepts,
                    concept_id=concept_id,
                    display_name=display_name,
                    role=role,
                    source=SOURCE_PRODUCT_TAXONOMY,
                    confidence=confidence if confidence in {"HIGH", "MEDIUM"} else "MEDIUM",
                    required_terms=required_terms,
                    excluded_terms=excluded_terms,
                )
            else:
                concept_id = slugify_concept_id(display_name)
                role = infer_lexical_role(display_name)
                _register_concept(
                    ingredient_concepts,
                    concept_id=concept_id,
                    display_name=display_name,
                    role=role,
                    source=SOURCE_RECIPE_CURATED,
                    confidence="MEDIUM",
                    required_terms=required_terms,
                    excluded_terms=excluded_terms,
                )

            concept = ingredient_concepts[concept_id]
            recipe_ingredients_by_dish[dish_id].append(
                RecipeIngredient(
                    dish_id=dish_id,
                    ingredient_concept_id=concept_id,
                    raw_text=display_name,
                    role=concept.role,
                    requirement="REQUIRED",
                )
            )
            dish_list = ingredient_to_dishes.setdefault(concept_id, [])
            if dish_id not in dish_list:
                dish_list.append(dish_id)

    # --- ingredient alias index (Section 7/8) --------------------------
    ingredient_alias_index: dict[str, str] = {}
    for concept in ingredient_concepts.values():
        ingredient_alias_index[normalize(concept.concept_id.replace("_", " "))] = concept.concept_id
        for alias in concept.aliases:
            normalized_alias = normalize(alias)
            if normalized_alias:
                ingredient_alias_index[normalized_alias] = concept.concept_id

    # --- NOT_AVAILABLE ingredients (Section 19/20, real curated data) ---
    not_available_by_dish: dict[str, tuple[str, ...]] = {}
    for dish_id in dishes_by_id:
        items = missing_ingredients_by_subject.get(dish_id)
        if items:
            not_available_by_dish[dish_id] = tuple(items)

    # --- substitution graph (Section 35/37/40, exactly one real edge) ---
    substitution_edges: dict[str, list[SubstitutionEdge]] = {}
    vegan_fish_sauce_terms = special_product_queries.get("vegan_fish_sauce_replacement", ())
    # The 47 curated dishes never specify light/dark soy sauce explicitly
    # (always plain "sojova omacka"), so that concept may resolve as
    # PRODUCT_TAXONOMY ("soy_sauce", when the catalog query is unambiguous)
    # or fall back to RECIPE_CURATED ("sojova_omacka") depending on live
    # catalog contents - discover which one actually exists rather than
    # assuming (Section 92 - no silent parent-fallback guessing here).
    _soy_sauce_target = "soy_sauce" if "soy_sauce" in ingredient_concepts else "sojova_omacka"
    if "fish_sauce" in ingredient_concepts and _soy_sauce_target in ingredient_concepts and vegan_fish_sauce_terms:
        edge = SubstitutionEdge(
            from_concept="fish_sauce",
            to_concept=_soy_sauce_target,
            context="vegan",
            confidence="MEDIUM",
            source=SOURCE_CURATED_SPECIAL_QUERIES,
            notes=(
                "Kurátorská vegánska náhrada rybacej omáčky (SPECIAL_PRODUCT_QUERIES."
                "vegan_fish_sauce_replacement): " + ", ".join(vegan_fish_sauce_terms)
            ),
        )
        substitution_edges.setdefault("fish_sauce", []).append(edge)
    else:
        build_issues.append("vegan_fish_sauce_replacement substitution edge skipped: source concept(s) missing")

    # --- reverse product -> dish lookup (Section 48/50, curated seed) ---
    product_to_dishes: dict[str, list[str]] = {}
    for record in products_ai:
        linked_title = _record_value(record, "suvisiaci recept")
        product_id = str(record.get("ID") or "").strip()
        if not linked_title or not product_id:
            continue
        normalized_title = normalize(linked_title)
        dish_id = dish_alias_index.get(normalized_title)
        if dish_id is None:
            for marker, candidate_dish_id in dish_alias_index.items():
                if marker and marker in normalized_title:
                    dish_id = candidate_dish_id
                    break
        if dish_id:
            product_to_dishes.setdefault(product_id, [])
            if dish_id not in product_to_dishes[product_id]:
                product_to_dishes[product_id].append(dish_id)
        else:
            build_issues.append(f"Products_AI record {product_id} links unresolved recipe '{linked_title}'")

    # --- validation (Section 67) ----------------------------------------
    for dish_id, ingredients in recipe_ingredients_by_dish.items():
        if not ingredients:
            build_issues.append(f"dish '{dish_id}' resolved zero ingredients")
    for concept_id, edges in substitution_edges.items():
        if concept_id not in ingredient_concepts:
            build_issues.append(f"substitution edge references unknown source concept '{concept_id}'")
        for edge in edges:
            if edge.to_concept not in ingredient_concepts:
                build_issues.append(f"substitution edge references unknown target concept '{edge.to_concept}'")

    taxonomy_backed = sum(1 for c in ingredient_concepts.values() if c.source == SOURCE_PRODUCT_TAXONOMY)
    curated_lexical = sum(1 for c in ingredient_concepts.values() if c.source == SOURCE_RECIPE_CURATED)
    unresolved = 0
    for concept in ingredient_concepts.values():
        if concept.source != SOURCE_RECIPE_CURATED:
            continue
        if not lexical_candidates(products, concept.display_name, concept.lexical_required_terms, concept.lexical_excluded_terms, limit=1):
            unresolved += 1

    stats = {
        "recipe_count": len(recipes_by_id),
        "dish_count": len(dishes_by_id),
        "ingredient_concept_count": len(ingredient_concepts),
        "ingredient_concept_taxonomy_backed": taxonomy_backed,
        "ingredient_concept_recipe_curated": curated_lexical,
        "ingredient_alias_count": len(ingredient_alias_index),
        "ingredient_role_edge_count": sum(len(v) for v in recipe_ingredients_by_dish.values()),
        "ingredient_product_mapping_count": len(ingredient_concepts) - unresolved,
        "unresolved_ingredient_concept_count": unresolved,
        "reverse_ingredient_to_dish_count": len(ingredient_to_dishes),
        "reverse_product_to_dish_count": len(product_to_dishes),
        "substitution_edge_count": sum(len(v) for v in substitution_edges.values()),
        "build_issue_count": len(build_issues),
    }

    return RecipeGraphIndex(
        version=GRAPH_VERSION,
        dishes_by_id=dishes_by_id,
        dish_alias_index=dish_alias_index,
        recipes_by_id=recipes_by_id,
        ingredient_concepts=ingredient_concepts,
        ingredient_alias_index=ingredient_alias_index,
        recipe_ingredients_by_dish=recipe_ingredients_by_dish,
        ingredient_to_dishes=ingredient_to_dishes,
        not_available_by_dish=not_available_by_dish,
        substitution_edges=substitution_edges,
        product_to_dishes=product_to_dishes,
        build_issues=build_issues,
        stats=stats,
        catalog_version=catalog_version,
    )


def resolve_dish(graph: RecipeGraphIndex, message: str) -> str | None:
    """Section 45/46 dish lookup - alias index only, no per-request scan."""
    normalized = normalize(message)
    if not normalized:
        return None
    if normalized in graph.dish_alias_index:
        return graph.dish_alias_index[normalized]
    for alias, dish_id in graph.dish_alias_index.items():
        if alias and alias in normalized:
            return dish_id
    return None


def resolve_ingredient_concept(graph: RecipeGraphIndex, text: str) -> str | None:
    """Section 47/61 ingredient lookup for informational queries
    ("co je mirin?"). Alias-index only - deterministic, no scan."""
    normalized = normalize(text)
    if not normalized:
        return None
    if normalized in graph.ingredient_alias_index:
        return graph.ingredient_alias_index[normalized]
    for alias, concept_id in graph.ingredient_alias_index.items():
        if alias and alias in normalized:
            return concept_id
    return None


def recipes_for_ingredient_concept(graph: RecipeGraphIndex, concept_id: str, limit: int = 5) -> list[str]:
    """Section 48/49/50 reverse lookup: ingredient/product concept -> dishes."""
    return list(graph.ingredient_to_dishes.get(concept_id, ()))[:limit]


def recipes_for_product(graph: RecipeGraphIndex, product_id: str, limit: int = 5) -> list[str]:
    """Section 48 reverse lookup: product SKU -> dishes (curated seed only,
    HIGH confidence - Products_AI 'Suvisiaci recept' links)."""
    return list(graph.product_to_dishes.get(product_id, ()))[:limit]


def match_recipes_by_ingredient_concepts(
    graph: RecipeGraphIndex,
    concept_ids: list[str],
    limit: int = 5,
) -> list[tuple[str, int, int]]:
    """Section 51/52/113 multi-ingredient recipe discovery. Returns
    (dish_id, satisfied_count, total_required_count) sorted by satisfied
    count desc, then coverage ratio desc, then dish_id for determinism.
    Deliberately simple/deterministic - no advanced meal planning
    (Section 51)."""
    wanted = set(concept_ids)
    scored: list[tuple[str, int, int]] = []
    for dish_id, ingredients in graph.recipe_ingredients_by_dish.items():
        required = [ing for ing in ingredients if ing.requirement == "REQUIRED"]
        if not required:
            continue
        satisfied = sum(1 for ing in required if ing.ingredient_concept_id in wanted)
        if satisfied == 0:
            continue
        scored.append((dish_id, satisfied, len(required)))
    scored.sort(key=lambda item: (-item[1], -(item[1] / item[2]), item[0]))
    return scored[:limit]


CATALOG_AVAILABLE = "AVAILABLE"
CATALOG_NOT_AVAILABLE = "NOT_AVAILABLE"
CATALOG_UNKNOWN_MAPPING = "UNKNOWN_MAPPING"


@dataclass(frozen=True)
class IngredientProductResolution:
    """Section 18 structured resolver output - never free-form prose."""
    ingredient_concept_id: str
    catalog_status: str
    matching_product_ids: tuple[str, ...] = ()
    confidence: str = "UNKNOWN"
    evidence: tuple[str, ...] = ()


def resolve_ingredient_products(
    graph: RecipeGraphIndex,
    concept_id: str,
    products: list[Product],
    taxonomy_index: dict[str, ProductTaxonomy],
    normalized_index: dict[str, NormalizedProduct],
    *,
    limit: int = 8,
) -> IngredientProductResolution:
    """Section 18 - the one deterministic entry point every V2.8 consumer
    (RecipeShoppingPlan, informational answers, reverse lookup) uses to go
    from an ingredient concept to real product ids. Never returns a forced
    mapping (Section 19/141): a concept with no real catalog evidence comes
    back NOT_AVAILABLE/UNKNOWN_MAPPING, not an arbitrary nearest product."""
    concept = graph.ingredient_concepts.get(concept_id)
    if concept is None:
        return IngredientProductResolution(
            ingredient_concept_id=concept_id,
            catalog_status=CATALOG_UNKNOWN_MAPPING,
            confidence="UNKNOWN",
            evidence=("ingredient concept not found in graph",),
        )

    if concept.source == SOURCE_PRODUCT_TAXONOMY:
        try:
            result = retrieve_products_for_query(concept.display_name, products, taxonomy_index, normalized_index)
            unranked_ids = result.exact_match_ids or result.nearest_match_ids
            if unranked_ids and result.interpretation is not None:
                index = get_structured_index(products, taxonomy_index, normalized_index)
                products_by_id = {product.id: product for product in products}
                ranked_ids = rank_candidates(unranked_ids, result.interpretation, products_by_id, index, normalized_index)
            else:
                ranked_ids = unranked_ids
        except Exception:
            result = None
            ranked_ids = []
        candidate_ids = tuple(ranked_ids[:limit]) if result else ()
        if candidate_ids:
            return IngredientProductResolution(
                ingredient_concept_id=concept_id,
                catalog_status=CATALOG_AVAILABLE,
                matching_product_ids=candidate_ids,
                confidence=result.confidence,
                evidence=(f"PRODUCT_TAXONOMY:{concept_id}",),
            )
        return IngredientProductResolution(
            ingredient_concept_id=concept_id,
            catalog_status=CATALOG_NOT_AVAILABLE,
            confidence=concept.confidence,
            evidence=(f"PRODUCT_TAXONOMY:{concept_id}:no_current_stock",),
        )

    matches = lexical_candidates(products, concept.display_name, concept.lexical_required_terms, concept.lexical_excluded_terms, limit=limit)
    if matches:
        return IngredientProductResolution(
            ingredient_concept_id=concept_id,
            catalog_status=CATALOG_AVAILABLE,
            matching_product_ids=tuple(p.id for p in matches),
            confidence=concept.confidence,
            evidence=(f"RECIPE_CURATED:{concept.lexical_required_terms}",),
        )
    return IngredientProductResolution(
        ingredient_concept_id=concept_id,
        catalog_status=CATALOG_NOT_AVAILABLE,
        confidence="LOW",
        evidence=(f"RECIPE_CURATED:{concept.lexical_required_terms}:no_match",),
    )


def get_substitutes(graph: RecipeGraphIndex, concept_id: str, context: str | None = None) -> list[SubstitutionEdge]:
    """Section 35/36/81 - curated only, returns [] (not a guess) when
    nothing verified exists for this concept/context (Section 40)."""
    edges = graph.substitution_edges.get(concept_id, [])
    if context is None:
        return list(edges)
    return [edge for edge in edges if edge.context == context]
