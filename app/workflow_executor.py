"""
app/workflow_executor.py  -  V2.13c: canonical execution boundary.

Only two workflows qualify for migration this sprint:
RESULTSET_CONTINUATION and ALLERGEN_SAFETY. Both are (a) already
causally decided by app.workflow_resolver (Invariant #1 - resolver
decides, executor executes) AND (b) fully self-contained - they return
immediately, with zero dependency on the special_subject/related_subject
cascade or the ~250-line shared matches -> structured_presentation ->
answer-composition pipeline the remaining legacy branches (including
RELATED_PRODUCTS's own execution phase) still run through.

The remaining branches stay LEGACY_EXECUTION this sprint - see
docs/workflow-inventory-v2.13c.md for the full audit and
docs/workflow-migration-v2.13c.md for per-workflow migration status.
Extracting them would mean either duplicating that shared presentation
pipeline (forbidden - handlers must not duplicate presentation/ranking/
retrieval algorithms) or a much larger cross-cutting restructure of all
~11 legacy branches at once, which is exactly the big-bang rewrite this
sprint's own governing spec (Invariant #14, incremental migration only)
prohibits without extensive per-branch characterization coverage this
session does not yet have.

WorkflowResult is intentionally `dict[str, Any]`, not a new wrapper
class - same reasoning as app.advisor_engine.AdvisorResponse (V2.13a):
these two handlers already produce the exact, stable /chat response
shape ~40+ existing call sites depend on, with no downstream
presentation stage to hand an intermediate object to. Wrapping and
immediately unwrapping it would be ceremony, not architecture
(Invariant #13 - smallest correct abstraction, no plugin framework for
two handlers).

Handlers import app.main lazily, inside the function body, not at
module load time - the same technique app.advisor_engine.AdvisorEngine.run()
already uses. app.main imports THIS module at load time to register the
dispatch table, so a module-level `from app.main import ...` here would
be a circular import (Section 56 of the governing spec). A deferred
import is safe because by the time a handler is actually CALLED,
app.main has already finished loading.
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
    explicit."""
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
    m.log_question(chat_request.message, client_key, len(allergen_matches), intent="allergen_safety", session_id=session_id, primary_intent=_ci.primary_intent, subject=_ci.subject or "")
    return {
        "answer": m.allergen_safety_answer(allergen_term, query_language),
        "products": allergen_matches,
        "articles": articles,
        "knowledge": m.knowledge_summary(knowledge_matches),
        "memory": m.public_user_memory_summary(updated_profile),
        "intent": "allergen_safety",
    }
