"""
tests/test_use_case_action_frame_v2_25f.py  -  V2.25f: bounded
product_search_0007 repair via a new, independent USE_CASE_ACTION_FRAME
signal.

Context (V2.25a-f read-only contract review series, docs/query-semantics.md):
the original 13-case "Contract 1" direct-shopping-vs-related_subject debt
was progressively decomposed across V2.24q-z into the Selected-6 subcluster
(fixed in V2.24y - see test_related_subject_direct_guard_v2_24y.py) plus
Contract 2 (recipe_only_0005 - see test_recipe_intent_slovak_uvar_marker.py).
product_search_0007 ("Chcem miso pastu na polievku.") was deliberately left
out of Selected-6 because it relies solely on the generic "chcem " marker,
which V2.24v found collides with the genuine "chcem robit/varit <jedlo>"
use-case-activation idiom ("chcem robit sushi") - no existing signal
(shop_lang, conf_family, wants_shopping_list, is_recipe_intent) can tell
the two apart.

V2.25a-c (read-only) designed and empirically verified the missing signal:
a tiny, independent, word-boundary-matched helper,
_has_use_case_action_frame(), detecting the Slovak "robit/varit/pripravit"
verb stems. V2.25d implemented it, found it functionally correct (target
fixed, 93-DEV counterfactual showing exactly the intended change) but
reverted on a single full-pytest failure - a stale V2.24y scope-lock
assertion in test_related_subject_direct_guard_v2_24y.py that predated
this exact repair and asserted the pre-fix state. V2.25e proved that
assertion was a per-sprint scope boundary, not a behavioral GT contract
(golden requires intent_is:product_search; a direct, already-merged
precedent exists in the same test class for the Contract 2 debt). V2.25f
re-implements the identical production patch and updates exactly that one
stale assertion (renamed, narrowed to the permanent invariant it actually
protects - see TestExcludedSubclustersUntouched::
test_product_search_0007_guard_unaffected in that file), following the
same pattern already used for the Contract 2 sibling test.

The new guard clause is a SEPARATE clause - it does NOT touch
_SELECTED_DIRECT_SHOPPING_MARKERS/_is_selected_direct_shopping_query()
(Selected-6) at all - paired with the existing wants_shopping_list()/
conf_family() exclusions already used by the Selected-6 guard.

Full pytest (2771 passed, 0 failed) was run as a pre-commit gate before
this file was added - see the V2.25f report for the exact baseline/
post-patch comparison. This file locks the contract going forward.
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


class TestHasUseCaseActionFrameHelper:
    """Unit-level contract for the new, independent helper."""

    def test_robit_stem_fires(self):
        assert m._has_use_case_action_frame("chcem robit sushi")

    def test_varit_stem_fires(self):
        assert m._has_use_case_action_frame("chcem variť sushi")

    def test_pripravit_stem_fires(self):
        assert m._has_use_case_action_frame("chcem pripravit Pad Thai")

    def test_conjugated_forms_also_fire(self):
        # Bare-stem, word-boundary matched - catches other conjugations too.
        assert m._has_use_case_action_frame("chcem si robiť sushi")
        assert m._has_use_case_action_frame("budem variť ramen")

    def test_no_action_stem_does_not_fire(self):
        assert not m._has_use_case_action_frame("Chcem miso pastu na polievku.")

    def test_token_boundary_uvarit_does_not_collide_with_varit_stem(self):
        # "uvariť" ("ako uvariť") must NOT be mistaken for the "varit" stem -
        # that would collide with the Contract 2 recipe path. This is the
        # exact reason the helper uses \b word-boundary matching, not a
        # bare substring check.
        assert not m._has_use_case_action_frame("Ako uvariť Ma Po Tofu?")

    def test_does_not_require_chcem(self):
        # The helper itself is a pure action-frame detector, independent
        # of "chcem " - the "chcem " requirement lives in the guard clause,
        # not in this helper. Uses the infinitive "robiť" stem form
        # (bare-stem matched) rather than the "robím" present-tense
        # conjugation, which does not share the "robit" stem prefix after
        # diacritic normalization and is a documented recall limit, not a
        # locked must-match case.
        assert m._has_use_case_action_frame("idem robiť sushi")


class TestProductSearch0007Target:
    """The bounded repair target - golden scenario v222_product_search_0007.
    Golden requires intent_is:product_search, products_nonempty,
    product_title_contains_any:miso pasta (AUTHORITATIVE_DATA, 4 matching
    SKUs in data/products.json)."""

    def test_intent_is_product_search(self):
        r = _chat("Chcem miso pastu na polievku.", "v225f-ps0007")
        assert r.get("intent") == "product_search"

    def test_products_nonempty(self):
        r = _chat("Chcem miso pastu na polievku.", "v225f-ps0007-products")
        assert r.get("products")

    def test_product_title_contains_miso_pasta(self):
        r = _chat("Chcem miso pastu na polievku.", "v225f-ps0007-title")
        titles = " ".join((p.get("title") or "") for p in (r.get("products") or []))
        assert "miso pasta" in titles.lower()


class TestSushiCurrentTurnHardRegression:
    """Mandatory lock: "chcem robit sushi" must stay related_products for
    ITS OWN turn (V2.24v historical collision) - the new guard must never
    fire on this query."""

    def test_chcem_robit_sushi_stays_related_products(self):
        r = _chat("chcem robit sushi", "v225f-sushi-currentturn")
        assert r.get("intent") == "related_products"

    def test_chcem_variz_sushi_stays_related_products(self):
        r = _chat("chcem variť sushi", "v225f-sushi-variz")
        assert r.get("intent") == "related_products"

    def test_sushi_session_followup_unaffected(self):
        sid = "v225f-sushi-session-followup"
        _chat("chcem robit sushi", sid)
        r2 = _chat("aká ryžu?", sid)
        assert r2.get("intent") == "product_search"
        r3 = _chat("a aký ocot?", sid)
        assert r3.get("intent") == "product_search"


class TestOtherActionFrameControls:
    """Other exact V2.25c must-match use-case controls - direct recovery
    must stay blocked (these already route via recipe, unaffected either
    way, but locked here as an explicit regression control)."""

    def test_chcem_robit_pad_thai_unaffected(self):
        r = _chat("chcem robit Pad Thai", "v225f-padthai")
        assert r.get("intent") != "product_search"

    def test_chcem_robit_tom_kha_gai_unaffected(self):
        r = _chat("chcem robit Tom Kha Gai", "v225f-tomkhagai")
        assert r.get("intent") != "product_search"


class TestFaqFalsePositiveControl:
    """The helper itself fires TRUE on this FAQ complaint (raw "robiť"
    substring), but routing stays safe because related_subject is None -
    the guard's own precondition, independent of this patch."""

    def test_raw_helper_fires_true(self):
        assert m._has_use_case_action_frame("V balíku mi chýba produkt, čo mám robiť?")

    def test_routing_stays_faq(self):
        r = _chat("V balíku mi chýba produkt, čo mám robiť?", "v225f-faq-control")
        assert r.get("intent") == "faq"


