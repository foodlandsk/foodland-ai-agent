"""
tests/test_v220_scenario_factory.py  -  V2.20a Independent Scenario
Factory & Holdout Architecture self-tests.

BLINDNESS INVARIANT: this file must never import app.main,
app.advisor_engine, or app.evaluation.adapter, and must never call the
Advisor. Every test here operates on scenario definitions, metadata,
manifests, and the frozen catalog snapshot only (docs/
v2-20-scenario-factory.md Section 4/114). NEW_V220_ADVISOR_EXECUTIONS
must remain 0 for this entire file.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.intelligence_diagnostics.v220_factory as factory
from app.intelligence_diagnostics.scenario_schema import (
    CAPABILITIES,
    DIFFICULTIES,
    FORBIDDEN_AUTHORITY_CURRENT_MODEL_OUTPUT,
    GROUND_TRUTH_AUTHORITIES,
    GROUND_TRUTH_PENDING,
    GROUND_TRUTH_SCORED,
    LANGUAGES,
    SPLIT_DEV,
    SPLIT_HOLDOUT,
)


class TestBlindnessInvariant:
    """Section 4/104/114 - the factory module must be structurally
    incapable of executing the Advisor, not merely disciplined about
    not doing so."""

    def test_factory_module_never_imports_advisor_code(self):
        # AST-based, not a raw substring check on the source text - the
        # module's own docstring/comments intentionally NAME these
        # modules in prose (explaining what must never be imported),
        # which a naive text search would misflag. Only actual
        # import/import-from statements matter here.
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
        # Must run in a FRESH subprocess, not inspect sys.modules in the
        # shared pytest process - by the time this test runs in a full
        # suite, other unrelated test files have already imported
        # app.main, which would make an in-process sys.modules check
        # pass or fail depending on test order rather than on what
        # v220_factory.py itself actually imports.
        import subprocess

        code = (
            "import sys; sys.path.insert(0, '.'); "
            "import app.intelligence_diagnostics.v220_factory; "
            "forbidden = ('app.main', 'app.advisor_engine', 'app.evaluation.adapter'); "
            "loaded = [m for m in forbidden if m in sys.modules]; "
            "print(','.join(loaded))"
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        loaded = [m for m in result.stdout.strip().split(",") if m]
        assert not loaded, f"importing v220_factory.py transitively loaded: {loaded}"

    def test_scenario_registry_does_not_load_v220_scenarios(self):
        """The structural guarantee behind NEW_V220_ADVISOR_EXECUTIONS=0:
        scripts/run_intelligence_benchmark.py and the V2.18 310-case
        regression core both go through
        scenario_registry.load_all_scenarios(), which must never read
        eval/golden/v2_20_scenarios.json."""
        import inspect

        from app.intelligence_diagnostics import scenario_registry

        source = inspect.getsource(scenario_registry)
        assert "v2_20_scenarios" not in source
        assert "v220_factory" not in source


class TestScenarioData:
    @classmethod
    def setup_class(cls):
        cls.scenarios = factory.load_v220_scenarios()

    def test_scenarios_exist(self):
        assert len(self.scenarios) > 0

    def test_unique_scenario_ids(self):
        ids = [s.scenario_id for s in self.scenarios]
        assert len(ids) == len(set(ids))

    def test_all_capabilities_valid(self):
        for s in self.scenarios:
            assert s.capability in CAPABILITIES, s.scenario_id
            for cap in s.secondary_capabilities:
                assert cap in CAPABILITIES, f"{s.scenario_id}: {cap}"

    def test_all_difficulties_valid_or_none(self):
        for s in self.scenarios:
            assert s.difficulty is None or s.difficulty in DIFFICULTIES, s.scenario_id

    def test_all_languages_valid(self):
        for s in self.scenarios:
            assert s.language in LANGUAGES, s.scenario_id

    def test_no_forbidden_current_model_output_authority(self):
        # Scenario.__post_init__ already makes this impossible to
        # construct, but assert it explicitly at the data level too -
        # a future loader change must not silently bypass the guard.
        for s in self.scenarios:
            assert s.ground_truth_authority != FORBIDDEN_AUTHORITY_CURRENT_MODEL_OUTPUT, s.scenario_id

    def test_scored_scenarios_have_valid_authority(self):
        for s in self.scenarios:
            if s.ground_truth_status == GROUND_TRUTH_SCORED:
                assert s.ground_truth_authority in GROUND_TRUTH_AUTHORITIES, s.scenario_id

    def test_pending_scenarios_have_no_scored_invariants_required(self):
        # PENDING scenarios may carry no expected_invariants at all -
        # they are not scored (Section 33/34).
        for s in self.scenarios:
            if s.ground_truth_status == GROUND_TRUTH_PENDING:
                assert s.ground_truth_reason.strip(), f"{s.scenario_id}: PENDING scenario must explain why"

    def test_every_scenario_has_provenance_or_is_pending(self):
        for s in self.scenarios:
            if s.ground_truth_status == GROUND_TRUTH_SCORED:
                assert s.provenance.strip(), s.scenario_id

    def test_no_hard_validation_errors(self):
        errors = factory.validate_scenarios(self.scenarios)
        hard = factory.hard_errors(errors)
        assert hard == [], hard

    def test_no_semantic_duplicates(self):
        dups = factory.find_semantic_duplicates(self.scenarios)
        assert dups == [], dups

    def test_majority_are_not_variants_of_known_old_bugs(self):
        # Section 67 - independence from C1-C6/"co "/known FAQ/allergen
        # bugs. A crude but effective structural proxy: the majority of
        # scenario_ids should not reference old regbug/rt00xx ids or the
        # literal V2.18 bug-class names.
        stale_markers = ("regbug", "rt00", "co_boundary")
        stale = [s.scenario_id for s in self.scenarios if any(m in s.scenario_id.lower() for m in stale_markers)]
        assert len(stale) < len(self.scenarios) * 0.1


class TestSplitDeterminism:
    @classmethod
    def setup_class(cls):
        cls.scenarios = factory.load_v220_scenarios()

    def test_split_is_deterministic_across_runs(self):
        split_1 = factory.assign_split(self.scenarios)
        split_2 = factory.assign_split(self.scenarios)
        assert split_1 == split_2

    def test_split_covers_every_scenario_exactly_once(self):
        split_map = factory.assign_split(self.scenarios)
        assert set(split_map) == {s.scenario_id for s in self.scenarios}
        assert all(v in (SPLIT_DEV, SPLIT_HOLDOUT) for v in split_map.values())

    def test_holdout_fraction_is_roughly_target(self):
        split_map = factory.assign_split(self.scenarios, factory.DEFAULT_HOLDOUT_FRACTION)
        holdout_count = sum(1 for v in split_map.values() if v == SPLIT_HOLDOUT)
        fraction = holdout_count / len(split_map)
        assert 0.15 <= fraction <= 0.35, fraction

    def test_holdout_contains_multiple_difficulties(self):
        split_map = factory.assign_split(self.scenarios)
        holdout_difficulties = {s.difficulty for s in self.scenarios if split_map[s.scenario_id] == SPLIT_HOLDOUT}
        assert len(holdout_difficulties) >= 3, holdout_difficulties

    def test_holdout_contains_multi_turn_case(self):
        split_map = factory.assign_split(self.scenarios)
        holdout_multi_turn = sum(1 for s in self.scenarios if split_map[s.scenario_id] == SPLIT_HOLDOUT and s.is_multi_turn)
        assert holdout_multi_turn >= 1

    def test_holdout_contains_safety_sensitive_case(self):
        split_map = factory.assign_split(self.scenarios)
        holdout_safety = sum(1 for s in self.scenarios if split_map[s.scenario_id] == SPLIT_HOLDOUT and s.safety_sensitive)
        assert holdout_safety >= 1

    def test_dev_is_not_trivially_easier_than_holdout(self):
        # Section 116 - HOLDOUT is an independent sample, not "the hard
        # set." Proxy check: L3+ share in DEV must not be dramatically
        # lower than in HOLDOUT.
        split_map = factory.assign_split(self.scenarios)
        def l3_plus_share(split_name):
            subset = [s for s in self.scenarios if split_map[s.scenario_id] == split_name and s.difficulty]
            if not subset:
                return 0.0
            return sum(1 for s in subset if s.difficulty in ("L3", "L4", "L5")) / len(subset)
        dev_share = l3_plus_share(SPLIT_DEV)
        holdout_share = l3_plus_share(SPLIT_HOLDOUT)
        assert abs(dev_share - holdout_share) < 0.25, (dev_share, holdout_share)


class TestManifest:
    @classmethod
    def setup_class(cls):
        cls.scenarios = factory.load_v220_scenarios()
        cls.manifest_path = factory.V220_MANIFEST_PATH

    def test_manifest_file_exists(self):
        assert self.manifest_path.exists()

    def test_frozen_manifest_matches_recomputed_split_and_hashes(self):
        frozen = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        split_map = factory.assign_split(self.scenarios, frozen["holdout_fraction_target"])
        mismatches_dev = factory.verify_manifest(frozen["dev"], self.scenarios, split_map)
        mismatches_holdout = factory.verify_manifest(frozen["holdout"], self.scenarios, split_map)
        assert mismatches_dev == [], mismatches_dev
        assert mismatches_holdout == [], mismatches_holdout

    def test_manifest_declares_holdout_governance_flags(self):
        frozen = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        assert frozen["holdout_is_not_secret"] is True
        assert frozen["author_has_seen_holdout"] is True

    def test_manifest_catalog_snapshot_matches_current_products_file_or_is_documented_stale(self):
        frozen = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        current = factory.compute_catalog_snapshot()
        # Not asserted equal - the catalog legitimately changes over
        # time (Section 38 stale-truth lifecycle). This test only
        # proves the frozen snapshot is well-formed and traceable, not
        # that it is still current.
        assert frozen["catalog_snapshot"]["product_count"] > 0
        assert len(frozen["catalog_snapshot"]["content_hash"]) == 64
        assert current["source"] == frozen["catalog_snapshot"]["source"]

    def test_every_catalog_dependent_scenario_references_the_frozen_snapshot(self):
        frozen = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        snapshot_id = frozen["catalog_snapshot"]["snapshot_id"]
        for s in self.scenarios:
            if s.catalog_dependency:
                assert s.catalog_snapshot_id == snapshot_id, s.scenario_id


class TestContentHashStability:
    def test_content_hash_is_stable_for_same_input(self):
        scenarios = factory.load_v220_scenarios()
        h1 = factory.content_hash(scenarios)
        h2 = factory.content_hash(scenarios)
        assert h1 == h2

    def test_content_hash_is_order_independent(self):
        scenarios = factory.load_v220_scenarios()
        reversed_scenarios = list(reversed(scenarios))
        assert factory.content_hash(scenarios) == factory.content_hash(reversed_scenarios)

    def test_content_hash_changes_if_a_turn_message_changes(self):
        scenarios = factory.load_v220_scenarios()
        if not scenarios:
            return
        from dataclasses import replace

        original = scenarios[0]
        mutated_turn = replace(original.turns[0], message=original.turns[0].message + " ")
        mutated = replace(original, turns=(mutated_turn,) + original.turns[1:])
        changed = [mutated if s.scenario_id == original.scenario_id else s for s in scenarios]
        assert factory.content_hash(scenarios) != factory.content_hash(changed)
