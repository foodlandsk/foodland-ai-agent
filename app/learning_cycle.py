"""
app/learning_cycle.py  -  V2.12: the ONE orchestrator - collect events ->
aggregate signals -> detect opportunities -> generate candidates ->
report. Both `scripts/run_learning_cycle.py` (CLI) and `app/main.py`'s
admin endpoints/background loop import this module - orchestration logic
lives here exactly once (Section 70/93/94).

Does not import app.main (same circular-import reasoning app.behavioral/
app.fbt/app.learning_events already document) - `known_product_ids` is
passed in by the caller instead.

Section 99 - independent feature flags, each an env var, each defaulting
to something safe:
  - LEARNING_ENGINE_ENABLED (default true) - master switch for reading/
    aggregating/detecting. Safe default ON: this only READS the events
    the system already collects via the pre-existing /events endpoint
    (Section 99 - "event collection" itself is not a new thing V2.12
    introduces, see app.learning_events' module docstring).
  - LEARNING_CANDIDATE_GENERATION_ENABLED (default true) - runs
    app.learning_candidates, which itself never mutates production state.
  - LEARNING_SHADOW_ENABLED (default true) - runs app.ranking_shadow for
    SHADOW_ELIGIBLE candidates, never touches active.json.
  - Promotion (ACTIVE) is a SEPARATE, always-manual step
    (app.learning_lifecycle.approve_and_activate) that this orchestrator
    never calls itself (Section 132 - COLLECT -> LEARN -> PROPOSE ->
    EVALUATE -> SHADOW -> HUMAN APPROVAL -> ACTIVATE, not further).

Disabling this entire module must never affect app.ranking's actual
request-serving behavior (Section 100/99) - it only ever READS events and
WRITES to its own report/history files.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from app.learning_candidates import (
    DECISION_REJECTED,
    DECISION_REVIEW_REQUIRED,
    DECISION_SHADOW_ELIGIBLE,
    LearningCandidate,
    generate_candidates,
)
from app.learning_events import load_learning_events
from app.learning_lifecycle import run_shadow
from app.learning_opportunities import LearningOpportunity, detect_all_opportunities
from app.learning_signals import (
    QueryProductSignal,
    compute_autocomplete_signals,
    compute_query_product_signals,
    detect_reformulations,
    rollup_family_signals,
)
from app.ranking_config import RankingProfile, get_active_ranking_profile, get_active_ranking_profile_version

REPORTS_DIR = Path(os.getenv("LEARNING_REPORTS_DIR", "learning/reports"))

LEARNING_ENGINE_ENABLED = os.getenv("LEARNING_ENGINE_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
LEARNING_CANDIDATE_GENERATION_ENABLED = os.getenv("LEARNING_CANDIDATE_GENERATION_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
LEARNING_SHADOW_ENABLED = os.getenv("LEARNING_SHADOW_ENABLED", "true").strip().lower() not in {"0", "false", "no"}

DEFAULT_LOOKBACK_DAYS = int(os.getenv("LEARNING_LOOKBACK_DAYS", "30"))
# Section 70/73 - conservative initial cadence, gated by env (0=disabled,
# same convention as FEED_REFRESH_MINUTES). Left disabled by default; ops
# enables once real traffic volume justifies a cadence (Section 73/74).
LEARNING_CYCLE_MINUTES = int(os.getenv("LEARNING_CYCLE_MINUTES", "0"))

# Section 45/126 - fast=critical-cases-only for the periodic background
# job (keeps cycle runtime bounded); an operator-triggered manual run via
# scripts/run_learning_cycle.py --full can opt into the full V2.10 suite.
_FAST_EVALUATION_DEFAULT = os.getenv("LEARNING_CYCLE_FAST_EVAL", "true").strip().lower() not in {"0", "false", "no"}


def new_learning_cycle_id() -> str:
    """Section 64 - stable per-cycle id linking evidence -> opportunity ->
    candidate -> evaluation -> shadow -> decision. Not `uuid.uuid4()`
    directly (Workflow scripts elsewhere in this codebase forbid it, and
    a readable, sortable id is more useful in the ledger/report anyway)."""
    return f"learning_cycle_{time.strftime('%Y_%m_%d', time.gmtime())}_{uuid.uuid4().hex[:8]}"


def run_learning_cycle(
    *,
    known_product_ids: frozenset[str],
    days: int | None = None,
    fast_evaluation: bool | None = None,
    run_shadow_stage: bool | None = None,
    events_path: str | None = None,
) -> dict:
    """Section 70/93/94 - the full cycle. Never raises on a healthy repo -
    an empty/insufficient event stream produces a report saying so
    (Section 137), not an exception; a genuine internal error is caught
    and reported as `"status": "error"` rather than propagated, because a
    learning-cycle failure must never be allowed to look like anything
    more than what it is: this module failed, customer search did not
    (Section 100/101)."""
    cycle_id = new_learning_cycle_id()
    started_at = time.time()

    if not LEARNING_ENGINE_ENABLED:
        return _finalize_report(cycle_id, started_at, {
            "status": "disabled",
            "reason": "LEARNING_ENGINE_ENABLED is false",
        })

    try:
        days = DEFAULT_LOOKBACK_DAYS if days is None else days
        fast_evaluation = _FAST_EVALUATION_DEFAULT if fast_evaluation is None else fast_evaluation
        run_shadow_stage = LEARNING_SHADOW_ENABLED if run_shadow_stage is None else run_shadow_stage

        events, event_stats = load_learning_events(days=days, path=events_path, known_product_ids=known_product_ids)

        if not events:
            return _finalize_report(cycle_id, started_at, {
                "status": "insufficient_data",
                "reason": "No valid learning events in the lookback window - see Section 137, do not fabricate a result.",
                "event_stats": event_stats.__dict__,
            })

        product_signals = compute_query_product_signals(events)
        family_signals = rollup_family_signals(product_signals)
        reformulations = detect_reformulations(events)
        autocomplete_signals = compute_autocomplete_signals(events)

        opportunities = detect_all_opportunities(product_signals, reformulations, events)

        base_profile = get_active_ranking_profile()
        candidates: list[LearningCandidate] = []
        if LEARNING_CANDIDATE_GENERATION_ENABLED and opportunities:
            candidates = generate_candidates(opportunities, base_profile, fast=fast_evaluation)

        shadow_summaries = []
        if run_shadow_stage:
            for candidate in candidates:
                if candidate.decision != DECISION_SHADOW_ELIGIBLE:
                    continue
                try:
                    shadow_result = run_shadow(candidate, learning_cycle_id=cycle_id)
                    shadow_summaries.append({
                        "candidate_id": candidate.id,
                        "profile_version": candidate.profile.version if candidate.profile else None,
                        "queries_changed": shadow_result.report.queries_changed,
                        "windows_with_set_changes": shadow_result.report.windows_with_set_changes,
                    })
                except Exception as exc:  # noqa: BLE001 - a single candidate's shadow failure must not kill the cycle
                    shadow_summaries.append({"candidate_id": candidate.id, "error": str(exc)})

        result = {
            "status": "completed",
            "base_profile_version": base_profile.version,
            "event_stats": event_stats.__dict__,
            "signals": {
                "query_product_signal_count": len(product_signals),
                "query_family_signals": [s.__dict__ for s in family_signals],
                "reformulation_count": len(reformulations),
                "reformulation_failures": sum(1 for r in reformulations if r.classification == "FAILURE_REFORMULATION"),
                "autocomplete_signal_count": len(autocomplete_signals),
            },
            "opportunities": [_opportunity_to_dict(o) for o in opportunities],
            "candidates": [_candidate_to_dict(c) for c in candidates],
            "candidate_summary": {
                "generated": len(candidates),
                "rejected": sum(1 for c in candidates if c.decision == DECISION_REJECTED),
                "review_required": sum(1 for c in candidates if c.decision == DECISION_REVIEW_REQUIRED),
                "shadow_eligible": sum(1 for c in candidates if c.decision == DECISION_SHADOW_ELIGIBLE),
            },
            "shadow_summaries": shadow_summaries,
        }
        return _finalize_report(cycle_id, started_at, result)
    except Exception as exc:  # noqa: BLE001 - Section 100/101: never let a learning-cycle bug look like anything but this module failing
        return _finalize_report(cycle_id, started_at, {"status": "error", "error": str(exc)})


def _opportunity_to_dict(o: LearningOpportunity) -> dict:
    return {
        "id": o.id, "type": o.type, "scope": o.scope, "evidence": o.evidence,
        "confidence": o.confidence, "sample_size": o.sample_size,
        "affected_queries": list(o.affected_queries), "affected_products": list(o.affected_products),
        "proposed_action_type": o.proposed_action_type,
    }


def _candidate_to_dict(c: LearningCandidate) -> dict:
    return {
        "id": c.id, "opportunity_id": c.opportunity_id, "opportunity_type": c.opportunity_type,
        "risk_class": c.risk_class, "decision": c.decision,
        "profile_version": c.profile.version if c.profile else None,
        "rejection_reasons": list(c.rejection_reasons),
        "baseline_objective": c.baseline_objective, "candidate_objective": c.candidate_objective,
        "explanation": c.explanation,
    }


def _finalize_report(cycle_id: str, started_at: float, result: dict) -> dict:
    report = {
        "learning_cycle_id": cycle_id,
        "started_at": started_at,
        "duration_seconds": round(time.time() - started_at, 3),
        "active_ranking_config_version": get_active_ranking_profile_version(),
        **result,
    }
    _save_report(report)
    return report


def _save_report(report: dict) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (REPORTS_DIR / "latest.md").write_text(render_markdown(report), encoding="utf-8")


def render_markdown(report: dict) -> str:
    lines = [
        f"# Foodland Learning Cycle Report",
        "",
        f"Cycle: `{report.get('learning_cycle_id')}`",
        f"Status: **{report.get('status')}**",
        f"Active ranking config: `{report.get('active_ranking_config_version')}`",
        "",
    ]
    if report.get("status") in {"disabled", "insufficient_data", "error"}:
        lines.append(f"Reason: {report.get('reason') or report.get('error')}")
        return "\n".join(lines)

    stats = report.get("event_stats", {})
    lines += [
        "## Event volume",
        f"- valid: {stats.get('valid')} / raw: {stats.get('total_raw')}",
        f"- rejected (malformed/unknown-product/missing-session): "
        f"{stats.get('rejected_malformed')}/{stats.get('rejected_unknown_product')}/{stats.get('rejected_missing_session')}",
        f"- duplicates dropped: {stats.get('duplicates_dropped')}",
        "",
        "## Opportunities",
    ]
    for o in report.get("opportunities", []):
        lines.append(f"- **{o['type']}** (scope={o['scope']}, confidence={o['confidence']}, n={o['sample_size']}) -> {o['proposed_action_type']}")
    lines.append("")
    lines.append("## Candidates")
    summary = report.get("candidate_summary", {})
    lines.append(f"generated={summary.get('generated')} rejected={summary.get('rejected')} "
                 f"review_required={summary.get('review_required')} shadow_eligible={summary.get('shadow_eligible')}")
    for c in report.get("candidates", []):
        lines.append(f"- {c['id']}: {c['decision']} (risk={c['risk_class']}, reasons={c['rejection_reasons']})")
    return "\n".join(lines)
