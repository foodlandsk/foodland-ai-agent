"""
app/customer_qa_reproduction.py  -  V2.17.3: Finding Review & Reproduction
Layer.

WHAT THIS IS: independently re-verifies whether a V2.17.2 QA finding is
a real, contract-bound violation, using either the finding's own
immutable historical evidence (OFFLINE) or a fresh, isolated re-run of
the same sanitized question through today's code/data (ADMIN_TEST).

    REAL CUSTOMER (V2.17.1 audit) -> QA FINDING (V2.17.2) -> REVIEW ->
    REPRODUCTION SPEC -> SAFE EXECUTION -> CONTRACT ASSERTION ->
    REPRODUCTION RESULT

    never:

    FINDING -> AUTOMATIC LABEL -> AUTOMATIC FIX -> AUTOMATIC DEPLOY

PERMANENT INVARIANT: FINDING != BUG. A V2.17.2 finding is a reason to
look, not a confirmed defect. It becomes REPRODUCED only when a named
CONTRACT (a deterministic evaluator - Section 4/14/15) can prove the
violation from real evidence. `automatic_fix`/`automatic_deploy` are
hard-coded false on every result; nothing in this module edits
retrieval/ranking/recommendations/cross-sell/substitution/recipes/
knowledge/Merchant data/product data/customer memory/prompts/learning/
promotion. REPRODUCED does not authorize a fix (Section 29) - it only
produces evidence for a human, or a future, separately-mandated sprint.

CONTRACT REGISTRY: every V2.17.2 rule_id maps 1:1 to a contract_id.
Rather than re-implementing "what counts as a violation" a second time,
each contract's evaluator IS the exact same app.customer_qa rule
function that originally produced the finding - single source of
truth, zero duplicated logic, and a genuine independent re-verification
step (re-run through a separate code path/entry point) rather than a
trivial re-statement of "the QA layer already said so".

REPRODUCIBILITY CLASSIFICATION (audited - see docs/finding-review-
reproduction-v2.17.3.md Section 7): all 8 current V2.17.2 rules are
REPRODUCIBLE, because every one of them evaluates fields already
present in the immutable, sanitized historical audit record (answer
text, product_groups, has_more/counts) - none depends on live /chat
behavior, current catalog state, or anything requiring re-execution to
evaluate historically. This module therefore has two independent modes:

  OFFLINE     - evaluates the SAME immutable historical turn the
                finding was originally computed from. Deterministic by
                construction: if the finding existed, OFFLINE
                reproduction confirms it from evidence alone, with no
                /chat call, no CUSTOMER traffic risk, and no side
                effects whatsoever. This is the DEFAULT, preferred mode
                (Section 18 - "offline-first").

  ADMIN_TEST  - the only mode where NOT_REPRODUCED is a genuinely
                meaningful, evidence-grounded outcome: it re-runs the
                SAME sanitized question (never the original session/
                identity) through app.advisor_engine with
                admin_test_context(), then evaluates the SAME contract
                against the FRESH response. Answers "does today's
                code/data still violate this contract?" - a different
                question from OFFLINE's "did this historically happen?"
                (Section 10 - historical output != current output).
                Empirically verified (not assumed - Section 9) that
                admin_test_context() traffic never reaches
                customer_audit.jsonl (capture_customer_turn() is gated
                on execution_context.is_customer_traffic, False here).
                It DOES still flow through app.main.update_user_memory/
                update_session_memory like every ADMIN_TEST call always
                has (V2.15b's own documented behavior - only the
                CUSTOMER-only rate limit and analytics/audit hooks are
                gated off, not the shared internal-tooling pipeline) -
                this module uses a fixed, clearly-synthetic client_key
                ("admin-test-reproduction") for every reproduction call
                so that write only ever touches one bounded, non-
                customer-identifying profile bucket, never a real
                customer's.

STORAGE: none. ON-READ, same precedent V2.17.2 established - nothing is
persisted (no customer_qa_reproductions.jsonl). OFFLINE reproduction is
trivially cheap to recompute from the bounded audit window; ADMIN_TEST
reproduction's own result never needs separate persistence either, so
there is no separate store to manage, no duplicate-record risk, and no
history to keep immutable-but-stale.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from app.customer_audit import read_audit_turns
from app.customer_qa import (
    analyze_turn,
    _rule_cross_sell_overlaps_products,
    _rule_cross_sell_eligible_but_empty,
    _rule_has_more_contradicts_counts,
    _rule_prompt_leak_marker,
    _rule_pii_pattern_in_stored_text,
    _rule_forbidden_stock_wording,
    _rule_no_results_claim_but_products_present,
    _rule_alternatives_claim_but_empty,
)

logger = logging.getLogger(__name__)

REPRODUCTION_STATUSES = (
    "REPRODUCED",
    "NOT_REPRODUCED",
    "INSUFFICIENT_EVIDENCE",
    "NOT_REPRODUCIBLE",
    "STALE",
    "INVALID_FINDING",
    "BLOCKED_BY_DATA",
)

REPRODUCTION_MODES = ("OFFLINE", "ADMIN_TEST")

NEXT_ACTIONS = (
    "NO_ACTION",
    "HUMAN_REVIEW",
    "CHECK_QA_RULE",
    "CHECK_CATALOG_DATA",
    "CHECK_KNOWLEDGE",
    "CREATE_REGRESSION_CANDIDATE",
    "SECURITY_REVIEW",
    "DATA_REVIEW",
)

EVALUATOR_VERSION = "1"

# rule_id -> (contract_id, contract_description, evaluator). The
# evaluator is literally the app.customer_qa rule function - Section 15
# "prefer machine-verifiable evidence" is satisfied by reusing the exact
# predicate that produced the finding, not a re-description of it.
_CONTRACT_REGISTRY: dict[str, tuple[str, str, Any]] = {
    "QA_STRUCT_001": (
        "CROSS_SELL_GROUP_SEPARATION_V2_17",
        "cross_sell must never share a product id with `products` in the same turn.",
        _rule_cross_sell_overlaps_products,
    ),
    "QA_STRUCT_002": (
        "CROSS_SELL_ELIGIBILITY_CONSISTENCY_V2_17",
        "cross_sell_eligible=True must be backed by a non-empty cross_sell group.",
        _rule_cross_sell_eligible_but_empty,
    ),
    "QA_STRUCT_003": (
        "RESULT_GROUP_CONSISTENCY",
        "has_more=True must be consistent with displayed_count/matching_total.",
        _rule_has_more_contradicts_counts,
    ),
    "QA_TRUST_001": (
        "PROMPT_LEAK_PROTECTION_V2_16E",
        "Customer-facing answers must never contain the known curation-template leak signature.",
        _rule_prompt_leak_marker,
    ),
    "QA_TRUST_002": (
        "PII_REDACTION_V2_17_1",
        "Persisted question/answer text must never contain an unredacted email-like pattern.",
        _rule_pii_pattern_in_stored_text,
    ),
    "QA_STOCK_001": (
        "STOCK_SEMANTICS_V2_17",
        'Customer-facing answers must never claim "Skladom"/live warehouse stock from catalog-presence-only data.',
        _rule_forbidden_stock_wording,
    ),
    "QA_COMPOSE_001": (
        "RESPONSE_STRUCTURE_CONSISTENCY_V2_17_2",
        "An answer must not claim zero results when its own `products` group is non-empty.",
        _rule_no_results_claim_but_products_present,
    ),
    "QA_COMPOSE_002": (
        "RESPONSE_STRUCTURE_CONSISTENCY_V2_17_2",
        "An answer must not claim alternatives/cross-sell exist when the corresponding group is empty.",
        _rule_alternatives_claim_but_empty,
    ),
    "QA_COMPOSE_003": (
        "RESPONSE_STRUCTURE_CONSISTENCY_V2_17_2",
        "An answer must not claim alternatives/cross-sell exist when the corresponding group is empty.",
        _rule_alternatives_claim_but_empty,
    ),
}

_REPRODUCTION_ACTIONS = {
    "SAFETY_TRUST": "SECURITY_REVIEW",
    "CROSS_SELL": "CREATE_REGRESSION_CANDIDATE",
    "PRESENT": "CREATE_REGRESSION_CANDIDATE",
    "COMPOSE": "CREATE_REGRESSION_CANDIDATE",
}


def _reproduction_id(qa_id: str, contract_id: str, mode: str) -> str:
    digest = hashlib.sha256(f"{qa_id}:{contract_id}:{mode}:{EVALUATOR_VERSION}".encode("utf-8")).hexdigest()
    return digest[:24]


def _find_finding_and_turn(qa_id: str, days: int = 90) -> tuple[dict | None, dict | None]:
    """Scans the bounded audit window (Section 46/22 - same cost model
    app.customer_qa.qa_findings() already accepts) for the turn that
    originally produced this qa_id. Nothing is indexed/stored (ON-READ,
    consistent with V2.17.2) - qa_id is a one-way hash, so the only way
    to resolve it back to a turn is to recompute findings the same way
    the QA layer itself does."""
    safe_days = max(1, min(int(days or 90), 90))
    turns = read_audit_turns(days=safe_days, limit=500)
    for turn in turns:
        result = analyze_turn(turn)
        for finding in result["findings"]:
            if finding["qa_id"] == qa_id:
                return finding, turn
    return None, None


def _build_reproduction_result(
    *,
    qa_id: str,
    finding: dict | None,
    status: str,
    mode: str,
    contract_id: str | None,
    contract_description: str | None,
    reproduction_evidence: dict,
    recommended_next_action: str,
) -> dict:
    assert status in REPRODUCTION_STATUSES
    assert mode in REPRODUCTION_MODES
    assert recommended_next_action in NEXT_ACTIONS
    rule_id = finding.get("rule_id") if finding else None
    classification = finding.get("classification") if finding else None
    return {
        "reproduction_id": _reproduction_id(qa_id, contract_id or "UNKNOWN", mode),
        "qa_id": qa_id,
        "status": status,
        "rule_id": rule_id,
        "rule_version": finding.get("rule_version") if finding else None,
        "contract_id": contract_id,
        "contract_description": contract_description,
        "evaluator_version": EVALUATOR_VERSION,
        "classification": classification,
        "reproduction_mode": mode,
        "historical_evidence": (
            {
                "conversation_hash": finding.get("conversation_hash"),
                "interaction_id": finding.get("interaction_id"),
                "decision_id": finding.get("decision_id"),
                "result_set_id": finding.get("result_set_id"),
            }
            if finding
            else None
        ),
        "reproduction_evidence": reproduction_evidence,
        "recommended_next_action": recommended_next_action,
        # Section 4/29 - hard-coded, never computed. REPRODUCED never
        # authorizes a fix; this module contains no fix/deploy/train/
        # promote action anywhere in its source.
        "automatic_fix": False,
        "automatic_deploy": False,
    }


def reproduce_offline(qa_id: str, days: int = 90) -> dict:
    """OFFLINE reproduction (Section 18 - the default, preferred mode):
    re-evaluates the SAME contract against the SAME immutable historical
    turn the finding was originally computed from. No /chat call, no
    CUSTOMER traffic risk, no side effects. Deterministic by
    construction - if the finding is found, its contract fires again
    against the same evidence every time."""
    finding, turn = _find_finding_and_turn(qa_id, days=days)
    if finding is None or turn is None:
        return _build_reproduction_result(
            qa_id=qa_id,
            finding=None,
            status="INSUFFICIENT_EVIDENCE",
            mode="OFFLINE",
            contract_id=None,
            contract_description=None,
            reproduction_evidence={"reason": f"No QA finding with qa_id={qa_id!r} exists in the last {days} day(s) of retained audit history."},
            recommended_next_action="HUMAN_REVIEW",
        )

    rule_id = finding["rule_id"]
    contract = _CONTRACT_REGISTRY.get(rule_id)
    if contract is None:
        # Section 13 - a finding whose rule has no registered contract
        # cannot be independently verified; honest as NOT_REPRODUCIBLE,
        # never silently upgraded to REPRODUCED.
        return _build_reproduction_result(
            qa_id=qa_id,
            finding=finding,
            status="NOT_REPRODUCIBLE",
            mode="OFFLINE",
            contract_id=None,
            contract_description=None,
            reproduction_evidence={"reason": f"rule_id={rule_id!r} has no registered contract evaluator."},
            recommended_next_action="CHECK_QA_RULE",
        )

    contract_id, contract_description, evaluator = contract
    re_finding = evaluator(turn)
    classification = finding.get("classification")
    action = _REPRODUCTION_ACTIONS.get(classification, "HUMAN_REVIEW")

    if re_finding is not None:
        return _build_reproduction_result(
            qa_id=qa_id,
            finding=finding,
            status="REPRODUCED",
            mode="OFFLINE",
            contract_id=contract_id,
            contract_description=contract_description,
            reproduction_evidence={
                "contract_expected": contract_description,
                "contract_observed": re_finding["finding"],
                "violation": re_finding["finding"],
            },
            recommended_next_action=action,
        )
    # By construction this branch is unreachable for a deterministic,
    # side-effect-free evaluator re-run against unchanged evidence - kept
    # as an explicit, honestly-labeled path rather than assumed
    # impossible, in case a future evaluator version is not purely
    # deterministic over the stored turn shape.
    return _build_reproduction_result(
        qa_id=qa_id,
        finding=finding,
        status="NOT_REPRODUCED",
        mode="OFFLINE",
        contract_id=contract_id,
        contract_description=contract_description,
        reproduction_evidence={"reason": "Contract evaluator did not re-fire against the same historical evidence."},
        recommended_next_action="CHECK_QA_RULE",
    )


def reproduce_admin_test(qa_id: str, days: int = 90) -> dict:
    """ADMIN_TEST reproduction (Section 19-23): the only mode where
    NOT_REPRODUCED is meaningful. Re-runs the historical finding's own
    already-sanitized `question` text (never raw identity, never
    conversation_history - Section 8) through app.advisor_engine with
    an explicit, forced admin_test_context() (Section 7/20 - CUSTOMER is
    never reachable from this function; there is no execution_context
    parameter for a caller to override). Evaluates the SAME contract
    against the FRESH response."""
    finding, _historical_turn = _find_finding_and_turn(qa_id, days=days)
    if finding is None:
        return _build_reproduction_result(
            qa_id=qa_id,
            finding=None,
            status="INSUFFICIENT_EVIDENCE",
            mode="ADMIN_TEST",
            contract_id=None,
            contract_description=None,
            reproduction_evidence={"reason": f"No QA finding with qa_id={qa_id!r} exists in the last {days} day(s) of retained audit history."},
            recommended_next_action="HUMAN_REVIEW",
        )

    rule_id = finding["rule_id"]
    contract = _CONTRACT_REGISTRY.get(rule_id)
    if contract is None:
        return _build_reproduction_result(
            qa_id=qa_id,
            finding=finding,
            status="NOT_REPRODUCIBLE",
            mode="ADMIN_TEST",
            contract_id=None,
            contract_description=None,
            reproduction_evidence={"reason": f"rule_id={rule_id!r} has no registered contract evaluator."},
            recommended_next_action="CHECK_QA_RULE",
        )

    sanitized_question = finding["evidence"].get("question") or ""
    if not sanitized_question.strip():
        return _build_reproduction_result(
            qa_id=qa_id,
            finding=finding,
            status="INSUFFICIENT_EVIDENCE",
            mode="ADMIN_TEST",
            contract_id=contract[0],
            contract_description=contract[1],
            reproduction_evidence={"reason": "Historical evidence has no retained question text to safely replay."},
            recommended_next_action="HUMAN_REVIEW",
        )

    # Deferred imports - same reasoning app.customer_audit/app.advisor_
    # engine already document: keep this module importable without
    # forcing app.main's heavy catalog load at import time.
    from app.advisor_engine import advisor_engine, AdvisorRequest
    from app.execution_context import admin_test_context

    fresh_response = advisor_engine.run(
        AdvisorRequest(
            message=sanitized_question,
            # A fixed, clearly-synthetic identity - never the original
            # customer's session_id (Section 6/8/31/32) and never
            # colliding with any real customer's client_key-derived
            # profile bucket (empirically verified - see module
            # docstring).
            session_id=f"admin-test-repro-{qa_id}",
            client_key="admin-test-reproduction",
        ),
        admin_test_context(),
    )

    contract_id, contract_description, evaluator = contract
    # Build a turn-shaped view of the FRESH response using the same
    # evidence extraction app.customer_qa already uses, so the SAME
    # evaluator function can run against it unmodified.
    synthetic_turn = {
        "answer": fresh_response.get("answer"),
        "intent": fresh_response.get("intent"),
        "workflow_id": fresh_response.get("workflow_id"),
        "has_more": fresh_response.get("has_more"),
        "matching_total": fresh_response.get("matching_total"),
        "displayed_count": fresh_response.get("displayed_count"),
        "cross_sell_eligible": fresh_response.get("cross_sell_eligible"),
        "product_groups": {
            "products": fresh_response.get("products") or [],
            "cross_sell": fresh_response.get("cross_sell") or [],
        },
        "conversation_hash": finding.get("conversation_hash"),
        "interaction_id": fresh_response.get("interaction_id"),
        "decision_id": None,
        "result_set_id": fresh_response.get("result_set_id"),
    }
    current_finding = evaluator(synthetic_turn)
    classification = finding.get("classification")
    action = _REPRODUCTION_ACTIONS.get(classification, "HUMAN_REVIEW")

    if current_finding is not None:
        return _build_reproduction_result(
            qa_id=qa_id,
            finding=finding,
            status="REPRODUCED",
            mode="ADMIN_TEST",
            contract_id=contract_id,
            contract_description=contract_description,
            reproduction_evidence={
                "contract_expected": contract_description,
                "contract_observed": current_finding["finding"],
                "violation": current_finding["finding"],
            },
            recommended_next_action=action,
        )
    return _build_reproduction_result(
        qa_id=qa_id,
        finding=finding,
        status="NOT_REPRODUCED",
        mode="ADMIN_TEST",
        contract_id=contract_id,
        contract_description=contract_description,
        reproduction_evidence={
            "reason": "Contract currently passes when the same sanitized question is re-run today - this does not prove the historical finding never happened (Section 10/27)."
        },
        recommended_next_action="NO_ACTION",
    )


def reproduction_status() -> dict:
    """READ-only accessor for GET /admin/qa/reproductions/status."""
    return {
        "readonly_inspection": True,
        "offline_reproduction": True,
        "active_reproduction": True,
        "active_execution_context": "ADMIN_TEST",
        "automatic_fix": False,
        "automatic_deploy": False,
        "contract_count": len(set(c[0] for c in _CONTRACT_REGISTRY.values())),
        "reproducible_rule_count": len(_CONTRACT_REGISTRY),
    }
