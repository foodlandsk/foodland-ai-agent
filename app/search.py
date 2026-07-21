from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, is_dataclass

from app.feed import Product


PHRASE_SYNONYMS = {
    "soja sos": "sojova omacka",
    "soy sauce": "sojova omacka",
    "fish sauce": "rybacia omacka",
    "rice vinegar": "ryzovy ocot",
    "rice paper": "ryzovy papier",
    "coconut milk": "kokosove mlieko",
    "kokosove mliko": "kokosove mlieko",
    "sushi rice": "sushi ryza",
    "glass noodles": "sklenene rezance",
    "spring rolls": "jarne zavitky",
    "hot sauce": "chili omacka",
    "sojovka": "sojova omacka",
    "chin su": "chin-su",
}

TOKEN_SYNONYMS = {
    "sos": {"omacka"},
    "omaca": {"omacka"},
    "omaka": {"omacka"},
    "susi": {"sushi"},
    "soy": {"sojova"},
    "soya": {"sojova"},
    "sojovka": {"sojova", "omacka"},
    "coconut": {"kokosove"},
    "kokos": {"kokosove"},
    "milk": {"mlieko"},
    "mliko": {"mlieko"},
    "chilli": {"chili"},
    "cili": {"chili"},
    "nudle": {"rezance"},
    "noodles": {"rezance", "nudle"},
    "vinegar": {"ocot"},
}

POPULARITY_BOOSTS = {
    "sushi": 7,
    "kimchi": 7,
    "ramen": 6,
    "gochujang": 6,
    "sriracha": 5,
    "kokosove": 4,
    "sojova": 4,
    "ryza": 4,
    "nori": 3,
    "miso": 3,
}

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


def expand_query(value: str) -> str:
    normalized = normalize(value)
    additions: list[str] = []
    for phrase, replacement in PHRASE_SYNONYMS.items():
        if phrase in normalized:
            additions.append(replacement)
    return " ".join([value, *additions]).strip()


def tokenize(value: str) -> set[str]:
    tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", normalize(expand_query(value)))
        if len(token) >= 2 and token not in STOPWORDS
    }
    expanded = set(tokens)
    for token in tokens:
        expanded.update(TOKEN_SYNONYMS.get(token, set()))
        if token.startswith("bezlepk"):
            expanded.update({"bezlepkovy", "bezlepkova", "bezlepkovu", "bezlepkove"})
        if token.startswith("sojov"):
            expanded.update({"sojova", "sojovu", "sojove", "sojovy"})
        if token.startswith("omack"):
            expanded.update({"omacka", "omacku", "omacky"})
        if token.startswith("rybac") or token.startswith("rybi"):
            expanded.update({"rybacia", "rybiu", "rybia"})
        if token == "fish":
            expanded.update({"rybacia", "rybiu", "rybia"})
        if token == "sauce":
            expanded.update({"omacka", "omacku", "omacky"})
        if token == "sesame":
            expanded.update({"sezamovy", "sezamova", "sezamove"})
        if token == "oil":
            expanded.update({"olej"})
        if token == "rice":
            expanded.update({"ryza", "ryzovy"})
        if token == "paper":
            expanded.update({"papier"})
        if token.startswith("kredit"):
            expanded.add("kredit")
        if token.startswith("srirach") or token.startswith("srirac") or token.startswith("sirach"):
            expanded.add("sriracha")
        if token in {"sushi", "susi", "sushy"}:
            expanded.update({"sushi", "susi"})
        if token.startswith("ryz"):
            expanded.add("ryza")
        if token.startswith("kimchi") or token.startswith("kimci") or token.startswith("kimchee"):
            expanded.add("kimchi")
        if (
            token.startswith("gochuj")
            or token.startswith("gochuang")
            or token.startswith("gochud")
            or token.startswith("gocud")
            or token.startswith("gocuj")
        ):
            expanded.add("gochujang")
    return expanded


def edit_distance(a: str, b: str, max_distance: int = 2) -> int:
    if abs(len(a) - len(b)) > max_distance:
        return max_distance + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        row_min = i
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
            row_min = min(row_min, current[-1])
        if row_min > max_distance:
            return max_distance + 1
        previous = current
    return previous[-1]


def fuzzy_hits(query_tokens: set[str], field_tokens: set[str]) -> int:
    hits = 0
    for query_token in query_tokens:
        if len(query_token) < 4:
            continue
        if any(edit_distance(query_token, field_token, 1 if len(query_token) <= 6 else 2) <= (1 if len(query_token) <= 6 else 2) for field_token in field_tokens):
            hits += 1
    return hits


