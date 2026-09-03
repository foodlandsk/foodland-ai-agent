"""
app/intelligence_diagnostics/scenario_registry.py  -  V2.18a append-only
scenario registry.

Three layers, all additive, never mutating an existing file's content:

  1. EXISTING_GOLDEN / REGRESSION_BUG - every case already under
     eval/golden/*.json and eval/conversations/*.json (V2.10), adapted
     into a Scenario VIEW via app.evaluation.loader (read-only - this
     module never writes back to those files). This is Section 2's
     "integrate minimally, do not replace proven infrastructure."

  2. Lifecycle overlay (eval/golden/v2_18_lifecycle_overlay.json) - the
     ONLY place a case's lifecycle_status can be recorded as CLOSED/
     SUPERSEDED/DATA_BLOCKED. A brand-new, purely additive file: the
     underlying golden JSON is never touched, so there is zero risk to
     the proven V2.10 pipeline. This is the formalization Section 2
     asked for - the one existing case that already carries an informal
     "CLOSED_BY_HUMAN_SEMANTIC_DECISION" prose note (regbug rt0013, see
     eval/golden/regression_bugs.json) gets a REAL structured status
     here instead of leaving the free-text note as the only record.

  3. Curated scenarios (eval/golden/v2_18_curated_scenarios.json) -
     CURATED / REAL_CUSTOMER_QA / SAFE_MUTATION scenarios authored
     directly against the V2.18 Scenario schema. New file, version-
     controlled, human-reviewable JSON (same discipline as eval/golden/
     itself).

APPEND-ONLY / ANTI-LAUNDERING (Section 8/9): `detect_benchmark_shrinkage()`
compares two scenario-id sets and flags any id present in the OLDER set
but missing from the NEWER one - the deterministic, testable form of "a
historical valid case must never silently disappear."
"""
from __future__ import annotations

import json
from pathlib import Path

from app.evaluation.loader import GOLDEN_DIR, load_all_conversation_cases, load_all_golden_cases
from app.evaluation.schema import GoldenCase, ConversationCase
from app.intelligence_diagnostics.scenario_schema import (
    AUTHORITY_EXISTING_GOLDEN,
    GROUND_TRUTH_SCORED,
    LIFECYCLE_OPEN,
    Persona,
    Scenario,
    ScenarioTurn,
    SOURCE_EXISTING_GOLDEN,
    SOURCE_REGRESSION_BUG,
)

LIFECYCLE_OVERLAY_PATH = GOLDEN_DIR / "v2_18_lifecycle_overlay.json"
CURATED_SCENARIOS_PATH = GOLDEN_DIR / "v2_18_curated_scenarios.json"

# query_type (V2.10, Section 7 of app.evaluation.schema) -> V2.18
# capability. Reuses the existing controlled vocabulary rather than
# re-classifying every case by hand (Section 15).
_QUERY_TYPE_TO_CAPABILITY = {
    "EXACT_PRODUCT": "PRODUCT_SEARCH",
    "CATEGORY": "PRODUCT_SEARCH",
    "SUBCATEGORY": "PRODUCT_SEARCH",
    "BRAND": "PRODUCT_SEARCH",
    "BRAND_CATEGORY": "PRODUCT_SEARCH",
    "ATTRIBUTE": "RETRIEVE",
    "PACKAGE_SIZE": "RETRIEVE",
    "USE_CASE": "PRODUCT_ADVICE",
    "RECIPE_INGREDIENT": "RECIPE_TO_PRODUCTS",
    "REPLACEMENT": "REPLACEMENT",
    "COMPARISON": "COMPARISON",
    "INFORMATIONAL": "FAQ",
    "AMBIGUOUS": "UNDERSTAND",
    "MISSPELLING": "UNDERSTAND",
    "MULTI_TOKEN": "UNDERSTAND",
    "NEGATION": "CONSTRAINT_PRESERVATION",
    "FOLLOW_UP": "FOLLOW_UP",
    "CONTEXT_SWITCH": "FOLLOW_UP",
    "SHOW_MORE": "PRESENT",
    "SHOW_ALL": "PRESENT",
    "CROSS_SELL": "CROSS_SELL",
    "REGRESSION_BUG": "RETRIEVE",
}


def _capability_for_golden_case(case: GoldenCase) -> str:
    return _QUERY_TYPE_TO_CAPABILITY.get(case.query_type, "PRODUCT_SEARCH")


def _lifecycle_overlay() -> dict[str, dict]:
    if not LIFECYCLE_OVERLAY_PATH.exists():
        return {}
    payload = json.loads(LIFECYCLE_OVERLAY_PATH.read_text(encoding="utf-8"))
    return {entry["case_id"]: entry for entry in payload.get("entries", [])}


