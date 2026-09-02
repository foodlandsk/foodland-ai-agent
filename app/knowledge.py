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
    "Products_AI": [
        "product_name",
        "synonyms",
        "category",
        "usage",
        "taste",
        "advisor_note",
        "Produkt (URL)",
        "Kategória",
        "Kuchyňa",
        "AI popis – SK",
        "Cross-sell",
        "Alternatíva",
        "Súvisiaci recept",
        "Kucharsky tip - SK",
        "Nakupne odporucanie - SK",
        "Chutovy profil - SK",
        "Pouzitie v kuchyni - SK",
        "Kedy odporucit - SK",
        "Pozor / overit - SK",
        "Predajny argument - SK",
        "Agenticky dalsi krok - SK",
    ],
    "CrossSell": ["Produkt", "Kategoria", "Cross-sell 1", "Cross-sell 2", "Cross-sell 3", "Cross-sell 4", "Cross-sell 5"],
    "Alternatives": ["Produkt", "Kategoria", "Alternativa 1", "Alternativa 2", "Alternativa 3", "Alternativa 4", "Alternativa 5"],
    "Recipes": ["Recept (SK názov)", "Kuchyňa", "SK", "Poznámka (anomálie na webe)"],
    "Magazine": ["Článok (SK názov)", "Téma", "SK", "Poznámka (anomálie na webe)"],
    "IntentMapping": [
        "intent",
        "examples",
        "action",
        "source",
        "Typ zámeru",
        "Zámer (príklad otázky/vyhľadávania)",
        "Názov prepojeného obsahu",
        "Poznámka",
    ],
}


