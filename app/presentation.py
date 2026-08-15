"""
app/presentation.py  -  V2.5 Presentation Policy

Turns a V2.4 RetrievalResult + ranked ids into a ResultSet: which answer
strategy applies, how many products to show initially, and (for broad
queries) which semantic groups exist with real counts. This module NEVER
changes product membership (Section 2/89) - it only decides how much of
an already-computed valid set to reveal, and how to describe it.

matching_total always equals len(exact_match_ids) (Section 5): when a
query has no explicit brand/size, V2.4's retrieve_products() sets
exact_match_ids == valid_match_ids (nothing to relax), so this is the
same number either way; when relaxation happened (NO_EXACT_MATCH),
exact_match_ids is empty and nearest_match_ids is reported as a
separate, explicitly-labeled tier (Section 22) - never folded into the
primary count.
"""
from __future__ import annotations

import time

from app.result_sets import ResultSet, create_result_set
from app.taxonomy import FAMILY_DEFINITIONS_BY_ID, ProductTaxonomy

# --- answer strategies (Section 23) ----------------------------------------
EXACT_MATCH = "EXACT_MATCH"
FILTERED_PRODUCT_LIST = "FILTERED_PRODUCT_LIST"
GROUPED_DISCOVERY = "GROUPED_DISCOVERY"
NO_EXACT_MATCH = "NO_EXACT_MATCH"
# Strategies intentionally NOT auto-selected by this module this sprint -
# they already have dedicated, tested legacy detectors/handlers in
# app/main.py (comparison, use-case advice, recommendation, replacement,
# recipe shopping) and folding them into ResultSet is a larger, separate
# effort than "make V2.4 retrieval pageable" (Section 52 - controlled
# activation, legacy workflows keep their current presentation for now).

# Initial display size per strategy (Section 6).
INITIAL_DISPLAY_SIZES: dict[str, int] = {
    EXACT_MATCH: 3,
    FILTERED_PRODUCT_LIST: 4,
    GROUPED_DISCOVERY: 5,  # number of GROUPS shown initially, not products
    NO_EXACT_MATCH: 3,  # nearest matches shown
}
DEFAULT_INITIAL_DISPLAY = 4

PAGE_SIZES: dict[str, int] = {
    EXACT_MATCH: 3,
    FILTERED_PRODUCT_LIST: 4,
    NO_EXACT_MATCH: 3,
}
DEFAULT_PAGE_SIZE = 4

# Minimum distinct concepts for a broad family query to prefer grouped
# discovery over a flat filtered list (Section 15/59).
MIN_GROUPS_FOR_DISCOVERY = 2


def decide_answer_strategy(retrieval_result, query) -> str:
    """retrieval_result: app.retrieval.RetrievalResult: query:
    app.query_constraints.StructuredProductQuery. Both already computed
    by V2.4 - this function only reads them, never re-derives constraints."""
    if not retrieval_result.exact_match_ids and retrieval_result.nearest_match_ids:
        return NO_EXACT_MATCH

    has_p3_explicit = bool({"brand", "package_size"} & query.explicit_constraints)
    has_p2_explicit = bool({"subfamily", "attributes", "dietary_facets"} & query.explicit_constraints)

    if has_p3_explicit:
        return EXACT_MATCH if len(retrieval_result.exact_match_ids) <= 3 else FILTERED_PRODUCT_LIST
    if not has_p2_explicit:
        # Broad family-only query (e.g. "ryža") - prefer grouped discovery
        # when the valid set actually spans multiple distinct concepts.
        return GROUPED_DISCOVERY
    return FILTERED_PRODUCT_LIST


def build_groups(valid_match_ids: list[str], taxonomy_index: dict[str, ProductTaxonomy]) -> list[dict]:
    """Real counts from the CURRENT valid_match_ids set only - never
    hallucinated, never computed over the whole catalog (Section 15)."""
    counts: dict[str, int] = {}
    representative: dict[str, str] = {}
    for product_id in valid_match_ids:
        tax = taxonomy_index.get(product_id)
        if tax is None or not tax.concept_id:
            continue
        counts[tax.concept_id] = counts.get(tax.concept_id, 0) + 1
        representative.setdefault(tax.concept_id, product_id)

    groups: list[dict] = []
    for concept_id, count in counts.items():
        rule = FAMILY_DEFINITIONS_BY_ID.get(concept_id)
        if rule is None or not rule.display_label:
            continue
        groups.append({
            "concept_id": concept_id,
            "label": rule.display_label,
            "family": rule.family,
            "subfamily": rule.subfamily,
            "attributes": dict(rule.attributes),
            "product_count": count,
            "representative_product_id": representative[concept_id],
        })
    groups.sort(key=lambda g: g["product_count"], reverse=True)
    return groups


def build_result_set(
    raw_query: str,
    structured_query,  # StructuredProductQuery
    retrieval_result,  # RetrievalResult
    ranked_ids: list[str],  # already rank_candidates()-ordered primary_ids
    taxonomy_index: dict[str, ProductTaxonomy],
    *,
    catalog_version: int,
    taxonomy_version: int,
    now: float | None = None,
) -> ResultSet:
    now = now if now is not None else time.time()
    strategy = decide_answer_strategy(retrieval_result, structured_query)

    groups: list[dict] = []
    if strategy == GROUPED_DISCOVERY:
        groups = build_groups(retrieval_result.valid_match_ids, taxonomy_index)
        if len(groups) < MIN_GROUPS_FOR_DISCOVERY:
            # Not actually a multi-concept family (e.g. only one rule ever
            # matched this family) - a flat list serves the customer better
            # than a "group" of one.
            strategy = FILTERED_PRODUCT_LIST
            groups = []

    matching_total = len(retrieval_result.exact_match_ids)  # Section 5 - primary only, real PRODUCT count

    if strategy == GROUPED_DISCOVERY:
        # Pagination unit becomes GROUPS, not raw products (Section 17/18):
        # "Show More" on a broad query reveals more group cards, one
        # representative product each. Seeing every product in one group
        # is a GROUP DRILL-DOWN (a fresh, narrower ResultSet via
        # query_from_constraints), not flat pagination over all 78 items.
        pagination_ids = [g["representative_product_id"] for g in groups]
        displayed_count = min(len(pagination_ids), INITIAL_DISPLAY_SIZES[GROUPED_DISCOVERY])
    else:
        pagination_ids = ranked_ids
        displayed_count = min(len(pagination_ids), INITIAL_DISPLAY_SIZES.get(strategy, DEFAULT_INITIAL_DISPLAY))

    return create_result_set(
        raw_query=raw_query,
        structured_query=structured_query,
        answer_strategy=strategy,
        ranked_product_ids=pagination_ids,
        matching_total=matching_total,
        exact_match_ids=retrieval_result.exact_match_ids,
        nearest_match_ids=retrieval_result.nearest_match_ids,
        alternative_ids=[],
        groups=groups,
        displayed_count=displayed_count,
        page_size=PAGE_SIZES.get(strategy, DEFAULT_PAGE_SIZE),
        catalog_version=catalog_version,
        taxonomy_version=taxonomy_version,
        now=now,
    )
