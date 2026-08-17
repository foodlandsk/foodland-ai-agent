"""
app/evaluation/schema.py  -  V2.10 golden case / result data model

Golden cases live as plain JSON under eval/golden/ (Section 54 -
human-reviewable, no opaque serialized Python objects). This module is
the typed contract between that JSON and the runner - loading is
intentionally permissive about missing optional fields (a case with no
`expected_concept_ids` simply skips concept-based metrics rather than
crashing), matching the "not every case needs one exact expected SKU"
principle (Section 10).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# --- controlled query-type vocabulary (Section 7) --------------------------
EXACT_PRODUCT = "EXACT_PRODUCT"
CATEGORY = "CATEGORY"
SUBCATEGORY = "SUBCATEGORY"
BRAND = "BRAND"
BRAND_CATEGORY = "BRAND_CATEGORY"
ATTRIBUTE = "ATTRIBUTE"
PACKAGE_SIZE = "PACKAGE_SIZE"
USE_CASE = "USE_CASE"
RECIPE_INGREDIENT = "RECIPE_INGREDIENT"
REPLACEMENT = "REPLACEMENT"
COMPARISON = "COMPARISON"
INFORMATIONAL = "INFORMATIONAL"
AMBIGUOUS = "AMBIGUOUS"
MISSPELLING = "MISSPELLING"
MULTI_TOKEN = "MULTI_TOKEN"
NEGATION = "NEGATION"
FOLLOW_UP = "FOLLOW_UP"
CONTEXT_SWITCH = "CONTEXT_SWITCH"
SHOW_MORE = "SHOW_MORE"
SHOW_ALL = "SHOW_ALL"
CROSS_SELL = "CROSS_SELL"
REGRESSION_BUG = "REGRESSION_BUG"

# --- error buckets (Section 49) --------------------------------------------
INTENT_ERROR = "INTENT_ERROR"
QUERY_PARSE_ERROR = "QUERY_PARSE_ERROR"
TAXONOMY_ERROR = "TAXONOMY_ERROR"
ELIGIBILITY_ERROR = "ELIGIBILITY_ERROR"
RETRIEVAL_MISS = "RETRIEVAL_MISS"
RANKING_ERROR = "RANKING_ERROR"
PRESENTATION_ERROR = "PRESENTATION_ERROR"
CROSS_SELL_ERROR = "CROSS_SELL_ERROR"
RECIPE_MAPPING_ERROR = "RECIPE_MAPPING_ERROR"
SESSION_ERROR = "SESSION_ERROR"
REFERENCE_ERROR = "REFERENCE_ERROR"
GROUNDING_ERROR = "GROUNDING_ERROR"
PERFORMANCE_ERROR = "PERFORMANCE_ERROR"


@dataclass(frozen=True)
class GoldenCase:
    """One single-turn evaluation case (Section 5/6)."""

    id: str
    query: str
    query_type: str
    language: str = "sk"
    limit: int = 8
    # Relevance ground truth is computed AGAINST THE CURRENT CATALOG at run
    # time (real taxonomy classification of whatever products come back),
    # never a hardcoded SKU list (Section 5 - do not hardcode unstable
    # specifics; a catalog refresh must not silently break the dataset).
    expected_concept_ids: tuple[str, ...] = ()
    must_not_concept_ids: tuple[str, ...] = ()
    must_include_title_substrings: tuple[str, ...] = ()
    must_not_include_title_substrings: tuple[str, ...] = ()
    must_not_be_first_title_substrings: tuple[str, ...] = ()
    expected_answer_include: tuple[str, ...] = ()
    max_products: int | None = None
    min_relevant_count: int = 0
    expected_workflow: str | None = None
    expected_intent: str | None = None
    critical: bool = False  # Section 37 - hard failure regardless of average score
    note: str = ""
    source: str = "golden"  # "golden" | "regression_bug"


@dataclass(frozen=True)
class ConversationTurn:
    """One turn inside a ConversationCase (Section 29)."""

    message: str
    expected_workflow: str | None = None
    expected_intent: str | None = None
    expected_response_mode: str | None = None
    expected_active_recipe_id: str | None = None
    expected_servings: int | None = None
    expected_context_switch: str | None = None  # "NONE" | "SOFT" | "HARD"
    expected_reference_resolved_from_previous_index: int | None = None  # 0-based index into PREVIOUS turn's products
    expected_products_nonempty: bool | None = None
    expected_recipe_plan_present: bool | None = None
    note: str = ""


@dataclass(frozen=True)
class ConversationCase:
    """A named multi-turn sequence (Section 29-32)."""

    id: str
    session_id_prefix: str
    turns: tuple[ConversationTurn, ...]
    note: str = ""
    critical: bool = False


@dataclass
class CaseMetrics:
    eligibility_precision: float | None = None
    precision_at_k: dict[int, float] = field(default_factory=dict)
    recall_at_k: dict[int, float] = field(default_factory=dict)
    hit_rate_at_k: dict[int, float] = field(default_factory=dict)
    reciprocal_rank: float | None = None


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    critical_failure: bool
    error_buckets: tuple[str, ...]
    metrics: CaseMetrics
    returned_product_ids: tuple[str, ...]
    workflow_id: str | None
    intent: str | None
    latency_ms: float
    reasons: tuple[str, ...] = ()


@dataclass
class ConversationCaseResult:
    case_id: str
    passed: bool
    critical_failure: bool
    turn_results: tuple[dict, ...]
    context_contamination: bool
    reference_errors: int
    reasons: tuple[str, ...] = ()
