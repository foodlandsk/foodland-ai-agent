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

RECIPE_INTENT_TOKENS = {
    "recept",
    "recepty",
    "jedlo",
    "jedla",
    "obed",
    "vecera",
    "varenie",
    "varit",
    "uvarit",
    "pripravit",
    "priprava",
}

IMPORTANT_FIELDS = {
    "FAQ": ["Otázka", "Odpoveď", "Kategória", "question", "answer", "category"],
    "Products_AI": [
        "Produkt (URL)", "Kategória", "Kuchyňa", "Cena", "Balenie", "GTIN", "Atribúty",
        "AI popis – SK", "AI popis – CZ", "AI popis – EN",
        "Cross-sell", "Alternatíva", "Súvisiaci recept", "Poznámka",
        "product_name", "synonyms", "category", "usage", "taste", "advisor_note",
        "Kucharsky tip - SK", "Nakupne odporucanie - SK", "Chutovy profil - SK",
        "Pouzitie v kuchyni - SK", "Kedy odporucit - SK", "Pozor / overit - SK",
        "Predajny argument - SK", "Agenticky dalsi krok - SK",
    ],
    "CrossSell": ["Produkt", "Kategoria", "Cross-sell 1", "Cross-sell 2", "Cross-sell 3", "Cross-sell 4", "Cross-sell 5"],
    "Alternatives": ["Produkt", "Kategoria", "Alternativa 1", "Alternativa 2", "Alternativa 3", "Alternativa 4", "Alternativa 5"],
    "Recipes": ["Recept (SK názov)", "Kuchyňa", "SK", "Poznámka (anomálie na webe)"],
    "Magazine": ["Článok (SK názov)", "Téma", "SK", "Poznámka (anomálie na webe)"],
    "IntentMapping": [
        "Typ zámeru", "Zámer (príklad otázky/vyhľadávania)", "Názov prepojeného obsahu",
        "Poznámka", "SK", "intent", "examples", "action", "source",
    ],
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
    content_tokens = query_tokens - RECIPE_INTENT_TOKENS
    effective_query_tokens = query_tokens
    if section == "Recipes" and content_tokens:
        effective_query_tokens = content_tokens

    fields = IMPORTANT_FIELDS.get(section) or list(record.keys())
    weighted_text = " ".join(str(record.get(field, "")) for field in fields)
    full_text = " ".join(str(value) for value in record.values())

    field_tokens = tokenize(weighted_text)
    full_tokens = tokenize(full_text)
    score = 0
    score += SECTION_WEIGHTS.get(section, 3) * len(effective_query_tokens & field_tokens)
    score += len(effective_query_tokens & full_tokens)

    normalized_query = normalize(query)
    normalized_weighted = normalize(weighted_text)
    if normalized_query and normalized_query in normalized_weighted:
        score += 12

    if section in {"CrossSell", "Alternatives"}:
        source_tokens = tokenize(str(record.get("Produkt") or ""))
        source_overlap = len(effective_query_tokens & source_tokens)
        if source_overlap >= 2:
            score += 8 * source_overlap
        normalized_source = normalize(str(record.get("Produkt") or ""))
        if normalized_source and normalized_source in normalized_query:
            score += 30

    if section == "Recipes" and query_tokens & RECIPE_INTENT_TOKENS and not content_tokens:
        score += 8

    if section == "FAQ":
        shipping_tokens = {
            "doprava", "dopravu", "dopravy", "doprave",
            "dorucenie", "dorucenia", "dorucit", "postovne", "kurier", "packeta",
        }
        price_tokens = {"kolko", "stoj", "stoji", "cena", "poplatok", "platba", "plati", "platit", "zadarmo"}
        if query_tokens & shipping_tokens and query_tokens & price_tokens and full_tokens & {"doprava", "dorucenie", "zadarmo"}:
            score += 8
            if "zadarmo" in full_tokens:
                score += 6
            normalized_full = normalize(full_text)
            if "kedy je doprava zadarmo" in normalized_full or "doprava je zadarmo" in normalized_full:
                score += 10

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
    if section == "Magazine":
        return join_parts(
            [
                first_matching_key_value(record, ["tema", "tma"]),
                first_matching_key_value(record, ["clanok", "lanok", "article"]),
                first_url_value(record),
                record.get("SK"),
            ],
            " | ",
        )

    if section == "Recipes":
        return join_parts(
            [
                first_matching_key_value(record, ["kuchy", "kuchyna"]),
                first_matching_key_value(record, ["recept"]),
                first_url_value(record),
                record.get("SK"),
            ],
            " | ",
        )

    if section == "FAQ":
        question = first_value(record, ["Otázka", "question"])
        answer = first_value(record, ["Odpoveď", "answer"])
        category = first_value(record, ["Kategória", "category"])
        return join_parts([category, question, answer], " | ")

    if section == "Products_AI":
        return join_parts(
            [
                first_url_value(record),
                first_matching_key_value(record, ["kategoria", "category"]),
                first_matching_key_value(record, ["kuchyn", "kuchy"]),
                record.get("Cena"),
                record.get("Balenie"),
                record.get("GTIN"),
                first_matching_key_value(record, ["atribut"]),
                first_matching_key_value(record, ["ai popis", "popis"]),
                first_matching_key_value(record, ["cross"]),
                first_matching_key_value(record, ["alternat"]),
                first_matching_key_value(record, ["suvisiaci", "recept"]),
                record.get("product_name"),
                record.get("category"),
                record.get("usage"),
                record.get("taste"),
                record.get("advisor_note"),
                first_matching_key_value(record, ["kucharsky tip", "kucharsky"]),
                first_matching_key_value(record, ["nakupne odporucanie", "nakupne"]),
                first_matching_key_value(record, ["chutovy profil", "chutovy"]),
                first_matching_key_value(record, ["pouzitie v kuchyni", "pouzitie"]),
                first_matching_key_value(record, ["kedy odporucit", "odporucit"]),
                first_matching_key_value(record, ["pozor", "overit"]),
                first_matching_key_value(record, ["predajny argument", "predajny"]),
                first_matching_key_value(record, ["agenticky dalsi krok", "agenticky"]),
            ],
            " | ",
        )

    if section == "CrossSell":
        recommendations = [
            recommendation_with_url(record, f"Cross-sell {index}")
            for index in range(1, 6)
            if record.get(f"Cross-sell {index}")
        ]
        return join_parts(
            [
                recommendation_with_url(record, "Produkt"),
                record.get("Kategoria"),
                "; ".join(recommendations),
            ],
            " | ",
        )

    if section == "Alternatives":
        alternatives = [
            recommendation_with_url(record, f"Alternativa {index}")
            for index in range(1, 6)
            if record.get(f"Alternativa {index}")
        ]
        return join_parts(
            [
                recommendation_with_url(record, "Produkt"),
                record.get("Kategoria"),
                "; ".join(alternatives),
            ],
            " | ",
        )

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
        return join_parts(
            [
                record.get("Typ zámeru") or record.get("intent"),
                record.get("Zámer (príklad otázky/vyhľadávania)") or record.get("examples"),
                record.get("Názov prepojeného obsahu") or first_matching_key_value(record, ["nazov prepojeneho", "prepojeneho obsahu"]),
                first_url_value(record),
                record.get("action"),
                record.get("source"),
                first_matching_key_value(record, ["poznamka"]),
            ],
            " | ",
        )

    return join_parts(record.values(), " | ")


def knowledge_summary(results: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    return {section: len(hits) for section, hits in results.items()}


def content_cards(results: dict[str, list[dict[str, Any]]], lang: str = "SK") -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    lang = normalize_lang(lang)

    seen_urls: set[str] = set()

    for hit in results.get("CrossSell", [])[:2]:
        record = hit["record"]
        source_product = str(record.get("Produkt") or "").strip()
        for index in range(1, 6):
            title = str(record.get(f"Cross-sell {index}") or "").strip()
            url = str(record.get(f"Cross-sell {index}_url") or "").strip()
            if not title or not url or url in seen_urls:
                continue
            seen_urls.add(url)
            cards.append(
                {
                    "type": "cross_sell",
                    "title": clean_recommendation_title(title),
                    "source_product": clean_recommendation_title(source_product),
                    "subtitle": f"Súvisiace k: {source_product}" if source_product else "Súvisiaci produkt",
                    "url": url,
                    "button_label": "Zobraziť produkt",
                }
            )
            if len(cards) >= 4:
                break
        if len(cards) >= 4:
            break

    for hit in results.get("Alternatives", [])[:2]:
        record = hit["record"]
        source_product = str(record.get("Produkt") or "").strip()
        for index in range(1, 6):
            title = str(record.get(f"Alternativa {index}") or "").strip()
            url = str(record.get(f"Alternativa {index}_url") or "").strip()
            if not title or not url or url in seen_urls:
                continue
            if normalize(clean_recommendation_title(title)) == normalize(clean_recommendation_title(source_product)):
                continue
            seen_urls.add(url)
            cards.append(
                {
                    "type": "alternative",
                    "title": clean_recommendation_title(title),
                    "source_product": clean_recommendation_title(source_product),
                    "subtitle": f"Alternatíva k: {source_product}" if source_product else "Alternatíva produktu",
                    "url": url,
                    "button_label": "Zobraziť produkt",
                }
            )
            if len(cards) >= 4:
                break
        if len(cards) >= 4:
            break

    for hit in results.get("Recipes", [])[:3]:
        record = hit["record"]
        title = first_matching_key_value(record, ["recept"])
        if not title:
            continue
        cards.append(
                {
                    "type": "recipe",
                    "title": title,
                    "subtitle": first_matching_key_value(record, ["kuchy", "kuchyna"]),
                    "url": first_url_value(record, lang),
                    "button_label": "Zobraziť recept",
                }
            )

    for hit in results.get("Magazine", [])[:3]:
        record = hit["record"]
        title = first_matching_key_value(record, ["clanok", "lanok", "article"])
        if not title:
            continue
        cards.append(
                {
                    "type": "article",
                    "title": title,
                    "subtitle": first_matching_key_value(record, ["tema", "tma"]),
                    "url": first_url_value(record, lang),
                    "button_label": "Čítať článok",
                }
            )

    for hit in results.get("IntentMapping", [])[:2]:
        record = hit["record"]
        title = record.get("Názov prepojeného obsahu") or first_matching_key_value(record, ["nazov prepojeneho", "prepojeneho obsahu"])
        url = first_url_value(record, lang)
        if not title or not url:
            continue
        cards.append(
            {
                "type": "link",
                "title": title,
                "subtitle": record.get("Typ zámeru") or first_matching_key_value(record, ["typ zameru", "intent"]),
                "url": url,
                "button_label": "Otvoriť stránku",
            }
        )

    return cards


def normalize_lang(lang: str) -> str:
    normalized = (lang or "SK").upper()
    if normalized not in {"SK", "CZ", "AT", "EN", "PL", "HU", "VI"}:
        return "SK"
    return normalized


def is_recipe_query(query: str) -> bool:
    return bool(tokenize(query) & RECIPE_INTENT_TOKENS)


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


def first_matching_key_value(record: dict[str, Any], fragments: list[str]) -> str:
    normalized_fragments = [normalize(fragment) for fragment in fragments]
    for key, value in record.items():
        normalized_key = normalize(str(key))
        if value and any(fragment in normalized_key for fragment in normalized_fragments):
            return str(value)
    return ""


def first_url_value(record: dict[str, Any], lang: str = "SK") -> str:
    lang = normalize_lang(lang)
    preferred_keys = [f"{lang}_url", lang]
    for key in preferred_keys:
        value = record.get(key)
        if not value:
            continue
        text = str(value).strip()
        if text.startswith(("http://", "https://")):
            return text

    url_fragments = ["url", "link", "odkaz", "href"]
    for key, value in record.items():
        if not value:
            continue
        text = str(value).strip()
        normalized_key = normalize(str(key))
        if any(fragment in normalized_key for fragment in url_fragments) and text.startswith(("http://", "https://")):
            return text

    for value in record.values():
        if not value:
            continue
        text = str(value).strip()
        if text.startswith(("http://", "https://")):
            return text

    return ""


def recommendation_with_url(record: dict[str, Any], key: str) -> str:
    value = str(record.get(key) or "").strip()
    url = str(record.get(f"{key}_url") or "").strip()
    if value and url:
        return f"{value} ({url})"
    return value


def clean_recommendation_title(value: str) -> str:
    for separator in [" – ", " - "]:
        if separator in value:
            return value.split(separator, 1)[0].strip()
    return value.strip()


def best_recipe_answer(results: dict[str, list[dict[str, Any]]]) -> str | None:
    hits = results.get("Recipes", [])
    if not hits:
        return None

    recipes = []
    for hit in hits[:3]:
        record = hit["record"]
        title = first_matching_key_value(record, ["recept"])
        cuisine = first_matching_key_value(record, ["kuchy", "kuchyna"])
        if title and cuisine:
            recipes.append(f"{title} ({cuisine})")
        elif title:
            recipes.append(title)

    if not recipes:
        return None

    count = len(recipes)
    if count == 1:
        return f"Našiel som jeden vhodný recept: {recipes[0]}. Otvoriť si ho môžete nižšie."
    return f"Našiel som {count} vhodné recepty: " + "; ".join(recipes) + ". Otvoriť si ich môžete nižšie."


def join_parts(values, separator: str) -> str:
    return separator.join(str(value) for value in values if value)
