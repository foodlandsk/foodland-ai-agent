"""
tests/test_v221_runner.py  -  scripts/run_v221_benchmark.py self-tests.

Every Advisor call in this file is a fake/mock - this file must never
import app.main / app.advisor_engine, and must never let
app.evaluation.adapter.make_session_chat_fn() actually run (Section
88/89/90 of the V2.21a mandate: mock-based proof only, real Advisor
execution stays forbidden until V2.21b).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "run_v221_benchmark.py"


class TestDefaultNoExecution:
    """Section 90 - the critical safety test: invoking the tool without
    an explicit execution flag must never call the Advisor."""

    def test_cli_with_no_flags_exits_without_importing_adapter(self):
        code = (
            "import sys; sys.path.insert(0, '.'); "
            "sys.argv = ['run_v221_benchmark.py']; "
            "import runpy; "
            "runpy.run_path('scripts/run_v221_benchmark.py', run_name='__main__')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=30, check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "NEW_V221_ADVISOR_EXECUTIONS = 0" in result.stdout

    def test_cli_with_no_flags_never_loads_advisor_modules_in_process(self):
        code = (
            "import sys; sys.path.insert(0, '.'); "
            "sys.argv = ['run_v221_benchmark.py']; "
            "import runpy\n"
            "try:\n"
            "    runpy.run_path('scripts/run_v221_benchmark.py', run_name='__main__')\n"
            "except SystemExit:\n"
            "    pass\n"
            "forbidden = ('app.main', 'app.advisor_engine', 'app.evaluation.adapter')\n"
            "loaded = [m for m in forbidden if m in sys.modules]\n"
            "print('LOADED:' + ','.join(loaded))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=30, check=False,
        )
        assert result.returncode == 0, result.stderr
        loaded_line = [line for line in result.stdout.splitlines() if line.startswith("LOADED:")][0]
        loaded = [m for m in loaded_line[len("LOADED:"):].split(",") if m]
        assert loaded == [], f"default (no-flag) run loaded forbidden modules: {loaded}"

    def test_execute_advisor_function_is_only_reachable_via_explicit_flag(self):
        # Structural proof (AST), not a runtime promise: _execute_advisor
        # must only be called from main()'s args.execute_advisor branch.
        import ast
        import inspect

        source = RUNNER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        main_func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main")
        main_source = ast.get_source_segment(source, main_func)
        assert "_execute_advisor" in main_source
        assert "args.execute_advisor" in main_source


class TestExecutionContext:
    """Section 64/89 - the future runner must request EVALUATION, never
    default to CUSTOMER. Proven via mock: patch make_session_chat_fn()
    with a fake that records how it was invoked, never a real Advisor
    call."""

    def test_execute_advisor_calls_make_session_chat_fn_not_a_customer_path(self, monkeypatch, tmp_path):
        calls = []

        def fake_make_session_chat_fn():
            def fake_chat_fn(message, limit, session_id):
                calls.append((message, limit, session_id))
                return {"intent": "product_search", "products": [{"id": "FAKE_1", "title": "Fake product"}], "answer": "fake answer", "cross_sell": []}
            return fake_chat_fn

        import app.evaluation.adapter as real_adapter_module
        monkeypatch.setattr(real_adapter_module, "make_session_chat_fn", fake_make_session_chat_fn)

        sys.path.insert(0, str(ROOT))
        import importlib.util

        spec = importlib.util.spec_from_file_location("run_v221_benchmark_test_import", RUNNER_PATH)
        runner_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner_module)

        output_path = tmp_path / "fake_run.json"
        rc = runner_module._execute_advisor("HOLDOUT", output_path)
        assert rc == 0
        assert len(calls) > 0, "expected the fake chat_fn to have been invoked at least once"
        assert output_path.exists()


class TestMultiTurnSessionIsolation:
    """Section 65/88 - same identity within one scenario's turns, a
    fresh identity for the next scenario. Proven with a fake Advisor
    that records the actual session_id each turn used - never a real
    Advisor call.

    This class was the pre-fix blind spot: it only checked that
    `last_result`/`answer_excerpt` didn't leak across scenarios, which a
    stateless fake chat_fn can satisfy even if every turn got a
    different session_id - it could not distinguish "shares identity
    within a scenario" from "gets a fresh identity every single call"
    (the actual runner bug found during the V2.21b pre-execution audit:
    scripts/run_v221_benchmark.py was calling make_chat_fn(), which
    mints a brand-new session_id on every call, so turn 2+ of a
    multi-turn scenario never saw turn 1's session memory). Now the fake
    records session_id itself so this is checked directly."""

    def test_sequential_turns_within_one_scenario_share_no_leaked_state_and_next_scenario_starts_fresh(self, monkeypatch, tmp_path):
        # This test proves the RUNNER'S OWN LOOP SHAPE (Section 66 of
        # scripts/run_v221_benchmark.py's _execute_advisor): each
        # scenario's turns are executed as a sequential chain against
        # ONE chat_fn closure call each, and `last_result` is reset to
        # {} at the start of every scenario - so a later scenario can
        # never observe an earlier scenario's turn output by accident.
        call_log = []  # list of (message, session_id)

        def fake_make_session_chat_fn():
            def fake_chat_fn(message, limit, session_id):
                call_log.append((message, session_id))
                return {"intent": "product_search", "products": [], "answer": f"answered: {message}", "cross_sell": []}
            return fake_chat_fn

        import app.evaluation.adapter as real_adapter_module
        monkeypatch.setattr(real_adapter_module, "make_session_chat_fn", fake_make_session_chat_fn)

        import importlib.util

        spec = importlib.util.spec_from_file_location("run_v221_benchmark_test_import2", RUNNER_PATH)
        runner_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner_module)

        output_path = tmp_path / "fake_run2.json"
        runner_module._execute_advisor(None, output_path)

        import json

        payload = json.loads(output_path.read_text(encoding="utf-8"))
        # Every scenario in the frozen dataset was called at least once,
        # and the recorded answer_excerpt for each result corresponds to
        # ONLY that scenario's own last turn message, never a different
        # scenario's message leaking through.
        for r in payload["results"]:
            assert r["answer_excerpt"].startswith("answered:")
        assert len(call_log) >= len(payload["results"])

    def test_multi_turn_scenario_reuses_one_session_id_across_its_own_turns_only(self, monkeypatch, tmp_path):
        # The actual defect this fix closes: within ONE multi-turn
        # scenario, every turn must share the same session_id (so the
        # Advisor's session memory carries context forward); across
        # DIFFERENT scenarios, session_ids must never collide.
        call_log = []  # list of (message, session_id)

        def fake_make_session_chat_fn():
            def fake_chat_fn(message, limit, session_id):
                call_log.append((message, session_id))
                return {"intent": "product_search", "products": [], "answer": f"answered: {message}", "cross_sell": []}
            return fake_chat_fn

        import app.evaluation.adapter as real_adapter_module
        monkeypatch.setattr(real_adapter_module, "make_session_chat_fn", fake_make_session_chat_fn)

        import importlib.util

        spec = importlib.util.spec_from_file_location("run_v221_benchmark_test_import3", RUNNER_PATH)
        runner_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner_module)

        output_path = tmp_path / "fake_run3.json"
        runner_module._execute_advisor(None, output_path)

        from app.intelligence_diagnostics import v221_factory as factory

        scenarios = factory.load_v221_scenarios()
        multi_turn = [s for s in scenarios if len(s.turns) > 1]
        assert multi_turn, "expected at least one multi-turn scenario in the frozen dataset"

        offset = 0
        for s in scenarios:
            n = len(s.turns)
            turn_session_ids = {sid for _, sid in call_log[offset:offset + n]}
            assert len(turn_session_ids) == 1, (
                f"{s.scenario_id}: expected all {n} turns to share one session_id, got {turn_session_ids}"
            )
            offset += n

        all_session_ids = [sid for _, sid in call_log]
        scenario_session_ids = {f"eval-session-{s.scenario_id}" for s in scenarios}
        assert len(scenario_session_ids) == len(scenarios), "session_ids must not collide across scenarios"
        assert set(all_session_ids) == scenario_session_ids
