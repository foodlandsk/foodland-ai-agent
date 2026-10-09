"""
tests/test_chat_budget_price_filtering_v2_27e.py  -  V2.27e: wiring
app.query_constraints.extract_price_constraint() into /chat as a hard
product-eligibility filter.

Context (V2.27a-e read-only architecture/contract/wiring review series,
docs/query-semantics.md): V2.26d closed budget_0001's ROUTING debt
(related_subject -> product_search); V2.27c implemented the pure parser,
not wired into /chat; V2.27d locked the exact wiring shape. This is that
bounded implementation: one filter clause in _chat_impl(), between
`is_shopping_list_request = wants_shopping_list(...)` and
`matches = personalize_products(matches, user_profile)` - hard
eligibility only (never a ranking signal), reading `effective_price`
directly off the already-formatted product dict.

Deliberately NOT in scope (V2.27d Sections E/H, re-asserted here, not
re-litigated):
- no widen-fetch (both real DEV targets stay non-empty without one -
  live-verified in V2.27d before implementing);
- no structured-retrieval-path ranked_product_ids-level depth fix;
- no shopping-list-override (sushi/tom_yum/kimchi_ramen/recipe) fix -
  those functions rebuild their own product list from the full catalog
  and only use the caller's `matches` as a last-resort filler, so a
  budget constraint stated alongside a shopping-list request is not
  honored by this patch (none of the 3 corpus-triggering scenarios are
  shopping-list requests, so this never fires here).

Full pytest (2889 passed, 0 failed) was run as a pre-commit gate before
this file was added - see the V2.27e report for the exact
baseline/post-patch comparison. This file locks the contract going
forward.
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


class TestBudget0001Target:
    """The bounded repair target - golden scenario v222_budget_0001. All
    8 of its current matches are already <=10 EUR (live-verified in
    V2.27d), so this is also a no-op-on-this-exact-query regression lock,
    not just a feature test."""

    def test_intent_is_product_search(self):
        r = _chat("Mám 10 eur, akú rybaciu omáčku si za to môžem kúpiť?", "v227e-budget0001")
        assert r.get("intent") == "product_search"

    def test_products_nonempty(self):
        r = _chat("Mám 10 eur, akú rybaciu omáčku si za to môžem kúpiť?", "v227e-budget0001-products")
        assert r.get("products")

    def test_all_returned_products_satisfy_budget(self):
        r = _chat("Mám 10 eur, akú rybaciu omáčku si za to môžem kúpiť?", "v227e-budget0001-pricefit")
        products = r.get("products") or []
        assert products
        assert all(p.get("effective_price") is not None and p["effective_price"] <= 10.0 for p in products)


class TestBudget0003Narrowing:
    """budget_0003 goes from 5 to 4 products - the one 11.90 EUR item
    (over the stated 5 EUR budget) is correctly excluded, while intent
    and the golden products_nonempty invariant both stay satisfied."""

    def test_intent_unchanged(self):
        r = _chat("Mám rozpočet 5 eur na kari pastu.", "v227e-budget0003")
        assert r.get("intent") == "product_search"

    def test_products_nonempty_and_narrowed(self):
        r = _chat("Mám rozpočet 5 eur na kari pastu.", "v227e-budget0003-narrow")
        products = r.get("products") or []
        assert products
        assert len(products) == 4
        assert all(p.get("effective_price") is not None and p["effective_price"] <= 5.0 for p in products)


class TestMultiConstraint0003NonInterference:
    """"pod 5 eur" (strict) is deferred by the parser (extract_price_
    constraint returns None) - the filter clause never activates for
    this message, so its 8 matches stay exactly as before, including the
    5.47 EUR item that a (not-implemented) strict "<5" filter would have
    excluded."""

    def test_unchanged(self):
        r = _chat("Potrebujem rybaciu omáčku pod 5 eur, značka Megachef.", "v227e-mc0003")
        products = r.get("products") or []
        assert r.get("intent") == "product_search"
        assert len(products) == 8
        assert any(p.get("effective_price", 0) > 5.0 for p in products)


class TestSelected6Unaffected:
    """All 6 closed V2.24y cases must remain exactly as before - none of
    them contains a parseable price constraint, so the new clause never
    activates."""

    def test_cd0001(self):
        r = _chat("Aké máte rybacie omáčky?", "v227e-cd0001")
        assert r.get("intent") == "product_search"
        assert len(r.get("products") or []) == 8

    def test_kw0001(self):
        r = _chat("Predávate misky na matcha čaj?", "v227e-kw0001")
        assert r.get("intent") == "product_search"

    def test_ps0005(self):
        r = _chat("Máte v ponuke matcha čaj?", "v227e-ps0005")
        assert r.get("intent") == "product_search"

    def test_ps0006(self):
        r = _chat("Zháňam tofu na prípravu ázijského jedla.", "v227e-ps0006")
        assert r.get("intent") == "product_search"

    def test_ps0009(self):
        r = _chat("Máte wasabi prášok alebo pastu?", "v227e-ps0009")
        assert r.get("intent") == "product_search"

    def test_rtp0005(self):
        r = _chat("Aké produkty potrebujem na Tom Yum polievku?", "v227e-rtp0005")
        assert r.get("intent") == "product_search"


class TestProductSearch0007AndContract2Unaffected:
    def test_ps0007_unchanged(self):
        r = _chat("Chcem miso pastu na polievku.", "v227e-ps0007")
        assert r.get("intent") == "product_search"
        assert len(r.get("products") or []) == 8

    def test_contract2_unchanged(self):
        r = _chat("Ako uvariť Ma Po Tofu?", "v227e-contract2")
        assert r.get("intent") == "recipe"


class TestSushiSessionUnaffected:
    def test_current_turn_and_followup_unchanged(self):
        sid = "v227e-sushi-session"
        r1 = _chat("chcem robit sushi", sid)
        assert r1.get("intent") == "related_products"
        r2 = _chat("aká ryžu?", sid)
        assert r2.get("intent") == "product_search"


class TestOpenDebtUnaffected:
    """quantity/dish-shaped A2 remain untouched - neither contains a
    parseable price constraint."""

    def test_quantity_0001_unchanged(self):
        r = _chat(
            "Potrebujem sriracha omáčku na 20 porcií, aké veľké balenie mi odporúčate?",
            "v227e-quantity0001",
        )
        assert r.get("intent") == "related_products"
        assert len(r.get("products") or []) == 20

    def test_dish_a2_unchanged(self):
        r = _chat("Aké sushi suroviny predávate?", "v227e-disha2")
        assert r.get("intent") == "related_products"


class TestPriceInfoAndSaleUnaffected:
    """A price-information question (no stated budget) and a sale/FAQ
    question must not trigger filtering - extract_price_constraint()
    already returns None for both (V2.27c), re-asserted here at the
    /chat level."""

    def test_price_information_unchanged(self):
        r = _chat("Koľko stojí jazmínová ryža Royal Umbrella 1kg?", "v227e-priceinfo")
        assert r.get("intent") == "product_search"
        assert len(r.get("products") or []) == 2

    def test_sale_faq_unchanged(self):
        r = _chat("Funguje u vás vernostný program so zľavami?", "v227e-faq0010")
        assert r.get("intent") == "faq"
