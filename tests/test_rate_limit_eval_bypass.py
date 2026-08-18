"""
tests/test_rate_limit_eval_bypass.py  -  regression test for a real
production bug found running V2.12's learning cycle against Railway:
app.evaluation.adapter.make_chat_fn() calls app.main.chat() directly with
a plain, duck-typed _FakeRequest stub (client.host="127.0.0.1", never a
real Starlette/FastAPI Request). Every such call shared ONE rate-limit
bucket, and in production (where RATE_LIMIT_PER_MINUTE is a real,
explicitly-configured value - unlike CI/tests, where the harness's own
`os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")` successfully
overrides an UNSET var) a single evaluate_profile() call tripped the
customer-facing 429 after ~12 calls, ~12 seconds into a real
`POST /admin/learning/run-cycle`.

Fix: `chat()` only calls `enforce_rate_limit()` when `request` is a real
`isinstance(request, Request)` - something only the actual FastAPI ASGI
dispatch can construct, never spoofable by an external HTTP client via
headers/query/body, since FastAPI itself controls what `request` is.

Note: tests/test_core.py installs a lightweight stub `fastapi` module
(`Request = object`) into sys.modules the first time it runs in a
session; once installed, `isinstance(x, object)` is trivially true for
everything, so this test's bypass assertion is only meaningful under the
REAL fastapi package - skipped (not falsely failed) when the stub is
active, matching this repo's existing dual-mode test convention (see
tests/test_main_learning_endpoints.py's m.HTTPException comment)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import pytest

import app.main as m

_REAL_FASTAPI = m.Request is not object


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


@pytest.mark.skipif(not _REAL_FASTAPI, reason="stub fastapi active in this session (Request is object) - bypass check is meaningless here")
class TestEvalHarnessBypassesCustomerRateLimit:
    def test_fake_request_bypasses_rate_limit_under_a_tiny_limit(self, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
        chat_request = m.ChatRequest(message="jazminova ryza", limit=3, session_id="rl-bypass-test")
        for _ in range(5):  # well past the tiny limit - must never raise for a FakeRequest
            m.chat(chat_request, _FakeRequest())

    def test_real_request_still_enforced_under_the_same_tiny_limit(self, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
        scope = {
            "type": "http", "method": "POST", "path": "/chat", "headers": [],
            "client": ("9.9.9.9", 1234), "query_string": b"", "server": ("test", 80), "scheme": "http",
        }
        real_request = m.Request(scope)
        chat_request = m.ChatRequest(message="jazminova ryza", limit=3, session_id="rl-real-test")
        m.chat(chat_request, real_request)
        m.chat(chat_request, real_request)
        with pytest.raises(m.HTTPException):
            m.chat(chat_request, real_request)


@pytest.mark.skipif(not _REAL_FASTAPI, reason="stub fastapi active in this session (Request is object) - bypass check is meaningless here")
class TestMakeChatFnUsesTheBypass:
    """Section 128 - deterministic, no live production traffic needed."""

    def test_make_chat_fn_survives_a_tiny_production_style_limit(self, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
        from app.evaluation.adapter import make_chat_fn
        chat_fn = make_chat_fn()
        for _ in range(5):
            chat_fn("jazminova ryza", 3)
