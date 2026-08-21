"""
app/workflow_executor.py  -  canonical execution boundary.

V2.13c migrated RESULTSET_CONTINUATION and ALLERGEN_SAFETY - the two
workflows that are (a) already causally decided by app.workflow_resolver
(Invariant #1 - resolver decides, executor executes) AND (b) fully
self-contained, with zero dependency on the special_subject/
related_subject cascade or the shared matches -> structured_presentation
-> answer-composition pipeline the remaining legacy branches run
through.

V2.13d migrates the six OTHER fully self-contained, immediate-return
branches that were never actually coupled to that shared pipeline
either (docs/workflow-inventory-v2.13c.md's classification of these as
requiring "big-bang" extraction was over-cautious once the actual code
was re-read line-by-line for V2.13d - each is a clean, independent
early return, no different in shape from ALLERGEN_SAFETY):
missing_composition, FAQ, random_recipe, reset, out_of_domain,
category_discovery. None of these correspond to a distinct
app.workflow_resolver output - WorkflowResolver only distinguishes 4
values (RESULTSET_CONTINUATION, ALLERGEN_SAFETY, RELATED_PRODUCTS,
LEGACY_FALLBACK); these six are internal sub-cases of LEGACY_FALLBACK,
dispatched by app.main._chat_impl() the same way it always was - V2.13d
moves their EXECUTION into this module without inventing new resolver
granularity WorkflowResolver doesn't actually have evidence for
(Invariant #12 of the V2.13d spec - no new routing heuristics).

Recipe (recipe_subject + the recipe-followup/ordinal-reference/orphaned-
followup pre-checks immediately before it) and the remaining commerce
matches-dispatch cascade (already_have_subject/special_subject bundles/
replacement_subject/article_product_subject/cross_sell fallback/plain
related_subject/product_search, all sharing one ~250-line downstream
presentation pipeline) are NOT migrated in V2.13d - see
docs/workflow-migration-v2.13d.md for the evidenced reasoning
(BLOCKED_WITH_REASON, not silently skipped).

V2.13e migrates recipe execution (execute_recipe(), see
docs/recipe-state-machine-v2.13e.md for the full state-machine audit).
The recipe-followup/ordinal-reference/orphaned-followup PRE-CHECKS stay
inline in app.main._chat_impl() - direct code tracing showed the
ordinal-reference and orphaned-followup blocks are NOT recipe-specific
at all (they are general session-continuity clarification fallbacks
that merely check recipe state as part of their own gating condition to
avoid double-handling a turn recipe already resolved). Only the two
genuinely recipe-specific TERMINAL blocks - the main recipe_subject
handler and the recipe_followup_result handler - are recipe execution
in the WorkflowExecutor sense, and they are proven mutually exclusive
with the ordinal/orphaned-followup blocks by construction (their gating
conditions are pairwise disjoint), so combining them into one function
called immediately after the pre-check setup, ahead of the ordinal/
orphaned-followup blocks, is behaviorally identical to the original
interleaved order - not a reordering that changes what can fire when.

WorkflowResult is intentionally `dict[str, Any]`, not a new wrapper
class - same reasoning as app.advisor_engine.AdvisorResponse (V2.13a):
these handlers already produce the exact, stable /chat response shape
~40+ existing call sites depend on, with no downstream presentation
stage to hand an intermediate object to. Wrapping and immediately
unwrapping it would be ceremony, not architecture (Invariant #13 of the
V2.13c spec - smallest correct abstraction).

Handlers import app.main lazily, inside the function body, not at
module load time - the same technique app.advisor_engine.AdvisorEngine.run()
already uses. app.main imports THIS module at load time to register the
dispatch table, so a module-level `from app.main import ...` here would
be a circular import. A deferred import is safe because by the time a
handler is actually CALLED, app.main has already finished loading.

IMPORTANT - log_question() gating: app.main._chat_impl() does not call
the module-level log_question() directly. It locally rebinds the name
(`log_question = _real_log_question if execution_context.emit_customer_analytics
else (lambda *a, **k): None`) once near the top of the function, so
every one of its ~13 call sites is gated for free without touching each
one individually. That local rebinding is scoped to _chat_impl()'s own
function body in Python - it does NOT follow the call across a module
boundary. A handler here calling `m.log_question(...)` therefore always
hits the REAL, unconditional module-level function regardless of
execution_context, silently defeating the suppression that keeps
EVALUATION/LEARNING/SHADOW/ADMIN_TEST traffic out of
question_analytics.jsonl (V2.12.1's customer/internal separation).
Caught by tests/test_execution_context.py's
TestExecutionContextSuppressesCustomerAnalytics suite, which exercises
a query that reaches these handlers under non-customer contexts - not
by inspection, and not something "verbatim code motion" caught on its
own, since the bug is specifically that the move CHANGES which
log_question a bare call resolves to. Every handler below that logs a
question takes emit_customer_analytics explicitly and gates its own
m.log_question(...) call on it, matching _chat_impl()'s original
behavior exactly.
"""
from __future__ import annotations

