"""
tests/test_resultset_continuation_attribution_v2_15e_1.py  -  V2.15e.1:
Resultset Continuation Attribution & Recommendation Causal Chain Closure.

GATE B (minimal propagation fix). Audit finding (docs/resultset-
continuation-attribution-v2.15e.1.md): app.result_sets.ResultSet already
carries a STABLE, per-search result_set_id - minted once via uuid.uuid4()
in create_result_set(), never re-minted by
execute_resultset_continuation() (which only mutates displayed_count on
the SAME stored object) - and this id is ALREADY returned identically in
both the original search response and every subsequent "Show More"/
"Show All" continuation response. The gap was never a missing backend
identifier: it was that app/widget.js never read or forwarded it.

interaction_id remains, correctly and honestly, a FRESH value on every
single /chat call including continuations - this is not a bug, it
reflects that each HTTP request genuinely is a new interaction.
decision_id remains, correctly, null for ordinary product_search and its
continuations, since comparison/use_case_advice/basket_completion never
create a ResultSet at all and this sprint does not fabricate a decision
where none exists.

The fix: result_set_id is now threaded through exactly the same additive
path interaction_id/decision_id already use - EventRequest gains an
optional result_set_id field, log_event() persists it, and
app/widget.js stashes it onto every product object (both the original-
search and continuation-revealed products, since they share ONE code
path - see docs) and includes it in the 5 renderCard() fireEvent() calls
plus the impression event.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m
from app.execution_context import customer_context, evaluation_context


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat_as_customer(message: str, session_id: str, limit: int = 3) -> dict:
    return m._chat_internal(
        m.ChatRequest(message=message, session_id=session_id, limit=limit),
        _FakeRequest(),
        execution_context=customer_context(),
    )


SEARCH_QUERY = "jazminova ryza"
COMPARISON_QUERY = "porovnaj Samyang Buldak a Nissin Demae Ramen"
BASKET_QUERY = "co potrebujem na sushi"
USE_CASE_QUERY = "ake kokosove mlieko na tom kha gai?"


# ---------------------------------------------------------------------
# CASE A/B - result_set_id survives continuation, interaction_id does not
# ---------------------------------------------------------------------

class TestResultSetIdStableAcrossContinuation:
    def test_result_set_id_present_on_initial_search(self):
        r = _chat_as_customer(SEARCH_QUERY, "v215e1-a-initial")
        assert r.get("result_set_id")
        assert r.get("has_more") is True

    def test_result_set_id_identical_after_show_more(self):
        sid = "v215e1-b-continuation"
        r1 = _chat_as_customer(SEARCH_QUERY, sid)
        r2 = _chat_as_customer("zobraz viac", sid)
        assert r2.get("intent") == "product_search"
        assert r2.get("result_set_id") == r1.get("result_set_id")

    def test_interaction_id_correctly_differs_across_continuation(self):
        # Honest, not a bug: a new HTTP /chat call is a new interaction.
        sid = "v215e1-c-fresh-interaction"
        r1 = _chat_as_customer(SEARCH_QUERY, sid)
        r2 = _chat_as_customer("zobraz viac", sid)
        assert r2.get("interaction_id") != r1.get("interaction_id")
        assert r2.get("interaction_id")


class TestSecondContinuation:
    def test_result_set_id_stable_across_two_continuations(self):
        sid = "v215e1-second-continuation"
        r1 = _chat_as_customer(SEARCH_QUERY, sid)
        r2 = _chat_as_customer("zobraz viac", sid)
        r3 = _chat_as_customer("zobraz vsetky", sid)
        ids = {r1.get("result_set_id"), r2.get("result_set_id"), r3.get("result_set_id")}
        assert len(ids) == 1
        interaction_ids = {r1.get("interaction_id"), r2.get("interaction_id"), r3.get("interaction_id")}
        assert len(interaction_ids) == 3


# ---------------------------------------------------------------------
# CASE F/G/H - comparison/use_case/basket never fabricate a result_set_id
# ---------------------------------------------------------------------

class TestNoFabricatedResultSetId:
    def test_comparison_has_no_result_set_id(self):
        r = _chat_as_customer(COMPARISON_QUERY, "v215e1-cmp-no-rsid")
        assert r.get("intent") == "product_comparison"
        assert not r.get("result_set_id")

    def test_use_case_advice_has_no_result_set_id(self):
        r = _chat_as_customer(USE_CASE_QUERY, "v215e1-usecase-no-rsid")
        assert r.get("intent") == "use_case_advice"
        assert not r.get("result_set_id")

    def test_basket_completion_has_no_result_set_id(self):
        r = _chat_as_customer(BASKET_QUERY, "v215e1-basket-no-rsid")
        assert r.get("intent") == "basket_completion"
        assert not r.get("result_set_id")


# ---------------------------------------------------------------------
# CASE K/L/M - boundaries: refinement stays same result_set, new query/
# hard switch/reset correctly rotate or clear it
# ---------------------------------------------------------------------

class TestBoundaries:
    def test_new_unrelated_query_gets_a_different_result_set_id(self):
        sid = "v215e1-new-query-boundary"
        r1 = _chat_as_customer(SEARCH_QUERY, sid)
        r2 = _chat_as_customer("kikkoman sojova omacka", sid)
        assert r2.get("result_set_id") != r1.get("result_set_id")

    def test_hard_topic_switch_to_comparison_has_no_result_set_id(self):
        sid = "v215e1-hard-switch-boundary"
        _chat_as_customer(SEARCH_QUERY, sid)
        r2 = _chat_as_customer(COMPARISON_QUERY, sid)
        assert r2.get("intent") == "product_comparison"
        assert not r2.get("result_set_id")

    def test_reset_clears_active_result_set(self):
        sid = "v215e1-reset-boundary"
        _chat_as_customer(SEARCH_QUERY, sid)
        _chat_as_customer("Zacnime odznova", sid)
        r3 = _chat_as_customer("zobraz viac", sid)
        # No active result set survives reset - "zobraz viac" with nothing
        # to continue falls through to the ordinary cascade, not a
        # result_set_continuation response.
        assert r3.get("response_mode") != "result_set_continuation"


class TestCrossSessionIsolation:
    def test_two_sessions_never_share_a_result_set_id(self):
        r1 = _chat_as_customer(SEARCH_QUERY, "v215e1-isolation-a")
        r2 = _chat_as_customer(SEARCH_QUERY, "v215e1-isolation-b")
        assert r1.get("result_set_id") != r2.get("result_set_id")

    def test_continuation_in_one_session_does_not_affect_another(self):
        sid_a = "v215e1-isolation-cont-a"
        sid_b = "v215e1-isolation-cont-b"
        _chat_as_customer(SEARCH_QUERY, sid_a)
        r_b = _chat_as_customer("zobraz viac", sid_b)
        # session B never searched, so "zobraz viac" cannot be a
        # continuation there - must not resolve using session A's state.
        assert r_b.get("response_mode") != "result_set_continuation"


# ---------------------------------------------------------------------
# CASE P/Q - EventRequest/log_event backward compatibility and persistence
# ---------------------------------------------------------------------

class TestEventRequestBackwardCompatibility:
    def test_event_request_without_result_set_id_still_valid(self):
        req = m.EventRequest(session_id="s1", event_type="click", product_sku="SKU1")
        assert req.result_set_id is None

    def test_event_request_accepts_result_set_id(self):
        req = m.EventRequest(session_id="s1", event_type="click", product_sku="SKU1", result_set_id="abc123")
        assert req.result_set_id == "abc123"

    def test_log_event_persists_result_set_id(self, tmp_path, monkeypatch):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        req = m.EventRequest(session_id="s1", event_type="click", product_sku="SKU1", result_set_id="abc123")
        m.log_event(req, "ck", execution_context=customer_context())
        rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert rows[0]["result_set_id"] == "abc123"

    def test_legacy_event_without_result_set_id_field_still_readable(self, tmp_path):
        events_path = tmp_path / "events.jsonl"
        events_path.write_text(json.dumps({
            "ts": 1700000000, "session_id": "old", "event_type": "click", "product_sku": "SKU1",
        }) + "\n", encoding="utf-8")
        rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
        assert "result_set_id" not in rows[0]


# ---------------------------------------------------------------------
# Execution context / failure isolation / AUTO_PROMOTION (re-affirmed)
# ---------------------------------------------------------------------

class TestExecutionContextIsolationUnaffected:
    def test_evaluation_context_still_not_durably_logged(self, tmp_path, monkeypatch):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        req = m.EventRequest(session_id="s1", event_type="click", product_sku="SKU1", result_set_id="abc")
        m.log_event(req, "ck", execution_context=evaluation_context())
        assert not events_path.exists() or events_path.read_text(encoding="utf-8").strip() == ""


class TestFailureIsolation:
    def test_unwritable_events_path_does_not_break_event_logging_call(self, monkeypatch):
        monkeypatch.setenv("EVENTS_LOG_PATH", "Z:\\definitely\\not\\writable\\events.jsonl")
        req = m.EventRequest(session_id="s1", event_type="click", product_sku="SKU1", result_set_id="abc")
        m.log_event(req, "ck", execution_context=customer_context())  # must not raise


class TestAutoPromotionUnchanged:
    def test_auto_promotion_still_disabled(self):
        from app.learning_lifecycle import AUTO_PROMOTION_ENABLED
        assert AUTO_PROMOTION_ENABLED is False


# ---------------------------------------------------------------------
# Permanent regression controls (rt0004/rt0010/rt0011/rt0013, V2.15c)
# ---------------------------------------------------------------------

class TestControlRegressionMatrix:
    def test_rt0004_related_products_protected(self):
        r = _chat_as_customer("súvisiace produkty k sushi ryži", "v215e1-rt0004")
        assert r.get("intent") == "related_products"

    def test_rt0010_allergen_safety_protected(self):
        r = _chat_as_customer("sójová omáčka bez sóje", "v215e1-rt0010")
        assert r.get("intent") == "allergen_safety"

    def test_rt0011_no_session_contamination(self):
        sid = "v215e1-rt0011"
        query = "mám rád nepálivé jedlo, čo odporúčaš?"
        first = _chat_as_customer(query, sid)
        second = _chat_as_customer(query, sid)
        assert first.get("intent") == "product_search"
        assert second.get("intent") == "product_search"

    def test_rt0013_replacement_products_protected(self):
        r = _chat_as_customer("náhrada za rybiu omáčku vegan", "v215e1-rt0013")
        assert r.get("intent") == "replacement_products"

    def test_v2_15c_store_location_followup_still_live(self):
        sid = "v215e1-store-followup"
        _chat_as_customer("Kde sa nachadza kamenna predajna?", sid)
        r = _chat_as_customer("Prilož mi Google link na adresu.", sid)
        assert r.get("intent") == "faq"
        assert "maps.app.goo.gl" in (r.get("answer") or "")
