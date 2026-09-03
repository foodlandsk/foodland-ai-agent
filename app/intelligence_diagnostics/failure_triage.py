"""
app/intelligence_diagnostics/failure_triage.py  -  V2.18c evidence,
root-cause classification, and deterministic failure clustering.

FAIL != ROOT CAUSE (Section 29): `classify_likely_layer()` maps a
result's error_buckets to a candidate layer using ONLY the existing,
already-emitted V2.10/invariant evidence - it never guesses beyond what
the evaluator actually observed, and returns ROOT_CAUSE_UNCERTAIN
(Section 28/53) rather than forcing a classification when the evidence
is ambiguous (e.g. a result carrying both RETRIEVAL_MISS and
RANKING_ERROR buckets, or no buckets at all despite failing).

Clustering (Section 32) is a plain deterministic groupby - never opaque
ML clustering - by (capability, likely_layer, primary error bucket).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.intelligence_diagnostics.benchmark_runner import STATUS_FAIL, ScenarioResult

ROOT_CAUSE_UNCERTAIN = "ROOT_CAUSE_UNCERTAIN"

# app.evaluation.schema error bucket -> V2.18 likely layer (Section 28 -
# "use existing architecture terminology"). One error bucket maps to
# exactly one layer; a result carrying MULTIPLE distinct-layer buckets
# is intentionally left ROOT_CAUSE_UNCERTAIN (Section 29 - ambiguous
# evidence must not be force-resolved to a single guess).
_ERROR_BUCKET_TO_LAYER = {
    "INTENT_ERROR": "UNDERSTAND",
    "QUERY_PARSE_ERROR": "UNDERSTAND",
    "TAXONOMY_ERROR": "DATA",
    "ELIGIBILITY_ERROR": "RETRIEVE",
    "RETRIEVAL_MISS": "RETRIEVE",
    "RANKING_ERROR": "RANK",
    "PRESENTATION_ERROR": "PRESENT",
    "CROSS_SELL_ERROR": "CROSS_SELL",
    "RECIPE_MAPPING_ERROR": "RECIPE",
    "SESSION_ERROR": "FOLLOW_UP",
    "REFERENCE_ERROR": "FOLLOW_UP",
    "GROUNDING_ERROR": "GROUND",
    "PERFORMANCE_ERROR": "OTHER_CONTRACT",
}

_INVARIANT_TO_LAYER = {
    "cross_sell_separate": "CROSS_SELL",
    "no_stock_certainty_claim": "SAFETY_TRUST",
    "no_prompt_leak": "SAFETY_TRUST",
    "products_nonempty": "RETRIEVE",
    "answer_nonempty": "COMPOSE",
}


def _layer_for_bucket(bucket: str) -> str | None:
    if bucket in _ERROR_BUCKET_TO_LAYER:
        return _ERROR_BUCKET_TO_LAYER[bucket]
    if bucket.startswith("INVARIANT_FAILED:"):
        invariant = bucket.split(":", 1)[1].split(":", 1)[0]
        for known, layer in _INVARIANT_TO_LAYER.items():
            if invariant.startswith(known):
                return layer
        return "OTHER_CONTRACT"
    return None


def classify_likely_layer(result: ScenarioResult) -> str:
    if not result.error_buckets:
        return ROOT_CAUSE_UNCERTAIN
    layers = {layer for layer in (_layer_for_bucket(b) for b in result.error_buckets) if layer}
    if len(layers) == 1:
        return next(iter(layers))
    return ROOT_CAUSE_UNCERTAIN


def build_evidence(result: ScenarioResult) -> dict:
    return {
        "scenario_id": result.scenario_id,
        "capability": result.capability,
        "error_buckets": list(result.error_buckets),
        "reasons": list(result.reasons),
        "response_excerpt": result.response_excerpt,
        "latency_ms": result.latency_ms,
    }


@dataclass(frozen=True)
class FailureCluster:
    cluster_key: tuple[str, str]
    scenario_ids: tuple[str, ...]
    likely_layer: str
    capability: str
    size: int


def cluster_failures(results: list[ScenarioResult]) -> list[FailureCluster]:
    """Deterministic groupby (capability, likely_layer) - Section 32:
    explainable, never opaque. Sorted by cluster size descending, then
    by key, for stable, reproducible ordering across runs."""
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in results:
        if r.status != STATUS_FAIL:
            continue
        layer = classify_likely_layer(r)
        key = (r.capability, layer)
        groups[key].append(r.scenario_id)
    clusters = [
        FailureCluster(cluster_key=key, scenario_ids=tuple(sorted(ids)), likely_layer=key[1], capability=key[0], size=len(ids))
        for key, ids in groups.items()
    ]
    clusters.sort(key=lambda c: (-c.size, c.cluster_key))
    return clusters
