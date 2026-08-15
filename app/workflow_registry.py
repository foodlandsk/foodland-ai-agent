"""
app/workflow_registry.py  -  V2.7 Workflow & Orchestration Migration

Formalizes the routing decisions app/main.py's chat() cascade already
makes into a stable, explicit vocabulary (Section 6): a WorkflowContract
per workflow_id, and a deterministic select_workflow() that LABELS which
workflow a turn belongs to from signals chat() has already computed - it
never re-detects intent itself (Section 4/7: workflows orchestrate
existing modules, they do not reimplement detection logic).

Migration status is explicit and honest (Section 39), not aspirational:

MIGRATED (this sprint) - PRODUCT_LOOKUP, CATEGORY_BROWSE, ATTRIBUTE_SEARCH:
    these three already run entirely through the V2.4-V2.6 structured
    pipeline (app.structured_search -> app.presentation -> app.cross_sell
    -> app.answer_composer) built across the last three sprints. V2.7's
    contribution for them is making that pipeline explicitly addressable
    as a workflow contract, not rewriting it (Section 4).

SHADOW (labeled, not yet re-routed) - USE_CASE_ADVICE, COMPARISON,
    REPLACEMENT, RECIPE_SHOPPING, FAQ_INFORMATIONAL: select_workflow()
    correctly identifies these turns and an analytics label is recorded,
    but the actual response is still produced by the existing, separately
    battle-tested app/main.py branches (recipe_results(), replacement
    logic, FAQ lookup, ...) - re-platforming five more legacy branches
    onto WorkflowContract in the same sprint the labeling layer was
    introduced is exactly the "one-shot rewrite" the spec forbids
    (Section 0/5/38/66/80). Section 20's shadow-mode-first requirement is
    satisfied by construction: the label is compared against actual
    behavior with zero risk of changing it.

LEGACY - ORDER_TRACKING, SUPPORT_ESCALATION: Foodland's current product
    surface has no order-tracking or support-escalation capability at all
    (confirmed by inspecting app/main.py - no order/ticket/complaint
    system exists to migrate). Listed in the registry per Section 6 for
    schema completeness, always LEGACY_FALLBACK in practice - Section 80
    forbids inventing capabilities that do not exist.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# --- stable workflow identifiers (Section 6) --------------------------------
PRODUCT_LOOKUP = "PRODUCT_LOOKUP"
CATEGORY_BROWSE = "CATEGORY_BROWSE"
ATTRIBUTE_SEARCH = "ATTRIBUTE_SEARCH"
USE_CASE_ADVICE = "USE_CASE_ADVICE"
COMPARISON = "COMPARISON"
REPLACEMENT = "REPLACEMENT"
RECIPE_SHOPPING = "RECIPE_SHOPPING"
FAQ_INFORMATIONAL = "FAQ_INFORMATIONAL"
ORDER_TRACKING = "ORDER_TRACKING"
SUPPORT_ESCALATION = "SUPPORT_ESCALATION"
LEGACY_FALLBACK = "LEGACY_FALLBACK"

MIGRATED = "MIGRATED"
SHADOW = "SHADOW"
LEGACY = "LEGACY"


@dataclass(frozen=True, slots=True)
class WorkflowContract:
    """Section 3 - what a workflow promises, not how it's implemented."""

    workflow_id: str
    migration_status: str
    supported_intents: tuple[str, ...]
    retrieval_strategy: str
    presentation_strategy: str
    cross_sell_policy: str  # "conservative" | "enabled" | "suppressed" | "disabled"
    grounding: str
    fallback_behavior: str


