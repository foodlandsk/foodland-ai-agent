"""
app/ranking_optimizer.py  -  V2.11 bounded offline ranking optimizer.

Generates candidate RankingProfiles by bounded perturbation of a base
profile and evaluates EVERY candidate through the REAL V2.10 evaluation
harness (app.evaluation) - never a synthetic proxy metric (Section 45).
Applies the same baseline-regression quality gates V2.10 already uses
(app.evaluation.baseline.evaluate_quality_gates) so a candidate that
regresses a critical case, or introduces context contamination / duplicate
results, is rejected outright regardless of how good its composite score
looks (Section 51/110-112 - anti-gaming). The objective itself blends
multiple metrics (Section 55 - never a single-metric optimization), so a
candidate cannot look good by trading one metric against another either.

This module never mutates config/ranking_profiles/active.json - `optimize()`
returns a recommendation. Activating it is a separate, explicit step
(app.ranking_config.set_active_ranking_profile_version), left to a human
via scripts/ranking_cli.py - a fully automated apply-the-winner loop is
deliberately NOT built here; that is V2.12's job (Section 130), and this
sprint's optimizer is architecturally ready for it without being it."""
from __future__ import annotations

import random
from dataclasses import dataclass, replace

from app.evaluation.adapter import get_taxonomy_index, make_chat_fn, make_session_chat_fn
from app.execution_context import learning_context
from app.evaluation.baseline import GATE_FAIL, aggregate_results, evaluate_quality_gates, load_baseline
from app.evaluation.conversation import run_conversation_suite
from app.evaluation.loader import BASELINES_DIR, load_all_conversation_cases, load_all_golden_cases
from app.evaluation.runner import run_golden_suite
from app.evaluation.taxonomy_quality import taxonomy_coverage, taxonomy_precision_against_golden
from app.ranking_config import (
    BEHAVIORAL_MAX_RATIO_BOUNDS,
    BEHAVIORAL_MIN_RATIO_BOUNDS,
    BEHAVIORAL_WEIGHT_BOUNDS,
    MERCHANDISING_EXPONENT_BOUNDS,
    PERSONALIZATION_CAP_BOUNDS,
    RankingProfile,
    RankingProfileError,
    RankingWeights,
    use_ranking_profile,
)

# Perturbation step size per field - a candidate is CONSTRUCTED already
# clamped inside RankingWeights' own validated bounds (Section 111);
# evaluate_profile() still independently re-validates as defense in depth,
# so a bug in this generator can never be the only thing standing between
# an out-of-bounds config and evaluation.
_PERTURB_STEP = {
    "behavioral_weight": 0.5,
    "behavioral_min_ratio": 0.1,
    "behavioral_max_ratio": 0.5,
    "merchandising_exponent": 0.5,
    "personalization_cap": 0.2,
}
_FIELD_BOUNDS = {
    "behavioral_weight": BEHAVIORAL_WEIGHT_BOUNDS,
    "behavioral_min_ratio": BEHAVIORAL_MIN_RATIO_BOUNDS,
    "behavioral_max_ratio": BEHAVIORAL_MAX_RATIO_BOUNDS,
    "merchandising_exponent": MERCHANDISING_EXPONENT_BOUNDS,
    "personalization_cap": PERSONALIZATION_CAP_BOUNDS,
}


@dataclass(frozen=True)
class CandidateEvaluation:
    profile: RankingProfile
    summary: dict
    gate: dict
    objective: float
    rejected: bool
    rejection_reason: str | None


def generate_candidate_profiles(base: RankingProfile, n: int, *, seed: int) -> list[RankingProfile]:
    """Bounded, deterministic-given-`seed` perturbation of `base.default`
    (Section 45/46/109 - reproducible, not real randomness reused across
    runs)."""
    rng = random.Random(seed)
    candidates = []
    for i in range(n):
        base_weights = base.default
        kwargs = {}
        for field_name, step in _PERTURB_STEP.items():
            lo, hi = _FIELD_BOUNDS[field_name]
            current = getattr(base_weights, field_name)
            kwargs[field_name] = max(lo, min(hi, current + rng.uniform(-step, step)))
        candidate_weights = RankingWeights(**kwargs)
        if candidate_weights.behavioral_min_ratio > candidate_weights.behavioral_max_ratio:
            candidate_weights = replace(candidate_weights, behavioral_min_ratio=candidate_weights.behavioral_max_ratio)
        candidates.append(RankingProfile(
            version=f"candidate-{seed}-{i}",
            name=f"optimizer candidate {i}",
            description=f"Bounded perturbation of {base.version} (seed={seed}, index={i})",
            default=candidate_weights,
        ))
    return candidates


