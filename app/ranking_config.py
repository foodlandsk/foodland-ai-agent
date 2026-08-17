"""
app/ranking_config.py  -  V2.11 Ranking & Recommendation Optimization Engine:
versioned, validated ranking configuration.

V2.11's central invariant (Section 3/8/106): this module may only ever
change the ORDER of an already-eligible candidate set. It has no concept
of a product being valid or invalid - that stays entirely owned by V2.3
taxonomy / V2.4 retrieval / V2.8 recipe intelligence. Every weight here
scales an existing SOFT signal (behavioral CTR, merchandising, personal-
ization) that app.ranking.rank_candidates() already applies strictly
AFTER the hard l1-l4 priority tuple (taxonomy confidence, explicit
constraint hits, availability, lexical relevance) - so no matter how a
RankingProfile is tuned, a soft signal can never outrank a hard one.

A RankingProfile is a named, versioned, *validated* bundle of weights:
  - `behavioral_weight`      -> app.behavioral.behavioral_multiplier(weight=...)
  - `behavioral_min_ratio`/`behavioral_max_ratio` -> same function's clamp bounds
  - `merchandising_exponent` -> merchandising_multiplier(...) ** exponent
  - `personalization_cap`    -> ceiling applied to a personalization score
                                 before it contributes to the soft multiplier

`RankingWeights()` with no arguments reproduces EXACTLY the behavior
app.ranking.rank_candidates() already had before V2.11 (weight=1.0,
min/max ratio 0.5/2.0 - the same defaults app.behavioral.py itself uses,
merchandising_exponent=1.0 i.e. unchanged, personalization_cap=1.0 - the
same hardcoded ceiling the pre-V2.11 code applied). Passing
`ranking_profile=None` anywhere in the pipeline is therefore
behaviorally identical to passing the default profile (Section 106 -
this sprint changes what is *possible*, never today's actual output).

Versions are immutable once saved (Section 13/99-101): tuning a weight
means writing a NEW version file and repointing config/ranking_profiles/
active.json at it, never editing a version in place. That gives rollback
for free - flip active.json back to the previous version, restart
nothing, no code change.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path

CONFIG_DIR = Path(os.getenv("RANKING_PROFILE_DIR", "config/ranking_profiles"))
ACTIVE_POINTER_PATH = CONFIG_DIR / "active.json"

_VERSION_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")

# Bounds (Section 110/111 - a config outside these is rejected outright,
# never even reaching the optimizer's evaluation harness). Chosen wide
# enough to let real tuning happen, narrow enough that a deliberately
# extreme config (e.g. behavioral_weight=50) cannot possibly pass.
BEHAVIORAL_WEIGHT_BOUNDS = (0.0, 3.0)
BEHAVIORAL_MIN_RATIO_BOUNDS = (0.1, 1.0)
BEHAVIORAL_MAX_RATIO_BOUNDS = (1.0, 4.0)
MERCHANDISING_EXPONENT_BOUNDS = (0.0, 3.0)
PERSONALIZATION_CAP_BOUNDS = (0.0, 1.0)


class RankingProfileError(ValueError):
    """Raised when a RankingProfile fails validation or cannot be loaded."""


@dataclass(frozen=True)
class RankingWeights:
    behavioral_weight: float = 1.0
    behavioral_min_ratio: float = 0.5
    behavioral_max_ratio: float = 2.0
    merchandising_exponent: float = 1.0
    personalization_cap: float = 1.0

    def validate(self, *, label: str = "weights") -> None:
        checks = (
            ("behavioral_weight", self.behavioral_weight, BEHAVIORAL_WEIGHT_BOUNDS),
            ("behavioral_min_ratio", self.behavioral_min_ratio, BEHAVIORAL_MIN_RATIO_BOUNDS),
            ("behavioral_max_ratio", self.behavioral_max_ratio, BEHAVIORAL_MAX_RATIO_BOUNDS),
            ("merchandising_exponent", self.merchandising_exponent, MERCHANDISING_EXPONENT_BOUNDS),
            ("personalization_cap", self.personalization_cap, PERSONALIZATION_CAP_BOUNDS),
        )
        for field_name, value, (lo, hi) in checks:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise RankingProfileError(f"{label}.{field_name} must be numeric, got {value!r}")
            if not (lo <= value <= hi):
                raise RankingProfileError(f"{label}.{field_name}={value} outside allowed bounds [{lo}, {hi}]")
        if self.behavioral_min_ratio > self.behavioral_max_ratio:
            raise RankingProfileError(
                f"{label}.behavioral_min_ratio ({self.behavioral_min_ratio}) must be <= "
                f"behavioral_max_ratio ({self.behavioral_max_ratio})"
            )

    def to_dict(self) -> dict:
        return {
            "behavioral_weight": self.behavioral_weight,
            "behavioral_min_ratio": self.behavioral_min_ratio,
            "behavioral_max_ratio": self.behavioral_max_ratio,
            "merchandising_exponent": self.merchandising_exponent,
            "personalization_cap": self.personalization_cap,
        }

    @staticmethod
    def from_dict(data: dict) -> "RankingWeights":
        known = {f: data[f] for f in RankingWeights.__dataclass_fields__ if f in data}
        return RankingWeights(**known)


@dataclass(frozen=True)
class RankingProfile:
    version: str
    name: str
    default: RankingWeights = field(default_factory=RankingWeights)
    family_overrides: dict[str, RankingWeights] = field(default_factory=dict)
    description: str = ""

    def validate(self) -> None:
        if not _VERSION_RE.match(self.version):
            raise RankingProfileError(f"invalid profile version {self.version!r}")
        self.default.validate(label="default")
        for family, weights in self.family_overrides.items():
            if not family:
                raise RankingProfileError("family_overrides key must be a non-empty family/category id")
            weights.validate(label=f"family_overrides[{family}]")

    def weights_for(self, family: str | None) -> RankingWeights:
        """Category/family-specific override inheriting from `default`
        (Section 11/58) - any field the override does not set is not a
        thing here because RankingWeights is fully-specified; instead an
        override is a COMPLETE RankingWeights, built by `replace()`-ing
        default() so unspecified fields silently inherit the default's
        values (Section 12)."""
        if family and family in self.family_overrides:
            return self.family_overrides[family]
        return self.default

    def with_family_override(self, family: str, **weight_overrides) -> "RankingProfile":
        base = self.family_overrides.get(family, self.default)
        overrides = dict(self.family_overrides)
        overrides[family] = replace(base, **weight_overrides)
        return replace(self, family_overrides=overrides)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "default": self.default.to_dict(),
            "family_overrides": {family: w.to_dict() for family, w in self.family_overrides.items()},
        }

    @staticmethod
    def from_dict(data: dict) -> "RankingProfile":
        return RankingProfile(
            version=str(data["version"]),
            name=str(data.get("name", data["version"])),
            description=str(data.get("description", "")),
            default=RankingWeights.from_dict(data.get("default", {})),
            family_overrides={
                family: RankingWeights.from_dict(weights)
                for family, weights in (data.get("family_overrides") or {}).items()
            },
        )


DEFAULT_PROFILE = RankingProfile(version="v1", name="default", description="Pre-V2.11 behavior, unchanged.")
DEFAULT_PROFILE.validate()


# --- Versioned storage -----------------------------------------------------

def _profile_path(version: str) -> Path:
    if not _VERSION_RE.match(version):
        raise RankingProfileError(f"invalid profile version {version!r}")
    return CONFIG_DIR / f"{version}.json"


def save_ranking_profile(profile: RankingProfile, *, overwrite: bool = False) -> Path:
    """Versions are immutable (Section 99) - refuses to silently overwrite
    an existing version file unless `overwrite=True` is explicit."""
    profile.validate()
    path = _profile_path(profile.version)
    if path.exists() and not overwrite:
        raise RankingProfileError(f"ranking profile version {profile.version!r} already exists at {path} (immutable - use a new version)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def load_ranking_profile(version: str) -> RankingProfile:
    path = _profile_path(version)
    if not path.exists():
        raise RankingProfileError(f"no ranking profile version {version!r} at {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RankingProfileError(f"ranking profile {version!r} is not valid JSON: {exc}") from exc
    profile = RankingProfile.from_dict(data)
    profile.validate()
    return profile


def list_ranking_profile_versions() -> list[str]:
    if not CONFIG_DIR.exists():
        return []
    return sorted(p.stem for p in CONFIG_DIR.glob("*.json") if p.stem != "active")


def get_active_ranking_profile_version() -> str | None:
    if not ACTIVE_POINTER_PATH.exists():
        return None
    try:
        data = json.loads(ACTIVE_POINTER_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    version = data.get("active_version")
    return str(version) if version else None


def set_active_ranking_profile_version(version: str) -> None:
    """Rollback/activation is an atomic pointer swap (Section 14/59/60) -
    write-then-replace so a crash mid-write never leaves a half-written
    active.json."""
    if version not in list_ranking_profile_versions():
        raise RankingProfileError(f"cannot activate unknown ranking profile version {version!r}")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"active_version": version, "activated_at": time.time()}, indent=2, sort_keys=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(CONFIG_DIR), prefix=".active-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_path, ACTIVE_POINTER_PATH)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    clear_active_ranking_profile_cache()


# --- Active-profile resolution (cached, like get_merchandising_rules) -----

RANKING_PROFILE_CACHE_SECONDS = int(os.getenv("RANKING_PROFILE_CACHE_SECONDS", "60"))
_active_profile_cache: RankingProfile | None = None
_active_profile_cache_at: float = 0.0
_profile_override: RankingProfile | None = None


def clear_active_ranking_profile_cache() -> None:
    global _active_profile_cache, _active_profile_cache_at
    _active_profile_cache = None
    _active_profile_cache_at = 0.0


def get_active_ranking_profile() -> RankingProfile:
    """Resolution order (Section 106 - must never surprise a caller that
    passes nothing): an explicit `use_ranking_profile()` override (used by
    the optimizer/shadow tooling to evaluate a candidate in-process without
    touching persisted state) > the persisted active.json pointer > the
    built-in DEFAULT_PROFILE, which is what every caller got before V2.11
    existed."""
    if _profile_override is not None:
        return _profile_override

    global _active_profile_cache, _active_profile_cache_at
    now = time.time()
    if _active_profile_cache is not None and now - _active_profile_cache_at <= RANKING_PROFILE_CACHE_SECONDS:
        return _active_profile_cache

    version = get_active_ranking_profile_version()
    if version is None:
        profile = DEFAULT_PROFILE
    else:
        try:
            profile = load_ranking_profile(version)
        except RankingProfileError:
            profile = DEFAULT_PROFILE
    _active_profile_cache = profile
    _active_profile_cache_at = now
    return profile


@contextmanager
def use_ranking_profile(profile: RankingProfile | None):
    """Evaluate a candidate profile in-process (optimizer, shadow mode,
    tests) without ever touching config/ranking_profiles/active.json -
    real customer traffic on another worker is never affected (Section
    62/63 - shadow mode must not expose candidates to real customers)."""
    global _profile_override
    profile.validate() if profile is not None else None
    previous = _profile_override
    _profile_override = profile
    try:
        yield profile
    finally:
        _profile_override = previous
