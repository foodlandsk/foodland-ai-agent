from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict

from app.feed import Product


STOPWORDS = {
    "a",
    "aj",
    "ak",
    "ako",
    "ale",
    "alebo",
    "by",
    "co",
    "com",
    "ci",
    "do",
    "je",
    "kde",
    "kedy",
    "ku",
    "ma",
    "mam",
    "mate",
    "mi",
    "mozem",
    "na",
    "nad",
    "nam",
    "nie",
    "od",
    "pre",
    "pri",
    "prosim",
    "sa",
    "si",
    "som",
    "su",
    "to",
    "uz",
    "vam",
    "vas",
    "viem",
    "viete",
    "za",
    "ze",
}


def normalize(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower()


def tokenize(value: str) -> set[str]:
    tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", normalize(value))
        if len(token) >= 2 and token not in STOPWORDS
    }
    expanded = set(tokens)
    for token in tokens:
        if token.startswith("kredit"):
            expanded.add("kredit")
        if token.startswith("srirach"):
            expanded.add("sriracha")
        if token in {"sushi", "susi"}:
            expanded.update({"sushi", "susi"})
        if token.startswith("ryz"):
            expanded.add("ryza")
        if token.startswith("kimchi") or token.startswith("kimci"):
            expanded.add("kimchi")
        if token.startswith("recept"):
            expanded.add("recept")
        if token.startswith("priprav") or token.startswith("uvar") or token.startswith("var"):
            expanded.add("recept")
    return expanded


def search_products(products: list[Product], query: str, limit: int = 8) -> list[dict]:
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    ranked: list[tuple[int, Product]] = []
    for product in products:
        title_tokens = tokenize(product.title)
        category_tokens = tokenize(product.product_type)
        brand_tokens = tokenize(product.brand)
        description_tokens = tokenize(product.description)

        score = 0
        score += 6 * len(query_tokens & title_tokens)
        score += 4 * len(query_tokens & brand_tokens)
        score += 3 * len(query_tokens & category_tokens)
        score += len(query_tokens & description_tokens)

        normalized_query = normalize(query)
        normalized_title = normalize(product.title)
        if normalized_query in normalized_title:
            score += 10

        # Availability should only break ties among relevant matches.
        if score > 0 and product.availability == "in_stock":
            score += 1

        if score > 0:
            ranked.append((score, product))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [format_product(product) for _, product in ranked[:limit]]


def format_product(product: Product) -> dict:
    data = asdict(product)
    data["effective_price"] = product.effective_price
    return data


def products_context(products: list[dict]) -> str:
    lines = []
    for product in products:
        price = product.get("effective_price")
        price_text = f"{price:.2f} {product.get('currency', 'EUR')}" if price is not None else "cena neuvedena"
        lines.append(
            "- {title} | {price} | {availability} | {brand} | {url}".format(
                title=product.get("title", ""),
                price=price_text,
                availability=product.get("availability", ""),
                brand=product.get("brand", ""),
                url=product.get("link", ""),
            )
        )
    return "\n".join(lines)
