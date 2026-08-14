"""Autocomplete endpoint helpers: prefix and token matching over products,
categories, brands, and cached top questions from analytics.

Sprint V2.2 adds two taxonomy/knowledge-grounded suggestion sources
(taxonomy_category_suggestions, question_suggestions) - deterministic,
no LLM calls, no invented labels. Both operate on small precomputed
inputs (a concept list, a curated knowledge subset) so they stay cheap
enough for per-keystroke use even though they use order-independent
multi-token matching instead of the simple single-prefix check below.
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
                "brand": str(product_value(product, "brand", "")),
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


def _token_wise_match_score(normalized_query: str, candidate_normalized: str) -> int:
    """Order-independent multi-token prefix match (Sprint V2.2).

    Unlike _prefix_rank above (single whole-string prefix, or one word of
    the candidate matching the whole query), this treats the query itself
    as multiple tokens and requires each one to prefix-match SOME token in
    the candidate, in any order - so "ryza basmati" and "basmati ryza"
    both match "Basmati ryža", and "rozdiel jaz" matches a question
    starting "Aký je rozdiel medzi jazmínovou...". 0 = no match.
    """
    if not normalized_query or not candidate_normalized:
        return 0
    if candidate_normalized.startswith(normalized_query):
        return 100
    query_tokens = [t for t in normalized_query.split() if t]
    candidate_tokens = candidate_normalized.split()
    if not query_tokens or not candidate_tokens:
        return 0
    matched = sum(1 for qt in query_tokens if any(ct.startswith(qt) for ct in candidate_tokens))
    if matched == len(query_tokens):
        return 50 + matched
    return matched


def taxonomy_category_suggestions(query: str, concepts: list[dict], limit: int = 4) -> list[dict]:
    """Taxonomy-grounded compound category suggestions (Sprint V2.2).

    `concepts` is app.taxonomy.build_concept_index() output - precomputed
    once per feed refresh, so this function only does cheap string
    matching per keystroke, no catalog scan. Every returned suggestion
    maps to real, currently-classified catalog products (product_count).
    """
    normalized_query = normalize(query).strip()
    if not normalized_query:
        return []

    ranked: list[tuple[int, dict]] = []
    for concept in concepts:
        label_normalized = normalize(concept["label"])
        match_score = _token_wise_match_score(normalized_query, label_normalized)
        if not match_score:
            continue
        ranked.append((match_score * 10 + min(concept["product_count"], 9), concept))

    ranked.sort(key=lambda item: item[0], reverse=True)
    results = []
    for _, concept in ranked[:limit]:
        constraints = {"family": concept["family"], **concept["attributes"]}
        if concept["subfamily"]:
            constraints["subfamily"] = concept["subfamily"]
        results.append({
            "type": "taxonomy_category",
            "label": concept["label"],
            "query": concept["label"],
            "action": "APPLY_CONSTRAINTS",
            "constraints": constraints,
            "product_count": concept["product_count"],
        })
    return results


# Two of the 19 curated "výber produktu" (product-choice) IntentMapping
# records are explicit product-vs-product comparisons ("Aký je rozdiel
# medzi..."); the rest are single-concept advice questions. Marker-based,
# not a separate hand-maintained list - deterministic (Section 19).
_COMPARISON_QUESTION_MARKERS = ("rozdiel", " vs ", "verzus")


def question_suggestions(knowledge: dict, query: str, limit: int = 3) -> list[dict]:
    """Grounded QUESTION/COMPARISON suggestions from data/knowledge.json's
    curated IntentMapping "výber produktu" (product-choice) records only
    (Sprint V2.2) - never magazine/FAQ text or LLM-generated phrasing.
    """
    normalized_query = normalize(query).strip()
    if not normalized_query:
        return []

    records = knowledge.get("sections", {}).get("IntentMapping", []) if isinstance(knowledge, dict) else []
    ranked: list[tuple[int, dict]] = []
    seen: set[str] = set()
    for record in records:
        intent_type = str(record.get("Typ zámeru", ""))
        if not intent_type.endswith("výber produktu"):
            continue
        question = str(record.get("Zámer (príklad otázky/vyhľadávania)", "")).strip()
        if not question:
            continue
        key = normalize(question)
        if key in seen:
            continue
        normalized_question = normalize(question)
        score = _token_wise_match_score(normalized_query, normalized_question)
        if not score:
            continue
        seen.add(key)
        is_comparison = any(marker in normalized_question for marker in _COMPARISON_QUESTION_MARKERS)
        ranked.append((score, {
            "type": "comparison" if is_comparison else "question",
            "label": question,
            "query": question,
            "action": "ASK_QUESTION",
        }))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in ranked[:limit]]


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
