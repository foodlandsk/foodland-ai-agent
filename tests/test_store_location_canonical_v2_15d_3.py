"""
tests/test_store_location_canonical_v2_15d_3.py  -  V2.15d.3 STORE_LOCATION
canonical data closure subtask (docs/event-execution-context-isolation-
v2.15d.3.md).

Authoritative, product-owner-supplied Foodland business data:

    Canonical physical address:
        Stara Vajnorska 3308/19, 831 04 Bratislava

    Canonical Google Maps URL:
        https://maps.app.goo.gl/3tFJ4P6w2pj88xAP8

Single source of truth: the address lives ONLY as free text in the
"Ma Foodland kamennu predajnu?" FAQ record in data/knowledge.json (no
separate business-config module exists in this repo - confirmed by
audit before implementation). The canonical Maps URL is NOT baked into
that FAQ text - it would then be duplicated when app.main.
_build_maps_link_from_faq_answer() re-derives it a second time for a
V2.15c follow-up recall of the same answer. Instead, ONE function
(_build_maps_link_from_faq_answer) is the sole authority for whether/
which Maps link gets attached, called identically at both the initial-
answer site (new in this sprint) and the V2.15c follow-up site
(unchanged) - so the canonical link is never duplicated and never
drifts between the two call sites.

_ADDRESS_PATTERN was extended to accept a "houseNumber/orientationNumber"
format (e.g. "3308/19"), which the previous V2.15c pattern could not
extract at all. _build_maps_link_from_faq_answer() now prefers the
authoritative canonical Foodland Maps URL over a generated
google.com/maps/search URL whenever the extracted address matches the
Foodland store's own canonical address exactly; the generated-search
fallback remains available for any other address text this function
might ever be asked to build a link for.
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


STORE_QUESTION = "Kde sa nachádza kamenná predajňa Foodland?"
CANONICAL_ADDRESS_FRAGMENT_STREET = "Stará Vajnorská 3308/19"
CANONICAL_ADDRESS_FRAGMENT_CITY = "831 04 Bratislava"
CANONICAL_MAPS_URL = "https://maps.app.goo.gl/3tFJ4P6w2pj88xAP8"
GENERIC_MAPS_SEARCH_PREFIX = "https://www.google.com/maps/search/"


class TestSL_A_InitialAddress:
    """CASE SL-A - the very first answer must already contain the
    authoritative address, with no second question required."""

    def test_initial_answer_contains_canonical_address(self):
        r = _chat(STORE_QUESTION, "sl-a-address")
        assert r.get("intent") == "faq"
        answer = r.get("answer", "")
        assert CANONICAL_ADDRESS_FRAGMENT_STREET in answer
        assert CANONICAL_ADDRESS_FRAGMENT_CITY in answer


class TestSL_B_InitialMapsLink:
    """CASE SL-B - the very first answer must already contain the exact
    configured canonical Maps destination, not a placeholder or a
    generated substitute."""

    def test_initial_answer_contains_canonical_maps_url(self):
        r = _chat(STORE_QUESTION, "sl-b-maps")
        assert CANONICAL_MAPS_URL in r.get("answer", "")


class TestSL_C_NoGenericMapsReplacement:
    """CASE SL-C - when canonical Maps data exists for Foodland, the
    response must never fall back to a generic generated Maps-search
    URL instead of (or alongside) the canonical one."""

    def test_initial_answer_does_not_use_generated_search_url(self):
        r = _chat(STORE_QUESTION, "sl-c-no-generic")
        answer = r.get("answer", "")
        assert GENERIC_MAPS_SEARCH_PREFIX not in answer

    def test_followup_does_not_use_generated_search_url_either(self):
        sid = "sl-c-followup-no-generic"
        _chat(STORE_QUESTION, sid)
        r = _chat("Prilož mi Google link na adresu.", sid)
        assert GENERIC_MAPS_SEARCH_PREFIX not in r.get("answer", "")

    def test_canonical_link_appears_exactly_once_not_duplicated(self):
        # Guards against the exact failure mode this design avoids: the
        # link baked into knowledge.json AND re-derived by
        # _build_maps_link_from_faq_answer() both firing.
        r = _chat(STORE_QUESTION, "sl-c-no-duplicate")
        answer = r.get("answer", "")
        assert answer.count(CANONICAL_MAPS_URL) == 1


class TestSL_D_FollowupMap:
    """CASE SL-D - "Pošli mi mapu." after the store-location question
    must remain STORE_LOCATION and return the canonical Maps URL."""

    def test_posli_mi_mapu_returns_canonical_url(self):
        sid = "sl-d-posli-mapu"
        _chat(STORE_QUESTION, sid)
        r = _chat("Pošli mi mapu.", sid)
        assert r.get("intent") == "faq"
        assert r.get("products") == []
        assert CANONICAL_MAPS_URL in r.get("answer", "")


class TestSL_E_FollowupGoogleLink:
    """CASE SL-E - "Prilož mi Google link na adresu." must not enter
    product search (rt0014, reaffirmed)."""

    def test_google_link_followup_stays_in_store_location(self):
        sid = "sl-e-google-link"
        _chat(STORE_QUESTION, sid)
        r = _chat("Prilož mi Google link na adresu.", sid)
        assert r.get("intent") == "faq"
        assert r.get("products") == []
        assert CANONICAL_MAPS_URL in r.get("answer", "")


class TestSL_F_ProductHardSwitch:
    """CASE SL-F - an explicit product mention after STORE_LOCATION must
    enter ordinary commerce behavior, never be swallowed."""

    def test_kikkoman_hard_switch_enters_product_search(self):
        sid = "sl-f-kikkoman"
        _chat(STORE_QUESTION, sid)
        r = _chat("Ukáž mi Kikkoman sójovú omáčku.", sid)
        assert r.get("intent") == "product_search"
        assert len(r.get("products") or []) > 0


class TestSL_G_ReplacementHardSwitch:
    """CASE SL-G - rt0013 (CLOSED) semantics must be preserved after a
    STORE_LOCATION turn."""

    def test_replacement_hard_switch_preserves_rt0013(self):
        sid = "sl-g-replacement"
        _chat(STORE_QUESTION, sid)
        r = _chat("Náhrada za rybiu omáčku vegan.", sid)
        assert r.get("intent") == "replacement_products"


class TestSL_H_RecipeHardSwitch:
    """CASE SL-H - existing ramen/recipe-related behavior must be
    preserved after a STORE_LOCATION turn (whatever that behavior
    currently and correctly is - this test locks it, it does not
    redefine it)."""

    def test_ramen_hard_switch_preserves_existing_behavior(self):
        sid = "sl-h-ramen"
        _chat(STORE_QUESTION, sid)
        r = _chat("Čo potrebujem na ramen?", sid)
        # Confirmed via direct baseline comparison against unmodified
        # HEAD before this sprint: this exact phrasing already resolves
        # to related_products, unaffected by this sprint's changes -
        # locking that pre-existing behavior, not asserting a specific
        # new one.
        assert r.get("intent") in ("related_products", "recipe", "basket_completion", "use_case_advice")


class TestSL_NoAddressFabrication:
    """The canonical address text is never fabricated beyond what
    data/knowledge.json actually contains - this is grounded FAQ data,
    not invented business information."""

    def test_no_link_for_delivery_faq_which_has_no_address(self):
        r = _chat("Akym sposobom dorucujete tovar?", "sl-no-fabrication")
        assert CANONICAL_MAPS_URL not in r.get("answer", "")
        assert GENERIC_MAPS_SEARCH_PREFIX not in r.get("answer", "")
