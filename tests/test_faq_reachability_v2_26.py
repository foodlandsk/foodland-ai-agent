"""
tests/test_faq_reachability_v2_26.py  -  V2.26 FAQ-import reachability gap
closure.

The 2026-10-02 FAQ import (V2.25) added 26 new FAQ records to data/
knowledge.json, but only the data was imported - roughly 15 of the new
questions were never reachable via app.main.is_faq_intent()'s marker
gate (or app.session_state.is_contact_query()), so a customer asking
them in those exact words would never reach the FAQ answer at all (the
record sits in the knowledge base, correctly findable via
best_direct_faq_answer() directly, but the OUTER gate in _chat_impl()
never lets the query reach that call). This closure adds narrow,
specific markers/conjunctions for each gap, following the same
discipline as every prior FAQ_INTENT_MARKERS addition in this file's
history: a bare word only when confirmed safe alone (0 blast-radius
hits against data/products.json title+description+product_type+brand),
otherwise a conjunction of the question's own distinguishing words.

Each fix was iterated at least once after an initial version was found,
via direct adversarial testing, to swallow a genuine commerce/product
question into FAQ with 0 products - documented inline at each site in
app/main.py. This test file locks both directions: the target FAQ
question now resolves, and the adversarial collision it was initially
found to cause does not.

Also covers two related fixes from the same investigation:
- app.main.best_direct_faq_answer()'s single-SKU exclusion guard (added
  in V2.25 to stop new Kikkoman-specific FAQ entries from false-matching
  unrelated English queries via the EN-SK ingredient-word bridge) was
  keyed on the wrong signal (FAQ_scope text, which several GENERAL
  process answers also carry as an unrelated compliance caveat) and
  wrongly excluded FL-FAQ-038/039 too - re-keyed onto the question's own
  brand name ("kikkoman") instead.
- app.session_state._CONTACT_TOPIC_PHRASE_MARKERS gained "kontaktuj" (the
  verb stem) for FL-FAQ-006's phrasing.
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


class TestReachabilityFixes:
    """Each previously-unreachable new FAQ question now resolves to the
    faq intent."""

    def test_how_to_order_meta_question(self):
        r = _chat("Ako môžem na Foodlande objednať tovar?", "v226-order-meta")
        assert r.get("intent") == "faq"

    def test_stock_check_process_question(self):
        r = _chat("Ako zistím, či je konkrétny produkt skladom?", "v226-stock-process")
        assert r.get("intent") == "faq"

    def test_missing_item_in_package(self):
        r = _chat("V balíku mi chýba produkt, čo mám robiť?", "v226-missing-item")
        assert r.get("intent") == "faq"

    def test_received_wrong_product(self):
        r = _chat("Dostal som iný produkt, než som si objednal. Ako postupovať?", "v226-wrong-product")
        assert r.get("intent") == "faq"

    def test_forgot_password(self):
        r = _chat("Zabudol som heslo, ako ho obnovím?", "v226-password")
        assert r.get("intent") == "faq"

    def test_how_to_learn_about_promotions(self):
        r = _chat("Ako sa dozviem o akciách a zľavách?", "v226-promotions")
        assert r.get("intent") == "faq"

    def test_gift_vouchers_availability(self):
        r = _chat("Predáva Foodland darčekové poukazy?", "v226-vouchers")
        assert r.get("intent") == "faq"

    def test_what_is_foodland(self):
        r = _chat("Čo je Foodland?", "v226-what-is")
        assert r.get("intent") == "faq"

    def test_since_when_operating(self):
        r = _chat("Odkedy Foodland pôsobí na Slovensku?", "v226-since-when")
        assert r.get("intent") == "faq"

    def test_contact_eshop_support(self):
        r = _chat("Ako kontaktujem podporu e-shopu?", "v226-contact-support")
        assert r.get("intent") == "faq"

    def test_what_to_state_for_availability_question(self):
        r = _chat("Čo mám uviesť pri otázke na dostupnosť?", "v226-availability-info")
        assert r.get("intent") == "faq"

    def test_where_to_enter_discount_coupon(self):
        r = _chat("Kde zadám zľavový kupón?", "v226-coupon")
        assert r.get("intent") == "faq"

    def test_confirmation_email_did_not_arrive(self):
        r = _chat("Neprišiel mi potvrdzovací e-mail. Čo mám spraviť?", "v226-confirm-email")
        assert r.get("intent") == "faq"

    def test_buying_as_a_company(self):
        r = _chat("Môžem nakupovať na firmu?", "v226-company-buy")
        assert r.get("intent") == "faq"

    def test_change_address_after_ordering(self):
        r = _chat("Môžem zmeniť adresu po objednaní?", "v226-change-address")
        assert r.get("intent") == "faq"

    def test_apple_pay_google_pay(self):
        r = _chat("Podporujete Apple Pay alebo Google Pay?", "v226-apple-google-pay")
        assert r.get("intent") == "faq"

    def test_expiry_date_of_received_package(self):
        r = _chat("Aký dátum trvanlivosti má balenie, ktoré dostanem?", "v226-expiry-date")
        assert r.get("intent") == "faq"


class TestReachabilityFixesDoNotOvertrigger:
    """Each marker/conjunction above was iterated at least once after
    direct adversarial testing found it swallowing a genuine commerce/
    product question into FAQ with 0 products - locked here so a future
    change can't silently reintroduce any of them."""

    def test_explicit_order_of_named_product_not_swallowed(self):
        r = _chat("Chcem si objednať jazmínovú ryžu FOODLAND 18kg", "v226-neg-order-product")
        assert r.get("intent") != "faq"
        assert len(r.get("products") or []) > 0

    def test_explicit_order_of_named_sauce_not_swallowed(self):
        r = _chat("Chcem objednať sójovú omáčku KIKKOMAN", "v226-neg-order-sauce")
        assert r.get("intent") != "faq"

    def test_stock_question_for_named_product_not_swallowed(self):
        r = _chat("Je kokosové mlieko skladom aj vo veľkom balení?", "v226-neg-stock-product")
        assert r.get("intent") != "faq"

    def test_bulk_company_product_question_not_swallowed(self):
        r = _chat("Chcem nakupovať ryžu na firmu, koľko kusov odporúčate?", "v226-neg-company-bulk")
        assert r.get("intent") != "faq"
        assert len(r.get("products") or []) > 0

    def test_stock_availability_by_date_for_named_product_not_swallowed(self):
        r = _chat("Odkedy máte skladom FOODLAND ryžu?", "v226-neg-stock-since")
        assert r.get("intent") != "faq"

    def test_product_recommendation_phrased_with_dozviem_not_swallowed(self):
        r = _chat("Dozviem sa, aká ryža je najlepšia na sushi?", "v226-neg-dozviem-product")
        assert r.get("intent") != "faq"

    def test_general_shelf_life_product_browsing_not_swallowed(self):
        r = _chat(
            "Ukáž mi produkty na dlhú trvanlivosť, aký je ich dátum trvanlivosti?",
            "v226-neg-shelf-life-browse",
        )
        assert r.get("intent") != "faq"
        assert len(r.get("products") or []) > 0


