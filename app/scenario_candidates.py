"""
app/scenario_candidates.py  -  V2.23a: real-customer learning candidate
framework.

WHAT THIS IS: a structured, auditable intake for turning a real customer
Advisor failure into a CANDIDATE scenario a human can later promote into
an eval/golden regression case. Candidates are offline, human-curated
records living under eval/candidates/ (git-tracked, reviewable in a PR
like golden cases already are) - this module never writes to Railway's
runtime storage and never touches production traffic.

WHAT THIS IS NOT: not a second ranking-learning system (see
app.learning_candidates/app.learning_lifecycle for that - different
problem, different data shape, intentionally not reused here beyond the
append-only-ledger *pattern*), not an evaluator, not a golden writer, not
an Advisor behavior change. Nothing in this module can:
  - change app/main.py routing/retrieval/ranking/composition
  - write eval/golden/*.json
  - compute or alter a benchmark score
  - promote a candidate without an explicit, named human review decision

CENTRAL INVARIANT (never relaxed by any flag in this module):
current Mei/Advisor output is never ground truth, and customer behavior
(what they clicked/ordered/typed) is evidence of a *problem*, never
evidence of the *correct answer*. See GROUND_TRUTH_AUTHORITIES below -
there is no code path that accepts "model output" or "customer behavior"
as an authority value; FORBIDDEN_AUTHORITIES exists specifically to make
that an explicit, tested rejection rather than an omission.

LIFECYCLE (Section 4 of the V2.23a mandate - no step may be skipped):

    REAL_CUSTOMER_EVENT
      -> SANITIZED_CANDIDATE      (this module: build_candidate())
      -> HUMAN_REVIEW             (this module: review event, append-only)
      -> GROUND_TRUTH_PENDING     (default status until review resolves)
      -> VALIDATED_SCENARIO       (human sets a trusted authority)
      -> REGRESSION/GOLDEN CANDIDATE  (future sprint, manual promotion)
      -> ACCEPTED_TEST -> REPRODUCTION -> ROOT_CAUSE -> BOUNDED_REPAIR
         -> POST-REPAIR VALIDATION   (existing V2.22-style bounded-repair
         discipline this project already uses - unchanged, reused as-is)

A candidate can NEVER reach "golden" directly; every step above is a
distinct, recorded action an operator takes outside this module (this
sprint builds the intake and the schema, not the promotion tooling).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# --- storage location -------------------------------------------------------
# Deliberately a plain repo path (like eval/golden/*.json), NOT something
# resolved through app.storage_paths - candidates are reviewed via git/PR,
# never written by production Railway traffic, so they must never land on
# a runtime-only persistent volume a reviewer can't see in a diff.
CANDIDATES_ROOT = Path("eval/candidates")
REAL_CUSTOMER_DIR = CANDIDATES_ROOT / "real_customer"
CANDIDATES_PATH = REAL_CUSTOMER_DIR / "candidates.jsonl"
REVIEWS_PATH = REAL_CUSTOMER_DIR / "reviews.jsonl"

# --- ground truth governance (Section 7) ------------------------------------
GT_PENDING = "GROUND_TRUTH_PENDING"
GT_HUMAN_CURATED = "HUMAN_CURATED"
GT_AUTHORITATIVE_DATA = "AUTHORITATIVE_DATA"
GT_EXISTING_CONTRACT = "EXISTING_CONTRACT"
GT_VERIFIED_REPRODUCTION_CONTRACT = "VERIFIED_REPRODUCTION_CONTRACT"

# The only statuses/authorities this module will ever persist. Matches the
# vocabulary eval/golden/*.json scenarios already use (ground_truth_
# authority), plus GT_PENDING - no new vocabulary invented for golden-
# facing fields, only for the parts (failure family, entity_state, review
# workflow) existing golden scenarios have no equivalent of.
ALLOWED_GROUND_TRUTH_STATUSES = (GT_PENDING, GT_HUMAN_CURATED, GT_AUTHORITATIVE_DATA,
                                  GT_EXISTING_CONTRACT, GT_VERIFIED_REPRODUCTION_CONTRACT)
TRUSTED_AUTHORITIES = (GT_HUMAN_CURATED, GT_AUTHORITATIVE_DATA, GT_EXISTING_CONTRACT,
                        GT_VERIFIED_REPRODUCTION_CONTRACT)

# Explicitly named and tested rejections (Section 7) - current model output
# and customer behavioral signals are evidence of a failure, never of the
# correct answer. Listed exhaustively rather than relying on "not in the
# allowed set" alone, so a typo'd-but-plausible-sounding new authority
# string doesn't accidentally slip through as "not forbidden == allowed".
FORBIDDEN_AUTHORITIES = frozenset({
    "CURRENT_MODEL_OUTPUT",
    "CUSTOMER_CLICKED_THIS",
    "CUSTOMER_PURCHASED_THIS",
    "MODEL_MAJORITY_VOTE",
    "ADVISOR_OUTPUT",
    "AI_GENERATED",
})


class CandidateValidationError(ValueError):
    pass


# --- failure family taxonomy (Section 8) ------------------------------------
# Deliberately a candidate-intake-only vocabulary, separate from
# app.intent.PRIMARY_INTENTS (routing) - a failure family is "what kind of
# problem is this", not "what should primary_intent be"; several families
# below (ORDER_SUPPORT/ACCOUNT_SUPPORT/INVOICE_SUPPORT) have no primary_
# intent equivalent yet at all (see docs/governance note on this gap).
FAILURE_FAMILIES = (
    "INTENT_ROUTING",
    "FAQ_ROUTING",
    "ORDER_SUPPORT",
    "ACCOUNT_SUPPORT",
    "INVOICE_SUPPORT",
    "PRODUCT_SEARCH",
    "PRODUCT_ADVICE",
    "PRODUCT_COMPARISON",
    "RECIPE_ROUTING",
    "RECIPE_TO_PRODUCTS",
    "ALREADY_HAVE",
    "CROSS_SELL",
    "REPLACEMENT",
    "AVAILABILITY_OR_PRICE",
    "ALLERGEN_SAFETY",
    "OUT_OF_DOMAIN",
    "MULTI_TURN_STATE",
    "PRESENTATION_GROUPING",
    "DATA_QUALITY",
    "EVALUATOR_DEFECT",
    "GROUND_TRUTH_PROBLEM",
    "UNKNOWN",
)

RISK_LOW, RISK_NORMAL, RISK_HIGH = "LOW", "NORMAL", "HIGH"
RISK_LEVELS = (RISK_LOW, RISK_NORMAL, RISK_HIGH)

SOURCE_TYPES = (
    "SANITIZED_SUPPORT_CONVERSATION",
    "SANITIZED_AI_CHAT_FAILURE",
    "MANUAL_STAFF_REPORT",
    "PRODUCTION_INCIDENT_NOTE",
    # V2.23b (Section 16) - a deterministic semantic mutation of an
    # already-approved real-customer seed, created for paraphrase
    # robustness. MUST NEVER be confused with a real-customer source -
    # kept as its own explicit value rather than overloading one of the
    # four above, so a reader (or a future filter) can never mistake one
    # for the other.
    "SYNTHETIC_MUTATION",
)

# --- ALREADY_HAVE entity states (Section 9/10) ------------------------------
# Reuses the EXISTING concept, not a new one: app.intent.CustomerIntent
# already carries `customer_has: list[str]`, and app/main.py already has
# ALREADY_HAVE_MARKERS/ALREADY_HAVE_SUBJECT_MAP/ALREADY_HAVE_COMPLEMENT_
# QUERIES plus app.recipe_shopping's RECIPE_ALREADY_HAVE status. This
# module's entity_state field is intake-schema vocabulary for *describing*
# that same state on a candidate, not a parallel production mechanism.
ENTITY_STATE_ALREADY_HAVE = "ALREADY_HAVE"
ENTITY_STATE_NEEDS_SUBSTITUTE = "NEEDS_SUBSTITUTE"
ENTITY_STATE_RUNNING_OUT = "RUNNING_OUT"
ENTITY_STATE_WANTS_MORE = "WANTS_MORE"
ENTITY_STATES = (ENTITY_STATE_ALREADY_HAVE, ENTITY_STATE_NEEDS_SUBSTITUTE,
                  ENTITY_STATE_RUNNING_OUT, ENTITY_STATE_WANTS_MORE)

# Presentation groups ALREADY_HAVE must stay disjoint from (Section 10).
# Named here only to make the invariant greppable/testable from this
# module; the groups themselves are owned by app/presentation.py and
# app/result_sets.py and are not redefined here.
PRESENTATION_GROUPS_EXCLUDING_ALREADY_HAVE = (
    "MATCH", "ALTERNATIVE", "SUBSTITUTE", "CROSS_SELL", "RECIPE_MISSING_ROLE",
)

# --- human review workflow (Section 17) -------------------------------------
REVIEW_APPROVE_AS_SCENARIO = "APPROVE_AS_SCENARIO"
REVIEW_NEEDS_MORE_CONTEXT = "NEEDS_MORE_CONTEXT"
REVIEW_DATA_ISSUE = "DATA_ISSUE"
REVIEW_EVALUATOR_ISSUE = "EVALUATOR_ISSUE"
REVIEW_PRODUCT_BUG = "PRODUCT_BUG"
REVIEW_OUT_OF_SCOPE = "OUT_OF_SCOPE"
REVIEW_REJECT_NO_CLEAR_GT = "REJECT_NO_CLEAR_GT"
REVIEW_DECISIONS = (
    REVIEW_APPROVE_AS_SCENARIO, REVIEW_NEEDS_MORE_CONTEXT, REVIEW_DATA_ISSUE,
    REVIEW_EVALUATOR_ISSUE, REVIEW_PRODUCT_BUG, REVIEW_OUT_OF_SCOPE,
    REVIEW_REJECT_NO_CLEAR_GT,
)

HUMAN_REVIEW_PENDING = "PENDING"
HUMAN_REVIEW_REVIEWED = "REVIEWED"
HUMAN_REVIEW_STATUSES = (HUMAN_REVIEW_PENDING, HUMAN_REVIEW_REVIEWED)

# Role-based reviewer identifiers (Section 4 of the V2.23b mandate) - used
# when no real named individual is appropriate/available to attach to a
# review record. Never a fabricated person's name.
REVIEWER_ROLE_BUSINESS_OWNER = "BUSINESS_OWNER"
REVIEWER_ROLE_HUMAN_REVIEWER = "HUMAN_REVIEWER"
REVIEWER_ROLES = (REVIEWER_ROLE_BUSINESS_OWNER, REVIEWER_ROLE_HUMAN_REVIEWER)

# --- reproduction / first-divergence (V2.23b, Sections 8/11/22-24) ---------
# Recorded on the HumanReview event, not on the candidate itself - keeps
# candidates.jsonl a pure, immutable record of the original intake, with
# reproduction/diagnosis evidence living in the same append-only place as
# the review decision that used it. This is diagnostic evidence only
# (Section 21: "reproduction is not GT") - it never substitutes for a
# trusted ground_truth_authority.
REPRODUCED = "REPRODUCED"
NOT_REPRODUCED = "NOT_REPRODUCED"
PARTIAL = "PARTIAL"
ENVIRONMENT_BLOCKED = "ENVIRONMENT_BLOCKED"
NOT_ATTEMPTED = "NOT_ATTEMPTED"
REPRODUCTION_STATUSES = (REPRODUCED, NOT_REPRODUCED, PARTIAL, ENVIRONMENT_BLOCKED, NOT_ATTEMPTED)

FIRST_DIVERGENCE_STAGES = (
    "INTENT", "RETRIEVAL", "RANKING", "COMPOSITION", "PRESENTATION", "STATE", "UNKNOWN",
)
CONFIDENCE_LOW, CONFIDENCE_MEDIUM, CONFIDENCE_HIGH = "LOW", "MEDIUM", "HIGH"
CONFIDENCE_LEVELS = (CONFIDENCE_LOW, CONFIDENCE_MEDIUM, CONFIDENCE_HIGH)


# --- sanitization -----------------------------------------------------------
# Order number / reference patterns seen in Foodland-style support text
# ("objednávka č. 12345", "#45821", a bare 5+ digit run). Deliberately
# conservative (5+ digits) to avoid redacting short, meaningless numbers
# ("mám 2 balíčky") while still catching real order/invoice references.
_ORDER_REF_RE = re.compile(r"(?:(?:objedn[áa]vk\w*|faktúr\w*|fakturu|dobropis\w*)\s*(?:č\.?|#|num\w*)?\s*[:#]?\s*)?\b\d{5,}\b", re.IGNORECASE)
# A capitalized-word-pair pattern as a conservative name heuristic (e.g.
# "Jana Nováková"). Regex cannot reliably strip every personal name - see
# docs/governance note: operators MUST visually confirm no name/address
# remains before this file is committed. This is a safety net, not a
# guarantee.
# Two of the Slovak capital letters below are written as \u00C4/\u0139
# escape sequences rather than literal characters - scripts/check_
# deployment.py's mojibake scan flags those two exact Unicode code
# points anywhere in a tracked text file (they are common double-
# encoding lead bytes), so the project's existing Slovak-capital-
# letter regexes (e.g. app/main.py's _ADDRESS_PATTERN) already use
# this same escape convention.
_NAME_PAIR_RE = re.compile(
    r"\b[A-ZÁ\u00C4ČĎÉÍ\u0139ĽŇÓÔŔŠŤÚÝŽ][\wáäčďéíĺľňóôŕšťúýž]+\s+[A-ZÁ\u00C4ČĎÉÍ\u0139ĽŇÓÔŔŠŤÚÝŽ][\wáäčďéíĺľňóôŕšťúýž]+\b"
)


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{6,}\d")


def sanitize_text(text: str) -> tuple[str, dict[str, int]]:
    """Redact PII from candidate text. Reuses app.main.redact_pii() (email/
    phone) exactly like app.customer_audit._redact() already does - lazy
    import for the same reason (app.main is heavy and this module must
    stay importable without pulling in the whole Advisor at import time).
    Adds order/invoice-reference redaction on top, since redact_pii() was
    never scoped to cover that. Name/address redaction is NOT attempted
    beyond a conservative capitalized-word-pair heuristic - see docstring.
    Returns (sanitized_text, counts) so callers/CLI can report exactly
    what was redacted."""
    from app.main import redact_pii  # deferred - see module docstring

    working = str(text or "")
    counts = {
        "email": len(_EMAIL_RE.findall(working)),
        "phone": len(_PHONE_RE.findall(working)),
        "order_reference": len(_ORDER_REF_RE.findall(working)),
        "name_like": len(_NAME_PAIR_RE.findall(working)),
    }

    working = redact_pii(working)  # email + phone, the project's one proven pass
    working = _ORDER_REF_RE.sub("[order_reference]", working)
    working = _NAME_PAIR_RE.sub("[name_like]", working)
    return working, counts


# --- schema (Section 6) ------------------------------------------------------
@dataclass(frozen=True)
class TurnContext:
    """One turn of multi-turn intake (Section 15)."""
    turn_index: int
    speaker: str  # "customer" | "advisor"
    sanitized_text: str
    state_before: dict | None = None
    state_after: dict | None = None


@dataclass(frozen=True)
class HumanReview:
    """Section 17 - append-only, never mutates the original candidate.

    V2.23b additions (reproduction_status / suspected_first_divergence /
    suspected_first_divergence_confidence, reviewer_role): deliberately
    placed HERE rather than on ScenarioCandidate - reproduction/diagnosis
    is evidence gathered as part of ONE review action, not a property of
    the original intake, and this keeps the append-only/never-mutate
    invariant intact without needing any "update candidate" code path.
    Per Section 21 of the mandate, a REPRODUCED status is diagnostic
    confirmation only - it never substitutes for `authority`."""
    candidate_id: str
    reviewer: str
    reviewed_at: float
    decision: str
    expected_intent: str | None = None
    expected_behavior: str | None = None
    forbidden_behavior: tuple[str, ...] = ()
    authority: str | None = None
    notes: str = ""
    reviewer_role: str | None = None
    reproduction_status: str = NOT_ATTEMPTED
    suspected_first_divergence: str | None = None
    suspected_first_divergence_confidence: str | None = None

    def __post_init__(self) -> None:
        if self.decision not in REVIEW_DECISIONS:
            raise CandidateValidationError(f"unknown review decision {self.decision!r}")
        if not self.reviewer or not self.reviewer.strip():
            raise CandidateValidationError("human review requires a non-empty reviewer identity")
        if self.reviewer_role is not None and self.reviewer_role not in REVIEWER_ROLES:
            raise CandidateValidationError(f"unknown reviewer_role {self.reviewer_role!r}")
        if self.reproduction_status not in REPRODUCTION_STATUSES:
            raise CandidateValidationError(f"unknown reproduction_status {self.reproduction_status!r}")
        if self.suspected_first_divergence is not None and self.suspected_first_divergence not in FIRST_DIVERGENCE_STAGES:
            raise CandidateValidationError(f"unknown suspected_first_divergence {self.suspected_first_divergence!r}")
        if self.suspected_first_divergence_confidence is not None and self.suspected_first_divergence_confidence not in CONFIDENCE_LEVELS:
            raise CandidateValidationError(f"unknown confidence {self.suspected_first_divergence_confidence!r}")
        if self.decision == REVIEW_APPROVE_AS_SCENARIO:
            if self.authority not in TRUSTED_AUTHORITIES:
                raise CandidateValidationError(
                    f"APPROVE_AS_SCENARIO requires a trusted authority in {TRUSTED_AUTHORITIES}, got {self.authority!r}"
                )
            if not self.expected_behavior:
                raise CandidateValidationError("APPROVE_AS_SCENARIO requires expected_behavior to be set")


@dataclass(frozen=True)
class ScenarioCandidate:
    candidate_id: str
    source_type: str
    created_at: float
    language: str
    sanitized_query: str
    conversation_context: tuple[TurnContext, ...] = ()
    current_observed_intent: str | None = None
    current_observed_behavior: str | None = None
    suspected_failure_family: str = "UNKNOWN"
    expected_intent: str | None = None
    expected_behavior: str | None = None
    forbidden_behavior: tuple[str, ...] = ()
    entity_state: dict[str, str] = field(default_factory=dict)
    risk_level: str = RISK_NORMAL
    ground_truth_status: str = GT_PENDING
    ground_truth_authority: str | None = None
    human_review_status: str = HUMAN_REVIEW_PENDING
    notes: str = ""
    source_reference_hash: str = ""
    # optional (Section 6)
    current_selected_products: tuple[str, ...] = ()
    current_selected_faq: str | None = None
    current_recipe: str | None = None
    presentation_groups: tuple[str, ...] = ()
    sanitization_counts: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.sanitized_query:
            raise CandidateValidationError("sanitized_query is required")
        if self.source_type not in SOURCE_TYPES:
            raise CandidateValidationError(f"unknown source_type {self.source_type!r}")
        if self.suspected_failure_family not in FAILURE_FAMILIES:
            raise CandidateValidationError(f"unknown suspected_failure_family {self.suspected_failure_family!r}")
        if self.risk_level not in RISK_LEVELS:
            raise CandidateValidationError(f"unknown risk_level {self.risk_level!r}")
        if self.ground_truth_status not in ALLOWED_GROUND_TRUTH_STATUSES:
            raise CandidateValidationError(f"unknown ground_truth_status {self.ground_truth_status!r}")
        if self.ground_truth_authority is not None and self.ground_truth_authority in FORBIDDEN_AUTHORITIES:
            raise CandidateValidationError(
                f"ground_truth_authority {self.ground_truth_authority!r} is forbidden - "
                "current model output and customer behavior are never ground truth (Section 7)."
            )
        if self.ground_truth_status != GT_PENDING and self.ground_truth_authority not in TRUSTED_AUTHORITIES:
            raise CandidateValidationError(
                "a non-PENDING ground_truth_status requires a trusted ground_truth_authority"
            )
        for state in self.entity_state.values():
            if state not in ENTITY_STATES:
                raise CandidateValidationError(f"unknown entity_state value {state!r}")

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "source_type": self.source_type,
            "created_at": self.created_at,
            "language": self.language,
            "sanitized_query": self.sanitized_query,
            "conversation_context": [
                {
                    "turn_index": t.turn_index, "speaker": t.speaker, "sanitized_text": t.sanitized_text,
                    "state_before": t.state_before, "state_after": t.state_after,
                }
                for t in self.conversation_context
            ],
            "current_observed_intent": self.current_observed_intent,
            "current_observed_behavior": self.current_observed_behavior,
            "suspected_failure_family": self.suspected_failure_family,
            "expected_intent": self.expected_intent,
            "expected_behavior": self.expected_behavior,
            "forbidden_behavior": list(self.forbidden_behavior),
            "entity_state": dict(self.entity_state),
            "risk_level": self.risk_level,
            "ground_truth_status": self.ground_truth_status,
            "ground_truth_authority": self.ground_truth_authority,
            "human_review_status": self.human_review_status,
            "notes": self.notes,
            "source_reference_hash": self.source_reference_hash,
            "current_selected_products": list(self.current_selected_products),
            "current_selected_faq": self.current_selected_faq,
            "current_recipe": self.current_recipe,
            "presentation_groups": list(self.presentation_groups),
            "sanitization_counts": dict(self.sanitization_counts),
        }

    @staticmethod
    def from_dict(d: dict) -> "ScenarioCandidate":
        turns = tuple(
            TurnContext(
                turn_index=t["turn_index"], speaker=t["speaker"], sanitized_text=t["sanitized_text"],
                state_before=t.get("state_before"), state_after=t.get("state_after"),
            )
            for t in d.get("conversation_context", [])
        )
        return ScenarioCandidate(
            candidate_id=d["candidate_id"], source_type=d["source_type"], created_at=d["created_at"],
            language=d["language"], sanitized_query=d["sanitized_query"], conversation_context=turns,
            current_observed_intent=d.get("current_observed_intent"),
            current_observed_behavior=d.get("current_observed_behavior"),
            suspected_failure_family=d.get("suspected_failure_family", "UNKNOWN"),
            expected_intent=d.get("expected_intent"), expected_behavior=d.get("expected_behavior"),
            forbidden_behavior=tuple(d.get("forbidden_behavior", ())),
            entity_state=dict(d.get("entity_state", {})), risk_level=d.get("risk_level", RISK_NORMAL),
            ground_truth_status=d.get("ground_truth_status", GT_PENDING),
            ground_truth_authority=d.get("ground_truth_authority"),
            human_review_status=d.get("human_review_status", HUMAN_REVIEW_PENDING),
            notes=d.get("notes", ""), source_reference_hash=d.get("source_reference_hash", ""),
            current_selected_products=tuple(d.get("current_selected_products", ())),
            current_selected_faq=d.get("current_selected_faq"), current_recipe=d.get("current_recipe"),
            presentation_groups=tuple(d.get("presentation_groups", ())),
            sanitization_counts=dict(d.get("sanitization_counts", {})),
        )


def _content_hash(sanitized_query: str) -> str:
    """A content hash for duplicate-detection/traceability - deliberately
    NOT a hash of any customer/session identifier (this framework never
    receives one; intake is of already-sanitized text a human prepared
    offline), so no salt/identity material is needed or used here."""
    normalized = re.sub(r"\s+", " ", sanitized_query.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def build_candidate(
    *,
    raw_text: str,
    language: str,
    source_type: str,
    current_observed_intent: str | None = None,
    current_observed_behavior: str | None = None,
    suspected_failure_family: str = "UNKNOWN",
    expected_intent: str | None = None,
    expected_behavior: str | None = None,
    forbidden_behavior: tuple[str, ...] = (),
    entity_state: dict[str, str] | None = None,
    risk_level: str = RISK_NORMAL,
    notes: str = "",
    conversation_context: tuple[TurnContext, ...] = (),
    current_selected_products: tuple[str, ...] = (),
    current_selected_faq: str | None = None,
    current_recipe: str | None = None,
    presentation_groups: tuple[str, ...] = (),
) -> ScenarioCandidate:
    """The single entry point that turns raw (human-prepared, already
    mostly-sanitized) text into a ScenarioCandidate. ALWAYS forces
    ground_truth_status=GROUND_TRUTH_PENDING and ground_truth_authority=
    None - Section 3 rule 6 ("unresolved candidate must remain GROUND_
    TRUTH_PENDING") is enforced here structurally: there is no parameter
    on this function that can set a trusted authority at intake time.
    Promotion past PENDING only ever happens through a recorded
    HumanReview (see apply_human_review below)."""
    sanitized, counts = sanitize_text(raw_text)
    candidate_id = f"rc-{uuid.uuid4().hex[:12]}"
    return ScenarioCandidate(
        candidate_id=candidate_id,
        source_type=source_type,
        created_at=time.time(),
        language=language,
        sanitized_query=sanitized,
        conversation_context=conversation_context,
        current_observed_intent=current_observed_intent,
        current_observed_behavior=current_observed_behavior,
        suspected_failure_family=suspected_failure_family,
        expected_intent=expected_intent,
        expected_behavior=expected_behavior,
        forbidden_behavior=tuple(forbidden_behavior),
        entity_state=dict(entity_state or {}),
        risk_level=risk_level,
        ground_truth_status=GT_PENDING,
        ground_truth_authority=None,
        human_review_status=HUMAN_REVIEW_PENDING,
        notes=notes,
        source_reference_hash=_content_hash(sanitized),
        current_selected_products=tuple(current_selected_products),
        current_selected_faq=current_selected_faq,
        current_recipe=current_recipe,
        presentation_groups=tuple(presentation_groups),
        sanitization_counts=counts,
    )


# --- storage (append-only JSONL, Section 20/21) -----------------------------
def load_candidates(path: Path = CANDIDATES_PATH) -> list[ScenarioCandidate]:
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(ScenarioCandidate.from_dict(json.loads(line)))
    return out


def find_duplicate(candidate: ScenarioCandidate, existing: list[ScenarioCandidate]) -> ScenarioCandidate | None:
    """Exact normalized-text duplicate only (Section 28) - never model
    similarity. A same-failure-family, different-text candidate is NOT
    reported here (that is a near-duplicate for a human to link manually,
    not something this function auto-merges)."""
    for other in existing:
        if other.source_reference_hash == candidate.source_reference_hash:
            return other
    return None


def append_candidate(candidate: ScenarioCandidate, path: Path = CANDIDATES_PATH) -> ScenarioCandidate | None:
    """Appends to the JSONL store. Returns the existing duplicate (if any)
    WITHOUT writing a second copy - callers decide whether that's an error
    or an expected re-submission."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_candidates(path)
    dup = find_duplicate(candidate, existing)
    if dup is not None:
        return dup
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(candidate.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    return None


def apply_human_review(
    candidate: ScenarioCandidate,
    *,
    reviewer: str,
    decision: str,
    expected_intent: str | None = None,
    expected_behavior: str | None = None,
    forbidden_behavior: tuple[str, ...] = (),
    authority: str | None = None,
    notes: str = "",
    reviewer_role: str | None = None,
    reproduction_status: str = NOT_ATTEMPTED,
    suspected_first_divergence: str | None = None,
    suspected_first_divergence_confidence: str | None = None,
    path: Path = REVIEWS_PATH,
) -> HumanReview:
    """Records a review decision as an immutable, append-only event
    (mirrors app.learning_lifecycle.record_transition's ledger pattern -
    same proven shape, not the same module, since this is a different
    system). NEVER mutates the original candidate record in candidates.
    jsonl - a reader reconstructs "current" status by reading the latest
    review event for a candidate_id, same as the ledger already does for
    ranking-candidate state."""
    review = HumanReview(
        candidate_id=candidate.candidate_id, reviewer=reviewer, reviewed_at=time.time(),
        decision=decision, expected_intent=expected_intent, expected_behavior=expected_behavior,
        forbidden_behavior=tuple(forbidden_behavior), authority=authority, notes=notes,
        reviewer_role=reviewer_role, reproduction_status=reproduction_status,
        suspected_first_divergence=suspected_first_divergence,
        suspected_first_divergence_confidence=suspected_first_divergence_confidence,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "candidate_id": review.candidate_id, "reviewer": review.reviewer,
            "reviewed_at": review.reviewed_at, "decision": review.decision,
            "expected_intent": review.expected_intent, "expected_behavior": review.expected_behavior,
            "forbidden_behavior": list(review.forbidden_behavior), "authority": review.authority,
            "notes": review.notes, "reviewer_role": review.reviewer_role,
            "reproduction_status": review.reproduction_status,
            "suspected_first_divergence": review.suspected_first_divergence,
            "suspected_first_divergence_confidence": review.suspected_first_divergence_confidence,
        }, ensure_ascii=False, sort_keys=True) + "\n")
    return review


