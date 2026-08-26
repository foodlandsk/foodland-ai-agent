"""
tests/test_conversational_informational_followup_v2_16a.py  -  V2.16a
CONVERSATIONAL CONTEXT & INFORMATIONAL FOLLOW-UP EXPANSION.

V2.16a extends V2.15c's NON_COMMERCE_CONTEXTUAL_FOLLOWUP mechanism
(originally store_location-only) to the payment-methods topic, and
characterizes/locks the current, evidence-audited state of five other
informational topics (opening_hours, contact, delivery, pickup, payment)
rather than assuming they all need (or already have) follow-up support.

Audit findings (V2.16a characterization against HEAD 5c18062), reproduced
by tests below rather than merely asserted:

- store_location: LIVE (unchanged from V2.15c; regression-locked here).
- delivery, pickup: the sprint's own target phrasings ("Koľko stojí
  doprava?", "A osobný odber?") ALREADY resolve correctly TODAY,
  independent of any session-context mechanism - "doprav"/"odber" are
  themselves existing app.main.FAQ_INTENT_MARKERS entries, so these
  messages independently trigger the normal FAQ path (position #4 in the
  routing cascade) on their own merits. No new code was needed or added
  for these two topics; the tests below regression-lock the ALREADY-LIVE
  behavior rather than introduce a new mechanism for it (Section 26 -
  do not claim credit for pre-existing behavior).
- payment: "Da sa kartou?" is likewise already independently FAQ-matched
  ("kartou" is a marker). The one REAL, reproduced gap: a follow-up
  naming a SPECIFIC payment method not covered by FAQ_INTENT_MARKERS
  (e.g. "A Apple Pay?") previously fell through the entire cascade into
  commerce product search, which fuzzy-matched "apple" against unrelated
  catalog items (e.g. "Lepkavá ryža APPLE BRAND 2,27kg" - confirmed via
  reproduction against unmodified HEAD). This is the one capability
  V2.16a actually adds new code for: app.session_state.
  looks_like_payment_method_followup() + a second branch in app/main.py's
  existing V2.15c fallback block, at the exact same last-resort position,
  reusing the exact same last_informational_question field (no new
  session-state field, no new topic enum - see the function's own
  docstring for the full rationale).
- opening_hours, contact: reproduced PRE_EXISTING GAP, unchanged from the
  V2.15c audit (docs/noncommerce-context-followup-v2.15c.md) - the
  INITIAL question ("Kedy máte otvorené?", "Ako vás môžem kontaktovať?")
  does not reach the FAQ cascade at all (no FAQ_INTENT_MARKERS entry
  matches "otvoren"/"hodin"/"kontakt"/"telefon"). V2.16a explicitly did
  NOT add markers for these: a blast-radius check against
  data/products.json found "otvoren" collides with real product
  description text ("po otvorení" storage/usage instructions on 5+
  catalog items, e.g. Kikkoman Teriyaki BBQ omáčka), which would risk
  hijacking a legitimate storage-instruction question into a wrong FAQ
  answer (Section 26/46 - a fix that improves one topic but steals an
  unrelated query is a failed fix). Per Section 26, NOT_REACHED_PRE_
  EXISTING_GAP is an explicitly valid outcome; these are characterized,
  not silently ignored, and are NOT claimed as V2.16a follow-up
  capabilities (Section 27 - no capability may claim follow-up support
  whose initial question cannot reliably resolve).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m
from app.search import normalize


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, limit: int = 8) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


STORE_QUESTION = "Kde sa nachadza kamenna predajna?"
PAYMENT_QUESTION = "Ako mozem zaplatit?"
HOURS_QUESTION = "Kedy mate otvorene?"
CONTACT_QUESTION = "Ako vas mozem kontaktovat?"
DELIVERY_QUESTION = "Dorucujete do Ceska?"
PICKUP_QUESTION = "Mozem si tovar vyzdvihnut osobne?"


# ---------------------------------------------------------------------------
# 1-2: store_location - regression lock (permanent test matrix item 1-2,
# unchanged behavior, already covered by test_noncommerce_context_followup_
# v2_15c.py; re-locked here as the V2.16a "still LIVE after this sprint's
# changes" control).
# ---------------------------------------------------------------------------

class TestStoreLocationRegression:
    def test_store_to_maps_followup_still_works(self):
        sid = "v216a-store-maps"
        _chat(STORE_QUESTION, sid)
        r = _chat("Posli mi mapu.", sid)
        assert r.get("intent") == "faq"
        assert "Stará Vajnorská 3308/19" in r.get("answer", "")
        assert "maps.app.goo.gl/3tFJ4P6w2pj88xAP8" in r.get("answer", "")

    def test_store_address_wording_variant(self):
        sid = "v216a-store-variant"
        _chat("Kde mate predajnu?", sid)
        r = _chat("Ako sa tam dostanem?", sid)
        assert r.get("intent") == "faq"
        assert "Stará Vajnorská" in r.get("answer", "")


# ---------------------------------------------------------------------------
# 3-4: opening_hours - PRE_EXISTING_GAP characterization (not a V2.16a
# regression - proven not to reach FAQ at all, with or without a prior
# turn).
# ---------------------------------------------------------------------------

class TestOpeningHoursPreExistingGap:
    """PRE_EXISTING_GAP: FAQ_INTENT_MARKERS has no entry matching
    "otvoren"/"hodin", so is_faq_intent() is False and the query never
    reaches best_direct_faq_answer/best_faq_answer at all - confirmed by
    intent != "faq" on the bare initial question. Saturday/Sunday
    follow-ups therefore cannot be evaluated as follow-ups: there is no
    informational topic ever established to follow up on."""

    def test_initial_hours_question_does_not_reach_faq(self):
        r = _chat(HOURS_QUESTION, "v216a-hours-initial")
        assert r.get("intent") != "faq"

    def test_saturday_followup_stays_pre_existing_gap(self):
        sid = "v216a-hours-saturday"
        _chat(HOURS_QUESTION, sid)
        r = _chat("A v sobotu?", sid)
        assert r.get("intent") != "faq"

    def test_sunday_followup_stays_pre_existing_gap(self):
        sid = "v216a-hours-sunday"
        _chat(HOURS_QUESTION, sid)
        r = _chat("A v nedelu?", sid)
        assert r.get("intent") != "faq"


# ---------------------------------------------------------------------------
# 5: contact - PRE_EXISTING_GAP characterization.
# ---------------------------------------------------------------------------

class TestContactPreExistingGap:
    def test_initial_contact_question_does_not_reach_faq(self):
        r = _chat(CONTACT_QUESTION, "v216a-contact-initial")
        assert r.get("intent") != "faq"

    def test_phone_followup_stays_pre_existing_gap(self):
        sid = "v216a-contact-phone"
        _chat(CONTACT_QUESTION, sid)
        r = _chat("Posli mi telefon.", sid)
        assert r.get("intent") != "faq"


# ---------------------------------------------------------------------------
# 6-7: delivery / pickup - ALREADY-LIVE regression lock (no new code; the
# sprint's own example phrasings are independently FAQ-marker matches).
# ---------------------------------------------------------------------------

class TestDeliveryAlreadyLive:
    def test_delivery_initial_question(self):
        r = _chat(DELIVERY_QUESTION, "v216a-delivery-initial")
        assert r.get("intent") == "faq"

    def test_delivery_price_followup_independently_resolves(self):
        sid = "v216a-delivery-price"
        _chat(DELIVERY_QUESTION, sid)
        r = _chat("Kolko stoji doprava?", sid)
        assert r.get("intent") == "faq"
        assert "49" in r.get("answer", "")


class TestPickupAlreadyLive:
    def test_pickup_initial_question(self):
        r = _chat(PICKUP_QUESTION, "v216a-pickup-initial")
        assert r.get("intent") == "faq"

    def test_personal_collection_followup_independently_resolves(self):
        sid = "v216a-pickup-followup"
        _chat("Ake mate moznosti dopravy?", sid)
        r = _chat("A osobny odber?", sid)
        assert r.get("intent") == "faq"
        assert len(r.get("products") or []) == 0


# ---------------------------------------------------------------------------
# 8-9: payment - card ALREADY-LIVE regression lock; Apple Pay is the new
# V2.16a Gate C capability.
# ---------------------------------------------------------------------------

class TestPaymentCardAlreadyLive:
    def test_payment_initial_question(self):
        r = _chat(PAYMENT_QUESTION, "v216a-payment-initial")
        assert r.get("intent") == "faq"

    def test_card_followup_independently_resolves(self):
        sid = "v216a-payment-card"
        _chat(PAYMENT_QUESTION, sid)
        r = _chat("Da sa kartou?", sid)
        assert r.get("intent") == "faq"
        assert len(r.get("products") or []) == 0


class TestPaymentMethodFollowupNewCapability:
    """The one genuinely new V2.16a capability: a named payment-method
    follow-up ("A Apple Pay?") that FAQ_INTENT_MARKERS does not itself
    catch must recall the real, grounded payment-methods answer instead
    of falling into commerce product search."""

    def test_apple_pay_followup_recalls_payment_faq_not_product_search(self):
        sid = "v216a-payment-applepay"
        _chat(PAYMENT_QUESTION, sid)
        r = _chat("A Apple Pay?", sid)
        assert r.get("intent") == "faq"
        assert r.get("products") == []
        # Must not fabricate a yes/no claim about Apple Pay specifically -
        # it recalls the real, already-grounded methods list, which does
        # not mention Apple Pay (DATA_ABSENT in data/knowledge.json).
        assert "apple" not in r.get("answer", "").lower()

    def test_google_pay_followup_recalls_payment_faq(self):
        sid = "v216a-payment-googlepay"
        _chat(PAYMENT_QUESTION, sid)
        r = _chat("A Google Pay?", sid)
        assert r.get("intent") == "faq"
        assert r.get("products") == []

    def test_paypal_followup_recalls_payment_faq(self):
        sid = "v216a-payment-paypal"
        _chat(PAYMENT_QUESTION, sid)
        r = _chat("A PayPal?", sid)
        assert r.get("intent") == "faq"
        assert r.get("products") == []

    def test_bare_apple_pay_with_no_prior_context_is_not_treated_as_followup(self):
        # Negative control (Section 22/32 anti-over-triggering discipline):
        # with no prior informational question to recall, "A Apple Pay?"
        # must NOT manufacture a payment answer out of nothing.
        r = _chat("A Apple Pay?", "v216a-payment-bare-no-context")
        assert r.get("intent") != "faq" or "kartou" not in r.get("answer", "").lower()

    def test_explicit_apple_branded_product_after_payment_topic_stays_product_search(self):
        # Explicit current-turn target always wins (Section 12/21): a real
        # product query that happens to contain "Apple" (brand text) must
        # never be swallowed by the payment-followup vocabulary, which
        # requires the specific phrase "apple pay", not the bare word.
        sid = "v216a-payment-explicit-apple-product"
        _chat(PAYMENT_QUESTION, sid)
        r = _chat("Poslite mi Apple Brand ryzu", sid)
        assert r.get("intent") == "product_search"


# ---------------------------------------------------------------------------
# 10-15: hard topic switches after an informational (payment) topic.
# ---------------------------------------------------------------------------

class TestHardTopicSwitchesAfterPaymentTopic:
    def test_product_search_hard_switch(self):
        sid = "v216a-hardswitch-product"
        _chat(PAYMENT_QUESTION, sid)
        r = _chat("Poslite mi Kikkoman sojovu omacku", sid)
        assert r.get("intent") == "product_search"
        assert len(r.get("products") or []) > 0

    def test_replacement_products_hard_switch(self):
        sid = "v216a-hardswitch-replacement"
        _chat(PAYMENT_QUESTION, sid)
        r = _chat("nahrada za rybiu omacku vegan", sid)
        assert r.get("intent") == "replacement_products"

    def test_recipe_hard_switch(self):
        sid = "v216a-hardswitch-recipe"
        _chat(PAYMENT_QUESTION, sid)
        r = _chat("Das mi recept na ramen?", sid)
        assert r.get("intent") == "recipe"

    def test_use_case_hard_switch(self):
        sid = "v216a-hardswitch-usecase"
        _chat(STORE_QUESTION, sid)
        r = _chat("Co potrebujem na domace sushi?", sid)
        assert r.get("intent") in ("related_products", "use_case_advice")

    def test_comparison_hard_switch(self):
        sid = "v216a-hardswitch-comparison"
        _chat(PAYMENT_QUESTION, sid)
        r = _chat("Aky je rozdiel medzi Kikkoman a Yamasa sojovou omackou?", sid)
        assert r.get("intent") in ("product_advice", "comparison")

    def test_allergen_safety_hard_switch(self):
        sid = "v216a-hardswitch-safety"
        _chat(PAYMENT_QUESTION, sid)
        r = _chat("Mam alergiu na arasidy, co mi odporucate?", sid)
        assert r.get("intent") == "allergen_safety"


# ---------------------------------------------------------------------------
# 16-17: explicit new topic overrides stale context / no over-triggering.
# ---------------------------------------------------------------------------

class TestExplicitNewTopicAndOverTriggering:
    def test_explicit_new_faq_topic_overrides_stale_topic(self):
        sid = "v216a-explicit-override"
        _chat(PAYMENT_QUESTION, sid)
        r = _chat(DELIVERY_QUESTION, sid)
        assert r.get("intent") == "faq"
        normalized_answer = normalize(r.get("answer", ""))
        assert "doruc" in normalized_answer or "krajin" in normalized_answer

    def test_generic_ambiguous_followup_does_not_over_resolve(self):
        sid = "v216a-ambiguous"
        _chat(PAYMENT_QUESTION, sid)
        r = _chat("A co to?", sid)
        # Must not fabricate a payment continuation out of a fully generic
        # phrase with no payment-method vocabulary in it.
        assert r.get("intent") != "faq" or "kartou" not in r.get("answer", "").lower()


# ---------------------------------------------------------------------------
# 18-19: reset / cross-session isolation (payment-topic specific; the
# store_location versions of these are already permanently covered by
# tests/test_noncommerce_context_followup_v2_15c.py).
# ---------------------------------------------------------------------------

class TestResetAndIsolationForPaymentTopic:
    def test_reset_clears_payment_context(self):
        sid = "v216a-payment-reset"
        _chat(PAYMENT_QUESTION, sid)
        _chat("Zacnime odznova", sid)
        r = _chat("A Apple Pay?", sid)
        assert r.get("intent") != "faq" or "kartou" not in r.get("answer", "").lower()

    def test_cross_session_isolation_for_payment_topic(self):
        _chat(PAYMENT_QUESTION, "v216a-payment-isolation-a")
        r = _chat("A Apple Pay?", "v216a-payment-isolation-b")
        assert r.get("intent") != "faq" or "kartou" not in r.get("answer", "").lower()


# ---------------------------------------------------------------------------
# 21-24: rt0004 / rt0010 / rt0011 / rt0013 permanent controls (also
# covered in test_noncommerce_context_followup_v2_15c.py; re-asserted here
# as the V2.16a "did not regress these" control per Section 35).
# ---------------------------------------------------------------------------

class TestPermanentRoutingControls:
    def test_rt0004_related_products_protected(self):
        r = _chat("suvisiace produkty k sushi ryzi", "v216a-rt0004")
        assert r.get("intent") == "related_products"

    def test_rt0010_allergen_safety_protected(self):
        r = _chat("sojova omacka bez soje", "v216a-rt0010")
        assert r.get("intent") == "allergen_safety"

    def test_rt0011_no_session_contamination(self):
        sid = "v216a-rt0011"
        query = "mam rad nepalive jedlo, co odporucas?"
        first = _chat(query, sid)
        second = _chat(query, sid)
        assert first.get("intent") == "product_search"
        assert second.get("intent") == "product_search"

    def test_rt0013_replacement_products_protected(self):
        r = _chat("nahrada za rybiu omacku vegan", "v216a-rt0013")
        assert r.get("intent") == "replacement_products"
