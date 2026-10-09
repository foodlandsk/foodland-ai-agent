"""
tests/test_shopping_list_budget_interaction_v2_27j.py  -  V2.27j: wiring
app.query_constraints.PriceConstraint into the 4 curated shopping-list-
override functions (sushi/tom_yum/kimchi_ramen/recipe), complementing
V2.27e's /chat-level filter and V2.27h's structured-retrieval-path filter.

Context (V2.27a-j read-only architecture/contract/wiring review series,
docs/query-semantics.md): V2.27d/e/h flagged that sushi_shopping_core_
products()/tom_yum_shopping_core_products()/kimchi_ramen_shopping_core_
products()/recipe_shopping_core_products() rebuild their own product list
from the full catalog via hardcoded per-ingredient queries, using the
caller's (already price-filtered) `matches` only as a last-resort filler
- so a budget stated alongside a shopping-list request was not honored
for the curated picks themselves. V2.27i found this is not a narrow edge
case: RECIPE_SHOPPING_CORE_QUERIES alone has 47 entries (pad_thai, satay,
tom_kha, pho, bulgogi, kari, ramen, ...), so combined with sushi/tom_yum/
kimchi_ramen this is effectively the system's entire recipe-shopping-list
feature. The open question was a product decision, not an engineering
unknown: what happens when no candidate for an ingredient fits the
budget? The user chose Option A - omit that ingredient, never substitute
a cheaper-but-wrong or pricier-but-right item.

No golden/HOLDOUT scenario combines a shopping-list request with a price
constraint (re-verified in V2.27i), so this file's target tests use
synthetic (not corpus-sourced) queries - clearly marked as such, not
presented as golden-backed.

Full pytest was run as a pre-commit gate before this file was added - see
the V2.27j report for the exact baseline/post-patch comparison.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m
from app.query_constraints import PriceConstraint


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, limit: int = 8) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


class TestSushiShoppingListBudgetSynthetic:
    """Synthetic (not golden/HOLDOUT) - "nákupný zoznam na sushi, mám 10
    eur" previously returned byte-identical output to the unconstrained
    query (live-verified pre-patch, including a 23.80 EUR sushi rice
    pack). Post-patch, every returned item must satisfy the budget."""

    def test_intent_unchanged(self):
        r = _chat("nákupný zoznam na sushi, mám 10 eur", "v227j-sushi-budget10")
        assert r.get("intent") == "related_products"

    def test_all_products_satisfy_budget(self):
        r = _chat("nákupný zoznam na sushi, mám 10 eur", "v227j-sushi-budget10-prices")
        products = r.get("products") or []
        assert products
        assert all(p.get("effective_price") is not None and p["effective_price"] <= 10.0 for p in products)

    def test_tight_budget_omits_ingredients_rather_than_substituting(self):
        # Option A: with a 2 EUR budget, several of the 6 curated
        # ingredients have no eligible candidate even in the widened
        # pool - they must be omitted, never filled with an over-budget
        # item.
        r = _chat("nákupný zoznam na sushi, mám 2 eur", "v227j-sushi-budget2")
        products = r.get("products") or []
        assert products
        assert len(products) < 7
        assert all(p.get("effective_price") is not None and p["effective_price"] <= 2.0 for p in products)


class TestPadThaiShoppingListBudgetSynthetic:
    """Uses the shared RECIPE_SHOPPING_CORE_QUERIES/recipe_core_product_
    candidates() path (47 dish subjects route through this one
    mechanism) - pad_thai's own ingredients already happen to fit a 5 EUR
    budget, so this is a no-op-on-this-exact-query regression lock."""

    def test_unchanged_when_already_within_budget(self):
        r = _chat("čo potrebujem na pad thai, mám 5 eur?", "v227j-padthai-budget5")
        products = r.get("products") or []
        assert r.get("intent") == "recipe_to_products"
        assert products
        assert all(p.get("effective_price") is not None and p["effective_price"] <= 5.0 for p in products)


class TestSushiShoppingListNoInterference:
    """No budget stated - must remain byte-identical to the pre-V2.27j
    baseline (price_constraint defaults to None in all 4 functions)."""

    def test_sushi_unchanged(self):
        r = _chat("nákupný zoznam na sushi", "v227j-sushi-noB")
        products = r.get("products") or []
        assert r.get("intent") == "related_products"
        assert len(products) == 7

    def test_tom_yum_unchanged(self):
        r = _chat("nákupný zoznam na tom yum", "v227j-tomyum-noB")
        products = r.get("products") or []
        assert r.get("intent") == "related_products"
        assert len(products) == 6

    def test_kimchi_ramen_unchanged(self):
        r = _chat("nákupný zoznam na kimchi ramen", "v227j-kimchiramen-noB")
        products = r.get("products") or []
        assert r.get("intent") == "related_products"
        assert len(products) == 8

    def test_pad_thai_unchanged(self):
        r = _chat("čo potrebujem na pad thai?", "v227j-padthai-noB")
        products = r.get("products") or []
        assert r.get("intent") == "recipe_to_products"
        assert len(products) == 5


class TestHelperFunctionsDirectly:
    """Direct, non-/chat unit coverage of the 4 patched functions and the
    shared eligibility helper."""

    def test_shopping_core_price_eligible(self):
        eligible = {"effective_price": 3.0}
        ineligible = {"effective_price": 15.0}
        missing = {"effective_price": None}
        constraint = PriceConstraint(price_max=10.0)
        assert m._shopping_core_price_eligible(eligible, constraint)
        assert not m._shopping_core_price_eligible(ineligible, constraint)
        assert not m._shopping_core_price_eligible(missing, constraint)

    def test_sushi_function_accepts_price_constraint_kwarg(self):
        result = m.sushi_shopping_core_products(m.products, [], 8, price_constraint=PriceConstraint(price_max=10.0))
        assert all(p.get("effective_price") is not None and p["effective_price"] <= 10.0 for p in result)

    def test_sushi_function_default_unchanged(self):
        with_default = m.sushi_shopping_core_products(m.products, [], 8)
        without_kwarg = m.sushi_shopping_core_products(m.products, [], 8, price_constraint=None)
        assert with_default == without_kwarg

    def test_recipe_core_product_candidates_filters_by_price(self):
        candidates = m.recipe_core_product_candidates(
            m.products, "ryzove rezance", ("rezance",), (), 5, price_constraint=PriceConstraint(price_max=3.0),
        )
        assert all(p.get("effective_price") is not None and p["effective_price"] <= 3.0 for p in candidates)


class TestClosedContractsUnaffected:
    """Re-asserted non-interference - none of these ever reach the
    shopping-list-override branch, so this patch must have zero effect."""

    def test_budget_0001_unchanged(self):
        r = _chat("Mám 10 eur, akú rybaciu omáčku si za to môžem kúpiť?", "v227j-budget0001")
        products = r.get("products") or []
        assert r.get("intent") == "product_search"
        assert len(products) == 8

    def test_budget_0003_unchanged(self):
        r = _chat("Mám rozpočet 5 eur na kari pastu.", "v227j-budget0003")
        products = r.get("products") or []
        assert r.get("intent") == "product_search"
        assert len(products) == 4

    def test_selected6_unaffected(self):
        r = _chat("Aké máte rybacie omáčky?", "v227j-sel6")
        assert r.get("intent") == "product_search"
        assert len(r.get("products") or []) == 8

    def test_product_search_0007_unaffected(self):
        r = _chat("Chcem miso pastu na polievku.", "v227j-ps0007")
        assert r.get("intent") == "product_search"
        assert len(r.get("products") or []) == 8

    def test_contract2_unaffected(self):
        r = _chat("Ako uvariť Ma Po Tofu?", "v227j-contract2")
        assert r.get("intent") == "recipe"

    def test_sushi_session_unaffected(self):
        sid = "v227j-sushi-session"
        r1 = _chat("chcem robit sushi", sid)
        assert r1.get("intent") == "related_products"
        r2 = _chat("aká ryžu?", sid)
        assert r2.get("intent") == "product_search"
