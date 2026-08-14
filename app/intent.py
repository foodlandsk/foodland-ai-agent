"""
app/intent.py  -  V2.1: CustomerIntent foundation

Introduces the canonical CustomerIntent object described in the Foodland AI
Advisor V2 architecture: a single standardized representation of what a
customer wants, separate from the many parallel routing mechanisms that
currently live in app/main.py (FAQ markers, recipe detection, special
product subjects, replacement detection, cross-sell detection, ...).

This module does NOT replace any of those detectors yet. It adds a
compatibility layer on top of them:

    legacy intent string (already computed in app/main.py)
        -> map_legacy_intent()
        -> canonical primary_intent

    already-computed signals (subject, allergen, language, ...)
        -> build_customer_intent()
        -> CustomerIntent

Phase V2.1 wires this into analytics logging only, so canonical intent
distribution becomes observable in production without changing any
existing routing decision, answer text, or response schema. Later phases
(V2.2+) can move actual routing decisions behind CustomerIntent.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Canonical primary intents (roadmap V2 section 4). Keep this list short and
# stable - product/dish specifics belong in fields like subject, recipe,
# category, cuisine, use_case, not in new top-level intents.
PRIMARY_INTENTS: tuple[str, ...] = (
    "product_search",
    "product_advice",
    "product_comparison",
    "category_discovery",
    "recipe_only",
    "recipe_to_products",
    "replacement",
    "cross_sell",
    "product_information",
    "allergen_safety",
    "faq",
    "availability_or_price",
    "conversation_followup",
    "general_culinary",
    "out_of_domain",
)

_PRIMARY_INTENTS_SET = frozenset(PRIMARY_INTENTS)

# Default requested_output per canonical intent, used when the caller does
# not specify one explicitly.
_DEFAULT_REQUESTED_OUTPUT: dict[str, str] = {
    "faq": "answer",
    "allergen_safety": "answer",
    "out_of_domain": "answer",
    "general_culinary": "answer",
    "recipe_only": "recipe",
    "recipe_to_products": "shopping_list",
    "product_comparison": "comparison",
    "category_discovery": "answer",
}

# Compatibility adapter: maps the legacy intent strings currently produced
# by app/main.py's chat() routing cascade onto the canonical V2 primary
# intents. This is the seam future phases will migrate away from - once a
# workflow is driven natively by CustomerIntent, its legacy string can be
# retired from this table.
LEGACY_INTENT_MAP: dict[str, str] = {
    "missing_composition": "faq",
    "allergen_safety": "allergen_safety",
    "faq": "faq",
    "recipe": "recipe_only",
    "recipe_to_products": "recipe_to_products",
    "unknown": "out_of_domain",
    "article_products": "product_information",
    "replacement_products": "replacement",
    "product_advice": "product_advice",
    "related_products": "cross_sell",
    "product_search": "product_search",
    "category_discovery": "category_discovery",
}

# Legacy intent strings whose mapping above is a confident, deterministic
# match (used for the confidence heuristic in build_customer_intent()).
_KNOWN_LEGACY_INTENTS = frozenset(LEGACY_INTENT_MAP)


def map_legacy_intent(legacy_intent: str | None) -> str:
    """Map a legacy app/main.py intent string to a canonical primary_intent.

    Unknown or empty input falls back to "product_search", the same
    fallback the legacy routing cascade itself uses when nothing more
    specific was detected.
    """
    if not legacy_intent:
        return "product_search"
    return LEGACY_INTENT_MAP.get(legacy_intent, "product_search")


@dataclass
class CustomerIntent:
    """Canonical representation of what a customer wants (roadmap V2 section 3).

    Not every field has to be filled - unknown fields keep their empty
    default. Fields are intentionally untyped-loose (str | None, list[str])
    to stay a plain data carrier rather than a validation layer.
    """

    primary_intent: str = "product_search"
    subject: str | None = None
    question_type: str | None = None
    brand: str | None = None
    category: str | None = None
    recipe: str | None = None
    cuisine: str | None = None
    use_case: str | None = None
    dietary_constraints: list[str] = field(default_factory=list)
    allergen_constraints: list[str] = field(default_factory=list)
    desired_attributes: list[str] = field(default_factory=list)
    excluded_attributes: list[str] = field(default_factory=list)
    customer_has: list[str] = field(default_factory=list)
    requested_output: str = "products"
    language: str = "sk"
    confidence: float = 0.5
    original_message: str = ""
    # Traceability only (not part of the roadmap schema): which legacy
    # app/main.py intent string this object was adapted from, so V2.2+
    # migrations can be verified against real production data.
    legacy_intent: str = ""

    def __post_init__(self) -> None:
        if self.primary_intent not in _PRIMARY_INTENTS_SET:
            self.primary_intent = "product_search"


def build_customer_intent(
    original_message: str,
    legacy_intent: str | None,
    *,
    subject: str | None = None,
    brand: str | None = None,
    category: str | None = None,
    recipe: str | None = None,
    cuisine: str | None = None,
    use_case: str | None = None,
    allergen_constraints: list[str] | None = None,
    customer_has: list[str] | None = None,
    language: str = "sk",
    requested_output: str | None = None,
) -> CustomerIntent:
    """Compatibility adapter: build a CustomerIntent from already-computed
    legacy signals without re-deriving them.

    This is intentionally a thin, pure mapping - it must not change any
    existing routing decision. Callers pass in whatever subject/brand/etc.
    the legacy detectors already found; fields nobody computed stay empty.
    """
    primary_intent = map_legacy_intent(legacy_intent)
    confidence = 0.9 if legacy_intent in _KNOWN_LEGACY_INTENTS else 0.4
    output = requested_output or _DEFAULT_REQUESTED_OUTPUT.get(primary_intent, "products")
    return CustomerIntent(
        primary_intent=primary_intent,
        subject=subject,
        brand=brand,
        category=category,
        recipe=recipe,
        cuisine=cuisine,
        use_case=use_case,
        allergen_constraints=list(allergen_constraints or []),
        customer_has=list(customer_has or []),
        requested_output=output,
        language=language or "sk",
        confidence=confidence,
        original_message=original_message or "",
        legacy_intent=legacy_intent or "",
    )
