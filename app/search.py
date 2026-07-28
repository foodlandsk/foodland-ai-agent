from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, is_dataclass

from app.feed import Product


def _load_synonyms() -> dict:
    path = os.getenv("SYNONYMS_JSON_PATH", "data/synonyms.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


_SYNONYMS = _load_synonyms()
PHRASE_SYNONYMS: dict[str, str] = _SYNONYMS.get("phrases", {})
TOKEN_SYNONYMS: dict[str, set[str]] = {
    token: set(variants) for token, variants in _SYNONYMS.get("tokens", {}).items()
}
PREFIX_SYNONYMS: dict[str, set[str]] = {
    prefix: set(variants) for prefix, variants in _SYNONYMS.get("prefixes", {}).items()
}

BM25_ENABLED = os.getenv("BM25_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
BM25_WEIGHT = float(os.getenv("BM25_WEIGHT", "3.0"))
BM25_K1 = 1.5
BM25_B = 0.75

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

CONVERSATIONAL_NOISE_PHRASES = (
    "bez omacky okolo",
    "bez omacky",
    "bez zbytocnych reci",
    "nechcem nahodne produkty",
    "nie nahodne",
    "len strucne",
    "po slovensky",
    "zobrazit viac",
    "zobraz viac",
    "ukaz viac",
    "do kosika",
    "klikol som na tlacidlo",
    "rychle tlacidlo",
    "tlacidlo nereagovalo",
    "po znovuotvoreni widgetu",
    "po zatvoreni a otvoreni",
    "po otvoreni widgetu",
    "po zavreti widgetu",
    "opakujem otazku",
    "omylom som zavrel",
    "pisem v mobile",
    "som v mobile",
    "mobil",
    "rychlo",
    "este raz",
    "znova",
    "opat",
    "dakujem",
    "prosim",
    "pls",
)

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


def strip_conversational_noise(value: str) -> str:
    normalized = normalize(value)
    for phrase in CONVERSATIONAL_NOISE_PHRASES:
        normalized = normalized.replace(phrase, " ")
    return " ".join(normalized.split())


def expand_query(value: str) -> str:
    normalized = strip_conversational_noise(value)
    additions: list[str] = []
    for phrase, replacement in PHRASE_SYNONYMS.items():
        if phrase in normalized:
            additions.append(replacement)
    return " ".join([normalized, *additions]).strip()


def tokenize(value: str) -> set[str]:
    tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", normalize(expand_query(value)))
        if len(token) >= 2 and token not in STOPWORDS
    }
    expanded = set(tokens)
    for token in tokens:
        expanded.update(TOKEN_SYNONYMS.get(token, set()))
        for prefix, variants in PREFIX_SYNONYMS.items():
            if token.startswith(prefix):
                expanded.update(variants)
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


def raw_tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", normalize(value)) if token}


def strict_product_match(raw_query_tokens: set[str], normalized_title: str) -> bool:
    title_tokens = raw_tokens(normalized_title)
    if "soju" in raw_query_tokens:
        return "soju" in title_tokens
    if "shoyu" in raw_query_tokens:
        return "shoyu" in title_tokens or ("sojova" in title_tokens and "omacka" in title_tokens)
    return True


def product_value(product: Product | dict, key: str, default=""):
    if isinstance(product, dict):
        return product.get(key, default)
    return getattr(product, key, default)


@dataclass(slots=True)
class BM25Index:
    doc_freq: dict[str, int]
    doc_term_freq: dict[str, Counter]
    doc_lengths: dict[str, int]
    avgdl: float
    n_docs: int


def _bm25_document_tokens(product: Product | dict) -> list[str]:
    """Bag of tokens per product, field-weighted by repetition so title matches
    count for more than description matches - mirrors the title>brand>category>
    description priority search_products already uses for its heuristic score."""
    title_tokens = list(tokenize(str(product_value(product, "title", ""))))
    brand_tokens = list(tokenize(str(product_value(product, "brand", ""))))
    category_tokens = list(tokenize(str(product_value(product, "product_type", product_value(product, "category", "")))))
    description_tokens = list(tokenize(str(product_value(product, "description", ""))))
    return title_tokens * 3 + brand_tokens * 2 + category_tokens * 2 + description_tokens


def build_bm25_index(products: list[Product] | list[dict]) -> BM25Index:
    doc_freq: dict[str, int] = {}
    doc_term_freq: dict[str, Counter] = {}
    doc_lengths: dict[str, int] = {}
    total_length = 0

    for product in products:
        product_id = str(product_value(product, "id", ""))
        if not product_id or product_id in doc_term_freq:
            continue
        tokens = _bm25_document_tokens(product)
        term_freq = Counter(tokens)
        doc_term_freq[product_id] = term_freq
        doc_lengths[product_id] = len(tokens)
        total_length += len(tokens)
        for token in term_freq:
            doc_freq[token] = doc_freq.get(token, 0) + 1

    n_docs = len(doc_term_freq)
    avgdl = (total_length / n_docs) if n_docs else 0.0
    return BM25Index(doc_freq, doc_term_freq, doc_lengths, avgdl, n_docs)


_bm25_index_cache: dict[int, BM25Index] = {}


def get_bm25_index(products: list[Product] | list[dict]) -> BM25Index:
    """Cached by products-list identity, same pattern as main.py's product/
    autocomplete search caches: a feed refresh creates a new list object, so a
    stale entry is simply never looked up again rather than needing explicit
    invalidation."""
    key = id(products)
    cached = _bm25_index_cache.get(key)
    if cached is None:
        cached = build_bm25_index(products)
        if len(_bm25_index_cache) > 4:
            _bm25_index_cache.clear()
        _bm25_index_cache[key] = cached
    return cached


def bm25_score(index: BM25Index, product_id: str, query_tokens: set[str]) -> float:
    if not index.n_docs or not index.avgdl:
        return 0.0
    term_freq = index.doc_term_freq.get(product_id)
    if not term_freq:
        return 0.0
    doc_length = index.doc_lengths.get(product_id, 0)
    score = 0.0
    for token in query_tokens:
        freq = term_freq.get(token, 0)
        if not freq:
            continue
        doc_freq = index.doc_freq.get(token, 0)
        idf = math.log((index.n_docs - doc_freq + 0.5) / (doc_freq + 0.5) + 1)
        denom = freq + BM25_K1 * (1 - BM25_B + BM25_B * doc_length / index.avgdl)
        score += idf * (freq * (BM25_K1 + 1)) / denom
    return score


def search_products(products: list[Product] | list[dict], query: str, limit: int = 8) -> list[dict]:
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    normalized_query = strip_conversational_noise(query)
    raw_query_tokens = raw_tokens(query)
    wants_sushi_rice = {"ryza"} <= query_tokens and bool({"sushi", "susi"} & query_tokens)
    bm25_index = get_bm25_index(products) if BM25_ENABLED else None

    ranked: list[tuple[float, bool, Product]] = []
    for product in products:
        title_tokens = tokenize(str(product_value(product, "title", "")))
        category_tokens = tokenize(str(product_value(product, "product_type", product_value(product, "category", ""))))
        brand_tokens = tokenize(str(product_value(product, "brand", "")))
        description_tokens = tokenize(str(product_value(product, "description", "")))
        normalized_title = normalize(str(product_value(product, "title", "")))
        if not strict_product_match(raw_query_tokens, normalized_title):
            continue

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

        if bm25_index is not None:
            product_id = str(product_value(product, "id", ""))
            score += BM25_WEIGHT * bm25_score(bm25_index, product_id, query_tokens)

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
    normalized_query = strip_conversational_noise(query)
    if len(normalized_query) < 2:
        return []

    query_tokens = tokenize(query)
    raw_query_tokens = raw_tokens(query)
    suggestions: dict[str, dict] = {}

    def add(label: str, kind: str, score: int) -> None:
        clean = " ".join(str(label or "").split())
        if not clean:
            return
        key = normalize(clean)
        if kind == "product" and not strict_product_match(raw_query_tokens, key):
            return
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


def _product_effective_price(product: Product | dict) -> float | None:
    price = product_value(product, "sale_price", None)
    if price is None:
        price = product_value(product, "price", None)
    return price if isinstance(price, (int, float)) else None


def _matches_price_range(product: Product | dict, price_min: float | None, price_max: float | None) -> bool:
    if price_min is None and price_max is None:
        return True
    price = _product_effective_price(product)
    if price is None:
        return False
    if price_min is not None and price < price_min:
        return False
    if price_max is not None and price > price_max:
        return False
    return True


def _matches_brand(product: Product | dict, brands: list[str] | None) -> bool:
    if not brands:
        return True
    normalized_brand = normalize(str(product_value(product, "brand", "")))
    return normalized_brand in {normalize(brand) for brand in brands}


def _matches_availability(product: Product | dict, availability: str) -> bool:
    if availability == "all":
        return True
    in_stock = str(product_value(product, "availability", "")) in {"in_stock", "in stock"}
    if availability == "in_stock":
        return in_stock
    if availability == "out_of_stock":
        return not in_stock
    return True


def _matches_category_terms(product: Product | dict, terms: list[str] | None) -> bool:
    """Category and dietary filters both work as substring matches against the
    product_type breadcrumb - dietary attributes like "Bezlepkove potraviny"
    (gluten-free) or "Veganske potraviny" already live in there as their own
    breadcrumb segments, so no separate dietary taxonomy is needed."""
    if not terms:
        return True
    normalized_category = normalize(
        str(product_value(product, "product_type", product_value(product, "category", "")))
    )
    return any(normalize(term) in normalized_category for term in terms)


def filter_products(
    products: list[Product] | list[dict],
    price_min: float | None = None,
    price_max: float | None = None,
    brand: list[str] | None = None,
    availability: str = "all",
    category: list[str] | None = None,
    dietary: list[str] | None = None,
) -> list[Product | dict]:
    results = []
    for product in products:
        if not _matches_price_range(product, price_min, price_max):
            continue
        if not _matches_brand(product, brand):
            continue
        if not _matches_availability(product, availability):
            continue
        if not _matches_category_terms(product, category):
            continue
        if not _matches_category_terms(product, dietary):
            continue
        results.append(product)
    return results


def compute_product_facets(products: list[Product] | list[dict]) -> dict:
    brands: set[str] = set()
    categories: set[str] = set()
    prices: list[float] = []

    for product in products:
        brand_value = str(product_value(product, "brand", "")).strip()
        if brand_value:
            brands.add(brand_value)

        category_raw = str(product_value(product, "product_type", product_value(product, "category", "")))
        for part in re.split(r"[>/|]", category_raw):
            clean_part = part.strip()
            if clean_part:
                categories.add(clean_part)

        price = _product_effective_price(product)
        if price is not None:
            prices.append(price)

    return {
        "brands": sorted(brands, key=normalize),
        "categories": sorted(categories, key=normalize),
        "price_min": min(prices) if prices else None,
        "price_max": max(prices) if prices else None,
    }