def load_reviews(candidate_id: str | None = None, path: Path = REVIEWS_PATH) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if candidate_id is None or entry.get("candidate_id") == candidate_id:
                out.append(entry)
    return out


# --- reporting counters (Section 26, minimal) -------------------------------
def summarize(path: Path = CANDIDATES_PATH, reviews_path: Path = REVIEWS_PATH) -> dict:
    """Minimal counters only (Section 26 explicitly defers a dashboard) -
    computed fresh from the JSONL stores every call, no cached/derived
    state that could drift from the source of truth."""
    candidates = load_candidates(path)
    reviews = load_reviews(path=reviews_path)
    latest_decision: dict[str, str] = {}
    for r in reviews:
        latest_decision[r["candidate_id"]] = r["decision"]

    by_family: dict[str, int] = {}
    by_language: dict[str, int] = {}
    by_risk: dict[str, int] = {}
    by_source: dict[str, int] = {}
    pending = approved = rejected = 0
    for c in candidates:
        by_family[c.suspected_failure_family] = by_family.get(c.suspected_failure_family, 0) + 1
        by_language[c.language] = by_language.get(c.language, 0) + 1
        by_risk[c.risk_level] = by_risk.get(c.risk_level, 0) + 1
        by_source[c.source_type] = by_source.get(c.source_type, 0) + 1
        decision = latest_decision.get(c.candidate_id)
        if decision == REVIEW_APPROVE_AS_SCENARIO:
            approved += 1
        elif decision == REVIEW_REJECT_NO_CLEAR_GT:
            rejected += 1
        else:
            pending += 1

    return {
        "total_candidates": len(candidates),
        "pending": pending, "approved": approved, "rejected": rejected,
        "by_failure_family": by_family, "by_language": by_language,
        "by_risk": by_risk, "by_source_type": by_source,
    }
