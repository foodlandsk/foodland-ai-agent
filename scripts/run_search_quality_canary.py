"""V2.12.4 Section 38/102/103/125 - runs the curated hard semantic canary
set (eval/search_quality_canaries.json) through the REAL /chat retrieval
path (app.main._chat_internal, same function every genuine customer
request goes through) in ADMIN_TEST execution mode - never CUSTOMER, so a
canary run can never contaminate customer search-quality metrics
(Section 39/103, verified by tests/test_search_quality.py::
TestCanaryExecutionContextIsolation).

Each case's `must_not_family` is checked against the ACTUAL classified
family of every returned product (app.product_taxonomy_index), not just
the query's own resolved family - this is what makes wrong-family
leakage detection (Section 40) a genuine invariant check rather than a
restatement of parse_structured_query()'s own output.

Usage:
    python scripts/run_search_quality_canary.py
    python scripts/run_search_quality_canary.py --json   # machine-readable
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import main as bot  # noqa: E402
from app.advisor_engine import advisor_engine, AdvisorRequest  # noqa: E402
from app.execution_context import admin_test_context  # noqa: E402
from app.search_quality import canary_anomalies, current_deployment_version, load_canary_cases, run_canaries  # noqa: E402

DEFAULT_CANARY_PATH = ROOT / "eval" / "search_quality_canaries.json"


def _chat_fn(query: str) -> dict:
    # V2.13a: goes through AdvisorEngine (app/advisor_engine.py) instead of
    # a script-local duck-typed FakeRequest + app.main._chat_internal() -
    # same underlying call, one fewer independent shim to keep in sync.
    request = AdvisorRequest(message=query, session_id="search-quality-canary", client_key="search-quality-canary")
    return advisor_engine.run(request, admin_test_context())


def _classify_product_family(product_id: str) -> str | None:
    tax = bot.product_taxonomy_index.get(product_id)
    return tax.canonical_family if tax else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--path", default=str(DEFAULT_CANARY_PATH), help="canary definition file")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON instead of a text summary")
    args = parser.parse_args()

    cases = load_canary_cases(args.path)
    if not cases:
        print(f"No canary cases found at {args.path}", file=sys.stderr)
        sys.exit(2)

    results = run_canaries(cases, chat_fn=_chat_fn, classify_product_family=_classify_product_family)
    anomalies = canary_anomalies(results, current_deployment_version())

    if args.json:
        print(json.dumps({
            "results": [r.__dict__ for r in results],
            "anomalies": [a.__dict__ for a in anomalies],
        }, ensure_ascii=False, indent=2))
        sys.exit(0 if all(r.passed for r in results) else 1)

    passed = sum(1 for r in results if r.passed)
    print(f"Search Quality Canary — {passed}/{len(results)} PASS\n")
    for r in results:
        status = "PASS" if r.passed else f"FAIL ({r.criticality})"
        print(f"  [{status}] {r.id:24s} query={r.query!r:35s} path={r.retrieval_path} family={r.family} latency={r.latency_ms:.1f}ms")
        if not r.passed:
            print(f"           reason: {r.reason}")
    print()
    if anomalies:
        print(f"{len(anomalies)} anomaly(ies):")
        for a in anomalies:
            print(f"  [{a.severity}] {a.type} scope={a.scope} evidence={a.evidence}")
    else:
        print("No anomalies.")

    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
