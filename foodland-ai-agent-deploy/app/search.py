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
    "ktore",
    "ktory",
    "ktoru",
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
    "produkt",
    "produkty",
    "produktov",
    "pri",
    "prosim",
    "sa",
    "si",
    "som",
    "su",
    "suvisiace",
    "suvisiaci",
    "suvisiaca",
    "suvisia",
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
        if token.startswith("gochuj") or token.startswith("gochuang"):
            expanded.add("gochujang")
    return expanded


def search_products(products: list[Product], query: str, limit: int = 8) -> list[dict]:
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    ranked: list[tuple[int, bool, Product]] = []
    for product in products:
        title_tokens = tokenize(product.title)
        category_tokens = tokenize(product.product_type)
        brand_tokens = tokenize(product.brand)
        description_tokens = tokenize(product.description)

        title_hits = len(query_tokens & title_tokens)
        brand_hits = len(query_tokens & brand_tokens)
        category_hits = len(query_tokens & category_tokens)
        description_hits = len(query_tokens & description_tokens)

        score = 0
        score += 8 * title_hits
        score += 5 * brand_hits
        score += 4 * category_hits
        score += description_hits

        normalized_query = normalize(query)
        normalized_title = normalize(product.title)
        if normalized_query in normalized_title:
            score += 12

        strong_match = bool(title_hits or brand_hits or category_hits or normalized_query in normalized_title)

        # Availability should only break ties among relevant matches.
        if score > 0 and product.availability == "in_stock":
            score += 1

        if score > 0:
            ranked.append((score, strong_match, product))

    strong_ranked = [item for item in ranked if item[1]]
    weak_ranked = [item for item in ranked if not item[1]]
    strong_ranked.sort(key=lambda item: item[0], reverse=True)
    weak_ranked.sort(key=lambda item: item[0], reverse=True)

    # Description-only hits often mean "served with X", not that the product itself is X.
    # Use them only as a fallback when strong title/brand/category matches are scarce.
    if len(strong_ranked) >= min(limit, 4):
        ranked = strong_ranked
    else:
        ranked = strong_ranked + weak_ranked

    return [format_product(product) for _, _, product in ranked[:limit]]


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
