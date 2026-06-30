from __future__ import annotations

from app.feed import load_products_json
from app.cross_sell_rules import recommend_live_related_products
from app.knowledge import is_recipe_query, load_knowledge_json, search_knowledge
from app.recipe_ingredients import is_ingredient_query
from app.search import normalize, search_products
from app.workflows import detect_workflow


GOLDEN_CASES = [
    ("mate sriracha?", "product_search"),
    ("na vyrobu kimchi", "recipe_to_products"),
    ("co potrebujem na recept Pho Bo", "recipe_to_products"),
    ("recept na kimchi", "recipe_only"),
    ("kolko stoji doprava do Kosic?", "faq"),
    ("alternativy k sriracha", "alternatives"),
    ("porovnaj sriracha omacky", "product_compare"),
    ("co sa hodi ku kokosovemu mlieku?", "cross_sell"),
    ("co je gochujang?", "content"),
    ("porovnaj ceny podobnych produktov", "product_compare"),
]

PRODUCT_GOLDEN_CASES = [
    ("Mate sushi ryzu?", "susi ryza"),
    ("Porovnaj sriracha omacky", "sriracha"),
]

LIVE_RELATED_GOLDEN_CASES = [
    ("co sa hodi ku kokosovemu mlieku AROY-D 1000ml", "Kokosové mlieko AROY-D 1000ml"),
]


def main() -> None:
    products = load_products_json("data/products.json")
    knowledge = load_knowledge_json("data/knowledge.json")
    failures: list[str] = []

    for query, expected_workflow in GOLDEN_CASES:
        matches = search_products(products, query, 6)
        knowledge_matches = search_knowledge(knowledge, query)
        workflow = detect_workflow(
            query,
            recipe_mode=is_recipe_query(query),
            ingredient_mode=is_ingredient_query(query),
            crosssell_mode=is_crosssell_query(query),
            compare_mode=is_compare_query(query),
            alternative_mode=is_alternative_query(query),
            has_faq=bool(knowledge_matches.get("FAQ")),
            has_products=bool(matches),
            has_content=bool(knowledge_matches.get("Magazine") or knowledge_matches.get("Recipes") or knowledge_matches.get("IntentMapping")),
        )
        status = "OK" if workflow.workflow == expected_workflow else "FAIL"
        print(f"{status}: {query!r} -> {workflow.workflow} expected {expected_workflow}")
        if status == "FAIL":
            failures.append(query)

    for query, expected_title_part in PRODUCT_GOLDEN_CASES:
        matches = search_products(products, query, 5)
        first_title = normalize(str(matches[0].get("title") or "")) if matches else ""
        status = "OK" if expected_title_part in first_title else "FAIL"
        print(f"{status}: {query!r} -> first product {first_title!r} expected title containing {expected_title_part!r}")
        if status == "FAIL":
            failures.append(query)

    for query, expected_source_product in LIVE_RELATED_GOLDEN_CASES:
        result = recommend_live_related_products(query, knowledge, products, limit=4)
        source_product = str(result.cards[0].get("source_product") or "") if result.cards else ""
        status = "OK" if source_product == expected_source_product else "FAIL"
        print(f"{status}: {query!r} -> live related source {source_product!r} expected {expected_source_product!r}")
        if status == "FAIL":
            failures.append(query)

    if failures:
        raise SystemExit(1)


def is_crosssell_query(message: str) -> bool:
    normalized = normalize(message)
    return any(marker in normalized for marker in ["suvisiace", "co sa hodi", "k tomu", "hodi sa", "odporuc"])


def is_compare_query(message: str) -> bool:
    normalized = normalize(message)
    return any(marker in normalized for marker in ["porovnaj", "porovnanie", "rozdiel", "co je lepsie", "vyber"])


def is_alternative_query(message: str) -> bool:
    normalized = normalize(message)
    return any(marker in normalized for marker in ["alternativa", "alternativy", "nahrada", "namiesto", "podobne"])


if __name__ == "__main__":
    main()
