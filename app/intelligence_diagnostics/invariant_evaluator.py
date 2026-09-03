"""
app/intelligence_diagnostics/invariant_evaluator.py  -  V2.18a deterministic
semantic-contract checker for CURATED/REAL_CUSTOMER_QA/SAFE_MUTATION
scenarios.

WHY THIS EXISTS SEPARATELY FROM app.evaluation.runner: EXISTING_GOLDEN/
REGRESSION_BUG-sourced scenarios wrap a real GoldenCase and are scored
by the proven, unchanged app.evaluation.runner.run_golden_case() engine
(concept_id/title-substring based - see scenario_registry.py). New
scenarios authored directly for V2.18 (Section 17: "prefer semantic
contracts over exact answer strings") do not carry a catalog-specific
concept_id list - they carry small, human-readable invariant strings
from a FIXED, deterministic vocabulary. This module is the evaluator for
that vocabulary only - it never asks an LLM, never invents a new scoring
dimension, and reuses the SAME structural checks app.customer_qa already
proved live (cross-sell separation, stock wording, prompt-leak
detection) so V2.18's notion of "correct" stays consistent with V2.17's.
"""
from __future__ import annotations

_STOCK_MARKERS = ("skladom", "potvrdena skladova zasoba", "overena dostupnost na sklade")


def _lower(text) -> str:
    return str(text or "").lower()


def check_invariant(invariant: str, response: dict) -> tuple[bool, str]:
    """Returns (passed, reason). `reason` is always populated so a FAIL
    is never opaque (Section 15 - machine-verifiable evidence plus a
    concise human explanation)."""
    if invariant == "products_nonempty":
        products = response.get("products") or []
        return bool(products), f"products_nonempty: {len(products)} product(s) returned"

    if invariant == "products_empty":
        # V2.18d.1 - the honest-abstention counterpart to products_nonempty.
        # A max_products=0 golden/regression case (e.g. allergen_safety/faq/
        # recipe intents where recommending a product would be unsafe or
        # simply wrong) has EMPTY products as its correct, safe behavior -
        # scoring it against products_nonempty would flag correct abstention
        # as a failure (see docs/intelligence-diagnostic-loop-v2.18.1.md).
        products = response.get("products") or []
        return not products, f"products_empty: {len(products)} product(s) returned (expected 0)"

    if invariant == "answer_nonempty":
        answer = str(response.get("answer") or "").strip()
        return bool(answer), f"answer_nonempty: {len(answer)} char(s)"

    if invariant == "cross_sell_separate":
        product_ids = {p.get("id") for p in (response.get("products") or []) if p.get("id")}
        cross_sell_ids = {p.get("id") for p in (response.get("cross_sell") or []) if p.get("id")}
        overlap = product_ids & cross_sell_ids
        return not overlap, f"cross_sell_separate: overlap={sorted(overlap)}"

    if invariant == "no_stock_certainty_claim":
        answer_lower = _lower(response.get("answer"))
        hit = next((m for m in _STOCK_MARKERS if m in answer_lower), None)
        return hit is None, f"no_stock_certainty_claim: forbidden_marker={hit!r}"

    if invariant == "no_prompt_leak":
        from app.knowledge import _is_broken_curation_placeholder

        answer = str(response.get("answer") or "")
        leaked = _is_broken_curation_placeholder(answer)
        return not leaked, f"no_prompt_leak: leaked={leaked}"

    if invariant.startswith("intent=="):
        expected = invariant.split("==", 1)[1]
        actual = response.get("intent")
        return actual == expected, f"intent=={expected!r}: actual={actual!r}"

    if invariant.startswith("workflow=="):
        expected = invariant.split("==", 1)[1]
        actual = response.get("workflow_id")
        return actual == expected, f"workflow=={expected!r}: actual={actual!r}"

    if invariant.startswith("answer_contains:"):
        needle = invariant.split(":", 1)[1]
        answer_lower = _lower(response.get("answer"))
        present = needle.lower() in answer_lower
        return present, f"answer_contains:{needle!r}: present={present}"

    if invariant.startswith("answer_must_not_contain:"):
        needle = invariant.split(":", 1)[1]
        answer_lower = _lower(response.get("answer"))
        present = needle.lower() in answer_lower
        return not present, f"answer_must_not_contain:{needle!r}: present={present}"

    return False, f"UNKNOWN_INVARIANT: {invariant!r} has no registered evaluator"


def evaluate_invariants(invariants: tuple[str, ...], response: dict) -> tuple[bool, list[str], list[str]]:
    """Returns (all_passed, failed_invariants, reasons)."""
    failed: list[str] = []
    reasons: list[str] = []
    for invariant in invariants:
        passed, reason = check_invariant(invariant, response)
        reasons.append(reason)
        if not passed:
            failed.append(invariant)
    return not failed, failed, reasons
