"""
app/intelligence_diagnostics/v220_factory.py  -  V2.20a Independent
Scenario Factory & Holdout Architecture (docs/v2-20-scenario-factory.md).

WHAT THIS MODULE IS NOT: it never calls the Advisor, never imports
app.main/app.advisor_engine/app.evaluation.adapter, and is never
imported by app.intelligence_diagnostics.scenario_registry.load_all_
scenarios() - that is the structural guarantee behind
NEW_V220_ADVISOR_EXECUTIONS = 0 (Section 104 of the V2.20a mandate).
V2.20 scenarios exist in their own file
(eval/golden/v2_20_scenarios.json), read only by the functions below,
which produce plain data (Scenario objects, manifests, hashes) for a
FUTURE V2.20b blind-execution sprint to consume - building the test,
not taking it.

DETERMINISM (Section 28): the DEV/HOLDOUT split never uses random.* or
time.* - it stratifies scenarios by (primary_capability, difficulty,
language), sorts each stratum by scenario_id, and assigns every Kth
item (K = round(1 / holdout_fraction)) to HOLDOUT. Same input scenarios
+ same seed/fraction => byte-identical split, forever, on any machine.
`seed` is accepted for future algorithm versions that might use it, but
SPLIT_ALGORITHM_VERSION v1 is seed-independent by construction (no RNG
to seed) - this is intentional, not a placeholder bug.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.intelligence_diagnostics.scenario_schema import (
    CAPABILITIES,
    DIFFICULTIES,
    FORBIDDEN_AUTHORITY_CURRENT_MODEL_OUTPUT,
    GROUND_TRUTH_AUTHORITIES,
    GROUND_TRUTH_PENDING,
    GROUND_TRUTH_SCORED,
    LANGUAGES,
    Persona,
    Scenario,
    ScenarioTurn,
    SPLIT_DEV,
    SPLIT_HOLDOUT,
)

ROOT = Path(__file__).resolve().parents[2]
V220_SCENARIOS_PATH = ROOT / "eval" / "golden" / "v2_20_scenarios.json"
V220_MANIFEST_PATH = ROOT / "eval" / "golden" / "v2_20_manifest.json"
PRODUCTS_PATH = ROOT / "data" / "products.json"

FACTORY_VERSION = "v220a.1"
SPLIT_ALGORITHM_VERSION = "stratified_every_kth_v1"
DEFAULT_HOLDOUT_FRACTION = 0.25


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


def load_v220_scenarios(path: Path = V220_SCENARIOS_PATH) -> list[Scenario]:
    """Loads eval/golden/v2_20_scenarios.json only. Deliberately NOT
    called by scenario_registry.load_all_scenarios() - see module
    docstring. Returns [] if the file does not exist (never raises on
    a fresh checkout before V2.20a has been authored)."""
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    scenarios = [_scenario_from_dict(raw) for raw in payload.get("scenarios", [])]
    scenarios.sort(key=lambda s: s.scenario_id)
    return scenarios


# --------------------------------------------------------------------
# Catalog snapshot (Section 36)
# --------------------------------------------------------------------


def compute_catalog_snapshot(products_path: Path = PRODUCTS_PATH, git_sha: str = "") -> dict:
    """Content-hash-based snapshot identity - deliberately NOT a
    wall-clock timestamp (Section 45's "no real randomness/nondeterminism"
    principle extended to snapshot identity: a content hash is
    reproducible from the file alone, a timestamp is not)."""
    raw = products_path.read_bytes()
    products = json.loads(raw)
    content_hash = hashlib.sha256(raw).hexdigest()
    return {
        "snapshot_id": f"products_{content_hash[:16]}",
        "source": str(products_path.relative_to(ROOT)).replace("\\", "/"),
        "as_of_git_sha": git_sha,
        "product_count": len(products),
        "content_hash": content_hash,
    }


# --------------------------------------------------------------------
# Deterministic canonical serialization + content hash (Section 87)
# --------------------------------------------------------------------


def _canonical_scenario_dict(s: Scenario) -> dict:
    """Sorted-key, stable, hash-relevant view of a scenario - excludes
    nothing scoring-relevant, excludes nothing identity-relevant. Turn
    order is preserved (meaningful for multi-turn); everything else is
    a plain sorted-keys dict for deterministic JSON serialization."""
    return {
        "scenario_id": s.scenario_id,
        "source": s.source,
        "capability": s.capability,
        "secondary_capabilities": sorted(s.secondary_capabilities),
        "difficulty": s.difficulty,
        "language": s.language,
        "turns": [
            {"message": t.message, "expected_intent": t.expected_intent, "expected_workflow": t.expected_workflow}
            for t in s.turns
        ],
        "ground_truth_status": s.ground_truth_status,
        "ground_truth_authority": s.ground_truth_authority,
        "ground_truth_reason": s.ground_truth_reason,
        "objective": s.objective,
        "known_facts": sorted(s.known_facts),
        "expected_invariants": sorted(s.expected_invariants),
        "forbidden_behavior": sorted(s.forbidden_behavior),
        "constraints": sorted(s.constraints),
        "catalog_dependency": s.catalog_dependency,
        "safety_sensitive": s.safety_sensitive,
        "catalog_snapshot_id": s.catalog_snapshot_id,
        "review_flags": sorted(s.review_flags),
        "critical": s.critical,
    }


def canonical_serialize(scenarios: list[Scenario]) -> str:
    ordered = sorted(scenarios, key=lambda s: s.scenario_id)
    payload = [_canonical_scenario_dict(s) for s in ordered]
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"


def content_hash(scenarios: list[Scenario]) -> str:
    return hashlib.sha256(canonical_serialize(scenarios).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------
# Deterministic stratified DEV/HOLDOUT split (Section 23/27/28)
# --------------------------------------------------------------------


def assign_split(scenarios: list[Scenario], holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION) -> dict[str, str]:
    """Stratifies by difficulty ONLY (Section 27's most important axis -
    Section 115 explicitly requires HOLDOUT to carry meaningful L3/L4/L5
    coverage, which a benchmark this size cannot guarantee if stratified
    on the full (capability, difficulty, language) triple: with ~106
    scenarios across ~25 capabilities x 5 difficulties x 2 languages,
    most triples have 1-3 items, and "every Kth" (K=4) then never fires
    for any stratum smaller than K - the bug this replaced produced a
    6% holdout with zero L4/L5/EN cases. Difficulty alone gives 5 buckets
    of 3-30 items each, large enough for proportional holdout at every
    difficulty tier. Within each difficulty bucket, scenarios are sorted
    by (language, safety_sensitive, capability, scenario_id) before
    applying the modulo-K cut, so the language/safety/capability axes
    still interleave into the holdout pick instead of clustering -
    still fully deterministic, no randomness (Section 28)."""
    k = max(2, round(1 / holdout_fraction))
    strata: dict[str | None, list[Scenario]] = {}
    for s in scenarios:
        strata.setdefault(s.difficulty, []).append(s)

    split_map: dict[str, str] = {}
    for key in sorted(strata, key=lambda k: (k or "",)):
        stratum = sorted(strata[key], key=lambda s: (s.language, s.safety_sensitive, s.capability, s.scenario_id))
        for i, s in enumerate(stratum):
            split_map[s.scenario_id] = SPLIT_HOLDOUT if (i % k == k - 1) else SPLIT_DEV
    return split_map


# --------------------------------------------------------------------
# Validation (Section 83/84)
# --------------------------------------------------------------------


def validate_scenarios(scenarios: list[Scenario]) -> list[str]:
    """Returns a list of human-readable error strings; empty list means
    valid. Scenario.__post_init__ already structurally rejects invalid
    source/ground_truth_status/lifecycle_status/difficulty/language/
    split/CURRENT_MODEL_OUTPUT at construction time - this function
    checks the CROSS-scenario and cross-field consistency rules that
    __post_init__ cannot (Section 84: contradictory contracts)."""
    errors: list[str] = []

    seen_ids: dict[str, int] = {}
    for s in scenarios:
        seen_ids[s.scenario_id] = seen_ids.get(s.scenario_id, 0) + 1
    errors += [f"duplicate scenario_id: {sid}" for sid, n in seen_ids.items() if n > 1]

    for s in scenarios:
        if s.capability not in CAPABILITIES:
            errors.append(f"{s.scenario_id}: invalid primary capability {s.capability!r}")
        for cap in s.secondary_capabilities:
            if cap not in CAPABILITIES:
                errors.append(f"{s.scenario_id}: invalid secondary capability {cap!r}")

        if s.ground_truth_status == GROUND_TRUTH_SCORED:
            if not s.provenance.strip():
                errors.append(f"{s.scenario_id}: SCORED scenario missing provenance")
            if not s.ground_truth_reason.strip():
                errors.append(f"{s.scenario_id}: SCORED scenario missing ground_truth_reason")
            if s.catalog_dependency and not s.catalog_snapshot_id:
                errors.append(f"{s.scenario_id}: catalog_dependency=True but no catalog_snapshot_id")

        invariants = set(s.expected_invariants)
        if "products_empty" in invariants and any(inv.startswith("min_products:") for inv in invariants):
            for inv in invariants:
                if inv.startswith("min_products:") and int(inv.split(":", 1)[1]) > 0:
                    errors.append(f"{s.scenario_id}: contradictory contract - products_empty AND {inv}")
        if "products_empty" in invariants and "products_nonempty" in invariants:
            errors.append(f"{s.scenario_id}: contradictory contract - products_empty AND products_nonempty")
        if "requires_uncertainty" in invariants and s.safety_sensitive is False and s.ground_truth_status == GROUND_TRUTH_SCORED:
            # Not a hard error (a non-safety scenario can legitimately test
            # uncertainty too), but flagged for review since in practice
            # every V2.20a author-time use of this invariant was safety-
            # motivated - a silent mismatch here is worth a human glance.
            # "WARNING:" prefix lets callers separate hard errors (block
            # release) from review flags (do not block) with a simple
            # str.startswith() filter.
            errors.append(f"WARNING:{s.scenario_id}: requires_uncertainty without safety_sensitive=True")

    return errors


def hard_errors(errors: list[str]) -> list[str]:
    return [e for e in errors if not e.startswith("WARNING:")]


def find_semantic_duplicates(scenarios: list[Scenario]) -> list[tuple[str, str]]:
    """Deterministic, repository-local near-duplicate detection (Section
    72/85) - no embeddings, no Advisor output. Two scenarios are flagged
    as clones when they share the exact same (capability, sorted
    constraints, sorted expected_invariants) tuple AND their first
    turn's normalized token set is identical - i.e. genuinely the same
    reasoning test restated, not just a similar topic."""
    import re

    def _tokens(text: str) -> frozenset[str]:
        return frozenset(re.findall(r"[a-z0-9]+", text.lower()))

    seen: dict[tuple, str] = {}
    duplicates: list[tuple[str, str]] = []
    for s in sorted(scenarios, key=lambda s: s.scenario_id):
        fingerprint = (
            s.capability,
            tuple(sorted(s.constraints)),
            tuple(sorted(s.expected_invariants)),
            _tokens(s.turns[0].message),
        )
        if fingerprint in seen:
            duplicates.append((seen[fingerprint], s.scenario_id))
        else:
            seen[fingerprint] = s.scenario_id
    return duplicates


# --------------------------------------------------------------------
# Manifest (Section 86)
# --------------------------------------------------------------------


def _distribution(scenarios: list[Scenario], key) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in scenarios:
        v = key(s)
        out[str(v)] = out.get(str(v), 0) + 1
    return dict(sorted(out.items()))


def build_manifest(scenarios: list[Scenario], split_map: dict[str, str], catalog_snapshot: dict, split_name: str) -> dict:
    subset = [s for s in scenarios if split_map.get(s.scenario_id) == split_name]
    scored = [s for s in subset if s.is_scored]
    pending = [s for s in subset if s.ground_truth_status == GROUND_TRUTH_PENDING]
    return {
        "split": split_name,
        "factory_version": FACTORY_VERSION,
        "split_algorithm_version": SPLIT_ALGORITHM_VERSION,
        "scenario_count": len(subset),
        "scored_count": len(scored),
        "pending_count": len(pending),
        "language_distribution": _distribution(subset, lambda s: s.language),
        "capability_distribution": _distribution(subset, lambda s: s.capability),
        "difficulty_distribution": _distribution(subset, lambda s: s.difficulty),
        "multi_turn_count": sum(1 for s in subset if s.is_multi_turn),
        "safety_sensitive_count": sum(1 for s in subset if s.safety_sensitive),
        "catalog_dependent_count": sum(1 for s in subset if s.catalog_dependency),
        "catalog_snapshot": catalog_snapshot,
        "content_hash": content_hash(subset),
        "scenario_ids": sorted(s.scenario_id for s in subset),
    }


def verify_manifest(manifest: dict, scenarios: list[Scenario], split_map: dict[str, str]) -> list[str]:
    """Recomputes a manifest from current scenario data and reports any
    mismatch against the frozen one - the self-verification tooling
    Section 90 requires. Never calls the Advisor."""
    fresh = build_manifest(scenarios, split_map, manifest["catalog_snapshot"], manifest["split"])
    mismatches = []
    for key in ("scenario_count", "scored_count", "pending_count", "content_hash", "scenario_ids",
                "language_distribution", "capability_distribution", "difficulty_distribution"):
        if fresh[key] != manifest[key]:
            mismatches.append(f"{key}: frozen={manifest[key]!r} recomputed={fresh[key]!r}")
    return mismatches
