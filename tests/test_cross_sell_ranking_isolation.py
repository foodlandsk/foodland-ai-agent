"""
tests/test_cross_sell_ranking_isolation.py  -  V2.11 Section 34-38: cross-sell
ranking must stay architecturally separate from primary (app.ranking)
ranking. This was already true going into V2.11 (app.cross_sell has its
own CrossSellCandidate/rank_candidates()/build_cross_sell()) - these tests
make that separation an explicit, enforced contract rather than an
implicit fact nothing checks.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.cross_sell as cross_sell
import app.ranking as ranking
from app.cross_sell import CrossSellCandidate, rank_candidates as cross_sell_rank_candidates
from app.ranking import rank_candidates as primary_rank_candidates


class TestDistinctFunctions:
    def test_cross_sell_rank_candidates_is_not_primary_rank_candidates(self):
        assert cross_sell_rank_candidates is not primary_rank_candidates
        assert cross_sell.rank_candidates.__module__ == "app.cross_sell"
        assert ranking.rank_candidates.__module__ == "app.ranking"

    def test_cross_sell_rank_candidates_has_no_ranking_profile_parameter(self):
        """V2.11's RankingProfile/behavioral/merchandising/personalization
        machinery is a primary-ranking concept only - cross-sell's own
        scoring (role priority + curated/FBT evidence bonuses) is untouched
        by it, by construction (Section 34/35)."""
        sig = inspect.signature(cross_sell_rank_candidates)
        assert "ranking_profile" not in sig.parameters
        assert "behavioral_rankings" not in sig.parameters
        assert "merchandising_rules" not in sig.parameters
        assert "personalization_scores" not in sig.parameters


class TestCrossSellOrderingIsScoreOnly:
    def test_sorted_by_score_desc_then_product_id_asc(self):
        candidates = [
            CrossSellCandidate(product_id="FL_B", role="sauce", score=1.0),
            CrossSellCandidate(product_id="FL_A", role="sauce", score=2.0),
            CrossSellCandidate(product_id="FL_C", role="topping", score=2.0),
        ]
        ranked = cross_sell_rank_candidates(candidates)
        assert [c.product_id for c in ranked] == ["FL_A", "FL_C", "FL_B"]

    def test_ranking_profile_import_does_not_affect_cross_sell_module(self):
        """Sanity check that app.cross_sell was not accidentally wired to
        app.ranking_config during V2.11 - the two ranking systems' config
        surfaces must stay separate (Section 111 of the V2.11 spec)."""
        assert "ranking_config" not in dir(cross_sell) or not hasattr(cross_sell, "RankingProfile")
