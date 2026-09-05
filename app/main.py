from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import random
import re
import secrets
import tempfile
import time
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openai import OpenAI, APIConnectionError, APITimeoutError, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from pydantic import BaseModel, Field

from app.autocomplete import (
    autocomplete_brands,
    autocomplete_categories,
    autocomplete_products,
    autocomplete_questions,
    question_suggestions,
    taxonomy_category_suggestions,
)
from app.embeddings import (
    build_product_embeddings,
    load_embeddings,
    save_embeddings,
    semantic_search,
)
from app.fbt import fbt_recommendations, load_fbt_data
from app.grounding import validate_answer, collect_allowed_urls, collect_allowed_prices
from app.feed import (
    Product,
    load_multilang_feeds,
    load_products_json,
    multilang_translation_index,
    parse_google_merchant_feed,
)
from app.knowledge import (
    best_faq_answer,
    best_product_advice_answer,
    knowledge_context,
    knowledge_summary,
    load_knowledge_json,
    search_knowledge,
)
from app.knowledge_builder import (
    ProductSnapshot,
    build_knowledge,
    build_product_snapshot,
    save_knowledge,
)
from app.search import (
    PHRASE_SYNONYMS,
    autocomplete_suggestions,
    compute_product_facets,
    filter_products,
    format_product,
    fuzzy_hits,
    get_behavioral_rankings,
    get_merchandising_rules,
    normalize,
    products_context,
    raw_tokens,
    search_products,
    strict_product_match,
    tokenize,
    warm_search_indexes,
)
from app.workflows import products_to_cart_candidates
from app.intent import build_customer_intent
from app.taxonomy import classify_rice_query, build_taxonomy_index, taxonomy_coverage, build_concept_index, TAXONOMY_VERSION
from app.product_normalizer import normalize_catalog
from app.structured_search import hybrid_search_products as _hybrid_search_products
from app.structured_search import build_structured_result_set as _build_structured_result_set
from app.structured_search import format_result_set_products as _format_result_set_products
from app.query_constraints import parse_structured_query
from app.ranking_config import get_active_ranking_profile, get_active_ranking_profile_version
from app.ranking_config import CONFIG_DIR as _RANKING_PROFILE_DIR
from app.ranking_config import is_active_profile_degraded as _ranking_profile_degraded
from app.storage_paths import data_dir as _foodland_data_dir
from app.storage_paths import is_data_dir_configured as _foodland_data_dir_configured
from app.storage_paths import resolve_path as _resolve_storage_path
from app.durable_storage import atomic_write_json as _atomic_write_json
from app.admin_auth import require_admin_scope as _require_admin_scope
from app.admin_auth import SCOPE_READ as _SCOPE_READ
from app.admin_auth import SCOPE_OPERATIONS as _SCOPE_OPERATIONS
from app.admin_auth import SCOPE_PROMOTION as _SCOPE_PROMOTION
from app.admin_auth import resolve_token_scope as _resolve_admin_token_scope
from app.execution_context import ExecutionContext as _ExecutionContext
from app.execution_context import customer_context as _customer_context
from app.execution_context import evaluation_context as _evaluation_context
from app.customer_audit import capture_customer_turn as _capture_customer_turn
from app.customer_audit import read_audit_turns as _read_audit_turns
from app.customer_audit import audit_status as _audit_status
from app.customer_qa import qa_status as _qa_status
from app.customer_qa import qa_findings as _qa_findings
from app.customer_qa import qa_conversation as _qa_conversation
from app.customer_qa_reproduction import reproduction_status as _reproduction_status
from app.customer_qa_reproduction import reproduce_offline as _reproduce_offline
from app.customer_qa_reproduction import reproduce_admin_test as _reproduce_admin_test
from app.search_quality import reset_retrieval_decision as _reset_search_quality_decision
from app.search_quality import pop_retrieval_decision as _pop_search_quality_decision
from app.search_quality import build_trace as _build_search_quality_trace
from app.search_quality import record_search_quality_trace as _record_search_quality_trace
from app.search_quality import current_deployment_version as _search_quality_deployment_version
from app.execution_context import admin_test_context as _admin_test_context
from app.search_quality import generate_quality_report as _generate_search_quality_report
from app.search_quality import load_quality_baseline as _load_search_quality_baseline
from app.search_quality import save_quality_baseline as _save_search_quality_baseline
from app.search_quality import load_last_canary_result as _load_last_search_quality_canary
from app.search_quality import save_last_canary_result as _save_last_search_quality_canary
from app.search_quality import canary_anomalies as _search_quality_canary_anomalies
from app.search_quality import load_canary_cases as _load_search_quality_canary_cases
from app.search_quality import run_canaries as _run_search_quality_canaries
from app.turn_resolver import resolve_safety_signal as _resolve_safety_signal
from app.turn_resolver import resolve_action_target_signal as _resolve_action_target_signal
from app.workflow_resolver import resolve_workflow as _resolve_workflow
from app.workflow_resolver import WORKFLOW_ALLERGEN_SAFETY as _WORKFLOW_ALLERGEN_SAFETY
from app.workflow_resolver import WORKFLOW_RELATED_PRODUCTS as _WORKFLOW_RELATED_PRODUCTS
from app.workflow_resolver import reset_last_resolution as _reset_workflow_resolution
from app.workflow_resolver import stash_resolution as _stash_workflow_resolution
from app.workflow_resolver import pop_last_resolution as _pop_workflow_resolution
from app.advisor_engine import advisor_engine as _advisor_engine
from app.advisor_engine import AdvisorRequest as _AdvisorRequest
from app.workflow_executor import execute_resultset_continuation as _execute_resultset_continuation
from app.workflow_executor import execute_allergen_safety as _execute_allergen_safety
from app.workflow_executor import execute_missing_composition as _execute_missing_composition
from app.workflow_executor import execute_faq as _execute_faq
from app.workflow_executor import execute_random_recipe as _execute_random_recipe
from app.workflow_executor import execute_reset as _execute_reset
from app.workflow_executor import execute_out_of_domain as _execute_out_of_domain
from app.workflow_executor import execute_category_discovery as _execute_category_discovery
from app.workflow_executor import execute_recipe as _execute_recipe
from app.workflow_executor import execute_comparison as _execute_comparison
from app.workflow_executor import execute_use_case_advice as _execute_use_case_advice
from app.use_case_advice import has_resolvable_role as _use_case_advice_has_resolvable_role
from app.workflow_executor import execute_basket_completion as _execute_basket_completion
from app.workflow_executor import execute_why_followup as _execute_why_followup
from app.learning_cycle import run_learning_cycle as _run_learning_cycle
from app.learning_cycle import REPORTS_DIR as _LEARNING_REPORTS_DIR
from app.learning_cycle import LEARNING_ENGINE_ENABLED as _LEARNING_ENGINE_ENABLED
from app.learning_cycle import LEARNING_CYCLE_MINUTES as _LEARNING_CYCLE_MINUTES
from app.learning_lifecycle import get_history as _learning_history
from app.learning_lifecycle import get_last_known_good as _learning_last_known_good
from app.learning_lifecycle import AUTO_PROMOTION_ENABLED as _LEARNING_AUTO_PROMOTION_ENABLED
from app.learning_lifecycle import HISTORY_DIR as _LEARNING_HISTORY_DIR
from app.learning_lifecycle import approve_candidate_by_id as _approve_candidate_by_id
from app.learning_lifecycle import rollback_to_last_known_good as _rollback_to_last_known_good
from app.learning_lifecycle import LifecycleError as _LifecycleError
from app.answer_composer import compose_answer as _compose_answer
from app.answer_composer import compose_continuation_answer as _compose_continuation_answer
from app.result_sets import get_result_set as _get_result_set
from app.result_sets import advance_displayed_count as _advance_displayed_count
from app.result_sets import show_all as _show_all_result_set
from app import cross_sell as _cross_sell
from app.answer_composer import compose_cross_sell_intro as _compose_cross_sell_intro
from app.workflow_registry import select_workflow as _select_workflow
from app.workflow_registry import RoutingSignals as _RoutingSignals
from app.recipe_graph import build_recipe_graph_index as _build_recipe_graph_index
from app.recipe_shopping import build_recipe_shopping_plan as _build_recipe_shopping_plan
from app.recipe_shopping import summarize_plan as _summarize_recipe_shopping_plan
from app.ingredients import extract_requested_servings as _extract_requested_servings
from app.ingredients import extract_requested_servings_lenient as _extract_requested_servings_lenient
from app.recipe_shopping import resolve_recipe_followup as _resolve_recipe_followup
from app.recipe_shopping import compose_recipe_followup_answer as _compose_recipe_followup_answer
from app.recipe_shopping import RECIPE_FOLLOWUP_INGREDIENT as _RF_INGREDIENT
from app.recipe_shopping import RECIPE_FOLLOWUP_SELECTED as _RF_SELECTED
from app.recipe_shopping import RECIPE_FOLLOWUP_PLAN_UPDATE as _RF_PLAN_UPDATE
from app.recipe_shopping import STATUS_AVAILABLE as _RF_STATUS_AVAILABLE
from app.session_state import get_active_recipe as _get_active_recipe
from app.session_state import set_active_recipe as _set_active_recipe
from app.session_state import clear_recipe_state as _clear_recipe_state
from app.session_state import detect_reset_request as _detect_reset_request
from app.session_state import apply_reset as _apply_session_reset
from app.session_state import get_active_use_case as _get_active_use_case
from app.session_state import set_active_use_case as _set_active_use_case
from app.session_state import clear_use_case_state as _clear_use_case_state
from app.session_state import mentions_ordinal_reference as _mentions_ordinal_reference
from app.session_state import resolve_ordinal_reference as _resolve_ordinal_reference
from app.session_state import track_presentation as _track_presentation
from app.session_state import detect_size_removal as _detect_size_removal
from app.session_state import detect_brand_removal as _detect_brand_removal
from app.session_state import detect_price_direction as _detect_price_direction
from app.session_state import looks_like_recipe_followup as _looks_like_recipe_followup
from app.session_state import get_last_informational_question as _get_last_informational_question
from app.session_state import set_last_informational_question as _set_last_informational_question
from app.session_state import looks_like_location_reference_followup as _looks_like_location_reference_followup
from app.session_state import looks_like_payment_method_followup as _looks_like_payment_method_followup
from app.session_state import is_opening_hours_query as _is_opening_hours_query
from app.session_state import looks_like_opening_hours_followup as _looks_like_opening_hours_followup
from app.session_state import is_contact_query as _is_contact_query
from app.session_state import looks_like_contact_followup as _looks_like_contact_followup


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class UTF8StaticFiles(StaticFiles):
    ALLOWED_SUFFIXES = {".css", ".html", ".ico", ".js", ".json", ".map", ".txt", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".glb"}
    CHARSET_BY_SUFFIX = {
        ".css": "text/css; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".map": "application/json; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
    }

    def file_response(self, full_path, stat_result, scope, status_code=200):
        suffix = Path(full_path).suffix.lower()
        if suffix not in self.ALLOWED_SUFFIXES:
            raise HTTPException(status_code=404, detail="Static file not found.")

        response = super().file_response(full_path, stat_result, scope, status_code)
        content_type = self.CHARSET_BY_SUFFIX.get(suffix)
        if content_type:
            response.headers["content-type"] = content_type
        return response


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    limit: int = Field(default=6, ge=1, le=12)
    conversation_history: list[dict] = Field(default_factory=list)
    session_id: str = Field(default="", max_length=64)
    client_id: str = Field(default="", max_length=96)


class ProductSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)
    limit: int = Field(default=8, ge=1, le=30)


class ProductSuggestRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=120)
    limit: int = Field(default=8, ge=1, le=12)


class ProductFilterRequest(BaseModel):
    query: str = Field(default="", max_length=300)
    price_min: float | None = Field(default=None, ge=0)
    price_max: float | None = Field(default=None, ge=0)
    brand: list[str] | None = Field(default=None, max_length=20)
    availability: Literal["in_stock", "out_of_stock", "all"] = "all"
    category: list[str] | None = Field(default=None, max_length=20)
    dietary: list[str] | None = Field(default=None, max_length=10)
    limit: int = Field(default=20, ge=1, le=60)


class SearchAutocompleteRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=120)
    limit: int = Field(default=8, ge=1, le=12)
    client_id: str = Field(default="", max_length=96)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)


class MemoryClearRequest(BaseModel):
    client_id: str = Field(default="", max_length=96)


class EventRequest(BaseModel):
    session_id: str = Field(default="", max_length=64)
    client_id: str = Field(default="", max_length=96)
    event_type: Literal[
        "impression",
        "click",
        "add_to_cart",
        # V2.15d.2 (docs/frontend-recommendation-correlation-v2.15d.2.md)
        # - additive, distinct from the legacy "add_to_cart" above
        # (kept unchanged for backward compatibility with
        # app.fbt/app.behavioral/app.learning_signals, which all key
        # off that exact literal string). "add_to_cart_attempt" fires
        # when the customer initiates the cart-add mechanism;
        # "add_to_cart_confirmed" fires ONLY when the host site's own
        # add-to-cart AJAX call authoritatively confirmed success (never
        # from the widget's own fallback-timeout guess) - see
        # app/widget.js submitRealAddToCartForm()'s `authoritative` flag.
        "add_to_cart_attempt",
        "add_to_cart_confirmed",
        "no_result",
        "autocomplete_select",
        "search_submit",
        "conversion",
        "feedback",
    ]
    query: str | None = Field(default=None, max_length=300)
    product_sku: str | None = Field(default=None, max_length=64)
    product_skus: list[str] | None = Field(default=None, max_length=50)
    position: int | None = Field(default=None, ge=0, le=1000)
    rating: int | None = Field(default=None, ge=-1, le=1)
    # V2.15d (docs/recommendation-conversion-correlation-v2.15d.md) -
    # additive, optional correlation fields, additive schema evolution.
    # Existing callers that omit them are completely unaffected.
    # V2.15d.2 (docs/frontend-recommendation-correlation-v2.15d.2.md):
    # app/widget.js now populates interaction_id/decision_id on
    # click/add_to_cart*/impression/no_result events.
    interaction_id: str | None = Field(default=None, max_length=32)
    decision_id: str | None = Field(default=None, max_length=32)
    event_id: str | None = Field(default=None, max_length=64)
    # V2.15e.1 (docs/resultset-continuation-attribution-v2.15e.1.md) -
    # additive, optional. Unlike interaction_id/decision_id (fresh/
    # capability-specific per request), result_set_id is the backend's
    # already-existing, STABLE per-search identifier (app.result_sets.
    # ResultSet.result_set_id) that survives a "Show More"/"Show All"
    # continuation unchanged - see app.workflow_executor.
    # execute_resultset_continuation(), which never re-mints it.
    result_set_id: str | None = Field(default=None, max_length=64)


class EventsPurgeRequest(BaseModel):
    """V2.15d.3 follow-up - surgical removal of specific synthetic/
    test events.jsonl records by EXACT session_id match only (never a
    date-range or wildcard sweep, so this cannot accidentally remove
    unrelated real customer data). `confirm` must be explicitly true -
    a defensive requirement, not a technical necessity, since an empty
    session_ids list is already rejected by min_length."""
    session_ids: list[str] = Field(min_length=1, max_length=50)
    confirm: bool = False


class ApproveCandidateRequest(BaseModel):
    approved_by: str = Field(min_length=1, max_length=120)
    expected_current_config_version: str | None = Field(default=None, max_length=64)


class RollbackRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    triggered_by: str = Field(min_length=1, max_length=120)
    expected_current_config_version: str | None = Field(default=None, max_length=64)


class BasketRecommendRequest(BaseModel):
    skus: list[str] = Field(..., min_length=1, max_length=50)
    limit: int = Field(default=6, ge=1, le=20)
    client_id: str = Field(default="", max_length=96)


def load_products() -> list[Product]:
    json_path = os.getenv("PRODUCTS_JSON_PATH", "data/products.json")
    feed_path = os.getenv("PRODUCT_FEED_PATH", "data/googleMerchant_sk_export.xml")

    if json_path and Path(json_path).exists():
        logger.info("Loading products from JSON: %s", json_path)
        return load_products_json(json_path)
    if Path(feed_path).exists() or feed_path.startswith(("http://", "https://")):
        logger.info("Loading products from feed: %s", feed_path)
        return parse_google_merchant_feed(feed_path)
    logger.warning("No products source found at: %s", json_path or feed_path)
    return []


def load_knowledge() -> dict:
    knowledge_path = os.getenv("KNOWLEDGE_JSON_PATH", "data/knowledge.json")
    try:
        loaded_knowledge = load_knowledge_json(knowledge_path)
        logger.info("Knowledge loaded: %s", loaded_knowledge.get("counts", {}))
        return loaded_knowledge
    except Exception as exc:
        logger.error("Failed to load knowledge from %s: %s", knowledge_path, exc, exc_info=True)
        return {"version": "error", "sections": {}, "counts": {}}


products = load_products()
knowledge = load_knowledge()
last_feed_refresh_at = int(time.time()) if products else None
last_feed_refresh_error: str | None = None
feed_refresh_task: asyncio.Task | None = None
learning_cycle_task: asyncio.Task | None = None
# Knowledge-builder state
product_snapshot: ProductSnapshot = build_product_snapshot(products)
translation_index: dict[str, dict[str, "Product"]] = {}
# V2.1 taxonomy foundation (shadow only - not used by legacy search/routing).
# Rebuilt in lockstep with `products` on every refresh_feed() call.
product_taxonomy_index = build_taxonomy_index(products)
taxonomy_concept_index = build_concept_index(product_taxonomy_index)
# V2.4 structured retrieval (Section 54/55) - rebuilt in lockstep with
# `products`/`product_taxonomy_index` on every refresh_feed() call.
normalized_product_index = normalize_catalog(products)
V2_STRUCTURED_RETRIEVAL_ENABLED = os.getenv("V2_STRUCTURED_RETRIEVAL_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
LEGACY_SEARCH_FAMILY_GUARD_ENABLED = os.getenv("LEGACY_SEARCH_FAMILY_GUARD_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
warm_search_indexes(products)
rate_limit_events: dict[str, deque[float]] = defaultdict(deque)
event_rate_limit_events: dict[str, deque[float]] = defaultdict(deque)
autocomplete_rate_limit_events: dict[str, deque[float]] = defaultdict(deque)
recommend_rate_limit_events: dict[str, deque[float]] = defaultdict(deque)
_top_questions_cache: list[dict] = []
_top_questions_cache_at: float = 0.0
TOP_QUESTIONS_CACHE_SECONDS = int(os.getenv("TOP_QUESTIONS_CACHE_SECONDS", "60"))
_trending_products_cache: list[dict] = []
_trending_products_cache_at: float = 0.0
TRENDING_CACHE_SECONDS = int(os.getenv("TRENDING_CACHE_SECONDS", "300"))
TRENDING_EVENT_WEIGHTS = {"conversion": 8, "add_to_cart": 5, "click": 2, "impression": 1}
_fbt_data_cache: dict | None = None
_fbt_data_cache_at: float = 0.0
FBT_CACHE_SECONDS = int(os.getenv("FBT_CACHE_SECONDS", "300"))
FBT_RECOMMENDATIONS_ENABLED = os.getenv("FBT_RECOMMENDATIONS_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
semantic_search_rate_limit_events: dict[str, deque[float]] = defaultdict(deque)
_product_embeddings_cache: dict[str, list[float]] | None = None
_facets_cache: dict | None = None
_facets_cache_at: float = 0.0
FACETS_CACHE_SECONDS = int(os.getenv("FACETS_CACHE_SECONDS", "600"))
_RATE_LIMIT_MAX_CLIENTS = 50_000  # BUG-02: ochrana pamate – max pocet trackovanych klientov
DEFAULT_RUNTIME_LOG_DIR = _foodland_data_dir()
SESSION_MEMORY_TTL_SECONDS = int(os.getenv("SESSION_MEMORY_TTL_SECONDS", "1800"))
SESSION_MEMORY_MAX_SESSIONS = int(os.getenv("SESSION_MEMORY_MAX_SESSIONS", "20000"))
USER_MEMORY_ENABLED = os.getenv("USER_MEMORY_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
USER_MEMORY_MAX_PROFILES = int(os.getenv("USER_MEMORY_MAX_PROFILES", "50000"))
session_memories: dict[str, dict] = {}
user_memories: dict[str, dict] | None = None
PRODUCT_SEARCH_CACHE_MAX_SIZE = int(os.getenv("PRODUCT_SEARCH_CACHE_MAX_SIZE", "512"))
product_search_cache: dict[tuple[int, str, int], list[dict]] = {}
autocomplete_cache: dict[tuple[int, str, int], list[dict]] = {}


def _exclude_taxonomy_family_mismatches(results: list[dict], query: str, limit: int) -> list[dict]:
    """V2.12.3 Bug C (docs/query-semantics.md): the legacy search_products()
    scorer is additive/OR-based with no taxonomy awareness and no minimum
    token coverage, so PREFIX_SYNONYMS roots shared across unrelated families
    (kokos, ryz/rice, sojov/soy, rezance/noodles) let it surface a different,
    well-classified family alongside the query's own confidently-resolved
    family (e.g. "kokosovy olej" pulling in coconut vinegar/juice/cream).
    This filters exactly that: candidates that resolved to a DIFFERENT known
    canonical_family than the query's own resolved family. It runs inside
    cached_search_products() rather than app/search.py because app.taxonomy
    already imports app.search (search_normalize) - importing app.taxonomy
    back into app/search.py would be circular. Unclassified candidates and
    unresolved/low-confidence queries are left untouched (absence of
    classification never excludes a product, same invariant as
    classify_product()), and filtering never empties an otherwise non-empty
    result set - a partially wrong list beats a hard zero-result regression."""
    if not LEGACY_SEARCH_FAMILY_GUARD_ENABLED or not results:
        return results

    structured = parse_structured_query(query)
    if structured.family is None or structured.confidence not in {"HIGH", "MEDIUM"}:
        return results

    filtered = [
        item
        for item in results
        if (taxonomy := product_taxonomy_index.get(item.get("id"))) is None
        or taxonomy.canonical_family is None
        or taxonomy.canonical_family == structured.family
    ]
    if not filtered:
        return results
    return filtered[:limit]


def cached_search_products(products_list: list[Product] | list[dict], query: str, limit: int = 8) -> list[dict]:
    """Cache repeated catalog scans for hot chat/autocomplete queries."""
    if PRODUCT_SEARCH_CACHE_MAX_SIZE <= 0:
        return _exclude_taxonomy_family_mismatches(search_products(products_list, query, limit), query, limit)

    cache_key = (id(products_list), normalize(query), int(limit))
    cached = product_search_cache.get(cache_key)
    if cached is not None:
        return [dict(product) for product in cached]

    results = _exclude_taxonomy_family_mismatches(search_products(products_list, query, limit), query, limit)
    if len(product_search_cache) >= PRODUCT_SEARCH_CACHE_MAX_SIZE:
        product_search_cache.pop(next(iter(product_search_cache)))
    product_search_cache[cache_key] = [dict(product) for product in results]
    return [dict(product) for product in results]


def hybrid_cached_search_products(query: str, limit: int = 8) -> list[dict]:
    """V2.4 Structured Retrieval & Category-Aware Ranking: uses the V2.3
    taxonomy for families/queries it confidently recognizes, falls back to
    legacy cached_search_products() otherwise or on any internal error
    (Section 39/41/82 - hybrid by construction, never a single point of
    failure). Feature-switchable via V2_STRUCTURED_RETRIEVAL_ENABLED for
    rollback safety (Section 42)."""
    if not V2_STRUCTURED_RETRIEVAL_ENABLED:
        return cached_search_products(products, query, limit)
    return _hybrid_search_products(
        products,
        product_taxonomy_index,
        normalized_product_index,
        query,
        limit,
        legacy_search_fn=cached_search_products,
        behavioral_rankings=get_behavioral_rankings(),
        merchandising_rules=get_merchandising_rules(),
        ranking_profile=get_active_ranking_profile(),
    )


def cached_product_embeddings() -> dict[str, list[float]]:
    global _product_embeddings_cache
    if _product_embeddings_cache is None:
        _product_embeddings_cache = load_embeddings(os.getenv("PRODUCT_EMBEDDINGS_PATH"))
    return _product_embeddings_cache


def clear_embeddings_cache() -> None:
    global _product_embeddings_cache
    _product_embeddings_cache = None


def clear_product_search_cache() -> None:
    global _facets_cache, _facets_cache_at
    product_search_cache.clear()
    autocomplete_cache.clear()
    _facets_cache = None
    _facets_cache_at = 0.0


def get_fbt_data() -> dict:
    global _fbt_data_cache, _fbt_data_cache_at
    now = time.time()
    if _fbt_data_cache is None or now - _fbt_data_cache_at > FBT_CACHE_SECONDS:
        _fbt_data_cache = load_fbt_data()
        _fbt_data_cache_at = now
    return _fbt_data_cache


def clear_fbt_cache() -> None:
    global _fbt_data_cache, _fbt_data_cache_at
    _fbt_data_cache = None
    _fbt_data_cache_at = 0.0


def cached_product_facets(products_list: list[Product] | list[dict]) -> dict:
    global _facets_cache, _facets_cache_at
    now = time.time()
    if _facets_cache is None or now - _facets_cache_at > FACETS_CACHE_SECONDS:
        _facets_cache = compute_product_facets(products_list)
        _facets_cache_at = now
    return _facets_cache


def cached_autocomplete_suggestions(products_list: list[Product] | list[dict], query: str, limit: int = 8) -> list[dict]:
    if PRODUCT_SEARCH_CACHE_MAX_SIZE <= 0:
        return autocomplete_suggestions(products_list, query, limit)

    cache_key = (id(products_list), normalize(query), int(limit))
    cached = autocomplete_cache.get(cache_key)
    if cached is not None:
        return [dict(item) for item in cached]

    results = autocomplete_suggestions(products_list, query, limit)
    if len(autocomplete_cache) >= PRODUCT_SEARCH_CACHE_MAX_SIZE:
        autocomplete_cache.pop(next(iter(autocomplete_cache)))
    autocomplete_cache[cache_key] = [dict(item) for item in results]
    return [dict(item) for item in results]

RELATED_PRODUCT_QUERIES = {
    "vindaloo": [
        "korianderove semienka",
        "horcicove semienka",
        "senovka grecka",
        "susene cili papricky",
        "skorica",
        "bazmati ryza",
    ],
    "cesnak": [
        "sojova omacka",
        "sezamovy olej",
        "miso pasta",
        "gochujang",
        "chili omacka",
        "hoisin omacka",
    ],
    "nakladany_zazvor": [
        "nakladany zazvor", "sushi ryza",
        "nori",
        "wasabi",
        "sojova omacka",
        "ryzovy ocot",
    ],
    "nuoc_cham": [
        "rybacia omacka",
        "ryzovy papier",
        "sweet chili omacka",
        "sriracha",
        "lime",
    ],
    "arasidovy_olej": [
        "arasidovy olej", "sezamovy olej",
        "sojova omacka",
        "sriracha",
        "hoisin omacka",
        "chili omacka",
    ],
    "koriander": [
        "koriander", "citronova trava",
        "rybacia omacka",
        "kokosove mlieko",
        "sweet chili omacka",
        "gochujang",
    ],
    "ssamjang": [
        "ssamjang", "gochujang",
        "doenjang",
        "sezamove semienka",
        "sezamovy olej",
        "hovadzie maso",
    ],
    "mung_fazula": [
        "mung fazula", "sojova omacka",
        "sezamovy olej",
        "rybacia omacka",
        "tofu",
        "koriander",
    ],
    "agar_agar": [
        "agar agar", "kokosove mlieko",
        "matcha",
        "tapiokove perly",
        "ryzova muka",
        "kondenzovane mlieko",
    ],
    "bambusove_vyhanky": [
        "sojova omacka",
        "sezamovy olej",
        "ustricova omacka",
        "shiitake",
        "tofu",
    ],
    "vodne_kastany": [
        "sojova omacka",
        "sezamovy olej",
        "ustricova omacka",
        "tofu",
        "bambusove vyhanky",
    ],
    "ryzove_rezance": [
        "ryzove rezance", "rybacia omacka",
        "sojova omacka",
        "sriracha",
        "kokosove mlieko",
        "sweet chili omacka",
    ],
    "sklenene_rezance": [
        "sklenene rezance", "sojova omacka",
        "sezamovy olej",
        "rybacia omacka",
        "gochujang",
        "shiitake",
    ],
    "shichimi_togarashi": [
        "shichimi togarashi", "sushi ryza",
        "ramen",
        "udon",
        "sezamovy olej",
        "sojova omacka",
    ],
    "furikake": [
        "jazminova ryza",
        "sushi ryza",
        "nori",
        "sezamove semienka",
        "sojova omacka",
    ],
    "kewpie": [
        "kewpie", "sojova omacka",
        "sriracha",
        "gochujang",
        "sezamovy olej",
        "nori",
    ],
    "mentsuyu": [
        "dashi",
        "sojova omacka",
        "mirin",
        "ramen",
        "udon",
    ],
    "natto": [
        "natto", "jazminova ryza",
        "sojova omacka",
        "nori",
        "sezamove semienka",
        "wasabi",
    ],
    "okonomiyaki": [
        "panko strobanka",
        "katsuobushi",
        "nori",
        "kewpie",
        "sojova omacka",
    ],
    "pandan": [
        "pandan", "kokosove mlieko",
        "ryzova muka",
        "kondenzovane mlieko",
        "matcha",
        "agar agar",
    ],
    "lychee": [
        "kokosove mlieko",
        "matcha",
        "tapiokove perly",
        "kondenzovane mlieko",
        "jasminovy caj",
    ],
    "taro": [
        "taro", "kokosove mlieko",
        "ryzova muka",
        "matcha",
        "tapiokove perly",
        "kondenzovane mlieko",
    ],
    "hokkien_rezance": [
        "sojova omacka",
        "sezamovy olej",
        "ustricova omacka",
        "sriracha",
        "miso pasta",
    ],
    "kombu": [
        "kombu", "dashi",
        "miso pasta",
        "sojova omacka",
        "mirin",
        "sake na varen",
    ],
    "yakiniku": [
        "sojova omacka",
        "mirin",
        "sezamovy olej",
        "cesnak",
        "gochujang",
    ],
    "omurice": [
        "jazminova ryza",
        "sojova omacka",
        "kuraci bujon",
        "mirin",
        "ketchup",
    ],
    "chahan": [
        "jazminova ryza",
        "sojova omacka",
        "sezamovy olej",
        "kuraci bujon",
        "mirin",
    ],
    "kimchi_recipe": [
        "gochugaru",
        "gochujang",
        "rybacia omacka",
        "ryzova muka",
        "cervena cili paprika",
        "sezamovy olej",
        "sojova omacka",
    ],
    "ryzovy_ocot": [
        "ryzovy ocot", "sushi ryza",
        "nori",
        "wasabi",
        "sojova omacka",
        "sezamovy olej",
        "nakladany zazvor",
    ],
    "ocot": [
        "cukor",
        "sezamovy olej",
        "sojova omacka",
        "cesnak",
        "cili omacka",
    ],
    "kimchi": [
        "ramen",
        "jazminova ryza",
        "sezamovy olej",
        "gochujang",
        "tofu",
        "kimchi",
    ],
    "sushi": [
        "nori",
        "ryzovy ocot",
        "wasabi",
        "nakladany zazvor",
        "sojova omacka",
        "bezlepkova sojova omacka",
    ],
    "gochujang": [
        "kimchi",
        "sezamovy olej",
        "jazi,nova ryza",
        "sushi ryza",
        "ramen",
        "sojova omacka",
        "gochugaru",
    ],
    "ramen": [
        "ramen rezance",
        "dashi", "bonito",
        "miso pasta",
        "bambusove vyhonky",
        "nori",
        "wakame",
        "sojova omacka", "sezamovy olej",
        "sriracha", "gochujang",
    ],
    "kimchi_ramen": [
        "kimchi ramen", "ramen rezance",
        "kimchi",
        "gochujang",
        "miso pasta",
        "sojova omacka",
        "dashi",
        "wakame",
        "nori",
        "sezamovy olej",
    ],
    "black_rice_salad": [
        "cierna ryza",
        "ryzovy ocot",
        "sezamovy olej",
        "sojova omacka",
        "cili omacka",
    ],
    "jasmine_rice": [
        "jazminova ryza",
    ],
    "kuromame_gohan": [
        "japonska ryza",
        "cierna soja",
        "sojova omacka",
        "mirin",
        "nori",
    ],
    "kari": [
        "kokosove mlieko",
        "jazminova ryza",
        "rybacia omacka",
        "kari pasta cervena",
        "kari pasta zelena",
        "ryzove rezance",
    ],
    "pho": [
        "korenie na pho", "pho korenie",
        "badián", "skorica",
        "bujón",
        "banh pho", "pho rezance", "ryzove rezance",
        "hovadzi bujón", "kuraci bujón",
        "rybacia omacka",
        "koriander", "mung fazulove klicky",
        "hoisin", "sriracha",
        "jazminovy caj", "zeleny caj",
    ],
    "pad_thai": [
        "pad thai", "ryzove rezance",
        "tamarind",
        "rybacia omacka",
        "arasidy",
        "pad thai omacka",
    ],
    "bibimbap": [
        "gochujang",
        "ssamjang",
        "doenjang",
        "sezamovy olej",
        "sezamove semienka",
        "kimchi",
        "jazminova ryza",
    ],
    "gyoza": [
        "gyoza", "sojova omacka",
        "ryzovy ocot",
        "chilli olej",
    ],
    "poke_bowl": [
        "sushi ryza",
        "nori",
        "sojova omacka",
        "sezamovy olej",
        "wasabi",
        "nakladany zazvor",
    ],
    "korejsky_gril": [
        "gochujang",
        "ssamjang",
        "sezamovy olej",
        "kimchi",
        "sojova omacka",
    ],
    "thajske_kari": [
        "kokosove mlieko",
        "rybacia omacka",
        "kari pasta cervena",
        "jazminova ryza",
        "sriracha",
    ],
    "sojova_omacka": [
        "mirin",
        "ryzovy ocot",
        "hoisin omacka",
        "sezamovy olej",
        "dashi",
    ],
    "wok": [
        "wok", "ustricova omacka",
        "sojova omacka",
        "sezamovy olej",
        "sriracha",
        "thajska cili stir-fry omacka",
    ],
    "beginner_kit": [
        "sojova omacka",
        "sezamovy olej",
        "ryzovy ocot",
        "jazminova ryza",
        "ramen rezance",
        "sriracha",
    ],
    "azijske_dezerty": [
        "pocky",
        "mochi",
        "bubble tea",
        "ryzove krekry",
        "kokosove cukriky",
    ],
    "jarne_zavitky": [
        "jarne zavitky", "ryzovy papier",
        "ryzove rezance",
        "sweet chili omacka",
        "rybacia omacka",
        "sriracha",
    ],
    "teriyaki": [
        "teriyaki", "sojova omacka",
        "mirin",
        "ryzovy ocot",
        "sezamovy olej",
        "jazminova ryza",
    ],
    "miso_polievka": [
        "miso pasta",
        "dashi",
        "tofu",
        "wakame",
        "nori",
    ],
    "fried_rice": [
        "sojova omacka",
        "sezamovy olej",
        "ustricova omacka",
        "jazminova ryza",
        "sriracha",
    ],
    "bulgogi": [
        "bulgogi", "sojova omacka",
        "sezamovy olej",
        "gochugaru",
        "kimchi",
        "jazminova ryza",
    ],
    "tteokbokki": [
        "tteokbokki", "gochujang",
        "gochugaru",
        "sezamovy olej",
        "sojova omacka",
        "rybacia omacka",
    ],
    "tom_yum": [
        "tom yum pasta",
        "citronova trava",
        "galangal",
        "kaffirove listy",
        "kokosove mlieko",
        "rybacia omacka",
        "sriracha",
    ],
    "japchae": [
        "japchae", "sklenene rezance",
        "dangmyeon",
        "sojova omacka",
        "sezamovy olej",
        "sezamove semienka",
        "gochujang",
    ],
    "vietnamska_kuchyna": [
        "rybacia omacka",
        "ryzove rezance",
        "sriracha",
        "hoisin omacka",
        "pho rezance",
    ],
    "japonska_kuchyna": [
        "sojova omacka",
        "mirin",
        "dashi",
        "wasabi",
        "sushi ryza",
    ],
    "korejska_kuchyna": [
        "gochujang",
        "sezamovy olej",
        "kimchi",
        "ssamjang",
        "jazminova ryza",
    ],
    "thajska_kuchyna": [
        "thajska kuchyna", "kokosove mlieko",
        "rybacia omacka",
        "sriracha",
        "kari pasta cervena",
        "ryzove rezance",
    ],
    "cinska_kuchyna": [
        "sojova omacka",
        "ustricova omacka",
        "sezamovy olej",
        "ramen rezance",
    ],
    "suan_la_tang": [
        "ostro kysla polievka",
        "cierna fazula cesnak omacka",
        "ryzovy ocot",
        "sojova omacka",
        "bambusove vyhonky",
    ],
    "japanese_curry": [
        "japonske kari",
        "golden curry",
        "japonska ryza",
        "sushi ryza",
    ],
    "pad_thai": [
        "pad thai", "ryzove rezance",
        "rybacia omacka",
        "tamarind",
        "arasidy",
        "sriracha",
    ],
    "tempura": [
        "tempura muka",
        "sojova omacka",
        "wasabi",
        "nakladany zazvor",
        "ryzovy ocot",
    ],
    "okonomiyaki": [
        "sojova omacka",
        "sezamovy olej",
        "gochujang",
        "miso pasta",
    ],
    "takoyaki": [
        "sojova omacka",
        "ponzu",
        "sezamovy olej",
        "morske riasy",
    ],
    "shabu_shabu": [
        "sojova omacka",
        "sezamovy olej",
        "dashi",
        "miso pasta",
        "gochujang",
    ],
    "onigiri": [
        "onigiri", "sushi ryza",
        "nori",
        "sojova omacka",
        "sezamove semienka",
        "nakladany zazvor",
    ],
    "yakisoba": [
        "yakisoba",
        "yakisoba omacka",
        "sojova omacka",
        "sezamovy olej",
        "ustricova omacka",
        "sriracha",
    ],
    "beginner_kit": [
        "sojova omacka",
        "sezamovy olej",
        "ryzovy ocot",
        "sriracha",
        "mirin",
        "dashi",
        "kokosove mlieko",
        "rybacia omacka",
    ],
    "udon": [
        "udon", "dashi",
        "sojova omacka",
        "mirin",
        "nori",
        "tofu",
    ],
    "soba": [
        "soba", "sojova omacka",
        "mirin",
        "dashi",
        "nori",
        "wasabi",
    ],
    "mandu": [
        "sojova omacka",
        "sezamovy olej",
        "ryzovy ocot",
        "zazvor",
        "gochujang",
    ],
    "wonton": [
        "wonton", "sojova omacka",
        "sezamovy olej",
        "ustricova omacka",
        "zazvor",
    ],
    "laksa": [
        "laksa", "kokosove mlieko",
        "rybacia omacka",
        "ryzove rezance",
        "sojova omacka",
    ],
    "banh_mi": [
        "rybacia omacka",
        "ryzovy ocot",
        "nakladany zazvor",
        "sojova omacka",
        "sriracha",
    ],
    "congee": [
        "sojova omacka",
        "sezamovy olej",
        "dashi",
        "miso pasta",
        "zazvor",
    ],
    "matcha": [
        "matcha prah",
        "smetana",
        "mlieko",
        "sladidlo",
        "zeleny caj",
    ],
    "mochi": [
        "mochiko",
        "ryzova muka",
        "kokosove mlieko",
        "cukrovy praskovy",
        "sezamove semienka",
    ],
    "bubble_tea": [
        "bubble tea", "tapiokove perly",
        "caj",
        "kokosove mlieko",
        "kondenzovane mlieko",
        "cierny caj",
    ],
    "edamame": [
        "edamame", "sojova omacka",
        "morska sol",
        "sezamovy olej",
        "wasabi",
    ],
    "tonkatsu": [
        "panko",
        "tonkatsu omacka",
        "sojova omacka",
        "sezamovy olej",
        "ryzovy ocot",
    ],
    "agedashi_tofu": [
        "tofu",
        "dashi",
        "sojova omacka",
        "mirin",
        "katsuobushi",
    ],
    "nori_rolky": [
        "nori",
        "sushi ryza",
        "ryzovy ocot",
        "wasabi",
        "nakladany zazvor",
        "sojova omacka",
    ],
    "dashi_vyvar": [
        "dashi",
        "katsuobushi",
        "kombu",
        "sojova omacka",
        "mirin",
    ],
    "grilovanie": [
        "grilovanie", "sojova omacka",
        "gochujang",
        "teriyaki omacka",
        "sezamovy olej",
        "sriracha",
    ],
    "asian_snack": [
        "ryzove krekry",
        "pocky",
        "mochi",
        "edamame",
        "nori snack",
    ],
    "tom_yum": [
        "citronova trava",
        "galangal",
        "kaffirove listy",
        "rybacia omacka",
        "sriracha",
        "tom yum pasta",
    ],
    "tom_kha": [
        "tom kha", "kokosove mlieko",
        "citronova trava",
        "galangal",
        "kaffirove listy",
        "rybacia omacka",
        "sriracha",
    ],
    "jjigae": [
        "gochujang",
        "doenjang pasta",
        "tofu",
        "sojova omacka",
        "sezamovy olej",
        "dashi",
    ],
    "nam_van": [
        "nam vang", "ryzovy papier",
        "rybacia omacka",
        "ryzove rezance",
        "sojova omacka",
        "sezamovy olej",
    ],
    "sukiyaki": [
        "sukiyaki", "sojova omacka",
        "mirin",
        "sake",
        "sezamovy olej",
        "tofu",
        "dashi",
    ],
    "bao_bun": [
        "bao buns", "sojova omacka",
        "sezamovy olej",
        "ustricova omacka",
        "hoisin omacka",
        "gochujang",
    ],
    "gyudon": [
        "sojova omacka",
        "mirin",
        "dashi",
        "ryzovy ocot",
    ],
    "oyakodon": [
        "sojova omacka",
        "mirin",
        "dashi",
        "sake",
    ],
    "karaage": [
        "sojova omacka", "sake", "zazvor", "mirin", "kukuricny skrob", "cesnak", "sezamovy olej",
    ],
    "tonkatsu": [
        "sojova omacka", "tonkatsu omacka", "panko", "sezamovy olej", "cesnak",
    ],
    "gyoza": [
        "gyoza", "sojova omacka", "ryzovy ocot", "sezamovy olej", "zazvor", "cesnak",
    ],
    "yakitori": [
        "yakitori", "sojova omacka", "mirin", "sake", "sezamovy olej", "cesnak",
    ],
    "adobo": [
        "sojova omacka", "ryzovy ocot", "sezamovy olej", "cesnak", "kokosove mlieko",
    ],
    "malatang": [
        "sojova omacka", "sezamovy olej", "tofu", "ryzove rezance", "gochujang",
    ],
    "jajangmyeon": [
        "sojova omacka", "sezamovy olej", "ryzove rezance", "ustricova omacka",
    ],
    "bento": [
        "bento", "sojova omacka", "mirin", "nori", "sezamovy olej", "ryzovy ocot",
    ],
    "yangnyeom_chicken": [
        "gochujang", "sojova omacka", "ryzovy ocot", "cesnak", "zazvor", "sezamovy olej",
    ],
    "samgyeopsal": [
        "sojova omacka", "sezamovy olej", "gochujang", "ryzovy ocot", "sesam",
    ],
    "bun_bo_nam_bo": [
        "ryzove rezance", "rybacia omacka", "hoisin", "sezamovy olej", "arasidy", "citronova trava",
    ],
    "bun_cha": [
        "ryzove rezance", "rybacia omacka", "ryzovy ocot", "cesnak", "chili omacka", "arasidy",
    ],
    "thit_dong": [
        "rybacia omacka", "shiitake huby", "susene huby", "sojova omacka", "chili omacka",
    ],
    "bun_bo_hue": [
        "bun bo hue", "rybacia omacka", "ryzove rezance", "citronova trava", "sojova omacka", "sriracha",
    ],
    "banh_gio": [
        "banh gio", "ryzova muka", "rybacia omacka", "sojova omacka", "shiitake", "chili omacka",
    ],
    "banh_xeo": [
        "ryzova muka", "kokosove mlieko", "rybacia omacka", "sriracha",
    ],
    "mapo_tofu": [
        "tofu", "gochujang", "sojova omacka", "sezamovy olej", "cesnak", "zazvor",
    ],
    "kung_pao": [
        "kung pao", "sojova omacka", "ryzovy ocot", "sezamovy olej", "zazvor", "cesnak", "sriracha",
    ],
    "dim_sum": [
        "siu mai",
        "dim sum krevetove",
        "dim sum kuracie",
        "hoisin omacka",
        "sojova omacka",
        "chili olej",
        "sezamovy olej",
    ],
    "dakgalbi": [
        "gochujang", "sojova omacka", "sezamovy olej", "ryzovy ocot",
    ],
    "char_siu": [
        "char siu", "sojova omacka", "hoisin omacka", "sezamovy olej", "ryzovy ocot", "cesnak",
    ],
    "som_tam": [
        "rybacia omacka", "ryzovy ocot", "sriracha", "sojova omacka",
    ],
    "nasi_goreng": [
        "nasi goreng", "sojova omacka", "sezamovy olej", "rybacia omacka", "sriracha",
    ],
    "mee_goreng": [
        "sojova omacka", "sezamovy olej", "rybacia omacka", "sriracha", "ustricova omacka",
    ],
    "rendang": [
        "kokosove mlieko", "citronova trava", "sojova omacka", "kari pasta",
    ],
    "larb": [
        "larb", "rybacia omacka", "ryzovy ocot", "sriracha", "sezamovy olej",
    ],
    "chow_mein": [
        "chow mein", "sojova omacka", "sezamovy olej", "ustricova omacka", "ryzove rezance",
    ],
    "satay": [
        "satay", "sojova omacka", "kari pasta", "kokosove mlieko", "sriracha", "sezamovy olej",
    ],
    "khao_pad": [
        "sojova omacka", "rybacia omacka", "sezamovy olej", "sriracha",
    ],
    "crying_tiger": [
        "sojova omacka", "rybacia omacka", "sriracha", "ryzovy ocot",
    ],
    "banchan": [
        "gochujang", "sojova omacka", "sezamovy olej", "ryzovy ocot",
    ],
    "dubu_jorim": [
        "tofu", "gochujang", "sojova omacka", "sezamovy olej",
    ],
    "haemul_pajeon": [
        "sojova omacka", "ryzovy ocot", "sezamovy olej", "gochujang",
    ],
    "gimbap": [
        "nori", "sushi ryza", "sojova omacka", "sezamovy olej", "ryzovy ocot",
    ],
    "tangsu_yuk": [
        "sojova omacka", "ryzovy ocot", "sezamovy olej", "gochujang",
    ],
    "hainanese_chicken": [
        "sojova omacka", "sezamovy olej", "zazvor", "cesnak",
    ],
    "mango_sticky_rice": [
        "lepkava ryza", "kokosove mlieko", "mango", "sezamove semienka",
    ],
    "sesame_balls": [
        "ryzova muka", "sezamove semienka", "kokosove mlieko", "matcha",
    ],
    "tikka_masala": [
        "tikka masala", "garam masala", "kari pasta", "kokosove mlieko", "jazminova ryza",
    ],
    "tandoori": [
        "tandoori masala", "garam masala", "kari pasta", "jazminova ryza",
    ],
    "biryani": [
        "basmati ryza", "biryani masala", "garam masala", "kardamom", "skorica",
    ],
    "nasi_lemak": [
        "kokosove mlieko", "jazminova ryza", "sambal", "arasidy", "rybacia omacka",
    ],
    "singapore_noodles": [
        "ryzove rezance", "kari korenie", "sojova omacka", "sezamovy olej", "sriracha",
    ],
    "sinigang": [
        "sinigang", "tamarind koncentrat", "tamarind pasta", "rybacia omacka", "ryzove rezance",
    ],
    "yukgaejang": [
        "gochujang", "sojova omacka", "sezamovy olej", "ryzovy ocot",
    ],
    "bossam": [
        "gochujang", "sojova omacka", "sezamovy olej", "kimchi",
    ],
    "wakame": [
        "wakame", "miso pasta", "tofu", "sojova omacka", "nori", "ryzovy ocot", "sezamovy olej",
    ],
    "dashi": [
        "kombu", "katsuobushi", "bonito vlocky", "shiitake houby",
        "miso pasta", "sojova omacka", "rybacia omacka",
    ],
    "spring_roll": [
        "ryzovy papier", "rice paper", "ryzove vermicelli", "sladkokyselka",
        "sojova omacka", "sezamovy olej", "chili omacka", "koriander",
    ],
    "ryza": [
        "ryza", "ryzovy ocot", "sojova omacka", "miso pasta", "sezamovy olej",
        "nori", "furikake", "kimchi", "tofu",
    ],
    "kokos": [
        "kokos", "kari pasta cervena", "kari pasta zelena", "rybacia omacka",
        "jazminova ryza", "sriracha", "lemongrass", "tamarind",
    ],
    "mirin": [
        "mirin", "sojova omacka", "sake", "ryzovy ocot", "dashi",
        "ginger", "cesnak", "sezamovy olej",
    ],
    "chili": [
        "chili", "sriracha", "gochujang", "sambal oelek", "chili olej",
        "thajske chili", "chili pasta",
    ],
    "nori": [
        "nori", "sushi ryza", "ryzovy ocot", "wasabi", "sojova omacka",
        "sezamovy olej", "furikake",
    ],
    "rybacia_omacka": [
        "rybacia omacka", "sojova omacka", "tamari", "miso pasta",
        "bezlepkova sojova omacka", "kokosove aminokyseliny",
    ],
    "special_occasion": [
        "sushi ryza", "nori", "wasabi", "ryzovy ocot",
        "sojova omacka", "sezamovy olej", "jazminova ryza",
    ],
    "wasabi": [
        "wasabi", "sojova omacka", "ryzovy ocot", "nori", "sushi ryza",
    ],
    "sezamovy_olej": [
        "sezamovy olej", "sojova omacka", "ryzovy ocot", "mirin", "gochujang", "hoisin",
        "sezamove semienka", "toasted sesame seeds",
    ],
    "ponzu": [
        "ponzu", "sojova omacka", "ryzovy ocot", "mirin", "yuzu",
    ],
    "potsticker": [
        "sojova omacka", "chili olej", "ryzovy ocot",
        "sezamovy olej", "gochujang", "sriracha",
    ],
    "sriracha": [
        "sriracha", "gochujang", "chili omacka", "chili olej",
    ],
    "hoisin": [
        "hoisin omacka", "sezamovy olej", "sojova omacka", "ustricova omacka",
    ],
    "ustricova_omacka": [
        "ustricova omacka", "sojova omacka", "sezamovy olej", "sriracha",
    ],
    "sojova_omacka": [
        "sojova omacka", "tamari", "mirin", "ryzovy ocot",
    ],
    "tamarind": [
        "tamarind pasta", "rybacia omacka", "kokosove mlieko", "hnedy cukor",
    ],
    "tofu": [
        "tofu", "sojova omacka", "sezamovy olej", "miso pasta", "gochujang",
    ],
    "losos": [
        "losos", "teriyaki omacka", "wasabi", "sojova omacka", "sezamovy olej", "zazvor",
    ],
    "kuraci": [
        "kuraci", "teriyaki omacka", "sojova omacka", "sezamovy olej", "gochujang", "karaage",
    ],
    "ryba": [
        "rybacia omacka", "sweet chili omacka", "wasabi", "sojova omacka", "citronova trava",
    ],
    "hovadzie": [
        "hovadzie", "teriyaki omacka", "sojova omacka", "sezamovy olej", "gochujang", "hoisin omacka",
    ],
    "kreveta": [
        "kreveta", "sweet chili omacka", "sojova omacka", "sriracha", "citronova trava", "wasabi",
    ],
    "panko": [
        "panko strobanka", "teriyaki omacka", "tonkatsu omacka", "sojova omacka", "karaage",
    ],
    "sake": [
        "sake", "mirin", "ryzovy ocot", "sojova omacka", "dashi", "sake na varen",
    ],
    "shiitake": [
        "shiitake", "sojova omacka", "sezamovy olej", "miso pasta", "dashi", "oyster sauce",
    ],
    "lotus_root": [
        "sojova omacka", "ryzovy ocot", "sezamovy olej", "dashi", "mirin", "sezamove semienka",
    ],
    "cierne_hriby": [
        "sojova omacka", "sezamovy olej", "ustricova omacka", "cesnak", "zazvor", "wok omacka",
    ],
    "ryzova_muka": [
        "ryzova muka", "kokosove mlieko", "pandan", "tapiokove perly", "mango", "cukrovy sirup", "sezamove semienka",
    ],
    "tapiokove_perly": [
        "zeleny caj", "matcha", "kokosove mlieko", "med", "ovocny sirup", "bubble tea",
    ],
    "sezamova_pasta": [
        "sezamova pasta", "sezamovy olej", "sojova omacka", "ryzovy ocot", "cesnak", "gochujang", "miso pasta",
    ],
    "zeleny_caj": [
        "matcha", "med", "citron", "sencha", "japonsky caj", "zeleny caj", "sojove mlieko",
    ],
    "cierny_caj": [
        "med", "citron", "chai", "caj", "mliecne mlieko", "cierny caj",
    ],
    "oolong": [
        "oolong", "med", "matcha", "zeleny caj", "sencha", "caj",
    ],
    "kondenzovane_mlieko": [
        "kondenzovane mlieko", "bubble tea", "tapiokove perly", "kokosove mlieko", "mango", "ovocny sirup", "matcha",
    ],
}

PRODUCT_SET_SIGNAL_TOKENS = {"set", "sety", "setu", "setov", "sada", "sady", "sad", "kit", "suprava", "supravy", "supravu", "supravou"}

RELATED_SUBJECT_ALIASES = {
    "kimchi_ramen": ("kimchi ramen", "ramen kimchi"),
    "kimchi_recipe": ("vyrobu kimchi", "kimchi ingrediencie", "kimchi recept", "kimchi navod", "spravit kimchi", "pripravit kimchi", "urobim kimchi", "kimchi suroviny", "ako vyrob kimchi"),
    "kimchi": ("kimchi", "kimci"),
    # onigiri must be checked before sushi: sushi's "nigiri" alias is a
    # substring of "onigiri", so without this ordering every onigiri
    # question got misclassified as a sushi question.
    "onigiri": ("onigiri", "ryžové gulky", "ryzove gulky", "ryzove gulky", "onigiri"),
    "sushi": ("sushi", "susi", "sushi ryza", "susi ryza", "maki", "maki rolky", "california roll", "futomaki", "hosomaki", "uramaki", "nigiri", "temaki", "sashimi"),
    "gochujang": ("gochujang", "gochu jang", "gochuang", "gochugaru", "korean chili flakes", "koreanska cili"),
    "ramen": ("ramen", "ramyun", "ramyeon", "tonkotsu", "tantanmen", "noodle soup", "noodle broth", "soup noodles", "nudl", "nudle", "nudlov"),
    "kari": ("kari", "curry"),
    "pho": ("pho",),
    "pad_thai": ("pad thai", "padthai", "pad-thai", "pad tai", "pat thai"),
    "bibimbap": ("bibimbap",),
    "gyoza": ("gyoza", "gyozu", "gyozy", "gyozou"),
    "poke_bowl": ("poke bowl", "poke", "poke boul"),
    "korejsky_gril": ("korejsky gril", "korejsky bbq", "korejsky barbecue", "kbbq", "korean bbq", "korejsku barbecue", "korejskeho grilu", "korejskeho bbq", "korejsky grill"),
    "thajske_kari": ("thajske kari", "thajske curry", "thajsky curry", "thajskeho curry", "thai curry", "thajskemu kari", "thajskeho kari", "thajskou kari", "thajskej kari"),
    "sojova_omacka": ("sojovej omacke", "k sojovej omacke", "doplnky k sojovej", "sojova omacka", "sojov", "soja sos", "soy sauce"),
    "wok": ("woku", "wok", "stir fry", "stir-fry", "na woku", "smaz", "smazit", "smazenie", "vysmaz"),
    "beginner_kit": ("zacinam azijsky", "zacinam varit azijsky", "zacinam s azijskou", "azijska spajza", "co si kupit ako prv", "zacinam varit", "prvy krat azij", "prvy krat varit azij", "krat korejsk", "krat japonsk", "krat thajsk", "krat cinsk", "azijsk", "azijskeho", "azijsku kuchyn", "azijske jedlo", "azijsku vecer", "nieco azij", "nejake azij", "asian", "east asian", "southeast asian", "spicy asian", "vegetarian asian", "vegan asian", "asijsk", "asijsku", "asijskej",
        "azijsk", "azijsku", "azijskej", "azia", "azii", "azijsky"),
    "azijske_dezerty": ("azijske dezerty", "azijsky dezert", "na dezert", "dezert ky"),
    "jarne_zavitky": ("jarne zavitky", "spring rolls", "jarnych zavitkov", "jarne rolky", "nemecke zavitky", "jarnym zavinkom", "jarneho zavitku", "jarnych zavinkov", "jarne zaviny", "jarny zavitok", "jarneho zavitka", "spring roll"),
    "teriyaki": ("teriyaki", "teriyaki kuracie", "teriyaki losos", "teriyaki omacku"),
    "miso_polievka": ("miso", "miso polievku", "miso polievka", "miso soup", "miso sopu", "miso polevku", "miso polievky", "miso polievke"),
    "fried_rice": ("fried rice", "smazena ryza", "vysmazena ryza", "ryza na panvici", "vyprazana ryza", "vyprazanu ryzu", "smazenu ryzu", "smaza ryzu", "smazim ryzu", "rice dish", "rice bowl", "rice meal"),
    "bulgogi": ("bulgogi", "galbi", "galby", "galbi jjim"),
    "tteokbokki": ("tteokbokki", "ddukbokki", "tteok", "dduk"),
    "tom_yum": ("tom yum", "tom yam", "tom kha", "citronova trava", "lemongrass", "galangal", "kaffirove listy", "kaffir lime"),
    "japchae": ("japchae", "jap chae", "korejske sklenene rezance"),
    "vietnamska_kuchyna": ("vietnamsku kuchynu", "vietnamska kuchyna", "vietnamska vecera", "vietnam", "vietnamsk"),
    "japonska_kuchyna": ("japonsku kuchynu", "japonska kuchyna", "japonska vecera", "japonsku veceru", "japonsk", "japansk", "japanese", "j-food", "j food"),
    "korejska_kuchyna": ("korejsku kuchynu", "korejska kuchyna", "korejska vecera", "korejsku veceru", "korejsk", "korean", "k-food", "k food"),
    "thajska_kuchyna": ("thajsku kuchynu", "thajska kuchyna", "thajska vecera", "thajsku veceru", "thajsk", "thai"),
    "cinska_kuchyna": ("cinsku kuchynu", "cinska kuchyna", "cinska vecera", "cinsku veceru", "cinsk", "chinese"),
    "pad_thai": ("pad thai", "padthai", "pad-thai", "pad tai", "pat thai"),
    "tempura": ("tempura", "tempuru", "tempury", "tempurou", "tempur"),
    "okonomiyaki": ("okonomiyaki",),
    "takoyaki": ("takoyaki",),
    "shabu_shabu": ("shabu shabu", "shabu-shabu", "hot pot", "hotpot", "hot-pot", "hot potu", "hotpotu"),
    "yakisoba": ("yakisoba", "yaki soba", "yakisobu", "yaki sobu", "yakisoby", "yakisobe"),
    # gyudon must be checked before udon: udon's alias is a substring
    # of "gyudon", so without this ordering every gyudon question got
    # misclassified as a plain udon-noodle question.
    "gyudon": ("gyudon", "hovaezi don", "beef bowl"),
    "udon": ("udon", "udonom", "udonove nudle", "udonovu polievku"),
    "soba": ("soba", "soba nudle", "soba rezance", "sobove nudle"),
    "mandu": ("mandu",),
    "wonton": ("wonton", "wonton soup", "wontonova polievka"),
    "laksa": ("laksa",),
    "banh_mi": ("banh mi",),
    "congee": ("congee", "ryzova kasa", "ryzovu kasu"),
    "matcha": ("matcha", "matche", "matchu", "matchou", "matchom", "matcha latte", "matcha tea"),
    "mochi": ("mochi",),
    "bubble_tea": ("bubble tea", "boba", "boba tea", "bubble tea", "bubbletea", "boba drink", "bubble drink"),
    "edamame": ("edamame",),
    "tonkatsu": ("tonkatsu",),
    "agedashi_tofu": ("agedashi tofu", "agedashi",),
    "nori_rolky": ("nori rolky", "nori wrap", "nori sheet"),
    "dashi_vyvar": ("dashi vyvar", "dashi vyvaru", "dashi polievka"),
    "japansk": ("japanske ranajky", "japanska snidana"),
    "grilovanie": ("grilovacku", "grilovat", "grilovanie", "na gril", "grilu", "grilovacky"),
    "asian_snack": ("k filmu", "k serialu", "na film", "na serial", "k pivu azij", "snack azij"),
    "tom_yum": ("tom yum", "tom yum polievka", "thajska polievka", "thajskej polievky", "tom yum soup", "citronova trava", "lemongrass", "galangal", "kaffirove listy", "kaffir lime"),
    "tom_kha": ("tom kha", "tom kha gai", "kokosova kuracia polievka", "thajska kokosova polievka"),
    "jjigae": ("jjigae", "sundubu jjigae", "sundubu", "doenjang jjigae", "doenjang", "korejsky stew"),
    "nam_van": ("nam van", "goi cuon", "vietnamske rolky", "cerstve rolky"),
    "sukiyaki": ("sukiyaki",),
    "bao_bun": ("bao bun", "bao", "baozi", "parovany bun", "parovane buchty"),
    "oyakodon": ("oyakodon", "oyako don"),
    "karaage": ("karaage",),
    "tonkatsu": ("tonkatsu",),
    "gyoza": ("gyoza", "gyozu", "gyozy", "gyozou", "gyoze", "gyozam", "jiaozi"),
    "yakitori": ("yakitori",),
    "adobo": ("adobo", "filipino adobo"),
    "malatang": ("malatang", "mala tang", "mala hotpot"),
    "jajangmyeon": ("jajangmyeon", "jajangmyon", "black bean noodles"),
    "asian_noodles": ("asian noodles", "asian noodle", "stir fry noodles"),
    "medium_spicy": ("spicy food", "hot food", "spicy dinner", "spicy meal", "pikantne jedlo", "horuce jedlo", "hot sauce", "chili sauce", "sriracha dinner", "spicy", "pikantne"),
    "bento": ("bento", "bento box", "bento lunch", "benta", "bente", "do benta", "bent"),
    "yangnyeom_chicken": ("yangnyeom chicken", "yangnyeom", "chimaek", "korean fried chicken", "korean chicken"),
    "samgyeopsal": ("samgyeopsal", "pork belly"),
    "bun_bo_nam_bo": ("bun bo nam bo", "bun bo nam", "vietnamsky hovadzi salat", "hovadzi salat s rezancami", "bun bo juh"),
    "bun_cha": ("bun cha", "bún chả"),
    "bun_bo_hue": ("bun bo hue", "bun bo"),
    "banh_gio": ("banh gio", "bánh giò", "parene pyramídove knedliky", "parene pyramidove knedliky"),
    "banh_xeo": ("banh xeo",),
    "mapo_tofu": ("mapo tofu", "mapo"),
    "suan_la_tang": ("suan la tang", "ostro kysla polievka", "hot sour soup"),
    "kung_pao": ("kung pao", "kung pao chicken"),
    "dim_sum": ("dim sum", "dimsum", "dumpling", "dumplingy", "dumplingom", "plnene testo"),
    "dakgalbi": ("dakgalbi",),
    "char_siu": ("char siu", "char-siu", "cinsky bbq"),
    "som_tam": ("som tam", "som tum", "papajovy salat"),
    "nasi_goreng": ("nasi goreng",),
    "japanese_curry": ("japonske kari", "golden curry"),
    "mee_goreng": ("mee goreng", "mi goreng"),
    "rendang": ("rendang",),
    "larb": ("larb",),
    "chow_mein": ("chow mein", "chowmein", "chow-mein"),
    "satay": ("satay", "sate", "satay kura"),
    "mango_sticky_rice": ("mango sticky rice", "lepkava ryza s mangom", "sladka lepkava ryza"),
    "sesame_balls": ("sezamove gulocky", "banh ran", "bánh rán"),
    "tikka_masala": ("tikka masala", "murgh makhani", "maslove kura"),
    "tandoori": ("tandoori", "tandoori masala"),
    "biryani": ("biryani", "kuracie biryani"),
    "nasi_lemak": ("nasi lemak",),
    "singapore_noodles": ("singapurske rezance", "singapore noodles"),
    "sinigang": ("sinigang", "filipinska kysla polievka"),
    "thit_dong": ("thit dong", "thit ong", "vietnamska huspenina", "huspenina"),
    "khao_pad": ("khao pad",),
    "crying_tiger": ("crying tiger",),
    "banchan": ("banchan", "korejske prilohy"),
    "dubu_jorim": ("dubu jorim",),
    "haemul_pajeon": ("haemul pajeon", "pajeon", "korejske palacinky"),
    "gimbap": ("gimbap", "kimbap"),
    "tangsu_yuk": ("tangsu yuk", "tangsu"),
    "hainanese_chicken": ("hainanese chicken", "hainanese rice", "hainan chicken"),
    "yukgaejang": ("yukgaejang",),
    "bossam": ("bossam",),
    "wakame": ("wakame", "wakamy", "wakamu", "wakamom"),
    "dashi": ("dashi", "dashi vyvar", "dashi stock", "dashi buljon", "dashiho", "bonito", "bonito vlocky", "katsuobushi"),
    "spring_roll": ("spring roll", "spring rollu", "spring rollom", "spring rollov", "jarny zavin", "jarneho zavinu", "rice paper", "ryzovy papier"),
    "ryza": ("ryzu", "ryzou", "ryzy", "ryze", "ryzi", "jasminovu ryzu", "jasminovej", "jasminov", "basmati", "sushi ryzu", "bielu ryzu"),
    "kokos": ("kokosov", "kokosove", "kokosoveho", "kokosovym", "kokosove mlieko", "coconut", "kokosova smotana", "kokosova smetan"),
    "mirin": ("mirin", "mirine", "mirinom", "mirinu"),
    "rybacia_omacka": ("rybacia omacka", "rybacou omackou", "rybaci omacku", "rybac", "fish sauce", "nuoc mam", "nuoc nam"),
    "chili": ("chili", "chilli", "chili omacka", "chili paste", "chili paprika", "chili sauce"),
    "nori": ("nori", "nori list", "nori listov", "nori sheets", "nori sheet"),
    "wasabi": ("wasabi", "wasabi pasta", "wasabi prasok", "wasabi omacka"),
    "sezamovy_olej": ("sezamovy olej", "sezamoveho oleja", "sezamovym olejom", "sesame oil", "sezam olej", "dark sesame", "toasted sesame", "sezamove semienka", "sezamovych semienok", "sesame seeds", "sezamovych semen"),
    "ponzu": ("ponzu", "ponzu omacku", "ponzu sauce", "ponzu shoyu", "ponzu yuzu", "yuzu"),
    "potsticker": ("potsticker", "potstickeram", "guo tie", "pot sticker", "pot-sticker"),
    "special_occasion": (
        "svadba", "svadb", "narodeninov", "narozenin", "vianoc", "silvester",
        "novy rok", "sviatok", "romantick", "specialn",
        "priatelk", "anniversary", "wedding", "birthday", "christmas",
        "new year", "date night", "valentin",
        "vikend", "nedel", "sobot", "dnes", "dnesna",
        "host", "hosti", "ludi", "clovek", "osob",
    ),
    "sriracha": ("sriracha", "sriracha omacka", "sriracha sauce", "sriracha hot sauce"),
    "hoisin": ("hoisin", "hoisin omacka", "hoisin sauce"),
    "ustricova_omacka": ("ustricova omacka", "ustricovej omacky", "oyster sauce", "ustricovou omackou"),
    "sojova_omacka": ("sojova omacka", "sojovej omacky", "sojovou omackou", "svetla soja", "tmava soja", "soy sauce", "sojou", "tamari omacka"),
    "tamarind": ("tamarind", "tamarindova pasta", "tamarind paste", "tamarindovy"),
    "tofu": ("tofu", "tofuom", "tofuovi", "firm tofu", "silk tofu", "hedvabne tofu", "silken tofu"),
    "losos": ("losos", "lososa", "lososu", "lososom", "lososovi", "salmon", "lososovy"),
    "kuraci": ("kuraci", "kuracie", "kuraciemu", "kurace", "kuracim", "kuracom", "kuraciom", "chicken", "kure"),
    "ryba": ("ryba", "rybu", "rybe", "rybou", "ryby", "rybaci", "fish", "sea food", "seafood"),
    "hovadzie": ("hovadzie", "hovadziu", "hovadziemu", "hovadze", "beef", "hovadzeho", "hovadzinym", "hovadzimu", "steak"),
    "kreveta": ("kreveta", "krevety", "krevetam", "krevetami", "shrimp", "prawns", "garnele", "krevetove"),
    "panko": ("panko", "panko strobanka", "panko obalenie", "japanese breadcrumbs", "strobanka panko"),
    "sake": ("sake", "sake na varen", "varecke sake", "rice wine", "japanese sake", "varenie sake"),
    "shiitake": ("shiitake", "shiitake houby", "shiitake huby", "shiitake grib", "dried shiitake", "susene shiitake"),
    "ryzovy_ocot": ("ryzovy ocot", "rice vinegar", "ocot sushi", "sushi ocot", "ryzoveho octu", "ryzovym octom"),
    # "ocot" must be checked after "ryzovy_ocot" above: it is a substring
    # of "ryzovy ocot"/"rice vinegar", so without this ordering a rice-
    # vinegar question would lose its sushi-specific cross-sell.
    "ocot": ("ocot", "octom", "octu", "octe", "octy", "vinegar"),

    "cesnak": ("cesnak", "cesnakom", "cesnaku", "cesnakovy olej", "garlic", "cesnakoveho", "cesnakova"),
    "nakladany_zazvor": ("nakladany zazvor", "nakladanym zazvorom", "nakladaneho zazvoru", "pickled ginger", "sushi ginger", "gari"),
    "nuoc_cham": ("nuoc cham", "nuoc mam", "vietnamese omacka", "viet dipping", "viet sauce"),

    "arasidovy_olej": ("arasidovy olej", "arasidovym olejom", "arasidoveho oleja", "peanut oil", "groundnut oil", "arasidove maslo", "peanut butter"),
    "koriander": ("koriander", "koriandr", "coriander", "cilantro", "koriandrom", "koriandru", "koriandra"),
    "ssamjang": ("ssamjang", "ssamjangu", "ssam jang", "korean bbq paste", "koreanska omacka"),
    "mung_fazula": ("mung fazula", "mung bean", "mungove klicky", "mung fazule", "mungo fazula", "fazulove klicky"),
    "agar_agar": ("agar agar", "agar-agar", "agar", "vegan gelatin", "veganska zelatina", "agaru"),
    "bambusove_vyhanky": ("bambusove vyhanky", "bambusovych vyhankov", "bamboo shoots", "bambusove klicky", "bamboo klicky"),
    "vodne_kastany": ("vodne kastany", "vodnych kastanov", "water chestnuts", "water chestnut"),
    "ryzove_rezance": ("ryzove rezance", "ryzovych rezancov", "rice noodles", "rice vermicelli", "ryžové rezance", "pho rezance", "bun rezance"),
    "sklenene_rezance": ("sklenene rezance", "sklenych rezancov", "glass noodles", "cellophane noodles", "dangmyeon rezance", "sklenene nudle"),

    "shichimi_togarashi": ("shichimi", "shichimi togarashi", "seven spice", "japanese seven spice", "togarashi"),
    "furikake": ("furikake", "furikake korenie", "japanese rice seasoning", "rice seasoning"),
    "kewpie": ("kewpie", "kewpie majoneza", "japonska majoneza", "japanese mayo", "kewpie mayo", "kewpi"),
    "mentsuyu": ("mentsuyu", "mentsuyu omacka", "japanese dipping sauce", "tsuyu", "men tsuyu"),
    "natto": ("natto", "nattu", "natto soybeans", "fermented soybeans"),
    "okonomiyaki": ("okonomiyaki", "okonomijaki", "japanese pancake", "okonomi"),
    "pandan": ("pandan", "pandanove listy", "pandan listy", "pandan leaves", "pandanu"),
    "lychee": ("lychee", "lichi", "lichin", "litchi", "lychee ovocie"),
    "taro": ("taro", "taro koren", "taro chip", "taro root", "taro boba"),
    "hokkien_rezance": ("hokkien rezance", "hokkien noodles", "hokkien", "wheat noodles lo mein", "lo mein"),
    "kombu": ("kombu", "kombu riasy", "kelp riasy", "kombu dashi", "kombuvych", "kelp seaweed"),
    "yakiniku": ("yakiniku", "yakiniku omacka", "korean bbq", "japanese bbq", "yakiniku sauce"),
    "omurice": ("omurice", "omu rice", "japonska omeleta", "omurajisu"),
    "chahan": ("chahan", "cahan", "japanese fried rice", "yakimeshi", "yaki meshi"),
    "lotus_root": ("lotus root", "lotusovy koren", "renkon", "lotus chips", "lotusoveho korena", "lotusovym korenom"),
    "cierne_hriby": ("cierne hriby", "ciernymi hrybmi", "ciernych hrib", "wood ear", "black fungus", "mu err", "cloud ear", "drevene hriby"),
    "ryzova_muka": ("ryzova muka", "ryzovej muky", "ryzovou mukou", "rice flour", "glutinous rice flour", "lepkava ryzova muka"),
    "tapiokove_perly": ("tapiokove perly", "tapioka", "tapiocove perly", "boba perly", "tapioca pearls", "tapiokovy skrob"),
    "sezamova_pasta": ("sezamova pasta", "tahini", "sezamovej pasty", "sesame paste", "tahini pasta"),
    "zeleny_caj": ("zeleny caj", "zeleneho caju", "zelenym cajom", "green tea", "zelenemu caju"),
    "cierny_caj": ("cierny caj", "cierneho caju", "ciernym cajom", "black tea", "ciernemu caju"),
    "oolong": ("oolong", "oolong caj", "wu long", "wulong", "oolong tea"),
    "kondenzovane_mlieko": ("kondenzovane mlieko", "kondenzovaneho mlieka", "kondenzovanym mliekem", "sweetened condensed milk", "sladzene kondenzovane mlieko"),

}

ARTICLE_PRODUCT_QUERIES = {
    "kimchi_article": ["kimchi"],
    "pho_article": ["pho", "banh pho"],
    "udon_article": ["udon rezance", "udon"],
    "ramen_article": ["ramen rezance", "ramen"],
    "udon_ramen_article": ["udon rezance", "ramen rezance"],
    "tofu_article": ["tofu"],
    "shoyu_article": ["shoyu", "sojova omacka"],
    "tamari_article": ["tamari"],
    "miso_article": ["miso pasta", "miso"],
    "matcha_article": ["matcha"],
    "mochi_article": ["mochi"],
    "bubble_tea_article": ["bubble tea", "tapiokove perly"],
}

RECIPE_TITLE_PRODUCT_SUBJECTS = (
    ("pad thai", "pad_thai"),
    ("sushi a sashimi", "sushi"),
    ("satay", "satay"),
    ("tom kha", "tom_kha"),
    ("tom yum", "tom_yum"),
    ("kokosove kari", "thajske_kari"),
    ("vindaloo", "vindaloo"),
    ("karaage", "karaage"),
    ("tekvicou", "thajske_kari"),
    ("ciernej ryze", "black_rice_salad"),
    ("cierna ryza", "black_rice_salad"),
    ("lepkava ryza", "mango_sticky_rice"),
    ("mangom", "mango_sticky_rice"),
    ("pho bo", "pho"),
    ("pho ga", "pho"),
    ("banh mi", "banh_mi"),
    ("nem cuon", "nam_van"),
    ("jarne zavitky", "nam_van"),
    ("bun cha", "bun_cha"),
    ("bun bo nam bo", "bun_bo_nam_bo"),
    ("nuoc cham", "nuoc_cham"),
    ("banh gio", "banh_gio"),
    ("vietnamsky zeleninovy salat", "vietnamska_kuchyna"),
    ("rybacou omackou", "rybacia_omacka"),
    ("thit dong", "thit_dong"),
    ("thit ong", "thit_dong"),
    ("huspenina", "thit_dong"),
    ("varena jazminova ryza", "jasmine_rice"),
    ("jazminova ryza", "jasmine_rice"),
    ("banh ran", "sesame_balls"),
    ("sezamove gulocky", "sesame_balls"),
    ("kimchi ramen", "kimchi_ramen"),
    ("ramen kimchi", "kimchi_ramen"),
    ("jjigae", "jjigae"),
    ("japchae", "japchae"),
    ("kimchi recept", "kimchi_recipe"),
    ("bulgogi", "bulgogi"),
    ("kimchi prazena ryza", "fried_rice"),
    ("bibimbap", "bibimbap"),
    ("gimbap", "gimbap"),
    ("japonske kuracie kari", "japanese_curry"),
    ("kuracie kari", "kari"),
    # gyudon must be checked before udon here too - same substring
    # collision as the RELATED_SUBJECT_ALIASES reorder above.
    ("gyudon", "gyudon"),
    ("udon", "udon"),
    ("teriyaki tofu", "teriyaki"),
    ("kuromame gohan", "kuromame_gohan"),
    ("yakiudon", "yakisoba"),
    ("miso polievka", "miso_polievka"),
    ("tempura", "tempura"),
    ("shoyu ramen", "ramen"),
    ("kung pao", "kung_pao"),
    ("pekingska kacica", "cinska_kuchyna"),
    ("ma po tofu", "mapo_tofu"),
    ("mapo tofu", "mapo_tofu"),
    ("suan la tang", "suan_la_tang"),
    ("murgh makhani", "tikka_masala"),
    ("tikka masala", "tikka_masala"),
    ("tandoori", "tandoori"),
    ("biryani", "biryani"),
    ("nasi goreng", "nasi_goreng"),
    ("mie goreng", "mee_goreng"),
    ("rendang", "rendang"),
    ("nasi lemak", "nasi_lemak"),
    ("hainanske", "hainanese_chicken"),
    ("singapurske rezance", "singapore_noodles"),
    ("sinigang", "sinigang"),
)

RECIPE_URL_OVERRIDES: dict[str, str] = {
    "bun bo nam bo": "https://www.foodland.sk/recepty/vietnamska-specialita-bun-bo-nam-bo/",
    "bun bo nam": "https://www.foodland.sk/recepty/vietnamska-specialita-bun-bo-nam-bo/",
    "vietnamsky hovadzi salat": "https://www.foodland.sk/recepty/vietnamska-specialita-bun-bo-nam-bo/",
}

SPECIAL_PRODUCT_QUERIES = {
    "sushi_rice": [
        "sushi ryza",
        "ryza na sushi",
        "susi ryza",
        "nori",
        "ryzovy ocot",
        "wasabi",
    ],
    "kimchi_product": [
        "kimchi",
        "mat kimchi",
        "kimchi jongga",
        "veganske kimchi",
        "nakladana kapusta kimchi",
    ],
    "gluten_free_sushi": [
        "bezlepkova sojova omacka",
        "tamari",
        "nori",
        "sushi ryza",
        "wasabi",
        "nakladany zazvor",
    ],
    "mild": [
        "mochi",
        "kokosove mlieko",
        "jazminova ryza",
        "ryzove rezance",
        "miso pasta",
        "mirin",
    ],
    "hot": [
        "sambal oelek extra hot",
        "sriracha",
        "cili pasta",
        "gochujang",
        "cervena cili paprika",
    ],
    "vegan_fish_sauce_replacement": [
        "sojova omacka",
        "tamari",
        "hubova vegetarianska omacka",
        "bezlepkova sojova omacka",
    ],
    "kids_snack": [
        "pocky",
        "mochi",
        "ryzove krekry",
        "bubble tea",
    ],
    "asian_sweets": [
        "mochi",
        "ryzove krekry",
        "pocky",
        "kokosove cukriky",
    ],
    "dairy_replacement": [
        "sezamovy olej",
        "kokosove mlieko",
        "miso pasta",
    ],
    "fermented_sour": [
        "kimchi",
        "nakladany zazvor",
        "tamarind",
    ],
    "rice_vinegar": [
        "ryzovy ocot",
        "rice vinegar",
        "ocot sushi",
    ],
    "asian_noodles": [
        "ryzove rezance",
        "udon",
        "ramen rezance",
    ],
    "rice_side": [
        "jazminova ryza",
        "sushi ryza",
        "basmati ryza",
    ],
    "vegan_asian": [
        "tofu",
        "nori",
        "ryzove rezance",
        "kokosove mlieko",
    ],
    "no_pork_asian": [
        "tofu",
        "nori",
        "wakame",
        "ryzove rezance",
    ],
    "medium_spicy": [
        "sriracha",
        "gochujang",
        "chilli olej",
    ],
    "korean_paste": [
        "gochujang",
        "ssamjang",
    ],
    "tamari": [
        "tamari",
        "bezlepkova sojova omacka",
    ],
    "safe_snack": [
        "mochi",
        "pocky",
        "ryzove krekry",
    ],
    "safe_sauce": [
        "sojova omacka",
        "tamari",
        "hoisin",
    ],
    "plain_rice": [
        "jazminova ryza",
        "basmati ryza",
    ],
    "rice_cooker": [
        "ryzovar",
        "hrniec na ryzu",
    ],
    "rice_seasoning": [
        "koreniaca zmes na ryzu",
        "korenie na ryzu",
    ],
    "sushi_condiments": [
        "nori",
        "wasabi",
        "nakladany zazvor",
    ],
    "tofu_seaweed": [
        "tofu",
        "nori",
        "wakame",
    ],
}

SPECIAL_PRODUCT_EXCLUDE_TERMS = {
    "kimchi_product": ("instant", "ramen", "ramyun", "rezance", "polievk", "omack"),
    "gluten_free_sushi": (
        "flastick",
        "flast",
        "miska",
        "misky",
        "nadoba",
        "doza",
        "davkovac",
        "obal",
        "box",
    ),
    "mild": ("spicy", "hot", "cili", "chilli", "paliv", "angry", "wasabi"),
    "vegan_fish_sauce_replacement": (
        "box",
        "dressing",
        "flastick",
        "flast",
        "miska",
        "misky",
        "nadoba",
        "doza",
        "davkovac",
        "obal",
    ),
    "kids_snack": ("spicy", "hot", "cili", "chilli", "paliv", "angry", "wasabi", "soju", "sake", "alkohol"),
    "asian_sweets": ("spicy", "hot", "cili", "chilli", "paliv", "angry", "wasabi", "soju", "sake", "alkohol"),
    "dairy_replacement": ("dezert", "cukrik", "snack", "cokolad"),
    "fermented_sour": ("polievk", "lemonade", "cukrik", "krekry", "forma", "noznice", "miska"),
    "vegan_asian": ("caj", "kava", "napoj", "dzus", "cukrik", "snack", "box", "filter"),
    "no_pork_asian": ("caj", "kava", "napoj", "dzus", "cukrik", "snack", "box", "filter"),
    "medium_spicy": ("rezance", "chips", "cipsy", "curry", "kari pasta", "sladk"),
    "korean_paste": ("rezance", "snack", "rolky", "omacka na morske", "caj", "dzus"),
    "safe_snack": ("spicy", "hot", "cili", "chilli", "paliv", "angry", "wasabi", "soju", "sake", "alkohol"),
    "safe_sauce": ("rybacia", "arasid"),
    "plain_rice": ("ryzovar", "hrniec", "muka", "ocot", "vinegar", "rezance", "korenie", "koreniaca", "papier"),
    "rice_cooker": ("muka", "ocot", "korenie", "koreniaca"),
    "rice_seasoning": ("hrniec", "ryzovar", "ocot", "muka"),
    "sushi_condiments": ("ryza", "rice"),
    "tofu_seaweed": ("bravc", "kurac", "maso"),
}

FAQ_INTENT_MARKERS = (
    "kredit",
    "doprav",
    "doruc",
    "postovn",
    "kurier",
    "posiel",
    "preprav",
    "privez",
    "rozvaz",
    "packeta",
    "zasiel",
    "sledov",
    "objednav",
    "plat",
    "kartou",
    "hotovost",
    "vyzdvih",
    "reklamac",
    "vraten",
    "vracen",
    "delivery",
    "shipping",
    "courier",
    "payment",
    "pay by card",
    "cash on delivery",
    "complaint",
    "refund",
    "registration",
    "password",
    "loyalty",
    "vernostn",
    "discount code",
    "predajn",
    "store",
    "park",
    "kariet",
    "adresa",
    "dodan",
    "pockanie",
    "odber",
)

SHOPPING_LIST_MARKERS = (
    "nakupny zoznam",
    "nákupný zoznam",
    "co potrebujem",
    "čo potrebujem",
    "co treba",
    "čo treba",
    "co kupit",
    "čo kúpiť",
    "co mi chyba",
    "čo mi chýba",
    "co chyba",
    "čo chýba",
    "do kosika",
    "do košíka",
    "suroviny",
    "ingrediencie",
)

MISSING_INGREDIENTS_BY_SUBJECT = {
    "vindaloo": ["bravčové pliecko (mäso)", "čerstvý cesnak", "čerstvý zázvor", "vínny alebo jablčný ocot", "cibuľa"],
    "karaage": ["kuracie stehná (mäso)", "čerstvý zázvor", "citrón", "biela kapusta"],
    "sushi": ["čerstvá ryba alebo zelenina podľa rolky", "avokádo alebo uhorka"],
    "kimchi_recipe": ["čínska kapusta", "daikon alebo biela reďkovka", "jarná cibuľka", "cesnak"],
    "kimchi": ["čínska kapusta", "daikon alebo biela reďkovka", "jarná cibuľka", "cesnak"],
    "pho": ["hovädzie alebo kuracie mäso", "čerstvé bylinky", "cibuľa", "limetka", "fazuľové klíčky"],
    "pad_thai": ["vajce alebo tofu", "čerstvé klíčky", "limetka", "jarná cibuľka"],
    "ryza": ["voda", "soľ podľa chuti", "čerstvá príloha podľa jedla"],
    "mango_sticky_rice": ["zrelé mango", "soľ podľa chuti"],
    "bibimbap": ["vajce", "čerstvá zelenina", "mäso alebo tofu"],
    "gyoza": ["mleté mäso alebo tofu", "kapusta", "jarná cibuľka", "cesnak"],
    "ramen": ["vajce", "čerstvá jarná cibuľka", "mäso alebo tofu"],
    "kimchi_ramen": ["vajce", "čerstvá jarná cibuľka", "mäso alebo tofu"],
    "kari": ["mäso alebo tofu", "čerstvá zelenina", "cibuľa"],
    "japanese_curry": ["kuracie mäso alebo tofu", "zemiaky", "mrkva", "cibuľa"],
    "thajske_kari": ["mäso alebo tofu", "čerstvá zelenina", "cibuľa"],
    "tom_yum": ["krevety alebo kuracie mäso", "čerstvé huby", "limetka", "čerstvý koriander"],
    "tom_kha": ["kuracie mäso alebo tofu", "čerstvé huby", "limetka", "čerstvý koriander"],
    "satay": ["kuracie mäso alebo tofu", "limetka", "čerstvá uhorka"],
    "bun_cha": ["bravčové alebo tofu", "čerstvé bylinky", "šalát", "limetka"],
    "bun_bo_nam_bo": ["hovädzie mäso", "čerstvé bylinky", "šalát", "uhorka"],
    "banh_mi": ["bageta", "mäso alebo tofu", "čerstvá zelenina", "koriander"],
    "nuoc_cham": ["limetka", "cesnak", "čerstvé čili", "voda"],
    "banh_gio": ["mleté mäso alebo huby", "cibuľa", "banánové listy alebo papier na balenie"],
    "vietnamska_kuchyna": ["čerstvá zelenina", "bylinky", "limetka"],
    "rybacia_omacka": ["mäso, ryba alebo tofu podľa receptu", "cesnak", "čerstvé čili", "limetka"],
    "thit_dong": ["bravčové alebo kuracie mäso", "čerstvá cibuľa", "mrkva"],
    "spring_roll": ["čerstvá zelenina", "bylinky", "mäso alebo tofu"],
    "nam_van": ["čerstvá zelenina", "bylinky", "mäso alebo tofu"],
    "sesame_balls": ["voda", "olej na vyprážanie", "náplň podľa chuti"],
    "jjigae": ["mäso alebo tofu", "jarná cibuľka", "cesnak"],
    "japchae": ["hovädzie mäso alebo tofu", "čerstvá zelenina", "cibuľa"],
    "bulgogi": ["hovädzie mäso alebo tofu", "cibuľa", "jarná cibuľka"],
    "fried_rice": ["varená ryža", "vajce alebo tofu", "čerstvá zelenina", "jarná cibuľka"],
    "gimbap": ["vajce alebo tofu", "čerstvá zelenina", "šunka, ryba alebo iná plnka podľa chuti"],
    "teriyaki": ["kuracie mäso, losos alebo tofu", "čerstvá zelenina"],
    "miso_polievka": ["tofu", "jarná cibuľka"],
    "udon": ["mäso, krevety alebo tofu", "čerstvá zelenina", "jarná cibuľka"],
    "tempura": ["čerstvá zelenina alebo krevety", "ľadová voda", "olej na vyprážanie"],
    "mapo_tofu": ["tofu", "mleté mäso alebo huby", "jarná cibuľka"],
    "suan_la_tang": ["tofu", "vajce", "huby", "jarná cibuľka"],
    "kung_pao": ["kuracie mäso alebo tofu", "čerstvá paprika", "jarná cibuľka"],
    "cinska_kuchyna": ["mäso alebo tofu", "čerstvá zelenina", "jarná cibuľka"],
    "tikka_masala": ["kuracie mäso alebo tofu", "jogurt alebo smotana", "cibuľa"],
    "tandoori": ["kuracie mäso alebo tofu", "jogurt", "citrón"],
    "biryani": ["mäso alebo zelenina", "cibuľa", "čerstvý koriander"],
    "nasi_goreng": ["vajce", "čerstvá zelenina", "mäso alebo tofu"],
    "mee_goreng": ["vajce", "čerstvá zelenina", "mäso alebo tofu", "limetka"],
    "rendang": ["hovädzie mäso alebo tofu", "cibuľa", "čerstvý zázvor", "cesnak"],
    "nasi_lemak": ["vajce", "uhorka", "arašidy alebo ančovičky podľa verzie"],
    "hainanese_chicken": ["kuracie mäso", "uhorka", "čerstvá jarná cibuľka"],
    "singapore_noodles": ["vajce", "čerstvá zelenina", "mäso alebo tofu", "jarná cibuľka"],
    "sinigang": ["mäso alebo ryba", "čerstvá zelenina"],
    "black_rice_salad": ["cerstva zelenina", "bylinky", "limetka"],
    "jasmine_rice": ["voda", "sol podla chuti"],
    "kuromame_gohan": ["voda", "sol podla chuti"],
}

RECIPE_SHOPPING_CORE_QUERIES = {
    "pad_thai": [
        ("ryzove rezance", ("rezance",), ()),
        ("tamarind pasta", ("tamarind",), ()),
        ("rybacia omacka", ("rybacia omacka",), ()),
        ("palmovy cukor", ("cukor",), ()),
        ("arasidy", ("arasid",), ()),
    ],
    "satay": [
        ("arasidova omacka", ("arasid",), ()),
        ("kokosove mlieko", ("kokosove mlieko",), ()),
        ("cervena kari pasta", ("kari", "pasta"), ()),
        ("sojova omacka", ("sojova omacka",), ()),
        ("sezamovy olej", ("sezamovy olej",), ()),
    ],
    "tom_kha": [
        ("kokosove mlieko", ("kokosove mlieko",), ()),
        ("galangal", ("galangal",), ()),
        ("citronova trava", ("citronova trava",), ()),
        ("kaffirove listy", ("kaffir",), ("bambus", "caj")),
        ("rybacia omacka", ("rybacia omacka",), ()),
    ],
    "black_rice_salad": [
        ("cierna ryza", ("cierna", "ryza"), ()),
        ("ryzovy ocot", ("ryzovy", "ocot"), ()),
        ("sezamovy olej", ("sezamovy olej",), ()),
        ("sojova omacka", ("sojova omacka",), ()),
    ],
    "jasmine_rice": [
        ("jazminova ryza", ("jazminova", "ryza"), ()),
    ],
    "kuromame_gohan": [
        ("japonska ryza", ("ryza",), ("ocot",)),
        ("cierna soja", ("cierna", "soja"), ()),
        ("mirin", ("mirin",), ()),
        ("sojova omacka", ("sojova omacka",), ()),
    ],
    "mango_sticky_rice": [
        ("lepkava ryza", ("lepkava", "ryza"), ("cierna",)),
        ("kokosove mlieko", ("kokosove mlieko",), ()),
        ("mango pyre", ("mango",), ()),
        ("sezamove semienka", ("sezam",), ()),
    ],
    "pho": [
        ("korenie pho", ("pho",), ()),
        ("rybacia omacka", ("rybacia omacka",), ()),
        ("banh pho", ("pho",), ()),
        ("hoisin", ("hoisin",), ()),
        ("sriracha", ("sriracha",), ()),
    ],
    "banh_mi": [
        ("ryzovy ocot", ("ryzovy", "ocot"), ()),
        ("rybacia omacka", ("rybacia omacka",), ()),
        ("sriracha", ("sriracha",), ()),
        ("sojova omacka", ("sojova omacka",), ()),
    ],
    "nam_van": [
        ("ryzovy papier", ("ryzovy", "papier"), ()),
        ("ryzove rezance", ("rezance",), ()),
        ("rybacia omacka", ("rybacia omacka",), ()),
        ("sweet chili omacka", ("chili", "omacka"), ()),
    ],
    "bun_cha": [
        ("ryzove rezance", ("rezance",), ()),
        ("rybacia omacka", ("rybacia omacka",), ()),
        ("ryzovy ocot", ("ryzovy", "ocot"), ()),
        ("cili cesnak omacka", ("cesnak", "omacka"), ()),
    ],
    "bun_bo_nam_bo": [
        ("ryzove rezance", ("rezance",), ()),
        ("citronova trava", ("citronova trava",), ()),
        ("rybacia omacka", ("rybacia omacka",), ()),
        ("hoisin", ("hoisin",), ()),
        ("sezamovy olej", ("sezamovy olej",), ()),
    ],
    "nuoc_cham": [
        ("rybacia omacka", ("rybacia omacka",), ()),
        ("ryzovy ocot", ("ryzovy", "ocot"), ()),
        ("cili cesnak omacka", ("cesnak", "omacka"), ()),
        ("sweet chili omacka", ("chili", "omacka"), ()),
    ],
    "banh_gio": [
        ("ryzova muka", ("ryzova", "muka"), ()),
        ("rybacia omacka", ("rybacia omacka",), ()),
        ("shiitake", ("shiitake",), ()),
        ("sojova omacka", ("sojova omacka",), ()),
    ],
    "vietnamska_kuchyna": [
        ("rybacia omacka", ("rybacia omacka",), ()),
        ("ryzovy ocot", ("ryzovy", "ocot"), ()),
        ("sriracha", ("sriracha",), ()),
        ("ryzove rezance", ("rezance",), ()),
    ],
    "rybacia_omacka": [
        ("rybacia omacka", ("rybacia omacka",), ()),
        ("cili cesnak omacka", ("cesnak", "omacka"), ()),
        ("sojova omacka", ("sojova omacka",), ()),
    ],
    "thit_dong": [
        ("rybacia omacka", ("rybacia omacka",), ()),
        ("sojova omacka", ("sojova omacka",), ()),
        ("shiitake", ("shiitake",), ()),
        ("cierne hriby", ("hrib",), ()),
    ],
    "sesame_balls": [
        ("lepkava ryzova muka", ("ryzova", "muka"), ()),
        ("sezamove semienka", ("sezam",), ()),
        ("adzuki pasta", ("adzuki",), ()),
        ("kokosove mlieko", ("kokosove mlieko",), ()),
    ],
    "jjigae": [
        ("kimchi", ("kimchi",), ("instant", "ramen", "polievk", "omack")),
        ("gochujang", ("gochujang",), ()),
        ("doenjang", ("doenjang",), ()),
        ("dashi", ("dashi",), ()),
        ("tofu", ("tofu",), ()),
    ],
    "kimchi_recipe": [
        ("kimchi zaklad", ("kimchi", "zaklad"), ()),
        ("cervena cili paprika", ("cervena", "cili"), ("omacka", "polievka", "arasid")),
        ("rybacia omacka", ("rybacia omacka",), ()),
        ("ryzova muka", ("ryzova", "muka"), ("lepkava",)),
        ("zazvor cesnak", ("zazvor",), ("nakladany", "susi", "sushi")),
    ],
    "japchae": [
        ("sklenene rezance", ("sklenene", "rezance"), ()),
        ("sojova omacka", ("sojova omacka",), ()),
        ("sezamovy olej", ("sezamovy olej",), ()),
        ("sezamove semienka", ("sezam",), ()),
    ],
    "bulgogi": [
        ("bulgogi omacka", ("bulgogi",), ()),
        ("sojova omacka", ("sojova omacka",), ()),
        ("sezamovy olej", ("sezamovy olej",), ()),
        ("gochujang", ("gochujang",), ()),
        ("jazminova ryza", ("jazminova", "ryza"), ()),
    ],
    "fried_rice": [
        ("jazminova ryza", ("jazminova", "ryza"), ()),
        ("kimchi", ("kimchi",), ("instant", "ramen", "polievk", "omack")),
        ("sojova omacka", ("sojova omacka",), ()),
        ("sezamovy olej", ("sezamovy olej",), ()),
    ],
    "bibimbap": [
        ("gochujang", ("gochujang",), ()),
        ("jazminova ryza", ("jazminova", "ryza"), ()),
        ("sezamovy olej", ("sezamovy olej",), ()),
        ("kimchi", ("kimchi",), ("instant", "ramen", "polievk", "omack")),
        ("doenjang", ("doenjang",), ()),
    ],
    "gimbap": [
        ("sushi ryza", ("susi", "ryza"), ("ocot",)),
        ("nori", ("nori",), ()),
        ("sezamovy olej", ("sezamovy olej",), ()),
        ("nakladany zazvor", ("zazvor",), ()),
    ],
    "kari": [
        ("kari pasta", ("kari", "pasta"), ()),
        ("kokosove mlieko", ("kokosove mlieko",), ()),
        ("jazminova ryza", ("jazminova", "ryza"), ()),
        ("rybacia omacka", ("rybacia omacka",), ()),
    ],
    "thajske_kari": [
        ("kokosove mlieko", ("kokosove mlieko",), ()),
        ("cervena kari pasta", ("kari", "pasta"), ()),
        ("jazminova ryza", ("jazminova", "ryza"), ()),
        ("rybacia omacka", ("rybacia omacka",), ()),
    ],
    "japanese_curry": [
        ("japonske kari", ("japonske", "kari"), ()),
        ("golden curry", ("golden", "curry"), ()),
        ("sushi ryza", ("susi", "ryza"), ("ocot",)),
        ("jazminova ryza", ("jazminova", "ryza"), ()),
    ],
    "udon": [
        ("udon rezance", ("udon",), ()),
        ("sojova omacka", ("sojova omacka",), ()),
        ("mirin", ("mirin",), ()),
        ("dashi", ("dashi",), ()),
        ("sezamovy olej", ("sezamovy olej",), ()),
    ],
    "teriyaki": [
        ("teriyaki omacka", ("teriyaki",), ()),
        ("sojova omacka", ("sojova omacka",), ()),
        ("mirin", ("mirin",), ()),
        ("sezamovy olej", ("sezamovy olej",), ()),
        ("jazminova ryza", ("jazminova", "ryza"), ()),
    ],
    "miso_polievka": [
        ("miso pasta", ("miso",), ()),
        ("dashi", ("dashi",), ()),
        ("wakame", ("wakame",), ()),
        ("tofu", ("tofu",), ()),
    ],
    "ramen": [
        ("ramen rezance", ("ramen",), ()),
        ("dashi", ("dashi",), ()),
        ("miso pasta", ("miso",), ()),
        ("sojova omacka", ("sojova omacka",), ()),
        ("wakame", ("wakame",), ()),
    ],
    "tempura": [
        ("tempura muka", ("tempura",), ()),
        ("sojova omacka", ("sojova omacka",), ()),
        ("ryzovy ocot", ("ryzovy", "ocot"), ()),
        ("sezamovy olej", ("sezamovy olej",), ()),
    ],
    "kung_pao": [
        ("sojova omacka", ("sojova omacka",), ()),
        ("cili cesnak omacka", ("cesnak", "omacka"), ()),
        ("sezamovy olej", ("sezamovy olej",), ()),
        ("ryzovy ocot", ("ryzovy", "ocot"), ()),
        ("arasidy", ("arasid",), ()),
    ],
    "mapo_tofu": [
        ("fazulova omacka", ("fazulova", "omacka"), ()),
        ("ma po omacka", ("ma po", "omacka"), ()),
        ("cierna fazula cesnak omacka", ("cierna", "fazula", "omacka"), ()),
        ("cili cesnak omacka", ("cesnak", "omacka"), ()),
        ("sojova omacka", ("sojova omacka",), ()),
    ],
    "suan_la_tang": [
        ("ostro kysla polievka", ("ostro", "kysla", "polievka"), ()),
        ("cierna fazula cesnak omacka", ("cierna", "fazula", "omacka"), ()),
        ("ryzovy ocot", ("ryzovy", "ocot"), ()),
        ("sojova omacka", ("sojova omacka",), ()),
        ("bambusove vyhonky", ("bambus",), ()),
    ],
    "cinska_kuchyna": [
        ("hoisin omacka", ("hoisin",), ()),
        ("sojova omacka", ("sojova omacka",), ()),
        ("ustricova omacka", ("ustricova", "omacka"), ()),
        ("sezamovy olej", ("sezamovy olej",), ()),
    ],
    "tikka_masala": [
        ("tikka masala pasta", ("masala",), ()),
        ("garam masala", ("garam", "masala"), ()),
        ("kokosove mlieko", ("kokosove mlieko",), ()),
        ("basmati ryza", ("basmati", "ryza"), ()),
    ],
    "tandoori": [
        ("tandoori masala", ("tandoori",), ()),
        ("garam masala", ("garam", "masala"), ()),
        ("basmati ryza", ("basmati", "ryza"), ()),
    ],
    "biryani": [
        ("basmati ryza", ("basmati", "ryza"), ()),
        ("biryani pasta", ("biryani",), ()),
        ("garam masala", ("garam", "masala"), ()),
        ("kardamom", ("kardam",), ()),
        ("skorica", ("skorica",), ()),
    ],
    "nasi_goreng": [
        ("sambal oelek", ("sambal",), ()),
        ("sojova omacka", ("sojova omacka",), ()),
        ("rybacia omacka", ("rybacia omacka",), ()),
        ("jazminova ryza", ("jazminova", "ryza"), ()),
    ],
    "mee_goreng": [
        ("mie rezance", ("rezance",), ()),
        ("sojova omacka", ("sojova omacka",), ()),
        ("rybacia omacka", ("rybacia omacka",), ()),
        ("sambal oelek", ("sambal",), ()),
    ],
    "rendang": [
        ("rendang pasta", ("rendang",), ()),
        ("kokosove mlieko", ("kokosove mlieko",), ()),
        ("citronova trava", ("citronova trava",), ()),
        ("galangal", ("galangal",), ()),
        ("kaffirove listy", ("kaffir",), ("bambus", "caj")),
    ],
    "nasi_lemak": [
        ("jazminova ryza", ("jazminova", "ryza"), ()),
        ("kokosove mlieko", ("kokosove mlieko",), ()),
        ("sambal oelek", ("sambal",), ()),
        ("arasidy", ("arasid",), ()),
        ("rybacia omacka", ("rybacia omacka",), ()),
    ],
    "hainanese_chicken": [
        ("jazminova ryza", ("jazminova", "ryza"), ()),
        ("sezamovy olej", ("sezamovy olej",), ()),
        ("sojova omacka", ("sojova omacka",), ()),
        ("cili cesnak omacka", ("cesnak", "omacka"), ()),
        ("zazvor", ("zazvor",), ()),
    ],
    "singapore_noodles": [
        ("ryzove rezance", ("rezance",), ()),
        ("kari korenie", ("kari",), ()),
        ("sojova omacka", ("sojova omacka",), ()),
        ("sezamovy olej", ("sezamovy olej",), ()),
    ],
    "sinigang": [
        ("sinigang", ("sinigang",), ()),
        ("tamarind", ("tamarind",), ()),
        ("rybacia omacka", ("rybacia omacka",), ()),
    ],
}

# V2.6 cross-sell mines these two curated dicts (recipe ingredient
# roles, use-case companion products) - handed in once here rather
# than imported the other way, so app/cross_sell.py never depends on
# app/main.py (Section 110).
_cross_sell.set_data_sources(RECIPE_SHOPPING_CORE_QUERIES, SPECIAL_PRODUCT_QUERIES)

# V2.8 recipe/ingredient knowledge graph (Section 64/65/66) - built once
# here, rebuilt in lockstep with `products`/`product_taxonomy_index` in
# refresh_feed(). Grounded entirely in already-curated, already-in-
# production data (docs/recipe-knowledge-audit.md); never invents recipe
# or ingredient facts.
recipe_graph_index = _build_recipe_graph_index(
    products=products,
    taxonomy_index=product_taxonomy_index,
    normalized_index=normalized_product_index,
    recipe_shopping_core_queries=RECIPE_SHOPPING_CORE_QUERIES,
    missing_ingredients_by_subject=MISSING_INGREDIENTS_BY_SUBJECT,
    recipe_title_product_subjects=RECIPE_TITLE_PRODUCT_SUBJECTS,
    cms_recipes=knowledge.get("sections", {}).get("Recipes", []),
    products_ai=knowledge.get("sections", {}).get("Products_AI", []),
    special_product_queries=SPECIAL_PRODUCT_QUERIES,
)


RELATED_INTENT_MARKERS = (
    "co na",
    "co k",
    "co ku",
    "ukaz viac",
    "ukazte viac",
    "suvisiace",
    "hodi",
    "hodia",
    "vyrob",
    "priprav",
    "ingredien",
    "surovin",
    "potrebujem",
    "kupit",
    "produkty na",
    "varit",
    "odporuc",
    "doplnky",
    "recept",
    "urobit",
    "spravit",
    "nakupny zoznam",
    "nesmie",
    "chybat",
    "chyba",
    "chybaju",
    "treba",
    "treba kupit",
    "potrebne",
    "co este",
    "este chybat",
    "este chyba",
    "robim",
    "patri",
    "nakupujem",
    "doplnky k",
    "co k tomu",
    "zacinam",
    "dam do",
    "davam do",
    "do woku",
    "na dezert",
    "na ranajky",
    "na obed",
    "na vecer",
    "pripravujem",
    "chystam",
    "planujem",
    "co este",
    "este nieco",
    "kuchynu",
    "kuchyni",
    "jedlo",
    "veceru",
    "obed",
    "ranajky",
    "snack",
    "grilovanie",
    "grilovacku",
    "varim",
    "chcem",
    "nakupovat",
    "co dame",
    "co dat",
    "co pouzit",
    "na varenie",
    "do polievky",
    "do omacky",
    "do marinady",
    "omacku",
    "polievku",
    "na grilovanie",
    "dam",
    "skusam",
    "vyskusam",
    "chceme",
    "co pridat",
    "k recepty",
    "k receptu",
    "zvyknu",
    "hodiat",
    "co jest", "co si dat", "co dat na stol", "jest so", "jest k", "co hodia",
    "na film", "k filmu", "k serialu", "na serial", "na snack",
    "polievky", "pre vegetarianov", "pre deti", "pre alergikov",
    "vegetariansk", "bezmasov", "vegetarian", "vegan", "spicy", "gluten free",
    "dinner", "lunch", "meal", "cooking", "recipe",
    "vecer", "obedom", "ranom",
    "what do i need", "what to buy", "what goes with",
    "supplies", "party",
    "making", "tonight", "want to make", "need to make", "going to make",
    "want to cook", "going to cook", "how to make", "i make",
    "ideas", "food ideas", "dinner ideas",
    "should i", "night", "grocery", "shopping list", "items", "needed",
    "what to get", "stuff for", "things to buy", "week", "pantry",
    "dokup", "zobrat", "zoznam",
    "at home", "cook", "easy", "learn to",
    "budget", "toppings", "topping", "upgrade", "to buy",
    "sauce", "oil", "seasoning", "spice", "sides", "noodle",
    "korenie", "olej", "rezanc", "polevk", "ocot",
    "skus", "pridat",
    "serve", "pair", "side dish", "goes well",
    "podavat", "dodat", "dobavit",
    "prep", "food prep",
    "kuchyn", "veci", "potrebuj", "koupit",
    "svadba", "sviatok", "vianoc", "silvester", "novy rok",
    "romantick", "specialn", "priatelk", "co si dat", "valentin",
    "robit", "zostalo", "dochut", "poloz", "koreni", "dnes",
    "nahrad", "alternativ", "namiesto", "replacement", "substitute", "instead",
    "jedl", "vecer",
    "darek", "darcek", "gift", "present", "mnozstvo", "kus",
    "jednoduch", "maju rad", "pacia", "miluj",
    "varil", "prvykrat", "zleps", "marin", "namach", "japons",
    # beverage pairing, ingredient-type questions, recommendation, usage/substitution
    "najleps", "pijem", "pije", "pijeme", "pouzit", "mozem",
    "omack", "nieco", "ake", "aky", "akou",
    "ktor", "lepsi", "doplnok",
    "doplni", "kombin", "s cim",
    "nosi", "servir", "spar", "prispiev",
    "ochut", "vyuzi", "zvys",
    # garnish/fill/spread/EN pairing
    "posyp", "napln", "namaz", "ozob", "cim",
    "condiment", "go with", "goes with", "could i", "can i", "ide k",
    # flavour/quality comparative adjectives
    "pikan", "chutnejsi", "zdrav", "sladk", "kysl",
    # EN usage/method queries
    "best way", "how to use", "season", "objedn",
    # ingredient composition queries SK
    "obsah", "sklad", "z coho", "ide do", "obsahuj",
    # diet/health/texture/substitution queries
    "bezgluten", "nizkokalor", "dietn", "verzia",
    "chrumkav", "kremov", "umami", "nahrad",
    # heat/spice balancing, garnish, decoration, storage
    "zniz", "palivost", "zmier", "ostrost", "neutral",
    "garnish", "ozdobi", "uchov",
    # ratio/comparison/sourcing/side-dish queries
    "pomer", "rozdiel", "zohnat", "prikrm",
    # thickening/seasoning/mixing/marinating
    "zahust", "dochuc", "naklad", "zmiesat",
    # flavor enrichment / intensification
    "obohati", "intenz", "zintenz", "povys", "hutnej",
    # upgrade / typical / cuisine-characteristic queries
    "upgrad", "typick", "charakter", "autent",
    # side-dish, beverage-pairing (tea/wine/beer with dish), protein, ingredient-into-dish, recipe-base
    "priloha", "caj", "vino", "pivo", "tofu", "protein", "bielkovin", "baza", "co do",
    # what-is / what-to-put / Czech food spelling / all pouzi* forms
    "co je", "co dat", "jidl", "pouziva",
    # Slovak dative preposition k/ku/ko + space — strongest pairing signal possible
    "k ", "ku ", "ko ",
    # finger food / snack context
    "finger food",
    # meatless / plant-based queries
    "bez mas", "bez mäs",
    "na co",
    "vs",
    "co s",
    "varen",
)

RECIPE_INTENT_MARKERS = (
    "recept",
    "reept",
    "recet",
    "navod",
    "postup",
    "ako spravim",
    "ako pripravim",
    "ako urobim",
    "recipe",
    "how to make",
    "how do i make",
    "how to cook",
    "how do i cook",
    "how do i prepare",
    "jak udelam",
    "jak pripravim",
    "jak uvarim",
    "vindaloo",
    "karaage",
    # Real user report: "co potrebujem na tom kha gai" (a shopping-list
    # style question, no "recept"/how-to wording at all) fell through
    # is_recipe_intent() entirely and got misrouted into the generic
    # cross-sell branch instead of the recipe_to_products workflow that
    # already has a real Tom Kha Gai recipe card and missing-ingredient
    # mapping. Same fix pattern as vindaloo/karaage above: a bare dish
    # marker so the recipe workflow is reachable without the word
    # "recept".
    "tom kha",
    # V2.8 Section 100/142 target scenario ("Chcem robit Pad Thai") -
    # same bare-dish-marker fix pattern as vindaloo/karaage/tom kha above.
    "pad thai",
)
# V2.14d (Section 27-34, docs/use-case-recipe-data-quality-v2.14d.md) -
# the subset of RECIPE_INTENT_MARKERS above that are bare dish NAMES
# rather than genuine recipe-action words ("recept"/"navod"/"ako
# uvarim"/...). A message matching ONLY one of these (no other recipe
# marker, no shopping-list language) is ambiguous between "show me a
# recipe" and "answer a specific product/attribute question that
# happens to name this dish" (e.g. "ake kokosove mlieko na tom kha
# gai?") - see _recipe_intent_is_bare_dish_marker_only() below, which
# lets a specific, resolvable use-case role win that narrow case
# generically, without weakening recipe detection for every other
# message (explicit "recept na X"/"co potrebujem na X" are unaffected).
_BARE_DISH_RECIPE_MARKERS = ("tom kha", "pad thai")

RANDOM_RECIPE_INTENT_MARKERS = (
    "co dnes varit",
    "co varit na veceru",
    "co sa vari na veceru",
    "co uvarit na veceru",
    "co dnes uvarimc",
    "co uvarimc dnes",
    "tip na veceru",
    "recept na veceru",
    "vecera dnes",
    "nahodny recept",
    "nahodne recept",
    "co by som dnes",
    "co si dat dnes",
    "co bych si dal dnes",
    "what should i cook",
    "what to cook for dinner",
    "dinner idea",
    "recipe idea",
    "random recipe",
    "surprise me with a recipe",
)


ALREADY_HAVE_MARKERS = (
    "mam ",
    "mam doma ",
    "mam uz ",
    "kupil som ",
    "vlastnim ",
    "mám ",
    "mám doma ",
    "mám uz ",
    "kúpil som ",
    "vlastním ",
)

ALREADY_HAVE_SUBJECT_MAP = {
    "sojova_omacka": ("sojovu omacku", "sojovej omacke", "sojova omacka", "sojovku", "sojovou omackou"),
    "kimchi": ("kimchi",),
    "ramen": ("ramen", "ramyeon", "ramyun"),
    "ryza": ("ryzu", "ryzou", "ryzy", "ryze", "ryzi", "bielu ryzu", "jasminovu ryzu", "jasminovej", "jasminov", "sushi ryzu"),
    "kokos": ("kokosove mlieko", "kokosoveho mlieka", "kokosovym mliekom"),
    "miso": ("miso pastu", "miso pastu", "miso"),
    "nori": ("nori", "morske riasy"),
    "tofu": ("tofu",),
    "gochujang": ("gochujang",),
    "sriracha": ("sriracha", "srirachu", "srirachom"),
    "ryzovy_ocot": ("ryzovy ocot", "ryzovom octe", "sushi ocot", "ocot na sushi", "ryzi ocot"),
    "wasabi": ("wasabi",),
    "udon": ("udon", "udon rezance", "udon rezancov"),
    "hoisin": ("hoisin", "hoisin omacku", "hoisin omacka", "hoisin omacke"),
    "rybacia_omacka": ("rybaciu omacku", "rybacia omacka", "rybacou omackou", "fish sauce"),
    "sezamovy_olej": ("sezamovy olej", "sezamovym olejom"),
    "kari": ("kari pastu", "kari omacku", "kari", "curry"),
    "gyoza": ("gyozu", "gyoza", "gyozove cestoviny", "gyozovych cestoviny"),
    "mochi": ("mochi",),
    "dashi": ("dashi", "dashi bujonu", "dashi stock"),
    "edamame": ("edamame",),
    "rezance": ("udon rezance", "ramen rezance", "ryze rezance", "rezancov", "rezance"),
    "nakladany_zazvor": ("nakladany zazvor", "nakladaneho zazvoru", "zazvor na sushi"),
    "wakame": ("wakame", "morske riasy wakame"),
    "panko": ("panko", "panko struhanka"),
    "ryzovy_papier": ("ryzovy papier", "ryzoveho papiera", "rice paper", "ryzovy papier na zavitky"),
    "gochugaru": ("gochugaru", "kórejske chilli", "korejske cili"),
    "matcha": ("matcha", "matchu", "matchou"),
    "sezamove_semienka": ("sezamove semienka", "sezamovych semienok", "sezam"),
    "pad_thai_omacka": ("pad thai omacku", "pad thai omacka", "pad thai sauce"),
    "sweet_chili": ("sweet chili", "sladku chili", "sladka chili", "sweet chilli"),
    "tamarind": ("tamarind", "tamarindu"),
    "pocky": ("pocky",),
    "bubble_tea": ("bubble tea", "boba tea", "bubble tea prasok"),
    "ustricova_omacka": ("ustricovu omacku", "ustricova omacka", "oyster sauce"),
    "ponzu": ("ponzu", "ponzu omacku"),
    "doenjang": ("doenjang", "korejska sojova pasta"),
    "ssamjang": ("ssamjang",),
    "chilli_olej": ("chilli olej", "cili olej", "chilli olejom", "cili olejom"),
    "mirin": ("mirin", "mirinom", "mirin na varenie"),
    "sake": ("sake", "ryžové víno sake", "ryzove vino sake"),
}

ALREADY_HAVE_COMPLEMENT_QUERIES = {
    "sojova_omacka": ["mirin", "ryzovy ocot", "hoisin omacka", "sezamovy olej", "dashi"],
    "kimchi": ["ramen rezance", "gochujang", "jazminova ryza", "sezamovy olej", "miso pasta"],
    "ramen": ["miso pasta", "wakame", "kimchi", "sezamovy olej", "dashi"],
    "ryza": ["sojova omacka", "rybacia omacka", "mirin", "tofu", "kimchi"],
    "kokos": ["kari pasta cervena", "rybacia omacka", "jazminova ryza", "sriracha"],
    "miso": ["dashi", "tofu", "wakame", "ramen rezance", "nori"],
    "nori": ["sushi ryza", "wasabi", "ryzovy ocot", "nakladany zazvor", "sojova omacka"],
    "tofu": ["sojova omacka", "sezamovy olej", "gochujang", "miso pasta", "rybacia omacka"],
    "gochujang": ["sezamovy olej", "jazminova ryza", "kimchi", "ssamjang", "ramen"],
    "sriracha": ["kokosove mlieko", "rybacia omacka", "jazminova ryza", "ramen"],
    "sezamovy_olej": ["sojova omacka", "ryzovy ocot", "mirin", "gochujang", "kimchi"],
    "kari": ["kokosove mlieko", "jazminova ryza", "rybacia omacka", "koriander", "sriracha"],
    "ryzovy_ocot": ["sushi ryza", "nori", "wasabi", "nakladany zazvor", "sojova omacka"],
    "ocot": ["cukor", "sezamovy olej", "sojova omacka", "cesnak", "cili omacka"],
    "wasabi": ["sojova omacka", "nakladany zazvor", "nori", "sushi ryza", "ryzovy ocot"],
    "udon": ["sojova omacka", "dashi", "wakame", "miso pasta", "sriracha"],
    "hoisin": ["sojova omacka", "sezamovy olej", "ramen rezance", "udon", "sriracha"],
    "rybacia_omacka": ["ryzove rezance", "sriracha", "hoisin omacka", "nakladany zazvor", "kokosove mlieko"],
    "gyoza": ["sojova omacka", "ryzovy ocot", "chilli olej", "sriracha"],
    "mochi": ["pocky", "bubble tea", "ryzove krekry", "kokosove cukriky"],
    "dashi": ["miso pasta", "tofu", "wakame", "ramen rezance"],
    "edamame": ["sojova omacka", "wasabi", "sezamovy olej", "sriracha"],
    "rezance": ["sojova omacka", "sezamovy olej", "sriracha", "ustricova omacka", "dashi"],
    "nakladany_zazvor": ["sushi ryza", "nori", "wasabi", "sojova omacka", "ryzovy ocot"],
    "wakame": ["miso pasta", "dashi", "tofu", "ramen rezance", "nori"],
    "panko": ["tonkatsu omacka", "sojova omacka", "wasabi", "ryzovy ocot"],
    "ryzovy_papier": ["ryzove rezance", "rybacia omacka", "sweet chili omacka", "sriracha"],
    "gochugaru": ["gochujang", "kimchi", "sezamovy olej", "sojova omacka", "jazminova ryza"],
    "matcha": ["mochi", "bubble tea", "pocky", "ryzove krekry"],
    "sezamove_semienka": ["sezamovy olej", "sojova omacka", "mirin", "ryzovy ocot"],
    "pad_thai_omacka": ["ryzove rezance", "rybacia omacka", "tamarind", "arasidy", "sriracha"],
    "sweet_chili": ["ryzovy papier", "sriracha", "rybacia omacka", "ramen rezance"],
    "tamarind": ["rybacia omacka", "kokosove mlieko", "kari pasta cervena", "sriracha"],
    "pocky": ["mochi", "bubble tea", "ryzove krekry", "matcha"],
    "bubble_tea": ["pocky", "mochi", "matcha", "ryzove krekry"],
    "ustricova_omacka": ["sojova omacka", "sezamovy olej", "sriracha", "ramen rezance"],
    "ponzu": ["sojova omacka", "nakladany zazvor", "wasabi", "nori", "sushi ryza"],
    "doenjang": ["gochujang", "sezamovy olej", "kimchi", "tofu", "jazminova ryza"],
    "ssamjang": ["gochujang", "sezamovy olej", "kimchi", "jazminova ryza"],
    "chilli_olej": ["sojova omacka", "ryzovy ocot", "sezamovy olej", "sriracha"],
    "mirin": ["sojova omacka", "dashi", "ryzovy ocot", "sezamovy olej"],
    "sake": ["mirin", "sojova omacka", "dashi", "sushi ryza"],
}

ALLERGEN_INTENT_MARKERS = (
    "alerg",
    "alergen",
    "bez soj",
    "bez soja",
    "bezlepk",
    "obsahuje",
    "neobsahuje",
    "neznasam",
    "intoler",
    "celiak",
    "celiaki",
    "lakto",
    "vhodn",
    "zlozen",
    "allerg",
    "gluten free",
    "does it contain",
    "does not contain",
    "suitable for",
    "ingredients",
)

ALLERGEN_TERMS = {
    # BUG-01 fix: zluceny do jedneho dict, akcentovane user-facing labely zachovane
    "soja": "sóju",
    "soj": "sóju",
    "lepok": "lepok",
    "gluten": "lepok",
    "arasid": "arašidy",
    "orech": "orechy",
    "mlieko": "mlieko",
    "lakto": "laktózu",
    "vajc": "vajcia",
    "sezam": "sezam",
    "ryb": "ryby",
    "makky": "mäkkýše",
    "krev": "krevety",
}

# Subset of ALLERGEN_TERMS that is unambiguous allergen vocabulary on
# its own - unlike "mlieko"/"ryb"/"vajc"/"orech", which are also just
# plain grocery nouns. Used to safely widen bare "ma/je/su X?" allergen
# questions without misrouting generic product questions that happen to
# name a food (e.g. "aku ma chut toto mlieko").
# NOTE: "soja"/"soj" were removed after a real regression - "sojova
# omacka" (soy sauce) is one of the store's flagship product
# categories, and the extremely common word "je" ("is") co-occurs with
# it constantly ("co je lepsie svetla alebo tmava sojova omacka?",
# "aka je cena kikkoman sojovej omacky?") - both got misrouted into an
# allergy warning instead of answering the actual question. "soja"/
# "soj" turned out to be exactly the kind of ambiguous grocery noun
# this list was designed to exclude, same as "mlieko"/"orech".
BARE_ALLERGEN_QUESTION_TERMS = ("lepok", "gluten", "arasid", "sezam", "makky", "krev")

OUT_OF_DOMAIN_MARKERS = (
    # --- potravinovy obchod: existujuce markery ---
    "bicyk",
    "notebook",
    "opravujete telefon",
    "poistenie auta",
    "pocasie",
    "basen",
    "letenk",
    "prack",
    "stavebn",
    "danov",
    "taxik",
    "taxi",
    " liek",
    " predpis",
    "akcie",
    "burz",
    "krypto",
    "kryptomen",
    "bitcoin",
    "ethereum",
    "hypotek",
    "nahradne diely",
    "diely do auta",
    "krmivo",
    "psov",
    "psa",
    " lekar",
    " lekara",
    "zdravotn",
    "diagnoz",
    "jedalnick",
    # --- elektronika ---
    "televizor",
    "televiz",
    "smartphon",
    "laptop",
    "pocitac",
    "sluchadl",
    "reproduktor",
    "fotoaparat",
    "tlaciare",
    "hernu konzol",
    "mobil telefon",
    "kupim telefon",
    "aky telefon",
    # --- oblecenie a obuv ---
    "oblecen",
    "topank",
    "sandal",
    "nohavic",
    "sukn",
    "saty",
    "sveter",
    "ponozk",
    "spodna bielizen",
    "tenisk",
    # --- nabytok a domacnost ---
    "nabytok",
    "nabytku",
    "matrac",
    "kreslo",
    "skrink",
    "komoda",
    # --- vozidla ---
    "auto servis",
    "pneumatik",
    "motorka",
    "elektricke auto",
    "ojazdene auto",
    # --- nehnutelnosti ---
    "nehnutelnost",
    "prenajom bytu",
    "kupim byt",
    "predaj domu",
    "realitna",
    # --- kozmetika ---
    "parfum",
    "kozmetika",
    "lak na nechty",
    # --- financie ---
    "kryptomien",
    "bitcoin",
    "investici",
    # --- praca a zamestnanie ---
    "zivotopis",
    "pracovnu ponuku",
    "pracovne miesto",
    # --- sport a volny cas ---
    "lyze",
    "lyzovania",
    "futbalov",
    "basketbal",
    # --- cestovanie ---
    "hotelovu rezervaci",
    "dovolenk",
    # --- zabava a media ---
    # Real user report: "aky je najlepsi film?" (general entertainment
    # trivia, not a Foodland question) fell through detect_out_of_domain()
    # entirely and got answered with a confident-sounding but nonsensical
    # product search. Deliberately NOT the bare words "film"/"serial" -
    # those are substrings of the existing "asian_snack" cross-sell
    # aliases ("na film", "k filmu", "na serial", "k serialu" - "co si
    # dat na film" is a legitimate snack request), so only specific
    # multi-word phrases are used here to avoid that collision.
    "najlepsi film",
    "najlepsi serial",
    "aky film mi",
    "dobry film odporuc",
    "filmovu recenziu",
    "herec vo filme",
    # --- vseobecne znalosti a politika ---
    "kto je prezident",
    "hlavne mesto",
    "kto vyhral volby",
    "politicku stranu",
    # --- domace ulohy a skola ---
    "domacu ulohu",
    "domaca uloha",
    "domacou ulohou",
    "domacej ulohy",
    "referat na tema",
)

# Real user report: "aku kategoriu produktov mate?" and similar generic
# inventory questions either dead-ended with an unhelpful empty answer
# or, worse, confidently presented RANDOM irrelevant products as "most
# relevant" (cached_search_products() always finds *something* via
# token/fuzzy matching, even for filler words). category_discovery is a
# canonical V2 primary intent (see app/intent.py) with no detector at
# all in the legacy cascade. Exact-message match (not substring) so a
# longer, specific query like "aky tovar mate na sushi?" is never swept
# in - only bare "what do you sell" style questions with nothing else
# in them.
CATEGORY_DISCOVERY_MARKERS = frozenset((
    "aku kategoriu produktov mate",
    "ake kategorie produktov mate",
    "co vsetko predavate",
    "aky sortiment mate",
    "ake znacky predavate",
    "aky tovar mate",
))

# product_type breadcrumb segments that are cross-cutting dietary/
# marketing tags, not real navigational categories - excluded from the
# category-discovery answer so it reads like an actual department list
# ("Sojove omacky, Korenie, Cajove prislusenstvo...") rather than a mix
# of attribute tags ("Vegan", "Zdrave potraviny", "Darcekove sety"...).
CATEGORY_DISCOVERY_NOISE = frozenset((
    "veganske potraviny",
    "vegetarianske potraviny",
    "zdrave potraviny",
    "super potraviny",
    "bezlepkove potraviny",
    "susene produkty",
    "darcekove sety",
    "darcekove poukazy",
    "bio potraviny",
    "horeca - pre hotely, restauracie, catering",
    "box asia to go",
))

# BUG-03 fix: OpenAI client singleton – nevytvara novy connection pool pri kazdom requeste
_openai_client: OpenAI | None = None


def _get_openai_client() -> OpenAI | None:
    """Vrati singleton OpenAI klienta. None ak OPENAI_API_KEY nie je nastaveny."""
    global _openai_client
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    if _openai_client is None:
        timeout = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "6"))
        _openai_client = OpenAI(api_key=api_key, timeout=timeout, max_retries=0)
    return _openai_client


# RETRY-01: Retry pre transientne OpenAI chyby (rate limit, timeout, connection)
# Max 3 pokusy, exponencialne backoff 1s → 2s → 4s, ostatne vynimky padaju okamzite.
@retry(
    retry=retry_if_exception_type((RateLimitError, APITimeoutError, APIConnectionError)),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _call_openai_with_retry(client: OpenAI, messages: list[dict], model: str, max_tokens: int | None = None) -> str:
    """
    Zavola OpenAI chat completion s retry pri transientnych chybach.
    Vracia text odpovede alebo prazdny retazec ak choices[0].message.content je None.
    """
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
        max_tokens=max_tokens if max_tokens is not None else int(os.getenv("OPENAI_MAX_TOKENS", "120")),
    )
    return response.choices[0].message.content or ""


app = FastAPI(title="Foodland AI Agent", version="0.1.0")
app.mount("/static", UTF8StaticFiles(directory=Path(__file__).parent), name="static")

allowed_origins = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "https://www.foodland.sk,https://foodland.sk").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _learning_health_summary() -> dict:
    """Section 98 - aggregate-only, never raw events."""
    summary = {
        "learning_engine_enabled": _LEARNING_ENGINE_ENABLED,
        "active_ranking_config": get_active_ranking_profile_version(),
        "last_learning_cycle_status": None,
        "shadow_candidate_count": 0,
    }
    try:
        report_path = _LEARNING_REPORTS_DIR / "latest.json"
        if report_path.exists():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            summary["last_learning_cycle_status"] = report.get("status")
            summary["shadow_candidate_count"] = (report.get("candidate_summary") or {}).get("shadow_eligible", 0)
    except Exception:
        pass
    return summary


def _durable_storage_health_summary() -> dict:
    """Section 111/112 - durable storage must be observable, not assumed.
    `*_uses_git_tracked_default` / `*_uses_unmounted_default` is True precisely
    when that path is still on the git-tracked/unmounted default it has today
    (docs/runtime-state-inventory.md finding 2/3) - i.e. neither FOODLAND_DATA_DIR
    nor the per-item override env var has been set, so a redeploy will reset or
    revert it."""
    return {
        "foodland_data_dir_configured": _foodland_data_dir_configured(),
        "foodland_data_dir": str(_foodland_data_dir()),
        "ranking_profile_dir": str(_RANKING_PROFILE_DIR),
        "ranking_profile_dir_uses_git_tracked_default": _RANKING_PROFILE_DIR == Path("config/ranking_profiles"),
        "active_ranking_profile_degraded": _ranking_profile_degraded(),
        "learning_history_dir": str(_LEARNING_HISTORY_DIR),
        "learning_history_dir_uses_unmounted_default": _LEARNING_HISTORY_DIR == Path("config/learning_history"),
        "learning_history_dir_exists": _LEARNING_HISTORY_DIR.exists(),
    }


def _search_quality_health_summary() -> dict:
    """Section 65 - public /health may expose only aggregate SAFE
    status, never anomaly details or raw traces (that stays behind
    admin READ scope - see /admin/search-quality/*)."""
    baseline = _load_search_quality_baseline()
    canary = _load_last_search_quality_canary()
    return {
        "search_quality_monitor_enabled": True,
        "last_quality_report_status": "available" if baseline is not None else "insufficient_data",
        "last_canary_status": ("pass" if canary.get("all_passed") else "fail") if canary else "never_run",
        "production_quality_baseline_present": baseline is not None,
    }


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "products": len(products),
        "knowledge": knowledge.get("counts", {}),
        "last_feed_refresh_at": last_feed_refresh_at,
        "last_feed_refresh_error": last_feed_refresh_error,
        "learning": _learning_health_summary(),
        "durable_storage": _durable_storage_health_summary(),
        "search_quality": _search_quality_health_summary(),
    }


@app.post("/products/search")
def product_search(request: ProductSearchRequest) -> dict:
    return {"products": hybrid_cached_search_products(request.query, request.limit)}


@app.post("/products/suggest")
def product_suggest(request: ProductSuggestRequest) -> dict:
    return {"suggestions": cached_autocomplete_suggestions(products, request.query, request.limit)}


@app.get("/products/facets")
def product_facets() -> dict:
    return cached_product_facets(products)


@app.post("/products/filter")
def product_filter(filter_request: ProductFilterRequest) -> dict:
    if filter_request.query.strip():
        candidates = cached_search_products(products, filter_request.query, 200)
    else:
        candidates = [format_product(product) for product in products]

    filtered = filter_products(
        candidates,
        price_min=filter_request.price_min,
        price_max=filter_request.price_max,
        brand=filter_request.brand,
        availability=filter_request.availability,
        category=filter_request.category,
        dietary=filter_request.dietary,
    )
    return {
        "products": filtered[: filter_request.limit],
        "total_matches": len(filtered),
    }


@app.post("/search/autocomplete")
def search_autocomplete_endpoint(request: SearchAutocompleteRequest, fastapi_request: Request) -> dict:
    client_key = get_client_key(fastapi_request)
    profile_key = user_memory_key(request.client_id, client_key)
    user_profile = get_user_memory(profile_key) if USER_MEMORY_ENABLED else {}
    return {
        "suggestions": search_autocomplete(
            products,
            knowledge,
            request.query,
            request.limit,
            user_profile,
        )
    }


@app.get("/search/semantic")
def semantic_search_endpoint(request: Request, query: str = "", limit: int = 8) -> dict:
    client_key = get_client_key(request)
    enforce_semantic_search_rate_limit(client_key)

    openai_client = _get_openai_client()
    if openai_client is None:
        return {"products": [], "error": "Semantic search is not available (no OpenAI API key configured)."}

    safe_limit = max(1, min(int(limit or 8), 20))
    embeddings = cached_product_embeddings()
    if not embeddings:
        return {"products": [], "error": "No product embeddings have been generated yet."}

    scored = semantic_search(openai_client, query, embeddings, safe_limit)
    results = []
    for product_id, score in scored:
        product = find_product_by_id(products, product_id)
        if not product:
            continue
        formatted = format_product(product)
        formatted["similarity"] = round(score, 4)
        results.append(formatted)

    return {"products": results}


@app.get("/autocomplete")
def autocomplete(request: Request, q: str = "", limit: int = 4, client_id: str = "") -> dict:
    client_key = get_client_key(request)
    enforce_autocomplete_rate_limit(client_key)

    safe_limit = max(1, min(int(limit or 4), 12))
    top_questions = cached_top_questions()
    product_suggestions = autocomplete_products(products, q, safe_limit)
    if USER_MEMORY_ENABLED:
        profile_key = user_memory_key(client_id, client_key)
        user_profile = get_user_memory(profile_key)
        product_suggestions = personalize_products(product_suggestions, user_profile)

    return {
        "products": product_suggestions,
        "categories": autocomplete_categories(products, q, 3),
        "brands": autocomplete_brands(products, q, 3),
        "top_questions": autocomplete_questions(top_questions, q, 3),
    }


@app.get("/suggested-questions")
def public_suggested_questions(days: int = 14, limit: int = 5) -> dict:
    events = read_analytics_events(max(1, min(int(days or 14), 60)))
    min_count = int(os.getenv("PUBLIC_SUGGESTED_QUESTION_MIN_COUNT", "2") or 2)
    return {"questions": public_suggested_question_rows(events, limit, min_count)}


@app.post("/knowledge/search")
def knowledge_search(request: KnowledgeSearchRequest) -> dict:
    results = search_knowledge(knowledge, request.query)
    return {
        "summary": knowledge_summary(results),
        "results": results,
    }


@app.post("/memory/clear")
def clear_user_memory(clear_request: MemoryClearRequest, request: Request) -> dict:
    client_key = get_client_key(request)
    profile_key = user_memory_key(clear_request.client_id, client_key)
    memories = load_user_memories()
    removed = profile_key in memories
    memories.pop(profile_key, None)
    save_user_memories()
    return {"cleared": removed}


@app.post("/events")
def track_event(
    event_request: EventRequest,
    request: Request,
    x_admin_token: str | None = Header(default=None),
    x_execution_context: str | None = Header(default=None),
) -> dict:
    # V2.15d.3 (docs/event-execution-context-isolation-v2.15d.3.md) -
    # /events previously had NO execution-context mechanism at all
    # (unlike /chat), so a live-verification smoke event was
    # indistinguishable from real customer telemetry once durably
    # logged. Reuses the EXACT same server-side-verified resolution as
    # /chat (app.admin_auth token scope check) - a client cannot claim
    # ADMIN_TEST merely by sending the header; it fails closed to
    # CUSTOMER without a valid OPERATIONS/PROMOTION-scope admin token.
    client_key = get_client_key(request)
    event_execution_context = _customer_context()
    if (
        x_execution_context == "ADMIN_TEST"
        and _resolve_admin_token_scope(x_admin_token) in (_SCOPE_OPERATIONS, _SCOPE_PROMOTION)
    ):
        event_execution_context = _admin_test_context()
    if event_execution_context.apply_rate_limit:
        enforce_event_rate_limit(client_key)
    log_event(event_request, client_key, execution_context=event_execution_context)
    return {"ok": True}


@app.get("/recommend/similar")
def recommend_similar(request: Request, sku: str = "", limit: int = 6, client_id: str = "") -> dict:
    safe_limit = max(1, min(int(limit or 6), 20))
    product = find_product_by_id(products, sku)
    if not product:
        return {"sku": sku, "product": None, "recommendations": []}

    record = knowledge_record_by_id(knowledge, "Alternatives", sku)
    prefix = "Alternativa"
    if not record:
        record = knowledge_record_by_id(knowledge, "CrossSell", sku)
        prefix = "Cross-sell"

    recommendations = linked_products_from_record(products, record, prefix, safe_limit) if record else []
    if len(recommendations) < safe_limit:
        seen = {sku} | {item.get("id") or item.get("link") for item in recommendations}
        title = product_field(product, "title")
        for candidate in cached_search_products(products, title, safe_limit + len(seen)):
            key = candidate.get("id") or candidate.get("link")
            if key and key not in seen:
                seen.add(key)
                recommendations.append(candidate)
            if len(recommendations) >= safe_limit:
                break

    if USER_MEMORY_ENABLED:
        profile_key = user_memory_key(client_id, get_client_key(request))
        user_profile = get_user_memory(profile_key)
        recommendations = personalize_products(recommendations[:safe_limit], user_profile)

    return {
        "sku": sku,
        "product": format_product(product),
        "recommendations": recommendations[:safe_limit],
    }


@app.get("/recommend/recipe")
def recommend_recipe(name: str = "", limit: int = 6) -> dict:
    safe_limit = max(1, min(int(limit or 6), 20))
    record = find_recipe_record(knowledge, name)
    if not record:
        return {"recipe": None, "recommendations": []}

    card = recipe_card(record)
    title = card.get("title", "")
    subject = recipe_product_subject_from_title(title)
    fallback_matches = cached_search_products(products, title, safe_limit) if title else []
    recommendations = recipe_shopping_core_products(products, subject, fallback_matches, safe_limit)

    return {"recipe": card, "recommendations": recommendations}


@app.get("/recommend/trending")
def recommend_trending(limit: int = 10) -> dict:
    safe_limit = max(1, min(int(limit or 10), 30))
    return {"recommendations": cached_trending_products(products, safe_limit)}


@app.post("/recommend/basket")
def recommend_basket(basket_request: BasketRecommendRequest, request: Request) -> dict:
    client_key = get_client_key(request)
    enforce_recommend_rate_limit(client_key)
    profile_key = user_memory_key(basket_request.client_id, client_key)
    user_profile = get_user_memory(profile_key) if USER_MEMORY_ENABLED else {}
    recommendations = basket_recommendations(
        products, knowledge, basket_request.skus, basket_request.limit, user_profile
    )
    return {"recommendations": recommendations}


@app.get("/admin/analytics/summary")
def admin_analytics_summary(
    days: int = 7,
    limit: int = 10,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    events = read_analytics_events(days)
    errors = read_error_events(days)
    return analytics_report(events, errors, limit)


@app.get("/admin/analytics/top-questions")
def admin_analytics_top_questions(
    days: int = 7,
    limit: int = 20,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    events = read_analytics_events(days)
    return {"top_questions": top_question_rows(events, limit)}


@app.get("/admin/analytics/no-results")
def admin_analytics_no_results(
    days: int = 7,
    limit: int = 20,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    events = read_analytics_events(days)
    return {"no_results": no_result_rows(events, limit)}


@app.get("/admin/analytics/intents")
def admin_analytics_intents(
    days: int = 7,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    events = read_analytics_events(days)
    return {"intents": intent_rows(events)}


@app.get("/admin/analytics/tasks")
def admin_analytics_tasks(
    days: int = 7,
    limit: int = 20,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    events = read_analytics_events(days)
    errors = read_error_events(days)
    return {"action_items": analytics_action_items(events, errors, limit)}


@app.get("/admin/analytics/events-summary")
def admin_analytics_events_summary(
    days: int = 30,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    events = read_engagement_events(days)
    return events_summary(events)


@app.get("/admin/analytics/events-detail")
def admin_analytics_events_detail(
    days: int = 1,
    limit: int = 50,
    session_id: str | None = None,
    event_type: str | None = None,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """V2.15d.3 follow-up - closes the per-record readback gap the
    aggregate-only events-summary endpoint could not: proves the exact
    execution_context/learning_eligible value a specific durably-logged
    event actually carries (e.g. after a live ADMIN_TEST /events smoke
    verification), instead of only an aggregate count. READ scope, same
    as events-summary - genuinely read-only, no side effects. Records
    are already sanitized at write time (client_hash is a salted hash,
    never raw client_key; query text is already PII-redacted by
    log_event()) so returning full records here adds no new PII
    exposure beyond what events-summary's own source data already is.
    Most-recent-first, capped at 200 records regardless of the
    requested limit to keep the response bounded."""
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    safe_limit = max(1, min(int(limit or 50), 200))
    events = read_engagement_events(days)
    if session_id:
        events = [e for e in events if e.get("session_id") == session_id]
    if event_type:
        events = [e for e in events if e.get("event_type") == event_type]
    events.sort(key=lambda e: e.get("ts", 0), reverse=True)
    return {"count": len(events), "events": events[:safe_limit]}


@app.get("/admin/audit/status")
def admin_audit_status(
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """V2.17.1 - read-only operational status for the customer conversation
    audit stream. READ scope, same as every other /admin/analytics/* GET.
    Returns only non-sensitive counts/booleans - no filesystem paths, no
    salts, no tokens, no customer identity (Section 15)."""
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    return _audit_status()


@app.get("/admin/audit/conversations")
def admin_audit_conversations(
    days: int = 7,
    limit: int = 100,
    conversation_hash: str | None = None,
    intent: str | None = None,
    q: str | None = None,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """V2.17.1 - read-only human investigation API over customer_audit.jsonl
    (app/customer_audit.py). READ scope. Reconstructs what a real customer
    was shown - question/answer (already PII-redacted at write time),
    correlation ids, and allowlisted product groups - without rerunning
    any business logic. A GET here can never mutate ranking, learning,
    profiles, sessions, events, or promotion state (Section 16)."""
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    safe_days = max(1, min(int(days or 7), 90))
    turns = _read_audit_turns(
        days=safe_days,
        limit=limit,
        conversation_hash=conversation_hash,
        intent=intent,
        q=q,
    )
    return {"readonly": True, "days": safe_days, "count": len(turns), "turns": turns}


@app.get("/admin/qa/status")
def admin_qa_status(
    days: int = 1,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """V2.17.2 - read-only aggregate QA status: how many analyzed
    customer turns are PASS/FINDING/UNCERTAIN. READ scope. Runs the
    deterministic app.customer_qa rules ON READ over sanitized
    app.customer_audit turns - never writes to the audit stream, never
    reruns intent/search/ranking/cross-sell/LLM (Section 22)."""
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    safe_days = max(1, min(int(days or 1), 90))
    return _qa_status(days=safe_days)


@app.get("/admin/qa/findings")
def admin_qa_findings(
    days: int = 7,
    limit: int = 100,
    classification: str | None = None,
    severity: str | None = None,
    conversation_hash: str | None = None,
    q: str | None = None,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """V2.17.2 - read-only, evidence-backed QA findings over sanitized
    customer_audit.jsonl turns. READ scope. A finding is a structural
    or known-pattern contradiction in an ALREADY-COMPLETED response -
    never a behavioral/preference judgment, never a training label, and
    automatic_production_change is always false (Section 26 - this
    endpoint can never mutate ranking, learning, promotion, or the
    audit stream itself)."""
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    safe_days = max(1, min(int(days or 7), 90))
    findings = _qa_findings(
        days=safe_days,
        limit=limit,
        classification=classification,
        severity=severity,
        conversation_hash=conversation_hash,
        q=q,
    )
    return {"readonly": True, "days": safe_days, "count": len(findings), "findings": findings}


@app.get("/admin/qa/conversations/{conversation_hash}")
def admin_qa_conversation(
    conversation_hash: str,
    days: int = 90,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """V2.17.2 - full PASS/FINDING/UNCERTAIN QA result for every turn of
    one conversation (identified only by its already-hashed
    conversation_hash - never a raw session_id). READ scope."""
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    safe_days = max(1, min(int(days or 90), 90))
    results = _qa_conversation(conversation_hash, days=safe_days)
    return {"readonly": True, "conversation_hash": conversation_hash, "count": len(results), "turns": results}


@app.get("/admin/qa/reproductions/status")
def admin_qa_reproductions_status(
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """V2.17.3 - non-sensitive operational status for the finding
    reproduction layer. READ scope."""
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    return _reproduction_status()


@app.get("/admin/qa/reproductions/{qa_id}")
def admin_qa_reproduction_offline(
    qa_id: str,
    days: int = 90,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """V2.17.3 - OFFLINE reproduction (Section 18/37): re-evaluates a
    V2.17.2 finding's contract against the SAME immutable historical
    audit turn it was originally computed from. Pure GET, no /chat
    call, no side effects whatsoever - READ scope is sufficient
    because this can never execute customer-facing behavior."""
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    safe_days = max(1, min(int(days or 90), 90))
    return _reproduce_offline(qa_id, days=safe_days)


class QaReproductionRequest(BaseModel):
    qa_id: str = Field(..., min_length=1, max_length=64)


@app.post("/admin/qa/reproductions")
def admin_qa_reproduction_active(
    reproduction_request: QaReproductionRequest,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """V2.17.3 - ACTIVE ADMIN_TEST reproduction (Section 19-23/38): the
    only mode where NOT_REPRODUCED is a meaningful, evidence-grounded
    outcome (does today's code/data still violate the same contract?).
    Executes one isolated /chat-equivalent call - OPERATIONS scope
    minimum (Section 23 hard security boundary: a READ-only token must
    never be able to trigger execution). Accepts ONLY qa_id - the
    server derives the sanitized reproduction input entirely from
    trusted, already-redacted QA evidence (Section 38); execution_context
    is never a request field, so CUSTOMER can never be requested by a
    caller (Section 20/37) - admin_test_context() is forced internally
    by app.customer_qa_reproduction.reproduce_admin_test()."""
    _require_admin_scope(x_admin_token, _SCOPE_OPERATIONS)
    return _reproduce_admin_test(reproduction_request.qa_id)


@app.post("/admin/analytics/events-purge")
def admin_analytics_events_purge(
    purge_request: EventsPurgeRequest,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """V2.15d.3 follow-up - surgical cleanup for specific synthetic/
    test session_ids (e.g. a live ADMIN_TEST verification run that
    fell back to CUSTOMER before a credential was correctly configured,
    or a deliberate negative-control spoof test). PROMOTION scope
    (highest tier) since this is destructive, matching the pattern used
    by rollback_to_last_known_good() elsewhere in this file. Matches
    ONLY by exact session_id equality - never a timestamp range or
    pattern match - so it structurally cannot sweep up real customer
    data by accident. Writes via a temp file + atomic rename so a mid-
    write failure cannot leave events.jsonl truncated or corrupted;
    a line that fails to parse as JSON is preserved untouched rather
    than silently dropped."""
    _require_admin_scope(x_admin_token, _SCOPE_PROMOTION)
    if not purge_request.confirm:
        raise HTTPException(status_code=400, detail="confirm must be true to purge events.")
    target_ids = set(purge_request.session_ids)
    path = Path(os.getenv("EVENTS_LOG_PATH", str(DEFAULT_RUNTIME_LOG_DIR / "events.jsonl")))
    if not path.exists():
        return {"removed": 0, "remaining": 0, "requested_session_ids": sorted(target_ids)}
    kept_lines: list[str] = []
    removed = 0
    with path.open("r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.rstrip("\n")
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                kept_lines.append(line)
                continue
            if record.get("session_id") in target_ids:
                removed += 1
                continue
            kept_lines.append(line)
    tmp_path = path.with_name(path.name + ".purge.tmp")
    with tmp_path.open("w", encoding="utf-8") as file:
        for line in kept_lines:
            file.write(line + "\n")
    tmp_path.replace(path)
    return {"removed": removed, "remaining": len(kept_lines), "requested_session_ids": sorted(target_ids)}


@app.post("/admin/embeddings/rebuild")
def admin_rebuild_embeddings(x_admin_token: str | None = Header(default=None)) -> dict:
    _require_admin_scope(x_admin_token, _SCOPE_OPERATIONS)

    openai_client = _get_openai_client()
    if openai_client is None:
        raise HTTPException(status_code=503, detail="OpenAI API key not configured.")

    new_embeddings = build_product_embeddings(openai_client, products)
    save_embeddings(new_embeddings, os.getenv("PRODUCT_EMBEDDINGS_PATH"))
    clear_embeddings_cache()

    return {"products_embedded": len(new_embeddings)}


@app.post("/admin/feed/refresh")
def admin_refresh_feed(x_admin_token: str | None = Header(default=None)) -> dict:
    """Manual on-demand refresh_feed() trigger (V2.1) - the scheduled
    feed_refresh_loop() only runs every FEED_REFRESH_MINUTES and waits a
    full interval before its first run, so this exists to verify the
    feed/normalization/taxonomy pipeline against live data without
    waiting. Deliberately does NOT call rebuild_knowledge_from_feed() -
    that triggers OpenAI enrichment calls, out of scope for a pipeline
    smoke check."""
    _require_admin_scope(x_admin_token, _SCOPE_OPERATIONS)

    started_at = time.time()
    refresh_feed()
    duration = time.time() - started_at

    if last_feed_refresh_error:
        raise HTTPException(status_code=502, detail=last_feed_refresh_error)

    return {
        "products": len(products),
        "taxonomy": taxonomy_coverage(product_taxonomy_index),
        "duration_seconds": round(duration, 2),
        "last_feed_refresh_at": last_feed_refresh_at,
    }


@app.get("/admin/analytics/behavioral-rankings")
def admin_behavioral_rankings(
    limit: int = 20,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    rankings = get_behavioral_rankings()
    scores = rankings["scores"]
    safe_limit = max(1, min(int(limit or 20), 100))

    ranked = sorted(scores.items(), key=lambda item: item[1]["ctr"], reverse=True)
    top = [{"product_sku": sku, **entry} for sku, entry in ranked[:safe_limit]]
    bottom = [{"product_sku": sku, **entry} for sku, entry in ranked[-safe_limit:]] if len(ranked) > safe_limit else []

    return {
        "baseline_ctr": rankings["baseline_ctr"],
        "products_with_scores": len(scores),
        "top_products": top,
        "bottom_products": bottom,
    }


@app.get("/admin/analytics/fbt-pairs")
def admin_fbt_pairs(
    sku: str = "",
    limit: int = 20,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    fbt_data = get_fbt_data()
    safe_limit = max(1, min(int(limit or 20), 100))

    if sku:
        pairs = fbt_recommendations(sku, fbt_data, safe_limit)
        return {
            "active": fbt_data["active"],
            "total_add_to_cart_events": fbt_data["total_add_to_cart_events"],
            "sku": sku,
            "co_purchased_skus": pairs,
        }

    skus_with_pairs = len(fbt_data["pairs"])
    sample = [
        {"sku": product_sku, "co_purchased": entries[:safe_limit]}
        for product_sku, entries in list(fbt_data["pairs"].items())[:safe_limit]
    ]
    return {
        "active": fbt_data["active"],
        "total_add_to_cart_events": fbt_data["total_add_to_cart_events"],
        "skus_with_pairs": skus_with_pairs,
        "sample": sample,
    }


@app.get("/admin/learning/status")
def admin_learning_status(x_admin_token: str | None = Header(default=None)) -> dict:
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    return {
        "learning_engine_enabled": _LEARNING_ENGINE_ENABLED,
        "auto_promotion_enabled": _LEARNING_AUTO_PROMOTION_ENABLED,
        "learning_cycle_minutes": _LEARNING_CYCLE_MINUTES,
        "active_ranking_config": get_active_ranking_profile_version(),
        "last_known_good": _learning_last_known_good(),
        **_learning_health_summary(),
    }


@app.get("/admin/learning/candidates")
def admin_learning_candidates(x_admin_token: str | None = Header(default=None)) -> dict:
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    try:
        report = json.loads((_LEARNING_REPORTS_DIR / "latest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"learning_cycle_id": None, "candidates": [], "note": "no learning cycle report available yet"}
    return {
        "learning_cycle_id": report.get("learning_cycle_id"),
        "status": report.get("status"),
        "candidate_summary": report.get("candidate_summary"),
        "candidates": report.get("candidates", []),
    }


@app.get("/admin/learning/history")
def admin_learning_history(
    candidate_id: str = "",
    limit: int = 100,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    safe_limit = max(1, min(int(limit or 100), 500))
    return {"entries": _learning_history(candidate_id or None, safe_limit)}


@app.post("/admin/learning/run-cycle")
def admin_learning_run_cycle(
    days: int = 0,
    full: bool = False,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """Section 70/97 - manual on-demand trigger, same pairing pattern as
    POST /admin/feed/refresh next to the periodic asyncio loop below."""
    _require_admin_scope(x_admin_token, _SCOPE_OPERATIONS)
    known_product_ids = frozenset(p.id for p in products)
    return _run_learning_cycle(known_product_ids=known_product_ids, days=days or None, fast_evaluation=not full)


@app.post("/admin/learning/candidates/{candidate_id}/approve")
def admin_approve_candidate(
    candidate_id: str,
    body: ApproveCandidateRequest,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """Section [Part C] - the only HTTP-reachable path that can move
    config/ranking_profiles/active.json. Requires PROMOTION scope (a
    READ or OPERATIONS token, including both legacy tokens, is refused -
    see app.admin_auth) and a real approved_by identity (enforced again,
    unconditionally, inside approve_and_activate() itself)."""
    _require_admin_scope(x_admin_token, _SCOPE_PROMOTION)
    try:
        return _approve_candidate_by_id(
            candidate_id,
            approved_by=body.approved_by,
            expected_current_config_version=body.expected_current_config_version,
        )
    except _LifecycleError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/admin/learning/rollback")
def admin_rollback_learning(
    body: RollbackRequest,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """Section [Part C] - manual, human-triggered rollback to
    last_known_good. Requires PROMOTION scope, same as approval - rolling
    back what is live for real customers is exactly as sensitive as
    promoting something new."""
    _require_admin_scope(x_admin_token, _SCOPE_PROMOTION)
    try:
        version = _rollback_to_last_known_good(
            reason=body.reason,
            learning_cycle_id="manual-rollback",
            triggered_by=body.triggered_by,
            expected_current_config_version=body.expected_current_config_version,
        )
    except _LifecycleError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if version is None:
        return {"status": "no_op", "reason": "no last_known_good recorded"}
    return {"status": "rolled_back", "profile_version": version}


_SEARCH_QUALITY_CANARY_PATH = str(Path(__file__).resolve().parents[1] / "eval" / "search_quality_canaries.json")


def _search_quality_chat_fn(query: str) -> dict:
    # V2.13a: goes through AdvisorEngine instead of a locally-defined
    # duck-typed request shim - AdvisorEngine owns that internally now.
    request = _AdvisorRequest(message=query, session_id="search-quality-admin-canary", client_key="search-quality-admin-canary")
    return _advisor_engine.run(request, _admin_test_context())


def _search_quality_classify_product_family(product_id: str) -> str | None:
    tax = product_taxonomy_index.get(product_id)
    return tax.canonical_family if tax else None


@app.get("/admin/search-quality/status")
def admin_search_quality_status(x_admin_token: str | None = Header(default=None)) -> dict:
    """Section 62 - READ scope, aggregate/safe status only (mirrors the
    public /health subset but with a bit more admin-facing detail)."""
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    baseline = _load_search_quality_baseline()
    canary = _load_last_search_quality_canary()
    return {
        "search_quality_monitor_enabled": True,
        "auto_promotion_enabled": _LEARNING_AUTO_PROMOTION_ENABLED,
        "production_quality_baseline_present": baseline is not None,
        "baseline_deployment_version": baseline.get("deployment_version") if baseline else None,
        "last_canary_ran_at": canary.get("ran_at") if canary else None,
        "last_canary_all_passed": canary.get("all_passed") if canary else None,
        "active_ranking_config": get_active_ranking_profile_version(),
    }


@app.get("/admin/search-quality/report")
def admin_search_quality_report(days: int = 1, x_admin_token: str | None = Header(default=None)) -> dict:
    """Section 62/128 - reads already-logged customer traces and
    aggregates on the fly (cheap, no retrieval calls) - READ scope.
    Honestly reports INSUFFICIENT_DATA rather than a fabricated verdict
    when volume is too low (Section 34/73)."""
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    safe_days = max(1, min(int(days or 1), 30))
    return _generate_search_quality_report(days=safe_days, ranking_config_version=get_active_ranking_profile_version())


@app.get("/admin/search-quality/anomalies")
def admin_search_quality_anomalies(days: int = 1, x_admin_token: str | None = Header(default=None)) -> dict:
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    safe_days = max(1, min(int(days or 1), 30))
    report = _generate_search_quality_report(days=safe_days, ranking_config_version=get_active_ranking_profile_version())
    return {"generated_at": report["generated_at"], "deployment_version": report["deployment_version"], "anomalies": report["anomalies"]}


@app.get("/admin/search-quality/canary")
def admin_search_quality_canary_status(x_admin_token: str | None = Header(default=None)) -> dict:
    """Section 62 - READ scope, returns the LAST STORED canary result.
    Does not execute a fresh run (see POST .../run for that, Section 63 -
    expensive/state-changing operations require OPERATIONS)."""
    _require_admin_scope(x_admin_token, _SCOPE_READ)
    result = _load_last_search_quality_canary()
    if result is None:
        return {"status": "never_run"}
    return result


@app.post("/admin/search-quality/run")
def admin_search_quality_run(x_admin_token: str | None = Header(default=None)) -> dict:
    """Section 63/106 - manual/post-deploy execution: runs the hard
    canary set through the real retrieval path in ADMIN_TEST execution
    mode (never CUSTOMER, Section 39/103) and persists the result.
    OPERATIONS scope - this is a state-changing, non-trivial-cost call,
    not a plain read."""
    _require_admin_scope(x_admin_token, _SCOPE_OPERATIONS)
    cases = _load_search_quality_canary_cases(_SEARCH_QUALITY_CANARY_PATH)
    deployment_version = _search_quality_deployment_version()
    if not cases:
        return {"status": "no_canary_cases_defined", "path": _SEARCH_QUALITY_CANARY_PATH}
    results = _run_search_quality_canaries(
        cases,
        chat_fn=_search_quality_chat_fn,
        classify_product_family=_search_quality_classify_product_family,
    )
    anomalies = _search_quality_canary_anomalies(results, deployment_version)
    _save_last_search_quality_canary(results, anomalies, deployment_version)
    report = _generate_search_quality_report(days=1, ranking_config_version=get_active_ranking_profile_version())
    return {
        "canary_pass_count": sum(1 for r in results if r.passed),
        "canary_total_count": len(results),
        "canary_all_passed": all(r.passed for r in results),
        "canary_anomalies": [a.__dict__ for a in anomalies],
        "report": report,
    }


def session_memory_key(session_id: str, client_key: str) -> str:
    raw_session = re.sub(r"[^a-zA-Z0-9_-]", "", str(session_id or ""))[:64]
    if raw_session:
        return raw_session
    digest = hashlib.sha256(str(client_key or "unknown").encode("utf-8")).hexdigest()[:24]
    return f"anon-{digest}"


def user_memory_key(client_id: str, client_key: str) -> str:
    raw_client = re.sub(r"[^a-zA-Z0-9_-]", "", str(client_id or ""))[:96]
    if raw_client:
        return raw_client
    digest = hashlib.sha256(str(client_key or "unknown").encode("utf-8")).hexdigest()[:24]
    return f"anon-{digest}"


def user_memory_path() -> Path:
    return Path(os.getenv("USER_MEMORY_PATH", str(DEFAULT_RUNTIME_LOG_DIR / "user_memory.json")))


def load_user_memories() -> dict[str, dict]:
    global user_memories
    if user_memories is not None:
        return user_memories
    user_memories = {}
    if not USER_MEMORY_ENABLED:
        return user_memories

    path = user_memory_path()
    if not path.exists():
        return user_memories
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            user_memories = {
                str(key): value
                for key, value in data.items()
                if isinstance(value, dict)
            }
    except Exception as exc:
        logger.error("Failed to read user memory %s: %s", path, exc, exc_info=True)
        user_memories = {}
    return user_memories


def save_user_memories() -> None:
    if not USER_MEMORY_ENABLED or user_memories is None:
        return
    path = user_memory_path()
    try:
        _atomic_write_json(path, pruned_user_memories(user_memories))
    except Exception as exc:
        logger.error("Failed to write user memory %s: %s", path, exc, exc_info=True)


def pruned_user_memories(memories: dict[str, dict]) -> dict[str, dict]:
    if len(memories) <= USER_MEMORY_MAX_PROFILES:
        return memories
    sorted_items = sorted(memories.items(), key=lambda item: float(item[1].get("updated_at", 0)), reverse=True)
    return dict(sorted_items[:USER_MEMORY_MAX_PROFILES])


def get_user_memory(profile_key: str) -> dict:
    memories = load_user_memories()
    profile = memories.get(profile_key)
    if not profile:
        profile = {
            "subjects": {},
            "diet_terms": {},
            "cuisines": {},
            "product_titles": {},
            "product_brands": {},
            "recipe_titles": {},
            "intent_counts": {},
            "last_intent": "",
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        memories[profile_key] = profile
    return profile


def bump_profile_counter(profile: dict, key: str, value: str, weight: int = 1, limit: int = 40) -> None:
    normalized_value = redact_memory_text(str(value or "")).strip()
    if not normalized_value:
        return
    bucket = profile.setdefault(key, {})
    bucket[normalized_value] = int(bucket.get(normalized_value, 0)) + weight
    if len(bucket) > limit:
        keep = sorted(bucket.items(), key=lambda item: item[1], reverse=True)[:limit]
        profile[key] = dict(keep)


def update_user_memory(
    profile_key: str,
    message: str,
    intent: str,
    matches: list[dict] | None = None,
    recipes: list[dict] | None = None,
) -> dict:
    if not USER_MEMORY_ENABLED:
        return {}
    profile = get_user_memory(profile_key)
    profile["last_intent"] = intent
    profile["updated_at"] = time.time()
    bump_profile_counter(profile, "intent_counts", memory_intent_bucket(intent), limit=12)

    for subject in detect_memory_subjects(message):
        bump_profile_counter(profile, "subjects", subject)
    for term in detect_diet_terms(message):
        bump_profile_counter(profile, "diet_terms", term)
    for cuisine in detect_cuisines_from_text(message):
        bump_profile_counter(profile, "cuisines", cuisine)

    for product in (matches or [])[:6]:
        if not should_remember_product_match(message, product):
            continue
        title = str(product.get("title") or "").strip()
        brand = str(product.get("brand") or "").strip()
        if title:
            bump_profile_counter(profile, "product_titles", title)
            for subject in detect_memory_subjects(title):
                bump_profile_counter(profile, "subjects", subject)
            for cuisine in detect_cuisines_from_text(title):
                bump_profile_counter(profile, "cuisines", cuisine)
        if brand:
            bump_profile_counter(profile, "product_brands", brand)

    for recipe in (recipes or [])[:4]:
        title = str(recipe.get("title") or "").strip()
        cuisine = str(recipe.get("cuisine") or "").strip()
        if title:
            bump_profile_counter(profile, "recipe_titles", title)
            for subject in detect_memory_subjects(title):
                bump_profile_counter(profile, "subjects", subject)
            for detected_cuisine in detect_cuisines_from_text(title):
                bump_profile_counter(profile, "cuisines", detected_cuisine)
        for detected_cuisine in detect_cuisines_from_text(cuisine):
            bump_profile_counter(profile, "cuisines", detected_cuisine)

    save_user_memories()
    return profile


def memory_intent_bucket(intent: str) -> str:
    if intent in {"product_search", "related_products", "replacement_products", "article_products", "product_advice", "allergen_safety"}:
        return "buy"
    if intent in {"recipe", "recipe_to_products"}:
        return "cook"
    if intent in {"faq", "unknown"}:
        return "explain"
    return normalize(intent or "unknown")


def should_remember_product_match(message: str, product: dict) -> bool:
    message_tokens = {token for token in tokenize(message) if len(token) > 3}
    if not message_tokens:
        return False
    product_tokens = set(tokenize(str(product.get("title", ""))))
    direct_hits = message_tokens & product_tokens
    if direct_hits:
        return True
    product_text = product_profile_text(product)
    detected_subjects = set(detect_memory_subjects(message))
    return any(
        subject in detected_subjects and any(alias in product_text for alias in aliases)
        for subject, aliases in RELATED_SUBJECT_ALIASES.items()
    )


def public_user_memory_summary(profile: dict | None) -> dict:
    profile = profile or {}
    return {
        "top_subjects": top_profile_values(profile, "subjects", 5),
        "top_cuisines": top_profile_values(profile, "cuisines", 5),
        "diet_terms": top_profile_values(profile, "diet_terms", 5),
        "favorite_brands": top_profile_values(profile, "product_brands", 5),
    }


def top_profile_values(profile: dict, key: str, limit: int = 5) -> list[str]:
    bucket = profile.get(key, {})
    if not isinstance(bucket, dict):
        return []
    return [
        str(value)
        for value, _ in sorted(bucket.items(), key=lambda item: int(item[1]), reverse=True)[:limit]
    ]


def get_session_memory(memory_key: str) -> dict:
    now = time.time()
    prune_session_memories(now)
    memory = session_memories.get(memory_key)
    if not memory:
        memory = {
            "queries": deque(maxlen=6),
            "subjects": deque(maxlen=5),
            "diet_terms": deque(maxlen=4),
            "product_titles": deque(maxlen=8),
            "recipe_titles": deque(maxlen=5),
            "last_top_product_title": "",
            "last_intent": "",
            "active_result_set_id": "",
            "active_use_case": "",
            "active_recipe_id": "",
            "recipe_servings": None,
            "last_recipe_ingredient_concept": "",
            "selected_ingredient_products": {},
            "recent_presentation_ids": [],
            "updated_at": now,
        }
        session_memories[memory_key] = memory
    memory["updated_at"] = now
    return memory


def prune_session_memories(now: float | None = None) -> None:
    now = now or time.time()
    if len(session_memories) <= SESSION_MEMORY_MAX_SESSIONS:
        expired = [
            key
            for key, memory in session_memories.items()
            if now - float(memory.get("updated_at", 0)) > SESSION_MEMORY_TTL_SECONDS
        ]
    else:
        sorted_items = sorted(session_memories.items(), key=lambda item: float(item[1].get("updated_at", 0)))
        expired = [key for key, _ in sorted_items[: max(1, len(session_memories) - SESSION_MEMORY_MAX_SESSIONS)]]

    for key in expired:
        session_memories.pop(key, None)


def contextualize_message(message: str, memory: dict | None) -> str:
    if not memory:
        return message

    parts = [message]
    if is_context_followup(message):
        # Prefer the most recently shown product over the coarser dish
        # subject: subjects can get tagged by an incidental/unrelated
        # co-result (e.g. a jujube search pulling in an unrelated Japanese
        # noodle product tags the whole session "japonska_kuchyna"), while
        # the last product title is what the customer is actually looking
        # at - and it still resolves via the normal subject-alias matching
        # once appended, since product titles contain the dish/ingredient
        # keyword too.
        if memory.get("last_top_product_title"):
            parts.append(memory["last_top_product_title"])
        else:
            subject = best_memory_subject(memory)
            if subject:
                parts.append(subject.replace("_", " "))
    for term in list(memory.get("diet_terms", []))[-2:]:
        if term and term not in normalize(" ".join(parts)):
            parts.append(term)
    return " ".join(parts).strip()


def _routing_message(message: str, memory: dict | None) -> str:
    # V2.13b.1 (docs/contextualization-risk-v2.13b.1.md, regbug_rt0011):
    # text for WORKFLOW-ROUTING-CRITICAL detection (special_subject/
    # related_subject/already_have_subject/replacement_subject/
    # article_product_subject and the guards that refine them below).
    # Reuses contextualize_message()'s legitimate is_context_followup()-
    # gated subject/product-title carry-over unchanged (same Show More/
    # ordinal/companion-follow-up behavior, e.g. "a co k tomu" ->
    # resolves the prior dish) but NEVER appends diet_terms. Diet
    # preference is retrieval/answer-quality signal, not workflow-
    # routing evidence - unconditionally folding it into the same text
    # used for special_subject/related_subject detection let a stale,
    # unrelated diet term manufacture a false routing conflict on a
    # later, unrelated turn (regbug_rt0011: "jemne"/"pikantne" left over
    # from an earlier message coincidentally matched special_subject=
    # "mild"/related_subject="medium_spicy", hijacking dispatch into
    # RELATED_PRODUCTS for a plain "co odporucas?" follow-up). This is a
    # separate, narrower value than contextualize_message()'s output -
    # retrieval, knowledge search, recipe-subject detection and answer
    # composition keep using the full contextualized message unchanged
    # (Invariant: this sprint hardens workflow-routing input, it does
    # not redesign retrieval/ranking/taxonomy).
    if not memory:
        return message
    parts = [message]
    if is_context_followup(message):
        if memory.get("last_top_product_title"):
            parts.append(memory["last_top_product_title"])
        else:
            subject = best_memory_subject(memory)
            if subject:
                parts.append(subject.replace("_", " "))
    return " ".join(parts).strip()


def is_context_followup(message: str) -> bool:
    normalized_message = normalize(message).strip()
    if len(tokenize(normalized_message)) <= 3 and any(
        marker in normalized_message
        for marker in ("k tomu", "co este", "este nieco", "dopln", "hodia", "odporuc", "kostk", "a co", "a este")
    ):
        return True
    return normalized_message in {
        "co k tomu",
        "a co k tomu",
        "co este",
        "a este nieco",
        "co odporucas",
        "doplnky",
        "ake doplnky",
        "co chyba",
        "co mi chyba",
    }


# V2.5 Show More / Show All (Section 14) - exact-phrase detection so a
# customer follow-up like "zobraz vsetky" acts on the ACTIVE ResultSet
# instead of triggering a brand-new broad search from that short text.
SHOW_MORE_PHRASES = ("zobraz viac", "zobrazit viac", "ukaz viac", "ukaz este", "dalsie produkty", "show more")
SHOW_ALL_PHRASES = ("zobraz vsetky", "zobrazit vsetky", "ukaz vsetky", "vsetky produkty", "show all", "zobraz vsetkych", "ukaz vsetkych", "zobrazit vsetkych")


def is_show_all_query(normalized_message: str) -> bool:
    return any(phrase in normalized_message for phrase in SHOW_ALL_PHRASES)


def is_show_more_query(normalized_message: str) -> bool:
    return any(phrase in normalized_message for phrase in SHOW_MORE_PHRASES)


def best_memory_subject(memory: dict | None) -> str | None:
    if not memory:
        return None
    subjects = list(memory.get("subjects", []))
    return subjects[-1] if subjects else None


def update_session_memory(
    memory_key: str,
    message: str,
    intent: str,
    matches: list[dict] | None = None,
    recipes: list[dict] | None = None,
    knowledge_matches: dict | None = None,
) -> dict:
    memory = get_session_memory(memory_key)
    memory["last_intent"] = intent
    memory["queries"].append(redact_memory_text(message))

    for subject in detect_memory_subjects(message):
        append_unique(memory["subjects"], subject)
    for term in detect_diet_terms(message):
        append_unique(memory["diet_terms"], term)

    if matches:
        top_title = matches[0].get("title")
        if top_title:
            memory["last_top_product_title"] = redact_memory_text(str(top_title))[:120]
    for product in (matches or [])[:4]:
        title = product.get("title")
        if title:
            append_unique(memory["product_titles"], redact_memory_text(str(title))[:120])
            for subject in detect_memory_subjects(str(title)):
                append_unique(memory["subjects"], subject)

    for recipe in (recipes or [])[:3]:
        title = recipe.get("title")
        if title:
            append_unique(memory["recipe_titles"], redact_memory_text(str(title))[:120])
            for subject in detect_memory_subjects(str(title)):
                append_unique(memory["subjects"], subject)

    for hit in (knowledge_matches or {}).get("Recipes", [])[:2]:
        record = hit.get("record", {})
        title = first_record_value(record, ("Recept", "recipe", "nazov", "názov"))
        if title:
            append_unique(memory["recipe_titles"], redact_memory_text(title)[:120])

    memory["updated_at"] = time.time()
    return memory


def detect_memory_subjects(text: str) -> list[str]:
    normalized_text = normalize(text)
    subjects: list[str] = []
    for subject, aliases in RELATED_SUBJECT_ALIASES.items():
        if any(alias in normalized_text for alias in aliases):
            subjects.append(subject)
    return subjects[:4]


def detect_cuisines_from_text(text: str) -> list[str]:
    normalized_text = normalize(text)
    cuisines: list[str] = []
    for cuisine, markers in RECIPE_CUISINE_MARKERS.items():
        if any(marker in normalized_text for marker in markers):
            cuisines.append(cuisine)
    return cuisines[:4]


# Real regression, second occurrence of the same root-cause class as
# the "pikantnejsie" comparative-form fix: detect_diet_terms() matched
# bare substrings with no negation awareness at all, so "nechcem nic
# pikantne" ("I don't want anything spicy") got recorded as a POSITIVE
# "pikantne" preference - the opposite of what the customer said. That
# silently-injected (via contextualize_message()) inverted preference
# then corrupted a later, unrelated question into a broken answer
# built from an unrelated product's knowledge text. A blanket guard is
# coarser than real negation-scoped parsing (a compound sentence like
# "nechcem sladke, chcem pikantne" would lose the genuine second half),
# but never recording an inverted preference is the safer failure mode
# for a signal that persists silently across an entire conversation.
DIET_TERM_NEGATION_MARKERS = ("nechcem", "nemam rad", "nemam rada", "neznasam", "nie som")


def detect_diet_terms(text: str) -> list[str]:
    normalized_text = normalize(text)
    if any(marker in normalized_text for marker in DIET_TERM_NEGATION_MARKERS):
        return []
    terms: list[str] = []
    if any(marker in normalized_text for marker in ("bezlepk", "celiak", "bez lepku")):
        terms.append("bezlepkove")
    if any(marker in normalized_text for marker in ("vegan", "vegans")):
        terms.append("veganske")
    if any(marker in normalized_text for marker in ("vegetarian", "vegetariansk")):
        terms.append("vegetarianske")
    if any(marker in normalized_text for marker in ("nepaliv", "jemne", "menej paliv", "nie paliv")):
        terms.append("jemne")
    # Real regression: "pikant" also matches inside the comparative
    # form "pikantnejsie/pikantnejsi/pikantnejsia" ("spicier"), which
    # shows up in comparison QUESTIONS ("gochujang vs sriracha, co je
    # pikantnejsie?") - not a stated preference. This wrongly-detected
    # diet term then got silently injected into every later message in
    # the session via contextualize_message(), corrupting completely
    # unrelated follow-up queries. Excluded via the shared "pikantnej"
    # comparative stem; genuine preference statements like "pikantne"
    # (positive form, e.g. "mam rad pikantne kimchi") are unaffected.
    if any(marker in normalized_text for marker in ("paliv", "pikant", "chilli", "chili")) and "pikantnej" not in normalized_text:
        terms.append("pikantne")
    return terms


def append_unique(values: deque, value: str) -> None:
    if value in values:
        try:
            values.remove(value)
        except ValueError:
            pass
    values.append(value)


def redact_pii(text: str) -> str:
    cleaned = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[email]", str(text))
    cleaned = re.sub(r"\+?\d[\d\s().-]{6,}\d", "[phone]", cleaned)
    return cleaned


def redact_memory_text(text: str) -> str:
    return redact_pii(text)[:200]


def session_memory_context(memory: dict | None) -> str:
    if not memory:
        return "bez ulozeneho kontextu"
    parts = []
    if memory.get("subjects"):
        parts.append("temy: " + ", ".join(list(memory["subjects"])[-3:]))
    if memory.get("diet_terms"):
        parts.append("preferencie: " + ", ".join(list(memory["diet_terms"])[-3:]))
    if memory.get("product_titles"):
        parts.append("posledne produkty: " + "; ".join(list(memory["product_titles"])[-3:]))
    if memory.get("recipe_titles"):
        parts.append("posledne recepty: " + "; ".join(list(memory["recipe_titles"])[-2:]))
    return " | ".join(parts) if parts else "bez ulozeneho kontextu"


def is_explicit_article_request(message: str) -> bool:
    normalized_message = normalize(message)
    return any(
        marker in normalized_message
        for marker in (
            "clanok",
            "clanky",
            "clanek",
            "blog",
            "magazin",
            "magazinovy",
            "mate clanok",
            "mas clanok",
            "ukaz clanok",
            "article",
        )
    )


def knowledge_sections_for_intent(
    *,
    is_faq_query: bool,
    is_random_recipe_query: bool,
    recipe_subject: str | None,
    needs_article_context: bool,
    explicit_article_request: bool,
) -> tuple[str, ...]:
    if is_faq_query:
        return ("FAQ",)
    if is_random_recipe_query or recipe_subject:
        return ("Recipes",)
    if needs_article_context:
        if explicit_article_request:
            return ("Magazine", "Products_AI")
        return ("Products_AI",)
    return ()


EN_LANGUAGE_MARKERS = frozenset({
    "what", "how", "why", "does", "do", "you", "your", "please",
    "the", "is", "are", "have", "has", "for", "with", "and", "this",
    "that", "can", "could", "would", "recommend", "delivery",
    "shipping", "allergy", "allergic", "recipe", "ingredients",
    "product", "products", "thanks", "thank",
})


def detect_query_language(message: str) -> str:
    """Lightweight heuristic, not a general language detector: only
    distinguishes English from everything else (Slovak/Czech share so
    much vocabulary that a reliable SK/CZ split isn't worth the extra
    complexity for template selection - Czech customers read Slovak
    text fine). Requires >=2 hits to avoid false positives on short
    queries that are just an English product name.
    """
    hits = raw_tokens(message) & EN_LANGUAGE_MARKERS
    return "en" if len(hits) >= 2 else "sk"


def _chat_impl(chat_request: ChatRequest, request: Request, execution_context: _ExecutionContext | None = None, interaction_id: str | None = None) -> dict:
    # V2.12.1 Part D: explicit execution context replaces the old
    # isinstance(request, Request) hotfix (commit 8936188) as the
    # PREFERRED signal for "is this real customer traffic" - see
    # app/execution_context.py's module docstring. The isinstance check
    # is preserved as a fallback for any caller that has not been
    # migrated to pass an explicit context (Section 59 - not removed
    # until every internal caller passes one explicitly).
    if execution_context is None:
        execution_context = _customer_context() if isinstance(request, Request) else _evaluation_context()
    _reset_search_quality_decision()
    _reset_workflow_resolution()

    client_key = get_client_key(request)
    # V2.12 fix, now generalized by execution_context.apply_rate_limit
    # (Section 48/59): app.evaluation.adapter.make_chat_fn() calls chat()
    # directly in-process with a plain duck-typed _FakeRequest stub
    # (never reachable via real HTTP dispatch - FastAPI itself always
    # constructs a genuine Request from the ASGI scope for actual
    # customer calls, so this cannot be spoofed by an external client).
    # Without this, every evaluate_profile() call inside a learning
    # cycle shares ONE client_key ("127.0.0.1") and trips the real
    # customer-facing RATE_LIMIT_PER_MINUTE within seconds in production,
    # where (unlike CI/tests) that env var is already explicitly set so
    # the harness's own setdefault() override never takes effect - found
    # via a real failed POST /admin/learning/run-cycle against
    # production (429 after ~12 calls).
    if execution_context.apply_rate_limit:
        enforce_rate_limit(client_key)
    # Section 59 - only CUSTOMER traffic is counted in customer-facing
    # analytics. Rebinding the name locally (rather than touching each
    # of the ~13 log_question(...) call sites below) works because a
    # local assignment makes `log_question` local for this ENTIRE
    # function body in Python - the real function is fetched via
    # globals() rather than a bare `log_question` reference, since a
    # bare reference on the right-hand side would itself resolve to the
    # (not-yet-assigned) local and raise UnboundLocalError.
    _real_log_question = globals()["log_question"]
    log_question = _real_log_question if execution_context.emit_customer_analytics else (lambda *args, **kwargs: None)  # noqa: E731
    # V2.15a audit: log_taxonomy_shadow() was never wired to this gate at
    # all (predates app.execution_context - V2 catalog-first taxonomy is
    # an earlier sprint) - every EVALUATION/LEARNING/SHADOW/ADMIN_TEST
    # call was silently polluting taxonomy_shadow.jsonl exactly like a
    # real customer message. See tests/test_execution_context.py::
    # TestExecutionContextSuppressesTaxonomyShadow.
    if execution_context.emit_customer_analytics:
        log_taxonomy_shadow(chat_request.message, client_key, classify_rice_query(chat_request.message, normalize))
    # V2.15b: opaque per-request correlation id - generated once by
    # _chat_internal() and threaded down to every log_question() call
    # site below (and, separately, into the SearchQualityTrace and the
    # response dict by _chat_internal() itself). The fallback here only
    # matters for a caller that invokes _chat_impl() directly without
    # going through _chat_internal() - never leave it unset.
    interaction_id = interaction_id or secrets.token_hex(8)

    session_id = getattr(chat_request, "session_id", "") or ""
    memory_key = session_memory_key(session_id, client_key)
    memory = get_session_memory(memory_key)
    profile_key = user_memory_key(getattr(chat_request, "client_id", ""), client_key)
    user_profile = get_user_memory(profile_key) if USER_MEMORY_ENABLED else {}

    # V2.5 Show More / Show All (Section 9/14/46): a pure continuation of
    # the ACTIVE ResultSet, never a new search - product membership and
    # order come entirely from the stored ResultSet, never re-derived
    # from this short message.
    active_result_set_id = memory.get("active_result_set_id", "")
    if active_result_set_id:
        normalized_continuation_message = normalize(chat_request.message)
        wants_show_all = is_show_all_query(normalized_continuation_message)
        wants_show_more = not wants_show_all and is_show_more_query(normalized_continuation_message)
        if wants_show_all or wants_show_more:
            # V2.13c: RESULTSET_CONTINUATION executor handler
            # (app.workflow_executor) - unchanged logic, formalized as
            # the canonical execution boundary for the one workflow
            # that is both resolver-decided AND fully self-contained
            # (docs/workflow-inventory-v2.13c.md). Returns None (falls
            # through to the unchanged legacy cascade below) if the
            # ResultSet has expired/rotated - same fallback contract as
            # before, just made explicit.
            _rc_result = _execute_resultset_continuation(
                chat_request=chat_request,
                memory_key=memory_key,
                profile_key=profile_key,
                memory=memory,
                user_profile=user_profile,
                products=products,
                active_result_set_id=active_result_set_id,
                wants_show_all=wants_show_all,
            )
            if _rc_result is not None:
                return _rc_result
    contextual_message = contextualize_message(chat_request.message, memory)
    routing_message = _routing_message(chat_request.message, memory)
    memory_subject = best_memory_subject(memory)

    allergen_term = detect_allergen_intent(chat_request.message)
    is_faq_query = (
        is_faq_intent(chat_request.message)
        or _is_opening_hours_query(chat_request.message)
        or _is_contact_query(chat_request.message)
    )
    is_random_recipe_query = is_random_recipe_intent(chat_request.message)
    recipe_subject = detect_recipe_subject(contextual_message)
    if recipe_subject and _recipe_intent_is_bare_dish_marker_only(contextual_message):
        # V2.14d (Section 27-34) - a bare dish-name-only recipe trigger
        # (e.g. "tom kha" inside "ake kokosove mlieko na tom kha gai?")
        # must not outrank a specific, resolvable use-case/attribute
        # question naming that same dish - defer to use_case_advice
        # below instead of forcing recipe flow. Explicit recipe intent
        # ("recept na X") and shopping-list intent ("co potrebujem na X")
        # never reach this branch (excluded by the check above).
        if _use_case_advice_has_resolvable_role(contextual_message):
            recipe_subject = None
    needs_article_context = is_article_info_intent(chat_request.message)
    explicit_article_request = is_explicit_article_request(chat_request.message)
    query_language = detect_query_language(chat_request.message)
    knowledge_sections = knowledge_sections_for_intent(
        is_faq_query=is_faq_query,
        is_random_recipe_query=is_random_recipe_query,
        recipe_subject=recipe_subject,
        needs_article_context=needs_article_context,
        explicit_article_request=explicit_article_request,
    )
    needs_knowledge = bool(knowledge_sections)
    knowledge_matches = (
        search_knowledge(knowledge, contextual_message, allowed_sections=knowledge_sections)
        if needs_knowledge
        else {}
    )
    articles = article_results(knowledge_matches, chat_request.limit) if "Magazine" in knowledge_sections else []

    if is_missing_composition_complaint(chat_request.message):
        # V2.13d: verbatim code motion into app.workflow_executor.
        return _execute_missing_composition(
            chat_request=chat_request,
            memory_key=memory_key,
            profile_key=profile_key,
            articles=articles,
            knowledge_matches=knowledge_matches,
            client_key=client_key,
            session_id=session_id,
            query_language=query_language,
            emit_customer_analytics=execution_context.emit_customer_analytics,
        )

    # V2.13b (docs/workflow-precedence-before-v2.13b.md, rt0010): the
    # old inline condition treated allergen_product_query() returning ""
    # as "not applicable", when it is often a DELIBERATE zero-safe-
    # product signal (e.g. "bez soj"/"bez soja") - conflating the two
    # let a coincidental related_subject match suppress a genuine
    # safety answer. WorkflowResolver makes that distinction explicit
    # and generically (Invariant #11 - not hard-coded to this query);
    # the two detector calls below are the SAME ones the old condition
    # already made, just fed through the resolver instead of inlined.
    _safety_analysis = _resolve_safety_signal(
        chat_request.message,
        allergen_term=allergen_term,
        allergen_product_query_result=allergen_product_query(chat_request.message),
        related_subject=detect_related_subject(chat_request.message),
    )
    _safety_resolution = _resolve_workflow(_safety_analysis)
    _stash_workflow_resolution(_safety_resolution)
    if _safety_resolution.workflow_id == _WORKFLOW_ALLERGEN_SAFETY:
        # V2.13c: ALLERGEN_SAFETY executor handler (app.workflow_executor)
        # - unchanged logic, formalized as the canonical execution
        # boundary. The precedence decision above (frozen, V2.13b/
        # V2.13b.1) is unchanged - this only moves EXECUTION of that
        # already-made decision.
        return _execute_allergen_safety(
            chat_request=chat_request,
            memory_key=memory_key,
            profile_key=profile_key,
            user_profile=user_profile,
            knowledge_matches=knowledge_matches,
            articles=articles,
            allergen_term=allergen_term,
            client_key=client_key,
            session_id=session_id,
            query_language=query_language,
            emit_customer_analytics=execution_context.emit_customer_analytics,
        )

    faq_answer = None
    if is_faq_query:
        faq_answer = best_direct_faq_answer(chat_request.message, knowledge) or best_faq_answer(knowledge_matches)
    if faq_answer and is_faq_query:
        # V2.15c (rt0014): remember the raw question text so a later,
        # genuinely referential follow-up ("Prilož mi Google link na
        # adresu.") can re-derive this SAME grounded answer instead of
        # falling through to an unrelated product search - see
        # app.session_state.get_last_informational_question().
        _set_last_informational_question(memory, chat_request.message)
        # V2.15d.3 (STORE_LOCATION canonical data closure) - the
        # customer should not need a second turn just to receive the
        # Maps link, so the SAME function that builds it for the V2.15c
        # follow-up path also runs here, on the very first answer. No
        # link is baked into data/knowledge.json itself, so there is a
        # single place (_build_maps_link_from_faq_answer) deciding
        # whether/which link to attach - never duplicated between the
        # initial answer and a later follow-up recall of it.
        _initial_maps_link = _build_maps_link_from_faq_answer(faq_answer)
        if _initial_maps_link:
            faq_answer = f"{faq_answer}\n\n{_initial_maps_link}"
        # V2.13d: verbatim code motion into app.workflow_executor.
        return _execute_faq(
            chat_request=chat_request,
            memory_key=memory_key,
            profile_key=profile_key,
            articles=articles,
            knowledge_matches=knowledge_matches,
            client_key=client_key,
            session_id=session_id,
            query_language=query_language,
            faq_answer=faq_answer,
            emit_customer_analytics=execution_context.emit_customer_analytics,
        )

    if is_random_recipe_query:
        # V2.13d: verbatim code motion into app.workflow_executor.
        return _execute_random_recipe(
            chat_request=chat_request,
            memory_key=memory_key,
            profile_key=profile_key,
            user_profile=user_profile,
            knowledge=knowledge,
            articles=articles,
            knowledge_matches=knowledge_matches,
            client_key=client_key,
            session_id=session_id,
            query_language=query_language,
            emit_customer_analytics=execution_context.emit_customer_analytics,
        )

    # V2.9 (Section 30) - explicit reset clears shopping/task state and
    # answers immediately; never touches anything else (no account data
    # exists in this system to accidentally affect).
    if _detect_reset_request(chat_request.message):
        # V2.13d: verbatim code motion into app.workflow_executor.
        return _execute_reset(
            chat_request=chat_request,
            memory=memory,
            profile_key=profile_key,
            client_key=client_key,
            session_id=session_id,
            query_language=query_language,
            emit_customer_analytics=execution_context.emit_customer_analytics,
        )

    # V2.14b (docs/recommendation-comparison-v2.14b.md) - activates the
    # V2.7 COMPARISON workflow_id (previously SHADOW-only). Placed after
    # the allergen-safety/FAQ/random-recipe/reset early returns above (so
    # safety and those other self-contained workflows always take
    # precedence, Section 31 - allergen safety must never be bypassed by
    # comparison language) and before recipe detection below. Returns None
    # (not a dict) whenever the message does not look like a comparison
    # request at all, so every other branch below is completely unaffected
    # for any non-comparison turn - same fall-through contract as
    # execute_recipe().
    _comparison_result = _execute_comparison(
        chat_request=chat_request,
        memory=memory,
        memory_key=memory_key,
        profile_key=profile_key,
        products=products,
        product_taxonomy_index=product_taxonomy_index,
        client_key=client_key,
        session_id=session_id,
        query_language=query_language,
        emit_customer_analytics=execution_context.emit_customer_analytics,
        interaction_id=interaction_id or "",
        should_log_decision=execution_context.mode.value in ("CUSTOMER", "ADMIN_TEST"),
        learning_eligible=execution_context.is_customer_traffic,
    )
    if _comparison_result is not None:
        return _comparison_result

    # V2.14c (docs/use-case-intelligence-v2.14c.md) - activates the V2.7
    # USE_CASE_ADVICE workflow_id label for a narrow, audited-safe set of
    # culinary use cases (app.use_case_advice.LIVE_USE_CASES). Placed at the
    # same precedence tier as V2.14b comparison (after allergen-safety/FAQ/
    # random-recipe/reset, before recipe detection) - naturally disjoint from
    # comparison by construction (comparison requires 2 resolved targets,
    # this requires exactly 1 named use-case+role). Returns None whenever the
    # message does not name a LIVE use case at all, or explicitly excludes
    # the exact role this module would recommend - every other branch below
    # is completely unaffected for any other turn.
    _use_case_advice_result = _execute_use_case_advice(
        chat_request=chat_request,
        recipe_subject=recipe_subject,
        memory=memory,
        memory_key=memory_key,
        profile_key=profile_key,
        products=products,
        product_taxonomy_index=product_taxonomy_index,
        client_key=client_key,
        session_id=session_id,
        query_language=query_language,
        emit_customer_analytics=execution_context.emit_customer_analytics,
        interaction_id=interaction_id or "",
        should_log_decision=execution_context.mode.value in ("CUSTOMER", "ADMIN_TEST"),
        learning_eligible=execution_context.is_customer_traffic,
    )
    if _use_case_advice_result is not None:
        return _use_case_advice_result

    # V2.14e (docs/basket-completion-v2.14e.md) - goal-oriented
    # shopping/basket completion for app.basket_completion.BASKET_V1_ELIGIBLE_USE_CASES
    # (sushi/pho/kari - pad_thai/tom_kha already reach the existing,
    # live app.recipe_shopping path via their bare RECIPE_INTENT_MARKERS
    # entry, so decide_basket_completion() defers to it via the
    # recipe_subject guard below and never double-handles them).
    # Placed after use_case_advice (single-role Q&A stays distinct from
    # a multi-role basket request) and before recipe detection, same
    # precedence tier as V2.14b/c. Returns None whenever the message is
    # not a basket request for an eligible use case at all - every
    # other branch below is completely unaffected for any other turn.
    _basket_completion_result = _execute_basket_completion(
        chat_request=chat_request,
        recipe_subject=recipe_subject,
        memory=memory,
        memory_key=memory_key,
        profile_key=profile_key,
        products=products,
        product_taxonomy_index=product_taxonomy_index,
        client_key=client_key,
        session_id=session_id,
        query_language=query_language,
        emit_customer_analytics=execution_context.emit_customer_analytics,
        interaction_id=interaction_id or "",
        should_log_decision=execution_context.mode.value in ("CUSTOMER", "ADMIN_TEST"),
        learning_eligible=execution_context.is_customer_traffic,
    )
    if _basket_completion_result is not None:
        return _basket_completion_result

    # V2.16e (Section 17/45 - "why this?" core capability) - checked
    # after comparison/use_case_advice/basket_completion have all had
    # their chance to fire FRESH for this turn (a why-followup has no
    # demonstrative-free overlap with those - see app.explanation.
    # looks_like_why_followup()'s narrow marker set), and before the
    # recipe-followup/article-info cascade below, which is exactly
    # where a bare "preco"/"why" was previously silently absorbed
    # (is_article_info_intent()'s own broad marker) instead of
    # re-explaining the customer's actual last recommendation -
    # reproduced live during V2.16e characterization, not hypothetical.
    _why_followup_result = _execute_why_followup(
        chat_request=chat_request,
        memory=memory,
        memory_key=memory_key,
        profile_key=profile_key,
        products=products,
        query_language=query_language,
    )
    if _why_followup_result is not None:
        return _why_followup_result

    # V2.9 (Section 16/17/18/53) - a follow-up about an already-active
    # recipe ("aké rezance?", "tie druhé", "čo ešte potrebujem?") is
    # resolved BEFORE recipe_subject re-detection, since these messages
    # rarely name the dish again. When the active recipe does NOT explain
    # this turn, that is a hard switch (Section 27/84) - drop the stale
    # recipe state immediately so it cannot leak into whatever this turn
    # actually is.
    _active_recipe_id_before, _ = _get_active_recipe(memory)
    _recipe_followup_result = None
    if _active_recipe_id_before and not recipe_subject:
        try:
            _recipe_followup_result = _resolve_recipe_followup(
                chat_request.message, memory, recipe_graph_index, products, product_taxonomy_index, normalized_product_index,
            )
        except Exception:
            logger.warning("V2.9 recipe followup resolution failed", exc_info=True)
            _recipe_followup_result = None
        if _recipe_followup_result is None:
            _clear_recipe_state(memory)

    # V2.13e: recipe execution boundary (app.workflow_executor.execute_recipe)
    # - Block D (main recipe_subject handler) and Block E (recipe_followup_result
    # handler) moved verbatim, docs/recipe-state-machine-v2.13e.md. Called
    # HERE, ahead of the ordinal-reference/orphaned-followup blocks below,
    # instead of interleaved between them as in the original source order -
    # proven behaviorally identical because recipe_subject/_recipe_followup_result
    # are pairwise disjoint with those two blocks' own gating conditions
    # (mutual-exclusivity proof in the state-machine doc), so no turn can
    # ever reach both.
    _recipe_result = _execute_recipe(
        chat_request=chat_request,
        recipe_subject=recipe_subject,
        recipe_followup_result=_recipe_followup_result,
        contextual_message=contextual_message,
        knowledge=knowledge,
        knowledge_matches=knowledge_matches,
        knowledge_sections=knowledge_sections,
        articles=articles,
        user_profile=user_profile,
        products=products,
        recipe_graph_index=recipe_graph_index,
        product_taxonomy_index=product_taxonomy_index,
        normalized_product_index=normalized_product_index,
        memory=memory,
        memory_key=memory_key,
        profile_key=profile_key,
        client_key=client_key,
        session_id=session_id,
        query_language=query_language,
        emit_customer_analytics=execution_context.emit_customer_analytics,
        interaction_id=interaction_id or "",
        should_log_decision=execution_context.mode.value in ("CUSTOMER", "ADMIN_TEST"),
        learning_eligible=execution_context.is_customer_traffic,
    )
    if _recipe_result is not None:
        return _recipe_result

    # V2.9 (Section 11/13/60/61) - a short, bare ordinal reference ("ten
    # druhý") with no recipe follow-up match is resolved against
    # whatever was most recently shown to THIS session, or answered with
    # a clarification when nothing was - never an arbitrary/random SKU
    # (Section 141). Tightly scoped to short messages so a longer
    # sentence that merely CONTAINS an ordinal word is not misfired on.
    if (
        _recipe_followup_result is None
        and not recipe_subject
        and len(tokenize(chat_request.message)) <= 4
        and _mentions_ordinal_reference(chat_request.message)
    ):
        _ordinal_product_id, _ordinal_needs_clarification = _resolve_ordinal_reference(chat_request.message, memory)
        if _ordinal_product_id or _ordinal_needs_clarification:
            _products_by_id = {product.id: product for product in products}
            _ordinal_products = [format_product(_products_by_id[_ordinal_product_id])] if _ordinal_product_id in _products_by_id else []
            _ordinal_answer = (
                (
                    "Sorry, which one do you mean? I don't have a recent list to refer to."
                    if query_language == "en"
                    else "Prepáčte, ktorý presne máte na mysli? Naposledy som Vám nič nezobrazila, na čo by som mohla odkázať."
                )
                if not _ordinal_products
                else (
                    f"Here it is: {_ordinal_products[0].get('title', '')}"
                    if query_language == "en"
                    else f"Tu je: {_ordinal_products[0].get('title', '')}"
                )
            )
            updated_profile = update_user_memory(profile_key, chat_request.message, "product_search", _ordinal_products, [])
            log_question(chat_request.message, client_key, 0, intent="product_search", session_id=session_id, primary_intent="product_search", subject="", interaction_id=interaction_id)
            return {
                "answer": _ordinal_answer,
                "products": _ordinal_products,
                "knowledge": knowledge_summary({}),
                "memory": public_user_memory_summary(updated_profile),
                "intent": "product_search",
            }

    # Real gap found via a production no-result/analytics audit: "co este
    # potrebujem?" / "niečo lacnejšie" are ONLY meaningful as a follow-up
    # to an active recipe or an active result set (Section 16/20). Without
    # that context they previously fell all the way through to raw
    # lexical search, which confidently matched unrelated tokens and
    # returned WRONG products - worse than no result at all ("co este
    # potrebujem?" returned bamboo steamers, "nieco lacnejsie" returned
    # candy and ice cream, live-verified against production data). Mirrors
    # the ordinal-reference clarification above, not a new pattern.
    _orphaned_followup = _recipe_followup_result is None and not recipe_subject and (
        _looks_like_recipe_followup(chat_request.message)
        or (_detect_price_direction(chat_request.message) is not None and not memory.get("active_result_set_id"))
    )
    if _orphaned_followup:
        updated_profile = update_user_memory(profile_key, chat_request.message, "product_search", [], [])
        log_question(chat_request.message, client_key, 0, intent="product_search", session_id=session_id, primary_intent="product_search", subject="", interaction_id=interaction_id)
        return {
            "answer": (
                "I don't have an active shopping list or search to refer that to - what are you looking for?"
                if query_language == "en"
                else "Nemám aktívny nákupný zoznam ani vyhľadávanie, na ktoré by som to mohla naviazať - čo hľadáte?"
            ),
            "products": [],
            "knowledge": knowledge_summary({}),
            "memory": public_user_memory_summary(updated_profile),
            "intent": "product_search",
        }


    # V2.15c (rt0014 closure) - NON_COMMERCE_CONTEXTUAL_FOLLOWUP_TARGET_LOSS.
    # Positioned as a last resort: reached only when safety, comparison,
    # use_case_advice, basket_completion, recipe, the ordinal-reference
    # clarification, and the recipe/result-set orphaned-followup check
    # above have ALL already declined this turn, and BEFORE the generic
    # special_subject/related_subject commerce cascade starts - so an
    # explicit hard topic switch (a real product/brand/replacement/
    # recipe/allergen mention) is resolved by its own, earlier, higher-
    # precedence branch and never reaches here (Section 12 of the
    # closure spec - explicit current-turn target always wins). Narrow
    # by construction: _looks_like_location_reference_followup()'s
    # vocabulary is location/navigation-specific (mapa/adresa/tam/
    # dostanem), not a generic "any short follow-up inherits context"
    # catch-all, so "Pošli mi link na Kikkoman" (an explicit product
    # target) never matches it and is handled normally below.
    # V2.16a - generalizes the same last-resort pattern to the
    # payment-methods topic (Case I: "Ako môžem zaplatiť?" -> "A Apple
    # Pay?" previously fell through into commerce product search). Same
    # position, same hard-switch guarantees, same re-derivation via the
    # unmodified FAQ cascade - see
    # app.session_state.looks_like_payment_method_followup().
    # V2.16a.1 - generalizes the same last-resort pattern to opening_hours
    # and contact (opening-hours-and-contact-grounding closure). Same
    # position, same hard-switch guarantees, same re-derivation via the
    # unmodified FAQ cascade - see
    # app.session_state.looks_like_opening_hours_followup() and
    # app.session_state.looks_like_contact_followup(). Address/Maps
    # follow-ups after a contact topic are already covered by the
    # existing location-followup branch below (it is not topic-gated),
    # so no separate handling is needed for those.
    _last_informational_question = _get_last_informational_question(memory)
    _is_location_followup = _last_informational_question and _looks_like_location_reference_followup(chat_request.message)
    _is_payment_followup = _last_informational_question and not _is_location_followup and _looks_like_payment_method_followup(
        _last_informational_question, chat_request.message
    )
    _is_opening_hours_followup = (
        _last_informational_question and not _is_location_followup and not _is_payment_followup
        and _looks_like_opening_hours_followup(_last_informational_question, chat_request.message)
    )
    _is_contact_followup = (
        _last_informational_question and not _is_location_followup and not _is_payment_followup and not _is_opening_hours_followup
        and _looks_like_contact_followup(_last_informational_question, chat_request.message)
    )
    if _is_location_followup or _is_payment_followup or _is_opening_hours_followup or _is_contact_followup:
        _followup_faq_answer = best_direct_faq_answer(_last_informational_question, knowledge) or best_faq_answer(
            search_knowledge(knowledge, _last_informational_question, allowed_sections=("FAQ",))
        )
        if _followup_faq_answer:
            _maps_link = (
                _build_maps_link_from_faq_answer(_followup_faq_answer)
                if (_is_location_followup or _is_opening_hours_followup or _is_contact_followup)
                else None
            )
            _followup_answer_text = f"{_followup_faq_answer}\n\n{_maps_link}" if _maps_link else _followup_faq_answer
            updated_profile = update_user_memory(profile_key, chat_request.message, "faq", [], [])
            if _is_location_followup:
                _followup_subject = "location_reference_followup"
            elif _is_payment_followup:
                _followup_subject = "payment_method_followup"
            elif _is_opening_hours_followup:
                _followup_subject = "opening_hours_followup"
            else:
                _followup_subject = "contact_followup"
            log_question(
                chat_request.message, client_key, 0, intent="faq", session_id=session_id,
                primary_intent="faq",
                subject=_followup_subject,
                interaction_id=interaction_id,
            )
            return {
                "answer": _followup_answer_text,
                "products": [],
                "articles": [],
                "knowledge": knowledge_summary({}),
                "memory": public_user_memory_summary(updated_profile),
                "intent": "faq",
            }

    if detect_out_of_domain(chat_request.message):
        # V2.13d: verbatim code motion into app.workflow_executor.
        return _execute_out_of_domain(
            chat_request=chat_request,
            memory_key=memory_key,
            profile_key=profile_key,
            knowledge_matches=knowledge_matches,
            client_key=client_key,
            session_id=session_id,
            query_language=query_language,
            emit_customer_analytics=execution_context.emit_customer_analytics,
        )

    if is_category_discovery_query(chat_request.message):
        # V2.13d: verbatim code motion into app.workflow_executor.
        return _execute_category_discovery(
            chat_request=chat_request,
            memory_key=memory_key,
            profile_key=profile_key,
            products=products,
            knowledge_matches=knowledge_matches,
            client_key=client_key,
            session_id=session_id,
            query_language=query_language,
            emit_customer_analytics=execution_context.emit_customer_analytics,
        )

    already_have_subject = detect_already_have_subject(routing_message)
    special_subject = detect_special_product_subject(routing_message)
    replacement_subject = detect_replacement_subject(routing_message)
    related_subject = detect_related_subject(routing_message)
    # V2.13b (docs/workflow-precedence-before-v2.13b.md, rt0004): the
    # old unconditional "if special_subject: related_subject = None"
    # let a coarse, substring-based special_subject match (e.g.
    # "sushi_rice" from "sushi ryzi" anywhere in the message) always
    # win over an explicit companion/action request ("suvisiace
    # produkty k X") - product recognition is not the same as the
    # requested ACTION (Invariant #1). WorkflowResolver decides this
    # generically (Invariant #10), reusing the same action-language
    # marker set (_has_recipe_shopping_language) the V2.12.2 guard
    # below already relies on - not a new, query-specific patch.
    # V2.13b (regbug_rt0011 session-collision investigation): the
    # special_subject/related_subject conflict this resolver arbitrates
    # must be NATIVE to the current turn's own text, not manufactured by
    # contextualize_message() appending stale session diet-terms (e.g. a
    # carried-over diet-term tail coincidentally matching a special_subject
    # like "mild" on an unrelated later turn). Anchor the conflict check
    # against the raw message so contextualization cannot newly create a
    # related-products conflict that was never actually in this turn
    # (Section 8 - one turn -> one primary workflow, decided by what the
    # customer actually typed this turn).
    _raw_special_subject = detect_special_product_subject(chat_request.message)
    _raw_related_subject = detect_related_subject(chat_request.message)
    _action_target_analysis = _resolve_action_target_signal(
        routing_message,
        special_subject=special_subject if _raw_special_subject else None,
        related_subject=related_subject if _raw_related_subject else None,
        has_recipe_shopping_language=_has_recipe_shopping_language(routing_message),
        # V2.13b perf note: resolve_workflow()'s RELATED_PRODUCTS decision
        # only needs related_subject + has_recipe_shopping_language (see
        # app/turn_resolver.py) - the confident-family check is a separate,
        # already-existing guard a few lines below (V2.12.2 Bug A), so it
        # is intentionally NOT recomputed here (Section 17 - compute once).
        resolves_confident_product_family=False,
    )
    _action_target_resolution = _resolve_workflow(_action_target_analysis)
    _stash_workflow_resolution(_action_target_resolution)
    _related_products_forced = _action_target_resolution.workflow_id == _WORKFLOW_RELATED_PRODUCTS
    if special_subject and not _related_products_forced:
        related_subject = None
    if related_subject and PRODUCT_SET_SIGNAL_TOKENS & tokenize(routing_message):
        # "sake sety" (sake SETS) was forced into the sake cross-sell
        # branch just because it contains "sake" - even though a plain
        # search finds the literal "Sake Set" products among the top
        # hits. A set/kit/bundle word signals the customer wants a
        # specific product type, not "what goes well with X" pairings.
        related_subject = None
    if related_subject:
        # Real user report (screenshot, confirmed across brands): "Yamasa
        # sojova omacka" / "Sempio gochujang" named a specific brand but
        # got a cross-sell answer ("skvelo pasuje k tomu...") recommending
        # a DIFFERENT brand entirely, because "sojova omacka"/"gochujang"
        # already match a RELATED_SUBJECT_ALIASES entry regardless of what
        # brand prefixes it. A customer naming a specific brand wants that
        # product, not "what pairs with this category" - fall through to
        # plain product search instead, which already handles brand+
        # category combinations correctly (same fix as the Kikkoman
        # behavioral-ranking issue above, one layer up in the cascade).
        mentioned_related_brand = detect_mentioned_replacement_brand(routing_message, products, related_subject)
        if mentioned_related_brand:
            related_subject = None
    if related_subject and not _has_recipe_shopping_language(routing_message) and _query_resolves_to_confident_product_family(routing_message):
        # V2.12.2 root cause (docs/query-semantics.md): RELATED_INTENT_MARKERS
        # intentionally contains broad single-word markers like "rezanc"/
        # "olej" so genuine recipe questions ("co este chyba do rezancov")
        # are caught - but that same broadness was sweeping bare PRODUCT
        # NAME queries ("ryzove rezance", "kokosovy olej") into the
        # recipe-ingredient-companion workflow (related_products_for_subject)
        # just because the product name happens to contain one of those
        # words, returning an unrelated sauce/condiment shopping list
        # instead of the literal product. A bare query the taxonomy engine
        # can confidently resolve to its OWN family, with no genuine
        # recipe-shopping-list language present, is a direct product
        # search - same "explicit signal beats broad category word"
        # principle as the brand/kitchenware guards below.
        related_subject = None
    if related_subject and related_subject.endswith("_kuchyna") and any(
        marker in normalize(routing_message)
        for marker in ("noz", "nozice", "palick", "tanier", "misk", "misa", "cajnik", "salk", "lyzic", "podlozk", "sekaci", "brusny")
    ):
        # Real user report: "japonske noze" / "noz japonsky" (Japanese
        # knives) got swept into the broad "japonska_kuchyna" cuisine
        # cross-sell (soy sauce, mirin, dashi, wasabi, sushi rice) instead
        # of actual knife products - the "japonska_kuchyna" alias
        # "japonsk" matches ANY word starting with it, including
        # kitchenware (knives, chopsticks, plates, bowls, teapots), not
        # just food/ingredient questions. Same fix pattern as the
        # explicit-brand override above: a specific kitchenware term
        # signals the customer wants that literal product, not "what
        # goes with this cuisine" pairings.
        related_subject = None
    # V2.9 (Section 15/26/52) - within an active "sushi" use case, a
    # bare follow-up naming only the generic ingredient family ("aká
    # ryžu?", "aký ocot?") resolves to the sushi-specific concept
    # instead of a generic one. Scoped to exactly the verified test
    # scenario (Section 5 - narrow first); special_subject/related_subject
    # have already run their own collision guards above by this point.
    _V29_SUSHI_NARROWING = {"ryza": "sushi_rice", "ocot": "rice_vinegar"}
    _active_use_case = _get_active_use_case(memory)
    if _active_use_case == "sushi":
        if special_subject == "plain_rice":
            special_subject = _V29_SUSHI_NARROWING["ryza"]
            related_subject = None
        elif related_subject in _V29_SUSHI_NARROWING:
            special_subject = _V29_SUSHI_NARROWING[related_subject]
            related_subject = None
    if related_subject == "sushi":
        _set_active_use_case(memory, "sushi")
    elif _active_use_case == "sushi" and (
        (special_subject and special_subject not in {"sushi_rice", "rice_vinegar"})
        or replacement_subject
        or (related_subject and related_subject not in {"sushi", "ocot"})
    ):
        # Hard switch (Section 27/84) - a concretely different, named
        # subject means the customer has moved on from sushi.
        _clear_use_case_state(memory)
    cross_sell_matches = cross_sell_products_for_message(products, knowledge, contextual_message, chat_request.limit)
    article_product_subject = (
        detect_article_product_subject(routing_message, articles)
        if is_article_info_intent(chat_request.message)
        else None
    )
    product_advice_context = (
        is_article_info_intent(chat_request.message)
        and not article_product_subject
        and not already_have_subject
        and not special_subject
        and not replacement_subject
        and bool((knowledge_matches or {}).get("Products_AI"))
    )
    if not related_subject and is_context_followup(chat_request.message) and not memory.get("last_top_product_title"):
        # Only fall back to the coarse memory subject when there was no
        # specific last-seen product to fold into contextual_message in
        # the first place (contextualize_message() already tried the
        # more precise product-title-based context and it flows through
        # detect_related_subject() above on its own).
        related_subject = memory_subject
    needs_composition_caution = is_composition_caution_search(contextual_message)
    structured_presentation = None
    if _related_products_forced:
        matches = related_products_for_subject(products, knowledge, related_subject, chat_request.limit)
    elif already_have_subject:
        matches = complement_products_for_subject(products, already_have_subject, chat_request.limit)
    # V2.12.2 (docs/query-semantics.md, Section 34/106) - "sushi_rice" is a
    # second legacy special_subject (predating V2.4/V2.5) superseded the
    # same way "plain_rice" already was: SPECIAL_PRODUCT_QUERIES["sushi_rice"]
    # is a hardcoded BUNDLE search ("sushi ryza" + "nori" + "ryzovy ocot" +
    # "wasabi" merged together) that put nori/wasabi/rice-vinegar directly
    # into the primary search result for a plain "sushi ryza" product
    # query - cross-sell items mixed into direct search (a real,
    # confirmed production bug, not a hypothetical). The taxonomy engine
    # already classifies sushi rice as its own family=rice/subfamily=
    # sushi_rice with real exclusion of nori (family=seaweed) and rice
    # vinegar (family=vinegar) - falls back to the legacy bundle only if
    # structured retrieval genuinely cannot answer (identical safety net
    # to plain_rice).
    # V2.12.2 - rice_vinegar/rice_cooker are the SAME class
    # of legacy bare-product-name detector as plain_rice/sushi_rice above
    # (detect_special_product_subject() matches them via simple "root word
    # in message [+ second word]" patterns, not genuine dietary/exclusion
    # constraint language) - SPECIAL_PRODUCT_QUERIES["rice_vinegar"] includes
    # the sub-query "ocot sushi", which (via the legacy OR-based scorer
    # this bundle mechanism uses, see docs/query-semantics.md "Bug C")
    # pulled unrelated sushi-kit/rice-flour products directly into a plain
    # "ryzovy ocot" search - a real production bug found via this sprint
    # own smoke-testing, not from the original hypothesis. Every OTHER
    # special_subject (gluten_free_sushi/medium_spicy/hot/tofu_seaweed/
    # dairy_replacement/tamari/sushi_condiments/...) is a genuine curated
    # recommendation list for constraint-based questions the taxonomy
    # engine does not natively answer ("very spicy, not sweet") and is
    # deliberately left on the legacy path.
    elif special_subject in {"plain_rice", "sushi_rice", "rice_vinegar", "rice_cooker"} and V2_STRUCTURED_RETRIEVAL_ENABLED and (
        structured_presentation := _build_structured_result_set(
            contextual_message,
            products,
            product_taxonomy_index,
            normalized_product_index,
            catalog_version=id(products),
            taxonomy_version=TAXONOMY_VERSION,
            now=time.time(),
            base_query=(
                _bq.structured_query
                if (_bq := _get_result_set(memory.get("active_result_set_id", ""), time.time())) is not None
                and _bq.catalog_version == id(products)
                else None
            ),
            behavioral_rankings=get_behavioral_rankings(),
            merchandising_rules=get_merchandising_rules(),
            ranking_profile=get_active_ranking_profile(),
            # V2.9 (Section 9/10/20/21) - explicit override/removal/price
            # signals must reach retrieval, not just the merge function
            # itself (a real gap found via live multi-turn testing,
            # Section 79 - "niečo lacnejšie" fell through to a
            # nonsensical legacy lexical search without this).
            remove_size=_detect_size_removal(chat_request.message),
            remove_brand=_detect_brand_removal(chat_request.message),
            price_direction=_detect_price_direction(chat_request.message),
        )
    ) is not None:
        # V2.4/V2.5 supersede the legacy "plain_rice" bare-"ryz" special-
        # subject detector (a broad catch-all predating the taxonomy
        # engine) with precise family/variety-aware structured retrieval
        # and pagination - every OTHER special_subject entry (mild/hot/
        # kids_snack/rice_cooker/sushi_rice/...) is untouched.
        matches = _format_result_set_products(products, structured_presentation.initial_page_ids())
    elif special_subject:
        matches = special_products_for_subject(products, special_subject, chat_request.limit)
        # V2.16c (Section 19/65) - detect_special_product_subject() is
        # checked ahead of replacement_subject in this cascade and wins
        # for 3 of 13 REPLACEMENT_SUBJECT_ALIASES entries (fish sauce/rice
        # vinegar/sushi rice - confirmed via live audit, see docs/routing-
        # debt.md), so an explicit replacement request for one of those 3
        # never reached the gluten-free filter added below for the
        # alternative_products_for_subject() path. The intent label
        # itself (special_subject's own routing, incl. rt0013) is
        # deliberately NOT changed here - only candidate quality, and only
        # when this turn's own text also resolved a replacement_subject
        # (i.e. this really is a substitution request the legacy
        # special_subject path is silently servicing) and carries explicit
        # gluten-free language. rt0013's locked vegan case has no
        # gluten-free language and is unaffected (verified byte-identical).
        # The primary candidate list here (unlike alternative_products_for_
        # subject()'s Alternatives/REPLACEMENT_PRODUCT_QUERIES lookups) is a
        # generic SPECIAL_PRODUCT_QUERIES bundle (e.g. "gluten_free_sushi" -
        # soy sauce/nori/rice/wasabi/ginger together), never guaranteed to be
        # specific to the named replacement_subject - reproduced live:
        # "gluten_free_sushi" filtered to gluten-free soy sauce for an
        # explicit "sushi ryza" (sushi rice) replacement request, which does
        # not substitute for rice at all. Applying the same subject-name
        # relevance check used below for the widen fallback.
        if replacement_subject and is_gluten_free_search(chat_request.message):
            gluten_free_matches = [
                p for p in matches
                if product_is_gluten_free(p)
                and replacement_subject_matches_product(replacement_subject, str(p.get("title") or ""))
            ]
            if not gluten_free_matches:
                widened = cached_search_products(products, f"bezlepkova {replacement_subject}", max(chat_request.limit, 8))
                gluten_free_matches = [
                    p for p in widened
                    if product_is_gluten_free(p)
                    and replacement_subject_matches_product(replacement_subject, str(p.get("title") or ""))
                ]
            matches = gluten_free_matches[: chat_request.limit]
    elif replacement_subject:
        mentioned_replacement_brand = detect_mentioned_replacement_brand(chat_request.message, products, replacement_subject)
        matches = alternative_products_for_subject(
            products, knowledge, replacement_subject, chat_request.limit, exclude_brand=mentioned_replacement_brand
        )
        # V2.16c (Section 19, closure spec) - gluten-free is the one
        # dietary constraint the V2.16b audit proved reliable enough to
        # filter on (0 confirmed mistags across the full catalog, see
        # app.taxonomy._DIETARY_CATEGORY_TERMS docstring); vegan/
        # vegetarian remain unreliable (a real live false-positive was
        # found and fixed in V2.16b) and are deliberately NOT filtered
        # here - filtering on unverified data would risk silently
        # excluding safe candidates while giving false confidence in
        # whichever ones remain. Before this fix, "bez lepku"/"gluten
        # free" in a replacement query had ZERO effect on candidates -
        # reproduced live: "sojova omacka" and "sojova omacka bez lepku"
        # returned byte-identical lists, with a non-gluten-free product
        # ranked #1 either way.
        if replacement_subject and is_gluten_free_search(chat_request.message):
            gluten_free_matches = [m for m in matches if product_is_gluten_free(m)]
            if not gluten_free_matches:
                # Zero grounded candidates in the curated list - widen with
                # a direct catalog search rather than silently keeping the
                # unfiltered (unverified) list (Section 19/36: no unknown-
                # as-negative shortcut, no silent constraint relaxation).
                widened = cached_search_products(products, f"bezlepkova {replacement_subject}", max(chat_request.limit, 8))
                gluten_free_matches = [
                    p for p in widened
                    if product_is_gluten_free(p)
                    and replacement_subject_matches_product(replacement_subject, str(p.get("title") or ""))
                    and not (mentioned_replacement_brand and normalize(str(p.get("brand") or "")) == normalize(mentioned_replacement_brand))
                ]
            matches = gluten_free_matches[: chat_request.limit]
    elif article_product_subject:
        matches = article_products_for_subject(products, article_product_subject, chat_request.limit)
    elif cross_sell_matches:
        matches = cross_sell_matches
    elif related_subject:
        matches = related_products_for_subject(products, knowledge, related_subject, chat_request.limit)
    else:
        base_result_set = _get_result_set(memory.get("active_result_set_id", ""), time.time())
        base_query = (
            base_result_set.structured_query
            if base_result_set is not None and base_result_set.catalog_version == id(products)
            else None
        )
        structured_presentation = _build_structured_result_set(
            contextual_message,
            products,
            product_taxonomy_index,
            normalized_product_index,
            catalog_version=id(products),
            taxonomy_version=TAXONOMY_VERSION,
            now=time.time(),
            base_query=base_query,
            behavioral_rankings=get_behavioral_rankings(),
            merchandising_rules=get_merchandising_rules(),
            ranking_profile=get_active_ranking_profile(),
            remove_size=_detect_size_removal(chat_request.message),
            remove_brand=_detect_brand_removal(chat_request.message),
            price_direction=_detect_price_direction(chat_request.message),
        ) if V2_STRUCTURED_RETRIEVAL_ENABLED else None
        if structured_presentation is not None:
            matches = _format_result_set_products(products, structured_presentation.initial_page_ids())
        else:
            matches = hybrid_cached_search_products(contextual_message, chat_request.limit)
    is_shopping_list_request = wants_shopping_list(contextual_message)
    if structured_presentation is None:
        matches = personalize_products(matches, user_profile)
    memory["active_result_set_id"] = structured_presentation.result_set_id if structured_presentation is not None else ""
    _track_presentation(memory, [product.get("id") for product in matches if product.get("id")])
    if is_shopping_list_request and related_subject == "sushi":
        matches = sushi_shopping_core_products(products, matches, chat_request.limit)
    if is_shopping_list_request and related_subject == "tom_yum":
        matches = tom_yum_shopping_core_products(products, matches, chat_request.limit)
    if is_shopping_list_request and related_subject == "kimchi_ramen":
        matches = kimchi_ramen_shopping_core_products(products, matches, chat_request.limit)
    if is_shopping_list_request and related_subject not in {"sushi", "tom_yum", "kimchi_ramen"}:
        matches = recipe_shopping_core_products(products, related_subject, matches, chat_request.limit)
    if special_subject == "sushi_rice":
        matches = sorted(
            matches,
            key=lambda product: (
                not (
                    "ryza" in normalize(product.get("title", ""))
                    and bool({"sushi", "susi"} & set(normalize(product.get("title", "")).split()))
                ),
                int(product.get("recommendation_priority") or 999),
            ),
        )
    product_advice_text = (
        best_product_advice_answer(
            knowledge_matches,
            matched_links={m.get("link") for m in matches if m.get("link")},
        )
        if product_advice_context
        else None
    )
    intent = (
        "related_products"
        if _related_products_forced
        else (
            "article_products"
            if article_product_subject
            else (
                "replacement_products"
                if replacement_subject
                else (
                    "product_advice"
                    if product_advice_context
                    else ("related_products" if not special_subject and (related_subject or cross_sell_matches) else "product_search")
                )
            )
        )
    )
    annotate_recommendations(
        matches,
        intent,
        related_subject or article_product_subject,
        already_have_subject,
        replacement_subject or special_subject,
        contextual_message,
    )
    cart_candidates = cart_candidates_for_response(
        matches,
        intent,
        article_product_subject or replacement_subject or related_subject or already_have_subject or special_subject or contextual_message,
    )
    missing_ingredients = (
        missing_ingredients_for_subject(related_subject or article_product_subject or special_subject, [])
        if is_shopping_list_request and intent in {"related_products", "article_products", "product_search"}
        else []
    )
    shopping_list = (
        shopping_list_for_response(cart_candidates, missing_ingredients)
        if is_shopping_list_request and (cart_candidates or missing_ingredients)
        else {}
    )
    shopping_list_answer_text = (
        shopping_list_answer(related_subject or article_product_subject or special_subject or contextual_message, matches, missing_ingredients, query_language)
        if shopping_list
        else ""
    )
    fallback_related_subject = None if replacement_subject else related_subject
    update_session_memory(memory_key, chat_request.message, intent, matches, [], knowledge_matches)
    updated_profile = update_user_memory(profile_key, chat_request.message, intent, matches, [])
    _ci = build_customer_intent(
        chat_request.message, intent,
        subject=related_subject or article_product_subject or special_subject or replacement_subject or already_have_subject,
        language=query_language,
    )
    log_question(chat_request.message, client_key, len(matches), intent=intent, session_id=session_id, primary_intent=_ci.primary_intent, subject=_ci.subject or "", interaction_id=interaction_id)

    if structured_presentation is not None:
        # V2.5 Result Presentation (Section 24/50): deterministic, template-
        # based answer over the already-decided ResultSet - no OpenAI call,
        # no LLM re-selection of products/counts/pagination state.
        # V2.6 cross-sell: only ever computed for a FRESH primary answer,
        # never for a SHOW_MORE/SHOW_ALL continuation (Section 36 - that
        # branch returns earlier in this function and never reaches here).
        # Uses `memory_subject` (the raw persisted session subject,
        # Section 34), not `related_subject`: by construction,
        # `related_subject` is ALWAYS falsy whenever this code runs at
        # all - a truthy value (freshly detected or promoted from memory
        # a few lines above) always diverts to the earlier
        # `elif related_subject:` branch first. `memory_subject` is
        # computed once, independently, near the top of this function
        # and is never reassigned by the routing cascade, so it is the
        # only signal that can carry a persisted recipe/dish context
        # into this branch.
        _cross_sell_decision, _cross_sell_products = _cross_sell.build_cross_sell(
            structured_presentation=structured_presentation,
            related_subject=memory_subject,
            is_continuation=False,
            products=products,
            taxonomy_index=product_taxonomy_index,
            knowledge=knowledge,
            fbt_data=get_fbt_data(),
        )
        # V2.7 workflow labeling (Section 40): a pure analytics label
        # over signals already computed above - selection here never
        # changes which branch produced `matches`/`_cross_sell_products`
        # (shadow-safe, Section 20). Every early-return branch above
        # this point guarantees its own signal is falsy by the time
        # execution reaches here, so only the later-computed cascade
        # variables need to be passed explicitly.
        _workflow_selection = _select_workflow(_RoutingSignals(
            message=chat_request.message,
            already_have_subject=already_have_subject,
            special_subject=special_subject,
            replacement_subject=replacement_subject,
            article_product_subject=article_product_subject,
            cross_sell_matches_found=bool(cross_sell_matches),
            related_subject=related_subject,
            structured_answer_strategy=structured_presentation.answer_strategy,
            structured_has_explicit_attributes=bool(structured_presentation.structured_query.attributes),
            cross_sell_context_type=_cross_sell_decision.context_type or None,
        ))
        logger.info(
            "workflow_selected id=%s confidence=%.2f reason=%s fallback=%s",
            _workflow_selection.workflow_id, _workflow_selection.confidence,
            _workflow_selection.reason, _workflow_selection.fallback_workflow,
        )
        return {
            "answer": _compose_answer(structured_presentation),
            "products": matches,
            "articles": articles,
            "cart_candidates": cart_candidates,
            "missing_ingredients": missing_ingredients,
            "shopping_list": shopping_list,
            "knowledge": knowledge_summary(knowledge_matches),
            "memory": public_user_memory_summary(updated_profile),
            "intent": intent,
            "response_mode": "result_set",
            "matching_total": structured_presentation.matching_total,
            "displayed_count": structured_presentation.displayed_count,
            "has_more": structured_presentation.has_more,
            "result_set_id": structured_presentation.result_set_id,
            "answer_strategy": structured_presentation.answer_strategy,
            "groups": structured_presentation.groups,
            "cross_sell": _cross_sell_products,
            "cross_sell_eligible": _cross_sell_decision.eligible,
            "cross_sell_context_type": _cross_sell_decision.context_type,
            "cross_sell_intro": _compose_cross_sell_intro(_cross_sell_decision.context_type) if _cross_sell_decision.eligible else "",
            "workflow_id": _workflow_selection.workflow_id,
            "workflow_confidence": _workflow_selection.confidence,
        }

    if not matches and not knowledge_matches and not needs_knowledge:
        fallback_sections = (
            ("Products_AI", "Alternatives", "IntentMapping")
            if replacement_subject
            else ("Products_AI", "CrossSell", "Alternatives", "IntentMapping")
        )
        knowledge_matches = search_knowledge(
            knowledge,
            contextual_message,
            allowed_sections=fallback_sections,
        )
        articles = []

    if not matches and not knowledge_matches:
        general_recipe_answer = general_ai_recipe_answer(chat_request.message)
        if general_recipe_answer:
            return {
                "answer": general_recipe_answer,
                "products": [],
                "intent": "recipe",
                "memory": public_user_memory_summary(updated_profile),
                "response_mode": "no_match",
            }
        return {
            "answer": (
                "I couldn't find an exact product match. Try writing the name, brand, or category a bit differently."
                if query_language == "en"
                else "Nenašla som presný produkt. Skúste napísať názov, značku alebo kategóriu trochu inak."
            ),
            "products": [],
            "intent": intent,
            "memory": public_user_memory_summary(updated_profile),
            "response_mode": "no_match",
        }

    if should_use_fast_chat_answer(intent, matches, knowledge_matches, needs_composition_caution):
        return {
            "answer": product_advice_text or shopping_list_answer_text or fallback_answer(matches, knowledge_matches, fallback_related_subject, needs_composition_caution, query_language, is_product_advice=product_advice_context),
            "products": matches,
            "articles": articles,
            "cart_candidates": cart_candidates,
            "missing_ingredients": missing_ingredients,
            "shopping_list": shopping_list,
            "knowledge": knowledge_summary(knowledge_matches),
            "memory": public_user_memory_summary(updated_profile),
            "intent": intent,
            "response_mode": "fast",
        }

    if shopping_list_answer_text:
        return {
            "answer": shopping_list_answer_text,
            "products": matches,
            "articles": articles,
            "cart_candidates": cart_candidates,
            "missing_ingredients": missing_ingredients,
            "shopping_list": shopping_list,
            "knowledge": knowledge_summary(knowledge_matches),
            "memory": public_user_memory_summary(updated_profile),
            "intent": intent,
            "response_mode": "shopping_list",
        }

    client = _get_openai_client()
    if not client:
        logger.debug("No OPENAI_API_KEY set, using fallback answer.")
        return {
            "answer": product_advice_text or shopping_list_answer_text or fallback_answer(matches, knowledge_matches, fallback_related_subject, needs_composition_caution, query_language, is_product_advice=product_advice_context),
            "products": matches,
            "articles": articles,
            "cart_candidates": cart_candidates,
            "missing_ingredients": missing_ingredients,
            "shopping_list": shopping_list,
            "knowledge": knowledge_summary(knowledge_matches),
            "memory": public_user_memory_summary(updated_profile),
            "intent": intent,
            "response_mode": "fallback",
        }

    try:
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        messages = [
            {
                "role": "system",
                "content": (
                    "Si Foodland poradkyňa – odborná nákupná asistentka pre Foodland.sk, špeciálne azijské a svetové potraviny. "
                    "Odpovedaj v jazyku otázky zákazníka (napríklad slovensky, česky alebo anglicky); ak jazyk nie je jasný, odpovedaj po slovensky. Odpovedaj priateľsky a s predajným tónom. Neprezentuj sa ako AI. "
                    "Vždy rozlišuj náhrady a doplnky: pri otázke 'čím nahradiť X' odporúčaj podobné alternatívy, nie cross-sell doplnky. "
                    "Ak je zámer replacement_products, textovo iba vysvetli, že nižšie sú podobné alternatívy; nepridávaj domáce kombinácie ani produkty mimo kariet. "
                    "Pri otázke 'čo sa hodí k X' navrhuj doplnkové produkty (cross-sell) – napr. k sójovej omáčke mirin alebo ryžový ocot. "
                    "k ramen navrhni dashi alebo kimchi. Používaj formulácie: 'Odporúčam tiež...', "
                    "'Skvelo sa hodí k...', 'Zákazníci si k tomu zvyčajne berú aj...'. "
                    "Ak sa zákazník pýta, čo produkt je, na čo sa používa alebo ako chutí, "
                    "odpovedz na základe kontextu Products_AI v 1-2 vetách, až potom môžeš doplniť súvisiace odporúčania. "
                    "Používaj iba poskytnutý kontext: produkty, FAQ, recepty, cross-sell, alternatívy a Products_AI. "
                    "Pri produktoch uvádzaj cenu a odkaz, ak sú dostupné. Pri alergiách, zložení a dostupnosti "
                    "odporuč overiť detail produktu. Nevymýšľaj ceny, sklad ani vlastnosti produktu. "
                    "Nevkladaj žiadne URL ani markdown odkazy, ktoré nie sú doslovne v poskytnutom kontexte. "
                    "Konverzácia je viackolová – pri otázkach ako 'a čo k tomu?' alebo 'a ešte niečo?' "
                    "odkazuj na predchádzajúce správy v konverzácii."
                    "Ak zákazník hovorí, že produkt UŽ MÁ ('mám X', 'kúpil som X', 'vlastním X'), "
                    "odporúčaj výhradne iné, komplementárne produkty – nie ďalšie varianty toho istého. "
                    "Tvoja textová odpoveď má byť iba 1–2 vety: vysvetli, prečo odporúčané produkty patria k danej téme alebo receptu. "
                    "Nepíš zoznam produktov, ich názvy ani ceny – zákazník ich vidí v kartách pod odpoveďou."
                ),
            },
        ]
        # Pridaj historiu konverzacie (max 10 sprav)
        conversation_history = getattr(chat_request, "conversation_history", None) or []
        for msg in conversation_history[-10:]:
            if isinstance(msg, dict) and msg.get("role") in ("user", "assistant") and isinstance(msg.get("content"), str):
                messages.append({"role": msg["role"], "content": msg["content"][:2000]})
        # Pridaj aktualnu otazku so vsetkym kontextom
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Otázka zákazníka: {chat_request.message}\n\n"
                    f"Jazyk odpovede (pouzi presne tento formulovany jazyk, nie jazyk okolo neho): {'anglictina' if query_language == 'en' else 'slovencina'}\n\n"
                    f"Zistený zámer: {intent}\n\n"
                    f"Relevantné produkty:\n{products_context(matches)}\n\n"
                    f"Foodland Knowledge:\n{knowledge_context(knowledge_matches)}\n\n"
                    f"Bezpečnostná poznámka: {composition_caution_context(needs_composition_caution)}"
                ),
            }
        )
        # RETRY-01: _call_openai_with_retry pokusi sa max 3x pri RateLimit/Timeout/Connection
        answer_text = _call_openai_with_retry(client, messages, model)
        if not answer_text:
            answer_text = product_advice_text or shopping_list_answer_text or fallback_answer(matches, knowledge_matches, fallback_related_subject, needs_composition_caution, query_language, is_product_advice=product_advice_context)
        allowed_urls = collect_allowed_urls(matches, knowledge_matches)
        allowed_prices = collect_allowed_prices(matches)
        grounding_result = validate_answer(
            answer_text,
            allowed_urls,
            allowed_prices=allowed_prices,
            strict_prices=True,
        )
        if grounding_result.has_violations:
            logger.warning("Grounding violations: %s", grounding_result.violations)
        answer_text = grounding_result.sanitized_answer
        logger.info("OpenAI response generated.")
        return {
            "answer": answer_text,
            "products": matches,
            "articles": articles,
            "cart_candidates": cart_candidates,
            "missing_ingredients": missing_ingredients,
            "shopping_list": shopping_list,
            "knowledge": knowledge_summary(knowledge_matches),
            "memory": public_user_memory_summary(updated_profile),
            "intent": intent,
            "response_mode": "llm",
        }
    except (RateLimitError, APITimeoutError, APIConnectionError) as exc:
        logger.warning("OpenAI transient error after retries: %s", exc)
        log_backend_error("openai_transient_error", str(exc))
        return {
            "answer": product_advice_text or shopping_list_answer_text or fallback_answer(matches, knowledge_matches, fallback_related_subject, needs_composition_caution, query_language, is_product_advice=product_advice_context),
            "products": matches,
            "articles": articles,
            "cart_candidates": cart_candidates,
            "missing_ingredients": missing_ingredients,
            "shopping_list": shopping_list,
            "knowledge": knowledge_summary(knowledge_matches),
            "memory": public_user_memory_summary(updated_profile),
            "intent": intent,
            "response_mode": "fallback",
            "warning": (
                "The service is currently overloaded, showing the products we found."
                if query_language == "en"
                else "Služba je momentálne preťažená, zobrazujem nájdené produkty."
            ),
        }
    except Exception as exc:
        logger.error("OpenAI API failed: %s", exc, exc_info=True)
        log_backend_error("openai_response_failed", str(exc))
        return {
            "answer": product_advice_text or shopping_list_answer_text or fallback_answer(matches, knowledge_matches, fallback_related_subject, needs_composition_caution, query_language, is_product_advice=product_advice_context),
            "products": matches,
            "articles": articles,
            "cart_candidates": cart_candidates,
            "missing_ingredients": missing_ingredients,
            "shopping_list": shopping_list,
            "knowledge": knowledge_summary(knowledge_matches),
            "memory": public_user_memory_summary(updated_profile),
            "intent": intent,
            "response_mode": "fallback",
            "warning": (
                "Could not generate a written answer, showing the products we found."
                if query_language == "en"
                else "Odpoveď sa nepodarilo vygenerovať, zobrazujem nájdené produkty."
            ),
        }


def _compute_answered(response: dict) -> bool:
    """V2.12 audit fix: app.widget.js's no_result telemetry (and
    therefore app.learning_opportunities' HIGH_ZERO_RESULT/TAXONOMY_GAP_
    CANDIDATE detectors, which read that same event) only ever checked
    products/recipes/articles - a real FAQ answer or allergen-safety
    disclaimer lives in `answer` text alone and was being misclassified
    as a customer-facing failure (found via a real production audit -
    'doprava' got a correct FAQ answer about shipping options but still
    fired no_result on every occurrence). This is the single choke point
    every /chat response passes through, so the widget checks ONE
    explicit field instead of re-deriving 'did we help' itself."""
    if response.get("products"):
        return True
    if response.get("recipes"):
        return True
    if response.get("articles"):
        return True
    if response.get("recipe_shopping_plan"):
        return True
    knowledge = response.get("knowledge") or {}
    if any(isinstance(v, (int, float)) and v > 0 for v in knowledge.values()):
        return True
    # These intents always carry a real, substantive `answer` (never the
    # generic fallback text) at their one-and-only return site in
    # _chat_impl() - each is gated so it can only return with this
    # intent when it actually has something to say.
    if response.get("intent") in {"allergen_safety", "faq", "missing_composition", "reset"}:
        return True
    return False


def _chat_internal(chat_request: ChatRequest, request: Request, execution_context: _ExecutionContext | None = None) -> dict:
    # V2.12.4: resolved locally (mirrors _chat_impl's own resolution,
    # Section 59 precedent) so the quality-trace gate below sees the
    # REAL resolved context even when the caller passed None.
    _resolved_context = execution_context if execution_context is not None else (
        _customer_context() if isinstance(request, Request) else _evaluation_context()
    )
    # V2.15b: single choke point for every response _chat_impl() can
    # produce (legacy inline branches and workflow_executor handlers
    # alike), so this is the one place that can attach interaction_id
    # to ALL of them without touching every individual return site.
    _interaction_id = secrets.token_hex(8)
    _quality_start = time.perf_counter()
    response = _chat_impl(chat_request, request, execution_context=execution_context, interaction_id=_interaction_id)
    response["answered"] = _compute_answered(response)
    response["interaction_id"] = _interaction_id
    # V2.17.1: read-only customer conversation audit capture (Section 11 -
    # observes the ALREADY-COMPLETED response, never reruns intent/search/
    # ranking/cross-sell/LLM). Gated on the same is_customer_traffic signal
    # the search-quality trace below already uses, so EVALUATION/LEARNING/
    # SHADOW/ADMIN_TEST traffic never reaches customer_audit.jsonl.
    # capture_customer_turn() never raises - see app.customer_audit
    # docstring - but a call-site try/except stays here too anyway, the
    # same double-safety pattern _record_search_quality_trace already
    # uses just below, so a future change to that guarantee still cannot
    # affect this response.
    if _resolved_context.is_customer_traffic:
        try:
            _capture_customer_turn(
                chat_request=chat_request,
                client_key=get_client_key(request),
                response=response,
                latency_ms=(time.perf_counter() - _quality_start) * 1000,
            )
        except Exception:
            logger.warning("Customer audit capture failed at call site (non-fatal)", exc_info=True)
    if _resolved_context.emit_customer_analytics:
        try:
            _trace = _build_search_quality_trace(
                session_id=getattr(chat_request, "session_id", "") or "",
                salt=os.getenv("ANALYTICS_SALT", ""),
                execution_mode=_resolved_context.mode.value,
                intent=response.get("intent") or "",
                visible_product_count=len(response.get("products") or []),
                no_result=not response["answered"],
                answered=response["answered"],
                latency_ms=(time.perf_counter() - _quality_start) * 1000,
                deployment_version=_search_quality_deployment_version(),
                ranking_config_version=get_active_ranking_profile_version(),
                taxonomy_version=TAXONOMY_VERSION,
                retrieval_decision=_pop_search_quality_decision(),
                resolved_workflow=(_resolved_workflow := _pop_workflow_resolution()) and _resolved_workflow.workflow_id,
                resolver_reason=_resolved_workflow.reason if _resolved_workflow else None,
                interaction_id=_interaction_id,
            )
            _record_search_quality_trace(_trace)
        except Exception:
            logger.warning("Failed to record search quality trace", exc_info=True)
    return response


@app.post("/chat")
def chat(
    chat_request: ChatRequest,
    request: Request,
    x_admin_token: str | None = Header(default=None),
    x_execution_context: str | None = Header(default=None),
) -> dict:
    # V2.13a: thin AdvisorEngine adapter (app/advisor_engine.py) - HTTP
    # transport concerns (real vs. duck-typed Request, client_key
    # derivation) are resolved HERE, once, then handed to AdvisorEngine
    # as plain, already-trusted values. Deliberately does NOT force
    # execution_context=customer_context() here: real HTTP dispatch
    # always hands this a genuine Request, and a large existing test
    # suite calls chat() directly with a duck-typed FakeRequest
    # expecting the pre-V2.12.1 "not a real Request -> not
    # rate-limited" behavior to keep working unchanged - same
    # isinstance() fallback as before, just resolved one level up.
    # Callers that want to declare a specific non-CUSTOMER mode
    # explicitly should call app.advisor_engine.advisor_engine.run()
    # directly (see app.evaluation.adapter, app.ranking_shadow) rather
    # than route through this endpoint function.
    resolved_context = _customer_context() if isinstance(request, Request) else _evaluation_context()
    # V2.15b (Section 8/11/12 of the readiness audit): the single most
    # severe V2.15a finding was that ANY external HTTP call to /chat -
    # including every live production smoke/verification test this
    # project has ever run - was silently indistinguishable from a real
    # customer, since isinstance(request, Request) is unconditionally
    # True for real HTTP dispatch. This lets an authorized caller
    # declare ADMIN_TEST explicitly, but FAILS CLOSED: a missing header,
    # an unrecognized x_execution_context value, or a token that does
    # not resolve to at least OPERATIONS scope leaves resolved_context
    # completely untouched - a real customer request (which never sends
    # these headers) is byte-for-byte unaffected. Does not weaken
    # authentication: reuses the same admin token store every other
    # /admin/* endpoint already validates against.
    if (
        resolved_context.is_customer_traffic
        and x_execution_context == "ADMIN_TEST"
        and _resolve_admin_token_scope(x_admin_token) in (_SCOPE_OPERATIONS, _SCOPE_PROMOTION)
    ):
        resolved_context = _admin_test_context()
    advisor_request = _AdvisorRequest(
        message=chat_request.message,
        session_id=chat_request.session_id,
        limit=chat_request.limit,
        conversation_history=chat_request.conversation_history,
        client_id=chat_request.client_id,
        client_key=get_client_key(request),
    )
    return _advisor_engine.run(advisor_request, resolved_context)


def should_use_fast_chat_answer(
    intent: str,
    matches: list[dict],
    knowledge_matches: dict | None,
    needs_composition_caution: bool = False,
) -> bool:
    if os.getenv("FOODLAND_FAST_RESPONSES", "true").strip().lower() in {"0", "false", "no"}:
        return False
    if needs_composition_caution:
        return False
    if intent == "product_search" and matches and not knowledge_matches:
        return True
    if intent in {"faq", "recipe", "unknown", "allergen_safety"}:
        return True
    return False


def get_client_key(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def annotate_recommendations(
    matches: list[dict],
    intent: str,
    related_subject: str | None = None,
    already_have_subject: str | None = None,
    special_subject: str | None = None,
    query: str = "",
) -> None:
    context = related_subject or already_have_subject or special_subject or query
    for index, product in enumerate(matches or [], start=1):
        group = recommendation_group(product)
        product["recommendation_group"] = group
        product["recommendation_priority"] = index
        product["recommendation_reason"] = recommendation_reason(product, group, intent, context)


def personalize_products(matches: list[dict], profile: dict | None) -> list[dict]:
    if not matches or not profile:
        return matches
    ranked: list[tuple[int, int, dict]] = []
    for index, product in enumerate(matches):
        score = personalization_score(product_profile_text(product), product, profile)
        if score > 0:
            product["personalized"] = True
            product["personalization_score"] = score
        ranked.append((score, -index, product))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [product for _, _, product in ranked]


def personalize_recipes(recipes: list[dict], profile: dict | None) -> list[dict]:
    if not recipes or not profile:
        return recipes
    ranked: list[tuple[int, int, dict]] = []
    for index, recipe in enumerate(recipes):
        text = normalize(" ".join(str(recipe.get(key, "")) for key in ("title", "cuisine", "note", "link")))
        score = personalization_score(text, {}, profile)
        if score > 0:
            recipe["personalized"] = True
            recipe["personalization_score"] = score
        ranked.append((score, -index, recipe))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [recipe for _, _, recipe in ranked]


def prioritize_recipes_for_phrase(recipes: list[dict], message: str) -> list[dict]:
    if not recipes:
        return recipes
    ranked = [
        (recipe_phrase_score(message, recipe), -index, recipe)
        for index, recipe in enumerate(recipes)
    ]
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [recipe for _, _, recipe in ranked]


def product_profile_text(product: dict) -> str:
    return normalize(
        " ".join(
            str(product.get(key, ""))
            for key in ("title", "brand", "product_type", "category", "description")
        )
    )


def personalization_score(text: str, item: dict, profile: dict) -> int:
    score = 0
    score += profile_marker_score(text, profile.get("cuisines", {}), RECIPE_CUISINE_MARKERS, 4)
    score += profile_marker_score(text, profile.get("subjects", {}), RELATED_SUBJECT_ALIASES, 3)
    score += profile_marker_score(text, profile.get("diet_terms", {}), DIET_TERM_MARKERS, 3)
    score += profile_text_score(text, profile.get("product_titles", {}), 1, max_weight=2)
    score += profile_text_score(text, profile.get("product_brands", {}), 4, max_weight=6)
    brand = normalize(str(item.get("brand", "")))
    if brand:
        score += profile_text_score(brand, profile.get("product_brands", {}), 2, max_weight=6)
    return score


def search_autocomplete(
    products_list: list[Product] | list[dict],
    all_knowledge: dict,
    query: str,
    limit: int = 8,
    profile: dict | None = None,
) -> list[dict]:
    normalized_query = normalize(query).strip()
    if len(normalized_query) < 2:
        return []

    query_tokens = tokenize(query)
    raw_query_tokens = raw_tokens(query)
    suggestions: dict[str, dict] = {}
    has_explicit_autocomplete_intent = any(
        marker in normalized_query
        for config in AUTOCOMPLETE_INTENTS.values()
        for marker in config["markers"]
    )
    suppress_highlight = is_predictive_autocomplete_query(normalized_query)

    def add_suggestion(item: dict) -> None:
        label = " ".join(str(item.get("label") or "").split())
        if not label:
            return
        item["label"] = label[:120]
        item.setdefault("query", label)
        item.setdefault("score", 0)
        if suppress_highlight:
            item.pop("highlight", None)
        else:
            highlight = autocomplete_highlight_ranges(label, query)
            if highlight:
                item.setdefault("highlight", highlight)
            else:
                item.pop("highlight", None)
        key = f"{item.get('type', 'tip')}:{normalize(label)}"
        existing = suggestions.get(key)
        if not existing or int(item["score"]) > int(existing.get("score", 0)):
            suggestions[key] = item

    def text_score(label: str, extra_text: str = "") -> int:
        text = normalize(" ".join([label, extra_text]))
        label_tokens = tokenize(label)
        all_tokens = tokenize(" ".join([label, extra_text]))
        token_hits = len(query_tokens & label_tokens)
        field_hits = len(query_tokens & all_tokens)
        fuzzy_label_hits = fuzzy_hits(query_tokens, label_tokens)
        direct = normalized_query in text or text.startswith(normalized_query)
        prefix = any(token.startswith(normalized_query) for token in label_tokens) if len(normalized_query) >= 3 else False
        if not direct and not prefix and not token_hits and not field_hits and not fuzzy_label_hits:
            return 0
        score = 0
        score += 28 if direct else 0
        score += 18 if prefix else 0
        score += 12 * token_hits
        score += 5 * field_hits
        score += 7 * fuzzy_label_hits
        score += sum(POPULAR_AUTOCOMPLETE_BOOSTS.get(token, 0) for token in query_tokens & all_tokens)
        return score

    for item in autocomplete_intent_suggestions(query, profile):
        add_suggestion(item)

    # V2.2 taxonomy-aware suggestions: grounded compound category
    # concepts (app.taxonomy.build_concept_index) and curated
    # product-choice questions (data/knowledge.json IntentMapping).
    # Scored to compete with exact-match products/intents (see
    # docs/advisor-v2-architecture.md) - never filters UNKNOWN products,
    # purely additive alongside every existing suggestion source below.
    for index, item in enumerate(taxonomy_category_suggestions(query, taxonomy_concept_index, 4)):
        item["score"] = 620 - index * 20 + min(int(item.get("product_count", 0)), 20)
        add_suggestion(item)

    for index, item in enumerate(question_suggestions(all_knowledge, query, 3)):
        item["score"] = (580 if item.get("type") == "comparison" else 540) - index * 15
        add_suggestion(item)

    for phrase, replacement in PHRASE_SYNONYMS.items():
        if normalized_query in phrase or normalized_query in replacement or any(token in tokenize(phrase) for token in query_tokens):
            add_suggestion({"type": "synonym", "label": replacement, "query": replacement, "score": 92})

    if should_use_fast_autocomplete():
        explicit_replace_query = is_explicit_replace_autocomplete_query(normalized_query)
        if not explicit_replace_query:
            product_hits = personalize_products(cached_search_products(products_list, query, max(limit * 2, 12)), profile)
            for index, product in enumerate(product_hits[: max(limit, 8)]):
                label = str(product.get("title", "")).strip()
                if not label or should_skip_autocomplete_product(raw_query_tokens, product):
                    continue
                availability = str(product.get("availability", ""))
                available = availability in {"in_stock", "in stock", "Skladom", "skladom"}
                add_suggestion(
                    {
                        "type": "product",
                        "label": label,
                        "query": label,
                        "score": autocomplete_content_score(
                            label,
                            query,
                            145 - index,
                            boost_direct_match=not has_explicit_autocomplete_intent,
                        )
                        + int(product.get("personalization_score", 0)) * 8,
                        "url": product.get("link") or product.get("url") or "",
                        "image": product.get("image_link") or "",
                        "badge": "Skladom" if available else "",
                        "brand": product.get("brand") or "",
                    }
                )
        if not explicit_replace_query:
            for index, item in enumerate(cached_autocomplete_suggestions(products_list, query, max(limit * 2, 8))):
                if item.get("type") == "product":
                    continue
                score_by_type = {"synonym": 112, "brand": 104, "category": 98}
                item["score"] = score_by_type.get(str(item.get("type", "")), 90) - index
                add_suggestion(item)
        for index, recipe in enumerate(lightweight_recipe_autocomplete(all_knowledge, query, limit)):
            add_suggestion(
                {
                    "type": "recipe",
                    "label": recipe["title"],
                    "query": f"recept na {recipe['title']}",
                    "score": autocomplete_content_score(
                        recipe["title"],
                        query,
                        118 - index,
                        boost_direct_match=not has_explicit_autocomplete_intent,
                    ),
                    "url": recipe.get("link") or "",
                    "badge": recipe.get("cuisine") or "Recept",
                }
            )
        ordered = diverse_autocomplete_items(suggestions.values(), limit)
        return [
            {key: value for key, value in item.items() if key != "score" and value not in ("", None)}
            for item in ordered
        ]

    product_hits = cached_search_products(products_list, query, max(limit * 4, 30))
    product_hits = personalize_products(product_hits, profile)
    for index, product in enumerate(product_hits[: max(limit, 8)]):
        label = str(product.get("title", "")).strip()
        base = text_score(
            label,
            " ".join(str(product.get(key, "")) for key in ("brand", "product_type", "category", "description")),
        )
        if base <= 0:
            continue
        availability = str(product.get("availability", ""))
        available = availability in {"in_stock", "in stock", "Skladom", "skladom"}
        score = 80 + base - index
        score += 24 if available else -30 if availability else 0
        score += int(product.get("personalization_score", 0)) * 6
        if not strict_product_match(raw_query_tokens, normalize(label)):
            continue
        if should_skip_autocomplete_product(raw_query_tokens, product):
            continue
        add_suggestion(
            {
                "type": "product",
                "label": label,
                "query": label,
                "score": score,
                "url": product.get("link") or product.get("url") or "",
                "image": product.get("image_link") or "",
                "badge": "Skladom" if available else "",
                "brand": product.get("brand") or "",
            }
        )

    brand_scores: Counter[str] = Counter()
    category_scores: Counter[str] = Counter()
    for product in products_list:
        product_data = format_product(product)
        title = str(product_data.get("title", ""))
        brand = str(product_data.get("brand", ""))
        category = str(product_data.get("product_type", product_data.get("category", "")))
        availability = str(product_data.get("availability", ""))
        availability_boost = 8 if availability in {"in_stock", "in stock"} else 0
        if brand:
            score = text_score(brand, title) + availability_boost
            if score > 0:
                brand_scores[brand] = max(brand_scores[brand], score + 45)
        for part in re.split(r"[>/|]", category):
            clean_part = " ".join(part.split())
            if not clean_part or len(clean_part) < 3:
                continue
            if "shoyu" in raw_query_tokens and any(marker in normalize(clean_part) for marker in ("krek", "snack")):
                continue
            score = text_score(clean_part, title) + availability_boost
            if score > 0:
                category_scores[clean_part] = max(category_scores[clean_part], score + 36)

    for brand, score in brand_scores.most_common(limit):
        normalized_brand = normalize(brand)
        score += profile_text_score(normalized_brand, (profile or {}).get("product_brands", {}), 4, max_weight=6)
        add_suggestion({"type": "brand", "label": brand, "query": brand, "score": score})

    for category, score in category_scores.most_common(limit):
        add_suggestion({"type": "category", "label": category, "query": category, "score": score})

    recipes = recipe_results(search_knowledge(all_knowledge, query), limit, query, all_knowledge)
    recipes = personalize_recipes(recipes, profile)
    recipes = prioritize_recipes_for_phrase(recipes, query)
    for index, recipe in enumerate(recipes):
        label = str(recipe.get("title", "")).strip()
        score = text_score(label, " ".join(str(recipe.get(key, "")) for key in ("cuisine", "note", "link")))
        if score <= 0:
            continue
        score += 75 - index + int(recipe.get("personalization_score", 0)) * 2
        add_suggestion(
            {
                "type": "recipe",
                "label": label,
                "query": f"recept na {label}",
                "score": score,
                "url": recipe.get("link") or "",
                "badge": recipe.get("cuisine") or "Recept",
            }
        )

    ordered = diverse_autocomplete_items(suggestions.values(), limit)
    return [
        {key: value for key, value in item.items() if key != "score" and value not in ("", None)}
        for item in ordered
    ]


def diverse_autocomplete_items(items, limit: int) -> list[dict]:
    target = max(1, min(limit, 12))
    ordered = sorted(items, key=lambda item: int(item.get("score", 0)), reverse=True)
    selected: list[dict] = []
    type_counts: Counter[str] = Counter()
    soft_caps = {
        "product": 3,
        "brand": 2,
        "category": 2,
        "recipe": 2,
        "synonym": 2,
        "buy_intent": 1,
        "cook_intent": 1,
        "explain_intent": 1,
        "replace_intent": 1,
        "taxonomy_category": 4,
        "question": 2,
        "comparison": 1,
    }

    for item in ordered:
        item_type = str(item.get("type", "tip"))
        if type_counts[item_type] >= soft_caps.get(item_type, 2):
            continue
        selected.append(item)
        type_counts[item_type] += 1
        if len(selected) >= target:
            return selected

    for item in ordered:
        if item in selected:
            continue
        selected.append(item)
        if len(selected) >= target:
            break
    return selected


def is_predictive_autocomplete_query(normalized_query: str) -> bool:
    tokens = normalized_query.split()
    if len(tokens) >= 3 and any(
        marker in normalized_query
        for marker in (
            "ako ",
            "co ",
            "cim ",
            "recept",
            "varit",
            "vari",
            "uvarit",
            "pripravit",
            "nahrad",
            "vysvetli",
            "rozdiel",
        )
    ):
        return True
    return any(
        marker in normalized_query
        for config in AUTOCOMPLETE_INTENTS.values()
        for marker in config["markers"]
    )


def autocomplete_content_score(label: str, query: str, base_score: int, boost_direct_match: bool = True) -> int:
    normalized_label = normalize(label)
    normalized_query = normalize(query).strip()
    query_tokens = {token for token in tokenize(query) if len(token) >= 2}
    score = base_score
    if boost_direct_match and normalized_query and normalized_query in normalized_label:
        score += 520
    if query_tokens:
        label_tokens = tokenize(label)
        prefix_hits = sum(1 for token in query_tokens if any(label_token.startswith(token) for label_token in label_tokens))
        if boost_direct_match:
            score += prefix_hits * 180
            score += len(query_tokens & label_tokens) * 120
        else:
            score += prefix_hits * 16
            score += len(query_tokens & label_tokens) * 10
    return score


def autocomplete_highlight_ranges(label: str, query: str) -> list[dict]:
    normalized_query_tokens = [token for token in tokenize(query) if len(token) >= 2]
    if not normalized_query_tokens:
        return []

    normalized_label = normalize(label)
    ranges: list[tuple[int, int]] = []
    for token in normalized_query_tokens:
        start = normalized_label.find(token)
        if start < 0:
            for label_token in normalized_label.split():
                if label_token.startswith(token):
                    start = normalized_label.find(label_token)
                    break
        if start < 0:
            continue
        ranges.append((start, min(len(label), start + len(token))))

    if not ranges:
        return []

    ranges.sort()
    merged: list[tuple[int, int]] = []
    for start, end in ranges:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))

    return [{"start": start, "end": end} for start, end in merged[:4]]


def should_use_fast_autocomplete() -> bool:
    return os.getenv("FOODLAND_FAST_AUTOCOMPLETE", "true").strip().lower() not in {"0", "false", "no"}


def lightweight_recipe_autocomplete(all_knowledge: dict, query: str, limit: int = 3) -> list[dict]:
    normalized_query = normalize(query).strip()
    if len(normalized_query) < 3:
        return []
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    recipes = all_knowledge.get("sections", {}).get("Recipes", [])
    ranked: list[tuple[int, dict]] = []
    for record in recipes:
        recipe = recipe_card(record)
        title = str(recipe.get("title", ""))
        text = normalize(recipe_search_text(record, recipe))
        title_tokens = tokenize(title)
        all_tokens = tokenize(text)
        token_hits = len(query_tokens & title_tokens)
        field_hits = len(query_tokens & all_tokens)
        direct = normalized_query in normalize(title) or normalize(title).startswith(normalized_query)
        fuzzy = fuzzy_hits(query_tokens, title_tokens)
        score = (40 if direct else 0) + 14 * token_hits + 5 * field_hits + 6 * fuzzy
        if "recept" in normalize(query):
            score += 18
        if score > 0 and recipe.get("title"):
            score += recipe_subject_score(detect_recipe_subject(query), recipe)
            score += recipe_phrase_score(query, recipe)
            ranked.append((score, recipe))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [recipe for _, recipe in ranked[: max(1, min(limit, 4))]]


AUTOCOMPLETE_INTENTS = {
    "buy": {
        "type": "buy_intent",
        "label": "{subject} skladom",
        "query": "{subject}",
        "badge": "Produkty",
        "markers": (
            "kupit",
            "chcem kupit",
            "mate",
            "predavate",
            "skladom",
            "cena",
            "najdi",
            "hladam",
            "ukaz",
            "potrebujem",
            "produkt",
            "produkty",
        ),
    },
    "cook": {
        "type": "cook_intent",
        "label": "Recept na {subject}",
        "query": "recept na {subject}",
        "badge": "Recept",
        "markers": (
            "recept",
            "varit",
            "vari",
            "ako sa vari",
            "ako sa variť",
            "ako varit",
            "uvarit",
            "pripravit",
            "postup",
            "ingrediencie",
            "suroviny",
            "co potrebujem",
            "co varit",
        ),
    },
    "explain": {
        "type": "explain_intent",
        "label": "Čo je {subject}?",
        "query": "čo je {subject}",
        "badge": "Poradca",
        "markers": (
            "co je",
            "čo je",
            "vysvetli",
            "znamena",
            "ako chut",
            "na co je",
            "pouzitie",
            "rozdiel",
        ),
    },
    "replace": {
        "type": "replace_intent",
        "label": "Čím nahradiť {subject}?",
        "query": "čím nahradiť {subject}",
        "badge": "Náhrada",
        "markers": (
            "nahrad",
            "namiesto",
            "alternativ",
            "alternativa",
            "cim nahradit",
            "čím nahradiť",
            "nemam",
            "nemám",
        ),
    },
}


AUTOCOMPLETE_INTENT_FILLER = (
    "chcem",
    "kupit",
    "kúpiť",
    "mate",
    "máte",
    "predavate",
    "predávate",
    "skladom",
    "cena",
    "najdi",
    "hladam",
    "hľadám",
    "ukaz",
    "ukáž",
    "potrebujem",
    "produkt",
    "produkty",
    "recept",
    "varit",
    "variť",
    "vari",
    "varí",
    "sa",
    "uvarit",
    "uvariť",
    "pripravit",
    "pripraviť",
    "postup",
    "ingrediencie",
    "suroviny",
    "co",
    "čo",
    "je",
    "vysvetli",
    "znamena",
    "znamená",
    "ako",
    "chuti",
    "chutí",
    "na",
    "pouzitie",
    "použitie",
    "rozdiel",
    "cim",
    "čím",
    "nahradit",
    "nahradiť",
    "nahrad",
    "namiesto",
    "alternativ",
    "alternativa",
    "nemam",
    "nemám",
)


def autocomplete_intent_suggestions(query: str, profile: dict | None = None) -> list[dict]:
    subject = autocomplete_subject(query)
    if len(normalize(subject)) < 2:
        return []
    display_subject = autocomplete_display_subject(subject)

    normalized_query = normalize(query)
    matched_intents = [
        intent
        for intent, config in AUTOCOMPLETE_INTENTS.items()
        if any(marker in normalized_query for marker in config["markers"])
    ]
    if not matched_intents:
        matched_intents = ["buy", "cook", "explain", "replace"]

    profile_intents = profile if isinstance(profile, dict) else {}
    suggestions: list[dict] = []
    for index, intent in enumerate(matched_intents):
        config = AUTOCOMPLETE_INTENTS[intent]
        strong_match = any(marker in normalized_query for marker in config["markers"])
        score = (650 if strong_match else 500) - index
        score += autocomplete_intent_memory_score(intent, profile_intents) if not strong_match else 0
        suggestions.append(
            {
                "type": config["type"],
                "label": config["label"].format(subject=display_subject),
                "query": config["query"].format(subject=display_subject),
                "score": score,
                "badge": config["badge"],
            }
        )
    return suggestions


def autocomplete_intent_memory_score(intent: str, profile: dict) -> int:
    counts = profile.get("intent_counts", {})
    if not isinstance(counts, dict):
        counts = {}
    direct_count = int(counts.get(intent, 0) or 0)
    if intent == "replace":
        direct_count += int(counts.get("dairy_replacement", 0) or 0)
        direct_count += int(counts.get("vegan_fish_sauce_replacement", 0) or 0)

    last_intent = memory_intent_bucket(str(profile.get("last_intent", "")))
    score = min(direct_count, 8) * 35
    if last_intent == intent:
        score += 55
    return score


def is_explicit_replace_autocomplete_query(normalized_query: str) -> bool:
    return any(marker in normalized_query for marker in AUTOCOMPLETE_INTENTS["replace"]["markers"])


def autocomplete_subject(query: str) -> str:
    normalized_query = normalize(query)
    if normalized_query.endswith("pho b"):
        return "pho bo"
    if normalized_query.endswith("pho g"):
        return "pho ga"
    tokens = [
        token
        for token in normalized_query.split()
        if token not in AUTOCOMPLETE_INTENT_FILLER and len(token) >= 2
    ]
    subject = " ".join(tokens).strip()
    return complete_autocomplete_subject(subject)[:60]


AUTOCOMPLETE_DISPLAY_SUBJECTS = {
    "sojova omacka": "Sójová omáčka",
    "kokosove mlieko": "Kokosové mlieko",
    "ryzovy ocot": "Ryžový ocot",
    "ryzove rezance": "Ryžové rezance",
    "hoisin omacka": "Hoisin omáčka",
    "rybacia omacka": "Rybacia omáčka",
    "ustricova omacka": "Ustricová omáčka",
    "pad thai": "Pad Thai",
    "gochujang": "Gochujang",
    "sriracha": "Sriracha",
    "kimchi": "Kimchi",
    "ramen": "Ramen",
    "sushi": "Sushi",
    "mirin": "Mirin",
    "wasabi": "Wasabi",
    "nori": "Nori",
    "tamari": "Tamari",
    "tofu": "Tofu",
    "kimchi ramen": "Kimchi Ramen",
    "pho bo": "Pho Bo",
    "pho ga": "Pho Ga",
}


def autocomplete_display_subject(subject: str) -> str:
    normalized_subject = normalize(subject).strip()
    if not normalized_subject:
        return subject
    display = AUTOCOMPLETE_DISPLAY_SUBJECTS.get(normalized_subject)
    if display:
        return display
    clean = " ".join(str(subject).split())
    return clean[:1].upper() + clean[1:]


AUTOCOMPLETE_SUBJECT_COMPLETIONS = {
    "kim": "kimchi",
    "kimc": "kimchi",
    "kimci": "kimchi",
    "kimch": "kimchi",
    "kimchi ram": "kimchi ramen",
    "kimchi rame": "kimchi ramen",
    "kimchi ramen": "kimchi ramen",
    "ramen kim": "kimchi ramen",
    "ramen kimc": "kimchi ramen",
    "ramen kimchi": "kimchi ramen",
    "gochu": "gochujang",
    "goch": "gochujang",
    "gochuang": "gochujang",
    "srir": "sriracha",
    "srira": "sriracha",
    "srirac": "sriracha",
    "kokos": "kokosove mlieko",
    "kokosove": "kokosove mlieko",
    "kokosov": "kokosove mlieko",
    "soj": "sojova omacka",
    "sojo": "sojova omacka",
    "sojov": "sojova omacka",
    "sojova": "sojova omacka",
    "soy": "sojova omacka",
    "pad": "pad thai",
    "padt": "pad thai",
    "padthai": "pad thai",
    "pat": "pad thai",
    "ram": "ramen",
    "rame": "ramen",
    "ramy": "ramen",
    "ramyu": "ramen",
    "pho b": "pho bo",
    "pho bo": "pho bo",
    "sus": "sushi",
    "sush": "sushi",
    "susi": "sushi",
    "mir": "mirin",
    "miri": "mirin",
    "was": "wasabi",
    "wasa": "wasabi",
    "nor": "nori",
    "hois": "hoisin omacka",
    "hoisin": "hoisin omacka",
    "tam": "tamari",
    "tama": "tamari",
    "to": "tofu",
    "tof": "tofu",
}


def complete_autocomplete_subject(subject: str) -> str:
    normalized_subject = normalize(subject).strip()
    if not normalized_subject:
        return subject
    if normalized_subject in AUTOCOMPLETE_SUBJECT_COMPLETIONS:
        return AUTOCOMPLETE_SUBJECT_COMPLETIONS[normalized_subject]

    tokens = normalized_subject.split()
    if not tokens:
        return subject
    last_token = tokens[-1]
    completed = AUTOCOMPLETE_SUBJECT_COMPLETIONS.get(last_token)
    if completed:
        return " ".join(tokens[:-1] + [completed]).strip()
    return subject


def should_skip_autocomplete_product(raw_query_tokens: set[str], product: dict) -> bool:
    text = product_profile_text(product)
    if "shoyu" in raw_query_tokens and any(marker in text for marker in ("krek", "cracker", "snack")):
        return True
    return False


POPULAR_AUTOCOMPLETE_BOOSTS = {
    "kimchi": 16,
    "sushi": 14,
    "ramen": 13,
    "gochujang": 12,
    "sriracha": 11,
    "miso": 10,
    "nori": 9,
    "pho": 9,
    "pad": 8,
    "thai": 8,
    "ryza": 7,
    "rezance": 7,
    "kokosove": 6,
    "sojova": 6,
}


def profile_marker_score(text: str, bucket: dict, marker_map: dict, weight: int) -> int:
    if not isinstance(bucket, dict):
        return 0
    score = 0
    for key, count in bucket.items():
        markers = marker_map.get(key, (key,))
        if any(marker in text for marker in markers):
            score += min(int(count), 5) * weight
    return score


def profile_text_score(text: str, bucket: dict, weight: int, max_weight: int = 5) -> int:
    if not isinstance(bucket, dict):
        return 0
    score = 0
    for key, count in bucket.items():
        normalized_key = normalize(str(key))
        if normalized_key and normalized_key in text:
            score += min(int(count), max_weight) * weight
    return score


def recommendation_group(product: dict) -> str:
    text = normalize(" ".join(str(product.get(key, "")) for key in ("title", "product_type", "category", "description")))
    if any(marker in text for marker in ("korenie", "badian", "skorica", "bujon", "vyvar", "dashi", "bonito")):
        return "Korenie a vývar"
    if any(marker in text for marker in ("ryza", "rezance", "nudle", "papier", "nori")):
        return "Základ"
    if any(marker in text for marker in ("omack", "sauce", "ocot", "mirin", "olej", "miso", "pasta")):
        return "Dochutenie"
    if any(marker in text for marker in ("chili", "cili", "sriracha", "gochujang", "wasabi", "kimchi")):
        return "Pikantné"
    if any(marker in text for marker in ("kokos", "mlieko", "tofu", "hub", "shiitake", "zazvor", "cesnak")):
        return "Doplnok"
    return "Odporúčané"


def recommendation_reason(product: dict, group: str, intent: str, context: str | None) -> str:
    title = normalize(str(product.get("title", "")))
    context_text = recommendation_context_label(context)
    if intent == "article_products" and context_text:
        return f"Ak vás zaujal článok o {context_text}, toto je priamo súvisiaci produkt."
    if intent == "replacement_products" and context_text:
        return f"Podobná alternatíva k {context_text}; vyberám produkt s podobným použitím, nie doplnok ku kombinácii."
    if intent == "related_products" and context_text:
        return f"K {context_text} sa hodí, keď chcete nákup doplniť o ďalšiu surovinu alebo dochutenie."
    if "bezlepk" in title or "tamari" in title:
        return "Vhodný kandidát pri bezlepkovom výbere; zloženie si overte v detaile produktu."
    if group == "Základ":
        return "Je to jedna zo základných surovín, bez ktorej sa dané jedlo pripravuje ťažšie."
    if group == "Korenie a vývar":
        return "Pomáha postaviť chuť vývaru a dodá jedlu typickú vôňu."
    if group == "Dochutenie":
        return "Doladí slanosť, kyslosť alebo umami, takže jedlo nebude chutiť plocho."
    if group == "Pikantné":
        return "Pridá pikantnosť alebo fermentovanú chuť, ak chcete výraznejší výsledok."
    return "Je to praktický doplnok, ktorý sa pri tejto kuchyni často zíde."


def recommendation_context_label(context: str | None) -> str:
    raw_context = str(context or "").strip()
    if not raw_context:
        return ""
    labels = {
        "kimchi_article": "kimchi",
        "pho_article": "pho",
        "udon_article": "udon rezancoch",
        "ramen_article": "ramene",
        "udon_ramen_article": "udon a ramen rezancoch",
        "tofu_article": "tofu",
        "shoyu_article": "shoyu",
        "tamari_article": "tamari",
        "miso_article": "miso paste",
        "matcha_article": "matcha",
        "mochi_article": "mochi",
        "bubble_tea_article": "bubble tea",
    }
    return labels.get(raw_context, raw_context.replace("_", " "))


def cart_candidates_for_response(matches: list[dict], intent: str, context: str | None = None) -> list[dict]:
    if intent not in {"related_products", "replacement_products", "product_search", "recipe_to_products", "article_products", "product_advice"}:
        return []
    reason = f"Odporúčanie Foodland Mei: {str(context or intent).replace('_', ' ')[:80]}"
    candidates = products_to_cart_candidates(matches or [], reason)
    for candidate, product in zip(candidates, matches or []):
        candidate["recommendation_group"] = product.get("recommendation_group", "Odporúčané")
        candidate["recommendation_reason"] = product.get("recommendation_reason", reason)
        candidate["priority"] = product.get("recommendation_priority", 0)
    return candidates


def wants_shopping_list(message: str) -> bool:
    normalized_message = normalize(message)
    return any(marker in normalized_message for marker in SHOPPING_LIST_MARKERS)


def missing_ingredients_for_subject(subject: str | None, recipes: list[dict] | None = None) -> list[str]:
    subjects: list[str] = []
    if subject:
        subjects.append(str(subject))
    for recipe in recipes or []:
        recipe_subject = recipe_product_subject_from_title(str(recipe.get("title") or ""))
        if recipe_subject:
            subjects.append(recipe_subject)

    seen: set[str] = set()
    missing: list[str] = []
    for item_subject in subjects:
        for ingredient in MISSING_INGREDIENTS_BY_SUBJECT.get(item_subject, []):
            key = normalize(ingredient)
            if key and key not in seen:
                seen.add(key)
                missing.append(ingredient)
    return missing[:8]


def sushi_shopping_core_products(products: list[Product], existing_matches: list[dict], limit: int) -> list[dict]:
    queries = ["sushi ryza", "ryzovy ocot", "wasabi", "nori", "nakladany zazvor", "sojova omacka"]
    seen: set[str] = set()
    recommendations: list[dict] = []

    def add_product(product: dict) -> None:
        key = product.get("id") or product.get("link") or product.get("title")
        if not key or key in seen:
            return
        seen.add(key)
        recommendations.append(product)

    for query in queries:
        for product in cached_search_products(products, query, 5):
            title = normalize(product.get("title", ""))
            if query == "sushi ryza" and not ("ryza" in title and {"sushi", "susi"} & set(title.split())):
                continue
            add_product(product)
            break
        if len(recommendations) >= limit:
            return recommendations[:limit]

    for product in existing_matches or []:
        add_product(product)
        if len(recommendations) >= limit:
            break

    return recommendations[:limit]


def tom_yum_shopping_core_products(products: list[Product], existing_matches: list[dict], limit: int) -> list[dict]:
    queries = [
        ("citronova trava", ("citronova trava",), ()),
        ("galangal", ("galangal",), ()),
        ("kaffirove listy", ("kaffir", "kaffirov"), ("bambus", "kari list", "caj")),
        ("rybacia omacka", ("rybacia omacka",), ()),
        ("kokosove mlieko", ("kokosove mlieko",), ()),
        ("tom yum pasta", ("tom yum", "pasta"), ("arasid", "riasy", "instant", "polievka v kelimku")),
    ]
    seen: set[str] = set()
    recommendations: list[dict] = []

    def add_product(product: dict) -> None:
        key = product.get("id") or product.get("link") or product.get("title")
        if not key or key in seen:
            return
        seen.add(key)
        recommendations.append(product)

    for query, required_terms, excluded_terms in queries:
        for product in cached_search_products(products, query, 8):
            title = normalize(product.get("title", ""))
            if any(term in title for term in excluded_terms):
                continue
            if not all(term in title for term in required_terms):
                continue
            add_product(product)
            break
        if len(recommendations) >= limit:
            return recommendations[:limit]

    for product in existing_matches or []:
        title = normalize(product.get("title", ""))
        if any(term in title for term in ("sojova omacka", "sriracha")):
            continue
        add_product(product)
        if len(recommendations) >= limit:
            break

    return recommendations[:limit]


def kimchi_ramen_shopping_core_products(products: list[Product], existing_matches: list[dict], limit: int) -> list[dict]:
    queries = [
        ("ramen rezance", ("ramen",), ()),
        ("kimchi", ("kimchi",), ("instant", "ramen", "ramyun", "rezance", "polievk", "omack")),
        ("gochujang", ("gochujang",), ()),
        ("miso pasta", ("miso",), ()),
        ("sojova omacka", ("sojova omacka",), ()),
        ("dashi", ("dashi",), ()),
        ("wakame", ("wakame",), ()),
        ("nori", ("nori",), ()),
    ]
    seen: set[str] = set()
    recommendations: list[dict] = []

    def add_product(product: dict) -> None:
        key = product.get("id") or product.get("link") or product.get("title")
        if not key or key in seen:
            return
        seen.add(key)
        recommendations.append(product)

    for query, required_terms, excluded_terms in queries:
        for product in cached_search_products(products, query, 8):
            title = normalize(product.get("title", ""))
            if any(term in title for term in excluded_terms):
                continue
            if not all(term in title for term in required_terms):
                continue
            add_product(product)
            break
        if len(recommendations) >= limit:
            return recommendations[:limit]

    for product in existing_matches or []:
        title = normalize(product.get("title", ""))
        if "kimchi" in title and any(term in title for term in ("instant", "ramen", "ramyun", "rezance", "polievk")):
            continue
        add_product(product)
        if len(recommendations) >= limit:
            break

    return recommendations[:limit]


def product_field(product: Product | dict, key: str, default: str = "") -> str:
    if isinstance(product, dict):
        return str(product.get(key, default) or "")
    return str(getattr(product, key, default) or "")


def recipe_core_product_candidates(
    products: list[Product] | list[dict],
    query: str,
    required_terms: tuple[str, ...],
    excluded_terms: tuple[str, ...],
    limit: int = 5,
) -> list[dict]:
    normalized_query = normalize(query)
    query_tokens = raw_tokens(query)
    ranked: list[tuple[int, Product | dict]] = []

    for product in products:
        title = normalize(product_field(product, "title"))
        if any(term in title for term in excluded_terms):
            continue
        if required_terms and not all(term in title for term in required_terms):
            continue

        category = normalize(product_field(product, "product_type", product_field(product, "category")))
        brand = normalize(product_field(product, "brand"))
        haystack = f"{title} {category} {brand}"
        title_tokens = raw_tokens(title)

        score = 0
        if normalized_query and normalized_query in title:
            score += 80
        if required_terms:
            score += 35 * sum(1 for term in required_terms if term in title)
        token_hits = len(query_tokens & title_tokens)
        score += 12 * token_hits
        score += 4 * len(query_tokens & raw_tokens(category))
        score += 3 * len(query_tokens & raw_tokens(brand))
        if not score and query_tokens and query_tokens <= raw_tokens(haystack):
            score += 10
        if not score:
            continue

        availability = product_field(product, "availability")
        if availability in {"in_stock", "in stock", "Skladom", "skladom"}:
            score += 6
        elif availability:
            score -= 2
        ranked.append((score, product))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [format_product(product) for _, product in ranked[:limit]]


def recipe_shopping_core_products(products: list[Product], subject: str | None, existing_matches: list[dict], limit: int) -> list[dict]:
    if not subject or subject not in RECIPE_SHOPPING_CORE_QUERIES:
        return existing_matches

    seen: set[str] = set()
    recommendations: list[dict] = []

    def add_product(product: dict) -> None:
        key = product.get("id") or product.get("link") or product.get("title")
        if not key or key in seen:
            return
        seen.add(key)
        recommendations.append(product)

    for query, required_terms, excluded_terms in RECIPE_SHOPPING_CORE_QUERIES.get(subject, []):
        for product in recipe_core_product_candidates(products, query, required_terms, excluded_terms, 5):
            add_product(product)
            break
        if len(recommendations) >= limit:
            return recommendations[:limit]

    for product in existing_matches or []:
        add_product(product)
        if len(recommendations) >= limit:
            break

    return recommendations[:limit]


def shopping_list_for_response(cart_candidates: list[dict], missing_ingredients: list[str]) -> dict:
    return {
        "available_on_foodland": cart_candidates or [],
        "missing_ingredients": missing_ingredients or [],
    }


def shopping_list_answer(subject: str | None, matches: list[dict], missing_ingredients: list[str], lang: str = "sk") -> str:
    subject_text = str(subject or "recept").replace("_", " ").strip()
    product_count = min(len(matches or []), 8)
    missing_count = len(missing_ingredients or [])
    if lang == "en":
        subject_text_en = readable_subject_label_en(subject) if subject else "this recipe"
        if product_count and missing_count:
            return (
                f"I put together a shopping list for {subject_text_en}: {product_count} items are on Foodland.sk, "
                f"and {missing_count} fresh or extra ingredients you'll need to get elsewhere."
            )
        if product_count:
            return f"I put together a shopping list for {subject_text_en}; the Foodland.sk items below are ready to add to your cart."
        return f"I couldn't find suitable products for {subject_text_en} on Foodland.sk, but the ingredients you'll need are listed below."
    if product_count and missing_count:
        return (
            f"Pripravila som nákupný zoznam pre {subject_text}: {product_count} položiek nájdete na Foodland.sk "
            f"a {missing_count} čerstvých alebo doplnkových surovín si doplňte mimo e-shopu."
        )
    if product_count:
        return f"Pripravila som nákupný zoznam pre {subject_text}; položky z Foodland.sk sú nižšie pripravené aj ako kandidáti do košíka."
    return f"Pri {subject_text} som nenašla vhodné produkty z Foodland.sk, ale nižšie uvádzam suroviny, ktoré treba doplniť."


def enforce_rate_limit(client_key: str) -> None:
    limit = int(os.getenv("RATE_LIMIT_PER_MINUTE", "12"))
    now = time.time()
    window_start = now - 60

    # BUG-02 fix: batch cleanup expired klientov ak dict presiahne limit
    if len(rate_limit_events) > _RATE_LIMIT_MAX_CLIENTS:
        expired = [k for k, v in rate_limit_events.items() if not v or v[-1] < window_start]
        for k in expired[:1000]:
            del rate_limit_events[k]
        if expired:
            logger.info("Rate limit cleanup: removed %d expired client entries.", len(expired[:1000]))

    events = rate_limit_events[client_key]

    while events and events[0] < window_start:
        events.popleft()

    if len(events) >= limit:
        logger.warning("Rate limit exceeded.")
        raise HTTPException(
            status_code=429,
            detail="Príliš veľa otázok za krátky čas. Skúste to prosím o chvíľu.",
        )

    events.append(now)


def enforce_event_rate_limit(client_key: str) -> None:
    limit = int(os.getenv("EVENTS_RATE_LIMIT_PER_MINUTE", "120"))
    now = time.time()
    window_start = now - 60

    if len(event_rate_limit_events) > _RATE_LIMIT_MAX_CLIENTS:
        expired = [k for k, v in event_rate_limit_events.items() if not v or v[-1] < window_start]
        for k in expired[:1000]:
            del event_rate_limit_events[k]

    events = event_rate_limit_events[client_key]

    while events and events[0] < window_start:
        events.popleft()

    if len(events) >= limit:
        raise HTTPException(
            status_code=429,
            detail="Priliš veľa eventov za krátky čas.",
        )

    events.append(now)


def enforce_autocomplete_rate_limit(client_key: str) -> None:
    limit = int(os.getenv("AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE", "180"))
    now = time.time()
    window_start = now - 60

    if len(autocomplete_rate_limit_events) > _RATE_LIMIT_MAX_CLIENTS:
        expired = [k for k, v in autocomplete_rate_limit_events.items() if not v or v[-1] < window_start]
        for k in expired[:1000]:
            del autocomplete_rate_limit_events[k]

    events = autocomplete_rate_limit_events[client_key]

    while events and events[0] < window_start:
        events.popleft()

    if len(events) >= limit:
        raise HTTPException(
            status_code=429,
            detail="Priliš veľa autocomplete požiadaviek za krátky čas.",
        )

    events.append(now)


def enforce_recommend_rate_limit(client_key: str) -> None:
    limit = int(os.getenv("RECOMMEND_RATE_LIMIT_PER_MINUTE", "60"))
    now = time.time()
    window_start = now - 60

    if len(recommend_rate_limit_events) > _RATE_LIMIT_MAX_CLIENTS:
        expired = [k for k, v in recommend_rate_limit_events.items() if not v or v[-1] < window_start]
        for k in expired[:1000]:
            del recommend_rate_limit_events[k]

    events = recommend_rate_limit_events[client_key]

    while events and events[0] < window_start:
        events.popleft()

    if len(events) >= limit:
        raise HTTPException(
            status_code=429,
            detail="Priliš veľa odporúčaní za krátky čas.",
        )

    events.append(now)


def enforce_semantic_search_rate_limit(client_key: str) -> None:
    limit = int(os.getenv("SEMANTIC_SEARCH_RATE_LIMIT_PER_MINUTE", "20"))
    now = time.time()
    window_start = now - 60

    if len(semantic_search_rate_limit_events) > _RATE_LIMIT_MAX_CLIENTS:
        expired = [k for k, v in semantic_search_rate_limit_events.items() if not v or v[-1] < window_start]
        for k in expired[:1000]:
            del semantic_search_rate_limit_events[k]

    events = semantic_search_rate_limit_events[client_key]

    while events and events[0] < window_start:
        events.popleft()

    if len(events) >= limit:
        raise HTTPException(
            status_code=429,
            detail="Priliš veľa sémantických vyhľadávaní za krátky čas.",
        )

    events.append(now)


def log_question(
    message: str,
    client_key: str,
    matches_count: int,
    intent: str = "",
    session_id: str = "",
    primary_intent: str = "",
    subject: str = "",
    interaction_id: str = "",
) -> None:
    path = Path(os.getenv("ANALYTICS_LOG_PATH", str(DEFAULT_RUNTIME_LOG_DIR / "question_analytics.jsonl")))
    salt = os.getenv("ANALYTICS_SALT", "")
    record = {
        "ts": int(time.time()),
        "client_hash": hashlib.sha256(f"{salt}:{client_key}".encode("utf-8")).hexdigest()[:24],
        "message": redact_pii(message)[:1000],
        "matches_count": matches_count,
        "intent": intent,
        "session_id": session_id,
        # V2.1: canonical CustomerIntent fields, additive and optional so
        # existing readers of this JSONL file are unaffected.
        "primary_intent": primary_intent,
        "subject": subject,
        # V2.15b: opaque per-/chat-request correlation id, additive and
        # optional (empty string default) for the same backward-
        # compatibility reason as primary_intent/subject above.
        "interaction_id": interaction_id,
    }
    if os.getenv("ANALYTICS_INCLUDE_IP", "false").lower() == "true":
        record["ip"] = client_key
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error("Failed to log question: %s", exc, exc_info=True)


def log_taxonomy_shadow(message: str, client_key: str, match) -> None:
    # V2 catalog-first taxonomy, Stage A (shadow/observation mode -
    # see docs/product-taxonomy-audit.md). Logs the rice-family
    # classification for later comparison against legacy routing;
    # does not affect routing, products, or answer text in any way.
    if match.subfamily is None:
        return
    path = Path(os.getenv("TAXONOMY_SHADOW_LOG_PATH", str(DEFAULT_RUNTIME_LOG_DIR / "taxonomy_shadow.jsonl")))
    salt = os.getenv("ANALYTICS_SALT", "")
    record = {
        "ts": int(time.time()),
        "client_hash": hashlib.sha256(f"{salt}:{client_key}".encode("utf-8")).hexdigest()[:24],
        "message": redact_pii(message)[:500],
        "family": match.family,
        "subfamily": match.subfamily,
        "confidence": match.confidence,
        "matched_phrase": match.matched_phrase,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error("Failed to log taxonomy shadow: %s", exc, exc_info=True)


def log_backend_error(event: str, detail: str) -> None:
    path = Path(os.getenv("ERROR_LOG_PATH", str(DEFAULT_RUNTIME_LOG_DIR / "backend_errors.jsonl")))
    record = {
        "ts": int(time.time()),
        "event": event,
        "detail": detail[:1000],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error("Failed to log backend error: %s", exc, exc_info=True)


def log_event(event_request: EventRequest, client_key: str, execution_context: _ExecutionContext | None = None) -> None:
    # V2.15d.3 - EVALUATION/LEARNING/SHADOW never reach this function
    # from the real /events HTTP route (that route only ever resolves
    # CUSTOMER or ADMIN_TEST), but internal callers could in principle
    # pass one, so this stays honestly gated the same way
    # log_recommendation_decision()'s should_log_decision already is:
    # never durably logged for EVALUATION/LEARNING/SHADOW.
    if execution_context is not None and execution_context.mode.value not in ("CUSTOMER", "ADMIN_TEST"):
        return
    path = Path(os.getenv("EVENTS_LOG_PATH", str(DEFAULT_RUNTIME_LOG_DIR / "events.jsonl")))
    salt = os.getenv("ANALYTICS_SALT", "")
    record = {
        "ts": int(time.time()),
        "client_hash": hashlib.sha256(f"{salt}:{client_key}".encode("utf-8")).hexdigest()[:24],
        "session_id": event_request.session_id[:64],
        "event_type": event_request.event_type,
        "query": redact_pii(event_request.query or "")[:300] or None,
        "product_sku": event_request.product_sku,
        "product_skus": event_request.product_skus[:50] if event_request.product_skus else None,
        "position": event_request.position,
        "rating": event_request.rating,
        # V2.15d: additive, optional - None for every pre-V2.15d
        # event and for every current app/widget.js submission (it
        # does not populate these yet, see EventRequest above).
        "interaction_id": event_request.interaction_id,
        "decision_id": event_request.decision_id,
        "event_id": event_request.event_id,
        # V2.15e.1: additive, optional - None for every event that never
        # involved a ResultSet (e.g. comparison/use_case_advice/
        # basket_completion never create one) and for every pre-V2.15e.1
        # app/widget.js submission (it did not populate this yet).
        "result_set_id": event_request.result_set_id,
        # V2.15d.3 (docs/event-execution-context-isolation-v2.15d.3.md)
        # - server-RESOLVED context (never trusts a client-supplied
        # field directly), so a synthetic/admin verification event can
        # never be mistaken for genuine customer behavior by any
        # downstream reader that checks this field. None/missing means
        # the record predates this mechanism (V2.15d.2 and earlier) -
        # downstream readers treat that the same as CUSTOMER, since
        # /events had no non-customer path at all before this sprint.
        "execution_context": execution_context.mode.value if execution_context is not None else None,
        "learning_eligible": execution_context.is_customer_traffic if execution_context is not None else True,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error("Failed to log event: %s", exc, exc_info=True)


def log_recommendation_decision(
    *,
    interaction_id: str,
    decision_id: str,
    decision_type: str,
    workflow_id: str,
    intent: str,
    session_id: str,
    client_key: str,
    use_case: str | None,
    state: str | None,
    candidate_product_ids: list,
    recommended_product_ids: list,
    reason_codes: list,
    confidence: str | None,
    learning_eligible: bool,
) -> None:
    """V2.15d (docs/recommendation-conversion-correlation-v2.15d.md) -
    durable, session-safe log of a recommendation DECISION object
    (comparison/use_case_advice/basket_completion), correlating
    interaction_id + decision_id + candidate/recommended product ids +
    reason_codes/confidence with the execution context that produced
    it. This is a SEPARATE stream from question_analytics.jsonl (which
    stays customer-only, unchanged) - callers here also log for
    ADMIN_TEST traffic (should_log_decision gate in app.workflow_executor)
    so a live production smoke test can be read back durably, but every
    record is explicitly tagged with learning_eligible=False unless the
    traffic was genuine CUSTOMER traffic - no event becomes a training
    label merely by existing here (Section 32 of the closure spec).
    This function NEVER interprets clicks/impressions/reformulation as
    preference - it only records the decision object itself, which is
    already fully computed and returned to the customer by the time
    this is called. Best-effort: any failure here is caught and must
    never break the customer-facing response (Section 44/45)."""
    try:
        path = _resolve_storage_path("RECOMMENDATION_DECISIONS_LOG_PATH", "recommendation_decisions.jsonl")
        salt = os.getenv("ANALYTICS_SALT", "")
        record = {
            "ts": int(time.time()),
            "interaction_id": interaction_id or "",
            "decision_id": decision_id,
            "decision_type": decision_type,
            "workflow_id": workflow_id,
            "intent": intent,
            "session_id": session_id,
            "client_hash": hashlib.sha256(f"{salt}:{client_key}".encode("utf-8")).hexdigest()[:24],
            "use_case": use_case,
            "state": state,
            "candidate_product_ids": list(candidate_product_ids or [])[:50],
            "recommended_product_ids": list(recommended_product_ids or [])[:50],
            "reason_codes": list(reason_codes or [])[:20],
            "confidence": confidence,
            "learning_eligible": learning_eligible,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error("Failed to log recommendation decision: %s", exc, exc_info=True)




def read_analytics_events(days: int = 7) -> list[dict]:
    path = Path(os.getenv("ANALYTICS_LOG_PATH", str(DEFAULT_RUNTIME_LOG_DIR / "question_analytics.jsonl")))
    return read_jsonl_events(path, days)


def read_error_events(days: int = 7) -> list[dict]:
    path = Path(os.getenv("ERROR_LOG_PATH", str(DEFAULT_RUNTIME_LOG_DIR / "backend_errors.jsonl")))
    return read_jsonl_events(path, days)


def read_engagement_events(days: int = 7) -> list[dict]:
    path = Path(os.getenv("EVENTS_LOG_PATH", str(DEFAULT_RUNTIME_LOG_DIR / "events.jsonl")))
    return read_jsonl_events(path, days)


def events_summary(events: list[dict]) -> dict:
    events_by_type: Counter[str] = Counter()
    sessions: set[str] = set()
    product_touches: Counter[str] = Counter()
    timestamps: list[int] = []

    for event in events:
        event_type = event.get("event_type")
        if event_type:
            events_by_type[event_type] += 1

        session_id = event.get("session_id")
        if session_id:
            sessions.add(session_id)

        sku = event.get("product_sku")
        if sku:
            product_touches[sku] += 1
        for batch_sku in event.get("product_skus") or []:
            product_touches[batch_sku] += 1

        ts = event.get("ts")
        if ts:
            timestamps.append(int(ts))

    return {
        "total_events": len(events),
        "events_by_type": dict(events_by_type),
        "unique_sessions": len(sessions),
        "unique_products_touched": len(product_touches),
        "top_products_by_touches": [
            {"product_sku": sku, "touches": count} for sku, count in product_touches.most_common(10)
        ],
        "earliest_ts": min(timestamps) if timestamps else None,
        "latest_ts": max(timestamps) if timestamps else None,
    }


def read_jsonl_events(path: Path, days: int = 7) -> list[dict]:
    if not path.exists():
        return []
    now = int(time.time())
    safe_days = max(1, min(int(days or 7), 90))
    since = now - safe_days * 86400
    events: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = int(record.get("ts", 0) or 0)
                if ts >= since:
                    events.append(record)
    except Exception as exc:
        logger.error("Failed to read analytics log %s: %s", path, exc, exc_info=True)
    return events


def analytics_report(events: list[dict], errors: list[dict] | None = None, limit: int = 10) -> dict:
    errors = errors or []
    safe_limit = max(1, min(int(limit or 10), 100))
    no_results = [event for event in events if is_no_result_event(event)]
    unknowns = [event for event in events if event.get("intent") == "unknown"]
    return {
        "summary": {
            "questions": len(events),
            "unique_clients": len({event.get("client_hash") for event in events if event.get("client_hash")}),
            "sessions": len({event.get("session_id") for event in events if event.get("session_id")}),
            "no_result_questions": len(no_results),
            "unknown_questions": len(unknowns),
            "backend_errors": len(errors),
        },
        "top_questions": top_question_rows(events, safe_limit),
        "no_results": no_result_rows(events, safe_limit),
        "intents": intent_rows(events),
        "weak_spots": weak_spot_rows(events, errors, safe_limit),
        "action_items": analytics_action_items(events, errors, safe_limit),
    }


def normalized_question_key(message: str) -> str:
    cleaned = normalize(message)
    cleaned = re.sub(r"\b\d+[,.]?\d*\s*(g|kg|ml|l|ks)\b", " ", cleaned)
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", cleaned)
    return " ".join(cleaned.split())[:160]


def top_question_rows(events: list[dict], limit: int = 20) -> list[dict]:
    counter: Counter[str] = Counter()
    examples: dict[str, str] = {}
    for event in events:
        message = str(event.get("message", "")).strip()
        key = normalized_question_key(message)
        if not key:
            continue
        counter[key] += 1
        examples.setdefault(key, message[:240])
    return [
        {"question": examples[key], "normalized": key, "count": count}
        for key, count in counter.most_common(max(1, min(limit, 100)))
    ]


def cached_top_questions(limit: int = 50) -> list[dict]:
    """Top questions barely change minute to minute, so re-scan the analytics
    log at most once per TOP_QUESTIONS_CACHE_SECONDS instead of on every
    /autocomplete keystroke."""
    global _top_questions_cache, _top_questions_cache_at
    now = time.time()
    if now - _top_questions_cache_at > TOP_QUESTIONS_CACHE_SECONDS:
        events = read_analytics_events(7)
        _top_questions_cache = top_question_rows(events, limit)
        _top_questions_cache_at = now
    return _top_questions_cache


def public_suggested_question_rows(events: list[dict], limit: int = 5, min_count: int = 2) -> list[dict]:
    safe_limit = max(1, min(int(limit or 5), 8))
    safe_min_count = max(1, min(int(min_count or 2), 20))
    # Never suggest a question that is itself tracked as a no-result in
    # this same window - e.g. "Ma kostky?" is only meaningful as a
    # follow-up right after a specific product was discussed, so it is
    # frequent AND a frequent no-result at once. Deriving this from the
    # no-result log (rather than a hardcoded phrase list) means any future
    # question with the same context-dependent shape is excluded
    # automatically, with no code change needed.
    no_result_keys = {
        normalized_question_key(str(event.get("message", "")))
        for event in events
        if is_no_result_event(event)
    }
    rows = []
    for row in top_question_rows(events, 50):
        if row.get("normalized") in no_result_keys:
            continue
        question = clean_public_suggested_question(str(row.get("question") or ""))
        if not question or int(row.get("count", 0) or 0) < safe_min_count:
            continue
        rows.append(
            {
                "question": question,
                "count": int(row.get("count", 0) or 0),
            }
        )
        if len(rows) >= safe_limit:
            break
    return rows


def clean_public_suggested_question(question: str) -> str:
    text = " ".join(str(question or "").split())
    if not text:
        return ""
    text = text[:90].strip()
    if len(text) < 4:
        return ""
    if re.search(r"[@<>]|https?://|www\.|\b\d{6,}\b", text, re.IGNORECASE):
        return ""
    if not text.endswith("?") and any(text.lower().startswith(prefix) for prefix in ("co ", "čo ", "ako ", "cim ", "čim ", "čím ", "recept", "mate ", "máte ", "naj")):
        text = f"{text}?"
    return text


def no_result_rows(events: list[dict], limit: int = 20) -> list[dict]:
    no_result_events = [event for event in events if is_no_result_event(event)]
    counter: Counter[str] = Counter()
    examples: dict[str, dict] = {}
    for event in no_result_events:
        message = str(event.get("message", "")).strip()
        key = normalized_question_key(message)
        if not key:
            continue
        counter[key] += 1
        examples.setdefault(
            key,
            {
                "question": message[:240],
                "intent": event.get("intent", ""),
                "last_seen": event.get("ts", 0),
            },
        )
        examples[key]["last_seen"] = max(int(examples[key].get("last_seen", 0) or 0), int(event.get("ts", 0) or 0))
    return [
        {"normalized": key, "count": count, **examples[key]}
        for key, count in counter.most_common(max(1, min(limit, 100)))
    ]


def intent_rows(events: list[dict]) -> list[dict]:
    counts = Counter(str(event.get("intent") or "unknown") for event in events)
    total = sum(counts.values()) or 1
    return [
        {"intent": intent, "count": count, "share": round(count / total, 4)}
        for intent, count in counts.most_common()
    ]


def weak_spot_rows(events: list[dict], errors: list[dict] | None = None, limit: int = 10) -> list[dict]:
    errors = errors or []
    rows: list[dict] = []
    no_result_count = sum(1 for event in events if is_no_result_event(event))
    unknown_count = sum(1 for event in events if event.get("intent") == "unknown")
    if no_result_count:
        rows.append({"area": "no_results", "count": no_result_count, "note": "Otázky bez nájdených produktov alebo obsahu."})
    if unknown_count:
        rows.append({"area": "unknown_intent", "count": unknown_count, "note": "Otázky mimo rozpoznaných Foodland tém."})
    for intent, count in Counter(str(event.get("intent") or "unknown") for event in events if is_no_result_event(event)).most_common():
        rows.append({"area": f"no_results:{intent}", "count": count, "note": "Intent často končí bez produktovej zhody."})
    for event_name, count in Counter(str(error.get("event") or "backend_error") for error in errors).most_common():
        rows.append({"area": f"backend:{event_name}", "count": count, "note": "Backend chyba v sledovanom období."})
    rows.sort(key=lambda row: row["count"], reverse=True)
    return rows[: max(1, min(limit, 100))]


def analytics_action_items(events: list[dict], errors: list[dict] | None = None, limit: int = 20) -> list[dict]:
    errors = errors or []
    safe_limit = max(1, min(int(limit or 20), 100))
    items: list[dict] = []

    for row in no_result_rows(events, safe_limit):
        items.append(
            {
                "priority": 100 + int(row.get("count", 0) or 0),
                "type": "missing_result",
                "title": f"Doplniť výsledok pre: {row.get('question', row.get('normalized', ''))}",
                "question": row.get("question", ""),
                "normalized": row.get("normalized", ""),
                "intent": row.get("intent", ""),
                "count": row.get("count", 0),
                "suggested_action": suggested_analytics_action(str(row.get("intent", "")), str(row.get("normalized", "")), "missing_result"),
            }
        )

    for row in low_relevance_rows(events, safe_limit):
        items.append(
            {
                "priority": 80 + int(row.get("count", 0) or 0),
                "type": "low_relevance",
                "title": f"Skontrolovať slabé výsledky pre: {row.get('question', row.get('normalized', ''))}",
                "question": row.get("question", ""),
                "normalized": row.get("normalized", ""),
                "intent": row.get("intent", ""),
                "count": row.get("count", 0),
                "avg_matches": row.get("avg_matches", 0),
                "suggested_action": suggested_analytics_action(str(row.get("intent", "")), str(row.get("normalized", "")), "low_relevance"),
            }
        )

    for row in top_question_rows(events, safe_limit):
        if int(row.get("count", 0) or 0) < 2:
            continue
        items.append(
            {
                "priority": 45 + int(row.get("count", 0) or 0),
                "type": "frequent_question",
                "title": f"Optimalizovať častú otázku: {row.get('question', '')}",
                "question": row.get("question", ""),
                "normalized": row.get("normalized", ""),
                "count": row.get("count", 0),
                "suggested_action": suggested_analytics_action("", str(row.get("normalized", "")), "frequent_question"),
            }
        )

    weak_intents = [
        row for row in weak_spot_rows(events, errors, safe_limit)
        if str(row.get("area", "")).startswith(("no_results:", "unknown_intent", "backend:"))
    ]
    for row in weak_intents:
        items.append(
            {
                "priority": 70 + int(row.get("count", 0) or 0),
                "type": "weak_area",
                "title": f"Slabé miesto: {row.get('area', '')}",
                "area": row.get("area", ""),
                "count": row.get("count", 0),
                "suggested_action": row.get("note", "Skontrolovať pravidlá poradkyne a doplniť test."),
            }
        )

    deduped: dict[tuple[str, str], dict] = {}
    for item in items:
        key = (str(item.get("type", "")), str(item.get("normalized") or item.get("area") or item.get("title", "")))
        existing = deduped.get(key)
        if not existing or int(item.get("priority", 0)) > int(existing.get("priority", 0)):
            deduped[key] = item

    ordered = sorted(deduped.values(), key=lambda item: int(item.get("priority", 0)), reverse=True)
    return [
        {key: value for key, value in item.items() if key != "priority" and value not in ("", None)}
        for item in ordered[:safe_limit]
    ]


def low_relevance_rows(events: list[dict], limit: int = 20) -> list[dict]:
    product_intents = {"product_search", "related_products", "replacement_products", "article_products", "product_advice", "recipe_to_products", "allergen_safety"}
    grouped: dict[str, dict] = {}
    for event in events:
        intent = str(event.get("intent") or "")
        matches_count = int(event.get("matches_count", 0) or 0)
        if intent not in product_intents or matches_count == 0 or matches_count > 2:
            continue
        message = str(event.get("message", "")).strip()
        key = normalized_question_key(message)
        if not key:
            continue
        row = grouped.setdefault(
            key,
            {"question": message[:240], "normalized": key, "intent": intent, "count": 0, "matches_total": 0},
        )
        row["count"] += 1
        row["matches_total"] += matches_count
    rows = []
    for row in grouped.values():
        count = int(row.get("count", 0) or 0)
        if not count:
            continue
        rows.append(
            {
                "question": row["question"],
                "normalized": row["normalized"],
                "intent": row["intent"],
                "count": count,
                "avg_matches": round(float(row.get("matches_total", 0)) / count, 2),
            }
        )
    rows.sort(key=lambda item: (int(item["count"]), -float(item["avg_matches"])), reverse=True)
    return rows[: max(1, min(limit, 100))]


def suggested_analytics_action(intent: str, normalized_question: str, issue_type: str) -> str:
    text = normalize(normalized_question)
    if issue_type == "frequent_question":
        return "Pridať alebo zlepšiť rýchlu odpoveď, synonymá a regresný test pre častý dotaz."
    if intent == "recipe" or any(token in text for token in ("recept", "varit", "pho", "ramen", "pad thai", "kimchi")):
        return "Doplniť receptové mapovanie, suroviny k receptu a test očakávaných produktov."
    if intent == "unknown":
        return "Rozšíriť intent detekciu alebo pridať odmietaciu odpoveď, ak je dotaz mimo Foodland sortimentu."
    if any(token in text for token in ("nahrad", "namiesto", "alternativ")):
        return "Doplniť pravidlá náhrad a synonymá pre alternatívne ingrediencie."
    if any(token in text for token in ("co je", "vysvetli", "pouzitie", "rozdiel")):
        return "Prepojiť magazínový článok s presnejšími produktmi a pridať test relevancie."
    return "Doplniť synonymá, produktové boost pravidlo alebo kategóriu a pridať regresný test."


def is_no_result_event(event: dict) -> bool:
    intent = str(event.get("intent") or "")
    # allergen_safety deliberately returns products=[] for a general
    # allergy question with no specific product named (Section audit,
    # regbug_rt0027 - critical golden case, never show product cards for
    # an unverified allergen match). The substantive answer lives in
    # `answer` text (a safety disclaimer), not in a product list, so
    # matches_count==0 there does not mean the customer got nothing
    # useful - counting it as a no-result event here would misrepresent
    # what actually happened (found via a real production analytics audit).
    product_intents = {"product_search", "related_products", "replacement_products", "article_products", "product_advice", "recipe_to_products"}
    return intent in product_intents and int(event.get("matches_count", 0) or 0) == 0


def is_faq_intent(message: str) -> bool:
    normalized_message = normalize(message)
    return any(marker in normalized_message for marker in FAQ_INTENT_MARKERS)


_ADDRESS_PATTERN = re.compile(
    r"((?:[A-ZÁ\u00C4ČĎÉÍ\u0139ĽŇÓÔŔŠŤÚÝŽ][\wáäčďéíĺľňóôŕšťúýž]*\s){1,3}\d+(?:/\d+)?[a-zA-Z]?,\s*\d{3}\s?\d{2}\s+"
    r"[A-ZÁ\u00C4ČĎÉÍ\u0139ĽŇÓÔŔŠŤÚÝŽ][\wáäčďéíĺľňóôŕšťúýž]+)"
)


# V2.15d.3 (docs/event-execution-context-isolation-v2.15d.3.md,
# STORE_LOCATION canonical data closure subtask) - authoritative,
# product-owner-supplied Foodland store address and Google Maps
# destination. Preferred over a generated maps.google.com/search url
# whenever the extracted address matches this exact canonical address
# - the generated search-url fallback remains for any OTHER address
# text this function might ever be asked to build a link for.
_FOODLAND_CANONICAL_ADDRESS = "Stara Vajnorska 3308/19, 831 04 Bratislava"
_FOODLAND_CANONICAL_MAPS_URL = "https://maps.app.goo.gl/3tFJ4P6w2pj88xAP8"


def _build_maps_link_from_faq_answer(answer_text: str) -> str | None:
    """V2.15c (rt0014, closure spec Section 16) - constructs a Google
    Maps link from a real, already-grounded street address substring
    extracted directly from the FAQ answer text itself (data/
    knowledge.json), so a link is never generated for an FAQ answer
    that has no address in it. Returns the authoritative canonical
    Foodland Google Maps URL (V2.15d.3) when the extracted address is
    the Foodland store's own address; otherwise falls back to a
    generated Maps SEARCH url (never a fabricated place ID/coordinate/
    route) that always reflects whatever the knowledge base currently
    says, rather than a separately hardcoded copy that could drift."""
    match = _ADDRESS_PATTERN.search(answer_text)
    if not match:
        return None
    extracted_address = match.group(1).strip()
    if normalize(extracted_address) == normalize(_FOODLAND_CANONICAL_ADDRESS):
        return _FOODLAND_CANONICAL_MAPS_URL
    return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(extracted_address)


FAQ_CATEGORY_MARKERS = {
    "doprava": ("doprava", "doruc", "kurier", "packeta", "dpd", "gls", "postovn", "vyzdvih"),
    "platby": ("plat", "zapl", "kart", "hotov", "dobier", "paypal", "gopay", "prevod"),
    "reklamacie": ("reklamac", "poskoden", "chyb", "vymen", "vratenie penaz"),
    "vratenie tovaru": ("vrat", "odstup", "vymen"),
    "registracia": ("registr", "prihlas", "heslo", "ucet"),
    "vernostny program": ("kredit", "vernost", "zlava", "body", "bod"),
    "nakup": ("objednav", "kosik", "nakup", "skladom"),
}


def best_direct_faq_answer(message: str, loaded_knowledge: dict) -> str | None:
    normalized_message = normalize(message)
    query_tokens = tokenize(message)
    best_score = 0
    best_answer = ""

    # "Kolko treba zaplatit za dopravu?" (how much do I need to pay for
    # delivery) has neither "stoji" nor the exact phrase "cena dopravy" -
    # it fell through to the generic delivery-methods shortcut below
    # instead. Broadened to a flexible "kolko"+"doprav" combination,
    # matching how "zadarmo"+"doprav" already works just below.
    if any(marker in normalized_message for marker in ("postovn", "cena dopravy", "stoji doprava")) or (
        "zadarmo" in normalized_message and "doprav" in normalized_message
    ) or (
        # "kolko" alone is ambiguous between cost ("kolko stoji dorucenie")
        # and duration ("kolko trva dorucenie", handled separately below by
        # the "trva" pairing) - require a cost-specific verb alongside it so
        # this does not also swallow the duration question.
        "kolko" in normalized_message
        and any(marker in normalized_message for marker in ("stoji", "zaplatit", "platit"))
        and any(marker in normalized_message for marker in ("doprav", "postovn", "doruc", "zasiel", "kurier"))
    ):
        shipping_answer = direct_faq_answer_by_question_markers(
            loaded_knowledge,
            required_markers=("doprava", "zadarmo"),
        )
        if shipping_answer:
            return shipping_answer
    # Checked before the delivery-methods shortcut below: "sledov" (track)
    # also matches "zasiel" (shipment), so an order-tracking question like
    # "sledovanie zasielok" would otherwise get the generic "which delivery
    # methods do you offer" answer instead of "where can I track my order".
    if any(marker in normalized_message for marker in ("sledov", "kde je moja objednavka", "stav objednavky")):
        tracking_answer = direct_faq_answer_by_question_markers(
            loaded_knowledge,
            required_markers=("sledovat", "objednavky"),
        )
        if tracking_answer:
            return tracking_answer
    # Checked before the delivery-methods shortcut below: "dobierk" also
    # matches "doruc"/"kurier" there, so a specific cash-on-delivery
    # question would otherwise get the generic "which delivery methods
    # do you offer" answer instead of a direct yes/no about COD.
    if "dobierk" in normalized_message:
        cod_markers = ("dobierkou", "kurierom") if "kurier" in normalized_message else ("domov", "dobierkou")
        cod_answer = direct_faq_answer_by_question_markers(loaded_knowledge, required_markers=cod_markers)
        if cod_answer:
            return cod_answer
    # Same reasoning: "which countries do you ship to" also contains
    # "doruc", so it must be checked before the generic shortcut too.
    if any(marker in normalized_message for marker in ("krajin", "do cr", "do ceska", "do cesko", "do rakuska", "zahranic")):
        countries_answer = direct_faq_answer_by_question_markers(loaded_knowledge, required_markers=("krajin", "dorucuje"))
        if countries_answer:
            return countries_answer
    # And again: "ako dlho trva dorucenie" (how long does delivery take)
    # also contains "doruc", so it was losing to the generic "which
    # delivery methods do you offer" shortcut instead of the specific
    # delivery-time answer.
    # "kolko trva dorucenie" (how much time does delivery take) uses "kolko"
    # instead of "dlho" - only paired with "trva" (takes/lasts) though,
    # since bare "kolko" + "doruc" is ambiguous with a COST question
    # ("kolko stoji dorucenie"), which the shipping-cost shortcut above
    # already owns.
    if "dodan" in normalized_message or (
        (any(marker in normalized_message for marker in ("dlho", "rychlost")) or ("kolko" in normalized_message and "trva" in normalized_message))
        and any(marker in normalized_message for marker in ("doruc", "zasiel", "kurier"))
    ):
        delivery_time_answer = direct_faq_answer_by_question_markers(loaded_knowledge, required_markers=("dlho", "dorucenie"))
        if delivery_time_answer:
            return delivery_time_answer
    # "je osobny odber na pockanie" (is in-store pickup ready-while-you-wait)
    # had no FAQ_INTENT_MARKERS trigger word at all until "pockanie"/"odber"
    # were added, so it fell all the way through to the general AI answer -
    # whose system prompt always appends a cross-sell nudge when any
    # products happen to be attached, even for a pure logistics question.
    if "pockanie" in normalized_message and any(marker in normalized_message for marker in ("odber", "vyzdvih")):
        pickup_ready_answer = direct_faq_answer_by_question_markers(loaded_knowledge, required_markers=("odberom", "pripraveny"))
        if pickup_ready_answer:
            return pickup_ready_answer
    if any(marker in normalized_message for marker in ("kurier", "doruc", "zasiel", "posiel", "preprav", "privez", "rozvaz", "doprav")):
        delivery_answer = direct_faq_answer_by_question_markers(
            loaded_knowledge,
            required_markers=("sposoby", "dorucenia"),
        )
        if delivery_answer:
            return delivery_answer
    if any(marker in normalized_message for marker in ("nevyzdvihol", "nevyzdvihla", "neprevzal", "neprevzala", "no-show", "noshow", "nevyzdvihnem", "neprebral")):
        no_show_answer = direct_faq_answer_by_question_markers(loaded_knowledge, required_markers=("neprevezmem",))
        if no_show_answer:
            return no_show_answer
    if "vratenie" in normalized_message and "penaz" in normalized_message:
        if "dobropis" in normalized_message:
            credit_note_answer = direct_faq_answer_by_question_markers(loaded_knowledge, required_markers=("vratenie", "dobropisu"))
            if credit_note_answer:
                return credit_note_answer
        refund_timing_answer = direct_faq_answer_by_question_markers(loaded_knowledge, required_markers=("vratenie", "odstupeni"))
        if refund_timing_answer:
            return refund_timing_answer
    if "vymen" in normalized_message and any(marker in normalized_message for marker in ("predajn", "obchod")):
        exchange_in_store_answer = direct_faq_answer_by_question_markers(loaded_knowledge, required_markers=("vymenit", "predajni"))
        if exchange_in_store_answer:
            return exchange_in_store_answer
    if any(marker in normalized_message for marker in ("parkovanie", "zaparkovat", "parkovat", "parking")):
        parking_answer = direct_faq_answer_by_question_markers(loaded_knowledge, required_markers=("parkovanie",))
        if parking_answer:
            return parking_answer
    # "typy kariet" / "aky typ kariet prijimate" (which card types do you
    # accept) - "kariet" (cards, genitive plural) contains "kari" (curry)
    # as a substring, so this used to hijack the curry-subject routing
    # and return kari-pasta cross-sell products instead of the payment
    # methods FAQ.
    if "kariet" in normalized_message:
        card_types_answer = direct_faq_answer_by_question_markers(loaded_knowledge, required_markers=("platobne", "metody"))
        if card_types_answer:
            return card_types_answer
    # V2.18d.4 (C3 FAQ retrieval topic mismatch): a bare "how can I pay"
    # question (no in-store/card-specific qualifier) must resolve to the
    # complete payment-methods answer (covers COD/bank transfer/card/
    # etc.), not whichever payment-related FAQ record happens to share
    # the most literal words with the query. The general scoring loop
    # below gives every "plat*"-question the same flat "ako"+"zapl"
    # bonus (no discrimination between them), so a generic query
    # previously lost on raw token overlap to the narrower "can I pay
    # by card in store" record (its question literally contains
    # "zaplatit"). Reuses the SAME canonical "platobne"+"metody" record
    # the "kariet" shortcut above already points to. Guarded on the
    # query NOT mentioning a store qualifier, so an explicit in-store
    # card question (test_faq_sub_question_beats_generic_same_category_
    # answer) still falls through unchanged to the general scoring loop.
    if (
        "ako" in normalized_message
        and "zapl" in normalized_message
        and not any(marker in normalized_message for marker in ("predajn", "obchod"))
    ):
        payment_methods_answer = direct_faq_answer_by_question_markers(
            loaded_knowledge, required_markers=("platobne", "metody")
        )
        if payment_methods_answer:
            return payment_methods_answer
    if "adresa" in normalized_message:
        address_answer = direct_faq_answer_by_question_markers(loaded_knowledge, required_markers=("kamennu", "predajnu"))
        if address_answer:
            return address_answer
    # V2.16a.1 - opening_hours has no standalone FAQ record (hours are
    # only a sub-clause of the store-location answer, per the
    # opening-hours source-of-truth audit); reuses the SAME existing
    # store-location record/shortcut target as the "adresa"/bare
    # "predajn" shortcuts above rather than duplicating the grounded
    # text into a second copy (OH-B: EXTRACT_FROM_EXISTING_AUTHORITATIVE_
    # SOURCE). is_opening_hours_query() is checked here (not folded into
    # a FAQ_INTENT_MARKERS entry) precisely because it is a narrow,
    # multi-signal detector, not a bare unsafe substring.
    if _is_opening_hours_query(message):
        hours_answer = direct_faq_answer_by_question_markers(loaded_knowledge, required_markers=("kamennu", "predajnu"))
        if hours_answer:
            return hours_answer
    # V2.16a.1 - contact: grounded in the existing, business-owner-
    # confirmed phone/email already live in missing_composition_answer()
    # (eshop@foodland.sk, +421 2 4468 1527) - see the dedicated FAQ
    # record added to data/knowledge.json for this closure.
    if _is_contact_query(message):
        contact_answer = direct_faq_answer_by_question_markers(loaded_knowledge, required_markers=("kontaktovat", "telefon"))
        if contact_answer:
            return contact_answer
    if "predajn" in normalized_message and len(tokenize(normalized_message)) <= 2:
        # Only a bare word like "Predajnu" defaults to the general store-info
        # FAQ - a longer sentence mentioning "predajni" (e.g. "can I pay by
        # card in store") has its own specific intent and must fall through
        # to the general scoring loop below instead of being shortcut here.
        store_info_answer = direct_faq_answer_by_question_markers(loaded_knowledge, required_markers=("kamennu", "predajnu"))
        if store_info_answer:
            return store_info_answer
    if "kredit" in normalized_message and any(marker in normalized_message for marker in ("platnost", "dokedy platia", "vyprsia", "vyprsanie", "expiruju")):
        if any(marker in normalized_message for marker in ("upozorn", "davate vediet", "notifikacia")):
            expiry_notice_answer = direct_faq_answer_by_question_markers(loaded_knowledge, required_markers=("upozornite", "vyprsanim"))
            if expiry_notice_answer:
                return expiry_notice_answer
        validity_answer = direct_faq_answer_by_question_markers(loaded_knowledge, required_markers=("platia", "kredity"))
        if validity_answer:
            return validity_answer

    current_category = ""
    for record in loaded_knowledge.get("sections", {}).get("FAQ", []):
        question = first_record_value(record, ("Otázka", "Otazka", "question"))
        answer = first_record_value(record, ("Odpoveď", "Odpoved", "answer"))
        category = first_record_value(record, ("Kategória", "Kategoria", "category"))
        if category:
            current_category = category
        else:
            # Sub-questions in knowledge.json leave Kategória blank and rely on
            # the preceding row's category (visual grouping in the source
            # sheet). Without this fallback those rows never get the
            # FAQ_CATEGORY_MARKERS bonus below, so a generic top-of-group
            # answer (which does carry the category) systematically outranks
            # a more specific sub-question even when the sub-question is the
            # better match (e.g. "card payment in store" losing to "which
            # payment methods do you support" because only the latter has
            # Kategória == "Platby").
            category = current_category
        if not answer:
            continue

        normalized_question = normalize(question)
        normalized_category = normalize(category)
        record_tokens = tokenize(" ".join([category, question, answer]))
        score = len(query_tokens & record_tokens)

        if normalized_question and normalized_question in normalized_message:
            score += 20
        if normalized_category and normalized_category in normalized_message:
            score += 12
        for category_name, markers in FAQ_CATEGORY_MARKERS.items():
            if normalized_category == category_name and any(marker in normalized_message for marker in markers):
                score += 10
        if (
            any(marker in normalized_message for marker in ("kolko", "cena", "stoji", "postovn"))
            and "zadarmo" in normalized_question
            and "doprava" in normalized_question
        ):
            score += 10
        if "ako" in normalized_message and "zapl" in normalized_message and "plat" in normalized_question:
            score += 10

        if score > best_score:
            best_score = score
            best_answer = answer

    return best_answer if best_score >= 3 else None


def direct_faq_answer_by_question_markers(loaded_knowledge: dict, required_markers: tuple[str, ...]) -> str | None:
    for record in loaded_knowledge.get("sections", {}).get("FAQ", []):
        question = first_record_value(record, ("Otázka", "Otazka", "question"))
        normalized_question = normalize(question)
        if all(marker in normalized_question for marker in required_markers):
            answer = first_record_value(record, ("Odpoveď", "Odpoved", "answer"))
            if answer:
                return answer
    return None


def detect_recipe_subject(message: str) -> str | None:
    normalized_message = normalize(message)
    if not is_recipe_intent(normalized_message):
        return None

    title_subject = recipe_product_subject_from_title(normalized_message)
    if title_subject:
        return title_subject

    for subject, aliases in RELATED_SUBJECT_ALIASES.items():
        if any(alias in normalized_message for alias in aliases):
            return subject

    return "general"


def wants_recipe_products(message: str) -> bool:
    normalized_message = normalize(message)
    return any(
        marker in normalized_message
        for marker in (
            "ingredien",
            "surovin",
            "produkt",
            "kupit",
            "nakup",
            "nakupny zoznam",
            "co potrebujem",
            "co treba",
            "co mi chyba",
            "co chyba",
            "do kosika",
            "k receptu",
            "k recept",
        )
    )


def recipe_related_product_subject(
    message: str,
    recipe_subject: str | None,
    recipes: list[dict] | None = None,
) -> str | None:
    message_subject = recipe_product_subject_from_title(message)
    if message_subject:
        return message_subject
    related_subject = detect_related_subject(message)
    if related_subject:
        return related_subject
    if recipe_subject in RELATED_PRODUCT_QUERIES:
        return recipe_subject
    for recipe in recipes or []:
        subject = recipe_product_subject_from_title(recipe.get("title", ""))
        if subject:
            return subject
    return None


def recipe_product_subject_from_title(title: str) -> str | None:
    normalized_title = normalize(title)
    for marker, subject in RECIPE_TITLE_PRODUCT_SUBJECTS:
        if marker in normalized_title:
            return subject
    return None


def is_recipe_intent(normalized_message: str) -> bool:
    if any(marker in normalized_message for marker in RECIPE_INTENT_MARKERS):
        return True
    return any(token.startswith("recept") for token in tokenize(normalized_message))


def _recipe_intent_is_bare_dish_marker_only(message: str) -> bool:
    """V2.14d (Section 27-34) - True iff the ONLY reason is_recipe_intent()
    would match this message is a bare dish-name marker
    (_BARE_DISH_RECIPE_MARKERS), with no genuine recipe-action language
    ("recept"/"navod"/"ako uvarim"/"how to make"/...) and no shopping-list
    language (wants_recipe_products()) present. Used to detect the narrow
    conflict class where a more specific use-case/attribute question
    should outrank a bare dish mention - never touches any other message,
    including every existing recipe/shopping-list phrasing this dish name
    already correctly triggers (Section 29 - explicit recipe intent and
    shopping-list intent are both preserved unconditionally)."""
    normalized_message = normalize(message)
    if not any(marker in normalized_message for marker in _BARE_DISH_RECIPE_MARKERS):
        return False
    other_markers = tuple(m for m in RECIPE_INTENT_MARKERS if m not in _BARE_DISH_RECIPE_MARKERS)
    if any(marker in normalized_message for marker in other_markers):
        return False
    if any(token.startswith("recept") for token in tokenize(normalized_message)):
        return False
    if wants_recipe_products(message):
        return False
    return True


def is_random_recipe_intent(message: str) -> bool:
    normalized_message = normalize(message)
    return any(marker in normalized_message for marker in RANDOM_RECIPE_INTENT_MARKERS)


def get_random_recipe(all_knowledge: dict) -> dict | None:
    all_recipes = all_knowledge.get("sections", {}).get("Recipes", [])
    if not all_recipes:
        return None
    return recipe_card(random.choice(all_recipes))


def get_random_recipes_by_cuisine(all_knowledge: dict, limit: int = 3) -> list[dict]:
    all_recipes = list(all_knowledge.get("sections", {}).get("Recipes", []))
    if not all_recipes:
        return []

    random.shuffle(all_recipes)
    safe_limit = max(1, min(int(limit or 3), 6))
    selected: list[dict] = []
    seen_titles: set[str] = set()
    seen_cuisines: set[str] = set()
    fallback: list[dict] = []

    for record in all_recipes:
        recipe = recipe_card(record)
        title_key = normalize(recipe.get("title", ""))
        if not title_key or title_key in seen_titles:
            continue
        cuisine_key = recipe_cuisine_key(record, recipe)
        if cuisine_key and cuisine_key not in seen_cuisines and len(selected) < safe_limit:
            selected.append(recipe)
            seen_titles.add(title_key)
            seen_cuisines.add(cuisine_key)
        else:
            fallback.append(recipe)

    for recipe in fallback:
        if len(selected) >= safe_limit:
            break
        title_key = normalize(recipe.get("title", ""))
        if title_key and title_key not in seen_titles:
            selected.append(recipe)
            seen_titles.add(title_key)

    return selected[:safe_limit]


def recipe_cuisine_key(record: dict, recipe: dict | None = None) -> str:
    recipe = recipe or recipe_card(record)
    text = " ".join(
        str(value or "")
        for value in (
            recipe.get("cuisine"),
            recipe.get("title"),
            recipe.get("note"),
            recipe.get("link"),
            recipe_search_text(record, recipe),
        )
    )
    cuisines = detect_cuisines_from_text(text)
    if cuisines:
        return cuisines[0]
    cuisine = normalize(str(recipe.get("cuisine") or ""))
    return cuisine or "unknown"


def recipe_results(
    knowledge_matches: dict | None,
    limit: int = 4,
    message: str = "",
    all_knowledge: dict | None = None,
) -> list[dict]:
    recipes = (knowledge_matches or {}).get("Recipes", [])
    results: list[tuple[int, dict]] = []
    seen_titles: set[str] = set()
    wanted_tokens = recipe_query_tokens(message)
    cuisine_subject = detect_recipe_cuisine(message)
    recipe_subject = detect_recipe_subject(message)

    if cuisine_subject and all_knowledge:
        recipes = [
            {"record": record, "score": 0}
            for record in all_knowledge.get("sections", {}).get("Recipes", [])
            if recipe_matches_cuisine(record, cuisine_subject)
        ]
        wanted_tokens = {token for token in wanted_tokens if not is_recipe_cuisine_query_token(token)}

    if not recipes and not wanted_tokens and all_knowledge:
        recipes = [
            {"record": record}
            for record in all_knowledge.get("sections", {}).get("Recipes", [])
        ]

    candidate_records = list(recipes)
    if wanted_tokens and all_knowledge:
        known_titles = {
            normalize(recipe_card(item.get("record", {})).get("title", ""))
            for item in candidate_records
        }
        for record in all_knowledge.get("sections", {}).get("Recipes", []):
            title_key = normalize(recipe_card(record).get("title", ""))
            if title_key and title_key not in known_titles:
                candidate_records.append({"record": record, "score": 0})
                known_titles.add(title_key)

    for item in candidate_records:
        record = item.get("record", {})
        recipe = recipe_card(record)
        title_key = normalize(recipe.get("title", ""))
        recipe_tokens = tokenize(recipe_search_text(record, recipe))
        token_hits = len(wanted_tokens & recipe_tokens)
        if wanted_tokens and token_hits == 0:
            continue
        if recipe["title"] and title_key not in seen_titles:
            seen_titles.add(title_key)
            title_tokens = tokenize(recipe.get("title", ""))
            score = int(item.get("score", 0)) + (10 * len(wanted_tokens & title_tokens)) + (3 * token_hits)
            score += recipe_subject_score(recipe_subject, recipe)
            score += recipe_phrase_score(message, recipe)
            results.append((score, recipe))
        if len(results) >= max(1, min(limit, 4)) and not wanted_tokens:
            break

    results.sort(key=lambda item: item[0], reverse=True)
    return [recipe for _, recipe in results[: max(1, min(limit, 4))]]


def recipe_phrase_score(message: str, recipe: dict) -> int:
    text = normalize(message)
    title = normalize(recipe.get("title", ""))
    score = 0

    if "pho bo" in text or text.endswith("pho b"):
        if "pho bo" in title or ("pho" in title and ("hovadz" in title or "hova" in title)):
            score += 140
        if "pho ga" in title or ("pho" in title and "kurac" in title):
            score -= 40
    if "pho ga" in text or text.endswith("pho g"):
        if "pho ga" in title or ("pho" in title and "kurac" in title):
            score += 140
        if "pho bo" in title or ("pho" in title and ("hovadz" in title or "hova" in title)):
            score -= 40
    if "kimchi ramen" in text or "ramen kimchi" in text:
        if "kimchi ramen" in title:
            score += 140
        elif "kimchi" in title and "ramen" not in title:
            score -= 40

    return score


def recipe_subject_score(subject: str | None, recipe: dict) -> int:
    if not subject:
        return 0
    title = normalize(recipe.get("title", ""))
    if subject == "kimchi_ramen":
        if "kimchi ramen" in title:
            return 120
        if "kimchi" in title and ("ramen" in title or "ramyun" in title):
            return 80
        if "kimchi" in title:
            return -20
    if subject == "ramen":
        if "ramen" in title:
            return 60
        if "kimchi" in title and "ramen" not in title:
            return -20
    if subject == "kimchi":
        if "kimchi recept" in title or ("tradicny" in title and "kimchi" in title):
            return 80
        if "kimchi" in title:
            return 24
    return 0


def recipe_search_text(record: dict, recipe: dict) -> str:
    values = [
        recipe.get("title", ""),
        recipe.get("cuisine", ""),
        recipe.get("note", ""),
    ]
    for key, value in record.items():
        normalized_key = normalize(str(key))
        if normalized_key in {"sk_url", "sk"} or "poznamka" in normalized_key:
            values.append(str(value))
    return " ".join(values)


RECIPE_CUISINE_MARKERS = {
    "vietnam": (
        "vietnam",
        "vietnamsk",
        "vietnamska",
        "vietnamske",
        "vietnamskej",
        "vietnamsku",
        "pho",
        "banh",
        "bun cha",
        "bun bo",
        "nem cuon",
        "nuoc cham",
        "thit dong",
    ),
    "thai": (
        "thai",
        "thajsk",
        "thajska",
        "thajske",
        "thajskej",
        "thajsku",
        "thajsko",
        "thajska",
        "pad thai",
        "tom yum",
        "tom kha",
        "satay",
        "khaoneeomamuang",
    ),
    "korean": (
        "korejsk",
        "korejska",
        "korejske",
        "korejskej",
        "korejsku",
        "korea",
        "korey",
        "korei",
        "korean",
        "kimchi",
        "jjigae",
        "japchae",
        "bulgogi",
        "bibimbap",
        "gimbap",
    ),
    "japanese": (
        "japonsk",
        "japonska",
        "japonske",
        "japonskej",
        "japonsku",
        "japansk",
        "japanese",
        "udon",
        "yakiudon",
        "teriyaki",
        "kuromame",
        "miso",
        "tempura",
        "shoyu",
    ),
    "chinese": (
        "cinsk",
        "cinska",
        "cinske",
        "cinskej",
        "cinsku",
        "cina",
        "ciny",
        "cinu",
        "chinese",
        "kung pao",
        "pekingsk",
        "peking",
        "ma po",
        "mapo",
        "sichuan",
        "suan la tang",
    ),
    "indian": (
        "indick",
        "indicka",
        "indicke",
        "indickej",
        "india",
        "indie",
        "indiu",
        "indian",
        "murgh makhani",
        "tikka masala",
        "tandoori",
        "biryani",
    ),
    "indonesian": (
        "indonez",
        "indonezska",
        "indonezske",
        "indonezskej",
        "indonezia",
        "indonezie",
        "indoneziu",
        "indonesia",
        "nasi goreng",
        "mie goreng",
    ),
    "malaysian": (
        "malajsk",
        "malajska",
        "malajske",
        "malajskej",
        "malajzia",
        "malajzie",
        "malajziu",
        "malaysia",
        "nasi lemak",
    ),
    "singapore": (
        "singapur",
        "singapursk",
        "singapurska",
        "singapurske",
        "singapurskej",
        "hainanske",
    ),
    "filipino": (
        "filipin",
        "filipinska",
        "filipinske",
        "filipinskej",
        "philippines",
        "sinigang",
    ),
}

RECIPE_CUISINE_QUERY_TOKENS = {
    "vietnam",
    "vietnamsk",
    "vietnamska",
    "vietnamske",
    "vietnamskej",
    "vietnamsku",
    "thai",
    "thajsk",
    "thajska",
    "thajske",
    "thajskej",
    "thajsku",
    "korejsk",
    "korejska",
    "korejske",
    "korejskej",
    "korejsku",
    "korea",
    "korey",
    "korei",
    "japonsk",
    "japonska",
    "japonske",
    "japonskej",
    "japonsku",
    "cinsk",
    "cinska",
    "cinske",
    "cinskej",
    "cinsku",
    "cina",
    "ciny",
    "cinu",
    "indick",
    "indicka",
    "indicke",
    "indickej",
    "india",
    "indie",
    "indiu",
    "indonez",
    "indonezia",
    "indonezie",
    "indoneziu",
    "malajsk",
    "malajzia",
    "malajzie",
    "malajziu",
    "singapur",
    "filipin",
    "kuchyna",
    "kuchyne",
    "kuchyni",
    "kuchynu",
}


ARTICLE_CULINARY_MARKERS = (
    "kuchyn",
    "recept",
    "jedal",
    "jedlo",
    "chut",
    "potrav",
    "ingredien",
    "omac",
    "rezanc",
    "poliev",
    "ryz",
    "snack",
    "pochut",
    "kimchi",
    "miso",
    "udon",
    "ramen",
    "shoyu",
    "mochi",
    "pho",
    "pad thai",
    "tom yum",
    "kung pao",
    "tofu",
    "biryani",
    "rendang",
    "nasi",
    "sinigang",
)


DIET_TERM_MARKERS = {
    "bezlepkove": ("bezlepk", "gluten free", "tamari"),
    "veganske": ("vegan", "vegansk", "tofu", "rastlinn"),
    "vegetarianske": ("vegetarian", "vegetariansk", "tofu", "rastlinn"),
    "jemne": ("jemne", "mild", "nepaliv"),
    "pikantne": ("pikant", "chili", "cili", "sriracha", "gochujang", "wasabi", "kimchi"),
}


def detect_recipe_cuisine(message: str) -> str | None:
    normalized_message = normalize(message)
    for cuisine, markers in RECIPE_CUISINE_MARKERS.items():
        if any(marker in normalized_message for marker in markers):
            return cuisine
    return None


def is_recipe_cuisine_query_token(token: str) -> bool:
    if token in RECIPE_CUISINE_QUERY_TOKENS:
        return True
    return token.startswith(
        (
            "vietnam",
            "vietnamsk",
            "thajsk",
            "korejsk",
            "japonsk",
            "japansk",
            "cinsk",
            "indick",
            "indonez",
            "malajsk",
            "singapur",
            "filipin",
            "kuchyn",
        )
    )


def recipe_matches_cuisine(record: dict, cuisine: str) -> bool:
    recipe = recipe_card(record)
    text = normalize(recipe_search_text(record, recipe))
    return any(marker in text for marker in RECIPE_CUISINE_MARKERS.get(cuisine, ()))


def recipe_query_tokens(message: str) -> set[str]:
    stop_words = {
        "recept",
        "recepty",
        "reept",
        "recet",
        "receppt",
        "recep",
        "navod",
        "postup",
        "ako",
        "spravim",
        "pripravim",
        "urobim",
        "na",
        "pre",
        "zo",
        "z",
        "stranky",
        "foodland",
        "foodlandu",
        "sk",
        "prosim",
        "ake",
        "aky",
        "aku",
        "mate",
        "mas",
        "mame",
        "ponukate",
        "ukaz",
        "daj",
        "thai",
    }
    return {token for token in tokenize(message) if token not in stop_words and len(token) > 2}


def recipe_card(record: dict) -> dict:
    title = first_record_value(record, ("Recept", "recipe", "nazov", "názov"))
    cuisine = first_record_value(record, ("Kuchyňa", "Kuchyna", "cuisine"))
    note = first_record_value(record, ("Poznámka", "Poznamka", "note"))
    return {
        "title": title,
        "cuisine": cuisine,
        "note": note,
        "link": first_recipe_link(record, title),
    }


def article_results(knowledge_matches: dict | None, limit: int = 3) -> list[dict]:
    results: list[dict] = []
    seen_titles: set[str] = set()
    for hit in (knowledge_matches or {}).get("Magazine", []):
        article = article_card(hit.get("record", {}))
        title_key = normalize(article.get("title", ""))
        if article["title"] and title_key not in seen_titles:
            seen_titles.add(title_key)
            results.append(article)
        if len(results) >= max(1, min(limit, 3)):
            break
    return results


def recipe_article_results(
    articles: list[dict],
    message: str,
    all_knowledge: dict | None = None,
    limit: int = 3,
) -> list[dict]:
    cuisine = detect_recipe_cuisine(message)
    if not cuisine:
        return articles
    filtered = [article for article in articles if article_matches_cuisine(article, cuisine)]
    if filtered or not all_knowledge:
        return filtered[: max(1, min(limit, 3))]

    results: list[dict] = []
    seen_titles: set[str] = set()
    for record in all_knowledge.get("sections", {}).get("Magazine", []):
        article = article_card(record)
        title_key = normalize(article.get("title", ""))
        if article.get("title") and title_key not in seen_titles and article_matches_cuisine(article, cuisine):
            seen_titles.add(title_key)
            results.append(article)
        if len(results) >= max(1, min(limit, 3)):
            break
    return results


def article_matches_cuisine(article: dict, cuisine: str) -> bool:
    text = normalize(
        " ".join(str(article.get(key, "")) for key in ("title", "topic", "note", "link"))
    )
    has_cuisine = any(marker in text for marker in RECIPE_CUISINE_MARKERS.get(cuisine, ()))
    has_culinary_context = any(marker in text for marker in ARTICLE_CULINARY_MARKERS)
    return has_cuisine and has_culinary_context


def article_card(record: dict) -> dict:
    title = first_record_value(record, ("Clanok", "článok", "article", "nazov", "názov"))
    topic = first_record_value(record, ("Tema", "téma", "topic"))
    note = first_record_value(record, ("Poznámka", "Poznamka", "note"))
    return {
        "title": title,
        "topic": topic,
        "note": note,
        "link": first_article_link(record, title),
    }


def first_record_value(record: dict, markers: tuple[str, ...]) -> str:
    normalized_markers = tuple(normalize(marker) for marker in markers)
    for key, value in record.items():
        normalized_key = normalize(str(key))
        if any(marker in normalized_key for marker in normalized_markers) and value:
            return str(value).strip()
    return ""


def first_recipe_link(record: dict, title: str) -> str:
    # Check hardcoded URL overrides by title
    normalized_title = normalize(title)
    for recipe_key, recipe_url in RECIPE_URL_OVERRIDES.items():
        if recipe_key in normalized_title:
            return recipe_url

    for key, value in record.items():
        text = str(value or "").strip()
        normalized_key = normalize(str(key))
        if text.startswith(("http://", "https://")) and any(
            marker in normalized_key for marker in ("url", "link", "odkaz", "sk", "cz", "en")
        ):
            return text

    if title:
        return f"https://www.foodland.sk/?s={quote_plus(title)}"
    return "https://www.foodland.sk/recepty/"


def first_article_link(record: dict, title: str) -> str:
    for key, value in record.items():
        text = str(value or "").strip()
        normalized_key = normalize(str(key))
        if text.startswith(("http://", "https://")) and any(
            marker in normalized_key for marker in ("sk_url", "url", "link", "odkaz")
        ):
            return text

    if title:
        return f"https://www.foodland.sk/blog/?s={quote_plus(title)}"
    return "https://www.foodland.sk/blog/"


def recipe_answer(subject: str, recipes: list[dict] | None = None, lang: str = "sk") -> str:
    if lang == "en":
        if recipes:
            if len(recipes) == 1:
                return "I found a recipe on Foodland.sk. Open it below."
            return "I found recipes on Foodland.sk. Pick one from the recommendations below."
        return "I picked up on a recipe question, but don't have enough detail for an exact recipe. Try writing e.g.: kimchi recipe or pad thai recipe."
    if recipes:
        if len(recipes) == 1:
            return "Našla som recept z Foodland.sk. Otvorte si ho nižšie."
        return "Našla som recepty z Foodland.sk. Vyberte si z odporúčaní nižšie."

    return "Receptovú otázku som zachytila, ale nemám dosť detailov na presný recept. Skúste napísať napríklad: recept na kimchi alebo recept na pad thai."


GENERAL_AI_RECIPE_SYSTEM_PROMPT = (
    "Si kulinárska poradkyňa pre Foodland.sk (obchod s ázijskými a svetovými potravinami). "
    "Zákazník napísal výraz, ktorý sa nenašiel medzi produktmi ani receptami Foodlandu. "
    "Ak je to rozpoznateľné JEDLO, RECEPT alebo KULINÁRSKA TÉMA (napr. názov konkrétneho jedla, "
    "kuchyne alebo ingrediencie): daj stručnú (2-4 vety) VŠEOBECNÚ kulinársku odpoveď - čo je "
    "to za jedlo a z akých typov surovín sa väčšinou pripravuje. Toto je tvoja všeobecná znalosť, "
    "nie ponuka Foodlandu - preto NIKDY nespomínaj konkrétny názov produktu, značku, cenu, sklad "
    "ani odkaz, akoby ich Foodland reálne predával. Na konci vždy jasne napíš, že presný recept "
    "na toto jedlo v databáze Foodlandu nemáme, a odporuč zákazníkovi vyhľadať si podobné "
    "suroviny priamo v našej ponuke. "
    "Ak výraz NIE JE jedlo, recept ani kulinárska téma (napr. názov produktu inej kategórie, "
    "meno, značka nesúvisiaca s jedlom, nezmyselný text) - neodpovedaj vôbec, iba doslovne "
    "napíš presne toto slovo bez úvodzoviek a bez čohokoľvek iného: NEURCITE. "
    "Odpovedaj v jazyku otázky zákazníka; ak jazyk nie je jasný, odpovedaj po slovensky."
)


def general_ai_recipe_answer(dish_query: str) -> str | None:
    """Krátka VŠEOBECNÁ kulinárska odpoveď pre recept/jedlo, ktoré nie je
    v databáze Foodlandu. Nikdy nevymýšľa konkrétne Foodland fakty (produkty,
    ceny, sklad) - iba všeobecnú kulinársku znalosť. Vráti None ak OpenAI
    nie je nakonfigurované alebo volanie zlyhá (volajúci sa vtedy vráti k
    pôvodnej fallback odpovedi)."""
    client = _get_openai_client()
    if not client:
        return None
    try:
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        messages = [
            {"role": "system", "content": GENERAL_AI_RECIPE_SYSTEM_PROMPT},
            {"role": "user", "content": f"Otázka zákazníka: {dish_query}"},
        ]
        answer = _call_openai_with_retry(client, messages, model, max_tokens=280)
        answer = answer.strip()
        if not answer or "NEURCITE" in answer:
            return None
        return answer
    except (RateLimitError, APITimeoutError, APIConnectionError) as exc:
        logger.warning("General AI recipe answer failed: %s", exc)
        return None


def random_recipes_answer(recipes: list[dict] | None = None, lang: str = "sk") -> str:
    if lang == "en":
        if recipes:
            return "I picked three recipes from different cuisines for dinner. Choose whichever sounds best below."
        return recipe_answer("general", recipes, lang)
    if recipes:
        return "Na večeru som vybrala tri recepty z rôznych kuchýň. Vyberte si podľa chuti nižšie."
    return recipe_answer("general", recipes)


def recipe_products_answer(subject: str | None, recipes: list[dict] | None = None, lang: str = "sk") -> str:
    subject_text = str(subject or "recept").replace("_", " ")
    if lang == "en":
        subject_text_en = readable_subject_label_en(subject) if subject else "this recipe"
        if recipes:
            return (
                f"I put together a shopping list for {subject_text_en}: Foodland.sk products first, then separately the things "
                "you'll need to get elsewhere. Products are sorted from key ingredients to extras."
            )
        return (
            f"I found relevant Foodland.sk products for the {subject_text_en} recipe. "
            "They're sorted from key ingredients to extras; add fresh items yourself per the recipe."
        )
    if recipes:
        return (
            f"Pripravila som nákupný zoznam pre {subject_text}: najprv produkty z Foodland.sk, potom zvlášť veci, ktoré si treba doplniť mimo e-shopu. "
            "Produkty sú zoradené od kľúčových surovín po doplnky."
        )
    return (
        f"K receptu pre {subject_text} som našla relevantné produkty z Foodland.sk. "
        "Sú zoradené od kľúčových surovín po doplnky; čerstvé veci si doplňte podľa receptu."
    )


REPLACEMENT_QUERY_FILLER = (
    "cim",
    "čím",
    "vynahradim",
    "vynahradím",
    "nahradim",
    "nahradím",
    "nahradit",
    "nahradiť",
    "nahrad",
    "nahrada",
    "náhrada",
    "namiesto",
    "alternativa",
    "alternatíva",
    "alternativu",
    "alternatívu",
    "co pouzit",
    "čo použiť",
    "pouzit",
    "použiť",
    "za",
    "ak",
    "nemam",
    "nemám",
    "nemame",
    "nemáme",
    "x",
    "znacka",
    "znacky",
    "znacku",
    "znacke",
)


REPLACEMENT_SUBJECT_ALIASES = {
    "rybacia omacka": ("rybacia omacka", "rybaciu omacku", "rybiu omacku", "rybacej omacky", "rybacej omacke", "rybacou omackou", "fish sauce"),
    "sojova omacka": ("sojova omacka", "sojovu omacku", "sojovej omacke", "sojovej omacky", "sojovou omackou", "shoyu", "soy sauce"),
    "gochujang": ("gochujang", "gochu jang", "gochudzang", "gochu"),
    "mirin": ("mirin",),
    "ryzovy ocot": ("ryzovy ocot", "rice vinegar"),
    "kokosove mlieko": ("kokosove mlieko", "kokosoveho mlieka", "coconut milk"),
    "miso pasta": ("miso pasta", "miso"),
    "sriracha": ("sriracha", "sriraca"),
    "hoisin omacka": ("hoisin", "hoisin omacka"),
    "tamari": ("tamari",),
    "tamarind": ("tamarind",),
    "ryzove rezance": ("ryzove rezance", "rice noodles"),
    "sushi ryza": ("sushi ryza", "sushi ryzu"),
}


REPLACEMENT_PRODUCT_QUERIES = {
    "mirin": ["mirin", "sladke ryzove vino"],
    "sojova omacka": ["tamari sojova omacka", "bezlepkova sojova omacka", "japonska sojova omacka"],
    "rybacia omacka": ["tamari sojova omacka", "sojova omacka", "hubova vegetarianska omacka"],
    "gochujang": ["gochujang", "korejska cili pasta"],
    "ryzovy ocot": ["ryzovy ocot", "rice vinegar"],
    "kokosove mlieko": ["kokosove mlieko", "kokosovy krem"],
    "miso pasta": ["miso pasta", "miso"],
    "sriracha": ["sriracha", "chili omacka", "sambal"],
    "hoisin omacka": ["hoisin omacka", "sladka sojova omacka"],
    "tamari": ["tamari sojova omacka", "bezlepkova sojova omacka"],
}


def detect_replacement_subject(message: str) -> str | None:
    normalized_message = normalize(message)
    has_explicit_marker = any(
        marker in normalized_message
        for marker in ("nahrad", "vynahrad", "namiesto", "alternativ", "nemam", "nemame", "cim ", "čim ", "čím ")
    )
    # "ina sojova omacka ako Kikkoman" (a different X than Y) is a natural
    # way to ask for an alternative brand, but has none of the markers
    # above - it fell through to the related_products (cross-sell)
    # branch instead, which surfaced unrelated pairings (mirin, rice
    # vinegar) rather than competing soy sauce brands.
    padded_message = f" {normalized_message} "
    has_comparative_marker = "ako" in normalized_message and any(
        marker in padded_message for marker in (" ina ", " ine ", " iny ", " inu ", " inej ", " ineho ")
    )
    if not (has_explicit_marker or has_comparative_marker):
        return None

    for subject, aliases in REPLACEMENT_SUBJECT_ALIASES.items():
        if any(alias in normalized_message for alias in aliases):
            return subject

    cleaned = normalized_message
    for filler in REPLACEMENT_QUERY_FILLER:
        cleaned = cleaned.replace(normalize(filler), " ")
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", cleaned)
    cleaned = " ".join(token for token in cleaned.split() if len(token) > 2)
    if not cleaned:
        return None
    unambiguous_brand_subject = resolve_unambiguous_sauce_brand(cleaned)
    if unambiguous_brand_subject:
        return unambiguous_brand_subject
    return complete_autocomplete_subject(cleaned)


def resolve_unambiguous_sauce_brand(cleaned_message: str) -> str | None:
    """A replacement query naming only a brand with no category word
    (e.g. "alternativa Kikkoman", no "sojova omacka") used to fall
    through to a plain brand-name search, surfacing whatever Kikkoman
    product happened to match (wok sauce, kimchi base, teriyaki
    marinade) instead of soy sauce alternatives. If the (filler-stripped)
    message names a brand that sells only ONE of our two sauce categories
    (verified: only MEGACHEF sells both soy and fish sauce - every other
    brand in the catalog is unambiguous), resolve directly to it.

    Substring match, not equality: detect_replacement_subject() is called
    with contextualize_message()'s output, which can append prior-session
    context (diet terms, last product title) after the brand name - an
    exact-equality check missed that live and produced an empty result
    (subject stayed the polluted literal text while exclude_brand still
    correctly matched the brand, so the two contradicted each other).
    """
    normalized = normalize(cleaned_message).strip()
    if not normalized:
        return None
    matched_categories = set()
    for category_subject in ("sojova omacka", "rybacia omacka"):
        category_products = cached_search_products(products, category_subject, 30)
        brands = {normalize(str(product.get("brand") or "")) for product in category_products}
        if any(brand and brand in normalized for brand in brands):
            matched_categories.add(category_subject)
    if len(matched_categories) == 1:
        return matched_categories.pop()
    return None


def detect_mentioned_replacement_brand(message: str, products_list: list[Product] | list[dict], subject: str) -> str | None:
    """Find a specific brand named in a replacement-style query, e.g.
    "alternativa ku Kikkoman sojovej omacke" -> "KIKKOMAN". Real user need:
    "alternative to brand X" means a DIFFERENT brand, so this is used to
    exclude that brand from alternative_products_for_subject() below -
    without it, the fallback search matched the brand name as a plain
    keyword and recommended MORE of the same brand instead of competitors.
    """
    if not subject:
        return None
    normalized_message = normalize(message)
    category_products = cached_search_products(products_list, subject, 30)
    candidate_brands = {str(product.get("brand") or "").strip() for product in category_products}
    matched: str | None = None
    for brand in candidate_brands:
        normalized_brand = normalize(brand)
        if len(normalized_brand) >= 3 and normalized_brand in normalized_message:
            if not matched or len(normalized_brand) > len(normalize(matched)):
                matched = brand
    return matched


def alternative_products_for_subject(
    products_list: list[Product] | list[dict],
    all_knowledge: dict,
    subject: str,
    limit: int,
    exclude_brand: str | None = None,
) -> list[dict]:
    recommendations = _alternative_products_for_subject_impl(products_list, all_knowledge, subject, limit, exclude_brand)
    if recommendations or not exclude_brand:
        return recommendations
    # Safety net: if excluding the named brand leaves literally nothing (all
    # three tiers empty), fall back to showing that brand's own products
    # rather than an empty list - the AI-generated answer for
    # replacement_products always claims "here are alternatives below"
    # regardless of whether matches is empty, so an empty list here means a
    # customer sees confident text with nothing under it. Some real product
    # beats a contradiction between what the answer says and what it shows.
    return _alternative_products_for_subject_impl(products_list, all_knowledge, subject, limit, None)


def _alternative_products_for_subject_impl(
    products_list: list[Product] | list[dict],
    all_knowledge: dict,
    subject: str,
    limit: int,
    exclude_brand: str | None,
) -> list[dict]:
    seen: set[str] = set()
    recommendations: list[dict] = []
    normalized_exclude_brand = normalize(exclude_brand) if exclude_brand else ""

    def is_excluded(product: dict) -> bool:
        if not normalized_exclude_brand:
            return False
        return normalize(str(product.get("brand") or "")) == normalized_exclude_brand

    alternative_hits = search_knowledge(all_knowledge, subject, allowed_sections=("Alternatives",))
    for hit in alternative_hits.get("Alternatives", []):
        record = hit.get("record", {})
        product_name = first_record_value(record, ("Produkt", "product"))
        if subject and not replacement_subject_matches_product(subject, product_name):
            continue
        for index in range(1, 6):
            alt_title = clean_alternative_title(str(record.get(f"Alternativa {index}") or ""))
            alt_url = str(record.get(f"Alternativa {index}_url") or "").strip()
            for product in products_from_alternative(products_list, alt_title, alt_url, subject):
                if is_excluded(product):
                    continue
                key = product.get("id") or product.get("link") or product.get("title")
                if not key or key in seen:
                    continue
                seen.add(key)
                recommendations.append(product)
                if len(recommendations) >= limit:
                    return recommendations
                break

    if recommendations:
        return recommendations

    for query in REPLACEMENT_PRODUCT_QUERIES.get(subject, []):
        for product in prioritize_replacement_title_matches(cached_search_products(products_list, query, max(limit, 6)), query):
            if is_excluded(product):
                continue
            key = product.get("id") or product.get("link") or product.get("title")
            if key and key not in seen:
                seen.add(key)
                recommendations.append(product)
            if len(recommendations) >= limit:
                return recommendations

    if recommendations:
        return recommendations

    # Fallback: same-name/category products are still alternatives, unlike cross-sell complements.
    fallback_products = prioritize_replacement_title_matches(cached_search_products(products_list, subject, max(limit * 2, 8)), subject)
    for product in fallback_products:
        if is_excluded(product):
            continue
        key = product.get("id") or product.get("link") or product.get("title")
        if key and key not in seen:
            seen.add(key)
            recommendations.append(product)
        if len(recommendations) >= limit:
            break
    return recommendations


def replacement_subject_matches_product(subject: str, product_name: str) -> bool:
    normalized_subject = normalize(subject)
    normalized_title = normalize(product_name)
    if normalized_subject and normalized_subject in normalized_title:
        return True
    subject_tokens = {token for token in tokenize(normalized_subject) if len(token) > 2}
    title_tokens = set(tokenize(normalized_title))
    return bool(subject_tokens) and subject_tokens <= title_tokens


def prioritize_replacement_title_matches(products_list: list[dict], subject: str) -> list[dict]:
    strong: list[dict] = []
    weak: list[dict] = []
    for product in products_list:
        title = str(product.get("title") or "")
        if replacement_subject_matches_product(subject, title):
            strong.append(product)
        else:
            weak.append(product)
    return strong if strong else weak


def clean_alternative_title(value: str) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    for separator in (" – alternativa", " - alternativa", " – alternatíva", " - alternatíva"):
        if separator in text:
            text = text.split(separator, 1)[0]
    return text.strip()


def products_from_alternative(products_list: list[Product] | list[dict], title: str, url: str, subject: str) -> list[dict]:
    if title and not replacement_subject_matches_product(subject, title):
        # Product alternative rows sometimes contain broad category neighbors; avoid treating accessories as substitutes.
        return []
    if url:
        normalized_url = normalize_url_for_match(url)
        for product in products_list:
            product_data = format_product(product)
            product_url = normalize_url_for_match(str(product_data.get("link") or product_data.get("url") or ""))
            if product_url and product_url == normalized_url:
                return [product_data]
    if title:
        return cached_search_products(products_list, title, 3)
    return []


def clean_cross_sell_title(value: str) -> str:
    text = " ".join(str(value or "").split())
    for separator in (" – ", " — ", " - "):
        if separator in text:
            return text.split(separator, 1)[0].strip()
    return text.strip()


def is_product_cross_sell_request(message: str) -> bool:
    normalized_message = normalize(message)
    return any(
        marker in normalized_message
        for marker in (
            "co sa hodi k",
            "čo sa hodí k",
            "co kupit k",
            "čo kúpiť k",
            "suvisiace produkty k",
            "súvisiace produkty k",
            "doplnky k",
            "co odporucate k",
            "čo odporúčate k",
            "ak kupujem",
        )
    )


def cross_sell_products_for_message(
    products_list: list[Product] | list[dict],
    all_knowledge: dict,
    message: str,
    limit: int,
) -> list[dict]:
    if not is_product_cross_sell_request(message):
        return []

    normalized_message = normalize(message)
    seen: set[str] = set()
    recommendations: list[dict] = []

    for record in all_knowledge.get("sections", {}).get("CrossSell", []):
        product_name = first_record_value(record, ("Produkt", "product"))
        if not product_name or normalize(product_name) not in normalized_message:
            continue
        for index in range(1, 6):
            cross_sell_title = clean_cross_sell_title(record.get(f"Cross-sell {index}") or "")
            if not cross_sell_title:
                continue
            for product in cached_search_products(products_list, cross_sell_title, 3):
                key = product.get("id") or product.get("link") or product.get("title")
                if not key or key in seen:
                    continue
                seen.add(key)
                recommendations.append(product)
                if len(recommendations) >= limit:
                    return recommendations
                break
        break

    return recommendations


def normalize_url_for_match(url: str) -> str:
    return str(url or "").strip().rstrip("/")


def find_product_by_id(products_list: list[Product] | list[dict], product_id: str) -> Product | dict | None:
    if not product_id:
        return None
    for product in products_list:
        if product_field(product, "id") == product_id:
            return product
    return None


def knowledge_record_by_id(all_knowledge: dict, section: str, product_id: str) -> dict | None:
    if not product_id:
        return None
    for record in all_knowledge.get("sections", {}).get(section, []):
        if str(record.get("ID", "")).strip() == product_id:
            return record
    return None


def linked_products_from_record(
    products_list: list[Product] | list[dict],
    record: dict,
    prefix: str,
    limit: int,
) -> list[dict]:
    """Resolve a knowledge record's numbered "<prefix> N"/"<prefix> N_url" pairs
    (Alternativa/Cross-sell) to catalog products, preferring an exact URL match
    over a fuzzy title search fallback."""
    entries: list[tuple[str, str]] = []
    for index in range(1, 6):
        title = clean_cross_sell_title(record.get(f"{prefix} {index}") or "")
        url = normalize_url_for_match(record.get(f"{prefix} {index}_url") or "")
        if title or url:
            entries.append((title, url))
    if not entries:
        return []

    url_to_product: dict[str, dict] = {}
    if any(url for _, url in entries):
        for product in products_list:
            product_data = format_product(product)
            product_url = normalize_url_for_match(str(product_data.get("link") or ""))
            if product_url:
                url_to_product.setdefault(product_url, product_data)

    seen: set[str] = set()
    results: list[dict] = []
    for title, url in entries:
        matched = url_to_product.get(url) if url else None
        if not matched and title:
            hits = cached_search_products(products_list, title, 1)
            matched = hits[0] if hits else None
        if not matched:
            continue
        key = matched.get("id") or matched.get("link") or matched.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        results.append(matched)
        if len(results) >= limit:
            break
    return results


def find_recipe_record(all_knowledge: dict, name: str) -> dict | None:
    normalized_query = normalize(name)
    if not normalized_query:
        return None
    query_tokens = tokenize(name)

    best_score = 0
    best_record: dict | None = None
    for record in all_knowledge.get("sections", {}).get("Recipes", []):
        title = first_record_value(record, ("Recept", "recipe", "nazov", "n\u00e1zov"))
        if not title:
            continue
        normalized_title = normalize(title)

        score = 0
        if normalized_query == normalized_title:
            score += 100
        elif normalized_query in normalized_title or normalized_title in normalized_query:
            score += 40
        score += 10 * len(query_tokens & tokenize(title))
        if score > best_score:
            best_score = score
            best_record = record
    return best_record


def basket_recommendations(
    products_list: list[Product] | list[dict],
    all_knowledge: dict,
    skus: list[str],
    limit: int,
    profile: dict | None = None,
) -> list[dict]:
    seen: set[str] = {sku for sku in skus if sku}
    results: list[dict] = []

    def add_all(candidates: list[dict]) -> bool:
        for product in candidates:
            key = product.get("id") or product.get("link") or product.get("title")
            if not key or key in seen:
                continue
            seen.add(key)
            results.append(product)
            if len(results) >= limit:
                return True
        return False

    def finalize() -> list[dict]:
        return personalize_products(results[:limit], profile)

    if FBT_RECOMMENDATIONS_ENABLED:
        fbt_data = get_fbt_data()
        for sku in skus:
            fbt_candidates = []
            for candidate_sku in fbt_recommendations(sku, fbt_data, limit - len(results)):
                product = find_product_by_id(products_list, candidate_sku)
                if product:
                    fbt_candidates.append(format_product(product))
            if fbt_candidates and add_all(fbt_candidates):
                return finalize()

    for sku in skus:
        record = knowledge_record_by_id(all_knowledge, "CrossSell", sku)
        if record and add_all(linked_products_from_record(products_list, record, "Cross-sell", limit - len(results))):
            return finalize()

    for sku in skus:
        record = knowledge_record_by_id(all_knowledge, "Alternatives", sku)
        if record and add_all(linked_products_from_record(products_list, record, "Alternativa", limit - len(results))):
            return finalize()

    # Baskets with no matching knowledge record still get something: search
    # using each basket product's own title instead of returning nothing.
    for sku in skus:
        product = find_product_by_id(products_list, sku)
        title = product_field(product, "title") if product else ""
        if title and add_all(cached_search_products(products_list, title, limit)):
            return finalize()

    return finalize()


def trending_product_skus(limit: int = 50) -> list[str]:
    events = read_engagement_events(14)
    scores: dict[str, float] = defaultdict(float)
    for event in events:
        weight = TRENDING_EVENT_WEIGHTS.get(event.get("event_type"), 0)
        if not weight:
            continue
        sku = event.get("product_sku")
        if sku:
            scores[sku] += weight
        # Impressions land as a batch of skus shown together, so each one on
        # its own is a weaker signal than a direct click/add-to-cart/conversion.
        for batch_sku in event.get("product_skus") or []:
            scores[batch_sku] += weight * 0.5
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [sku for sku, _score in ranked[:limit]]


def cached_trending_products(products_list: list[Product] | list[dict], limit: int) -> list[dict]:
    global _trending_products_cache, _trending_products_cache_at
    now = time.time()
    if now - _trending_products_cache_at > TRENDING_CACHE_SECONDS or not _trending_products_cache:
        results: list[dict] = []
        for sku in trending_product_skus(50):
            product = find_product_by_id(products_list, sku)
            if product:
                results.append(format_product(product))
        if not results:
            # Cold start: no engagement events logged yet. Fall back to a
            # handful of popular ingredient categories instead of an empty
            # response.
            seen: set[str] = set()
            for term in ("sushi", "kimchi", "ramen", "gochujang"):
                for candidate in cached_search_products(products_list, term, 5):
                    key = candidate.get("id") or candidate.get("link")
                    if key and key not in seen:
                        seen.add(key)
                        results.append(candidate)
        _trending_products_cache = results
        _trending_products_cache_at = now
    return _trending_products_cache[:limit]


def detect_special_product_subject(message: str) -> str | None:
    normalized_message = normalize(message)
    if ("kimchi" in normalized_message or "kimci" in normalized_message) and not any(
        marker in normalized_message
        for marker in (
            "co je",
            "co znamena",
            "ako chuti",
            "recept",
            "ingredien",
            "surovin",
            "potrebujem",
            "co treba",
            "co kupit",
            "vyrob",
            "priprav",
            "varit",
            "urobit",
            "spravit",
            "nakupny zoznam",
            "do kosika",
            "nahrad",
            "vynahrad",
        )
    ):
        return "kimchi_product"
    if ("sushi ryz" in normalized_message or "susi ryz" in normalized_message) and not any(
        marker in normalized_message for marker in ("bez lepku", "bezlepk", "celiak", "dopln")
    ):
        return "sushi_rice"
    if (is_gluten_free_search(normalized_message) or "celiak" in normalized_message) and bool(
        {"sushi", "susi"} & set(normalized_message.split())
    ):
        return "gluten_free_sushi"
    if "ryzovar" in normalized_message or ("hrniec" in normalized_message and "ryz" in normalized_message):
        return "rice_cooker"
    if "korenie" in normalized_message and "ryz" in normalized_message:
        return "rice_seasoning"
    if "ryz" in normalized_message and not any(
        marker in normalized_message
        for marker in ("ryzovar", "hrniec", "korenie", "muka", "ocot", "rezance", "sushi", "susi", "papier", "nudle")
    ):
        return "plain_rice"
    if "sushi" in normalized_message and "dopln" in normalized_message and any(
        marker in normalized_message for marker in ("nie dalsie balenia ryze", "nie ryz")
    ):
        return "sushi_condiments"
    if ("paliv" in normalized_message or "pikant" in normalized_message) and any(
        marker in normalized_message for marker in ("nie sladke", "cukrik")
    ):
        return "medium_spicy"
    if ("tofu" in normalized_message or "rias" in normalized_message) and "nie maso" in normalized_message:
        return "tofu_seaweed"
    if "gochu jang" in normalized_message or "gochudzang" in normalized_message or "gochudang" in normalized_message:
        return "korean_paste"
    if "coconat milk" in normalized_message or "coconut milk" in normalized_message:
        return "dairy_replacement"
    if "kokos" in normalized_message and "mlieko" in normalized_message and "kari" in normalized_message:
        return "dairy_replacement"
    if any(marker in normalized_message for marker in ("extra paliv", "velmi paliv", "najpaliv")):
        return "hot"
    if "pikant" in normalized_message and any(marker in normalized_message for marker in ("nie extrem", "nie velmi", "mierne")):
        return "medium_spicy"
    if "rice vinegar" in normalized_message or ("ryzov" in normalized_message and "ocot" in normalized_message):
        return "rice_vinegar"
    if ("tamari" in normalized_message or "tamary" in normalized_message) and (
        "sojov" in normalized_message or "bezlepk" in normalized_message or "namiesto" in normalized_message
    ):
        return "tamari"
    if "bezlepk" in normalized_message and "sojov" in normalized_message and "omack" in normalized_message:
        return "tamari"
    if "korejsk" in normalized_message and "past" in normalized_message:
        return "korean_paste"
    if "vegan" in normalized_message and any(marker in normalized_message for marker in ("azij", "europsk", "jedl")):
        return "vegan_asian"
    if "bravcov" in normalized_message and any(marker in normalized_message for marker in ("azij", "jedl", "bez")):
        return "no_pork_asian"
    if "sladkost" in normalized_message or (
        "snack" in normalized_message
        and any(marker in normalized_message for marker in ("azij", "cokolad", "europsk"))
        and "omack" not in normalized_message
    ):
        return "asian_sweets"
    if "mochi" in normalized_message and "ryz" in normalized_message:
        return "asian_sweets"
    if "snack" in normalized_message and any(marker in normalized_message for marker in ("nic paliv", "alkohol", "wasabi")):
        return "safe_snack"
    if "omack" in normalized_message and "nie rybac" in normalized_message:
        return "safe_sauce"
    if any(marker in normalized_message for marker in ("masla", "maslo", "smotany", "smotana")) and any(
        marker in normalized_message for marker in ("namiesto", "nahrad", "dochuten")
    ):
        return "dairy_replacement"
    if any(marker in normalized_message for marker in ("smotanov", "kravskym mliekom", "kravske mlieko")) and any(
        marker in normalized_message for marker in ("kokos", "azij", "varenia", "kari")
    ):
        return "dairy_replacement"
    if "ferment" in normalized_message or ("kysl" in normalized_message and "kapust" in normalized_message):
        return "fermented_sour"
    if any(marker in normalized_message for marker in ("psenic", "talianske cestoviny", "cestoviny")) and any(
        marker in normalized_message for marker in ("nahrad", "nechcem", "nesedia")
    ):
        return "asian_noodles"
    if "zemiak" in normalized_message and "ryz" in normalized_message:
        return "rice_side"
    if "snack" in normalized_message and any(marker in normalized_message for marker in ("det", "dieta", "deti")):
        return "kids_snack"
    if any(term in normalized_message for term in ("rybi", "rybac")) and "omack" in normalized_message and any(
        marker in normalized_message for marker in ("vegan", "vegans", "nahrad", "alternativ")
    ):
        return "vegan_fish_sauce_replacement"
    if "nepaliv" in normalized_message or "jemne" in normalized_message:
        return "mild"
    return None


# V2.12.2 (docs/query-semantics.md) - a small, deliberately narrow set of
# phrases that genuinely signal "I want a recipe/shopping list", as
# opposed to RELATED_INTENT_MARKERS below, which is intentionally broad
# (single category words like "rezanc"/"olej") so real recipe questions
# are still caught. Used only to DISTINGUISH a genuine recipe question
# from a bare product-name query that happens to share a word with one -
# never to detect recipe intent on its own.
RECIPE_SHOPPING_LANGUAGE_MARKERS = (
    "recept", "ingredien", "surovin", "vyrob", "priprav", "urobit", "spravit",
    "nakupny zoznam", "co potrebujem", "co treba", "co k tomu", "chyba mi",
    "chybaju mi", "este chyba", "co pridat", "do kosika", "nakupujem",
    "hodi", "hodia", "pasuje", "pasuju", "suvisiace", "doplnky", "odporuc",
)


def _has_recipe_shopping_language(message: str) -> bool:
    normalized_message = normalize(message)
    return any(marker in normalized_message for marker in RECIPE_SHOPPING_LANGUAGE_MARKERS)


def _query_resolves_to_confident_product_family(message: str) -> bool:
    """True when the taxonomy engine can resolve this bare query to its
    own family with real confidence - i.e. it looks like a direct
    product-name search the structured retrieval pipeline should own,
    not a cross-sell/recipe-companion question."""
    try:
        parsed = parse_structured_query(message)
    except Exception:
        return False
    return parsed.family is not None and parsed.confidence in {"HIGH", "MEDIUM"}


def detect_related_subject(message: str) -> str | None:
    normalized_message = normalize(message)
    if not any(marker in normalized_message for marker in RELATED_INTENT_MARKERS):
        return None

    title_subject = recipe_product_subject_from_title(normalized_message)
    if title_subject and title_subject in RELATED_PRODUCT_QUERIES:
        return title_subject

    if ("kimchi" in normalized_message or "kimci" in normalized_message) and any(
        marker in normalized_message
        for marker in (
            "co potrebujem",
            "co treba",
            "ingredien",
            "surovin",
            "vyrob",
            "priprav",
            "urobit",
            "spravit",
            "nakupny zoznam",
            "do kosika",
        )
    ):
        return "kimchi_recipe"

    if "pho" in normalized_message:
        return "pho"

    for subject, aliases in RELATED_SUBJECT_ALIASES.items():
        if any(alias in normalized_message for alias in aliases):
            return subject

    if normalized_message.strip() in {
        "na vyrobu",
        "na pripravu",
        "ingrediencie",
        "suroviny",
        "co na vyrobu",
        "co treba na vyrobu",
        "co potrebujem na vyrobu",
    }:
        return "kimchi_recipe"

    return None


def is_article_info_intent(message: str) -> bool:
    normalized_message = normalize(message)
    return any(
        marker in normalized_message
        for marker in (
            "co je",
            "co znamena",
            "ako chuti",
            "ako sa je",
            "ako sa vyraba",
            "aky je rozdiel",
            "rozdiel",
            "rozdil",
            "preco",
            "proc",
            "benefity",
            "ucinky",
            "na co sa pouziva",
            "na co sa pouzivaju",
            "ako sa pouziva",
            "aky ma pouziva",
            "what is",
            "what does it mean",
            "how does it taste",
            "how is it made",
            "what is the difference",
            "difference between",
            "what is it used for",
            "used for",
            "why",
            "benefits",
        )
    )


def detect_article_product_subject(message: str, articles: list[dict] | None = None) -> str | None:
    text = normalize(" ".join([message, *[article.get("title", "") for article in articles or []]]))
    if "kimchi" in text or "kimci" in text:
        return "kimchi_article"
    if "pho" in text:
        return "pho_article"
    if "udon" in text and "ramen" in text:
        return "udon_ramen_article"
    if "udon" in text:
        return "udon_article"
    if "ramen" in text or "ramyun" in text:
        return "ramen_article"
    if "tofu" in text:
        return "tofu_article"
    if "shoyu" in text:
        return "shoyu_article"
    if "tamari" in text:
        return "tamari_article"
    if "miso" in text:
        return "miso_article"
    if "matcha" in text:
        return "matcha_article"
    if "mochi" in text:
        return "mochi_article"
    if "bubble tea" in text or "boba" in text:
        return "bubble_tea_article"
    return None


def article_products_for_subject(products_list: list[Product], subject: str, limit: int) -> list[dict]:
    seen: set[str] = set()
    recommendations: list[dict] = []

    for query in ARTICLE_PRODUCT_QUERIES.get(subject, []):
        for product in cached_search_products(products_list, query, max(6, limit)):
            if not is_article_relevant_product(product, subject):
                continue
            key = product.get("id") or product.get("link") or product.get("title")
            if not key or key in seen:
                continue
            seen.add(key)
            recommendations.append(product)
            if len(recommendations) >= limit:
                return recommendations
    return recommendations


def is_article_relevant_product(product: dict, subject: str) -> bool:
    title = normalize(str(product.get("title", "")))
    text = normalize(" ".join(str(product.get(key, "")) for key in ("title", "product_type", "category", "description")))
    title_tokens = set(title.split())

    blocked_markers = (
        "miska",
        "misky",
        "set ",
        "suprava",
        "palicky",
        "podlozka",
        "sushi mat",
        "krek",
        "snack",
        "chips",
        "cukrik",
        "bonbon",
    )
    if any(marker in text for marker in blocked_markers):
        return False

    if subject == "kimchi_article":
        return "kimchi" in title and not any(marker in title for marker in ("ramen", "ramyun", "instant", "polievka"))
    if subject == "pho_article":
        return "pho" in title or "banh pho" in title
    if subject == "udon_article":
        return "udon" in title
    if subject == "ramen_article":
        return "ramen" in title or "ramyun" in title
    if subject == "udon_ramen_article":
        return "udon" in title or "ramen" in title or "ramyun" in title
    if subject == "tofu_article":
        return "tofu" in title and "miso" not in title_tokens and "polievka" not in title_tokens
    if subject == "shoyu_article":
        return "shoyu" in title or ("sojova" in title_tokens and "omacka" in title_tokens)
    if subject == "tamari_article":
        return "tamari" in title_tokens
    if subject == "miso_article":
        return "miso" in title and "polievka" not in title_tokens
    if subject == "matcha_article":
        return "matcha" in title
    if subject == "mochi_article":
        return "mochi" in title
    if subject == "bubble_tea_article":
        return "bubble" in title or "boba" in title or "tapiok" in title
    return True


def detect_already_have_subject(message: str) -> str | None:
    """Detekuje vzor 'mám X / kúpil som X / vlastním X' a vracia kanonický kľúč subjektu."""
    normalized_message = normalize(message)
    # V2.16c (root-caused during substitution-intelligence characterization):
    # ALREADY_HAVE_MARKERS used bare substring containment ("mam " in text),
    # which also matches inside "nemam " (I do NOT have) - the opposite
    # meaning. "Nemam mirin, potrebujem nahradu bez lepku." (I don't have
    # mirin, I need a gluten-free substitute) was silently classified as
    # already_have_subject="mirin" and routed to complement_products_for_
    # subject() (a "goes well with what you have" cross-sell), so
    # replacement_subject was never reached at all - reproduced live.
    # Padding both sides with a leading space enforces a real left word
    # boundary before each marker while every legitimately space-preceded
    # occurrence ("uz mam ", start-of-string "mam ") is unaffected.
    padded_message = " " + normalized_message
    if not any((" " + marker) in padded_message for marker in ALREADY_HAVE_MARKERS):
        return None
    for subject_key, aliases in ALREADY_HAVE_SUBJECT_MAP.items():
        if any(alias in normalized_message for alias in aliases):
            return subject_key
    return None


def complement_products_for_subject(products_list: list, subject_key: str, limit: int) -> list[dict]:
    """Vráti komplementárne produkty k tomu, čo zákazník už má."""
    seen: set[str] = set()
    recommendations: list[dict] = []
    for query in ALREADY_HAVE_COMPLEMENT_QUERIES.get(subject_key, []):
        for product in cached_search_products(products_list, query, 3):
            key = product.get("id") or product.get("link") or product.get("title")
            if not key or key in seen:
                continue
            seen.add(key)
            recommendations.append(product)
            if len(recommendations) >= limit:
                return recommendations
            break
    return recommendations


MISSING_COMPOSITION_MARKERS = (
    "zlozenie chyba",
    "chyba zlozenie",
    "neviem najst zlozenie",
    "nemozem najst zlozenie",
    "zlozenie neni",
    "zlozenie nie je",
    "chyba mi zlozenie",
    "missing ingredients",
    "ingredients are missing",
    "cant find the ingredients",
    "cannot find the ingredients",
)


def is_missing_composition_complaint(message: str) -> bool:
    normalized_message = normalize(message)
    return any(marker in normalized_message for marker in MISSING_COMPOSITION_MARKERS)


def missing_composition_answer(lang: str = "sk") -> str:
    if lang == "en":
        return (
            "Sorry about that - some product pages may be missing the full ingredient list. "
            "Please contact our support team directly at eshop@foodland.sk or +421 2 4468 1527 "
            "and we will get you the composition for that specific product."
        )
    return (
        "Ospravedlňujeme sa, niektoré produkty môžu mať na stránke neúplne uvedené zloženie. "
        "Napíšte nám prosím priamo na eshop@foodland.sk alebo zavolajte na +421 2 4468 1527 "
        "a radi vám zloženie konkrétneho produktu doplníme."
    )


def detect_allergen_intent(message: str) -> str | None:
    normalized_message = normalize(message)
    is_product_safety_question = re.search(r"\b(je|su|obsahuje|neobsahuje|vhodn|bezpec)\b", normalized_message) is not None
    if "pozor na alerg" in normalized_message and not is_product_safety_question and not any(
        marker in normalized_message for marker in ("mam alerg", "alergiu na", "alergia na")
    ):
        return None
    direct_product_request = re.search(r"\b(chcem|dajte|ukazte|hladam|potrebujem|najdi)\b", normalized_message) is not None
    direct_product_terms = (
        "kokosove mlieko",
        "ryzove rezance",
        "tofu",
        "nori",
        "sushi ryza",
        "gochujang",
        "kimchi",
    )
    if direct_product_request and any(term in normalized_message for term in direct_product_terms) and any(
        marker in normalized_message for marker in ("pozor na alerg", "neznasam", "nesedia")
    ):
        return None
    # Recept query bez explicitnej alergenicke otazky -> nie je allergen intent
    _allergen_explicit = ("alerg", "intoler", "bezlepk", "bez soj", "bez lakt", "celiak")
    if "recept" in normalized_message and not any(e in normalized_message for e in _allergen_explicit):
        return None
    if any(term in normalized_message for term in ("rybi", "rybac")) and "omack" in normalized_message and any(
        marker in normalized_message for marker in ("nahrad", "alternativ")
    ):
        return None
    if ("celiak" in normalized_message or "vhodn" in normalized_message) and any(
        term in normalized_message for term in ("bez lepku", "bezlepk", "celiak")
    ):
        return "lepok"
    if "vegan" in normalized_message and (
        re.search(r"\b(je|su)\b.*\bvegan", normalized_message) is not None
        or any(marker in normalized_message for marker in ("vhodn", "zlozen"))
    ):
        return "vhodnost pre veganov"
    if "lepk" in normalized_message and any(marker in normalized_message for marker in ("tamari", "bezpec", "pri lepk")):
        return "lepok"
    gluten_free_product_search = is_gluten_free_search(normalized_message)
    asks_if_gluten_free = gluten_free_product_search and (
        re.search(r"\b(je|su|mate|obsahuje)\b.*\bbez lepku\b", normalized_message) is not None
    )
    if asks_if_gluten_free:
        return "lepok"

    if gluten_free_product_search and not any(
        marker in normalized_message
        for marker in ("alerg", "alergen", "intoler", "celiak", "obsahuje", "neobsahuje", "zlozen")
    ):
        return None

    if gluten_free_product_search and any(
        phrase in normalized_message
        for phrase in ("sojova omacka", "sojovu omacku", "sojovka", "tamari")
    ):
        return None

    if "bezlepk" in normalized_message:
        return "lepok"

    # Real user report: "ma to lepok?" (bare "has X allergen" question
    # using "ma/je/su" instead of "obsahuje"/"vhodn"/"alerg"...) fell
    # through the marker gate below entirely - ALLERGEN_INTENT_MARKERS
    # only recognizes explicit safety-framing words, not a plain named
    # allergen term paired with a "has" verb. Bypass the gate when both
    # are present, but only for unambiguous allergen vocabulary - not
    # generic grocery nouns from ALLERGEN_TERMS like "mlieko"/"ryb"/
    # "vajc"/"orech" that are also just plain product words ("aku ma
    # chut toto mlieko" is a taste question, not an allergen question).
    allergen_question_verb = re.search(r"\b(ma|maju|je|su)\b", normalized_message) is not None
    if not any(marker in normalized_message for marker in ALLERGEN_INTENT_MARKERS) and not (
        allergen_question_verb and any(term in normalized_message for term in BARE_ALLERGEN_QUESTION_TERMS)
    ):
        return None

    for term, label in ALLERGEN_TERMS.items():
        if term in normalized_message:
            return label

    if "intoler" in normalized_message or "zlozen" in normalized_message:
        return "alergeny"

    if "alerg" in normalized_message or "alergen" in normalized_message or "allerg" in normalized_message:
        return "alergény"

    return None


def detect_out_of_domain(message: str) -> bool:
    normalized_message = normalize(message)
    return any(marker in normalized_message for marker in OUT_OF_DOMAIN_MARKERS)


def is_category_discovery_query(message: str) -> bool:
    normalized_message = normalize(message).strip().rstrip("?!.")
    return normalized_message in CATEGORY_DISCOVERY_MARKERS


def top_product_categories(products_list: list[Product] | list[dict], limit: int = 8) -> list[str]:
    counts: Counter = Counter()
    for product in products_list:
        raw_type = product_field(product, "product_type", "")
        first_segment = raw_type.split(">")[0].strip() if raw_type else ""
        if first_segment and normalize(first_segment) not in CATEGORY_DISCOVERY_NOISE:
            counts[first_segment] += 1
    return [name for name, _ in counts.most_common(limit)]


def category_discovery_answer(products_list: list[Product] | list[dict], lang: str = "sk") -> str:
    categories = top_product_categories(products_list, 8)
    if not categories:
        return (
            "Foodland.sk offers a wide range of Asian and international groceries. "
            "Tell me what you are looking for, or browse the full catalog on Foodland.sk."
            if lang == "en"
            else "Foodland.sk ponúka široký sortiment ázijských a svetových potravín. "
            "Napíšte mi, čo konkrétne hľadáte, alebo si prezrite celý katalóg na Foodland.sk."
        )
    listed = ", ".join(categories)
    if lang == "en":
        return f"Foodland.sk carries many categories, for example: {listed} and more. Tell me what you are looking for and I will suggest specific products."
    return f"Foodland.sk ponúka široký sortiment naprieč mnohými kategóriami, napríklad: {listed} a ďalšie. Napíšte mi, čo konkrétne hľadáte, a poradím vám konkrétne produkty."


def allergen_product_matches(message: str, limit: int) -> list[dict]:
    query = allergen_product_query(message)
    if not query:
        return []
    if query == "__gluten_free_sushi__":
        return special_products_for_subject(products, "gluten_free_sushi", limit)
    return cached_search_products(products, query, limit)


def allergen_product_query(message: str) -> str:
    normalized_message = normalize(message)
    if "bez soj" in normalized_message or "bez soja" in normalized_message:
        return ""
    if ("celiak" in normalized_message or "bez lepku" in normalized_message or "bezlepk" in normalized_message) and (
        "sushi" in normalized_message or "susi" in normalized_message
    ):
        return "__gluten_free_sushi__"
    if "gochu jang" in normalized_message or "gochudzang" in normalized_message or "gochudang" in normalized_message:
        return "gochujang"

    known_product_queries = (
        "bezlepkova sojova omacka",
        "sushi ryza",
        "gochujang",
        "kimchi",
        "tamari",
        "miso pasta",
        "miso",
        "kokosove mlieko",
        "sezamovy olej",
        "ryzovy ocot",
        "nori",
        "wakame",
        "tofu",
        "sriracha",
        "ramen",
        "ramyun",
        "udon",
        "panko",
        "ssamjang",
        "sambal",
        "hoisin",
        "sojova omacka",
        "rybacia omacka",
        "ryzove rezance",
        "ryzovy papier",
        "mochi",
        "wasabi",
    )
    for product_query in known_product_queries:
        if product_query in normalized_message:
            return product_query

    # V2.18d.3 (C2 allergen-safety product leakage): a general allergen
    # question with no explicitly named product above must never fall back
    # to a free-text catalog search built from whatever text is left after
    # stripping a hand-maintained list of exact phrases - a single typo or
    # word-order change breaks that exact-string matching (the residual
    # text, sometimes still containing the allergen term itself, then
    # became a live product query - e.g. "arasiidy" fuzzy-matched real
    # peanut products). Returning "" here is the same deliberate
    # zero-safe-product signal as the branches above, universally, for
    # every case not already recognized as one of the specific named
    # products handled earlier in this function.
    return ""


def is_generic_allergen_recommendation_tail(normalized_text: str) -> bool:
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", normalized_text)
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return True
    generic_markers = (
        "co by ste odporucili",
        "co odporucate",
        "co odporucas",
        "co by ste doporucili",
        "co by ste dopurucili",
        "co doporucujete",
        "co dopurucujete",
        "poradite",
        "poradis",
        "ake produkty",
        "co mam kupit",
        "co si mam kupit",
        "co ma kupit",
        "co si ma kupit",
    )
    if any(marker in cleaned for marker in generic_markers):
        return True
    generic_words = {
        "co",
        "by",
        "ste",
        "mi",
        "prosim",
        "odporucili",
        "odporucate",
        "odporucas",
        "doporucili",
        "doporucujete",
        "dopurucili",
        "dopurucujete",
        "poradite",
        "poradis",
        "kupit",
        "produkty",
    }
    tokens = set(cleaned.split())
    return bool(tokens) and tokens <= generic_words


def is_gluten_free_search(message_or_normalized: str) -> bool:
    normalized_message = normalize(message_or_normalized)
    return (
        "bezlepk" in normalized_message
        or "bez lepku" in normalized_message
        or "bezlepkova" in normalized_message
    )


def product_is_gluten_free(product: Product | dict) -> bool:
    """V2.16c - same catalog-derived signal app.taxonomy._DIETARY_CATEGORY_
    TERMS/app.query_constraints._DIETARY_QUERY_STEMS already use for
    gluten_free (product_type breadcrumb contains "Bezlepkove potraviny"),
    reused here rather than re-derived, for the replacement_products
    gluten-free candidate filter. Deliberately does NOT have a vegan/
    vegetarian counterpart - that breadcrumb mapping was proven unreliable
    and removed in V2.16b (a real chicken product was tagged "vegan")."""
    product_type = product.get("product_type") if isinstance(product, dict) else getattr(product, "product_type", "")
    return "bezlepkov" in normalize(str(product_type or ""))


def is_composition_caution_search(message: str) -> bool:
    normalized_message = normalize(message)
    return is_gluten_free_search(normalized_message) or any(
        marker in normalized_message for marker in ("zlozen", "obsahuje", "neobsahuje")
    )


def composition_caution_context(needs_composition_caution: bool) -> str:
    if not needs_composition_caution:
        return "Nie je potrebná."
    return "Pri bezlepkových otázkach alebo otázkach na zloženie odporuč overiť zloženie v detaile produktu."


ALLERGEN_TERM_EN_LABELS = {
    "sóju": "soy",
    "lepok": "gluten",
    "arašidy": "peanuts",
    "orechy": "nuts",
    "mlieko": "milk",
    "laktózu": "lactose",
    "vajcia": "eggs",
    "sezam": "sesame",
    "ryby": "fish",
    "mäkkýše": "shellfish",
    "krevety": "shrimp",
}


def allergen_safety_answer(allergen_term: str, lang: str = "sk") -> str:
    if lang == "en":
        if allergen_term in ("alergeny", "alerginy"):
            return (
                "I don't want to recommend the wrong product for allergens. "
                "Please check the ingredients on the specific product page, or tell us which product "
                "you'd like us to check."
            )
        if allergen_term in ("vhodnost pre veganov", "vhodnosť pre veganov"):
            return (
                "Got it, you're vegan. Foodland.sk carries several vegan-friendly products "
                "- plant-based sauces, coconut milk, tofu, tempeh, and more. "
                "Try using the filters, or tell us exactly what you're looking for."
            )
        term_en = ALLERGEN_TERM_EN_LABELS.get(allergen_term, allergen_term)
        return (
            f"For allergies or intolerance to {term_en}, I don't want to recommend a product by name alone. "
            "Please check the ingredients and allergens on the specific product page - the label is what matters. "
            "Send us the product name and we'll help you find its page on Foodland.sk."
        )
    if allergen_term in ("alergeny", "alerginy"):
        return (
            "Pri alergénoch vám nechcem odporučiť nesprávny produkt. "
            "Prosím overte zloženie v detaile konkrétneho produktu alebo nám napíšte názov produktu, "
            "ktorý chcete skontrolovať."
        )

    if allergen_term in ("vhodnost pre veganov", "vhodnosť pre veganov"):
        return (
            "Rozumiem, že ste vegán. V Foodland.sk máme viaceré produkty vhodné pre vegánov "
            "— rastlinné omáčky, kokosové mlieko, tofu, tempeh a iné. "
            "Odporúčam použiť filter alebo nám napísať čo konkrétne hľadáte."
        )
    return (
        f"Pri alergii alebo intolerancii na {allergen_term} vám nechcem odporučiť produkt len podľa názvu. "
        "Prosím overte zloženie a alergény v detaile konkrétneho produktu. Ak riešite konkrétny produkt, rozhodujúca je etiketa. "
        "Ak mi pošlete názov produktu, pomôžem vám nájsť jeho detail na Foodland.sk."
    )


def related_products_for_subject(products: list[Product], all_knowledge: dict, subject: str, limit: int) -> list[dict]:
    subject_query = normalize(subject)
    seen: set[str] = set()
    recommendations: list[dict] = []

    queries = RELATED_PRODUCT_QUERIES.get(subject, [])
    # If the first query is the subject's own name, gather as much real
    # stock as exists (capped generously) so the widget can page through
    # "Zobrazit viac" in batches - a customer asking about sake should keep
    # seeing more sake bottles, not cross-sell, until the category runs out.
    is_self_query = bool(queries) and normalize(queries[0]) == subject_query
    self_category_max = 20

    for index, query in enumerate(queries):
        is_self = index == 0 and is_self_query
        search_limit = self_category_max + 2 if is_self else 3
        max_from_this_query = self_category_max if is_self else 1
        taken_from_query = 0
        for product in cached_search_products(products, query, search_limit):
            title = normalize(product.get("title", ""))
            title_tokens = set(title.split())
            if not is_recipe_relevant_product(product, subject):
                continue
            if subject == "sushi" and "ryza" in title_tokens and {"sushi", "susi"} & title_tokens:
                continue
            if subject in {"kimchi", "gochujang"} and subject_query and subject_query in title:
                continue

            key = product.get("id") or product.get("link") or product.get("title")
            if not key or key in seen:
                continue

            seen.add(key)
            recommendations.append(product)
            taken_from_query += 1
            if not is_self and len(recommendations) >= limit:
                return recommendations
            if taken_from_query >= max_from_this_query:
                break
        if is_self and len(recommendations) >= limit:
            # category has enough of its own stock - never fall through to
            # cross-sell/companion queries below.
            return recommendations

    if recommendations:
        return recommendations

    # BUG-04 fallback: RELATED_PRODUCT_QUERIES has no entry (or no hits) for this
    # subject - use the CrossSell knowledge records (2 140 products) instead of
    # giving up.
    cross_sell_hits = search_knowledge(all_knowledge, subject, allowed_sections=("CrossSell",))
    for hit in cross_sell_hits.get("CrossSell", []):
        record = hit.get("record", {})
        product_name = first_record_value(record, ("Produkt", "product"))
        if subject and not replacement_subject_matches_product(subject, product_name):
            continue
        for index in range(1, 6):
            cross_sell_title = clean_cross_sell_title(record.get(f"Cross-sell {index}") or "")
            if not cross_sell_title:
                continue
            for product in cached_search_products(products, cross_sell_title, 2):
                if not is_recipe_relevant_product(product, subject):
                    continue
                key = product.get("id") or product.get("link") or product.get("title")
                if not key or key in seen:
                    continue
                seen.add(key)
                recommendations.append(product)
                if len(recommendations) >= limit:
                    return recommendations
                break

    return recommendations


def is_recipe_relevant_product(product: dict, subject: str | None = None) -> bool:
    text = normalize(" ".join(str(product.get(key, "")) for key in ("title", "product_type", "category", "description")))
    blocked_markers = (
        "podlozka",
        "sushi mat",
        "miska",
        "misky",
        "set ",
        "suprava",
        "palicky",
        "dekor",
        "ozdoby",
        "solarna",
        "macka stastia",
        "vonna tycinka",
        "ananasova cili",
    )
    if any(marker in text for marker in blocked_markers):
        return False

    snack_markers = ("krek", "snack", "pocky", "cukrik", "bonbon", "chips")
    subject_allows_snacks = subject in {"asian_snack", "azijske_dezerty", "mochi", "matcha", "bubble_tea", "mango_sticky_rice"}
    if not subject_allows_snacks and any(marker in text for marker in snack_markers):
        return False

    return True


def special_products_for_subject(products: list[Product], subject: str, limit: int) -> list[dict]:
    seen: set[str] = set()
    recommendations: list[dict] = []
    excluded_terms = SPECIAL_PRODUCT_EXCLUDE_TERMS.get(subject, ())

    for query in SPECIAL_PRODUCT_QUERIES.get(subject, []):
        for product in cached_search_products(products, query, 5):
            title = normalize(product.get("title", ""))
            if excluded_terms and any(term in title for term in excluded_terms):
                continue

            key = product.get("id") or product.get("link") or product.get("title")
            if not key or key in seen:
                continue

            seen.add(key)
            recommendations.append(product)
            if len(recommendations) >= limit:
                return recommendations
            break

    return recommendations


def readable_subject_label(subject: str | None) -> str:
    if not subject:
        return "tejto teme"
    labels = {
        "sojova_omacka": "sójovej omáčke",
        "kimchi": "kimchi",
        "gochujang": "gochujangu",
        "sushi": "sushi",
        "ramen": "ramenu",
        "pho": "pho",
        "pad_thai": "pad thai",
        "miso": "miso paste",
        "tofu": "tofu",
        "kokosove_mlieko": "kokosovému mlieku",
        "ryzove_rezance": "ryžovým rezancom",
    }
    return labels.get(subject, subject.replace("_", " "))


def readable_subject_label_en(subject: str | None) -> str:
    if not subject:
        return "this topic"
    labels = {
        "sojova_omacka": "soy sauce",
        "kimchi": "kimchi",
        "gochujang": "gochujang",
        "sushi": "sushi",
        "ramen": "ramen",
        "pho": "pho",
        "pad_thai": "pad thai",
        "miso": "miso paste",
        "tofu": "tofu",
        "kokosove_mlieko": "coconut milk",
        "ryzove_rezance": "rice noodles",
    }
    return labels.get(subject, subject.replace("_", " "))


def compact_product_titles(matches: list[dict], limit: int = 3) -> str:
    titles = []
    for product in matches[:limit]:
        title = " ".join(str(product.get("title") or "").split())
        if title:
            titles.append(title)
    return "; ".join(titles)


def fallback_answer(
    matches: list[dict],
    knowledge_matches: dict | None = None,
    related_subject: str | None = None,
    needs_composition_caution: bool = False,
    lang: str = "sk",
    is_product_advice: bool = False,
) -> str:
    knowledge_matches = knowledge_matches or {}
    faq_answer = best_faq_answer(knowledge_matches)
    if faq_answer and not matches:
        return faq_answer

    if lang == "en":
        if matches:
            count = min(len(matches), 5)
            caution = (
                " For gluten-free products or ingredient questions, please check the composition on the product page."
                if needs_composition_caution
                else ""
            )
            titles = compact_product_titles(matches)
            if related_subject and not is_product_advice:
                subject_label = readable_subject_label_en(related_subject)
                if titles:
                    return (
                        f"For {subject_label}, I'd mainly recommend these related products: {titles}. "
                        f"See the recommendations below, sorted by relevance.{caution}"
                    )
                return f"I found {count} related products and ingredients that go well with {subject_label}.{caution}"
            if knowledge_matches:
                if titles:
                    return f"I found suitable products for this question: {titles}. See details and availability below.{caution}"
                return f"I found {count} suitable products and added recommendations from the Foodland assistant.{caution}"
            if titles:
                return f"I found these most relevant products: {titles}. More recommendations are below.{caution}"
            return f"I found {count} suitable products. See the recommendations below.{caution}"

        if knowledge_matches:
            return "I found related information in the Foodland assistant."

        return "I couldn't find an exact answer. Try rephrasing your question."

    if matches:
        count = min(len(matches), 5)
        caution = (
            " Pri bezlepkových produktoch alebo otázkach na zloženie si prosím overte zloženie v detaile produktu."
            if needs_composition_caution
            else ""
        )
        titles = compact_product_titles(matches)
        if related_subject and not is_product_advice:
            subject_label = readable_subject_label(related_subject)
            if titles:
                return (
                    f"K {subject_label} odporúčam hlavne tieto súvisiace produkty: {titles}. "
                    f"Pozrite si odporúčania nižšie, zoradila som ich podľa relevantnosti.{caution}"
                )
            return f"Našla som {count} súvisiacich produktov a surovín, ktoré sa hodia k {subject_label}.{caution}"
        if knowledge_matches:
            if titles:
                return f"Našla som vhodné produkty k tejto otázke: {titles}. Detail a dostupnosť si pozrite nižšie.{caution}"
            return f"Našla som {count} vhodných produktov a doplnila som odporúčania z Foodland poradkyne.{caution}"
        if titles:
            return f"Našla som tieto najrelevantnejšie produkty: {titles}. Ďalšie odporúčania sú nižšie.{caution}"
        return f"Našla som {count} vhodných produktov. Pozrite si odporúčania nižšie.{caution}"

    if knowledge_matches:
        return "Našla som súvisiace informácie vo Foodland poradkyni."

    return "Nenašla som presnú odpoveď. Skúste otázku napísať trochu inak."


@app.on_event("startup")
async def start_feed_refresh_loop() -> None:
    global feed_refresh_task
    refresh_minutes = int(os.getenv("FEED_REFRESH_MINUTES", "0"))
    if refresh_minutes > 0:
        logger.info("Starting feed refresh loop every %s minutes.", refresh_minutes)
        feed_refresh_task = asyncio.create_task(feed_refresh_loop(refresh_minutes))


async def feed_refresh_loop(refresh_minutes: int) -> None:
    """Periodicky obnovi produktovy feed a prebuduje knowledge databazu."""
    global last_feed_refresh_error
    while True:
        await asyncio.sleep(refresh_minutes * 60)
        # asyncio.to_thread() cannot be cancelled - a wait_for() timeout only
        # abandons the Task, the underlying thread keeps mutating global state
        # and finishes on its own. Shield it so a slow-but-eventually-successful
        # refresh still triggers the knowledge rebuild instead of being skipped.
        refresh_task = asyncio.ensure_future(asyncio.to_thread(refresh_feed))
        try:
            await asyncio.wait_for(asyncio.shield(refresh_task), timeout=90.0)
        except asyncio.TimeoutError:
            logger.warning("Feed refresh still running after 90s, waiting for it to finish in the background.")
            try:
                await refresh_task
            except Exception as exc:
                last_feed_refresh_error = str(exc)
                logger.error("Feed refresh failed: %s", exc, exc_info=True)
                continue
        except Exception as exc:
            last_feed_refresh_error = str(exc)
            logger.error("Feed refresh failed: %s", exc, exc_info=True)
            continue

        try:
            await asyncio.wait_for(rebuild_knowledge_from_feed(), timeout=300.0)
        except asyncio.TimeoutError:
            logger.error("Knowledge rebuild timed out after 300s.")
        except Exception as exc:
            logger.error("Knowledge rebuild failed: %s", exc, exc_info=True)


@app.on_event("startup")
async def start_learning_cycle_loop() -> None:
    global learning_cycle_task
    if _LEARNING_CYCLE_MINUTES > 0 and _LEARNING_ENGINE_ENABLED:
        logger.info("Starting learning cycle loop every %s minutes.", _LEARNING_CYCLE_MINUTES)
        learning_cycle_task = asyncio.create_task(learning_cycle_loop(_LEARNING_CYCLE_MINUTES))


async def learning_cycle_loop(cycle_minutes: int) -> None:
    """Off the customer request path (Section 102) - same asyncio-loop-
    in-the-web-process pattern as feed_refresh_loop above, since this
    repo has no separate scheduler infrastructure (Section 9 audit).
    A learning-cycle failure is logged and skipped, never raised past
    this loop (Section 100 - it must never affect customer search)."""
    while True:
        await asyncio.sleep(cycle_minutes * 60)
        known_product_ids = frozenset(p.id for p in products)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(_run_learning_cycle, known_product_ids=known_product_ids),
                timeout=280.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Learning cycle still running after 280s, will retry next interval.")
        except Exception as exc:
            logger.error("Learning cycle failed: %s", exc, exc_info=True)


def refresh_feed() -> None:
    """Nacita produkty zo vsetkych jazykovych mutacii feedu (SK/CZ/DE/EN/HU/PL)."""
    global products, product_snapshot, translation_index, product_taxonomy_index, taxonomy_concept_index, normalized_product_index
    global last_feed_refresh_at, last_feed_refresh_error, recipe_graph_index

    lang_feeds = load_multilang_feeds()
    new_products = lang_feeds.get('sk', [])
    new_translation_index = multilang_translation_index(lang_feeds)
    if not new_products:
        # load_multilang_feeds() swallows per-language fetch errors and
        # just omits the key (network blip, HTTP error, malformed XML) -
        # no exception reaches feed_refresh_loop()'s try/except in that
        # case. Without this guard an empty SK feed silently wiped the
        # live product catalog to [] and every /chat query would answer
        # "no products found" until the next successful refresh.
        last_feed_refresh_error = "SK feed returned 0 products; keeping previous catalog."
        logger.error(last_feed_refresh_error)
        return
    # Built from new_products before the global swap, so a taxonomy bug
    # can never leave `products` and `product_taxonomy_index` out of sync
    # (V2.1 taxonomy foundation - failure isolated per-product inside
    # build_taxonomy_index(), never wipes a healthy catalog).
    new_taxonomy_index = build_taxonomy_index(new_products)
    products = new_products
    product_snapshot = build_product_snapshot(new_products)
    translation_index = new_translation_index
    product_taxonomy_index = new_taxonomy_index
    taxonomy_concept_index = build_concept_index(new_taxonomy_index)
    normalized_product_index = normalize_catalog(new_products)
    # V2.8 - atomic rebuild alongside the taxonomy/normalized indexes it
    # depends on (Section 66); uses the current `knowledge` global, same as
    # every other feed-refresh-driven index here.
    recipe_graph_index = _build_recipe_graph_index(
        products=new_products,
        taxonomy_index=new_taxonomy_index,
        normalized_index=normalized_product_index,
        recipe_shopping_core_queries=RECIPE_SHOPPING_CORE_QUERIES,
        missing_ingredients_by_subject=MISSING_INGREDIENTS_BY_SUBJECT,
        recipe_title_product_subjects=RECIPE_TITLE_PRODUCT_SUBJECTS,
        cms_recipes=knowledge.get("sections", {}).get("Recipes", []),
        products_ai=knowledge.get("sections", {}).get("Products_AI", []),
        special_product_queries=SPECIAL_PRODUCT_QUERIES,
        catalog_version=int(last_feed_refresh_at or 0),
    )
    warm_search_indexes(new_products)
    clear_product_search_cache()
    last_feed_refresh_at = int(time.time())
    last_feed_refresh_error = None
    logger.info(
        "Feed refreshed: %d products, langs=%s",
        len(products),
        list(new_translation_index.keys()),
    )


async def rebuild_knowledge_from_feed() -> None:
    """Prebuduje knowledge.json z aktualnych produktov a ulozi na disk."""
    global knowledge, product_snapshot
    knowledge_path = os.getenv("KNOWLEDGE_JSON_PATH", "data/knowledge.json")
    openai_client = _get_openai_client()

    logger.info("Starting knowledge rebuild from feed (%d products)...", len(products))
    new_knowledge, new_snapshot = await asyncio.to_thread(
        build_knowledge,
        products,
        knowledge,
        old_snapshot=product_snapshot,
        translation_index=translation_index,
        openai_client=openai_client,
    )
    await asyncio.to_thread(save_knowledge, new_knowledge, knowledge_path)
    knowledge = new_knowledge
    product_snapshot = new_snapshot
    logger.info("Knowledge rebuilt successfully: %s", new_knowledge.get("counts", {}))
