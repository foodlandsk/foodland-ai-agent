"""
app/intelligence_diagnostics/synthetic_reproduction.py  -  V2.18c
reproduction for synthetic (benchmark) failures.

Reuses the V2.17.3 principle unchanged (Section 30): contract ->
reproduction -> evidence, never authorizing a fix. For a scenario, this
is simpler than V2.17.3's real-customer case: there is no historical
record to look up by qa_id - the scenario itself IS the reproduction
spec (Section 6 of the V2.17.3 doc's "reproduction spec" concept,
applied here to a benchmark scenario instead of a customer finding). Re-
running it through app.intelligence_diagnostics.benchmark_runner with a
FRESH EVALUATION-context call and re-checking the SAME contract is the
whole mechanism - "reproduced" means "failed again, independently, on a
second run," not "we re-read the first result."

HARD GUARD (Section 31, mirrors V2.17.3 Section 29): REPRODUCED_SYNTHETIC_
FAILURE never authorizes a fix. automatic_fix/automatic_deploy are
hard-coded false on every result. recommended_next_action reuses the
EXACT SAME constrained vocabulary app.customer_qa_reproduction already
established (imported, not duplicated) so V2.18's evidence artifacts and
V2.17.3's stay consistent for a human reading both.
"""
from __future__ import annotations

import hashlib

from app.customer_qa_reproduction import NEXT_ACTIONS
from app.intelligence_diagnostics.benchmark_runner import STATUS_FAIL, ScenarioResult, run_scenario
from app.intelligence_diagnostics.failure_triage import ROOT_CAUSE_UNCERTAIN, classify_likely_layer
from app.intelligence_diagnostics.scenario_schema import Scenario

REPRODUCED_SYNTHETIC_FAILURE = "REPRODUCED_SYNTHETIC_FAILURE"
NOT_REPRODUCED = "NOT_REPRODUCED"

_LAYER_TO_ACTION = {
    "UNDERSTAND": "HUMAN_REVIEW",
    "RETRIEVE": "CHECK_CATALOG_DATA",
    "RANK": "CHECK_QA_RULE",
    "COMPOSE": "HUMAN_REVIEW",
    "GROUND": "CHECK_KNOWLEDGE",
    "PRESENT": "HUMAN_REVIEW",
    "CROSS_SELL": "CREATE_REGRESSION_CANDIDATE",
    "DATA": "CHECK_CATALOG_DATA",
    "SAFETY_TRUST": "SECURITY_REVIEW",
    "FOLLOW_UP": "HUMAN_REVIEW",
    "OTHER_CONTRACT": "HUMAN_REVIEW",
    ROOT_CAUSE_UNCERTAIN: "HUMAN_REVIEW",
}


def _reproduction_id(scenario_id: str, generation_marker: str) -> str:
    return hashlib.sha256(f"{scenario_id}:{generation_marker}".encode("utf-8")).hexdigest()[:24]


def reproduce_synthetic_failure(
    scenario: Scenario,
    *,
    chat_fn,
    session_chat_fn,
    taxonomy_index: dict,
    golden_lookup: dict,
    conversation_lookup: dict,
    git_sha: str = "",
) -> dict:
    """Independently re-runs `scenario` (fresh EVALUATION-context call,
    never CUSTOMER) and re-checks the same contract. Returns a bounded
    evidence dict - never a fix, never a deploy action."""
    result: ScenarioResult = run_scenario(
        scenario,
        chat_fn=chat_fn,
        session_chat_fn=session_chat_fn,
        taxonomy_index=taxonomy_index,
        golden_lookup=golden_lookup,
        conversation_lookup=conversation_lookup,
    )
    likely_layer = classify_likely_layer(result) if result.status == STATUS_FAIL else None
    status = REPRODUCED_SYNTHETIC_FAILURE if result.status == STATUS_FAIL else NOT_REPRODUCED
    action = _LAYER_TO_ACTION.get(likely_layer, "HUMAN_REVIEW") if likely_layer else "NO_ACTION"
    assert action in NEXT_ACTIONS

    return {
        "reproduction_id": _reproduction_id(scenario.scenario_id, git_sha),
        "scenario_id": scenario.scenario_id,
        "status": status,
        "capability": scenario.capability,
        "likely_layer": likely_layer,
        "observed_error_buckets": list(result.error_buckets),
        "observed_reasons": list(result.reasons),
        "git_sha": git_sha,
        "recommended_next_action": action,
        # Hard guard (Section 31/29) - never computed from the result,
        # never true anywhere in this module's source.
        "automatic_fix": False,
        "automatic_deploy": False,
    }
