"""
tests/test_signal_correlation_v2_15b.py  -  V2.15b: recommendation signal
persistence, correlation & normalization closure.

Closes the observability gaps V2.15a found, within the sprint's hard
safety boundary: no learning, no ranking mutation, no AUTO_PROMOTION
change, no customer-facing recommendation/retrieval behavior change.

What this sprint actually implements (see
docs/recommendation-signal-correlation-v2.15b.md for the full audit):

1. interaction_id - an opaque id generated once per /chat request
   (app.main._chat_internal(), the single choke point every response
   passes through regardless of which internal branch produced it),
   threaded into log_question() and SearchQualityTrace, and returned in
   the response. Lets an offline analyst join question_analytics.jsonl
   and search_quality.jsonl for the same request without timestamp
   guessing (V2.15a's Section 6 finding).

2. decision_id (comparison/use_case_advice/basket_completion) - a fresh
   opaque id per resolved recommendation decision, returned in the
   response. Generated and returned only - NOT yet durably logged
   alongside its evidence (an honestly-scoped remaining gap, not
   claimed as closed).

3. An authorized-only HTTP mechanism (X-Execution-Context: ADMIN_TEST +
   a valid OPERATIONS/PROMOTION-scope X-Admin-Token) letting live
   production verification traffic declare itself non-customer, fail-
   closed for anyone else - see tests/test_execution_context.py::
   TestChatHttpAdminTestOverride for the dedicated test class.

4. Durable storage path normalization (search_quality.jsonl and the 3
   independent EVENTS_LOG_PATH readers) through the single
   FOODLAND_DATA_DIR knob, closing the V2.15a-documented silent-drift
   risk.

This file covers 1 and 2; the byte-safe main.py execution-context header
tests live in test_execution_context.py; the storage-path tests live in
test_storage_paths_v2_15b.py.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m
import app.search_quality as sq
from app.execution_context import customer_context


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, limit: int = 8) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


def _chat_as_customer(message: str, session_id: str, limit: int = 8) -> dict:
    # m.chat()'s isinstance(request, Request) fallback resolves a
    # duck-typed _FakeRequest to EVALUATION (correctly suppressing
    # analytics) - tests that need to observe a REAL customer-analytics
    # write must go through _chat_internal() with an explicit
    # customer_context(), same pattern as test_execution_context.py.
    return m._chat_internal(
        m.ChatRequest(message=message, session_id=session_id, limit=limit),
        _FakeRequest(),
        execution_context=customer_context(),
    )


class TestInteractionId:
    def test_present_on_ordinary_product_search(self):
        r = _chat("jazminova ryza", "corr-interaction-search")
        interaction_id = r.get("interaction_id")
        assert interaction_id and isinstance(interaction_id, str)

    def test_distinct_per_request(self):
        r1 = _chat("jazminova ryza", "corr-interaction-distinct-1")
        r2 = _chat("jazminova ryza", "corr-interaction-distinct-2")
        assert r1.get("interaction_id") != r2.get("interaction_id")

    def test_present_across_capabilities(self):
        # A single choke point (_chat_internal) injects this - it must
        # not depend on which internal branch produced the response.
        for message, session_id in (
            ("jazminova ryza", "corr-cap-search"),
            ("porovnaj Samyang Buldak a Nissin Demae Ramen", "corr-cap-comparison"),
            ("ryza na sushi", "corr-cap-usecase"),
            ("co potrebujem na pho", "corr-cap-basket"),
            ("sojova omacka bez soje", "corr-cap-allergen"),
        ):
            r = _chat(message, session_id)
            assert r.get("interaction_id"), f"missing interaction_id for {message!r} (intent={r.get('intent')!r})"

    def test_reaches_question_analytics_log(self, tmp_path, monkeypatch):
        analytics_path = tmp_path / "question_analytics.jsonl"
        monkeypatch.setenv("ANALYTICS_LOG_PATH", str(analytics_path))
        r = _chat_as_customer("jazminova ryza", "corr-interaction-log")
        import json
        lines = [json.loads(line) for line in analytics_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) >= 1
        assert lines[-1]["interaction_id"] == r.get("interaction_id")

    def test_reaches_search_quality_trace(self, tmp_path, monkeypatch):
        # SEARCH_QUALITY_LOG_PATH is a module-level constant resolved once
        # at import time (app.search_quality:SEARCH_QUALITY_LOG_PATH) -
        # monkeypatch.setenv() after import has no effect on it, same
        # pattern already established in tests/test_search_quality.py.
        trace_path = tmp_path / "search_quality.jsonl"
        monkeypatch.setattr(sq, "SEARCH_QUALITY_LOG_PATH", str(trace_path))
        r = _chat_as_customer("jazminova ryza", "corr-interaction-quality")
        import json
        lines = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) >= 1
        assert lines[-1]["interaction_id"] == r.get("interaction_id")


class TestDecisionId:
    def test_comparison_decision_id_present_and_distinct(self):
        r1 = _chat("porovnaj Samyang Buldak a Nissin Demae Ramen", "corr-decision-cmp-1")
        r2 = _chat("porovnaj Samyang Buldak a Nissin Demae Ramen", "corr-decision-cmp-2")
        assert r1.get("comparison_decision_id")
        assert r2.get("comparison_decision_id")
        assert r1["comparison_decision_id"] != r2["comparison_decision_id"]

    def test_use_case_advice_decision_id_present(self):
        r = _chat("ryza na sushi", "corr-decision-usecase")
        assert r.get("use_case_advice_decision_id")

    def test_basket_decision_id_present(self):
        r = _chat("co potrebujem na pho", "corr-decision-basket")
        assert r.get("basket_decision_id")

    def test_decision_id_distinct_from_interaction_id(self):
        r = _chat("ryza na sushi", "corr-decision-vs-interaction")
        assert r.get("use_case_advice_decision_id") != r.get("interaction_id")

    def test_plain_product_search_has_no_decision_id(self):
        # decision_id is scoped to capabilities with a real recommendation
        # decision concept - a plain product-search result must not be
        # mislabeled with a fabricated decision id (Section 9 invariant).
        r = _chat("jazminova ryza", "corr-decision-none")
        assert "comparison_decision_id" not in r
        assert "use_case_advice_decision_id" not in r
        assert "basket_decision_id" not in r
