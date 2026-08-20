"""
tests/test_search_quality.py  -  Sprint V2.12.4: Search Quality
Observability & Production Relevance Monitoring.

Covers the spec's mandatory test matrix (Sections 79-99). Every trace/
aggregation test goes through the REAL app.main._chat_internal() pipeline
(same convention as tests/test_query_semantics_v2122.py and
tests/test_query_semantics_v2123.py) - the whole point of this sprint is
observing the real customer path, not a synthetic one (Invariant #1).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import pytest

import app.main as m
import app.search_quality as sq
from app.execution_context import admin_test_context, customer_context, evaluation_context, learning_context, shadow_context


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, context=None) -> dict:
    return m._chat_internal(m.ChatRequest(message=message, session_id=session_id), _FakeRequest(), execution_context=context)


@pytest.fixture()
def quality_log(tmp_path, monkeypatch):
    log_path = tmp_path / "search_quality.jsonl"
    monkeypatch.setattr(sq, "SEARCH_QUALITY_LOG_PATH", str(log_path))
    return str(log_path)


class TestCustomerTraceEmission:
    """Section 79 - a normal customer search emits one coherent trace with
    execution_mode=CUSTOMER, real retrieval path, candidate counts,
    deployment/ranking version."""

    def test_customer_query_emits_one_trace_with_expected_fields(self, quality_log):
        _chat("kokosovy olej", "sq-t79", context=customer_context())
        traces = sq.load_search_quality_traces(days=1, path=quality_log)
        assert len(traces) == 1
        trace = traces[0]
        assert trace["execution_mode"] == "CUSTOMER"
        assert trace["retrieval_path"] in sq.KNOWN_PATHS
        assert trace["family"] == "oil"
        assert trace["visible_product_count"] > 0
        assert trace["ranking_config_version"] is not None
        assert trace["taxonomy_version"] is not None
        assert "kokosovy" not in str(trace)  # Section 9 - no raw query text stored


class TestInternalTraceExclusion:
    """Section 80/81/94 - EVALUATION/LEARNING/SHADOW traffic (and repeated
    volume of it) must never increment customer quality trace counts."""

    def test_evaluation_context_produces_no_trace(self, quality_log):
        _chat("sojova omacka", "sq-t80", context=evaluation_context())
        assert sq.load_search_quality_traces(days=1, path=quality_log) == []

    def test_shadow_context_produces_no_trace(self, quality_log):
        _chat("rybacia omacka", "sq-t81", context=shadow_context())
        assert sq.load_search_quality_traces(days=1, path=quality_log) == []

    def test_learning_context_produces_no_trace(self, quality_log):
        _chat("kokosove mlieko", "sq-t81b", context=learning_context())
        assert sq.load_search_quality_traces(days=1, path=quality_log) == []

    def test_many_internal_requests_never_poison_customer_metrics(self, quality_log):
        """Section 94 - mandatory: run many evaluation/shadow requests,
        expect production customer-quality metrics unchanged."""
        for i in range(15):
            _chat(f"sojova omacka {i}", f"sq-t94-{i}", context=evaluation_context())
        for i in range(15):
            _chat(f"rybacia omacka {i}", f"sq-t94b-{i}", context=shadow_context())
        assert sq.load_search_quality_traces(days=1, path=quality_log) == []
        # defense in depth: even a raw, unfiltered read shows nothing,
        # since the write-side gate never wrote anything at all.
        assert sq._read_raw_traces(days=1, path=quality_log) == []


class TestLegacyFallbackMetric:
    """Section 82 - a query that structured retrieval cannot confidently
    resolve must increment the legacy fallback path."""

    def test_unresolved_family_query_records_legacy_fallback(self, quality_log):
        _chat("wasabi", "sq-t82", context=customer_context())
        traces = sq.load_search_quality_traces(days=1, path=quality_log)
        assert len(traces) == 1
        assert traces[0]["retrieval_path"] == sq.PATH_LEGACY_FALLBACK
        assert traces[0]["family"] is None


class TestSemanticPathMetric:
    """Section 83 - a known structured query increments a STRUCTURED_* path."""

    def test_known_structured_query_records_semantic_path(self, quality_log):
        _chat("basmati ryza", "sq-t83", context=customer_context())
        traces = sq.load_search_quality_traces(days=1, path=quality_log)
        assert len(traces) == 1
        assert traces[0]["retrieval_path"] in sq.STRUCTURED_PATHS
        assert traces[0]["family"] == "rice"


class TestContradictionAndUnknownRetention:
    """Section 84/85 - contradiction filtering is visible, and an
    unknown-taxonomy exact product remains discoverable (not silently
    dropped) - regbug_rt0010-adjacent invariant, but for retrieval, not
    safety text."""

    def test_jasmine_rice_query_stays_within_rice_family(self, quality_log):
        response = _chat("jazmínová ryža", "sq-t84", context=customer_context())
        titles = [p.get("title", "").lower() for p in (response.get("products") or [])]
        assert titles
        assert not any("čaj" in t or "caj" in t for t in titles)
        traces = sq.load_search_quality_traces(days=1, path=quality_log)
        assert traces[0]["family"] == "rice"

    def test_exact_brand_product_lookup_still_returns_results(self, quality_log):
        response = _chat("kikkoman", "sq-t85", context=customer_context())
        assert response.get("products")


class TestNoResultSemantics:
    """Section 17/18/86/99 - products=[] does NOT automatically mean
    no_result; a substantive answer (allergen safety, FAQ) must not be
    misclassified as a search failure. Reuses _compute_answered() -
    the same choke point every /chat response already passes through."""

    def test_substantive_allergen_answer_is_not_no_result(self, quality_log):
        response = _chat("sójová omáčka bez sóje", "sq-t99", context=customer_context())
        traces = sq.load_search_quality_traces(days=1, path=quality_log)
        assert len(traces) == 1
        assert traces[0]["answered"] == response["answered"]
        if response["answered"]:
            assert traces[0]["no_result"] is False

    def test_no_result_and_answered_are_always_complementary(self, quality_log):
        _chat("basmati ryza", "sq-t86", context=customer_context())
        trace = sq.load_search_quality_traces(days=1, path=quality_log)[0]
        assert trace["no_result"] == (not trace["answered"])


class TestNonStructuredWorkflow:
    """A chat workflow branch that never attempts structured retrieval at
    all (e.g. recipe lookup) must be labeled honestly, not silently
    inherit a stale decision from a previous request (per-request reset)."""

    def test_recipe_workflow_records_non_structured_path(self, quality_log):
        _chat("recept na kokosove kura", "sq-t-recipe", context=customer_context())
        trace = sq.load_search_quality_traces(days=1, path=quality_log)[0]
        assert trace["retrieval_path"] == sq.PATH_NON_STRUCTURED_WORKFLOW

    def test_reset_prevents_stale_decision_leaking_across_requests(self, quality_log):
        _chat("basmati ryza", "sq-t-reset-a", context=customer_context())
        _chat("recept na kokosove kura", "sq-t-reset-b", context=customer_context())
        traces = sq.load_search_quality_traces(days=1, path=quality_log)
        assert traces[0]["retrieval_path"] in sq.STRUCTURED_PATHS
        assert traces[1]["retrieval_path"] == sq.PATH_NON_STRUCTURED_WORKFLOW


class TestCanaryPassAndFailure:
    """Section 89/90 - a deliberately wrong semantic result must fail
    CRITICAL with wrong-family leakage detected; a correct one passes."""

    def test_canary_pass_on_correct_semantics(self):
        case = sq.CanaryCase(id="pass_case", language="sk", query="basmati ryza", expected_family="rice", must_not_family=("noodles",), criticality="CRITICAL")
        results = sq.run_canaries(
            [case],
            chat_fn=lambda q: _chat(q, "sq-canary-pass", context=admin_test_context()),
            classify_product_family=lambda pid: m.product_taxonomy_index.get(pid).canonical_family if m.product_taxonomy_index.get(pid) else None,
        )
        assert results[0].passed
        assert sq.canary_anomalies(results, "dep-1") == []

    def test_canary_fails_critical_on_injected_wrong_family(self):
        case = sq.CanaryCase(id="fail_case", language="sk", query="kokosovy olej", expected_family="coconut_product", must_not_family=("oil",), criticality="CRITICAL")
        results = sq.run_canaries(
            [case],
            chat_fn=lambda q: _chat(q, "sq-canary-fail", context=admin_test_context()),
            classify_product_family=lambda pid: m.product_taxonomy_index.get(pid).canonical_family if m.product_taxonomy_index.get(pid) else None,
        )
        assert not results[0].passed
        assert "wrong_family_leakage" in results[0].reason
        anomalies = sq.canary_anomalies(results, "dep-1")
        assert len(anomalies) == 1
        assert anomalies[0].severity == "CRITICAL"
        assert anomalies[0].type == sq.TYPE_WRONG_FAMILY_LEAKAGE

    def test_real_canary_set_passes(self):
        """The actual shipped canary definition must pass against the
        real catalog - a genuine regression gate, not a synthetic check."""
        cases = sq.load_canary_cases(str(ROOT / "eval" / "search_quality_canaries.json"))
        assert len(cases) >= 10
        results = sq.run_canaries(
            cases,
            chat_fn=lambda q: _chat(q, "sq-canary-real", context=admin_test_context()),
            classify_product_family=lambda pid: m.product_taxonomy_index.get(pid).canonical_family if m.product_taxonomy_index.get(pid) else None,
        )
        failed = [r for r in results if not r.passed]
        assert not failed, failed


class TestCanaryExecutionContextIsolation:
    """Section 39/103/127 - canary execution must NEVER contaminate
    customer quality metrics, however many times it runs."""

    def test_repeated_canary_runs_do_not_increment_customer_metrics(self, quality_log):
        cases = sq.load_canary_cases(str(ROOT / "eval" / "search_quality_canaries.json"))
        for _ in range(3):
            sq.run_canaries(
                cases,
                chat_fn=lambda q: _chat(q, "sq-canary-isolation", context=admin_test_context()),
                classify_product_family=lambda pid: m.product_taxonomy_index.get(pid).canonical_family if m.product_taxonomy_index.get(pid) else None,
            )
        assert sq.load_search_quality_traces(days=1, path=quality_log) == []
        assert sq._read_raw_traces(days=1, path=quality_log) == []


class TestDeploymentComparisonAndAnomalies:
    """Section 91/92 - a real rate spike with sufficient support becomes
    an anomaly; the same shift with a tiny sample does not."""

    def test_sufficient_support_spike_detected(self):
        baseline = sq.aggregate_traces(
            [{"retrieval_path": "STRUCTURED_FILTERED", "family": "sauce", "no_result": False}] * 190
            + [{"retrieval_path": "LEGACY_FALLBACK", "family": "sauce", "no_result": False}] * 10,
            min_support=20,
        )
        current = sq.aggregate_traces(
            [{"retrieval_path": "STRUCTURED_FILTERED", "family": "sauce", "no_result": False}] * 150
            + [{"retrieval_path": "LEGACY_FALLBACK", "family": "sauce", "no_result": False}] * 50,
            min_support=20,
        )
        anomalies = sq.detect_anomalies(baseline, current, deployment_version="dep-2")
        types = {a.type for a in anomalies}
        assert sq.TYPE_LEGACY_FALLBACK_SPIKE in types

    def test_low_support_shift_is_insufficient_data_not_critical(self):
        baseline = sq.aggregate_traces(
            [{"retrieval_path": "STRUCTURED_FILTERED", "family": "sauce", "no_result": False}] * 190
            + [{"retrieval_path": "LEGACY_FALLBACK", "family": "sauce", "no_result": False}] * 10,
            min_support=20,
        )
        tiny_current = sq.aggregate_traces(
            [{"retrieval_path": "LEGACY_FALLBACK", "family": "sauce", "no_result": False}] * 2
            + [{"retrieval_path": "STRUCTURED_FILTERED", "family": "sauce", "no_result": False}],
            min_support=20,
        )
        assert tiny_current["overall"]["status"] == sq.STATUS_INSUFFICIENT_DATA
        assert sq.detect_anomalies(baseline, tiny_current, deployment_version="dep-2") == []

    def test_improving_metric_is_never_flagged(self):
        baseline = sq.aggregate_traces(
            [{"retrieval_path": "STRUCTURED_FILTERED", "family": "sauce", "no_result": False}] * 150
            + [{"retrieval_path": "LEGACY_FALLBACK", "family": "sauce", "no_result": False}] * 50,
            min_support=20,
        )
        current = sq.aggregate_traces(
            [{"retrieval_path": "STRUCTURED_FILTERED", "family": "sauce", "no_result": False}] * 195
            + [{"retrieval_path": "LEGACY_FALLBACK", "family": "sauce", "no_result": False}] * 5,
            min_support=20,
        )
        assert sq.detect_anomalies(baseline, current, deployment_version="dep-2") == []


class TestStorageFailureDoesNotBreakServing:
    """Section 67/93 - if quality-trace storage fails, customer search
    still works; monitoring degrades silently, request does not."""

    def test_record_trace_to_unwritable_path_returns_false_not_raises(self, tmp_path):
        # A path whose parent cannot be created (a file standing where a
        # directory is expected) reliably fails mkdir/open on every OS.
        blocker = tmp_path / "blocked"
        blocker.write_text("x", encoding="utf-8")
        bad_path = str(blocker / "sub" / "search_quality.jsonl")
        trace = sq.build_trace(
            session_id="s", salt="", execution_mode="CUSTOMER", intent="product_search",
            visible_product_count=1, no_result=False, answered=True, latency_ms=1.0,
            deployment_version=None, ranking_config_version=None, taxonomy_version=1,
            retrieval_decision=None,
        )
        assert sq.record_search_quality_trace(trace, path=bad_path) is False

    def test_customer_chat_still_works_when_quality_log_path_is_unwritable(self, tmp_path, monkeypatch):
        blocker = tmp_path / "blocked2"
        blocker.write_text("x", encoding="utf-8")
        monkeypatch.setattr(sq, "SEARCH_QUALITY_LOG_PATH", str(blocker / "sub" / "search_quality.jsonl"))
        response = _chat("basmati ryza", "sq-storage-fail", context=customer_context())
        assert response.get("products")
        assert response["answered"] is True


class TestRankingAndDeploymentVersionFields:
    """Section 95/96 - trace/report distinguishes ranking config version
    from deployment (code) version."""

    def test_trace_includes_active_ranking_config_version(self, quality_log):
        _chat("basmati ryza", "sq-t95", context=customer_context())
        trace = sq.load_search_quality_traces(days=1, path=quality_log)[0]
        assert trace["ranking_config_version"] == m.get_active_ranking_profile_version()

    def test_report_differentiates_deployment_version_field(self, quality_log, monkeypatch):
        monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "deploy-abc123")
        _chat("basmati ryza", "sq-t96", context=customer_context())
        report = sq.generate_quality_report(days=1, path=quality_log, ranking_config_version="v1")
        assert report["deployment_version"] == "deploy-abc123"


class TestFamilyAndIntentSegmentation:
    """Section 97 - rice and sauce query metrics remain separately
    aggregatable, without merging distinct families' evidence."""

    def test_rice_and_sauce_traces_segment_independently(self, quality_log):
        for i in range(25):
            _chat("basmati ryza", f"sq-rice-{i}", context=customer_context())
        for i in range(25):
            _chat("sojova omacka", f"sq-sauce-{i}", context=customer_context())
        traces = sq.load_search_quality_traces(days=1, path=quality_log)
        agg = sq.aggregate_traces(traces, min_support=20)
        assert agg["by_family"]["rice"]["status"] == sq.STATUS_OK
        assert agg["by_family"]["sauce"]["status"] == sq.STATUS_OK
        assert agg["by_family"]["rice"]["sample_size"] == 25
        assert agg["by_family"]["sauce"]["sample_size"] == 25


