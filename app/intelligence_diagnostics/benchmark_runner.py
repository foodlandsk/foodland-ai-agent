"""
app/intelligence_diagnostics/benchmark_runner.py  -  V2.18b benchmark
execution.

Reuses the proven V2.10 scoring engine unchanged wherever a scenario
wraps a real GoldenCase/ConversationCase (EXISTING_GOLDEN/
REGRESSION_BUG): app.evaluation.runner.run_golden_case() and
app.evaluation.conversation.run_conversation_case() are called exactly
as scripts/run_evaluation.py already calls them. Only CURATED/
REAL_CUSTOMER_QA/SAFE_MUTATION scenarios (which carry no catalog-
specific concept_id list) go through the new, small
app.intelligence_diagnostics.invariant_evaluator.

CUSTOMER STREAM INTEGRITY (Section 24/25, hard blocker): `chat_fn`/
`session_chat_fn` are always built via app.evaluation.adapter's
make_chat_fn()/make_session_chat_fn() with the default EVALUATION
execution context - the exact same non-CUSTOMER path V2.10 has always
used. Nothing in this module accepts or forwards an execution_context
choice from a scenario; CUSTOMER is not a reachable value anywhere in
this call chain.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.evaluation.loader import load_all_conversation_cases, load_all_golden_cases
from app.evaluation.runner import run_golden_case
from app.evaluation.conversation import run_conversation_case
from app.intelligence_diagnostics.invariant_evaluator import evaluate_invariants
from app.intelligence_diagnostics.scenario_schema import (
    GROUND_TRUTH_PENDING,
    LIFECYCLE_OPEN,
    Scenario,
    SOURCE_EXISTING_GOLDEN,
    SOURCE_REGRESSION_BUG,
)

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_PENDING = "PENDING_GROUND_TRUTH"

SCENARIO_RESULT_STATUSES = (STATUS_PASS, STATUS_FAIL, STATUS_UNKNOWN, STATUS_PENDING)


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    capability: str
    source: str
    status: str
    critical: bool
    error_buckets: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    latency_ms: float = 0.0
    response_excerpt: str = ""


def _golden_case_lookup() -> dict[str, object]:
    return {c.id: c for c in load_all_golden_cases()}


def _conversation_case_lookup() -> dict[str, object]:
    return {c.id: c for c in load_all_conversation_cases()}


def _run_wrapped_golden(scenario: Scenario, golden_lookup: dict, chat_fn, taxonomy_index) -> ScenarioResult:
    case = golden_lookup.get(scenario.underlying_case_id)
    if case is None:
        return ScenarioResult(
            scenario_id=scenario.scenario_id, capability=scenario.capability, source=scenario.source,
            status=STATUS_UNKNOWN, critical=scenario.critical,
            reasons=(f"underlying golden case {scenario.underlying_case_id!r} not found",),
        )
    result = run_golden_case(case, chat_fn, taxonomy_index)
    return ScenarioResult(
        scenario_id=scenario.scenario_id,
        capability=scenario.capability,
        source=scenario.source,
        status=STATUS_PASS if result.passed else STATUS_FAIL,
        critical=scenario.critical or result.critical_failure,
        error_buckets=result.error_buckets,
        reasons=result.reasons,
        latency_ms=result.latency_ms,
    )


def _run_wrapped_conversation(scenario: Scenario, conversation_lookup: dict, session_chat_fn) -> ScenarioResult:
    case = conversation_lookup.get(scenario.underlying_case_id)
    if case is None:
        return ScenarioResult(
            scenario_id=scenario.scenario_id, capability=scenario.capability, source=scenario.source,
            status=STATUS_UNKNOWN, critical=scenario.critical,
            reasons=(f"underlying conversation case {scenario.underlying_case_id!r} not found",),
        )
    result = run_conversation_case(case, session_chat_fn)
    reasons = result.reasons
    if result.context_contamination:
        reasons = reasons + ("context contamination detected",)
    return ScenarioResult(
        scenario_id=scenario.scenario_id,
        capability=scenario.capability,
        source=scenario.source,
        status=STATUS_PASS if result.passed else STATUS_FAIL,
        critical=scenario.critical or result.critical_failure,
        reasons=reasons,
    )


def _run_curated(scenario: Scenario, chat_fn, session_chat_fn) -> ScenarioResult:
    import time

    start = time.perf_counter()
    if scenario.is_multi_turn:
        # Reuses the SAME isolated-session mechanism app.evaluation.
        # conversation already relies on - one fresh session per
        # scenario, never the customer's original session_id (Section
        # 6/9/31 of the V2.17.3 doc, same discipline here).
        session_id = f"v218-{scenario.scenario_id}"
        response = {}
        for turn in scenario.turns:
            response = session_chat_fn(turn.message, 8, session_id) or {}
    else:
        response = chat_fn(scenario.turns[0].message, 8) or {}
    latency_ms = (time.perf_counter() - start) * 1000

    passed, failed_invariants, reasons = evaluate_invariants(scenario.expected_invariants, response)
    status = STATUS_PASS if passed else STATUS_FAIL
    error_buckets = tuple(f"INVARIANT_FAILED:{inv}" for inv in failed_invariants)
    return ScenarioResult(
        scenario_id=scenario.scenario_id,
        capability=scenario.capability,
        source=scenario.source,
        status=status,
        critical=scenario.critical,
        error_buckets=error_buckets,
        reasons=tuple(reasons),
        latency_ms=latency_ms,
        response_excerpt=str(response.get("answer") or "")[:200],
    )


def run_scenario(
    scenario: Scenario,
    *,
    chat_fn,
    session_chat_fn,
    taxonomy_index: dict,
    golden_lookup: dict,
    conversation_lookup: dict,
) -> ScenarioResult:
    if scenario.lifecycle_status != LIFECYCLE_OPEN:
        return ScenarioResult(
            scenario_id=scenario.scenario_id, capability=scenario.capability, source=scenario.source,
            status=STATUS_UNKNOWN, critical=False,
            reasons=(f"lifecycle_status={scenario.lifecycle_status} - excluded from active scoring",),
        )
    if scenario.ground_truth_status == GROUND_TRUTH_PENDING:
        # Section 6 hard guard: never executed for scoring purposes -
        # there is no ground truth to check a response against yet.
        return ScenarioResult(
            scenario_id=scenario.scenario_id, capability=scenario.capability, source=scenario.source,
            status=STATUS_PENDING, critical=False,
            reasons=("GROUND_TRUTH_PENDING - not scored (Section 6)",),
        )

    if scenario.source in (SOURCE_EXISTING_GOLDEN, SOURCE_REGRESSION_BUG) and scenario.underlying_case_id:
        if scenario.is_multi_turn:
            return _run_wrapped_conversation(scenario, conversation_lookup, session_chat_fn)
        return _run_wrapped_golden(scenario, golden_lookup, chat_fn, taxonomy_index)

    return _run_curated(scenario, chat_fn, session_chat_fn)


@dataclass
class BenchmarkRun:
    results: list[ScenarioResult] = field(default_factory=list)

    def by_status(self, status: str) -> list[ScenarioResult]:
        return [r for r in self.results if r.status == status]

    def scored_results(self) -> list[ScenarioResult]:
        return [r for r in self.results if r.status in (STATUS_PASS, STATUS_FAIL)]

    def overall_score(self) -> float | None:
        scored = self.scored_results()
        if not scored:
            return None
        return sum(1 for r in scored if r.status == STATUS_PASS) / len(scored)

    def capability_scores(self) -> dict[str, dict]:
        by_cap: dict[str, list[ScenarioResult]] = {}
        for r in self.scored_results():
            by_cap.setdefault(r.capability, []).append(r)
        out = {}
        for cap, results in sorted(by_cap.items()):
            passed = sum(1 for r in results if r.status == STATUS_PASS)
            out[cap] = {"pass": passed, "fail": len(results) - passed, "total": len(results), "score": passed / len(results)}
        return out


def run_benchmark(
    scenarios: list[Scenario],
    *,
    chat_fn,
    session_chat_fn,
    taxonomy_index: dict,
) -> BenchmarkRun:
    golden_lookup = _golden_case_lookup()
    conversation_lookup = _conversation_case_lookup()
    run = BenchmarkRun()
    for scenario in scenarios:
        run.results.append(
            run_scenario(
                scenario,
                chat_fn=chat_fn,
                session_chat_fn=session_chat_fn,
                taxonomy_index=taxonomy_index,
                golden_lookup=golden_lookup,
                conversation_lookup=conversation_lookup,
            )
        )
    return run
