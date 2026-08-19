"""
app/storage_paths.py  -  V2.12.1 Part A: single source of truth for where
runtime-written state lives.

Before this module, six separate places in the codebase (app/main.py,
app/embeddings.py, app/behavioral.py, app/fbt.py, app/learning_events.py)
each independently hardcoded `Path(tempfile.gettempdir()) / "foodland-ai-agent"`
as the default runtime directory - see docs/runtime-state-inventory.md.
That duplication meant there was no single knob to repoint every durable
write path at a persistent volume at once; forgetting even one env var
left that one piece of state silently resetting on every Railway
redeploy while the others persisted correctly.

`FOODLAND_DATA_DIR` is that single knob. When set (e.g. to a Railway
volume mount point such as `/data/foodland-ai-agent`), every *_PATH /
*_DIR env var in this codebase that does not have its own explicit
override resolves underneath it. When unset, behavior is byte-for-byte
identical to before this module existed (Path(tempfile.gettempdir()) /
"foodland-ai-agent") - this module changes nothing about local dev or
CI, only gives production one place to opt in to durability.

Per-variable overrides (e.g. RANKING_PROFILE_DIR, EVENTS_LOG_PATH) still
win over FOODLAND_DATA_DIR when set explicitly - this module never
removes the ability to point an individual path somewhere unrelated to
the rest.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def data_dir() -> Path:
    """The base directory every unpinned runtime path resolves under.

    Resolution order: explicit FOODLAND_DATA_DIR env var > the legacy
    tempdir-based default every runtime path used before this module
    existed. Never creates the directory - callers create it lazily on
    first write, same as before."""
    configured = os.getenv("FOODLAND_DATA_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "foodland-ai-agent"


def is_data_dir_configured() -> bool:
    """True when FOODLAND_DATA_DIR is explicitly set - i.e. runtime state
    is intentionally pointed at durable storage rather than defaulting to
    an ephemeral tempdir. Used by /health and startup validation to warn
    when production is running without it."""
    return bool(os.getenv("FOODLAND_DATA_DIR", "").strip())


def resolve_path(env_var: str, filename: str) -> Path:
    """Resolve a single runtime file path: explicit `env_var` override >
    `data_dir() / filename`. This is the pattern every *_LOG_PATH /
    *_PATH env var in app/main.py, app/embeddings.py, app/behavioral.py,
    app/fbt.py and app/learning_events.py should use instead of each
    hardcoding its own tempdir expression."""
    explicit = os.getenv(env_var, "").strip()
    if explicit:
        return Path(explicit)
    return data_dir() / filename


def resolve_dir(env_var: str, subdir: str, *, legacy_default: str) -> Path:
    """Resolve a directory-shaped runtime path (ranking profiles, learning
    history): explicit `env_var` override > (if FOODLAND_DATA_DIR is
    configured) `data_dir() / subdir` > `legacy_default` unchanged.

    The three-way order (rather than always falling back to data_dir())
    matters here specifically: RANKING_PROFILE_DIR and LEARNING_HISTORY_DIR
    default to git-tracked/repo-relative `config/...` paths today, not a
    tempdir. Local dev and CI never set FOODLAND_DATA_DIR, so this
    resolves to `legacy_default` exactly as before - only a production
    deployment that opts in to FOODLAND_DATA_DIR gets these repointed
    automatically alongside every other runtime path."""
    explicit = os.getenv(env_var, "").strip()
    if explicit:
        return Path(explicit)
    if is_data_dir_configured():
        return data_dir() / subdir
    return Path(legacy_default)
