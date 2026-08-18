"""
tests/test_main_learning_endpoints.py  -  V2.12 admin endpoints: same
require_admin_token() auth pattern as the pre-existing /admin/analytics/*
and /admin/feed/* endpoints, and /health exposes only aggregate learning
status (Section 98 - never raw events).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import pytest

import app.main as m

# Section 130/pre-existing convention (see tests/test_core.py's
# test_admin_behavioral_rankings_requires_token) - reference m.HTTPException,
# never a fresh `from fastapi import HTTPException`. tests/test_core.py
# installs a lightweight stub `fastapi` module into sys.modules the first
# time it runs in a session (so app.main's own logic can be unit-tested
# without a real FastAPI/pydantic install); once installed, that stub is
# what every later-imported module's `HTTPException` actually is - the
# stub's __init__ deliberately doesn't set .status_code, so tests only
# assert that SOME exception is raised, exactly like every other existing
# admin-endpoint test in this codebase already does.


@pytest.fixture()
def admin_token(monkeypatch):
    monkeypatch.setenv("ADMIN_ANALYTICS_TOKEN", "test-admin-token")
    yield "test-admin-token"


class TestAdminAuthGating:
    def test_status_endpoint_requires_token(self, admin_token):
        with pytest.raises(m.HTTPException):
            m.admin_learning_status(x_admin_token=None)

    def test_status_endpoint_rejects_wrong_token(self, admin_token):
        with pytest.raises(m.HTTPException):
            m.admin_learning_status(x_admin_token="wrong-token")

    def test_status_endpoint_blocked_when_admin_disabled(self, monkeypatch):
        monkeypatch.delenv("ADMIN_ANALYTICS_TOKEN", raising=False)
        monkeypatch.delenv("ADMIN_RELOAD_TOKEN", raising=False)
        with pytest.raises(m.HTTPException):
            m.admin_learning_status(x_admin_token="anything")

    def test_history_endpoint_requires_token(self, admin_token):
        with pytest.raises(m.HTTPException):
            m.admin_learning_history(x_admin_token=None)

    def test_candidates_endpoint_requires_token(self, admin_token):
        with pytest.raises(m.HTTPException):
            m.admin_learning_candidates(x_admin_token=None)

    def test_run_cycle_endpoint_requires_token(self, admin_token):
        with pytest.raises(m.HTTPException):
            m.admin_learning_run_cycle(x_admin_token=None)


class TestAdminEndpointsReturnExpectedShape:
    def test_status_returns_expected_keys(self, admin_token):
        result = m.admin_learning_status(x_admin_token=admin_token)
        for key in (
            "learning_engine_enabled", "auto_promotion_enabled", "learning_cycle_minutes",
            "active_ranking_config", "last_known_good", "last_learning_cycle_status", "shadow_candidate_count",
        ):
            assert key in result

    def test_history_returns_entries_list(self, admin_token):
        result = m.admin_learning_history(x_admin_token=admin_token)
        assert "entries" in result
        assert isinstance(result["entries"], list)

    def test_candidates_handles_missing_report_gracefully(self, admin_token, tmp_path, monkeypatch):
        monkeypatch.setattr(m, "_LEARNING_REPORTS_DIR", tmp_path / "does_not_exist")
        result = m.admin_learning_candidates(x_admin_token=admin_token)
        assert result["candidates"] == []


class TestHealthExposesOnlyAggregateLearningStatus:
    def test_health_learning_block_has_no_raw_event_fields(self):
        result = m.health()
        learning = result["learning"]
        assert set(learning.keys()) == {
            "learning_engine_enabled", "active_ranking_config",
            "last_learning_cycle_status", "shadow_candidate_count",
        }
        # Section 98 - none of these look like raw event/session data.
        assert "events" not in learning
        assert "session_id" not in learning


class TestDisablingLearningNeverDisablesRanking:
    def test_ranking_profile_reachable_regardless_of_learning_flags(self, monkeypatch):
        """Section 99 - disabling V2.12 must not disable V2.11."""
        monkeypatch.setattr(m, "_LEARNING_ENGINE_ENABLED", False)
        from app.ranking_config import get_active_ranking_profile
        profile = get_active_ranking_profile()
        assert profile is not None
