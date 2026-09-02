"""
app/cross_sell.py  -  V2.6 Contextual Cross-Sell & Basket Intelligence

Answers "what else would genuinely help the customer complete the same
task?" - never "what else can we advertise?" (Section 2 of the spec).

Complementary ROLES are determined before products (Section 7/8): every
role is a V2.3 taxonomy concept_id (app.taxonomy.FAMILY_DEFINITIONS rule
id) wherever possible, never free-text. Two evidence graphs are mined
from data ALREADY curated by Foodland/earlier V2 sprints, not invented:

1. RECIPE_ROLE_INDEX - app.main.RECIPE_SHOPPING_CORE_QUERIES (47 dishes,
   each a curated ingredient-query list) normalized through V2.4's own
   app.query_constraints.parse_structured_query() - the same taxonomy
   that classifies catalog products classifies these ingredient phrases,
   so "ryzove rezance" -> noodles/rice_noodles the same way it would for
   a product title (Section 11).
2. USE_CASE_ROLE_INDEX - a small, explicitly hand-picked subset of
   app.main.SPECIAL_PRODUCT_QUERIES ("sushi_rice", "gluten_free_sushi",
   "sushi_condiments", "rice_seasoning") - the entries that describe how
   to USE/prepare a product, not generic marketing themes ("mild"/"hot"/
   "kids_snack" were deliberately excluded after inspection showed they
   produce overly aggressive pairings, e.g. suggesting curry paste for a
   bare jasmine rice query - exactly what Section 31/88 forbid).

Curated `data/knowledge.json["CrossSell"]` (per-product, URL-resolved to
product ids) is used only to REINFORCE roles already established by
recipe/use-case context, never as an independent eligibility trigger -
inspection during design found it recommends curry paste + soy sauce for
a bare jasmine rice product, which is real curated business data but not
safe to show without contextual justification (documented in
docs/cross-sell-audit.md).

No LLM anywhere in this module (Section 70) - selection is entirely
deterministic set operations over precomputed indexes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import unquote

from app.feed import Product
from app.fbt import fbt_recommendations
from app.query_constraints import parse_structured_query
from app.search import format_product
from app.taxonomy import FAMILY_DEFINITIONS_BY_ID, ProductTaxonomy

logger = logging.getLogger(__name__)

# --- context types (Section 6) ---------------------------------------------
USE_CASE_COMPLETION = "USE_CASE_COMPLETION"
RECIPE_COMPLETION = "RECIPE_COMPLETION"
PRODUCT_COMPLEMENT = "PRODUCT_COMPLEMENT"

# --- evidence source tags (Section 26/57) -----------------------------------
SOURCE_RECIPE = "recipe"
SOURCE_CURATED = "curated_crosssell"
SOURCE_USE_CASE = "use_case_compatibility"
SOURCE_FBT = "fbt"

DEFAULT_MAX_PRODUCTS = 3

# Curated dish->ingredient-query data (Section 10/11). Kept as a lazily
# resolved reference to app.main to avoid a hard import-time dependency -
# app/main.py is the only module that legitimately owns request routing
# and this data was authored there across several earlier sprints; V2.6
# reads it rather than duplicating or relocating it (Section 110: do not
# destroy existing modules; minimal, targeted reuse).
_recipe_shopping_core_queries_ref: dict | None = None
_special_product_queries_ref: dict | None = None

# Section 7/8 - hand-verified subset of SPECIAL_PRODUCT_QUERIES that are
# genuinely "how to use/prepare this product" companion sets, not generic
# marketing/gift themes. Deliberately narrow (Section 31/88).
_USE_CASE_SOURCE_KEYS = ("sushi_rice", "gluten_free_sushi", "sushi_condiments", "rice_seasoning")

# use_case attribute value (from FamilyRule.attributes) -> which
# SPECIAL_PRODUCT_QUERIES source keys describe its companion products.
_USE_CASE_TO_SOURCE_KEYS = {
    "sushi": ("sushi_rice", "gluten_free_sushi", "sushi_condiments"),
}


def set_data_sources(recipe_shopping_core_queries: dict, special_product_queries: dict) -> None:
    """Called once from app/main.py at module load to hand in the two
    curated dicts this module mines (Section 110 - no circular import;
    app.main imports app.cross_sell, never the reverse)."""
    global _recipe_shopping_core_queries_ref, _special_product_queries_ref
    _recipe_shopping_core_queries_ref = recipe_shopping_core_queries
    _special_product_queries_ref = special_product_queries
    global _RECIPE_ROLE_INDEX, _USE_CASE_ROLE_INDEX
    _RECIPE_ROLE_INDEX = None
    _USE_CASE_ROLE_INDEX = None


_RECIPE_ROLE_INDEX: dict[str, list[str]] | None = None
_USE_CASE_ROLE_INDEX: dict[str, list[str]] | None = None


def _role_key_for_query_text(text: str) -> str | None:
    """Normalizes one curated ingredient/companion phrase into a taxonomy
    concept_id role key (Section 11) - phrases with no recognized concept
    (fresh produce, generic meat, ungrounded items like "galangal") return
    None and are simply excluded, never guessed (Section 61)."""
    query = parse_structured_query(text, known_brands=())
    return query.concept_id or None


def _build_role_indexes() -> None:
    global _RECIPE_ROLE_INDEX, _USE_CASE_ROLE_INDEX
    if _RECIPE_ROLE_INDEX is not None and _USE_CASE_ROLE_INDEX is not None:
        return

    recipe_index: dict[str, list[str]] = {}
    for dish, ingredient_queries in (_recipe_shopping_core_queries_ref or {}).items():
        roles: list[str] = []
        for query_text, _required, _excluded in ingredient_queries:
            role = _role_key_for_query_text(query_text)
            if role and role not in roles:
                roles.append(role)
        if roles:
            recipe_index[dish] = roles
    _RECIPE_ROLE_INDEX = recipe_index

    use_case_index: dict[str, list[str]] = {}
    for use_case, source_keys in _USE_CASE_TO_SOURCE_KEYS.items():
        roles = []
        for key in source_keys:
            for phrase in (_special_product_queries_ref or {}).get(key, []):
                role = _role_key_for_query_text(phrase)
                if role and role not in roles:
                    roles.append(role)
        if roles:
            use_case_index[use_case] = roles
    _USE_CASE_ROLE_INDEX = use_case_index


def roles_for_recipe(dish: str) -> list[str]:
    _build_role_indexes()
    return list((_RECIPE_ROLE_INDEX or {}).get(dish, []))


def roles_for_use_case(use_case: str) -> list[str]:
    _build_role_indexes()
    return list((_USE_CASE_ROLE_INDEX or {}).get(use_case, []))


def known_recipe_dishes() -> frozenset[str]:
    _build_role_indexes()
    return frozenset((_RECIPE_ROLE_INDEX or {}).keys())


# --- curated per-product CrossSell knowledge (Section 13) ------------------

_curated_cross_sell_cache: dict[tuple[int, int, int], dict[str, list[str]]] = {}


def build_curated_cross_sell_index(products: list[Product], cross_sell_records: list[dict]) -> dict[str, list[str]]:
    """product_id -> [complementary product_id, ...], resolved via URL
    match against the CURRENT catalog (Section 64 - never serves a
    deleted product; ids not found in `products` are silently dropped)."""
    link_to_id = {product.link: product.id for product in products if product.link}
    index: dict[str, list[str]] = {}
    for record in cross_sell_records:
        source_id = str(record.get("ID", ""))
        if not source_id:
            continue
        targets: list[str] = []
        for i in range(1, 6):
            url = record.get(f"Cross-sell {i}_url")
            if not url:
                continue
            target_id = link_to_id.get(url) or link_to_id.get(unquote(url))
            if target_id and target_id != source_id and target_id not in targets:
                targets.append(target_id)
        if targets:
            index[source_id] = targets
    return index


def get_curated_cross_sell_index(products: list[Product], cross_sell_records: list[dict]) -> dict[str, list[str]]:
    key = (id(products), len(products), id(cross_sell_records))
    cached = _curated_cross_sell_cache.get(key)
    if cached is None:
        cached = build_curated_cross_sell_index(products, cross_sell_records)
        if len(_curated_cross_sell_cache) > 4:
            _curated_cross_sell_cache.clear()
        _curated_cross_sell_cache[key] = cached
    return cached


# --- decision + candidate schema (Section 5/26) -----------------------------

@dataclass
class CrossSellDecision:
    eligible: bool = False
    reason: str = ""
    context_type: str = ""
    primary_concept_ids: list[str] = field(default_factory=list)
    complementary_roles: list[str] = field(default_factory=list)
    max_products: int = DEFAULT_MAX_PRODUCTS


@dataclass
class CrossSellCandidate:
    product_id: str
    role: str
    evidence: list[str] = field(default_factory=list)
    reason_code: str = ""
    score: float = 0.0


def should_cross_sell(
    *,
    structured_presentation,  # app.result_sets.ResultSet | None
    related_subject: str | None,
    is_continuation: bool,
) -> CrossSellDecision:
    """The eligibility gate (Section 4). Conservative by default - a bare
    variety query ("jazmínová ryža") with no recipe/use-case context is
    NOT eligible (Section 31/88), even though curated per-product
    CrossSell data exists for it (see module docstring)."""
    if structured_presentation is None or is_continuation:
        return CrossSellDecision(eligible=False, reason="no_primary_or_continuation")

    strategy = structured_presentation.answer_strategy
    if strategy in {"NO_EXACT_MATCH", "GROUPED_DISCOVERY"}:
        return CrossSellDecision(eligible=False, reason=f"strategy_{strategy.lower()}_not_eligible")

    query = structured_presentation.structured_query
    primary_concept_ids = [query.concept_id] if getattr(query, "concept_id", "") else []
    use_case = query.attributes.get("use_case") if query.attributes else None

    _build_role_indexes()

    if related_subject and related_subject in (_RECIPE_ROLE_INDEX or {}):
        roles = [r for r in roles_for_recipe(related_subject) if r not in primary_concept_ids]
        if roles:
            return CrossSellDecision(
                eligible=True, reason="recipe_context", context_type=RECIPE_COMPLETION,
                primary_concept_ids=primary_concept_ids, complementary_roles=roles, max_products=DEFAULT_MAX_PRODUCTS,
            )

    if use_case:
        roles = [r for r in roles_for_use_case(use_case) if r not in primary_concept_ids]
        if roles:
            return CrossSellDecision(
                eligible=True, reason="use_case_context", context_type=USE_CASE_COMPLETION,
                primary_concept_ids=primary_concept_ids, complementary_roles=roles, max_products=DEFAULT_MAX_PRODUCTS,
            )

    if strategy == "EXACT_MATCH":
        return CrossSellDecision(eligible=False, reason="exact_lookup_no_context")

    return CrossSellDecision(eligible=False, reason="no_grounded_context")


# --- candidate generation, semantic validation, ranking (Section 7/18/25) --

_SOURCE_PRIORITY = {SOURCE_RECIPE: 4, SOURCE_USE_CASE: 3, SOURCE_CURATED: 2, SOURCE_FBT: 1}

_concept_index_cache: dict[tuple[int, int], dict[str, list[str]]] = {}


def _concept_id_index(taxonomy_index: dict[str, ProductTaxonomy], products: list[Product]) -> dict[str, list[str]]:
    """concept_id -> product ids, HIGH/MEDIUM confidence only (same gate
    V2.4's StructuredProductIndex uses) - built once per catalog identity."""
    key = (id(products), len(products))
    cached = _concept_index_cache.get(key)
    if cached is not None:
        return cached
    index: dict[str, list[str]] = {}
    for product in products:
        tax = taxonomy_index.get(product.id)
        if tax is None or not tax.concept_id or tax.confidence not in {"HIGH", "MEDIUM"}:
            continue
        index.setdefault(tax.concept_id, []).append(product.id)
    if len(_concept_index_cache) > 4:
        _concept_index_cache.clear()
    _concept_index_cache[key] = index
    return index


def _is_in_stock(product: Product) -> bool:
    return str(getattr(product, "availability", "")) in {"in_stock", "in stock"}


def _same_primary_need(
    candidate_id: str,
    primary_family: str | None,
    primary_subfamily: str | None,
    taxonomy_index: dict[str, ProductTaxonomy],
) -> bool:
    """Section 18 - a product satisfying the SAME primary need is never
    cross-sell, regardless of which role/evidence surfaced it.

    Granularity matters: comparing by bare `family` alone is too coarse
    for a family like `sauce` (soy_sauce vs fish_sauce are genuinely
    different complementary needs, not substitutes for each other) - it
    would silently exclude every other sauce subfamily from ever being a
    valid cross-sell candidate. Compare by `subfamily` when the primary
    has one (rice: jasmine/basmati/plain all share subfamily="plain_rice"
    - correctly collapsed into "same need", matching the spec's own
    example); fall back to `family` only when subfamily is None (e.g.
    curry_paste variety rules, where different flavours are substitutes
    of each other, not complements)."""
    if not primary_family:
        return False
    tax = taxonomy_index.get(candidate_id)
    if tax is None:
        return False
    if primary_subfamily:
        return tax.canonical_subfamily == primary_subfamily
    return tax.canonical_family == primary_family


def generate_candidates(
    decision: CrossSellDecision,
    *,
    primary_product_ids: list[str],
    exclude_ids: set[str],
    products_by_id: dict[str, Product],
    taxonomy_index: dict[str, ProductTaxonomy],
    products: list[Product],
    primary_family: str | None,
    primary_subfamily: str | None = None,
    curated_cross_sell_index: dict[str, list[str]] | None = None,
    fbt_data: dict | None = None,
) -> list[CrossSellCandidate]:
    """Role-first candidate generation (Section 7): a product only ever
    enters the result because it fills one of `decision.complementary_
    roles`, never the other way around."""
    if not decision.eligible or not decision.complementary_roles:
        return []

    concept_index = _concept_id_index(taxonomy_index, products)
    role_source = SOURCE_RECIPE if decision.context_type == RECIPE_COMPLETION else SOURCE_USE_CASE

    candidates_by_role: dict[str, CrossSellCandidate] = {}

    for role in decision.complementary_roles:
        product_ids = concept_index.get(role, [])
        eligible_ids = [
            pid for pid in product_ids
            if pid not in exclude_ids and not _same_primary_need(pid, primary_family, primary_subfamily, taxonomy_index)
        ]
        if not eligible_ids:
            continue
        # Section 46: prefer in-stock; deterministic tie-break by id (Section 46/47).
        eligible_ids.sort(key=lambda pid: (not _is_in_stock(products_by_id[pid]), pid))
        chosen = eligible_ids[0]
        candidates_by_role[role] = CrossSellCandidate(
            product_id=chosen, role=role, evidence=[role_source],
            reason_code=role, score=_SOURCE_PRIORITY[role_source],
        )

    # Curated per-product CrossSell reinforces roles already established -
    # never introduces a role the recipe/use-case context didn't (Section 51).
    if curated_cross_sell_index:
        for primary_id in primary_product_ids:
            for target_id in curated_cross_sell_index.get(primary_id, []):
                if target_id in exclude_ids or _same_primary_need(target_id, primary_family, primary_subfamily, taxonomy_index):
                    continue
                target_tax = taxonomy_index.get(target_id)
                target_role = target_tax.concept_id if target_tax else None
                if not target_role or target_role not in decision.complementary_roles:
                    continue
                existing = candidates_by_role.get(target_role)
                if existing is None:
                    candidates_by_role[target_role] = CrossSellCandidate(
                        product_id=target_id, role=target_role, evidence=[SOURCE_CURATED],
                        reason_code=target_role, score=_SOURCE_PRIORITY[SOURCE_CURATED],
                    )
                elif existing.product_id == target_id and SOURCE_CURATED not in existing.evidence:
                    existing.evidence.append(SOURCE_CURATED)
                    existing.score += 0.5

    # FBT reinforces/tie-breaks EXISTING role candidates only - never
    # introduces a new role by itself (Section 15/16/51).
    if fbt_data and fbt_data.get("active"):
        for primary_id in primary_product_ids:
            for target_id in fbt_recommendations(primary_id, fbt_data, limit=10):
                if target_id in exclude_ids or _same_primary_need(target_id, primary_family, primary_subfamily, taxonomy_index):
                    continue
                target_tax = taxonomy_index.get(target_id)
                target_role = target_tax.concept_id if target_tax else None
                if not target_role or target_role not in decision.complementary_roles:
                    continue
                existing = candidates_by_role.get(target_role)
                if existing is not None and existing.product_id == target_id and SOURCE_FBT not in existing.evidence:
                    existing.evidence.append(SOURCE_FBT)
                    existing.score += 0.25

    return list(candidates_by_role.values())


def rank_candidates(candidates: list[CrossSellCandidate]) -> list[CrossSellCandidate]:
    """Section 25 - contextual/semantic priority (multi-source score)
    first, deterministic id tie-break last."""
    return sorted(candidates, key=lambda c: (-c.score, c.product_id))


def build_cross_sell(
    *,
    structured_presentation,
    related_subject: str | None,
    is_continuation: bool,
    products: list[Product],
    taxonomy_index: dict[str, ProductTaxonomy],
    knowledge: dict,
    fbt_data: dict | None = None,
) -> tuple[CrossSellDecision, list[dict]]:
    """Top-level orchestrator (Section 111 - clean interface for future
    workflow callers). Returns (decision, formatted product dicts) -
    formatted the same way app.search.format_product() formats primary
    results, so the widget/response schema stays consistent."""
    decision = should_cross_sell(
        structured_presentation=structured_presentation,
        related_subject=related_subject,
        is_continuation=is_continuation,
    )
    if not decision.eligible:
        return decision, []

    try:
        products_by_id = {product.id: product for product in products}
        primary_product_ids = list(structured_presentation.initial_page_ids())
        exclude_ids = set(structured_presentation.ranked_product_ids)
        cross_sell_records = knowledge.get("sections", {}).get("CrossSell", []) if isinstance(knowledge, dict) else []
        curated_index = get_curated_cross_sell_index(products, cross_sell_records)

        candidates = generate_candidates(
            decision,
            primary_product_ids=primary_product_ids,
            exclude_ids=exclude_ids,
            products_by_id=products_by_id,
            taxonomy_index=taxonomy_index,
            products=products,
            primary_family=structured_presentation.structured_query.family,
            primary_subfamily=structured_presentation.structured_query.subfamily,
            curated_cross_sell_index=curated_index,
            fbt_data=fbt_data,
        )
        ranked = rank_candidates(candidates)[: decision.max_products]
        formatted = [format_product(products_by_id[c.product_id]) for c in ranked if c.product_id in products_by_id]
        for product_dict, candidate in zip(formatted, ranked):
            product_dict["cross_sell_role"] = candidate.role
            product_dict["cross_sell_reason"] = _reason_text(candidate.role)
            product_dict["cross_sell_evidence"] = candidate.evidence
            # V2.17 (Section 62 Gate B, Section 64) - mirrored onto the same
            # recommendation_group/recommendation_reason fields
            # app.main.annotate_recommendations() already sets on primary
            # `products`, which app/widget.js's existing card template
            # already renders (no new field name, no new widget rendering
            # logic invented - reuses the proven mechanism instead of a
            # parallel one).
            product_dict["recommendation_group"] = "Hodí sa k tomu"
            product_dict["recommendation_reason"] = product_dict["cross_sell_reason"]
        return decision, formatted
    except Exception:
        logger.warning("Cross-sell generation failed, suppressing section (Section 106).", exc_info=True)
        return CrossSellDecision(eligible=False, reason="internal_error"), []


def _reason_text(role: str) -> str:
    """Section 27/73 - short, grounded reason derived from the taxonomy
    display_label, never an invented culinary claim."""
    rule = FAMILY_DEFINITIONS_BY_ID.get(role)
    label = rule.display_label if rule is not None and rule.display_label else role
    return label
