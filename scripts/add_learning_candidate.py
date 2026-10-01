"""
scripts/add_learning_candidate.py  -  V2.23a offline intake CLI.

Turns one real-customer failure (already sanitized by the operator
pasting it in - this script applies a second, mechanical safety-net pass
via app.scenario_candidates.sanitize_text()) into a GROUND_TRUTH_PENDING
ScenarioCandidate, appended to eval/candidates/real_customer/candidates.
jsonl.

This is deliberately an OFFLINE, local CLI (Section 22/34 of the V2.23a
mandate) - no new HTTP endpoint, no new auth surface. An operator runs
this on their own machine, reviews the printed sanitization summary, and
only then commits the resulting diff like any other repo change.

NEVER:
  - sets ground_truth_status to anything but GROUND_TRUTH_PENDING
  - sets a ground_truth_authority
  - writes to eval/golden/
  - calls the Advisor / app.main / production code paths
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.scenario_candidates import (  # noqa: E402
    CANDIDATES_PATH,
    FAILURE_FAMILIES,
    RISK_LEVELS,
    SOURCE_TYPES,
    CandidateValidationError,
    append_candidate,
    build_candidate,
)


def _parse_entity_state(pairs: list[str]) -> dict[str, str]:
    out = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit(f"--entity-state expects key=VALUE, got {pair!r}")
        key, value = pair.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--text", required=True, help="sanitized customer text (operator must have already removed obvious PII)")
    parser.add_argument("--language", default="sk")
    parser.add_argument("--source-type", required=True, choices=SOURCE_TYPES)
    parser.add_argument("--observed-intent", default=None, help="current_observed_intent, if known")
    parser.add_argument("--observed-behavior", default=None)
    parser.add_argument("--failure-family", default="UNKNOWN", choices=FAILURE_FAMILIES)
    parser.add_argument("--expected-intent", default=None)
    parser.add_argument("--expected-behavior", default=None)
    parser.add_argument("--forbidden-behavior", action="append", default=[], help="repeatable")
    parser.add_argument("--entity-state", action="append", default=[], help="repeatable key=VALUE, e.g. ryza=ALREADY_HAVE")
    parser.add_argument("--risk", default="NORMAL", choices=RISK_LEVELS)
    parser.add_argument("--notes", default="")
    parser.add_argument("--candidates-path", default=str(CANDIDATES_PATH))
    args = parser.parse_args(argv)

    try:
        candidate = build_candidate(
            raw_text=args.text,
            language=args.language,
            source_type=args.source_type,
            current_observed_intent=args.observed_intent,
            current_observed_behavior=args.observed_behavior,
            suspected_failure_family=args.failure_family,
            expected_intent=args.expected_intent,
            expected_behavior=args.expected_behavior,
            forbidden_behavior=tuple(args.forbidden_behavior),
            entity_state=_parse_entity_state(args.entity_state),
            risk_level=args.risk,
            notes=args.notes,
        )
    except CandidateValidationError as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 1

    duplicate = append_candidate(candidate, path=Path(args.candidates_path))
    if duplicate is not None:
        print(f"DUPLICATE of existing candidate {duplicate.candidate_id} (same sanitized text) - not appended again.")
        print(f"  existing status: {duplicate.ground_truth_status}, human_review_status: {duplicate.human_review_status}")
        return 0

    print(f"candidate_id: {candidate.candidate_id}")
    print(f"ground_truth_status: {candidate.ground_truth_status} (always PENDING at intake)")
    print(f"sanitized_query: {candidate.sanitized_query!r}")
    print(f"sanitization_counts: {candidate.sanitization_counts}")
    if any(candidate.sanitization_counts.values()):
        print("  -> PII markers were redacted automatically. Please VISUALLY re-check the")
        print("     sanitized_query above for any remaining name/address/identifier before")
        print(f"     committing {args.candidates_path}.")
    else:
        print("  -> no email/phone/order-reference/name-like pattern detected automatically.")
        print("     Please still visually confirm no PII remains before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
