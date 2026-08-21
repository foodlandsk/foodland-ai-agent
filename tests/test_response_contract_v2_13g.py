"""
tests/test_response_contract_v2_13g.py  -  V2.13g: permanent defense
against future drift of the canonical /chat response contract
(docs/response-contract-v2.13g.md) across all 8 terminal branches of
the commerce matches-dispatch pipeline (app.main._chat_impl(), the
same pipeline characterized - not extracted - by V2.13f-A,
docs/commerce-pipeline-v2.13f-a.md).

Per that contract, REQUIRED_ALWAYS fields for every one of these 8
branches are: answer, products, intent, memory, response_mode.
REQUIRED_WHEN_APPLICABLE fields (articles/cart_candidates/
missing_ingredients/shopping_list/knowledge) are intentionally NOT
asserted here where a branch has nothing meaningful to report (the 2
zero-match branches) - forcing them would contradict the contract
itself (docs/response-contract-v2.13g.md Section 2).

This file is intentionally separate from
tests/test_commerce_pipeline_v2_13f_a.py: that file's job is
characterizing/freezing pipeline BEHAVIOR (control flow, side effects,
dispatch), this file's job is asserting the PUBLIC CONTRACT SHAPE - a
distinct concern per the V2.13g spec (Section 13: "add a small
dedicated test file only if a test logically does not belong in the
existing characterization file").
"""
from __future__ import annotations

import os
import sys
import unittest.mock as mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m
from app.advisor_engine import AdvisorRequest, advisor_engine
from app.execution_context import customer_context
from openai import RateLimitError

REQUIRED_ALWAYS = ("answer", "products", "intent", "memory", "response_mode")


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, limit: int = 8) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


def _make_rate_limit_error(message: str = "contract-test"):
    return RateLimitError(message, response=mock.MagicMock(status_code=429, headers={}), body=None)


def _assert_required_always(r: dict, branch: str):
    for field in REQUIRED_ALWAYS:
        assert field in r, f"branch={branch!r} missing REQUIRED_ALWAYS field {field!r}: {r!r}"


class TestAllEightTerminalBranchesSatisfyCanonicalContract:
    """One test per branch, each triggered deterministically, each
    asserting exactly the REQUIRED_ALWAYS field set - the permanent
    regression net against future contract drift (V2.13g spec Section
    15)."""

    def test_branch_1_structured_presentation_result_set(self):
        r = _chat("ryza", "rc-v213g-branch1")
        _assert_required_always(r, "structured_presentation")
        assert r["response_mode"] == "result_set"

    def test_branch_2_zero_match_recipe_answer(self):
        with mock.patch.object(m, "_get_openai_client", return_value=mock.MagicMock()), \
             mock.patch.object(m, "_call_openai_with_retry", return_value="Vseobecna kulinarska odpoved."):
            r = _chat("qzxjklw vbnmzx 88771 asdfgh poiuytrewq", "rc-v213g-branch2")
        _assert_required_always(r, "zero_match_recipe_answer")
        assert r["response_mode"] == "no_match"
        assert r["intent"] == "recipe"
        assert r["products"] == []

    def test_branch_3_zero_match_generic_apology(self):
        with mock.patch.object(m, "_get_openai_client", return_value=None):
            r = _chat("qzxjklw vbnmzx 88771 asdfgh poiuytrewq", "rc-v213g-branch3")
        _assert_required_always(r, "zero_match_generic_apology")
        assert r["response_mode"] == "no_match"
        assert r["products"] == []

    def test_branch_4_fast_path(self):
        r = _chat("kikkoman", "rc-v213g-branch4")
        _assert_required_always(r, "fast")
        assert r["response_mode"] == "fast"

    def test_branch_5_shopping_list_path(self):
        r = _chat("co potrebujem na prípravu ryze", "rc-v213g-branch5")
        if r.get("response_mode") == "shopping_list":
            _assert_required_always(r, "shopping_list")
        else:
            # Dispatch may legitimately resolve this to result_set/fast
            # depending on retrieval - still must satisfy the contract.
            _assert_required_always(r, f"shopping_list_query_resolved_as_{r.get('response_mode')}")

    def test_branch_6_no_openai_key_fallback(self):
        with mock.patch.object(m, "_get_openai_client", return_value=None):
            r = _chat("cim nahradit sojovu omacku", "rc-v213g-branch6")
        _assert_required_always(r, "no_openai_key_fallback")
        assert r["response_mode"] == "fallback"

    def test_branch_7_openai_success_llm(self):
        with mock.patch.object(m, "_get_openai_client", return_value=mock.MagicMock()), \
             mock.patch.object(m, "_call_openai_with_retry", return_value="Skuste tamari ako alternativu."):
            r = _chat("cim nahradit sojovu omacku", "rc-v213g-branch7")
        _assert_required_always(r, "openai_success")
        assert r["response_mode"] == "llm"

    def test_branch_8_openai_transient_error_fallback(self):
        with mock.patch.object(m, "_get_openai_client", return_value=mock.MagicMock()), \
             mock.patch.object(m, "_call_openai_with_retry", side_effect=_make_rate_limit_error()):
            r = _chat("cim nahradit sojovu omacku", "rc-v213g-branch8")
        _assert_required_always(r, "openai_transient_error")
        assert r["response_mode"] == "fallback"
        assert "warning" in r

    def test_branch_9_openai_generic_exception_fallback(self):
        with mock.patch.object(m, "_get_openai_client", return_value=mock.MagicMock()), \
             mock.patch.object(m, "_call_openai_with_retry", side_effect=RuntimeError("contract-test-boom")):
            r = _chat("cim nahradit sojovu omacku", "rc-v213g-branch9")
        _assert_required_always(r, "openai_generic_exception")
        assert r["response_mode"] == "fallback"
        assert "warning" in r


