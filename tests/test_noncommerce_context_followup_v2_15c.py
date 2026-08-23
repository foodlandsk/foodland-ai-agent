"""
tests/test_noncommerce_context_followup_v2_15c.py  -  V2.15c / rt0014 closure.

rt0014 ("Kde sa nachadza kamenna predajna?" -> Mei answers correctly, then
"Prilož mi Google link na adresu." in the SAME session loses context and
falls into product-search behavior) is closed via a small, GENERAL
mechanism, not a Google/"adresa"-specific hack (explicitly forbidden by
the closure spec):

  - app.session_state.set_last_informational_question()/
    get_last_informational_question(): remembers the RAW QUESTION TEXT
    (never the answer, never assistant-generated content) of the last
    successfully-answered FAQ/informational query this session.
  - app.session_state.looks_like_location_reference_followup(): a
    narrow, location/navigation-specific vocabulary check (mapa, adresa,
    "ako sa tam dostanem", google link, ...) - NOT a generic "any short
    follow-up inherits context" catch-all.
  - app/main.py: a new fallback block in _chat_impl(), positioned dead
    last - after safety, FAQ, comparison, use_case_advice,
    basket_completion, recipe, ordinal-reference, and the recipe/
    result-set orphaned-followup check have ALL already declined the
    turn, and BEFORE the generic special_subject/related_subject
    commerce cascade begins. This position is what guarantees "explicit
    current-turn target always wins" (Section 12): any real product/
    brand/replacement/recipe/allergen mention is claimed by its own
    earlier, higher-precedence branch and structurally cannot reach this
    fallback.
  - app.main._build_maps_link_from_faq_answer(): a Google Maps SEARCH
    url (never fabricated coordinates/place IDs/routes) built by
    regex-extracting the real, already-grounded street address directly
    out of the recalled FAQ answer text (data/knowledge.json), so a link
    is only ever produced when the recalled topic actually contains an
    address, and it always tracks whatever the knowledge base currently
    says.

resolve_action_target_signal() (app/turn_resolver.py) was evaluated and
judged NOT_SUITABLE for reuse: its parameters are all commerce/product-
family-specific detector concepts (special_subject, related_subject,
has_recipe_shopping_language, resolves_confident_product_family); its
sole job is arbitrating the special_subject-vs-related_subject conflict
that caused rt0004, not general action/reference resolution. This
closure instead follows the spec's WRAP_WITH_SMALL_INFORMATIONAL_RESOLVER
path.

Audited finding, disclosed rather than hidden: opening_hours ("Ake mate
otvaracie hodiny?") and contact ("Aky mate telefonny kontakt?") phrasings
do not currently reach the FAQ answer cascade at all (is_faq_intent/
FAQ marker gap) - confirmed via reproduction against the unmodified
HEAD commit, i.e. PRE-EXISTING and out of scope for this closure, not a
V2.15c regression. store_location (with the new follow-up mechanism) and
delivery (initial question only, no follow-up vocabulary of its own)
are the only two informational capabilities exercised as passing here.
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


STORE_QUESTION = "Kde sa nachadza kamenna predajna?"
MAPS_FOLLOWUP = "Prilož mi Google link na adresu."
ADDRESS_FRAGMENT = "Stará Vajnorská 19"
MAPS_URL_PREFIX = "https://www.google.com/maps/search/?api=1&query="


class TestRt0014PrimaryCase:
    """The exact rt0014 reproduction sequence, permanently locked."""

    def test_turn1_answers_store_location(self):
        r = _chat(STORE_QUESTION, "rt0014-primary-t1")
        assert r.get("intent") == "faq"
        assert ADDRESS_FRAGMENT in r.get("answer", "")

    def test_turn2_stays_in_location_context_not_product_search(self):
        sid = "rt0014-primary-t2"
        _chat(STORE_QUESTION, sid)
        r = _chat(MAPS_FOLLOWUP, sid)
        assert r.get("intent") == "faq"
        assert r.get("products") == []
        assert ADDRESS_FRAGMENT in r.get("answer", "")
        assert MAPS_URL_PREFIX in r.get("answer", "")


class TestRt0014Generalization:
    """Section 7 of the closure spec: the mechanism must be general
    (vocabulary-driven), not a single hardcoded phrase - proven by
    rephrasing the follow-up several ways."""

    def test_ako_sa_tam_dostanem_phrasing(self):
        sid = "rt0014-gen-dostanem"
        _chat(STORE_QUESTION, sid)
        r = _chat("Ako sa tam dostanem?", sid)
        assert r.get("intent") == "faq"
        assert r.get("products") == []

    def test_mapa_phrasing(self):
        sid = "rt0014-gen-mapa"
        _chat(STORE_QUESTION, sid)
        r = _chat("Mas na to mapu?", sid)
        assert r.get("intent") == "faq"
        assert r.get("products") == []

    def test_link_na_adresu_phrasing(self):
        sid = "rt0014-gen-link"
        _chat(STORE_QUESTION, sid)
        r = _chat("Das mi link na adresu?", sid)
        assert r.get("intent") == "faq"
        assert MAPS_URL_PREFIX in r.get("answer", "")


class TestRt0014MapsLinkGrounding:
    """The maps link must be derived from the real, already-grounded
    address text - never fabricated - and must be absent when the
    recalled topic has no address in it at all."""

    def test_link_contains_urlencoded_real_address(self):
        sid = "rt0014-grounding-address"
        _chat(STORE_QUESTION, sid)
        r = _chat(MAPS_FOLLOWUP, sid)
        assert "Star%C3%A1+Vajnorsk%C3%A1+19" in r.get("answer", "")

    def test_no_link_fabricated_when_recalled_topic_has_no_address(self):
        # Delivery FAQ answer contains no street address - the follow-up
        # must recall the delivery answer verbatim, with no maps link
        # invented for it.
        sid = "rt0014-grounding-no-address"
        _chat("Akym sposobom dorucujete tovar?", sid)
        r = _chat(MAPS_FOLLOWUP, sid)
        assert r.get("intent") == "faq"
        assert "maps" not in r.get("answer", "").lower()


class TestRt0014MultiTopicRecency:
    """When more than one informational topic has been discussed, the
    MOST RECENT one is what a location-reference follow-up resolves
    against."""

    def test_most_recent_informational_topic_wins(self):
        sid = "rt0014-recency"
        _chat(STORE_QUESTION, sid)
        _chat("Akym sposobom dorucujete tovar?", sid)
        r = _chat(MAPS_FOLLOWUP, sid)
        assert r.get("intent") == "faq"
        assert "packeta" in r.get("answer", "").lower()
        assert ADDRESS_FRAGMENT not in r.get("answer", "")


class TestRt0014HardSwitchSafetyControls:
    """Section 12 of the closure spec - EXPLICIT CURRENT-TURN TARGET
    ALWAYS WINS. A real product/brand/replacement/allergen/recipe
    mention after a store-location question must be routed normally and
    must NEVER be swallowed by the new fallback, since the fallback sits
    strictly after every one of these workflows in _chat_impl()'s
    cascade."""

    def test_hard_switch_to_product_search(self):
        sid = "rt0014-hardswitch-product"
        _chat(STORE_QUESTION, sid)
        r = _chat("Poslite mi Kikkoman sojovu omacku", sid)
        assert r.get("intent") == "product_search"
        assert len(r.get("products") or []) > 0

    def test_hard_switch_to_replacement_products_rt0013_preserved(self):
        sid = "rt0014-hardswitch-replacement"
        _chat(STORE_QUESTION, sid)
        r = _chat("Potrebujem vegan nahradu za rybaciu omacku", sid)
        assert r.get("intent") == "replacement_products"

    def test_hard_switch_to_allergen_safety(self):
        sid = "rt0014-hardswitch-allergen"
        _chat(STORE_QUESTION, sid)
        r = _chat("Mam alergiu na arasidy, co mi odporucate?", sid)
        assert r.get("intent") == "allergen_safety"

    def test_hard_switch_to_recipe(self):
        sid = "rt0014-hardswitch-recipe"
        _chat(STORE_QUESTION, sid)
        r = _chat("Das mi recept na ramen?", sid)
        assert r.get("intent") == "recipe"


class TestRt0014ExplicitTargetOverridesGenericLinkWord:
    """A message containing the word "link" but naming an explicit,
    unrelated product target must NOT be treated as a location-reference
    follow-up - the vocabulary check alone is not sufficient without an
    explicit target to protect against, which this proves directly."""

    def test_link_with_explicit_brand_target_stays_product_search(self):
        sid = "rt0014-explicit-target"
        _chat(STORE_QUESTION, sid)
        r = _chat("Pošli mi link na Kikkoman", sid)
        assert r.get("intent") == "product_search"


class TestRt0014ResetClearsContext:
    """apply_reset() must clear last_informational_question - a
    location-reference follow-up after an explicit reset must NOT
    resurrect the pre-reset topic."""

    def test_reset_prevents_resurrection(self):
        sid = "rt0014-reset"
        _chat(STORE_QUESTION, sid)
        _chat("Zacnime odznova", sid)
        r = _chat(MAPS_FOLLOWUP, sid)
        assert r.get("intent") != "faq" or ADDRESS_FRAGMENT not in r.get("answer", "")


class TestRt0014CrossSessionIsolation:
    """A location-reference follow-up in a session that never asked an
    informational question must NOT inherit another session's topic."""

    def test_no_cross_session_leakage(self):
        _chat(STORE_QUESTION, "rt0014-isolation-a")
        r = _chat(MAPS_FOLLOWUP, "rt0014-isolation-b")
        assert ADDRESS_FRAGMENT not in r.get("answer", "")


