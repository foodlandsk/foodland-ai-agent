"""
tests/test_evaluation_engine.py  -  Sprint V2.10 tests for the evaluator
itself (Section 100/101).

An evaluator that always passes is useless (Section 101) - the
deliberate-failure tests below prove the opposite: given a demonstrably
WRONG response, the evaluator must fail it. Metric-level tests use tiny
hand-computed examples (no catalog access needed - app.evaluation.metrics
is pure). Runner/conversation tests use fake chat_fn closures, never the
real app.main.chat() (that integration is covered separately in
tests/test_evaluation_golden.py against the real catalog).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.baseline import (
    GATE_FAIL,
    GATE_PASS,
    GATE_WARN,
    aggregate_results,
    diff_against_baseline,
    evaluate_quality_gates,
)
from app.evaluation.conversation import run_conversation_case
from app.evaluation.loader import load_all_conversation_cases, load_all_golden_cases
from app.evaluation.metrics import (
    dcg_at_k,
    duplicate_rate,
    eligibility_precision,
    hit_rate_at_k,
    mrr,
    ndcg_at_k,
    overlap_rate,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from app.evaluation.runner import run_golden_case
from app.evaluation.schema import ConversationCase, ConversationTurn, GoldenCase


class TestMetricsCorrectness:
    def test_eligibility_precision_basic(self):
        concept_map = {"A": "jasmine_rice", "B": "rice_vinegar"}
        assert eligibility_precision(["A", "B"], frozenset({"rice_vinegar"}), concept_map) == 0.5

    def test_eligibility_precision_empty_returns_vacuous_pass(self):
        assert eligibility_precision([], frozenset({"x"}), {}) == 1.0

    def test_eligibility_precision_no_forbidden_concepts(self):
        assert eligibility_precision(["A"], frozenset(), {"A": "x"}) == 1.0

    def test_precision_at_k(self):
        assert precision_at_k(["A", "B", "C"], {"A", "C"}, 3) == 2 / 3
        assert precision_at_k([], {"A"}, 3) == 0.0

    def test_recall_at_k(self):
        assert recall_at_k(["A", "B"], {"A", "B", "C"}, 2) == 2 / 3
        assert recall_at_k(["A"], set(), 5) == 1.0

    def test_hit_rate_at_k(self):
        assert hit_rate_at_k(["A", "B"], {"B"}, 2) == 1.0
        assert hit_rate_at_k(["A", "B"], {"Z"}, 2) == 0.0

    def test_reciprocal_rank(self):
        assert reciprocal_rank(["A", "B", "C"], {"B"}) == 0.5
        assert reciprocal_rank(["A"], {"Z"}) == 0.0

    def test_mrr(self):
        assert mrr([1.0, 0.5, 0.0]) == 0.5
        assert mrr([]) == 0.0

    def test_dcg_monotonic_with_position(self):
        # Same relevance value ranked earlier must score >= ranked later.
        early = dcg_at_k([3.0, 0.0], 2)
        late = dcg_at_k([0.0, 3.0], 2)
        assert early > late

    def test_ndcg_perfect_ranking_is_one(self):
        assert ndcg_at_k(["A", "B", "C"], {"A": 3, "B": 2, "C": 1}, 3) == 1.0

    def test_ndcg_worst_ranking_is_low(self):
        score = ndcg_at_k(["C", "B", "A"], {"A": 3, "B": 2, "C": 1}, 3)
        assert score < 1.0

    def test_ndcg_no_graded_relevance_is_vacuous_pass(self):
        assert ndcg_at_k(["A", "B"], {"A": 0, "B": 0}, 2) == 1.0

    def test_duplicate_rate(self):
        assert duplicate_rate(["A", "A", "B"]) == 1 / 3
        assert duplicate_rate(["A", "B", "C"]) == 0.0
        assert duplicate_rate([]) == 0.0

    def test_overlap_rate(self):
        assert overlap_rate(["A", "B"], ["B", "C"]) == 0.5
        assert overlap_rate(["A"], []) == 0.0


class TestDeliberateFailureDetection:
    """Section 101 - the evaluator must be PROVABLY able to catch a wrong
    response, not just pass everything by construction."""

    def test_ineligible_product_injection_is_caught(self):
        taxonomy_index = {
            "A": type("T", (), {"concept_id": "jasmine_rice"})(),
            "V": type("T", (), {"concept_id": "rice_vinegar"})(),
        }
        case = GoldenCase(
            id="deliberate_1", query="jazminova ryza", query_type="ATTRIBUTE",
            expected_concept_ids=("jasmine_rice",), must_not_concept_ids=("rice_vinegar",), critical=True,
        )

        def wrong_chat(query, limit):
            return {"products": [{"id": "V", "title": "Rice vinegar"}, {"id": "A", "title": "Jasmine"}]}

        result = run_golden_case(case, wrong_chat, taxonomy_index)
        assert not result.passed
        assert result.critical_failure
        assert "ELIGIBILITY_ERROR" in result.error_buckets

    def test_correct_response_is_not_falsely_flagged(self):
        taxonomy_index = {"A": type("T", (), {"concept_id": "jasmine_rice"})()}
        case = GoldenCase(
            id="deliberate_2", query="jazminova ryza", query_type="ATTRIBUTE",
            expected_concept_ids=("jasmine_rice",), must_not_concept_ids=("rice_vinegar",),
        )

        def correct_chat(query, limit):
            return {"products": [{"id": "A", "title": "Jasmine"}]}

        result = run_golden_case(case, correct_chat, taxonomy_index)
        assert result.passed

    def test_wrong_ordinal_reference_resolution_is_caught(self):
        case = ConversationCase(
            id="deliberate_ordinal", session_id_prefix="d", critical=True,
            turns=(
                ConversationTurn(message="show", expected_products_nonempty=True),
                ConversationTurn(message="second one", expected_reference_resolved_from_previous_index=1),
            ),
        )

        def wrong_chat(message, limit, session_id):
            if message == "show":
                return {"products": [{"id": "A"}, {"id": "B"}, {"id": "C"}]}
            return {"products": [{"id": "C"}]}  # should have been B (index 1)

        result = run_conversation_case(case, wrong_chat)
        assert not result.passed
        assert result.critical_failure
        assert result.reference_errors == 1

    def test_context_contamination_is_caught(self):
        case = ConversationCase(
            id="deliberate_hardswitch", session_id_prefix="d", critical=True,
            turns=(
                ConversationTurn(message="sushi rice"),
                ConversationTurn(message="Shin Ramyun", expected_context_switch="HARD"),
            ),
        )

        def contaminated_chat(message, limit, session_id):
            # Same products returned regardless of message - simulates a
            # hard switch that failed to clear stale context.
            return {"products": [{"id": "A"}, {"id": "B"}]}

        result = run_conversation_case(case, contaminated_chat)
        assert not result.passed
        assert result.context_contamination

    def test_clean_hard_switch_is_not_falsely_flagged(self):
        case = ConversationCase(
            id="deliberate_hardswitch_ok", session_id_prefix="d",
            turns=(
                ConversationTurn(message="sushi rice"),
                ConversationTurn(message="Shin Ramyun", expected_context_switch="HARD"),
            ),
        )

        def clean_chat(message, limit, session_id):
            return {"products": [{"id": "A"}]} if message == "sushi rice" else {"products": [{"id": "Z"}]}

        result = run_conversation_case(case, clean_chat)
        assert result.passed
        assert not result.context_contamination


class TestBaselineAndGates:
    def _fake_summary(self, golden_passed: dict[str, bool]) -> dict:
        return {
            "golden": {
                "total": len(golden_passed), "passed": sum(golden_passed.values()),
                "pass_rate": sum(golden_passed.values()) / len(golden_passed),
                "critical_failures": [k for k, v in golden_passed.items() if not v],
                "error_buckets": {}, "avg_eligibility_precision": 1.0, "avg_precision_at_5": 1.0,
                "avg_recall_at_5": 1.0, "avg_hit_rate_at_3": 1.0, "mrr": 1.0, "max_duplicate_rate": 0.0,
                "per_case": {k: {"passed": v, "critical_failure": not v, "error_buckets": []} for k, v in golden_passed.items()},
            },
            "conversations": {
                "total": 0, "passed": 0, "pass_rate": 1.0, "context_contamination_rate": 0.0,
                "reference_errors_total": 0, "critical_failures": [], "per_case": {},
            },
            "taxonomy": {}, "performance": {},
        }

    def test_diff_detects_regression(self):
        baseline = {"summary": self._fake_summary({"c1": True, "c2": True})}
        candidate = self._fake_summary({"c1": True, "c2": False})
        diff = diff_against_baseline(baseline, candidate)
        assert diff["golden_regressions"] == ["c2"]
        assert diff["golden_improvements"] == []

    def test_diff_detects_improvement(self):
        baseline = {"summary": self._fake_summary({"c1": False, "c2": True})}
        candidate = self._fake_summary({"c1": True, "c2": True})
        diff = diff_against_baseline(baseline, candidate)
        assert diff["golden_improvements"] == ["c1"]

    def test_gate_fails_on_critical_regression(self):
        baseline = {"summary": self._fake_summary({"c1": True})}
        candidate = self._fake_summary({"c1": False})
        gates = evaluate_quality_gates(candidate, baseline, frozenset({"c1"}))
        assert gates["gate"] == GATE_FAIL
        assert any("c1" in reason for reason in gates["blocking_reasons"])

    def test_gate_does_not_fail_on_non_critical_regression(self):
        baseline = {"summary": self._fake_summary({"c1": True})}
        candidate = self._fake_summary({"c1": False})
        gates = evaluate_quality_gates(candidate, baseline, frozenset())  # c1 not critical
        assert gates["gate"] != GATE_FAIL

    def test_gate_blocks_on_context_contamination_regardless_of_baseline(self):
        candidate = self._fake_summary({"c1": True})
        candidate["conversations"]["context_contamination_rate"] = 0.1
        gates = evaluate_quality_gates(candidate, None, frozenset())
        assert gates["gate"] == GATE_FAIL

    def test_gate_first_run_no_baseline_does_not_block_on_preexisting_failure(self):
        candidate = self._fake_summary({"c1": False})
        gates = evaluate_quality_gates(candidate, None, frozenset({"c1"}))
        assert gates["gate"] != GATE_FAIL
        assert gates["gate"] == GATE_WARN

    def test_gate_all_pass_is_pass(self):
        candidate = self._fake_summary({"c1": True})
        gates = evaluate_quality_gates(candidate, None, frozenset())
        assert gates["gate"] == GATE_PASS


class TestGoldenDatasetIntegrity:
    """The dataset itself must load cleanly and be internally consistent -
    independent of whether individual cases currently pass against the
    live system."""

    def test_all_golden_cases_load_with_unique_ids(self):
        cases = load_all_golden_cases()
        assert len(cases) > 0
        ids = [c.id for c in cases]
        assert len(ids) == len(set(ids))

    def test_every_case_has_a_query_type(self):
        for case in load_all_golden_cases():
            assert case.query_type

    def test_conversation_cases_load_with_unique_ids(self):
        cases = load_all_conversation_cases()
        assert len(cases) > 0
        ids = [c.id for c in cases]
        assert len(ids) == len(set(ids))

    def test_every_conversation_has_at_least_two_turns(self):
        for case in load_all_conversation_cases():
            assert len(case.turns) >= 2, f"{case.id} should be a GoldenCase if it only has one turn"
