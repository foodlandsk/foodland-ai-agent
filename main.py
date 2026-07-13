from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.search import normalize, tokenize


SECTION_LIMITS = {
    "FAQ": 4,
    "Products_AI": 4,
    "CrossSell": 3,
    "Alternatives": 3,
    "Recipes": 3,
    "Magazine": 2,
    "IntentMapping": 2,
}

SECTION_WEIGHTS = {
    "FAQ": 8,
    "Products_AI": 7,
    "CrossSell": 5,
    "Alternatives": 5,
    "Recipes": 4,
    "Magazine": 3,
    "IntentMapping": 3,
}

SECTION_MIN_SCORES = {
    "FAQ": 10,
    "Products_AI": 4,
    "CrossSell": 4,
    "Alternatives": 4,
    "Recipes": 4,
    "Magazine": 4,
    "IntentMapping": 4,
}

IMPORTANT_FIELDS = {
    "FAQ": ["Otázka", "Odpoveď", "Kategória", "question", "answer", "category"],
    "Products_AI": ["product_name", "synonyms", "category", "usage", "taste", "advisor_note"],
    "CrossSell": ["Produkt", "Kategoria", "Cross-sell 1", "Cross-sell 2", "Cross-sell 3", "Cross-sell 4", "Cross-sell 5"],
    "Alternatives": ["Produkt", "Kategoria", "Alternativa 1", "Alternativa 2", "Alternativa 3", "Alternativa 4", "Alternativa 5"],
    "Recipes": ["Recept (SK názov)", "Kuchyňa", "SK", "Poznámka (anomálie na webe)"],
    "Magazine": ["Článok (SK názov)", "Téma", "SK", "Poznámka (anomálie na webe)"],
    "IntentMapping": ["intent", "examples", "action", "source"],
}


def load_knowledge_json(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {"version": "missing", "sections": {}, "counts": {}}
    return json.loads(file_path.read_text(encoding="utf-8"))


def search_knowledge(knowledge: dict[str, Any], query: str) -> dict[str, list[dict[str, Any]]]:
    query_tokens = tokenize(query)
    if not query_tokens:
        return {}

    sections = knowledge.get("sections", {})
    results: dict[str, list[dict[str, Any]]] = {}
    for section, records in sections.items():
        ranked: list[tuple[int, dict[str, Any]]] = []
        for record in records:
            score = score_record(section, record, query, query_tokens)
            if score >= SECTION_MIN_SCORES.get(section, 1):
                ranked.append((score, record))

        ranked.sort(key=lambda item: item[0], reverse=True)
        limit = SECTION_LIMITS.get(section, 3)
        results[section] = [
            {"score": score, "record": record}
            for score, record in ranked[:limit]
        ]

    return {section: hits for section, hits in results.items() if hits}


def score_record(section: str, record: dict[str, Any], query: str, query_tokens: set[str]) -> int:
    fields = IMPORTANT_FIELDS.get(section) or list(record.keys())
    weighted_text = " ".join(str(record.get(field, "")) for field in fields)
    full_text = " ".join(str(value) for value in record.values())

    field_tokens = tokenize(weighted_text)
    full_tokens = tokenize(full_text)
    score = 0
    score += SECTION_WEIGHTS.get(section, 3) * len(query_tokens & field_tokens)
    score += len(query_tokens & full_tokens)

    normalized_query = normalize(query)
    normalized_weighted = normalize(weighted_text)
    if normalized_query and normalized_query in normalized_weighted:
        score += 12

    return score


def knowledge_context(results: dict[str, list[dict[str, Any]]]) -> str:
    parts: list[str] = []
    for section in ["FAQ", "Products_AI", "CrossSell", "Alternatives", "Recipes", "Magazine", "IntentMapping"]:
        hits = results.get(section, [])
        if not hits:
            continue
        parts.append(f"{section}:")
        for hit in hits:
            parts.append(f"- {format_record(section, hit['record'])}")
    return "\n".join(parts)


def format_record(section: str, record: dict[str, Any]) -> str:
    if section == "FAQ":
        question = first_value(record, ["Otázka", "question"])
        answer = first_value(record, ["Odpoveď", "answer"])
        category = first_value(record, ["Kategória", "category"])
        return join_parts([category, question, answer], " | ")

    if section == "Products_AI":
        return join_parts(
            [
                record.get("product_name"),
                record.get("category"),
                record.get("usage"),
                record.get("taste"),
                record.get("advisor_note"),
            ],
            " | ",
        )

    if section == "CrossSell":
        recommendations = [
            record.get(f"Cross-sell {index}")
            for index in range(1, 6)
            if record.get(f"Cross-sell {index}")
        ]
        return join_parts([record.get("Produkt"), record.get("Kategoria"), "; ".join(recommendations)], " | ")

    if section == "Alternatives":
        alternatives = [
            record.get(f"Alternativa {index}")
            for index in range(1, 6)
            if record.get(f"Alternativa {index}")
        ]
        return join_parts([record.get("Produkt"), record.get("Kategoria"), "; ".join(alternatives)], " | ")

    if section == "Recipes":
        return join_parts(
            [
                first_value(record, ["Kuchyňa", "Kuchyna"]),
                first_value(record, ["Recept (SK názov)", "Recept (SK nazov)"]),
                record.get("SK"),
            ],
            " | ",
        )

    if section == "Magazine":
        return join_parts(
            [
                first_value(record, ["Téma", "Tema"]),
                first_value(record, ["Článok (SK názov)", "Clanok (SK nazov)"]),
                record.get("SK"),
            ],
            " | ",
        )

    if section == "IntentMapping":
        return join_parts([record.get("intent"), record.get("examples"), record.get("action")], " | ")

    return join_parts(record.values(), " | ")


def knowledge_summary(results: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    return {section: len(hits) for section, hits in results.items()}


def best_faq_answer(results: dict[str, list[dict[str, Any]]]) -> str | None:
    hits = results.get("FAQ", [])
    if not hits:
        return None
    return first_value(hits[0]["record"], ["Odpoveď", "answer"]) or None


def first_value(record: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = record.get(key)
        if value:
            return str(value)
    return ""


def join_parts(values, separator: str) -> str:
    return separator.join(str(value) for value in values if value)
