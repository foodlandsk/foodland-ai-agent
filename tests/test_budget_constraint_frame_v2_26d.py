"""
tests/test_budget_constraint_frame_v2_26d.py  -  V2.26d: bounded
budget_0001 repair via a new, independent BUDGET_CONSTRAINT_FRAME signal.

Context (V2.26a-d read-only contract review series, docs/query-semantics.md):
after Selected-6 (V2.24y), Contract 2 (recipe_only_0005), and
product_search_0007 (V2.25f) were closed, three debts remained: quantity,
budget, dish-shaped A2. V2.26a selected budget as the narrowest, least
entangled candidate (no shared-signal modification, no sushi/session
overlap, unlike quantity's shared _has_recipe_shopping_language() or
dish-A2's entanglement with the dedicated sushi_shopping_core_products()
workflow).

budget_0001 ("Mám 10 eur, akú rybaciu omáčku si za to môžem kúpiť?") fails
because no existing signal (shop_lang, conf_family, Selected-6 markers,
V2.25f "chcem ") recognizes an absolute EUR budget constraint. V2.26b/c
found that a bare digit immediately followed by "eur" is, on the full
corpus, already a precise and sufficient discriminator - no prefix-word
list ("mam"/"do"/"pod"/"rozpocet") is needed, and it never collides with
the ownership "mam <produkt>" idiom (which never has a digit there) - see
tests/test_substitution_intelligence_v2_16c.py::
TestAlreadyHaveSubjectClauseLocalityFix for the pre-existing, independent
V2.21k fix protecting that same ownership/budget distinction one layer
lower (detect_already_have_subject()).

This signal is ROUTING-ONLY: it does NOT claim returned products respect
the stated budget - golden v222_budget_0001 only scores
intent_is:product_search + products_nonempty, no price-fit invariant.
Wiring filter_products()/_matches_price_range() (app/search.py) into this
chat pipeline is a separate, unauthorized future project.

Full pytest (2799 passed, 0 failed) was run as a pre-commit gate before
this file was added - see the V2.26d report for the exact
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


class TestHasBudgetConstraintFrameHelper:
    """Unit-level contract for the new, independent helper."""

    def test_digit_eur_fires(self):
        assert m._has_budget_constraint_frame("Mám 10 eur, akú rybaciu omáčku si za to môžem kúpiť?")

    def test_do_eur_fires(self):
        assert m._has_budget_constraint_frame("Chcem sriracha omáčku do 3 eur.")

    def test_pod_eur_fires(self):
        assert m._has_budget_constraint_frame("Potrebujem rybaciu omáčku pod 5 eur, značka Megachef.")

    def test_rozpocet_eur_fires(self):
        assert m._has_budget_constraint_frame("Mám rozpočet 5 eur na kari pastu.")

    def test_no_digit_does_not_fire(self):
        assert not m._has_budget_constraint_frame("Mám kimchi, čo sa k tomu hodí?")

    def test_no_eur_does_not_fire(self):
        assert not m._has_budget_constraint_frame("Potrebujem sriracha omáčku na 20 porcií.")


class TestOwnershipMamCollision:
    """The critical discriminator: a bare digit before "eur", never the
    ownership "mam <produkt>" idiom (no digit there)."""

    def test_mam_doma_kimchi_does_not_fire(self):
        assert not m._has_budget_constraint_frame("Mám doma kimchi, čo ešte potrebujem na Kimchi Jjigae?")

    def test_mam_uz_sriracha_does_not_fire(self):
        assert not m._has_budget_constraint_frame("Mám už sriracha omáčku, čo iné mi odporúčate k rezancom?")

    def test_mam_kimchi_cross_sell_does_not_fire(self):
        assert not m._has_budget_constraint_frame("Mám kimchi, čo sa k tomu hodí?")

    def test_faq_kedy_mam_dopravu_does_not_fire(self):
        assert not m._has_budget_constraint_frame("Kedy mám dopravu zadarmo?")

    def test_faq_ak_mam_otazku_does_not_fire(self):
        assert not m._has_budget_constraint_frame("Ako vás môžem kontaktovať, ak mám otázku k objednávke?")


class TestQuantityCollision:
    def test_porcie_does_not_fire(self):
        assert not m._has_budget_constraint_frame(
            "Potrebujem sriracha omáčku na 20 porcií, aké veľké balenie mi odporúčate?"
        )

    def test_litrov_does_not_fire(self):
        assert not m._has_budget_constraint_frame("Koľko balení ryžového octu potrebujem na 5 litrov sushi ryže?")


class TestPriceInformationCollision:
    def test_kolko_stoji_does_not_fire(self):
        assert not m._has_budget_constraint_frame("Koľko stojí jazmínová ryža Royal Umbrella 1kg?")

    def test_kolko_stoji_kokosove_mlieko_does_not_fire(self):
        assert not m._has_budget_constraint_frame("Koľko stojí kokosové mlieko Aroy-D 1000ml?")


class TestRelativePriceCollision:
    def test_lacnejsie_does_not_fire(self):
        assert not m._has_budget_constraint_frame("niečo lacnejšie")


class TestSaleDiscountCollision:
    def test_zlava_faq_does_not_fire(self):
        assert not m._has_budget_constraint_frame("Funguje u vás vernostný program so zľavami?")


class TestDishA2Collision:
    def test_sushi_suroviny_does_not_fire(self):
        assert not m._has_budget_constraint_frame("Aké sushi suroviny predávate?")


class TestSelected6Collision:
    def test_cd0001_does_not_fire(self):
        assert not m._has_budget_constraint_frame("Aké máte rybacie omáčky?")

    def test_kw0001_does_not_fire(self):
        assert not m._has_budget_constraint_frame("Predávate misky na matcha čaj?")

    def test_ps0005_does_not_fire(self):
        assert not m._has_budget_constraint_frame("Máte v ponuke matcha čaj?")

    def test_ps0006_does_not_fire(self):
        assert not m._has_budget_constraint_frame("Zháňam tofu na prípravu ázijského jedla.")

    def test_ps0009_does_not_fire(self):
        assert not m._has_budget_constraint_frame("Máte wasabi prášok alebo pastu?")

    def test_rtp0005_does_not_fire(self):
        assert not m._has_budget_constraint_frame("Aké produkty potrebujem na Tom Yum polievku?")


class TestProductSearch0007AndContract2Collision:
    def test_ps0007_does_not_fire(self):
        assert not m._has_budget_constraint_frame("Chcem miso pastu na polievku.")

    def test_contract2_does_not_fire(self):
        assert not m._has_budget_constraint_frame("Ako uvariť Ma Po Tofu?")


class TestSushiSessionCollision:
    def test_chcem_robit_sushi_does_not_fire(self):
        assert not m._has_budget_constraint_frame("chcem robit sushi")


class TestBudget0001Target:
    """The bounded repair target - golden scenario v222_budget_0001.
    Golden requires intent_is:product_search, products_nonempty - NO
    price-fit invariant (this fix is routing-only, see module docstring)."""

    def test_intent_is_product_search(self):
        r = _chat("Mám 10 eur, akú rybaciu omáčku si za to môžem kúpiť?", "v226d-budget0001")
        assert r.get("intent") == "product_search"

    def test_products_nonempty(self):
        r = _chat("Mám 10 eur, akú rybaciu omáčku si za to môžem kúpiť?", "v226d-budget0001-products")
        assert r.get("products")


class TestBudget0003NonInterference:
    """related_subject is already None for this phrasing - the new
    clause's precondition never applies, so it stays inert."""

    def test_stays_product_search(self):
        r = _chat("Mám rozpočet 5 eur na kari pastu.", "v226d-budget0003")
        assert r.get("intent") == "product_search"