@pytest.fixture()
def read_admin_token(monkeypatch):
    monkeypatch.setenv("ADMIN_READ_TOKEN", "test-read-token")
    yield "test-read-token"


@pytest.fixture()
def ops_admin_token(monkeypatch):
    monkeypatch.setenv("ADMIN_OPERATIONS_TOKEN", "test-ops-token")
    yield "test-ops-token"


class TestAdminEndpointScoping:
    """Section 62-64 - READ-scope endpoints reject a missing/wrong token;
    the OPERATIONS-scope run endpoint rejects a READ-only token."""

    def test_status_requires_token(self, read_admin_token):
        with pytest.raises(m.HTTPException):
            m.admin_search_quality_status(x_admin_token=None)

    def test_status_works_with_read_token(self, read_admin_token):
        result = m.admin_search_quality_status(x_admin_token=read_admin_token)
        for key in ("search_quality_monitor_enabled", "auto_promotion_enabled", "production_quality_baseline_present"):
            assert key in result
        assert result["auto_promotion_enabled"] is False

    def test_report_requires_token(self, read_admin_token):
        with pytest.raises(m.HTTPException):
            m.admin_search_quality_report(x_admin_token=None)

    def test_anomalies_works_with_read_token(self, read_admin_token):
        result = m.admin_search_quality_anomalies(x_admin_token=read_admin_token)
        assert "anomalies" in result

    def test_canary_get_works_with_read_token_before_any_run(self, read_admin_token):
        result = m.admin_search_quality_canary_status(x_admin_token=read_admin_token)
        assert result.get("status") == "never_run" or "all_passed" in result

    def test_run_endpoint_rejects_read_only_token(self, read_admin_token):
        with pytest.raises(m.HTTPException):
            m.admin_search_quality_run(x_admin_token=read_admin_token)

    def test_run_endpoint_accepts_operations_token(self, ops_admin_token):
        result = m.admin_search_quality_run(x_admin_token=ops_admin_token)
        assert "canary_pass_count" in result
        assert "canary_total_count" in result
        assert result["canary_total_count"] >= 10

    def test_run_endpoint_persists_canary_result_for_get_endpoint(self, ops_admin_token):
        m.admin_search_quality_run(x_admin_token=ops_admin_token)
        status = m.admin_search_quality_canary_status(x_admin_token=ops_admin_token)
        assert "all_passed" in status
        assert status["total_count"] >= 10


class TestPublicHealthExposesOnlySafeAggregate:
    """Section 65 - public /health exposes aggregate status only, never
    anomaly details, raw traces, or per-query evidence."""

    def test_health_includes_search_quality_block(self):
        result = m.health()
        block = result.get("search_quality")
        assert block is not None
        for key in ("search_quality_monitor_enabled", "last_quality_report_status", "last_canary_status", "production_quality_baseline_present"):
            assert key in block
        assert "anomalies" not in block
        assert "results" not in block


class TestPrivacyNoRawQueryStored:
    """Section 9/49 - no raw query text, no PII in a trace record."""

    def test_trace_contains_no_raw_query_text(self, quality_log):
        _chat("kokosovy olej pre Jana Novaka jan@example.com", "sq-privacy", context=customer_context())
        traces = sq._read_raw_traces(days=1, path=quality_log)
        assert traces
        blob = str(traces[0])
        assert "jan@example.com" not in blob
        assert "Jana Novaka" not in blob
        assert "kokosovy olej" not in blob
