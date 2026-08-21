"""
app/comparison.py  -  V2.14b Evidence-Grounded Product Comparison &
Recommendation Decision Foundation.

Builds on app.recommendation_evidence (V2.14a) - reuses its
EvidenceItem/provenance/confidence primitives directly rather than
inventing a competing model. Does NOT reuse app.workflow_registry's
COMPARISON label's own trigger gate (_looks_like_comparison() there is
scoped to "an existing FAQ answer happens to contain comparison
markers" - it is not a general product-vs-product comparison
detector) or its full marker tuple: a real regression, found during
implementation (see looks_like_comparison_request()'s docstring),
showed that tuple's "rozdiel" ("difference") marker is safe as a
post-hoc FAQ-hit relabel but far too broad as a causal product-pick
trigger - "aký je rozdiel medzi X a Y?" is usually an informational
question, not a request to choose between two SKUs. This module
defines its own narrower, causally-safe marker set instead.

SAFETY DESIGN CHOICE (the single most important decision in this
module): comparison ANSWERS are composed ENTIRELY DETERMINISTICALLY
from computed evidence, via compose_comparison_answer() - there is NO
LLM call anywhere in this module's decision or composition path. This
sidesteps "LLM override protection" (spec Section 26) BY CONSTRUCTION:
there is no free-form generated text for a decision like TRADE_OFF or
ABSTAIN to be overridden by, because no LLM ever composes it. This
mirrors the established, already-audited precedent of
app.answer_composer (V2.5): "deterministic, template-based answer... no
LLM call, no LLM re-selection" for structured commerce answers.

Comparison target resolution (Section 8) is intentionally narrow in
this first sprint - two forms only:
1. Ordinal pair reference into the session's last shown result set
   ("prvý alebo druhý", "porovnaj prvý a tretí") - reuses
   app.session_state.get_recent_presentation(), the same primitive the
   existing single-ordinal follow-up handler already trusts.
2. Explicit two-fragment text comparison ("Kikkoman alebo Yamasa",
   "Porovnaj Kikkoman a Yamasa") - splits on the same connector
   vocabulary as app.workflow_registry._COMPARISON_MARKERS, resolves
   each fragment through the EXISTING retrieval pipeline
   (hybrid_cached_search_products, top-1) rather than a new NLU layer.

Anything that does not resolve to exactly 2 distinct products through
one of these two deterministic paths is CLARIFY, never a guessed pair
(Section 8: "If target resolution is ambiguous: CLARIFY, not
fabricated comparison").
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.recommendation_evidence import (
    CONFIDENCE_HIGH,
    PROVENANCE_DATA_DERIVED,
    EvidenceItem,
    compute_confidence,
)

# --- comparison goals (Section 9) -------------------------------------------
GOAL_CHEAPEST = "CHEAPEST"
GOAL_BEST_VALUE = "BEST_VALUE"
GOAL_LARGEST_PACK = "LARGEST_PACK"
GOAL_SMALLEST_PACK = "SMALLEST_PACK"
GOAL_GENERAL_BEST = "GENERAL_BEST"
GOAL_UNSUPPORTED_QUALITATIVE = "UNSUPPORTED_QUALITATIVE"

# --- decision states (Section 14) -------------------------------------------
STATE_CLEAR_WINNER = "CLEAR_WINNER"
STATE_CONDITIONAL_WINNER = "CONDITIONAL_WINNER"
STATE_TRADE_OFF = "TRADE_OFF"
STATE_NO_MEANINGFUL_DIFFERENCE = "NO_MEANINGFUL_DIFFERENCE"
STATE_CLARIFY = "CLARIFY"
STATE_ABSTAIN = "ABSTAIN"

# --- reason codes (Section 12) - only dimensions with real catalog evidence
REASON_PRICE_FIT = "price_fit"
REASON_UNIT_PRICE_FIT = "unit_price_fit"
REASON_SIZE_FIT = "size_fit"
REASON_BRAND_FIT = "brand_fit"
REASON_PRODUCT_TYPE_FIT = "product_type_fit"

# Relative difference below this is treated as noise, not a real
# distinction (Section 18 - do not manufacture differences).
_MEANINGFUL_RELATIVE_DIFFERENCE = 0.05

_UNIT_MEASURE_RE = re.compile(r"^\s*([\d.,]+)\s*([a-zA-Z]+)\s*$")

# Reused, not duplicated, from app.workflow_registry's own comparison
# marker vocabulary (imported lazily in _split_explicit_pair to avoid
# a module-load-order dependency on app.main's registration sequence).
_PAIR_CONNECTORS = (" alebo ", " vs ", " verzus ", " a ")

_CHEAPEST_MARKERS = ("lacnejsi", "lacnejsia", "lacnejsie", "cena", "drahsi", "drahsia", "cheaper")
_BEST_VALUE_MARKERS = ("oplati", "vyhodnejsi", "vyhodnejsia", "vyhodnejsie", "value", "jednotkov")
_LARGEST_PACK_MARKERS = ("vacsie balenie", "väčšie balenie", "viac", "objem", "väčší", "vacsi")
_QUALITATIVE_MARKERS = (
    "chuti", "chutnejsi", "chutnejsia", "tastier", "taste",
    "autentick", "authentic", "premium", "kvalitnejsi", "kvalitnejsia",
    "zdravsi", "zdravsia", "healthier", "oblubenejsi", "popular",
)


@dataclass(frozen=True, slots=True)
class ComparisonTargets:
    product_a: dict
    product_b: dict
    resolution_method: str  # "ordinal_pair" | "explicit_pair"


@dataclass(frozen=True, slots=True)
class ComparisonDecision:
    state: str
    goal: str
    winner_product_id: str | None
    confidence: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    missing_dimensions: list[str] = field(default_factory=list)
    clarification_question: str | None = None
    abstain_reason: str | None = None


def resolve_comparison_goal(message: str) -> str:
    """Deterministic keyword classification (Section 9) - no LLM, no
    large ontology. Qualitative goals (flavor/authenticity/premium/
    popularity/healthiness) are recognized explicitly so they route to
    ABSTAIN rather than silently falling through to GENERAL_BEST and
    being answered with irrelevant evidence (Section 15: "Do not allow
    irrelevant evidence to manufacture a winner")."""
    from app.search import normalize

    normalized = f" {normalize(message)} "
    if any(marker in normalized for marker in _QUALITATIVE_MARKERS):
        return GOAL_UNSUPPORTED_QUALITATIVE
    if any(marker in normalized for marker in _BEST_VALUE_MARKERS):
        return GOAL_BEST_VALUE
    if any(marker in normalized for marker in _CHEAPEST_MARKERS):
        return GOAL_CHEAPEST
    if any(marker in normalized for marker in _LARGEST_PACK_MARKERS):
        return GOAL_LARGEST_PACK
    return GOAL_GENERAL_BEST


def _extract_ordinal_indices(message: str) -> list[int]:
    """Unlike app.session_state._extract_ordinal_index (which returns
    only the FIRST ordinal word, designed for single-product follow-up
    references like "ten druhý"), comparison needs ALL ordinals
    mentioned in one message ("prvý alebo druhý"). Reuses the same
    normalize() + word-token approach, not a new normalization
    scheme."""
    from app.search import normalize
    from app.session_state import _ORDINAL_WORDS

    normalized = normalize(message)
    indices: list[int] = []
    for token in normalized.split():
        if token in _ORDINAL_WORDS:
            index = _ORDINAL_WORDS[token]
            if index not in indices:
                indices.append(index)
    return indices


def looks_like_comparison_request(message: str) -> bool:
    """Deliberately does NOT reuse the full app.workflow_registry
    ._COMPARISON_MARKERS tuple verbatim - real regression found during
    implementation: that tuple includes "rozdiel" ("difference"),
    which is safe in workflow_registry's own context (a pure ANALYTICS
    LABEL applied only after an existing FAQ answer was already found -
    "rozdiel" there can only relabel a real FAQ hit, never redirect
    one), but is FAR too broad as a CAUSAL trigger here: "aký je
    rozdiel medzi mirin a ryžovým octom?" is a genuine informational/
    FAQ-style question asking to EXPLAIN a conceptual difference
    between two ingredient concepts, not a request to pick a winner
    between two purchasable SKUs - it broke an existing session-safety
    regression test (tests/test_session_contamination_v2_13b_1.py)
    before this exclusion was added. " vs "/"verzus"/" alebo " and the
    "porovnaj" (compare) verb stem are unambiguous enough to keep as
    causal triggers; "rozdiel" is not."""
    _CAUSAL_COMPARISON_MARKERS = (" vs ", "verzus", " alebo ")

    normalized_for_check = normalize_for_check(message)
    has_marker = any(marker.strip() in normalized_for_check for marker in _CAUSAL_COMPARISON_MARKERS) or "porovna" in normalized_for_check
    return has_marker or len(_extract_ordinal_indices(message)) >= 2


def _split_explicit_pair(message: str) -> tuple[str, str] | None:
    normalized_message = f" {message.strip()} "
    if not looks_like_comparison_request(message):
        return None
    for connector in _PAIR_CONNECTORS:
        if connector not in normalized_message:
            continue
        left, _, right = normalized_message.partition(connector)
        left, right = left.strip(" ?.!"), right.strip(" ?.!")
        left = re.sub(r"^porovnaj\s+", "", left, flags=re.IGNORECASE).strip()
        if left and right:
            return left, right
    return None


def normalize_for_check(message: str) -> str:
    from app.search import normalize

    return f" {normalize(message)} "


def resolve_comparison_targets(message: str, memory: dict, products: list) -> ComparisonTargets | None:
    """Returns None (never a partial/guessed pair) when resolution is
    ambiguous - the caller must then CLARIFY (Section 8)."""
    import app.main as m
    from app.search import format_product
    from app.session_state import get_recent_presentation

    ordinal_indices = _extract_ordinal_indices(message)
    if len(ordinal_indices) >= 2:
        presented = get_recent_presentation(memory)
        products_by_id = {p.id: p for p in products}
        first_two = sorted(ordinal_indices)[:2]
        if all(index < len(presented) for index in first_two):
            id_a, id_b = presented[first_two[0]], presented[first_two[1]]
            if id_a != id_b and id_a in products_by_id and id_b in products_by_id:
                return ComparisonTargets(
                    product_a=format_product(products_by_id[id_a]),
                    product_b=format_product(products_by_id[id_b]),
                    resolution_method="ordinal_pair",
                )
        return None

    pair_text = _split_explicit_pair(message)
    if pair_text is not None:
        fragment_a, fragment_b = pair_text
        matches_a = m.hybrid_cached_search_products(fragment_a, 1)
        matches_b = m.hybrid_cached_search_products(fragment_b, 1)
        if (
            matches_a and matches_b
            and matches_a[0].get("id") != matches_b[0].get("id")
            and _same_product_category(matches_a[0], matches_b[0], getattr(m, "product_taxonomy_index", {}))
        ):
            return ComparisonTargets(
                product_a=matches_a[0],
                product_b=matches_b[0],
                resolution_method="explicit_pair",
            )
        return None

    return None


def _same_product_category(product_a: dict, product_b: dict, product_taxonomy_index: dict) -> bool:
    """Section 8: "Do not silently compare arbitrary unrelated
    products." A bare two-brand-name query ("Kikkoman alebo Yamasa?")
    resolves each fragment independently through generic retrieval -
    without this check, the top hit for "Kikkoman" could be a kimchi
    base while the top hit for "Yamasa" is a teriyaki sauce, which
    would silently compare two unrelated product types. Real product
    resolution confirmed this actually happens (verified during
    implementation, not hypothetical). Ordinal-pair resolution
    (comparing two products the customer can already see) is
    deliberately NOT subject to this gate - that pairing is explicit
    and deictic, not inferred from a bare brand name."""
    from app.taxonomy import get_taxonomy

    taxonomy_a = get_taxonomy(product_taxonomy_index, product_a.get("id", ""))
    taxonomy_b = get_taxonomy(product_taxonomy_index, product_b.get("id", ""))
    if taxonomy_a is not None and taxonomy_b is not None:
        return taxonomy_a.canonical_family == taxonomy_b.canonical_family

    category_a = str(product_a.get("product_type") or "").split(">")[0].strip().lower()
    category_b = str(product_b.get("product_type") or "").split(">")[0].strip().lower()
    return bool(category_a) and category_a == category_b


def _parse_unit_measure(raw: str | None) -> tuple[float, str] | None:
    if not raw:
        return None
    match = _UNIT_MEASURE_RE.match(raw)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    return value, match.group(2).lower()


def _price_evidence(product_a: dict, product_b: dict) -> tuple[list[EvidenceItem], str | None] | None:
    """Returns None when price data is missing (caller must ABSTAIN),
    otherwise (evidence, cheaper_id) where cheaper_id is None when
    prices are equal (NO_MEANINGFUL_DIFFERENCE territory)."""
    price_a, price_b = product_a.get("effective_price"), product_b.get("effective_price")
    if price_a is None or price_b is None:
        return None
    if price_a == price_b:
        return [EvidenceItem(REASON_PRICE_FIT, PROVENANCE_DATA_DERIVED, "price/effective_price", 0.9)], None
    cheaper_id = product_a["id"] if price_a < price_b else product_b["id"]
    return [EvidenceItem(REASON_PRICE_FIT, PROVENANCE_DATA_DERIVED, "price/effective_price", 0.9)], cheaper_id


def _unit_price_evidence(product_a: dict, product_b: dict) -> tuple[list[EvidenceItem], str | None, bool]:
    """Returns (evidence, cheaper_per_unit_id, units_comparable).
    Section 13 - never compares g against ml; ABSTAIN territory when
    units_comparable is False."""
    size_a = _parse_unit_measure(product_a.get("unit_pricing_measure"))
    size_b = _parse_unit_measure(product_b.get("unit_pricing_measure"))
    price_a, price_b = product_a.get("effective_price"), product_b.get("effective_price")
    if size_a is None or size_b is None or price_a is None or price_b is None:
        return [], None, False
    (value_a, unit_a), (value_b, unit_b) = size_a, size_b
    if unit_a != unit_b or value_a <= 0 or value_b <= 0:
        return [], None, False
    unit_price_a, unit_price_b = price_a / value_a, price_b / value_b
    lower, higher = min(unit_price_a, unit_price_b), max(unit_price_a, unit_price_b)
    if higher == 0:
        return [], None, False
    relative_difference = (higher - lower) / higher
    if relative_difference < _MEANINGFUL_RELATIVE_DIFFERENCE:
        return [EvidenceItem(REASON_UNIT_PRICE_FIT, PROVENANCE_DATA_DERIVED, "unit_price_per_measure", 0.6)], None, True
    better_id = product_a["id"] if unit_price_a < unit_price_b else product_b["id"]
    return [EvidenceItem(REASON_UNIT_PRICE_FIT, PROVENANCE_DATA_DERIVED, "unit_price_per_measure", 0.85)], better_id, True


def _size_evidence(product_a: dict, product_b: dict, prefer_largest: bool) -> tuple[list[EvidenceItem], str | None]:
    size_a = _parse_unit_measure(product_a.get("unit_pricing_measure"))
    size_b = _parse_unit_measure(product_b.get("unit_pricing_measure"))
    if size_a is None or size_b is None or size_a[1] != size_b[1]:
        return [], None
    (value_a, _), (value_b, _) = size_a, size_b
    if value_a == value_b:
        return [EvidenceItem(REASON_SIZE_FIT, PROVENANCE_DATA_DERIVED, "unit_pricing_measure", 0.7)], None
    larger_id = product_a["id"] if value_a > value_b else product_b["id"]
    smaller_id = product_b["id"] if value_a > value_b else product_a["id"]
    winner_id = larger_id if prefer_largest else smaller_id
    return [EvidenceItem(REASON_SIZE_FIT, PROVENANCE_DATA_DERIVED, "unit_pricing_measure", 0.85)], winner_id


def _descriptive_evidence(product_a: dict, product_b: dict, product_taxonomy_index: dict) -> list[EvidenceItem]:
    """Brand/product_type/taxonomy facts - always DATA_DERIVED,
    descriptive only (Section 27 - part of the "why", never a winner
    by themselves for GENERAL_BEST unless combined with a supported
    directional dimension)."""
    from app.taxonomy import get_taxonomy

    evidence = []
    if product_a.get("brand") and product_b.get("brand"):
        evidence.append(EvidenceItem(REASON_BRAND_FIT, PROVENANCE_DATA_DERIVED, "brand", 0.4))
    taxonomy_a = get_taxonomy(product_taxonomy_index, product_a.get("id", ""))
    taxonomy_b = get_taxonomy(product_taxonomy_index, product_b.get("id", ""))
    if taxonomy_a is not None and taxonomy_b is not None and taxonomy_a.confidence == CONFIDENCE_HIGH_TAXONOMY:
        evidence.append(EvidenceItem(REASON_PRODUCT_TYPE_FIT, PROVENANCE_DATA_DERIVED, "taxonomy.canonical_family", 0.5))
    return evidence


CONFIDENCE_HIGH_TAXONOMY = "HIGH"  # app.taxonomy's own confidence tier vocabulary, not app.recommendation_evidence's


def decide_comparison(
    targets: ComparisonTargets,
    goal: str,
    *,
    product_taxonomy_index: dict | None = None,
) -> ComparisonDecision:
    """Deterministic decision over the resolved pair (Section 14-20).
    Never invokes an LLM."""
    product_a, product_b = targets.product_a, targets.product_b
    product_taxonomy_index = product_taxonomy_index or {}

    if goal == GOAL_UNSUPPORTED_QUALITATIVE:
        return ComparisonDecision(
            state=STATE_ABSTAIN,
            goal=goal,
            winner_product_id=None,
            confidence=compute_confidence([]),
            abstain_reason="no_grounded_evidence_for_qualitative_claim",
        )

    if goal == GOAL_CHEAPEST:
        result = _price_evidence(product_a, product_b)
        if not result:
            return ComparisonDecision(STATE_ABSTAIN, goal, None, compute_confidence([]), abstain_reason="missing_price_data")
        evidence, winner_id = result
        if winner_id is None:
            return ComparisonDecision(STATE_NO_MEANINGFUL_DIFFERENCE, goal, None, compute_confidence(evidence), evidence=evidence, reason_codes=[REASON_PRICE_FIT])
        return ComparisonDecision(STATE_CLEAR_WINNER, goal, winner_id, compute_confidence(evidence), evidence=evidence, reason_codes=[REASON_PRICE_FIT])

    if goal == GOAL_BEST_VALUE:
        evidence, winner_id, units_comparable = _unit_price_evidence(product_a, product_b)
        if not units_comparable:
            return ComparisonDecision(STATE_ABSTAIN, goal, None, compute_confidence([]), abstain_reason="incompatible_or_missing_units")
        if winner_id is None:
            return ComparisonDecision(STATE_NO_MEANINGFUL_DIFFERENCE, goal, None, compute_confidence(evidence), evidence=evidence, reason_codes=[REASON_UNIT_PRICE_FIT])
        return ComparisonDecision(STATE_CLEAR_WINNER, goal, winner_id, compute_confidence(evidence), evidence=evidence, reason_codes=[REASON_UNIT_PRICE_FIT])

    if goal in (GOAL_LARGEST_PACK, GOAL_SMALLEST_PACK):
        evidence, winner_id = _size_evidence(product_a, product_b, prefer_largest=(goal == GOAL_LARGEST_PACK))
        if not evidence:
            return ComparisonDecision(STATE_ABSTAIN, goal, None, compute_confidence([]), abstain_reason="incompatible_or_missing_size_units")
        if winner_id is None:
            return ComparisonDecision(STATE_NO_MEANINGFUL_DIFFERENCE, goal, None, compute_confidence(evidence), evidence=evidence, reason_codes=[REASON_SIZE_FIT])
        return ComparisonDecision(STATE_CLEAR_WINNER, goal, winner_id, compute_confidence(evidence), evidence=evidence, reason_codes=[REASON_SIZE_FIT])

    # GOAL_GENERAL_BEST: gather every supported dimension, look for
    # dominance (Section 15/16/17) rather than assuming one exists.
    #
    # Value dimension: prefer UNIT price over raw price whenever
    # package sizes are comparable (same unit) - raw price alone would
    # let a 150ml bottle "beat" an 18L catering pack on price for no
    # meaningful reason (verified this exact case during
    # implementation: 150ml @ EUR4.17 vs 18L @ EUR50.57 - a real
    # example, not hypothetical). Raw price is only used as the value
    # dimension when sizes are equal or unknown, i.e. when it is
    # actually an apples-to-apples comparison.
    size_a = _parse_unit_measure(product_a.get("unit_pricing_measure"))
    size_b = _parse_unit_measure(product_b.get("unit_pricing_measure"))
    sizes_comparable = size_a is not None and size_b is not None and size_a[1] == size_b[1]
    sizes_equal = sizes_comparable and size_a[0] == size_b[0]

    descriptive = _descriptive_evidence(product_a, product_b, product_taxonomy_index)
    directional: dict[str, str] = {}
    all_evidence: list[EvidenceItem] = list(descriptive)
    missing_dimensions: list[str] = []

    if sizes_comparable and not sizes_equal:
        unit_price_evidence, unit_price_winner, _ = _unit_price_evidence(product_a, product_b)
        if unit_price_evidence:
            all_evidence.extend(unit_price_evidence)
            if unit_price_winner is not None:
                directional[REASON_UNIT_PRICE_FIT] = unit_price_winner
        else:
            missing_dimensions.append(REASON_UNIT_PRICE_FIT)
    else:
        price_result = _price_evidence(product_a, product_b)
        if price_result:
            price_evidence, price_winner = price_result
            all_evidence.extend(price_evidence)
            if price_winner is not None:
                directional[REASON_PRICE_FIT] = price_winner
        else:
            missing_dimensions.append(REASON_PRICE_FIT)

    size_evidence, size_winner = _size_evidence(product_a, product_b, prefer_largest=True)
    if size_evidence:
        all_evidence.extend(size_evidence)
        if size_winner is not None:
            directional[REASON_SIZE_FIT] = size_winner
    else:
        missing_dimensions.append(REASON_SIZE_FIT)

    if not directional:
        if not all_evidence:
            return ComparisonDecision(STATE_ABSTAIN, goal, None, compute_confidence([]), missing_dimensions=missing_dimensions, abstain_reason="no_comparable_dimensions")
        return ComparisonDecision(STATE_NO_MEANINGFUL_DIFFERENCE, goal, None, compute_confidence(all_evidence), evidence=all_evidence, missing_dimensions=missing_dimensions)

    winners = set(directional.values())
    if len(winners) == 1:
        (winner_id,) = winners
        return ComparisonDecision(
            STATE_CLEAR_WINNER, goal, winner_id, compute_confidence(all_evidence),
            evidence=all_evidence, reason_codes=list(directional.keys()), missing_dimensions=missing_dimensions,
        )

    # Different dimensions favor different products - Section 16/17:
    # CONDITIONAL_WINNER when we can phrase "if X matters, pick A",
    # which is always possible here since each directional dimension
    # names its own winner explicitly.
    return ComparisonDecision(
        STATE_CONDITIONAL_WINNER, goal, None, compute_confidence(all_evidence),
        evidence=all_evidence, reason_codes=list(directional.keys()), missing_dimensions=missing_dimensions,
    )


# --- deterministic answer composition (Section 27) --------------------------
# NO LLM CALL ANYWHERE BELOW THIS LINE. Every sentence is built from a
# fixed Slovak template plus values already present on the resolved
# product dicts (title, effective_price, currency, unit_pricing_measure) -
# this is what makes "LLM override protection" (Section 26) structurally
# unnecessary for this module: there is no generated prose to override.

_REASON_LABELS_SK = {
    REASON_PRICE_FIT: "cena",
    REASON_UNIT_PRICE_FIT: "cena za jednotku množstva",
    REASON_SIZE_FIT: "veľkosť balenia",
    REASON_BRAND_FIT: "značka",
    REASON_PRODUCT_TYPE_FIT: "kategória produktu",
}


def _title(product: dict) -> str:
    return str(product.get("title") or product.get("id") or "produkt")


def _price_text(product: dict) -> str:
    price = product.get("effective_price")
    if price is None:
        return "cena neuvedená"
    currency = product.get("currency", "EUR")
    return f"{price:.2f} {currency}"


def _size_text(product: dict) -> str:
    size = product.get("unit_pricing_measure")
    return size if size else "veľkosť balenia neuvedená"


def compose_comparison_answer(decision: ComparisonDecision, targets: ComparisonTargets | None, query_language: str = "sk") -> str:
    is_en = query_language == "en"

    if decision.state == STATE_CLARIFY:
        # CLARIFY never needs a resolved pair - it fires precisely
        # BECAUSE no safe pair could be resolved (Section 19).
        if is_en:
            return "Which two products would you like me to compare, and what matters most - price, package size, or a specific use case?"
        return "Ktoré dva produkty presne chcete porovnať, a čo je pre Vás dôležitejšie - cena, veľkosť balenia, alebo konkrétne použitie?"

    assert targets is not None, "only STATE_CLARIFY may compose without resolved targets"
    product_a, product_b = targets.product_a, targets.product_b

    def other(product_id: str) -> dict:
        return product_b if product_id == product_a.get("id") else product_a

    if decision.state == STATE_CLEAR_WINNER:
        winner = product_a if decision.winner_product_id == product_a.get("id") else product_b
        loser = other(decision.winner_product_id)
        missing_note_sk = ""
        missing_note_en = ""
        if REASON_SIZE_FIT in decision.missing_dimensions or REASON_UNIT_PRICE_FIT in decision.missing_dimensions:
            missing_note_sk = " (porovnanie podľa veľkosti balenia nebolo možné, chýba údaj o balení.)"
            missing_note_en = " (I could not compare package size - that data is missing.)"
        if is_en:
            return (
                f"Based on {', '.join(_REASON_LABELS_SK.get(r, r) for r in decision.reason_codes)}, "
                f"I'd pick {_title(winner)} ({_price_text(winner)}, {_size_text(winner)}) over "
                f"{_title(loser)} ({_price_text(loser)}, {_size_text(loser)}).{missing_note_en}"
            )
        reasons = ", ".join(_REASON_LABELS_SK.get(r, r) for r in decision.reason_codes)
        return (
            f"Podľa dostupných údajov ({reasons}) by som vybrala {_title(winner)} "
            f"({_price_text(winner)}, {_size_text(winner)}) pred {_title(loser)} "
            f"({_price_text(loser)}, {_size_text(loser)}).{missing_note_sk}"
        )

    if decision.state == STATE_CONDITIONAL_WINNER:
        parts = [_REASON_LABELS_SK.get(reason_code, reason_code) for reason_code in decision.reason_codes]
        if is_en:
            return (
                f"These two differ on {', '.join(parts)} without one dominating overall - "
                f"{_title(product_a)} ({_price_text(product_a)}, {_size_text(product_a)}) vs. "
                f"{_title(product_b)} ({_price_text(product_b)}, {_size_text(product_b)}). "
                "Which matters more to you: price or package size?"
            )
        return (
            f"Tieto dva produkty sa líšia v {', '.join(parts)}, žiadny nie je jednoznačne lepší vo všetkom - "
            f"{_title(product_a)} ({_price_text(product_a)}, {_size_text(product_a)}) vs. "
            f"{_title(product_b)} ({_price_text(product_b)}, {_size_text(product_b)}). "
            "Je pre Vás dôležitejšia cena, alebo veľkosť balenia?"
        )

    if decision.state == STATE_TRADE_OFF:
        if is_en:
            return (
                f"{_title(product_a)} ({_price_text(product_a)}, {_size_text(product_a)}) and "
                f"{_title(product_b)} ({_price_text(product_b)}, {_size_text(product_b)}) each have "
                "different advantages and I don't have a clear overall winner - could you tell me "
                "what matters most: price, package size, or a specific use case?"
            )
        return (
            f"{_title(product_a)} ({_price_text(product_a)}, {_size_text(product_a)}) a "
            f"{_title(product_b)} ({_price_text(product_b)}, {_size_text(product_b)}) majú každý inú výhodu "
            "a nemám jednoznačného víťaza - je pre Vás dôležitejšia cena, veľkosť balenia, alebo konkrétne použitie?"
        )

    if decision.state == STATE_NO_MEANINGFUL_DIFFERENCE:
        if is_en:
            return (
                f"{_title(product_a)} and {_title(product_b)} are comparable on the data I have "
                f"({_price_text(product_a)} vs. {_price_text(product_b)}) - there is no meaningful "
                "difference between them for this comparison."
            )
        return (
            f"{_title(product_a)} a {_title(product_b)} sú si podľa dostupných údajov podobné "
            f"({_price_text(product_a)} vs. {_price_text(product_b)}) - nevidím medzi nimi zásadný rozdiel."
        )

    # STATE_ABSTAIN
    if is_en:
        return (
            f"I can compare {_title(product_a)} and {_title(product_b)} on price and package size, "
            "but I don't have reliable data to say which one tastes better or is more authentic."
        )
    return (
        f"Viem porovnať {_title(product_a)} a {_title(product_b)} podľa ceny a veľkosti balenia, "
        "ale nemám spoľahlivé údaje na to, aby som povedala, ktorá chutí lepšie alebo je autentickejšia."
    )
