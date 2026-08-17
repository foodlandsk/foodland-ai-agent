"""
scripts/run_evaluation.py  -  V2.10 Foodland quality suite CLI

Usage:
    python scripts/run_evaluation.py --fast              # critical cases only, for CI
    python scripts/run_evaluation.py --full               # everything
    python scripts/run_evaluation.py --full --diff        # + compare against stored baseline
    python scripts/run_evaluation.py --full --save-baseline COMMIT   # write eval/baselines/v2.9.json
    python scripts/run_evaluation.py --case rice_jasmine_001          # drilldown one case

Deterministic (Section 45) - only imports app.main (which loads the
checked-in data/products.json fixture), never the network/Railway/OpenAI.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _get_commit() -> str:
    import subprocess
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fast", action="store_true", help="critical cases only")
    parser.add_argument("--full", action="store_true", help="all cases (default if neither flag given)")
    parser.add_argument("--diff", action="store_true", help="compare against eval/baselines/v2.9.json")
    parser.add_argument("--save-baseline", metavar="COMMIT", help="write results as the new baseline")
    parser.add_argument("--case", metavar="CASE_ID", help="drilldown one golden case by id")
    parser.add_argument("--json-out", default=None, help="path for machine-readable report (default eval/reports/latest.json)")
    parser.add_argument("--md-out", default=None, help="path for human-readable report (default eval/reports/latest.md)")
    args = parser.parse_args()

    from app.evaluation.adapter import get_taxonomy_index, make_chat_fn, make_session_chat_fn
    from app.evaluation.baseline import (
        GATE_FAIL,
        aggregate_results,
        diff_against_baseline,
        evaluate_quality_gates,
        load_baseline,
        save_baseline,
    )
    from app.evaluation.conversation import run_conversation_suite
    from app.evaluation.loader import (
        BASELINES_DIR,
        REPORTS_DIR,
        load_all_conversation_cases,
        load_all_golden_cases,
    )
    from app.evaluation.runner import run_golden_case, run_golden_suite
    from app.evaluation.taxonomy_quality import taxonomy_coverage, taxonomy_precision_against_golden

    taxonomy_index = get_taxonomy_index()
    all_golden_cases = load_all_golden_cases()

    if args.case:
        case = next((c for c in all_golden_cases if c.id == args.case), None)
        if case is None:
            print(f"No such case: {args.case}")
            return 1
        chat_fn = make_chat_fn()
        result = run_golden_case(case, lambda q, limit: chat_fn(q, limit), taxonomy_index)
        print(json.dumps({
            "case_id": result.case_id,
            "query": case.query,
            "expected_concept_ids": case.expected_concept_ids,
            "must_not_concept_ids": case.must_not_concept_ids,
            "passed": result.passed,
            "critical_failure": result.critical_failure,
            "error_buckets": result.error_buckets,
            "returned_product_ids": result.returned_product_ids,
            "workflow_id": result.workflow_id,
            "intent": result.intent,
            "latency_ms": round(result.latency_ms, 2),
            "reasons": result.reasons,
        }, ensure_ascii=False, indent=2))
        return 0 if result.passed else 1

    fast_mode = args.fast and not args.full
    golden_cases = [c for c in all_golden_cases if c.critical] if fast_mode else all_golden_cases
    conversation_cases = load_all_conversation_cases()
    if fast_mode:
        conversation_cases = [c for c in conversation_cases if c.critical]

    print(f"Running {len(golden_cases)} golden case(s), {len(conversation_cases)} conversation case(s)"
          f" ({'fast' if fast_mode else 'full'} mode)...")

    chat_fn = make_chat_fn()
    golden_results = run_golden_suite(golden_cases, lambda q, limit: chat_fn(q, limit), taxonomy_index)

    session_chat_fn = make_session_chat_fn()
    conversation_results = run_conversation_suite(conversation_cases, session_chat_fn)

    tax_stats = taxonomy_coverage(taxonomy_index)
    tax_stats.update(taxonomy_precision_against_golden(all_golden_cases, taxonomy_index))

    summary = aggregate_results(golden_results, conversation_results, tax_stats)
    critical_case_ids = frozenset(
        c.id for c in all_golden_cases if c.critical
    ) | frozenset(
        c.id for c in load_all_conversation_cases() if c.critical
    )

    baseline_path = BASELINES_DIR / "v2.9.json"
    baseline = None
    diff = None
    if args.diff or (not args.save_baseline and baseline_path.exists()):
        if baseline_path.exists():
            baseline = load_baseline(baseline_path)
            diff = diff_against_baseline(baseline, summary)

    gates = evaluate_quality_gates(summary, baseline, critical_case_ids)

    report = {
        "commit": _get_commit(),
        "mode": "fast" if fast_mode else "full",
        "summary": summary,
        "gates": gates,
        "diff": diff,
    }

    json_out = Path(args.json_out) if args.json_out else REPORTS_DIR / "latest.json"
    md_out = Path(args.md_out) if args.md_out else REPORTS_DIR / "latest.md"
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    md_out.write_text(_render_markdown(report), encoding="utf-8")

    print(_render_markdown(report))

    if args.save_baseline:
        save_baseline(baseline_path, summary, commit=args.save_baseline, dataset_version="1.0")
        print(f"\nBaseline saved to {baseline_path}")

    return 1 if gates["gate"] == GATE_FAIL else 0


def _render_markdown(report: dict) -> str:
    summary = report["summary"]
    gates = report["gates"]
    lines = [
        f"# Foodland Quality Suite Report ({report['mode']} mode)",
        "",
        f"Commit: `{report['commit']}`",
        f"Gate: **{gates['gate']}**",
        "",
        "## Domain scorecard",
        "",
        f"| Golden cases | {summary['golden']['passed']}/{summary['golden']['total']} ({summary['golden']['pass_rate']:.1%}) |",
        f"|---|---|",
        f"| Conversation cases | {summary['conversations']['passed']}/{summary['conversations']['total']} ({summary['conversations']['pass_rate']:.1%}) |",
        f"| Context contamination rate | {summary['conversations']['context_contamination_rate']:.3f} |",
        f"| Avg eligibility precision | {summary['golden']['avg_eligibility_precision']} |",
        f"| Avg precision@5 | {summary['golden']['avg_precision_at_5']} |",
        f"| Avg recall@5 | {summary['golden']['avg_recall_at_5']} |",
        f"| MRR | {summary['golden']['mrr']} |",
        f"| Taxonomy coverage | {summary['taxonomy']['coverage_ratio']:.3f} |",
        f"| Latency p50/p95/p99 (ms) | {summary['performance']['p50_ms']} / {summary['performance']['p95_ms']} / {summary['performance']['p99_ms']} |",
        "",
    ]
    if gates["blocking_reasons"]:
        lines.append("## Blocking failures")
        lines.extend(f"- {reason}" for reason in gates["blocking_reasons"])
        lines.append("")
    if gates["warnings"]:
        lines.append("## Warnings (non-blocking)")
        lines.extend(f"- {warning}" for warning in gates["warnings"])
        lines.append("")
    if summary["golden"]["critical_failures"]:
        lines.append("## Critical golden failures")
        lines.extend(f"- {case_id}" for case_id in summary["golden"]["critical_failures"])
        lines.append("")
    if summary["golden"]["error_buckets"]:
        lines.append("## Error buckets")
        for bucket, count in summary["golden"]["error_buckets"].items():
            lines.append(f"- {bucket}: {count}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
