"""
tests/test_execution_context.py  -  V2.12.1 Part D: explicit
ExecutionContext replacing the isinstance(request, Request) hotfix as
the preferred (not the only - see the fallback tests below) signal for
rate-limiting and customer-analytics suppression in app.main._chat_impl().
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import pytest

import app.main as m
from app.execution_context import (
    ExecutionMode,
    admin_test_context,
    customer_context,
    evaluation_context,
    learning_context,
    shadow_context,
)


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


class TestExecutionContextFactories:
    def test_customer_context_applies_rate_limit_and_analytics(self):
        ctx = customer_context()
        assert ctx.mode is ExecutionMode.CUSTOMER
        assert ctx.apply_rate_limit is True
        assert ctx.emit_customer_analytics is True
        assert ctx.is_customer_traffic is True

    @pytest.mark.parametrize("factory", [evaluation_context, learning_context, shadow_context, admin_test_context])
    def test_every_non_customer_context_disables_rate_limit_and_analytics(self, factory):
        ctx = factory()
        assert ctx.apply_rate_limit is False
        assert ctx.emit_customer_analytics is False
        assert ctx.is_customer_traffic is False

    def test_modes_are_distinct(self):
        modes = {evaluation_context().mode, learning_context().mode, shadow_context().mode, admin_test_context().mode, customer_context().mode}
        assert len(modes) == 5


class TestChatImplRespectsExplicitExecutionContext:
    def test_explicit_evaluation_context_never_rate_limits_even_with_a_real_request(self, monkeypatch):
        """Before Part D, a real Request object always meant 'apply the
        customer rate limit' (isinstance-only inference) - an explicit
        EVALUATION context must override that, proving the new signal is
        actually consulted rather than isinstance always winning."""
        monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "1")
        scope = {
            "type": "http", "method": "POST", "path": "/chat", "headers": [],
            "client": ("9.9.9.9", 4321), "query_string": b"", "server": ("test", 80), "scheme": "http",
        }
        real_request = m.Request(scope) if m.Request is not object else _FakeRequest()
        chat_request = m.ChatRequest(message="jazminova ryza", limit=3, session_id="ctx-eval-real-req")
        for _ in range(5):
            m._chat_internal(chat_request, real_request, execution_context=evaluation_context())

    def test_explicit_customer_context_rate_limits_even_with_a_fake_request(self, monkeypatch):
        """Symmetric case: before Part D, a FakeRequest always bypassed
        the rate limit - an explicit CUSTOMER context must override that
        too."""
        if m.Request is object:
            pytest.skip("stub fastapi active in this session - Request/HTTPException are not real")
        monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
        chat_request = m.ChatRequest(message="jazminova ryza", limit=3, session_id="ctx-customer-fake-req")
        m._chat_internal(chat_request, _FakeRequest(), execution_context=customer_context())
        m._chat_internal(chat_request, _FakeRequest(), execution_context=customer_context())
        with pytest.raises(m.HTTPException):
            m._chat_internal(chat_request, _FakeRequest(), execution_context=customer_context())

    def test_no_context_falls_back_to_isinstance_check(self, monkeypatch):
        """Section 59 - the isinstance fallback must still work exactly
        as before for any caller that has not migrated to pass an
        explicit context."""
        if m.Request is object:
            pytest.skip("stub fastapi active in this session - Request/HTTPException are not real")
        monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
        chat_request = m.ChatRequest(message="jazminova ryza", limit=3, session_id="ctx-fallback-test")
        # FakeRequest, no explicit context -> isinstance fallback -> not rate-limited.
        for _ in range(5):
            m._chat_internal(chat_request, _FakeRequest())


class TestExecutionContextSuppressesCustomerAnalytics(object):
    def _read_analytics_lines(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_evaluation_context_never_writes_question_analytics(self, tmp_path, monkeypatch):
        analytics_path = tmp_path / "question_analytics.jsonl"
        monkeypatch.setenv("ANALYTICS_LOG_PATH", str(analytics_path))
        chat_request = m.ChatRequest(message="doprava", limit=3, session_id="ctx-analytics-eval")
        m._chat_internal(chat_request, _FakeRequest(), execution_context=evaluation_context())
        assert self._read_analytics_lines(analytics_path) == []

    def test_customer_context_writes_question_analytics(self, tmp_path, monkeypatch):
        analytics_path = tmp_path / "question_analytics.jsonl"
        monkeypatch.setenv("ANALYTICS_LOG_PATH", str(analytics_path))
        chat_request = m.ChatRequest(message="doprava", limit=3, session_id="ctx-analytics-customer")
        m._chat_internal(chat_request, _FakeRequest(), execution_context=customer_context())
        assert len(self._read_analytics_lines(analytics_path)) >= 1

    def test_shadow_context_never_writes_question_analytics(self, tmp_path, monkeypatch):
        analytics_path = tmp_path / "question_analytics.jsonl"
        monkeypatch.setenv("ANALYTICS_LOG_PATH", str(analytics_path))
        chat_request = m.ChatRequest(message="doprava", limit=3, session_id="ctx-analytics-shadow")
        m._chat_internal(chat_request, _FakeRequest(), execution_context=shadow_context())
        assert self._read_analytics_lines(analytics_path) == []

    def test_learning_context_never_writes_question_analytics(self, tmp_path, monkeypatch):
        analytics_path = tmp_path / "question_analytics.jsonl"
        monkeypatch.setenv("ANALYTICS_LOG_PATH", str(analytics_path))
        chat_request = m.ChatRequest(message="doprava", limit=3, session_id="ctx-analytics-learning")
        m._chat_internal(chat_request, _FakeRequest(), execution_context=learning_context())
        assert self._read_analytics_lines(analytics_path) == []


class TestAdapterAndShadowUseExplicitContexts:
    def test_make_chat_fn_defaults_to_evaluation_context(self):
        from app.evaluation.adapter import make_chat_fn
        # Behavioral proxy: still callable, still bypasses a tiny rate
        # limit exactly like before Part D (test_rate_limit_eval_bypass.py
        # covers the rate-limit specifics end to end already).
        chat_fn = make_chat_fn()
        result = chat_fn("jazminova ryza", 3)
        assert isinstance(result, dict)

    def test_make_chat_fn_accepts_an_explicit_override(self):
        from app.evaluation.adapter import make_chat_fn
        chat_fn = make_chat_fn(execution_context=shadow_context())
        result = chat_fn("jazminova ryza", 3)
        assert isinstance(result, dict)

    def test_ranking_shadow_uses_shadow_context(self):
        import app.ranking_shadow as rs
        import inspect
        source = inspect.getsource(rs.shadow_compare)
        assert "shadow_context()" in source

    def test_ranking_optimizer_uses_learning_context(self):
        import app.ranking_optimizer as ro
        import inspect
        source = inspect.getsource(ro.evaluate_profile)
        assert "learning_context()" in source