def load_knowledge_json(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {"version": "missing", "sections": {}, "counts": {}}
    data = json.loads(file_path.read_text(encoding="utf-8"))
    # Inject missing recipes not yet indexed in knowledge.json
    _missing = [
        {"Recept (SK n\u00e1zov)": "Japonsk\u00e9 sushi a sashimi", "SK": "SK", "SK_url": "https://www.foodland.sk/recepty/japonske-sushi-a-sashimi/", "CZ": "CZ", "CZ_url": "https://www.foodland-express.cz/recepty/japonske-sushi-a-sashimi/", "AT": "AT", "AT_url": "https://www.foodland.at/rezepte/japanisches-sushi-und-sashimi/", "EN": "EN", "EN_url": "https://www.foodland-express.com/recipes/japanese-sushi-and-sashimi/", "PL": "PL", "PL_url": "https://www.foodland-express.pl/przepisy/japonskie-sushi-i-sashimi/", "HU": "HU", "HU_url": "https://www.foodland.hu/receptek/japan-sushi-es-sashimi/", "VI": "VI", "VI_url": "https://vn.foodland.sk/cong-thuc-mon-an/sushi-va-sashimi-nhat-ban/"},
        {"Recept (SK n\u00e1zov)": "20-min\u00fatov\u00e9 japonsk\u00e9 kuracie kari", "SK": "SK", "SK_url": "https://www.foodland.sk/recepty/20-minutove-japonske-kuracie-kari/", "CZ": "CZ", "CZ_url": "https://www.foodland-express.cz/recepty/20minutove-japonske-kureci-kari/", "AT": "AT", "AT_url": "https://www.foodland.at/rezepte/20-minutiges-japanisches-huhnchen-curry/", "EN": "EN", "EN_url": "https://www.foodland-express.com/recipes/20-minute-japanese-chicken-curry/", "PL": "PL", "PL_url": "https://www.foodland-express.pl/przepisy/20-minutowe-japonskie-curry-z-kurczakiem/", "HU": "HU", "HU_url": "https://www.foodland.hu/receptek/20-perces-japan-csirke-curry/", "VI": "VI", "VI_url": "https://vn.foodland.sk/cong-thuc-mon-an/ca-ri-ga-kieu-nhat-voi-20-phut/"},
        {"Recept (SK n\u00e1zov)": "Thajsk\u00e9 kokosov\u00e9 kari s tekvicou a c\u00edcerom (veg\u00e1nske)", "SK": "SK", "SK_url": "https://www.foodland.sk/recepty/thajske-kokosove-kari-s-tekvicou-a-cicerom-veganske/", "CZ": "CZ", "CZ_url": "https://www.foodland-express.cz/recepty/thajske-kokosove-kari-s-dyni-a-cizrnou-veganske/", "AT": "AT", "AT_url": "https://www.foodland.at/rezepte/thailandisches-kokos-curry-mit-kurbis-und-kichererbsen-vegan/", "EN": "EN", "EN_url": "https://www.foodland-express.com/recipes/thai-coconut-curry-with-pumpkin-and-chickpeas-vegan/", "PL": "PL", "PL_url": "https://www.foodland-express.pl/przepisy/tajskie-curry-kokosowe-z-dynia-i-ciecierzyca-weganskie/", "HU": "HU", "HU_url": "https://www.foodland.hu/receptek/thai-kokuszos-curry-tokkel-es-csicseriborsoval-vegan/", "VI": "VI", "VI_url": "https://vn.foodland.sk/cong-thuc-mon-an/ca-ri-dua-thai-voi-bi-do-va-dau-ga-thuan-chay/"},
    ]
    recipes = data.setdefault("sections", {}).setdefault("Recipes", [])
    existing = {r.get("Recept (SK n\u00e1zov)") for r in recipes}
    for r in _missing:
        if r.get("Recept (SK n\u00e1zov)") not in existing:
            recipes.append(r)
    return data


def search_knowledge(
    knowledge: dict[str, Any],
    query: str,
    allowed_sections: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    query_tokens = tokenize(query)
    if not query_tokens:
        return {}

    sections = knowledge.get("sections", {})
    allowed = set(allowed_sections) if allowed_sections else None
    results: dict[str, list[dict[str, Any]]] = {}
    for section, records in sections.items():
        if allowed is not None and section not in allowed:
            continue
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
        taste = first_value(record, ["taste", "Chutovy profil - SK"])
        if _is_broken_curation_placeholder(taste):
            taste = ""
        kucharsky_tip = record.get("Kucharsky tip - SK")
        if _is_broken_curation_placeholder(kucharsky_tip):
            kucharsky_tip = ""
        return join_parts(
            [
                first_value(record, ["product_name", "Produkt (URL)"]),
                first_value(record, ["category", "Kategória"]),
                first_value(record, ["usage", "Pouzitie v kuchyni - SK"]),
                taste,
                first_value(record, ["advisor_note", "Nakupne odporucanie - SK"]),
                kucharsky_tip,
                record.get("Kedy odporucit - SK"),
                record.get("Pozor / overit - SK"),
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
        return join_parts(
            [
                first_value(record, ["intent", "Typ zámeru"]),
                first_value(record, ["examples", "Zámer (príklad otázky/vyhľadávania)"]),
                first_value(record, ["action", "Názov prepojeného obsahu"]),
                first_value(record, ["source", "Poznámka"]),
            ],
            " | ",
        )

    return join_parts(record.values(), " | ")


def knowledge_summary(results: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    return {section: len(hits) for section, hits in results.items()}


def best_faq_answer(results: dict[str, list[dict[str, Any]]]) -> str | None:
    hits = results.get("FAQ", [])
    if not hits:
        return None
    return first_value(hits[0]["record"], ["Odpoveď", "answer"]) or None


def best_product_advice_answer(
    results: dict[str, list[dict[str, Any]]],
    matched_links: set[str] | None = None,
) -> str | None:
    """Only "taste"/"usage" are genuinely customer-facing prose - other
    Products_AI fields (e.g. "Kedy odporucit - SK", "Pozor / overit - SK")
    are internal instructions written for the AI, not sentences to show a
    customer. Also require the record to match one of the products already
    found for this query: a topical keyword match (e.g. "chilli sauce") can
    outscore the one Products_AI record that's actually about the product
    being asked about, or land on an unrelated one entirely.
    """
    hits = results.get("Products_AI", [])
    if not hits:
        return None
    record = None
    if matched_links:
        for hit in hits:
            url = hit["record"].get("Produkt (URL)") or hit["record"].get("product_name")
            if url and url in matched_links:
                record = hit["record"]
                break
    elif hits:
        record = hits[0]["record"]
    if record is None:
        return None
    taste = first_value(record, ["taste", "Chutovy profil - SK"])
    if _is_broken_curation_placeholder(taste):
        taste = ""
    usage = first_value(record, ["usage", "Pouzitie v kuchyni - SK"])
    parts = [part for part in (taste, usage) if part]
    if not parts:
        return None
    return " ".join(parts[:2])


_BROKEN_CURATION_MARKERS = (
    "nevymyslaj zlozenie",
    "urci podla nazvu produktu",
    "formuluj prirodzene",
    "genericka ai odpoved",
    "najprv zisti, ci zakaznik",
)


def _is_broken_curation_placeholder(text: str) -> bool:
    """V2.16e (Section 58/59, explanation claim-safety audit) - the
    Products_AI curated sheet's AI-content-generation pipeline
    (app.knowledge_builder's own prompt template) left its instructional
    template text in the cell instead of real generated content for a
    large share of records - live-confirmed: "Chutovy profil - SK"/
    "Kucharsky tip - SK" are broken for 63/130 (48.5%) records, e.g.
    literally "profil urci podla nazvu produktu, kategorie a detailu na
    webe; nevymyslaj zlozenie" (an instruction TO an AI author, not a
    sentence ABOUT a product). One such record was reproduced live,
    verbatim, as the customer-facing answer to "Preco prave tento?"
    during V2.16e characterization. Fixing the source data belongs to
    the curation pipeline (out of scope here, see
    docs/recommendation-explanation-transparency-v2.16e.md) - this guard
    only stops the known-broken pattern from being treated as real
    content at its two customer/LLM-context read sites
    (best_product_advice_answer(), format_record()); it does not
    attempt to repair or regenerate it, and other Products_AI fields
    (usage/advisor_note/Kedy odporucit/Pozor-overit) were live-audited
    clean (0/130) and are left untouched."""
    normalized_text = str(text or "").lower()
    return any(marker in normalized_text for marker in _BROKEN_CURATION_MARKERS)


def first_value(record: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = record.get(key)
        if value:
            return str(value)
    return ""


def join_parts(values, separator: str) -> str:
    return separator.join(str(value) for value in values if value)
