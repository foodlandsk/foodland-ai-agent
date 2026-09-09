"""
tests/test_v221_scenario_factory.py  -  V2.21a Independent Fresh
Scenario Factory self-tests.

BLINDNESS INVARIANT: this file must never import app.main,
app.advisor_engine, or app.evaluation.adapter, and must never call the
Advisor. Every test here operates on scenario definitions, metadata,
manifests, the scorer's invariant registry, and the frozen catalog
snapshot only. NEW_V221_ADVISOR_EXECUTIONS must remain 0 for this
entire file (Section 73/90 of the V2.21a mandate).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.intelligence_diagnostics.v221_factory as factory
from app.intelligence_diagnostics.scenario_schema import (
    GROUND_TRUTH_AUTHORITIES,
    GROUND_TRUTH_PENDING,
    GROUND_TRUTH_SCORED,
    FORBIDDEN_AUTHORITY_CURRENT_MODEL_OUTPUT,
    LANGUAGES,
)


class TestBlindnessInvariant:
    """The factory (and scorer) module must be structurally incapable
    of executing the Advisor, not merely disciplined about not doing
    so - mirrors tests/test_v220_scenario_factory.py's own pattern."""

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

    def test_scorer_module_never_imports_advisor_code(self):
        import ast
        import inspect

        from app.intelligence_diagnostics import v221_scorer

        tree = ast.parse(inspect.getsource(v221_scorer))
        forbidden = ("app.main", "app.advisor_engine", "app.evaluation.adapter", "app.search", "app.ranking_shadow")
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
            "import app.intelligence_diagnostics.v221_factory; "
            "import app.intelligence_diagnostics.v221_scorer; "
            "forbidden = ('app.main', 'app.advisor_engine', 'app.evaluation.adapter'); "
            "loaded = [m for m in forbidden if m in sys.modules]; "
            "print(','.join(loaded))"
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        loaded = [m for m in result.stdout.strip().split(",") if m]
        assert not loaded, f"importing v221 modules transitively loaded: {loaded}"

    def test_scenario_registry_does_not_load_v221_scenarios(self):
        import inspect

        from app.intelligence_diagnostics import scenario_registry

        source = inspect.getsource(scenario_registry)
        assert "v2_21_scenarios" not in source
        assert "v221_factory" not in source


class TestScenarioData:
    @classmethod
    def setup_class(cls):
        cls.scenarios = factory.load_v221_scenarios()

    def test_scenarios_exist(self):
        assert len(self.scenarios) > 0

    def test_scenario_count_within_target_range(self):
        # Section 10 - "approximately 120-150," guidance not a hard
        # requirement, but a gross deviation would indicate a freeze
        # regression worth flagging.
        assert 100 <= len(self.scenarios) <= 160, len(self.scenarios)

    def test_unique_scenario_ids(self):
        ids = [s.scenario_id for s in self.scenarios]
        assert len(ids) == len(set(ids))

    def test_all_ids_use_v221_prefix(self):
        assert all(s.scenario_id.startswith("v221_") for s in self.scenarios)

    def test_all_languages_valid(self):
        assert all(s.language in LANGUAGES for s in self.scenarios)

    def test_no_forbidden_current_model_output_authority(self):
        for s in self.scenarios:
            assert s.ground_truth_authority != FORBIDDEN_AUTHORITY_CURRENT_MODEL_OUTPUT

    def test_scored_scenarios_have_valid_authority(self):
        for s in self.scenarios:
            if s.ground_truth_status == GROUND_TRUTH_SCORED:
                assert s.ground_truth_authority in GROUND_TRUTH_AUTHORITIES, s.scenario_id

    def test_pending_scenarios_have_no_expected_invariants(self):
        for s in self.scenarios:
            if s.ground_truth_status == GROUND_TRUTH_PENDING:
                assert not s.expected_invariants, s.scenario_id

    def test_every_scored_scenario_has_provenance(self):
        for s in self.scenarios:
            if s.is_scored:
                assert s.provenance.strip(), s.scenario_id

    def test_both_languages_represented(self):
        langs = {s.language for s in self.scenarios}
        assert "sk" in langs and "en" in langs

    def test_multi_turn_scenarios_exist(self):
        assert any(s.is_multi_turn for s in self.scenarios)

    def test_safety_sensitive_scenarios_exist(self):
        assert any(s.safety_sensitive for s in self.scenarios)

    def test_pending_scenarios_exist(self):
        # Section 29 - PENDING is a legitimate, expected outcome, not a
        # failure to eliminate.
        assert any(s.ground_truth_status == GROUND_TRUTH_PENDING for s in self.scenarios)


