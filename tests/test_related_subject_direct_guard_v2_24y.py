"""
tests/test_related_subject_direct_guard_v2_24y.py  -  V2.24y: Selected-6
bounded related_subject guard repair.

Context (V2.24q-x read-only contract review series, docs/query-semantics.md):
the original 13-case "Contract 1" population (self-contained direct-shopping
queries incorrectly surviving as related_subject/cross-sell instead of
routing to product_search) was progressively decomposed:

- V2.24r attempted a 13-case fix using (direct marker OR wants_recipe_products())
  as the clearing signal - full pytest revealed 69 failures. Root cause
  (V2.24s): wants_recipe_products() is a POSITIVE signal for *entering*
  related_products/recipe-shopping-list behavior (see the dedicated
  sushi_shopping_core_products()/tom_yum_.../kimchi_ramen_... functions and
  their own regression-lock tests below), never a signal for leaving it.
- V2.24t/u isolated a 7-case subcluster using (direct marker AND NOT
  wants_shopping_list() AND NOT conf_family) instead - still including
  "chcem " in the marker set.
- V2.24v implemented that 7-case fix; full pytest revealed exactly one
  further collision (3 failures, one root cause): "chcem robit sushi" must
  resolve to intent == related_products for ITS OWN turn, not merely
  activate the sushi use case for later turns - and "chcem " cannot be
  told apart from that genuine "chcem robit/varit <jedlo>" use-case-
  activation idiom by any existing signal.
- V2.24w/x removed "chcem " entirely, shrinking the safe population to
  exactly 6 cases (product_search_0007, the only one relying solely on
  "chcem ", moves back out of scope).

This is the bounded V2.24y implementation of that final 6-case contract:

    related_subject
    AND _is_selected_direct_shopping_query(message)   # 5 markers, no "chcem "
    AND NOT wants_shopping_list(message)
    AND NOT _query_resolves_to_confident_product_family(message)

Full pytest (2728 passed, 0 failed) was run as a pre-commit gate before this
file was added - see the V2.24y report for the exact baseline/post-patch
comparison. This file locks the contract going forward.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m
from app.session_state import get_active_use_case


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, limit: int = 8) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


class TestSelectedSixTargets:
    """The exact 6-case contract locked by V2.24x. Each was previously
    misrouted to related_products despite being a self-contained direct
    product/category request - the existing confident-family guard
    (app/main.py ~line 5400) could not clear related_subject for any of
    them because conf_family is False for all 6 (the taxonomy parser
    cannot confidently resolve a bare category word like "rybacia
    omacka"/"matcha" to its own family)."""

    def test_category_discovery_0001(self):
        r = _chat("Aké máte rybacie omáčky?", "v224y-cd0001")
        assert r.get("intent") in ("category_discovery", "product_search")
        assert r.get("products")

    def test_kitchenware_0001(self):
        r = _chat("Predávate misky na matcha čaj?", "v224y-kw0001")
        assert r.get("intent") in ("product_search", "category_discovery")
        assert r.get("products")

    def test_product_search_0005(self):
        r = _chat("Máte v ponuke matcha čaj?", "v224y-ps0005")
        assert r.get("intent") == "product_search"
        titles = " | ".join(p.get("title", "") for p in r.get("products") or [])
        assert "matcha" in titles.lower()

    def test_product_search_0006(self):
        r = _chat("Zháňam tofu na prípravu ázijského jedla.", "v224y-ps0006")
        assert r.get("intent") == "product_search"
        titles = " | ".join(p.get("title", "") for p in r.get("products") or [])
        assert "tofu" in titles.lower()

    def test_product_search_0009(self):
        r = _chat("Máte wasabi prášok alebo pastu?", "v224y-ps0009")
        assert r.get("intent") == "product_search"
        titles = " | ".join(p.get("title", "") for p in r.get("products") or [])
        assert "wasabi" in titles.lower()

    def test_recipe_to_products_0005_mechanism_fixed(self):
        # V2.24r/v/y residual debt (out of this sprint's scope): the
        # guard mechanism is fixed (no longer related_products), but
        # this specific case lands on product_search rather than
        # recipe_to_products/recipe_only - a separate, unrelated
        # downstream routing gap, not re-opened here.
        r = _chat("Aké produkty potrebujem na Tom Yum polievku?", "v224y-rtp0005")
        assert r.get("intent") != "related_products"
        assert r.get("products")


class TestDirectShoppingMarkerHelper:
    """Unit-level audit of the exact 5-marker set authorized by V2.24x -
    no "chcem ", no wants_recipe_products()."""

    def test_exact_marker_set_has_no_chcem(self):
        assert "chcem " not in m._SELECTED_DIRECT_SHOPPING_MARKERS
        assert m._SELECTED_DIRECT_SHOPPING_MARKERS == ("mate ", "predavate", "hladam", "zhanam", "potrebujem")

    def test_mate_marker(self):
        assert m._is_selected_direct_shopping_query("Máte wasabi?")

    def test_predavate_marker(self):
        assert m._is_selected_direct_shopping_query("Predávate misky?")

    def test_hladam_marker(self):
        assert m._is_selected_direct_shopping_query("Hľadám niečo konkrétne.")

    def test_zhanam_marker(self):
        assert m._is_selected_direct_shopping_query("Zháňam tofu.")

    def test_potrebujem_marker(self):
        assert m._is_selected_direct_shopping_query("Potrebujem niečo.")

    def test_chcem_alone_does_not_match(self):
        # The load-bearing V2.24v/w/x exclusion: "chcem " must not be
        # part of this helper at all.
        assert not m._is_selected_direct_shopping_query("Chcem miso pastu na polievku.")
        assert not m._is_selected_direct_shopping_query("chcem robit sushi")

    def test_ownership_mam_is_not_mate(self):
        assert not m._is_selected_direct_shopping_query("Mám kimchi, čo sa k tomu hodí?")


class TestWantsShoppingListExclusion:
    """A direct marker alone must not override genuine shopping-list/
    recipe-companion framing - wants_shopping_list() protects the
    dedicated sushi_shopping_core_products()/tom_yum_.../kimchi_ramen_...
    workflows these phrasings deliberately route into."""

    def test_tom_yum_shopping_list_untouched(self):
        r = _chat("nákupný zoznam na tom yum", "v224y-wsl-tomyum")
        assert r.get("intent") == "related_products"

    def test_kimchi_ramen_shopping_list_untouched(self):
        r = _chat("nákupný zoznam na kimchi ramen", "v224y-wsl-kimchiramen")
        assert r.get("intent") == "related_products"

    def test_ramen_hard_switch_untouched(self):
        r = _chat("Čo potrebujem na ramen?", "v224y-wsl-ramen")
        assert r.get("intent") in ("related_products", "recipe", "basket_completion", "use_case_advice")

    def test_dish_shaped_a2_category_discovery_0004_untouched(self):
        # Out of scope (V2.24s A2 / V2.24t-x "dish-shaped" group) -
        # wants_shopping_list=True here, same architecture as above.
        r = _chat("Aké sushi suroviny predávate?", "v224y-wsl-a2-cd0004")
        assert r.get("intent") == "related_products"

    def test_recipe_to_products_0001_untouched(self):
        r = _chat("Pomôž mi nakúpiť suroviny na Bulgogi.", "v224y-wsl-rtp0001")
        assert r.get("intent") == "related_products"

    def test_recipe_to_products_0002_untouched(self):
        r = _chat("Čo potrebujem kúpiť na Kimchi Jjigae?", "v224y-wsl-rtp0002")
        assert r.get("intent") == "related_products"

    def test_recipe_to_products_0004_untouched(self):
        r = _chat("Potrebujem suroviny na Yakiudon.", "v224y-wsl-rtp0004")
        assert r.get("intent") == "related_products"


class TestConfFamilyExclusion:
    """A direct marker alone must not override a confident-family hit -
    the existing confident-family guard above remains authoritative."""

    def test_quantity_0001_untouched(self):
        # V2.24v/w/x nuance: quantity_0001 has conf_family=True (sriracha
        # resolves confidently) - this condition is exactly what keeps
        # the Selected-6 override from also firing on it, out of scope
        # for this sprint.
        r = _chat(
            "Potrebujem sriracha omáčku na 20 porcií, aké veľké balenie mi odporúčate?",
            "v224y-cf-quantity0001",
        )
        assert r.get("intent") == "related_products"

    def test_bulk_company_quantity_untouched(self):
        r = _chat(
            "Chcem nakupovať ryžu na firmu, koľko kusov odporúčate?",
            "v224y-cf-bulkcompany",
        )
        assert r.get("intent") == "related_products"


class TestChcemRobitSushiHardRegression:
    """The exact V2.24v collision. HARD regression lock: must never be
    reintroduced by broadening the direct-marker set back to include
    "chcem "."""

    def test_current_turn_intent_stays_related_products(self):
        r = _chat("chcem robit sushi", "v224y-sushi-currentturn")
        assert r.get("intent") == "related_products"

    def test_session_activation_and_followup_preserved(self):
        sid = "v224y-sushi-session"
        _chat("chcem robit sushi", sid)
        assert get_active_use_case(m.get_session_memory(sid)) == "sushi"

        r2 = _chat("aká ryžu?", sid)
        titles2 = [p.get("title", "").lower() for p in r2.get("products", [])]
        assert any("sushi" in t or "suši" in t for t in titles2), titles2

        r3 = _chat("a aký ocot?", sid)
        titles3 = [p.get("title", "").lower() for p in r3.get("products", [])]
        assert any("ocot" in t for t in titles3), titles3

    def test_chcem_robit_pad_thai_unaffected(self):
        # Pre-existing, unrelated routing (bare-dish RECIPE_INTENT_MARKERS
        # entry "pad thai") - unchanged by this guard either way.
        r = _chat("chcem robit Pad Thai", "v224y-padthai")
        assert r.get("intent") != "related_products" or r.get("intent") == "recipe"

    def test_chcem_variz_sushi_stays_related_products(self):
        r = _chat("chcem variť sushi", "v224y-variz-sushi")
        assert r.get("intent") == "related_products"


class TestNegativeControls:
    """Inherited V2.24q-x negative-control set: ownership/companion,
    ambiguous, and existing confident-family-direct controls."""

    def test_ownership_mam_kimchi_protected(self):
        r = _chat("Mám kimchi, čo sa k tomu hodí?", "v224y-nc-mamkimchi")
        assert r.get("intent") == "related_products"

    def test_ownership_mam_uz_sriracha_protected(self):
        r = _chat(
            "Mám už sriracha omáčku, čo iné mi odporúčate k rezancom?",
            "v224y-nc-mamsriracha",
        )
        assert r.get("intent") == "related_products"

    def test_ambiguous_niecopikantne_protected(self):
        r = _chat("Dajte mi niečo pikantné.", "v224y-nc-ambiguous")
        assert r.get("intent") == "related_products"

    def test_direct_confident_family_yamasa_unaffected(self):
        r = _chat("Yamasa sójová omáčka", "v224y-nc-yamasa")
        assert r.get("intent") == "product_search"

    def test_direct_confident_family_ryzove_rezance_unaffected(self):
        r = _chat("ryžové rezance", "v224y-nc-ryzoverezance")
        assert r.get("intent") == "product_search"

    def test_direct_confident_family_kokosovy_olej_unaffected(self):
        r = _chat("kokosový olej", "v224y-nc-kokosovyolej")
        assert r.get("intent") == "product_search"


class TestExcludedSubclustersUntouched:
    """Explicit controls for every out-of-scope group locked by
    V2.24u-x: product_search_0007, budget, dish-shaped A2, Contract 2.
    None may be fixed or absorbed by this sprint."""

    def test_product_search_0007_still_related_products(self):
        # The one case removed from Selected-7 to Selected-6 (V2.24w) -
        # it relies solely on "chcem ", now excluded from the marker set.
        r = _chat("Chcem miso pastu na polievku.", "v224y-excl-ps0007")
        assert r.get("intent") == "related_products"

    def test_budget_0001_still_related_products(self):
        r = _chat(
            "Mám 10 eur, akú rybaciu omáčku si za to môžem kúpiť?",
            "v224y-excl-budget0001",
        )
        assert r.get("intent") == "related_products"

    def test_contract_2_recipe_only_0005_untouched(self):
        r = _chat("Ako uvariť Ma Po Tofu?", "v224y-excl-contract2")
        assert r.get("intent") == "related_products"
