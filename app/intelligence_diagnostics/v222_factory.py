"""
app/intelligence_diagnostics/v222_factory.py  -  V2.22a Fresh Independent
Evaluation Factory.

WHAT THIS MODULE IS NOT: it never calls the Advisor, never imports
app.main/app.advisor_engine/app.evaluation.adapter, and is never
imported by app.intelligence_diagnostics.scenario_registry.load_all_
scenarios() - the same structural guarantee V2.20/V2.21's factories
rely on (NEW_V222_ADVISOR_EXECUTIONS = 0 throughout V2.22a). V2.22
scenarios live in their own file (eval/golden/v2_22_scenarios.json),
read only by the functions below.

REUSE, NOT DUPLICATION: the Scenario/Persona/ScenarioTurn data model
and the deterministic canonical-serialization / content-hash /
stratified-split / manifest-building primitives are genuinely generic
(they take scenario lists and paths, never depend on which sprint
authored the scenarios) - this module imports them from
app.intelligence_diagnostics.v220_factory exactly as v221_factory.py
already does, instead of re-implementing them a third time. Only what
is genuinely V2.22-specific (scenario_id prefix validation, FAQ/recipe
snapshot hashing, freshness checking against the V2.18/V2.20/V2.21
historical corpus) lives here.

V2.21 QUARANTINE (V2.22a Section 3): this module intentionally does
NOT import app.intelligence_diagnostics.v221_factory or read
eval/golden/v2_21_scenarios.json as a scenario TEXT source. It is only
ever used as a comparison corpus for freshness/duplication checking
(check_textual_freshness), never copied from.
"""
from __future__ import annotations

import hashlib
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
V222_SCENARIOS_PATH = ROOT / "eval" / "golden" / "v2_22_scenarios.json"
V222_MANIFEST_PATH = ROOT / "eval" / "golden" / "v2_22_manifest.json"
PRODUCTS_PATH = ROOT / "data" / "products.json"
KNOWLEDGE_PATH = ROOT / "data" / "knowledge.json"

FACTORY_VERSION = "v222a.1"
DEFAULT_HOLDOUT_FRACTION = 0.25

# --- V2.22 capability taxonomy - the same union V2.21 already
# established (V218 base + V2.21's genuinely-new labels). No new labels
# are introduced here: every capability family named in the V2.22a
# mandate (product_search, product_advice, product_comparison,
# category_discovery, recipe_only, recipe_to_products, replacement,
# cross_sell, product_information, allergen_safety, faq,
# availability_or_price, conversation_followup, general_culinary,
# out_of_domain, multi_constraint, negation, brand_constraint, budget,
# ambiguity, insufficient_data, already_have, dietary_safety,
# cultural_authenticity, kitchenware, quantity) already maps onto an
# existing enum value below - reusing the scorer/schema vocabulary
# exactly as Section 31 of the mandate requires. ------------------------
V222_CAPABILITIES = tuple(
    sorted(
        set(V218_CAPABILITIES)
        | {
            "TYPO_ROBUSTNESS",
            "MULTI_TURN_STATE",
            "BRAND_CONSTRAINT",
            "KITCHENWARE",
            "RELATED_PRODUCTS",
            "GENERAL_CULINARY",
        }
    )
)

SPLIT_DEV = "DEV"
SPLIT_HOLDOUT = "HOLDOUT"
SPLITS = (SPLIT_DEV, SPLIT_HOLDOUT)

# --- source-class governance (V2.22a Section 3) - a scenario reusing
# text/structure from a prior revealed corpus (V2.21 HOLDOUT/DEV, V2.21
# repair negative controls) must be labeled REVEALED_REGRESSION and is
# then hard-excluded from blind HOLDOUT eligibility by
# independence_gate() below, never merely a convention. -----------------
SOURCE_CLASS_FRESH = "FRESH_INDEPENDENT"
SOURCE_CLASS_REVEALED_REGRESSION = "REVEALED_REGRESSION"
SOURCE_CLASSES = (SOURCE_CLASS_FRESH, SOURCE_CLASS_REVEALED_REGRESSION)

INDEPENDENCE_HIGH = "HIGH"
INDEPENDENCE_MEDIUM = "MEDIUM"
INDEPENDENCE_LOW = "LOW"
INDEPENDENCE_LEVELS = (INDEPENDENCE_HIGH, INDEPENDENCE_MEDIUM, INDEPENDENCE_LOW)


# --------------------------------------------------------------------
# Load / serialize (mirrors v221_factory._scenario_from_dict, plus the
# two V2.22-specific extension fields carried through raw dict passthrough
# since Scenario itself is a shared, sprint-agnostic dataclass).
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


def load_v222_scenarios(path: Path = V222_SCENARIOS_PATH) -> list[Scenario]:
    """Returns [] if the file does not exist (never raises before
    authoring)."""
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    scenarios = [_scenario_from_dict(raw) for raw in payload.get("scenarios", [])]
    scenarios.sort(key=lambda s: s.scenario_id)
    return scenarios


def load_v222_raw(path: Path = V222_SCENARIOS_PATH) -> list[dict]:
    """Raw dict access (preserves V2.22-only extension keys like
    source_class/independence_level/risk_level that the shared Scenario
    dataclass does not itself model)."""
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("scenarios", [])


# --------------------------------------------------------------------
# Split / manifest - thin wrappers naming the V2.22 defaults.
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
# FAQ / Recipe snapshot hashing (mirrors compute_catalog_snapshot's
# content-hash-based identity, applied to the two other authoritative
# data sources V2.22 FAQ/recipe scenarios cite as ground truth).
# --------------------------------------------------------------------


