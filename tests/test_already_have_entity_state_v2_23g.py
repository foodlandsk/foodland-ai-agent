"""
tests/test_already_have_entity_state_v2_23g.py  -  V2.23g bounded
ALREADY_HAVE entity-state repair.

V2.23f (read-only architecture review of real-customer seed
rc-c444e16673f0, "Co variit k ryzi?") found that the existing ownership
abstraction (detect_already_have_subject()/ALREADY_HAVE_SUBJECT_MAP/
complement_products_for_subject()) was already correctly wired into the
main pipeline - the only gap was that detect_already_have_subject()
required an EXPLICIT "mam X" marker, so implicit "co V k/s X" framing
("Co variit k ryzi?", "Co sa hodi k ryzi?") never set already_have_
subject at all and fell through to a purchasable-rice retrieval path.

This sprint adds exactly two narrow things in app/main.py:
1. A new, conservative implicit-ownership detector
   (_detect_implicit_already_have_subject(), ALREADY_HAVE_IMPLICIT_*
   constants) - verb-anchored only (co varit/uvarit/spravit/urobit/
   pripravit/mozem .../sa hodi/sa ide), deliberately NOT matching a
   bare "co k X"/"co s X" with no cooking verb (V2.23f Section 19 -
   too ambiguous on its own), and guarded by a purchase-intent
   override so "Aku ryzu mam kupit?" is never affected.
2. A precedence fix in _chat_impl(): already_have_subject is now
   checked BEFORE _related_products_forced (previously the other way
   round), because recipe-shopping language ("Co sa hodi k ryzi?")
   was forcing the RELATED_PRODUCTS workflow even when ownership was
   correctly detected, silently reintroducing bare rice.

Both changes are generic (keyed off the pre-existing
ALREADY_HAVE_SUBJECT_MAP, not hardcoded to rice) - verified here
against rice, tofu and udon.
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


def _titles(response: dict) -> list[str]:
    return [p.get("title", "") for p in (response.get("products") or [])]


def _has_bare_rice(titles: list[str]) -> bool:
    # "ryzove vino"/"ryzovy ocot" (rice wine/vinegar) are legitimate
    # complement condiments, not the owned grain itself - only count a
    # title as "bare rice" if it is a plain rice product (no condiment
    # qualifier word alongside the rice stem).
    condiment_qualifiers = ("vino", "ocot")
    for title in titles:
        normalized = m.normalize(title)
        if "ryz" in normalized and not any(q in normalized for q in condiment_qualifiers):
            return True
    return False


CANONICAL_SEED = "Čo variť k ryži?"


class TestImplicitOwnershipDetector:
    def test_canonical_seed_detected_as_ryza(self):
        assert m.detect_already_have_subject(CANONICAL_SEED) == "ryza"

    def test_co_sa_hodi_paraphrase_detected(self):
        assert m.detect_already_have_subject("Čo sa hodí k ryži?") == "ryza"

    def test_co_mozem_spravit_paraphrase_detected(self):
        assert m.detect_already_have_subject("Čo môžem spraviť s ryžou?") == "ryza"

    def test_generalizes_to_tofu_not_rice_specific(self):
        assert m.detect_already_have_subject("Čo spraviť s tofu?") == "tofu"

    def test_generalizes_to_udon_not_rice_specific(self):
        assert m.detect_already_have_subject("Čo spraviť s udon rezancami?") == "udon"

    def test_bare_co_s_without_verb_stays_conservative(self):
        # V2.23f Section 19 - deliberately NOT matched (too ambiguous
        # without a cooking verb).
        assert m.detect_already_have_subject("Čo s ryžou?") is None

    def test_bare_mention_without_co_stays_none(self):
        assert m.detect_already_have_subject("Ryža na sushi") is None
        assert m.detect_already_have_subject("Tofu a ryža") is None

    def test_purchase_intent_override_buy(self):
        assert m.detect_already_have_subject("Akú ryžu mám kúpiť?") is None

    def test_purchase_intent_override_recommend(self):
        assert m.detect_already_have_subject("Odporuč mi jazmínovú ryžu.") is None

    def test_purchase_intent_override_need(self):
        assert m.detect_already_have_subject("Potrebujem ryžu na sushi.") is None

    def test_existing_explicit_marker_unaffected(self):
        # Pre-existing V2.16c explicit-marker behavior must stay unchanged.
        assert m.detect_already_have_subject("Mam doma kimchi, co dalsie by sa hodilo?") == "kimchi"
        assert m.detect_already_have_subject("Nemam mirin, potrebujem nahradu bez lepku.") is None


class TestCanonicalSeedEndToEnd:
    def test_canonical_seed_no_bare_rice_recommended(self):
        r = _chat(CANONICAL_SEED, "v223g-canonical")
        assert not _has_bare_rice(_titles(r))

    def test_canonical_seed_returns_products(self):
        r = _chat(CANONICAL_SEED, "v223g-canonical-2")
        assert len(r.get("products") or []) > 0


class TestPositiveOwnershipParaphrases:
    def test_explicit_mam_ryzu(self):
        r = _chat("Mám ryžu, čo k nej uvariť?", "v223g-p1")
        assert not _has_bare_rice(_titles(r))

    def test_implicit_co_sa_hodi(self):
        r = _chat("Čo sa hodí k ryži?", "v223g-p2")
        assert not _has_bare_rice(_titles(r))

    def test_implicit_co_mozem_spravit(self):
        r = _chat("Čo môžem spraviť s ryžou?", "v223g-p3")
        assert not _has_bare_rice(_titles(r))

    def test_explicit_mam_doma_tofu(self):
        r = _chat("Mám doma tofu, čo z neho?", "v223g-p4")
        titles_normalized = [m.normalize(t) for t in _titles(r)]
        assert not any("tofu" in t for t in titles_normalized)

    def test_explicit_mam_udon_rezance(self):
        r = _chat("Mám udon rezance, čo k nim?", "v223g-p5")
        titles_normalized = [m.normalize(t) for t in _titles(r)]
        assert not any("udon" in t for t in titles_normalized)


class TestPurchaseIntentContrastPreserved:
    def test_buy_rice_still_recommends_rice(self):
        r = _chat("Akú ryžu mám kúpiť?", "v223g-neg1")
        assert _has_bare_rice(_titles(r))

    def test_recommend_rice_still_recommends_rice(self):
        r = _chat("Odporuč mi jazmínovú ryžu.", "v223g-neg2")
        assert _has_bare_rice(_titles(r))

    def test_need_sushi_rice_still_recommends_rice(self):
        r = _chat("Potrebujem ryžu na sushi.", "v223g-neg3")
        assert _has_bare_rice(_titles(r))

    def test_buy_tofu_still_recommends_tofu(self):
        r = _chat("Ktoré tofu mám kúpiť?", "v223g-neg4")
        titles_normalized = [m.normalize(t) for t in _titles(r)]
        assert any("tofu" in t for t in titles_normalized)

    def test_want_udon_still_recommends_udon(self):
        r = _chat("Chcem udon rezance.", "v223g-neg5")
        titles_normalized = [m.normalize(t) for t in _titles(r)]
        assert any("udon" in t for t in titles_normalized)


class TestExistingBehaviorPreservation:
    def test_faq_still_works(self):
        r = _chat("Aké máte možnosti platby?", "v223g-preserve-faq")
        assert r.get("intent") == "faq"

    def test_invoice_support_still_works(self):
        r = _chat("Potrebujem faktúru k poslednej objednávke.", "v223g-preserve-invoice")
        assert r.get("intent") == "invoice_support"

    def test_plain_product_search_still_works(self):
        r = _chat("Aké máte ryžové rezance?", "v223g-preserve-product")
        assert len(r.get("products") or []) > 0
