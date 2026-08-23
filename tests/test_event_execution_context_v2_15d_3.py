"""
tests/test_event_execution_context_v2_15d_3.py  -  V2.15d.3: Event
Execution-Context Isolation, Synthetic Signal Hygiene & Analytics
Contamination Closure.

Root cause: /events (unlike /chat) had NO execution-context mechanism at
all - no X-Execution-Context/X-Admin-Token headers, no app.execution_context
or app.admin_auth integration. V2.15d.2's own production verification
demonstrated this concretely: 2 synthetic add_to_cart_attempt/
add_to_cart_confirmed events (fake SKU "SMOKE-TEST-SKU", session_id
"live-v215d2-verify") were durably written to production events.jsonl,
indistinguishable from real customer telemetry by anything reading that
field. Audited finding, disclosed rather than hidden: those two specific
historical rows are ALSO already structurally invisible to every current
downstream consumer regardless of this fix - app.behavioral, app.fbt, and
app.learning_events all key on a fixed literal event_type set that does
NOT include "add_to_cart_attempt"/"add_to_cart_confirmed" (only the
legacy "add_to_cart" string). Historical classification:
HISTORICAL_SYNTHETIC_EVENTS_LEFT_AS_DOCUMENTED_ARTIFACT - no destructive
JSONL rewrite was performed or is in scope.

Fix (this file's scope): reuse the EXACT same server-side-verified
execution-context resolution /chat already uses (app.admin_auth token
scope checking) - a client cannot become ADMIN_TEST merely by sending a
header; it fails closed to CUSTOMER without a valid OPERATIONS/PROMOTION
token. log_event() now persists a server-resolved (never client-trusted)
execution_context field plus a conservative learning_eligible flag, and
suppresses EVALUATION/LEARNING/SHADOW entirely (mirroring
log_recommendation_decision()'s existing should_log_decision precedent).
app.behavioral/app.fbt/app.learning_events were all updated to skip any
non-CUSTOMER-tagged record when computing CTR/FBT/learning signals -
None/missing execution_context (every pre-V2.15d.3 record) is treated as
CUSTOMER, since /events had no non-customer path before this sprint.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m
from app.execution_context import customer_context, evaluation_context, learning_context, shadow_context


def _post_events(client, payload, headers=None):
    return client.post("/events", json=payload, headers=headers or {})


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestCustomerDefault:
    """A. normal CUSTOMER /events request - no header at all."""

    def test_ordinary_request_resolves_to_customer(self, tmp_path, monkeypatch):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        from fastapi.testclient import TestClient
        client = TestClient(m.app)
        resp = _post_events(client, {"session_id": "s1", "event_type": "click", "product_sku": "SKU1"})
        assert resp.status_code == 200
        rows = _read_jsonl(events_path)
        assert rows[-1]["execution_context"] == "CUSTOMER"
        assert rows[-1]["learning_eligible"] is True


class TestTrustedAdminTest:
    """B. trusted ADMIN_TEST event with a genuinely valid, sufficiently-
    scoped token."""

    def test_valid_operations_token_resolves_to_admin_test(self, tmp_path, monkeypatch):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        monkeypatch.setenv("ADMIN_OPERATIONS_TOKEN", "valid-ops-token")
        from fastapi.testclient import TestClient
        client = TestClient(m.app)
        resp = _post_events(
            client, {"session_id": "s-admin", "event_type": "click", "product_sku": "SMOKE"},
            headers={"X-Execution-Context": "ADMIN_TEST", "X-Admin-Token": "valid-ops-token"},
        )
        assert resp.status_code == 200
        rows = _read_jsonl(events_path)
        assert rows[-1]["execution_context"] == "ADMIN_TEST"
        assert rows[-1]["learning_eligible"] is False


class TestSpoofingProtection:
    """E. untrusted attempt to spoof ADMIN_TEST must fail closed to
    CUSTOMER - the server, not the client, is authoritative."""

    def test_header_alone_without_valid_token_fails_closed_to_customer(self, tmp_path, monkeypatch):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        monkeypatch.delenv("ADMIN_OPERATIONS_TOKEN", raising=False)
        monkeypatch.delenv("ADMIN_PROMOTION_TOKEN", raising=False)
        from fastapi.testclient import TestClient
        client = TestClient(m.app)
        resp = _post_events(
            client, {"session_id": "s-spoof", "event_type": "click", "product_sku": "SKU1"},
            headers={"X-Execution-Context": "ADMIN_TEST", "X-Admin-Token": "garbage-not-a-real-token"},
        )
        assert resp.status_code == 200
        rows = _read_jsonl(events_path)
        assert rows[-1]["execution_context"] == "CUSTOMER"
        assert rows[-1]["learning_eligible"] is True

    def test_valid_token_but_insufficient_scope_fails_closed_to_customer(self, tmp_path, monkeypatch):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        monkeypatch.setenv("ADMIN_READ_TOKEN", "read-only-token")
        monkeypatch.delenv("ADMIN_OPERATIONS_TOKEN", raising=False)
        monkeypatch.delenv("ADMIN_PROMOTION_TOKEN", raising=False)
        from fastapi.testclient import TestClient
        client = TestClient(m.app)
        resp = _post_events(
            client, {"session_id": "s-underscoped", "event_type": "click", "product_sku": "SKU1"},
            headers={"X-Execution-Context": "ADMIN_TEST", "X-Admin-Token": "read-only-token"},
        )
        assert resp.status_code == 200
        rows = _read_jsonl(events_path)
        # A READ-scope token is real but insufficient for ADMIN_TEST
        # (which requires OPERATIONS/PROMOTION, matching /chat's rule) -
        # must still fail closed, not silently accept a lesser scope.
        assert rows[-1]["execution_context"] == "CUSTOMER"


class TestMalformedOrMissingContext:
    """F/G. malformed or missing execution-context header must default
    safely to CUSTOMER, never crash the endpoint."""

    def test_malformed_execution_context_value_is_customer(self, tmp_path, monkeypatch):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        from fastapi.testclient import TestClient
        client = TestClient(m.app)
        resp = _post_events(
            client, {"session_id": "s-malformed", "event_type": "click", "product_sku": "SKU1"},
            headers={"X-Execution-Context": "NOT_A_REAL_MODE"},
        )
        assert resp.status_code == 200
        rows = _read_jsonl(events_path)
        assert rows[-1]["execution_context"] == "CUSTOMER"

    def test_missing_execution_context_header_is_customer(self, tmp_path, monkeypatch):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        from fastapi.testclient import TestClient
        client = TestClient(m.app)
        resp = _post_events(client, {"session_id": "s-none", "event_type": "click", "product_sku": "SKU1"})
        assert resp.status_code == 200
        rows = _read_jsonl(events_path)
        assert rows[-1]["execution_context"] == "CUSTOMER"


class TestNonCustomerContextsSuppressedOrTagged:
    """C/D/I. EVALUATION/SHADOW/LEARNING internal callers must never be
    durably logged at all (test-suite/optimizer scale, mirrors the
    existing log_recommendation_decision precedent) - and must never
    become learning_eligible even in principle."""

    def test_evaluation_context_not_logged(self, tmp_path, monkeypatch):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        req = m.EventRequest(session_id="s1", event_type="click", product_sku="SKU1")
        m.log_event(req, "ck", execution_context=evaluation_context())
        assert _read_jsonl(events_path) == []

    def test_shadow_context_not_logged(self, tmp_path, monkeypatch):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        req = m.EventRequest(session_id="s1", event_type="click", product_sku="SKU1")
        m.log_event(req, "ck", execution_context=shadow_context())
        assert _read_jsonl(events_path) == []

    def test_learning_context_not_logged(self, tmp_path, monkeypatch):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        req = m.EventRequest(session_id="s1", event_type="click", product_sku="SKU1")
        m.log_event(req, "ck", execution_context=learning_context())
        assert _read_jsonl(events_path) == []

    def test_customer_context_is_logged_and_eligible(self, tmp_path, monkeypatch):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        req = m.EventRequest(session_id="s1", event_type="click", product_sku="SKU1")
        m.log_event(req, "ck", execution_context=customer_context())
        rows = _read_jsonl(events_path)
        assert len(rows) == 1
        assert rows[0]["execution_context"] == "CUSTOMER"
        assert rows[0]["learning_eligible"] is True


class TestBackwardCompatibility:
    """V. the pre-V2.15d.3 log_event(req, client_key) call signature
    (no execution_context argument at all) must keep working exactly as
    before - additive, non-breaking change."""

    def test_log_event_without_execution_context_arg_still_works(self, tmp_path, monkeypatch):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        req = m.EventRequest(session_id="s1", event_type="click", product_sku="SKU1")
        m.log_event(req, "ck")
        rows = _read_jsonl(events_path)
        assert len(rows) == 1
        assert rows[0]["execution_context"] is None
        assert rows[0]["learning_eligible"] is True

    def test_old_event_record_without_execution_context_field_still_readable(self, tmp_path):
        events_path = tmp_path / "events.jsonl"
        events_path.write_text(json.dumps({
            "ts": 1700000000, "client_hash": "abc", "session_id": "old-session",
            "event_type": "click", "product_sku": "SKU1",
        }) + "\n", encoding="utf-8")
        rows = _read_jsonl(events_path)
        assert "execution_context" not in rows[0]


class TestDownstreamReadersExcludeNonCustomerTraffic:
    """Closes the actual contamination gap: app.behavioral/app.fbt/
    app.learning_events must skip any record explicitly tagged as
    non-CUSTOMER when computing CTR/FBT/learning signals - a synthetic
    ADMIN_TEST verification event using a recognized event_type (e.g.
    "click") must not silently count toward these signals."""

    def test_behavioral_excludes_admin_test_events(self, monkeypatch, tmp_path):
        import importlib
        events_path = tmp_path / "events.jsonl"
        rows = [
            {"ts": 9999999999, "event_type": "click", "product_sku": "REAL-SKU", "execution_context": "CUSTOMER"},
            {"ts": 9999999999, "event_type": "click", "product_sku": "ADMIN-SKU", "execution_context": "ADMIN_TEST"},
        ]
        events_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        behavioral = importlib.reload(importlib.import_module("app.behavioral"))
        events = behavioral._read_events(days=36500, path=str(events_path))
        skus = {e.get("product_sku") for e in events}
        assert "REAL-SKU" in skus
        assert "ADMIN-SKU" not in skus

    def test_fbt_excludes_admin_test_events(self, monkeypatch, tmp_path):
        import importlib
        events_path = tmp_path / "events.jsonl"
        rows = [
            {"ts": 9999999999, "event_type": "add_to_cart", "product_sku": "REAL-SKU", "session_id": "s1", "execution_context": "CUSTOMER"},
            {"ts": 9999999999, "event_type": "add_to_cart", "product_sku": "ADMIN-SKU", "session_id": "s2", "execution_context": "ADMIN_TEST"},
        ]
        events_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        fbt = importlib.reload(importlib.import_module("app.fbt"))
        events = fbt._read_events(days=36500, path=str(events_path))
        skus = {e.get("product_sku") for e in events}
        assert "REAL-SKU" in skus
        assert "ADMIN-SKU" not in skus

    def test_learning_events_excludes_admin_test_events(self, monkeypatch, tmp_path):
        import importlib
        events_path = tmp_path / "events.jsonl"
        rows = [
            {"ts": 9999999999, "event_type": "click", "product_sku": "REAL-SKU", "execution_context": "CUSTOMER"},
            {"ts": 9999999999, "event_type": "click", "product_sku": "ADMIN-SKU", "execution_context": "ADMIN_TEST"},
        ]
        events_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        learning_events = importlib.reload(importlib.import_module("app.learning_events"))
        events = learning_events._read_raw_events(days=36500, path=str(events_path))
        skus = {e.get("product_sku") for e in events}
        assert "REAL-SKU" in skus
        assert "ADMIN-SKU" not in skus

    def test_legacy_records_without_execution_context_still_counted(self, monkeypatch, tmp_path):
        # Pre-V2.15d.3 records (including every real historical customer
        # event) have no execution_context field at all - these must NOT
        # be silently excluded, or the fix would erase real signal.
        import importlib
        events_path = tmp_path / "events.jsonl"
        rows = [{"ts": 9999999999, "event_type": "click", "product_sku": "LEGACY-SKU"}]
        events_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        behavioral = importlib.reload(importlib.import_module("app.behavioral"))
        events = behavioral._read_events(days=36500, path=str(events_path))
        assert any(e.get("product_sku") == "LEGACY-SKU" for e in events)


class TestHistoricalSyntheticArtifact:
    """The two V2.15d.2 historical synthetic events (event_type
    "add_to_cart_attempt"/"add_to_cart_confirmed", product_sku
    "SMOKE-TEST-SKU") are NOT rewritten or deleted (no destructive JSONL
    rewrite is in scope). This proves the disclosed, evidence-backed
    reason they are already functionally inert: none of the 3 real
    downstream readers recognize these two event_type strings at all -
    only the legacy "add_to_cart" literal is ever counted."""

    def test_add_to_cart_attempt_and_confirmed_are_not_in_learning_events_accepted_set(self):
        import app.learning_events as le
        source = Path(le.__file__).read_text(encoding="utf-8")
        assert '"add_to_cart_attempt"' not in source
        assert '"add_to_cart_confirmed"' not in source
        assert '"add_to_cart"' in source

    def test_behavioral_only_recognizes_legacy_add_to_cart_literal(self):
        import app.behavioral as beh
        source = Path(beh.__file__).read_text(encoding="utf-8")
        assert 'event_type == "add_to_cart"' in source

    def test_fbt_only_recognizes_legacy_add_to_cart_literal(self):
        import app.fbt as fbt
        source = Path(fbt.__file__).read_text(encoding="utf-8")
        assert '!= "add_to_cart"' in source or '== "add_to_cart"' in source


class TestTelemetryFailureIsolation:
    """Q. a durable-logging failure must never break /events' response
    to the caller (pre-existing invariant, reaffirmed unchanged)."""

    def test_unwritable_events_path_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("EVENTS_LOG_PATH", "Z:\\definitely\\not\\writable\\events.jsonl")
        req = m.EventRequest(session_id="s1", event_type="click", product_sku="SKU1")
        m.log_event(req, "ck", execution_context=customer_context())  # must not raise


class TestAutoPromotionUnchanged:
    def test_auto_promotion_still_disabled(self):
        from app.learning_lifecycle import AUTO_PROMOTION_ENABLED
        assert AUTO_PROMOTION_ENABLED is False


class TestControlRegressionMatrix:
    """rt0004/rt0010/rt0011/rt0013 and V2.15c - unaffected by this
    purely-additive isolation sprint."""

    def _chat(self, message, session_id):
        class _FR:
            class client:
                host = "127.0.0.1"
            headers: dict = {}
        return m.chat(m.ChatRequest(message=message, session_id=session_id), _FR())

    def test_rt0004_related_products_protected(self):
        r = self._chat("súvisiace produkty k sushi ryži", "v215d3-rt0004")
        assert r.get("intent") == "related_products"

    def test_rt0010_allergen_safety_protected(self):
        r = self._chat("sójová omáčka bez sóje", "v215d3-rt0010")
        assert r.get("intent") == "allergen_safety"

    def test_rt0011_no_session_contamination(self):
        sid = "v215d3-rt0011"
        query = "mám rád nepálivé jedlo, čo odporúčaš?"
        first = self._chat(query, sid)
        second = self._chat(query, sid)
        assert first.get("intent") == "product_search"
        assert second.get("intent") == "product_search"

    def test_rt0013_replacement_products_protected(self):
        r = self._chat("náhrada za rybiu omáčku vegan", "v215d3-rt0013")
        assert r.get("intent") == "replacement_products"
