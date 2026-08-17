"""
app/evaluation/metrics.py  -  V2.10 pure metric calculations

Every function here is pure (no I/O, no chat() calls) so it is trivially
unit-testable in isolation (Section 100) - app/evaluation/runner.py is the
only place that calls into the live system and feeds these functions real
data.

Semantic correctness over lexical similarity (Section 116): "relevant"
throughout this module means "matches an EXPECTED CONCEPT_ID via real
taxonomy classification", not "title contains a similar word". A caller
that only has title substrings should treat that as a weaker, secondary
signal (see app.evaluation.runner).
"""
from __future__ import annotations

import math


def eligibility_precision(
    returned_ids: list[str],
    forbidden_concept_ids: frozenset[str],
    concept_id_by_product: dict[str, str | None],
) -> float:
    """Section 11/12 - fraction of returned products that are NOT one of
    the explicitly forbidden concepts (e.g. rice_vinegar/rice_noodles/
    rice_paper/rice_cooker must never count as eligible for "jazmínová
    ryža"). An empty result list is vacuously fully eligible (nothing
    ineligible was returned) - a RETRIEVAL_MISS is a separate, distinct
    failure mode (see recall_at_k), not an eligibility failure."""
    if not returned_ids:
        return 1.0
    if not forbidden_concept_ids:
        return 1.0
    ineligible = sum(
        1 for pid in returned_ids
        if concept_id_by_product.get(pid) in forbidden_concept_ids
    )
    return 1.0 - (ineligible / len(returned_ids))


def _relevant_set(returned_ids: list[str], expected_concept_ids: frozenset[str], concept_id_by_product: dict[str, str | None]) -> set[str]:
    if not expected_concept_ids:
        return set()
    return {pid for pid in returned_ids if concept_id_by_product.get(pid) in expected_concept_ids}


def precision_at_k(returned_ids: list[str], relevant_ids: set[str], k: int) -> float:
    top = returned_ids[:k]
    if not top:
        return 0.0
    return sum(1 for pid in top if pid in relevant_ids) / len(top)


def recall_at_k(returned_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Recall is only meaningful when the caller supplies the TRUE full
    relevant set (e.g. every catalog product matching the expected
    concept, not just what got returned) - see
    app.evaluation.runner.compute_relevant_universe."""
    if not relevant_ids:
        return 1.0
    top = set(returned_ids[:k])
    return len(top & relevant_ids) / len(relevant_ids)


def hit_rate_at_k(returned_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if not relevant_ids:
        return 1.0
    return 1.0 if set(returned_ids[:k]) & relevant_ids else 0.0


def reciprocal_rank(returned_ids: list[str], relevant_ids: set[str]) -> float:
    for index, pid in enumerate(returned_ids, start=1):
        if pid in relevant_ids:
            return 1.0 / index
    return 0.0


def mrr(reciprocal_ranks: list[float]) -> float:
    if not reciprocal_ranks:
        return 0.0
    return sum(reciprocal_ranks) / len(reciprocal_ranks)


def dcg_at_k(graded_relevance_in_rank_order: list[float], k: int) -> float:
    total = 0.0
    for index, relevance in enumerate(graded_relevance_in_rank_order[:k], start=1):
        total += relevance / math.log2(index + 1)
    return total


def ndcg_at_k(returned_ids: list[str], relevance_grades: dict[str, float], k: int) -> float:
    """Section 17 - only meaningful when relevance_grades carries real,
    deliberately-graded relevance (not fabricated per Section 17's own
    warning). Returns 1.0 for a case with no graded-relevant items at all
    (nothing to rank wrong), matching hit_rate_at_k's vacuous-pass
    convention."""
    if not any(relevance_grades.values()):
        return 1.0
    actual = [relevance_grades.get(pid, 0.0) for pid in returned_ids[:k]]
    ideal = sorted(relevance_grades.values(), reverse=True)[:k]
    idcg = dcg_at_k(ideal, k)
    if idcg == 0.0:
        return 1.0
    return dcg_at_k(actual, k) / idcg


def duplicate_rate(ids: list[str]) -> float:
    """Section 23 - pagination/dedup invariant: fraction of entries that
    are repeats of an earlier entry in the same list."""
    if not ids:
        return 0.0
    seen: set[str] = set()
    duplicates = 0
    for pid in ids:
        if pid in seen:
            duplicates += 1
        else:
            seen.add(pid)
    return duplicates / len(ids)


def overlap_rate(list_a: list[str], list_b: list[str]) -> float:
    """Section 24/25 - primary vs cross-sell separation: fraction of
    list_b entries that also appear in list_a."""
    if not list_b:
        return 0.0
    set_a = set(list_a)
    return sum(1 for pid in list_b if pid in set_a) / len(list_b)
