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

V2.29e update: sushi_shopping_core_products()/tom_yum_shopping_core_
products()/kimchi_ramen_shopping_core_products() are deleted (Legacy
Special-3 Builder Retirement) - sushi/tom_yum/kimchi_ramen now resolve
through the same canonical recipe-shopping pipeline as
recipe_shopping_core_products()'s other 47 dishes, with an equivalent
V2.29d-added price filter in app.workflow_executor.execute_recipe().
Tests below that exercised the three deleted functions directly were
replaced with canonical-behavior coverage (see TestHelperFunctionsDirectly's
docstring note); the /chat-level budget tests for sushi/tom_yum/
kimchi_ramen were already updated for the routing change in V2.29d and
needed no further change here.
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
        # V2.29d (Special-3 RECIPE_SHOPPING routing flip): intent/
        # workflow_id updated to the new canonical contract - the price-
        # ceiling checks in the two sibling tests below are unaffected
        # (still pass unmodified) thanks to the paired V2.29d price-
        # filtering-parity fix in app.workflow_executor.execute_recipe().
        r = _chat("nákupný zoznam na sushi, mám 10 eur", "v227j-sushi-budget10")
        assert r.get("intent") == "recipe_to_products"
        assert r.get("workflow_id") == "RECIPE_SHOPPING"

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
        # OLD CONTRACT (pre-V2.29d): intent=related_products, 7 products
        # (the legacy sushi_shopping_core_products() builder's 6 curated
        # queries plus one existing_matches fallback-fill pad).
        # NEW CONTRACT (V2.29d, Special-3 RECIPE_SHOPPING routing flip):
        # intent=recipe_to_products/RECIPE_SHOPPING, 6 products - one per
        # curated ingredient role, no fallback-fill pad (V2.29c's data-port
        # docstring explicitly documents that padding step as NOT ported -
        # an intentional, acknowledged customer-visible difference, not a
        # regression; see Section 25 of the V2.29d spec).
        r = _chat("nákupný zoznam na sushi", "v227j-sushi-noB")
        products = r.get("products") or []
        assert r.get("intent") == "recipe_to_products"
        assert r.get("workflow_id") == "RECIPE_SHOPPING"
        assert len(products) == 6

    def test_tom_yum_unchanged(self):
        # V2.29d: intent/workflow_id updated; count unaffected (still 6 -
        # verified directly, this dish's 6 curated queries all resolve
        # with no fallback-fill difference).
        r = _chat("nákupný zoznam na tom yum", "v227j-tomyum-noB")
        products = r.get("products") or []
        assert r.get("intent") == "recipe_to_products"
        assert r.get("workflow_id") == "RECIPE_SHOPPING"
        assert len(products) == 6

    def test_kimchi_ramen_unchanged(self):
        # V2.29d: intent/workflow_id updated; count unaffected (still 8 -
        # verified directly, this dish's 8 curated queries all resolve
        # with no fallback-fill difference).
        r = _chat("nákupný zoznam na kimchi ramen", "v227j-kimchiramen-noB")
        products = r.get("products") or []
        assert r.get("intent") == "recipe_to_products"
        assert r.get("workflow_id") == "RECIPE_SHOPPING"
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

    # V2.29e (Legacy Special-3 Builder Retirement) - the two direct-call
    # tests that used to live here, test_sushi_function_accepts_price_
    # constraint_kwarg and test_sushi_function_default_unchanged, unit-
    # tested app.main.sushi_shopping_core_products() directly (now
    # deleted - sushi/tom_yum/kimchi_ramen resolve exclusively through
    # the canonical recipe-shopping pipeline since V2.29d).
    # OLD CONTRACT: sushi_shopping_core_products(products, [], limit,
    # price_constraint=X) filters its own curated candidates to <= X,
    # and produces byte-identical output whether price_constraint is
    # omitted or passed explicitly as None.
    # NEW CONTRACT: the equivalent price-eligibility guarantee for sushi
    # now lives in app.workflow_executor.execute_recipe()'s post-hoc
    # filter (added in V2.29d) and is already covered end-to-end by
    # TestSushiShoppingListBudgetSynthetic.test_all_products_satisfy_budget
    # and .test_tight_budget_omits_ingredients_rather_than_substituting
    # above (via /chat, the only way that filter is reachable - it has
    # no standalone public function to unit-test directly). The default-
    # vs-explicit-None equivalence check has no canonical replacement:
    # the new filter takes a single `price_constraint` parameter with no
    # default-argument ambiguity to verify.

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
