"""
scripts/recipe_graph_audit.py  -  V2.8 Recipe/Ingredient Knowledge Graph audit

Builds the real production RecipeGraphIndex from the current data/products.json
and data/knowledge.json and reports graph integrity stats plus an unresolved-
ingredient report ranked by recipe frequency (Section 68/69/70). Nothing here
is hardcoded - every number is recomputed from current data on each run.

Usage:
    python scripts/recipe_graph_audit.py
    python scripts/recipe_graph_audit.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=str, default=None, help="also dump raw stats as JSON")
    args = parser.parse_args()

    import app.main as m
    from app.ingredients import lexical_candidates
    from app.recipe_graph import SOURCE_RECIPE_CURATED, build_recipe_graph_index

    graph = build_recipe_graph_index(
        products=m.products,
        taxonomy_index=m.product_taxonomy_index,
        normalized_index=m.normalized_product_index,
        recipe_shopping_core_queries=m.RECIPE_SHOPPING_CORE_QUERIES,
        missing_ingredients_by_subject=m.MISSING_INGREDIENTS_BY_SUBJECT,
        recipe_title_product_subjects=m.RECIPE_TITLE_PRODUCT_SUBJECTS,
        cms_recipes=m.knowledge.get("sections", {}).get("Recipes", []),
        products_ai=m.knowledge.get("sections", {}).get("Products_AI", []),
        special_product_queries=m.SPECIAL_PRODUCT_QUERIES,
    )

    print("=== V2.8 Recipe Graph Integrity Audit ===")
    print(f"catalog: {len(m.products)} products")
    for key, value in graph.stats.items():
        print(f"{key}: {value}")

    print()
    print("=== Build issues ===")
    if graph.build_issues:
        for issue in graph.build_issues:
            print(f" - {issue}")
    else:
        print(" (none)")

    print()
    print("=== Unresolved ingredient concepts (Section 69/70, ranked by recipe frequency) ===")
    unresolved: list[tuple[str, str, list[str]]] = []
    for concept in graph.ingredient_concepts.values():
        if concept.source != SOURCE_RECIPE_CURATED:
            continue
        hits = lexical_candidates(m.products, concept.display_name, concept.lexical_required_terms, concept.lexical_excluded_terms, limit=1)
        if not hits:
            dishes = graph.ingredient_to_dishes.get(concept.concept_id, [])
            unresolved.append((concept.concept_id, concept.display_name, dishes))
    unresolved.sort(key=lambda item: -len(item[2]))
    if unresolved:
        for concept_id, display_name, dishes in unresolved:
            print(f" - {concept_id} ('{display_name}'): {len(dishes)} recipe(s) -> {dishes}")
    else:
        print(" (none - every curated ingredient concept has at least one current catalog match)")

    if args.json:
        payload = {
            "stats": graph.stats,
            "build_issues": graph.build_issues,
            "unresolved": [{"concept_id": c, "display_name": d, "dishes": ds} for c, d, ds in unresolved],
        }
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON written to {args.json}")


if __name__ == "__main__":
    main()
