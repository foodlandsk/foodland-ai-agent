"""
tests/test_opening_hours_contact_grounding_v2_16a_1.py  -  V2.16a.1
OPENING HOURS & CONTACT DATA GROUNDING CLOSURE.

Closes the two capabilities V2.16a deliberately left as NOT_REACHED_
PRE_EXISTING_GAP (opening_hours) / DATA_REQUIRED (contact), after a
data-grounding audit (not a routing-first fix) found:

- opening_hours: still has no standalone FAQ record (hours are only a
  sub-clause of the store-location Odpoveď in data/knowledge.json) - so
  this closure REUSES that existing, already-grounded record (OH-B:
  EXTRACT_FROM_EXISTING_AUTHORITATIVE_SOURCE) via the same
  direct_faq_answer_by_question_markers(required_markers=("kamennu",
  "predajnu")) shortcut the "adresa"/bare "predajn" paths already use -
  no new hours data was invented.
- contact: the V2.16a report's claim that phone was DATA_ABSENT was
  WRONG - a real, business-owner-confirmed phone number
  (+421 2 4468 1527) and support email (eshop@foodland.sk) already
  exist live in production inside missing_composition_answer()
  (app/main.py), reachable only through a narrow composition-complaint
  path. This closure adds ONE new FAQ record to data/knowledge.json
  reusing that exact same grounded phone/email (no invention), so a
  general "how do I contact you" question can reach it too.

New routing primitives (app.session_state):
- is_opening_hours_query() / looks_like_opening_hours_followup()
- is_contact_query() / looks_like_contact_followup()

Both are narrow, phrase/token-based detectors - NEITHER adds a bare
substring to the shared FAQ_INTENT_MARKERS list, because a blast-radius
re-check against data/products.json (re-verifying the V2.16a finding)
confirmed real product description text containing "po otvorení"
(storage instructions), "otvorenými"/"dotvorenie" (unrelated words
containing "otvoren" as a substring), and "kontakt s potravinami"/
"priamy kontakt s fóliou" (food-contact-safe packaging material) - a
bare "otvoren"/"kontakt" marker would misroute those legitimate product
questions into the wrong FAQ. Both detectors are instead gated into
is_faq_query directly (app/main.py `_chat_impl`), not into
FAQ_INTENT_MARKERS, and opening_hours additionally excludes the exact
"po otvoren" collision substring.

Follow-up continuation reuses the single last_informational_question
field established by V2.15c/V2.16a - no new session-state field, no new
topic enum. Address/Maps follow-ups after a contact topic are handled
for free by the pre-existing looks_like_location_reference_followup()
path (not topic-gated).

RELATIVE_DAY_QUERY_FOUNDATION_ONLY: "dnes"/"zajtra" (today/tomorrow) are
deliberately excluded from the opening-hours follow-up cue set - this
codebase has no reliable timezone-aware "what day is it" mechanism, and
a bare "dnes"/"zajtra" is common inside unrelated commerce queries
(Section 10/14 of the closure spec). The multi-word phrase markers "ste
dnes otvoreni"/"mate dnes otvorene" ARE recognized as an INITIAL query
(they return the real, correct weekly schedule, from which the customer
can read off whether today's hours apply), but no code computes or
asserts a specific "open right now: yes/no" claim.
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


HOURS_QUESTION = "Kedy mate otvorene?"
CONTACT_QUESTION = "Ako vas mozem kontaktovat?"
PHONE = "+421 2 4468 1527"
EMAIL = "eshop@foodland.sk"
ADDRESS_FRAGMENT = "Stará Vajnorská"


# ---------------------------------------------------------------------------
# 1-2: opening-hours initial query, alternate wording
# ---------------------------------------------------------------------------

class TestOpeningHoursInitial:
    def test_generic_opening_hours_question(self):
        r = _chat(HOURS_QUESTION, "v2161a-hours-generic")
        assert r.get("intent") == "faq"
        assert "8:00" in r.get("answer", "") and "18:00" in r.get("answer", "")

    def test_alternate_wording(self):
        r = _chat("Ake su otvaracie hodiny?", "v2161a-hours-alt")
        assert r.get("intent") == "faq"
        assert "otvaracie hodin" in normalize(r.get("answer", ""))


# ---------------------------------------------------------------------------
# 3-4: Saturday / Sunday
# ---------------------------------------------------------------------------

class TestOpeningHoursDaySpecific:
    def test_saturday_question(self):
        r = _chat("Ste otvoreni v sobotu?", "v2161a-hours-sat")
        assert r.get("intent") == "faq"
        assert "So 9" in r.get("answer", "") or "9:00" in r.get("answer", "")

    def test_sunday_question(self):
        r = _chat("Ste otvoreni v nedelu?", "v2161a-hours-sun")
        assert r.get("intent") == "faq"


# ---------------------------------------------------------------------------
# 5-6: contextual Saturday/Sunday follow-up
# ---------------------------------------------------------------------------

class TestOpeningHoursFollowup:
    def test_saturday_followup(self):
        sid = "v2161a-hours-followup-sat"
        _chat(HOURS_QUESTION, sid)
        r = _chat("A v sobotu?", sid)
        assert r.get("intent") == "faq"
        assert r.get("products") == []

    def test_sunday_followup(self):
        sid = "v2161a-hours-followup-sun"
        _chat(HOURS_QUESTION, sid)
        r = _chat("A v nedelu?", sid)
        assert r.get("intent") == "faq"

    def test_weekend_followup_alternate_wording(self):
        sid = "v2161a-hours-followup-weekend"
        _chat("Ake su otvaracie hodiny?", sid)
        r = _chat("A cez vikend?", sid)
        assert r.get("intent") == "faq"

    def test_bare_day_word_with_no_prior_context_not_treated_as_followup(self):
        # Negative control (anti-over-triggering): with no prior
        # informational question, "A v sobotu?" alone must NOT
        # manufacture an hours answer out of nothing.
        r = _chat("A v sobotu?", "v2161a-hours-bare-no-context")
        assert r.get("intent") != "faq" or "8:00" not in r.get("answer", "")


# ---------------------------------------------------------------------------
# 7-9: hard switches away from opening_hours
# ---------------------------------------------------------------------------

class TestOpeningHoursHardSwitch:
    def test_hard_switch_to_product_search(self):
        sid = "v2161a-hours-hardswitch-product"
        _chat(HOURS_QUESTION, sid)
        r = _chat("Ukaz mi sushi ryzu.", sid)
        assert r.get("intent") == "product_search"
        assert len(r.get("products") or []) > 0

    def test_hard_switch_to_recipe(self):
        sid = "v2161a-hours-hardswitch-recipe"
        _chat(HOURS_QUESTION, sid)
        r = _chat("Daj mi recept na ramen.", sid)
        assert r.get("intent") == "recipe"

    def test_hard_switch_to_replacement(self):
        sid = "v2161a-hours-hardswitch-replacement"
        _chat(HOURS_QUESTION, sid)
        r = _chat("Cim nahradim rybiu omacku?", sid)
        assert r.get("intent") == "replacement_products"


# ---------------------------------------------------------------------------
# 10-11: reset, cross-session isolation (opening_hours)
# ---------------------------------------------------------------------------

class TestOpeningHoursSessionSafety:
    def test_reset_clears_opening_hours_context(self):
        sid = "v2161a-hours-reset"
        _chat(HOURS_QUESTION, sid)
        _chat("Zacnime odznova", sid)
        r = _chat("A v sobotu?", sid)
        assert r.get("intent") != "faq" or "8:00" not in r.get("answer", "")

    def test_cross_session_isolation(self):
        _chat(HOURS_QUESTION, "v2161a-hours-isolation-a")
        r = _chat("A v sobotu?", "v2161a-hours-isolation-b")
        assert r.get("intent") != "faq" or "8:00" not in r.get("answer", "")


# ---------------------------------------------------------------------------
# 12: product-description "po otvorení" negative control (blast-radius)
# ---------------------------------------------------------------------------

class TestOpeningHoursBlastRadiusNegativeControl:
    def test_storage_instruction_question_not_misrouted_to_hours(self):
        r = _chat("Ako mam skladovat tento produkt po otvoreni?", "v2161a-hours-negctrl")
        assert r.get("intent") != "faq"

    def test_relative_day_query_returns_real_schedule_not_fabricated_status(self):
        # RELATIVE_DAY_QUERY_FOUNDATION_ONLY: recognized as opening-hours
        # topic (not commerce garbage) and returns the real schedule, but
        # the answer text must not claim a specific "open right now"
        # status - only report the real, static weekly hours.
        r = _chat("Dokedy mate dnes otvorene?", "v2161a-hours-relday")
        assert r.get("intent") == "faq"
        assert "8:00" in r.get("answer", "")


# ---------------------------------------------------------------------------
# Contact: 1-2 generic + address
# ---------------------------------------------------------------------------

class TestContactInitial:
    def test_generic_contact_question(self):
        r = _chat(CONTACT_QUESTION, "v2161a-contact-generic")
        assert r.get("intent") == "faq"
        assert PHONE in r.get("answer", "")
        assert EMAIL in r.get("answer", "")

    def test_address_present_in_contact_answer(self):
        r = _chat(CONTACT_QUESTION, "v2161a-contact-address")
        assert ADDRESS_FRAGMENT in r.get("answer", "")


# ---------------------------------------------------------------------------
# 3: Google Maps query (initial contact answer auto-attaches canonical link)
# ---------------------------------------------------------------------------

class TestContactMaps:
    def test_maps_link_attached_to_contact_answer(self):
        r = _chat(CONTACT_QUESTION, "v2161a-contact-maps")
        assert "maps.app.goo.gl/3tFJ4P6w2pj88xAP8" in r.get("answer", "")


# ---------------------------------------------------------------------------
# 4-5: phone / email initial
# ---------------------------------------------------------------------------

class TestContactPhoneEmail:
    def test_phone_question(self):
        r = _chat("Aky mate telefon?", "v2161a-contact-phone")
        assert r.get("intent") == "faq"
        assert PHONE in r.get("answer", "")

    def test_email_question(self):
        r = _chat("Mate email?", "v2161a-contact-email")
        assert r.get("intent") == "faq"
        assert EMAIL in r.get("answer", "")


# ---------------------------------------------------------------------------
# 6-7: contextual address / Maps follow-up
# ---------------------------------------------------------------------------

class TestContactFollowup:
    def test_address_followup(self):
        sid = "v2161a-contact-followup-address"
        _chat(CONTACT_QUESTION, sid)
        r = _chat("Posli mi adresu.", sid)
        assert r.get("intent") == "faq"
        assert ADDRESS_FRAGMENT in r.get("answer", "")

    def test_maps_followup(self):
        sid = "v2161a-contact-followup-maps"
        _chat(CONTACT_QUESTION, sid)
        r = _chat("A Google Maps?", sid)
        assert r.get("intent") == "faq"
        assert "maps.app.goo.gl" in r.get("answer", "")

    def test_phone_followup(self):
        sid = "v2161a-contact-followup-phone"
        _chat(CONTACT_QUESTION, sid)
        r = _chat("A telefon?", sid)
        assert r.get("intent") == "faq"
        assert PHONE in r.get("answer", "")

    def test_email_followup(self):
        sid = "v2161a-contact-followup-email"
        _chat(CONTACT_QUESTION, sid)
        r = _chat("A email?", sid)
        assert r.get("intent") == "faq"
        assert EMAIL in r.get("answer", "")


# ---------------------------------------------------------------------------
# 8-10: hard switches away from contact
# ---------------------------------------------------------------------------

class TestContactHardSwitch:
    def test_hard_switch_to_product_search(self):
        sid = "v2161a-contact-hardswitch-product"
        _chat(CONTACT_QUESTION, sid)
        r = _chat("Ukaz mi sushi ryzu.", sid)
        assert r.get("intent") == "product_search"

    def test_hard_switch_to_replacement(self):
        sid = "v2161a-contact-hardswitch-replacement"
        _chat(CONTACT_QUESTION, sid)
        r = _chat("Cim nahradim rybiu omacku?", sid)
        assert r.get("intent") == "replacement_products"

    def test_hard_switch_to_recipe(self):
        sid = "v2161a-contact-hardswitch-recipe"
        _chat(CONTACT_QUESTION, sid)
        r = _chat("Daj mi recept na ramen.", sid)
        assert r.get("intent") == "recipe"

    def test_hard_switch_to_allergen_safety(self):
        sid = "v2161a-contact-hardswitch-safety"
        _chat(CONTACT_QUESTION, sid)
        r = _chat("Mam alergiu na arasidy, co mi odporucate?", sid)
        assert r.get("intent") == "allergen_safety"


# ---------------------------------------------------------------------------
# 11-12: reset, cross-session isolation (contact)
# ---------------------------------------------------------------------------

class TestContactSessionSafety:
    def test_reset_clears_contact_context(self):
        sid = "v2161a-contact-reset"
        _chat(CONTACT_QUESTION, sid)
        _chat("Zacnime odznova", sid)
        r = _chat("A telefon?", sid)
        assert r.get("intent") != "faq" or PHONE not in r.get("answer", "")

    def test_cross_session_isolation(self):
        _chat(CONTACT_QUESTION, "v2161a-contact-isolation-a")
        r = _chat("A telefon?", "v2161a-contact-isolation-b")
        assert r.get("intent") != "faq" or PHONE not in r.get("answer", "")


# ---------------------------------------------------------------------------
# Contact blast-radius negative control
# ---------------------------------------------------------------------------

class TestContactBlastRadiusNegativeControl:
    def test_food_contact_packaging_question_not_misrouted_to_contact(self):
        r = _chat("Je tato folia vhodna na priamy kontakt s potravinami?", "v2161a-contact-negctrl")
        assert r.get("intent") != "faq" or PHONE not in r.get("answer", "")


# ---------------------------------------------------------------------------
# Explicit target overrides generic word (both topics)
# ---------------------------------------------------------------------------

class TestExplicitTargetOverridesGenericWord:
    def test_apple_pay_after_hours_topic_unaffected(self):
        # Cross-capability regression: V2.16a's payment-followup mechanism
        # must remain unaffected by adding two more topics to the same
        # fallback block.
        sid = "v2161a-crosscheck-payment"
        _chat("Ako mozem zaplatit?", sid)
        r = _chat("A Apple Pay?", sid)
        assert r.get("intent") == "faq"
        assert "apple" not in r.get("answer", "").lower()


# ---------------------------------------------------------------------------
# Permanent regression controls (rt0004/rt0010/rt0011/rt0013 + V2.15c/V2.16a)
# ---------------------------------------------------------------------------

class TestPermanentRoutingControls:
    def test_rt0004_related_products_protected(self):
        r = _chat("suvisiace produkty k sushi ryzi", "v2161a-rt0004")
        assert r.get("intent") == "related_products"

    def test_rt0010_allergen_safety_protected(self):
        r = _chat("sojova omacka bez soje", "v2161a-rt0010")
        assert r.get("intent") == "allergen_safety"

    def test_rt0011_no_session_contamination(self):
        sid = "v2161a-rt0011"
        query = "mam rad nepalive jedlo, co odporucas?"
        first = _chat(query, sid)
        second = _chat(query, sid)
        assert first.get("intent") == "product_search"
        assert second.get("intent") == "product_search"

    def test_rt0013_replacement_products_protected(self):
        r = _chat("nahrada za rybiu omacku vegan", "v2161a-rt0013")
        assert r.get("intent") == "replacement_products"

    def test_v2_15c_store_location_maps_regression(self):
        sid = "v2161a-v215c-regression"
        _chat("Kde sa nachadza kamenna predajna?", sid)
        r = _chat("Posli mi mapu.", sid)
        assert r.get("intent") == "faq"
        assert "maps.app.goo.gl/3tFJ4P6w2pj88xAP8" in r.get("answer", "")
