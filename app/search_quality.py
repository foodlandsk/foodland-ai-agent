"""
app/search_quality.py  -  V2.12.4 Search Quality Observability & Production
Relevance Monitoring.

Ground rule (Invariant #1): this module OBSERVES the real customer path.
It does not build a parallel search/quality engine. The retrieval-decision
fields below are captured verbatim from the same computation
`app.structured_search._log_shadow()` already performs on every real
retrieval attempt (previously only reaching a Python logger, never
persisted) - nothing here is re-derived or re-computed from scratch.

Two existing telemetry sources are deliberately NOT duplicated here
(Section 28 - avoid duplicate event logs):
  - `app.learning_events`/`events.jsonl` already carries real customer
    interaction signals (impression/click/add_to_cart/no_result/
    search_submit) and `app.learning_signals.detect_reformulations()`
    already classifies reformulation sequences from it. This module reuses
    both directly for the reformulation/Show-More side of the report
    rather than re-implementing sequence detection.
  - This module adds exactly the piece that was missing: a lightweight,
    server-side snapshot of the RETRIEVAL DECISION itself (search path,
    candidate counts, contradiction filtering, family) per customer
    request, keyed by session for correlation with the interaction stream
    above. Genuinely new information, not a second copy of the same event.

Privacy (Section 9): raw query text is never stored here. A trace is
identified by session_hash (same salted-sha256 pattern as
`app.main.log_event`'s `client_hash`) and by the query's own resolved
`family` (already the privacy-safe canonicalization every other V2
telemetry module uses) - never free text.

ExecutionContext filtering (Section 8/80/81/94, Invariant #5): this module
does not decide what counts as customer traffic - it trusts its caller
(`app.main._chat_impl`/`_chat_internal`) to only invoke
`record_search_quality_trace()` when `execution_context.emit_customer_analytics`
is True, the exact same gate `log_question`/`log_event` already use.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from app.storage_paths import resolve_path

# ---------------------------------------------------------------------
# Search path taxonomy (Section 10) - the REAL retrieval_mode values
# app.retrieval already defines, plus one honest additional label for
# chat() workflow branches (recipe lookup, replacement, cross-sell, ...)
# that never attempt structured retrieval at all for a given request.
# ---------------------------------------------------------------------
PATH_STRUCTURED_EXACT = "STRUCTURED_EXACT"
PATH_STRUCTURED_FILTERED = "STRUCTURED_FILTERED"
PATH_STRUCTURED_BROAD = "STRUCTURED_BROAD"
PATH_LEGACY_FALLBACK = "LEGACY_FALLBACK"
PATH_NON_STRUCTURED_WORKFLOW = "NON_STRUCTURED_WORKFLOW"

STRUCTURED_PATHS = frozenset({PATH_STRUCTURED_EXACT, PATH_STRUCTURED_FILTERED, PATH_STRUCTURED_BROAD})
KNOWN_PATHS = STRUCTURED_PATHS | {PATH_LEGACY_FALLBACK, PATH_NON_STRUCTURED_WORKFLOW}

# ---------------------------------------------------------------------
# Per-request retrieval-decision stash. A ContextVar (not a plain module
# global) so concurrent requests never see each other's decision -
# Starlette/FastAPI copy the context per request even for sync route
# handlers run in the threadpool (Section 68 - near-zero overhead: a
# dict assignment, no I/O).
# ---------------------------------------------------------------------
_retrieval_decision: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "search_quality_retrieval_decision", default=None
)


def reset_retrieval_decision() -> None:
    """Call once at the top of every /chat request, before any retrieval
    attempt, so a request whose workflow branch never calls structured
    retrieval reports PATH_NON_STRUCTURED_WORKFLOW rather than a stale
    decision left over from a previous request context."""
    _retrieval_decision.set(None)


def stash_retrieval_decision(
    *,
    mode: str,
    family: str | None,
    constraint_count: int,
    exact_count: int,
    valid_count: int,
    nearest_count: int,
    legacy_fallback_used: bool,
    zero_exact_match: bool,
) -> None:
    """Called from `app.structured_search._log_shadow()` - the existing,
    already-computed retrieval decision, verbatim."""
    _retrieval_decision.set({
        "mode": mode if mode in KNOWN_PATHS else PATH_LEGACY_FALLBACK,
        "family": family,
        "constraint_count": constraint_count,
        "exact_count": exact_count,
        "valid_count": valid_count,
        "nearest_count": nearest_count,
        "legacy_fallback_used": legacy_fallback_used,
        "zero_exact_match": zero_exact_match,
    })


def pop_retrieval_decision() -> dict | None:
    return _retrieval_decision.get()


# ---------------------------------------------------------------------
# Trace model (Section 7 - reuse where possible, not a blind field-for-
# field copy of the spec's conceptual schema).
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class SearchQualityTrace:
    ts: int
    session_hash: str
    execution_mode: str
    retrieval_path: str
    family: str | None
    intent: str
    constraint_count: int
    exact_candidate_count: int
    valid_candidate_count: int
    nearest_candidate_count: int
    legacy_fallback_used: bool
    zero_exact_match: bool
    visible_product_count: int
    no_result: bool
    answered: bool
    latency_ms: float | None
    deployment_version: str | None
    ranking_config_version: str | None
    taxonomy_version: int | None
    resolved_workflow: str | None = None
    resolver_reason: str | None = None
    # V2.15b: opaque per-/chat-request correlation id (app.main
    # generates it once in _chat_internal(), threads it through to
    # log_question() and back into the response dict) - lets an
    # offline analyst join a quality trace to the same request's
    # question_analytics.jsonl record without timestamp guessing.
    # None for any trace built before this field existed (Section 39
    # legacy compatibility - readers already use dict.get()).
    interaction_id: str | None = None


def session_hash(session_id: str, salt: str) -> str:
    """Same salted-sha256-truncated pattern as app.main.log_event's
    `client_hash` - not a raw identifier, not reversible without the salt."""
    return hashlib.sha256(f"{salt}:{session_id}".encode("utf-8")).hexdigest()[:24]


def build_trace(
    *,
    session_id: str,
    salt: str,
    execution_mode: str,
    intent: str,
    visible_product_count: int,
    no_result: bool,
    answered: bool,
    latency_ms: float | None,
    deployment_version: str | None,
    ranking_config_version: str | None,
    taxonomy_version: int | None,
    retrieval_decision: dict | None,
    resolved_workflow: str | None = None,
    resolver_reason: str | None = None,
    interaction_id: str | None = None,
) -> SearchQualityTrace:
    decision = retrieval_decision or {
        "mode": PATH_NON_STRUCTURED_WORKFLOW,
        "family": None,
        "constraint_count": 0,
        "exact_count": 0,
        "valid_count": 0,
        "nearest_count": 0,
        "legacy_fallback_used": False,
        "zero_exact_match": False,
    }
    return SearchQualityTrace(
        ts=int(time.time()),
        session_hash=session_hash(session_id, salt),
        execution_mode=execution_mode,
        retrieval_path=decision["mode"],
        family=decision["family"],
        intent=intent,
        constraint_count=decision["constraint_count"],
        exact_candidate_count=decision["exact_count"],
        valid_candidate_count=decision["valid_count"],
        nearest_candidate_count=decision["nearest_count"],
        legacy_fallback_used=decision["legacy_fallback_used"],
        zero_exact_match=decision["zero_exact_match"],
        resolved_workflow=resolved_workflow,
        resolver_reason=resolver_reason,
        visible_product_count=visible_product_count,
        no_result=no_result,
        answered=answered,
        latency_ms=latency_ms,
        deployment_version=deployment_version,
        ranking_config_version=ranking_config_version,
        taxonomy_version=taxonomy_version,
        interaction_id=interaction_id,
    )


# ---------------------------------------------------------------------
# Durable storage (Section 55/66/67 - FOODLAND_DATA_DIR, never breaks
# customer serving on failure). Self-contained default (same convention
# as app.learning_events.EVENTS_PATH) so this module has zero dependency
# on app.main and cannot create a circular import.
# ---------------------------------------------------------------------
# V2.15b: resolved through the single FOODLAND_DATA_DIR knob instead
# of an independently-hardcoded tempdir default - the baseline/canary
# files in this same module already used app.storage_paths.resolve_path(),
# this trace stream did not (V2.15a finding). app.storage_paths has no
# dependency on app.main, so this does not reintroduce a circular import.
SEARCH_QUALITY_LOG_PATH = str(resolve_path("SEARCH_QUALITY_LOG_PATH", "search_quality.jsonl"))


def record_search_quality_trace(trace: SearchQualityTrace, path: str | None = None) -> bool:
    """Append-only, same pattern as app.main.log_event()/log_question().
    Never raises - a storage failure degrades monitoring, never customer
    serving (Section 67)."""
    resolved_path = Path(path or SEARCH_QUALITY_LOG_PATH)
    try:
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        with resolved_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(trace), ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False


def _read_raw_traces(days: int, path: str | None = None) -> list[dict]:
    resolved_path = Path(path or SEARCH_QUALITY_LOG_PATH)
    if not resolved_path.exists():
        return []
    now = int(time.time())
    since = now - max(1, days) * 86400
    records: list[dict] = []
    try:
        with resolved_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if int(record.get("ts", 0) or 0) >= since:
                    records.append(record)
    except OSError:
        return []
    return records


def load_search_quality_traces(days: int = 1, path: str | None = None) -> list[dict]:
    """Section 8 - callers doing customer-quality analysis should already
    only be reading records this module itself only ever wrote from
    CUSTOMER-mode requests (the caller-side gate), but this reader also
    defensively re-filters by execution_mode so a future bug in the
    write-side gate cannot silently poison aggregate customer metrics
    (Section 94 - internal telemetry poisoning is mandatory to prevent)."""
    raw = _read_raw_traces(days, path)
    return [r for r in raw if r.get("execution_mode") == "CUSTOMER"]


# ---------------------------------------------------------------------
# Aggregation (Section 11-18, 43-45) - global + segmented metrics.
# Section 34/73 - INSUFFICIENT_DATA is a valid result, not PASS/FAIL.
# ---------------------------------------------------------------------
MIN_SUPPORT_SEGMENT = int(os.getenv("SEARCH_QUALITY_MIN_SUPPORT_SEGMENT", "20"))
STATUS_OK = "OK"
STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _segment_summary(group: list[dict], min_support: int) -> dict:
    n = len(group)
    if n < min_support:
        return {"status": STATUS_INSUFFICIENT_DATA, "sample_size": n}
    semantic = sum(1 for t in group if t.get("retrieval_path") in STRUCTURED_PATHS)
    legacy = sum(1 for t in group if t.get("retrieval_path") == PATH_LEGACY_FALLBACK)
    non_structured = sum(1 for t in group if t.get("retrieval_path") == PATH_NON_STRUCTURED_WORKFLOW)
    # Section 14 - "unknown fallback" = the query resolved no family AND
    # fell back to the unfiltered legacy scorer (zero_exact_match with no
    # family is the taxonomy-blind case; a resolved family with
    # zero_exact_match just means no EXACT sku match, not UNKNOWN).
    unknown_fallback = sum(1 for t in group if t.get("family") is None and t.get("retrieval_path") == PATH_LEGACY_FALLBACK)
    no_result = sum(1 for t in group if t.get("no_result"))
    contradiction_filtered = sum(1 for t in group if (t.get("exact_candidate_count", 0) or 0) < (t.get("valid_candidate_count", 0) or 0))
    return {
        "status": STATUS_OK,
        "sample_size": n,
        "semantic_path_rate": _rate(semantic, n),
        "legacy_fallback_rate": _rate(legacy, n),
        "non_structured_workflow_rate": _rate(non_structured, n),
        "unknown_fallback_rate": _rate(unknown_fallback, n),
        "no_result_rate": _rate(no_result, n),
        "contradiction_filtered_rate": _rate(contradiction_filtered, n),
    }


def aggregate_traces(traces: list[dict], min_support: int = MIN_SUPPORT_SEGMENT) -> dict:
    """Section 43-45 - segmented by family/query-intent/retrieval path.
    Language segmentation (Section 44) is deferred - the current trace
    has no language field yet (customer messages are Slovak-first, no
    per-request language detector exists in the repo today; adding one
    only for telemetry would violate Section 1's 'observe, don't build a
    parallel engine' - documented gap, not silently skipped)."""
    overall = _segment_summary(traces, min_support=1)  # global uses n>=1 threshold; status still reflects min_support below
    overall["status"] = STATUS_OK if len(traces) >= min_support else STATUS_INSUFFICIENT_DATA

    by_family: dict[str, list[dict]] = {}
    by_intent: dict[str, list[dict]] = {}
    for t in traces:
        by_family.setdefault(t.get("family") or "UNKNOWN", []).append(t)
        by_intent.setdefault(t.get("intent") or "unknown", []).append(t)

    return {
        "overall": overall,
        "by_family": {k: _segment_summary(v, min_support) for k, v in by_family.items()},
        "by_intent": {k: _segment_summary(v, min_support) for k, v in by_intent.items()},
    }


# ---------------------------------------------------------------------
# Hard semantic canary framework (Section 37-40, 100-103).
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class CanaryCase:
    id: str
    language: str
    query: str
    expected_family: str | None
    must_not_family: tuple[str, ...]
    criticality: str  # CRITICAL | WARN


@dataclass(frozen=True)
class CanaryResult:
    id: str
    query: str
    retrieval_path: str | None
    family: str | None
    passed: bool
    reason: str
    latency_ms: float
    criticality: str


def load_canary_cases(path: str) -> list[CanaryCase]:
    resolved = Path(path)
    if not resolved.exists():
        return []
    data = json.loads(resolved.read_text(encoding="utf-8"))
    cases = []
    for entry in data.get("cases", []):
        cases.append(CanaryCase(
            id=entry["id"],
            language=entry.get("language", "sk"),
            query=entry["query"],
            expected_family=entry.get("expected_family"),
            must_not_family=tuple(entry.get("must_not_family", [])),
            criticality=entry.get("criticality", "CRITICAL"),
        ))
    return cases


def run_canaries(
    cases: list[CanaryCase],
    *,
    chat_fn: Callable[[str], dict],
    classify_product_family: Callable[[str], str | None],
) -> list[CanaryResult]:
    """Section 102/103 - `chat_fn` must already be bound to an
    EVALUATION/ADMIN_TEST execution context by the caller (this function
    is execution-context-agnostic by design; enforcing CUSTOMER exclusion
    is the caller's responsibility - see app.main's admin canary endpoint,
    which always uses `_admin_test_context()`). `classify_product_family`
    maps a returned product id to its canonical_family (product_taxonomy_index
    lookup) so wrong-family leakage (Section 40) is checked against the
    ACTUAL returned products, not just the query's own resolved family."""
    results = []
    for case in cases:
        start = time.perf_counter()
        try:
            response = chat_fn(case.query)
        except Exception as exc:
            results.append(CanaryResult(
                id=case.id, query=case.query, retrieval_path=None, family=None,
                passed=False, reason=f"chat_fn raised: {exc}",
                latency_ms=(time.perf_counter() - start) * 1000, criticality=case.criticality,
            ))
            continue
        latency_ms = (time.perf_counter() - start) * 1000
        products = response.get("products") or []
        leaked_families = set()
        for product in products:
            pid = product.get("id")
            if not pid:
                continue
            fam = classify_product_family(pid)
            if fam and fam in case.must_not_family:
                leaked_families.add(fam)

        decision = pop_retrieval_decision()
        retrieval_path = decision["mode"] if decision else None
        family = decision["family"] if decision else None

        if leaked_families:
            passed = False
            reason = f"wrong_family_leakage: {sorted(leaked_families)}"
        elif case.expected_family and family and family != case.expected_family:
            passed = False
            reason = f"expected_family={case.expected_family} got={family}"
        else:
            passed = True
            reason = "OK"

        results.append(CanaryResult(
            id=case.id, query=case.query, retrieval_path=retrieval_path, family=family,
            passed=passed, reason=reason, latency_ms=latency_ms, criticality=case.criticality,
        ))
    return results


# ---------------------------------------------------------------------
# Anomaly detection (Section 52-54, 108-110) - deployment-window
# comparison only, never triggers a production change by itself
# (Invariant #2/#11 - observability, AUTO_PROMOTION stays disabled).
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class QualityAnomaly:
    id: str
    type: str
    scope: str
    severity: str  # INFO | WARN | CRITICAL
    current_value: float | None
    baseline_value: float | None
    delta: float | None
    sample_size: int
    confidence: str
    deployment_version: str | None
    evidence: dict


TYPE_LEGACY_FALLBACK_SPIKE = "LEGACY_FALLBACK_SPIKE"
TYPE_NO_RESULT_SPIKE = "NO_RESULT_SPIKE"
TYPE_UNKNOWN_FALLBACK_SPIKE = "UNKNOWN_FALLBACK_SPIKE"
TYPE_CANARY_SEMANTIC_FAILURE = "CANARY_SEMANTIC_FAILURE"
TYPE_WRONG_FAMILY_LEAKAGE = "WRONG_FAMILY_LEAKAGE"

MIN_SUPPORT_ANOMALY = int(os.getenv("SEARCH_QUALITY_MIN_SUPPORT_ANOMALY", "50"))
WARN_RELATIVE_DELTA = float(os.getenv("SEARCH_QUALITY_WARN_RELATIVE_DELTA", "0.3"))
CRITICAL_RELATIVE_DELTA = float(os.getenv("SEARCH_QUALITY_CRITICAL_RELATIVE_DELTA", "0.75"))


def _rate_spike_anomaly(
    type_: str, scope: str, baseline_value: float | None, current_value: float | None,
    sample_size: int, deployment_version: str | None,
) -> QualityAnomaly | None:
    """Section 34/54 - only a RISING rate with sufficient sample support
    is ever flagged; a metric improving is never an anomaly here."""
    if sample_size < MIN_SUPPORT_ANOMALY or baseline_value is None or current_value is None:
        return None
    delta = current_value - baseline_value
    if delta <= 0:
        return None
    relative = (delta / baseline_value) if baseline_value > 0 else float("inf")
    if relative >= CRITICAL_RELATIVE_DELTA:
        severity = "CRITICAL"
    elif relative >= WARN_RELATIVE_DELTA:
        severity = "WARN"
    else:
        return None
    return QualityAnomaly(
        id=f"{type_}:{scope}",
        type=type_,
        scope=scope,
        severity=severity,
        current_value=current_value,
        baseline_value=baseline_value,
        delta=delta,
        sample_size=sample_size,
        confidence="HIGH" if sample_size >= MIN_SUPPORT_ANOMALY * 2 else "MEDIUM",
        deployment_version=deployment_version,
        evidence={"relative_delta": relative},
    )


def detect_anomalies(baseline_metrics: dict, current_metrics: dict, deployment_version: str | None) -> list[QualityAnomaly]:
    """Section 33/42/109 - deployment-to-deployment comparison. Stable,
    deterministic anomaly ids (type:scope) so re-running against the same
    window never produces duplicate/renamed anomalies (Section 109)."""
    anomalies = []
    overall_current = current_metrics.get("overall", {})
    overall_baseline = baseline_metrics.get("overall", {})
    n = overall_current.get("sample_size", 0)
    for metric_key, anomaly_type in (
        ("legacy_fallback_rate", TYPE_LEGACY_FALLBACK_SPIKE),
        ("no_result_rate", TYPE_NO_RESULT_SPIKE),
        ("unknown_fallback_rate", TYPE_UNKNOWN_FALLBACK_SPIKE),
    ):
        a = _rate_spike_anomaly(
            anomaly_type, "global", overall_baseline.get(metric_key), overall_current.get(metric_key),
            n, deployment_version,
        )
        if a:
            anomalies.append(a)

    for family, current_seg in current_metrics.get("by_family", {}).items():
        baseline_seg = baseline_metrics.get("by_family", {}).get(family, {})
        a = _rate_spike_anomaly(
            TYPE_LEGACY_FALLBACK_SPIKE, f"family:{family}",
            baseline_seg.get("legacy_fallback_rate"), current_seg.get("legacy_fallback_rate"),
            current_seg.get("sample_size", 0), deployment_version,
        )
        if a:
            anomalies.append(a)
    return anomalies


def canary_anomalies(canary_results: list[CanaryResult], deployment_version: str | None) -> list[QualityAnomaly]:
    """Section 36/77 - hard semantic canary failures are deterministic
    invariant violations, always CRITICAL regardless of sample size
    (Section 54 - 'hard canary semantic failures may bypass statistical
    thresholds')."""
    anomalies = []
    for result in canary_results:
        if result.passed:
            continue
        anomaly_type = TYPE_WRONG_FAMILY_LEAKAGE if "wrong_family_leakage" in result.reason else TYPE_CANARY_SEMANTIC_FAILURE
        severity = "CRITICAL" if result.criticality == "CRITICAL" else "WARN"
        anomalies.append(QualityAnomaly(
            id=f"{anomaly_type}:{result.id}",
            type=anomaly_type,
            scope=result.id,
            severity=severity,
            current_value=None,
            baseline_value=None,
            delta=None,
            sample_size=1,
            confidence="HIGH",
            deployment_version=deployment_version,
            evidence={"query": result.query, "reason": result.reason, "family": result.family, "retrieval_path": result.retrieval_path},
        ))
    return anomalies


# ---------------------------------------------------------------------
# Durable production quality baselines (Section 55-58) - FOODLAND_DATA_DIR,
# never auto-promoted (Section 57/129/130).
# ---------------------------------------------------------------------
def _baseline_path() -> Path:
    from app.storage_paths import resolve_path
    return resolve_path("SEARCH_QUALITY_BASELINE_PATH", "search_quality_baseline.json")


def save_quality_baseline(metrics: dict, *, deployment_version: str | None, ranking_config_version: str | None) -> None:
    """Section 57 - the CALLER decides when promotion is warranted
    (a controlled/manual/policy decision); this function only performs
    the durable write once that decision has been made. Never called
    automatically after every report (Section 56/129)."""
    from app.durable_storage import atomic_write_json
    payload = {
        "created_at": int(time.time()),
        "deployment_version": deployment_version,
        "ranking_config_version": ranking_config_version,
        "metrics": metrics,
    }
    atomic_write_json(_baseline_path(), payload)


def load_quality_baseline() -> dict | None:
    path = _baseline_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------
# Last canary run result (durable, Section 65/113 - so GET .../canary and
# public /health can report the last status without re-running canaries
# on every read).
# ---------------------------------------------------------------------
def _last_canary_path() -> Path:
    from app.storage_paths import resolve_path
    return resolve_path("SEARCH_QUALITY_CANARY_STATE_PATH", "search_quality_last_canary.json")


def save_last_canary_result(results: list[CanaryResult], anomalies: list[QualityAnomaly], deployment_version: str | None) -> None:
    from app.durable_storage import atomic_write_json
    payload = {
        "ran_at": int(time.time()),
        "deployment_version": deployment_version,
        "pass_count": sum(1 for r in results if r.passed),
        "total_count": len(results),
        "all_passed": all(r.passed for r in results),
        "results": [asdict(r) for r in results],
        "anomalies": [asdict(a) for a in anomalies],
    }
    atomic_write_json(_last_canary_path(), payload)


def load_last_canary_result() -> dict | None:
    path = _last_canary_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------
# Report generation (Section 47-51, 111-113).
# ---------------------------------------------------------------------
def current_deployment_version() -> str | None:
    """Section 30 - 'where infrastructure allows'. Railway stamps
    RAILWAY_GIT_COMMIT_SHA as a build-time env var; honestly None
    elsewhere rather than fabricated."""
    return os.getenv("RAILWAY_GIT_COMMIT_SHA") or os.getenv("DEPLOYMENT_VERSION")


def generate_quality_report(
    *,
    days: int = 1,
    min_support: int = MIN_SUPPORT_SEGMENT,
    path: str | None = None,
    ranking_config_version: str | None = None,
) -> dict:
    """Section 47/128 - if volume is insufficient, the report says so
    honestly (STATUS_INSUFFICIENT_DATA) rather than fabricating a
    conclusion."""
    traces = load_search_quality_traces(days=days, path=path)
    current = aggregate_traces(traces, min_support=min_support)
    baseline = load_quality_baseline()
    deployment_version = current_deployment_version()

    anomalies: list[QualityAnomaly] = []
    if baseline and current["overall"]["status"] == STATUS_OK:
        anomalies = detect_anomalies(baseline.get("metrics", {}), current, deployment_version)

    return {
        "generated_at": int(time.time()),
        "period_days": days,
        "deployment_version": deployment_version,
        "ranking_config_version": ranking_config_version,
        "sample_size": len(traces),
        "current": current,
        "baseline_present": baseline is not None,
        "baseline_deployment_version": baseline.get("deployment_version") if baseline else None,
        "anomalies": [asdict(a) for a in anomalies],
    }
