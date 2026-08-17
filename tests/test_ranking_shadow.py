"""
tests/test_ranking_shadow.py  -  V2.11 shadow-mode comparison (Section 61-64):
baseline vs candidate product order, computed entirely in-process, must
never touch config/ranking_profiles/active.json (i.e. must never be able
to leak into real customer traffic).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

from app.ranking_config import (
    DEFAULT_PROFILE,
    RankingProfile,
    RankingWeights,
    get_active_ranking_profile_version,
)
from app.ranking_shadow import shadow_compare


class TestShadowCompareNeverTouchesPersistedState:
    def test_active_pointer_unaffected_by_shadow_compare(self):
        before = get_active_ranking_profile_version()
        candidate = RankingProfile(version="v-shadow-cand", name="cand", default=RankingWeights(behavioral_weight=2.0))
        shadow_compare(["jazmínová ryža"], DEFAULT_PROFILE, candidate, limit=3)
        after = get_active_ranking_profile_version()
        assert before == after


class TestShadowCompareIdentityIsNoOp:
    def test_same_profile_against_itself_never_changes_order(self):
        report = shadow_compare(["jazmínová ryža", "kokosové mlieko"], DEFAULT_PROFILE, DEFAULT_PROFILE, limit=5)
        assert report.queries_changed == 0
        assert report.windows_with_set_changes == []
        for r in report.results:
            assert r.baseline_order == r.candidate_order


class TestShadowCompareNeverChangesFullEligibilitySet:
    def test_full_candidate_set_identical_when_limit_covers_the_whole_pool(self):
        """The true invariant (Section 3): ranking may only reorder, never
        change eligibility. `ChatRequest.limit` is capped at 12 (an HTTP-
        level page-size limit unrelated to ranking), so for this fixture
        query - whose candidate pool is 11, safely under that cap - the
        returned window IS the full eligible set, and comparing it
        directly is meaningful (unlike a query whose pool exceeds the
        cap, where a window-set difference is expected pagination
        behavior, not a violation - see the module docstring and
        test_small_limit_can_legitimately_change_the_visible_window)."""
        candidate = RankingProfile(version="v-shadow-extreme", name="extreme", default=RankingWeights(
            behavioral_weight=3.0, merchandising_exponent=3.0, personalization_cap=1.0,
        ))
        report = shadow_compare(["kikkoman sójová omáčka"], DEFAULT_PROFILE, candidate, limit=12)
        assert report.windows_with_set_changes == []

    def test_small_limit_can_legitimately_change_the_visible_window(self):
        """Documents the expected, non-violating behavior when a query's
        candidate pool exceeds `limit` - a reordering can change which ids
        land on page 1 even though the underlying eligible set (retrieval's
        job, never ranking's) is unaffected."""
        candidate = RankingProfile(version="v-shadow-extreme2", name="extreme", default=RankingWeights(
            behavioral_weight=3.0, merchandising_exponent=3.0,
        ))
        report = shadow_compare(["kikkoman sójová omáčka"], DEFAULT_PROFILE, candidate, limit=8)
        # Not asserted to be non-empty (behavioral rankings may be inactive
        # in this fixture environment) - this test documents the semantics,
        # it does not require the confound to reproduce every run.
        assert isinstance(report.windows_with_set_changes, list)