WORKFLOWS: dict[str, WorkflowContract] = {
    PRODUCT_LOOKUP: WorkflowContract(
        workflow_id=PRODUCT_LOOKUP,
        migration_status=MIGRATED,
        supported_intents=("product_lookup", "exact_sku_lookup"),
        retrieval_strategy="v2.4_structured_retrieval",
        presentation_strategy="EXACT_MATCH | NO_EXACT_MATCH",
        cross_sell_policy="conservative",  # V2.6 eligibility gate decides per-turn
        grounding="catalog_facts",
        fallback_behavior="legacy_lexical_search",
    ),
    CATEGORY_BROWSE: WorkflowContract(
        workflow_id=CATEGORY_BROWSE,
        migration_status=MIGRATED,
        supported_intents=("category_browse", "category_discovery"),
        retrieval_strategy="v2.4_structured_retrieval",
        presentation_strategy="GROUPED_DISCOVERY",
        cross_sell_policy="suppressed",  # Section 31 - too early for cross-sell
        grounding="catalog_facts",
        fallback_behavior="legacy_category_discovery_answer",
    ),
    ATTRIBUTE_SEARCH: WorkflowContract(
        workflow_id=ATTRIBUTE_SEARCH,
        migration_status=MIGRATED,
        supported_intents=("attribute_search",),
        retrieval_strategy="v2.4_structured_retrieval",
        presentation_strategy="FILTERED_PRODUCT_LIST",
        cross_sell_policy="conservative",
        grounding="catalog_facts",
        fallback_behavior="legacy_lexical_search",
    ),
    USE_CASE_ADVICE: WorkflowContract(
        workflow_id=USE_CASE_ADVICE,
        migration_status=SHADOW,
        supported_intents=("use_case_advice",),
        retrieval_strategy="v2.4_structured_retrieval",
        presentation_strategy="FILTERED_PRODUCT_LIST",
        cross_sell_policy="enabled",  # V2.6 USE_CASE_COMPLETION
        grounding="catalog_facts + verified_use_case_roles",
        fallback_behavior="legacy_related_subject_products",
    ),
    COMPARISON: WorkflowContract(
        workflow_id=COMPARISON,
        migration_status=SHADOW,
        supported_intents=("product_comparison",),
        retrieval_strategy="legacy_knowledge_search",
        presentation_strategy="COMPARISON",
        cross_sell_policy="suppressed",  # Section 14/38
        grounding="knowledge_facts",
        fallback_behavior="legacy_faq_answer",
    ),
    REPLACEMENT: WorkflowContract(
        workflow_id=REPLACEMENT,
        migration_status=SHADOW,
        supported_intents=("replacement", "alternative_lookup"),
        retrieval_strategy="legacy_alternative_products_for_subject",
        presentation_strategy="FILTERED_PRODUCT_LIST",
        cross_sell_policy="suppressed",  # Section 15 - never merge with cross-sell
        grounding="catalog_facts",
        fallback_behavior="legacy_replacement_logic",
    ),
    RECIPE_SHOPPING: WorkflowContract(
        workflow_id=RECIPE_SHOPPING,
        migration_status=SHADOW,
        supported_intents=("recipe_shopping", "recipe_discovery"),
        retrieval_strategy="legacy_recipe_shopping_core_products",
        presentation_strategy="RECIPE_SHOPPING",
        cross_sell_policy="enabled",  # V2.6 RECIPE_COMPLETION
        grounding="verified_recipe_data",
        fallback_behavior="legacy_recipe_results",
    ),
    FAQ_INFORMATIONAL: WorkflowContract(
        workflow_id=FAQ_INFORMATIONAL,
        migration_status=SHADOW,
        supported_intents=("faq", "informational", "allergen_safety", "article_info"),
        retrieval_strategy="legacy_knowledge_search",
        presentation_strategy="INFORMATIONAL",
        cross_sell_policy="suppressed",  # Section 17/39
        grounding="knowledge_facts",
        fallback_behavior="legacy_faq_answer",
    ),
    ORDER_TRACKING: WorkflowContract(
        workflow_id=ORDER_TRACKING,
        migration_status=LEGACY,
        supported_intents=("order_tracking",),
        retrieval_strategy="not_implemented",
        presentation_strategy="INFORMATIONAL",
        cross_sell_policy="disabled",
        grounding="order_system_facts",
        fallback_behavior="legacy_fallback",
    ),
    SUPPORT_ESCALATION: WorkflowContract(
        workflow_id=SUPPORT_ESCALATION,
        migration_status=LEGACY,
        supported_intents=("support_escalation", "complaint"),
        retrieval_strategy="not_implemented",
        presentation_strategy="INFORMATIONAL",
        cross_sell_policy="disabled",
        grounding="support_system_facts",
        fallback_behavior="legacy_fallback",
    ),
    LEGACY_FALLBACK: WorkflowContract(
        workflow_id=LEGACY_FALLBACK,
        migration_status=LEGACY,
        supported_intents=("unclassified",),
        retrieval_strategy="legacy_lexical_search",
        presentation_strategy="legacy",
        cross_sell_policy="disabled",
        grounding="catalog_facts",
        fallback_behavior="n/a",
    ),
}


@dataclass
class WorkflowSelection:
    workflow_id: str
    confidence: float
    reason: str
    fallback_workflow: str = LEGACY_FALLBACK


@dataclass
class RoutingSignals:
    """One field per branch app/main.py's chat() cascade already checks,
    in the SAME order it checks them (Section 49 - precedence must be
    derived from current behavior, not invented). select_workflow() only
    ever reads these; it never calls a detector itself."""

    message: str = ""
    missing_composition: bool = False
    allergen_term: str | None = None
    faq_answer_found: bool = False
    is_random_recipe_query: bool = False
    recipe_subject: str | None = None
    out_of_domain: bool = False
    is_category_discovery: bool = False
    already_have_subject: str | None = None
    special_subject: str | None = None
    replacement_subject: str | None = None
    article_product_subject: str | None = None
    cross_sell_matches_found: bool = False
    related_subject: str | None = None
    # Populated only when the turn reaches the V2.4-V2.6 structured
    # pipeline (app.structured_search.build_structured_result_set()
    # returned a ResultSet):
    structured_answer_strategy: str | None = None
    structured_has_explicit_attributes: bool = False
    cross_sell_context_type: str | None = None