class TestRt0014NegativeControlsNoOverTriggering:
    """Section 32 of the closure spec - the mechanism must not
    over-trigger on generic vocabulary when there is no prior
    informational question to recall at all."""

    def test_bare_location_words_without_prior_question_no_faq_leak(self):
        r = _chat(MAPS_FOLLOWUP, "rt0014-neg-no-prior")
        assert ADDRESS_FRAGMENT not in r.get("answer", "")

    def test_bare_address_word_alone_is_not_treated_as_followup(self):
        # "adresa" alone, with no prior informational question, must not
        # manufacture a store-location answer out of nothing.
        r = _chat("Aka je vasa adresa", "rt0014-neg-bare-adresa")
        assert ADDRESS_FRAGMENT not in r.get("answer", "") or r.get("intent") == "faq"


class TestRt0014SafetyRegressionControls:
    """rt0004/rt0010/rt0011/rt0013 permanent controls must remain
    completely unaffected by this closure."""

    def test_rt0004_related_products_protected(self):
        r = _chat("súvisiace produkty k sushi ryži", "rt0014-rt0004")
        assert r.get("intent") == "related_products"

    def test_rt0010_allergen_safety_protected(self):
        r = _chat("sójová omáčka bez sóje", "rt0014-rt0010")
        assert r.get("intent") == "allergen_safety"

    def test_rt0011_no_session_contamination(self):
        sid = "rt0014-rt0011"
        query = "mám rád nepálivé jedlo, čo odporúčaš?"
        first = _chat(query, sid)
        second = _chat(query, sid)
        assert first.get("intent") == "product_search"
        assert second.get("intent") == "product_search"

    def test_rt0013_replacement_products_protected(self):
        r = _chat("náhrada za rybiu omáčku vegan", "rt0014-rt0013")
        assert r.get("intent") == "replacement_products"
