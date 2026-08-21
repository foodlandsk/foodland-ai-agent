"""
tests/test_workflow_executor_v2_13d.py  -  V2.13d: migrates six more
fully self-contained, immediate-return branches into
app.workflow_executor (missing_composition, FAQ, random_recipe, reset,
out_of_domain, category_discovery) - verbatim code motion, same pattern
V2.13c already proved for RESULTSET_CONTINUATION/ALLERGEN_SAFETY. None
of these are distinct app.workflow_resolver outputs (WorkflowResolver
only distinguishes 4 values); they are internal LEGACY_FALLBACK
sub-cases, dispatched by app.main._chat_impl() exactly as before -
V2.13d moves execution only, invents no new resolver granularity.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m
from app.workflow_executor import (
    execute_category_discovery,
    execute_faq,
    execute_missing_composition,
    execute_out_of_domain,
    execute_random_recipe,
    execute_reset,
)


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, limit: int = 8) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


class TestMissingCompositionIntegration:
    def test_trigger_phrase_resolves_to_missing_composition(self):
        r = _chat("chyba zlozenie na stranke", "wf13d-mc")
        assert r.get("intent") == "missing_composition"
        assert r.get("products") == []
        assert r.get("answered") is True

    def test_handler_unit(self):
        chat_request = m.ChatRequest(message="chyba zlozenie", limit=6, session_id="wf13d-mc-unit")
        result = execute_missing_composition(
            chat_request=chat_request,
            memory_key=m.session_memory_key("wf13d-mc-unit", "127.0.0.1"),
            profile_key=m.user_memory_key("", "127.0.0.1"),
            articles=[],
            knowledge_matches={},
            client_key="127.0.0.1",
            session_id="wf13d-mc-unit",
            query_language="sk",
            emit_customer_analytics=True,
        )
        assert result["intent"] == "missing_composition"
        assert result["products"] == []


class TestFaqIntegration:
    def test_faq_query_resolves_to_faq(self):
        r = _chat("ako mozem zaplatit?", "wf13d-faq")
        assert r.get("intent") == "faq"
        assert r.get("products") == []
        assert r.get("answer")

    def test_handler_unit(self):
        chat_request = m.ChatRequest(message="ako mozem zaplatit?", limit=6, session_id="wf13d-faq-unit")
        result = execute_faq(
            chat_request=chat_request,
            memory_key=m.session_memory_key("wf13d-faq-unit", "127.0.0.1"),
            profile_key=m.user_memory_key("", "127.0.0.1"),
            articles=[],
            knowledge_matches={},
            client_key="127.0.0.1",
            session_id="wf13d-faq-unit",
            query_language="sk",
            faq_answer="test answer",
            emit_customer_analytics=True,
        )
        assert result["intent"] == "faq"
        assert result["answer"] == "test answer"


class TestRandomRecipeIntegration:
    def test_random_recipe_query_returns_recipes(self):
        r = _chat("daj mi nahodny recept", "wf13d-rr")
        assert r.get("intent") == "recipe"
        assert len(r.get("recipes") or []) > 0
        assert r.get("products") == []

    def test_handler_unit(self):
        chat_request = m.ChatRequest(message="daj mi nahodny recept", limit=6, session_id="wf13d-rr-unit")
        result = execute_random_recipe(
            chat_request=chat_request,
            memory_key=m.session_memory_key("wf13d-rr-unit", "127.0.0.1"),
            profile_key=m.user_memory_key("", "127.0.0.1"),
            user_profile={},
            knowledge=m.knowledge,
            articles=[],
            knowledge_matches={},
            client_key="127.0.0.1",
            session_id="wf13d-rr-unit",
            query_language="sk",
            emit_customer_analytics=True,
        )
        assert result["intent"] == "recipe"
        assert len(result["recipes"]) > 0


class TestResetIntegration:
    def test_reset_clears_prior_context_exactly_once(self):
        sid = "wf13d-reset"
        _chat("chcem robiť sushi", sid)
        key = m.session_memory_key(sid, "127.0.0.1")
        memory_before = m.get_session_memory(key)
        assert memory_before["subjects"]

        r = _chat("zacnime odznova", sid)
        assert r.get("intent") == "reset"

        memory_after = m.get_session_memory(key)
        assert not memory_after["subjects"]
        assert memory_after.get("active_result_set_id", "") == ""

    def test_handler_unit(self):
        m.session_memories.clear()
        key = m.session_memory_key("wf13d-reset-unit", "127.0.0.1")
        memory = m.get_session_memory(key)
        m.update_session_memory(key, "chcem robiť sushi", "product_search", [], [], {})
        assert memory["subjects"]

        chat_request = m.ChatRequest(message="zacnime odznova", limit=6, session_id="wf13d-reset-unit")
        result = execute_reset(
            chat_request=chat_request,
            memory=memory,
            profile_key=m.user_memory_key("", "127.0.0.1"),
            client_key="127.0.0.1",
            session_id="wf13d-reset-unit",
            query_language="sk",
            emit_customer_analytics=True,
        )
        assert result["intent"] == "reset"
        assert not memory["subjects"]


class TestOutOfDomainIntegration:
    def test_out_of_domain_query(self):
        r = _chat("aky je najlepsi film?", "wf13d-ood")
        assert r.get("intent") == "unknown"
        assert r.get("products") == []

    def test_handler_unit(self):
        chat_request = m.ChatRequest(message="aky je najlepsi film?", limit=6, session_id="wf13d-ood-unit")
        result = execute_out_of_domain(
            chat_request=chat_request,
            memory_key=m.session_memory_key("wf13d-ood-unit", "127.0.0.1"),
            profile_key=m.user_memory_key("", "127.0.0.1"),
            knowledge_matches={},
            client_key="127.0.0.1",
            session_id="wf13d-ood-unit",
            query_language="sk",
            emit_customer_analytics=True,
        )
        assert result["intent"] == "unknown"


class TestCategoryDiscoveryIntegration:
    def test_category_discovery_query(self):
        r = _chat("aku kategoriu produktov mate?", "wf13d-cd")
        assert r.get("intent") == "category_discovery"
        assert r.get("products") == []
        assert r.get("answer")

    def test_handler_unit(self):
        chat_request = m.ChatRequest(message="aku kategoriu produktov mate?", limit=6, session_id="wf13d-cd-unit")
        result = execute_category_discovery(
            chat_request=chat_request,
            memory_key=m.session_memory_key("wf13d-cd-unit", "127.0.0.1"),
            profile_key=m.user_memory_key("", "127.0.0.1"),
            products=m.products,
            knowledge_matches={},
            client_key="127.0.0.1",
            session_id="wf13d-cd-unit",
            query_language="sk",
            emit_customer_analytics=True,
        )
        assert result["intent"] == "category_discovery"


class TestRegressionLocksAfterGroupAMigration:
    """rt0004/rt0010/rt0011 must remain fixed after Group A's executor
    migration - none of these six branches touch the safety/action-
    target resolution path, but this is the permanent regression
    tripwire per this session's established discipline."""

    def test_rt0004_still_related_products(self):
        r = _chat("súvisiace produkty k sushi ryži", "wf13d-lock-rt0004")
        assert r.get("intent") == "related_products"
        assert r.get("products")

    def test_rt0010_still_allergen_safety(self):
        r = _chat("sójová omáčka bez sóje", "wf13d-lock-rt0010")
        assert r.get("intent") == "allergen_safety"
        assert r.get("products") == []

    def test_rt0011_session_collision_still_fixed(self):
        sid = "wf13d-lock-rt0011"
        r1 = _chat("mám rád nepálivé jedlo, čo odporúčaš?", sid)
        r2 = _chat("mám rád nepálivé jedlo, čo odporúčaš?", sid)
        assert r1.get("intent") == "product_search"
        assert r2.get("intent") == "product_search"

    def test_show_more_still_works(self):
        sid = "wf13d-lock-showmore"
        first = _chat("basmati ryza", sid, limit=3)
        assert first.get("has_more") is True or first.get("matching_total", 0) > 3
        second = _chat("zobraz viac", sid)
        assert second.get("response_mode") == "result_set_continuation"
