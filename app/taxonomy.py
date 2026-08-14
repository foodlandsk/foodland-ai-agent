"""
app/taxonomy.py  -  V2 catalog-first product taxonomy (Phase 5-6): rice family

Rice is the first canonical family selected for implementation, per
docs/product-taxonomy-audit.md (mandatory first taxonomy run). Selected on
real catalog evidence, not example text from a prompt: at least 7 distinct
sub-families share the "ryz*" linguistic root (plain rice, sushi rice,
rice noodles, rice vinegar, rice flour, rice paper, rice cookers - the
last of which has its own real catalog category, "Ryžovary"), this exact
collision class caused repeated production bugs (roadmap Sprint Z.6), and
app/main.py's SPECIAL_PRODUCT_QUERIES already has partial coverage
(plain_rice, sushi_rice, rice_vinegar, rice_cooker, rice_seasoning,
rice_side) to build on rather than replace.

Rollout stage (Phase 16): Stage A, shadow/observation mode only.
classify_rice_query() is wired into /chat purely for analytics logging
(see log_taxonomy_shadow() in app/main.py) - it does not change any
routing decision, product selection, or answer text. Nothing here is a
manually maintained per-SKU mapping (Phase 12): classification runs over
message/title text via a small, reusable phrase table, not a list of
product IDs.

Sprint V2.1 (Feed Foundation / Product Normalization / Taxonomy Engine)
extends this module with a second, distinct classifier: classify_product()
and build_taxonomy_index() operate on catalog PRODUCTS (category
memberships + title + URL), not on customer message text, and produce a
real canonical_family per product (family != word root - a rice cooker's
family is "kitchenware", not "rice"). See the "PRODUCT-LEVEL TAXONOMY
ENGINE" section below. classify_rice_query() above is unchanged and keeps
its original message-classification meaning.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Iterable

from app.feed import Product
from app.product_normalizer import extract_url_category
from app.search import normalize as search_normalize

logger = logging.getLogger(__name__)


@dataclass
class TaxonomyMatch:
    family: str = "rice"
    subfamily: str | None = None
    confidence: str = "NONE"  # HIGH / MEDIUM / LOW / NONE
    matched_phrase: str | None = None


# Subfamily detection phrases, most specific first - the same
# collision-ordering discipline already used for RELATED_SUBJECT_ALIASES
# in app/main.py (e.g. "gyudon" checked before "udon"). Compound phrases
# for the six non-generic subfamilies are checked before the bare grain
# itself ("plain_rice"), since every one of them shares the "ryz*" root
# with it.
RICE_SUBFAMILY_PHRASES: dict[str, tuple[str, ...]] = {
    "rice_cooker": ("ryzovar", "hrniec na ryzu", "rice cooker"),
    "rice_vinegar": ("ryzovy ocot", "ryzoveho octu", "ryzovym octom", "rice vinegar"),
    "rice_flour": ("ryzova muka", "ryzovu muku", "ryzovej muky", "muka z ryze", "muka z lepkavej ryze", "rice flour"),
    "rice_paper": ("ryzovy papier", "rice paper"),
    "rice_noodles": ("ryzove rezance", "ryzovych rezancov", "ryzovymi rezancami", "rice noodles"),
    "sushi_rice": ("sushi ryza", "susi ryza", "ryza na sushi", "ryzu na sushi", "sushi rice"),
    "rice_drink": ("ryzovy napoj", "rice drink"),
    "plain_rice": ("ryza", "ryzu", "ryze", "ryzou", "ryzova", "ryzi"),
}

RICE_SUBFAMILY_CONFIDENCE: dict[str, str] = {
    "rice_cooker": "HIGH",
    "rice_vinegar": "HIGH",
    "rice_flour": "HIGH",
    "rice_paper": "HIGH",
    "rice_noodles": "HIGH",
    "sushi_rice": "HIGH",
    "rice_drink": "MEDIUM",
    "plain_rice": "HIGH",
}


def classify_rice_query(message: str, normalize: Callable[[str], str]) -> TaxonomyMatch:
    """Shadow-mode rice-family classifier.

    `normalize` is injected (pass app.search.normalize) to avoid a
    circular import between this module and app.main/app.search.
    """
    normalized = f" {normalize(message)} "
    for subfamily, phrases in RICE_SUBFAMILY_PHRASES.items():
        for phrase in phrases:
            if phrase in normalized:
                # "aku ryzu odporucas na sushi?" names plain rice and the
                # sushi use-case as separate words, not the compound
                # "sushi ryza" phrase - IntentMapping's verified "Ryža /
                # výber produktu" entry for this exact question says to
                # prefer sushi rice, so treat rice+sushi co-occurrence the
                # same as the compound phrase.
                if subfamily == "plain_rice" and any(t in normalized for t in (" sushi ", " susi ")):
                    return TaxonomyMatch(
                        family="rice",
                        subfamily="sushi_rice",
                        confidence="HIGH",
                        matched_phrase=f"{phrase.strip()}+sushi",
                    )
                return TaxonomyMatch(
                    family="rice",
                    subfamily=subfamily,
                    confidence=RICE_SUBFAMILY_CONFIDENCE[subfamily],
                    matched_phrase=phrase.strip(),
                )
    return TaxonomyMatch(family="rice", subfamily=None, confidence="NONE", matched_phrase=None)


# ===========================================================================
# V2.1 PRODUCT-LEVEL TAXONOMY ENGINE
# ===========================================================================
#
# `classify_rice_query()` above answers "does this MESSAGE mention the rice
# linguistic cluster?" for shadow analytics - it always reports family="rice"
# even for a rice cooker or rice vinegar query, because it is grouping
# *query text* by shared root, not classifying a *product's identity*.
#
# The engine below answers a different question: "what IS this catalog
# PRODUCT?" Family ≠ word root is a mandatory invariant here
# (docs/product-taxonomy-audit.md): a rice cooker's canonical_family is
# "kitchenware", not "rice", even though both classifiers key off the same
# "ryz*" vocabulary. Do not conflate the two - they serve different
# consumers (message-level shadow logging vs. per-product structured data).
#
# Deterministic, data-driven, no LLM calls. Rules are ordered most-specific
# first (rice_cooker/rice_paper/rice_noodles/... before generic plain rice)
# so a compound concept is never swallowed by the bare grain rule it shares
# a root with - the same collision-ordering discipline already used above
# for RICE_SUBFAMILY_PHRASES.

TAXONOMY_VERSION = 1

CONFIDENCE_LEVELS = ("HIGH", "MEDIUM", "LOW", "UNKNOWN")

_CONFIDENCE_DOWNGRADE = {"HIGH": "MEDIUM", "MEDIUM": "LOW", "LOW": "LOW"}


class CategoryRole:
    """Reusable role vocabulary for a single category_memberships[] entry.

    Not every membership resolves to a known role - UNKNOWN is legitimate
    and expected (recurring UNKNOWN memberships become input for a future
    V2 taxonomy iteration, docs/product-taxonomy-audit.md).
    """

    PRODUCT_FAMILY = "PRODUCT_FAMILY"
    PRODUCT_SUBFAMILY = "PRODUCT_SUBFAMILY"
    VARIETY = "VARIETY"
    DIETARY_FACET = "DIETARY_FACET"
    CUISINE_FACET = "CUISINE_FACET"
    USE_CASE = "USE_CASE"
    COMMERCIAL_FACET = "COMMERCIAL_FACET"
    MERCHANDISING_FACET = "MERCHANDISING_FACET"
    UNKNOWN = "UNKNOWN"


# Cross-referential dietary/merchandising labels that show up as *category
# memberships* across many unrelated families (Fáza 1 of the catalog audit:
# "Vegánske potraviny", "Zdravé potraviny" etc. dominate by count but say
# nothing about product identity). Roled as facets, never as canonical_family.
_DIETARY_CATEGORY_TERMS = {
    "veganske potraviny": "vegan",
    "vegetarianske potraviny": "vegetarian",
    "bezlepkove potraviny": "gluten_free",
    "bio potraviny": "organic",
}
_MERCHANDISING_CATEGORY_TERMS = {
    "zdrave potraviny": "healthy_food",
    "super potraviny": "superfood",
    "vypredaj": "clearance",
}

# Two catalog category labels observed for the same sushi-rice product set
# (docs/product-taxonomy-audit.md, canonical aliases). Deterministic,
# testable, no LLM - both normalize (app.search.normalize) to distinct
# strings but must resolve to the same taxonomy signal.
CATEGORY_ALIASES: dict[str, str] = {
    "ryza na susi (sushi)": "sushi_rice_category",
    "susi ryza": "sushi_rice_category",
}


@dataclass(frozen=True, slots=True)
class FamilyRule:
    """One data-driven classification rule. Evaluated in list order - the
    engine stops at the first rule that matches (most specific first)."""

    rule_id: str
    family: str
    subfamily: str | None
    confidence: str  # applied when matched via category evidence
    category_terms: tuple[str, ...] = ()  # normalized; matched against category_memberships (+ aliases)
    title_phrases: tuple[str, ...] = ()  # normalized; matched as substrings of the normalized title
    attributes: tuple[tuple[str, str], ...] = ()


# Rice pilot family (Sprint V2.1) - every rule grounded in real
# data/products.json / live-feed category paths and titles, not invented
# examples (see docs/product-taxonomy-audit.md for the evidence). Ordered
# so every rice-root collision (rezance/ocot/muka/papier/ryzovar/napoj/vino)
# is resolved BEFORE the generic bare-grain rule at the bottom.
FAMILY_DEFINITIONS: list[FamilyRule] = [
    FamilyRule(
        rule_id="rice_cooker",
        family="kitchenware",
        subfamily="rice_cooker",
        confidence="HIGH",
        category_terms=("ryzovary",),
        title_phrases=("ryzovar", "hrniec na ryzu"),
        attributes=(("object_type", "rice_cooker"),),
    ),
    FamilyRule(
        rule_id="rice_paper",
        family="rice_paper",
        subfamily=None,
        confidence="HIGH",
        category_terms=("ryzovy papier",),
        title_phrases=("ryzovy papier",),
    ),
    FamilyRule(
        rule_id="rice_noodles",
        family="noodles",
        subfamily="rice_noodles",
        confidence="HIGH",
        category_terms=("ryzove rezance",),
        title_phrases=("ryzove rezance", "ryzovymi rezancami", "ryzovych rezancov"),
        attributes=(("ingredient_base", "rice"),),
    ),
    FamilyRule(
        rule_id="rice_vinegar",
        family="vinegar",
        subfamily="rice_vinegar",
        confidence="HIGH",
        title_phrases=("ryzovy ocot",),
        attributes=(("source", "rice"),),
    ),
    FamilyRule(
        rule_id="rice_flour",
        family="flour",
        subfamily="rice_flour",
        confidence="HIGH",
        title_phrases=("ryzova muka", "muka z ryze", "muka z lepkavej ryze"),
        attributes=(("ingredient_base", "rice"),),
    ),
    FamilyRule(
        rule_id="rice_wine",
        family="beverages",
        subfamily="rice_wine",
        confidence="MEDIUM",
        title_phrases=("ryzove vino", "makgeolli"),
        attributes=(("source", "rice"),),
    ),
    FamilyRule(
        rule_id="rice_drink",
        family="beverages",
        subfamily="rice_drink",
        confidence="MEDIUM",
        title_phrases=("ryzovy napoj",),
        attributes=(("source", "rice"),),
    ),
    FamilyRule(
        rule_id="sushi_rice",
        family="rice",
        subfamily="sushi_rice",
        confidence="HIGH",
        category_terms=("sushi_rice_category",),
        title_phrases=("susi ryza", "ryza na susi", "sushi ryza"),
        attributes=(("use_case", "sushi"),),
    ),
    FamilyRule(
        rule_id="jasmine_rice",
        family="rice",
        subfamily="plain_rice",
        confidence="HIGH",
        category_terms=("jazminova ryza",),
        title_phrases=("jazminova ryza",),
        attributes=(("variety", "jasmine"),),
    ),
    FamilyRule(
        rule_id="basmati_rice",
        family="rice",
        subfamily="plain_rice",
        confidence="HIGH",
        category_terms=("basmati ryza",),
        title_phrases=("basmati ryza",),
        attributes=(("variety", "basmati"),),
    ),
    FamilyRule(
        rule_id="glutinous_rice",
        family="rice",
        subfamily="plain_rice",
        confidence="HIGH",
        title_phrases=("lepkava ryza", "lepkavej ryze", "lepkavu ryzu"),
        attributes=(("variety", "glutinous"),),
    ),
    FamilyRule(
        rule_id="plain_rice",
        family="rice",
        subfamily="plain_rice",
        confidence="HIGH",
        category_terms=("ryza",),
        title_phrases=("ryza", "ryzu", "ryze", "ryzou", "ryzi"),
    ),
]


@dataclass(slots=True)
class ProductTaxonomy:
    product_id: str
    canonical_family: str | None = None
    canonical_subfamily: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    dietary_facets: list[str] = field(default_factory=list)
    cuisine_facets: list[str] = field(default_factory=list)
    use_case_facets: list[str] = field(default_factory=list)
    commercial_facets: list[str] = field(default_factory=list)
    merchandising_facets: list[str] = field(default_factory=list)
    confidence: str = "UNKNOWN"
    evidence: list[str] = field(default_factory=list)
    taxonomy_version: int = TAXONOMY_VERSION


def _facets_from_category_memberships(category_memberships: Iterable[str]) -> tuple[list[str], list[str]]:
    """Split cross-cutting category labels into (dietary_facets, merchandising_facets).

    These labels dominate the catalog by raw count but are attribute
    facets, not product identity (docs/product-taxonomy-audit.md, Fáza 1).
    """
    dietary: list[str] = []
    merchandising: list[str] = []
    for raw in category_memberships:
        normalized = search_normalize(raw)
        if normalized in _DIETARY_CATEGORY_TERMS:
            dietary.append(_DIETARY_CATEGORY_TERMS[normalized])
        elif normalized in _MERCHANDISING_CATEGORY_TERMS:
            merchandising.append(_MERCHANDISING_CATEGORY_TERMS[normalized])
    return dietary, merchandising


def classify_product(product: Product) -> ProductTaxonomy:
    """Deterministic per-product classification. Pure function, no I/O.

    Evaluates FAMILY_DEFINITIONS in order and returns on the first match.
    A product matching no rule gets canonical_family=None,
    confidence="UNKNOWN" - it stays fully available to legacy search
    (failure/absence of classification never removes a product).
    """
    category_memberships = product.category_memberships
    normalized_categories = {search_normalize(c) for c in category_memberships}
    aliased_categories = {
        CATEGORY_ALIASES[c] for c in normalized_categories if c in CATEGORY_ALIASES
    }
    category_set = normalized_categories | aliased_categories

    normalized_title = search_normalize(product.title)
    url_category = extract_url_category(product.link)

    dietary_facets, merchandising_facets = _facets_from_category_memberships(category_memberships)

    for rule in FAMILY_DEFINITIONS:
        category_hit = next((t for t in rule.category_terms if t in category_set), None)
        title_hit = next((p for p in rule.title_phrases if p in normalized_title), None)

        if category_hit is None and title_hit is None:
            continue

        confidence = rule.confidence if category_hit is not None else _CONFIDENCE_DOWNGRADE[rule.confidence]
        evidence = []
        if category_hit:
            evidence.append(f"category:{category_hit}")
        if title_hit:
            evidence.append(f"title:{title_hit}")
        if url_category:
            evidence.append(f"url_category:{url_category}")

        return ProductTaxonomy(
            product_id=product.id,
            canonical_family=rule.family,
            canonical_subfamily=rule.subfamily,
            attributes=dict(rule.attributes),
            dietary_facets=dietary_facets,
            cuisine_facets=[],
            use_case_facets=[],
            commercial_facets=[],
            merchandising_facets=merchandising_facets,
            confidence=confidence,
            evidence=evidence,
        )

    return ProductTaxonomy(
        product_id=product.id,
        confidence="UNKNOWN",
        dietary_facets=dietary_facets,
        merchandising_facets=merchandising_facets,
    )


def build_taxonomy_index(products: Iterable[Product]) -> dict[str, ProductTaxonomy]:
    """Batch-classify a catalog with per-product failure isolation.

    A single bad product's classification failure must not break the
    refresh (docs/product-taxonomy-audit.md, failure isolation / global
    failure safety) - it just falls back to UNKNOWN and the raw product
    stays available to legacy search.
    """
    index: dict[str, ProductTaxonomy] = {}
    failures = 0
    for product in products:
        try:
            index[product.id] = classify_product(product)
        except Exception:
            logger.warning("Product taxonomy classification failed for id=%s", getattr(product, "id", "?"), exc_info=True)
            failures += 1
            index[product.id] = ProductTaxonomy(product_id=getattr(product, "id", ""), confidence="UNKNOWN")

    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    for entry in index.values():
        counts[entry.confidence] = counts.get(entry.confidence, 0) + 1
    logger.info(
        "Taxonomy index built: %d products, HIGH=%d MEDIUM=%d LOW=%d UNKNOWN=%d, failures=%d",
        len(index), counts["HIGH"], counts["MEDIUM"], counts["LOW"], counts["UNKNOWN"], failures,
    )
    return index


def get_taxonomy(index: dict[str, ProductTaxonomy], product_id: str) -> ProductTaxonomy | None:
    return index.get(product_id)


def find_by_family(index: dict[str, ProductTaxonomy], family: str) -> list[str]:
    """Product ids whose canonical_family matches - the structural query
    future retrieval code needs instead of re-tokenizing product_type."""
    return [pid for pid, tax in index.items() if tax.canonical_family == family]


def find_by_attributes(index: dict[str, ProductTaxonomy], **constraints: str) -> list[str]:
    """Product ids matching every given attribute constraint (AND)."""
    return [
        pid for pid, tax in index.items()
        if all(tax.attributes.get(key) == value for key, value in constraints.items())
    ]


def taxonomy_coverage(index: dict[str, ProductTaxonomy]) -> dict:
    """Aggregate stats for docs/product-taxonomy-audit.md (Fáza: coverage)."""
    total = len(index)
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    families: dict[str, int] = {}
    subfamilies: dict[str, int] = {}
    for tax in index.values():
        counts[tax.confidence] = counts.get(tax.confidence, 0) + 1
        if tax.canonical_family:
            families[tax.canonical_family] = families.get(tax.canonical_family, 0) + 1
        if tax.canonical_subfamily:
            subfamilies[tax.canonical_subfamily] = subfamilies.get(tax.canonical_subfamily, 0) + 1
    classified = total - counts["UNKNOWN"]
    return {
        "total_products": total,
        "classified_products": classified,
        "taxonomy_coverage": (classified / total) if total else 0.0,
        "confidence_counts": counts,
        "canonical_family_count": len(families),
        "canonical_subfamily_count": len(subfamilies),
        "families": families,
        "subfamilies": subfamilies,
    }
