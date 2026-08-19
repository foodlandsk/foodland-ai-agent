"""
tests/test_admin_auth.py  -  V2.12.1 Part B: three-tier scoped admin
authorization matrix (READ < OPERATIONS < PROMOTION). See
app/admin_auth.py's module docstring for why this replaced the old flat
require_admin_token() check, and docs/admin-security.md for the full
endpoint-by-scope mapping.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from app.admin_auth import (
    SCOPE_OPERATIONS,
    SCOPE_PROMOTION,
    SCOPE_READ,
    any_admin_token_configured,
    require_admin_scope,
    resolve_token_scope,
)

_ALL_ADMIN_ENV_VARS = (
    "ADMIN_PROMOTION_TOKEN",
    "ADMIN_OPERATIONS_TOKEN",
    "ADMIN_RELOAD_TOKEN",
    "ADMIN_READ_TOKEN",
    "ADMIN_ANALYTICS_TOKEN",
)


@pytest.fixture(autouse=True)
def _clean_admin_env(monkeypatch):
    """Every test starts with zero admin tokens configured, regardless of
    what the developer's local .env happens to set - the pre-existing
    convention in tests/test_main_learning_endpoints.py."""
    for var in _ALL_ADMIN_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield


class TestNoTokenConfiguredHidesTheEndpoint:
    def test_any_admin_token_configured_is_false(self):
        assert any_admin_token_configured() is False

    def test_require_admin_scope_raises_404_regardless_of_presented_token(self):
        with pytest.raises(Exception) as exc_info:
            require_admin_scope("anything-at-all", SCOPE_READ)
        assert getattr(exc_info.value, "status_code", None) == 404

    def test_require_admin_scope_raises_404_even_with_no_presented_token(self):
        with pytest.raises(Exception) as exc_info:
            require_admin_scope(None, SCOPE_READ)
        assert getattr(exc_info.value, "status_code", None) == 404


class TestReadScopeToken:
    def test_read_token_grants_read(self, monkeypatch):
        monkeypatch.setenv("ADMIN_READ_TOKEN", "read-secret")
        assert require_admin_scope("read-secret", SCOPE_READ) == SCOPE_READ

    def test_read_token_denied_operations_with_403(self, monkeypatch):
        monkeypatch.setenv("ADMIN_READ_TOKEN", "read-secret")
        with pytest.raises(Exception) as exc_info:
            require_admin_scope("read-secret", SCOPE_OPERATIONS)
        assert getattr(exc_info.value, "status_code", None) == 403

    def test_read_token_denied_promotion_with_403(self, monkeypatch):
        monkeypatch.setenv("ADMIN_READ_TOKEN", "read-secret")
        with pytest.raises(Exception) as exc_info:
            require_admin_scope("read-secret", SCOPE_PROMOTION)
        assert getattr(exc_info.value, "status_code", None) == 403


class TestOperationsScopeToken:
    def test_operations_token_grants_operations_and_read(self, monkeypatch):
        monkeypatch.setenv("ADMIN_OPERATIONS_TOKEN", "ops-secret")
        assert require_admin_scope("ops-secret", SCOPE_READ) == SCOPE_OPERATIONS
        assert require_admin_scope("ops-secret", SCOPE_OPERATIONS) == SCOPE_OPERATIONS

    def test_operations_token_denied_promotion_with_403(self, monkeypatch):
        monkeypatch.setenv("ADMIN_OPERATIONS_TOKEN", "ops-secret")
        with pytest.raises(Exception) as exc_info:
            require_admin_scope("ops-secret", SCOPE_PROMOTION)
        assert getattr(exc_info.value, "status_code", None) == 403


class TestPromotionScopeToken:
    def test_promotion_token_grants_every_scope(self, monkeypatch):
        monkeypatch.setenv("ADMIN_PROMOTION_TOKEN", "promo-secret")
        assert require_admin_scope("promo-secret", SCOPE_READ) == SCOPE_PROMOTION
        assert require_admin_scope("promo-secret", SCOPE_OPERATIONS) == SCOPE_PROMOTION
        assert require_admin_scope("promo-secret", SCOPE_PROMOTION) == SCOPE_PROMOTION


class TestLegacyTokenCompatibility:
    """Section 83 - an existing deployment that has only ever set
    ADMIN_ANALYTICS_TOKEN / ADMIN_RELOAD_TOKEN keeps working unchanged,
    and neither legacy token ever reaches PROMOTION."""

    def test_legacy_analytics_token_behaves_as_read(self, monkeypatch):
        monkeypatch.setenv("ADMIN_ANALYTICS_TOKEN", "legacy-analytics")
        assert require_admin_scope("legacy-analytics", SCOPE_READ) == SCOPE_READ
        with pytest.raises(Exception) as exc_info:
            require_admin_scope("legacy-analytics", SCOPE_OPERATIONS)
        assert getattr(exc_info.value, "status_code", None) == 403

    def test_legacy_reload_token_behaves_as_operations(self, monkeypatch):
        monkeypatch.setenv("ADMIN_RELOAD_TOKEN", "legacy-reload")
        assert require_admin_scope("legacy-reload", SCOPE_READ) == SCOPE_OPERATIONS
        assert require_admin_scope("legacy-reload", SCOPE_OPERATIONS) == SCOPE_OPERATIONS

    def test_no_legacy_token_ever_grants_promotion(self, monkeypatch):
        monkeypatch.setenv("ADMIN_ANALYTICS_TOKEN", "legacy-analytics")
        monkeypatch.setenv("ADMIN_RELOAD_TOKEN", "legacy-reload")
        for token in ("legacy-analytics", "legacy-reload"):
            with pytest.raises(Exception) as exc_info:
                require_admin_scope(token, SCOPE_PROMOTION)
            assert getattr(exc_info.value, "status_code", None) == 403

    def test_both_legacy_tokens_coexist_with_distinct_scopes(self, monkeypatch):
        monkeypatch.setenv("ADMIN_ANALYTICS_TOKEN", "legacy-analytics")
        monkeypatch.setenv("ADMIN_RELOAD_TOKEN", "legacy-reload")
        assert resolve_token_scope("legacy-analytics") == SCOPE_READ
        assert resolve_token_scope("legacy-reload") == SCOPE_OPERATIONS


class TestInvalidOrMissingToken:
    def test_wrong_token_value_raises_401(self, monkeypatch):
        monkeypatch.setenv("ADMIN_READ_TOKEN", "read-secret")
        with pytest.raises(Exception) as exc_info:
            require_admin_scope("totally-wrong", SCOPE_READ)
        assert getattr(exc_info.value, "status_code", None) == 401

    def test_missing_token_raises_401_when_tokens_are_configured(self, monkeypatch):
        monkeypatch.setenv("ADMIN_READ_TOKEN", "read-secret")
        with pytest.raises(Exception) as exc_info:
            require_admin_scope(None, SCOPE_READ)
        assert getattr(exc_info.value, "status_code", None) == 401

    def test_empty_string_token_raises_401_when_tokens_are_configured(self, monkeypatch):
        monkeypatch.setenv("ADMIN_READ_TOKEN", "read-secret")
        with pytest.raises(Exception) as exc_info:
            require_admin_scope("", SCOPE_READ)
        assert getattr(exc_info.value, "status_code", None) in (401, 404)


class TestHighestConfiguredScopeWins:
    """If a token value happens to be reused across multiple env vars, it
    must resolve to the HIGHEST scope it matches, never a lower one."""

    def test_same_value_configured_as_both_read_and_promotion(self, monkeypatch):
        monkeypatch.setenv("ADMIN_READ_TOKEN", "shared-value")
        monkeypatch.setenv("ADMIN_PROMOTION_TOKEN", "shared-value")
        assert resolve_token_scope("shared-value") == SCOPE_PROMOTION
