"""
app/ranking_features.py  -  V2.11: explainable per-candidate ranking features.

A pure, read-only computation over the same signals app.ranking.rank_candidates()
already consults - this module does not introduce a NEW signal (Section 6 -
"do not duplicate existing signals"), it names and exposes the ones that
already exist so a human (CLI drilldown, Section 79/80) or a program
(the optimizer, shadow mode) can see WHY one product outranked another,
not just that it did.

RankingFeatures mirrors app.ranking.rank_candidates()'s sort key exactly:
    (-l1_confidence, -l2_explicit_hits, -l3_availability, -l4_relevance, -soft, product_id)
so `explain_candidates()` output is always consistent with the actual
ranking a query would receive - it is computed FROM the same helper
functions app.ranking uses, never a second reimplementation of them.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.behavioral import behavioral_multiplier
from app.merchandising import merchandising_multiplier
from app.ranking import _CONFIDENCE_RANK, _explicit_attribute_hits, _in_stock, _relevance_score
from app.ranking_config import RankingWeights


@dataclass(frozen=True)
class RankingFeatures:
    product_id: str
    l1_confidence: int
    l2_explicit_hits: int
    l3_availability: int
    l4_relevance: int
    behavioral_multiplier: float
    merchandising_multiplier: float
    personalization_multiplier: float
    soft_score: float

    @property
    def sort_key(self) -> tuple:
        return (
            -self.l1_confidence,
            -self.l2_explicit_hits,
            -self.l3_availability,
            -self.l4_relevance,
            -self.soft_score,
            self.product_id,
        )

    def explain(self) -> str:
        """One-line, human-readable breakdown for CLI drilldown (Section
        15/79/80) - hard signals first (these alone decide the outcome
        whenever two candidates differ on any of them), soft signals last."""
        return (
            f"{self.product_id}: "
            f"confidence={self.l1_confidence} explicit_hits={self.l2_explicit_hits} "
            f"in_stock={self.l3_availability} relevance={self.l4_relevance} "
            f"| soft={self.soft_score:.4f} "
            f"(behavioral={self.behavioral_multiplier:.4f} x "
            f"merchandising={self.merchandising_multiplier:.4f} x "
            f"personalization={self.personalization_multiplier:.4f})"
        )


def compute_ranking_features(
    product_id: str,
    query,
    products_by_id: dict,
    index,
    normalized_index: dict,
    *,
    query_tokens: frozenset,
    weights: RankingWeights | None = None,
    behavioral_rankings: dict | None = None,
    merchandising_rules: dict | None = None,
    personalization_scores: dict[str, float] | None = None,
) -> RankingFeatures:
    weights = weights or RankingWeights()
    product = products_by_id.get(product_id)
    if product is None:
        return RankingFeatures(product_id, -1, -1, -1, -1, 1.0, 1.0, 1.0, 0.0)

    l1_confidence = _CONFIDENCE_RANK.get(index.confidence_by_id.get(product_id, "UNKNOWN"), 0)
    l2_explicit_hits = _explicit_attribute_hits(product_id, query, index, normalized_index)
    l3_availability = 1 if _in_stock(product) else 0
    l4_relevance = _relevance_score(product, query_tokens)

    behavioral = 1.0
    if behavioral_rankings and behavioral_rankings.get("active"):
        behavioral = behavioral_multiplier(
            product_id,
            behavioral_rankings["scores"],
            behavioral_rankings["baseline_ctr"],
            weights.behavioral_weight,
            weights.behavioral_min_ratio,
            weights.behavioral_max_ratio,
        )

    merchandising = 1.0
    if merchandising_rules:
        raw = merchandising_multiplier(
            str(getattr(product, "brand", "")),
            str(getattr(product, "product_type", "")),
            merchandising_rules,
        )
        merchandising = raw ** weights.merchandising_exponent if raw > 0 else raw

    personalization = 1.0
    if personalization_scores:
        capped = max(0.0, min(weights.personalization_cap, personalization_scores.get(product_id, 0.0)))
        personalization = 1.0 + capped

    soft_score = behavioral * merchandising * personalization

    return RankingFeatures(
        product_id=product_id,
        l1_confidence=l1_confidence,
        l2_explicit_hits=l2_explicit_hits,
        l3_availability=l3_availability,
        l4_relevance=l4_relevance,
        behavioral_multiplier=behavioral,
        merchandising_multiplier=merchandising,
        personalization_multiplier=personalization,
        soft_score=soft_score,
    )


def explain_candidates(
    candidate_ids: list[str],
    query,
    products_by_id: dict,
    index,
    normalized_index: dict,
    *,
    weights: RankingWeights | None = None,
    behavioral_rankings: dict | None = None,
    merchandising_rules: dict | None = None,
    personalization_scores: dict[str, float] | None = None,
) -> list[RankingFeatures]:
    """Returns every candidate's RankingFeatures, already sorted in the
    same order app.ranking.rank_candidates() would rank them (Section 15) -
    the drilldown a human reads and the order a customer would actually
    see are always the same computation, never two."""
    from app.search import tokenize

    query_tokens = frozenset(tokenize(getattr(query, "raw_query", "") or "")) if getattr(query, "raw_query", "") else frozenset()
    features = [
        compute_ranking_features(
            pid, query, products_by_id, index, normalized_index,
            query_tokens=query_tokens,
            weights=weights,
            behavioral_rankings=behavioral_rankings,
            merchandising_rules=merchandising_rules,
            personalization_scores=personalization_scores,
        )
        for pid in candidate_ids
    ]
    return sorted(features, key=lambda f: f.sort_key)