import time
from typing import Any

WorkflowResult = dict[str, Any]

WORKFLOW_RESULTSET_CONTINUATION = "RESULTSET_CONTINUATION"
WORKFLOW_ALLERGEN_SAFETY = "ALLERGEN_SAFETY"


def execute_resultset_continuation(
    *,
    chat_request: Any,
    memory_key: str,
    profile_key: str,
    memory: dict,
    user_profile: dict,
    products: list,
    active_result_set_id: str,
    wants_show_all: bool,
) -> WorkflowResult | None:
    """V2.5 Show More/Show All, formalized as an executor handler
    (V2.13c) - unchanged logic, moved verbatim from its former inline
    location in app.main._chat_impl(). Returns None if the ResultSet
    has since expired/rotated (catalog changed), in which case the
    caller falls through to the normal legacy cascade exactly as before
    - this is not a new fallback contract, just the same one made
    explicit. Does not call log_question() at all in the original code
    - no emit_customer_analytics gating needed here."""
    import app.main as m

    active_result_set = m._get_result_set(active_result_set_id, time.time())
    if active_result_set is None or active_result_set.catalog_version != id(products):
        return None
    revealed_ids = active_result_set.remaining_ids() if wants_show_all else active_result_set.next_page_ids()
    if wants_show_all:
        m._show_all_result_set(active_result_set)
    else:
        m._advance_displayed_count(active_result_set, active_result_set.page_size)
    revealed_products = m._format_result_set_products(products, revealed_ids)
    revealed_products = m.personalize_products(revealed_products, user_profile)
    m.update_session_memory(memory_key, chat_request.message, "product_search", revealed_products, [], {})
    updated_profile = m.update_user_memory(profile_key, chat_request.message, "product_search", revealed_products, [])
    return {
        "answer": m._compose_continuation_answer(active_result_set, len(revealed_products)),
        "products": revealed_products,
        "matching_total": active_result_set.matching_total,
        "displayed_count": active_result_set.displayed_count,
        "has_more": active_result_set.has_more,
        "result_set_id": active_result_set.result_set_id,
        "answer_strategy": active_result_set.answer_strategy,
        "memory": m.public_user_memory_summary(updated_profile),
        "intent": "product_search",
        "response_mode": "result_set_continuation",
    }


def execute_allergen_safety(
    *,
    chat_request: Any,
    memory_key: str,
    profile_key: str,
    user_profile: dict,
    knowledge_matches: dict,
    articles: list,
    allergen_term: str | None,
    client_key: str,
    session_id: str,
    query_language: str,
    emit_customer_analytics: bool,
) -> WorkflowResult:
    """V2.13b's ALLERGEN_SAFETY branch, formalized as an executor
    handler (V2.13c) - unchanged logic, moved verbatim from its former
    inline location. The WorkflowResolver decision (safety has the
    highest precedence, Invariant #6/#7 - frozen) is made by the caller
    BEFORE this handler is invoked; this handler only executes it."""
    import app.main as m

    allergen_matches = m.allergen_product_matches(chat_request.message, chat_request.limit)
    allergen_matches = m.personalize_products(allergen_matches, user_profile)
    m.update_session_memory(memory_key, chat_request.message, "allergen_safety", allergen_matches, [], knowledge_matches)
    updated_profile = m.update_user_memory(profile_key, chat_request.message, "allergen_safety", allergen_matches, [])
    _ci = m.build_customer_intent(
        chat_request.message, "allergen_safety",
        allergen_constraints=[allergen_term] if allergen_term else None,
        language=query_language,
    )
    if emit_customer_analytics:
        m.log_question(chat_request.message, client_key, len(allergen_matches), intent="allergen_safety", session_id=session_id, primary_intent=_ci.primary_intent, subject=_ci.subject or "")
    return {
        "answer": m.allergen_safety_answer(allergen_term, query_language),
        "products": allergen_matches,
        "articles": articles,
        "knowledge": m.knowledge_summary(knowledge_matches),
        "memory": m.public_user_memory_summary(updated_profile),
        "intent": "allergen_safety",
    }


