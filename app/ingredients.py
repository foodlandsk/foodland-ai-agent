"""
app/ingredients.py  -  V2.8 Ingredient Normalization & Role Classification

Deterministic, no-LLM ingredient primitives used by app.recipe_graph and
app.recipe_shopping (Section 9/13/89 of the V2.8 spec).

Grounding (see docs/recipe-knowledge-audit.md): the current
`data/knowledge.json` "Recipes" CMS collection carries no ingredient text
at all - the real, production-proven ingredient ground truth is
`app.main.RECIPE_SHOPPING_CORE_QUERIES` (47 curated dishes, each a list of
`(display_name_sk, required_terms, excluded_terms)`). This module never
invents ingredient identity - it only normalizes/classifies text that
already exists in that curated data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.feed import Product
from app.search import normalize, raw_tokens

# ---------------------------------------------------------------------------
# Controlled role vocabulary (Section 13). Free-text roles are never used.
# ---------------------------------------------------------------------------
ROLE_BASE = "BASE"
ROLE_NOODLE = "NOODLE"
ROLE_RICE = "RICE"
ROLE_PROTEIN = "PROTEIN"
ROLE_SAUCE = "SAUCE"
ROLE_SEASONING = "SEASONING"
ROLE_PASTE = "PASTE"
ROLE_OIL = "OIL"
ROLE_ACID = "ACID"
ROLE_SWEETENER = "SWEETENER"
ROLE_AROMATIC = "AROMATIC"
ROLE_VEGETABLE = "VEGETABLE"
ROLE_HERB = "HERB"
ROLE_GARNISH = "GARNISH"
ROLE_TOPPING = "TOPPING"
ROLE_WRAPPER = "WRAPPER"
ROLE_BROTH = "BROTH"
ROLE_SOUP_BASE = "SOUP_BASE"

KNOWN_ROLES = frozenset({
    ROLE_BASE, ROLE_NOODLE, ROLE_RICE, ROLE_PROTEIN, ROLE_SAUCE,
    ROLE_SEASONING, ROLE_PASTE, ROLE_OIL, ROLE_ACID, ROLE_SWEETENER,
    ROLE_AROMATIC, ROLE_VEGETABLE, ROLE_HERB, ROLE_GARNISH, ROLE_TOPPING,
    ROLE_WRAPPER, ROLE_BROTH, ROLE_SOUP_BASE,
})

# Taxonomy family (app.taxonomy.FamilyRule.family) -> commerce role. Used
# when an ingredient concept resolved to a real V2.3 taxonomy rule.
ROLE_BY_TAXONOMY_FAMILY = {
    "rice": ROLE_RICE,
    "noodles": ROLE_NOODLE,
    "sauce": ROLE_SAUCE,
    "paste": ROLE_PASTE,
    "curry_paste": ROLE_PASTE,
    "oil": ROLE_OIL,
    "vinegar": ROLE_ACID,
    "coconut_product": ROLE_BASE,
    "seaweed": ROLE_TOPPING,
    "rice_paper": ROLE_WRAPPER,
    "flour": ROLE_BASE,
    "instant_food": ROLE_BASE,
}

# Keyword-based role inference for ingredient concepts with NO matching
# V2.3 taxonomy rule (Section 72 - lexical-only concepts, e.g. tamarind,
# galangal, dashi). Ordered - first match wins. Every keyword below is a
# real Slovak word that appears in RECIPE_SHOPPING_CORE_QUERIES display
# names, not an invented pattern.
_LEXICAL_ROLE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("omacka", ROLE_SAUCE),
    ("pasta", ROLE_PASTE),
    ("polievk", ROLE_SOUP_BASE),
    ("muka", ROLE_BASE),
    ("rezance", ROLE_NOODLE),
    ("nudle", ROLE_NOODLE),
    ("ocot", ROLE_ACID),
    ("cukor", ROLE_SWEETENER),
    ("olej", ROLE_OIL),
    ("tofu", ROLE_PROTEIN),
    ("dashi", ROLE_BROTH),
    ("vyhonky", ROLE_VEGETABLE),
    ("huby", ROLE_VEGETABLE),
    ("hrib", ROLE_VEGETABLE),
    ("shiitake", ROLE_VEGETABLE),
    ("listy", ROLE_AROMATIC),
    ("trava", ROLE_AROMATIC),
    ("zazvor", ROLE_AROMATIC),
    ("cesnak", ROLE_AROMATIC),
    ("galangal", ROLE_AROMATIC),
    ("semienka", ROLE_TOPPING),
    ("arasid", ROLE_GARNISH),
    ("orech", ROLE_GARNISH),
    ("korenie", ROLE_SEASONING),
    ("korenina", ROLE_SEASONING),
    ("masala", ROLE_SEASONING),
    ("mirin", ROLE_SEASONING),
    ("papier", ROLE_WRAPPER),
)


def infer_lexical_role(display_name_sk: str) -> str:
    """Deterministic keyword classification for a lexical-only ingredient
    concept. Falls back to SEASONING (the most defensible generic bucket
    for spice/condiment mixes) rather than fabricating a more specific
    claim without evidence (Section 141)."""
    normalized = normalize(display_name_sk)
    for keyword, role in _LEXICAL_ROLE_KEYWORDS:
        if keyword in normalized:
            return role
    return ROLE_SEASONING


def slugify_concept_id(display_name_sk: str) -> str:
    """Stable, deterministic concept id for ingredient concepts with no
    matching V2.3 taxonomy rule_id. Never used for taxonomy-backed
    concepts (those keep the real rule_id as concept_id - Section 6)."""
    normalized = normalize(display_name_sk)
    slug = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return slug or "unknown_ingredient"


def lexical_candidates(
    products: list[Product],
    query_text: str,
    required_terms: tuple[str, ...],
    excluded_terms: tuple[str, ...],
    limit: int = 5,
) -> list[Product]:
    """Ranked title-substring candidate match for ingredient concepts that
    have no V2.3 taxonomy rule (Section 18 resolver, lexical branch).
    Mirrors the matching AND scoring semantics of the existing,
    production-proven `app.main.recipe_core_product_candidates` (full-phrase
    match bonus, required-term-count bonus, token overlap) without
    importing app.main (would be circular - app.main imports this module).

    Scoring is not optional here: a bare single-word required_terms tuple
    like ("pho",) is a SUBSTRING test, so without the full-phrase/token
    ranking below it can surface an unrelated product whose title merely
    contains that substring (e.g. "pho" inside "Alphonso Mango Puree") as
    the top - and only - candidate. Collecting every match and ranking by
    real relevance, the same way the legacy function does, is what keeps
    that from happening."""
    normalized_query = normalize(query_text)
    query_tokens = raw_tokens(query_text)
    scored: list[tuple[int, Product]] = []
    for product in products:
        title = normalize(getattr(product, "title", "") or "")
        if any(term in title for term in excluded_terms):
            continue
        if required_terms and not all(term in title for term in required_terms):
            continue
        score = 0
        if normalized_query and normalized_query in title:
            score += 80
        if required_terms:
            score += 35 * sum(1 for term in required_terms if term in title)
        score += 12 * len(query_tokens & raw_tokens(title))
        scored.append((score, product))
    scored.sort(key=lambda item: (-item[0], item[1].id))
    return [product for _, product in scored[:limit]]


_QUANTITY_UNIT_PATTERN = re.compile(
    r"^\s*(?P<quantity>\d+(?:[.,]\d+)?)\s*(?P<unit>ml|l|g|kg|tsp|tbsp|pl|pcs|ks)?\b",
    re.IGNORECASE,
)

_UNIT_ALIASES = {
    "pl": "tbsp",  # Slovak "polievkova lyzica" abbreviation used in curated notes
    "ks": "piece",
    "pcs": "piece",
}

# Non-numeric quantity phrases (Section 25) - must NEVER be scaled.
NON_NUMERIC_QUANTITY_MARKERS = ("podla chuti", "na dochutenie", "podla potreby", "na ozdobu")


@dataclass(frozen=True)
class ParsedQuantity:
    quantity: float | None
    unit: str | None
    is_numeric: bool
    raw_text: str


def parse_quantity_text(raw_text: str) -> ParsedQuantity:
    """Deterministic quantity/unit extraction (Section 9/25/26). Returns
    is_numeric=False for anything that isn't a clean `<number> <unit>`
    prefix - including all Section-25 nonnumeric phrases - rather than
    guessing. No current Foodland recipe ingredient actually carries a
    parseable quantity (see docs/recipe-knowledge-audit.md); this parser
    exists so the capability is implemented and tested, not activated on
    fabricated numbers."""
    text = str(raw_text or "").strip()
    normalized = normalize(text)
    if any(marker in normalized for marker in NON_NUMERIC_QUANTITY_MARKERS):
        return ParsedQuantity(quantity=None, unit=None, is_numeric=False, raw_text=text)

    match = _QUANTITY_UNIT_PATTERN.match(text)
    if not match:
        return ParsedQuantity(quantity=None, unit=None, is_numeric=False, raw_text=text)

    quantity_str = match.group("quantity").replace(",", ".")
    try:
        quantity = float(quantity_str)
    except ValueError:
        return ParsedQuantity(quantity=None, unit=None, is_numeric=False, raw_text=text)

    unit_raw = (match.group("unit") or "").lower() or None
    unit = _UNIT_ALIASES.get(unit_raw, unit_raw)
    return ParsedQuantity(quantity=quantity, unit=unit, is_numeric=True, raw_text=text)


# Safe, unambiguous unit conversions (Section 27). Deliberately excludes
# spoon<->volume conversions (ambiguous across recipe source conventions).
_VOLUME_TO_ML = {"ml": 1.0, "l": 1000.0}
_MASS_TO_G = {"g": 1.0, "kg": 1000.0}


def convert_to_base_unit(quantity: float, unit: str) -> tuple[float, str] | None:
    """Returns (value, base_unit) in ml or g, or None if the unit isn't a
    safely convertible volume/mass unit (Section 27/29 - no fabricated
    conversion for tsp/tbsp/piece, which vary by ingredient density)."""
    if unit in _VOLUME_TO_ML:
        return quantity * _VOLUME_TO_ML[unit], "ml"
    if unit in _MASS_TO_G:
        return quantity * _MASS_TO_G[unit], "g"
    return None


_SERVINGS_PATTERN = re.compile(
    r"\b(?:pre|na)\s+(\d{1,2})\s*(?:osob|osoby|osobu|ludi|ludia|luda|porci|porcie|porcii)\b",
    re.IGNORECASE,
)


def extract_requested_servings(message: str) -> int | None:
    """Section 134-F - "Pad Thai pre 8 ludi" -> 8. Purely a request-side
    signal surfaced on RecipeShoppingPlan.requested_servings; does not by
    itself imply scaled quantities are available (Section 24/25 - see
    docs/recipe-knowledge-audit.md: no current recipe carries a structured
    base quantity, so there is nothing to scale against today)."""
    normalized = normalize(message)
    match = _SERVINGS_PATTERN.search(normalized)
    if not match:
        return None
    value = int(match.group(1))
    return value if 1 <= value <= 20 else None


def scale_quantity(quantity: float, base_servings: int, target_servings: int) -> float:
    """Linear serving scale (Section 24). Caller must only call this for
    ParsedQuantity.is_numeric=True values (Section 25)."""
    if base_servings <= 0:
        return quantity
    return quantity * (target_servings / base_servings)