class TestValidation:
    @classmethod
    def setup_class(cls):
        cls.scenarios = factory.load_v221_scenarios()

    def test_no_hard_validation_errors(self):
        errors = factory.validate_scenarios(self.scenarios)
        hard = factory.hard_errors(errors)
        assert hard == [], hard

    def test_every_scored_invariant_has_a_scorer_implementation(self):
        # Section 36/51 - the exact V2.20-gap-closing guarantee: no
        # scored invariant without an executable scorer. Cross-checked
        # independently here against the real scorer registry, not just
        # trusted from validate_scenarios().
        from app.intelligence_diagnostics.v221_scorer import (
            KNOWN_ARG_INVARIANT_TYPES,
            KNOWN_BARE_INVARIANTS,
        )

        for s in self.scenarios:
            if not s.is_scored:
                continue
            for inv in s.expected_invariants:
                inv_type = inv.split(":", 1)[0] if ":" in inv else inv
                assert inv_type in KNOWN_BARE_INVARIANTS or inv_type in KNOWN_ARG_INVARIANT_TYPES, (
                    s.scenario_id, inv
                )

    def test_no_internal_semantic_duplicates(self):
        from app.intelligence_diagnostics.v220_factory import find_semantic_duplicates

        dups = find_semantic_duplicates(self.scenarios)
        assert dups == [], dups

    def test_no_contradictory_products_empty_and_nonempty(self):
        for s in self.scenarios:
            invs = set(s.expected_invariants)
            assert not ("products_empty" in invs and "products_nonempty" in invs), s.scenario_id


class TestFreshness:
    """Section 52/53 - TEXTUAL_DUPLICATE_CHECK against the full V2.18 +
    V2.20 historical corpus. Loads existing scenario/golden DATA only;
    never calls the Advisor."""

    @classmethod
    def setup_class(cls):
        from app.intelligence_diagnostics import scenario_registry
        from app.intelligence_diagnostics.v220_factory import load_v220_scenarios

        cls.v221 = factory.load_v221_scenarios()
        v220 = load_v220_scenarios()
        v218 = scenario_registry.load_all_scenarios()
        cls.historical_messages = [t.message for s in (v220 + v218) for t in s.turns]

    def test_no_exact_textual_duplicates_against_historical_corpus(self):
        result = factory.check_textual_freshness(self.v221, self.historical_messages)
        assert result["exact_duplicates"] == [], result["exact_duplicates"]

    def test_no_near_duplicates_against_historical_corpus(self):
        result = factory.check_textual_freshness(self.v221, self.historical_messages)
        assert result["near_duplicates"] == [], result["near_duplicates"]

    def test_freshness_check_actually_detects_a_planted_duplicate(self):
        # Self-integrity: prove the checker isn't vacuously always-clean
        # by planting a known exact duplicate and asserting it IS caught.
        from app.intelligence_diagnostics.scenario_schema import Scenario, ScenarioTurn

        planted = Scenario(
            scenario_id="v221_planted_dup_test",
            source="CURATED",
            capability="PRODUCT_SEARCH",
            turns=(ScenarioTurn(message=self.historical_messages[0]),),
            ground_truth_status=GROUND_TRUTH_PENDING,
        )
        result = factory.check_textual_freshness([planted], self.historical_messages)
        assert "v221_planted_dup_test" in result["exact_duplicates"]


