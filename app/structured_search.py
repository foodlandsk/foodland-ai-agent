"""
app/structured_search.py  -  V2.4 entry point: Structured Retrieval + Ranking

Ties together the pipeline the V2.4 spec describes:

    query text -> StructuredProductQuery (app.query_constraints)
               -> RetrievalResult        (app.retrieval)
               -> ranked product ids     (app.ranking)
               -> formatted product dicts (app.search.format_product)

`hybrid_search_products()` is the drop-in replacement for a
`search_products(products, query, limit) -> list[dict]` call site: same
signature shape, same return shape, safe fallback to the caller-supplied
legacy search function whenever structured retrieval cannot confidently
answer the query or raises unexpectedly (Section 39/82 - structured
retrieval must never be a single point of failure).

`retrieve_products_for_query()` exposes the full RetrievalResult (all
valid ids, not just the top `limit`) for future callers - workflows,
Show More/Show All in V2.5 - that need the complete structured answer
rather than a formatted top-N list (Section 27/45/84).
"""
from __future__ import annotations

import logging
from typing import Callable

from app.feed import Product
from app.presentation import build_result_set
from app.product_normalizer import NormalizedProduct
from app.query_constraints import StructuredProductQuery, merge_constraints, parse_structured_query
from app.ranking import rank_candidates
from app.result_sets import ResultSet
from app.retrieval import (
    LEGACY_FALLBACK,
    RetrievalResult,
    get_structured_index,
    retrieve_products,
)
from app.search import format_product
from app.taxonomy import ProductTaxonomy

logger = logging.getLogger(__name__)


def retrieve_products_for_query(
    query_text: str,
    products: list[Product],
    taxonomy_index: dict[str, ProductTaxonomy],
    normalized_index: dict[str, NormalizedProduct],
) -> RetrievalResult:
    """The `retrieve_products(structured_query, context)`-shaped API
    Section 84 asks for - suitable for a future workflow to call directly
    without going through the chat-facing formatting/fallback path below."""
    index = get_structured_index(products, taxonomy_index, normalized_index)
    query = parse_structured_query(query_text, known_brands=index.known_brands)
    return retrieve_products(query, index)


def hybrid_search_products(
    products: list[Product],
    taxonomy_index: dict[str, ProductTaxonomy],
    normalized_index: dict[str, NormalizedProduct],
    query_text: str,
    limit: int,
    *,
    legacy_search_fn: Callable[[list[Product], str, int], list[dict]],
    behavioral_rankings: dict | None = None,
    merchandising_rules: dict | None = None,
    personalization_scores: dict[str, float] | None = None,
) -> list[dict]:
    """Structured retrieval where the taxonomy confidently recognizes the
    query's family; legacy `legacy_search_fn` (e.g. main.cached_search_products)
    otherwise or on any internal error (Section 39/82)."""
    try:
        index = get_structured_index(products, taxonomy_index, normalized_index)
        query = parse_structured_query(query_text, known_brands=index.known_brands)
        result = retrieve_products(query, index)

        if result.retrieval_mode == LEGACY_FALLBACK or not result.valid_match_ids:
            _log_shadow(result, legacy_fallback_used=True)
            return legacy_search_fn(products, query_text, limit)

        primary_ids = result.exact_match_ids or result.nearest_match_ids or result.valid_match_ids
        products_by_id = {product.id: product for product in products}
        ranked_ids = rank_candidates(
            primary_ids,
            query,
            products_by_id,
            index,
            normalized_index,
            behavioral_rankings=behavioral_rankings,
            merchandising_rules=merchandising_rules,
            personalization_scores=personalization_scores,
        )
        results = [format_product(products_by_id[pid]) for pid in ranked_ids[:limit] if pid in products_by_id]
        if not results:
            _log_shadow(result, legacy_fallback_used=True)
            return legacy_search_fn(products, query_text, limit)

        _log_shadow(result, legacy_fallback_used=False)
        return results
    except Exception:
        logger.warning("Structured retrieval failed for query %r, falling back to legacy search.", query_text[:80], exc_info=True)
        return legacy_search_fn(products, query_text, limit)


