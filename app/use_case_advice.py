"""
app/use_case_advice.py  -  V2.14c Evidence-Grounded Use-Case Intelligence.

Answers questions of the shape "[product type] na [culinary use case]"
("rybacia omacka na pho", "ryza na sushi", "aku kari pastu na thajske
kari") with an evidence-grounded product-family recommendation, built
directly on app.recommendation_evidence (V2.14a) and following the
same "no LLM in the decision/composition path" safety design as
app.comparison (V2.14b).

CUSTOMER REACHABILITY vs. EVIDENCE VALIDITY - a real, confirmed finding
(not a design choice): "pad_thai" and "tom_kha" have real, tested,
correct role tables below, but are PRACTICALLY UNREACHABLE from a real
customer message today - app.main.RECIPE_INTENT_MARKERS hardcodes the
literal strings "tom kha" and "pad thai" as automatic recipe-intent
triggers (a pre-existing V2.9-era design predating this sprint), so
app.main.detect_recipe_subject() resolves a truthy recipe_subject for
ANY message containing those two dish names, and this module's
recipe_subject guard (Section 35: never compete with the protected
recipe flow) then correctly defers every single time. "sushi", "pho",
and "kari" have no such collision and ARE reachable. This is not a bug
in this module - fixing it would mean changing RECIPE_INTENT_MARKERS/
recipe-intent precedence, which Section 6/35 of the V2.14c spec
explicitly forbids reopening in this sprint. Documented honestly in
docs/use-case-intelligence-v2.14c.md as SHADOW_ONLY for these two,
not LIVE, despite equally strong underlying evidence.

WHY A NEW MODULE (Section 39 of the V2.14c spec: "New module/class is
justified only when ownership is genuinely missing"): none of the
existing primitives own this responsibility.
- app.cross_sell answers "what else completes this" (companion/
  completion), not "which product family is correct for this use
  case" - and its USE_CASE_COMPLETION mechanism is wired for exactly
  ONE value ("sushi") via a single hardcoded taxonomy attribute
  (app/taxonomy.py, FamilyRule "sushi_rice"), not a general use-case
  resolver.
- app.recipe_graph's RECIPE_SHOPPING_CORE_QUERIES/resolve_ingredient_products()
  answers "give me a full shopping list for dish X" - it has no
  standalone "just this one product type for this one use case"
  query shape, and (audited directly) its own ingredient-role text
  frequently fails to resolve through app.cross_sell's stricter
  taxonomy-only path (see the per-role table below - several
  RECIPE_CURATED-sourced roles are deliberately excluded here for
  exactly this reason).
- app.comparison answers "which of these two ALREADY-RESOLVED products
  is better", not "what family of product fits this use case at all".

DATA REALITY (audited directly against app.taxonomy/app.recipe_graph
and the real 2140-product catalog before writing this table - see
docs/use-case-intelligence-v2.14c.md for the full per-use-case audit).
Every row below is a real, live-verified (family, subfamily, confidence)
triple, not an assumption:

- Only ONE use case (sushi) has a clean, unambiguous, taxonomy-native
  central product family (rice/sushi_rice, HIGH confidence, 12 products).
- pho, pad_thai, tom_kha, and kari/thajske_kari each have SOME real,
  clean, taxonomy-backed roles (fish_sauce, rice_noodles, coconut_milk,
  curry_paste, hoisin_sauce, chili_sauce, tamarind_pasta) - these are
  included below.
- ramen was added in V2.14h, re-auditing this original V2.14c
  exclusion rather than assuming it still holds. The original blocker
  (bowls/kitchenware polluting instant_noodles) was independently fixed
  in V2.14d (a dedicated "tableware" FamilyRule now intercepts those 268
  products before instant_noodles ever sees them; the family is 79
  products, 76 HIGH/3 MEDIUM, live-verified against current HEAD). The
  deeper "instant packet vs. dry noodles for a homemade broth" ambiguity
  also does not hold at the taxonomy level: dry/fresh ramen-style wheat
  noodles (e.g. HAKUBAKU, MISTER MIE, GOLDEN TURTLE, AYUKO) live in the
  separate "wheat_noodles" family (32 products, HIGH), not
  instant_noodles - the two are already cleanly split by the taxonomy,
  not conflated. This module only claims the instant_noodles role
  (matching the "ramen rezance" ingredient text already used by
  app.main.RECIPE_SHOPPING_CORE_QUERIES["ramen"], reused for
  consistency, not redefined); a separate "dry ramen noodle" role
  carved out of wheat_noodles is NOT added here (would require a new
  title-substring concept and its own blast-radius review - left as a
  documented, evidence-backed future enhancement, not guessed at).
  ramen also gets miso, soy_sauce, and wakame roles - the same three
  reused, unmodified concept_ids app.cross_sell.roles_for_recipe("ramen")
  has resolved since V2.8/V2.14c. soy_sauce is 100% MEDIUM confidence
  catalog-wide (51 products, verified: not a variety-shadowing artifact
  like curry_paste - every soy_sauce/dark_soy_sauce/light_soy_sauce
  product is MEDIUM, a real structural ceiling from thin category-path
  evidence in the feed, not a bug) - MEDIUM is an already-accepted
  confidence tier for this module (see UNKNOWN TAXONOMY POLICY below),
  so this does not block inclusion. miso (4 products) and wakame (5
  products) are thin stock, entirely MEDIUM - included per the same
  policy, expected to legitimately ABSTAIN/return few candidates rather
  than fabricate a false "well-stocked" impression.
  dashi is DELIBERATELY EXCLUDED, for a different reason than the
  original ramen exclusion: 3 real catalog SKUs exist (SHIMAYA Dashi
  Bonito Stock, Dashinomoto bonito powder, PAKU PAKU dashima kelp) but
  all three are taxonomically UNKNOWN (no FamilyRule/concept_id claims
  them) - real data, zero structured evidence. Authoring a "dashi"
  FamilyRule is a real taxonomy change requiring its own blast-radius
  review and is explicitly out of scope for this sprint; guessing a
  dashi role from UNKNOWN-confidence products would violate this
  module's own confidence gate. Documented as a specific, actionable
  DATA_REQUIRED backlog item, not vague TODO debt.
- Aromatics with real but extremely thin stock (galangal: 1 SKU
  catalog-wide; kaffir lime leaves: 3; lemongrass: 4) are excluded from
  tom_kha's role table for this sprint - not because the evidence is
  wrong, but because a single-SKU "recommendation" is one stock-out
  away from being false, and Section 87 requires honest ABSTAIN/no-
  match behavior over a technically-true-today claim that expires
  silently. Documented as a data-enrichment backlog item.
- The "jasmine rice" role (kari/thajske_kari) has NO dedicated taxonomy
  subfamily - jasmine rice products land in the broad "plain_rice"
  subfamily (66 products, only 15 of which are actually jasmine) -
  so this role requires an additional lexical narrowing (title
  contains "jazmin") on top of the family match, making it INFERRED
  rather than DATA_DERIVED (Section 16: "INFERRED - derived
  deterministically from validated mappings", here two signals
  combined, not one raw structured field).

CONFLICT HANDLING (Section 19): if the customer's own message negates
the exact family/role this module would otherwise recommend ("nie
sushi ryzu", "bez kokosoveho mlieka"), this module returns None
(defers to the normal cascade) rather than recommending the very thing
the customer explicitly excluded. It does not attempt to fix what the
normal cascade then does with that exclusion - that pipeline is
V2.13's accepted, unmodified legacy commerce dispatch (Section 6 - do
not reopen).

UNKNOWN TAXONOMY POLICY (Section 20): candidate generation filters to
confidence in {HIGH, MEDIUM} only - UNKNOWN and LOW confidence
products are never used as the sole basis for a use-case claim, though
LOW-confidence candidates are also excluded from presentation (not
just evidence) to avoid presenting a doubly-uncertain product list.

NO LLM ANYWHERE in resolution, evidence, decision, or composition -
identical safety posture to app.comparison (V2.14b).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.recommendation_evidence import (
    CONFIDENCE_HIGH,
    PROVENANCE_DATA_DERIVED,
    PROVENANCE_INFERRED,
    EvidenceItem,
    compute_confidence,
    decide,
)

# --- canonical use cases exposed to customers this sprint -------------------
# ramen added in V2.14h - re-audited, not carried over by assumption; see
# module docstring for the full evidence trail.
LIVE_USE_CASES = ("sushi", "pho", "pad_thai", "tom_kha", "kari", "ramen")

# alias (normalized) -> canonical_use_case. "thajske_kari"/"thai curry"
# collapse into "kari" - the taxonomy has no real red/green/panang
# subfamily distinction (all 31 curry_paste products share
# canonical_subfamily=None), so treating them as one canonical use case
# with an optional lexical variety narrowing is the honest scope.
_USE_CASE_ALIASES: dict[str, str] = {
    "sushi": "sushi", "susi": "sushi",
    "pho": "pho", "pho bo": "pho", "pho ga": "pho",
    "pad thai": "pad_thai", "padthai": "pad_thai", "pad-thai": "pad_thai", "pad tai": "pad_thai",
    "tom kha": "tom_kha", "tom kha gai": "tom_kha",
    "kari": "kari", "curry": "kari", "thajske kari": "kari", "thajske curry": "kari",
    "thajsky curry": "kari", "thai curry": "kari",
    "ramen": "ramen",
}

_NEGATION_MARKERS = ("nie ", "nechcem ", "bez ", "okrem ")

# Section 30 of the V2.14c spec, protecting rt0004: "súvisiace produkty
# k sushi ryži" is a RELATED_PRODUCTS (companion-item) request, not a
# "which product type should I use" request - a real regression found
# during implementation (the full test suite's rt0004 control broke on
# first wiring: this branch ran before the commerce cascade's own
# RELATED_PRODUCTS resolution ever got a chance to fire, and a bare
# "sushi ryzi" substring matched this module's sushi/rice role). These
# two markers are the same ones RECIPE_SHOPPING_LANGUAGE_MARKERS
# (app/main.py) already recognizes as unambiguous companion-request
# language - reused here narrowly, not the full broader marker set
# (which also includes "odporuc"/"hodi"/"pasuje", too general-purpose
# to safely exclude without also blocking this module's own core
# queries).
_COMPANION_REQUEST_MARKERS = ("suvisiace", "doplnky")


@dataclass(frozen=True, slots=True)
class RoleEvidence:
    use_case: str
    role: str
    reason_code: str
    canonical_family: str
    canonical_subfamily: str | None  # None means "match family only"
    provenance: str
    strength: float
    role_markers: tuple[str, ...]
    lexical_filter: str | None = None  # extra required title substring, for INFERRED narrowing
    display_label_sk: str = ""


_ROLE_TABLE: dict[str, tuple[RoleEvidence, ...]] = {
    "sushi": (
        RoleEvidence("sushi", "rice", "product_type_fit", "rice", "sushi_rice",
                     PROVENANCE_DATA_DERIVED, 0.9, ("ryza", "ryzu", "ryzi", "ryzou", "ryze"),
                     display_label_sk="sushi ryža"),
    ),
    "pho": (
        RoleEvidence("pho", "noodles", "product_type_fit", "noodles", "rice_noodles",
                     PROVENANCE_DATA_DERIVED, 0.8, ("rezance", "rezancov", "nudle", "nudlov"),
                     display_label_sk="ryžové rezance"),
        RoleEvidence("pho", "sauce_fish", "product_type_fit", "sauce", "fish_sauce",
                     PROVENANCE_DATA_DERIVED, 0.6, ("rybacia omacka", "rybaciu omacku", "omacku", "omacka"),
                     display_label_sk="rybacia omáčka"),
        RoleEvidence("pho", "sauce_hoisin", "product_type_fit", "sauce", "hoisin_sauce",
                     PROVENANCE_DATA_DERIVED, 0.6, ("hoisin",),
                     display_label_sk="hoisin omáčka"),
        RoleEvidence("pho", "sauce_chili", "product_type_fit", "sauce", "chili_sauce",
                     PROVENANCE_DATA_DERIVED, 0.6, ("sriracha",),
                     display_label_sk="sriracha čili omáčka"),
    ),
    "pad_thai": (
        RoleEvidence("pad_thai", "noodles", "product_type_fit", "noodles", "rice_noodles",
                     PROVENANCE_DATA_DERIVED, 0.8, ("rezance", "rezancov"),
                     display_label_sk="ryžové rezance"),
        RoleEvidence("pad_thai", "paste_tamarind", "product_type_fit", "paste", "tamarind_pasta",
                     PROVENANCE_DATA_DERIVED, 0.55, ("tamarind",),
                     display_label_sk="tamarindová pasta"),
        RoleEvidence("pad_thai", "sauce_fish", "product_type_fit", "sauce", "fish_sauce",
                     PROVENANCE_DATA_DERIVED, 0.6, ("rybacia omacka", "rybaciu omacku", "omacku", "omacka"),
                     display_label_sk="rybacia omáčka"),
    ),
    "tom_kha": (
        RoleEvidence("tom_kha", "base_coconut", "product_type_fit", "coconut_product", "coconut_milk",
                     PROVENANCE_DATA_DERIVED, 0.85, ("kokosove mlieko", "kokosoveho mlieka", "mlieko"),
                     display_label_sk="kokosové mlieko"),
        RoleEvidence("tom_kha", "sauce_fish", "product_type_fit", "sauce", "fish_sauce",
                     PROVENANCE_DATA_DERIVED, 0.6, ("rybacia omacka", "rybaciu omacku", "omacku", "omacka"),
                     display_label_sk="rybacia omáčka"),
    ),
    "kari": (
        RoleEvidence("kari", "paste_curry", "product_type_fit", "curry_paste", None,
                     PROVENANCE_DATA_DERIVED, 0.55, ("kari pasta", "curry pasta", "kari pastu", "curry pastu", "pasta"),
                     display_label_sk="kari pasta"),
        RoleEvidence("kari", "base_coconut", "product_type_fit", "coconut_product", "coconut_milk",
                     PROVENANCE_DATA_DERIVED, 0.85, ("kokosove mlieko", "kokosoveho mlieka", "mlieko"),
                     display_label_sk="kokosové mlieko"),
        RoleEvidence("kari", "rice_jasmine", "use_case_fit", "rice", "plain_rice",
                     PROVENANCE_INFERRED, 0.6, ("jazminova ryza", "jazminovu ryzu", "jazminova"),
                     lexical_filter="jazmin", display_label_sk="jazmínová ryža"),
        RoleEvidence("kari", "sauce_fish", "product_type_fit", "sauce", "fish_sauce",
                     PROVENANCE_DATA_DERIVED, 0.6, ("rybacia omacka", "rybaciu omacku", "omacku", "omacka"),
                     display_label_sk="rybacia omáčka"),
    ),
    "ramen": (
        RoleEvidence("ramen", "noodles", "product_type_fit", "instant_food", "instant_noodles",
                     PROVENANCE_DATA_DERIVED, 0.8, ("rezance", "rezancov", "nudle", "nudlov"),
                     display_label_sk="ramen rezance"),
        RoleEvidence("ramen", "paste_miso", "product_type_fit", "paste", "miso",
                     PROVENANCE_DATA_DERIVED, 0.55, ("miso", "miso pasta", "miso pastu"),
                     display_label_sk="miso pasta"),
        RoleEvidence("ramen", "sauce_soy", "product_type_fit", "sauce", "soy_sauce",
                     PROVENANCE_DATA_DERIVED, 0.6, ("sojova omacka", "sojovu omacku", "omacku", "omacka"),
                     display_label_sk="sójová omáčka"),
        RoleEvidence("ramen", "topping_wakame", "product_type_fit", "seaweed", "wakame",
                     PROVENANCE_DATA_DERIVED, 0.5, ("wakame",),
                     display_label_sk="wakame riasy"),
    ),
}


@dataclass(frozen=True, slots=True)
class UseCaseDecision:
    state: str  # "RECOMMEND" | "CLARIFY" | "ABSTAIN"
    use_case: str | None
    role: str | None
    confidence: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    candidate_product_ids: list[str] = field(default_factory=list)
    display_label_sk: str = ""
    reason: str = ""


_USE_CASE_FRAMING_PREPOSITIONS = (" na ", " pre ")


def _padded_for_boundary_match(message: str) -> str:
    """V2.14f - real defect found via characterization (not hypothetical):
    resolve_use_case()/resolve_role() require their target phrase to be
    followed by a literal space (word-boundary-by-space, not by regex),
    so "...na pho?" or "...na sushi, ktoru..." silently failed to
    resolve at all - the alias/marker is followed by punctuation, not a
    space, in extremely common natural questions ("Ktora rybacia
    omacka je najlepsia na pho?"). Fixed generically here (not by
    special-casing "?"/","): common sentence punctuation is replaced
    with spaces before the existing wrapped-space boundary check runs,
    for every current and future alias/marker, not just these two
    examples."""
    from app.search import normalize

    normalized = normalize(message)
    for char in "?!.,;:":
        normalized = normalized.replace(char, " ")
    return f" {normalized} "


def resolve_use_case(message: str) -> str | None:
    """Deterministic alias lookup - no LLM, no fuzzy matching.

    REQUIRES an explicit "for this use case" framing preposition
    (" na "/" pre ") immediately before the use-case alias - a real
    regression found during full-suite evaluation (not hypothetical):
    without this requirement, a bare PRODUCT NAME query like "červená
    kari pasta" ("red curry paste" - the customer is naming a specific
    product, not asking what to use for a use case) matched the "kari"
    alias anywhere in the message and broke the permanent
    curry_red_001 golden regression case, which expects that query to
    resolve to the specific red_curry_paste concept via the normal
    structured-search path, not this module's broader generic
    curry_paste family. Every one of this module's own target queries
    ("ryza na sushi", "rybacia omacka na pho", "kari pasta na thajske
    kari") already naturally has this preposition, so requiring it
    costs nothing for the intended use case."""
    normalized = _padded_for_boundary_match(message)
    best: str | None = None
    best_len = 0
    for alias, canonical in _USE_CASE_ALIASES.items():
        for preposition in _USE_CASE_FRAMING_PREPOSITIONS:
            if f"{preposition}{alias} " in normalized and len(alias) > best_len:
                best = canonical
                best_len = len(alias)
    return best


def resolve_role(use_case: str, message: str) -> RoleEvidence | None:
    """Among the given use case's known roles, find the one whose
    lexical markers appear in the message. Returns None (-> CLARIFY at
    the caller) when the use case is named but no specific role can be
    identified - Section 18/86: do not guess which ingredient/role the
    customer means.

    Deliberately does NOT use _padded_for_boundary_match() (unlike
    resolve_use_case() above) - a real regression found via the full
    V2.10/pytest run during V2.14f (not hypothetical): normalizing a
    mid-sentence comma to a space let a role marker immediately before
    an unrelated clause ("mam ryzove rezance, co este potrebujem na
    pho?") match across what is semantically a CLAUSE BOUNDARY,
    hijacking a genuine app.basket_completion self-declaration turn
    into a single-role use_case_advice answer instead
    (tests/test_basket_completion_v2_14e.py::TestCaseG_AlreadyCoveredRole).
    Trailing "?"/"." directly after a role marker at the very end of a
    message remains a known, narrower residual gap (not reintroduced
    here) - resolve_use_case()'s fix already covers the two mandatory
    V2.14f characterization cases (B, J), neither of which needed this
    function's marker match to change."""
    from app.search import normalize

    normalized = f" {normalize(message)} "
    best: RoleEvidence | None = None
    best_len = 0
    for role_evidence in _ROLE_TABLE.get(use_case, ()):
        for marker in role_evidence.role_markers:
            if f" {marker} " in normalized and len(marker) > best_len:
                best = role_evidence
                best_len = len(marker)
    return best


def has_explicit_exclusion(role_evidence: RoleEvidence, message: str) -> bool:
    """Section 19: an explicit current-turn negation of the exact
    family/role this module would recommend outranks the use-case
    default. Conservative regex: negation marker directly followed
    (within a few words) by one of the role's own markers or its
    display label."""
    from app.search import normalize

    normalized = normalize(message)
    check_terms = set(role_evidence.role_markers) | {normalize(role_evidence.display_label_sk)}
    for negation in _NEGATION_MARKERS:
        idx = normalized.find(negation)
        if idx == -1:
            continue
        window = normalized[idx: idx + len(negation) + 40]
        if any(term and term in window for term in check_terms):
            return True
    return False


def generate_candidates(role_evidence: RoleEvidence, products: list, product_taxonomy_index: dict, limit: int = 8) -> list:
    """Reuses the existing taxonomy index directly (Section 21 - no
    parallel retrieval engine). UNKNOWN and LOW confidence products are
    never included (Section 20)."""
    from app.taxonomy import get_taxonomy
    from app.search import normalize

    matches = []
    for product in products:
        taxonomy = get_taxonomy(product_taxonomy_index, product.id)
        if taxonomy is None or taxonomy.confidence not in ("HIGH", "MEDIUM"):
            continue
        if taxonomy.canonical_family != role_evidence.canonical_family:
            continue
        if role_evidence.canonical_subfamily is not None and taxonomy.canonical_subfamily != role_evidence.canonical_subfamily:
            continue
        if role_evidence.lexical_filter and role_evidence.lexical_filter not in normalize(product.title):
            continue
        matches.append((taxonomy.confidence, product))

    matches.sort(key=lambda pair: (pair[0] != "HIGH", pair[1].effective_price if pair[1].effective_price is not None else 1e9))
    return [product for _confidence, product in matches[:limit]]


def is_companion_request(message: str) -> bool:
    """Section 30: a companion/related-products request ("súvisiace
    produkty k X", "doplnky k X") must never be captured by use-case
    advice - RELATED_PRODUCTS stays authoritative for that phrasing."""
    from app.search import normalize

    normalized = normalize(message)
    return any(marker in normalized for marker in _COMPANION_REQUEST_MARKERS)


def has_resolvable_role(message: str) -> bool:
    """V2.14d (Section 27-34, docs/use-case-recipe-data-quality-v2.14d.md) -
    True iff this message names a LIVE use case via an explicit "na X"/
    "pre X" framing preposition AND a specific ingredient/product role
    within it - i.e. this module has genuine, specific evidence to act
    on, not just a bare dish-name mention. Used by app.main to arbitrate
    the precedence conflict between a bare dish-name-only recipe trigger
    (RECIPE_INTENT_MARKERS' "pad thai"/"tom kha" entries) and a specific
    use-case/attribute question naming the same dish, without duplicating
    this module's own alias/role resolution."""
    use_case = resolve_use_case(message)
    if use_case is None or use_case not in LIVE_USE_CASES:
        return False
    return resolve_role(use_case, message) is not None


def decide_use_case_advice(
    message: str,
    products: list,
    product_taxonomy_index: dict,
    limit: int = 8,
    *,
    recipe_subject: str | None = None,
) -> UseCaseDecision | None:
    """Returns None when the message does not name one of this
    sprint's LIVE_USE_CASES at all, when it is actually a
    companion-products request (Section 30, rt0004), when the caller
    has already resolved a recipe_subject for this turn (Section 35 -
    "chcem robiť Pad Thai" is a recipe request, not a use-case product
    question, even though "Pad Thai" is also one of this module's
    canonical use cases), or when the use case is named but no
    specific role can be identified - the caller must then defer
    entirely to the normal cascade (same fall-through contract as
    execute_recipe()/execute_comparison()).

    IMPORTANT (a second real regression found during full-suite
    evaluation, not hypothetical): a bare use-case mention with no
    resolvable role ("chcem robiť sushi", "ramen na Pho polievku máte
    ingrediencie?") used to CLARIFY here in an earlier version of this
    function - that broke two protected golden/conversation cases
    (regbug_rt0026, conv_sushi_matrix_001) which correctly expect the
    EXISTING related_subject/companion-product mechanism to handle
    bare dish mentions, not a new clarifying question this module
    invented. This function now defers (returns None) in that case
    too, exactly like every other "cannot safely resolve" case -
    UseCaseDecision's own CLARIFY state remains a real, tested code
    path (see TestConflictHandling/TestRoleResolution) but is
    deliberately never reached from the customer-facing entry point in
    this sprint's scope."""
    if recipe_subject:
        return None
    if is_companion_request(message):
        return None

    use_case = resolve_use_case(message)
    if use_case is None or use_case not in LIVE_USE_CASES:
        return None

    role_evidence = resolve_role(use_case, message)
    if role_evidence is None:
        return None

    if has_explicit_exclusion(role_evidence, message):
        return None

    candidates = generate_candidates(role_evidence, products, product_taxonomy_index, limit)
    evidence_items = [EvidenceItem(role_evidence.reason_code, role_evidence.provenance, "app.taxonomy", role_evidence.strength)]

    if not candidates:
        return UseCaseDecision(
            state="ABSTAIN", use_case=use_case, role=role_evidence.role,
            confidence=compute_confidence([]), evidence=[], display_label_sk=role_evidence.display_label_sk,
            reason="no_matching_products",
        )

    confidence = compute_confidence(evidence_items)
    decision_state = decide(evidence_items, has_meaningful_differentiation=True)
    return UseCaseDecision(
        state=decision_state, use_case=use_case, role=role_evidence.role, confidence=confidence,
        evidence=evidence_items, candidate_product_ids=[p.id for p in candidates],
        display_label_sk=role_evidence.display_label_sk,
    )


# --- deterministic answer composition (no LLM, mirrors app.comparison) ------

_USE_CASE_LABELS_SK = {
    "sushi": "sushi", "pho": "pho", "pad_thai": "Pad Thai", "tom_kha": "Tom Kha", "kari": "kari/curry",
}


def compose_use_case_answer(decision: UseCaseDecision, matched_products: list[dict], query_language: str = "sk") -> str:
    is_en = query_language == "en"
    use_case_label = _USE_CASE_LABELS_SK.get(decision.use_case or "", decision.use_case or "")

    if decision.state == "CLARIFY":
        if is_en:
            return f"For {use_case_label}, which specific ingredient or product are you looking for?"
        return f"Pri {use_case_label} - ktorú konkrétnu surovinu alebo produkt hľadáte?"

    if decision.state == "ABSTAIN":
        if is_en:
            return f"I don't currently have {decision.display_label_sk} in stock to recommend for {use_case_label}."
        return f"Momentálne nemám na sklade {decision.display_label_sk} na odporúčanie k {use_case_label}."

    # RECOMMEND
    assertive = decision.confidence == CONFIDENCE_HIGH
    if is_en:
        if assertive:
            return f"For {use_case_label}, {decision.display_label_sk} is the right product type - see the options below."
        return f"For {use_case_label}, {decision.display_label_sk} is a suitable choice - see the options below."
    if assertive:
        return f"Na {use_case_label} odporúčam {decision.display_label_sk} - je to správny typ produktu na tento účel. Možnosti nájdete nižšie."
    return f"Na {use_case_label} je {decision.display_label_sk} vhodná voľba. Možnosti nájdete nižšie."