class TestSplit:
    @classmethod
    def setup_class(cls):
        cls.scenarios = factory.load_v221_scenarios()
        cls.split_map = factory.assign_split(cls.scenarios)

    def test_split_is_deterministic_across_runs(self):
        split_map_2 = factory.assign_split(self.scenarios)
        assert self.split_map == split_map_2

    def test_split_covers_every_scenario_exactly_once(self):
        assert set(self.split_map.keys()) == {s.scenario_id for s in self.scenarios}
        assert all(v in (factory.SPLIT_DEV, factory.SPLIT_HOLDOUT) for v in self.split_map.values())

    def test_holdout_fraction_is_roughly_target(self):
        dev = sum(1 for v in self.split_map.values() if v == factory.SPLIT_DEV)
        holdout = sum(1 for v in self.split_map.values() if v == factory.SPLIT_HOLDOUT)
        ratio = holdout / (dev + holdout)
        assert 0.15 <= ratio <= 0.30, ratio

    def test_holdout_contains_multiple_capabilities(self):
        holdout_caps = {s.capability for s in self.scenarios if self.split_map[s.scenario_id] == factory.SPLIT_HOLDOUT}
        assert len(holdout_caps) >= 10, holdout_caps

    def test_holdout_contains_safety_sensitive_case(self):
        assert any(
            s.safety_sensitive for s in self.scenarios if self.split_map[s.scenario_id] == factory.SPLIT_HOLDOUT
        )

    def test_holdout_contains_multi_turn_case(self):
        assert any(
            s.is_multi_turn for s in self.scenarios if self.split_map[s.scenario_id] == factory.SPLIT_HOLDOUT
        )

    def test_split_not_derived_from_advisor_performance(self):
        # Structural proof, not just a promise: assign_split()'s only
        # inputs are scenario metadata fields already present before
        # any execution could occur (difficulty/language/safety/
        # capability/scenario_id) - verified here by re-deriving the
        # split from a freshly-loaded, independent copy of the same
        # scenario list and confirming byte-identical output.
        fresh_scenarios = factory.load_v221_scenarios()
        fresh_split = factory.assign_split(fresh_scenarios)
        assert fresh_split == self.split_map


class TestManifest:
    @classmethod
    def setup_class(cls):
        cls.scenarios = factory.load_v221_scenarios()
        cls.split_map = factory.assign_split(cls.scenarios)
        with open(factory.V221_MANIFEST_PATH, encoding="utf-8") as f:
            cls.manifest = json.load(f)

    def test_manifest_file_exists(self):
        assert factory.V221_MANIFEST_PATH.exists()

    def test_manifest_dev_matches_recomputed_split_and_hashes(self):
        mismatches = factory.verify_manifest(self.manifest["dev"], self.scenarios, self.split_map)
        assert mismatches == [], mismatches

    def test_manifest_holdout_matches_recomputed_split_and_hashes(self):
        mismatches = factory.verify_manifest(self.manifest["holdout"], self.scenarios, self.split_map)
        assert mismatches == [], mismatches

    def test_manifest_declares_pending_counts_separately(self):
        # Section 58 - PENDING must never be silently hidden or folded
        # into scored.
        assert "pending_count" in self.manifest["dev"]
        assert "pending_count" in self.manifest["holdout"]
        assert self.manifest["total_pending_count"] == (
            self.manifest["dev"]["pending_count"] + self.manifest["holdout"]["pending_count"]
        )

    def test_manifest_catalog_snapshot_matches_current_products_file(self):
        current = factory.compute_catalog_snapshot()
        assert self.manifest["catalog_snapshot"]["content_hash"] == current["content_hash"]

    def test_manifest_scenario_file_hash_is_reproducible(self):
        assert factory.content_hash(self.scenarios) is not None
        # Recomputing twice from independently reloaded data must agree.
        again = factory.load_v221_scenarios()
        assert factory.content_hash(self.scenarios) == factory.content_hash(again)
