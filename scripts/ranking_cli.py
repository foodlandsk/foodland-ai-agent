"""
scripts/ranking_cli.py  -  V2.11 Ranking & Recommendation Optimization Engine CLI

Usage:
    python scripts/ranking_cli.py list
    python scripts/ranking_cli.py activate v1
    python scripts/ranking_cli.py explain --query "jazmínová ryža" [--profile v1] [--limit 8]
    python scripts/ranking_cli.py compare-profiles --baseline v1 --candidate v1 [--query "..."]*
    python scripts/ranking_cli.py optimize --candidates 8 --seed 1 [--fast|--full] [--save]

Deterministic (Section 45/109) - only imports app.main and app.evaluation
(the checked-in data/products.json fixture), never network/Railway.
`optimize`/`activate` never happen automatically together: optimize()
only ever RECOMMENDS a candidate version; activating it is a separate,
explicit `activate` invocation (Section 130 - full auto-apply is V2.12's
job, not this sprint's).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def cmd_list(args) -> int:
    from app.ranking_config import get_active_ranking_profile_version, list_ranking_profile_versions

    active = get_active_ranking_profile_version()
    for version in list_ranking_profile_versions():
        marker = " (active)" if version == active else ""
        print(f"{version}{marker}")
    return 0


def cmd_activate(args) -> int:
    from app.ranking_config import RankingProfileError, set_active_ranking_profile_version

    try:
        set_active_ranking_profile_version(args.version)
    except RankingProfileError as exc:
        print(f"Error: {exc}")
        return 1
    print(f"Activated ranking profile {args.version!r}.")
    return 0


def cmd_explain(args) -> int:
    from app.evaluation.adapter import get_taxonomy_index
    from app.ranking_config import DEFAULT_PROFILE, RankingProfileError, load_ranking_profile
    from app.ranking_features import explain_candidates
    from app.structured_search import retrieve_products_for_query

    import app.main as m

    taxonomy_index = get_taxonomy_index()
    profile = DEFAULT_PROFILE
    if args.profile:
        try:
            profile = load_ranking_profile(args.profile)
        except RankingProfileError as exc:
            print(f"Error: {exc}")
            return 1

    result = retrieve_products_for_query(args.query, m.products, taxonomy_index, m.normalized_product_index)
    candidate_ids = result.exact_match_ids or result.nearest_match_ids or result.valid_match_ids
    if not candidate_ids:
        print(f"No structured candidates for {args.query!r} (retrieval_mode={result.retrieval_mode}).")
        return 1

    from app.retrieval import get_structured_index
    index = get_structured_index(m.products, taxonomy_index, m.normalized_product_index)
    products_by_id = {p.id: p for p in m.products}
    from app.search import get_behavioral_rankings, get_merchandising_rules

    features = explain_candidates(
        list(candidate_ids)[: args.limit],
        result.interpretation,
        products_by_id,
        index,
        m.normalized_product_index,
        weights=profile.weights_for(getattr(result.interpretation, "family", None)),
        behavioral_rankings=get_behavioral_rankings(),
        merchandising_rules=get_merchandising_rules(),
    )
    print(f"Query: {args.query!r} | profile: {profile.version} | retrieval_mode: {result.retrieval_mode}")
    for rank, feature in enumerate(features, start=1):
        print(f"  {rank}. {feature.explain()}")
    return 0


def cmd_compare_profiles(args) -> int:
    from app.ranking_config import DEFAULT_PROFILE, RankingProfileError, load_ranking_profile
    from app.ranking_shadow import DEFAULT_SHADOW_QUERIES, shadow_compare

    def _load(version: str):
        if version == "default":
            return DEFAULT_PROFILE
        return load_ranking_profile(version)

    try:
        baseline = _load(args.baseline)
        candidate = _load(args.candidate)
    except RankingProfileError as exc:
        print(f"Error: {exc}")
        return 1

    queries = args.query or list(DEFAULT_SHADOW_QUERIES)
    report = shadow_compare(queries, baseline, candidate, limit=args.limit)
    print(report.render())
    return 0


def cmd_optimize(args) -> int:
    from app.ranking_config import DEFAULT_PROFILE, RankingProfileError, load_ranking_profile, save_ranking_profile
    from app.ranking_optimizer import optimize

    try:
        base = load_ranking_profile(args.base) if args.base else DEFAULT_PROFILE
    except RankingProfileError as exc:
        print(f"Error: {exc}")
        return 1

    print(f"Optimizing from base={base.version}, n_candidates={args.candidates}, seed={args.seed}, "
          f"mode={'fast' if not args.full else 'full'} ...")
    result = optimize(base, n_candidates=args.candidates, seed=args.seed, fast=not args.full)

    printable = {k: v for k, v in result.items() if k != "best_candidate_profile"}
    print(json.dumps(printable, ensure_ascii=False, indent=2, sort_keys=True))

    if args.save and result["improved"]:
        profile = result["best_candidate_profile"]
        path = save_ranking_profile(profile)
        print(f"\nSaved recommended candidate as new version {profile.version!r} at {path}.")
        print("Not activated - run `activate` explicitly to make it live.")
    elif args.save:
        print("\n--save given but no candidate improved on the base profile; nothing saved.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list known ranking profile versions").set_defaults(func=cmd_list)

    p = sub.add_parser("activate", help="atomically point active.json at a version (also used for rollback)")
    p.add_argument("version")
    p.set_defaults(func=cmd_activate)

    p = sub.add_parser("explain", help="single-case ranking drilldown")
    p.add_argument("--query", required=True)
    p.add_argument("--profile", default=None, help="profile version to explain under (default: built-in default)")
    p.add_argument("--limit", type=int, default=8)
    p.set_defaults(func=cmd_explain)

    p = sub.add_parser("compare-profiles", help="shadow-mode baseline vs candidate order comparison")
    p.add_argument("--baseline", required=True, help="version, or 'default'")
    p.add_argument("--candidate", required=True, help="version, or 'default'")
    p.add_argument("--query", action="append", help="repeatable; default query set used if omitted")
    p.add_argument("--limit", type=int, default=8)
    p.set_defaults(func=cmd_compare_profiles)

    p = sub.add_parser("optimize", help="bounded offline search via the real V2.10 evaluation harness")
    p.add_argument("--base", default=None, help="base profile version (default: built-in default)")
    p.add_argument("--candidates", type=int, default=6)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--full", action="store_true", help="evaluate all golden/conversation cases, not just critical ones")
    p.add_argument("--save", action="store_true", help="persist the recommended candidate as a new version (not activated)")
    p.set_defaults(func=cmd_optimize)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