def build_structured_result_set(
    query_text: str,
    products: list[Product],
    taxonomy_index: dict[str, ProductTaxonomy],
    normalized_index: dict[str, NormalizedProduct],
    *,
    catalog_version: int,
    taxonomy_version: int,
    now: float,
    base_query: StructuredProductQuery | None = None,
    behavioral_rankings: dict | None = None,
    merchandising_rules: dict | None = None,
    personalization_scores: dict[str, float] | None = None,
    remove_size: bool = False,
    remove_brand: bool = False,
) -> ResultSet | None:
    """V2.5 entry point: builds a full, pageable ResultSet, or None when
    structured retrieval cannot confidently answer this query (caller
    should fall back to the existing legacy chat answer path - Section 39/82).

    `base_query` is the previous turn's StructuredProductQuery (from an
    active session ResultSet) - if the NEW message parses with no family
    of its own but DOES carry a brand/size/dietary constraint, it is
    treated as a narrowing follow-up (Section 13) rather than a fresh,
    unrelated search.

    `remove_size`/`remove_brand` (V2.9 Section 10/21) - explicit customer
    removal ("na veľkosti nezáleží"/"nemusí byť Kikkoman") forces a merge
    against `base_query` even though the removal phrase itself carries no
    positive brand/size/dietary attribute of its own to trigger the usual
    narrowing check.
    """
    try:
        index = get_structured_index(products, taxonomy_index, normalized_index)
        parsed = parse_structured_query(query_text, known_brands=index.known_brands)
        should_merge = base_query is not None and parsed.family is None and (
            parsed.brand or parsed.package_size or parsed.dietary_facets or remove_size or remove_brand
        )
        if should_merge:
            query = merge_constraints(base_query, parsed, remove_size=remove_size, remove_brand=remove_brand)
        else:
            query = parsed

        result = retrieve_products(query, index)
        if result.retrieval_mode == LEGACY_FALLBACK or not (result.valid_match_ids or result.nearest_match_ids):
            _log_shadow(result, legacy_fallback_used=True)
            return None

        primary_ids = result.exact_match_ids or result.nearest_match_ids or result.valid_match_ids
        products_by_id = {product.id: product for product in products}
        ranked_ids = rank_candidates(
            primary_ids,
            query,
            products_by_id,
            index,
            normalized_index,
            behavioral_rankings=behavioral_rankings,
            merchandising_rules=merchandising_rules,
            personalization_scores=personalization_scores,
        )
        _log_shadow(result, legacy_fallback_used=False)
        return build_result_set(
            query_text,
            query,
            result,
            ranked_ids,
            taxonomy_index,
            catalog_version=catalog_version,
            taxonomy_version=taxonomy_version,
            now=now,
        )
    except Exception:
        logger.warning("Structured presentation failed for query %r, caller should fall back.", query_text[:80], exc_info=True)
        return None


def format_result_set_products(products: list[Product], product_ids: list[str]) -> list[dict]:
    """Formats a slice of a ResultSet's ranked_product_ids into the same
    dict shape app.search.format_product() already produces everywhere
    else - drop-in compatible with the existing `products` response field."""
    products_by_id = {product.id: product for product in products}
    return [format_product(products_by_id[pid]) for pid in product_ids if pid in products_by_id]


def _log_shadow(result: RetrievalResult, *, legacy_fallback_used: bool) -> None:
    """Section 61 analytics fields, as a structured log line - no PII, just
    the shape of the retrieval decision."""
    query: StructuredProductQuery = result.interpretation
    logger.info(
        "structured_retrieval mode=%s family=%s constraint_count=%d exact=%d valid=%d nearest=%d "
        "legacy_fallback_used=%s zero_exact_match=%s",
        result.retrieval_mode,
        getattr(query, "family", None),
        len(getattr(query, "explicit_constraints", ()) or ()),
        len(result.exact_match_ids),
        len(result.valid_match_ids),
        len(result.nearest_match_ids),
        legacy_fallback_used,
        not result.exact_match_ids and bool(result.valid_match_ids),
    )
