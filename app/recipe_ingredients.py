from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.feed import Product
from app.search import normalize, search_products, tokenize


INGREDIENT_INTENT_MARKERS = [
    "ingrediencie",
    "ingrediencia",
    "suroviny",
    "surovina",
    "co potrebujem",
    "co treba",
    "produkty na recept",
    "produkty k receptu",
    "nakupny zoznam",
    "na vyrobu",
    "na pripravu",
]

LOW_VALUE_PRODUCT_TOKENS = {
    "instantna",
    "instantne",
    "polievka",
    "polievky",
    "ramen",
    "rezance",
    "prichutou",
}

SKIP_INGREDIENT_FRAGMENTS = [
    "napa kapust",
    "koser soli",
    "nejodizovanej soli",
    "sladkej soli",
    "vody",
    "cukru",
    "redkovky",
    "mrkvy",
    "jarnej cibul",
    "pazitky",
    "buchu",
    "minari",
    "stredna cibula",
    "fermentovanych solenych kreviet",
    "solenych kreviet",
    "kreviet saeujeot",
]

DIRECT_INGREDIENT_QUERIES = [
    ("gochugaru", "gochugaru"),
    ("ryzovej muky", "ryzova muka"),
    ("ryzova muka", "ryzova muka"),
    ("rybacej omacky", "rybacia omacka"),
    ("rybacia omacka", "rybacia omacka"),
    ("cesnaku", "cesnakova pasta"),
    ("cesnak", "cesnakova pasta"),
    ("zazvoru", "zazvorova pasta"),
    ("zazvor", "zazvorova pasta"),
    ("sezamoveho oleja", "sezamovy olej"),
    ("sezamovy olej", "sezamovy olej"),
    ("sezamove semienka", "sezamove semienka"),
    ("kimchi", "kimchi"),
    ("gochujang", "gochujang"),
    ("ramen", "ramen"),
]


