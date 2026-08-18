"""
tests/test_learning_cycle.py  -  V2.12: end-to-end orchestrator (collect
-> aggregate -> detect -> generate -> shadow -> report), the
insufficient-data honesty path (Section 137), the disabled-engine path
(Section 99/100), and report persistence.
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

import app.learning_cycle as lc
import app.ranking_config as rc
from app.ranking_config import DEFAULT_PROFILE

KNOWN_PRODUCT_IDS = frozenset({"FL_A", "FL_B"})


def _write_events(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


def _isolate(tmp_path, monkeypatch, *, events: list[dict] | None = None):
    monkeypatch.setattr(rc, "CONFIG_DIR", tmp_path / "ranking_profiles")
    monkeypatch.setattr(rc, "ACTIVE_POINTER_PATH", tmp_path / "ranking_profiles" / "active.json")
    rc.clear_active_ranking_profile_cache()
    rc.save_ranking_profile(DEFAULT_PROFILE)
    rc.set_active_ranking_profile_version("v1")

    reports_dir = tmp_path / "reports"
    monkeypatch.setattr(lc, "REPORTS_DIR", reports_dir)

    events_path = tmp_path / "events.jsonl"
    if events:
        _write_events(events_path, events)
    return events_path


class TestInsufficientDataIsHonest:
    def test_no_events_at_all_reports_insufficient_data(self, tmp_path, monkeypatch):
        events_path = _isolate(tmp_path, monkeypatch, events=None)
        report = lc.run_learning_cycle(known_product_ids=KNOWN_PRODUCT_IDS, events_path=str(events_path))
        assert report["status"] == "insufficient_data"
        assert "Section 137" in report["reason"]

    def test_never_fabricates_opportunities_or_candidates_when_insufficient(self, tmp_path, monkeypatch):
        events_path = _isolate(tmp_path, monkeypatch, events=None)
        report = lc.run_learning_cycle(known_product_ids=KNOWN_PRODUCT_IDS, events_path=str(events_path))
        assert "opportunities" not in report
        assert "candidates" not in report


class TestDisabledEngine:
    def test_engine_disabled_short_circuits(self, tmp_path, monkeypatch):
        monkeypatch.setattr(lc, "LEARNING_ENGINE_ENABLED", False)
        events_path = _isolate(tmp_path, monkeypatch, events=None)
        report = lc.run_learning_cycle(known_product_ids=KNOWN_PRODUCT_IDS, events_path=str(events_path))
        assert report["status"] == "disabled"


class TestFullCycleWithSyntheticEvents:
    def _synthetic_ranking_anomaly_events(self) -> list[dict]:
        # Real epoch-relative timestamps (Section 1 - load_learning_events()
        # filters by a real days-since-now window, unlike the lower-level
        # normalize_events() tests elsewhere that bypass that window).
        base_ts = int(time.time()) - 3600
        events = []
        for i in range(1, 251):
            ts = base_ts + i
            order = ["FL_A", "FL_B"] if i % 2 == 0 else ["FL_B", "FL_A"]
            events.append({"ts": ts, "session_id": f"s{i}", "event_type": "impression", "product_skus": order, "query": "ryza"})
            if i % 3 != 0:
                pos = order.index("FL_B")
                events.append({"ts": ts, "session_id": f"s{i}", "event_type": "click", "product_sku": "FL_B", "position": pos, "query": "ryza"})
        return events

    def test_full_cycle_completes_and_produces_a_report(self, tmp_path, monkeypatch):
        events_path = _isolate(tmp_path, monkeypatch, events=self._synthetic_ranking_anomaly_events())
        report = lc.run_learning_cycle(
            known_product_ids=KNOWN_PRODUCT_IDS, events_path=str(events_path),
            fast_evaluation=True, run_shadow_stage=False,
        )
        assert report["status"] == "completed"
        assert report["event_stats"]["valid"] > 0
        assert len(report["opportunities"]) >= 1
        assert "candidate_summary" in report

    def test_report_persisted_to_disk(self, tmp_path, monkeypatch):
        events_path = _isolate(tmp_path, monkeypatch, events=self._synthetic_ranking_anomaly_events())
        lc.run_learning_cycle(known_product_ids=KNOWN_PRODUCT_IDS, events_path=str(events_path), run_shadow_stage=False)
        assert (lc.REPORTS_DIR / "latest.json").exists()
        assert (lc.REPORTS_DIR / "latest.md").exists()
        persisted = json.loads((lc.REPORTS_DIR / "latest.json").read_text(encoding="utf-8"))
        assert persisted["status"] == "completed"

    def test_candidate_generation_can_be_disabled_independently(self, tmp_path, monkeypatch):
        events_path = _isolate(tmp_path, monkeypatch, events=self._synthetic_ranking_anomaly_events())
        monkeypatch.setattr(lc, "LEARNING_CANDIDATE_GENERATION_ENABLED", False)
        report = lc.run_learning_cycle(known_product_ids=KNOWN_PRODUCT_IDS, events_path=str(events_path), run_shadow_stage=False)
        assert report["status"] == "completed"
        assert report["candidates"] == []
        assert len(report["opportunities"]) >= 1  # detection still ran

    def test_shadow_stage_can_be_disabled(self, tmp_path, monkeypatch):
        events_path = _isolate(tmp_path, monkeypatch, events=self._synthetic_ranking_anomaly_events())
        report = lc.run_learning_cycle(
            known_product_ids=KNOWN_PRODUCT_IDS, events_path=str(events_path),
            fast_evaluation=True, run_shadow_stage=False,
        )
        assert report["shadow_summaries"] == []

    def test_cycle_never_activates_anything(self, tmp_path, monkeypatch):
        events_path = _isolate(tmp_path, monkeypatch, events=self._synthetic_ranking_anomaly_events())
        before = rc.get_active_ranking_profile_version()
        lc.run_learning_cycle(known_product_ids=KNOWN_PRODUCT_IDS, events_path=str(events_path), run_shadow_stage=False)
        assert rc.get_active_ranking_profile_version() == before


class TestLearningCycleIdIsStableAndTraceable:
    def test_cycle_id_format(self):
        cycle_id = lc.new_learning_cycle_id()
        assert cycle_id.startswith("learning_cycle_")
        assert len(cycle_id) > len("learning_cycle_")

    def test_cycle_ids_are_unique(self):
        ids = {lc.new_learning_cycle_id() for _ in range(20)}
        assert len(ids) == 20


class TestNeverRaisesOnInternalError:
    def test_internal_exception_becomes_error_status_not_a_crash(self, tmp_path, monkeypatch):
        events_path = _isolate(tmp_path, monkeypatch, events=self._synthetic_ranking_anomaly_events_helper())
        monkeypatch.setattr(lc, "compute_query_product_signals", lambda events: (_ for _ in ()).throw(RuntimeError("boom")))
        report = lc.run_learning_cycle(known_product_ids=KNOWN_PRODUCT_IDS, events_path=str(events_path))
        assert report["status"] == "error"
        assert "boom" in report["error"]

    @staticmethod
    def _synthetic_ranking_anomaly_events_helper():
        ts = int(time.time()) - 60
        return [{"ts": ts, "session_id": "s1", "event_type": "impression", "product_skus": ["FL_A", "FL_B"], "query": "ryza"}]
