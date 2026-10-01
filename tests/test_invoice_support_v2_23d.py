"""
tests/test_invoice_support_v2_23d.py  -  V2.23d bounded invoice-support
routing repair.

V2.23c (real-customer seed rc-186acdd43f93, human-curated V2.23b) found
that an invoice/order-support request ("faktura k poslednej objednavke")
had no matching FAQ record anywhere in data/knowledge.json, so it fell
through FAQ retrieval, recipe, and every other branch all the way to the
generic product_search fallback - returning unrelated products instead
of a support answer. This sprint adds one narrow, routing-only fix
(app.main.is_invoice_support_query()/invoice_support_answer(), and one
early-return branch in app.main._chat_impl()) - no data/knowledge.json
edit, no ALREADY_HAVE, no recipe/ranking change.
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


CANONICAL_SEED = "Dobrý deň, potrebovala by som faktúru k poslednej objednávke."

FABRICATION_MARKERS = (
    "vasa objednavka c", "cislo objednavky je", "vasa faktura je", "faktura bola odoslana",
    "your order number is", "here is your invoice", "i found your invoice", "your last order was",
)


class TestIsInvoiceSupportQueryDetector:
    def test_canonical_seed_detected(self):
        assert m.is_invoice_support_query(CANONICAL_SEED) is True

    def test_bare_faktur_stem_detected(self):
        assert m.is_invoice_support_query("Potrebujem faktúru.") is True

    def test_bare_invoice_word_detected(self):
        assert m.is_invoice_support_query("Can I get an invoice please?") is True

    def test_doklad_alone_not_detected(self):
        # "doklad" is a generic Slovak word for "document/proof" (see
        # app.explanation's unrelated "nemam doklad na to" usage) - it
        # must not fire without an order-context word alongside it.
        assert m.is_invoice_support_query("Nemám na to doklad.") is False

    def test_doklad_with_order_context_detected(self):
        assert m.is_invoice_support_query("Potrebujem doklad k objednávke.") is True

    def test_payment_methods_not_detected(self):
        assert m.is_invoice_support_query("Aké máte možnosti platby?") is False

    def test_order_tracking_not_detected(self):
        assert m.is_invoice_support_query("Kde je moja objednávka?") is False

    def test_plain_product_order_not_detected(self):
        assert m.is_invoice_support_query("Chcem objednať ryžový papier.") is False

    def test_complaint_not_detected(self):
        assert m.is_invoice_support_query("Chcem reklamovať objednávku.") is False


class TestInvoiceSupportAnswerContract:
    def test_slovak_answer_has_no_fabrication_and_has_contact_channel(self):
        answer = m.invoice_support_answer("sk")
        normalized = m.normalize(answer)
        assert "eshop@foodland.sk" in answer
        for marker in FABRICATION_MARKERS:
            assert marker not in normalized

    def test_english_answer_has_no_fabrication_and_has_contact_channel(self):
        answer = m.invoice_support_answer("en")
        normalized = m.normalize(answer)
        assert "eshop@foodland.sk" in answer
        for marker in FABRICATION_MARKERS:
            assert marker not in normalized


class TestCanonicalSeedEndToEnd:
    """Section 9/20 of the V2.23d mandate - the canonical real-customer
    seed must now resolve to a pure support answer."""

    def test_canonical_seed_routes_to_invoice_support(self):
        r = _chat(CANONICAL_SEED, "v223d-canonical")
        assert r.get("intent") == "invoice_support"
        assert (r.get("products") or []) == []

    def test_canonical_seed_answer_is_not_fabricated(self):
        r = _chat(CANONICAL_SEED, "v223d-canonical-fab")
        normalized = m.normalize(r.get("answer") or "")
        for marker in FABRICATION_MARKERS:
            assert marker not in normalized


class TestPositiveParaphrases:
    """Section 10/21 - bounded equivalents of the canonical seed."""

    def test_p1(self):
        r = _chat("Potrebujem faktúru k poslednej objednávke.", "v223d-p1")
        assert r.get("intent") == "invoice_support"
        assert (r.get("products") or []) == []

    def test_p2(self):
        r = _chat("Kde nájdem faktúru za posledný nákup?", "v223d-p2")
        assert r.get("intent") == "invoice_support"
        assert (r.get("products") or []) == []

    def test_p3(self):
        r = _chat("Viete mi poslať faktúru k objednávke?", "v223d-p3")
        assert r.get("intent") == "invoice_support"
        assert (r.get("products") or []) == []

    def test_p4_doklad(self):
        r = _chat("Potrebujem doklad k objednávke.", "v223d-p4")
        assert r.get("intent") == "invoice_support"
        assert (r.get("products") or []) == []


class TestNegativeCollisionControls:
    """Section 11/12/13/14/22 - invoice-support must not hijack nearby
    payment/order-tracking/complaint/plain-product queries."""

    def test_payment_methods_stays_faq(self):
        r = _chat("Aké máte možnosti platby?", "v223d-neg-payment")
        assert r.get("intent") == "faq"

    def test_order_tracking_stays_faq_not_invoice(self):
        r = _chat("Kde je moja objednávka?", "v223d-neg-tracking")
        assert r.get("intent") == "faq"
        assert r.get("intent") != "invoice_support"

    def test_plain_product_order_with_order_word_not_hijacked(self):
        r = _chat("Chcem objednať ryžový papier.", "v223d-neg-product")
        assert r.get("intent") != "invoice_support"
        assert len(r.get("products") or []) > 0

    def test_complaint_not_hijacked_into_invoice_support(self):
        r = _chat("Chcem reklamovať objednávku.", "v223d-neg-complaint")
        assert r.get("intent") != "invoice_support"

    def test_payment_then_invoice_question_is_invoice_support(self):
        # Section 13 - genuinely about an invoice, correctly captured.
        r = _chat("Zaplatil som kartou, kde je faktúra?", "v223d-pos-payment-invoice")
        assert r.get("intent") == "invoice_support"
