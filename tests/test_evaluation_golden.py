"""
tests/test_evaluation_golden.py  -  Sprint V2.10 critical suite, integrated
into the regular pytest run (Section 44/107) against the REAL committed
data/products.json fixture (same convention as tests/test_cross_sell.py
and friends - deterministic, no network, Section 45).

This does NOT replace scripts/run_evaluation.py (the CI quality-gate step
uses that directly for its richer report output) - it's a second,
cheaper tripwire so `pytest tests/ -q` alone already catches a critical
regression, without anyone having to remember to run the eval CLI
separately.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.adapter import get_taxonomy_index, make_chat_fn, make_session_chat_fn
from app.evaluation.baseline import (
    GATE_FAIL,
    aggregate_results,
    evaluate_quality_gates,
    load_baseline,
)
from app.evaluation.conversation import run_conversation_suite
from app.evaluation.loader import BASELINES_DIR, load_all_conversation_cases, load_all_golden_cases
from app.evaluation.runner import run_golden_suite
from app.evaluation.taxonomy_quality import taxonomy_coverage, taxonomy_precision_against_golden


def test_critical_suite_gate_does_not_fail():
    all_golden = load_all_golden_cases()
    all_conversations = load_all_conversation_cases()
    critical_golden = [c for c in all_golden if c.critical]
    critical_conversations = [c for c in all_conversations if c.critical]

    taxonomy_index = get_taxonomy_index()
    chat_fn = make_chat_fn()
    golden_results = run_golden_suite(critical_golden, lambda q, limit: chat_fn(q, limit), taxonomy_index)

    session_chat_fn = make_session_chat_fn()
    conversation_results = run_conversation_suite(critical_conversations, session_chat_fn)

    tax_stats = taxonomy_coverage(taxonomy_index)
    tax_stats.update(taxonomy_precision_against_golden(all_golden, taxonomy_index))
    summary = aggregate_results(golden_results, conversation_results, tax_stats)

    baseline_path = BASELINES_DIR / "v2.9.json"
    baseline = load_baseline(baseline_path) if baseline_path.exists() else None
    critical_ids = frozenset(c.id for c in critical_golden) | frozenset(c.id for c in critical_conversations)

    gates = evaluate_quality_gates(summary, baseline, critical_ids)
    assert gates["gate"] != GATE_FAIL, gates["blocking_reasons"]
