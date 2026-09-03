"""
app/intelligence_diagnostics/scenario_schema.py  -  V2.18a scenario/
persona data model.

WHY A NEW TYPE INSTEAD OF EXTENDING app.evaluation.schema.GoldenCase:
GoldenCase/ConversationCase (V2.10) are the proven, unit-tested contract
between eval/golden/*.json and app.evaluation.runner's scoring engine -
Section 2 explicitly warns against "replacing proven infrastructure
merely to create a new abstraction." `Scenario` here is a thin envelope
ADDED around that existing contract, carrying only the NEW V2.18
concepts (persona, capability, ground-truth authority/status,
provenance, lifecycle) that GoldenCase never needed. `to_golden_case()`/
`to_conversation_case()` translate a Scenario back into the existing
typed models for actual execution - scoring logic itself is never
duplicated (see benchmark_runner.py, which calls
app.evaluation.runner.run_golden_case()/app.evaluation.conversation
unchanged).

GROUND-TRUTH AUTHORITY (Section 5) - the hard release-blocking
invariant this whole module exists to enforce: CURRENT_MODEL_OUTPUT is
NOT a valid authority. A scenario's `expected_invariants` may only be
trusted for scoring when `ground_truth_status == SCORED`, which in turn
requires `ground_truth_authority` to be one of the five allowed values
below - never derived from what the Advisor currently answers.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# --- scenario source / provenance (Section 13) ------------------------
SOURCE_EXISTING_GOLDEN = "EXISTING_GOLDEN"
SOURCE_REGRESSION_BUG = "REGRESSION_BUG"
SOURCE_CURATED = "CURATED"
SOURCE_REAL_CUSTOMER_QA = "REAL_CUSTOMER_QA"
SOURCE_SAFE_MUTATION = "SAFE_MUTATION"

SCENARIO_SOURCES = (
    SOURCE_EXISTING_GOLDEN,
    SOURCE_REGRESSION_BUG,
    SOURCE_CURATED,
    SOURCE_REAL_CUSTOMER_QA,
    SOURCE_SAFE_MUTATION,
)

# --- ground-truth authority (Section 5) - CURRENT_MODEL_OUTPUT is
# deliberately NOT in this tuple; that is the enforcement mechanism
# every acceptance check in this package relies on. ---------------------
AUTHORITY_EXISTING_CONTRACT = "EXISTING_CONTRACT"
AUTHORITY_EXISTING_GOLDEN = "EXISTING_GOLDEN"
AUTHORITY_AUTHORITATIVE_DATA = "AUTHORITATIVE_DATA"
AUTHORITY_HUMAN_CURATED = "HUMAN_CURATED"
AUTHORITY_VERIFIED_REPRODUCTION_CONTRACT = "VERIFIED_REPRODUCTION_CONTRACT"
FORBIDDEN_AUTHORITY_CURRENT_MODEL_OUTPUT = "CURRENT_MODEL_OUTPUT"

GROUND_TRUTH_AUTHORITIES = (
    AUTHORITY_EXISTING_CONTRACT,
    AUTHORITY_EXISTING_GOLDEN,
    AUTHORITY_AUTHORITATIVE_DATA,
    AUTHORITY_HUMAN_CURATED,
    AUTHORITY_VERIFIED_REPRODUCTION_CONTRACT,
)

# --- ground-truth status (Section 6/7) ----------------------------------
GROUND_TRUTH_SCORED = "SCORED"
GROUND_TRUTH_PENDING = "GROUND_TRUTH_PENDING"

GROUND_TRUTH_STATUSES = (GROUND_TRUTH_SCORED, GROUND_TRUTH_PENDING)

# --- lifecycle status (Section 8) ---------------------------------------
LIFECYCLE_OPEN = "OPEN"
LIFECYCLE_CLOSED = "CLOSED"
LIFECYCLE_SUPERSEDED = "SUPERSEDED"
LIFECYCLE_DATA_BLOCKED = "DATA_BLOCKED"
LIFECYCLE_GROUND_TRUTH_PENDING = "GROUND_TRUTH_PENDING"

LIFECYCLE_STATUSES = (
    LIFECYCLE_OPEN,
    LIFECYCLE_CLOSED,
    LIFECYCLE_SUPERSEDED,
    LIFECYCLE_DATA_BLOCKED,
    LIFECYCLE_GROUND_TRUTH_PENDING,
)

# --- capability taxonomy (Section 15) - reuses app.evaluation.schema's
# existing error_buckets vocabulary 1:1 wherever a direct mapping exists
# (RETRIEVAL_MISS/RANKING_ERROR/PRESENTATION_ERROR/GROUNDING_ERROR/
# INTENT_ERROR/CROSS_SELL_ERROR are the SAME real contracts V2.10 has
# scored since inception - Section 15 explicitly asks to "map to
# existing system contracts," not invent parallel category names). Only
# FOLLOW_UP/CONSTRAINT_PRESERVATION/BASKET_COMPLETENESS/ATTRIBUTE_SAFETY/
# ALLERGEN_SAFETY are genuinely new labels, added because V2.10's
# error_buckets has no equivalent for them yet. ------------------------
CAPABILITIES = (
    "UNDERSTAND",
    "RETRIEVE",
    "RANK",
    "COMPOSE",
    "GROUND",
    "PRESENT",
    "FOLLOW_UP",
    "CONSTRAINT_PRESERVATION",
    "PRODUCT_SEARCH",
    "PRODUCT_ADVICE",
    "COMPARISON",
    "REPLACEMENT",
    "CROSS_SELL",
    "RECIPE",
    "RECIPE_TO_PRODUCTS",
    "BASKET_COMPLETENESS",
    "PRODUCT_INFORMATION",
    "ATTRIBUTE_SAFETY",
    "ALLERGEN_SAFETY",
    "FAQ",
    "AVAILABILITY_PRICE",
    "OUT_OF_DOMAIN",
)

# --- persona dimensions (Section 14) - testing instruments, never
# demographic/personal attributes. -------------------------------------
KNOWLEDGE_LEVELS = ("BEGINNER", "EXPERIENCED", "UNCERTAIN")
SHOPPER_STYLES = (
    "RECIPE_DRIVEN",
    "BRAND_SPECIFIC",
    "DIETARY_CONSTRAINT",
    "COMPARISON_SHOPPER",
    "SUBSTITUTION_SHOPPER",
)
COMMUNICATION_STYLES = (
    "PRECISE",
    "INFORMAL",
    "TYPOS",
    "PARTIAL_PRODUCT_NAME",
    "MIXED_TERMINOLOGY",
    "FOLLOW_UP_HEAVY",
)

_FORBIDDEN_PERSONA_FIELDS = frozenset({
    "age", "gender", "ethnicity", "race", "religion", "income", "nationality",
    "sexual_orientation", "disability", "health_condition", "name", "location",
    "year old", "years old", "woman", "man", "male", "female", "boy", "girl",
})


@dataclass(frozen=True)
class Persona:
    """A testing instrument that varies interaction style/knowledge
    level - never a customer profile, never a demographic stereotype
    (Section 14). `__post_init__` is the enforcement point: it is
    impossible to construct a Persona carrying any of the forbidden
    sensitive-attribute field names."""

    persona_id: str
    knowledge_level: str
    shopper_style: str | None = None
    communication_style: str | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if self.knowledge_level not in KNOWLEDGE_LEVELS:
            raise ValueError(f"invalid knowledge_level: {self.knowledge_level!r}")
        if self.shopper_style is not None and self.shopper_style not in SHOPPER_STYLES:
            raise ValueError(f"invalid shopper_style: {self.shopper_style!r}")
        if self.communication_style is not None and self.communication_style not in COMMUNICATION_STYLES:
            raise ValueError(f"invalid communication_style: {self.communication_style!r}")
        lowered = f"{self.description} {self.persona_id}".lower()
        for forbidden in _FORBIDDEN_PERSONA_FIELDS:
            if forbidden in lowered:
                raise ValueError(f"persona description/id must not reference sensitive attribute: {forbidden!r}")


@dataclass(frozen=True)
class ScenarioTurn:
    message: str
    expected_intent: str | None = None
    expected_workflow: str | None = None
    note: str = ""


@dataclass(frozen=True)
class Scenario:
    """One V2.18 diagnostic scenario. May wrap an existing GoldenCase/
    ConversationCase (source in {EXISTING_GOLDEN, REGRESSION_BUG}, in
    which case `underlying_case_id` names it) or be authored directly
    (CURATED/REAL_CUSTOMER_QA/SAFE_MUTATION)."""

    scenario_id: str
    source: str
    capability: str
    turns: tuple[ScenarioTurn, ...]
    ground_truth_status: str
    ground_truth_authority: str | None = None
    ground_truth_reason: str = ""
    persona: Persona | None = None
    objective: str = ""
    known_facts: tuple[str, ...] = ()
    expected_invariants: tuple[str, ...] = ()
    forbidden_behavior: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    provenance: str = ""
    lifecycle_status: str = LIFECYCLE_OPEN
    lifecycle_reason: str = ""
    created_version: str = "V2.18a"
    closed_version: str | None = None
    underlying_case_id: str | None = None
    critical: bool = False

    def __post_init__(self) -> None:
        if self.source not in SCENARIO_SOURCES:
            raise ValueError(f"invalid scenario source: {self.source!r}")
        if self.ground_truth_status not in GROUND_TRUTH_STATUSES:
            raise ValueError(f"invalid ground_truth_status: {self.ground_truth_status!r}")
        if self.lifecycle_status not in LIFECYCLE_STATUSES:
            raise ValueError(f"invalid lifecycle_status: {self.lifecycle_status!r}")
        if not self.turns:
            raise ValueError("scenario must have at least one turn")
        # Section 5 hard guard - the one line that makes
        # CURRENT_MODEL_OUTPUT structurally impossible as an authority:
        # it simply is not a member of GROUND_TRUTH_AUTHORITIES, so any
        # attempt to pass it here raises immediately, at construction
        # time, before the scenario could ever reach scoring.
        if self.ground_truth_status == GROUND_TRUTH_SCORED:
            if self.ground_truth_authority not in GROUND_TRUTH_AUTHORITIES:
                raise ValueError(
                    f"a SCORED scenario must declare one of {GROUND_TRUTH_AUTHORITIES} "
                    f"as ground_truth_authority, got {self.ground_truth_authority!r}"
                )
        if self.ground_truth_authority == FORBIDDEN_AUTHORITY_CURRENT_MODEL_OUTPUT:
            raise ValueError("CURRENT_MODEL_OUTPUT can never be a ground_truth_authority (Section 5)")

    @property
    def is_multi_turn(self) -> bool:
        return len(self.turns) > 1

    @property
    def is_scored(self) -> bool:
        return self.ground_truth_status == GROUND_TRUTH_SCORED and self.lifecycle_status == LIFECYCLE_OPEN
