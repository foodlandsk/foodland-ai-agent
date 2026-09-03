"""
app/intelligence_diagnostics/real_customer_qa_bridge.py  -  V2.18a
Section 23: REAL CUSTOMER QA -> SCENARIO CANDIDATE.

A genuine V2.17.2 QA finding may suggest "we should permanently test
this customer situation." This module converts one finding into a
sanitized Scenario CANDIDATE - it NEVER copies the historical AI answer
as expected output (Section 4/23 hard guard), and NEVER copies raw
identifiers (the finding is already sanitized by app.customer_audit/
app.customer_qa - conversation_hash only, never session_id/client_id/IP).

Ground-truth resolution (Section 23):
  - If the finding's rule_id maps to a registered V2.17.3 contract
    (app.customer_qa_reproduction._CONTRACT_REGISTRY), the candidate is
    SCORED with ground_truth_authority=VERIFIED_REPRODUCTION_CONTRACT -
    but the expected_invariants are narrowly scoped to ONLY the specific
    contract that was actually violated (e.g. "cross_sell_separate"),
    never a broader claim about what the "correct" answer should have
    been (Section 5.E: "may establish the violated invariant, but NOT
    arbitrary broader semantic truth").
  - Otherwise the candidate is GROUND_TRUTH_PENDING - visible in
    diagnostic reports, reviewable by a human, but never scored, never
    PASS, never FAIL (Section 6).
"""
from __future__ import annotations

from app.intelligence_diagnostics.scenario_schema import (
    AUTHORITY_VERIFIED_REPRODUCTION_CONTRACT,
    GROUND_TRUTH_PENDING,
    GROUND_TRUTH_SCORED,
    Scenario,
    ScenarioTurn,
    SOURCE_REAL_CUSTOMER_QA,
)

# rule_id -> the one invariant string (app.intelligence_diagnostics.
# invariant_evaluator vocabulary) that rule's contract actually proves -
# deliberately narrow, mirrors app.customer_qa_reproduction._CONTRACT_REGISTRY
# 1:1 but expressed in the invariant_evaluator's own small vocabulary
# rather than importing the reproduction module's Python objects (kept
# decoupled - this bridge only needs to know WHICH single fact a rule
# proves, not how to re-run it).
_RULE_TO_INVARIANT = {
    "QA_STRUCT_001": "cross_sell_separate",
    "QA_STOCK_001": "no_stock_certainty_claim",
    "QA_TRUST_001": "no_prompt_leak",
}


def finding_to_scenario_candidate(finding: dict) -> Scenario:
    """`finding` is a V2.17.2 app.customer_qa finding dict (already
    sanitized - conversation_hash, redacted question/answer excerpt,
    classification, rule_id). Never accepts or copies session_id/
    client_id/IP/conversation_history - those never appear in a V2.17.2
    finding in the first place (Section 4 of docs/customer-conversation-
    audit-api-v2.17.1.md)."""
    evidence = finding.get("evidence") or {}
    question = str(evidence.get("question") or "").strip()
    if not question:
        question = "(no retained question text)"

    rule_id = finding.get("rule_id")
    invariant = _RULE_TO_INVARIANT.get(rule_id)
    scenario_id = f"v218_customer_qa_{finding.get('qa_id', 'unknown')}"

    if invariant is not None:
        return Scenario(
            scenario_id=scenario_id,
            source=SOURCE_REAL_CUSTOMER_QA,
            capability=finding.get("classification") or "OUT_OF_DOMAIN",
            turns=(ScenarioTurn(message=question),),
            ground_truth_status=GROUND_TRUTH_SCORED,
            ground_truth_authority=AUTHORITY_VERIFIED_REPRODUCTION_CONTRACT,
            ground_truth_reason=(
                f"V2.17.3-verified reproduction contract for rule_id={rule_id!r} - "
                "narrowly scoped to the one proven invariant, not the full historical answer."
            ),
            expected_invariants=(invariant,),
            provenance=f"real customer QA finding qa_id={finding.get('qa_id')}, conversation_hash={finding.get('conversation_hash')}",
            underlying_case_id=finding.get("qa_id"),
        )

    return Scenario(
        scenario_id=scenario_id,
        source=SOURCE_REAL_CUSTOMER_QA,
        capability=finding.get("classification") or "OUT_OF_DOMAIN",
        turns=(ScenarioTurn(message=question),),
        ground_truth_status=GROUND_TRUTH_PENDING,
        ground_truth_authority=None,
        ground_truth_reason=(
            f"No registered contract for rule_id={rule_id!r} - requires human curation before "
            "this candidate can become scored ground truth (Section 6/7)."
        ),
        provenance=f"real customer QA finding qa_id={finding.get('qa_id')}, conversation_hash={finding.get('conversation_hash')}",
        underlying_case_id=finding.get("qa_id"),
    )