def product_value(product: Product | dict, key: str, default=""):
    if isinstance(product, dict):
        return product.get(key, default)
    return getattr(product, key, default)


def search_products(products: list[Product] | list[dict], query: str, limit: int = 8) -> list[dict]:
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    normalized_query = normalize(query)
    wants_sushi_rice = {"ryza"} <= query_tokens and bool({"sushi", "susi"} & query_tokens)

    ranked: list[tuple[int, bool, Product]] = []
    for product in products:
        title_tokens = tokenize(str(product_value(product, "title", "")))
        category_tokens = tokenize(str(product_value(product, "product_type", product_value(product, "category", ""))))
        brand_tokens = tokenize(str(product_value(product, "brand", "")))
        description_tokens = tokenize(str(product_value(product, "description", "")))
        normalized_title = normalize(str(product_value(product, "title", "")))

        title_hits = len(query_tokens & title_tokens)
        brand_hits = len(query_tokens & brand_tokens)
        category_hits = len(query_tokens & category_tokens)
        description_hits = len(query_tokens & description_tokens)
        fuzzy_title_hits = fuzzy_hits(query_tokens, title_tokens)
        fuzzy_category_hits = fuzzy_hits(query_tokens, category_tokens)

        score = 0
        score += 8 * title_hits
        score += 5 * brand_hits
        score += 4 * category_hits
        score += description_hits
        score += 4 * fuzzy_title_hits
        score += 2 * fuzzy_category_hits
        score += sum(POPULARITY_BOOSTS.get(token, 0) for token in query_tokens & (title_tokens | category_tokens))

        if normalized_query in normalized_title:
            score += 12

        if wants_sushi_rice:
            title_is_sushi_rice = (
                "ryza" in title_tokens
                and bool({"sushi", "susi"} & title_tokens)
                and "ocot" not in title_tokens
                and "vinegar" not in title_tokens
            )
            if title_is_sushi_rice:
                score += 18
            if "ocot" in title_tokens or "vinegar" in title_tokens:
                score -= 30

        strong_match = bool(title_hits or brand_hits or category_hits or fuzzy_title_hits or normalized_query in normalized_title)

        availability = str(product_value(product, "availability", ""))
        if score > 0 and availability in {"in_stock", "in stock"}:
            score += 3
        elif score > 0 and availability:
            score -= 2

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


def autocomplete_suggestions(products: list[Product] | list[dict], query: str, limit: int = 8) -> list[dict]:
    normalized_query = normalize(query).strip()
    if len(normalized_query) < 2:
        return []

    query_tokens = tokenize(query)
    suggestions: dict[str, dict] = {}

    def add(label: str, kind: str, score: int) -> None:
        clean = " ".join(str(label or "").split())
        if not clean:
            return
        key = normalize(clean)
        label_tokens = tokenize(clean)
        token_hits = len(query_tokens & label_tokens)
        fuzzy_token_hits = fuzzy_hits(query_tokens, label_tokens)
        direct_match = normalized_query in key or key.startswith(normalized_query)
        if not direct_match and not token_hits and not fuzzy_token_hits:
            return
        score += 18 if direct_match else 0
        score += 8 * token_hits
        score += 4 * fuzzy_token_hits
        existing = suggestions.get(key)
        if not existing or score > existing["score"]:
            suggestions[key] = {"label": clean[:80], "query": clean, "type": kind, "score": score}

    for phrase, replacement in PHRASE_SYNONYMS.items():
        add(replacement, "synonym", 80)
        add(phrase, "synonym", 70)

    for product in products:
        title = str(product_value(product, "title", ""))
        brand = str(product_value(product, "brand", ""))
        category = str(product_value(product, "product_type", product_value(product, "category", "")))
        availability = str(product_value(product, "availability", ""))
        availability_score = 5 if availability in {"in_stock", "in stock"} else 0
        add(title, "product", 60 + availability_score)
        add(brand, "brand", 45 + availability_score)
        for part in re.split(r"[>/|]", category):
            add(part, "category", 35 + availability_score)

    ordered = sorted(suggestions.values(), key=lambda item: item["score"], reverse=True)
    return [{k: v for k, v in item.items() if k != "score"} for item in ordered[:limit]]


def format_product(product: Product | dict) -> dict:
    if isinstance(product, dict):
        data = dict(product)
        if "effective_price" not in data:
            data["effective_price"] = data.get("sale_price") if data.get("sale_price") is not None else data.get("price")
        if "product_type" not in data and "category" in data:
            data["product_type"] = data.get("category", "")
        return data

    data = asdict(product) if is_dataclass(product) else dict(product)
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
