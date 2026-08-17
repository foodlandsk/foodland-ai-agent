"""
tests/test_ranking_config.py  -  V2.11 RankingProfile model: validation,
versioned storage, active-profile resolution/rollback.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from app.ranking_config import (
    DEFAULT_PROFILE,
    RankingProfile,
    RankingProfileError,
    RankingWeights,
    get_active_ranking_profile,
    get_active_ranking_profile_version,
    list_ranking_profile_versions,
    load_ranking_profile,
    save_ranking_profile,
    set_active_ranking_profile_version,
    use_ranking_profile,
)


class TestDefaultProfileMatchesPreV211Behavior:
    def test_default_weights_reproduce_hardcoded_pre_v211_constants(self):
        # app.behavioral.behavioral_multiplier's own defaults were weight=1.0,
        # min_ratio=0.5, max_ratio=2.0 before V2.11 existed; app.ranking.py's
        # pre-V2.11 code hardcoded personalization cap at 1.0 and never scaled
        # merchandising_multiplier() at all (exponent=1.0 is a no-op power).
        weights = RankingWeights()
        assert weights.behavioral_weight == 1.0
        assert weights.behavioral_min_ratio == 0.5
        assert weights.behavioral_max_ratio == 2.0
        assert weights.merchandising_exponent == 1.0
        assert weights.personalization_cap == 1.0

    def test_default_profile_validates(self):
        DEFAULT_PROFILE.validate()


class TestValidation:
    @pytest.mark.parametrize("field,value", [
        ("behavioral_weight", -0.1),
        ("behavioral_weight", 3.1),
        ("behavioral_min_ratio", 0.0),
        ("behavioral_max_ratio", 4.1),
        ("merchandising_exponent", 3.5),
        ("personalization_cap", 1.5),
        ("personalization_cap", -0.1),
    ])
    def test_out_of_bounds_weight_rejected(self, field, value):
        weights = RankingWeights(**{field: value})
        with pytest.raises(RankingProfileError):
            weights.validate()

    def test_min_ratio_greater_than_max_ratio_rejected(self):
        weights = RankingWeights(behavioral_min_ratio=0.9, behavioral_max_ratio=0.5)
        with pytest.raises(RankingProfileError):
            weights.validate()

    def test_extreme_behavioral_weight_deliberately_rejected(self):
        """Section 110/111 - a deliberately unsafe candidate (huge behavioral
        weight) must be rejected, not silently clamped or accepted."""
        profile = RankingProfile(version="unsafe-v1", name="unsafe", default=RankingWeights(behavioral_weight=50.0))
        with pytest.raises(RankingProfileError):
            profile.validate()

    def test_invalid_version_string_rejected(self):
        profile = RankingProfile(version="not a valid version!!", name="x")
        with pytest.raises(RankingProfileError):
            profile.validate()

    def test_family_override_validated_too(self):
        profile = RankingProfile(
            version="v-bad-override", name="x",
            family_overrides={"rice": RankingWeights(personalization_cap=9.0)},
        )
        with pytest.raises(RankingProfileError):
            profile.validate()


class TestFamilyOverrideResolution:
    def test_no_override_falls_back_to_default(self):
        profile = RankingProfile(version="v-fam", name="x", default=RankingWeights(behavioral_weight=1.5))
        assert profile.weights_for("rice") == profile.default
        assert profile.weights_for(None) == profile.default

    def test_family_override_used_when_present(self):
        override = RankingWeights(behavioral_weight=2.0)
        profile = RankingProfile(version="v-fam2", name="x", family_overrides={"rice": override})
        assert profile.weights_for("rice") == override
        assert profile.weights_for("sauce") == profile.default  # unrelated family untouched

    def test_with_family_override_inherits_unspecified_fields_from_default(self):
        base = RankingProfile(version="v-fam3", name="x", default=RankingWeights(merchandising_exponent=1.5))
        updated = base.with_family_override("rice", behavioral_weight=2.0)
        rice_weights = updated.weights_for("rice")
        assert rice_weights.behavioral_weight == 2.0
        assert rice_weights.merchandising_exponent == 1.5  # inherited, not reset


class TestVersionedStorage:
    def test_save_then_load_roundtrips(self, tmp_path, monkeypatch):
        import app.ranking_config as rc
        monkeypatch.setattr(rc, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(rc, "ACTIVE_POINTER_PATH", tmp_path / "active.json")

        profile = RankingProfile(version="v-test1", name="test", default=RankingWeights(behavioral_weight=1.2))
        save_ranking_profile(profile)
        loaded = load_ranking_profile("v-test1")
        assert loaded.default.behavioral_weight == 1.2
        assert loaded.version == "v-test1"

    def test_versions_are_immutable_by_default(self, tmp_path, monkeypatch):
        import app.ranking_config as rc
        monkeypatch.setattr(rc, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(rc, "ACTIVE_POINTER_PATH", tmp_path / "active.json")

        profile = RankingProfile(version="v-immutable", name="test")
        save_ranking_profile(profile)
        with pytest.raises(RankingProfileError):
            save_ranking_profile(profile)  # no overwrite=True

    def test_list_versions(self, tmp_path, monkeypatch):
        import app.ranking_config as rc
        monkeypatch.setattr(rc, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(rc, "ACTIVE_POINTER_PATH", tmp_path / "active.json")

        save_ranking_profile(RankingProfile(version="v-a", name="a"))
        save_ranking_profile(RankingProfile(version="v-b", name="b"))
        assert list_ranking_profile_versions() == ["v-a", "v-b"]

    def test_load_unknown_version_raises(self, tmp_path, monkeypatch):
        import app.ranking_config as rc
        monkeypatch.setattr(rc, "CONFIG_DIR", tmp_path)
        with pytest.raises(RankingProfileError):
            load_ranking_profile("does-not-exist")


class TestActivationAndRollback:
    def _isolate(self, tmp_path, monkeypatch):
        import app.ranking_config as rc
        monkeypatch.setattr(rc, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(rc, "ACTIVE_POINTER_PATH", tmp_path / "active.json")
        rc.clear_active_ranking_profile_cache()
        return rc

    def test_activate_unknown_version_raises(self, tmp_path, monkeypatch):
        self._isolate(tmp_path, monkeypatch)
        with pytest.raises(RankingProfileError):
            set_active_ranking_profile_version("nope")

    def test_activate_then_get_active_version(self, tmp_path, monkeypatch):
        self._isolate(tmp_path, monkeypatch)
        save_ranking_profile(RankingProfile(version="v-x", name="x"))
        set_active_ranking_profile_version("v-x")
        assert get_active_ranking_profile_version() == "v-x"

    def test_rollback_is_just_activating_an_older_version(self, tmp_path, monkeypatch):
        rc = self._isolate(tmp_path, monkeypatch)
        save_ranking_profile(RankingProfile(version="v-old", name="old", default=RankingWeights(behavioral_weight=1.0)))
        save_ranking_profile(RankingProfile(version="v-new", name="new", default=RankingWeights(behavioral_weight=2.0)))
        set_active_ranking_profile_version("v-old")
        set_active_ranking_profile_version("v-new")
        assert get_active_ranking_profile().default.behavioral_weight == 2.0

        # Rollback: repoint at v-old, no code change, no file edit of v-new.
        set_active_ranking_profile_version("v-old")
        rc.clear_active_ranking_profile_cache()
        assert get_active_ranking_profile().default.behavioral_weight == 1.0

    def test_get_active_profile_falls_back_to_default_when_nothing_activated(self, tmp_path, monkeypatch):
        self._isolate(tmp_path, monkeypatch)
        assert get_active_ranking_profile() is DEFAULT_PROFILE


class TestUseRankingProfileOverride:
    def test_override_takes_effect_and_is_restored(self):
        candidate = RankingProfile(version="v-override", name="override", default=RankingWeights(behavioral_weight=2.5))
        assert get_active_ranking_profile() is not candidate
        with use_ranking_profile(candidate):
            assert get_active_ranking_profile() is candidate
        assert get_active_ranking_profile() is not candidate

    def test_invalid_profile_rejected_by_context_manager(self):
        bad = RankingProfile(version="v-bad", name="bad", default=RankingWeights(behavioral_weight=99.0))
        with pytest.raises(RankingProfileError):
            with use_ranking_profile(bad):
                pass

    def test_nested_override_restores_outer_override(self):
        outer = RankingProfile(version="v-outer", name="outer")
        inner = RankingProfile(version="v-inner", name="inner")
        with use_ranking_profile(outer):
            with use_ranking_profile(inner):
                assert get_active_ranking_profile() is inner
            assert get_active_ranking_profile() is outer
