"""
tests/test_scenario_candidates.py  -  V2.23a candidate-intake framework
tests.

Scope: the intake/schema/storage layer only (app/scenario_candidates.py,
scripts/add_learning_candidate.py). Does NOT exercise the Advisor - no
test here calls app.main.chat()/make_chat_fn(); that is intentional,
mirroring the mandate's "Advisor Behavior Freeze" (Section 31).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.scenario_candidates import (
    FORBIDDEN_AUTHORITIES,
    GT_HUMAN_CURATED,
    GT_PENDING,
    REVIEW_APPROVE_AS_SCENARIO,
    REVIEW_REJECT_NO_CLEAR_GT,
    CandidateValidationError,
    HumanReview,
    ScenarioCandidate,
    TurnContext,
    append_candidate,
    apply_human_review,
    build_candidate,
    find_duplicate,
    load_candidates,
    load_reviews,
    sanitize_text,
    summarize,
)


# --- schema / creation -------------------------------------------------------

def test_valid_candidate_creation():
    c = build_candidate(
        raw_text="Čo variť k ryži?", language="sk",
        source_type="SANITIZED_AI_CHAT_FAILURE",
        suspected_failure_family="RECIPE_TO_PRODUCTS",
        entity_state={"ryza": "ALREADY_HAVE"},
    )
    assert c.candidate_id.startswith("rc-")
    assert c.ground_truth_status == GT_PENDING
    assert c.ground_truth_authority is None
    assert c.entity_state == {"ryza": "ALREADY_HAVE"}


def test_required_fields_present():
    with pytest.raises(CandidateValidationError):
        build_candidate(raw_text="", language="sk", source_type="MANUAL_STAFF_REPORT")


def test_unknown_source_type_rejected():
    with pytest.raises(CandidateValidationError):
        build_candidate(raw_text="x", language="sk", source_type="NOT_A_REAL_SOURCE")


def test_unknown_failure_family_rejected():
    with pytest.raises(CandidateValidationError):
        build_candidate(raw_text="x", language="sk", source_type="MANUAL_STAFF_REPORT",
                         suspected_failure_family="NOT_A_REAL_FAMILY")


def test_unknown_entity_state_value_rejected():
    with pytest.raises(CandidateValidationError):
        build_candidate(raw_text="x", language="sk", source_type="MANUAL_STAFF_REPORT",
                         entity_state={"ryza": "NOT_A_REAL_STATE"})


# --- PII sanitization --------------------------------------------------------

def test_pii_sanitization_email_phone_order_name():
    text = ("Dobrý deň, volám sa Jana Nováková, email jana@example.com, "
            "tel 0905123456, objednávka 123456.")
    sanitized, counts = sanitize_text(text)
    assert "jana@example.com" not in sanitized
    assert "0905123456" not in sanitized
    assert "Jana Nováková" not in sanitized
    assert "123456" not in sanitized
    assert counts["email"] >= 1
    assert counts["phone"] >= 1
    assert counts["order_reference"] >= 1
    assert counts["name_like"] >= 1


def test_pii_sanitization_applied_inside_build_candidate():
    c = build_candidate(raw_text="Môj email je test@example.com", language="sk",
                         source_type="MANUAL_STAFF_REPORT")
    assert "test@example.com" not in c.sanitized_query
    assert c.sanitization_counts["email"] == 1


# --- ground-truth governance -------------------------------------------------

def test_ground_truth_status_defaults_to_pending_and_cannot_be_set_at_intake():
    c = build_candidate(raw_text="x", language="sk", source_type="MANUAL_STAFF_REPORT")
    assert c.ground_truth_status == GT_PENDING
    assert c.ground_truth_authority is None
    # build_candidate() has no parameter that can override this - this is
    # the structural enforcement of Section 3 rule 6, not a convention.
    import inspect
    assert "ground_truth_status" not in inspect.signature(build_candidate).parameters
    assert "ground_truth_authority" not in inspect.signature(build_candidate).parameters


@pytest.mark.parametrize("forbidden", sorted(FORBIDDEN_AUTHORITIES))
def test_forbidden_authority_rejected(forbidden):
    with pytest.raises(CandidateValidationError):
        ScenarioCandidate(
            candidate_id="rc-test", source_type="MANUAL_STAFF_REPORT", created_at=0.0,
            language="sk", sanitized_query="q",
            ground_truth_status=GT_HUMAN_CURATED, ground_truth_authority=forbidden,
        )


def test_non_pending_status_requires_trusted_authority():
    with pytest.raises(CandidateValidationError):
        ScenarioCandidate(
            candidate_id="rc-test", source_type="MANUAL_STAFF_REPORT", created_at=0.0,
            language="sk", sanitized_query="q",
            ground_truth_status=GT_HUMAN_CURATED, ground_truth_authority=None,
        )


# --- human review workflow ---------------------------------------------------

def test_human_review_requires_named_reviewer():
    with pytest.raises(CandidateValidationError):
        HumanReview(candidate_id="rc-test", reviewer="", reviewed_at=0.0, decision=REVIEW_REJECT_NO_CLEAR_GT)


def test_human_review_approve_requires_trusted_authority_and_expected_behavior():
    with pytest.raises(CandidateValidationError):
        HumanReview(candidate_id="rc-test", reviewer="alice", reviewed_at=0.0,
                     decision=REVIEW_APPROVE_AS_SCENARIO, authority=None)
    with pytest.raises(CandidateValidationError):
        HumanReview(candidate_id="rc-test", reviewer="alice", reviewed_at=0.0,
                     decision=REVIEW_APPROVE_AS_SCENARIO, authority=GT_HUMAN_CURATED,
                     expected_behavior=None)
    # valid approval
    review = HumanReview(candidate_id="rc-test", reviewer="alice", reviewed_at=0.0,
                          decision=REVIEW_APPROVE_AS_SCENARIO, authority=GT_HUMAN_CURATED,
                          expected_behavior="explain invoice process")
    assert review.decision == REVIEW_APPROVE_AS_SCENARIO


def test_apply_human_review_is_append_only_and_does_not_mutate_candidate(tmp_path):
    c = build_candidate(raw_text="potrebujem faktúru", language="sk", source_type="MANUAL_STAFF_REPORT")
    reviews_path = tmp_path / "reviews.jsonl"
    apply_human_review(c, reviewer="alice", decision=REVIEW_REJECT_NO_CLEAR_GT, path=reviews_path)
    # original candidate object is frozen/unchanged
    assert c.ground_truth_status == GT_PENDING
    loaded = load_reviews(c.candidate_id, path=reviews_path)
    assert len(loaded) == 1
    assert loaded[0]["decision"] == REVIEW_REJECT_NO_CLEAR_GT
    assert loaded[0]["reviewer"] == "alice"


# --- score contamination -----------------------------------------------------

def test_pending_excluded_from_score_by_construction():
    """This module has no function that computes or contributes to a
    benchmark score - a pending candidate literally cannot enter a score
    because no such code path exists here."""
    import app.scenario_candidates as mod
    score_like_names = [n for n in dir(mod) if "score" in n.lower() or "pass_rate" in n.lower()]
    assert score_like_names == []


# --- duplicate detection ------------------------------------------------------

def test_duplicate_detection_exact_text(tmp_path):
    path = tmp_path / "candidates.jsonl"
    c1 = build_candidate(raw_text="Čo variť k ryži?", language="sk", source_type="MANUAL_STAFF_REPORT")
    assert append_candidate(c1, path=path) is None
    c2 = build_candidate(raw_text="čo variť k ryži?  ", language="sk", source_type="MANUAL_STAFF_REPORT")
    dup = append_candidate(c2, path=path)
    assert dup is not None
    assert dup.candidate_id == c1.candidate_id
    # still only one line written
    assert len(load_candidates(path)) == 1


def test_different_text_not_flagged_as_duplicate(tmp_path):
    path = tmp_path / "candidates.jsonl"
    c1 = build_candidate(raw_text="Čo variť k ryži?", language="sk", source_type="MANUAL_STAFF_REPORT")
    c2 = build_candidate(raw_text="potrebujem faktúru", language="sk", source_type="MANUAL_STAFF_REPORT")
    assert append_candidate(c1, path=path) is None
    assert append_candidate(c2, path=path) is None
    assert find_duplicate(c2, [c1]) is None
    assert len(load_candidates(path)) == 2


# --- multi-turn / entity-state serialization --------------------------------

def test_multi_turn_serialization_round_trip():
    turns = (
        TurnContext(turn_index=0, speaker="customer", sanitized_text="Mám ryžu, čo s ňou?",
                    state_before=None, state_after={"ryza": "ALREADY_HAVE"}),
        TurnContext(turn_index=1, speaker="advisor", sanitized_text="[observed answer]",
                    state_before={"ryza": "ALREADY_HAVE"}, state_after={"ryza": "ALREADY_HAVE"}),
    )
    c = build_candidate(raw_text="Mám ryžu, čo s ňou?", language="sk", source_type="MANUAL_STAFF_REPORT",
                         conversation_context=turns, entity_state={"ryza": "ALREADY_HAVE"})
    d = c.to_dict()
    restored = ScenarioCandidate.from_dict(d)
    assert len(restored.conversation_context) == 2
    assert restored.conversation_context[0].state_after == {"ryza": "ALREADY_HAVE"}
    assert restored.entity_state == {"ryza": "ALREADY_HAVE"}


def test_already_have_field_serialization_round_trip():
    c = build_candidate(raw_text="Mám tofu, čo s ním uvarím?", language="sk",
                         source_type="MANUAL_STAFF_REPORT",
                         entity_state={"tofu": "ALREADY_HAVE"})
    restored = ScenarioCandidate.from_dict(json.loads(json.dumps(c.to_dict(), ensure_ascii=False)))
    assert restored.entity_state == {"tofu": "ALREADY_HAVE"}


# --- summarize() --------------------------------------------------------------

def test_summarize_counts(tmp_path):
    cpath = tmp_path / "candidates.jsonl"
    rpath = tmp_path / "reviews.jsonl"
    c1 = build_candidate(raw_text="a", language="sk", source_type="MANUAL_STAFF_REPORT",
                          suspected_failure_family="INVOICE_SUPPORT", risk_level="HIGH")
    c2 = build_candidate(raw_text="b", language="en", source_type="MANUAL_STAFF_REPORT",
                          suspected_failure_family="ALREADY_HAVE", risk_level="NORMAL")
    append_candidate(c1, path=cpath)
    append_candidate(c2, path=cpath)
    apply_human_review(c1, reviewer="alice", decision=REVIEW_APPROVE_AS_SCENARIO,
                        authority=GT_HUMAN_CURATED, expected_behavior="x", path=rpath)
    summary = summarize(path=cpath, reviews_path=rpath)
    assert summary["total_candidates"] == 2
    assert summary["approved"] == 1
    assert summary["pending"] == 1
    assert summary["by_language"] == {"sk": 1, "en": 1}


# --- CLI ----------------------------------------------------------------------

def test_cli_creates_pending_candidate(tmp_path):
    out_path = tmp_path / "candidates.jsonl"
    result = subprocess.run(
        [sys.executable, "scripts/add_learning_candidate.py",
         "--text", "Potrebujem faktúru k poslednej objednávke.",
         "--source-type", "SANITIZED_AI_CHAT_FAILURE",
         "--failure-family", "INVOICE_SUPPORT",
         "--expected-behavior", "explain how to obtain an invoice",
         "--forbidden-behavior", "product_cards",
         "--candidates-path", str(out_path)],
        capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent,
    )
    assert result.returncode == 0, result.stderr
    assert "GROUND_TRUTH_PENDING" in result.stdout
    candidates = load_candidates(out_path)
    assert len(candidates) == 1
    assert candidates[0].ground_truth_status == GT_PENDING
    assert candidates[0].suspected_failure_family == "INVOICE_SUPPORT"


def test_cli_rejects_invalid_source_type(tmp_path):
    out_path = tmp_path / "candidates.jsonl"
    result = subprocess.run(
        [sys.executable, "scripts/add_learning_candidate.py",
         "--text", "x", "--source-type", "NOT_REAL", "--candidates-path", str(out_path)],
        capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent,
    )
    assert result.returncode != 0