def execute_missing_composition(
    *,
    chat_request: Any,
    memory_key: str,
    profile_key: str,
    articles: list,
    knowledge_matches: dict,
    client_key: str,
    session_id: str,
    query_language: str,
    emit_customer_analytics: bool,
) -> WorkflowResult:
    """V2.13d - moved verbatim from its former inline location."""
    import app.main as m

    m.update_session_memory(memory_key, chat_request.message, "missing_composition", [], [], knowledge_matches)
    updated_profile = m.update_user_memory(profile_key, chat_request.message, "missing_composition", [], [])
    _ci = m.build_customer_intent(chat_request.message, "missing_composition", language=query_language)
    if emit_customer_analytics:
        m.log_question(chat_request.message, client_key, 0, intent="missing_composition", session_id=session_id, primary_intent=_ci.primary_intent, subject=_ci.subject or "")
    return {
        "answer": m.missing_composition_answer(query_language),
        "products": [],
        "articles": articles,
        "knowledge": m.knowledge_summary(knowledge_matches),
        "memory": m.public_user_memory_summary(updated_profile),
        "intent": "missing_composition",
    }


def execute_faq(
    *,
    chat_request: Any,
    memory_key: str,
    profile_key: str,
    articles: list,
    knowledge_matches: dict,
    client_key: str,
    session_id: str,
    query_language: str,
    faq_answer: str,
    emit_customer_analytics: bool,
) -> WorkflowResult:
    """V2.13d - moved verbatim from its former inline location.
    faq_answer is passed in already-resolved (best_direct_faq_answer()
    or best_faq_answer()) since the caller must check it is truthy
    BEFORE deciding this workflow applies - not this handler's job to
    rediscover that (Invariant #4/#58 of the V2.13d spec: executors do
    not rediscover intent / do not re-enter the routing cascade)."""
    import app.main as m

    m.update_session_memory(memory_key, chat_request.message, "faq", [], [], knowledge_matches)
    updated_profile = m.update_user_memory(profile_key, chat_request.message, "faq", [], [])
    _ci = m.build_customer_intent(chat_request.message, "faq", language=query_language)
    if emit_customer_analytics:
        m.log_question(chat_request.message, client_key, 0, intent="faq", session_id=session_id, primary_intent=_ci.primary_intent, subject=_ci.subject or "")
    return {
        "answer": faq_answer,
        "products": [],
        "articles": articles,
        "knowledge": m.knowledge_summary(knowledge_matches),
        "memory": m.public_user_memory_summary(updated_profile),
        "intent": "faq",
    }


