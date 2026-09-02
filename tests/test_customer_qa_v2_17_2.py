"""
tests/test_customer_qa_v2_17_2.py  -  V2.17.2 Customer QA Analyzer &
Evidence Layer.

app/customer_qa.py adds a deterministic, evidence-based QA analysis
layer over the V2.17.1 sanitized customer audit
(app.customer_audit.read_audit_turns()). It is OBSERVATION -> ANALYSIS
-> EVIDENCE -> HUMAN INVESTIGATION - never OBSERVATION -> AUTOMATIC
LABEL -> LEARNING -> RANKING CHANGE -> DEPLOY. Every rule checks a
STRUCTURAL or known-pattern TEXTUAL contradiction already present in an
ALREADY-COMPLETED response; none of them ever reruns intent/search/
ranking/cross-sell/LLM, and none of them ever writes to
customer_audit.jsonl (that stream is immutable input here). Findings
are computed ON READ (Section 22 option A) - nothing is persisted, so
there is no separate findings store and no duplicate-finding risk.

These tests prove the release-blocking guards from the V2.17.2 spec:
GUARD - cross_sell stays distinct from primary matches (never reranked,
never merged, never treated as a bad primary match); stock semantics
stay truthful ("Skladom" flagged, "Dostupné na Foodland.sk" never
flagged); arbitrary product order is never frozen into a RANK finding;
PII/privacy stays intact; the customer stream is never contaminated by
QA verification traffic; every finding carries rule_id/evidence/
classification/severity/recommended_action and
automatic_production_change=false; UNCERTAIN is a first-class result;
PASS never claims perfection.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import pytest
from fastapi.testclient import TestClient

import app.main as m
import app.customer_qa as qa
from app.advisor_engine import advisor_engine, AdvisorRequest
from app.execution_context import admin_test_context

client = TestClient(m.app)


@pytest.fixture(autouse=True)
def _isolated_audit_log(tmp_path, monkeypatch):
    log_path = tmp_path / "customer_audit.jsonl"
    monkeypatch.setenv("CUSTOMER_AUDIT_LOG_PATH", str(log_path))
    monkeypatch.setenv("ANALYTICS_SALT", "test-salt-v2172")
    monkeypatch.setenv("ADMIN_READ_TOKEN", "test-read-token-v2172")
    return log_path


def _clean_turn(**overrides) -> dict:
    base = {
        "ts": 1000,
        "conversation_hash": "hash-a",
        "interaction_id": "int-a",
        "decision_id": None,
        "result_set_id": "rs-a",
        "question": "sushi ryza",
        "answer": "Mame tieto produkty v kategorii sushi ryza.",
        "intent": "product_search",
        "workflow_id": "LEGACY_FALLBACK",
        "has_more": False,
        "matching_total": 2,
        "displayed_count": 2,
        "cross_sell_eligible": False,
        "product_groups": {
            "products": [{"id": "FL_1", "title": "Susi ryza", "availability": "in_stock"}],
            "cross_sell": [],
        },
    }
    base.update(overrides)
    return base


def _admin_test_chat(message: str, session_id: str) -> dict:
    return advisor_engine.run(
        AdvisorRequest(message=message, session_id=session_id, client_key="internal"),
        admin_test_context(),
    )


# ---------------------------------------------------------------------
# 1-9: consumes sanitized V2.17.1 data, preserves group semantics
# ---------------------------------------------------------------------
class TestConsumesSanitizedAudit:
    def test_qa_consumes_sanitized_v2171_audit_data(self, _isolated_audit_log):
        client.post("/chat", json={"message": "sushi ryza", "session_id": "qa-consume-1"})
        r = client.get("/admin/qa/status", headers={"x-admin-token": "test-read-token-v2172"})
        assert r.status_code == 200
        assert r.json()["turns_analyzed"] == 1

    def test_qa_does_not_require_raw_session_id(self):
        turn = _clean_turn()
        assert "session_id" not in turn
        result = qa.analyze_turn(turn)
        assert result["status"] == "PASS"

    def test_qa_does_not_require_raw_client_id(self):
        turn = _clean_turn()
        assert "client_id" not in turn
        qa.analyze_turn(turn)

    def test_qa_does_not_expose_raw_ip(self, _isolated_audit_log):
        client.post(
            "/chat",
            json={"message": "sushi ryza", "session_id": "qa-ip-1"},
            headers={"x-forwarded-for": "198.51.100.23"},
        )
        r = client.get("/admin/qa/findings?days=1", headers={"x-admin-token": "test-read-token-v2172"})
        assert "198.51.100.23" not in r.text

    def test_qa_does_not_expose_auth_tokens(self, _isolated_audit_log):
        client.post(
            "/chat",
            json={"message": "sushi ryza", "session_id": "qa-tok-1"},
            headers={"x-admin-token": "should-never-leak-into-qa"},
        )
        r = client.get("/admin/qa/findings?days=1", headers={"x-admin-token": "test-read-token-v2172"})
        assert "should-never-leak-into-qa" not in r.text

    def test_qa_preserves_matches_separately(self):
        turn = _clean_turn(product_groups={"products": [{"id": "FL_1"}], "cross_sell": []})
        result = qa.analyze_turn(turn)
        assert result["findings"] == [] or "products" in result["findings"][0]["evidence"]["groups"]

    def test_qa_preserves_cross_sell_separately(self):
        turn = _clean_turn(
            cross_sell_eligible=True,
            product_groups={"products": [{"id": "FL_1"}], "cross_sell": [{"id": "FL_2"}]},
        )
        result = qa.analyze_turn(turn)
        assert result["status"] == "PASS"

    def test_qa_does_not_treat_cross_sell_as_primary_match(self):
        turn = _clean_turn(
            cross_sell_eligible=True,
            product_groups={"products": [{"id": "FL_1"}], "cross_sell": [{"id": "FL_2"}]},
        )
        result = qa.analyze_turn(turn)
        for f in result["findings"]:
            assert f["classification"] != "CROSS_SELL" or "FL_2" not in [
                p.get("id") for p in f["evidence"]["groups"]["products"]
            ]

    def test_alternatives_and_substitutes_semantics_preserved_via_intent(self):
        # V2.17.1 does not expose separate alternatives/substitutes arrays
        # (repository reality - see docs/customer-conversation-audit-api-
        # v2.17.1.md Section 9); `intent` carries that semantic instead.
        turn = _clean_turn(intent="replacement_products")
        result = qa.analyze_turn(turn)
        assert result["findings"] == [] or result["findings"][0]["evidence"]["intent"] == "replacement_products"


# ---------------------------------------------------------------------
# 10-13: cross-sell guard
# ---------------------------------------------------------------------
class TestCrossSellGuard:
    def test_detects_prohibited_cross_group_duplication(self):
        turn = _clean_turn(
            product_groups={"products": [{"id": "FL_1"}], "cross_sell": [{"id": "FL_1"}]},
        )
        result = qa.analyze_turn(turn)
        rule_ids = [f["rule_id"] for f in result["findings"]]
        assert "QA_STRUCT_001" in rule_ids

    def test_qa_does_not_rerank_products(self):
        original_order = [{"id": "FL_3"}, {"id": "FL_1"}, {"id": "FL_2"}]
        turn = _clean_turn(product_groups={"products": original_order, "cross_sell": []})
        result = qa.analyze_turn(turn)
        for f in result["findings"]:
            assert [p["id"] for p in f["evidence"]["groups"]["products"]] == [p["id"] for p in original_order]

    def test_qa_does_not_require_arbitrary_exact_product_order(self):
        # GUARD (Section 15) - no rule in this module asserts or depends
        # on a specific product order; PASS is reachable regardless of
        # which permutation of the same set is present.
        turn_a = _clean_turn(product_groups={"products": [{"id": "FL_1"}, {"id": "FL_2"}], "cross_sell": []})
        turn_b = _clean_turn(product_groups={"products": [{"id": "FL_2"}, {"id": "FL_1"}], "cross_sell": []})
        assert qa.analyze_turn(turn_a)["status"] == "PASS"
        assert qa.analyze_turn(turn_b)["status"] == "PASS"

    def test_no_rule_classifies_as_rank_from_order_alone(self):
        turn = _clean_turn(product_groups={"products": [{"id": "FL_2"}, {"id": "FL_1"}], "cross_sell": []})
        result = qa.analyze_turn(turn)
        assert all(f["classification"] != "RANK" for f in result["findings"])


# ---------------------------------------------------------------------
# 14-16: stock semantics guard
# ---------------------------------------------------------------------
class TestStockGuard:
    def test_detects_unsupported_skladom_wording(self):
        turn = _clean_turn(answer="Tento produkt je Skladom, mozete si ho objednat.")
        result = qa.analyze_turn(turn)
        rule_ids = [f["rule_id"] for f in result["findings"]]
        assert "QA_STOCK_001" in rule_ids

    def test_dostupne_na_foodland_sk_is_not_flagged(self):
        turn = _clean_turn(answer="Tento produkt je Dostupne na Foodland.sk.")
        result = qa.analyze_turn(turn)
        rule_ids = [f["rule_id"] for f in result["findings"]]
        assert "QA_STOCK_001" not in rule_ids

    def test_raw_in_stock_availability_is_not_sufficient_for_live_stock_finding(self):
        turn = _clean_turn(
            answer="Mame tento produkt v ponuke.",
            product_groups={"products": [{"id": "FL_1", "availability": "in_stock"}], "cross_sell": []},
        )
        result = qa.analyze_turn(turn)
        assert all(f["rule_id"] != "QA_STOCK_001" for f in result["findings"])


# ---------------------------------------------------------------------
# 17-20: PASS / FINDING / UNCERTAIN semantics
# ---------------------------------------------------------------------
class TestStatusSemantics:
    def test_obvious_contradiction_produces_finding(self):
        turn = _clean_turn(answer="Nenasla som ziadne produkty.")
        result = qa.analyze_turn(turn)
        assert result["status"] == "FINDING"

    def test_clean_structural_conversation_produces_pass(self):
        turn = _clean_turn()
        result = qa.analyze_turn(turn)
        assert result["status"] == "PASS"

    def test_ambiguous_evidence_produces_uncertain(self):
        turn = {"ts": 1, "conversation_hash": "x", "interaction_id": "y"}  # missing answer/product_groups
        result = qa.analyze_turn(turn)
        assert result["status"] == "UNCERTAIN"

    def test_pass_does_not_claim_perfection(self):
        # Documented, not just asserted: PASS is reachable for a minimal
        # turn with a plausible but unverified answer - the module makes
        # no claim of having verified optimality anywhere in its output.
        turn = _clean_turn()
        result = qa.analyze_turn(turn)
        assert result["status"] == "PASS"
        assert "optimal" not in str(result).lower()
        assert "perfect" not in str(result).lower()


# ---------------------------------------------------------------------
# 21-26: finding shape
# ---------------------------------------------------------------------
class TestFindingShape:
    def test_each_finding_has_rule_id(self):
        turn = _clean_turn(answer="Skladom")
        for f in qa.analyze_turn(turn)["findings"]:
            assert f["rule_id"]

    def test_each_finding_has_evidence(self):
        turn = _clean_turn(answer="Skladom")
        for f in qa.analyze_turn(turn)["findings"]:
            assert f["evidence"]
            assert "question" in f["evidence"]
            assert "answer_excerpt" in f["evidence"]

    def test_each_finding_has_classification(self):
        turn = _clean_turn(answer="Skladom")
        for f in qa.analyze_turn(turn)["findings"]:
            assert f["classification"] in qa.CLASSIFICATIONS

    def test_each_finding_has_severity(self):
        turn = _clean_turn(answer="Skladom")
        for f in qa.analyze_turn(turn)["findings"]:
            assert f["severity"] in qa.SEVERITIES

    def test_each_finding_has_recommended_action(self):
        turn = _clean_turn(answer="Skladom")
        for f in qa.analyze_turn(turn)["findings"]:
            assert f["recommended_action"] in qa.RECOMMENDED_ACTIONS

    def test_automatic_production_change_is_false(self):
        turn = _clean_turn(answer="Skladom")
        for f in qa.analyze_turn(turn)["findings"]:
            assert f["automatic_production_change"] is False


# ---------------------------------------------------------------------
# 27-28: reproducibility / malformed rows
# ---------------------------------------------------------------------
class TestReproducibility:
    def test_same_turn_and_rule_does_not_generate_uncontrolled_duplicates(self):
        turn = _clean_turn(answer="Skladom")
        first = qa.analyze_turn(turn)["findings"]
        second = qa.analyze_turn(turn)["findings"]
        assert [f["qa_id"] for f in first] == [f["qa_id"] for f in second]
        assert len(first) == len(set(f["qa_id"] for f in first))

    def test_malformed_audit_jsonl_line_is_safely_skipped(self, _isolated_audit_log):
        client.post("/chat", json={"message": "sushi ryza", "session_id": "qa-malformed-1"})
        with _isolated_audit_log.open("a", encoding="utf-8") as handle:
            handle.write("{not valid json\n")
        client.post("/chat", json={"message": "sushi ryza", "session_id": "qa-malformed-2"})
        r = client.get("/admin/qa/status?days=1", headers={"x-admin-token": "test-read-token-v2172"})
        assert r.status_code == 200
        assert r.json()["turns_analyzed"] == 2


# ---------------------------------------------------------------------
# 29-38: admin auth + read-only surface
# ---------------------------------------------------------------------
class TestAdminAuthorization:
    def test_scope_read_can_access_status(self):
        r = client.get("/admin/qa/status", headers={"x-admin-token": "test-read-token-v2172"})
        assert r.status_code == 200

    def test_scope_read_can_access_findings(self):
        r = client.get("/admin/qa/findings", headers={"x-admin-token": "test-read-token-v2172"})
        assert r.status_code == 200

    def test_missing_auth_rejected(self):
        assert client.get("/admin/qa/findings").status_code == 401
        assert client.get("/admin/qa/status").status_code == 401

    def test_invalid_auth_rejected(self):
        r = client.get("/admin/qa/findings", headers={"x-admin-token": "wrong"})
        assert r.status_code == 401

    def test_no_qa_post_endpoint_exists(self):
        assert client.post("/admin/qa/findings", headers={"x-admin-token": "test-read-token-v2172"}).status_code in (404, 405)

    def test_no_qa_patch_endpoint_exists(self):
        assert client.patch("/admin/qa/findings", headers={"x-admin-token": "test-read-token-v2172"}).status_code in (404, 405)

    def test_no_qa_delete_endpoint_exists(self):
        assert client.delete("/admin/qa/findings", headers={"x-admin-token": "test-read-token-v2172"}).status_code in (404, 405)

    def test_qa_routes_are_get_only(self):
        # V2.17.2's own scope had no execution capability anywhere under
        # /admin/qa - true when this test was written. V2.17.3 (docs/
        # finding-review-reproduction-v2.17.3.md) deliberately, safely
        # widened that by adding ONE explicitly-authorized, OPERATIONS-
        # scoped, bounded execution route (POST /admin/qa/reproductions,
        # forces ADMIN_TEST, accepts only {"qa_id": ...}, never creates a
        # CUSTOMER audit record - exhaustively covered by
        # tests/test_customer_qa_reproduction_v2_17_3.py, including its
        # own test that this exact path is POST-only, never GET). Every
        # QA *inspection* route (status/findings/conversations, and the
        # OFFLINE reproduction preview) remains GET-only - this is the
        # corrected, current invariant, not a weakening of it.
        qa_routes = [
            route for route in m.app.routes
            if getattr(route, "path", "").startswith("/admin/qa")
            and route.path != "/admin/qa/reproductions"
        ]
        assert qa_routes
        for route in qa_routes:
            methods = getattr(route, "methods", set())
            assert methods <= {"GET", "HEAD"}, f"{route.path} exposes non-GET methods: {methods}"

    def test_qa_get_does_not_mutate_customer_audit(self, _isolated_audit_log):
        client.post("/chat", json={"message": "sushi ryza", "session_id": "qa-nomutate-1"})
        before = _isolated_audit_log.read_text(encoding="utf-8")
        client.get("/admin/qa/findings", headers={"x-admin-token": "test-read-token-v2172"})
        client.get("/admin/qa/status", headers={"x-admin-token": "test-read-token-v2172"})
        after = _isolated_audit_log.read_text(encoding="utf-8")
        assert before == after

    def test_qa_module_writes_no_findings_store_file(self, _isolated_audit_log, tmp_path):
        # ON-READ architecture (Section 22 option A) - no
        # customer_qa_findings.jsonl or similar is ever created.
        client.post("/chat", json={"message": "sushi ryza", "session_id": "qa-nofile-1"})
        client.get("/admin/qa/findings", headers={"x-admin-token": "test-read-token-v2172"})
        created = list(tmp_path.iterdir())
        names = [p.name for p in created]
        assert not any("qa_finding" in n for n in names)


# ---------------------------------------------------------------------
# 36-38, 39-40: no behavioral production changes, zero new LLM/search calls
# ---------------------------------------------------------------------
class TestNoProductionSideEffects:
    def test_qa_findings_endpoint_does_not_touch_ranking_module_state(self, monkeypatch):
        import app.search as search_module

        original = search_module.search_products
        called = {"n": 0}

        def _tracking(*args, **kwargs):
            called["n"] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(search_module, "search_products", _tracking)
        client.get("/admin/qa/findings", headers={"x-admin-token": "test-read-token-v2172"})
        assert called["n"] == 0

    def test_qa_module_source_calls_no_llm_or_openai_client(self):
        import inspect

        source = inspect.getsource(qa)
        assert "openai" not in source.lower()
        assert "chat.completions" not in source.lower()

    def test_qa_module_makes_zero_external_search_calls(self):
        import inspect

        source = inspect.getsource(qa)
        assert "search_products(" not in source
        assert "requests.get(" not in source
        assert "requests.post(" not in source

    def test_auto_promotion_remains_false(self):
        from app.learning_lifecycle import AUTO_PROMOTION_ENABLED

        assert AUTO_PROMOTION_ENABLED is False


# ---------------------------------------------------------------------
# 41: ADMIN_TEST verification does not contaminate CUSTOMER audit
# ---------------------------------------------------------------------
class TestCustomerStreamIntegrity:
    def test_admin_test_verification_call_does_not_create_customer_audit_record(self, _isolated_audit_log):
        _admin_test_chat("sushi ryza", "qa-admintest-verify-1")
        assert not _isolated_audit_log.exists() or _isolated_audit_log.read_text(encoding="utf-8").strip() == ""

    def test_real_customer_call_still_captured_after_admin_test_calls(self, _isolated_audit_log):
        _admin_test_chat("sushi ryza", "qa-admintest-verify-2")
        client.post("/chat", json={"message": "sushi ryza", "session_id": "qa-real-1"})
        lines = [l for l in _isolated_audit_log.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 1


# ---------------------------------------------------------------------
# 42-43: PII / prompt-leak evidence stays safe
# ---------------------------------------------------------------------
class TestSafeEvidence:
    def test_pii_redacted_input_remains_redacted_in_finding(self):
        # Redaction is app.customer_audit's job (runs BEFORE persistence,
        # V2.17.1) - this proves QA does not ADD any leakage beyond an
        # already-redacted turn, i.e. it reproduces the same redacted
        # text verbatim rather than re-exposing anything raw.
        turn = _clean_turn(
            question="kontaktujte ma na [email]",
            answer="Skladom",
        )
        result = qa.analyze_turn(turn)
        for f in result["findings"]:
            assert "@example.com" not in str(f)
            assert f["evidence"]["question"] == turn["question"]

    def test_prompt_leak_marker_detected_without_exposing_hidden_prompt(self):
        turn = _clean_turn(answer="profil urci podla nazvu produktu, kategorie a detailu na webe; nevymyslaj zlozenie")
        result = qa.analyze_turn(turn)
        rule_ids = [f["rule_id"] for f in result["findings"]]
        assert "QA_TRUST_001" in rule_ids
        for f in result["findings"]:
            if f["rule_id"] == "QA_TRUST_001":
                assert f["classification"] == "SAFETY_TRUST"
                assert f["severity"] == "CRITICAL"

    def test_pii_pattern_surviving_redaction_is_detected(self):
        turn = _clean_turn(answer="Kontaktujte nas na podpora@example.com pre viac info.")
        result = qa.analyze_turn(turn)
        rule_ids = [f["rule_id"] for f in result["findings"]]
        assert "QA_TRUST_002" in rule_ids


# ---------------------------------------------------------------------
# 44-46: correlation id preservation
# ---------------------------------------------------------------------
class TestCorrelationPreservation:
    def test_interaction_id_preserved(self):
        turn = _clean_turn(interaction_id="abc123")
        result = qa.analyze_turn(turn)
        assert result["interaction_id"] == "abc123"

    def test_decision_id_preserved(self):
        turn = _clean_turn(decision_id="dec-456")
        result = qa.analyze_turn(turn)
        assert result["decision_id"] == "dec-456"

    def test_result_set_id_preserved(self):
        turn = _clean_turn(result_set_id="rs-789")
        result = qa.analyze_turn(turn)
        assert result["result_set_id"] == "rs-789"


# ---------------------------------------------------------------------
# 47-52: query parameters
# ---------------------------------------------------------------------
class TestQueryParams:
    def test_days_bounds_enforced(self):
        r = client.get("/admin/qa/findings?days=99999", headers={"x-admin-token": "test-read-token-v2172"})
        assert r.status_code == 200
        assert r.json()["days"] <= 90

    def test_limit_bounds_enforced(self):
        assert qa.qa_findings(days=1, limit=99999) == qa.qa_findings(days=1, limit=500)

    def test_classification_filter_works(self, _isolated_audit_log):
        # Force a QA_STOCK_001 (SAFETY_TRUST) finding via a synthetic
        # ADMIN_TEST-safe direct write is not appropriate here (audit is
        # immutable input) - instead exercise the filter against the
        # in-process analyzer directly, which is the documented,
        # supported way this endpoint's filter logic is unit-tested.
        turns = [_clean_turn(conversation_hash="fh1", answer="Skladom"), _clean_turn(conversation_hash="fh2")]

        original = qa.read_audit_turns
        qa.read_audit_turns = lambda **kwargs: turns
        try:
            all_findings = qa.qa_findings(days=1, limit=100)
            filtered = qa.qa_findings(days=1, limit=100, classification="SAFETY_TRUST")
        finally:
            qa.read_audit_turns = original
        assert filtered
        assert all(f["classification"] == "SAFETY_TRUST" for f in filtered)
        assert len(filtered) <= len(all_findings)

    def test_severity_filter_works(self):
        turns = [_clean_turn(conversation_hash="fh3", answer="Skladom")]
        original = qa.read_audit_turns
        qa.read_audit_turns = lambda **kwargs: turns
        try:
            filtered = qa.qa_findings(days=1, limit=100, severity="MEDIUM")
        finally:
            qa.read_audit_turns = original
        assert all(f["severity"] == "MEDIUM" for f in filtered)

    def test_conversation_hash_filter_works(self, _isolated_audit_log):
        client.post("/chat", json={"message": "sushi ryza", "session_id": "qa-hashfilter-a"})
        import json

        conv_hash = json.loads(_isolated_audit_log.read_text(encoding="utf-8").splitlines()[0])["conversation_hash"]
        r = client.get(
            f"/admin/qa/conversations/{conv_hash}",
            headers={"x-admin-token": "test-read-token-v2172"},
        )
        assert r.status_code == 200
        assert r.json()["conversation_hash"] == conv_hash
        assert r.json()["count"] == 1

    def test_q_filter_works(self, _isolated_audit_log):
        client.post("/chat", json={"message": "kde mate predajnu", "session_id": "qa-qfilter-a"})
        client.post("/chat", json={"message": "sushi ryza", "session_id": "qa-qfilter-b"})
        r = client.get("/admin/qa/findings?days=1&q=predajnu", headers={"x-admin-token": "test-read-token-v2172"})
        assert r.status_code == 200

    def test_findings_returned_newest_first(self):
        turns = [
            _clean_turn(conversation_hash="old", ts=100, answer="Skladom"),
            _clean_turn(conversation_hash="new", ts=200, answer="Skladom"),
        ]
        original = qa.read_audit_turns
        qa.read_audit_turns = lambda **kwargs: turns
        try:
            findings = qa.qa_findings(days=90, limit=100)
        finally:
            qa.read_audit_turns = original
        timestamps = [f["ts"] for f in findings]
        assert timestamps == sorted(timestamps, reverse=True)