def _composite_objective(summary: dict) -> float:
    """Multi-metric objective (Section 55) - blends golden pass_rate,
    eligibility precision, precision@5, recall@5 and MRR so no single
    metric can be gamed in isolation (e.g. inflating recall with
    irrelevant-but-in-stock items is still caught by the precision terms)."""
    golden = summary.get("golden", {})
    terms = [
        golden.get("pass_rate"),
        golden.get("avg_eligibility_precision"),
        golden.get("avg_precision_at_5"),
        golden.get("avg_recall_at_5"),
        golden.get("mrr"),
    ]
    present = [t for t in terms if t is not None]
    return sum(present) / len(present) if present else 0.0


def evaluate_profile(profile: RankingProfile, *, fast: bool = False) -> CandidateEvaluation:
    """Runs the REAL V2.10 evaluation harness with `profile` active for
    the duration of this call only (`use_ranking_profile` - Section 62/63:
    never touches config/ranking_profiles/active.json, so this can never
    expose a candidate to real customer traffic)."""
    try:
        profile.validate()
    except RankingProfileError as exc:
        return CandidateEvaluation(
            profile, {}, {"gate": GATE_FAIL, "blocking_reasons": [str(exc)], "warnings": []}, 0.0, True, str(exc),
        )

    taxonomy_index = get_taxonomy_index()
    all_golden_cases = load_all_golden_cases()
    all_conversation_cases = load_all_conversation_cases()
    golden_cases = [c for c in all_golden_cases if c.critical] if fast else all_golden_cases
    conversation_cases = [c for c in all_conversation_cases if c.critical] if fast else all_conversation_cases

    with use_ranking_profile(profile):
        chat_fn = make_chat_fn(execution_context=learning_context())
        golden_results = run_golden_suite(golden_cases, lambda q, limit: chat_fn(q, limit), taxonomy_index)
        session_chat_fn = make_session_chat_fn(execution_context=learning_context())
        conversation_results = run_conversation_suite(conversation_cases, session_chat_fn)

    tax_stats = taxonomy_coverage(taxonomy_index)
    tax_stats.update(taxonomy_precision_against_golden(all_golden_cases, taxonomy_index))
    summary = aggregate_results(golden_results, conversation_results, tax_stats)

    critical_case_ids = frozenset(c.id for c in all_golden_cases if c.critical) | frozenset(
        c.id for c in all_conversation_cases if c.critical
    )
    baseline_path = BASELINES_DIR / "v2.9.json"
    baseline = load_baseline(baseline_path) if baseline_path.exists() else None

    gate = evaluate_quality_gates(summary, baseline, critical_case_ids)
    objective = _composite_objective(summary)
    rejected = gate["gate"] == GATE_FAIL
    reason = "; ".join(gate["blocking_reasons"]) if rejected else None
    return CandidateEvaluation(profile, summary, gate, objective, rejected, reason)


def optimize(base: RankingProfile, *, n_candidates: int, seed: int, fast: bool = True) -> dict:
    """Bounded offline search (Section 45-58): evaluates `base` plus
    `n_candidates` perturbations of it through the real harness, rejects
    any candidate that fails the quality gate, and recommends the best
    surviving candidate by composite objective - or honestly recommends
    KEEPING `base` if nothing beat it (Section 115/127: the point is to
    find a genuine improvement, never to manufacture one)."""
    baseline_eval = evaluate_profile(base, fast=fast)
    candidates = generate_candidate_profiles(base, n_candidates, seed=seed)
    evaluations = [evaluate_profile(c, fast=fast) for c in candidates]

    survivors = [e for e in evaluations if not e.rejected]
    rejected = [e for e in evaluations if e.rejected]
    best = max(survivors, key=lambda e: e.objective, default=None)
    improved = best is not None and best.objective > baseline_eval.objective

    return {
        "base_profile_version": base.version,
        "baseline_objective": baseline_eval.objective,
        "baseline_gate": baseline_eval.gate["gate"],
        "n_candidates": n_candidates,
        "n_rejected": len(rejected),
        "n_survivors": len(survivors),
        "rejected_reasons": [e.rejection_reason for e in rejected],
        "improved": improved,
        "recommendation": (
            {"version": best.profile.version, "objective": best.objective, "weights": best.profile.default.to_dict()}
            if improved else
            {
                "version": base.version,
                "objective": baseline_eval.objective,
                "note": "no candidate improved on the base profile within this search - keeping current defaults",
            }
        ),
        "best_candidate_profile": best.profile if improved else None,
    }
