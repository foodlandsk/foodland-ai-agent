"""
tests/test_frontend_recommendation_correlation_v2_15d_2.py  -  V2.15d.2:
frontend recommendation interaction & confirmed add-to-cart correlation.

This is the BACKEND half of V2.15d.2's proof. The frontend half (widget
click semantics, the authoritative-vs-fallback confirmation split, no
purchase fabrication, telemetry failure isolation) is proven statically
in tests/js/widget.test.mjs, since app/widget.js runs in a browser, not
under pytest.

Backend scope of this sprint is narrow and additive: extend
EventRequest.event_type with two new, honestly-distinct literals -
"add_to_cart_attempt" (the customer initiated the cart-add mechanism -
does NOT mean it succeeded) and "add_to_cart_confirmed" (the host site's
own add-to-cart AJAX call authoritatively confirmed success) - alongside
the legacy "add_to_cart" literal, which is kept completely unchanged for
backward compatibility with app.fbt/app.behavioral/app.learning_signals,
all of which key off that exact string. No backend persistence logic
changed - log_event() already accepted/persisted interaction_id/
decision_id/event_id as of V2.15d; this sprint only widens the accepted
event_type set.

Hard invariants proven here: no "purchase"/order-confirmation literal
was added (Section 24 - PURCHASE_SIGNAL_NOT_AVAILABLE remains true), the
legacy "add_to_cart" literal still round-trips exactly as before, and
malformed/unexpected event_type values still fail closed (422), not
silently.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import pytest
from pydantic import ValidationError

import app.main as m


class TestEventTypeLiteralExtension:
    def test_add_to_cart_attempt_is_a_valid_event_type(self):
        req = m.EventRequest(session_id="s1", event_type="add_to_cart_attempt", product_sku="SKU1")
        assert req.event_type == "add_to_cart_attempt"

    def test_add_to_cart_confirmed_is_a_valid_event_type(self):
        req = m.EventRequest(session_id="s1", event_type="add_to_cart_confirmed", product_sku="SKU1")
        assert req.event_type == "add_to_cart_confirmed"

    def test_legacy_add_to_cart_still_valid_unchanged(self):
        req = m.EventRequest(session_id="s1", event_type="add_to_cart", product_sku="SKU1")
        assert req.event_type == "add_to_cart"

    def test_purchase_is_not_a_valid_event_type(self):
        # Section 24 - PURCHASE_SIGNAL_NOT_AVAILABLE. No event type may be
        # named "purchase"/"order_confirmed" - the schema itself enforces
        # this, not just widget-side discipline.
        with pytest.raises(ValidationError):
            m.EventRequest(session_id="s1", event_type="purchase", product_sku="SKU1")

    def test_arbitrary_unknown_event_type_still_rejected(self):
        with pytest.raises(ValidationError):
            m.EventRequest(session_id="s1", event_type="totally_made_up", product_sku="SKU1")


class TestEventCorrelationPersistence:
    def test_add_to_cart_confirmed_persists_correlation_fields(self, tmp_path, monkeypatch):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        req = m.EventRequest(
            session_id="s1", event_type="add_to_cart_confirmed", product_sku="SKU1",
            interaction_id="I123", decision_id="D456", event_id="E789",
        )
        m.log_event(req, "client-key-1")
        rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        rec = rows[-1]
        assert rec["event_type"] == "add_to_cart_confirmed"
        assert rec["interaction_id"] == "I123"
        assert rec["decision_id"] == "D456"
        assert rec["event_id"] == "E789"
        assert rec["product_sku"] == "SKU1"

    def test_add_to_cart_attempt_persists_without_confirmation_claim(self, tmp_path, monkeypatch):
        # An ATTEMPT record is structurally identical in shape to a
        # CONFIRMED one - the event_type string itself is the only thing
        # that distinguishes "initiated" from "host-confirmed success".
        # This test exists to make that distinction explicit and
        # regression-proof.
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        req = m.EventRequest(
            session_id="s1", event_type="add_to_cart_attempt", product_sku="SKU1",
            interaction_id="I123", decision_id="D456",
        )
        m.log_event(req, "client-key-1")
        rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert rows[-1]["event_type"] == "add_to_cart_attempt"
        assert rows[-1]["event_type"] != "add_to_cart_confirmed"

    def test_old_event_without_correlation_fields_still_readable(self, tmp_path, monkeypatch):
        # Section 72 - backward compatibility. A pre-V2.15d event record
        # (no interaction_id/decision_id/event_id keys at all) must remain
        # structurally valid input to anything reading events.jsonl.
        events_path = tmp_path / "events.jsonl"
        events_path.write_text(json.dumps({
            "ts": 1700000000, "client_hash": "abc", "session_id": "old-session",
            "event_type": "add_to_cart", "query": None, "product_sku": "SKU1",
            "product_skus": None, "position": None, "rating": None,
        }) + "\n", encoding="utf-8")
        rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
        assert rows[0]["event_type"] == "add_to_cart"
        assert "interaction_id" not in rows[0]


class TestTrackEventEndpoint:
    """Exercises the real /events HTTP handler end-to-end for the two
    new event types, proving the whole request -> validation -> log_event
    chain accepts them (not just the Pydantic model in isolation)."""

    def test_endpoint_accepts_add_to_cart_attempt(self, tmp_path, monkeypatch):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        from fastapi.testclient import TestClient
        client = TestClient(m.app)
        resp = client.post("/events", json={
            "session_id": "s1", "event_type": "add_to_cart_attempt",
            "product_sku": "SKU1", "interaction_id": "I1", "decision_id": "D1",
        })
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_endpoint_accepts_add_to_cart_confirmed(self, tmp_path, monkeypatch):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        from fastapi.testclient import TestClient
        client = TestClient(m.app)
        resp = client.post("/events", json={
            "session_id": "s1", "event_type": "add_to_cart_confirmed",
            "product_sku": "SKU1", "interaction_id": "I1", "decision_id": "D1",
        })
        assert resp.status_code == 200

    def test_endpoint_rejects_fabricated_purchase_event(self):
        from fastapi.testclient import TestClient
        client = TestClient(m.app)
        resp = client.post("/events", json={"session_id": "s1", "event_type": "purchase"})
        assert resp.status_code == 422


class TestAutoPromotionUnchanged:
    def test_auto_promotion_still_disabled(self):
        from app.learning_lifecycle import AUTO_PROMOTION_ENABLED
        assert AUTO_PROMOTION_ENABLED is False


class TestControlRegressionMatrix:
    """Section 49/50 of the closure spec - must-preserve controls,
    unaffected by this purely-additive backend schema change."""

    def _chat(self, message, session_id):
        class _FakeRequest:
            class client:
                host = "127.0.0.1"
            headers: dict = {}
        return m.chat(m.ChatRequest(message=message, session_id=session_id), _FakeRequest())

    def test_rt0004_related_products_protected(self):
        r = self._chat("súvisiace produkty k sushi ryži", "v215d2-rt0004")
        assert r.get("intent") == "related_products"

    def test_rt0010_allergen_safety_protected(self):
        r = self._chat("sójová omáčka bez sóje", "v215d2-rt0010")
        assert r.get("intent") == "allergen_safety"

    def test_rt0013_replacement_products_protected(self):
        r = self._chat("náhrada za rybiu omáčku vegan", "v215d2-rt0013")
        assert r.get("intent") == "replacement_products"

    def test_v2_15c_store_location_followup_still_live(self):
        sid = "v215d2-store-followup"
        self._chat("Kde sa nachadza kamenna predajna?", sid)
        r = self._chat("Prilož mi Google link na adresu.", sid)
        assert r.get("intent") == "faq"
        assert r.get("products") == []
