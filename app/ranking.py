"""
app/ranking.py  -  V2.4 Category-Aware Ranking

Ranks an already-retrieved, already-valid candidate set (app.retrieval).
Never adds or removes a candidate - only reorders (Section 2/14/73 of the
V2.4 spec). Layered, not one opaque score (Section 30): explicit-constraint
satisfaction and semantic/data-quality signals are compared BEFORE any
soft behavioral/personalization/merchandising signal is even looked at, so
those soft layers can only reorder products that are already tied on
everything that matters more (Section 34/35/36/74/75 - popularity and
personalization must never outrank an explicit customer constraint).

Deterministic (Section 46/47): same inputs -> same order, every time, with
product id as the final tie-break.
"""
from __future__ import annotations

from app.behavioral import behavioral_multiplier
from app.feed import Product
from app.merchandising import merchandising_multiplier
from app.product_normalizer import NormalizedProduct
from app.retrieval import StructuredProductIndex, size_matches
from app.search import tokenize

_CONFIDENCE_RANK = {"HIGH": 2, "MEDIUM": 1, "LOW": 0, "UNKNOWN": 0}


def _in_stock(product: Product) -> bool:
    return str(getattr(product, "availability", "")) in {"in_stock", "in stock"}


def _explicit_attribute_hits(
    product_id: str,
    query,
    index: StructuredProductIndex,
    normalized_index: dict[str, NormalizedProduct],
) -> int:
    """Layer 2 (Section 31): how many of the query's EXPLICIT P3
    (commercial/preference) constraints this specific product satisfies.
    P1/P2 constraints are already guaranteed for every member of the
    ranked set by app.retrieval's intersection, so they do not
    differentiate candidates here - only brand/size do."""
    hits = 0
    normalized = normalized_index.get(product_id)
    if "brand" in query.explicit_constraints and query.brand:
        if normalized and normalized.brand_normalized == query.brand:
            hits += 1
    if "package_size" in query.explicit_constraints and query.package_size is not None:
        if normalized and size_matches(normalized.package_size, query.package_size):
            hits += 1
    return hits


def _relevance_score(product: Product, query_tokens: frozenset[str]) -> int:
    """Layer 4: light lexical tie-break over an already-small, already-valid
    candidate set (title/brand token overlap) - not a full catalog fuzzy
    scan (Section 56), just a secondary signal among semantically valid
    products."""
    if not query_tokens:
        return 0
    title_tokens = tokenize(str(getattr(product, "title", "")))
    brand_tokens = tokenize(str(getattr(product, "brand", "")))
    return 2 * len(query_tokens & title_tokens) + len(query_tokens & brand_tokens)


def rank_candidates(
    candidate_ids: list[str],
    query,  # StructuredProductQuery
    products_by_id: dict[str, Product],
    index: StructuredProductIndex,
    normalized_index: dict[str, NormalizedProduct],
    *,
    behavioral_rankings: dict | None = None,
    merchandising_rules: dict | None = None,
    personalization_scores: dict[str, float] | None = None,
) -> list[str]:
    """Returns `candidate_ids` reordered - same set, same length, just a
    different permutation. Never raises on missing optional signals (all
    default to a 1.0/no-op multiplier), matching the safe-fallback
    philosophy the rest of V2 already uses."""
    query_tokens = frozenset(tokenize(query.raw_query)) if getattr(query, "raw_query", "") else frozenset()

    def sort_key(product_id: str):
        product = products_by_id.get(product_id)
        if product is None:
            # Defensive only - retrieval only ever returns ids that exist in
            # the current catalog snapshot it was built from; keeps a stale
            # id from crashing ranking instead of silently vanishing it.
            return (-1, -1, -1, -1, 0.0, product_id)

        l1_confidence = _CONFIDENCE_RANK.get(index.confidence_by_id.get(product_id, "UNKNOWN"), 0)
        l2_explicit_hits = _explicit_attribute_hits(product_id, query, index, normalized_index)
        l3_availability = 1 if _in_stock(product) else 0
        l4_relevance = _relevance_score(product, query_tokens)

        soft = 1.0
        if behavioral_rankings and behavioral_rankings.get("active"):
            soft *= behavioral_multiplier(
                product_id,
                behavioral_rankings["scores"],
                behavioral_rankings["baseline_ctr"],
            )
        if merchandising_rules:
            soft *= merchandising_multiplier(
                str(getattr(product, "brand", "")),
                str(getattr(product, "product_type", "")),
                merchandising_rules,
            )
        if personalization_scores:
            soft *= 1.0 + max(0.0, min(1.0, personalization_scores.get(product_id, 0.0)))

        return (-l1_confidence, -l2_explicit_hits, -l3_availability, -l4_relevance, -soft, product_id)

    return sorted(candidate_ids, key=sort_key)