def compute_knowledge_section_snapshot(section: str, path: Path = KNOWLEDGE_PATH, git_sha: str = "") -> dict:
    raw = path.read_bytes()
    payload = json.loads(raw)
    section_data = payload.get("sections", {}).get(section, [])
    section_bytes = json.dumps(section_data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    section_hash = hashlib.sha256(section_bytes).hexdigest()
    return {
        "snapshot_id": f"{section.lower()}_{section_hash[:16]}",
        "source": str(path.relative_to(ROOT)).replace("\\", "/"),
        "section": section,
        "as_of_git_sha": git_sha,
        "entry_count": len(section_data),
        "content_hash": section_hash,
    }


# --------------------------------------------------------------------
# Validation (V2.22a Section 30/31/32) - structural + cross-scenario
# rules, plus the same "every scored invariant has an executable
# scorer" check V2.21 already established.
# --------------------------------------------------------------------


def _invariant_type(invariant: str) -> str:
    return invariant.split(":", 1)[0] if ":" in invariant else invariant


def validate_scenarios(scenarios: list[Scenario], raw_by_id: dict[str, dict] | None = None) -> list[str]:
    """Returns human-readable error strings; empty list means valid.
    Scenario.__post_init__ already rejects invalid source/status/
    lifecycle/difficulty/language/split/CURRENT_MODEL_OUTPUT at
    construction time. `raw_by_id`, when given, lets this also enforce
    the V2.22-only source_class/independence_level governance rule
    (Section 23/42: LOW independence is forbidden in blind HOLDOUT)."""
    errors: list[str] = []
    raw_by_id = raw_by_id or {}

    seen_ids: dict[str, int] = {}
    for s in scenarios:
        seen_ids[s.scenario_id] = seen_ids.get(s.scenario_id, 0) + 1
    errors += [f"duplicate scenario_id: {sid}" for sid, n in seen_ids.items() if n > 1]

    for s in scenarios:
        if not s.scenario_id.startswith("v222_"):
            errors.append(f"{s.scenario_id}: V2.22 scenario_id must start with 'v222_'")

        if s.capability not in V222_CAPABILITIES:
            errors.append(f"{s.scenario_id}: invalid primary capability {s.capability!r}")
        for cap in s.secondary_capabilities:
            if cap not in V222_CAPABILITIES:
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
            errors.append(f"WARNING:{s.scenario_id}: cross_sell_nonempty with products_empty - worth reviewing")
        if "requires_uncertainty" in invariants and s.safety_sensitive is False:
            errors.append(f"WARNING:{s.scenario_id}: requires_uncertainty without safety_sensitive=True")

        raw = raw_by_id.get(s.scenario_id)
        if raw is not None:
            source_class = raw.get("source_class")
            independence = raw.get("independence_level")
            if source_class not in SOURCE_CLASSES:
                errors.append(f"{s.scenario_id}: invalid source_class {source_class!r}")
            if independence not in INDEPENDENCE_LEVELS:
                errors.append(f"{s.scenario_id}: invalid independence_level {independence!r}")
            if s.split == SPLIT_HOLDOUT and independence == INDEPENDENCE_LOW:
                errors.append(f"{s.scenario_id}: LOW independence scenario is forbidden in blind HOLDOUT")
            if s.split == SPLIT_HOLDOUT and source_class == SOURCE_CLASS_REVEALED_REGRESSION:
                errors.append(f"{s.scenario_id}: REVEALED_REGRESSION source_class is forbidden in blind HOLDOUT")

    return errors


def hard_errors(errors: list[str]) -> list[str]:
    return [e for e in errors if not e.startswith("WARNING:")]


# --------------------------------------------------------------------
# Freshness / duplication checking against the V2.18 + V2.20 + V2.21
# historical corpus (V2.22a Section 22/42). Loads existing scenario
# data only (JSON/dataclass text), never calls the Advisor.
# --------------------------------------------------------------------


def _tokens(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", text.lower()))


def check_textual_freshness(
    new_scenarios: list[Scenario],
    historical_messages: list[str],
) -> dict[str, list[str]]:
    """TEXTUAL_DUPLICATE_CHECK only (not proof of semantic independence).
    Flags exact_duplicates (identical normalized message) and
    near_duplicates (>=90% token Jaccard overlap) against a historical
    message corpus."""
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


def load_historical_messages(paths: list[Path]) -> list[str]:
    """Reads scenario/turn message text out of arbitrary prior golden
    JSON files (V2.18/V2.20/V2.21 shape: {"scenarios": [{"turns": [{"message": ...}]}]}
    or a bare list of scenarios) for freshness comparison only - never
    imported as scenario content."""
    messages: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        scenarios = payload.get("scenarios", payload) if isinstance(payload, dict) else payload
        for raw in scenarios:
            for turn in raw.get("turns", []):
                msg = turn.get("message")
                if msg:
                    messages.append(msg)
    return messages


# --------------------------------------------------------------------
# Freeze counts (mirrors v221_factory.freeze_counts, plus V2.22's
# source_class/independence_level breakdown).
# --------------------------------------------------------------------


def freeze_counts(scenarios: list[Scenario], split_map: dict[str, str], raw_by_id: dict[str, dict] | None = None) -> dict:
    raw_by_id = raw_by_id or {}

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

    def _by_independence(subset: list[Scenario]) -> dict:
        out: dict[str, int] = {}
        for s in subset:
            level = raw_by_id.get(s.scenario_id, {}).get("independence_level", "UNKNOWN")
            out[level] = out.get(level, 0) + 1
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
        "holdout_independence_distribution": _by_independence(holdout),
    }
