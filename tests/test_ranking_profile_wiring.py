"""
tests/test_ranking_profile_wiring.py  -  V2.11: RankingProfile threaded
through app.ranking.rank_candidates() and app.ranking_features must never
change default (pre-V2.11) behavior, and must never let a soft signal
outrank a hard one regardless of how a profile is tuned.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.feed import Product
from app.product_normalizer import normalize_catalog
from app.query_constraints import parse_structured_query
from app.ranking import rank_candidates
from app.ranking_config import DEFAULT_PROFILE, RankingProfile, RankingWeights
from app.ranking_features import compute_ranking_features, explain_candidates
from app.retrieval import get_structured_index, retrieve_products
from app.search import tokenize
from app.taxonomy import build_taxonomy_index


def make_product(**overrides) -> Product:
    base = dict(
        id="FL_TEST", title="", description="", product_type="", link="",
        image_link="", price=10.0, sale_price=None, currency="EUR", brand="",
        availability="in_stock", gtin="", unit_pricing_measure="",
    )
    base.update(overrides)
    return Product(**base)


def build_catalog() -> list[Product]:
    return [
        make_product(id="FL_R1", title="Jazmínová ryža FOODLAND 5 kg", product_type="Ryža > Jazmínová ryža",
                     brand="FOODLAND", unit_pricing_measure="5 kg"),
        make_product(id="FL_R2", title="Jazmínová ryža FOODLAND 1 kg", product_type="Ryža > Jazmínová ryža",
                     brand="FOODLAND", unit_pricing_measure="1 kg"),
        make_product(id="FL_R3", title="Jazmínová ryža LAILA 1 kg", product_type="Ryža > Jazmínová ryža",
                     brand="LAILA", unit_pricing_measure="1 kg"),
    ]


CATALOG = build_catalog()
TAXONOMY_INDEX = build_taxonomy_index(CATALOG)
NORMALIZED_INDEX = normalize_catalog(CATALOG)
INDEX = get_structured_index(CATALOG, TAXONOMY_INDEX, NORMALIZED_INDEX)
PRODUCTS_BY_ID = {p.id: p for p in CATALOG}


def retrieve(text: str):
    query = parse_structured_query(text, known_brands=INDEX.known_brands)
    return query, retrieve_products(query, INDEX)


BEHAVIORAL = {
    "active": True,
    "baseline_ctr": 0.05,
    "scores": {"FL_R1": {"ctr": 0.5}},  # far above baseline -> big popularity boost for FL_R1
}
MERCHANDISING = {"boosts": [{"brand": "LAILA", "multiplier": 1.5}], "campaigns": []}
PERSONALIZATION = {"FL_R3": 1.0}


class TestDefaultProfilePreservesPreV211Behavior:
    def test_none_profile_and_default_profile_produce_identical_order(self):
        query, result = retrieve("jazminova ryza")
        without_profile = rank_candidates(
            list(result.valid_match_ids), query, PRODUCTS_BY_ID, INDEX, NORMALIZED_INDEX,
            behavioral_rankings=BEHAVIORAL, merchandising_rules=MERCHANDISING, personalization_scores=PERSONALIZATION,
        )
        with_default_profile = rank_candidates(
            list(result.valid_match_ids), query, PRODUCTS_BY_ID, INDEX, NORMALIZED_INDEX,
            behavioral_rankings=BEHAVIORAL, merchandising_rules=MERCHANDISING, personalization_scores=PERSONALIZATION,
            ranking_profile=DEFAULT_PROFILE,
        )
        assert without_profile == with_default_profile

    def test_none_profile_matches_explicit_default_weights_profile(self):
        explicit_default = RankingProfile(version="v-explicit", name="explicit", default=RankingWeights())
        query, result = retrieve("jazminova ryza")
        a = rank_candidates(list(result.valid_match_ids), query, PRODUCTS_BY_ID, INDEX, NORMALIZED_INDEX,
                             behavioral_rankings=BEHAVIORAL)
        b = rank_candidates(list(result.valid_match_ids), query, PRODUCTS_BY_ID, INDEX, NORMALIZED_INDEX,
                             behavioral_rankings=BEHAVIORAL, ranking_profile=explicit_default)
        assert a == b


class TestProfileChangesSoftOrderOnly:
    def test_behavioral_weight_zero_neutralizes_popularity_boost(self):
        query, result = retrieve("jazminova ryza")
        neutral = RankingProfile(version="v-neutral", name="neutral", default=RankingWeights(behavioral_weight=0.0))
        ranked = rank_candidates(
            list(result.valid_match_ids), query, PRODUCTS_BY_ID, INDEX, NORMALIZED_INDEX,
            behavioral_rankings=BEHAVIORAL, ranking_profile=neutral,
        )
        # With weight=0, behavioral_multiplier degenerates to 1.0 for every
        # candidate - order falls back to id tie-break among ties.
        default_ranked = rank_candidates(
            list(result.valid_match_ids), query, PRODUCTS_BY_ID, INDEX, NORMALIZED_INDEX,
        )
        assert ranked == sorted(result.valid_match_ids)
        assert set(ranked) == set(default_ranked)

    def test_higher_behavioral_weight_amplifies_popularity_reordering(self):
        query, result = retrieve("jazminova ryza")
        strong = RankingProfile(version="v-strong", name="strong", default=RankingWeights(behavioral_weight=3.0))
        ranked = rank_candidates(
            list(result.valid_match_ids), query, PRODUCTS_BY_ID, INDEX, NORMALIZED_INDEX,
            behavioral_rankings=BEHAVIORAL, ranking_profile=strong,
        )
        # FL_R1 has the strong CTR boost - with weight=3.0 (vs default 1.0)
        # it should rank at least as well as under the default profile.
        default_ranked = rank_candidates(
            list(result.valid_match_ids), query, PRODUCTS_BY_ID, INDEX, NORMALIZED_INDEX,
            behavioral_rankings=BEHAVIORAL,
        )
        assert ranked.index("FL_R1") <= default_ranked.index("FL_R1")

    def test_personalization_cap_bounds_the_soft_multiplier(self):
        query, result = retrieve("jazminova ryza")
        capped = RankingProfile(version="v-capped", name="capped", default=RankingWeights(personalization_cap=0.1))
        uncapped = RankingProfile(version="v-uncapped", name="uncapped", default=RankingWeights(personalization_cap=1.0))
        personalization = {"FL_R3": 1.0}

        f_capped = compute_ranking_features(
            "FL_R3", query, PRODUCTS_BY_ID, INDEX, NORMALIZED_INDEX,
            query_tokens=frozenset(tokenize(query.raw_query)),
            weights=capped.weights_for(None), personalization_scores=personalization,
        )
        f_uncapped = compute_ranking_features(
            "FL_R3", query, PRODUCTS_BY_ID, INDEX, NORMALIZED_INDEX,
            query_tokens=frozenset(tokenize(query.raw_query)),
            weights=uncapped.weights_for(None), personalization_scores=personalization,
        )
        assert f_capped.personalization_multiplier < f_uncapped.personalization_multiplier
        assert f_capped.personalization_multiplier == 1.1  # 1.0 + min(0.1, 1.0)
        assert f_uncapped.personalization_multiplier == 2.0  # 1.0 + min(1.0, 1.0)

    def test_merchandising_exponent_zero_neutralizes_brand_boost(self):
        query, result = retrieve("jazminova ryza")
        neutral = RankingWeights(merchandising_exponent=0.0)
        f = compute_ranking_features(
            "FL_R3", query, PRODUCTS_BY_ID, INDEX, NORMALIZED_INDEX,
            query_tokens=frozenset(tokenize(query.raw_query)),
            weights=neutral, merchandising_rules=MERCHANDISING,
        )
        assert f.merchandising_multiplier == 1.0  # 1.5 ** 0 == 1.0


class TestExplicitConstraintOutranksSoftSignals:
    """Central V2.11 invariant (Section 3/8/9): no matter how extreme the
    soft-signal weights, an explicit hard constraint (brand/size match)
    must still win."""

    def test_extreme_personalization_cannot_beat_explicit_brand_match(self):
        query, result = retrieve("foodland jazminova ryza")  # explicit brand: FOODLAND
        assert set(result.exact_match_ids) == {"FL_R1", "FL_R2"}
        candidates = list(result.exact_match_ids) + ["FL_R3"]
        extreme_personalization = {"FL_R3": 1.0}  # LAILA - maximum personalization affinity
        extreme_profile = RankingProfile(version="v-extreme", name="extreme", default=RankingWeights(personalization_cap=1.0))
        ranked = rank_candidates(
            candidates, query, PRODUCTS_BY_ID, INDEX, NORMALIZED_INDEX,
            personalization_scores=extreme_personalization, ranking_profile=extreme_profile,
        )
        # FL_R3 has zero explicit brand hits (not FOODLAND) - it must rank
        # after both FOODLAND products regardless of personalization weight.
        assert ranked.index("FL_R3") > ranked.index("FL_R1")
        assert ranked.index("FL_R3") > ranked.index("FL_R2")


class TestExplainCandidatesMatchesActualRankOrder:
    def test_explain_candidates_order_matches_rank_candidates_order(self):
        query, result = retrieve("jazminova ryza")
        ranked = rank_candidates(
            list(result.valid_match_ids), query, PRODUCTS_BY_ID, INDEX, NORMALIZED_INDEX,
            behavioral_rankings=BEHAVIORAL, merchandising_rules=MERCHANDISING, personalization_scores=PERSONALIZATION,
        )
        features = explain_candidates(
            list(result.valid_match_ids), query, PRODUCTS_BY_ID, INDEX, NORMALIZED_INDEX,
            behavioral_rankings=BEHAVIORAL, merchandising_rules=MERCHANDISING, personalization_scores=PERSONALIZATION,
        )
        assert [f.product_id for f in features] == ranked
