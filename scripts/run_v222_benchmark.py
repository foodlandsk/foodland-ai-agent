"""
scripts/run_v222_benchmark.py  -  V2.22b runner (frozen scenarios
prepared in V2.22a, NOT invoked with --execute-advisor during V2.22a).

DEFAULT BEHAVIOR IS SAFE: running this script with no flags validates
the frozen V2.22 dataset/scorer/split/manifest and exits - it never
touches the Advisor. The Advisor-execution path only exists behind the
explicit `--execute-advisor` flag, mirroring scripts/run_v221_benchmark.py's
own discipline exactly (same protocol, same guardrails, applied to the
independent V2.22 scenario pool).

V2.22b PROTOCOL (mirrors V2.21b Section 92/93):
    1. start from the frozen V2.22a artifacts (scenarios/manifest)
    2. verify hashes (--validate-only, this script's default mode)
    3. record EXECUTION_SHA (git rev-parse HEAD at run time)
    4. run DEV first (--split DEV --execute-advisor)
    5. make NO intervention based on DEV results
    6. run HOLDOUT (--split HOLDOUT --execute-advisor)
    7. make NO intervention based on HOLDOUT results
    8. store raw + scored results (--output)
    9. preserve the first blind result forever (do not overwrite/delete)
    10. make no fixes in the same sprint that ran the blind evaluation
    11. STOP.

Once DEV has been executed, no fix may occur before HOLDOUT - doing so
compromises HOLDOUT's independence.

SCORER REUSE: V2.22 scenarios use app.intelligence_diagnostics.
v221_scorer's existing invariant registry unchanged (no new evaluator
capability was created during V2.22a design - every V2.22 expected_
invariant is one of the 8 bare / 8 arg-based types that registry
already implements). This is intentional reuse, not a naming mistake.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _get_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, check=False).strip()
    except Exception:  # noqa: BLE001 - defensive: git metadata is best-effort
        return "unknown"


def _validate_only(split_filter: str | None) -> int:
    """Default mode - never imports or calls the Advisor. Validates the
    frozen dataset, scorer registry coverage, split, and manifest, then
    exits."""
    from app.intelligence_diagnostics import v222_factory as factory

    scenarios = factory.load_v222_scenarios()
    raw = factory.load_v222_raw()
    raw_by_id = {r["scenario_id"]: r for r in raw}
    errors = factory.validate_scenarios(scenarios, raw_by_id=raw_by_id)
    hard = factory.hard_errors(errors)
    split_map = {r["scenario_id"]: r["split"] for r in raw}

    print(f"V2.22 dataset: {len(scenarios)} scenarios, {len(hard)} hard errors, "
          f"{len(errors) - len(hard)} warnings")
    for e in errors:
        print(f"  {e}")

    if factory.V222_MANIFEST_PATH.exists():
        manifest = json.loads(factory.V222_MANIFEST_PATH.read_text(encoding="utf-8"))
        mismatches = (
            factory.verify_manifest(manifest["dev"], scenarios, split_map)
            + factory.verify_manifest(manifest["holdout"], scenarios, split_map)
        )
        print(f"manifest mismatches: {len(mismatches)}")
        for m in mismatches:
            print(f"  {m}")
    else:
        mismatches = ["manifest file missing"]
        print("manifest file missing")

    if split_filter:
        subset = [s for s in scenarios if split_map.get(s.scenario_id) == split_filter]
        print(f"{split_filter}: {len(subset)} scenarios "
              f"({sum(1 for s in subset if s.is_scored)} scored, "
              f"{sum(1 for s in subset if s.ground_truth_status == 'GROUND_TRUTH_PENDING')} pending)")

    print("NEW_V222_ADVISOR_EXECUTIONS = 0 (validate-only mode never imports app.evaluation.adapter)")
    return 0 if (not hard and not mismatches) else 1


def _execute_advisor(split_filter: str | None, output_path: Path) -> int:
    """V2.22b ONLY. Imports app.evaluation.adapter.make_session_chat_fn()
    for the first time in this codepath - mirrors run_v221_benchmark.py's
    make_session_chat_fn() usage exactly (multi-turn continuity via a
    caller-supplied, per-scenario session_id, never a shared counter)."""
    from app.evaluation.adapter import make_session_chat_fn  # noqa: PLC0415 - deliberately deferred: must never happen at module load time or under --validate-only
    from app.intelligence_diagnostics import v222_factory as factory
    from app.intelligence_diagnostics.v221_scorer import score_scenario

    execution_sha = _get_commit()
    scenarios = factory.load_v222_scenarios()
    raw = factory.load_v222_raw()
    split_map = {r["scenario_id"]: r["split"] for r in raw}
    if split_filter:
        scenarios = [s for s in scenarios if split_map.get(s.scenario_id) == split_filter]

    chat_fn = make_session_chat_fn()  # EVALUATION context by construction - never defaults to CUSTOMER

    results = []
    for s in scenarios:
        session_id = f"eval-session-{s.scenario_id}"
        last_result: dict = {}
        for turn in s.turns:
            last_result = chat_fn(turn.message, 8, session_id)

        score = score_scenario(s.scenario_id, s.expected_invariants if s.is_scored else (), last_result)
        results.append({
            "scenario_id": s.scenario_id,
            "split": split_map.get(s.scenario_id),
            "execution_sha": execution_sha,
            "scenario_hash": factory.content_hash([s]),
            "state": score.state if s.is_scored else "PENDING",
            "observed_intent": last_result.get("intent"),
            "failed_invariants": [
                {"invariant": r.invariant, "expected": r.expected, "observed": r.observed, "reason": r.reason}
                for r in score.failed
            ] if s.is_scored else [],
            "errored_invariants": [
                {"invariant": r.invariant, "reason": r.reason} for r in score.errored
            ] if s.is_scored else [],
            "answer_excerpt": (last_result.get("answer") or "")[:300],
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({
        "execution_sha": execution_sha,
        "scenario_freeze_hash": factory.content_hash(factory.load_v222_scenarios()),
        "split_filter": split_filter,
        "run_id": f"v222b_{execution_sha[:8]}_{uuid.uuid4().hex[:8]}",
        "results": results,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    scored = [r for r in results if r["state"] in ("PASS", "FAIL", "ERROR")]
    passed = sum(1 for r in scored if r["state"] == "PASS")
    print(f"{split_filter or 'ALL'}: {passed}/{len(scored)} scored PASS "
          f"({sum(1 for r in scored if r['state'] == 'FAIL')} FAIL, "
          f"{sum(1 for r in scored if r['state'] == 'ERROR')} ERROR), "
          f"{len(results) - len(scored)} PENDING. Written to {output_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", choices=["DEV", "HOLDOUT"], default=None, help="restrict to one split (default: both)")
    parser.add_argument(
        "--execute-advisor", action="store_true",
        help="REQUIRED to actually call the Advisor. Without this flag the script only validates the frozen dataset and exits.",
    )
    parser.add_argument("--output", default=str(ROOT / "eval" / "results" / "v2_22_b_first_frozen" / "run.json"))
    args = parser.parse_args()

    if not args.execute_advisor:
        return _validate_only(args.split)
    return _execute_advisor(args.split, Path(args.output))


if __name__ == "__main__":
    raise SystemExit(main())
