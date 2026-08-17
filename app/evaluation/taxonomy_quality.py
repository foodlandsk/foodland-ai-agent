"""
app/evaluation/taxonomy_quality.py  -  V2.10 taxonomy quality (Section 18/19)

Reports coverage AND precision together (Section 19) - never coverage
alone, since higher coverage with more wrong classifications is a
regression, not an improvement. "Precision" here is measured against the
golden dataset's own expected_concept_ids (the only ground truth
available - Section 18 also explicitly allows UNKNOWN to be correct, so
this never penalizes a product staying UNKNOWN).
"""
from __future__ import annotations

from collections import Counter

from app.evaluation.schema import GoldenCase


def taxonomy_coverage(taxonomy_index: dict) -> dict:
    confidence_counts = Counter(getattr(entry, "confidence", "UNKNOWN") for entry in taxonomy_index.values())
    total = len(taxonomy_index) or 1
    classified = total - confidence_counts.get("UNKNOWN", 0)
    return {
        "total_products": len(taxonomy_index),
        "confidence_distribution": dict(confidence_counts),
        "coverage_ratio": classified / total,
    }


def taxonomy_precision_against_golden(cases: list[GoldenCase], taxonomy_index: dict) -> dict:
    """For every golden case that names an expected_concept_id, checks
    whether that concept_id actually has ANY current catalog evidence
    (Section 18/19 - a golden expectation pointing at a concept the
    taxonomy no longer recognizes is itself a drift signal, not silently
    ignored)."""
    concept_ids_seen = {getattr(entry, "concept_id", None) for entry in taxonomy_index.values()}
    concept_ids_seen.discard(None)
    concept_ids_seen.discard("")

    expected_concepts = sorted({cid for case in cases for cid in case.expected_concept_ids})
    missing = [cid for cid in expected_concepts if cid not in concept_ids_seen]
    return {
        "expected_concepts_in_golden": len(expected_concepts),
        "expected_concepts_with_catalog_evidence": len(expected_concepts) - len(missing),
        "expected_concepts_missing_from_catalog": missing,
    }
