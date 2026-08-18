"""
app/learning_candidates.py  -  V2.12: structured candidate generator.

Converts a `LearningOpportunity` (app.learning_opportunities) into either
a REVIEW_REQUIRED report (no actionable config - the default for
anything touching retrieval/taxonomy/semantic truth) or, for the one
LOW-RISK opportunity type this sprint supports (RANKING_POSITION_ANOMALY),
a concrete `RankingProfile` candidate that is REUSED, not reimplemented,
through V2.11's own machinery end to end (Section 43: "Do not create a
second ranking system"):

    LearningOpportunity
          |
    app.ranking_config.RankingProfile.with_family_override(...)   <- V2.11
          |
    app.ranking_optimizer.evaluate_profile(candidate)              <- V2.11,
          |                                                            which
    app.evaluation (V2.10 golden + conversation suite, quality gates)  itself
          |                                                            runs
    LearningCandidate(decision=REJECTED|REVIEW_REQUIRED|SHADOW_ELIGIBLE) V2.10

No candidate ever becomes production-active from this module (Section 46)
- SHADOW_ELIGIBLE is the highest decision this module can reach; promotion
past that is app.learning_lifecycle's job, and it requires human approval
by default (Section 55/56).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace

from app.learning_opportunities import (
    ACTION_RANKING_WEIGHT_ADJUSTMENT,
    LearningOpportunity,
    TYPE_HIGH_REFORMULATION_RATE,
    TYPE_HIGH_ZERO_RESULT,
    TYPE_LOW_TOP1_SELECTION,
    TYPE_RANKING_POSITION_ANOMALY,
    TYPE_TAXONOMY_GAP_CANDIDATE,
)
from app.ranking_config import BEHAVIORAL_WEIGHT_BOUNDS, RankingProfile, RankingProfileError
from app.ranking_optimizer import CandidateEvaluation, evaluate_profile

RISK_LOW = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH = "HIGH"

DECISION_REJECTED = "REJECTED"
DECISION_REVIEW_REQUIRED = "REVIEW_REQUIRED"
DECISION_SHADOW_ELIGIBLE = "SHADOW_ELIGIBLE"

REASON_INSUFFICIENT_SUPPORT = "INSUFFICIENT_SUPPORT"
REASON_SEMANTIC_REGRESSION = "SEMANTIC_REGRESSION"
REASON_NO_MEANINGFUL_IMPROVEMENT = "NO_MEANINGFUL_IMPROVEMENT"
REASON_PERFORMANCE_REGRESSION = "PERFORMANCE_REGRESSION"
REASON_CONTEXT_REGRESSION = "CONTEXT_REGRESSION"
REASON_CROSS_SELL_REGRESSION = "CROSS_SELL_REGRESSION"
REASON_RECIPE_REGRESSION = "RECIPE_REGRESSION"
REASON_CONFIG_INVALID = "CONFIG_INVALID"
REASON_AMBIGUOUS_EVIDENCE = "AMBIGUOUS_EVIDENCE"

# Section 38 - only RANKING_POSITION_ANOMALY produces a LOW-RISK,
# automatable candidate this sprint. Everything else stays REVIEW_
# REQUIRED/MEDIUM-or-HIGH - see app.learning_opportunities' own docstring
# for why (retrieval/taxonomy/alias changes are never auto-actionable).
_RISK_BY_OPPORTUNITY_TYPE = {
    TYPE_RANKING_POSITION_ANOMALY: RISK_LOW,
    TYPE_LOW_TOP1_SELECTION: RISK_MEDIUM,
    TYPE_HIGH_REFORMULATION_RATE: RISK_MEDIUM,
    TYPE_HIGH_ZERO_RESULT: RISK_HIGH,
    TYPE_TAXONOMY_GAP_CANDIDATE: RISK_HIGH,
}

# Section 37/44 - the directed nudge step for a ranking-weight candidate.
# Deliberately small relative to BEHAVIORAL_WEIGHT_BOUNDS' full [0,3]
# range - this is a bounded, evidence-guided perturbation, not a search.
BEHAVIORAL_WEIGHT_STEP = float(os.getenv("LEARNING_BEHAVIORAL_WEIGHT_STEP", "0.3"))

# Section 48 - passing gates is not enough; require a real margin over
# the baseline's own composite objective, not just a non-negative delta.
MIN_IMPROVEMENT_MARGIN = float(os.getenv("LEARNING_MIN_IMPROVEMENT_MARGIN", "0.005"))


@dataclass(frozen=True)
class LearningCandidate:
    id: str
    opportunity_id: str
    opportunity_type: str
    risk_class: str
    decision: str
    profile: RankingProfile | None
    rejection_reasons: tuple[str, ...]
    baseline_objective: float | None
    candidate_objective: float | None
    explanation: dict


def _explanation(
    opportunity: LearningOpportunity,
    *,
    proposed_change: str,
    target_metric: str,
    could_regress: str,
    v210_result: str,
) -> dict:
    """Section 65 - every proposed change must answer these seven
    questions explicitly, not just carry raw numbers."""
    return {
        "what_did_we_observe": opportunity.evidence,
        "why_is_it_a_problem": f"{opportunity.type} detected in scope={opportunity.scope!r} "
                                f"with sample_size={opportunity.sample_size}, confidence={opportunity.confidence}",
        "what_change_is_proposed": proposed_change,
        "what_metric_should_improve": target_metric,
        "what_could_regress": could_regress,
        "what_did_v210_show": v210_result,
        "what_did_shadow_show": "not yet run - see app.learning_lifecycle",
    }


def generate_candidate(
    opportunity: LearningOpportunity,
    base_profile: RankingProfile,
    *,
    fast: bool = True,
) -> LearningCandidate:
    """Section 36/37/65 - the single entry point turning one opportunity
    into one LearningCandidate. Never raises on a well-formed opportunity
    (invalid/unsafe inputs resolve to REJECTED/REVIEW_REQUIRED, never an
    exception - a learning-cycle failure must not be able to crash the
    caller, Section 100)."""
    risk = _RISK_BY_OPPORTUNITY_TYPE.get(opportunity.type, RISK_HIGH)

    if opportunity.proposed_action_type != ACTION_RANKING_WEIGHT_ADJUSTMENT or risk != RISK_LOW:
        return LearningCandidate(
            id=f"candidate:{opportunity.id}",
            opportunity_id=opportunity.id,
            opportunity_type=opportunity.type,
            risk_class=risk,
            decision=DECISION_REVIEW_REQUIRED,
            profile=None,
            rejection_reasons=(),
            baseline_objective=None,
            candidate_objective=None,
            explanation=_explanation(
                opportunity,
                proposed_change="No automatic config change - human review of the underlying "
                                "retrieval/taxonomy/routing behavior for this scope is required.",
                target_metric="n/a (not a ranking-weight candidate)",
                could_regress="n/a",
                v210_result="not run - MEDIUM/HIGH risk opportunities never reach the evaluation harness (Section 39)",
            ),
        )

    family = opportunity.scope
    current_weights = base_profile.weights_for(family)
    new_weight = min(BEHAVIORAL_WEIGHT_BOUNDS[1], current_weights.behavioral_weight + BEHAVIORAL_WEIGHT_STEP)

    try:
        candidate_profile = base_profile.with_family_override(family, behavioral_weight=new_weight)
        candidate_profile = replace(
            candidate_profile,
            version=f"learning-{opportunity.id.replace(':', '-')}",
            name=f"learning candidate for {family}",
            description=f"Auto-generated from opportunity {opportunity.id}: "
                         f"behavioral_weight {current_weights.behavioral_weight} -> {new_weight} for family={family!r}.",
        )
        candidate_profile.validate()
    except RankingProfileError as exc:
        return LearningCandidate(
            id=f"candidate:{opportunity.id}",
            opportunity_id=opportunity.id,
            opportunity_type=opportunity.type,
            risk_class=risk,
            decision=DECISION_REJECTED,
            profile=None,
            rejection_reasons=(REASON_CONFIG_INVALID,),
            baseline_objective=None,
            candidate_objective=None,
            explanation=_explanation(
                opportunity, proposed_change=f"invalid candidate config: {exc}",
                target_metric="n/a", could_regress="n/a", v210_result="not run - config rejected before evaluation",
            ),
        )

    baseline_eval: CandidateEvaluation = evaluate_profile(base_profile, fast=fast)
    candidate_eval: CandidateEvaluation = evaluate_profile(candidate_profile, fast=fast)

    proposed_change = (
        f"RankingProfile family_override[{family!r}].behavioral_weight: "
        f"{current_weights.behavioral_weight} -> {new_weight}"
    )
    target_metric = "golden pass_rate / eligibility precision / precision@5 / recall@5 / MRR (composite objective)"
    could_regress = "any golden/conversation case for this family; context contamination; duplicate results"

    if candidate_eval.rejected:
        reasons = _map_gate_to_reasons(candidate_eval.gate)
        return LearningCandidate(
            id=f"candidate:{opportunity.id}",
            opportunity_id=opportunity.id,
            opportunity_type=opportunity.type,
            risk_class=risk,
            decision=DECISION_REJECTED,
            profile=candidate_profile,
            rejection_reasons=reasons,
            baseline_objective=baseline_eval.objective,
            candidate_objective=candidate_eval.objective,
            explanation=_explanation(
                opportunity, proposed_change=proposed_change, target_metric=target_metric,
                could_regress=could_regress,
                v210_result=f"gate={candidate_eval.gate['gate']}, blocking_reasons={candidate_eval.gate['blocking_reasons']}",
            ),
        )

    # Section 48 - passing gates is not enough; require a real margin.
    if candidate_eval.objective <= baseline_eval.objective * (1 + MIN_IMPROVEMENT_MARGIN):
        return LearningCandidate(
            id=f"candidate:{opportunity.id}",
            opportunity_id=opportunity.id,
            opportunity_type=opportunity.type,
            risk_class=risk,
            decision=DECISION_REJECTED,
            profile=candidate_profile,
            rejection_reasons=(REASON_NO_MEANINGFUL_IMPROVEMENT,),
            baseline_objective=baseline_eval.objective,
            candidate_objective=candidate_eval.objective,
            explanation=_explanation(
                opportunity, proposed_change=proposed_change, target_metric=target_metric,
                could_regress=could_regress,
                v210_result=f"gate=PASS/WARN but objective {candidate_eval.objective:.4f} did not "
                             f"meaningfully exceed baseline {baseline_eval.objective:.4f}",
            ),
        )

    return LearningCandidate(
        id=f"candidate:{opportunity.id}",
        opportunity_id=opportunity.id,
        opportunity_type=opportunity.type,
        risk_class=risk,
        decision=DECISION_SHADOW_ELIGIBLE,
        profile=candidate_profile,
        rejection_reasons=(),
        baseline_objective=baseline_eval.objective,
        candidate_objective=candidate_eval.objective,
        explanation=_explanation(
            opportunity, proposed_change=proposed_change, target_metric=target_metric,
            could_regress=could_regress,
            v210_result=f"gate={candidate_eval.gate['gate']}, objective improved {baseline_eval.objective:.4f} "
                         f"-> {candidate_eval.objective:.4f}",
        ),
    )


def _map_gate_to_reasons(gate: dict) -> tuple[str, ...]:
    """Section 96 - translate V2.10's blocking_reasons into the V2.12
    rejection-reason vocabulary. Best-effort text matching against the
    real, existing `evaluate_quality_gates()` message strings (app.
    evaluation.baseline) - never invents a reason absent from the gate."""
    reasons = []
    for blocking in gate.get("blocking_reasons", []):
        text = blocking.lower()
        if "contamination" in text:
            reasons.append(REASON_CONTEXT_REGRESSION)
        elif "duplicate" in text:
            reasons.append(REASON_SEMANTIC_REGRESSION)
        elif "critical" in text:
            reasons.append(REASON_SEMANTIC_REGRESSION)
        else:
            reasons.append(REASON_AMBIGUOUS_EVIDENCE)
    return tuple(dict.fromkeys(reasons)) or (REASON_SEMANTIC_REGRESSION,)


def generate_candidates(
    opportunities: list[LearningOpportunity],
    base_profile: RankingProfile,
    *,
    fast: bool = True,
) -> list[LearningCandidate]:
    return [generate_candidate(o, base_profile, fast=fast) for o in opportunities]