class TestSingleSkuExclusionGuardStaysCorrect:
    """app.main.best_direct_faq_answer()'s single-SKU exclusion guard is
    keyed on the question's own brand name (not FAQ_scope, which several
    unrelated general-process answers also carry) - this locks both
    sides of that distinction."""

    def test_kikkoman_specific_question_still_excluded(self):
        # Single-SKU question (names a specific Kikkoman product) -
        # must NOT resolve via the general FAQ scoring loop.
        answer = m.best_direct_faq_answer(
            "Je sójová omáčka KIKKOMAN 1000 ml bezlepková?", m.knowledge
        )
        assert answer is None

    def test_general_stock_check_process_question_still_included(self):
        answer = m.best_direct_faq_answer(
            "Ako zistím, či je konkrétny produkt skladom?", m.knowledge
        )
        assert answer is not None

    def test_general_expiry_date_process_question_still_included(self):
        answer = m.best_direct_faq_answer(
            "Aký dátum trvanlivosti má balenie, ktoré dostanem?", m.knowledge
        )
        assert answer is not None

    def test_english_negative_controls_still_clean(self):
        # Regression guard for the EN-SK ingredient-word bridge collision
        # this guard exists to prevent in the first place (V2.25).
        for msg in (
            "Do you sell soy sauce?",
            "What country is this fish sauce from?",
            "I want to return this and get a replacement fish sauce instead",
        ):
            assert m.best_direct_faq_answer(msg, m.knowledge) is None, msg
