"""
app/durable_storage.py  -  V2.12.1 Part A: shared atomic-write primitive.

Before this module, the codebase had two independent, correct
implementations of the same temp-file-then-os.replace() pattern
(app/ranking_config.py:set_active_ranking_profile_version,
app/learning_lifecycle.py:_atomic_write_json) and one durable JSON writer
(app/main.py's USER_MEMORY_PATH) that used a plain write_text() overwrite
with no atomicity at all - see docs/runtime-state-inventory.md finding 4.
This module gives every durable JSON/text writer in the codebase one
tested implementation instead of three independently-maintained copies.

The guarantee: a crash or container kill mid-write never leaves the
target path holding a partially-written (torn) file. Either the old
content is still there, or the complete new content is - never a mix.
This is achieved by writing to a temp file in the SAME directory as the
target (so the final os.replace() is on the same filesystem and
therefore atomic) and only replacing the target once the temp file is
fully written and flushed.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write `content` to `path` such that any reader either sees the
    complete previous content or the complete new content - never a
    partial write, regardless of when a crash/kill happens."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def atomic_write_json(path: Path, payload: Any, *, indent: int = 2, sort_keys: bool = True) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=indent, sort_keys=sort_keys),
    )
