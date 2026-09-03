"""
scripts/run_intelligence_benchmark.py  -  V2.18a-c Intelligence
Benchmark runner.

Loads the full V2.18 scenario pool (existing V2.10 golden/conversation
cases + curated scenarios), generates safe mutations for every SCORED
scenario, executes everything through EVALUATION context (never
CUSTOMER - app.evaluation.adapter.make_chat_fn()/make_session_chat_fn()
default), computes capability/overall/stable-core/mutation scores,
clusters failures deterministically, independently reproduces each
failure (fresh EVALUATION-context re-run), records an immutable
generation snapshot, and writes a machine-readable JSON report.

Does NOT fix anything it finds (Section 47: V2.18d must not start here).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import os

os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")


def _get_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-mutations", action="store_true", help="skip mutation generation (faster)")
    parser.add_argument("--output", default=str(ROOT / "eval" / "reports" / "intelligence_report.json"))
    args = parser.parse_args()

    from app.evaluation.adapter import make_chat_fn, make_session_chat_fn, get_taxonomy_index
    from app.intelligence_diagnostics import generation_history as gh
    from app.intelligence_diagnostics import mutation_engine as me
    from app.intelligence_diagnostics import failure_triage as ft
    from app.intelligence_diagnostics import scenario_registry as sr
    from app.intelligence_diagnostics.benchmark_runner import (
        STATUS_FAIL, STATUS_PASS, STATUS_PENDING, STATUS_UNKNOWN,
        run_benchmark, _golden_case_lookup, _conversation_case_lookup,
    )
    from app.intelligence_diagnostics.synthetic_reproduction import reproduce_synthetic_failure

    git_sha = _get_commit()
    print(f"=== V2.18 Intelligence Benchmark (git_sha={git_sha[:8]}) ===")

    canonical_scenarios = sr.load_all_scenarios()
    print(f"canonical scenarios: {len(canonical_scenarios)}")

    mutations: list = []
    if not args.no_mutations:
        for s in canonical_scenarios:
            if s.ground_truth_status == "SCORED" and s.lifecycle_status == "OPEN" and not s.is_multi_turn:
                mutations.extend(me.generate_safe_mutations(s))
    print(f"safe mutations generated: {len(mutations)}")

    all_scenarios = canonical_scenarios + mutations

    chat_fn = make_chat_fn()
    session_chat_fn = make_session_chat_fn()
    taxonomy_index = get_taxonomy_index()

    run = run_benchmark(all_scenarios, chat_fn=chat_fn, session_chat_fn=session_chat_fn, taxonomy_index=taxonomy_index)

    canonical_ids = {s.scenario_id for s in canonical_scenarios}
    canonical_results = [r for r in run.results if r.scenario_id in canonical_ids]
    mutation_results = [r for r in run.results if r.scenario_id not in canonical_ids]

    def _score(results):
        scored = [r for r in results if r.status in (STATUS_PASS, STATUS_FAIL)]
        if not scored:
            return None
        return sum(1 for r in scored if r.status == STATUS_PASS) / len(scored)

    overall_score = _score(run.results)
    stable_core_score = _score(canonical_results)
    mutation_score = _score(mutation_results)

    pass_count = len(run.by_status(STATUS_PASS))
    fail_count = len(run.by_status(STATUS_FAIL))
    unknown_count = len(run.by_status(STATUS_UNKNOWN))
    pending_count = len(run.by_status(STATUS_PENDING))

    capability_scores = run.capability_scores()

    fails = run.by_status(STATUS_FAIL)
    clusters = ft.cluster_failures(run.results)

    print(f"overall={overall_score} stable_core={stable_core_score} mutation={mutation_score}")
    print(f"PASS={pass_count} FAIL={fail_count} UNKNOWN={unknown_count} PENDING={pending_count}")
    print(f"failure clusters: {len(clusters)}")

    scenario_by_id = {s.scenario_id: s for s in all_scenarios}
    golden_lookup = _golden_case_lookup()
    conversation_lookup = _conversation_case_lookup()

    reproductions = []
    for fail_result in fails:
        scenario = scenario_by_id.get(fail_result.scenario_id)
        if scenario is None:
            continue
        repro = reproduce_synthetic_failure(
            scenario, chat_fn=chat_fn, session_chat_fn=session_chat_fn, taxonomy_index=taxonomy_index,
            golden_lookup=golden_lookup, conversation_lookup=conversation_lookup, git_sha=git_sha,
        )
        reproductions.append(repro)
    print(f"reproductions attempted: {len(reproductions)}, REPRODUCED_SYNTHETIC_FAILURE: {sum(1 for r in reproductions if r['status'] == 'REPRODUCED_SYNTHETIC_FAILURE')}")

    # existing_failures vs new_failures: compare against the immediately
    # prior generation, if one exists (Section 10 - "is intelligence
    # actually improving," not just today's score).
    prior_generations = gh.read_generations(limit=1)
    prior_fail_ids = set()
    if prior_generations and not prior_generations[-1].get("invalidated"):
        prior_fail_ids = set(prior_generations[-1].get("existing_failures", []) + prior_generations[-1].get("new_failures", []))
    current_fail_ids = {r.scenario_id for r in fails}
    new_failures = sorted(current_fail_ids - prior_fail_ids)
    existing_failures = sorted(current_fail_ids & prior_fail_ids)
    closed_regressions = sorted(prior_fail_ids - current_fail_ids)

    record = gh.build_generation_record(
        git_sha=git_sha,
        scenario_count=len(canonical_scenarios),
        scored_scenario_count=len([s for s in canonical_scenarios if s.ground_truth_status == "SCORED"]),
        pending_ground_truth_count=len([s for s in canonical_scenarios if s.ground_truth_status == "GROUND_TRUTH_PENDING"]),
        mutation_count=len(mutations),
        capability_scores=capability_scores,
        overall_score=overall_score,
        pass_count=pass_count,
        fail_count=fail_count,
        unknown_count=unknown_count,
        new_failures=new_failures,
        existing_failures=existing_failures,
        closed_regressions=closed_regressions,
    )
    gh.record_generation(record)
    print(f"generation recorded: {record['generation_id']}")

    report = {
        "generation_id": record["generation_id"],
        "git_sha": git_sha,
        "benchmark_version": gh.BENCHMARK_VERSION,
        "canonical_scenario_count": len(canonical_scenarios),
        "mutation_count": len(mutations),
        "total_evaluated": len(run.results),
        "overall_score": overall_score,
        "stable_core_score": stable_core_score,
        "mutation_score": mutation_score,
        "capability_scores": capability_scores,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "unknown_count": unknown_count,
        "pending_ground_truth_count": pending_count,
        "new_failures": new_failures,
        "existing_failures": existing_failures,
        "closed_regressions": closed_regressions,
        "failure_clusters": [
            {"capability": c.capability, "likely_layer": c.likely_layer, "size": c.size, "scenario_ids": list(c.scenario_ids)}
            for c in clusters
        ],
        "reproductions": reproductions,
        "root_cause_uncertain_count": sum(1 for r in reproductions if r.get("likely_layer") is None or r.get("likely_layer") == ft.ROOT_CAUSE_UNCERTAIN),
        "automatic_fix_applied": False,
        "automatic_deploy_applied": False,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"report written: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
