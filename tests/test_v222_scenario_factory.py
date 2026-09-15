"""
tests/test_v222_scenario_factory.py  -  V2.22a Fresh Independent
Evaluation Factory self-tests.

BLINDNESS INVARIANT: this file must never import app.main,
app.advisor_engine, or app.evaluation.adapter, and must never call the
Advisor. Every test here operates on scenario definitions, metadata,
manifests, the scorer's invariant registry, and the frozen catalog/FAQ/
Recipes/Products_AI snapshots only. NEW_V222_ADVISOR_EXECUTIONS must
remain 0 for this entire file (V2.22a mandate Section 38/54).

Mirrors tests/test_v221_scenario_factory.py's structure and discipline
exactly - same blindness-invariant test shapes, extended with the
V2.22-only governance checks (source_class/independence_level,
LOW-independence-forbidden-in-HOLDOUT, advisor_execution_count == 0 in
the frozen manifest, no CURRENT_MODEL_OUTPUT authority anywhere).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.intelligence_diagnostics.v222_factory as factory
from app.intelligence_diagnostics.scenario_schema import (
    FORBIDDEN_AUTHORITY_CURRENT_MODEL_OUTPUT,
    GROUND_TRUTH_AUTHORITIES,
    GROUND_TRUTH_PENDING,
    GROUND_TRUTH_SCORED,
    LANGUAGES,
)


class TestBlindnessInvariant:
    """The factory (and scorer) module must be structurally incapable
    of executing the Advisor, not merely disciplined about not doing
    so - mirrors tests/test_v221_scenario_factory.py's own pattern."""

    def test_factory_module_never_imports_advisor_code(self):
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(factory))
        forbidden = ("app.main", "app.advisor_engine", "app.evaluation.adapter", "app.ranking_shadow")
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        for name in forbidden:
            assert not any(mod == name or mod.startswith(name + ".") for mod in imported), (name, imported)

    def test_importing_factory_does_not_load_advisor_modules(self):
        # Fresh subprocess, not an in-process sys.modules check - other
        # test files in a full suite run may have already imported
        # app.main, which would make an in-process check order-dependent.
        import subprocess

        code = (
            "import sys; sys.path.insert(0, '.'); "
            "import app.intelligence_diagnostics.v222_factory; "
            "forbidden = ('app.main', 'app.advisor_engine', 'app.evaluation.adapter'); "
            "loaded = [m for m in forbidden if m in sys.modules]; "
            "print(','.join(loaded))"
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        loaded = [m for m in result.stdout.strip().split(",") if m]
        assert not loaded, f"importing v222_factory transitively loaded: {loaded}"

    def test_scenario_registry_does_not_load_v222_scenarios(self):
        import inspect

        from app.intelligence_diagnostics import scenario_registry

        source = inspect.getsource(scenario_registry)
        assert "v2_22_scenarios" not in source
        assert "v222_factory" not in source
        assert "load_v222_scenarios" not in source


class TestV222ScenarioFile:
    """Structural validation of eval/golden/v2_22_scenarios.json and
    its manifest - the frozen artifacts V2.22a produces."""

    def test_scenarios_file_exists(self):
        assert factory.V222_SCENARIOS_PATH.exists()

    def test_manifest_file_exists(self):
        assert factory.V222_MANIFEST_PATH.exists()

    def test_all_scenarios_load_without_error(self):
        scenarios = factory.load_v222_scenarios()
        assert len(scenarios) > 0

    def test_no_duplicate_scenario_ids(self):
        scenarios = factory.load_v222_scenarios()
        ids = [s.scenario_id for s in scenarios]
        assert len(ids) == len(set(ids))

    def test_all_ids_have_v222_prefix(self):
        scenarios = factory.load_v222_scenarios()
        for s in scenarios:
            assert s.scenario_id.startswith("v222_"), s.scenario_id

    def test_all_capabilities_are_valid(self):
        scenarios = factory.load_v222_scenarios()
        for s in scenarios:
            assert s.capability in factory.V222_CAPABILITIES, (s.scenario_id, s.capability)

    def test_all_languages_are_supported(self):
        scenarios = factory.load_v222_scenarios()
        for s in scenarios:
            assert s.language in LANGUAGES, (s.scenario_id, s.language)

    def test_scored_scenarios_have_valid_authority(self):
        scenarios = factory.load_v222_scenarios()
        for s in scenarios:
            if s.ground_truth_status == GROUND_TRUTH_SCORED:
                assert s.ground_truth_authority in GROUND_TRUTH_AUTHORITIES, s.scenario_id

    def test_no_current_model_output_authority_anywhere(self):
        # Structural guard duplicated at the file level, not just the
        # dataclass constructor - a raw dict edit that bypassed
        # Scenario.__post_init__ would still be caught here.
        raw = factory.load_v222_raw()
        for entry in raw:
            assert entry.get("ground_truth_authority") != FORBIDDEN_AUTHORITY_CURRENT_MODEL_OUTPUT, entry["scenario_id"]

    def test_hard_validation_passes(self):
        scenarios = factory.load_v222_scenarios()
        raw = factory.load_v222_raw()
        raw_by_id = {r["scenario_id"]: r for r in raw}
        errors = factory.validate_scenarios(scenarios, raw_by_id=raw_by_id)
        hard = factory.hard_errors(errors)
        assert not hard, hard

    def test_split_membership_recorded_for_every_scenario(self):
        raw = factory.load_v222_raw()
        for entry in raw:
            assert entry.get("split") in factory.SPLITS, entry["scenario_id"]

    def test_source_class_and_independence_level_valid(self):
        raw = factory.load_v222_raw()
        for entry in raw:
            assert entry.get("source_class") in factory.SOURCE_CLASSES, entry["scenario_id"]
            assert entry.get("independence_level") in factory.INDEPENDENCE_LEVELS, entry["scenario_id"]

    def test_no_low_independence_scenario_in_holdout(self):
        raw = factory.load_v222_raw()
        for entry in raw:
            if entry.get("split") == factory.SPLIT_HOLDOUT:
                assert entry.get("independence_level") != factory.INDEPENDENCE_LOW, entry["scenario_id"]

    def test_no_revealed_regression_scenario_in_holdout(self):
        raw = factory.load_v222_raw()
        for entry in raw:
            if entry.get("split") == factory.SPLIT_HOLDOUT:
                assert entry.get("source_class") != factory.SOURCE_CLASS_REVEALED_REGRESSION, entry["scenario_id"]


class TestV222Manifest:
    def _manifest(self):
        return json.loads(factory.V222_MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_advisor_execution_count_is_zero(self):
        manifest = self._manifest()
        assert manifest["advisor_execution_count"] == 0

    def test_v221_holdout_not_reused_as_blind(self):
        manifest = self._manifest()
        assert manifest["v221_revealed_holdout_reused_as_blind"] is False

    def test_manifest_self_verifies_against_current_scenarios(self):
        scenarios = factory.load_v222_scenarios()
        raw = factory.load_v222_raw()
        split_map = {r["scenario_id"]: r["split"] for r in raw}
        manifest = self._manifest()
        mismatches_dev = factory.verify_manifest(manifest["dev"], scenarios, split_map)
        mismatches_holdout = factory.verify_manifest(manifest["holdout"], scenarios, split_map)
        assert not mismatches_dev, mismatches_dev
        assert not mismatches_holdout, mismatches_holdout

    def test_total_counts_match_scenario_file(self):
        scenarios = factory.load_v222_scenarios()
        manifest = self._manifest()
        assert manifest["total_scenario_count"] == len(scenarios)
        assert manifest["total_scored_count"] == sum(1 for s in scenarios if s.is_scored)
        assert manifest["total_pending_count"] == sum(1 for s in scenarios if s.ground_truth_status == GROUND_TRUTH_PENDING)

    def test_holdout_fraction_within_target_range(self):
        manifest = self._manifest()
        total = manifest["total_scenario_count"]
        holdout = manifest["holdout"]["scenario_count"]
        fraction = holdout / total
        assert 0.15 <= fraction <= 0.30, fraction


class TestDuplicationAgainstHistoricalCorpus:
    """Re-runs the V2.22a freeze-time duplication audit as a living
    test - if a future edit to v2_22_scenarios.json introduces a new
    exact duplicate of prior-corpus text, this fails immediately."""

    def _historical_messages(self) -> list[str]:
        def extract(obj, out):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in ("message", "query") and isinstance(v, str):
                        out.append(v)
                    else:
                        extract(v, out)
            elif isinstance(obj, list):
                for item in obj:
                    extract(item, out)

        messages: list[str] = []
        for pattern_dir in (ROOT / "eval" / "golden", ROOT / "eval" / "conversations"):
            for path in pattern_dir.glob("*.json"):
                if path.name in ("v2_22_scenarios.json", "v2_22_manifest.json"):
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                extract(data, messages)
        return messages

    def test_no_exact_duplicates_against_v218_v220_v221_corpus(self):
        scenarios = factory.load_v222_scenarios()
        historical = self._historical_messages()
        result = factory.check_textual_freshness(scenarios, historical)
        assert not result["exact_duplicates"], result["exact_duplicates"]