class TestSelected6Unaffected:
    """All 6 closed V2.24y cases must remain exactly as before - this
    patch is an independent, disjoint guard clause."""

    def test_cd0001(self):
        r = _chat("Aké máte rybacie omáčky?", "v225f-cd0001")
        assert r.get("intent") == "product_search"

    def test_kw0001(self):
        r = _chat("Predávate misky na matcha čaj?", "v225f-kw0001")
        assert r.get("intent") == "product_search"

    def test_ps0005(self):
        r = _chat("Máte v ponuke matcha čaj?", "v225f-ps0005")
        assert r.get("intent") == "product_search"

    def test_ps0006(self):
        r = _chat("Zháňam tofu na prípravu ázijského jedla.", "v225f-ps0006")
        assert r.get("intent") == "product_search"

    def test_ps0009(self):
        r = _chat("Máte wasabi prášok alebo pastu?", "v225f-ps0009")
        assert r.get("intent") == "product_search"

    def test_rtp0005(self):
        r = _chat("Aké produkty potrebujem na Tom Yum polievku?", "v225f-rtp0005")
        assert r.get("intent") == "product_search"


class TestContract2Unaffected:
    def test_ako_uvarit_ma_po_tofu_unchanged(self):
        r = _chat("Ako uvariť Ma Po Tofu?", "v225f-contract2")
        assert r.get("intent") != "related_products"


class TestOpenDebtUnaffected:
    """quantity/budget/dish-shaped A2 remain out of scope - characterized
    as explicit controls, not fixed here."""

    def test_budget_0001_unchanged(self):
        r = _chat("Mám 10 eur, akú rybaciu omáčku si za to môžem kúpiť?", "v225f-budget0001")
        assert r.get("intent") == "related_products"

    def test_quantity_0001_unchanged(self):
        r = _chat(
            "Potrebujem sriracha omáčku na 20 porcií, aké veľké balenie mi odporúčate?",
            "v225f-quantity0001",
        )
        assert r.get("intent") == "related_products"

    def test_dish_shaped_a2_unchanged(self):
        r = _chat("Aké sushi suroviny predávate?", "v225f-disha2")
        assert r.get("intent") == "related_products"


class TestBrandConstraint0005RedundantNoOp:
    """V2.25c found this already correctly routes to product_search via
    an earlier brand-mention guard (detect_mentioned_replacement_brand) -
    this patch's own "chcem " condition would also fire, but related_subject
    is already cleared by that earlier guard before this clause runs."""

    def test_stays_product_search(self):
        r = _chat("Chcem kari pastu, ale nie značku Cock Brand.", "v225f-brand0005")
        assert r.get("intent") == "product_search"