def adapt_golden_case(case: GoldenCase, overlay: dict[str, dict] | None = None) -> Scenario:
    overlay = overlay if overlay is not None else _lifecycle_overlay()
    entry = overlay.get(case.id, {})
    invariants: list[str] = []
    # V2.18d.1 fix - the ORIGINAL fallback ("no title substrings declared
    # -> assume products_nonempty") ignored max_products=0, which is a
    # real, deliberate contract for allergen_safety/faq/recipe-style cases
    # where an EMPTY product list is the correct, safe answer (e.g.
    # regbug_rt0010 - "bez soje" allergen question must never recommend a
    # product by name alone). That mismatch only ever affected this
    # scenario's SAFE_MUTATION children (mutate_scenario() inherits
    # expected_invariants unchanged) - the unmutated EXISTING_GOLDEN/
    # REGRESSION_BUG scenario itself is always scored by the real
    # app.evaluation.runner.run_golden_case(), which already respects
    # max_products correctly and was never affected. See docs/
    # intelligence-diagnostic-loop-v2.18.1.md for the full diagnosis
    # (this bug explained 36 of the 43 FAIL results in the V2.18a-c
    # Intelligence Report's first generation).
    if case.max_products == 0:
        invariants.append("products_empty")
    elif not case.must_include_title_substrings:
        invariants.append("products_nonempty")
    if case.expected_intent:
        invariants.append(f"intent=={case.expected_intent}")
    source = SOURCE_REGRESSION_BUG if case.source == "regression_bug" else SOURCE_EXISTING_GOLDEN
    return Scenario(
        scenario_id=case.id,
        source=source,
        capability=_capability_for_golden_case(case),
        turns=(ScenarioTurn(message=case.query, expected_intent=case.expected_intent),),
        ground_truth_status=GROUND_TRUTH_SCORED,
        ground_truth_authority=AUTHORITY_EXISTING_GOLDEN,
        ground_truth_reason="Existing V2.10 golden/regression case - scored by app.evaluation.runner unchanged.",
        objective=case.note,
        expected_invariants=tuple(invariants),
        provenance=f"eval/golden (query_type={case.query_type})",
        lifecycle_status=entry.get("status", LIFECYCLE_OPEN),
        lifecycle_reason=entry.get("reason", ""),
        closed_version=entry.get("closed_version"),
        underlying_case_id=case.id,
        critical=case.critical,
    )


def adapt_conversation_case(case: ConversationCase, overlay: dict[str, dict] | None = None) -> Scenario:
    overlay = overlay if overlay is not None else _lifecycle_overlay()
    entry = overlay.get(case.id, {})
    turns = tuple(
        ScenarioTurn(message=t.message, expected_intent=t.expected_intent, expected_workflow=t.expected_workflow, note=t.note)
        for t in case.turns
    )
    return Scenario(
        scenario_id=case.id,
        source=SOURCE_EXISTING_GOLDEN,
        capability="FOLLOW_UP",
        turns=turns,
        ground_truth_status=GROUND_TRUTH_SCORED,
        ground_truth_authority=AUTHORITY_EXISTING_GOLDEN,
        ground_truth_reason="Existing V2.10 multi-turn conversation case - scored by app.evaluation.conversation unchanged.",
        objective=case.note,
        provenance="eval/conversations",
        lifecycle_status=entry.get("status", LIFECYCLE_OPEN),
        lifecycle_reason=entry.get("reason", ""),
        closed_version=entry.get("closed_version"),
        underlying_case_id=case.id,
        critical=case.critical,
    )


def _persona_from_dict(raw: dict | None) -> Persona | None:
    if not raw:
        return None
    return Persona(
        persona_id=raw["persona_id"],
        knowledge_level=raw["knowledge_level"],
        shopper_style=raw.get("shopper_style"),
        communication_style=raw.get("communication_style"),
        description=raw.get("description", ""),
    )


def _curated_scenario_from_dict(raw: dict) -> Scenario:
    turns = tuple(
        ScenarioTurn(
            message=t["message"],
            expected_intent=t.get("expected_intent"),
            expected_workflow=t.get("expected_workflow"),
            note=t.get("note", ""),
        )
        for t in raw["turns"]
    )
    return Scenario(
        scenario_id=raw["scenario_id"],
        source=raw["source"],
        capability=raw["capability"],
        turns=turns,
        ground_truth_status=raw["ground_truth_status"],
        ground_truth_authority=raw.get("ground_truth_authority"),
        ground_truth_reason=raw.get("ground_truth_reason", ""),
        persona=_persona_from_dict(raw.get("persona")),
        objective=raw.get("objective", ""),
        known_facts=tuple(raw.get("known_facts", ())),
        expected_invariants=tuple(raw.get("expected_invariants", ())),
        forbidden_behavior=tuple(raw.get("forbidden_behavior", ())),
        constraints=tuple(raw.get("constraints", ())),
        provenance=raw.get("provenance", ""),
        lifecycle_status=raw.get("lifecycle_status", LIFECYCLE_OPEN),
        lifecycle_reason=raw.get("lifecycle_reason", ""),
        created_version=raw.get("created_version", "V2.18a"),
        closed_version=raw.get("closed_version"),
        critical=raw.get("critical", False),
    )


def load_curated_scenarios(path: Path = CURATED_SCENARIOS_PATH) -> list[Scenario]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [_curated_scenario_from_dict(raw) for raw in payload.get("scenarios", [])]


def load_all_scenarios() -> list[Scenario]:
    """The full V2.18 scenario pool: every existing V2.10 golden/
    conversation case (adapted, read-only) plus every curated scenario.
    Deterministic ordering (matches app.evaluation.loader's own
    precedent) - sorted by scenario_id, never dict/filesystem iteration
    order."""
    overlay = _lifecycle_overlay()
    scenarios = [adapt_golden_case(c, overlay) for c in load_all_golden_cases()]
    scenarios += [adapt_conversation_case(c, overlay) for c in load_all_conversation_cases()]
    scenarios += load_curated_scenarios()
    scenarios.sort(key=lambda s: s.scenario_id)
    _assert_unique_ids(scenarios)
    return scenarios


def _assert_unique_ids(scenarios: list[Scenario]) -> None:
    seen: dict[str, int] = {}
    for s in scenarios:
        seen[s.scenario_id] = seen.get(s.scenario_id, 0) + 1
    duplicates = [sid for sid, count in seen.items() if count > 1]
    if duplicates:
        raise ValueError(f"Duplicate scenario ids: {duplicates}")


def detect_benchmark_shrinkage(older_ids: set[str], newer_ids: set[str]) -> set[str]:
    """Section 8/9 anti-laundering guard: any scenario_id present before
    but missing now. An empty result is the only acceptable state for a
    real generation-to-generation comparison."""
    return older_ids - newer_ids
