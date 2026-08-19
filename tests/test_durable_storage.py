"""
tests/test_durable_storage.py  -  V2.12.1 Part A: the shared atomic-write
primitive (app/durable_storage.py), the FOODLAND_DATA_DIR path resolver
(app/storage_paths.py), and the degraded-state fallback chain
(app.ranking_config.get_active_ranking_profile(): active.json ->
last_known_good.json -> DEFAULT_PROFILE) that replaces the old
two-step (active.json -> DEFAULT_PROFILE) fallback.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import pytest

import app.durable_storage as ds
import app.learning_lifecycle as ll
import app.ranking_config as rc
import app.storage_paths as sp
from app.ranking_config import DEFAULT_PROFILE


class TestAtomicWriteText:
    def test_writes_content_readable_back(self, tmp_path):
        target = tmp_path / "sub" / "file.txt"
        ds.atomic_write_text(target, "hello world")
        assert target.read_text(encoding="utf-8") == "hello world"

    def test_creates_parent_directories(self, tmp_path):
        target = tmp_path / "a" / "b" / "c" / "file.txt"
        ds.atomic_write_text(target, "x")
        assert target.exists()

    def test_overwrites_existing_content_completely(self, tmp_path):
        target = tmp_path / "file.txt"
        ds.atomic_write_text(target, "first version, quite long content here")
        ds.atomic_write_text(target, "v2")
        assert target.read_text(encoding="utf-8") == "v2"

    def test_no_leftover_temp_files_after_a_successful_write(self, tmp_path):
        target = tmp_path / "file.txt"
        ds.atomic_write_text(target, "content")
        leftovers = [p for p in tmp_path.iterdir() if p.name != "file.txt"]
        assert leftovers == []

    def test_temp_file_cleaned_up_when_replace_fails(self, tmp_path, monkeypatch):
        """Simulated write failure (Section [Part A durability tests]) -
        if os.replace() itself fails partway, the temp file must not be
        left behind forever, and the ORIGINAL target must be untouched
        (the atomicity guarantee: never a torn/partial write visible to
        readers)."""
        target = tmp_path / "file.txt"
        ds.atomic_write_text(target, "original content")

        def failing_replace(src, dst):
            raise OSError("simulated disk failure during replace")

        monkeypatch.setattr(ds.os, "replace", failing_replace)
        with pytest.raises(OSError):
            ds.atomic_write_text(target, "new content that must never land")

        # Original content survives untouched - no torn write.
        assert target.read_text(encoding="utf-8") == "original content"
        leftovers = [p for p in tmp_path.iterdir() if p.name != "file.txt"]
        assert leftovers == []  # temp file cleaned up despite the failure


class TestAtomicWriteJson:
    def test_roundtrips_a_dict(self, tmp_path):
        target = tmp_path / "data.json"
        ds.atomic_write_json(target, {"a": 1, "b": [1, 2, 3]})
        assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1, "b": [1, 2, 3]}


class TestStoragePathsResolution:
    def test_data_dir_defaults_to_tempdir_when_unconfigured(self, monkeypatch):
        monkeypatch.delenv("FOODLAND_DATA_DIR", raising=False)
        assert sp.is_data_dir_configured() is False
        assert "foodland-ai-agent" in str(sp.data_dir())

    def test_data_dir_uses_explicit_env_var_when_set(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FOODLAND_DATA_DIR", str(tmp_path / "custom"))
        assert sp.is_data_dir_configured() is True
        assert sp.data_dir() == tmp_path / "custom"

    def test_resolve_path_prefers_explicit_override(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FOODLAND_DATA_DIR", raising=False)
        monkeypatch.setenv("SOME_LOG_PATH", str(tmp_path / "explicit.jsonl"))
        assert sp.resolve_path("SOME_LOG_PATH", "default.jsonl") == tmp_path / "explicit.jsonl"

    def test_resolve_path_falls_back_to_data_dir(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SOME_LOG_PATH", raising=False)
        monkeypatch.setenv("FOODLAND_DATA_DIR", str(tmp_path))
        assert sp.resolve_path("SOME_LOG_PATH", "default.jsonl") == tmp_path / "default.jsonl"

    def test_resolve_dir_keeps_legacy_default_when_data_dir_unconfigured(self, monkeypatch):
        monkeypatch.delenv("FOODLAND_DATA_DIR", raising=False)
        monkeypatch.delenv("SOME_DIR", raising=False)
        assert sp.resolve_dir("SOME_DIR", "sub", legacy_default="config/legacy") == Path("config/legacy")

    def test_resolve_dir_follows_data_dir_when_configured(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SOME_DIR", raising=False)
        monkeypatch.setenv("FOODLAND_DATA_DIR", str(tmp_path))
        assert sp.resolve_dir("SOME_DIR", "sub", legacy_default="config/legacy") == tmp_path / "sub"

    def test_resolve_dir_explicit_override_wins_over_data_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FOODLAND_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("SOME_DIR", str(tmp_path / "explicit-dir"))
        assert sp.resolve_dir("SOME_DIR", "sub", legacy_default="config/legacy") == tmp_path / "explicit-dir"


@pytest.fixture()
def isolated_ranking(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "CONFIG_DIR", tmp_path / "ranking_profiles")
    monkeypatch.setattr(rc, "ACTIVE_POINTER_PATH", tmp_path / "ranking_profiles" / "active.json")
    monkeypatch.setattr(ll, "HISTORY_DIR", tmp_path / "learning_history")
    monkeypatch.setattr(ll, "LEDGER_PATH", tmp_path / "learning_history" / "ledger.jsonl")
    monkeypatch.setattr(ll, "LAST_KNOWN_GOOD_PATH", tmp_path / "learning_history" / "last_known_good.json")
    monkeypatch.setattr(ll, "CANDIDATE_STORE_PATH", tmp_path / "learning_history" / "candidates.jsonl")
    rc.clear_active_ranking_profile_cache()
    rc.save_ranking_profile(DEFAULT_PROFILE)
    rc.set_active_ranking_profile_version("v1")
    yield tmp_path


class TestActiveProfileFallbackChain:
    def test_healthy_state_is_not_degraded(self, isolated_ranking):
        rc.clear_active_ranking_profile_cache()
        profile = rc.get_active_ranking_profile()
        assert profile.version == "v1"
        assert rc.is_active_profile_degraded() is False

    def test_corrupted_active_pointer_falls_back_to_default_when_no_last_known_good(self, isolated_ranking):
        rc.ACTIVE_POINTER_PATH.write_text("{not valid json", encoding="utf-8")
        rc.clear_active_ranking_profile_cache()
        profile = rc.get_active_ranking_profile()
        assert profile.version == DEFAULT_PROFILE.version
        assert rc.is_active_profile_degraded() is True

    def test_corrupted_active_pointer_falls_back_to_last_known_good_when_present(self, isolated_ranking):
        # Simulate a prior activation having recorded a last_known_good.
        v2 = rc.RankingProfile(version="v2-lkg", name="lkg", description="")
        rc.save_ranking_profile(v2)
        ll.LAST_KNOWN_GOOD_PATH.parent.mkdir(parents=True, exist_ok=True)
        ll.LAST_KNOWN_GOOD_PATH.write_text(
            json.dumps({"version": "v2-lkg", "recorded_at": time.time(), "evaluation_summary": {}}),
            encoding="utf-8",
        )

        rc.ACTIVE_POINTER_PATH.write_text("{not valid json", encoding="utf-8")
        rc.clear_active_ranking_profile_cache()
        profile = rc.get_active_ranking_profile()
        assert profile.version == "v2-lkg"
        assert rc.is_active_profile_degraded() is True

    def test_missing_version_file_referenced_by_active_pointer_falls_back(self, isolated_ranking):
        # active.json points at a version whose file was never written / got deleted.
        rc.set_active_ranking_profile_version("v1")
        (rc.CONFIG_DIR / "v1.json").unlink()
        rc.clear_active_ranking_profile_cache()
        profile = rc.get_active_ranking_profile()
        assert profile.version == DEFAULT_PROFILE.version
        assert rc.is_active_profile_degraded() is True

    def test_degraded_flag_clears_once_active_pointer_is_healthy_again(self, isolated_ranking):
        rc.ACTIVE_POINTER_PATH.write_text("{not valid json", encoding="utf-8")
        rc.clear_active_ranking_profile_cache()
        rc.get_active_ranking_profile()
        assert rc.is_active_profile_degraded() is True

        rc.set_active_ranking_profile_version("v1")  # repairs the pointer
        rc.clear_active_ranking_profile_cache()
        profile = rc.get_active_ranking_profile()
        assert profile.version == "v1"
        assert rc.is_active_profile_degraded() is False
