"""
app/basket_completion.py  -  V2.14e Evidence-Grounded Basket Completion.

Answers goal-oriented shopping questions ("co potrebujem na pad thai?",
"co mi este chyba na pho?", "doplň mi veci na kari") with a role-based,
evidence-grounded basket: for the named use case, resolve each REQUIRED
product role to a catalog candidate (or an honest gap), never inventing
a product for a role that cannot be safely resolved.

WHY A NEW MODULE (same justification bar as app.use_case_advice, V2.14c
Section 39): none of the existing primitives owns "resolve ALL roles
for a dish into one structured basket with an explicit status per
role".
- app.use_case_advice answers exactly ONE role per turn ("aka omacka na
  pho?"), by design (Section 18 there: never guess which single role a
  bare use-case mention means) - deliberately not a basket.
- app.recipe_shopping.build_recipe_shopping_plan() already does this
  role-status modelling FOR DISHES REGISTERED IN app.recipe_graph
  (pho/pad_thai/tom_kha/kari/thajske_kari/ramen among others) and is
  ALREADY LIVE for pad_thai/tom_kha today, reached via the pre-existing
  bare-dish RECIPE_INTENT_MARKERS (V2.9-era) + wants_recipe_products()
  path - this module does NOT reimplement that, it reuses the SAME
  session state (app.session_state.get_selected_ingredient_products/
  mark_ingredient_selected) for continuity and defers entirely
  (returns None) whenever recipe_subject is already set, so pad_thai/
  tom_kha's existing, tested behavior is completely untouched.
- app.recipe_graph has no dish entry for "sushi" at all (a deliberate,
  pre-existing V2.8 scope decision - sushi's shopping list was always
  handled by the separate, flat sushi_shopping_core_products()), so
  pho/pad_thai/tom_kha/kari on one side and sushi on the other need a
  UNIFORM role-based abstraction that neither existing mechanism
  provides for all 5 Basket V1 use cases at once. This module supplies
  that uniform layer, built entirely on primitives that already exist:
  app.cross_sell.roles_for_recipe()/roles_for_use_case() for the
  REQUIRED ROLE LIST (V2.6, already taxonomy-grounded, already used
  in production for cross-sell), and app.taxonomy's product_taxonomy_index
  (concept_id-exact match) for CANDIDATE GENERATION - the same
  underlying index app.use_case_advice.generate_candidates() already
  filters, just keyed on the FamilyRule.rule_id (concept_id) directly
  instead of a per-role RoleEvidence object, since every role here
  already comes with a real, resolved concept_id (no lexical_filter
  workaround needed - Section 46, no new taxonomy invented here).

RAMEN EXCLUSION (Section 5, updated V2.14h): V2.14h made "ramen" live in
app.use_case_advice.LIVE_USE_CASES (re-audited, not carried over by
assumption - see that module's docstring), but ramen's basket behavior
is INTENTIONALLY NOT changed here - basket readiness is an independent
dimension from use-case readiness (V2.14h Section 20). This surfaced a
real latent defect: BASKET_V1_ELIGIBLE_USE_CASES used to be defined as
`tuple(LIVE_USE_CASES)`, a bare live mirror that would have silently
granted ramen basket eligibility the moment it became a live use case,
contradicting this very docstring's original claim of "two independent
structural gates". Fixed by making BASKET_V1_ELIGIBLE_USE_CASES an
explicit, hand-authored tuple that does not derive from LIVE_USE_CASES
at all - a future LIVE_USE_CASES addition (or ramen's own basket
readiness, decided on its own evidence) requires a deliberate edit here,
not a side effect of that other module's registry.

NO LLM anywhere in resolution/decision - identical safety posture to
app.use_case_advice (V2.14c) and app.comparison (V2.14b). No new
recommendation-confidence system (Section 12): reuses
app.recommendation_evidence's EvidenceItem/compute_confidence exactly
as app.use_case_advice does.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.recommendation_evidence import (
    PROVENANCE_DATA_DERIVED,
    EvidenceItem,
    compute_confidence,
)
from app.use_case_advice import is_companion_request, resolve_use_case

# Section 4 - explicit registry, deliberately NOT derived from
# app.use_case_advice.LIVE_USE_CASES (V2.14h: a bare tuple(LIVE_USE_CASES)
# alias here previously would have silently granted ramen basket
# eligibility the moment V2.14h made it a live use case - see this
# module's docstring). Basket readiness is decided per use case on its
# own evidence (a real role list backed by app.cross_sell), not
# inherited from use-case-advice readiness.
BASKET_V1_ELIGIBLE_USE_CASES = ("sushi", "pho", "pad_thai", "tom_kha", "kari")

# app.use_case_advice's canonical use_case name -> app.main.RECIPE_SHOPPING_CORE_QUERIES
# dish key. "kari" (not "thajske_kari") is the representative: it is the
# generic, colour-less ingredient list ("kari pasta", not "cervena kari
# pasta"), matching the canonical use_case's own colour-agnostic scope
# (app.use_case_advice already collapses "thajske kari"/"thai curry" into
# "kari" for the same reason - see its module docstring).
_USE_CASE_TO_RECIPE_DISH_KEY = {
    "pho": "pho",
    "pad_thai": "pad_thai",
    "tom_kha": "tom_kha",
    "kari": "kari",
}

# Section 20 - a DELIBERATELY NARROWER subset of app.main.wants_recipe_products()'s
# marker set, not a full reuse. A real regression found via the full
# V2.10 evaluation run (not hypothetical): "ramen na Pho polievku mate
# ingrediencie?" (permanent golden case regbug_rt0026, expects
# related_products) matches wants_recipe_products() via its broad bare
# "ingredien" marker, which is safe for the EXISTING recipe flow (gated
# separately by is_recipe_intent()/recipe_subject, Section 15 - not
# touched here) but is NOT specific enough evidence, on its own, for
# THIS module's stronger claim ("here is your full basket for X") -
# app.use_case_advice.resolve_role() also correctly returns None for
# that exact message (no specific role named), confirming the message
# itself is genuinely ambiguous, not merely under-triggering. Basket
# completion therefore requires one of the unambiguous, explicit
# "give me the full list" phrasings only - "ingredien"/"surovin"/
# "produkt"/"kupit"/"nakup"/"k receptu" remain valid triggers for the
# separate, pre-existing recipe flow, just not for this module.
#
# Deliberately EXCLUDES "nakupny zoznam"/"do kosika" - a second real
# regression found via the full pytest suite: "nakupny zoznam na sushi"
# already has an existing, content-validated legacy path
# (sushi_shopping_core_products() + shopping_list_for_response(), see
# tests/test_core.py::test_sushi_shopping_list_uses_buyable_core_items_not_water)
# that this module must not shadow - its response shape
# ("shopping_list": {"available_on_foodland", "missing_ingredients"})
# is different from and not a superset of this module's role-based
# shape. Customers still reach this module's richer sushi basket via
# "co potrebujem na sushi" (Section 20's own primary example).
_BASKET_ACTION_MARKERS = (
    "co potrebujem", "co treba", "co mi chyba", "co chyba",
    "co este potrebujem", "co este treba", "co este chyba",
    # "dopln" (matching "doplň"/"doplniť"/"doplňte"/"dopĺň") for the
    # "doplň mi [veci] na X" phrasing named explicitly in the V2.14e
    # spec. Deliberately NOT "doplnky" (plural noun) - that already
    # means something else (a companion/cross-sell request,
    # app.use_case_advice's _COMPANION_REQUEST_MARKERS) and is excluded
    # before this check ever runs (is_companion_request() guard below).
    "dopln",
)


def _wants_basket_completion(message: str) -> bool:
    from app.search import normalize

    normalized = normalize(message)
    return any(marker in normalized for marker in _BASKET_ACTION_MARKERS)


# --- role status vocabulary (Section 8) -------------------------------------
STATUS_RESOLVED_PRODUCT = "RESOLVED_PRODUCT"
STATUS_ALREADY_COVERED = "ALREADY_COVERED"
STATUS_NO_CATALOG_PRODUCT = "NO_CATALOG_PRODUCT"
STATUS_AMBIGUOUS = "AMBIGUOUS"  # defined for completeness (Section 8); not
# reached in V1 - every required role's candidates are deterministically
# ordered (HIGH confidence first, then price), so a role either resolves
# to a top pick or has zero candidates. Kept as a real status (not
# removed) so a future stricter comparison gate can populate it without
# a schema change, exactly like app.use_case_advice's own CLARIFY state.


@dataclass(frozen=True, slots=True)
class BasketRole:
    concept_id: str
    display_label_sk: str
    status: str
    recommended_product_id: str | None = None
    alternative_product_ids: tuple[str, ...] = ()
    confidence: str = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class BasketDecision:
    use_case: str
    roles: tuple[BasketRole, ...]
    unresolved_concepts: tuple[str, ...]  # known recipe concepts with NO taxonomy role at all (Section 30) - raw text, not a role (no concept_id exists for these)
    coverage: float
    fully_resolved: bool  # Section 27 - True only when every required role is RESOLVED_PRODUCT/ALREADY_COVERED AND unresolved_concepts is empty


def required_roles_for_use_case(use_case: str) -> list[str]:
    """Section 7/14 - the required-role LIST comes entirely from
    app.cross_sell, already taxonomy-grounded and already used in
    production (roles_for_recipe for the 4 recipe_graph-registered
    dishes, roles_for_use_case for sushi, which has no recipe_graph
    entry). No new role table, no new detector."""
    from app.cross_sell import roles_for_recipe, roles_for_use_case

    if use_case == "sushi":
        return roles_for_use_case("sushi")
    dish_key = _USE_CASE_TO_RECIPE_DISH_KEY.get(use_case)
    if dish_key is None:
        return []
    return roles_for_recipe(dish_key)


def known_unresolved_concepts(use_case: str) -> list[str]:
    """Section 30 - re-derived live against HEAD every call (not a
    hardcoded snapshot): for dishes with a RECIPE_SHOPPING_CORE_QUERIES
    entry, the raw ingredient phrases that do NOT resolve to any
    taxonomy concept at all (genuine NO_TAXONOMY_MATCH gaps, e.g.
    "galangal", "palmovy cukor" - see docs/use-case-recipe-data-quality-v2.14d.md
    Section 9). Returns raw customer-facing text, since these have no
    concept_id to key a BasketRole on. sushi has no raw ingredient list
    to diff against (no recipe_graph entry) - honestly returns [] rather
    than implying completeness."""
    from app.main import RECIPE_SHOPPING_CORE_QUERIES
    from app.query_constraints import parse_structured_query

    dish_key = _USE_CASE_TO_RECIPE_DISH_KEY.get(use_case)
    if dish_key is None:
        return []
    unresolved = []
    for query_text, _required, _excluded in RECIPE_SHOPPING_CORE_QUERIES.get(dish_key, []):
        resolved = parse_structured_query(query_text, known_brands=())
        if not resolved.concept_id:
            unresolved.append(query_text)
    return unresolved


def _display_label_for_concept(concept_id: str) -> str:
    from app.taxonomy import FAMILY_DEFINITIONS_BY_ID

    rule = FAMILY_DEFINITIONS_BY_ID.get(concept_id)
    return rule.display_label if rule else concept_id


def generate_role_candidates(concept_id: str, products: list, product_taxonomy_index: dict, limit: int = 8) -> list:
    """Section 7/21/46 - filters the EXISTING product_taxonomy_index by
    exact concept_id (FamilyRule.rule_id) equality, HIGH/MEDIUM
    confidence only (Section 29, same UNKNOWN-taxonomy policy as
    app.use_case_advice.generate_candidates()). No parallel retrieval
    engine, no new taxonomy rule, no per-role special-casing - concept_id
    equality is more precise than family/subfamily matching and needs no
    lexical_filter workaround for concepts like jasmine_rice."""
    from app.taxonomy import get_taxonomy

    matches = []
    for product in products:
        taxonomy = get_taxonomy(product_taxonomy_index, product.id)
        if taxonomy is None or taxonomy.confidence not in ("HIGH", "MEDIUM"):
            continue
        if taxonomy.concept_id != concept_id:
            continue
        matches.append((taxonomy.confidence, product))

    matches.sort(key=lambda pair: (pair[0] != "HIGH", pair[1].effective_price if pair[1].effective_price is not None else 1e9))
    return [product for _confidence, product in matches[:limit]]


def _self_declared_concept_ids(message: str, required_concept_ids: list[str]) -> set[str]:
    """Section 16 - 'mam ryzove rezance, co este potrebujem na pad thai?'
    (self-declared inventory in the SAME turn). Reuses the exact
    parse_structured_query() mechanism app.cross_sell already trusts for
    ingredient-phrase resolution (V2.14d fixed its 'banh pho'/bare 'kari
    pasta' gaps) - narrow and exact (only counts a role as covered when
    the message's own text resolves to that EXACT concept_id), never a
    fuzzy/partial match.

    V2.16d - parse_structured_query() on the WHOLE message returns at
    most one concept_id, so a genuine multi-item declaration ("Mam
    ryzove rezance A rybaciu omacku...") only ever credited the first
    item - reproduced live during characterization. Splitting on
    sentence punctuation and the conjunction " a " ("and") and parsing
    each segment separately is a strict improvement (can only ADD
    matches the single-call version already found) and needs no new
    resolver - the existing single-item test
    (tests/test_basket_completion_v2_14e.py::TestCaseG_AlreadyCoveredRole)
    is still satisfied since its message parses identically as its own
    lone segment. Still limited by parse_structured_query()'s own
    nominative-leaning case coverage (a real, separate, pre-existing
    data/architecture limitation of that shared primitive, e.g.
    accusative "rybaciu omacku" does not resolve where nominative
    "rybacia omacka" does) - documented as data debt, not fixed here
    (Section 87 - no broad search/parsing redesign in this sprint)."""
    from app.query_constraints import parse_structured_query

    found: set[str] = set()
    segments = re.split(r"[.,;]| a ", message)
    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        resolved = parse_structured_query(segment, known_brands=())
        if resolved.concept_id and resolved.concept_id in required_concept_ids:
            found.add(resolved.concept_id)
    return found


def decide_basket_completion(
    message: str,
    products: list,
    product_taxonomy_index: dict,
    memory: dict | None = None,
    *,
    recipe_subject: str | None = None,
    limit_per_role: int = 5,
) -> BasketDecision | None:
    """Returns None when the message does not name one of
    BASKET_V1_ELIGIBLE_USE_CASES at all, is actually a companion-products
    request (Section 30 of V2.14c, rt0004 protection - reused verbatim),
    the caller has already resolved a recipe_subject for this turn
    (Section 5/15 - pad_thai/tom_kha's EXISTING, live
    app.recipe_shopping.build_recipe_shopping_plan() path stays
    completely untouched and takes precedence; this module only covers
    the goal-oriented-shopping gap for sushi/pho/kari, which have no
    bare RECIPE_INTENT_MARKERS entry and so never set recipe_subject for
    this phrasing), or when the message does not read as a
    basket/shopping-list request at all (Section 20/21 - ACTION signal,
    reused from app.main.wants_recipe_products()).

    Same fall-through contract as execute_recipe()/execute_comparison()/
    execute_use_case_advice(): the caller defers to the normal cascade on
    None (never a customer-visible error)."""
    if recipe_subject:
        return None
    if is_companion_request(message):
        return None

    use_case = resolve_use_case(message)
    if use_case is None or use_case not in BASKET_V1_ELIGIBLE_USE_CASES:
        return None

    if not _wants_basket_completion(message):
        return None

    return _build_basket_decision(use_case, message, products, product_taxonomy_index, memory, limit_per_role)


def _build_basket_decision(
    use_case: str,
    message: str,
    products: list,
    product_taxonomy_index: dict,
    memory: dict | None,
    limit_per_role: int,
) -> BasketDecision | None:
    """V2.16d - the role-resolution body shared by decide_basket_completion()
    (fresh turn, use_case named+detected this turn) and
    resolve_basket_followup() (continuation turn, use_case comes from
    session state instead) - the two differ only in HOW use_case/gating
    is determined, never in how a decision is built from one."""
    required_concept_ids = required_roles_for_use_case(use_case)
    if not required_concept_ids:
        return None

    selected_ingredient_products: dict[str, str] = {}
    if memory is not None:
        from app.session_state import get_selected_ingredient_products

        selected_ingredient_products = get_selected_ingredient_products(memory)

    self_declared = _self_declared_concept_ids(message, required_concept_ids)

    roles: list[BasketRole] = []
    for concept_id in required_concept_ids:
        display_label = _display_label_for_concept(concept_id)

        already_covered_product_id = selected_ingredient_products.get(concept_id)
        if already_covered_product_id or concept_id in self_declared:
            candidates_for_label = generate_role_candidates(concept_id, products, product_taxonomy_index, limit=1)
            fallback_id = candidates_for_label[0].id if candidates_for_label else None
            roles.append(BasketRole(
                concept_id=concept_id, display_label_sk=display_label, status=STATUS_ALREADY_COVERED,
                recommended_product_id=already_covered_product_id or fallback_id,
            ))
            continue

        candidates = generate_role_candidates(concept_id, products, product_taxonomy_index, limit=limit_per_role)
        if not candidates:
            roles.append(BasketRole(
                concept_id=concept_id, display_label_sk=display_label, status=STATUS_NO_CATALOG_PRODUCT,
            ))
            continue

        top, *rest = candidates
        # Section 35 grounded "why": product_type_fit, same reason_code
        # vocabulary app.use_case_advice already uses for this exact
        # taxonomy-family-match evidence shape.
        roles.append(BasketRole(
            concept_id=concept_id, display_label_sk=display_label, status=STATUS_RESOLVED_PRODUCT,
            recommended_product_id=top.id, alternative_product_ids=tuple(p.id for p in rest),
            confidence=compute_confidence([EvidenceItem("product_type_fit", PROVENANCE_DATA_DERIVED, "app.taxonomy", 0.7)]),
        ))

    unresolved = known_unresolved_concepts(use_case)

    satisfied = sum(1 for r in roles if r.status in (STATUS_RESOLVED_PRODUCT, STATUS_ALREADY_COVERED))
    total_required = len(roles) or 1
    coverage = satisfied / total_required
    fully_resolved = satisfied == len(roles) and not unresolved

    return BasketDecision(
        use_case=use_case, roles=tuple(roles), unresolved_concepts=tuple(unresolved),
        coverage=coverage, fully_resolved=fully_resolved,
    )


def resolve_basket_followup(
    message: str,
    products: list,
    product_taxonomy_index: dict,
    memory: dict,
    *,
    recipe_subject: str | None = None,
    limit_per_role: int = 5,
) -> BasketDecision | None:
    """V2.16d (Section 30 - core target) - a bare continuation of the
    LAST successful basket_completion answer this session
    ("co este potrebujem?", "dopln mi...") rebuilds the same basket
    from session state instead of falling through to a generic "I
    don't understand" answer, which was the confirmed live behavior
    before this function existed (decide_basket_completion() alone has
    no session memory of its own - every follow-up after its first
    answer previously fell straight through).

    Returns None (caller falls through to the normal cascade unchanged,
    same fall-through contract as every other executor here) when:
    - no basket use case is active for this session at all;
    - the caller already resolved recipe_subject this turn (pad_thai/
      tom_kha's own, separate continuity owns that path - Section 5);
    - the message is a companion-products request (rt0004 protection,
      reused verbatim);
    - the message explicitly names a DIFFERENT use case than the active
      one - a real hard switch (Section 39), not a continuation; the
      caller's normal cascade (including a fresh decide_basket_completion()
      call for the newly named use case) handles it from here;
    - the message does not carry explicit basket-continuation action
      language at all. A real regression was found and reverted here
      during V2.16d testing: an earlier version of this function ALSO
      treated a bare self-declared item alone (no action language) as a
      continuation trigger, which reinterpreted an ordinary subsequent
      product search ("sushi ryza", right after an earlier "co
      potrebujem na sushi") as a basket self-declaration instead of a
      new product_search/cross_sell turn, breaking
      tests/test_decision_observability_expansion_v2_15e_3.py's
      cross_sell characterization. Self-declaration alone, without an
      explicit basket-action phrase, is intentionally left as a
      documented gap (Section 31 - "do not guess" - not implemented
      this sprint) rather than risk that class of false positive."""
    from app.session_state import get_active_basket_use_case

    active_use_case = get_active_basket_use_case(memory)
    if not active_use_case:
        return None
    if recipe_subject:
        return None
    if is_companion_request(message):
        return None

    named_use_case = resolve_use_case(message)
    if named_use_case and named_use_case != active_use_case:
        return None

    if not _wants_basket_completion(message):
        return None

    return _build_basket_decision(active_use_case, message, products, product_taxonomy_index, memory, limit_per_role)


# --- deterministic answer composition (no LLM, mirrors app.use_case_advice) -

_USE_CASE_LABELS_SK = {
    "sushi": "sushi", "pho": "pho", "pad_thai": "Pad Thai", "tom_kha": "Tom Kha", "kari": "kari/curry",
}


def compose_basket_answer(decision: BasketDecision, products_by_id: dict, query_language: str = "sk") -> str:
    """Section 26/27 - never claims a 'complete basket' unless every
    required role is safely resolved AND no known concept gap exists.
    Customer-facing language only, never internal enum names (Section 26)."""
    is_en = query_language == "en"
    use_case_label = _USE_CASE_LABELS_SK.get(decision.use_case, decision.use_case)

    covered_labels = [r.display_label_sk for r in decision.roles if r.status == STATUS_ALREADY_COVERED]
    missing_labels = [r.display_label_sk for r in decision.roles if r.status == STATUS_NO_CATALOG_PRODUCT]

    if is_en:
        parts = []
        if decision.fully_resolved:
            parts.append(f"Here is everything you need for {use_case_label}:")
        else:
            parts.append(f"From what's available, here is what I can put together for {use_case_label}:")
        if covered_labels:
            parts.append("Already covered: " + ", ".join(covered_labels) + ".")
        if missing_labels or decision.unresolved_concepts:
            gap_labels = missing_labels + list(decision.unresolved_concepts)
            parts.append("I could not safely match a product for: " + ", ".join(gap_labels) + ".")
        return " ".join(parts)

    parts = []
    if decision.fully_resolved:
        parts.append(f"Na {use_case_label} ti viem spoľahlivo doplniť všetko potrebné:")
    else:
        parts.append(f"Z dostupných produktov som pre {use_case_label} doplnila toto:")
    if covered_labels:
        parts.append("Už máte pokryté: " + ", ".join(covered_labels) + ".")
    if missing_labels or decision.unresolved_concepts:
        gap_labels = missing_labels + list(decision.unresolved_concepts)
        parts.append("Pre tieto položky zatiaľ nemám dostatočne spoľahlivé produktové priradenie: " + ", ".join(gap_labels) + ".")
    return " ".join(parts)
