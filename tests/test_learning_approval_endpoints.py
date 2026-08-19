"""
tests/test_learning_approval_endpoints.py  -  V2.12.1 Part C: durable,
ID-keyed candidate approval and rollback, exercised at both the
app.learning_lifecycle level (approve_candidate_by_id) and the real HTTP
endpoints (POST /admin/learning/candidates/{id}/approve, POST
/admin/learning/rollback). Before this sprint neither endpoint existed -
approve_and_activate()/rollback_to_last_known_good() were only reachable
from Python/tests (see docs/admin-security.md).
"""
from __future__ import annotations

import dataclasses
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import pytest

import app.learning_lifecycle as ll
import app.main as m
import app.ranking_config as rc
from app.learning_candidates import DECISION_SHADOW_ELIGIBLE, generate_candidate
from app.learning_opportunities import ACTION_RANKING_WEIGHT_ADJUSTMENT, LearningOpportunity, TYPE_RANKING_POSITION_ANOMALY
from app.ranking_config import DEFAULT_PROFILE, get_active_ranking_profile_version


@pytest.fixture()
def isolated_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "CONFIG_DIR", tmp_path / "ranking_profiles")
    monkeypatch.setattr(rc, "ACTIVE_POINTER_PATH", tmp_path / "ranking_profiles" / "active.json")
    rc.clear_active_ranking_profile_cache()
    rc.save_ranking_profile(DEFAULT_PROFILE)
    rc.set_active_ranking_profile_version("v1")

    monkeypatch.setattr(ll, "HISTORY_DIR", tmp_path / "learning_history")
    monkeypatch.setattr(ll, "LEDGER_PATH", tmp_path / "learning_history" / "ledger.jsonl")
    monkeypatch.setattr(ll, "LAST_KNOWN_GOOD_PATH", tmp_path / "learning_history" / "last_known_good.json")
    monkeypatch.setattr(ll, "CANDIDATE_STORE_PATH", tmp_path / "learning_history" / "candidates.jsonl")
    yield


def _shadow_eligible_candidate(version: str = "v-approval-test"):
    opportunity = LearningOpportunity(
        id="approval-test-opp", type=TYPE_RANKING_POSITION_ANOMALY, scope="rice", evidence={},
        confidence="HIGH", sample_size=500, affected_queries=("rice",), affected_products=(),
        proposed_action_type=ACTION_RANKING_WEIGHT_ADJUSTMENT,
    )
    candidate = generate_candidate(opportunity, DEFAULT_PROFILE, fast=True)
    profile = dataclasses.replace(candidate.profile, version=version)
    return dataclasses.replace(candidate, decision=DECISION_SHADOW_ELIGIBLE, profile=profile)


class TestApproveCandidateByIdRequiresAPersistedSnapshot:
    def test_unknown_candidate_id_raises(self, isolated_lifecycle):
        with pytest.raises(ll.LifecycleError):
            ll.approve_candidate_by_id("candidate:does-not-exist", approved_by="foodlandsk")

    def test_run_shadow_persists_a_snapshot_approve_can_find(self, isolated_lifecycle):
        candidate = _shadow_eligible_candidate()
        assert ll.get_persisted_candidate(candidate.id) is None
        ll.run_shadow(candidate, learning_cycle_id="cycle-test")
        snapshot = ll.get_persisted_candidate(candidate.id)
        assert snapshot is not None
        assert snapshot["profile"]["version"] == candidate.profile.version
        assert snapshot["config_version_at_generation"] == "v1"


class TestApproveCandidateByIdActivates:
    def test_approve_by_id_activates_the_profile(self, isolated_lifecycle):
        candidate = _shadow_eligible_candidate()
        ll.run_shadow(candidate, learning_cycle_id="cycle-test")

        result = ll.approve_candidate_by_id(candidate.id, approved_by="foodlandsk")
        assert result["status"] == "activated"
        assert result["profile_version"] == candidate.profile.version
        assert get_active_ranking_profile_version() == candidate.profile.version

    def test_second_approval_call_is_idempotent(self, isolated_lifecycle):
        candidate = _shadow_eligible_candidate()
        ll.run_shadow(candidate, learning_cycle_id="cycle-test")
        ll.approve_candidate_by_id(candidate.id, approved_by="foodlandsk")

        before_history_len = len(ll.get_history())
        result = ll.approve_candidate_by_id(candidate.id, approved_by="foodlandsk")
        assert result["status"] == "already_active"
        # No new ledger entry/last_known_good mutation on the duplicate call.
        assert len(ll.get_history()) == before_history_len


class TestApproveCandidateByIdStaleProtection:
    def test_mismatched_expected_config_version_raises(self, isolated_lifecycle):
        candidate = _shadow_eligible_candidate()
        ll.run_shadow(candidate, learning_cycle_id="cycle-test")

        with pytest.raises(ll.LifecycleError):
            ll.approve_candidate_by_id(
                candidate.id, approved_by="foodlandsk",
                expected_current_config_version="not-the-real-active-version",
            )
        # Nothing moved.
        assert get_active_ranking_profile_version() == "v1"

    def test_matching_expected_config_version_succeeds(self, isolated_lifecycle):
        candidate = _shadow_eligible_candidate()
        ll.run_shadow(candidate, learning_cycle_id="cycle-test")

        result = ll.approve_candidate_by_id(
            candidate.id, approved_by="foodlandsk", expected_current_config_version="v1",
        )
        assert result["status"] == "activated"


