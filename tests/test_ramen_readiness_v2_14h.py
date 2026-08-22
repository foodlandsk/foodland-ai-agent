"""
tests/test_ramen_readiness_v2_14h.py  -  V2.14h: RAMEN_USE_CASE_LIVE_WITH_LIMITATIONS.

Ramen was re-audited against current HEAD (not carried over from V2.14c's
original exclusion by assumption) and made live in app.use_case_advice,
reusing only already-proven, unmodified mechanisms:
- the same (family, subfamily) roles app.cross_sell.roles_for_recipe("ramen")
  has resolved since V2.8/V2.14c: instant_noodles, miso, soy_sauce, wakame.
- the same "na X"/"pre X" framing-preposition gate every other live use
  case (sushi/pho/pad_thai/tom_kha/kari) already goes through.
- the same negation/allergen/recipe-shopping/companion-request precedence
  the cascade already applies to every other live use case.

No new routing hack, no basket_completion change (basket readiness is an
independent dimension - see
tests/test_basket_completion_v2_14e.py::TestBasketV1EligibleUseCases::test_ramen_not_eligible,
still true and untouched by this sprint).

dashi was initially excluded (3 real catalog SKUs existed but were
taxonomically UNKNOWN - no FamilyRule, so including it would have meant
guessing a role from unclassified evidence). A follow-up authored a
dedicated "dashi" FamilyRule (app/taxonomy.py, family=stock/subfamily=dashi)
with its own blast-radius review (3 products UNKNOWN -> MEDIUM, 0 other
products touched), then wired the resulting DATA_DERIVED/MEDIUM evidence
into this module's ramen role table - see TestRamenRoleResolution.test_dashi_role.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.basket_completion as bc
import app.main as m
import app.use_case_advice as uca
from app.recommendation_evidence import PROVENANCE_DATA_DERIVED


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, limit: int = 8) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


# --- resolution: use case + all 4 roles -------------------------------------

class TestRamenUseCaseResolution:
    def test_ramen_is_live(self):
        assert "ramen" in uca.LIVE_USE_CASES

    def test_resolves_from_framed_message(self):
        assert uca.resolve_use_case("rezance na ramen") == "ramen"
        assert uca.resolve_use_case("co pouzit pre ramen") == "ramen"

    def test_bare_product_name_without_framing_does_not_resolve(self):
        assert uca.resolve_use_case("ramen rezance") is None


class TestRamenRoleResolution:
    def test_noodle_role(self):
        role = uca.resolve_role("ramen", "ake rezance na ramen")
        assert role is not None and role.canonical_subfamily == "instant_noodles"

    def test_miso_role(self):
        role = uca.resolve_role("ramen", "aku miso pastu na ramen")
        assert role is not None and role.canonical_subfamily == "miso"

    def test_soy_sauce_role(self):
        role = uca.resolve_role("ramen", "aku omacku na ramen")
        assert role is not None and role.canonical_subfamily == "soy_sauce"

    def test_wakame_role(self):
        role = uca.resolve_role("ramen", "wakame na ramen")
        assert role is not None and role.canonical_subfamily == "wakame"

    def test_dashi_role(self):
        # A dashi FamilyRule (family=stock, subfamily=dashi) was authored
        # as a V2.14h follow-up, with its own blast-radius review (3 real
        # catalog SKUs UNKNOWN -> MEDIUM, 0 other products touched) -
        # dashi now has the same DATA_DERIVED/MEDIUM evidence tier as
        # miso/soy_sauce/wakame and is a real, resolvable role here.
        role = uca.resolve_role("ramen", "dashi na ramen")
        assert role is not None and role.canonical_subfamily == "dashi"
        assert role.canonical_family == "stock"
        assert role.provenance == PROVENANCE_DATA_DERIVED

    def test_bare_use_case_no_role_returns_none(self):
        assert uca.resolve_role("ramen", "chcem nieco na ramen") is None


# --- end-to-end: role advice now reaches use_case_advice --------------------

class TestRamenRoleAdviceEndToEnd:
    def test_noodle_role_advice(self):
        r = _chat("ake rezance na ramen", "v214h-noodle")
        assert r.get("intent") == "use_case_advice"
        assert r.get("use_case_decision") == "RECOMMEND"
        assert len(r.get("products") or []) > 0

    def test_dashi_role_advice(self):
        r = _chat("aky dashi na ramen?", "v214h-dashi")
        assert r.get("intent") == "use_case_advice"
        assert r.get("use_case_decision") == "RECOMMEND"
        titles = [p.get("title", "").lower() for p in (r.get("products") or [])]
        assert any("dashi" in t for t in titles)

    def test_soy_sauce_role_advice_was_broken_before_v2_14h(self):
        # Real, reproduced-before-fix defect: this phrasing used to fall
        # through to a generic instant_noodles product-search dump
        # ("Mame 79 produktov v kategorii Instantne rezance"), which does
        # not answer a sauce question at all.
        r = _chat("aku omacku na ramen?", "v214h-soy")
        assert r.get("intent") == "use_case_advice"
        assert r.get("use_case_decision") == "RECOMMEND"

    def test_miso_role_advice(self):
        r = _chat("aku miso pastu na ramen?", "v214h-miso")
        assert r.get("intent") == "use_case_advice"
        assert r.get("use_case_decision") == "RECOMMEND"

    def test_unmodeled_role_defers_honestly_not_fabricated(self):
        # "zelenina" (vegetable) has no role in the table - correctness
        # over coverage: this must defer, not invent a vegetable role.
        r = _chat("aku zeleninu do ramenu?", "v214h-vegetable")
        assert r.get("intent") != "use_case_advice"


# --- protected precedence: this module must not hijack other paths ---------

class TestRamenPrecedenceProtections:
    def test_bare_product_name_not_hijacked(self):
        r = _chat("cerstve ramen rezance", "v214h-bare")
        assert r.get("intent") != "use_case_advice"

    def test_recipe_shopping_list_framing_defers_to_recipe_shopping(self):
        # app.recipe_shopping (V2.8) already owns this phrasing via
        # RECIPE_SHOPPING_CORE_QUERIES["ramen"] - unmodified by V2.14h.
        r = _chat("co potrebujem na ramen", "v214h-recipe")
        assert r.get("intent") != "use_case_advice"

    def test_rt0004_style_companion_request_not_hijacked(self):
        r = _chat("suvisiace produkty k ramen rezanciam", "v214h-rt0004")
        assert r.get("intent") == "related_products"

    def test_negation_defers_not_recommends_excluded_role(self):
        r = _chat("nie sojovu omacku na ramen, mam neco ine?", "v214h-negation")
        assert r.get("intent") != "use_case_advice"

    def test_allergen_safety_outranks_use_case_advice(self):
        r = _chat("sojova omacka bez soje na ramen", "v214h-allergen")
        assert r.get("intent") == "allergen_safety"
        assert r.get("products") == []


# --- independence: basket readiness is a separate dimension ----------------

class TestRamenBasketIndependence:
    def test_ramen_still_not_basket_v1_eligible(self):
        # Use-case advice going live must NOT auto-expand basket
        # eligibility (V2.14h Section 20 mandate) - ramen's basket
        # behavior continues to run entirely through the pre-existing
        # V2.8 recipe_shopping path, unmodified by this sprint.
        assert "ramen" not in bc.BASKET_V1_ELIGIBLE_USE_CASES

    def test_recipe_shopping_list_still_produces_a_plan(self):
        r = _chat("co potrebujem na ramen", "v214h-basket-indep")
        assert len(r.get("products") or []) > 0


# --- evidence provenance safety ---------------------------------------------

class TestRamenEvidenceProvenance:
    def test_all_ramen_roles_are_data_derived_not_llm_judgment(self):
        for role_evidence in uca._ROLE_TABLE["ramen"]:
            assert role_evidence.provenance == PROVENANCE_DATA_DERIVED

    def test_unknown_taxonomy_product_never_used_as_ramen_evidence(self):
        role = uca.resolve_role("ramen", "ake rezance na ramen")
        candidates = uca.generate_candidates(role, m.products, m.product_taxonomy_index)
        from app.taxonomy import get_taxonomy
        for product in candidates:
            info = get_taxonomy(m.product_taxonomy_index, product.id)
            assert info is not None and info.confidence in ("HIGH", "MEDIUM")
