"""
tests/test_special3_recipe_shopping_routing_v2_29d.py  -  V2.29d Special-3
RECIPE_SHOPPING routing flip & session convergence.

Activates app.recipe_shopping.SPECIAL3_SHOPPING_DEFINITIONS (sushi/tom_yum/
kimchi_ramen, ported inert in V2.29c) by merging it into the live
app.main.RECIPE_SHOPPING_CORE_QUERIES, and removes the special-3 exclusion
in app.workflow_executor.execute_recipe() that used to force these three
dishes to fall back to their legacy per-dish builders instead of the
generic V2.8 build_recipe_shopping_plan() pipeline every other curated
dish already uses.

Covers: cross-dish consistency, the routing flip itself, session
continuity, the informational-question guard, direct-product-search
protection, the already-have boundary, price/servings compatibility, and
negation. See tests/test_recipe_shopping_special3_v2_29c.py for the data-
parity/precision-guard evidence (unaffected by this sprint) and its
TestRoutingImmutability class for the specific pre/post routing-contract
documentation of the five superseded assertions.
"""
import os
import sys
from pathlib import Path

import pytest

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


SPECIAL3_DISH_PHRASES = {
    "sushi": "sushi",
    "tom_yum": "tom yum",
    "kimchi_ramen": "kimchi ramen",
}
GENERIC_REFERENCE_DISHES = ["pad thai", "tom kha", "satay", "pho"]


class TestSpecial3DataActivation:
    """Section 5/6 - the V2.29c-ported data is live in the dict the
    generic pipeline actually reads, for all three dishes."""

    def test_special3_keys_present_in_live_dict(self):
        for dish_id in SPECIAL3_DISH_PHRASES:
            assert dish_id in m.RECIPE_SHOPPING_CORE_QUERIES

    def test_special3_dishes_reachable_in_recipe_graph(self):
        for dish_id in SPECIAL3_DISH_PHRASES:
            assert dish_id in m.recipe_graph_index.dishes_by_id


class TestSpecial3RoutingFlip:
    """Section 9/35 - dish-shopping/category requests for special-3 now
    produce the canonical recipe_to_products/RECIPE_SHOPPING contract."""

    @pytest.mark.parametrize("dish_id,phrase", list(SPECIAL3_DISH_PHRASES.items()))
    def test_supplier_question_routes_to_recipe_shopping(self, dish_id, phrase):
        r = _chat(f"Aké {phrase} suroviny predávate?", f"v229d-flip-supplier-{dish_id}")
        assert r.get("intent") == "recipe_to_products"
        assert r.get("workflow_id") == "RECIPE_SHOPPING"
        assert r.get("products")
        plan = r.get("recipe_shopping_plan") or {}
        assert plan.get("dish_id") == dish_id

    @pytest.mark.parametrize("dish_id,phrase", list(SPECIAL3_DISH_PHRASES.items()))
    def test_shopping_list_phrase_routes_to_recipe_shopping(self, dish_id, phrase):
        r = _chat(f"Nákupný zoznam na {phrase}.", f"v229d-flip-shoplist-{dish_id}")
        assert r.get("intent") == "recipe_to_products"
        assert r.get("workflow_id") == "RECIPE_SHOPPING"
        assert r.get("products")


class TestSessionConvergence:
    """Section 14-23/41-42 - active_recipe is established and the
    "Co este potrebujem?" follow-up resolves against it, same as generic
    RECIPE_SHOPPING dishes."""

    @pytest.mark.parametrize("dish_id,phrase", list(SPECIAL3_DISH_PHRASES.items()))
    def test_two_turn_followup(self, dish_id, phrase):
        sid = f"v229d-session-{dish_id}"
        r1 = _chat(f"Nákupný zoznam na {phrase}.", sid)
        assert r1.get("intent") == "recipe_to_products"
        assert r1.get("workflow_id") == "RECIPE_SHOPPING"
        r2 = _chat("Čo ešte potrebujem?", sid)
        assert r2.get("workflow_id") == "RECIPE_SHOPPING"
        assert r2.get("products"), "no 'nemam aktivny nakupny zoznam' fallback expected"

    def test_servings_session_composition(self):
        sid = "v229d-session-servings-sushi"
        r1 = _chat("Nákupný zoznam na sushi pre 6 ľudí.", sid)
        plan = r1.get("recipe_shopping_plan") or {}
        assert plan.get("requested_servings") == 6
        for section in plan.get("sections", {}).values():
            for ing in section:
                assert ing.get("quantity") is None, "no ingredient quantity should be fabricated"
        r2 = _chat("Čo ešte potrebujem?", sid)
        assert r2.get("workflow_id") == "RECIPE_SHOPPING"
        assert r2.get("products")


class TestPriceCompatibility:
    """Section 19/43/67 - price_constraint stays a per-product hard
    eligibility ceiling after the flip, for all three dishes."""

    @pytest.mark.parametrize(
        "dish_id,phrase,ceiling",
        [("sushi", "sushi", 10.0), ("tom_yum", "Tom Yum", 10.0), ("kimchi_ramen", "Kimchi Ramen", 10.0)],
    )
    def test_price_ceiling_respected(self, dish_id, phrase, ceiling):
        r = _chat(f"Nákupný zoznam na {phrase} do {int(ceiling)} eur.", f"v229d-price-{dish_id}")
        assert r.get("intent") == "recipe_to_products"
        assert r.get("workflow_id") == "RECIPE_SHOPPING"
        for product in r.get("products") or []:
            price = product.get("effective_price")
            assert price is not None and price <= ceiling, (
                f"{dish_id}: {product.get('title')} at {price} exceeds ceiling {ceiling}"
            )


