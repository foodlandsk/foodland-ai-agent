"""
scripts/run_learning_cycle.py  -  V2.12 Controlled Auto-Learning CLI

Usage:
    python scripts/run_learning_cycle.py                 # default lookback, fast eval
    python scripts/run_learning_cycle.py --full           # full V2.10 suite per candidate
    python scripts/run_learning_cycle.py --days 60
    python scripts/run_learning_cycle.py --no-shadow       # skip shadow stage

Thin wrapper - all orchestration logic lives in app.learning_cycle (the
same module app.main's admin endpoints/background loop import), per
Section 70/93.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=None, help="event lookback window (default: LEARNING_LOOKBACK_DAYS env, 30)")
    parser.add_argument("--full", action="store_true", help="run each candidate through the FULL V2.10 suite, not just critical cases")
    parser.add_argument("--no-shadow", action="store_true", help="skip the shadow-comparison stage")
    args = parser.parse_args()

    import app.main as m  # only entry point that needs the real, loaded catalog
    from app.learning_cycle import run_learning_cycle, render_markdown

    known_product_ids = frozenset(p.id for p in m.products)
    report = run_learning_cycle(
        known_product_ids=known_product_ids,
        days=args.days,
        fast_evaluation=not args.full,
        run_shadow_stage=not args.no_shadow,
    )

    print(render_markdown(report))
    return 1 if report.get("status") == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
