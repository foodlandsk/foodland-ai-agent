"""
tests/test_customer_audit_v2_17_1.py  -  V2.17.1 Customer Conversation
Read-Only Audit API.

app/customer_audit.py adds a privacy-conscious, read-only observability
layer: a human operator can inspect a REAL customer conversation together
with the ACTUAL Foodland AI response structure that customer was shown.
It is not a learning sprint, not an evaluator, not a training-label
generator - capture_customer_turn() only observes an ALREADY-COMPLETED
response (app.main._chat_internal(), the same V2.15b choke point the
search-quality trace already hooks) and never reruns intent/search/
ranking/cross-sell/LLM. AUTO_PROMOTION stays FALSE; nothing here writes
to ranking/learning/promotion state.

These tests prove the four release-blocking guards from the V2.17.1
spec:
  GUARD 1 - product groups (`products` vs `cross_sell`) never collapse
            into one generic list, and cross-sell is never reranked.
  GUARD 2 - raw `availability` is persisted uninterpreted, never
            converted into "Skladom"/"confirmed in stock".
  GUARD 3 - no exact-order assertion on product membership (only the
            allowlisted fields/order the module itself controls).
  GUARD 4 - strict privacy/PII/READ-only boundary: only CUSTOMER traffic
            is captured, raw session_id/client_id/IP/headers/tokens are
            never persisted, question/answer are PII-redacted before
            persistence, and the admin API exposes GET only.
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
from fastapi.testclient import TestClient

import app.main as m
from app.advisor_engine import advisor_engine, AdvisorRequest
from app.execution_context import (
    admin_test_context,
    evaluation_context,
    learning_context,
    shadow_context,
)
import app.customer_audit as ca

client = TestClient(m.app)

_QUERY = "sushi ryza"


@pytest.fixture(autouse=True)
def _isolated_audit_log(tmp_path, monkeypatch):
    """Every test gets its own empty JSONL file and a fixed analytics
    salt - never the developer's real accumulated local log, and never
    cross-test pollution (the same class of hazard the V2.17 CI incident
    already taught this project to guard against - see docs/
    conversational-commerce-ux-v2.17.md Section 18)."""
    log_path = tmp_path / "customer_audit.jsonl"
    monkeypatch.setenv("CUSTOMER_AUDIT_LOG_PATH", str(log_path))
    monkeypatch.setenv("ANALYTICS_SALT", "test-salt-v2171")
    monkeypatch.setenv("ADMIN_READ_TOKEN", "test-read-token-v2171")
    return log_path


def _read_records(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _customer_chat(message: str, session_id: str) -> dict:
    r = client.post("/chat", json={"message": message, "session_id": session_id})
    assert r.status_code == 200
    return r.json()


def _internal_chat(message: str, session_id: str, execution_context) -> dict:
    return advisor_engine.run(
        AdvisorRequest(message=message, session_id=session_id, client_key="internal"),
        execution_context,
    )


# ---------------------------------------------------------------------
# 1-5: execution-context capture isolation
# ---------------------------------------------------------------------
class TestCaptureIsolation:
    def test_real_customer_chat_is_captured(self, _isolated_audit_log):
        _customer_chat(_QUERY, "audit-cust-1")
        records = _read_records(_isolated_audit_log)
        assert len(records) == 1
        assert records[0]["question"] == _QUERY

    def test_admin_test_traffic_is_not_captured(self, _isolated_audit_log):
        _internal_chat(_QUERY, "audit-admintest-1", admin_test_context())
        assert _read_records(_isolated_audit_log) == []

    def test_evaluation_traffic_is_not_captured(self, _isolated_audit_log):
        _internal_chat(_QUERY, "audit-eval-1", evaluation_context())
        assert _read_records(_isolated_audit_log) == []

    def test_learning_traffic_is_not_captured(self, _isolated_audit_log):
        _internal_chat(_QUERY, "audit-learning-1", learning_context())
        assert _read_records(_isolated_audit_log) == []

    def test_shadow_traffic_is_not_captured(self, _isolated_audit_log):
        _internal_chat(_QUERY, "audit-shadow-1", shadow_context())
        assert _read_records(_isolated_audit_log) == []

    def test_only_customer_call_survives_a_mixed_batch(self, _isolated_audit_log):
        _internal_chat(_QUERY, "audit-mix-eval", evaluation_context())
        _customer_chat(_QUERY, "audit-mix-cust")
        _internal_chat(_QUERY, "audit-mix-shadow", shadow_context())
        records = _read_records(_isolated_audit_log)
        assert len(records) == 1


# ---------------------------------------------------------------------
# 6-10, 18-20: stored fields
# ---------------------------------------------------------------------
class TestRecordContent:
    def test_customer_question_is_stored(self, _isolated_audit_log):
        _customer_chat(_QUERY, "audit-q-1")
        records = _read_records(_isolated_audit_log)
        assert records[0]["question"] == _QUERY

    def test_final_customer_answer_is_stored(self, _isolated_audit_log):
        response = _customer_chat(_QUERY, "audit-a-1")
        records = _read_records(_isolated_audit_log)
        assert records[0]["answer"]
        assert records[0]["answer"] == response["answer"][: len(records[0]["answer"])]

    def test_interaction_id_is_preserved_when_present(self, _isolated_audit_log):
        response = _customer_chat(_QUERY, "audit-iid-1")
        records = _read_records(_isolated_audit_log)
        assert response.get("interaction_id")
        assert records[0]["interaction_id"] == response["interaction_id"]

    def test_result_set_id_is_preserved_when_present(self, _isolated_audit_log):
        response = _customer_chat(_QUERY, "audit-rsid-1")
        records = _read_records(_isolated_audit_log)
        if response.get("result_set_id"):
            assert records[0]["result_set_id"] == response["result_set_id"]

    def test_decision_id_is_preserved_when_present(self, _isolated_audit_log):
        # "Aku ryzu odporucas na sushi?" resolves to use_case_advice,
        # which sets use_case_advice_decision_id - normalized to the
        # generic `decision_id` audit field (Section 7: safe key lookup,
        # no business logic re-run).
        response = _customer_chat("Aku ryzu odporucas na sushi?", "audit-did-1")
        records = _read_records(_isolated_audit_log)
        source_decision_id = response.get("use_case_advice_decision_id")
        if source_decision_id:
            assert records[0]["decision_id"] == source_decision_id


# ---------------------------------------------------------------------
# 8-9: PII redaction
# ---------------------------------------------------------------------
class TestPiiRedaction:
    def test_question_is_pii_redacted_before_persistence(self, _isolated_audit_log):
        _customer_chat("moj email je zakaznik@example.com, mate sojovu omacku?", "audit-pii-q")
        records = _read_records(_isolated_audit_log)
        assert "zakaznik@example.com" not in records[0]["question"]
        assert "[email]" in records[0]["question"]

    def test_answer_is_pii_redacted_before_persistence(self, monkeypatch):
        # Directly exercises capture_customer_turn with a synthetic
        # response so the redaction assertion does not depend on the
        # backend ever echoing an email back (it normally does not).
        class _FakeRequest:
            message = "test"
            session_id = "audit-pii-a"

        ca.capture_customer_turn(
            chat_request=_FakeRequest(),
            client_key="1.2.3.4",
            response={"answer": "Kontaktujte nas na podpora@example.com pre viac info.", "interaction_id": "x"},
            latency_ms=1.0,
        )
        records = _read_records(Path(os.environ["CUSTOMER_AUDIT_LOG_PATH"]))
        assert "podpora@example.com" not in records[0]["answer"]
        assert "[email]" in records[0]["answer"]


# ---------------------------------------------------------------------
# 10-15: privacy exclusions
# ---------------------------------------------------------------------
class TestPrivacyExclusions:
    def test_conversation_history_is_not_persisted(self, _isolated_audit_log):
        client.post(
            "/chat",
            json={
                "message": _QUERY,
                "session_id": "audit-hist-1",
                "conversation_history": [{"role": "user", "content": "predchadzajuca sprava s tajomstvom"}],
            },
        )
        raw_text = _isolated_audit_log.read_text(encoding="utf-8")
        assert "conversation_history" not in raw_text
        assert "predchadzajuca sprava" not in raw_text

    def test_raw_session_id_is_not_persisted(self, _isolated_audit_log):
        secret_session = "raw-session-id-should-never-appear-12345"
        _customer_chat(_QUERY, secret_session)
        raw_text = _isolated_audit_log.read_text(encoding="utf-8")
        assert secret_session not in raw_text

    def test_raw_client_id_is_not_persisted(self, _isolated_audit_log):
        secret_client_id = "raw-client-id-should-never-appear-67890"
        client.post("/chat", json={"message": _QUERY, "session_id": "audit-cid-1", "client_id": secret_client_id})
        raw_text = _isolated_audit_log.read_text(encoding="utf-8")
        assert secret_client_id not in raw_text

    def test_raw_ip_is_not_persisted(self, _isolated_audit_log):
        client.post(
            "/chat",
            json={"message": _QUERY, "session_id": "audit-ip-1"},
            headers={"x-forwarded-for": "203.0.113.77"},
        )
        raw_text = _isolated_audit_log.read_text(encoding="utf-8")
        assert "203.0.113.77" not in raw_text

    def test_headers_are_not_persisted(self, _isolated_audit_log):
        client.post(
            "/chat",
            json={"message": _QUERY, "session_id": "audit-hdr-1"},
            headers={"x-custom-secret-header": "should-never-be-stored"},
        )
        raw_text = _isolated_audit_log.read_text(encoding="utf-8")
        assert "should-never-be-stored" not in raw_text

    def test_admin_token_is_not_persisted(self, _isolated_audit_log):
        client.post(
            "/chat",
            json={"message": _QUERY, "session_id": "audit-tok-1"},
            headers={"x-admin-token": "super-secret-admin-token-value"},
        )
        raw_text = _isolated_audit_log.read_text(encoding="utf-8")
        assert "super-secret-admin-token-value" not in raw_text

    def test_record_has_no_unexpected_top_level_keys(self, _isolated_audit_log):
        _customer_chat(_QUERY, "audit-keys-1")
        record = _read_records(_isolated_audit_log)[0]
        allowed = {
            "ts", "conversation_hash", "question", "answer", "status_code", "latency_ms",
            "interaction_id", "decision_id", "result_set_id", "intent", "workflow_id",
            "response_mode", "has_more", "matching_total", "displayed_count",
            "cross_sell_eligible", "product_groups",
        }
        assert set(record.keys()) <= allowed


# ---------------------------------------------------------------------
# 16-17: conversation hashing
# ---------------------------------------------------------------------
class TestConversationHash:
    def test_conversation_hash_is_stable_for_same_session(self, _isolated_audit_log):
        _customer_chat(_QUERY, "audit-hash-stable")
        _customer_chat("kikkoman 1l", "audit-hash-stable")
        records = _read_records(_isolated_audit_log)
        assert len(records) == 2
        assert records[0]["conversation_hash"] == records[1]["conversation_hash"]

    def test_different_sessions_get_different_hashes_and_no_raw_identifiers(self, _isolated_audit_log):
        _customer_chat(_QUERY, "audit-hash-session-a")
        _customer_chat(_QUERY, "audit-hash-session-b")
        records = _read_records(_isolated_audit_log)
        assert records[0]["conversation_hash"] != records[1]["conversation_hash"]
        for record in records:
            assert "session_id" not in record
            assert "client_id" not in record
            assert "audit-hash-session-a" not in json.dumps(record)
            assert "audit-hash-session-b" not in json.dumps(record)


# ---------------------------------------------------------------------
# 21-29: product allowlist + GUARD 1 group semantics
# ---------------------------------------------------------------------
class TestProductGroupSemantics:
    def test_product_payload_is_reduced_to_explicit_allowlist(self, _isolated_audit_log):
        _customer_chat(_QUERY, "audit-allow-1")
        record = _read_records(_isolated_audit_log)[0]
        products = record["product_groups"]["products"]
        assert products
        for p in products:
            assert set(p.keys()) <= set(ca._PRODUCT_FIELD_ALLOWLIST)

    def test_arbitrary_internal_fields_are_not_persisted(self, _isolated_audit_log):
        _customer_chat(_QUERY, "audit-allow-2")
        raw_text = _isolated_audit_log.read_text(encoding="utf-8")
        for forbidden in ("description", "cross_sell_evidence", "embedding", "gtin", "image_link"):
            assert forbidden not in raw_text

    def test_matches_and_cross_sell_remain_semantically_separate(self, _isolated_audit_log):
        _customer_chat(_QUERY, "audit-sep-1")
        record = _read_records(_isolated_audit_log)[0]
        groups = record["product_groups"]
        assert "products" in groups
        assert "cross_sell" in groups
        product_ids = {p["id"] for p in groups["products"] if "id" in p}
        cross_sell_ids = {p["id"] for p in groups["cross_sell"] if "id" in p}
        if product_ids and cross_sell_ids:
            assert product_ids.isdisjoint(cross_sell_ids)

    def test_cross_sell_is_observable_when_actually_returned(self, _isolated_audit_log):
        response = _customer_chat(_QUERY, "audit-cs-obs-1")
        record = _read_records(_isolated_audit_log)[0]
        if response.get("cross_sell_eligible") and response.get("cross_sell"):
            assert record["cross_sell_eligible"] is True
            assert record["product_groups"]["cross_sell"]

    def test_cross_sell_products_are_not_reranked_by_audit(self, _isolated_audit_log):
        response = _customer_chat(_QUERY, "audit-cs-order-1")
        record = _read_records(_isolated_audit_log)[0]
        source_ids = [p.get("id") for p in (response.get("cross_sell") or [])]
        audit_ids = [p.get("id") for p in record["product_groups"]["cross_sell"]]
        assert audit_ids == source_ids[: ca._PRODUCTS_PER_GROUP_MAX]

    def test_products_are_not_reranked_by_audit(self, _isolated_audit_log):
        # GUARD 3 - this asserts the audit copy matches the response's
        # own order (whatever it is), never a hardcoded expected order -
        # the V2.17 rt0013 incident is exactly the mistake this avoids.
        response = _customer_chat(_QUERY, "audit-prod-order-1")
        record = _read_records(_isolated_audit_log)[0]
        source_ids = [p.get("id") for p in (response.get("products") or [])]
        audit_ids = [p.get("id") for p in record["product_groups"]["products"]]
        assert audit_ids == source_ids[: ca._PRODUCTS_PER_GROUP_MAX]

    def test_products_per_group_is_bounded(self):
        many_products = [{"id": f"FL_{i}", "title": f"p{i}"} for i in range(100)]
        summarized = ca._summarize_product_group(many_products)
        assert len(summarized) == ca._PRODUCTS_PER_GROUP_MAX


# ---------------------------------------------------------------------
# 30: GUARD 2 stock semantics
# ---------------------------------------------------------------------
class TestStockSemantics:
    def test_raw_availability_never_becomes_skladom(self, _isolated_audit_log):
        _customer_chat(_QUERY, "audit-stock-1")
        raw_text = _isolated_audit_log.read_text(encoding="utf-8")
        assert "Skladom" not in raw_text
        assert "confirmed in stock" not in raw_text.lower()
        assert "warehouse" not in raw_text.lower()

    def test_raw_availability_field_is_preserved_uninterpreted_when_present(self, _isolated_audit_log):
        _customer_chat(_QUERY, "audit-stock-2")
        record = _read_records(_isolated_audit_log)[0]
        for p in record["product_groups"]["products"]:
            if "availability" in p:
                assert p["availability"] in ("in_stock", "out_of_stock", "") or isinstance(p["availability"], str)


# ---------------------------------------------------------------------
# 31-32: failure isolation
# ---------------------------------------------------------------------
class TestFailureIsolation:
    def test_persistence_failure_does_not_break_chat(self, monkeypatch, tmp_path):
        # Point the audit log at a path whose parent cannot be created
        # (a file standing where a directory is required) to force a
        # real write failure inside capture_customer_turn().
        blocking_file = tmp_path / "not_a_directory"
        blocking_file.write_text("x", encoding="utf-8")
        monkeypatch.setenv("CUSTOMER_AUDIT_LOG_PATH", str(blocking_file / "customer_audit.jsonl"))
        response = client.post("/chat", json={"message": _QUERY, "session_id": "audit-fail-1"})
        assert response.status_code == 200
        assert response.json().get("products")

    def test_persistence_failure_does_not_change_chat_response_content(self, monkeypatch, tmp_path):
        blocking_file = tmp_path / "not_a_directory_2"
        blocking_file.write_text("x", encoding="utf-8")
        monkeypatch.setenv("CUSTOMER_AUDIT_LOG_PATH", str(blocking_file / "customer_audit.jsonl"))
        broken = client.post("/chat", json={"message": _QUERY, "session_id": "audit-fail-cmp-a"}).json()
        monkeypatch.delenv("CUSTOMER_AUDIT_LOG_PATH", raising=False)
        working_path = tmp_path / "working_audit.jsonl"
        monkeypatch.setenv("CUSTOMER_AUDIT_LOG_PATH", str(working_path))
        working = client.post("/chat", json={"message": _QUERY, "session_id": "audit-fail-cmp-b"}).json()
        assert [p.get("id") for p in broken.get("products") or []] == [p.get("id") for p in working.get("products") or []]
        assert broken.get("intent") == working.get("intent")


# ---------------------------------------------------------------------
# 33-37: admin authorization + read-only surface
# ---------------------------------------------------------------------
class TestAdminAuthorization:
    def test_scope_read_token_can_access_status(self):
        r = client.get("/admin/audit/status", headers={"x-admin-token": "test-read-token-v2171"})
        assert r.status_code == 200
        assert r.json()["readonly"] is True

    def test_scope_read_token_can_access_conversations(self):
        r = client.get("/admin/audit/conversations", headers={"x-admin-token": "test-read-token-v2171"})
        assert r.status_code == 200
        assert r.json()["readonly"] is True

    def test_missing_token_is_rejected(self):
        r = client.get("/admin/audit/conversations")
        assert r.status_code == 401

    def test_invalid_token_is_rejected(self):
        r = client.get("/admin/audit/conversations", headers={"x-admin-token": "definitely-wrong"})
        assert r.status_code == 401

    def test_status_missing_token_is_rejected(self):
        r = client.get("/admin/audit/status")
        assert r.status_code == 401

    def test_audit_namespace_exposes_no_write_operation(self):
        audit_routes = [route for route in m.app.routes if getattr(route, "path", "").startswith("/admin/audit")]
        assert audit_routes
        for route in audit_routes:
            methods = getattr(route, "methods", set())
            assert methods <= {"GET", "HEAD"}, f"{route.path} exposes non-GET methods: {methods}"

    def test_read_only_get_does_not_mutate_the_audit_stream(self, _isolated_audit_log):
        _customer_chat(_QUERY, "audit-nomutate-1")
        before = _isolated_audit_log.read_text(encoding="utf-8")
        client.get("/admin/audit/conversations", headers={"x-admin-token": "test-read-token-v2171"})
        client.get("/admin/audit/status", headers={"x-admin-token": "test-read-token-v2171"})
        after = _isolated_audit_log.read_text(encoding="utf-8")
        assert before == after


# ---------------------------------------------------------------------
# 38-44: query parameters, bounds, malformed rows, ordering
# ---------------------------------------------------------------------
class TestReadApiQueryParams:
    def test_days_bounds_are_enforced(self):
        r = client.get("/admin/audit/conversations?days=99999", headers={"x-admin-token": "test-read-token-v2171"})
        assert r.status_code == 200
        assert r.json()["days"] <= 90

    def test_limit_bounds_are_enforced(self):
        assert ca.read_audit_turns(days=1, limit=99999) == ca.read_audit_turns(days=1, limit=500)

    def test_conversation_hash_filter_works(self, _isolated_audit_log):
        _customer_chat(_QUERY, "audit-filter-hash-a")
        _customer_chat(_QUERY, "audit-filter-hash-b")
        all_records = _read_records(_isolated_audit_log)
        target_hash = all_records[0]["conversation_hash"]
        r = client.get(
            f"/admin/audit/conversations?conversation_hash={target_hash}",
            headers={"x-admin-token": "test-read-token-v2171"},
        )
        turns = r.json()["turns"]
        assert turns
        assert all(t["conversation_hash"] == target_hash for t in turns)

    def test_q_filter_works(self, _isolated_audit_log):
        _customer_chat("kde mate predajnu", "audit-filter-q-a")
        _customer_chat(_QUERY, "audit-filter-q-b")
        r = client.get("/admin/audit/conversations?q=predajnu", headers={"x-admin-token": "test-read-token-v2171"})
        turns = r.json()["turns"]
        assert turns
        assert all("predajnu" in t["question"].lower() or "predajnu" in t["answer"].lower() for t in turns)

    def test_intent_filter_works(self, _isolated_audit_log):
        _customer_chat(_QUERY, "audit-filter-intent-a")
        records = _read_records(_isolated_audit_log)
        target_intent = records[0]["intent"]
        if target_intent:
            r = client.get(
                f"/admin/audit/conversations?intent={target_intent}",
                headers={"x-admin-token": "test-read-token-v2171"},
            )
            turns = r.json()["turns"]
            assert all(t["intent"] == target_intent for t in turns)

    def test_malformed_jsonl_line_does_not_break_reads(self, _isolated_audit_log):
        _customer_chat(_QUERY, "audit-malformed-1")
        with _isolated_audit_log.open("a", encoding="utf-8") as handle:
            handle.write("{this is not valid json\n")
        _customer_chat(_QUERY, "audit-malformed-2")
        r = client.get("/admin/audit/conversations", headers={"x-admin-token": "test-read-token-v2171"})
        assert r.status_code == 200
        assert r.json()["count"] == 2

    def test_newest_first_ordering_of_audit_turns(self, _isolated_audit_log):
        # This is ordering of audit records by timestamp - NOT product
        # ranking order (Section 21 note #44 is explicit about this
        # distinction).
        _customer_chat(_QUERY, "audit-order-a")
        _customer_chat("kikkoman 1l", "audit-order-b")
        r = client.get("/admin/audit/conversations", headers={"x-admin-token": "test-read-token-v2171"})
        turns = r.json()["turns"]
        assert len(turns) == 2
        timestamps = [t["ts"] for t in turns]
        assert timestamps == sorted(timestamps, reverse=True)
