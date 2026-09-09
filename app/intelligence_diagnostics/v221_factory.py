"""
app/intelligence_diagnostics/v221_factory.py  -  V2.21a Independent
Fresh Scenario Factory (docs/v2-21-scenario-factory.md).

WHAT THIS MODULE IS NOT: it never calls the Advisor, never imports
app.main/app.advisor_engine/app.evaluation.adapter, and is never
imported by app.intelligence_diagnostics.scenario_registry.load_all_
scenarios() - the same structural guarantee V2.20's factory relies on,
extended to V2.21 (Section 2 - NEW_V221_ADVISOR_EXECUTIONS = 0
throughout V2.21a). V2.21 scenarios live in their own file
(eval/golden/v2_21_scenarios.json), read only by the functions below.

REUSE, NOT DUPLICATION (Section 2 of the V2.18 mandate, cited verbatim
in v220_factory.py's own docstring, applies here too): the Scenario/
Persona/ScenarioTurn data model and the deterministic canonical-
serialization / content-hash / stratified-split / manifest-building
primitives are genuinely generic - they take scenario lists and paths,
never depend on which sprint authored the scenarios - so this module
imports and reuses them directly from app.intelligence_diagnostics.
v220_factory instead of re-implementing ~150 lines of already-proven,
already-tested logic. Only what is genuinely V2.21-specific (capability
taxonomy, invariant-type validation against the V2.21 scorer registry,
freshness checking against the V2.18/V2.20 historical corpus, file
paths) lives in this module.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.intelligence_diagnostics.scenario_schema import (
    CAPABILITIES as V218_CAPABILITIES,
    GROUND_TRUTH_AUTHORITIES,
    GROUND_TRUTH_PENDING,
    GROUND_TRUTH_SCORED,
    LANGUAGES,
    Persona,
    Scenario,
    ScenarioTurn,
)
from app.intelligence_diagnostics.v220_factory import (
    assign_split as _assign_split,
    build_manifest as _build_manifest,
    canonical_serialize,
    compute_catalog_snapshot,
    content_hash,
    verify_manifest as _verify_manifest,
)
from app.intelligence_diagnostics.v221_scorer import (
    KNOWN_ARG_INVARIANT_TYPES,
    KNOWN_BARE_INVARIANTS,
)

ROOT = Path(__file__).resolve().parents[2]
V221_SCENARIOS_PATH = ROOT / "eval" / "golden" / "v2_21_scenarios.json"
V221_MANIFEST_PATH = ROOT / "eval" / "golden" / "v2_21_manifest.json"
PRODUCTS_PATH = ROOT / "data" / "products.json"

FACTORY_VERSION = "v221a.1"
DEFAULT_HOLDOUT_FRACTION = 0.25

# --- V2.21 capability taxonomy (Section 8) - superset of the V2.18/
# V2.20 taxonomy (reused unchanged, since most V2.21 scenarios exercise
# capabilities the Advisor already has a concept of) plus the genuinely
# new labels Section 8 calls out that had no prior equivalent. ---------
V221_NEW_CAPABILITIES = (
    "TYPO_ROBUSTNESS",
    "MULTI_TURN_STATE",
    "BRAND_CONSTRAINT",
    "KITCHENWARE",
    "RELATED_PRODUCTS",
    "GENERAL_CULINARY",
)
V221_CAPABILITIES = tuple(sorted(set(V218_CAPABILITIES) | set(V221_NEW_CAPABILITIES)))

SPLIT_DEV = "DEV"
SPLIT_HOLDOUT = "HOLDOUT"
SPLITS = (SPLIT_DEV, SPLIT_HOLDOUT)


# --------------------------------------------------------------------
# Load / serialize (mirrors v220_factory._scenario_from_dict exactly -
# same Scenario dataclass, same dict shape)
# --------------------------------------------------------------------


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


def _scenario_from_dict(raw: dict) -> Scenario:
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
        lifecycle_status=raw.get("lifecycle_status", "OPEN"),
        created_version=raw.get("created_version", FACTORY_VERSION),
        critical=raw.get("critical", False),
        secondary_capabilities=tuple(raw.get("secondary_capabilities", ())),
        difficulty=raw.get("difficulty"),
        language=raw.get("language", "sk"),
        split=raw.get("split"),
        catalog_dependency=raw.get("catalog_dependency", False),
        safety_sensitive=raw.get("safety_sensitive", False),
        catalog_snapshot_id=raw.get("catalog_snapshot_id"),
        review_flags=tuple(raw.get("review_flags", ())),
    )


def load_v221_scenarios(path: Path = V221_SCENARIOS_PATH) -> list[Scenario]:
    """Returns [] if the file does not exist (never raises on a fresh
    checkout before authoring)."""
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    scenarios = [_scenario_from_dict(raw) for raw in payload.get("scenarios", [])]
    scenarios.sort(key=lambda s: s.scenario_id)
    return scenarios


# --------------------------------------------------------------------
# Split / manifest - thin wrappers naming the V2.21 defaults, calling
# straight through to the shared v220_factory primitives.
# --------------------------------------------------------------------


def assign_split(scenarios: list[Scenario], holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION) -> dict[str, str]:
    return _assign_split(scenarios, holdout_fraction=holdout_fraction)


def build_manifest(scenarios: list[Scenario], split_map: dict[str, str], catalog_snapshot: dict, split_name: str) -> dict:
    manifest = _build_manifest(scenarios, split_map, catalog_snapshot, split_name)
    manifest["factory_version"] = FACTORY_VERSION
    return manifest


def verify_manifest(manifest: dict, scenarios: list[Scenario], split_map: dict[str, str]) -> list[str]:
    return _verify_manifest(manifest, scenarios, split_map)


# --------------------------------------------------------------------
# Validation (Section 51/78) - structural + cross-scenario rules,
# PLUS the V2.21-specific "every scored invariant has an executable
# scorer" check that closes V2.20's Section 7 gap.
# --------------------------------------------------------------------


def _invariant_type(invariant: str) -> str:
    return invariant.split(":", 1)[0] if ":" in invariant else invariant


def validate_scenarios(scenarios: list[Scenario]) -> list[str]:
    """Returns human-readable error strings; empty list means valid.
    Scenario.__post_init__ already rejects invalid source/status/
    lifecycle/difficulty/language/split/CURRENT_MODEL_OUTPUT at
    construction time. This function checks V2.21-specific and
    cross-scenario rules."""
    errors: list[str] = []

    seen_ids: dict[str, int] = {}
    for s in scenarios:
        seen_ids[s.scenario_id] = seen_ids.get(s.scenario_id, 0) + 1
    errors += [f"duplicate scenario_id: {sid}" for sid, n in seen_ids.items() if n > 1]

    for s in scenarios:
        if not s.scenario_id.startswith("v221_"):
            errors.append(f"{s.scenario_id}: V2.21 scenario_id must start with 'v221_'")

        if s.capability not in V221_CAPABILITIES:
            errors.append(f"{s.scenario_id}: invalid primary capability {s.capability!r}")
        for cap in s.secondary_capabilities:
            if cap not in V221_CAPABILITIES:
                errors.append(f"{s.scenario_id}: invalid secondary capability {cap!r}")

        if s.ground_truth_status == GROUND_TRUTH_SCORED:
            if not s.provenance.strip():
                errors.append(f"{s.scenario_id}: SCORED scenario missing provenance")
            if not s.ground_truth_reason.strip():
                errors.append(f"{s.scenario_id}: SCORED scenario missing ground_truth_reason")
            if s.ground_truth_authority not in GROUND_TRUTH_AUTHORITIES:
                errors.append(f"{s.scenario_id}: SCORED scenario has invalid authority {s.ground_truth_authority!r}")
            if s.catalog_dependency and not s.catalog_snapshot_id:
                errors.append(f"{s.scenario_id}: catalog_dependency=True but no catalog_snapshot_id")
            if not s.expected_invariants:
                errors.append(f"{s.scenario_id}: SCORED scenario has no expected_invariants")

            # Section 36/51 - no scored invariant without an executable
            # scorer implementation. Unknown type at freeze time is a
            # HARD error, not a runtime ERROR discovered later in V2.21b.
            for inv in s.expected_invariants:
                inv_type = _invariant_type(inv)
                if inv_type not in KNOWN_BARE_INVARIANTS and inv_type not in KNOWN_ARG_INVARIANT_TYPES:
                    errors.append(f"{s.scenario_id}: invariant {inv!r} has no scorer implementation")

        if s.ground_truth_status == GROUND_TRUTH_PENDING and s.expected_invariants:
            errors.append(f"{s.scenario_id}: GROUND_TRUTH_PENDING scenario must not declare expected_invariants")

        invariants = set(s.expected_invariants)
        if "products_empty" in invariants and "products_nonempty" in invariants:
            errors.append(f"{s.scenario_id}: contradictory contract - products_empty AND products_nonempty")
        if "cross_sell_nonempty" in invariants and "products_empty" in invariants:
            errors.append(f"{s.scenario_id}: WARNING contract worth reviewing - cross_sell_nonempty with products_empty")

        if "requires_uncertainty" in invariants and s.safety_sensitive is False:
            errors.append(f"WARNING:{s.scenario_id}: requires_uncertainty without safety_sensitive=True")

    return errors


def hard_errors(errors: list[str]) -> list[str]:
    return [e for e in errors if not e.startswith("WARNING:")]


# --------------------------------------------------------------------
# Freshness checking (Section 52/53) - compares V2.21 scenario TEXT
# against the V2.18 + V2.20 historical corpus. Loads existing scenario
# data only (JSON/dataclass), never calls the Advisor.
# --------------------------------------------------------------------


def _tokens(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", text.lower()))


def check_textual_freshness(
    new_scenarios: list[Scenario],
    historical_messages: list[str],
) -> dict[str, list[str]]:
    """TEXTUAL_DUPLICATE_CHECK only (Section 53 - this is NOT proof of
    semantic independence, only of textual non-duplication). Flags:
    - exact_duplicates: identical normalized message text
    - near_duplicates: >=90% token-set overlap (Jaccard) with a
      historical message, a bounded/cheap proxy for "trivial variant,"
      not a claim of true novelty."""
    historical_norm = [m.strip().lower() for m in historical_messages]
    historical_tok = [_tokens(m) for m in historical_messages]

    exact: list[str] = []
    near: list[str] = []
    for s in new_scenarios:
        for turn in s.turns:
            msg_norm = turn.message.strip().lower()
            if msg_norm in historical_norm:
                exact.append(s.scenario_id)
                break
            msg_tok = _tokens(turn.message)
            if not msg_tok:
                continue
            for h_tok in historical_tok:
                if not h_tok:
                    continue
                jaccard = len(msg_tok & h_tok) / len(msg_tok | h_tok)
                if jaccard >= 0.90:
                    near.append(s.scenario_id)
                    break
            else:
                continue
            break
    return {"exact_duplicates": sorted(set(exact)), "near_duplicates": sorted(set(near) - set(exact))}


# --------------------------------------------------------------------
# Freeze counts (Section 91)
# --------------------------------------------------------------------


def freeze_counts(scenarios: list[Scenario], split_map: dict[str, str]) -> dict:
    def _count(subset: list[Scenario]) -> dict:
        scored = [s for s in subset if s.is_scored]
        pending = [s for s in subset if s.ground_truth_status == GROUND_TRUTH_PENDING]
        return {"total": len(subset), "scored": len(scored), "pending": len(pending)}

    dev = [s for s in scenarios if split_map.get(s.scenario_id) == SPLIT_DEV]
    holdout = [s for s in scenarios if split_map.get(s.scenario_id) == SPLIT_HOLDOUT]
    single_turn = [s for s in scenarios if not s.is_multi_turn]
    multi_turn = [s for s in scenarios if s.is_multi_turn]

    def _by(key):
        out: dict[str, int] = {}
        for s in scenarios:
            v = str(key(s))
            out[v] = out.get(v, 0) + 1
        return dict(sorted(out.items()))

    return {
        "overall": _count(scenarios),
        "dev": _count(dev),
        "holdout": _count(holdout),
        "single_turn_count": len(single_turn),
        "multi_turn_count": len(multi_turn),
        "by_capability": _by(lambda s: s.capability),
        "by_language": _by(lambda s: s.language),
        "by_authority": _by(lambda s: s.ground_truth_authority),
        "by_safety_sensitive": _by(lambda s: s.safety_sensitive),
    }