_COMPARISON_MARKERS = ("rozdiel", " vs ", "verzus", " alebo ")


def _looks_like_comparison(message: str) -> bool:
    from app.search import normalize
    normalized = f" {normalize(message)} "
    return any(marker in normalized for marker in _COMPARISON_MARKERS)


def select_workflow(signals: RoutingSignals) -> WorkflowSelection:
    """Deterministic precedence, mirroring app/main.py's actual cascade
    order exactly (Section 8/9/34/49) - this function is a pure label
    over already-computed signals, never a new detector."""
    if signals.missing_composition:
        return WorkflowSelection(LEGACY_FALLBACK, 0.9, "missing_composition_complaint")

    if signals.allergen_term:
        return WorkflowSelection(FAQ_INFORMATIONAL, 0.85, "allergen_safety_question")

    if signals.faq_answer_found:
        if _looks_like_comparison(signals.message):
            return WorkflowSelection(COMPARISON, 0.7, "faq_comparison_markers", fallback_workflow=FAQ_INFORMATIONAL)
        return WorkflowSelection(FAQ_INFORMATIONAL, 0.9, "direct_faq_match")

    if signals.is_random_recipe_query:
        return WorkflowSelection(RECIPE_SHOPPING, 0.6, "random_recipe_discovery")

    if signals.recipe_subject:
        return WorkflowSelection(RECIPE_SHOPPING, 0.85, "recipe_subject_detected")

    if signals.out_of_domain:
        return WorkflowSelection(LEGACY_FALLBACK, 0.9, "out_of_domain")

    if signals.is_category_discovery:
        return WorkflowSelection(CATEGORY_BROWSE, 0.85, "category_discovery_phrase")

    if signals.already_have_subject:
        return WorkflowSelection(LEGACY_FALLBACK, 0.5, "already_have_complement_legacy")

    if signals.special_subject == "plain_rice":
        # This is the one special_subject entry V2.4 already supersedes
        # (see app/main.py's structured-retrieval-first override) - the
        # structured pipeline's own strategy is the real signal.
        if signals.structured_answer_strategy:
            return _from_structured_strategy(signals)
        return WorkflowSelection(PRODUCT_LOOKUP, 0.5, "plain_rice_legacy_fallback", fallback_workflow=LEGACY_FALLBACK)

    if signals.special_subject:
        return WorkflowSelection(LEGACY_FALLBACK, 0.6, f"special_subject:{signals.special_subject}")

    if signals.replacement_subject:
        return WorkflowSelection(REPLACEMENT, 0.85, "replacement_subject_detected")

    if signals.article_product_subject:
        return WorkflowSelection(FAQ_INFORMATIONAL, 0.6, "article_product_info")

    if signals.cross_sell_matches_found:
        return WorkflowSelection(LEGACY_FALLBACK, 0.5, "legacy_cross_sell_trigger")

    if signals.related_subject:
        return WorkflowSelection(LEGACY_FALLBACK, 0.5, "legacy_related_subject")

    if signals.structured_answer_strategy:
        return _from_structured_strategy(signals)

    return WorkflowSelection(LEGACY_FALLBACK, 0.4, "no_structured_match")


def _from_structured_strategy(signals: RoutingSignals) -> WorkflowSelection:
    """Section 29 - the V2.5 presentation strategy already resolved for
    this turn is the ground truth for which of the three MIGRATED
    workflows applies."""
    if signals.cross_sell_context_type == "USE_CASE_COMPLETION":
        return WorkflowSelection(USE_CASE_ADVICE, 0.75, "use_case_completion_context", fallback_workflow=ATTRIBUTE_SEARCH)
    strategy = signals.structured_answer_strategy
    if strategy == "GROUPED_DISCOVERY":
        return WorkflowSelection(CATEGORY_BROWSE, 0.9, "grouped_discovery_strategy")
    if strategy in {"EXACT_MATCH", "NO_EXACT_MATCH"}:
        return WorkflowSelection(PRODUCT_LOOKUP, 0.9, f"structured_strategy:{strategy}")
    if strategy == "FILTERED_PRODUCT_LIST":
        if signals.structured_has_explicit_attributes:
            return WorkflowSelection(ATTRIBUTE_SEARCH, 0.85, "filtered_list_with_attributes")
        return WorkflowSelection(PRODUCT_LOOKUP, 0.75, "filtered_list_bare_family")
    return WorkflowSelection(LEGACY_FALLBACK, 0.3, f"unrecognized_strategy:{strategy}")
