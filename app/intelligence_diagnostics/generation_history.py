"""
app/intelligence_diagnostics/generation_history.py  -  V2.18b immutable
generation score snapshots.

Append-only JSONL, same storage discipline app.customer_audit/
app.customer_qa already established: resolve_path() so production
follows FOODLAND_DATA_DIR automatically, one bounded record per
generation, malformed rows skipped safely on read. A generation is
NEVER rewritten in place (Section 41) - if an evaluator bug invalidates
one, `invalidate_generation()` appends a NEW record referencing the old
generation_id with reason="INVALIDATED: ...", the original stays exactly
as it was written.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

from app.storage_paths import resolve_path

logger = logging.getLogger(__name__)

_LOG_ENV_VAR = "INTELLIGENCE_GENERATION_LOG_PATH"
_LOG_FILENAME = "intelligence_generations.jsonl"

BENCHMARK_VERSION = "V2.18a-c.1"
MUTATION_ENGINE_VERSION = "1"
EVALUATOR_VERSION = "1"


def _log_path() -> Path:
    return resolve_path(_LOG_ENV_VAR, _LOG_FILENAME)


def _generation_id(git_sha: str, ts: int) -> str:
    return hashlib.sha256(f"{git_sha}:{ts}:{BENCHMARK_VERSION}".encode("utf-8")).hexdigest()[:24]


def build_generation_record(
    *,
    git_sha: str,
    scenario_count: int,
    scored_scenario_count: int,
    pending_ground_truth_count: int,
    mutation_count: int,
    capability_scores: dict,
    overall_score: float | None,
    pass_count: int,
    fail_count: int,
    unknown_count: int,
    new_failures: list[str],
    existing_failures: list[str],
    closed_regressions: list[str],
) -> dict:
    ts = int(time.time())
    return {
        "generation_id": _generation_id(git_sha, ts),
        "ts": ts,
        "git_sha": git_sha,
        "benchmark_version": BENCHMARK_VERSION,
        "mutation_engine_version": MUTATION_ENGINE_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "scenario_count": scenario_count,
        "scored_scenario_count": scored_scenario_count,
        "pending_ground_truth_count": pending_ground_truth_count,
        "mutation_count": mutation_count,
        "capability_scores": capability_scores,
        "overall_score": overall_score,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "unknown_count": unknown_count,
        "new_failures": new_failures,
        "existing_failures": existing_failures,
        "closed_regressions": closed_regressions,
        "invalidated": False,
        "invalidates_generation_id": None,
    }


def record_generation(record: dict) -> None:
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def invalidate_generation(generation_id: str, reason: str) -> dict:
    """Appends a NEW record marking `generation_id` invalidated - never
    rewrites the original line (Section 41)."""
    ts = int(time.time())
    record = {
        "generation_id": hashlib.sha256(f"invalidate:{generation_id}:{ts}".encode("utf-8")).hexdigest()[:24],
        "ts": ts,
        "invalidated": True,
        "invalidates_generation_id": generation_id,
        "reason": reason,
    }
    record_generation(record)
    return record


def read_generations(limit: int = 100) -> list[dict]:
    path = _log_path()
    if not path.exists():
        return []
    records: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        logger.warning("Failed to read intelligence generation log %s", path, exc_info=True)
        return []
    records.sort(key=lambda r: r.get("ts", 0))
    return records[-limit:]


def diff_scenario_ids(previous_ids: set[str], current_ids: set[str]) -> dict:
    return {
        "added": sorted(current_ids - previous_ids),
        "removed": sorted(previous_ids - current_ids),
        "unchanged": sorted(previous_ids & current_ids),
    }
