"""
tests/test_storage_paths_v2_15b.py  -  V2.15b: durable storage path
normalization.

V2.15a found that app.search_quality.SEARCH_QUALITY_LOG_PATH and the
EVENTS_LOG_PATH readers in app.behavioral/app.fbt/app.learning_events
each independently hardcoded their own tempdir default instead of going
through app.storage_paths.resolve_path() (the single FOODLAND_DATA_DIR
knob app/main.py's own log_event() writer, question_analytics writer,
etc. already use). They agreed with the real writer only because
EVENTS_LOG_PATH happens to already be explicitly set in production - a
future cleanup that removed that redundant override in favor of
FOODLAND_DATA_DIR alone would have silently desynced them with no error
anywhere.

These tests prove the fix: with FOODLAND_DATA_DIR set and no per-variable
override, every one of these paths resolves under the same base
directory - and an explicit per-variable override still wins, exactly as
storage_paths.resolve_path() has always documented.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _reload_with_env(monkeypatch, module_name, **env):
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    module = importlib.import_module(module_name)
    return importlib.reload(module)


class TestFoodlandDataDirConsolidation:
    def test_events_path_agrees_across_writer_and_readers(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        monkeypatch.setenv("FOODLAND_DATA_DIR", str(data_dir))
        monkeypatch.delenv("EVENTS_LOG_PATH", raising=False)

        behavioral = _reload_with_env(monkeypatch, "app.behavioral", FOODLAND_DATA_DIR=str(data_dir))
        fbt = _reload_with_env(monkeypatch, "app.fbt", FOODLAND_DATA_DIR=str(data_dir))
        learning_events = _reload_with_env(monkeypatch, "app.learning_events", FOODLAND_DATA_DIR=str(data_dir))

        expected = str(data_dir / "events.jsonl")
        assert behavioral.EVENTS_PATH == expected
        assert fbt.EVENTS_PATH == expected
        assert learning_events.EVENTS_PATH == expected

    def test_explicit_events_log_path_still_wins(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        explicit = tmp_path / "somewhere-else" / "events.jsonl"
        monkeypatch.setenv("FOODLAND_DATA_DIR", str(data_dir))
        monkeypatch.setenv("EVENTS_LOG_PATH", str(explicit))

        behavioral = _reload_with_env(monkeypatch, "app.behavioral", FOODLAND_DATA_DIR=str(data_dir), EVENTS_LOG_PATH=str(explicit))
        fbt = _reload_with_env(monkeypatch, "app.fbt", FOODLAND_DATA_DIR=str(data_dir), EVENTS_LOG_PATH=str(explicit))

        assert behavioral.EVENTS_PATH == str(explicit)
        assert fbt.EVENTS_PATH == str(explicit)

    def test_search_quality_log_path_uses_foodland_data_dir(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        monkeypatch.delenv("SEARCH_QUALITY_LOG_PATH", raising=False)
        sq = _reload_with_env(monkeypatch, "app.search_quality", FOODLAND_DATA_DIR=str(data_dir))
        assert sq.SEARCH_QUALITY_LOG_PATH == str(data_dir / "search_quality.jsonl")

    def test_product_embeddings_path_uses_foodland_data_dir(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        monkeypatch.delenv("PRODUCT_EMBEDDINGS_PATH", raising=False)
        embeddings = _reload_with_env(monkeypatch, "app.embeddings", FOODLAND_DATA_DIR=str(data_dir))
        assert embeddings.EMBEDDINGS_PATH == str(data_dir / "product_embeddings.json")

    def test_no_foodland_data_dir_falls_back_to_legacy_tempdir_default(self, monkeypatch):
        # Byte-for-byte unchanged default for any environment (local dev,
        # CI) that has never set FOODLAND_DATA_DIR - same tempdir path
        # every one of these modules hardcoded independently before this
        # sprint.
        import tempfile
        monkeypatch.delenv("FOODLAND_DATA_DIR", raising=False)
        monkeypatch.delenv("EVENTS_LOG_PATH", raising=False)
        fbt = _reload_with_env(monkeypatch, "app.fbt")
        expected = str(Path(tempfile.gettempdir()) / "foodland-ai-agent" / "events.jsonl")
        assert fbt.EVENTS_PATH == expected
