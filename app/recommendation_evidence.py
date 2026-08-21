"""
app/recommendation_evidence.py  -  V2.14a Recommendation Intelligence
Foundation: evidence provenance, deterministic confidence, and the
RECOMMEND/CLARIFY/ABSTAIN decision contract.

Scope (docs/recommendation-intelligence-v2.14a.md has the full audit):
this module is a NEW, SMALL, ISOLATED foundation - GATE A of the V2.14a
audit. It is intentionally NOT wired into app.main._chat_impl() or any
customer-facing response path in this sprint (Section 30 - no customer
behavior change). It exists so V2.14b (comparison/best-choice) has a
tested, safe place to compute confidence instead of inventing one
inline, ad-hoc, under schedule pressure.

Why a new module instead of extending an existing one (Section 29):
app.cross_sell answers "what else completes this task" (eligibility/
completion, not confidence-scored choice). app.ranking_features decomposes
a SINGLE product's rank into named factors (not multi-candidate
recommendation confidence). app.taxonomy classifies a product's
family/subfamily (not whether a customer-facing claim about it is safe
to make). None of these own "given some evidence about a candidate,
how sure are we, and should we recommend/clarify/abstain" - that is a
genuinely new, cross-cutting concern layered ON TOP of all of them.

CRITICAL INVARIANT (Section 12 of the V2.14a spec, enforced structurally
below, not just by convention): HIGH confidence can never arise from
LLM_JUDGMENT-only evidence. See compute_confidence()'s docstring for the
exact proof.

Evidence provenance audit backing this contract (full detail in
docs/recommendation-intelligence-v2.14a.md):
- Taxonomy canonical_family/canonical_subfamily is DATA_DERIVED only for
  the HIGH confidence tier (24.8% of the 2140-product catalog, backed by
  a real Foodland category-path match) - MEDIUM/LOW tiers are weaker and
  must not be presented as equivalently certain.
- app.cross_sell's role-based candidate matching (recipe/use-case
  completion) is INFERRED: deterministic rule application over trusted
  data (canonical_subfamily + a curated role index), reproducible and
  testable, but one inferential step removed from a raw catalog fact.
- Free-text qualitative claims ("more authentic", "better balanced
  flavor", "premium choice") that are not backed by a structured field
  are LLM_JUDGMENT - the audit found ~65.6% of the catalog has NO
  taxonomy family/subfamily claim available at all (UNKNOWN tier), so
  for most of the catalog today, unstructured LLM phrasing is the ONLY
  thing standing behind any comparative claim unless this contract
  gates it.
"""
from __future__ import annotations

from dataclasses import dataclass

# --- evidence provenance (Section 10) ---------------------------------------
PROVENANCE_DATA_DERIVED = "DATA_DERIVED"
PROVENANCE_INFERRED = "INFERRED"
PROVENANCE_LLM_JUDGMENT = "LLM_JUDGMENT"
_VALID_PROVENANCE = frozenset({PROVENANCE_DATA_DERIVED, PROVENANCE_INFERRED, PROVENANCE_LLM_JUDGMENT})

# --- confidence levels (Section 20) -----------------------------------------
CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"
CONFIDENCE_INSUFFICIENT = "INSUFFICIENT"

# --- decision policy (Section 13) -------------------------------------------
DECISION_RECOMMEND = "RECOMMEND"
DECISION_CLARIFY = "CLARIFY"
DECISION_ABSTAIN = "ABSTAIN"

_STRONG_STRENGTH = 0.75
_VERY_STRONG_STRENGTH = 0.9
_USABLE_STRENGTH = 0.5


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """One piece of evidence about one recommendation candidate.

    `strength` is a deterministic, caller-supplied 0..1 value the
    caller computes from its own trusted source (e.g. taxonomy
    confidence tier, cross_sell role-match score) - this module never
    invents or adjusts strength itself, it only aggregates.
    """

    reason_code: str
    provenance: str
    source: str
    strength: float
    customer_visible: bool = True

    def __post_init__(self) -> None:
        if self.provenance not in _VALID_PROVENANCE:
            raise ValueError(f"invalid provenance {self.provenance!r}, must be one of {sorted(_VALID_PROVENANCE)}")
        if not (0.0 <= self.strength <= 1.0):
            raise ValueError(f"strength must be in [0.0, 1.0], got {self.strength!r}")
        if not self.reason_code:
            raise ValueError("reason_code must not be empty")


def compute_confidence(evidence_items: list[EvidenceItem]) -> str:
    """Deterministic, reproducible confidence from evidence provenance
    and strength alone - never from how eloquent an LLM claim sounds.

    Proof of the Section 12 invariant (HIGH never from LLM_JUDGMENT-only
    evidence): `grounded` excludes every LLM_JUDGMENT item. The single
    branch that can return CONFIDENCE_HIGH is reached only through the
    `if not grounded: return CONFIDENCE_LOW` early-return above it - so
    by construction, CONFIDENCE_HIGH is only reachable when `grounded`
    (DATA_DERIVED or INFERRED evidence) is non-empty. This is not a
    convention callers must remember; it is structurally impossible to
    reach HIGH any other way in this function.
    """
    if not evidence_items:
        return CONFIDENCE_INSUFFICIENT

    grounded = [item for item in evidence_items if item.provenance != PROVENANCE_LLM_JUDGMENT]
    if not grounded:
        # LLM_JUDGMENT-only evidence is real evidence, just never strong
        # enough on its own to justify more than LOW (Section 12/21).
        return CONFIDENCE_LOW

    strong_grounded = [item for item in grounded if item.strength >= _STRONG_STRENGTH]
    if len(strong_grounded) >= 2 or any(item.strength >= _VERY_STRONG_STRENGTH for item in strong_grounded):
        return CONFIDENCE_HIGH
    if any(item.strength >= _USABLE_STRENGTH for item in grounded):
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


def decide(
    evidence_items: list[EvidenceItem],
    *,
    has_meaningful_differentiation: bool = True,
    missing_customer_info: bool = False,
) -> str:
    """RECOMMEND / CLARIFY / ABSTAIN (Section 13).

    Precedence, most conservative first:
    1. missing_customer_info -> CLARIFY (the caller determined the
       decision depends on information the customer has not given -
       e.g. no use_case resolved for an ambiguous bare-family query).
       This module never guesses what to ask; it only honors the
       caller's own determination that clarification is needed.
    2. no evidence at all, or evidence too weak to differentiate
       candidates -> ABSTAIN. ABSTAIN does not mean "return nothing" -
       callers may still show factual candidates, they just must not
       label one of them "best".
    3. otherwise -> RECOMMEND.
    """
    confidence = compute_confidence(evidence_items)

    if missing_customer_info and confidence != CONFIDENCE_INSUFFICIENT:
        return DECISION_CLARIFY

    if confidence == CONFIDENCE_INSUFFICIENT:
        return DECISION_ABSTAIN

    if not has_meaningful_differentiation:
        return DECISION_ABSTAIN

    if confidence == CONFIDENCE_LOW and all(item.provenance == PROVENANCE_LLM_JUDGMENT for item in evidence_items):
        # Confidence is LOW *because* every item is LLM_JUDGMENT (not
        # merely weak deterministic evidence) - Section 12/21 prefer
        # ABSTAIN over a recommendation that would rest entirely on
        # unverifiable qualitative judgment.
        return DECISION_ABSTAIN

    return DECISION_RECOMMEND
