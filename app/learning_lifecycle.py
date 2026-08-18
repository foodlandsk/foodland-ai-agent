"""
app/learning_lifecycle.py  -  V2.12: promotion lifecycle, audit trail,
last-known-good rollback.

State machine (Section 54), no state skipping:

    GENERATED -> OFFLINE_PASSED -> SHADOW -> READY_FOR_APPROVAL -> ACTIVE -> MONITORED
         \\-> REJECTED (terminal, any point before ACTIVE)
                                                              ACTIVE/MONITORED -> ROLLED_BACK

`app.learning_candidates.generate_candidate()` already performs the
GENERATED->OFFLINE_PASSED->(REJECTED|SHADOW_ELIGIBLE) step (it runs the
real V2.10 harness) - this module picks up from a SHADOW_ELIGIBLE
LearningCandidate and owns SHADOW onward.

Central safety property (Section 55/56/132): `approve_and_activate()`
ALWAYS requires a non-empty, real `approved_by` identifier - there is no
code path in this module that can reach ACTIVE without one, regardless
of `AUTO_PROMOTION_ENABLED`. That flag exists for a documented FUTURE
extension point (Section 56) and defaults OFF; nothing in this sprint
calls `approve_and_activate()` without explicit human input.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from app.learning_candidates import DECISION_SHADOW_ELIGIBLE, LearningCandidate
from app.ranking_config import (
    RankingProfile,
    RankingProfileError,
    get_active_ranking_profile,
    get_active_ranking_profile_version,
    save_ranking_profile,
    set_active_ranking_profile_version,
)
from app.ranking_shadow import DEFAULT_SHADOW_QUERIES, ShadowComparisonReport, shadow_compare

HISTORY_DIR = Path(os.getenv("LEARNING_HISTORY_DIR", "config/learning_history"))
LEDGER_PATH = HISTORY_DIR / "ledger.jsonl"
LAST_KNOWN_GOOD_PATH = HISTORY_DIR / "last_known_good.json"

# Section 55/56 - human approval is required by default. This flag is a
# documented future extension point (Section 56), not something this
# sprint's code path uses to bypass approval - see module docstring.
AUTO_PROMOTION_ENABLED = os.getenv("LEARNING_AUTO_PROMOTION_ENABLED", "false").strip().lower() in {"1", "true", "yes"}

STATE_GENERATED = "GENERATED"
STATE_OFFLINE_PASSED = "OFFLINE_PASSED"
STATE_SHADOW = "SHADOW"
STATE_READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
STATE_ACTIVE = "ACTIVE"
STATE_MONITORED = "MONITORED"
STATE_REJECTED = "REJECTED"
STATE_ROLLED_BACK = "ROLLED_BACK"

_DISALLOWED_APPROVER_IDENTIFIERS = {"auto", "system", "automated", "bot", "cron", ""}


class LifecycleError(ValueError):
    pass


def _append_ledger(entry: dict) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def record_transition(
    *,
    learning_cycle_id: str,
    candidate_id: str,
    profile_version: str | None,
    state: str,
    note: str = "",
    evidence: dict | None = None,
) -> None:
    """Section 63/64/105 - every transition is one immutable, append-only
    ledger line. No entry is ever edited or deleted (Section 63: 'no
    silent mutations')."""
    _append_ledger({
        "ts": time.time(),
        "learning_cycle_id": learning_cycle_id,
        "candidate_id": candidate_id,
        "profile_version": profile_version,
        "state": state,
        "note": note,
        "evidence": evidence or {},
    })


def get_history(candidate_id: str | None = None, limit: int = 200) -> list[dict]:
    if not LEDGER_PATH.exists():
        return []
    entries = []
    with LEDGER_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if candidate_id is None or entry.get("candidate_id") == candidate_id:
                entries.append(entry)
    return entries[-limit:]


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def get_last_known_good() -> dict | None:
    if not LAST_KNOWN_GOOD_PATH.exists():
        return None
    try:
        return json.loads(LAST_KNOWN_GOOD_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _record_last_known_good(version: str, *, evaluation_summary: dict | None = None) -> None:
    """Section 62 - captured BEFORE any activation, so rollback always has
    a deterministic, known-safe target: the config that was active
    immediately before the new one."""
    _atomic_write_json(LAST_KNOWN_GOOD_PATH, {
        "version": version,
        "recorded_at": time.time(),
        "evaluation_summary": evaluation_summary or {},
    })


@dataclass(frozen=True)
class ShadowResult:
    candidate: LearningCandidate
    report: ShadowComparisonReport


def run_shadow(
    candidate: LearningCandidate,
    *,
    learning_cycle_id: str,
    queries: list[str] | None = None,
) -> ShadowResult:
    """Section 50-53 - reuses app.ranking_shadow.shadow_compare() exactly
    (never a second shadow implementation). Never activates anything -
    `shadow_compare()` itself never touches config/ranking_profiles/
    active.json (verified by V2.11's own tests)."""
    if candidate.decision != DECISION_SHADOW_ELIGIBLE or candidate.profile is None:
        raise LifecycleError(f"candidate {candidate.id} is not SHADOW_ELIGIBLE (decision={candidate.decision})")

    record_transition(
        learning_cycle_id=learning_cycle_id, candidate_id=candidate.id,
        profile_version=candidate.profile.version, state=STATE_OFFLINE_PASSED,
        note="offline V2.10 evaluation passed with meaningful improvement",
        evidence={"baseline_objective": candidate.baseline_objective, "candidate_objective": candidate.candidate_objective},
    )

    baseline_profile = get_active_ranking_profile()
    report = shadow_compare(list(queries or DEFAULT_SHADOW_QUERIES), baseline_profile, candidate.profile)

    record_transition(
        learning_cycle_id=learning_cycle_id, candidate_id=candidate.id,
        profile_version=candidate.profile.version, state=STATE_SHADOW,
        note=f"{report.queries_changed}/{len(report.results)} queries changed order in shadow comparison",
        evidence={"windows_with_set_changes": report.windows_with_set_changes},
    )

    record_transition(
        learning_cycle_id=learning_cycle_id, candidate_id=candidate.id,
        profile_version=candidate.profile.version, state=STATE_READY_FOR_APPROVAL,
        note="shadow comparison complete - awaiting explicit human approval before activation",
    )
    return ShadowResult(candidate=candidate, report=report)


def approve_and_activate(
    candidate: LearningCandidate,
    *,
    approved_by: str,
    learning_cycle_id: str,
) -> RankingProfile:
    """Section 54/55/105 - the ONLY function in this codebase that can
    move a learning candidate's ranking profile into
    config/ranking_profiles/active.json. Requires a real, non-empty,
    non-automated approver identity every time - this is not softened by
    AUTO_PROMOTION_ENABLED (Section 56: that flag is a documented future
    extension point, not a bypass implemented in this sprint)."""
    if candidate.decision != DECISION_SHADOW_ELIGIBLE or candidate.profile is None:
        raise LifecycleError(f"candidate {candidate.id} is not eligible for activation (decision={candidate.decision})")

    normalized_approver = (approved_by or "").strip().lower()
    if not approved_by or normalized_approver in _DISALLOWED_APPROVER_IDENTIFIERS:
        raise LifecycleError(
            "approve_and_activate() requires a real, named human approver - "
            f"got approved_by={approved_by!r}. This is enforced unconditionally, not gated by "
            "AUTO_PROMOTION_ENABLED (Section 55)."
        )

    previous_version = get_active_ranking_profile_version()
    if previous_version:
        _record_last_known_good(previous_version)

    try:
        save_ranking_profile(candidate.profile)
    except RankingProfileError:
        # Version already saved (e.g. the same opportunity/candidate was
        # generated in an earlier cycle and already persisted) - versions
        # are immutable by design (Section 99), so an existing file with
        # this exact version is not an error here, just idempotent reuse.
        pass
    set_active_ranking_profile_version(candidate.profile.version)

    record_transition(
        learning_cycle_id=learning_cycle_id, candidate_id=candidate.id,
        profile_version=candidate.profile.version, state=STATE_ACTIVE,
        note=f"activated by {approved_by!r}, previous version was {previous_version!r}",
        evidence={"approved_by": approved_by, "previous_version": previous_version},
    )
    return candidate.profile


def mark_monitored(candidate_id: str, profile_version: str, *, learning_cycle_id: str, summary: dict) -> None:
    """Section 59 - post-deploy monitoring window observation, recorded
    but not itself a state transition trigger (that's `check_rollback_
    conditions` below)."""
    record_transition(
        learning_cycle_id=learning_cycle_id, candidate_id=candidate_id,
        profile_version=profile_version, state=STATE_MONITORED,
        note="post-deploy monitoring summary recorded", evidence=summary,
    )


def check_rollback_conditions(monitoring_gate: dict) -> tuple[bool, str | None]:
    """Section 60/61 - automatic rollback triggers ONLY on the same
    absolute-invariant/critical-regression gate V2.10 already uses
    (`app.evaluation.baseline.evaluate_quality_gates()` - reused, not
    reimplemented), which by construction never blocks on noisy business
    metrics like CTR (Section 61 - 'do NOT automatically rollback solely
    from small CTR fluctuations'; that gate has no CTR term at all)."""
    if monitoring_gate.get("gate") == "FAIL":
        return True, "; ".join(monitoring_gate.get("blocking_reasons", [])) or "quality gate FAIL"
    return False, None


def rollback_to_last_known_good(*, reason: str, learning_cycle_id: str) -> str | None:
    """Section 60/62 - deterministic: always the config active immediately
    before the most recent activation, never a heuristic guess."""
    last_known_good = get_last_known_good()
    if last_known_good is None:
        record_transition(
            learning_cycle_id=learning_cycle_id, candidate_id="rollback", profile_version=None,
            state=STATE_ROLLED_BACK, note=f"rollback requested ({reason}) but no last_known_good recorded - no-op",
        )
        return None

    version = last_known_good["version"]
    try:
        set_active_ranking_profile_version(version)
    except RankingProfileError as exc:
        record_transition(
            learning_cycle_id=learning_cycle_id, candidate_id="rollback", profile_version=version,
            state=STATE_ROLLED_BACK, note=f"rollback FAILED: {exc}",
        )
        raise

    record_transition(
        learning_cycle_id=learning_cycle_id, candidate_id="rollback", profile_version=version,
        state=STATE_ROLLED_BACK, note=f"rolled back to last_known_good: {reason}",
    )
    return version