class TestMultiConstraint0003NonInterference:
    """The helper structurally fires TRUE here, but routing stays
    unaffected - related_subject is already cleared by TWO earlier,
    independent guards (the brand-mention guard on "Megachef", and the
    Selected-6 "Potrebujem" marker) before this clause would ever run."""

    def test_helper_fires_true(self):
        assert m._has_budget_constraint_frame("Potrebujem rybaciu omáčku pod 5 eur, značka Megachef.")

    def test_routing_stays_product_search(self):
        r = _chat("Potrebujem rybaciu omáčku pod 5 eur, značka Megachef.", "v226d-mc0003")
        assert r.get("intent") == "product_search"


class TestV221kBudgetControlsRedundantNoOp:
    """Pre-existing, independent controls (test_substitution_intelligence_
    v2_16c.py) for other budget-shaped queries that already pass via
    conf_family=True - the new clause's helper fires TRUE structurally,
    but conf_family already clears related_subject earlier, so the new
    clause stays inert. Locked here to prove this patch does not disturb
    them."""

    def test_sushi_rice_budget_query_unaffected(self):
        r = _chat("Mam len 10 eur, kolko susi ryze si za to mozem kupit?", "v226d-v221k-sushirice")
        assert r.get("intent") == "product_search"

    def test_gochujang_budget_helper_fires_but_already_have_stays_none(self):
        q = "Mam len 5 eur, aky lacny gochujang mi odporucas?"
        assert m._has_budget_constraint_frame(q)
        assert m.detect_already_have_subject(q) is None