def execute_random_recipe(
    *,
    chat_request: Any,
    memory_key: str,
    profile_key: str,
    user_profile: dict,
    knowledge: dict,
    articles: list,
    knowledge_matches: dict,
    client_key: str,
    session_id: str,
    query_language: str,
    emit_customer_analytics: bool,
) -> WorkflowResult:
    """V2.13d - moved verbatim from its former inline location."""
    import app.main as m

    random_recipes = m.get_random_recipes_by_cuisine(knowledge, 3)
    random_recipes = m.personalize_recipes(random_recipes, user_profile)
    m.update_session_memory(memory_key, chat_request.message, "recipe", [], random_recipes, knowledge_matches)
    updated_profile = m.update_user_memory(profile_key, chat_request.message, "recipe", [], random_recipes)
    _ci = m.build_customer_intent(chat_request.message, "recipe", language=query_language)
    if emit_customer_analytics:
        m.log_question(chat_request.message, client_key, 0, intent="recipe", session_id=session_id, primary_intent=_ci.primary_intent, subject=_ci.subject or "")
    return {
        "answer": m.random_recipes_answer(random_recipes, query_language),
        "recipes": random_recipes,
        "products": [],
        "articles": articles,
        "knowledge": m.knowledge_summary(knowledge_matches),
        "memory": m.public_user_memory_summary(updated_profile),
        "intent": "recipe",
    }


def execute_reset(
    *,
    chat_request: Any,
    memory: dict,
    profile_key: str,
    client_key: str,
    session_id: str,
    query_language: str,
    emit_customer_analytics: bool,
) -> WorkflowResult:
    """V2.13d - moved verbatim from its former inline location.
    _apply_session_reset(memory) is the ENTIRE state-mutation side
    effect for this workflow - one call, exactly once (Invariant #10 of
    the V2.13d spec: one reset request, one state clear)."""
    import app.main as m

    m._apply_session_reset(memory)
    updated_profile = m.update_user_memory(profile_key, chat_request.message, "reset", [], [])
    if emit_customer_analytics:
        m.log_question(chat_request.message, client_key, 0, intent="reset", session_id=session_id, primary_intent="reset", subject="")
    return {
        "answer": (
            "Starting fresh - what are you looking for?"
            if query_language == "en"
            else "Začíname odznova - čo hľadáte?"
        ),
        "products": [],
        "knowledge": m.knowledge_summary({}),
        "memory": m.public_user_memory_summary(updated_profile),
        "intent": "reset",
    }


def execute_out_of_domain(
    *,
    chat_request: Any,
    memory_key: str,
    profile_key: str,
    knowledge_matches: dict,
    client_key: str,
    session_id: str,
    query_language: str,
    emit_customer_analytics: bool,
) -> WorkflowResult:
    """V2.13d - moved verbatim from its former inline location."""
    import app.main as m

    m.update_session_memory(memory_key, chat_request.message, "unknown", [], [], knowledge_matches)
    updated_profile = m.update_user_memory(profile_key, chat_request.message, "unknown", [], [])
    _ci = m.build_customer_intent(chat_request.message, "unknown", language=query_language)
    if emit_customer_analytics:
        m.log_question(chat_request.message, client_key, 0, intent="unknown", session_id=session_id, primary_intent=_ci.primary_intent, subject=_ci.subject or "")
    return {
        "answer": (
            "I can't reliably answer that as the Foodland assistant. Try asking about products, "
            "orders, delivery, or payment on Foodland.sk."
            if query_language == "en"
            else "Na toto neviem spoľahlivo odpovedať ako Foodland poradkyňa. Skúste sa opýtať na produkty, objednávku, dopravu alebo platbu na Foodland.sk."
        ),
        "products": [],
        "knowledge": m.knowledge_summary(knowledge_matches),
        "memory": m.public_user_memory_summary(updated_profile),
        "intent": "unknown",
    }


def execute_category_discovery(
    *,
    chat_request: Any,
    memory_key: str,
    profile_key: str,
    products: list,
    knowledge_matches: dict,
    client_key: str,
    session_id: str,
    query_language: str,
    emit_customer_analytics: bool,
) -> WorkflowResult:
    """V2.13d - moved verbatim from its former inline location."""
    import app.main as m

    m.update_session_memory(memory_key, chat_request.message, "category_discovery", [], [], knowledge_matches)
    updated_profile = m.update_user_memory(profile_key, chat_request.message, "category_discovery", [], [])
    _ci = m.build_customer_intent(chat_request.message, "category_discovery", language=query_language)
    if emit_customer_analytics:
        m.log_question(chat_request.message, client_key, 0, intent="category_discovery", session_id=session_id, primary_intent=_ci.primary_intent, subject=_ci.subject or "")
    return {
        "answer": m.category_discovery_answer(products, query_language),
        "products": [],
        "knowledge": m.knowledge_summary(knowledge_matches),
        "memory": m.public_user_memory_summary(updated_profile),
        "intent": "category_discovery",
    }


