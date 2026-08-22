"""
tests/test_commerce_pipeline_v2_13f_a.py  -  V2.13f-A: characterization
of the shared commerce matches-dispatch pipeline (app.main._chat_impl(),
already_have_subject computation through the final OpenAI-call return
sites) BEFORE any extraction decision. Written against the CURRENT
(unmodified) implementation - every assertion here captures actually
observed behavior via real chat()/AdvisorEngine calls against the real
product catalog, not assumed from reading the code.

Per docs/commerce-pipeline-v2.13f-a.md, V2.13f-A was CHARACTERIZATION
ONLY (no extraction, no refactor) - these tests originally existed to
(a) prove the control/data-flow claims in that document with direct
evidence and (b) freeze current behavior, including two response-shape
inconsistencies (missing "memory"/"intent" on 2 error branches, missing
"response_mode" on 4 of 8 branches) these tests deliberately surfaced
rather than silently working around.

V2.13g (docs/response-contract-v2.13g.md) FIXED those two
inconsistencies with the smallest safe change (reusing already-computed
locals, no re-routing, no new LLM/search calls, no side-effect
reordering) and updated TestTerminalReturnShapeConsistency (formerly
TestTerminalReturnShapeInconsistency) below to assert the corrected
contract instead of freezing the old defect - see that class's
docstring for exactly what changed and why.

These tests must keep passing unmodified regardless of what a later
sprint (V2.13f-B, if ever authorized) does to the commerce pipeline's
INTERNAL structure - that identity is the regression net for any
future extraction attempt. V2.13f-B remains STOPPED_BY_GO_STOP_DECISION
(docs/commerce-pipeline-v2.13f-a.md) - V2.13g only hardened the public
response contract, it did not reopen the extraction question.
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
from openai import APIConnectionError, APITimeoutError, RateLimitError


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, limit: int = 8) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


def _make_openai_error(error_cls, message: str = "characterization-test"):
    if error_cls is RateLimitError:
        return RateLimitError(message, response=mock.MagicMock(status_code=429, headers={}), body=None)
    if error_cls is APIConnectionError:
        return APIConnectionError(message=message, request=mock.MagicMock())
    if error_cls is APITimeoutError:
        return APITimeoutError(request=mock.MagicMock())
    return error_cls(message)


class TestStructuredPresentationBranchShape:
    """The `else:` dispatch arm (no special/related/replacement/article/
    already_have/cross_sell subject detected) builds a structured
    ResultSet and returns via the `structured_presentation is not None`
    branch (app/main.py L4848-4921) - the ONLY branch that computes and
    returns cross_sell_*/workflow_id/workflow_confidence/pagination
    fields. No other terminal branch in this pipeline sets any of
    these keys at all (absent, not null)."""

    def test_plain_product_search_returns_result_set_shape(self):
        r = _chat("ryza", "cpv213fa-structured-1")
        assert r.get("response_mode") == "result_set"
        for key in (
            "matching_total", "displayed_count", "has_more", "result_set_id",
            "answer_strategy", "groups", "cross_sell", "cross_sell_eligible",
            "cross_sell_context_type", "cross_sell_intro", "workflow_id",
            "workflow_confidence",
        ):
            assert key in r, f"expected {key!r} present on result_set response"

    def test_non_structured_branch_omits_result_set_only_fields(self):
        r = _chat("mam doma sojovu omacku", "cpv213fa-already-have-1")
        assert r.get("response_mode") != "result_set"
        for key in ("matching_total", "displayed_count", "has_more", "result_set_id", "cross_sell_context_type"):
            assert key not in r, f"unexpected {key!r} present on non-result_set response"


class TestTerminalReturnShapeConsistency:
    """V2.13g FIX (docs/response-contract-v2.13g.md): this class used to
    be TestTerminalReturnShapeInconsistency and froze 2 real defects
    found by V2.13f-A characterization - the RateLimitError/
    APITimeoutError/APIConnectionError branch (L5066-5082) and the
    generic Exception branch (L5083-5099) omitted "memory"/"intent",
    and 4 of 8 terminal branches omitted "response_mode" entirely.
    V2.13g closed both gaps with the smallest possible change: each
    fixed branch now reads the SAME already-computed `intent`/
    `updated_profile` locals every other branch already reads (no new
    computation, no re-routing, no new LLM/search call - see
    docs/response-contract-v2.13g.md Section "IMPLEMENTATION") and
    reports one of 3 canonical response_mode values ("llm" for the
    OpenAI-composed answer, "fallback" for the 3 non-LLM-composed
    answer branches, "no_match" for the 2 zero-result branches) chosen
    to reuse the existing "result_set"/"fast"/"shopping_list"
    vocabulary's spirit rather than inventing a large new enum.
    These assertions now lock the CORRECTED contract as the permanent
    regression net - a future change that re-breaks this must fail
    these tests, not silently ship."""

    def test_openai_success_branch_has_full_contract(self):
        with mock.patch.object(m, "_get_openai_client", return_value=mock.MagicMock()), \
             mock.patch.object(m, "_call_openai_with_retry", return_value="Skuste namiesto toho tamari."):
            r = _chat("cim nahradit sojovu omacku", "cpv213fa-repl-success")
        assert "memory" in r
        assert "intent" in r
        assert r.get("intent") == "replacement_products"
        assert r.get("response_mode") == "llm"

    def test_rate_limit_exhausted_branch_has_full_contract(self):
        err = _make_openai_error(RateLimitError)
        with mock.patch.object(m, "_get_openai_client", return_value=mock.MagicMock()), \
             mock.patch.object(m, "_call_openai_with_retry", side_effect=err):
            r = _chat("cim nahradit sojovu omacku", "cpv213fa-repl-ratelimit")
        assert "warning" in r
        assert r.get("intent") == "replacement_products"
        assert "memory" in r
        assert r.get("response_mode") == "fallback"
        assert r.get("products")

    def test_generic_exception_branch_has_full_contract(self):
        with mock.patch.object(m, "_get_openai_client", return_value=mock.MagicMock()), \
             mock.patch.object(m, "_call_openai_with_retry", side_effect=RuntimeError("boom")):
            r = _chat("cim nahradit sojovu omacku", "cpv213fa-repl-exc")
        assert "warning" in r
        assert r.get("intent") == "replacement_products"
        assert "memory" in r
        assert r.get("response_mode") == "fallback"
        assert r.get("products")

    def test_no_openai_key_fallback_has_response_mode(self):
        with mock.patch.object(m, "_get_openai_client", return_value=None):
            r = _chat("cim nahradit sojovu omacku", "cpv213fa-repl-nokey")
        assert "memory" in r
        assert "intent" in r
        assert r.get("response_mode") == "fallback"


class TestSideEffectsFireExactlyOnceAcrossAllTerminalBranches:
    """update_session_memory/update_user_memory/log_question
    (app/main.py L4839-4846) run ONCE, unconditionally, BEFORE the
    5-way terminal-branch fan-out that decides which dict shape is
    returned - so every branch, including the two exception branches
    above, must show exactly one analytics line per turn. This is the
    commerce-pipeline-specific instance of the same exactly-once
    guarantee TestExactlyOnceSideEffects (tests/test_advisor_engine.py)
    already locks for the AdvisorEngine boundary in general."""

    def test_exactly_one_analytics_line_on_plain_product_search(self, tmp_path, monkeypatch):
        # Section-4199 note: _chat_impl() locally rebinds log_question to
        # a no-op unless execution_context.emit_customer_analytics - a
        # duck-typed _FakeRequest resolves to _evaluation_context() (not
        # customer), which intentionally suppresses this. Go through
        # AdvisorEngine directly with an explicit customer_context() to
        # exercise the real, analytics-emitting path (same technique
        # TestExactlyOnceSideEffects in tests/test_advisor_engine.py uses).
        log_path = tmp_path / "questions.jsonl"
        monkeypatch.setenv("ANALYTICS_LOG_PATH", str(log_path))
        advisor_engine.run(AdvisorRequest(message="ryza", session_id="cpv213fa-once-search", client_key="k"), customer_context())
        lines = log_path.read_text(encoding="utf-8").strip().splitlines() if log_path.exists() else []
        assert len(lines) == 1

    def test_exactly_one_analytics_line_when_openai_raises(self, tmp_path, monkeypatch):
        log_path = tmp_path / "questions.jsonl"
        monkeypatch.setenv("ANALYTICS_LOG_PATH", str(log_path))
        err = _make_openai_error(APIConnectionError)
        with mock.patch.object(m, "_get_openai_client", return_value=mock.MagicMock()), \
             mock.patch.object(m, "_call_openai_with_retry", side_effect=err):
            advisor_engine.run(AdvisorRequest(message="cim nahradit sojovu omacku", session_id="cpv213fa-once-error", client_key="k"), customer_context())
        lines = log_path.read_text(encoding="utf-8").strip().splitlines() if log_path.exists() else []
        assert len(lines) == 1


class TestDispatchBranchesProduceDistinctSubjects:
    """Direct evidence that the ~9-way elif chain (app/main.py
    L4655-4760) genuinely dispatches distinct queries to distinct
    matches-producing functions - not a claim from reading code alone.
    Precedence ORDER between these subjects (rt0004/rt0010: special_subject
    vs related_subject, action-target override) is already covered by
    existing regression tests (docs/routing-debt.md, FIXED_V2_13B) and
    is intentionally not re-asserted here to avoid duplicate coverage."""

    def test_already_have_subject_dispatches_to_complement(self):
        r = _chat("mam doma sojovu omacku", "cpv213fa-dispatch-alreadyhave")
        assert r.get("products")

    def test_replacement_subject_dispatches_to_alternatives(self):
        with mock.patch.object(m, "_get_openai_client", return_value=None):
            r = _chat("cim nahradit sojovu omacku", "cpv213fa-dispatch-replacement")
        assert r.get("intent") == "replacement_products"
        assert r.get("products")

    def test_cross_sell_dispatches_when_no_other_subject_matches(self):
        r = _chat("co sa hodi k sojovej omacke", "cpv213fa-dispatch-crosssell")
        assert r.get("products")


class TestFastAndShoppingListBranchesIncludeMemoryAndIntent:
    """Control group for TestTerminalReturnShapeConsistency: the "fast"
    (response_mode="fast") and "shopping_list"
    (response_mode="shopping_list") terminal branches always included
    "memory" and "intent", even before the V2.13g fix - only the 2
    OpenAI-exception branches and (as of V2.13g's canonical contract,
    docs/response-contract-v2.13g.md) the response_mode field on 4
    other branches needed correcting."""

    def test_fast_path_shape(self):
        r = _chat("kikkoman", "cpv213fa-fast-shape")
        assert r.get("response_mode") == "fast"
        assert "memory" in r
        assert "intent" in r

    def test_shopping_list_path_shape(self):
        # V2.14e (docs/basket-completion-v2.14e.md): "co potrebujem na
        # sushi" is now intentionally answered by the new, richer
        # role-based basket_completion path instead of falling through
        # to a generic result_set/fast response - "basket_completion" is
        # a deliberate, new, additional response_mode value (same
        # precedent as V2.13g adding "llm"/"fallback"/"no_match").
        r = _chat("co potrebujem na sushi", "cpv213fa-shoppinglist-shape")
        if r.get("response_mode") in {"shopping_list", "basket_completion"}:
            assert "memory" in r
            assert "intent" in r
        else:
            assert r.get("response_mode") in {"result_set", "fast"}