class TestInformationalBoundary:
    """Section 11-13/32-33/39/65 - pure "what is <dish>?" questions never
    enter RECIPE_SHOPPING, for special-3 specifically (the mandatory gate)."""

    @pytest.mark.parametrize("phrase", ["sushi", "Tom Yum", "Kimchi Ramen"])
    def test_what_is_dish_not_recipe_shopping(self, phrase):
        r = _chat(f"Čo je {phrase}?", f"v229d-info-{hash(phrase) % 10000}")
        assert r.get("workflow_id") != "RECIPE_SHOPPING"


class TestDirectProductSearchBoundary:
    """Section 10/40/66 - a direct product mention stays product_search,
    never diverted into the recipe-shopping workflow."""

    @pytest.mark.parametrize(
        "text", ["Chcem sushi ryžu.", "Chcem ramen rezance.", "Chcem kimchi."],
    )
    def test_direct_product_phrase_stays_product_search(self, text):
        r = _chat(text, f"v229d-dps-{hash(text) % 10000}")
        assert r.get("intent") == "product_search"


class TestAlreadyHaveBoundary:
    """Section 20-23/34/64 - already-have phrasing for sushi keeps using
    BASKET_COMPLETION (Option 1: preserve existing precedence) and stays
    useful (recognizes the named ingredient), not an empty/generic plan."""

    @pytest.mark.parametrize(
        "text", [
            "Mám nori, čo ešte potrebujem na sushi?",
            "Mám ryžový ocot, čo ešte potrebujem na sushi?",
        ],
    )
    def test_already_have_sushi_uses_basket_completion(self, text):
        r = _chat(text, f"v229d-alreadyhave-{hash(text) % 10000}")
        assert r.get("intent") == "basket_completion"
        assert r.get("workflow_id") == "BASKET_COMPLETION"
        assert r.get("products"), "already-have follow-up must not return an empty result"

    def test_bare_shopping_question_without_already_have_goes_recipe_shopping(self):
        # Section 33/34 - "Co potrebujem na sushi?" carries no already-have
        # marker ("mam"/"uz mam"/"mam doma") at all, so it must NOT fall
        # into BASKET_COMPLETION on lexical overlap alone (the pre-V2.29d
        # bug this routing flip incidentally closes for sushi specifically -
        # see docstring Section 33). It must canonicalize to RECIPE_SHOPPING.
        r = _chat("Čo potrebujem na sushi?", "v229d-no-already-have-sushi")
        assert r.get("intent") == "recipe_to_products"
        assert r.get("workflow_id") == "RECIPE_SHOPPING"


class TestNegationBoundary:
    """Section 24 - declining the recipe prose still yields a non-empty
    product result; intent naming is not required to change."""

    def test_negated_recipe_request_still_returns_products(self):
        r = _chat("Nechcem recept, chcem iba produkty na sushi.", "v229d-negation-sushi")
        assert r.get("products")


class TestCrossDishConsistency:
    """Section 36-38 - special-3 plus a sample of generic dishes behave
    consistently; no unexplained third routing outcome remains for the
    bare shopping-intent template set."""

    @pytest.mark.parametrize("phrase", list(SPECIAL3_DISH_PHRASES.values()) + ["pad thai", "tom kha"])
    def test_supplier_question_template(self, phrase):
        r = _chat(f"Aké {phrase} suroviny predávate?", f"v229d-cross-supplier-{hash(phrase) % 10000}")
        assert r.get("intent") == "recipe_to_products"
        assert r.get("workflow_id") == "RECIPE_SHOPPING"
        assert r.get("products")

    @pytest.mark.parametrize("phrase", list(SPECIAL3_DISH_PHRASES.values()) + ["pad thai"])
    def test_shopping_list_template(self, phrase):
        r = _chat(f"Nákupný zoznam na {phrase}.", f"v229d-cross-shoplist-{hash(phrase) % 10000}")
        assert r.get("intent") == "recipe_to_products"
        assert r.get("workflow_id") == "RECIPE_SHOPPING"

    @pytest.mark.parametrize("phrase", list(SPECIAL3_DISH_PHRASES.values()) + ["pad thai"])
    def test_co_potrebujem_template_has_no_unexplained_third_outcome(self, phrase):
        r = _chat(f"Čo potrebujem na {phrase}?", f"v229d-cross-copotrebujem-{hash(phrase) % 10000}")
        assert r.get("workflow_id") in ("RECIPE_SHOPPING", "BASKET_COMPLETION")
        if r.get("workflow_id") == "BASKET_COMPLETION":
            pytest.fail(
                f"{phrase!r} fell into BASKET_COMPLETION with no already-have evidence in the message"
            )

    @pytest.mark.parametrize("phrase", list(SPECIAL3_DISH_PHRASES.values()) + ["pad thai"])
    def test_session_followup_template(self, phrase):
        sid = f"v229d-cross-followup-{hash(phrase) % 10000}"
        _chat(f"Nákupný zoznam na {phrase}.", sid)
        r2 = _chat("Čo ešte potrebujem?", sid)
        assert r2.get("workflow_id") == "RECIPE_SHOPPING"
        assert r2.get("products")
