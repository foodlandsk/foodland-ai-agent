"""
app/evaluation/loader.py  -  V2.10 golden dataset loading

Reads plain JSON under eval/golden/ (Section 54 - human reviewable) into
typed GoldenCase/ConversationCase objects. No network, no catalog access -
pure file I/O + parsing, safe to unit test in isolation.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.evaluation.schema import ConversationCase, ConversationTurn, GoldenCase

EVAL_ROOT = Path(__file__).resolve().parents[2] / "eval"
GOLDEN_DIR = EVAL_ROOT / "golden"
CONVERSATIONS_DIR = EVAL_ROOT / "conversations"
BASELINES_DIR = EVAL_ROOT / "baselines"
REPORTS_DIR = EVAL_ROOT / "reports"


def _case_from_dict(raw: dict) -> GoldenCase:
    return GoldenCase(
        id=raw["id"],
        query=raw["query"],
        query_type=raw["query_type"],
        language=raw.get("language", "sk"),
        limit=raw.get("limit", 8),
        expected_concept_ids=tuple(raw.get("expected_concept_ids", ())),
        must_not_concept_ids=tuple(raw.get("must_not_concept_ids", ())),
        must_include_title_substrings=tuple(raw.get("must_include_title_substrings", ())),
        must_not_include_title_substrings=tuple(raw.get("must_not_include_title_substrings", ())),
        must_not_be_first_title_substrings=tuple(raw.get("must_not_be_first_title_substrings", ())),
        expected_answer_include=tuple(raw.get("expected_answer_include", ())),
        max_products=raw.get("max_products"),
        min_relevant_count=raw.get("min_relevant_count", 0),
        expected_workflow=raw.get("expected_workflow"),
        expected_intent=raw.get("expected_intent"),
        critical=raw.get("critical", False),
        note=raw.get("note", ""),
        source=raw.get("source", "golden"),
    )


def load_golden_file(path: Path) -> list[GoldenCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [_case_from_dict(raw) for raw in payload.get("cases", [])]


def load_all_golden_cases(golden_dir: Path = GOLDEN_DIR) -> list[GoldenCase]:
    """Deterministic ordering (Section 102) - sorted by filename then by
    case id within each file, never dict/filesystem iteration order."""
    cases: list[GoldenCase] = []
    for path in sorted(golden_dir.glob("*.json")):
        cases.extend(load_golden_file(path))
    cases.sort(key=lambda case: case.id)
    _assert_unique_ids(cases)
    return cases


def _assert_unique_ids(cases: list[GoldenCase]) -> None:
    seen: dict[str, int] = {}
    for case in cases:
        seen[case.id] = seen.get(case.id, 0) + 1
    duplicates = [case_id for case_id, count in seen.items() if count > 1]
    if duplicates:
        raise ValueError(f"Duplicate golden case ids: {duplicates}")


def _turn_from_dict(raw: dict) -> ConversationTurn:
    return ConversationTurn(
        message=raw["message"],
        expected_workflow=raw.get("expected_workflow"),
        expected_intent=raw.get("expected_intent"),
        expected_response_mode=raw.get("expected_response_mode"),
        expected_active_recipe_id=raw.get("expected_active_recipe_id"),
        expected_servings=raw.get("expected_servings"),
        expected_context_switch=raw.get("expected_context_switch"),
        expected_reference_resolved_from_previous_index=raw.get("expected_reference_resolved_from_previous_index"),
        expected_products_nonempty=raw.get("expected_products_nonempty"),
        expected_recipe_plan_present=raw.get("expected_recipe_plan_present"),
        note=raw.get("note", ""),
    )


def _conversation_from_dict(raw: dict) -> ConversationCase:
    return ConversationCase(
        id=raw["id"],
        session_id_prefix=raw.get("session_id_prefix", raw["id"]),
        turns=tuple(_turn_from_dict(t) for t in raw["turns"]),
        note=raw.get("note", ""),
        critical=raw.get("critical", False),
    )


def load_conversation_file(path: Path) -> list[ConversationCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [_conversation_from_dict(raw) for raw in payload.get("cases", [])]


def load_all_conversation_cases(conversations_dir: Path = CONVERSATIONS_DIR) -> list[ConversationCase]:
    cases: list[ConversationCase] = []
    for path in sorted(conversations_dir.glob("*.json")):
        cases.extend(load_conversation_file(path))
    cases.sort(key=lambda case: case.id)
    return cases
