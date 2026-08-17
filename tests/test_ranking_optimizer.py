"""
tests/test_ranking_optimizer.py  -  V2.11 bounded offline optimizer.

Uses the real app.main / app.evaluation harness (same fixture data/products.json
every run, Section 45) in --fast (critical-cases-only) mode to keep runtime
reasonable while still proving the optimizer's safety net actually works
against the real pipeline, not a mock.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import pytest

from app.ranking_config import DEFAULT_PROFILE, RankingProfile, RankingWeights
from app.ranking_optimizer import evaluate_profile, generate_candidate_profiles, optimize


class TestGenerateCandidateProfiles:
    def test_candidates_stay_within_validated_bounds(self):
        candidates = generate_candidate_profiles(DEFAULT_PROFILE, 20, seed=42)
        for candidate in candidates:
            candidate.validate()  # raises if any field is out of bounds

    def test_deterministic_given_same_seed(self):
        a = generate_candidate_profiles(DEFAULT_PROFILE, 5, seed=7)
        b = generate_candidate_profiles(DEFAULT_PROFILE, 5, seed=7)
        assert [c.default.to_dict() for c in a] == [c.default.to_dict() for c in b]

    def test_different_seeds_produce_different_candidates(self):
        a = generate_candidate_profiles(DEFAULT_PROFILE, 5, seed=1)
        b = generate_candidate_profiles(DEFAULT_PROFILE, 5, seed=2)
        assert [c.default.to_dict() for c in a] != [c.default.to_dict() for c in b]

    def test_min_ratio_never_exceeds_max_ratio(self):
        candidates = generate_candidate_profiles(DEFAULT_PROFILE, 30, seed=99)
        for candidate in candidates:
            assert candidate.default.behavioral_min_ratio <= candidate.default.behavioral_max_ratio


class TestEvaluateProfileRejectsUnsafeConfigs:
    """Section 110-112 - deliberately unsafe candidate configs must be
    provably rejected by the quality-gate machinery, not just by hoping
    the optimizer never generates one."""

    def test_out_of_bounds_behavioral_weight_rejected_without_running_suite(self):
        unsafe = RankingProfile(version="unsafe-behavioral", name="unsafe", default=RankingWeights(behavioral_weight=50.0))
        result = evaluate_profile(unsafe, fast=True)
        assert result.rejected is True
        assert "behavioral_weight" in result.rejection_reason

    def test_out_of_bounds_personalization_cap_rejected(self):
        unsafe = RankingProfile(version="unsafe-personalization", name="unsafe", default=RankingWeights(personalization_cap=8.0))
        result = evaluate_profile(unsafe, fast=True)
        assert result.rejected is True

    def test_out_of_bounds_merchandising_exponent_rejected(self):
        unsafe = RankingProfile(version="unsafe-merch", name="unsafe", default=RankingWeights(merchandising_exponent=9.0))
        result = evaluate_profile(unsafe, fast=True)
        assert result.rejected is True

    def test_valid_but_extreme_config_still_runs_through_real_harness(self):
        """A config at the EDGE of the valid range (not out-of-bounds) must
        still be evaluated through the real pipeline, not short-circuited -
        the bounds check is the first safety net, the evaluation gate is
        the second, and this proves the second net is actually reachable."""
        extreme = RankingProfile(
            version="extreme-but-valid",
            name="extreme",
            default=RankingWeights(behavioral_weight=3.0, behavioral_min_ratio=0.1, behavioral_max_ratio=4.0,
                                    merchandising_exponent=3.0, personalization_cap=1.0),
        )
        result = evaluate_profile(extreme, fast=True)
        assert result.summary  # actually ran, not short-circuited
        assert "golden" in result.summary

    def test_default_profile_is_not_rejected(self):
        result = evaluate_profile(DEFAULT_PROFILE, fast=True)
        assert result.rejected is False
        assert result.gate["gate"] in {"PASS", "WARN"}


class TestOptimizeHonestlyReportsNoImprovement:
    def test_optimize_never_recommends_a_rejected_candidate(self):
        result = optimize(DEFAULT_PROFILE, n_candidates=4, seed=3, fast=True)
        if result["improved"]:
            assert result["best_candidate_profile"] is not None
            assert result["best_candidate_profile"].version == result["recommendation"]["version"]
        else:
            assert result["recommendation"]["version"] == DEFAULT_PROFILE.version
            assert result["best_candidate_profile"] is None

    def test_optimize_is_deterministic_given_seed(self):
        a = optimize(DEFAULT_PROFILE, n_candidates=3, seed=11, fast=True)
        b = optimize(DEFAULT_PROFILE, n_candidates=3, seed=11, fast=True)
        assert a["recommendation"] == b["recommendation"]
        assert a["n_rejected"] == b["n_rejected"]
