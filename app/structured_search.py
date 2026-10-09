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
from app.query_constraints import PriceConstraint, StructuredProductQuery, merge_constraints, parse_structured_query
from app.ranking import rank_candidates
from app.ranking_config import RankingProfile
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
    ranking_profile: RankingProfile | None = None,
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
            ranking_profile=ranking_profile,
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
    ranking_profile: RankingProfile | None = None,
    remove_size: bool = False,
    remove_brand: bool = False,
    price_direction: str | None = None,
    price_constraint: PriceConstraint | None = None,
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

    `price_direction` (V2.9 Section 20) - "niečo lacnejšie"/"drahšie" also
    carries no family/brand/size of its own, so it must ALSO force the
    narrowing merge (otherwise the bare phrase has nothing to retrieve
    against and falls through to a nonsensical legacy lexical search on
    the words "niečo"/"lacnejšie" themselves - a real regression caught
    by live multi-turn testing, spec Section 79). Re-ranks the already-
    valid candidate set by price after V2.4 ranking (Section 20 - never
    changes eligibility, only final order).

    `price_constraint` (V2.27h, V2.27a-g read-only architecture/contract
    review series, docs/query-semantics.md) - an ABSOLUTE EUR hard
    eligibility bound, semantically different from `price_direction`
    above: filters `result`'s own id-lists (exact/valid/nearest) BEFORE
    rank_candidates() ever sees them, so ranking only ever orders an
    already-eligible set and matching_total (app.presentation.
    build_result_set(), derived from exact_match_ids) is automatically
    correct too - one filtering step fixes both. Also makes Show-More/
    Show-All continuation correct for free: app.main._execute_resultset_
    continuation() pages purely over whatever ranked_product_ids was
    persisted on the ResultSet at creation time, with no re-filtering,
    so filtering here (before that ResultSet is ever built) is
    sufficient on its own. If every candidate is filtered out, returns
    None - reuses the exact existing empty-bailout convention above
    (each of this function's two call sites in app/main.py already has
    its own pre-existing fallback for that case)."""
    try:
        index = get_structured_index(products, taxonomy_index, normalized_index)
        parsed = parse_structured_query(query_text, known_brands=index.known_brands)
        should_merge = base_query is not None and parsed.family is None and (
            parsed.brand or parsed.package_size or parsed.dietary_facets or remove_size or remove_brand or price_direction
        )
        if should_merge:
            query = merge_constraints(base_query, parsed, remove_size=remove_size, remove_brand=remove_brand)
        else:
            query = parsed

        result = retrieve_products(query, index)
        if result.retrieval_mode == LEGACY_FALLBACK or not (result.valid_match_ids or result.nearest_match_ids):
            _log_shadow(result, legacy_fallback_used=True)
            return None

        if price_constraint is not None:
            price_by_id = {product.id: product.effective_price for product in products}

            def _price_eligible(product_id: str) -> bool:
                price = price_by_id.get(product_id)
                return price is not None and price <= price_constraint.price_max

            result.exact_match_ids = [pid for pid in result.exact_match_ids if _price_eligible(pid)]
            result.valid_match_ids = [pid for pid in result.valid_match_ids if _price_eligible(pid)]
            result.nearest_match_ids = [pid for pid in result.nearest_match_ids if _price_eligible(pid)]
            if not (result.valid_match_ids or result.nearest_match_ids):
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
            ranking_profile=ranking_profile,
        )
        if price_direction:
            from app.session_state import rank_by_price_direction
            reranked = rank_by_price_direction([products_by_id[pid] for pid in ranked_ids if pid in products_by_id], price_direction)
            ranked_ids = [product.id for product in reranked]
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
    the shape of the retrieval decision. V2.12.4: the same fields are also
    stashed (not written anywhere yet - a plain ContextVar assignment,
    Section 68 near-zero overhead) for app.main to durably record as a
    SearchQualityTrace, but ONLY for real customer requests - that gate
    lives entirely in app.main, this function has no execution-context
    awareness and must not decide it (Invariant #5)."""
    query: StructuredProductQuery = result.interpretation
    family = getattr(query, "family", None)
    constraint_count = len(getattr(query, "explicit_constraints", ()) or ())
    exact_count = len(result.exact_match_ids)
    valid_count = len(result.valid_match_ids)
    nearest_count = len(result.nearest_match_ids)
    zero_exact_match = not result.exact_match_ids and bool(result.valid_match_ids)
    logger.info(
        "structured_retrieval mode=%s family=%s constraint_count=%d exact=%d valid=%d nearest=%d "
        "legacy_fallback_used=%s zero_exact_match=%s",
        result.retrieval_mode, family, constraint_count, exact_count, valid_count, nearest_count,
        legacy_fallback_used, zero_exact_match,
    )
    from app.search_quality import stash_retrieval_decision
    stash_retrieval_decision(
        mode=result.retrieval_mode,
        family=family,
        constraint_count=constraint_count,
        exact_count=exact_count,
        valid_count=valid_count,
        nearest_count=nearest_count,
        legacy_fallback_used=legacy_fallback_used,
        zero_exact_match=zero_exact_match,
    )
