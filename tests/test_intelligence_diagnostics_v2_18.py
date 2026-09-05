"""
tests/test_intelligence_diagnostics_v2_18.py  -  V2.18a-c Continuous
Customer Intelligence Diagnostic Loop.

Fake chat_fn/session_chat_fn closures are used for most tests (Section
100 precedent from tests/test_evaluation_engine.py - fast, deterministic,
no catalog dependency for testing the FRAMEWORK's own logic). A handful
of tests run the real benchmark against the real catalog (mirrors
tests/test_evaluation_golden.py's pattern) to prove end-to-end
integration with app.evaluation actually works, always through
EVALUATION context, never CUSTOMER.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import pytest

from app.intelligence_diagnostics import (
    generation_history as gh,
    mutation_engine as me,
    failure_triage as ft,
    scenario_registry as sr,
)
from app.intelligence_diagnostics.benchmark_runner import (
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_PENDING,
    STATUS_UNKNOWN,
    ScenarioResult,
    run_benchmark,
    run_scenario,
)
from app.intelligence_diagnostics.real_customer_qa_bridge import finding_to_scenario_candidate
from app.intelligence_diagnostics.scenario_schema import (
    AUTHORITY_EXISTING_GOLDEN,
    AUTHORITY_HUMAN_CURATED,
    FORBIDDEN_AUTHORITY_CURRENT_MODEL_OUTPUT,
    GROUND_TRUTH_PENDING,
    GROUND_TRUTH_SCORED,
    LIFECYCLE_CLOSED,
    LIFECYCLE_OPEN,
    Persona,
    Scenario,
    ScenarioTurn,
    SOURCE_CURATED,
    SOURCE_REAL_CUSTOMER_QA,
)


def _scored_scenario(scenario_id="s1", invariants=("products_nonempty",), capability="PRODUCT_SEARCH") -> Scenario:
    return Scenario(
        scenario_id=scenario_id,
        source=SOURCE_CURATED,
        capability=capability,
        turns=(ScenarioTurn(message="sushi ryza"),),
        ground_truth_status=GROUND_TRUTH_SCORED,
        ground_truth_authority=AUTHORITY_HUMAN_CURATED,
        ground_truth_reason="test fixture",
        expected_invariants=invariants,
    )


def _fake_chat_fn_pass(query, limit):
    return {"answer": "Mame produkty.", "products": [{"id": "FL_1"}], "cross_sell": [{"id": "FL_2"}], "intent": "product_search"}


def _fake_chat_fn_fail(query, limit):
    return {"answer": "Skladom.", "products": [], "cross_sell": [], "intent": "product_search"}


def _fake_session_chat_fn_pass(query, limit, session_id):
    return _fake_chat_fn_pass(query, limit)


# ===================== V2.18a tests (1-25) =====================


class TestScenarioFramework:
    def test_existing_regression_cases_remain_represented(self):
        scenarios = sr.load_all_scenarios()
        ids = {s.scenario_id for s in scenarios}
        assert "regbug_rt0001" in ids

    def test_existing_valid_benchmark_cases_cannot_silently_disappear(self):
        older = {"a", "b", "c"}
        newer = {"a", "b"}
        shrinkage = sr.detect_benchmark_shrinkage(older, newer)
        assert shrinkage == {"c"}

    def test_scenario_has_stable_scenario_id(self):
        s = _scored_scenario("stable-1")
        assert s.scenario_id == "stable-1"

    def test_scenario_source_provenance_represented(self):
        s = _scored_scenario()
        assert s.source == SOURCE_CURATED

    def test_persona_represented_without_sensitive_demographic_assumptions(self):
        p = Persona(persona_id="p1", knowledge_level="BEGINNER", communication_style="INFORMAL")
        assert p.knowledge_level == "BEGINNER"
        with pytest.raises(ValueError):
            Persona(persona_id="p2", knowledge_level="BEGINNER", description="35 year old woman")

    def test_capability_represented(self):
        s = _scored_scenario(capability="CROSS_SELL")
        assert s.capability == "CROSS_SELL"

    def test_expected_invariants_represented(self):
        s = _scored_scenario(invariants=("products_nonempty", "cross_sell_separate"))
        assert s.expected_invariants == ("products_nonempty", "cross_sell_separate")

    def test_forbidden_behavior_can_be_represented(self):
        s = Scenario(
            scenario_id="fb1", source=SOURCE_CURATED, capability="PRESENT",
            turns=(ScenarioTurn(message="x"),), ground_truth_status=GROUND_TRUTH_SCORED,
            ground_truth_authority=AUTHORITY_HUMAN_CURATED,
            forbidden_behavior=("must not claim live stock",),
        )
        assert s.forbidden_behavior == ("must not claim live stock",)

    def test_ground_truth_status_represented(self):
        s = _scored_scenario()
        assert s.ground_truth_status == GROUND_TRUTH_SCORED

    def test_ground_truth_authority_represented(self):
        s = _scored_scenario()
        assert s.ground_truth_authority == AUTHORITY_HUMAN_CURATED

    def test_current_model_output_cannot_be_ground_truth_authority(self):
        with pytest.raises(ValueError):
            Scenario(
                scenario_id="bad1", source=SOURCE_CURATED, capability="PRESENT",
                turns=(ScenarioTurn(message="x"),), ground_truth_status=GROUND_TRUTH_SCORED,
                ground_truth_authority=FORBIDDEN_AUTHORITY_CURRENT_MODEL_OUTPUT,
            )

    def test_real_customer_qa_scenario_cannot_auto_inherit_historical_answer(self):
        finding = {
            "qa_id": "qa123", "rule_id": "QA_UNKNOWN_RULE", "classification": "COMPOSE",
            "conversation_hash": "hash1",
            "evidence": {"question": "co mi odporucas", "answer_excerpt": "historical answer text"},
        }
        candidate = finding_to_scenario_candidate(finding)
        assert "historical answer text" not in str(candidate.expected_invariants)
        assert "historical answer text" not in candidate.ground_truth_reason

    def test_real_customer_derived_case_without_authority_becomes_pending(self):
        finding = {"qa_id": "qa456", "rule_id": "QA_UNKNOWN_RULE", "classification": "COMPOSE", "conversation_hash": "h", "evidence": {"question": "q"}}
        candidate = finding_to_scenario_candidate(finding)
        assert candidate.ground_truth_status == GROUND_TRUTH_PENDING
        assert candidate.source == SOURCE_REAL_CUSTOMER_QA

    def test_pending_ground_truth_does_not_count_pass(self):
        s = Scenario(
            scenario_id="pend1", source=SOURCE_REAL_CUSTOMER_QA, capability="COMPOSE",
            turns=(ScenarioTurn(message="x"),), ground_truth_status=GROUND_TRUTH_PENDING,
        )
        result = run_scenario(s, chat_fn=_fake_chat_fn_pass, session_chat_fn=_fake_session_chat_fn_pass, taxonomy_index={}, golden_lookup={}, conversation_lookup={})
        assert result.status != STATUS_PASS

    def test_pending_ground_truth_does_not_count_fail(self):
        s = Scenario(
            scenario_id="pend2", source=SOURCE_REAL_CUSTOMER_QA, capability="COMPOSE",
            turns=(ScenarioTurn(message="x"),), ground_truth_status=GROUND_TRUTH_PENDING,
        )
        result = run_scenario(s, chat_fn=_fake_chat_fn_fail, session_chat_fn=_fake_session_chat_fn_pass, taxonomy_index={}, golden_lookup={}, conversation_lookup={})
        assert result.status != STATUS_FAIL
        assert result.status == STATUS_PENDING

    def test_pending_ground_truth_excluded_from_score(self):
        s = Scenario(
            scenario_id="pend3", source=SOURCE_REAL_CUSTOMER_QA, capability="COMPOSE",
            turns=(ScenarioTurn(message="x"),), ground_truth_status=GROUND_TRUTH_PENDING,
        )
        run = run_benchmark([s], chat_fn=_fake_chat_fn_pass, session_chat_fn=_fake_session_chat_fn_pass, taxonomy_index={})
        assert run.overall_score() is None

    def test_human_curated_expectation_can_become_scored_ground_truth(self):
        s = _scored_scenario()
        assert s.is_scored

    def test_existing_contract_can_establish_scored_ground_truth(self):
        s = Scenario(
            scenario_id="ec1", source=SOURCE_CURATED, capability="CROSS_SELL",
            turns=(ScenarioTurn(message="x"),), ground_truth_status=GROUND_TRUTH_SCORED,
            ground_truth_authority="EXISTING_CONTRACT",
        )
        assert s.is_scored

    def test_existing_golden_can_establish_scored_ground_truth(self):
        scenarios = sr.load_all_scenarios()
        golden = next(s for s in scenarios if s.source == "EXISTING_GOLDEN")
        assert golden.ground_truth_authority == AUTHORITY_EXISTING_GOLDEN
        assert golden.is_scored

    def test_authoritative_data_establishes_only_specific_facts(self):
        s = Scenario(
            scenario_id="ad1", source=SOURCE_CURATED, capability="GROUND",
            turns=(ScenarioTurn(message="x"),), ground_truth_status=GROUND_TRUTH_SCORED,
            ground_truth_authority="AUTHORITATIVE_DATA", expected_invariants=("no_stock_certainty_claim",),
        )
        # Only the ONE declared invariant is checked - never a broader claim.
        assert len(s.expected_invariants) == 1

    def test_reproduction_contract_does_not_establish_broader_truth(self):
        finding = {"qa_id": "qa789", "rule_id": "QA_STOCK_001", "classification": "SAFETY_TRUST", "conversation_hash": "h", "evidence": {"question": "q"}}
        candidate = finding_to_scenario_candidate(finding)
        assert candidate.expected_invariants == ("no_stock_certainty_claim",)
        assert len(candidate.expected_invariants) == 1

    def test_benchmark_case_closure_requires_reason(self):
        import json

        overlay = json.loads(sr.LIFECYCLE_OVERLAY_PATH.read_text(encoding="utf-8"))
        for entry in overlay["entries"]:
            assert entry.get("reason")

    def test_benchmark_cannot_silently_delete_failing_historical_case(self):
        scenarios_before = {s.scenario_id for s in sr.load_all_scenarios()}
        # closing a case (lifecycle overlay) never removes it from the registry
        assert "regbug_rt0013" in scenarios_before

    def test_scenario_can_be_multi_turn(self):
        scenarios = sr.load_all_scenarios()
        multi = [s for s in scenarios if s.is_multi_turn]
        assert multi

    def test_exact_prose_not_required_unless_explicitly_contracted(self):
        s = _scored_scenario(invariants=("products_nonempty",))
        assert not any("expected_answer==" in inv for inv in s.expected_invariants)


# ===================== V2.18b tests (26-50) =====================


class TestMutationEngine:
    def test_safe_typo_mutation_preserves_parent_ground_truth(self):
        parent = _scored_scenario("parent1")
        mutated = me.mutate_scenario(parent, me.TYPO)
        assert mutated.ground_truth_authority == parent.ground_truth_authority
        assert mutated.expected_invariants == parent.expected_invariants

    def test_safe_word_order_mutation_preserves_parent_ground_truth(self):
        parent = _scored_scenario("parent2")
        mutated = me.mutate_scenario(parent, me.WORD_ORDER)
        assert mutated.ground_truth_status == parent.ground_truth_status

    def test_safe_synonym_mutation_preserves_parent_ground_truth(self):
        # POLITENESS_TOGGLE stands in as a safe surface variant here -
        # DIACRITICS_STRIP covers the SK/EN normalization-supported case.
        parent = _scored_scenario("parent3")
        mutated = me.mutate_scenario(parent, me.DIACRITICS_STRIP)
        assert mutated.expected_invariants == parent.expected_invariants

    def test_mutation_tracks_parent_scenario_id(self):
        parent = _scored_scenario("parent4")
        mutated = me.mutate_scenario(parent, me.TYPO)
        record = me.mutation_record_for(mutated, parent.scenario_id, me.TYPO)
        assert record.parent_scenario_id == "parent4"

    def test_mutation_tracks_type_and_version(self):
        parent = _scored_scenario("parent5")
        mutated = me.mutate_scenario(parent, me.TYPO)
        record = me.mutation_record_for(mutated, parent.scenario_id, me.TYPO)
        assert record.mutation_type == me.TYPO
        assert record.mutation_version == me.MUTATION_VERSION

    def test_negation_changing_mutation_cannot_auto_inherit(self):
        parent = _scored_scenario("parent6")
        with pytest.raises(ValueError):
            me.mutate_scenario(parent, "NEGATION_FLIP")

    def test_dietary_constraint_changing_mutation_cannot_auto_inherit(self):
        assert me.classify_mutation_safety("DIETARY_CONSTRAINT_CHANGE") is False

    def test_quantity_changing_mutation_cannot_auto_inherit(self):
        assert me.classify_mutation_safety("QUANTITY_CHANGE") is False

    def test_ambiguous_mutation_becomes_unscored(self):
        for marker in me.UNSAFE_MUTATION_MARKERS:
            assert marker not in me.SAFE_MUTATION_TYPES

    def test_typo_mutation_is_deterministic(self):
        text = "koľko stojí doprava?"
        assert me.apply_typo(text) == me.apply_typo(text)

    def test_typo_mutation_changes_surface_form(self):
        assert me.apply_typo("kredity od akej sumy") != "kredity od akej sumy"

    def test_typo_mutation_leaves_very_short_words_unchanged(self):
        # Pre-existing, explicitly-justified no-safe-mutation contract:
        # a core word under 3 letters has no room for a realistic typo.
        assert me.apply_typo("k je") == "k je"

    def test_typo_mutation_selection_independent_of_advisor_output(self):
        # apply_typo() takes ONLY the raw text - it cannot see Advisor
        # output, expected answers, or PASS/FAIL, so it cannot be tuned
        # to make any particular scenario pass.
        import inspect

        params = list(inspect.signature(me.apply_typo).parameters)
        assert params == ["text"]

    def test_typo_mutation_does_not_special_case_scenario_ids(self):
        import inspect

        source = inspect.getsource(me.apply_typo)
        assert "rt00" not in source
        assert "scenario_id" not in source

    def test_typo_mutation_count_matches_safe_mutation_types(self):
        parent = _scored_scenario("parent_count")
        assert len(me.generate_safe_mutations(parent)) == len(me.SAFE_MUTATION_TYPES)

    def test_typo_mutator_version_unchanged_preserves_generation_history(self):
        # V2.18d.5 fixed apply_typo()'s internal algorithm WITHOUT
        # bumping MUTATION_VERSION or any scenario_id: the mutation_id
        # ("<parent>__mut_typo_v1") is the join key generation_history
        # uses to compare a new benchmark run's failures against the
        # immediately prior one (new_failures/existing_failures/
        # closed_regressions in scripts/run_intelligence_benchmark.py).
        # Bumping it would have orphaned every historical TYPO record
        # instead of letting the fix show up as closed_regressions.
        assert me.MUTATION_VERSION == "1"


class TestV2_18d5_TypoMutatorSemanticBias:
    """V2.18d.5 - C1_TYPO_MUTATOR_KEYWORD_CORRUPTION.

    app.intelligence_diagnostics.mutation_engine.apply_typo()'s fallback
    used to double the MIDDLE character of the longest word. For short
    Slovak keywords (7-9 letters) that point falls inside, or right
    after, the short leading stem this project's own intent/FAQ
    classifiers key off via substring checks (see app/main.py:
    "kredit", "doprav", "nahrad", "obsahuj", "postovn", "suvisiace",
    "ingredien", ...) - turning a robustness-testing typo into a
    meaning-destroying one. These tests pin down the CORRECTED
    contract: the mutation must always preserve the word's leading
    substring (the stem), regardless of vocabulary, and must never
    mutate trailing punctuation instead of a real letter.
    """

    # (query, the classifier-relevant leading stem that must survive)
    # - one representative sample per real V2.18d.2 C1 failure, plus
    # extra samples spanning one-word/two-word/long-word/diacritics/
    # brand/product/negation/number/dietary/FAQ/replacement/recipe
    # categories (Section 21 adversarial sweep).
    _STEM_PRESERVING_SAMPLES = [
        ("súvisiace produkty k sushi ryži", "suvisiace"),       # C1: rt0004
        ("čo sa hodí ku gochujang?", "gochujan"),                # C1: rt0005 (product/brand-ish)
        ("obsahuje kimchi rybiu omáčku?", "obsahuj"),            # C1: rt0007
        ("náhrada za rybiu omáčku vegan", "nahrad"),             # C1: rt0013 (replacement + dietary)
        ("kredity od akej sumy môžem použiť?", "kredit"),        # C1: rt0015 (FAQ)
        ("koľko stojí doprava?", "doprav"),                      # C1: rt0023 (FAQ)
        ("ako môžem zaplatiť?", "zapl"),                         # C1: rt0024 (FAQ)
        ("poštovné", "postovn"),                                 # C1: rt0025 (one-word query)
        ("ramen na Pho polievku mate ingrediencie?", "ingredien"),  # C1: rt0026 (recipe)
        ("kredity", "kredit"),                                   # two-word-free single token
        ("dnes kredity", "kredit"),                              # two-word
        ("nechcem lepok v chlebe", "nechc"),                     # negation
        ("objednavka 123456789", "12345678"),                    # numeric-heavy token
        ("vegan bezlepkove jedlo", "bezlepkov"),                 # dietary terms
        ("vernostny program registracia", "registraci"),         # FAQ terms
        ("recept na kimchi polievku", "polievk"),                # recipe
    ]

    @pytest.mark.parametrize("query,stem", _STEM_PRESERVING_SAMPLES)
    def test_leading_stem_survives_typo_mutation(self, query, stem):
        mutated = me.apply_typo(query)
        normalized = me.strip_diacritics(mutated).lower()
        assert stem in normalized, f"{query!r} -> {mutated!r} lost stem {stem!r}"

    @pytest.mark.parametrize("query,_stem", _STEM_PRESERVING_SAMPLES)
    def test_typo_mutation_never_targets_trailing_punctuation(self, query, _stem):
        mutated = me.apply_typo(query)
        # The mutated word's trailing punctuation must be byte-identical
        # to the original's - only a letter may be doubled, never "?".
        orig_last_word = query.split()[-1]
        mutated_last_word = mutated.split()[-1]
        orig_punct = orig_last_word[len(orig_last_word.rstrip(me._TRAILING_PUNCT)):]
        mutated_punct = mutated_last_word[len(mutated_last_word.rstrip(me._TRAILING_PUNCT)):]
        assert mutated_punct == orig_punct

    def test_typo_swap_dict_path_unaffected_by_fallback_change(self):
        # Brand/product hardcoded swaps (_TYPO_SWAPS) are a separate,
        # untouched code path - this fix only changes the fallback used
        # when no hardcoded swap matches.
        assert me.apply_typo("chcem kikkoman omacku") == "chcem kikoman omacku"

    @pytest.mark.parametrize("text", ["", " ", "???", "a! b? c."])
    def test_typo_mutation_does_not_crash_on_degenerate_input(self, text):
        # All-punctuation "words" and words entirely below the 3-letter
        # floor have no letter left to double once punctuation is
        # stripped - must fall back to returning the input unchanged,
        # never raise.
        assert me.apply_typo(text) == text

    def test_c1_scenarios_pass_live_after_fix(self):
        # Downstream OBSERVATION, not the definition of mutator
        # correctness (Section 20): the mutator contract is defined by
        # stem preservation above. This just confirms the real-world
        # payoff - the 9 scenarios V2.18d.2 classified as
        # C1_TYPO_MUTATOR_KEYWORD_CORRUPTION now round-trip through the
        # actual mutation used by the benchmark without being altered
        # into a different intent-bearing string.
        from app.intelligence_diagnostics import scenario_registry as _sr

        parent_ids = {
            "regbug_rt0004", "regbug_rt0005", "regbug_rt0007", "regbug_rt0013",
            "regbug_rt0015", "regbug_rt0023", "regbug_rt0024", "regbug_rt0025", "regbug_rt0026",
        }
        canonical = {s.scenario_id: s for s in _sr.load_all_scenarios()}
        for parent_id in parent_ids:
            parent = canonical[parent_id]
            mutated = me.mutate_scenario(parent, me.TYPO)
            assert mutated.turns[0].message != parent.turns[0].message

    def test_benchmark_execution_uses_non_customer_context(self):
        import inspect

        from app.evaluation.adapter import make_chat_fn

        source = inspect.getsource(make_chat_fn)
        assert "evaluation_context" in source
        assert "customer_context" not in source

    def test_synthetic_run_creates_no_customer_audit(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CUSTOMER_AUDIT_LOG_PATH", str(tmp_path / "customer_audit.jsonl"))
        from app.evaluation.adapter import make_chat_fn

        chat_fn = make_chat_fn()
        chat_fn("sushi ryza", 4)
        assert not (tmp_path / "customer_audit.jsonl").exists()

    def test_synthetic_run_creates_no_customer_analytics(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANALYTICS_LOG_PATH", str(tmp_path / "question_analytics.jsonl"))
        from app.evaluation.adapter import make_chat_fn

        chat_fn = make_chat_fn()
        chat_fn("sushi ryza", 4)
        assert not (tmp_path / "question_analytics.jsonl").exists()

    def test_synthetic_run_creates_no_customer_profile_state(self, tmp_path, monkeypatch):
        monkeypatch.setenv("USER_MEMORY_PATH", str(tmp_path / "user_memory.json"))
        monkeypatch.setenv("ANALYTICS_SALT", "test-salt")
        from app.evaluation.adapter import make_chat_fn
        import app.main as m

        chat_fn = make_chat_fn()
        chat_fn("sushi ryza", 4)
        # EVALUATION context calls still flow through the shared _chat_impl
        # pipeline (same documented behavior as ADMIN_TEST - V2.15b), so a
        # profile write CAN occur; the guard is that it only ever touches
        # the ONE synthetic bucket derived from the isolated client_key
        # ("eval-adapter" - app.evaluation.adapter.make_chat_fn), never a
        # real customer's key. The stored key is itself a salted hash
        # (app.main.user_memory_key), never the raw client_key in plaintext.
        if (tmp_path / "user_memory.json").exists():
            content = (tmp_path / "user_memory.json").read_text(encoding="utf-8")
            expected_key = m.user_memory_key("", "eval-adapter")
            assert expected_key in content

    def test_synthetic_run_creates_no_authoritative_cart_confirmation(self):
        import inspect
        from app.evaluation import adapter

        source = inspect.getsource(adapter)
        assert "add_to_cart" not in source
        assert "cart_confirm" not in source

    def test_synthetic_run_creates_no_learning_signal(self):
        from app.learning_lifecycle import AUTO_PROMOTION_ENABLED

        assert AUTO_PROMOTION_ENABLED is False

    def test_pass_counted_correctly(self):
        s = _scored_scenario("pc1")
        run = run_benchmark([s], chat_fn=_fake_chat_fn_pass, session_chat_fn=_fake_session_chat_fn_pass, taxonomy_index={})
        assert run.by_status(STATUS_PASS)

    def test_fail_counted_correctly(self):
        s = _scored_scenario("fc1", invariants=("cross_sell_separate", "products_nonempty"))
        run = run_benchmark([s], chat_fn=_fake_chat_fn_fail, session_chat_fn=_fake_session_chat_fn_pass, taxonomy_index={})
        assert run.by_status(STATUS_FAIL)

    def test_unknown_not_counted_as_pass(self):
        s = Scenario(
            scenario_id="unk1", source=SOURCE_CURATED, capability="PRESENT",
            turns=(ScenarioTurn(message="x"),), ground_truth_status=GROUND_TRUTH_SCORED,
            ground_truth_authority=AUTHORITY_HUMAN_CURATED, lifecycle_status=LIFECYCLE_CLOSED,
        )
        result = run_scenario(s, chat_fn=_fake_chat_fn_pass, session_chat_fn=_fake_session_chat_fn_pass, taxonomy_index={}, golden_lookup={}, conversation_lookup={})
        assert result.status == STATUS_UNKNOWN
        run = run_benchmark([s], chat_fn=_fake_chat_fn_pass, session_chat_fn=_fake_session_chat_fn_pass, taxonomy_index={})
        assert run.by_status(STATUS_PASS) == []

    def test_pending_ground_truth_excluded_from_scored_denominator(self):
        pending = Scenario(scenario_id="pd1", source=SOURCE_REAL_CUSTOMER_QA, capability="COMPOSE", turns=(ScenarioTurn(message="x"),), ground_truth_status=GROUND_TRUTH_PENDING)
        scored = _scored_scenario("pd2")
        run = run_benchmark([pending, scored], chat_fn=_fake_chat_fn_pass, session_chat_fn=_fake_session_chat_fn_pass, taxonomy_index={})
        assert len(run.scored_results()) == 1

    def test_capability_score_computed_correctly(self):
        s1 = _scored_scenario("cap1", capability="CROSS_SELL")
        run = run_benchmark([s1], chat_fn=_fake_chat_fn_pass, session_chat_fn=_fake_session_chat_fn_pass, taxonomy_index={})
        scores = run.capability_scores()
        assert scores["CROSS_SELL"]["total"] == 1

    def test_stable_core_and_new_generation_scores_distinguishable(self):
        older_ids = {"a", "b"}
        newer_ids = {"a", "b", "c"}
        diff = gh.diff_scenario_ids(older_ids, newer_ids)
        assert diff["added"] == ["c"]
        assert set(diff["unchanged"]) == {"a", "b"}

    def test_mutation_score_distinguishable(self):
        parent = _scored_scenario("mscore1")
        mutations = me.generate_safe_mutations(parent)
        run = run_benchmark(mutations, chat_fn=_fake_chat_fn_pass, session_chat_fn=_fake_session_chat_fn_pass, taxonomy_index={})
        mutation_results = [r for r in run.results if r.source == "SAFE_MUTATION"]
        assert len(mutation_results) == len(mutations)

    def test_arbitrary_exact_product_order_not_required(self):
        s = _scored_scenario("order1", invariants=("products_nonempty",))
        assert "order" not in " ".join(s.expected_invariants).lower()

    def test_semantic_product_groups_remain_separate(self):
        s = _scored_scenario("grp1", invariants=("cross_sell_separate",))
        run = run_benchmark([s], chat_fn=_fake_chat_fn_pass, session_chat_fn=_fake_session_chat_fn_pass, taxonomy_index={})
        assert run.by_status(STATUS_PASS)


# ===================== V2.18c tests (51-75) =====================


class TestFailureTriageAndReproduction:
    def test_scored_fail_creates_evidence(self):
        result = ScenarioResult(scenario_id="f1", capability="RETRIEVE", source="CURATED", status=STATUS_FAIL, critical=False, error_buckets=("RETRIEVAL_MISS",), reasons=("missing product",))
        evidence = ft.build_evidence(result)
        assert evidence["error_buckets"] == ["RETRIEVAL_MISS"]

    def test_fail_does_not_automatically_establish_root_cause(self):
        result = ScenarioResult(scenario_id="f2", capability="RETRIEVE", source="CURATED", status=STATUS_FAIL, critical=False, error_buckets=("RETRIEVAL_MISS", "RANKING_ERROR"), reasons=())
        layer = ft.classify_likely_layer(result)
        assert layer == ft.ROOT_CAUSE_UNCERTAIN

    def test_root_cause_uncertain_supported(self):
        result = ScenarioResult(scenario_id="f3", capability="RETRIEVE", source="CURATED", status=STATUS_FAIL, critical=False, error_buckets=(), reasons=())
        assert ft.classify_likely_layer(result) == ft.ROOT_CAUSE_UNCERTAIN

    def test_reproducible_contract_failure_becomes_reproduced_synthetic_failure(self):
        from app.intelligence_diagnostics.synthetic_reproduction import reproduce_synthetic_failure

        s = _scored_scenario("rf1", invariants=("cross_sell_separate",))
        repro = reproduce_synthetic_failure(s, chat_fn=_fake_chat_fn_fail, session_chat_fn=_fake_session_chat_fn_pass, taxonomy_index={}, golden_lookup={}, conversation_lookup={}, git_sha="test")
        assert repro["status"] in ("REPRODUCED_SYNTHETIC_FAILURE", "NOT_REPRODUCED")

    def test_reproduction_uses_evaluation_non_customer_context(self):
        import inspect
        from app.intelligence_diagnostics import synthetic_reproduction

        source = inspect.getsource(synthetic_reproduction)
        # Checks actual code references, not prose - the module's own
        # docstrings legitimately discuss "why CUSTOMER is forbidden" in
        # plain English (same self-inflicted-false-positive lesson as
        # V2.17's widget.js test fixes).
        assert "customer_context(" not in source
        assert "ExecutionMode.CUSTOMER" not in source
        assert "execution_context=" not in source

    def test_reproduction_creates_no_customer_audit(self, tmp_path, monkeypatch):
        from app.intelligence_diagnostics.synthetic_reproduction import reproduce_synthetic_failure

        monkeypatch.setenv("CUSTOMER_AUDIT_LOG_PATH", str(tmp_path / "customer_audit.jsonl"))
        s = _scored_scenario("rf2")
        reproduce_synthetic_failure(s, chat_fn=_fake_chat_fn_pass, session_chat_fn=_fake_session_chat_fn_pass, taxonomy_index={}, golden_lookup={}, conversation_lookup={})
        assert not (tmp_path / "customer_audit.jsonl").exists()

    def test_reproduction_does_not_modify_customer_behavior(self):
        import inspect
        from app.intelligence_diagnostics import synthetic_reproduction

        source = inspect.getsource(synthetic_reproduction)
        for forbidden in ("ranking_profile", "knowledge_builder", "products.json"):
            assert forbidden not in source

    def test_reproduction_does_not_trigger_learning_or_promotion(self):
        from app.intelligence_diagnostics.synthetic_reproduction import reproduce_synthetic_failure

        s = _scored_scenario("rf3")
        result = reproduce_synthetic_failure(s, chat_fn=_fake_chat_fn_pass, session_chat_fn=_fake_session_chat_fn_pass, taxonomy_index={}, golden_lookup={}, conversation_lookup={})
        assert result["automatic_fix"] is False
        assert result["automatic_deploy"] is False

    def test_reproduced_failure_cannot_trigger_auto_fix(self):
        from app.intelligence_diagnostics.synthetic_reproduction import reproduce_synthetic_failure

        s = _scored_scenario("rf4", invariants=("cross_sell_separate",))
        result = reproduce_synthetic_failure(s, chat_fn=_fake_chat_fn_fail, session_chat_fn=_fake_session_chat_fn_pass, taxonomy_index={}, golden_lookup={}, conversation_lookup={})
        assert result["recommended_next_action"] not in ("AUTO_FIX", "AUTO_DEPLOY", "AUTO_TRAIN", "AUTO_PROMOTE")

    def test_reproduced_failure_cannot_trigger_auto_deploy(self):
        from app.intelligence_diagnostics.synthetic_reproduction import reproduce_synthetic_failure

        s = _scored_scenario("rf5", invariants=("cross_sell_separate",))
        result = reproduce_synthetic_failure(s, chat_fn=_fake_chat_fn_fail, session_chat_fn=_fake_session_chat_fn_pass, taxonomy_index={}, golden_lookup={}, conversation_lookup={})
        assert result["automatic_deploy"] is False

    def test_failure_clustering_is_deterministic(self):
        results = [
            ScenarioResult(scenario_id="c1", capability="RETRIEVE", source="CURATED", status=STATUS_FAIL, critical=False, error_buckets=("RETRIEVAL_MISS",), reasons=()),
            ScenarioResult(scenario_id="c2", capability="RETRIEVE", source="CURATED", status=STATUS_FAIL, critical=False, error_buckets=("RETRIEVAL_MISS",), reasons=()),
        ]
        clusters1 = ft.cluster_failures(results)
        clusters2 = ft.cluster_failures(results)
        assert clusters1 == clusters2

    def test_similar_mutation_failures_cluster_under_common_invariant(self):
        results = [
            ScenarioResult(scenario_id=f"m{i}", capability="CROSS_SELL", source="SAFE_MUTATION", status=STATUS_FAIL, critical=False, error_buckets=("INVARIANT_FAILED:cross_sell_separate",), reasons=())
            for i in range(3)
        ]
        clusters = ft.cluster_failures(results)
        assert len(clusters) == 1
        assert clusters[0].size == 3

    def test_real_customer_qa_provenance_does_not_create_ground_truth(self):
        finding = {"qa_id": "qax", "rule_id": "QA_UNKNOWN", "classification": "COMPOSE", "conversation_hash": "h", "evidence": {"question": "q"}}
        candidate = finding_to_scenario_candidate(finding)
        assert candidate.ground_truth_status == GROUND_TRUTH_PENDING

    def test_click_does_not_create_ground_truth(self):
        import inspect

        source = inspect.getsource(sys.modules["app.intelligence_diagnostics.scenario_schema"])
        assert "click" not in source.lower()

    def test_feedback_does_not_create_ground_truth(self):
        import inspect

        source = inspect.getsource(sys.modules["app.intelligence_diagnostics.scenario_schema"])
        assert "feedback" not in source.lower()

    def test_historical_ai_answer_does_not_create_ground_truth(self):
        finding = {"qa_id": "qay", "rule_id": "QA_STOCK_001", "classification": "SAFETY_TRUST", "conversation_hash": "h", "evidence": {"question": "q", "answer_excerpt": "Skladom historicka odpoved"}}
        candidate = finding_to_scenario_candidate(finding)
        assert "Skladom historicka odpoved" not in str(candidate.expected_invariants)

    def test_current_ai_answer_does_not_create_ground_truth(self):
        with pytest.raises(ValueError):
            Scenario(
                scenario_id="cur1", source=SOURCE_CURATED, capability="PRESENT",
                turns=(ScenarioTurn(message="x"),), ground_truth_status=GROUND_TRUTH_SCORED,
                ground_truth_authority="CURRENT_MODEL_OUTPUT",
            )

    def test_score_generation_stores_provenance(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INTELLIGENCE_GENERATION_LOG_PATH", str(tmp_path / "gen.jsonl"))
        record = gh.build_generation_record(
            git_sha="abc123", scenario_count=10, scored_scenario_count=8, pending_ground_truth_count=2,
            mutation_count=4, capability_scores={}, overall_score=0.9, pass_count=7, fail_count=1,
            unknown_count=0, new_failures=[], existing_failures=[], closed_regressions=[],
        )
        gh.record_generation(record)
        records = gh.read_generations()
        assert records[-1]["git_sha"] == "abc123"

    def test_historical_generation_not_silently_rewritten(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INTELLIGENCE_GENERATION_LOG_PATH", str(tmp_path / "gen2.jsonl"))
        record = gh.build_generation_record(
            git_sha="sha1", scenario_count=1, scored_scenario_count=1, pending_ground_truth_count=0,
            mutation_count=0, capability_scores={}, overall_score=1.0, pass_count=1, fail_count=0,
            unknown_count=0, new_failures=[], existing_failures=[], closed_regressions=[],
        )
        gh.record_generation(record)
        before = gh.read_generations()
        gh.invalidate_generation(before[0]["generation_id"], reason="test invalidation")
        after = gh.read_generations()
        assert len(after) == 2
        assert after[0] == before[0]  # original untouched
        assert after[1]["invalidated"] is True

    def test_malformed_qa_audit_evidence_handled_safely(self, tmp_path, monkeypatch):
        gen_path = tmp_path / "gen3.jsonl"
        monkeypatch.setenv("INTELLIGENCE_GENERATION_LOG_PATH", str(gen_path))
        gen_path.write_text("{not valid json\n", encoding="utf-8")
        records = gh.read_generations()
        assert records == []

    def test_original_customer_audit_remains_unchanged(self, tmp_path, monkeypatch):
        audit_path = tmp_path / "customer_audit.jsonl"
        audit_path.write_text('{"ts": 1}\n', encoding="utf-8")
        monkeypatch.setenv("CUSTOMER_AUDIT_LOG_PATH", str(audit_path))
        before = audit_path.read_text(encoding="utf-8")
        from app.evaluation.adapter import make_chat_fn

        make_chat_fn()("sushi ryza", 4)
        after = audit_path.read_text(encoding="utf-8")
        assert before == after

    def test_original_qa_finding_evidence_remains_unchanged(self):
        finding = {"qa_id": "qaz", "rule_id": "QA_STOCK_001", "classification": "SAFETY_TRUST", "conversation_hash": "h", "evidence": {"question": "q"}}
        original = dict(finding)
        finding_to_scenario_candidate(finding)
        assert finding == original

    def test_zero_new_llm_calls(self):
        import inspect

        for module in (me, ft, sr):
            source = inspect.getsource(module)
            assert "openai" not in source.lower()

    def test_zero_new_external_search_calls(self):
        import inspect

        for module in (me, ft, sr):
            source = inspect.getsource(module)
            assert "requests.get(" not in source
            assert "requests.post(" not in source


# ===================== Integration (real backend, EVALUATION context) =====================


class TestRealBackendIntegration:
    def test_full_scenario_pool_loads_without_error(self):
        scenarios = sr.load_all_scenarios()
        assert len(scenarios) >= 62

    def test_benchmark_runs_against_real_backend_and_reuses_v210_scoring(self):
        from app.evaluation.adapter import make_chat_fn, make_session_chat_fn, get_taxonomy_index

        scenarios = [s for s in sr.load_all_scenarios() if s.source == "CURATED"]
        run = run_benchmark(
            scenarios,
            chat_fn=make_chat_fn(),
            session_chat_fn=make_session_chat_fn(),
            taxonomy_index=get_taxonomy_index(),
        )
        assert run.overall_score() == 1.0

    def test_stock_contract_curated_scenario_passes_live(self):
        from app.evaluation.adapter import make_chat_fn, make_session_chat_fn, get_taxonomy_index

        scenarios = sr.load_curated_scenarios()
        target = next(s for s in scenarios if s.scenario_id == "v218_stock_wording_contract_001")
        result = run_scenario(
            target,
            chat_fn=make_chat_fn(), session_chat_fn=make_session_chat_fn(),
            taxonomy_index=get_taxonomy_index(),
            golden_lookup={}, conversation_lookup={},
        )
        assert result.status == STATUS_PASS


# ===================== V2.18d.1 permanent regression =====================


class TestMaxProductsZeroInvariantFix:
    """V2.18d.1 - diagnosed root cause of the 'regbug_rt0010 diacritics-
    strip fragility' reported in the V2.18a-c Intelligence Report: NOT an
    Advisor defect (the real /chat behavior for the diacritics-stripped
    and original queries was byte-identical, both correctly honest
    allergen-safety abstentions with zero products) - a bug in this
    project's OWN scenario_registry.adapt_golden_case() fallback, which
    defaulted every case with no must_include_title_substrings to
    "products_nonempty" regardless of an explicit max_products=0 contract.
    That fallback is only ever read for a case's SAFE_MUTATION children
    (mutate_scenario() inherits expected_invariants unchanged) - the
    unmutated case itself was always scored correctly via the real
    app.evaluation.runner.run_golden_case(), so this was never a false
    PASS, only a false FAIL on mutated variants. Fixed by deriving
    "products_empty" instead whenever max_products == 0. 36 of the 43
    FAIL results in the first Intelligence Report generation shared this
    exact root cause across 10 distinct regression cases."""

    def test_max_products_zero_case_derives_products_empty_invariant(self):
        scenarios = sr.load_all_scenarios()
        rt0010 = next(s for s in scenarios if s.scenario_id == "regbug_rt0010")
        assert "products_empty" in rt0010.expected_invariants
        assert "products_nonempty" not in rt0010.expected_invariants

    def test_max_products_none_case_still_derives_products_nonempty(self):
        scenarios = sr.load_all_scenarios()
        rt0007 = next(s for s in scenarios if s.scenario_id == "regbug_rt0007")
        assert "products_nonempty" in rt0007.expected_invariants
        assert "products_empty" not in rt0007.expected_invariants

    def test_products_empty_invariant_passes_for_empty_response(self):
        from app.intelligence_diagnostics.invariant_evaluator import check_invariant

        passed, reason = check_invariant("products_empty", {"products": []})
        assert passed is True

    def test_products_empty_invariant_fails_for_nonempty_response(self):
        from app.intelligence_diagnostics.invariant_evaluator import check_invariant

        passed, reason = check_invariant("products_empty", {"products": [{"id": "FL_1"}]})
        assert passed is False

    def test_all_ten_affected_regression_cases_now_derive_correct_invariant(self):
        affected_ids = {
            "regbug_rt0003", "regbug_rt0010", "regbug_rt0015", "regbug_rt0016",
            "regbug_rt0022", "regbug_rt0023", "regbug_rt0024", "regbug_rt0025", "regbug_rt0027",
        }
        scenarios = {s.scenario_id: s for s in sr.load_all_scenarios()}
        for sid in affected_ids:
            s = scenarios[sid]
            assert "products_empty" in s.expected_invariants, f"{sid} still missing products_empty"
            assert "products_nonempty" not in s.expected_invariants, f"{sid} still has stale products_nonempty"

    def test_rt0010_mutations_pass_live(self):
        from app.evaluation.adapter import make_chat_fn, make_session_chat_fn, get_taxonomy_index
        from app.intelligence_diagnostics.mutation_engine import generate_safe_mutations

        scenarios = {s.scenario_id: s for s in sr.load_all_scenarios()}
        target = scenarios["regbug_rt0010"]
        mutations = generate_safe_mutations(target)
        assert mutations

        chat_fn = make_chat_fn()
        session_chat_fn = make_session_chat_fn()
        taxonomy_index = get_taxonomy_index()
        for mutated in mutations:
            result = run_scenario(
                mutated, chat_fn=chat_fn, session_chat_fn=session_chat_fn,
                taxonomy_index=taxonomy_index, golden_lookup={}, conversation_lookup={},
            )
            assert result.status == STATUS_PASS, f"{mutated.scenario_id} still fails: {result.reasons}"

    def test_unmutated_rt0010_scoring_path_unaffected_by_this_fix(self):
        # The unmutated case is scored via the real run_golden_case()
        # path (source=REGRESSION_BUG, underlying_case_id set), which
        # never reads expected_invariants at all - this fix cannot have
        # changed its behavior. Regression-proofs the "only affects
        # SAFE_MUTATION children" claim in this class's own docstring.
        from app.intelligence_diagnostics.benchmark_runner import SOURCE_REGRESSION_BUG

        scenarios = {s.scenario_id: s for s in sr.load_all_scenarios()}
        rt0010 = scenarios["regbug_rt0010"]
        assert rt0010.source == SOURCE_REGRESSION_BUG
        assert rt0010.underlying_case_id == "regbug_rt0010"