class TestRollbackStaleProtectionAndIdempotency:
    def test_mismatched_expected_config_version_raises(self, isolated_lifecycle):
        candidate = _shadow_eligible_candidate()
        ll.approve_and_activate(candidate, approved_by="foodlandsk", learning_cycle_id="cycle-test")

        with pytest.raises(ll.LifecycleError):
            ll.rollback_to_last_known_good(
                reason="test", learning_cycle_id="cycle-test",
                expected_current_config_version="not-the-real-active-version",
            )
        assert get_active_ranking_profile_version() == candidate.profile.version

    def test_repeated_rollback_is_idempotent(self, isolated_lifecycle):
        candidate = _shadow_eligible_candidate()
        ll.approve_and_activate(candidate, approved_by="foodlandsk", learning_cycle_id="cycle-test")

        first = ll.rollback_to_last_known_good(reason="test", learning_cycle_id="cycle-test")
        assert first == "v1"
        second = ll.rollback_to_last_known_good(reason="test again", learning_cycle_id="cycle-test")
        assert second == "v1"
        assert get_active_ranking_profile_version() == "v1"


class TestApprovalHTTPEndpointRequiresPromotionScope:
    def test_read_token_is_refused_with_403(self, isolated_lifecycle, monkeypatch):
        monkeypatch.setenv("ADMIN_READ_TOKEN", "read-secret")
        with pytest.raises(m.HTTPException):
            m.admin_approve_candidate(
                "candidate:whatever",
                m.ApproveCandidateRequest(approved_by="foodlandsk"),
                x_admin_token="read-secret",
            )

    def test_operations_token_is_refused_with_403(self, isolated_lifecycle, monkeypatch):
        monkeypatch.setenv("ADMIN_OPERATIONS_TOKEN", "ops-secret")
        with pytest.raises(m.HTTPException):
            m.admin_approve_candidate(
                "candidate:whatever",
                m.ApproveCandidateRequest(approved_by="foodlandsk"),
                x_admin_token="ops-secret",
            )

    def test_rollback_endpoint_requires_promotion_scope_too(self, isolated_lifecycle, monkeypatch):
        monkeypatch.setenv("ADMIN_READ_TOKEN", "read-secret")
        with pytest.raises(m.HTTPException):
            m.admin_rollback_learning(
                m.RollbackRequest(reason="test", triggered_by="foodlandsk"),
                x_admin_token="read-secret",
            )


class TestApprovalHTTPEndpointEndToEnd:
    def test_full_http_approve_then_rollback_cycle(self, isolated_lifecycle, monkeypatch):
        monkeypatch.setenv("ADMIN_PROMOTION_TOKEN", "promo-secret")
        candidate = _shadow_eligible_candidate()
        ll.run_shadow(candidate, learning_cycle_id="cycle-test")

        approve_result = m.admin_approve_candidate(
            candidate.id,
            m.ApproveCandidateRequest(approved_by="foodlandsk", expected_current_config_version="v1"),
            x_admin_token="promo-secret",
        )
        assert approve_result["status"] == "activated"
        assert get_active_ranking_profile_version() == candidate.profile.version

        rollback_result = m.admin_rollback_learning(
            m.RollbackRequest(reason="undo for test", triggered_by="foodlandsk"),
            x_admin_token="promo-secret",
        )
        assert rollback_result["status"] == "rolled_back"
        assert rollback_result["profile_version"] == "v1"
        assert get_active_ranking_profile_version() == "v1"

    def test_unknown_candidate_id_via_http_returns_409(self, isolated_lifecycle, monkeypatch):
        monkeypatch.setenv("ADMIN_PROMOTION_TOKEN", "promo-secret")
        with pytest.raises(m.HTTPException) as exc_info:
            m.admin_approve_candidate(
                "candidate:does-not-exist",
                m.ApproveCandidateRequest(approved_by="foodlandsk"),
                x_admin_token="promo-secret",
            )
        assert getattr(exc_info.value, "status_code", None) == 409

    def test_stale_expected_version_via_http_returns_409(self, isolated_lifecycle, monkeypatch):
        monkeypatch.setenv("ADMIN_PROMOTION_TOKEN", "promo-secret")
        candidate = _shadow_eligible_candidate()
        ll.run_shadow(candidate, learning_cycle_id="cycle-test")

        with pytest.raises(m.HTTPException) as exc_info:
            m.admin_approve_candidate(
                candidate.id,
                m.ApproveCandidateRequest(approved_by="foodlandsk", expected_current_config_version="stale-version"),
                x_admin_token="promo-secret",
            )
        assert getattr(exc_info.value, "status_code", None) == 409

    def test_rollback_with_no_history_via_http_is_a_no_op(self, isolated_lifecycle, monkeypatch):
        monkeypatch.setenv("ADMIN_PROMOTION_TOKEN", "promo-secret")
        result = m.admin_rollback_learning(
            m.RollbackRequest(reason="nothing to roll back", triggered_by="foodlandsk"),
            x_admin_token="promo-secret",
        )
        assert result["status"] == "no_op"
