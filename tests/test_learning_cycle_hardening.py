"""
tests/test_learning_cycle_hardening.py  -  V2.12.1 Part E: the periodic
in-process scheduler (app.main.learning_cycle_loop) must survive a cycle
that raises, and a failed cycle's error status must actually land on
disk. app.learning_cycle.run_learning_cycle()'s own internal-exception ->
"status": "error" behavior is already covered by
tests/test_learning_cycle.py::TestNeverRaisesOnInternalError - this file
adds the two pieces V2.12.1 specifically hardens: (1) the asyncio loop
that calls it periodically in the background never dies from a bad
iteration (Section 100's "off the customer request path" guarantee is
worthless if the loop itself stops scheduling future runs), and (2) an
error-status report is persisted to REPORTS_DIR just like a completed one.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.learning_cycle as lc
import app.main as m
import app.ranking_config as rc
from app.ranking_config import DEFAULT_PROFILE


def _isolate(tmp_path, monkeypatch, *, events=None):
    monkeypatch.setattr(rc, "CONFIG_DIR", tmp_path / "ranking_profiles")
    monkeypatch.setattr(rc, "ACTIVE_POINTER_PATH", tmp_path / "ranking_profiles" / "active.json")
    rc.clear_active_ranking_profile_cache()
    rc.save_ranking_profile(DEFAULT_PROFILE)
    rc.set_active_ranking_profile_version("v1")

    reports_dir = tmp_path / "reports"
    monkeypatch.setattr(lc, "REPORTS_DIR", reports_dir)

    events_path = tmp_path / "events.jsonl"
    if events:
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    return events_path


class TestErrorStatusReportIsPersisted:
    def test_error_status_report_lands_on_disk_same_as_a_completed_one(self, tmp_path, monkeypatch):
        ts = int(time.time()) - 60
        events = [{"ts": ts, "session_id": "s1", "event_type": "impression", "product_skus": ["FL_A", "FL_B"], "query": "ryza"}]
        events_path = _isolate(tmp_path, monkeypatch, events=events)
        monkeypatch.setattr(lc, "compute_query_product_signals", lambda events: (_ for _ in ()).throw(RuntimeError("boom")))

        report = lc.run_learning_cycle(known_product_ids=frozenset({"FL_A", "FL_B"}), events_path=str(events_path))
        assert report["status"] == "error"

        persisted = json.loads((lc.REPORTS_DIR / "latest.json").read_text(encoding="utf-8"))
        assert persisted["status"] == "error"
        assert "boom" in persisted["error"]
        assert persisted["learning_cycle_id"] == report["learning_cycle_id"]


class TestSchedulerLoopSurvivesAFailedCycle:
    def test_loop_keeps_scheduling_future_runs_after_a_cycle_raises(self, monkeypatch):
        """Section 100 - a learning-cycle failure must never affect
        customer search, and per V2.12.1 Part E that includes never
        silently stopping the periodic scheduler itself. Simulates two
        sleep/run iterations: the first _run_learning_cycle call raises,
        the second succeeds - the loop must reach the second call, proving
        the except-and-continue in app.main.learning_cycle_loop actually
        goes back to the top of `while True` rather than exiting."""
        run_calls = []
        release = asyncio.Event()

        async def fake_sleep(seconds):
            return None

        monkeypatch.setattr(m.asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(m, "products", [])

        async def run_test():
            loop = asyncio.get_running_loop()

            def fake_run_learning_cycle(*, known_product_ids):
                run_calls.append(known_product_ids)
                if len(run_calls) == 1:
                    raise RuntimeError("simulated cycle failure")
                # fake_run_learning_cycle executes inside asyncio.to_thread's
                # worker thread, not the event loop thread - Event.set()
                # must be scheduled back onto the loop, not called directly.
                loop.call_soon_threadsafe(release.set)
                return {"status": "completed"}

            monkeypatch.setattr(m, "_run_learning_cycle", fake_run_learning_cycle)

            task = asyncio.create_task(m.learning_cycle_loop(1))
            try:
                await asyncio.wait_for(release.wait(), timeout=5.0)
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            return task

        task = asyncio.run(run_test())
        # The loop must have survived the first call's RuntimeError and
        # gone on to attempt (and this time complete) a second cycle -
        # if the except block didn't loop back, run_calls would be [1].
        assert len(run_calls) >= 2
        # Cancellation is the only way this coroutine ever "exits" in
        # production too (process shutdown) - no unhandled exception
        # should have escaped the task itself.
        assert task.cancelled() or task.exception() is None