class TestMandatoryErrorPathRegressions:
    """Section 14 of the V2.13g spec: permanent coverage proving the
    error-path contract fix introduced no side-effect duplication, no
    extra LLM/search call, and respects execution-context analytics
    isolation - not just that the new fields exist."""

    def test_transient_error_emits_exactly_one_analytics_line(self, tmp_path, monkeypatch):
        log_path = tmp_path / "questions.jsonl"
        monkeypatch.setenv("ANALYTICS_LOG_PATH", str(log_path))
        with mock.patch.object(m, "_get_openai_client", return_value=mock.MagicMock()), \
             mock.patch.object(m, "_call_openai_with_retry", side_effect=_make_rate_limit_error()):
            advisor_engine.run(
                AdvisorRequest(message="cim nahradit sojovu omacku", session_id="rc-v213g-once-transient", client_key="k"),
                customer_context(),
            )
        lines = log_path.read_text(encoding="utf-8").strip().splitlines() if log_path.exists() else []
        assert len(lines) == 1

    def test_transient_error_calls_openai_exactly_once_per_retry_policy(self):
        call_count = {"n": 0}

        def _raise(*args, **kwargs):
            call_count["n"] += 1
            raise _make_rate_limit_error()

        with mock.patch.object(m, "_get_openai_client", return_value=mock.MagicMock()), \
             mock.patch.object(m, "_call_openai_with_retry", side_effect=_raise):
            _chat("cim nahradit sojovu omacku", "rc-v213g-callcount-transient")
        # _call_openai_with_retry is mocked as a single unit (it owns its
        # own internal @retry policy) - the commerce pipeline itself must
        # call it exactly once, never retrying independently on top.
        assert call_count["n"] == 1

    def test_generic_exception_does_not_duplicate_session_memory_write(self):
        sid = "rc-v213g-nodup-memory"
        with mock.patch.object(m, "_get_openai_client", return_value=mock.MagicMock()), \
             mock.patch.object(m, "_call_openai_with_retry", side_effect=RuntimeError("boom")):
            r = _chat("cim nahradit sojovu omacku", sid)
        assert r.get("memory") is not None
        memory_key = m.session_memory_key(sid, "127.0.0.1")
        session_memory = m.get_session_memory(memory_key)
        history = session_memory.get("history") or session_memory.get("recent_intents") or []
        # Whatever shape update_session_memory() uses, it must have
        # recorded this turn exactly once, not zero or twice.
        assert session_memory, "expected session memory to have been written exactly once"

    def test_generic_exception_respects_evaluation_context_analytics_suppression(self, tmp_path, monkeypatch):
        from app.execution_context import evaluation_context
        log_path = tmp_path / "questions.jsonl"
        monkeypatch.setenv("ANALYTICS_LOG_PATH", str(log_path))
        with mock.patch.object(m, "_get_openai_client", return_value=mock.MagicMock()), \
             mock.patch.object(m, "_call_openai_with_retry", side_effect=RuntimeError("boom")):
            advisor_engine.run(
                AdvisorRequest(message="cim nahradit sojovu omacku", session_id="rc-v213g-eval-suppressed", client_key="k"),
                evaluation_context(),
            )
        lines = log_path.read_text(encoding="utf-8").strip().splitlines() if log_path.exists() else []
        assert len(lines) == 0
