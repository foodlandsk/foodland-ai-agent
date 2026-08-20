"""
tests/test_advisor_engine.py  -  Sprint V2.13a: AdvisorEngine Application
Boundary & Internal Execution Unification.

Central rule (Section 5): OLD APPLICATION BEHAVIOR and NEW ADVISORENGINE
BEHAVIOR must be equivalent - even for known routing defects. This file
proves that equivalence empirically (not just architecturally), and
separately characterizes the two known routing defects (rt0004, rt0010)
plus one case pending human semantic review (rt0013) WITHOUT fixing any
of them (Invariant #2/#3).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m
from app.advisor_engine import AdvisorEngine, AdvisorRequest, advisor_engine
from app.execution_context import customer_context, evaluation_context


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _legacy_chat(message: str, session_id: str, context=None) -> dict:
    return m._chat_internal(m.ChatRequest(message=message, session_id=session_id), _FakeRequest(), execution_context=context)


def _engine_chat(message: str, session_id: str, context=None) -> dict:
    request = AdvisorRequest(message=message, session_id=session_id, client_key="127.0.0.1")
    return advisor_engine.run(request, context or evaluation_context())


_COMPARABLE_FIELDS = ("answered", "intent", "workflow_id", "response_mode", "no_result" if False else "has_more")


def _product_ids(response: dict) -> list[str]:
    return [p.get("id") for p in (response.get("products") or [])]


def _assert_equivalent(legacy: dict, engine: dict, *, context_label: str) -> None:
    assert legacy.get("answered") == engine.get("answered"), context_label
    assert legacy.get("intent") == engine.get("intent"), context_label
    assert legacy.get("workflow_id") == engine.get("workflow_id"), context_label
    assert _product_ids(legacy) == _product_ids(engine), context_label
    assert legacy.get("result_set_id") is not None or engine.get("result_set_id") is not None or "result_set_id" not in legacy, context_label


class TestAdvisorEngineIsIdentityPreservingWrapper:
    """AdvisorEngine.run() must produce byte-identical structured results
    to the legacy direct _chat_internal() call for the same inputs -
    it is a boundary, not a reimplementation."""

    def test_class_and_singleton_both_work(self):
        engine = AdvisorEngine()
        r1 = engine.run(AdvisorRequest(message="basmati ryza", session_id="ae-t1", client_key="k"), evaluation_context())
        r2 = advisor_engine.run(AdvisorRequest(message="basmati ryza", session_id="ae-t1b", client_key="k"), evaluation_context())
        assert r1.get("intent") == r2.get("intent") == "product_search"

    def test_engine_matches_legacy_for_product_search(self):
        legacy = _legacy_chat("basmati ryza", "ae-cmp-1", evaluation_context())
        engine = _engine_chat("basmati ryza", "ae-cmp-2", evaluation_context())
        _assert_equivalent(legacy, engine, context_label="basmati ryza")

    def test_engine_matches_legacy_for_recipe(self):
        legacy = _legacy_chat("recept na kokosove kura", "ae-cmp-3", evaluation_context())
        engine = _engine_chat("recept na kokosove kura", "ae-cmp-4", evaluation_context())
        _assert_equivalent(legacy, engine, context_label="recept na kokosove kura")

    def test_engine_matches_legacy_for_faq(self):
        legacy = _legacy_chat("ako mozem zaplatit?", "ae-cmp-5", evaluation_context())
        engine = _engine_chat("ako mozem zaplatit?", "ae-cmp-6", evaluation_context())
        _assert_equivalent(legacy, engine, context_label="faq")

    def test_engine_matches_legacy_for_allergen_query(self):
        legacy = _legacy_chat("sójová omáčka bez sóje", "ae-cmp-7", evaluation_context())
        engine = _engine_chat("sójová omáčka bez sóje", "ae-cmp-8", evaluation_context())
        _assert_equivalent(legacy, engine, context_label="allergen")

    def test_engine_customer_context_matches_chat_http_route(self):
        """The AdvisorEngine path chat() itself now uses (customer_context,
        real client_key derivation) must match a direct customer-context
        engine call with an equivalent client_key."""
        via_http_route = m.chat(m.ChatRequest(message="kokosovy olej", session_id="ae-http-1"), _FakeRequest())
        via_engine_direct = _engine_chat("kokosovy olej", "ae-http-2", customer_context())
        _assert_equivalent(via_http_route, via_engine_direct, context_label="kokosovy olej via chat() vs engine")


class TestBehaviorEquivalenceMatrix:
    """Section 31/32 - representative single-turn matrix, AdvisorEngine
    vs. legacy direct call, structured-field comparison."""

    QUERIES = (
        "jazmínová ryža",
        "basmati ryža",
        "ryžové rezance",
        "ryžový ocot",
        "sushi ryža",
        "Kikkoman",
        "Shin Ramyun",
        "rybacia omáčka",
        "tmavá sójová omáčka",
        "kokosové mlieko",
        "súvisiace produkty k sushi ryži",
        "sójová omáčka bez sóje",
        "náhrada za rybiu omáčku",
    )

    def test_matrix_structured_fields_match(self):
        mismatches = []
        for i, query in enumerate(self.QUERIES):
            legacy = _legacy_chat(query, f"ae-matrix-legacy-{i}", evaluation_context())
            engine = _engine_chat(query, f"ae-matrix-engine-{i}", evaluation_context())
            if (
                legacy.get("answered") != engine.get("answered")
                or legacy.get("intent") != engine.get("intent")
                or legacy.get("workflow_id") != engine.get("workflow_id")
                or _product_ids(legacy) != _product_ids(engine)
            ):
                mismatches.append((query, legacy.get("intent"), engine.get("intent")))
        assert not mismatches, f"UNEXPECTED_BEHAVIOR_DRIFT: {mismatches}"


class TestMultiTurnEquivalence:
    """Section 37 - multi-turn product refinement sequence, compared
    turn-by-turn between legacy and AdvisorEngine execution."""

    def _run_sequence(self, chat_fn, session_id: str) -> list[dict]:
        turns = ["jazmínová ryža", "len 5 kg", "radšej 1 kg", "lacnejšie"]
        responses = []
        for turn in turns:
            responses.append(chat_fn(turn, session_id, evaluation_context()))
        return responses

    def test_multi_turn_rice_refinement_matches(self):
        legacy_responses = self._run_sequence(_legacy_chat, "ae-multiturn-legacy")
        engine_responses = self._run_sequence(_engine_chat, "ae-multiturn-engine")
        assert len(legacy_responses) == len(engine_responses)
        for i, (legacy, engine) in enumerate(zip(legacy_responses, engine_responses)):
            assert legacy.get("intent") == engine.get("intent"), f"turn {i}"
            assert _product_ids(legacy) == _product_ids(engine), f"turn {i}"


class TestTopicSwitchEquivalence:
    """Section 36 - sushi -> Shin Ramyun must not leak stale context,
    identically in both paths."""

    def test_topic_switch_matches(self):
        legacy_1 = _legacy_chat("sushi ryza", "ae-topic-legacy", evaluation_context())
        legacy_2 = _legacy_chat("Shin Ramyun", "ae-topic-legacy", evaluation_context())
        engine_1 = _engine_chat("sushi ryza", "ae-topic-engine", evaluation_context())
        engine_2 = _engine_chat("Shin Ramyun", "ae-topic-engine", evaluation_context())
        assert _product_ids(legacy_2) == _product_ids(engine_2)
        assert legacy_2.get("intent") == engine_2.get("intent")


class TestCharacterization_rt0004_KNOWN_ROUTING_DEFECT_PENDING_V2_13B:
    """Section 28 - characterizes, does NOT fix. This test's purpose is to
    detect ACCIDENTAL behavior drift introduced by the AdvisorEngine
    extraction, not to assert the current behavior is desirable. See
    docs/routing-debt.md for the real root cause."""

    QUERY = "súvisiace produkty k sushi ryži"

    def test_current_defect_behavior_is_reproduced_by_advisor_engine(self):
        legacy = _legacy_chat(self.QUERY, "ae-rt0004-legacy", evaluation_context())
        engine = _engine_chat(self.QUERY, "ae-rt0004-engine", evaluation_context())
        # KNOWN_ROUTING_DEFECT_PENDING_V2_13B: the correct behavior would be
        # intent="related_products" with complementary products (nori,
        # rice vinegar, wasabi, pickled ginger). Current (defective)
        # behavior is captured here so V2.13a cannot silently change it.
        assert legacy.get("intent") == engine.get("intent") == "product_search"
        assert _product_ids(legacy) == _product_ids(engine)
        # Documents the defect signature itself (more sushi rice, not
        # complements) so a future accidental fix is visible as a test
        # change, not a silent pass.
        titles = [p.get("title", "").lower() for p in (legacy.get("products") or [])]
        assert any("ryža" in t or "ryza" in t for t in titles), "defect signature (more rice, not complements) changed unexpectedly"


class TestCharacterization_rt0010_KNOWN_SAFETY_ROUTING_GAP_PENDING_V2_13B:
    """Section 29 - characterizes, does NOT fix. See docs/routing-debt.md."""

    QUERY = "sójová omáčka bez sóje"

    def test_current_gap_behavior_is_reproduced_by_advisor_engine(self):
        legacy = _legacy_chat(self.QUERY, "ae-rt0010-legacy", evaluation_context())
        engine = _engine_chat(self.QUERY, "ae-rt0010-engine", evaluation_context())
        # KNOWN_SAFETY_ROUTING_GAP_PENDING_V2_13B: the correct behavior
        # would be intent="allergen_safety" with 0 products and a safety
        # disclaimer. Current (gap) behavior: product_search with real
        # soy-sauce products. Captured, not changed, not endorsed.
        assert legacy.get("intent") == engine.get("intent") == "product_search"
        assert len(_product_ids(legacy)) == len(_product_ids(engine)) > 0


class TestExactlyOnceSideEffects:
    """Section 39/40 - one CUSTOMER turn through AdvisorEngine must emit
    each applicable side effect exactly once, never duplicated by the
    engine boundary itself."""

    def test_one_customer_call_emits_exactly_one_quality_trace(self, tmp_path, monkeypatch):
        import app.search_quality as sq
        log_path = tmp_path / "sq.jsonl"
        monkeypatch.setattr(sq, "SEARCH_QUALITY_LOG_PATH", str(log_path))
        advisor_engine.run(AdvisorRequest(message="basmati ryza", session_id="ae-once-1", client_key="k"), customer_context())
        traces = sq.load_search_quality_traces(days=1, path=str(log_path))
        assert len(traces) == 1

    def test_one_customer_call_emits_exactly_one_question_analytics_line(self, tmp_path, monkeypatch):
        log_path = tmp_path / "questions.jsonl"
        monkeypatch.setenv("ANALYTICS_LOG_PATH", str(log_path))
        advisor_engine.run(AdvisorRequest(message="basmati ryza", session_id="ae-once-2", client_key="k"), customer_context())
        lines = log_path.read_text(encoding="utf-8").strip().splitlines() if log_path.exists() else []
        assert len(lines) == 1


class TestContextVarIsolationUnderConcurrency:
    """Section 42/56 - concurrent AdvisorEngine calls (different queries,
    different resolved families) must never leak each other's retrieval
    decision. Uses contextvars.copy_context().run() per submission, the
    same context-isolation mechanism Starlette actually uses for sync
    route handlers dispatched to its threadpool - a plain
    ThreadPoolExecutor.submit() alone would not reproduce that isolation."""

    def test_concurrent_calls_do_not_cross_contaminate_family(self):
        import contextvars
        from concurrent.futures import ThreadPoolExecutor

        queries = ["basmati ryza", "sojova omacka", "kokosovy olej", "udon rezance", "sushi ryza"] * 4

        def run_one(i, query):
            ctx = contextvars.copy_context()
            return ctx.run(lambda: _engine_chat(query, f"ae-concurrent-{i}", evaluation_context()))

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(run_one, i, q) for i, q in enumerate(queries)]
            results = [f.result() for f in futures]

        for query, result in zip(queries, results):
            titles = [p.get("title", "").lower() for p in (result.get("products") or [])]
            if "basmati" in query:
                assert all("ryž" in t or "ryz" in t for t in titles), (query, titles)
            if "sojova" in query:
                assert all("sój" in t or "soj" in t for t in titles), (query, titles)


class TestRateLimiting:
    """Section 24/59 - customer HTTP requests remain rate limited;
    internal AdvisorEngine execution (EVALUATION/ADMIN_TEST/...) is not,
    expressed purely through ExecutionContext, no isinstance(Request)
    check inside AdvisorEngine itself."""

    def test_customer_context_is_rate_limited_through_engine(self, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
        req = AdvisorRequest(message="basmati ryza", session_id="ae-ratelimit-1", client_key="ratelimit-test-key")
        advisor_engine.run(req, customer_context())
        advisor_engine.run(req, customer_context())
        with __import__("pytest").raises(m.HTTPException):
            advisor_engine.run(req, customer_context())

    def test_evaluation_context_is_never_rate_limited_through_engine(self, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "1")
        req = AdvisorRequest(message="basmati ryza", session_id="ae-ratelimit-2", client_key="ratelimit-test-key-2")
        for _ in range(5):
            advisor_engine.run(req, evaluation_context())


class TestInternalTrafficPoisoning:
    """Section 57 - mandatory: many EVALUATION/ADMIN_TEST AdvisorEngine
    calls must never increment the customer quality sample."""

    def test_many_internal_engine_calls_do_not_poison_customer_metrics(self, tmp_path, monkeypatch):
        import app.search_quality as sq
        from app.execution_context import admin_test_context
        log_path = tmp_path / "sq.jsonl"
        monkeypatch.setattr(sq, "SEARCH_QUALITY_LOG_PATH", str(log_path))
        for i in range(15):
            advisor_engine.run(AdvisorRequest(message=f"sojova omacka {i}", session_id=f"ae-poison-{i}", client_key="k"), evaluation_context())
        for i in range(15):
            advisor_engine.run(AdvisorRequest(message=f"rybacia omacka {i}", session_id=f"ae-poison-b-{i}", client_key="k"), admin_test_context())
        assert sq.load_search_quality_traces(days=1, path=str(log_path)) == []
        assert sq._read_raw_traces(days=1, path=str(log_path)) == []


class TestCharacterization_rt0013_HUMAN_SEMANTIC_REVIEW_REQUIRED:
    """Section 30 - captured for equivalence only, NOT used as a
    migration acceptance criterion beyond "AdvisorEngine == legacy"."""

    QUERY = "náhrada za rybiu omáčku"

    def test_current_behavior_reproduced_not_judged(self):
        legacy = _legacy_chat(self.QUERY, "ae-rt0013-legacy", evaluation_context())
        engine = _engine_chat(self.QUERY, "ae-rt0013-engine", evaluation_context())
        assert legacy.get("intent") == engine.get("intent")
        assert _product_ids(legacy) == _product_ids(engine)
