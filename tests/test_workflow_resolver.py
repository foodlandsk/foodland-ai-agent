"""
tests/test_workflow_resolver.py  -  V2.13b: WorkflowResolver precedence,
tested in isolation by feeding constructed TurnAnalysis objects directly
(Section 108) - no search, no retrieval, no app.main involved.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.turn_resolver import TurnAnalysis
from app.workflow_resolver import (
    WORKFLOW_ALLERGEN_SAFETY,
    WORKFLOW_LEGACY_FALLBACK,
    WORKFLOW_RELATED_PRODUCTS,
    WORKFLOW_RESULTSET_CONTINUATION,
    resolve_workflow,
)


class TestResultSetContinuationTopPrecedence:
    def test_active_continuation_wins_over_everything_else(self):
        analysis = TurnAnalysis(
            active_result_set_continuation=True,
            safety_intent="sóju",
            related_products_requested=True,
            related_products_anchor="sushi",
        )
        resolution = resolve_workflow(analysis)
        assert resolution.workflow_id == WORKFLOW_RESULTSET_CONTINUATION
        assert resolution.fallback_used is False


class TestSafetyPrecedence:
    def test_safety_intent_alone_resolves_allergen_safety(self):
        analysis = TurnAnalysis(safety_intent="sóju")
        resolution = resolve_workflow(analysis)
        assert resolution.workflow_id == WORKFLOW_ALLERGEN_SAFETY
        assert resolution.confidence == "HIGH"

    def test_safety_outranks_related_products_conflict(self):
        """Conflict matrix (Section 71): SAFETY + PRODUCT_ENTITY /
        RELATED_PRODUCTS_REQUESTED must resolve to safety."""
        analysis = TurnAnalysis(
            safety_intent="sóju",
            related_products_requested=True,
            related_products_anchor="sojova_omacka",
        )
        resolution = resolve_workflow(analysis)
        assert resolution.workflow_id == WORKFLOW_ALLERGEN_SAFETY

    def test_no_safety_intent_never_resolves_allergen_safety(self):
        """Control (Section 75/76): a plain product mention must not
        become safety merely because the resolver ran."""
        analysis = TurnAnalysis(safety_intent=None, related_products_anchor="sojova_omacka")
        resolution = resolve_workflow(analysis)
        assert resolution.workflow_id != WORKFLOW_ALLERGEN_SAFETY


class TestRelatedProductsPrecedence:
    def test_explicit_action_with_anchor_resolves_related_products(self):
        analysis = TurnAnalysis(related_products_requested=True, related_products_anchor="sushi")
        resolution = resolve_workflow(analysis)
        assert resolution.workflow_id == WORKFLOW_RELATED_PRODUCTS
        assert resolution.reason == "EXPLICIT_ACTION_INTENT"

    def test_requested_without_anchor_does_not_resolve_related_products(self):
        analysis = TurnAnalysis(related_products_requested=True, related_products_anchor=None)
        resolution = resolve_workflow(analysis)
        assert resolution.workflow_id != WORKFLOW_RELATED_PRODUCTS

    def test_anchor_without_explicit_action_does_not_resolve_related_products(self):
        """Control (Section 74/77): a bare product/family anchor alone
        (no explicit companion-language) must remain ordinary search."""
        analysis = TurnAnalysis(related_products_requested=False, related_products_anchor="sushi")
        resolution = resolve_workflow(analysis)
        assert resolution.workflow_id != WORKFLOW_RELATED_PRODUCTS


class TestLegacyFallback:
    def test_empty_analysis_falls_back(self):
        resolution = resolve_workflow(TurnAnalysis())
        assert resolution.workflow_id == WORKFLOW_LEGACY_FALLBACK
        assert resolution.fallback_used is True
        assert resolution.confidence == "LOW"


class TestResolutionEvidence:
    def test_resolution_carries_evidence_for_debugging(self):
        analysis = TurnAnalysis(
            safety_intent="sóju",
            evidence=("allergen_term='sóju'", "allergen_product_query_explicit_zero_result"),
        )
        resolution = resolve_workflow(analysis)
        assert resolution.evidence == analysis.evidence
