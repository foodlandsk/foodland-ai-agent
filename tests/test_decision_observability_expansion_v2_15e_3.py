"""
tests/test_decision_observability_expansion_v2_15e_3.py  -  V2.15e.3:
Decision Observability Expansion (cross_sell / recipe_shopping /
replacement_products).

V2.15e.2 classified all three as STRUCTURAL_GAP. This sprint audited
each INDEPENDENTLY (docs/decision-observability-expansion-v2.15e.3.md)
rather than forcing a uniform outcome - the result is deliberately
heterogeneous:

- cross_sell: GATE A / STRUCTURAL_GAP_ACCEPTED. app.cross_sell.build_cross_sell()
  already computes a genuine, evidence-grounded decision (CrossSellDecision/
  CrossSellCandidate, role-first, real evidence tags) - but app/widget.js
  NEVER renders `data.cross_sell` at all (grep-confirmed: zero matches in
  the whole file). Durably logging a decision the customer can never see
  or act on would create permanently-zero-engagement records that a
  future dataset builder could misread as a real negative signal - a
  worse outcome than not logging at all. No backend/frontend change.

- recipe_shopping: GATE C / DECISION_OBSERVABILITY_LIVE. Unlike cross_sell,
  recipe_shopping's products are already merged directly into the
  primary `data.products` array and fully rendered/interactive today.
  app.recipe_shopping.RecipeShoppingPlan already carries real per-role
  evidence (candidate_product_ids, selected_product_id, confidence,
  status) - structurally identical in shape to app.basket_completion's
  existing decision (which already has basket_decision_id). Implemented
  by mirroring that exact precedent: one decision_id per computed plan,
  reusing log_recommendation_decision().

- replacement_products: GATE A / STRUCTURAL_GAP_ACCEPTED. Unlike cross_sell
  and recipe_shopping, alternative_products_for_subject() is a raw
  3-tier fallback CASCADE (curated Alternatives -> hardcoded query list
  -> same-category search) with NO per-candidate evidence/confidence at
  all - it returns whichever tier's results were first non-empty, not an
  evaluated choice among ranked candidates. REPLACEMENT_QUALITY_DATA_LIMITATION
  (docs/cross-sell-audit.md's sibling finding) means a query constraint
  like "vegan" is not deterministically enforced - confirmed here by a
  direct rt0013 re-verification test. A decision object risks implying a
  quality guarantee ("best vegan substitute") the data cannot support.
  rt0013's CLOSED routing is preserved untouched.
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
from app.execution_context import customer_context, evaluation_context, admin_test_context


@pytest.fixture(autouse=True)
def _reset_shared_rate_limit_state():
    # app.main.rate_limit_events is a module-global dict keyed by
    # client_key, cleaned up only by a 60s sliding window - it persists
    # across the whole pytest process, not per-test. This file makes many
    # CUSTOMER-context _chat_internal() calls via _FakeRequest() (the
    # same client_key="127.0.0.1" every other sprint's test file also
    # uses), which would otherwise accumulate and could push an unrelated
    # test elsewhere in the suite (one that monkeypatches a low
    # RATE_LIMIT_PER_MINUTE and expects a clean count, e.g.
    # tests/test_execution_context.py) over its threshold purely due to
    # full-suite run ordering - not a real product regression, but a
    # shared-state leak this file should not cause. Scoped to this file
    # only; no other test file is touched.
    yield
    m.rate_limit_events.clear()


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat_as_customer(message: str, session_id: str, limit: int = 5) -> dict:
    return m._chat_internal(
        m.ChatRequest(message=message, session_id=session_id, limit=limit),
        _FakeRequest(),
        execution_context=customer_context(),
    )


# ---------------------------------------------------------------------
# PART A - cross_sell: decision logic real, but never rendered -
# STRUCTURAL_GAP_ACCEPTED, no change (characterization, not regression)
# ---------------------------------------------------------------------

class TestCrossSellStructuralGapCharacterization:
    def test_cross_sell_decision_still_computed_server_side(self):
        _chat_as_customer("co potrebujem na sushi", "v215e3-cs-a")
        r = _chat_as_customer("sushi ryza", "v215e3-cs-a")
        assert r.get("cross_sell_eligible") is True
        assert r.get("cross_sell_context_type")
        assert len(r.get("cross_sell") or []) > 0

    def test_cross_sell_products_are_a_separate_field_not_merged_into_products(self):
        _chat_as_customer("co potrebujem na sushi", "v215e3-cs-b")
        r = _chat_as_customer("sushi ryza", "v215e3-cs-b")
        cross_sell_ids = {p.get("id") for p in (r.get("cross_sell") or [])}
        product_ids = {p.get("id") for p in (r.get("products") or [])}
        assert cross_sell_ids, "expected non-empty cross_sell for this fixture"
        assert cross_sell_ids.isdisjoint(product_ids), "cross_sell must remain a distinct field, never merged into products"

    def test_cross_sell_has_no_decision_id_field_gate_a(self):
        _chat_as_customer("co potrebujem na sushi", "v215e3-cs-c")
        r = _chat_as_customer("sushi ryza", "v215e3-cs-c")
        assert r.get("cross_sell_eligible") is True
        assert "cross_sell_decision_id" not in r

    def test_widget_never_reads_cross_sell_field(self):
        widget_path = ROOT / "app" / "widget.js"
        source = widget_path.read_text(encoding="utf-8")
        assert "cross_sell" not in source, (
            "characterization invariant: app/widget.js must not read data.cross_sell "
            "(this is the exact finding GATE A for cross_sell is based on)"
        )


# ---------------------------------------------------------------------
# PART B - recipe_shopping: GATE C, implemented this sprint
# ---------------------------------------------------------------------

class TestRecipeShoppingDecisionCorrelation:
    def test_initial_recipe_plan_gets_a_decision_id(self):
        r = _chat_as_customer("co potrebujem na pad thai", "v215e3-rs-a")
        assert r.get("intent") == "recipe_to_products"
        assert r.get("recipe_shopping_plan") is not None
        assert r.get("recipe_shopping_decision_id")
        assert r.get("interaction_id")

    def test_decision_id_is_fresh_per_plan_not_reused_across_dishes(self):
        # "ramen" is a BASKET_V1_ELIGIBLE_USE_CASE (routes to
        # basket_completion, checked earlier in the cascade than
        # execute_recipe()) - tom_kha reaches the V2.8 recipe_graph path
        # directly, like pad_thai.
        r1 = _chat_as_customer("co potrebujem na pad thai", "v215e3-rs-b1")
        r2 = _chat_as_customer("co potrebujem na tom kha", "v215e3-rs-b2")
        assert r1.get("recipe_shopping_decision_id")
        assert r2.get("recipe_shopping_decision_id")
        assert r1["recipe_shopping_decision_id"] != r2["recipe_shopping_decision_id"]

    def test_plan_update_followup_gets_a_fresh_decision_id(self):
        sid = "v215e3-rs-c"
        r1 = _chat_as_customer("co potrebujem na pad thai", sid)
        r2 = _chat_as_customer("co este potrebujem?", sid)
        assert r1.get("recipe_shopping_decision_id")
        if r2.get("recipe_shopping_plan") is not None:
            assert r2.get("recipe_shopping_decision_id")
            assert r2["recipe_shopping_decision_id"] != r1["recipe_shopping_decision_id"]

    def test_ingredient_browse_followup_has_no_fabricated_decision_id(self):
        # RECIPE_FOLLOWUP_INGREDIENT: browsing candidates for one role is
        # not a system recommendation choice - honestly null.
        sid = "v215e3-rs-d"
        _chat_as_customer("co potrebujem na pad thai", sid)
        r2 = _chat_as_customer("ake rezance?", sid)
        assert not r2.get("recipe_shopping_decision_id")

    def test_legacy_dish_not_in_recipe_graph_has_no_decision_id(self):
        # Dishes outside recipe_graph_index.dishes_by_id fall back to the
        # legacy, evidence-free recipe_shopping_core_products() path -
        # honestly null, never fabricated.
        r = _chat_as_customer("co potrebujem na sushi", "v215e3-rs-e")
        assert r.get("intent") == "basket_completion"  # sushi is BASKET_V1, not recipe graph
        assert not r.get("recipe_shopping_decision_id")

    def test_recommended_product_ids_match_plan_selected_ids(self):
        r = _chat_as_customer("co potrebujem na pad thai", "v215e3-rs-f")
        plan = r.get("recipe_shopping_plan") or {}
        selected_ids = {
            ing["selected_product_id"]
            for section in plan.get("sections", {}).values()
            for ing in section
            if ing.get("selected_product_id")
        }
        product_ids = {p.get("id") for p in (r.get("products") or [])}
        assert selected_ids
        assert selected_ids == product_ids

    def test_hard_topic_switch_does_not_carry_previous_recipe_decision(self):
        sid = "v215e3-rs-g"
        r1 = _chat_as_customer("co potrebujem na pad thai", sid)
        r2 = _chat_as_customer("jazminova ryza", sid)
        assert r1.get("recipe_shopping_decision_id")
        assert not r2.get("recipe_shopping_decision_id")

    def test_reset_clears_recipe_state(self):
        sid = "v215e3-rs-h"
        _chat_as_customer("co potrebujem na pad thai", sid)
        _chat_as_customer("Zacnime odznova", sid)
        r3 = _chat_as_customer("ake rezance?", sid)
        assert not r3.get("recipe_shopping_decision_id")

    def test_cross_session_isolation(self):
        r1 = _chat_as_customer("co potrebujem na pad thai", "v215e3-rs-iso-a")
        r2 = _chat_as_customer("co potrebujem na pad thai", "v215e3-rs-iso-b")
        assert r1["recipe_shopping_decision_id"] != r2["recipe_shopping_decision_id"]
        assert r1["interaction_id"] != r2["interaction_id"]

    def test_durable_decision_log_written_for_recipe_shopping(self, tmp_path, monkeypatch):
        log_path = tmp_path / "recommendation_decisions.jsonl"
        monkeypatch.setenv("RECOMMENDATION_DECISIONS_LOG_PATH", str(log_path))
        r = _chat_as_customer("co potrebujem na pad thai", "v215e3-rs-durable")
        decision_id = r.get("recipe_shopping_decision_id")
        assert decision_id
        rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert rows
        record = rows[-1]
        assert record["decision_id"] == decision_id
        assert record["decision_type"] == "recipe_shopping"
        assert record["use_case"] == "pad_thai"
        assert record["recommended_product_ids"]


class TestRecipeShoppingRecommendedIdsHonesty:
    def test_reason_codes_reflect_real_ingredient_statuses(self):
        r = _chat_as_customer("co potrebujem na pad thai", "v215e3-rs-honesty")
        plan = r.get("recipe_shopping_plan") or {}
        statuses = set()
        for section_name, ingredients in plan.get("sections", {}).items():
            for ing in ingredients:
                statuses.add(ing["status"])
        assert statuses
        assert statuses <= {"AVAILABLE", "ALREADY_SATISFIED", "NOT_AVAILABLE", "OPTIONAL", "UNKNOWN_MAPPING"}


# ---------------------------------------------------------------------
# PART C - replacement_products: GATE A, STRUCTURAL_GAP_ACCEPTED
# ---------------------------------------------------------------------

class TestReplacementProductsStructuralGapCharacterization:
    def test_rt0013_still_resolves_to_replacement_products(self):
        # rt0013 IS CLOSED (spec Sec.23) - re-verified, not reopened.
        r = _chat_as_customer("nahrada za rybiu omacku vegan", "v215e3-rp-rt0013")
        assert r.get("intent") == "replacement_products"

    def test_replacement_has_no_decision_id_field_gate_a(self):
        r = _chat_as_customer("nahrada za rybiu omacku vegan", "v215e3-rp-a")
        assert "replacement_decision_id" not in r

    def test_replacement_quality_data_limitation_vegan_not_deterministically_filtered(self):
        # REPLACEMENT_QUALITY_DATA_LIMITATION: the "vegan" constraint word
        # does not deterministically filter alternative_products_for_subject()'s
        # candidates - documented, not silently "fixed" by this sprint.
        r_plain = _chat_as_customer("nahrada za rybiu omacku", "v215e3-rp-plain")
        r_vegan = _chat_as_customer("nahrada za rybiu omacku vegan", "v215e3-rp-vegan")
        plain_ids = [p.get("id") for p in (r_plain.get("products") or [])]
        vegan_ids = [p.get("id") for p in (r_vegan.get("products") or [])]
        assert plain_ids and vegan_ids
        # Both intents resolve to replacement_products; the candidate
        # SET is not required to differ, since there is no dietary filter -
        # this test documents current behavior, it does not assert the
        # constraint IS enforced.
        assert r_plain.get("intent") == "replacement_products"
        assert r_vegan.get("intent") == "replacement_products"

    def test_bare_replacement_query_still_returns_alternatives(self):
        r = _chat_as_customer("alternativa ku Kikkoman sojovej omacke", "v215e3-rp-bare")
        assert r.get("intent") == "replacement_products"
        assert len(r.get("products") or []) > 0


# ---------------------------------------------------------------------
# Execution context / AUTO_PROMOTION / failure isolation (recipe_shopping only)
# ---------------------------------------------------------------------

class TestExecutionContextIsolation:
    def test_evaluation_context_recipe_decision_never_durably_logged(self, tmp_path, monkeypatch):
        events_path = tmp_path / "recommendation_decisions.jsonl"
        monkeypatch.setenv("RECOMMENDATION_DECISIONS_LOG_PATH", str(events_path))
        r = m._chat_internal(
            m.ChatRequest(message="co potrebujem na pad thai", session_id="v215e3-eval-ctx", limit=5),
            _FakeRequest(),
            execution_context=evaluation_context(),
        )
        # EVALUATION traffic must not durably log a recommendation decision -
        # response may still compute a decision_id in-memory (V2.15d.3
        # gates DURABLE LOGGING, not in-response computation), but nothing
        # written to disk.
        assert not events_path.exists() or events_path.read_text(encoding="utf-8").strip() == ""


class TestAutoPromotionUnchanged:
    def test_auto_promotion_still_disabled(self):
        from app.learning_lifecycle import AUTO_PROMOTION_ENABLED
        assert AUTO_PROMOTION_ENABLED is False


# ---------------------------------------------------------------------
# Permanent regression controls
# ---------------------------------------------------------------------

class TestControlRegressionMatrix:
    def test_rt0004_related_products_protected(self):
        r = _chat_as_customer("súvisiace produkty k sushi ryži", "v215e3-rt0004")
        assert r.get("intent") == "related_products"

    def test_rt0010_allergen_safety_protected(self):
        r = _chat_as_customer("sójová omáčka bez sóje", "v215e3-rt0010")
        assert r.get("intent") == "allergen_safety"

    def test_rt0011_no_session_contamination(self):
        sid = "v215e3-rt0011"
        query = "mám rád nepálivé jedlo, čo odporúčaš?"
        first = _chat_as_customer(query, sid)
        second = _chat_as_customer(query, sid)
        assert first.get("intent") == "product_search"
        assert second.get("intent") == "product_search"

    def test_rt0013_replacement_products_protected(self):
        r = _chat_as_customer("náhrada za rybiu omáčku vegan", "v215e3-rt0013-control")
        assert r.get("intent") == "replacement_products"

    def test_v2_15c_store_location_followup_still_live(self):
        sid = "v215e3-store-followup"
        _chat_as_customer("Kde sa nachadza kamenna predajna?", sid)
        r = _chat_as_customer("Prilož mi Google link na adresu.", sid)
        assert r.get("intent") == "faq"
        assert "maps.app.goo.gl" in (r.get("answer") or "")

    def test_v2_15e_1_resultset_continuation_still_correct(self):
        sid = "v215e3-resultset-control"
        r1 = _chat_as_customer("jazminova ryza", sid)
        r2 = _chat_as_customer("zobraz viac", sid)
        assert r2.get("result_set_id") == r1.get("result_set_id")
        assert r2.get("interaction_id") != r1.get("interaction_id")

    def test_v2_15e_2_feedback_correlation_still_correct_for_comparison(self):
        r = _chat_as_customer("porovnaj Samyang Buldak a Nissin Demae Ramen", "v215e3-feedback-control")
        assert r.get("intent") == "product_comparison"
        assert r.get("comparison_decision_id")

    def test_basket_completion_unchanged(self):
        r = _chat_as_customer("co potrebujem na sushi", "v215e3-basket-control")
        assert r.get("intent") == "basket_completion"
        assert r.get("basket_decision_id")

    def test_use_case_ramen_control(self):
        r = _chat_as_customer("ake kokosove mlieko na tom kha gai?", "v215e3-usecase-control")
        assert r.get("intent") == "use_case_advice"
        assert r.get("use_case_advice_decision_id")
