"""
app/workflow_resolver.py  -  V2.13b: WorkflowResolver & WorkflowResolution.

Answers "what should the Advisor do?" given a TurnAnalysis (app.turn_resolver).
Pure function, no I/O, no product retrieval, no ranking (Section 19/56) -
this is the layer Invariant #6 describes: WORKFLOW RESOLUTION DECIDES THE
TASK, retrieval decides eligible products, ranking decides order,
presentation decides display. This module never touches any of the other
three.

Each TurnAnalysis passed in is a PARTIAL snapshot from one specific stage
of app.main._chat_impl()'s pipeline (see app/turn_resolver.py's module
docstring for why there are multiple entry points rather than one).
resolve_workflow() inspects whichever fields are populated and returns
the single primary decision relevant to that stage - this is still ONE
canonical decision function (Section 23/83), not two competing resolvers.
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass, field

WORKFLOW_ALLERGEN_SAFETY = "ALLERGEN_SAFETY"
WORKFLOW_RELATED_PRODUCTS = "RELATED_PRODUCTS"
WORKFLOW_RESULTSET_CONTINUATION = "RESULTSET_CONTINUATION"
WORKFLOW_LEGACY_FALLBACK = "LEGACY_FALLBACK"

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"


@dataclass(frozen=True)
class WorkflowResolution:
    workflow_id: str
    confidence: str
    reason: str
    evidence: tuple[str, ...] = field(default_factory=tuple)
    fallback_used: bool = False


def resolve_workflow(analysis) -> WorkflowResolution:
    """Deterministic precedence (Section 28, validated against actual
    current behavior in docs/workflow-precedence-before-v2.13b.md, not
    guessed):

      1. ACTIVE RESULTSET CONTINUATION (Show More/Show All) - a pure
         continuation of already-shown state always wins; it is not a
         new search of any kind.
      2. SAFETY / ALLERGEN (Invariant #3) - a recognized safety signal
         outranks ordinary product retrieval, INCLUDING when the message
         also happens to match a related-products anchor (rt0010's exact
         fix - the old guard's `not detect_related_subject(...)` veto is
         removed here, generically, for every case detect_allergen_intent()
         already recognizes, not just this one query).
      3. EXPLICIT RELATED-PRODUCTS ACTION (Invariant #1) - an explicit
         companion/action phrase ("súvisiace produkty k X") outranks the
         coarser product-family/special-subject match embedded in the
         same message (rt0004's exact fix).
      4. Otherwise: LEGACY_FALLBACK - the existing ~11-branch cascade in
         app.main._chat_impl() remains authoritative (Section 62's
         LegacyWorkflowAdapter), unchanged by this module."""
    if getattr(analysis, "active_result_set_continuation", False):
        return WorkflowResolution(
            workflow_id=WORKFLOW_RESULTSET_CONTINUATION,
            confidence=CONFIDENCE_HIGH,
            reason="ACTIVE_RESULT_SET_CONTINUATION",
            evidence=analysis.evidence,
        )

    if getattr(analysis, "safety_intent", None):
        return WorkflowResolution(
            workflow_id=WORKFLOW_ALLERGEN_SAFETY,
            confidence=CONFIDENCE_HIGH,
            reason="SAFETY_PRECEDENCE",
            evidence=analysis.evidence,
        )

    if getattr(analysis, "related_products_requested", False) and getattr(analysis, "related_products_anchor", None):
        return WorkflowResolution(
            workflow_id=WORKFLOW_RELATED_PRODUCTS,
            confidence=CONFIDENCE_HIGH,
            reason="EXPLICIT_ACTION_INTENT",
            evidence=analysis.evidence,
        )

    return WorkflowResolution(
        workflow_id=WORKFLOW_LEGACY_FALLBACK,
        confidence=CONFIDENCE_LOW,
        reason="NO_NATIVE_WORKFLOW_MATCHED",
        evidence=getattr(analysis, "evidence", ()),
        fallback_used=True,
    )


# ---------------------------------------------------------------------
# Per-request resolution stash (Section 88/129 - additive SearchQualityTrace
# extension). Same ContextVar pattern as app.search_quality's retrieval-
# decision stash (V2.12.4) - a plain assignment, no I/O, isolated per
# request the same way (Section 42/105).
# ---------------------------------------------------------------------
_last_resolution: contextvars.ContextVar[WorkflowResolution | None] = contextvars.ContextVar(
    "workflow_resolver_last_resolution", default=None
)


def reset_last_resolution() -> None:
    _last_resolution.set(None)


def stash_resolution(resolution: WorkflowResolution) -> None:
    """Only NATIVE resolutions (not LEGACY_FALLBACK) are stashed - a
    fallback means app.main's existing cascade made the actual decision,
    so there is nothing new to report (Section 90's legacy-fallback-rate
    is derived from its ABSENCE, not a fallback record)."""
    if resolution.workflow_id != WORKFLOW_LEGACY_FALLBACK:
        _last_resolution.set(resolution)


def pop_last_resolution() -> WorkflowResolution | None:
    return _last_resolution.get()
