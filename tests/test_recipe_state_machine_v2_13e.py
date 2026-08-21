"""
tests/test_recipe_state_machine_v2_13e.py  -  V2.13e: characterization
of the recipe state machine's terminal execution blocks (D: main
recipe_subject block, E: recipe_followup_result handling) BEFORE
extraction into app.workflow_executor. Written against the CURRENT
(pre-extraction) inline implementation in app.main._chat_impl() -
every assertion here captures actually-observed behavior, verified
directly via chat() calls, not assumed. Per docs/recipe-state-machine-v2.13e.md,
blocks B (ordinal reference) and C (orphaned follow-up) are NOT
recipe-specific (general session-continuity fallbacks gated on recipe
state) and are covered separately where they interact with recipe
state, not as recipe execution itself.

These tests must pass identically before AND after extraction - that
identity is the proof of behavioral parity (Invariant #2).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, limit: int = 8) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


class TestInitialRecipeDiscovery:
    """Block D, RECIPE_DISCOVERY sub-state - recipe named, no shopping
    intent, no V2.8 plan built, active_recipe NOT set."""

    def test_recipe_name_without_shopping_intent(self):
        r = _chat("chcem robit Pad Thai", "rsm-discovery")
        assert r.get("intent") == "recipe"
        assert r.get("workflow_id") == "RECIPE_SHOPPING"
        assert len(r.get("recipes") or []) > 0
        assert r.get("products") == []
        assert not r.get("recipe_shopping_plan")


class TestInitialRecipeShopping:
    """Block D, RECIPE_SHOPPING_ACTIVE sub-state - explicit shopping
    intent triggers a real V2.8 plan and sets active_recipe."""

    def test_recipe_with_shopping_intent_builds_plan(self):
        r = _chat("chcem robit Pad Thai, co potrebujem kupit", "rsm-shopping")
        assert r.get("intent") == "recipe_to_products"
        assert r.get("workflow_id") == "RECIPE_SHOPPING"
        assert r.get("recipe_shopping_plan")
        assert len(r.get("products") or []) > 0
        titles = [p.get("title", "").lower() for p in r["products"]]
        assert any("rezan" in t for t in titles)


class TestRecipeFollowupIngredient:
    """Block E, _RF_INGREDIENT kind - a specific ingredient question
    after an active shopping-plan recipe."""

    def test_ingredient_question_after_active_recipe(self):
        sid = "rsm-followup-ingredient"
        _chat("chcem robit Pad Thai, co potrebujem kupit", sid)
        r = _chat("ake rezance?", sid)
        assert r.get("intent") == "recipe_to_products"
        assert r.get("workflow_id") == "RECIPE_SHOPPING"
        assert len(r.get("products") or []) > 0
        titles = [p.get("title", "").lower() for p in r["products"]]
        assert any("rezan" in t for t in titles)


class TestRecipeFollowupRemainingPlan:
    """Block E, .plan kind - "co este potrebujem?" returns remaining
    available ingredients from the active plan."""

    def test_what_else_do_i_need(self):
        sid = "rsm-followup-remaining"
        _chat("chcem robit Pad Thai, co potrebujem kupit", sid)
        r = _chat("a co este potrebujem?", sid)
        assert r.get("intent") == "recipe_to_products"
        assert r.get("recipe_shopping_plan")
        assert len(r.get("products") or []) > 0


class TestRecipeToProductHardSwitch:
    """Active recipe -> explicit unrelated brand/product must switch
    cleanly, no stale recipe contamination (Invariant #7 of V2.13e)."""

    def test_recipe_then_kikkoman(self):
        sid = "rsm-recipe-to-product"
        _chat("chcem robit Pad Thai, co potrebujem kupit", sid)
        r = _chat("Kikkoman", sid)
        assert r.get("intent") == "product_search"
        assert r.get("recipes", []) == [] if "recipes" in r else True
        titles = [p.get("title", "").lower() for p in (r.get("products") or [])]
        assert titles
        assert all("kikkoman" in t for t in titles)


class TestProductToRecipeTransition:
    def test_product_then_recipe(self):
        sid = "rsm-product-to-recipe"
        _chat("jazmínová ryža", sid)
        r = _chat("chcem robit Pad Thai, co potrebujem kupit", sid)
        assert r.get("intent") == "recipe_to_products"
        assert r.get("workflow_id") == "RECIPE_SHOPPING"


class TestRecipeToSafety:
    """Safety precedence (rt0010) must not be swallowed by active
    recipe state - safety is resolved earlier in _chat_impl(), before
    the recipe blocks are ever reached."""

    def test_recipe_then_allergen_safety(self):
        sid = "rsm-recipe-to-safety"
        _chat("chcem robit Pad Thai, co potrebujem kupit", sid)
        r = _chat("sójová omáčka bez sóje", sid)
        assert r.get("intent") == "allergen_safety"
        assert r.get("products") == []


class TestRecipeToReset:
    def test_recipe_then_reset(self):
        sid = "rsm-recipe-to-reset"
        _chat("chcem robit Pad Thai, co potrebujem kupit", sid)
        r = _chat("zacnime odznova", sid)
        assert r.get("intent") == "reset"


class TestOrphanedFollowupNotRecipeSpecific:
    """Blocks B/C are general session-continuity fallbacks, not recipe
    execution - a fresh session with no active recipe AND no active
    ResultSet gets a clarification, answered=False."""

    def test_what_else_with_no_active_context(self):
        r = _chat("a co este potrebujem?", "rsm-orphaned-fresh")
        assert r.get("intent") == "product_search"
        assert r.get("answered") is False
        assert r.get("products") == []

    def test_ordinal_reference_with_no_active_context(self):
        r = _chat("ten druhy", "rsm-ordinal-fresh")
        assert r.get("intent") == "product_search"
        assert r.get("answered") is False


class TestCrossSessionIsolation:
    def test_active_recipe_in_one_session_does_not_leak_to_another(self):
        session_a = "rsm-isolation-a"
        session_b = "rsm-isolation-b"
        _chat("chcem robit Pad Thai, co potrebujem kupit", session_a)
        r_b = _chat("ake rezance?", session_b)
        # session B has no active recipe - "ake rezance?" must NOT
        # resolve as a recipe follow-up for session A's Pad Thai.
        assert r_b.get("intent") != "recipe_to_products"


class TestRepeatedSessionNoCumulativeContamination:
    def test_repeating_the_same_shopping_request_is_stable(self):
        sid = "rsm-repeated"
        r1 = _chat("chcem robit Pad Thai, co potrebujem kupit", sid)
        r2 = _chat("chcem robit Pad Thai, co potrebujem kupit", sid)
        assert r1.get("intent") == r2.get("intent") == "recipe_to_products"
        assert len(r1.get("products") or []) == len(r2.get("products") or [])


class TestInternalExecutionExcludesCustomerAnalytics:
    """V2.13d's exact lesson: log_question's local shadow in
    _chat_impl() must keep working for recipe blocks post-extraction -
    EVALUATION/LEARNING/SHADOW/ADMIN_TEST must never write to
    question_analytics.jsonl for a recipe turn."""

    def test_evaluation_context_recipe_turn_writes_no_customer_analytics(self, tmp_path, monkeypatch):
        from app.execution_context import evaluation_context

        analytics_path = tmp_path / "question_analytics.jsonl"
        monkeypatch.setenv("ANALYTICS_LOG_PATH", str(analytics_path))
        chat_request = m.ChatRequest(message="chcem robit Pad Thai, co potrebujem kupit", limit=6, session_id="rsm-eval-analytics")
        m._chat_internal(chat_request, _FakeRequest(), execution_context=evaluation_context())
        if analytics_path.exists():
            lines = [l for l in analytics_path.read_text(encoding="utf-8").splitlines() if l.strip()]
            assert lines == []


class TestRegressionLocksUnaffectedByRecipeState:
    """rt0004/rt0010/rt0011 must remain fixed regardless of recipe
    changes - permanent tripwire per this session's established
    discipline."""

    def test_rt0004_still_related_products(self):
        r = _chat("súvisiace produkty k sushi ryži", "rsm-lock-rt0004")
        assert r.get("intent") == "related_products"
        assert r.get("products")

    def test_rt0010_still_allergen_safety(self):
        r = _chat("sójová omáčka bez sóje", "rsm-lock-rt0010")
        assert r.get("intent") == "allergen_safety"
        assert r.get("products") == []

    def test_rt0011_session_collision_still_fixed(self):
        sid = "rsm-lock-rt0011"
        r1 = _chat("mám rád nepálivé jedlo, čo odporúčaš?", sid)
        r2 = _chat("mám rád nepálivé jedlo, čo odporúčaš?", sid)
        assert r1.get("intent") == "product_search"
        assert r2.get("intent") == "product_search"

    def test_show_more_still_works(self):
        sid = "rsm-lock-showmore"
        first = _chat("basmati ryza", sid, limit=3)
        assert first.get("has_more") is True or first.get("matching_total", 0) > 3
        second = _chat("zobraz viac", sid)
        assert second.get("response_mode") == "result_set_continuation"

    def test_size_refinement_still_works(self):
        sid = "rsm-lock-size"
        _chat("jazmínová ryža", sid)
        r = _chat("5kg", sid)
        titles = [p.get("title", "").lower() for p in (r.get("products") or [])]
        assert any("5" in t for t in titles)

    def test_topic_switch_still_clean(self):
        sid = "rsm-lock-topicswitch"
        _chat("jazmínová ryža", sid)
        r = _chat("Shin Ramyun", sid)
        titles = [p.get("title", "").lower() for p in (r.get("products") or [])]
        assert titles
        assert not any("ryz" in t and "ramyun" not in t for t in titles)
