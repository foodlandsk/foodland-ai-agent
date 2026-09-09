"""
scripts/run_v221_benchmark.py  -  V2.21b runner (prepared in V2.21a,
NOT invoked with --execute-advisor during V2.21a - Section 62/63/107).

DEFAULT BEHAVIOR IS SAFE: running this script with no flags validates
the frozen V2.21 dataset/scorer/split/manifest and exits - it never
touches the Advisor. The Advisor-execution path only exists behind the
explicit `--execute-advisor` flag, which is Section 92's documented
V2.21b protocol, not something V2.21a runs.

V2.21b PROTOCOL (Section 92/93 - commit this discipline, not just this
script):
    1. start from these frozen V2.21a artifacts (scenarios/manifest)
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
compromises HOLDOUT's independence (Section 93).
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
    exits. This is exactly what V2.21a itself already proved green in
    tests/test_v221_scenario_factory.py; this function re-runs the same
    checks as a standalone CLI convenience, nothing more."""
    from app.intelligence_diagnostics import v221_factory as factory

    scenarios = factory.load_v221_scenarios()
    errors = factory.validate_scenarios(scenarios)
    hard = factory.hard_errors(errors)
    split_map = factory.assign_split(scenarios)

    print(f"V2.21 dataset: {len(scenarios)} scenarios, {len(hard)} hard errors, "
          f"{len(errors) - len(hard)} warnings")
    for e in errors:
        print(f"  {e}")

    if factory.V221_MANIFEST_PATH.exists():
        manifest = json.loads(factory.V221_MANIFEST_PATH.read_text(encoding="utf-8"))
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

    print("NEW_V221_ADVISOR_EXECUTIONS = 0 (validate-only mode never imports app.evaluation.adapter)")
    return 0 if (not hard and not mismatches) else 1


def _execute_advisor(split_filter: str | None, output_path: Path) -> int:
    """V2.21b ONLY. Imports app.evaluation.adapter.make_chat_fn() for
    the first time in this codepath - this function must never be
    called by anything other than an explicit --execute-advisor
    invocation of this script."""
    from app.evaluation.adapter import make_chat_fn  # noqa: PLC0415 - deliberately deferred: this import must never happen at module load time or under --validate-only (Section 62/90)
    from app.intelligence_diagnostics import v221_factory as factory
    from app.intelligence_diagnostics.v221_scorer import score_scenario

    execution_sha = _get_commit()
    scenarios = factory.load_v221_scenarios()
    split_map = factory.assign_split(scenarios)
    if split_filter:
        scenarios = [s for s in scenarios if split_map.get(s.scenario_id) == split_filter]

    chat_fn = make_chat_fn()  # EVALUATION context by construction (Section 64) - app.evaluation.adapter.make_chat_fn() never defaults to CUSTOMER

    results = []
    for s in scenarios:
        # Section 65 - unique identity per scenario; make_chat_fn()'s
        # own module-level _call_counter already guarantees a fresh
        # eval-isolated-N session/client_key per call, and each
        # scenario's turns are executed sequentially through the SAME
        # closure call for multi-turn continuity within one scenario
        # only (never shared across scenarios - a fresh scenario always
        # starts a fresh call).
        last_result: dict = {}
        for turn in s.turns:
            last_result = chat_fn(turn.message, 8)

        score = score_scenario(s.scenario_id, s.expected_invariants if s.is_scored else (), last_result)
        results.append({
            "scenario_id": s.scenario_id,
            "split": split_map.get(s.scenario_id),
            "execution_sha": execution_sha,
            "scenario_hash": factory.content_hash([s]),
            "state": score.state if s.is_scored else "PENDING",
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
        "scenario_freeze_hash": factory.content_hash(factory.load_v221_scenarios()),
        "split_filter": split_filter,
        "run_id": f"v221b_{execution_sha[:8]}_{uuid.uuid4().hex[:8]}",
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
        help="REQUIRED to actually call the Advisor. Without this flag the script only validates the frozen dataset and exits (Section 62 - safe by default).",
    )
    parser.add_argument("--output", default=str(ROOT / "eval" / "results" / "v2_21_b" / "run.json"))
    args = parser.parse_args()

    if not args.execute_advisor:
        return _validate_only(args.split)
    return _execute_advisor(args.split, Path(args.output))


if __name__ == "__main__":
    raise SystemExit(main())