def load_recipe_ingredients_json(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    return json.loads(file_path.read_text(encoding="utf-8-sig"))


def is_ingredient_query(message: str) -> bool:
    normalized = normalize(message)
    if any(marker in normalized for marker in INGREDIENT_INTENT_MARKERS):
        return True

    tokens = tokenize(message)
    return bool(tokens & {"ingrediencie", "suroviny", "surovina"}) or (
        "recept" in tokens and bool(tokens & {"produkt", "produkty", "kupit", "nakup"})
    )


def search_recipe_ingredient_products(
    recipes: list[dict[str, Any]],
    products: list[Product],
    query: str,
    limit: int = 6,
    exclude_product_ids: set[str] | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not recipes:
        return None, []

    query_tokens = recipe_content_tokens(query)
    if not query_tokens:
        query_tokens = tokenize(query)

    ranked: list[tuple[int, dict[str, Any]]] = []
    for recipe in recipes:
        score = score_recipe(recipe, query, query_tokens)
        if score > 0:
            ranked.append((score, recipe))

    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked:
        return None, []

    recipe = ranked[0][1]
    product_lookup = {product.id: product for product in products}
    return recipe, ingredient_products(recipe, product_lookup, products, limit, exclude_product_ids or set())


def recipe_content_tokens(query: str) -> set[str]:
    intent_noise = {
        "recept",
        "recepty",
        "ingrediencie",
        "ingrediencia",
        "suroviny",
        "surovina",
        "produkty",
        "produkt",
        "potrebujem",
        "treba",
        "nakup",
        "nakupny",
        "zoznam",
        "vyrobu",
        "pripravu",
        "uvarit",
        "pripravit",
    }
    return tokenize(query) - intent_noise


def score_recipe(recipe: dict[str, Any], query: str, query_tokens: set[str]) -> int:
    name = str(recipe.get("name") or "")
    cuisine = str(recipe.get("cuisine") or "")
    ingredient_text = " ".join(str(item.get("text") or "") for item in recipe.get("ingredients", []))
    product_text = " ".join(
        str(match.get("title") or "")
        for item in recipe.get("ingredients", [])
        for match in item.get("product_matches", [])
    )

    name_tokens = tokenize(name)
    cuisine_tokens = tokenize(cuisine)
    ingredient_tokens = tokenize(ingredient_text)
    product_tokens = tokenize(product_text)

    score = 0
    score += 10 * len(query_tokens & name_tokens)
    score += 4 * len(query_tokens & cuisine_tokens)
    score += 3 * len(query_tokens & ingredient_tokens)
    score += 2 * len(query_tokens & product_tokens)

    normalized_query = normalize(query)
    normalized_name = normalize(name)
    if normalized_query and normalized_query in normalized_name:
        score += 20
    if query_tokens and query_tokens <= name_tokens:
        score += 12

    if is_base_recipe_query(query) and query_tokens & name_tokens:
        if name_tokens & {"tradicny", "tradicne", "zaklad", "recept"}:
            score += 18
        if name_tokens & {"ramen", "jjigae", "ryza", "polievka"}:
            score -= 10

    return score


def is_base_recipe_query(query: str) -> bool:
    normalized = normalize(query)
    markers = [
        "na vyrobu",
        "vyroba",
        "vyrobit",
        "ako urobit",
        "ako spravit",
        "pripravit kimchi",
        "urobit kimchi",
        "spravit kimchi",
    ]
    return any(marker in normalized for marker in markers)


def ingredient_products(
    recipe: dict[str, Any],
    product_lookup: dict[str, Product],
    product_catalog: list[Product],
    limit: int,
    exclude_product_ids: set[str],
) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for ingredient in recipe.get("ingredients", []):
        if ingredient.get("likely_generic_staple") is True:
            continue
        if should_skip_ingredient(ingredient):
            continue

        direct_product = direct_feed_product(recipe, ingredient, product_catalog)
        if direct_product:
            unique_key = str(direct_product.get("id") or direct_product.get("link") or "")
            if unique_key in exclude_product_ids:
                continue
            if unique_key and unique_key not in seen_ids:
                seen_ids.add(unique_key)
                products.append(direct_product)
                if len(products) >= limit:
                    break
                continue

        matches = ingredient.get("product_matches") or []
        best_match = best_product_match(ingredient, matches)
        if not best_match:
            continue
        if not is_compatible_match(ingredient, best_match):
            continue

        product_id = str(best_match.get("product_id") or "")
        link = str(best_match.get("link") or "")
        unique_key = product_id or link
        if unique_key in exclude_product_ids:
            continue
        if not unique_key or unique_key in seen_ids:
            continue
        seen_ids.add(unique_key)

        feed_product = product_lookup.get(product_id)
        products.append(format_ingredient_product(recipe, ingredient, best_match, feed_product))
        if len(products) >= limit:
            break

    return products


def should_skip_ingredient(ingredient: dict[str, Any]) -> bool:
    text = normalize(str(ingredient.get("text") or ""))
    return any(fragment in text for fragment in SKIP_INGREDIENT_FRAGMENTS)


def direct_feed_product(
    recipe: dict[str, Any],
    ingredient: dict[str, Any],
    product_catalog: list[Product],
) -> dict[str, Any] | None:
    ingredient_text = str(ingredient.get("text") or "")
    normalized = normalize(ingredient_text)
    query = ""
    for fragment, candidate_query in DIRECT_INGREDIENT_QUERIES:
        if fragment in normalized:
            query = candidate_query
            break
    if not query:
        return None

    for product in search_products(product_catalog, query, 8):
        if is_compatible_product_text(ingredient_text, product.get("title", "")):
            product["description"] = f"Ingrediencia: {ingredient_text}"
            product["product_type"] = f"Produkt k receptu: {recipe.get('name', '')}"
            product["recipe_name"] = recipe.get("name", "")
            product["ingredient_text"] = ingredient_text
            product["match_confidence"] = "feed"
            return product

    return None


def is_compatible_match(ingredient: dict[str, Any], match: dict[str, Any]) -> bool:
    return is_compatible_product_text(str(ingredient.get("text") or ""), str(match.get("title") or ""))


def is_compatible_product_text(ingredient_text: str, product_title: str) -> bool:
    ingredient = normalize(ingredient_text)
    title = normalize(product_title)

    if any(fragment in ingredient for fragment in ["soli", "sol "]):
        return "sol" in title and "sojov" not in title
    if "gochugaru" in ingredient:
        return "gochugaru" in title or ("cili" in title and "paprik" in title and "pasta" not in title)
    if "ryzovej muky" in ingredient or "ryzova muka" in ingredient:
        return "ryz" in title and "muka" in title
    if "rybacej omacky" in ingredient or "rybacia omacka" in ingredient:
        return "ryb" in title and "omack" in title
    if "cesnak" in ingredient:
        return "cesnak" in title
    if "zazvor" in ingredient:
        return "zazvor" in title
    if "sezamoveho oleja" in ingredient or "sezamovy olej" in ingredient:
        return "sezam" in title and "olej" in title
    if "sezamove semienka" in ingredient:
        return "sezam" in title and "semien" in title
    if "gochujang" in ingredient:
        return "gochujang" in title
    if "kimchi" in ingredient:
        return "kimchi" in title

    return True


def best_product_match(ingredient: dict[str, Any], matches: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not matches:
        return None

    ingredient_tokens = tokenize(str(ingredient.get("text") or ""))
    ranked: list[tuple[int, dict[str, Any]]] = []
    for match in matches:
        title_tokens = tokenize(str(match.get("title") or ""))
        confidence = str(match.get("match_confidence") or "").lower()
        score = 0
        score += 8 if confidence == "high" else 4 if confidence == "medium" else 1
        score += 5 * len(ingredient_tokens & title_tokens)
        score -= 3 * len((title_tokens & LOW_VALUE_PRODUCT_TOKENS) - ingredient_tokens)
        if match.get("availability") == "in_stock":
            score += 1
        ranked.append((score, match))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def format_ingredient_product(
    recipe: dict[str, Any],
    ingredient: dict[str, Any],
    match: dict[str, Any],
    feed_product: Product | None,
) -> dict[str, Any]:
    price, currency = parse_price(match.get("price"))
    sale_price, sale_currency = parse_price(match.get("sale_price"))
    effective_price = sale_price if sale_price is not None else price

    return {
        "id": match.get("product_id") or (feed_product.id if feed_product else ""),
        "title": match.get("title") or (feed_product.title if feed_product else ""),
        "description": f"Ingrediencia: {ingredient.get('text', '')}",
        "product_type": f"Produkt k receptu: {recipe.get('name', '')}",
        "link": match.get("link") or (feed_product.link if feed_product else ""),
        "image_link": feed_product.image_link if feed_product else "",
        "price": price,
        "sale_price": sale_price,
        "effective_price": effective_price,
        "currency": sale_currency if sale_price is not None else currency,
        "brand": feed_product.brand if feed_product else "",
        "availability": match.get("availability") or (feed_product.availability if feed_product else ""),
        "gtin": feed_product.gtin if feed_product else "",
        "unit_pricing_measure": feed_product.unit_pricing_measure if feed_product else "",
        "recipe_name": recipe.get("name", ""),
        "ingredient_text": ingredient.get("text", ""),
        "match_confidence": match.get("match_confidence", ""),
    }


def parse_price(value: Any) -> tuple[float | None, str]:
    text = str(value or "").strip()
    if not text:
        return None, "EUR"
    match = re.match(r"^\s*([0-9]+(?:[.,][0-9]+)?)\s*([A-Z]{3})?\s*$", text)
    if not match:
        return None, "EUR"
    return float(match.group(1).replace(",", ".")), match.group(2) or "EUR"


def recipe_ingredients_answer(recipe: dict[str, Any], products: list[dict[str, Any]]) -> str:
    recipe_name = str(recipe.get("name") or "receptu")
    if not products:
        return f"Našiel som recept {recipe_name}, ale k jeho ingredienciám zatiaľ nemám spoľahlivé produktové odporúčania."
    count = min(len(products), 6)
    return f"Našiel som {count} produktov k receptu {recipe_name}. Vybral som položky z Foodland dát podľa ingrediencií receptu."
