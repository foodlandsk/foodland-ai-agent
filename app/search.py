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
    "kolko",
    "ku",
    "lacnejsia",
    "lacnejsie",
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
    "produkt",
    "produkty",
    "produktov",
    "prosim",
    "porovnaj",
    "porovnanie",
    "podobne",
    "podobnych",
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

INTENT_NOISE_TOKENS = {
    "alternativa",
    "alternativy",
    "cena",
    "ceny",
    "doplnky",
    "hodi",
    "kupit",
    "moznosti",
    "nahrada",
    "odporuc",
    "porovnat",
    "suvisejuci",
    "suvisiace",
    "suvisiaci",
    "vyber",
    "vybrat",
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
        if token in INTENT_NOISE_TOKENS:
            continue
        if token.startswith("kredit"):
            expanded.add("kredit")
        if token in {"cili", "chili", "chilli"} or token.startswith("cil"):
            expanded.update({"cili", "chili"})
        if token.startswith("omack"):
            expanded.add("omacka")
        if token.startswith("kokos"):
            expanded.add("kokos")
        if token.startswith("mliek"):
            expanded.add("mlieko")
        if token.startswith("gochujang") or token.startswith("gocujang") or token.startswith("gocudzang") or token.startswith("gocudzan"):
            expanded.add("gochujang")
        if token.startswith("gochugaru"):
            expanded.update({"gochugaru", "cili", "chili", "paprika", "mleta", "mlete", "paliva", "cervena"})
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
    return expanded - INTENT_NOISE_TOKENS


def meaningful_query_tokens(query: str) -> set[str]:
    return tokenize(query) - INTENT_NOISE_TOKENS


def search_products(products: list[Product], query: str, limit: int = 8) -> list[dict]:
    query_tokens = meaningful_query_tokens(query)
    if not query_tokens:
        return []

    ranked: list[tuple[int, Product]] = []
    normalized_query = normalize(query).strip()
    for product in products:
        title_tokens = tokenize(product.title)
        category_tokens = tokenize(product.product_type)
        brand_tokens = tokenize(product.brand)
        description_tokens = tokenize(product.description)

        title_overlap = query_tokens & title_tokens
        brand_overlap = query_tokens & brand_tokens
        category_overlap = query_tokens & category_tokens
        primary_overlap_count = len(title_overlap | brand_overlap | category_overlap)

        normalized_title = normalize(product.title)
        phrase_match = bool(normalized_query and normalized_query in normalized_title)

        # Avoid random products from broad follow-up words or description-only hits.
        if not phrase_match and primary_overlap_count == 0:
            continue
        if len(query_tokens) >= 2 and not phrase_match and primary_overlap_count < 1:
            continue

        score = 0
        score += 8 * len(title_overlap)
        score += 5 * len(brand_overlap)
        score += 4 * len(category_overlap)
        score += min(2, len(query_tokens & description_tokens))

        if phrase_match:
            score += 14
        if query_tokens and query_tokens <= (title_tokens | brand_tokens | category_tokens):
            score += 8
        if len(query_tokens) >= 2 and len(query_tokens & title_tokens) >= 2:
            score += 6

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
