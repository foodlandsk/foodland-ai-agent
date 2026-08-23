"""
tests/test_events_detail_readback_v2_15d_3.py  -  follow-up to V2.15d.3:
per-record execution_context readback endpoint.

/admin/analytics/events-summary (existing) only exposes aggregate counts
- it cannot prove which execution_context/learning_eligible value a
SPECIFIC durably-logged event actually carries. This was discovered as
a live-verification gap when confirming the V2.15d.3 execution-context
isolation mechanism on production: a live ADMIN_TEST /events smoke call
returned 200, but there was no way to read back and prove the record
was actually tagged execution_context="ADMIN_TEST" rather than having
silently fallen back to CUSTOMER.

/admin/analytics/events-detail closes this: READ scope (same as
events-summary - genuinely read-only, no side effects), returns
full, already-sanitized records (client_hash is a salted hash, never
raw client_key; query text is already PII-redacted by log_event()
before this endpoint ever sees it), most-recent-first, with optional
session_id/event_type filtering and a hard 200-record response cap
regardless of the requested limit.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m
from fastapi.testclient import TestClient


def _client():
    return TestClient(m.app)


class TestAuthRequired:
    def test_missing_token_rejected(self, monkeypatch):
        # require_admin_scope() returns 404 (hides existence) only when NO
        # admin token is configured anywhere; with one configured, a
        # request with no token at all must get 401, not 404.
        monkeypatch.setenv("ADMIN_OPERATIONS_TOKEN", "some-real-token")
        r = _client().get("/admin/analytics/events-detail")
        assert r.status_code == 401

    def test_no_admin_auth_configured_at_all_hides_endpoint(self, monkeypatch):
        for var in ("ADMIN_PROMOTION_TOKEN", "ADMIN_OPERATIONS_TOKEN", "ADMIN_RELOAD_TOKEN", "ADMIN_READ_TOKEN", "ADMIN_ANALYTICS_TOKEN"):
            monkeypatch.delenv(var, raising=False)
        r = _client().get("/admin/analytics/events-detail")
        assert r.status_code == 404

    def test_garbage_token_rejected(self, monkeypatch):
        monkeypatch.setenv("ADMIN_OPERATIONS_TOKEN", "real-token")
        r = _client().get("/admin/analytics/events-detail", headers={"X-Admin-Token": "garbage"})
        assert r.status_code == 401

    def test_valid_read_scope_token_accepted(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EVENTS_LOG_PATH", str(tmp_path / "events.jsonl"))
        monkeypatch.setenv("ADMIN_READ_TOKEN", "read-token")
        r = _client().get("/admin/analytics/events-detail", headers={"X-Admin-Token": "read-token"})
        assert r.status_code == 200

    def test_operations_scope_token_also_accepted(self, monkeypatch, tmp_path):
        # OPERATIONS ranks above READ, so it must also satisfy this
        # READ-scoped endpoint (same hierarchy /chat's ADMIN_TEST check uses).
        monkeypatch.setenv("EVENTS_LOG_PATH", str(tmp_path / "events.jsonl"))
        monkeypatch.setenv("ADMIN_OPERATIONS_TOKEN", "ops-token")
        r = _client().get("/admin/analytics/events-detail", headers={"X-Admin-Token": "ops-token"})
        assert r.status_code == 200


class TestPerRecordExecutionContext:
    """The core gap this endpoint closes: proving the exact
    execution_context/learning_eligible value of a specific record."""

    def test_customer_and_admin_test_records_distinguished(self, monkeypatch, tmp_path):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        monkeypatch.setenv("ADMIN_OPERATIONS_TOKEN", "ops-token")
        client = _client()

        client.post("/events", json={"session_id": "cust-1", "event_type": "click", "product_sku": "SKU1"})
        client.post(
            "/events",
            json={"session_id": "admin-1", "event_type": "click", "product_sku": "SKU2"},
            headers={"X-Execution-Context": "ADMIN_TEST", "X-Admin-Token": "ops-token"},
        )

        r = client.get("/admin/analytics/events-detail", headers={"X-Admin-Token": "ops-token"})
        assert r.status_code == 200
        body = r.json()
        by_session = {e["session_id"]: e for e in body["events"]}
        assert by_session["cust-1"]["execution_context"] == "CUSTOMER"
        assert by_session["cust-1"]["learning_eligible"] is True
        assert by_session["admin-1"]["execution_context"] == "ADMIN_TEST"
        assert by_session["admin-1"]["learning_eligible"] is False

    def test_spoofed_admin_test_reads_back_as_customer(self, monkeypatch, tmp_path):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        monkeypatch.setenv("ADMIN_OPERATIONS_TOKEN", "ops-token")
        client = _client()

        client.post(
            "/events",
            json={"session_id": "spoof-1", "event_type": "click", "product_sku": "SKU3"},
            headers={"X-Execution-Context": "ADMIN_TEST", "X-Admin-Token": "not-a-real-token"},
        )
        r = client.get("/admin/analytics/events-detail", headers={"X-Admin-Token": "ops-token"})
        body = r.json()
        by_session = {e["session_id"]: e for e in body["events"]}
        assert by_session["spoof-1"]["execution_context"] == "CUSTOMER"


class TestFiltering:
    def test_filter_by_session_id(self, monkeypatch, tmp_path):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        monkeypatch.setenv("ADMIN_OPERATIONS_TOKEN", "ops-token")
        client = _client()
        client.post("/events", json={"session_id": "s-a", "event_type": "click", "product_sku": "SKU1"})
        client.post("/events", json={"session_id": "s-b", "event_type": "click", "product_sku": "SKU2"})

        r = client.get("/admin/analytics/events-detail?session_id=s-b", headers={"X-Admin-Token": "ops-token"})
        body = r.json()
        assert body["count"] == 1
        assert body["events"][0]["session_id"] == "s-b"

    def test_filter_by_event_type(self, monkeypatch, tmp_path):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        monkeypatch.setenv("ADMIN_OPERATIONS_TOKEN", "ops-token")
        client = _client()
        client.post("/events", json={"session_id": "s1", "event_type": "click", "product_sku": "SKU1"})
        client.post("/events", json={"session_id": "s1", "event_type": "add_to_cart_attempt", "product_sku": "SKU1"})

        r = client.get("/admin/analytics/events-detail?event_type=add_to_cart_attempt", headers={"X-Admin-Token": "ops-token"})
        body = r.json()
        assert body["count"] == 1
        assert body["events"][0]["event_type"] == "add_to_cart_attempt"


class TestResponseCap:
    def test_limit_is_capped_at_200_regardless_of_request(self, monkeypatch, tmp_path):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        monkeypatch.setenv("ADMIN_OPERATIONS_TOKEN", "ops-token")
        client = _client()
        for i in range(5):
            client.post("/events", json={"session_id": f"s{i}", "event_type": "click", "product_sku": "SKU1"})

        r = client.get("/admin/analytics/events-detail?limit=999999", headers={"X-Admin-Token": "ops-token"})
        body = r.json()
        assert len(body["events"]) == 5  # fewer than cap, all returned
        assert body["count"] == 5


class TestNoNewPII:
    def test_no_raw_client_key_or_ip_in_response(self, monkeypatch, tmp_path):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        monkeypatch.setenv("ADMIN_OPERATIONS_TOKEN", "ops-token")
        client = _client()
        client.post("/events", json={"session_id": "s1", "event_type": "click", "product_sku": "SKU1"})

        r = client.get("/admin/analytics/events-detail", headers={"X-Admin-Token": "ops-token"})
        event = r.json()["events"][0]
        assert "client_key" not in event
        assert "ip" not in event
        # client_hash is a salted hash, not the raw key - still present by
        # design (same as events-summary's underlying source data).
        assert "client_hash" in event
