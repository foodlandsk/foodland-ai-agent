"""
app/turn_resolver.py  -  V2.13b: TurnResolver & TurnAnalysis.

Answers ONE question: "what is in this turn?" - never "what should the
Advisor do?" (that is app.workflow_resolver's job, Section 12).

TurnResolver does NOT execute product retrieval, does NOT rank products,
does NOT generate answers, does NOT make HTTP decisions (Section 14). It
is a pure, side-effect-free function over already-computed detector
outputs - it reuses app.main's existing, already-well-gated detectors
(detect_allergen_intent, allergen_product_query, detect_related_subject,
_has_recipe_shopping_language, ...) rather than reimplementing intent
detection (Section 16/81/82 - existing markers remain valid signal
sources, they just no longer independently execute a workflow branch).

Two call sites, not one (docs/workflow-precedence-before-v2.13b.md):
app.main._chat_impl() consults the safety signal at the point where the
raw message's allergen intent is already known (before most of the
cascade even runs, since a SAFETY match returns immediately), and the
action/target signal at the point where special_subject/related_subject
are already known (later in the cascade, against the contextualized
message). These are sequential stages of the SAME pipeline, not two
competing resolutions of the same information - a turn that matches the
first never reaches the second.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TurnAnalysis:
    """Structured signal snapshot for one customer turn. Fields default to
    "unknown/not applicable" so each TurnResolver entry point can populate
    only what it has actually computed at its point in the pipeline
    (Section 15 - do not add fields with no current use; every field here
    is read by app.workflow_resolver.resolve_workflow())."""

    normalized_message: str = ""

    # Safety / allergen (Section 29/45/47/48).
    safety_intent: str | None = None
    safety_has_product_evidence: bool = False
    safety_zero_product_signal: bool = False

    # Action vs. target separation (Section 31/32, Invariant #1).
    related_products_requested: bool = False
    related_products_anchor: str | None = None

    # ResultSet continuation (Section 35/36, already causal - formalized here).
    active_result_set_continuation: bool = False

    evidence: tuple[str, ...] = field(default_factory=tuple)


def resolve_safety_signal(
    message: str,
    *,
    allergen_term: str | None,
    allergen_product_query_result: str,
    related_subject: str | None,
) -> TurnAnalysis:
    """Section 7/29/45 - rt0010's exact fix point. `allergen_term` is
    already the output of app.main.detect_allergen_intent(), an
    extensively-gated detector (excludes bare recipe mentions, generic
    taste questions, "nahrada" fish-sauce combos, ...) - TurnResolver does
    not re-derive or second-guess it, only decides what it MEANS for
    workflow precedence.

    Root cause (docs/workflow-precedence-before-v2.13b.md): the legacy
    guard `allergen_term and (allergen_product_query(...) or not
    detect_related_subject(...))` treats an EMPTY string from
    allergen_product_query() as "not applicable" - but allergen_product_query()
    deliberately returns "" for a recognized zero-safe-product case (e.g.
    "bez soj"/"bez soja"), which is a MEANINGFUL affirmative safety signal,
    not an absence of one. TurnResolver captures that distinction
    explicitly via `safety_zero_product_signal` instead of conflating it
    with "no match"."""
    evidence = []
    if allergen_term:
        evidence.append(f"allergen_term={allergen_term!r}")
    has_product_evidence = bool(allergen_product_query_result)
    if has_product_evidence:
        evidence.append("allergen_product_query_matched")
    zero_product_signal = allergen_term is not None and not has_product_evidence
    if zero_product_signal:
        evidence.append("allergen_product_query_explicit_zero_result")
    if related_subject:
        evidence.append(f"related_subject_also_matched={related_subject!r}")
    return TurnAnalysis(
        normalized_message=message,
        safety_intent=allergen_term,
        safety_has_product_evidence=has_product_evidence,
        safety_zero_product_signal=zero_product_signal,
        evidence=tuple(evidence),
    )


def resolve_action_target_signal(
    contextual_message: str,
    *,
    special_subject: str | None,
    related_subject: str | None,
    has_recipe_shopping_language: bool,
    resolves_confident_product_family: bool,
) -> TurnAnalysis:
    """Section 7/30/31/42 - rt0004's exact fix point. `special_subject` is
    a coarser, earlier-precedence substring detector
    (detect_special_product_subject) than `related_subject`
    (detect_related_subject) - the legacy cascade unconditionally let
    special_subject null out related_subject with no regard for whether
    the message carries explicit companion/action language.

    `has_recipe_shopping_language` reuses app.main.RECIPE_SHOPPING_LANGUAGE_MARKERS
    (curated, already battle-tested by V2.12.2's own regbug_rt0005
    regression fix) as the ACTION signal - not a new marker list
    (Invariant #10: fix generically, not by hard-coding this one query).

    `special_subject` is a required condition, not just evidence: this
    resolver's only job is to arbitrate the special_subject-vs-related_subject
    CONFLICT (special_subject nulling related_subject before action
    language was consulted). Without a special_subject there is no
    conflict to arbitrate - a bare related_subject with action language
    (e.g. session-context follow-ups like "co odporucas?" after
    contextualize_message() carries a prior subject forward) already
    flows correctly through the pre-existing, unmodified
    `elif related_subject:` branch further down the cascade. Dropping
    this condition previously let the resolver hijack dispatch for turns
    the original bug never touched, including session-memory-derived
    related_subject values that were never validated against action
    language in the first place (found via regbug_rt0011 regression -
    session_id reuse surfaced a case where a plain "what do you
    recommend?" follow-up was misrouted to RELATED_PRODUCTS)."""
    evidence = []
    if special_subject:
        evidence.append(f"special_subject={special_subject!r}")
    if related_subject:
        evidence.append(f"related_subject={related_subject!r}")
    if has_recipe_shopping_language:
        evidence.append("explicit_action_language_present")
    if resolves_confident_product_family:
        evidence.append("resolves_confident_product_family")

    # The action is genuinely requested only when there is a real
    # special_subject/related_subject CONFLICT to arbitrate (Invariant #1)
    # - a coarse special_subject match alone (no action language) must NOT
    # be reinterpreted as a related-products request (Section 74/77:
    # "sushi ryza" alone, or "ryza" alone, must remain ordinary search),
    # and a bare related_subject with no competing special_subject has
    # nothing to arbitrate - it already reaches the correct outcome via
    # the unmodified legacy `elif related_subject:` branch.
    requested = bool(special_subject) and bool(related_subject) and has_recipe_shopping_language

    return TurnAnalysis(
        normalized_message=contextual_message,
        related_products_requested=requested,
        related_products_anchor=related_subject if requested else None,
        evidence=tuple(evidence),
    )


def resolve_resultset_continuation_signal(message: str, *, active_result_set_id: str, wants_continuation: bool) -> TurnAnalysis:
    """Section 35/36 - formalizes the ALREADY-causal Show More/Show All
    path (app.main._chat_impl, unchanged logic) as a TurnAnalysis/
    WorkflowResolution for observability (Section 88) - does not change
    behavior."""
    evidence = []
    if active_result_set_id:
        evidence.append("active_result_set_present")
    if wants_continuation:
        evidence.append("show_more_or_show_all_marker")
    return TurnAnalysis(
        normalized_message=message,
        active_result_set_continuation=bool(active_result_set_id) and wants_continuation,
        evidence=tuple(evidence),
    )
