"""
app/evaluation/runner.py  -  V2.10 golden case execution

`chat_fn` is injected (never imports app.main at module import time) for
two reasons: (1) app.main is a heavy module (loads the catalog, warms
search indexes) that evaluation-engine unit tests should not have to pay
for just to test scoring logic, and (2) Section 101 requires the
evaluator itself to be provably capable of catching a deliberately wrong
response - trivial with a fake chat_fn, impossible if this module were
hard-wired to the real one.

`app.evaluation.cli` (the production entry point) is what actually wires
`chat_fn` to `app.main.chat()` - see scripts/run_evaluation.py.
"""
from __future__ import annotations

import time
from typing import Callable

from app.evaluation.metrics import (
    eligibility_precision,
    hit_rate_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from app.evaluation.schema import (
    CaseMetrics,
    CaseResult,
    ELIGIBILITY_ERROR,
    GoldenCase,
    GROUNDING_ERROR,
    INTENT_ERROR,
    PRESENTATION_ERROR,
    RANKING_ERROR,
    RETRIEVAL_MISS,
)

ChatFn = Callable[[str, int], dict]

_RECALL_KS = (3, 5, 10)


def concept_id_map(taxonomy_index: dict) -> dict[str, str | None]:
    return {pid: (getattr(entry, "concept_id", "") or None) for pid, entry in taxonomy_index.items()}


def compute_relevant_universe(expected_concept_ids: frozenset[str], taxonomy_index: dict) -> set[str]:
    """The TRUE relevant set for recall (Section 13) - every catalog
    product whose real taxonomy concept_id matches, not just what the
    query happened to return. Computed fresh against the current catalog
    every run (Section 5 - no hardcoded, unstable SKU lists)."""
    if not expected_concept_ids:
        return set()
    return {
        pid for pid, entry in taxonomy_index.items()
        if getattr(entry, "concept_id", None) in expected_concept_ids
    }


def run_golden_case(case: GoldenCase, chat_fn: ChatFn, taxonomy_index: dict) -> CaseResult:
    start = time.perf_counter()
    response = chat_fn(case.query, case.limit) or {}
    latency_ms = (time.perf_counter() - start) * 1000

    products = response.get("products") or []
    returned_ids = [p.get("id") for p in products if p.get("id")]
    titles_by_id = {p.get("id"): str(p.get("title") or "") for p in products}

    concept_map = concept_id_map(taxonomy_index)
    expected = frozenset(case.expected_concept_ids)
    forbidden = frozenset(case.must_not_concept_ids)

    metrics = CaseMetrics()
    reasons: list[str] = []
    error_buckets: list[str] = []
    passed = True
    critical_failure = False

    if forbidden:
        elig = eligibility_precision(returned_ids, forbidden, concept_map)
        metrics.eligibility_precision = elig
        if elig < 1.0:
            passed = False
            error_buckets.append(ELIGIBILITY_ERROR)
            bad = [pid for pid in returned_ids if concept_map.get(pid) in forbidden]
            reasons.append(
                f"ineligible products returned: {[(pid, titles_by_id.get(pid)) for pid in bad]}"
            )
            if case.critical:
                critical_failure = True

    if expected:
        relevant_universe = compute_relevant_universe(expected, taxonomy_index)
        relevant_in_results = {pid for pid in returned_ids if concept_map.get(pid) in expected}
        for k in _RECALL_KS:
            if k <= max(case.limit, k):
                metrics.precision_at_k[k] = precision_at_k(returned_ids, relevant_in_results, k)
                metrics.recall_at_k[k] = recall_at_k(returned_ids, relevant_universe, k)
                metrics.hit_rate_at_k[k] = hit_rate_at_k(returned_ids, relevant_universe, k)
        metrics.reciprocal_rank = reciprocal_rank(returned_ids, relevant_universe)

        if relevant_universe and not relevant_in_results:
            passed = False
            error_buckets.append(RETRIEVAL_MISS)
            reasons.append(f"no product matching expected concepts {sorted(expected)} in top {case.limit}")
            if case.critical:
                critical_failure = True

        if case.min_relevant_count and len(relevant_in_results) < case.min_relevant_count:
            passed = False
            error_buckets.append(RETRIEVAL_MISS)
            reasons.append(f"expected >= {case.min_relevant_count} relevant products, got {len(relevant_in_results)}")

    for substring in case.must_include_title_substrings:
        if not any(substring.lower() in title.lower() for title in titles_by_id.values()):
            passed = False
            error_buckets.append(RETRIEVAL_MISS)
            reasons.append(f"missing expected title substring: {substring!r}")

    for substring in case.must_not_include_title_substrings:
        offending = [pid for pid, title in titles_by_id.items() if substring.lower() in title.lower()]
        if offending:
            passed = False
            error_buckets.append(ELIGIBILITY_ERROR)
            reasons.append(f"forbidden title substring {substring!r} present in: {offending}")
            if case.critical:
                critical_failure = True

    if case.must_not_be_first_title_substrings and titles_by_id:
        first_title = titles_by_id.get(returned_ids[0], "") if returned_ids else ""
        for substring in case.must_not_be_first_title_substrings:
            if substring.lower() in first_title.lower():
                passed = False
                error_buckets.append(RANKING_ERROR)
                reasons.append(f"forbidden substring {substring!r} must not rank first, got {first_title!r}")

    if case.max_products is not None and len(returned_ids) > case.max_products:
        passed = False
        error_buckets.append(PRESENTATION_ERROR)
        reasons.append(f"expected at most {case.max_products} products, got {len(returned_ids)}")
        if case.critical:
            critical_failure = True

    if case.expected_answer_include:
        answer_text = str(response.get("answer") or "").lower()
        for substring in case.expected_answer_include:
            if substring.lower() not in answer_text:
                passed = False
                error_buckets.append(GROUNDING_ERROR)
                reasons.append(f"answer missing expected content: {substring!r}")

    if case.expected_workflow is not None and response.get("workflow_id") != case.expected_workflow:
        passed = False
        error_buckets.append(INTENT_ERROR)
        reasons.append(f"expected workflow {case.expected_workflow!r}, got {response.get('workflow_id')!r}")

    if case.expected_intent is not None and response.get("intent") != case.expected_intent:
        passed = False
        error_buckets.append(INTENT_ERROR)
        reasons.append(f"expected intent {case.expected_intent!r}, got {response.get('intent')!r}")

    return CaseResult(
        case_id=case.id,
        passed=passed,
        critical_failure=critical_failure,
        error_buckets=tuple(dict.fromkeys(error_buckets)),
        metrics=metrics,
        returned_product_ids=tuple(returned_ids),
        workflow_id=response.get("workflow_id"),
        intent=response.get("intent"),
        latency_ms=latency_ms,
        reasons=tuple(reasons),
    )


def run_golden_suite(cases: list[GoldenCase], chat_fn: ChatFn, taxonomy_index: dict) -> list[CaseResult]:
    return [run_golden_case(case, chat_fn, taxonomy_index) for case in cases]