def execute_recipe(
    *,
    chat_request: Any,
    recipe_subject: str | None,
    recipe_followup_result: Any,
    contextual_message: str,
    knowledge: dict,
    knowledge_matches: dict,
    knowledge_sections: Any,
    articles: list,
    user_profile: dict,
    products: list,
    recipe_graph_index: Any,
    product_taxonomy_index: Any,
    normalized_product_index: Any,
    memory: dict,
    memory_key: str,
    profile_key: str,
    client_key: str,
    session_id: str,
    query_language: str,
    emit_customer_analytics: bool,
) -> WorkflowResult | None:
    """V2.13e - moved verbatim from its former two inline locations
    (docs/recipe-state-machine-v2.13e.md's "Block D" and "Block E").
    Returns None if neither recipe_subject nor recipe_followup_result
    applies, in which case the caller falls through to the unchanged
    ordinal-reference/orphaned-followup blocks exactly as before -
    proven behaviorally identical to the original interleaved order
    because those two blocks' gating conditions are pairwise disjoint
    with recipe_subject/recipe_followup_result (see the state-machine
    doc's mutual-exclusivity proof), not merely reordered by
    convenience.

    recipe_subject and recipe_followup_result are passed in already
    computed by the caller - this function does not rediscover them
    (Invariant #4/#40 of the V2.13e spec: the recipe engine resolves
    recipe-INTERNAL state transitions, it does not re-run global
    routing detection)."""
    import app.main as m

    if recipe_subject:
        recipes = m.recipe_results(knowledge_matches, chat_request.limit, contextual_message, knowledge)
        recipes = m.personalize_recipes(recipes, user_profile)
        recipes = m.prioritize_recipes_for_phrase(recipes, contextual_message)
        recipe_articles = (
            m.recipe_article_results(articles, contextual_message, knowledge, chat_request.limit)
            if "Magazine" in knowledge_sections
            else []
        )
        recipe_product_subject = m.recipe_related_product_subject(contextual_message, recipe_subject, recipes)
        recipe_products = (
            m.related_products_for_subject(products, knowledge, recipe_product_subject, max(chat_request.limit, 8))
            if m.wants_recipe_products(contextual_message) and recipe_product_subject
            else []
        )
        recipe_products = m.personalize_products(recipe_products, user_profile)
        if recipe_products and recipe_product_subject == "sushi":
            recipe_products = m.sushi_shopping_core_products(products, recipe_products, max(chat_request.limit, 8))
        if recipe_products and recipe_product_subject == "tom_yum":
            recipe_products = m.tom_yum_shopping_core_products(products, recipe_products, max(chat_request.limit, 8))
        if recipe_products and recipe_product_subject == "kimchi_ramen":
            recipe_products = m.kimchi_ramen_shopping_core_products(products, recipe_products, max(chat_request.limit, 8))
        recipe_shopping_plan = None
        if recipe_products and recipe_product_subject not in {"sushi", "tom_yum", "kimchi_ramen"}:
            if m.V2_STRUCTURED_RETRIEVAL_ENABLED and recipe_product_subject in recipe_graph_index.dishes_by_id:
                try:
                    recipe_shopping_plan = m._build_recipe_shopping_plan(
                        recipe_graph_index,
                        recipe_product_subject,
                        products,
                        product_taxonomy_index,
                        normalized_product_index,
                        servings=m._extract_requested_servings_lenient(chat_request.message),
                    )
                except Exception:
                    m.logger.warning("V2.8 recipe shopping plan failed for dish=%s", recipe_product_subject, exc_info=True)
                    recipe_shopping_plan = None
            if recipe_shopping_plan is not None:
                _products_by_id = {product.id: product for product in products}
                _plan_product_ids = [
                    ing.selected_product_id for ing in recipe_shopping_plan.ingredients if ing.selected_product_id
                ]
                recipe_products = [
                    m.format_product(_products_by_id[pid]) for pid in _plan_product_ids if pid in _products_by_id
                ]
            else:
                recipe_products = m.recipe_shopping_core_products(products, recipe_product_subject, recipe_products, max(chat_request.limit, 8))
        if recipe_shopping_plan is not None:
            m._set_active_recipe(memory, recipe_product_subject, recipe_shopping_plan.requested_servings)
        intent = "recipe_to_products" if recipe_products else "recipe"
        if recipe_products:
            m.annotate_recommendations(
                recipe_products,
                intent,
                related_subject=recipe_product_subject,
                query=contextual_message,
            )
        recipe_cart_candidates = m.cart_candidates_for_response(recipe_products, intent, recipe_product_subject)
        missing_ingredients = m.missing_ingredients_for_subject(recipe_product_subject, recipes)
        shopping_list = m.shopping_list_for_response(recipe_cart_candidates, missing_ingredients) if recipe_products else {}
        m.update_session_memory(memory_key, chat_request.message, intent, recipe_products, recipes, knowledge_matches)
        updated_profile = m.update_user_memory(profile_key, chat_request.message, intent, recipe_products, recipes)
        _ci = m.build_customer_intent(
            chat_request.message, intent,
            subject=recipe_subject, recipe=recipe_subject,
            use_case=recipe_product_subject or None,
            language=query_language,
        )
        if emit_customer_analytics:
            m.log_question(chat_request.message, client_key, 0, intent=intent, session_id=session_id, primary_intent=_ci.primary_intent, subject=_ci.subject or "")
        if recipe_products:
            recipe_answer_text = m.recipe_products_answer(recipe_product_subject, recipes, query_language)
        elif recipes:
            recipe_answer_text = m.recipe_answer(recipe_subject, recipes, query_language)
        else:
            recipe_answer_text = m.general_ai_recipe_answer(chat_request.message) or m.recipe_answer(recipe_subject, recipes, query_language)
        _recipe_workflow = m._select_workflow(m._RoutingSignals(
            message=chat_request.message,
            recipe_subject=recipe_subject,
            recipe_shopping_plan_used=recipe_shopping_plan is not None,
        ))
        return {
            "answer": recipe_answer_text,
            "recipes": recipes,
            "products": recipe_products,
            "articles": recipe_articles,
            "cart_candidates": recipe_cart_candidates,
            "missing_ingredients": missing_ingredients if recipe_products else [],
            "shopping_list": shopping_list,
            "knowledge": m.knowledge_summary(knowledge_matches),
            "memory": m.public_user_memory_summary(updated_profile),
            "intent": intent,
            "workflow_id": _recipe_workflow.workflow_id,
            "workflow_confidence": _recipe_workflow.confidence,
            "recipe_shopping_plan": m._summarize_recipe_shopping_plan(recipe_shopping_plan) if recipe_shopping_plan else None,
        }

    if recipe_followup_result is not None:
        _products_by_id = {product.id: product for product in products}
        if recipe_followup_result.kind == m._RF_INGREDIENT:
            _followup_products = [
                m.format_product(_products_by_id[pid])
                for pid in recipe_followup_result.candidate_product_ids
                if pid in _products_by_id
            ][: chat_request.limit]
        elif recipe_followup_result.kind == m._RF_SELECTED and recipe_followup_result.selected_product_id in _products_by_id:
            _followup_products = [m.format_product(_products_by_id[recipe_followup_result.selected_product_id])]
        elif recipe_followup_result.plan is not None:
            _remaining_ids = [
                ing.selected_product_id
                for ing in recipe_followup_result.plan.ingredients
                if ing.status == m._RF_STATUS_AVAILABLE and ing.selected_product_id
            ]
            _followup_products = [m.format_product(_products_by_id[pid]) for pid in _remaining_ids if pid in _products_by_id]
        else:
            _followup_products = []
        _followup_answer = m._compose_recipe_followup_answer(recipe_followup_result, recipe_graph_index, _products_by_id, query_language)
        m.update_session_memory(memory_key, chat_request.message, "recipe_to_products", _followup_products, [], knowledge_matches)
        updated_profile = m.update_user_memory(profile_key, chat_request.message, "recipe_to_products", _followup_products, [])
        if emit_customer_analytics:
            m.log_question(chat_request.message, client_key, 0, intent="recipe_to_products", session_id=session_id, primary_intent="recipe_to_products", subject=recipe_followup_result.dish_id)
        return {
            "answer": _followup_answer,
            "products": _followup_products,
            "articles": [],
            "recipe_shopping_plan": m._summarize_recipe_shopping_plan(recipe_followup_result.plan) if recipe_followup_result.plan else None,
            "knowledge": m.knowledge_summary(knowledge_matches),
            "memory": m.public_user_memory_summary(updated_profile),
            "intent": "recipe_to_products",
            "workflow_id": "RECIPE_SHOPPING",
            "workflow_confidence": 0.9,
        }

    return None


