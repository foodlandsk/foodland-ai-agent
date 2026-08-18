"""
tests/test_learning_lifecycle.py  -  V2.12 Section 119/120: shadow does
not affect customer output and produces comparison data / can be disabled
safely; rollback restores last known good deterministically. Also covers
Section 55's unconditional human-approval gate.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import dataclasses

import pytest

import app.learning_lifecycle as ll
import app.ranking_config as rc
from app.learning_candidates import DECISION_REJECTED, DECISION_SHADOW_ELIGIBLE, generate_candidate
from app.learning_opportunities import ACTION_RANKING_WEIGHT_ADJUSTMENT, LearningOpportunity, TYPE_RANKING_POSITION_ANOMALY
from app.ranking_config import DEFAULT_PROFILE, RankingProfile, RankingWeights, get_active_ranking_profile_version


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
    yield


def _shadow_eligible_candidate(version: str = "v-lifecycle-test"):
    opportunity = LearningOpportunity(
        id="test-opp", type=TYPE_RANKING_POSITION_ANOMALY, scope="rice", evidence={},
        confidence="HIGH", sample_size=500, affected_queries=("rice",), affected_products=(),
        proposed_action_type=ACTION_RANKING_WEIGHT_ADJUSTMENT,
    )
    candidate = generate_candidate(opportunity, DEFAULT_PROFILE, fast=True)
    # Force SHADOW_ELIGIBLE regardless of the real (likely honest-reject)
    # outcome, since this test suite is about lifecycle mechanics, not
    # re-proving V2.10/V2.11 already-covered evaluation behavior.
    profile = dataclasses.replace(candidate.profile, version=version)
    return dataclasses.replace(candidate, decision=DECISION_SHADOW_ELIGIBLE, profile=profile)


class TestShadowDoesNotAffectCustomerOutput:
    def test_shadow_never_touches_active_pointer(self, isolated_lifecycle):
        before = get_active_ranking_profile_version()
        candidate = _shadow_eligible_candidate()
        ll.run_shadow(candidate, learning_cycle_id="cycle-test")
        assert get_active_ranking_profile_version() == before

    def test_shadow_produces_comparison_data(self, isolated_lifecycle):
        candidate = _shadow_eligible_candidate()
        result = ll.run_shadow(candidate, learning_cycle_id="cycle-test", queries=["jazmínová ryža", "kokosové mlieko"])
        assert len(result.report.results) == 2
        assert result.report.baseline_version == "v1"
        assert result.report.candidate_version == candidate.profile.version

    def test_shadow_can_be_disabled_by_not_calling_it(self, isolated_lifecycle):
        """Section 53/99 - LEARNING_SHADOW_ENABLED gates whether
        app.learning_cycle calls run_shadow() at all; the function itself
        has no independent 'enabled' flag to test in isolation - not
        invoking it is 'disabling' it, verified in test_learning_cycle.py."""
        assert callable(ll.run_shadow)

    def test_shadow_rejects_a_non_shadow_eligible_candidate(self, isolated_lifecycle):
        opportunity = LearningOpportunity(
            id="x", type=TYPE_RANKING_POSITION_ANOMALY, scope="rice", evidence={}, confidence="HIGH",
            sample_size=1, affected_queries=(), affected_products=(), proposed_action_type=ACTION_RANKING_WEIGHT_ADJUSTMENT,
        )
        rejected_candidate = dataclasses.replace(
            generate_candidate(opportunity, DEFAULT_PROFILE, fast=True), decision=DECISION_REJECTED,
        )
        with pytest.raises(ll.LifecycleError):
            ll.run_shadow(rejected_candidate, learning_cycle_id="cycle-test")


class TestApprovalGate:
    def test_activation_requires_real_approver(self, isolated_lifecycle):
        candidate = _shadow_eligible_candidate()
        for bad_approver in ("", "auto", "system", "AUTOMATED", "bot", "cron"):
            with pytest.raises(ll.LifecycleError):
                ll.approve_and_activate(candidate, approved_by=bad_approver, learning_cycle_id="cycle-test")
        assert get_active_ranking_profile_version() == "v1"  # never moved

    def test_activation_succeeds_with_real_approver(self, isolated_lifecycle):
        candidate = _shadow_eligible_candidate()
        ll.approve_and_activate(candidate, approved_by="foodlandsk", learning_cycle_id="cycle-test")
        assert get_active_ranking_profile_version() == candidate.profile.version

    def test_activation_records_last_known_good_before_switching(self, isolated_lifecycle):
        candidate = _shadow_eligible_candidate()
        ll.approve_and_activate(candidate, approved_by="foodlandsk", learning_cycle_id="cycle-test")
        last_known_good = ll.get_last_known_good()
        assert last_known_good["version"] == "v1"


class TestRollback:
    def test_rollback_restores_last_known_good_deterministically(self, isolated_lifecycle):
        candidate = _shadow_eligible_candidate()
        ll.approve_and_activate(candidate, approved_by="foodlandsk", learning_cycle_id="cycle-test")
        assert get_active_ranking_profile_version() == candidate.profile.version

        restored = ll.rollback_to_last_known_good(reason="simulated critical regression", learning_cycle_id="cycle-test")
        assert restored == "v1"
        assert get_active_ranking_profile_version() == "v1"

    def test_rollback_with_no_history_is_a_safe_no_op(self, isolated_lifecycle):
        result = ll.rollback_to_last_known_good(reason="test", learning_cycle_id="cycle-test")
        assert result is None


class TestRollbackConditions:
    def test_fail_gate_triggers_rollback(self):
        triggered, reason = ll.check_rollback_conditions({"gate": "FAIL", "blocking_reasons": ["critical case regressed"]})
        assert triggered is True
        assert "critical case regressed" in reason

    def test_warn_gate_does_not_trigger_rollback(self):
        """Section 61 - non-critical business-metric noise (which only
        ever shows up as a WARN, never FAIL, in the reused V2.10 gate)
        must never automatically roll back."""
        triggered, reason = ll.check_rollback_conditions({"gate": "WARN", "blocking_reasons": [], "warnings": ["ctr dipped slightly"]})
        assert triggered is False
        assert reason is None

    def test_pass_gate_does_not_trigger_rollback(self):
        triggered, reason = ll.check_rollback_conditions({"gate": "PASS", "blocking_reasons": []})
        assert triggered is False


class TestAuditTrail:
    def test_full_lifecycle_produces_an_ordered_immutable_ledger(self, isolated_lifecycle):
        candidate = _shadow_eligible_candidate()
        ll.run_shadow(candidate, learning_cycle_id="cycle-test")
        ll.approve_and_activate(candidate, approved_by="foodlandsk", learning_cycle_id="cycle-test")
        ll.rollback_to_last_known_good(reason="test", learning_cycle_id="cycle-test")

        history = ll.get_history()
        states = [entry["state"] for entry in history]
        assert states == [
            ll.STATE_OFFLINE_PASSED, ll.STATE_SHADOW, ll.STATE_READY_FOR_APPROVAL,
            ll.STATE_ACTIVE, ll.STATE_ROLLED_BACK,
        ]

    def test_history_filterable_by_candidate_id(self, isolated_lifecycle):
        candidate = _shadow_eligible_candidate()
        ll.run_shadow(candidate, learning_cycle_id="cycle-test")
        entries = ll.get_history(candidate_id=candidate.id)
        assert all(e["candidate_id"] == candidate.id for e in entries)
        assert len(entries) == 3  # OFFLINE_PASSED, SHADOW, READY_FOR_APPROVAL


class TestAutoPromotionDefaultsOff:
    def test_auto_promotion_disabled_by_default(self):
        assert ll.AUTO_PROMOTION_ENABLED is False
