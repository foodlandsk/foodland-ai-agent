"""
app/evaluation/baseline.py  -  V2.10 aggregation, baseline snapshots, diff,
quality gates.

Policy (Section 38/40/41): the FIRST run establishes the baseline as-is,
including any pre-existing issues it discovers (Section 115 - the point
is to find where Mei is wrong, not to start from a clean slate). Every
run after that blocks ONLY on a genuine regression against that baseline
for a case marked `critical` (Section 37), plus a small set of absolute
invariants (context contamination, duplicate results) that are never
acceptable regardless of baseline. A pre-existing critical failure that
was already red in the baseline stays a loud, reported WARN - it does
not silently block every future commit until someone fixes the
underlying V2.4-era cascade issue (out of this sprint's scope, Section 4).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from app.evaluation.metrics import duplicate_rate
from app.evaluation.schema import CaseResult, ConversationCaseResult

GATE_PASS = "PASS"
GATE_WARN = "WARN"
GATE_FAIL = "FAIL"


def _percentile(sorted_values: list[float], p: float) -> float | None:
    if not sorted_values:
        return None
    index = min(len(sorted_values) - 1, int(len(sorted_values) * p))
    return sorted_values[index]


def aggregate_results(
    golden_results: list[CaseResult],
    conversation_results: list[ConversationCaseResult],
    taxonomy_stats: dict,
) -> dict:
    total = len(golden_results)
    passed = sum(1 for r in golden_results if r.passed)
    critical_failures = sorted(r.case_id for r in golden_results if r.critical_failure)

    error_buckets: Counter = Counter()
    for r in golden_results:
        error_buckets.update(r.error_buckets)

    eligibility_scores = [r.metrics.eligibility_precision for r in golden_results if r.metrics.eligibility_precision is not None]
    precision_5 = [r.metrics.precision_at_k.get(5) for r in golden_results if r.metrics.precision_at_k.get(5) is not None]
    recall_5 = [r.metrics.recall_at_k.get(5) for r in golden_results if r.metrics.recall_at_k.get(5) is not None]
    hit_1 = [r.metrics.hit_rate_at_k.get(3) for r in golden_results if r.metrics.hit_rate_at_k.get(3) is not None]
    reciprocal_ranks = [r.metrics.reciprocal_rank for r in golden_results if r.metrics.reciprocal_rank is not None]

    duplicate_rates = [duplicate_rate(list(r.returned_product_ids)) for r in golden_results]

    latencies_sorted = sorted(r.latency_ms for r in golden_results)

    conv_total = len(conversation_results)
    conv_passed = sum(1 for r in conversation_results if r.passed)
    contamination_count = sum(1 for r in conversation_results if r.context_contamination)
    conv_critical_failures = sorted(r.case_id for r in conversation_results if r.critical_failure)

    return {
        "golden": {
            "total": total,
            "passed": passed,
            "pass_rate": (passed / total) if total else 1.0,
            "critical_failures": critical_failures,
            "error_buckets": dict(sorted(error_buckets.items())),
            "avg_eligibility_precision": (sum(eligibility_scores) / len(eligibility_scores)) if eligibility_scores else None,
            "avg_precision_at_5": (sum(precision_5) / len(precision_5)) if precision_5 else None,
            "avg_recall_at_5": (sum(recall_5) / len(recall_5)) if recall_5 else None,
            "avg_hit_rate_at_3": (sum(hit_1) / len(hit_1)) if hit_1 else None,
            "mrr": (sum(reciprocal_ranks) / len(reciprocal_ranks)) if reciprocal_ranks else None,
            "max_duplicate_rate": max(duplicate_rates) if duplicate_rates else 0.0,
            "per_case": {
                r.case_id: {"passed": r.passed, "critical_failure": r.critical_failure, "error_buckets": list(r.error_buckets)}
                for r in golden_results
            },
        },
        "conversations": {
            "total": conv_total,
            "passed": conv_passed,
            "pass_rate": (conv_passed / conv_total) if conv_total else 1.0,
            "context_contamination_rate": (contamination_count / conv_total) if conv_total else 0.0,
            "reference_errors_total": sum(r.reference_errors for r in conversation_results),
            "critical_failures": conv_critical_failures,
            "per_case": {
                r.case_id: {"passed": r.passed, "critical_failure": r.critical_failure, "context_contamination": r.context_contamination}
                for r in conversation_results
            },
        },
        "taxonomy": taxonomy_stats,
        "performance": {
            "p50_ms": _percentile(latencies_sorted, 0.50),
            "p95_ms": _percentile(latencies_sorted, 0.95),
            "p99_ms": _percentile(latencies_sorted, 0.99),
        },
    }


def save_baseline(path: Path, summary: dict, *, commit: str, dataset_version: str) -> None:
    payload = {
        "commit": commit,
        "dataset_version": dataset_version,
        "summary": summary,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    # sort_keys=True (Section 102/103) - stable, low-noise git diffs.
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def load_baseline(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def diff_against_baseline(baseline: dict, candidate_summary: dict) -> dict:
    baseline_golden = (baseline.get("summary") or {}).get("golden", {}).get("per_case", {})
    candidate_golden = candidate_summary.get("golden", {}).get("per_case", {})
    golden_regressions = []
    golden_improvements = []
    for case_id, cand in candidate_golden.items():
        base = baseline_golden.get(case_id)
        if base is None:
            continue
        if base["passed"] and not cand["passed"]:
            golden_regressions.append(case_id)
        elif not base["passed"] and cand["passed"]:
            golden_improvements.append(case_id)

    baseline_conv = (baseline.get("summary") or {}).get("conversations", {}).get("per_case", {})
    candidate_conv = candidate_summary.get("conversations", {}).get("per_case", {})
    conv_regressions = []
    conv_improvements = []
    for case_id, cand in candidate_conv.items():
        base = baseline_conv.get(case_id)
        if base is None:
            continue
        if base["passed"] and not cand["passed"]:
            conv_regressions.append(case_id)
        elif not base["passed"] and cand["passed"]:
            conv_improvements.append(case_id)

    metric_deltas = {}
    base_summary = baseline.get("summary") or {}
    for section in ("golden", "conversations"):
        for metric in ("pass_rate", "avg_eligibility_precision", "avg_precision_at_5", "avg_recall_at_5", "mrr", "context_contamination_rate"):
            base_value = (base_summary.get(section) or {}).get(metric)
            cand_value = (candidate_summary.get(section) or {}).get(metric)
            if base_value is not None and cand_value is not None:
                metric_deltas[f"{section}.{metric}"] = {"baseline": base_value, "candidate": cand_value, "delta": cand_value - base_value}

    return {
        "golden_regressions": sorted(golden_regressions),
        "golden_improvements": sorted(golden_improvements),
        "conversation_regressions": sorted(conv_regressions),
        "conversation_improvements": sorted(conv_improvements),
        "metric_deltas": metric_deltas,
    }


def evaluate_quality_gates(candidate_summary: dict, baseline: dict | None, critical_case_ids: frozenset[str]) -> dict:
    """Returns {"gate": PASS|WARN|FAIL, "blocking_reasons": [...], "warnings": [...]}.
    Section 38 - only a small, explicit set of checks are blocking."""
    blocking: list[str] = []
    warnings: list[str] = []

    # Absolute invariants (Section 32/37) - never acceptable regardless of baseline.
    contamination_rate = candidate_summary.get("conversations", {}).get("context_contamination_rate", 0.0)
    if contamination_rate > 0:
        blocking.append(f"context_contamination_rate={contamination_rate} (target: 0)")

    max_dup = candidate_summary.get("golden", {}).get("max_duplicate_rate", 0.0)
    if max_dup > 0:
        blocking.append(f"max_duplicate_rate={max_dup} (ResultSet must never repeat a SKU, Section 23)")

    if baseline is None:
        # First run - establishing baseline. Report critical failures loudly
        # but do not block (Section 39 - establish baseline BEFORE gating).
        critical_now_failing = set(candidate_summary.get("golden", {}).get("critical_failures", [])) & critical_case_ids
        if critical_now_failing:
            warnings.append(f"no baseline yet - critical cases currently failing (recorded as baseline): {sorted(critical_now_failing)}")
    else:
        diff = diff_against_baseline(baseline, candidate_summary)
        critical_golden_regressions = [c for c in diff["golden_regressions"] if c in critical_case_ids]
        critical_conv_regressions = [c for c in diff["conversation_regressions"] if c in critical_case_ids]
        if critical_golden_regressions:
            blocking.append(f"critical golden case(s) regressed: {critical_golden_regressions}")
        if critical_conv_regressions:
            blocking.append(f"critical conversation case(s) regressed: {critical_conv_regressions}")
        if diff["golden_regressions"] and not critical_golden_regressions:
            warnings.append(f"non-critical golden regressions: {diff['golden_regressions']}")
        if diff["conversation_regressions"] and not critical_conv_regressions:
            warnings.append(f"non-critical conversation regressions: {diff['conversation_regressions']}")

    if candidate_summary.get("golden", {}).get("pass_rate", 1.0) < 1.0:
        warnings.append(f"golden pass_rate={candidate_summary['golden']['pass_rate']:.3f} (not blocking - see per-case failures)")

    gate = GATE_FAIL if blocking else (GATE_WARN if warnings else GATE_PASS)
    return {"gate": gate, "blocking_reasons": blocking, "warnings": warnings}
