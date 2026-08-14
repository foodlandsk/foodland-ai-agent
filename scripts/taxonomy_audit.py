"""
scripts/taxonomy_audit.py  -  V2 catalog-first taxonomy discovery (Phase 1-4)

Profiles the CURRENT Foodland catalog (data/products.json) and knowledge
base (data/knowledge.json) from scratch - no hardcoded product counts,
category lists, or family assumptions. Every number in the generated
audit is recomputed from the live source data each run.

Usage:
    python3 scripts/taxonomy_audit.py                  # full audit, prints to stdout
    python3 scripts/taxonomy_audit.py --family ryza     # drill into one candidate family's collisions
    python3 scripts/taxonomy_audit.py --json out.json   # also dump raw stats as JSON

Regeneration: re-run this script after any data/products.json or
data/knowledge.json refresh. Nothing here is manually maintained - it is
fully derived from the two source files plus the routing dictionaries
already defined in app/main.py (read via import, not duplicated).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STOPWORDS = {
    "a", "s", "so", "na", "do", "od", "pre", "za", "po", "bez", "vo", "v",
    "z", "zo", "the", "and", "or", "of", "with", "for",
}


def normalize(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    return ascii_text.casefold().strip()


def tokenize(text: str) -> list[str]:
    normalized = normalize(text)
    return [t for t in re.split(r"[^a-z0-9]+", normalized) if t and t not in STOPWORDS]


def load_products() -> list[dict]:
    data = json.loads((ROOT / "data" / "products.json").read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("products", data)


def load_knowledge() -> dict:
    return json.loads((ROOT / "data" / "knowledge.json").read_text(encoding="utf-8"))


def category_path(product: dict) -> list[str]:
    raw = str(product.get("product_type") or product.get("category") or "")
    return [p.strip() for p in re.split(r"[>/|]", raw) if p.strip()]


def ngrams(tokens: list[str], n: int) -> list[str]:
    return [" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


def profile_catalog(products: list[dict]) -> dict:
    total = len(products)
    brands = Counter()
    categories_top = Counter()
    categories_all = Counter()
    title_tokens = Counter()
    title_bigrams = Counter()
    title_trigrams = Counter()
    size_pattern = re.compile(r"\b\d+([.,]\d+)?\s?(g|kg|ml|l|ks|pcs|cm|mm)\b")
    sizes = Counter()

    for p in products:
        brand = str(p.get("brand") or "").strip()
        if brand:
            brands[brand] += 1
        path = category_path(p)
        if path:
            categories_top[path[0]] += 1
        for part in path:
            categories_all[part] += 1
        title = str(p.get("title") or "")
        toks = tokenize(title)
        title_tokens.update(toks)
        title_bigrams.update(ngrams(toks, 2))
        title_trigrams.update(ngrams(toks, 3))
        for m in size_pattern.finditer(normalize(title)):
            sizes[m.group(2)] += 1

    return {
        "total_products": total,
        "unique_brands": len(brands),
        "unique_categories_top_level": len(categories_top),
        "unique_categories_all_levels": len(categories_all),
        "top_brands": brands.most_common(20),
        "top_categories_top_level": categories_top.most_common(30),
        "top_title_tokens": title_tokens.most_common(60),
        "top_title_bigrams": title_bigrams.most_common(60),
        "top_title_trigrams": title_trigrams.most_common(40),
        "package_size_units": sizes.most_common(20),
    }


# Candidate family ROOT STEMS to probe for cross-category collisions. This
# is a starting hypothesis list only (per prompt Phase 2/4) - the script
# reports actual catalog evidence for each; families/roots with no real
# products are simply reported as zero, not assumed.
CANDIDATE_ROOTS = [
    "ryz", "rice", "nudl", "rezanc", "noodle", "soj", "soy", "ryba", "fish",
    "kari", "curry", "kokos", "coconut", "morsk", "seaweed", "nori", "tofu",
    "caj", "tea", "susi", "sushi", "wasabi", "kimchi", "gochujang", "miso",
    "matcha", "sake", "ocot", "vinegar", "mlieko", "milk",
]


def collision_report(products: list[dict], roots: list[str]) -> dict:
    report = {}
    for root in roots:
        matches = defaultdict(list)
        for p in products:
            title = str(p.get("title") or "")
            toks = set(tokenize(title))
            hit_tokens = {t for t in toks if t.startswith(root)}
            if hit_tokens:
                for tok in hit_tokens:
                    matches[tok].append(p.get("id"))
        if len(matches) > 1:
            report[root] = {tok: len(ids) for tok, ids in sorted(matches.items(), key=lambda kv: -len(kv[1]))}
    return report


def knowledge_summary(knowledge: dict) -> dict:
    sections = knowledge.get("sections", {})
    return {name: len(records) for name, records in sections.items()}


def legacy_routing_summary() -> dict:
    import app.main as main  # noqa: E402  (import after sys.path insert)

    return {
        "RELATED_SUBJECT_ALIASES_subjects": len(main.RELATED_SUBJECT_ALIASES),
        "SPECIAL_PRODUCT_QUERIES_subjects": len(main.SPECIAL_PRODUCT_QUERIES),
        "REPLACEMENT_SUBJECT_ALIASES_subjects": len(main.REPLACEMENT_SUBJECT_ALIASES),
        "RECIPE_SHOPPING_CORE_QUERIES_subjects": len(main.RECIPE_SHOPPING_CORE_QUERIES),
        "MISSING_INGREDIENTS_BY_SUBJECT_subjects": len(main.MISSING_INGREDIENTS_BY_SUBJECT),
        "RECIPE_TITLE_PRODUCT_SUBJECTS_markers": len(main.RECIPE_TITLE_PRODUCT_SUBJECTS),
        "already_have_rice_related": [
            k for k in main.SPECIAL_PRODUCT_QUERIES
            if "ryz" in k or "rice" in k
        ],
    }


def family_detail(products: list[dict], root: str) -> None:
    print(f"\n=== Products containing tokens starting with {root!r} ===")
    by_token = defaultdict(list)
    for p in products:
        title = str(p.get("title") or "")
        toks = set(tokenize(title))
        for tok in toks:
            if tok.startswith(root):
                by_token[tok].append((p.get("id"), title, category_path(p)[:2]))
    for tok in sorted(by_token, key=lambda t: -len(by_token[t])):
        entries = by_token[tok]
        print(f"\n-- token {tok!r} ({len(entries)} products) --")
        for pid, title, cat in entries[:6]:
            print(f"   {pid}  {title!r}  cat={cat}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--family", help="Drill into one root stem's colliding products")
    parser.add_argument("--json", help="Also dump raw stats as JSON to this path")
    args = parser.parse_args()

    products = load_products()
    knowledge = load_knowledge()

    profile = profile_catalog(products)
    collisions = collision_report(products, CANDIDATE_ROOTS)
    ksum = knowledge_summary(knowledge)
    legacy = legacy_routing_summary()

    print("=" * 70)
    print("FOODLAND CATALOG TAXONOMY AUDIT (generated from current data)")
    print("=" * 70)
    print(f"\ntotal_products = {profile['total_products']}")
    print(f"unique_brands = {profile['unique_brands']}")
    print(f"unique_categories_top_level = {profile['unique_categories_top_level']}")
    print(f"unique_categories_all_levels = {profile['unique_categories_all_levels']}")

    print("\n--- top 20 brands ---")
    for name, count in profile["top_brands"]:
        print(f"  {count:4d}  {name}")

    print("\n--- top 30 top-level categories ---")
    for name, count in profile["top_categories_top_level"]:
        print(f"  {count:4d}  {name}")

    print("\n--- top 40 title bigrams (candidate compound product names) ---")
    for name, count in profile["top_title_bigrams"][:40]:
        print(f"  {count:4d}  {name}")

    print("\n--- top 25 title trigrams ---")
    for name, count in profile["top_title_trigrams"][:25]:
        print(f"  {count:4d}  {name}")

    print("\n--- package size units found in titles ---")
    for name, count in profile["package_size_units"]:
        print(f"  {count:4d}  {name}")

    print("\n--- cross-category collision candidates (shared root stem, multiple distinct tokens) ---")
    for root, toks in collisions.items():
        print(f"\n  root={root!r}:")
        for tok, count in toks.items():
            print(f"    {count:4d}  {tok}")

    print("\n--- knowledge.json section sizes ---")
    for name, count in ksum.items():
        print(f"  {count:4d}  {name}")

    print("\n--- existing legacy routing structures (app/main.py) ---")
    for name, value in legacy.items():
        print(f"  {name}: {value}")

    if args.family:
        family_detail(products, args.family)

    if args.json:
        out = {
            "profile": profile,
            "collisions": collisions,
            "knowledge_sections": ksum,
            "legacy_routing": legacy,
        }
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON dump written to {args.json}")


if __name__ == "__main__":
    main()
