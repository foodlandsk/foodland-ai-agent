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
import time
from dataclasses import dataclass

from app.durable_storage import atomic_write_json
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
from app.storage_paths import resolve_dir

HISTORY_DIR = resolve_dir("LEARNING_HISTORY_DIR", "learning_history", legacy_default="config/learning_history")
LEDGER_PATH = HISTORY_DIR / "ledger.jsonl"
LAST_KNOWN_GOOD_PATH = HISTORY_DIR / "last_known_good.json"
# Section [Part C] - candidate ids (e.g. "candidate:HIGH_ZERO_RESULT:mlieko
# bez laktozy") embed free-text query scopes and are not safe filesystem
# names on every OS this runs on (Windows dev boxes included) - stored as
# an append-only JSONL log instead, same pattern as LEDGER_PATH, so a
# real HTTP approval endpoint can look a candidate up by id without ever
# needing a filesystem-safe encoding of that id.
CANDIDATE_STORE_PATH = HISTORY_DIR / "candidates.jsonl"

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


def get_last_known_good() -> dict | None:
    if not LAST_KNOWN_GOOD_PATH.exists():
        return None
    try:
        return json.loads(LAST_KNOWN_GOOD_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _persist_candidate_snapshot(candidate: LearningCandidate, *, learning_cycle_id: str, config_version_at_generation: str | None) -> None:
    """Section [Part C] - durable, ID-keyed candidate persistence. Without
    this, a SHADOW_ELIGIBLE candidate's full RankingProfile (the actual
    proposed weights, not just a version string) only ever existed in the
    in-memory return value of the single run_learning_cycle() call that
    generated it - unrecoverable once that process call returned, and
    certainly not survivable across a Railway worker restart. Appending
    here at the moment a candidate reaches READY_FOR_APPROVAL means a
    real approval endpoint can act on it later, in a different process,
    using only the candidate id."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "id": candidate.id,
        "learning_cycle_id": learning_cycle_id,
        "persisted_at": time.time(),
        "config_version_at_generation": config_version_at_generation,
        "opportunity_id": candidate.opportunity_id,
        "opportunity_type": candidate.opportunity_type,
        "risk_class": candidate.risk_class,
        "decision": candidate.decision,
        "profile": candidate.profile.to_dict() if candidate.profile else None,
        "rejection_reasons": list(candidate.rejection_reasons),
        "baseline_objective": candidate.baseline_objective,
        "candidate_objective": candidate.candidate_objective,
        "explanation": candidate.explanation,
    }
    with CANDIDATE_STORE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def get_persisted_candidate(candidate_id: str) -> dict | None:
    """The MOST RECENT persisted snapshot for this id - if the same
    opportunity produced a candidate with this id in more than one cycle
    (evidence changed between runs), the latest snapshot is always the
    one an approval should act on."""
    if not CANDIDATE_STORE_PATH.exists():
        return None
    found = None
    with CANDIDATE_STORE_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("id") == candidate_id:
                found = entry
    return found


def _record_last_known_good(version: str, *, evaluation_summary: dict | None = None) -> None:
    """Section 62 - captured BEFORE any activation, so rollback always has
    a deterministic, known-safe target: the config that was active
    immediately before the new one."""
    atomic_write_json(LAST_KNOWN_GOOD_PATH, {
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
    _persist_candidate_snapshot(
        candidate, learning_cycle_id=learning_cycle_id,
        config_version_at_generation=baseline_profile.version,
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


def approve_candidate_by_id(
    candidate_id: str,
    *,
    approved_by: str,
    expected_current_config_version: str | None = None,
) -> dict:
    """Section [Part C] - the durable, ID-keyed counterpart to
    approve_and_activate() a real HTTP endpoint calls, without needing an
    in-memory LearningCandidate from the same process that generated it
    (Railway's worker handling this request is not guaranteed to be the
    one that ran the learning cycle).

    Two safety checks approve_and_activate() itself does not need (it
    always operates on a freshly-generated in-memory candidate, so
    staleness/duplication cannot happen there):
      - stale-candidate protection: if the caller supplies
        `expected_current_config_version` (the active version the
        approval UI/CLI last saw) and the real active version has since
        moved, this raises rather than silently promoting on top of a
        change the approver never saw.
      - idempotency: if this candidate's profile is ALREADY the active
        version (e.g. a duplicate/retried approval call), returns
        immediately without a second last_known_good/ledger mutation -
        calling approve_and_activate() again here would corrupt
        last_known_good with a self-referential "previous version"."""
    snapshot = get_persisted_candidate(candidate_id)
    if snapshot is None:
        raise LifecycleError(f"no persisted candidate found for id {candidate_id!r}")

    current_active_version = get_active_ranking_profile_version()
    snapshot_profile = snapshot.get("profile")

    if snapshot_profile and current_active_version == snapshot_profile.get("version"):
        return {
            "status": "already_active",
            "candidate_id": candidate_id,
            "profile_version": current_active_version,
        }

    if expected_current_config_version is not None and expected_current_config_version != current_active_version:
        raise LifecycleError(
            f"stale candidate: caller expected active config {expected_current_config_version!r} "
            f"but it is currently {current_active_version!r} - reload before approving"
        )

    if snapshot.get("decision") != DECISION_SHADOW_ELIGIBLE or not snapshot_profile:
        raise LifecycleError(f"candidate {candidate_id!r} is not SHADOW_ELIGIBLE (decision={snapshot.get('decision')!r})")

    candidate = LearningCandidate(
        id=snapshot["id"],
        opportunity_id=snapshot["opportunity_id"],
        opportunity_type=snapshot["opportunity_type"],
        risk_class=snapshot["risk_class"],
        decision=snapshot["decision"],
        profile=RankingProfile.from_dict(snapshot_profile),
        rejection_reasons=tuple(snapshot.get("rejection_reasons") or ()),
        baseline_objective=snapshot.get("baseline_objective"),
        candidate_objective=snapshot.get("candidate_objective"),
        explanation=snapshot.get("explanation") or {},
    )

    profile = approve_and_activate(
        candidate,
        approved_by=approved_by,
        learning_cycle_id=snapshot.get("learning_cycle_id") or "manual-approval",
    )
    return {
        "status": "activated",
        "candidate_id": candidate_id,
        "profile_version": profile.version,
        "approved_by": approved_by,
    }


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


def rollback_to_last_known_good(
    *,
    reason: str,
    learning_cycle_id: str,
    triggered_by: str = "system",
    expected_current_config_version: str | None = None,
) -> str | None:
    """Section 60/62 - deterministic: always the config active immediately
    before the most recent activation, never a heuristic guess.

    `expected_current_config_version` mirrors approve_candidate_by_id()'s
    stale-candidate protection: an operator's rollback UI/CLI may have
    been looking at an active version that has since changed (someone
    else already promoted or rolled back) - raises rather than rolling
    back on top of a change the caller never saw. `triggered_by` defaults
    to "system" so app.learning_cycle's own future automatic-rollback
    callers (Section 60/61 - check_rollback_conditions) need not change,
    while a real HTTP endpoint always passes a real identity."""
    current_active_version = get_active_ranking_profile_version()
    if expected_current_config_version is not None and expected_current_config_version != current_active_version:
        raise LifecycleError(
            f"stale rollback request: caller expected active config {expected_current_config_version!r} "
            f"but it is currently {current_active_version!r} - reload before rolling back"
        )

    last_known_good = get_last_known_good()
    if last_known_good is None:
        record_transition(
            learning_cycle_id=learning_cycle_id, candidate_id="rollback", profile_version=None,
            state=STATE_ROLLED_BACK, note=f"rollback requested ({reason}) but no last_known_good recorded - no-op",
            evidence={"triggered_by": triggered_by},
        )
        return None

    version = last_known_good["version"]

    if current_active_version == version:
        # Idempotent: already at the rollback target (duplicate/retried
        # request) - still recorded for the audit trail, but not treated
        # as a distinct rollback with its own last_known_good movement.
        record_transition(
            learning_cycle_id=learning_cycle_id, candidate_id="rollback", profile_version=version,
            state=STATE_ROLLED_BACK, note=f"rollback requested ({reason}) but already at last_known_good {version!r} - no-op",
            evidence={"triggered_by": triggered_by, "idempotent": True},
        )
        return version

    try:
        set_active_ranking_profile_version(version)
    except RankingProfileError as exc:
        record_transition(
            learning_cycle_id=learning_cycle_id, candidate_id="rollback", profile_version=version,
            state=STATE_ROLLED_BACK, note=f"rollback FAILED: {exc}",
            evidence={"triggered_by": triggered_by},
        )
        raise

    record_transition(
        learning_cycle_id=learning_cycle_id, candidate_id="rollback", profile_version=version,
        state=STATE_ROLLED_BACK, note=f"rolled back to last_known_good: {reason}",
        evidence={"triggered_by": triggered_by},
    )
    return version