def execute_comparison(
    *,
    chat_request: Any,
    memory: dict,
    memory_key: str,
    profile_key: str,
    products: list,
    product_taxonomy_index: dict,
    client_key: str,
    session_id: str,
    query_language: str,
    emit_customer_analytics: bool,
) -> WorkflowResult | None:
    """V2.14b - docs/recommendation-comparison-v2.14b.md. Activates the
    V2.7 COMPARISON workflow_id (app.workflow_registry), previously
    SHADOW-only (labeled for analytics, never causally executed).

    Returns None when the message does not look like a comparison
    request at all (Section 8/19: no comparison language, no
    multi-ordinal reference) - the caller (app.main._chat_impl()) must
    then fall through to its normal cascade unchanged, exactly like
    execute_recipe()'s own None contract.

    When the message DOES look like a comparison request but target
    resolution is ambiguous (e.g. a bare cross-category two-brand
    query like "Kikkoman alebo Yamasa?"), this returns a real CLARIFY
    decision to the customer instead of silently deferring - Section
    39 Case G requires ambiguous targets to CLARIFY, not to be dropped.

    Deterministic end-to-end (Section 44): app.comparison never calls
    an LLM, and this handler adds none either - target resolution,
    evidence, decision, and answer composition are all computed from
    already-loaded catalog/taxonomy/session data.
    """
    import app.main as m
    from app.comparison import (
        ComparisonDecision,
        STATE_CLARIFY,
        compose_comparison_answer,
        decide_comparison,
        looks_like_comparison_request,
        resolve_comparison_goal,
        resolve_comparison_targets,
    )
    from app.recommendation_evidence import CONFIDENCE_INSUFFICIENT

    if not looks_like_comparison_request(chat_request.message):
        return None

    targets = resolve_comparison_targets(chat_request.message, memory, products)
    if targets is None:
        decision = ComparisonDecision(state=STATE_CLARIFY, goal="UNKNOWN", winner_product_id=None, confidence=CONFIDENCE_INSUFFICIENT)
        answer_text = compose_comparison_answer(decision, None, query_language)
        result_products: list = []
    else:
        goal = resolve_comparison_goal(chat_request.message)
        decision = decide_comparison(targets, goal, product_taxonomy_index=product_taxonomy_index)
        answer_text = compose_comparison_answer(decision, targets, query_language)
        result_products = [targets.product_a, targets.product_b]

    m.update_session_memory(memory_key, chat_request.message, "product_comparison", result_products, [], {})
    updated_profile = m.update_user_memory(profile_key, chat_request.message, "product_comparison", result_products, [])
    _ci = m.build_customer_intent(chat_request.message, "product_comparison", language=query_language)
    if emit_customer_analytics:
        m.log_question(
            chat_request.message, client_key, len(result_products), intent="product_comparison",
            session_id=session_id, primary_intent=_ci.primary_intent, subject=decision.state,
        )
    return {
        "answer": answer_text,
        "products": result_products,
        "articles": [],
        "knowledge": m.knowledge_summary({}),
        "memory": m.public_user_memory_summary(updated_profile),
        "intent": "product_comparison",
        "response_mode": "comparison",
        "workflow_id": "COMPARISON",
        "comparison_decision": decision.state,
        "comparison_goal": decision.goal,
        "comparison_confidence": decision.confidence,
    }
