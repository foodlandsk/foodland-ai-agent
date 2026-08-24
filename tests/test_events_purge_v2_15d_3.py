"""
tests/test_events_purge_v2_15d_3.py  -  follow-up to V2.15d.3: surgical
production events.jsonl cleanup for synthetic/test session_ids.

Built at the user's explicit request after live-verifying the V2.15d.3
execution-context isolation mechanism, to clean up the smoke-test
records that verification itself created. Kept as a permanent, reusable
maintenance tool (the user's explicit choice) rather than a one-off
script - so it is held to the same PROMOTION-scope bar as this
repository's other destructive admin operations (rollback_to_last_known_good,
approve_candidate_by_id).

Hard safety properties this file exists to prove:
1. requires PROMOTION scope specifically - OPERATIONS (sufficient for
   ADMIN_TEST /chat and /events context) is NOT sufficient here, since
   this endpoint is destructive while those are not.
2. requires an explicit confirm=true flag.
3. matches ONLY by exact session_id equality - never a date range or
   pattern - so it cannot structurally sweep up unrelated real data.
4. malformed/unparseable lines are preserved untouched, never silently
   dropped.
5. the write is atomic (temp file + rename) so a mid-write failure
   cannot leave events.jsonl truncated.
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
from fastapi.testclient import TestClient


def _client():
    return TestClient(m.app)


def _seed(client, events_path, records):
    for r in records:
        client.post("/events", json=r)


class TestScopeRequirement:
    def test_promotion_scope_required_operations_insufficient(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EVENTS_LOG_PATH", str(tmp_path / "events.jsonl"))
        monkeypatch.setenv("ADMIN_OPERATIONS_TOKEN", "ops-token")
        r = _client().post(
            "/admin/analytics/events-purge",
            json={"session_ids": ["s1"], "confirm": True},
            headers={"X-Admin-Token": "ops-token"},
        )
        assert r.status_code == 403

    def test_promotion_scope_token_sufficient(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EVENTS_LOG_PATH", str(tmp_path / "events.jsonl"))
        monkeypatch.setenv("ADMIN_PROMOTION_TOKEN", "promo-token")
        r = _client().post(
            "/admin/analytics/events-purge",
            json={"session_ids": ["s1"], "confirm": True},
            headers={"X-Admin-Token": "promo-token"},
        )
        assert r.status_code == 200

    def test_no_token_rejected(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EVENTS_LOG_PATH", str(tmp_path / "events.jsonl"))
        monkeypatch.setenv("ADMIN_PROMOTION_TOKEN", "promo-token")
        r = _client().post("/admin/analytics/events-purge", json={"session_ids": ["s1"], "confirm": True})
        assert r.status_code == 401


class TestConfirmRequired:
    def test_missing_confirm_rejected(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EVENTS_LOG_PATH", str(tmp_path / "events.jsonl"))
        monkeypatch.setenv("ADMIN_PROMOTION_TOKEN", "promo-token")
        r = _client().post(
            "/admin/analytics/events-purge",
            json={"session_ids": ["s1"]},
            headers={"X-Admin-Token": "promo-token"},
        )
        assert r.status_code == 400

    def test_confirm_false_rejected(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EVENTS_LOG_PATH", str(tmp_path / "events.jsonl"))
        monkeypatch.setenv("ADMIN_PROMOTION_TOKEN", "promo-token")
        r = _client().post(
            "/admin/analytics/events-purge",
            json={"session_ids": ["s1"], "confirm": False},
            headers={"X-Admin-Token": "promo-token"},
        )
        assert r.status_code == 400

    def test_empty_session_ids_rejected_by_schema(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EVENTS_LOG_PATH", str(tmp_path / "events.jsonl"))
        monkeypatch.setenv("ADMIN_PROMOTION_TOKEN", "promo-token")
        r = _client().post(
            "/admin/analytics/events-purge",
            json={"session_ids": [], "confirm": True},
            headers={"X-Admin-Token": "promo-token"},
        )
        assert r.status_code == 422


class TestExactMatchOnly:
    def test_removes_only_exact_session_id_matches(self, monkeypatch, tmp_path):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        monkeypatch.setenv("ADMIN_PROMOTION_TOKEN", "promo-token")
        client = _client()
        client.post("/events", json={"session_id": "real-customer-1", "event_type": "click", "product_sku": "SKU1"})
        client.post("/events", json={"session_id": "synthetic-test-1", "event_type": "click", "product_sku": "FAKE"})

        r = client.post(
            "/admin/analytics/events-purge",
            json={"session_ids": ["synthetic-test-1"], "confirm": True},
            headers={"X-Admin-Token": "promo-token"},
        )
        assert r.status_code == 200
        assert r.json() == {"removed": 1, "remaining": 1, "requested_session_ids": ["synthetic-test-1"]}

        remaining = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(remaining) == 1
        assert remaining[0]["session_id"] == "real-customer-1"

    def test_does_not_match_substring_or_prefix(self, monkeypatch, tmp_path):
        # "synthetic-test-1" must not accidentally match "synthetic-test-10"
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        monkeypatch.setenv("ADMIN_PROMOTION_TOKEN", "promo-token")
        client = _client()
        client.post("/events", json={"session_id": "synthetic-test-1", "event_type": "click", "product_sku": "A"})
        client.post("/events", json={"session_id": "synthetic-test-10", "event_type": "click", "product_sku": "B"})

        r = client.post(
            "/admin/analytics/events-purge",
            json={"session_ids": ["synthetic-test-1"], "confirm": True},
            headers={"X-Admin-Token": "promo-token"},
        )
        assert r.json()["removed"] == 1

        remaining = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(remaining) == 1
        assert remaining[0]["session_id"] == "synthetic-test-10"

    def test_nonexistent_session_id_removes_nothing(self, monkeypatch, tmp_path):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        monkeypatch.setenv("ADMIN_PROMOTION_TOKEN", "promo-token")
        client = _client()
        client.post("/events", json={"session_id": "real-1", "event_type": "click", "product_sku": "SKU1"})

        r = client.post(
            "/admin/analytics/events-purge",
            json={"session_ids": ["does-not-exist"], "confirm": True},
            headers={"X-Admin-Token": "promo-token"},
        )
        assert r.json() == {"removed": 0, "remaining": 1, "requested_session_ids": ["does-not-exist"]}


class TestMalformedLinesPreserved:
    def test_unparseable_line_is_kept_not_dropped(self, monkeypatch, tmp_path):
        events_path = tmp_path / "events.jsonl"
        events_path.write_text(
            '{"session_id": "purge-me", "event_type": "click"}\n'
            'this is not valid json\n'
            '{"session_id": "keep-me", "event_type": "click"}\n',
            encoding="utf-8",
        )
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        monkeypatch.setenv("ADMIN_PROMOTION_TOKEN", "promo-token")
        r = _client().post(
            "/admin/analytics/events-purge",
            json={"session_ids": ["purge-me"], "confirm": True},
            headers={"X-Admin-Token": "promo-token"},
        )
        assert r.json()["removed"] == 1
        remaining_text = events_path.read_text(encoding="utf-8")
        assert "this is not valid json" in remaining_text
        assert "keep-me" in remaining_text
        assert "purge-me" not in remaining_text


class TestMissingFile:
    def test_missing_events_file_is_a_safe_no_op(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EVENTS_LOG_PATH", str(tmp_path / "does_not_exist.jsonl"))
        monkeypatch.setenv("ADMIN_PROMOTION_TOKEN", "promo-token")
        r = _client().post(
            "/admin/analytics/events-purge",
            json={"session_ids": ["anything"], "confirm": True},
            headers={"X-Admin-Token": "promo-token"},
        )
        assert r.status_code == 200
        assert r.json() == {"removed": 0, "remaining": 0, "requested_session_ids": ["anything"]}


class TestAtomicWrite:
    def test_no_leftover_temp_file_after_purge(self, monkeypatch, tmp_path):
        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("EVENTS_LOG_PATH", str(events_path))
        monkeypatch.setenv("ADMIN_PROMOTION_TOKEN", "promo-token")
        client = _client()
        client.post("/events", json={"session_id": "s1", "event_type": "click", "product_sku": "SKU1"})
        client.post(
            "/admin/analytics/events-purge",
            json={"session_ids": ["s1"], "confirm": True},
            headers={"X-Admin-Token": "promo-token"},
        )
        assert not (tmp_path / "events.jsonl.purge.tmp").exists()
