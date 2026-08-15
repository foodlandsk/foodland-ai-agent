"""
app/retrieval.py  -  V2.4 Structured Retrieval & Category-Aware Ranking

Implements the target flow from the V2.4 spec:

    StructuredProductQuery -> Candidate Retrieval -> Semantic Validation
        -> ALL VALID MATCHES -> Category-Aware Ranking -> Ranked ResultSet

Retrieval (which products satisfy the request) and ranking (what order they
appear in) are strictly separate modules (app.ranking does the latter) -
Section 2 of the spec. This module only ever narrows a candidate set by
constraint intersection; it never scores or reorders.

Hybrid by construction, not by exception: the structured index is built
ONLY from products whose V2.3 taxonomy confidence is HIGH or MEDIUM
(Section 10) - a LOW-confidence or UNKNOWN product simply never enters
`family_index`/`subfamily_index`/`attribute_index`, so it can never be
returned as a false-positive "exact" or "valid" structured match, and it
stays fully reachable through the existing legacy `search_products()` path
(Section 11/39/71/72 - UNKNOWN/LOW must never disappear from the catalog).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.feed import Product
from app.product_normalizer import NormalizedProduct, PackageSize
from app.taxonomy import TAXONOMY_VERSION, ProductTaxonomy

logger = logging.getLogger(__name__)

# --- retrieval modes (Section 12) -----------------------------------------
STRUCTURED_EXACT = "STRUCTURED_EXACT"
STRUCTURED_FILTERED = "STRUCTURED_FILTERED"
STRUCTURED_BROAD = "STRUCTURED_BROAD"
HYBRID = "HYBRID"
LEGACY_FALLBACK = "LEGACY_FALLBACK"

# Only these taxonomy confidence tiers are trusted for hard structured
# filtering (Section 10). LOW/UNKNOWN products are excluded from every
# index below and rely entirely on legacy search - never hard-filtered
# away, never falsely included as a structured "exact"/"valid" match.
_STRUCTURED_CONFIDENCE_TIERS = {"HIGH", "MEDIUM"}

_MASS_UNITS = {"g", "kg"}
_VOLUME_UNITS = {"ml", "l"}
_UNIT_TO_BASE = {"g": 1.0, "kg": 1000.0, "ml": 1.0, "l": 1000.0}


@dataclass(slots=True)
class StructuredProductIndex:
    """Compact inverted index: structured value -> product ids. Stores ids
    only, never duplicated Product data (Section 57/92)."""

    family_index: dict[str, set[str]] = field(default_factory=dict)
    subfamily_index: dict[str, set[str]] = field(default_factory=dict)
    attribute_index: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    brand_index: dict[str, set[str]] = field(default_factory=dict)
    dietary_index: dict[str, set[str]] = field(default_factory=dict)
    size_index: dict[tuple[str, float], set[str]] = field(default_factory=dict)
    confidence_by_id: dict[str, str] = field(default_factory=dict)
    known_brands: frozenset[str] = frozenset()


def build_structured_index(
    products: list[Product],
    taxonomy_index: dict[str, ProductTaxonomy],
    normalized_index: dict[str, NormalizedProduct],
) -> StructuredProductIndex:
    index = StructuredProductIndex()
    brands: set[str] = set()

    for product in products:
        product_id = product.id
        tax = taxonomy_index.get(product_id)
        if tax is None or tax.confidence not in _STRUCTURED_CONFIDENCE_TIERS:
            continue
        index.confidence_by_id[product_id] = tax.confidence

        if tax.canonical_family:
            index.family_index.setdefault(tax.canonical_family, set()).add(product_id)
        if tax.canonical_subfamily:
            index.subfamily_index.setdefault(tax.canonical_subfamily, set()).add(product_id)
        for key, value in tax.attributes.items():
            index.attribute_index.setdefault((key, value), set()).add(product_id)
        for facet in tax.dietary_facets:
            index.dietary_index.setdefault(facet, set()).add(product_id)

        normalized = normalized_index.get(product_id)
        if normalized and normalized.brand_normalized:
            index.brand_index.setdefault(normalized.brand_normalized, set()).add(product_id)
            brands.add(normalized.brand_normalized)
        if normalized:
            size_base = _size_to_base(normalized.package_size)
            if size_base is not None:
                index.size_index.setdefault(size_base, set()).add(product_id)

    index.known_brands = frozenset(brands)
    return index


_structured_index_cache: dict[tuple[int, int], StructuredProductIndex] = {}


def get_structured_index(
    products: list[Product],
    taxonomy_index: dict[str, ProductTaxonomy],
    normalized_index: dict[str, NormalizedProduct],
) -> StructuredProductIndex:
    """Cached by products-list identity, same pattern as app.search's
    caches - a feed/taxonomy refresh builds a new `products` list, so this
    invalidates automatically without an explicit cache-clear call
    (Section 54/55)."""
    key = (id(products), len(products))
    cached = _structured_index_cache.get(key)
    if cached is None:
        cached = build_structured_index(products, taxonomy_index, normalized_index)
        if len(_structured_index_cache) > 4:
            _structured_index_cache.clear()
        _structured_index_cache[key] = cached
    return cached


def _size_to_base(size: PackageSize) -> tuple[str, float] | None:
    """(unit_class, canonical_value) - mass in grams, volume in millilitres.
    Never equates mass and volume (Section 22)."""
    if not size.is_structured:
        return None
    unit_class = "mass" if size.unit in _MASS_UNITS else "volume" if size.unit in _VOLUME_UNITS else None
    if unit_class is None:
        return None
    return unit_class, size.value * _UNIT_TO_BASE[size.unit]


def size_matches(product_size: PackageSize | None, query_size: PackageSize) -> bool:
    """Exact-tier size match only (Section 21/67): 1000 g == 1 kg, 500 ml
    != 1 l. An unparseable/ambiguous product size never satisfies this -
    it simply isn't an exact match on size (Section 15), not an excluded
    product (it can still be a VALID/NEAREST match on other constraints)."""
    if product_size is None:
        return False
    product_base = _size_to_base(product_size)
    query_base = _size_to_base(query_size)
    if product_base is None or query_base is None:
        return False
    (p_class, p_value), (q_class, q_value) = product_base, query_base
    if p_class != q_class:
        return False
    return abs(p_value - q_value) < 1e-6


@dataclass
class RetrievalResult:
    """Section 27/28 - keeps EXACT/VALID/NEAREST/ALTERNATIVE semantically
    distinct rather than collapsing everything into one products[] list.
    All valid ids are retained here, uncapped (Section 13/45/60) -
    presentation limiting is a caller/UI concern, not a retrieval one."""

    raw_query: str = ""
    interpretation: object = None  # StructuredProductQuery
    retrieval_mode: str = LEGACY_FALLBACK

    exact_match_ids: list[str] = field(default_factory=list)
    valid_match_ids: list[str] = field(default_factory=list)
    nearest_match_ids: list[str] = field(default_factory=list)
    alternative_candidate_ids: list[str] = field(default_factory=list)

    matching_total: int = 0

    applied_constraints: list[str] = field(default_factory=list)
    relaxed_constraints: list[str] = field(default_factory=list)

    confidence: str = "UNKNOWN"
    taxonomy_version: int = TAXONOMY_VERSION
    catalog_version: int = 0


def retrieve_products(
    query,  # StructuredProductQuery - typed loosely to avoid a circular import
    index: StructuredProductIndex,
    *,
    catalog_version: int = 0,
) -> RetrievalResult:
    """Pure set-intersection retrieval (Section 58) - no scoring here.

    A product belongs to `valid_match_ids` because it satisfies every P1
    (identity) and P2 (selection) constraint the query actually carries;
    `exact_match_ids` additionally satisfies every explicit P3 (brand/size)
    constraint. Ranking (app.ranking) only ever reorders within these sets -
    it can never add or remove a member (Section 14/73)."""
    result = RetrievalResult(raw_query=query.raw_query, interpretation=query, catalog_version=catalog_version, confidence=query.confidence)

    if not query.family or query.family not in index.family_index:
        result.retrieval_mode = LEGACY_FALLBACK
        return result

    applied: list[str] = [f"family={query.family}"]
    candidates = set(index.family_index[query.family])

    if "subfamily" in query.explicit_constraints and query.subfamily:
        candidates &= index.subfamily_index.get(query.subfamily, set())
        applied.append(f"subfamily={query.subfamily}")

    if "attributes" in query.explicit_constraints:
        for key, value in query.attributes.items():
            candidates &= index.attribute_index.get((key, value), set())
            applied.append(f"attribute:{key}={value}")

    if "dietary_facets" in query.explicit_constraints:
        # Safety/relevance-critical (Section 19): hard-filtered, not scored.
        for facet in query.dietary_facets:
            candidates &= index.dietary_index.get(facet, set())
            applied.append(f"dietary={facet}")

    valid_ids = candidates
    result.valid_match_ids = sorted(valid_ids)
    result.matching_total = len(valid_ids)
    result.applied_constraints = applied

    brand_ids: set[str] | None = None
    if "brand" in query.explicit_constraints and query.brand:
        brand_ids = index.brand_index.get(query.brand, set())

    size_ids: set[str] | None = None
    if "package_size" in query.explicit_constraints and query.package_size is not None:
        query_base = _size_to_base(query.package_size)
        size_ids = index.size_index.get(query_base, set()) if query_base is not None else set()

    exact_ids = set(valid_ids)
    if brand_ids is not None:
        exact_ids &= brand_ids
    if size_ids is not None:
        exact_ids &= size_ids

    if exact_ids:
        result.exact_match_ids = sorted(exact_ids)
    else:
        # Deterministic staged relaxation (Section 17/18): keep product
        # identity (family/subfamily/attributes/dietary - already fixed in
        # valid_ids) always; relax package_size before brand, since brand
        # is typically the stronger, more identity-adjacent explicit
        # signal ("Kikkoman soy sauce" vs "soy sauce 1 l"). Try each single
        # relaxation before giving up and relaxing both.
        candidates_by_relaxation: list[tuple[list[str], set[str]]] = []
        if brand_ids is not None and size_ids is not None:
            candidates_by_relaxation = [
                (["package_size"], set(valid_ids) & brand_ids),
                (["brand"], set(valid_ids) & size_ids),
                (["brand", "package_size"], set(valid_ids)),
            ]
        elif brand_ids is not None:
            candidates_by_relaxation = [(["brand"], set(valid_ids))]
        elif size_ids is not None:
            candidates_by_relaxation = [(["package_size"], set(valid_ids))]

        chosen_relaxed: list[str] = []
        chosen_ids: set[str] = set()
        for relaxed_fields, candidate_set in candidates_by_relaxation:
            if candidate_set:
                chosen_relaxed, chosen_ids = relaxed_fields, candidate_set
                break

        result.exact_match_ids = []
        result.nearest_match_ids = sorted(chosen_ids)
        result.relaxed_constraints = [
            f"{field}={getattr(query, field) if field != 'package_size' else f'{query.package_size.value}{query.package_size.unit}'}"
            for field in chosen_relaxed
        ]

    has_p3_explicit = bool({"brand", "package_size"} & query.explicit_constraints)
    has_p2_explicit = bool({"subfamily", "attributes", "dietary_facets"} & query.explicit_constraints)
    if has_p3_explicit:
        result.retrieval_mode = STRUCTURED_EXACT
    elif has_p2_explicit:
        result.retrieval_mode = STRUCTURED_FILTERED
    else:
        result.retrieval_mode = STRUCTURED_BROAD

    return result

