"""Autocomplete endpoint helpers: prefix and token matching over products,
categories, brands, and cached top questions from analytics.
"""
from __future__ import annotations

import re

from app.search import normalize, product_value


def _prefix_rank(normalized_query: str, candidate: str) -> int:
    """2 = candidate starts with the query, 1 = a word in candidate does, 0 = no match."""
    normalized_candidate = normalize(candidate)
    if not normalized_candidate:
        return 0
    if normalized_candidate.startswith(normalized_query):
        return 2
    if any(word.startswith(normalized_query) for word in normalized_candidate.split()):
        return 1
    return 0


def autocomplete_products(products: list, query: str, limit: int = 4) -> list[dict]:
    normalized_query = normalize(query).strip()
    if not normalized_query:
        return []

    ranked: list[tuple[int, dict]] = []
    seen_ids: set[str] = set()
    for product in products:
        title = str(product_value(product, "title", "")).strip()
        rank = _prefix_rank(normalized_query, title)
        if not rank:
            continue
        product_id = str(product_value(product, "id", ""))
        if product_id and product_id in seen_ids:
            continue
        seen_ids.add(product_id)

        availability = str(product_value(product, "availability", ""))
        in_stock = 1 if availability in {"in_stock", "in stock"} else 0
        price = product_value(product, "sale_price", None)
        if price is None:
            price = product_value(product, "price", None)

        ranked.append((
            rank * 10 + in_stock,
            {
                "title": title,
                "url": str(product_value(product, "link", "")),
                "price": price,
                "image": str(product_value(product, "image_link", "")),
            },
        ))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in ranked[:limit]]


def _distinct_prefix_matches(values: list[str], query: str, limit: int) -> list[str]:
    normalized_query = normalize(query).strip()
    if not normalized_query:
        return []
    best_rank: dict[str, int] = {}
    for value in values:
        clean = value.strip()
        if not clean:
            continue
        rank = _prefix_rank(normalized_query, clean)
        if not rank:
            continue
        if rank > best_rank.get(clean, 0):
            best_rank[clean] = rank
    ordered = sorted(best_rank.items(), key=lambda item: (item[1], item[0]), reverse=True)
    return [value for value, _ in ordered[:limit]]


def autocomplete_categories(products: list, query: str, limit: int = 3) -> list[str]:
    parts: list[str] = []
    for product in products:
        category = str(product_value(product, "product_type", product_value(product, "category", "")))
        parts.extend(part.strip() for part in re.split(r"[>/|]", category) if part.strip())
    return _distinct_prefix_matches(parts, query, limit)


def autocomplete_brands(products: list, query: str, limit: int = 3) -> list[str]:
    brands = [str(product_value(product, "brand", "")) for product in products]
    return _distinct_prefix_matches(brands, query, limit)


def autocomplete_questions(top_questions: list[dict], query: str, limit: int = 3) -> list[str]:
    normalized_query = normalize(query).strip()
    if not normalized_query:
        return []
    results: list[str] = []
    seen: set[str] = set()
    for row in top_questions:
        question = str(row.get("question", "")).strip()
        if not question or not _prefix_rank(normalized_query, question):
            continue
        key = normalize(question)
        if key in seen:
            continue
        seen.add(key)
        results.append(question)
        if len(results) >= limit:
            break
    return results
