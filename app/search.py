from __future__ import annotations

import json
import logging
import math
import os
import re
import time
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, is_dataclass

from app.feed import Product

logger = logging.getLogger(__name__)
from app.behavioral import behavioral_multiplier, load_behavioral_rankings
from app.merchandising import (
    is_hidden,
    load_merchandising_rules,
    merchandising_multiplier,
    pins_for_query,
)


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

MERCHANDISING_CACHE_SECONDS = int(os.getenv("MERCHANDISING_CACHE_SECONDS", "60"))
_merchandising_rules_cache: dict | None = None
_merchandising_rules_cache_at: float = 0.0


def get_merchandising_rules() -> dict:
    """Cached so a hand-edited data/merchandising.json takes effect within
    MERCHANDISING_CACHE_SECONDS without needing a redeploy."""
    global _merchandising_rules_cache, _merchandising_rules_cache_at
    now = time.time()
    if _merchandising_rules_cache is None or now - _merchandising_rules_cache_at > MERCHANDISING_CACHE_SECONDS:
        _merchandising_rules_cache = load_merchandising_rules()
        _merchandising_rules_cache_at = now
    return _merchandising_rules_cache


def clear_merchandising_cache() -> None:
    global _merchandising_rules_cache, _merchandising_rules_cache_at
    _merchandising_rules_cache = None
    _merchandising_rules_cache_at = 0.0


BEHAVIORAL_RANKING_ENABLED = os.getenv("BEHAVIORAL_RANKING_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
BEHAVIORAL_RANKING_WEIGHT = float(os.getenv("BEHAVIORAL_RANKING_WEIGHT", "1.0"))
BEHAVIORAL_MIN_RATIO = float(os.getenv("BEHAVIORAL_MIN_RATIO", "0.5"))
BEHAVIORAL_MAX_RATIO = float(os.getenv("BEHAVIORAL_MAX_RATIO", "2.0"))
BEHAVIORAL_CACHE_SECONDS = int(os.getenv("BEHAVIORAL_CACHE_SECONDS", "300"))
_behavioral_rankings_cache: dict | None = None
_behavioral_rankings_cache_at: float = 0.0


def get_behavioral_rankings() -> dict:
    """Cached so a growing events.jsonl is only re-aggregated once every
    BEHAVIORAL_CACHE_SECONDS, not on every search."""
    global _behavioral_rankings_cache, _behavioral_rankings_cache_at
    now = time.time()
    if _behavioral_rankings_cache is None or now - _behavioral_rankings_cache_at > BEHAVIORAL_CACHE_SECONDS:
        _behavioral_rankings_cache = load_behavioral_rankings()
        _behavioral_rankings_cache_at = now
    return _behavioral_rankings_cache


def clear_behavioral_rankings_cache() -> None:
    global _behavioral_rankings_cache, _behavioral_rankings_cache_at
    _behavioral_rankings_cache = None
    _behavioral_rankings_cache_at = 0.0


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


def build_fuzzy_match_cache(query_tokens: set[str], vocabulary: frozenset[str]) -> dict[str, frozenset[str]]:
    """Sprint V2.2.1: the (product, field_token) fuzzy scan in search_products()/
    autocomplete_suggestions() called edit_distance() once per catalog token
    INSTANCE (~286k calls on a 2,140-product catalog), even though the same
    common words (e.g. "kg", "omacka", "ryza") repeat across hundreds of
    products - edit_distance(query_token, some_word) is a pure function of
    the two strings, so recomputing it per product instance was pure waste.
    This computes it once per (query_token, DISTINCT vocabulary token) pair
    instead - exactly equivalent results (same thresholds, same formula),
    just deduplicated. `vocabulary` is the catalog-wide distinct token set
    (see catalog_token_vocabulary() below)."""
    cache: dict[str, frozenset[str]] = {}
    for query_token in query_tokens:
        if len(query_token) < 4:
            continue
        max_distance = 1 if len(query_token) <= 6 else 2
        cache[query_token] = frozenset(
            token for token in vocabulary
            if edit_distance(query_token, token, max_distance) <= max_distance
        )
    return cache


_fuzzy_match_cache_by_query: dict[tuple[int, int, frozenset[str]], dict[str, frozenset[str]]] = {}
FUZZY_MATCH_CACHE_MAX_SIZE = 64


def get_fuzzy_match_cache(products: list[Product] | list[dict], query_tokens: set[str]) -> dict[str, frozenset[str]]:
    """search_autocomplete() calls both search_products() and
    autocomplete_suggestions() for the same query - without this, each
    independently rebuilt an identical build_fuzzy_match_cache(). Keyed by
    (products identity, query tokens), so a feed refresh invalidates it the
    same way as every other id(products)-keyed cache in this module."""
    key = (id(products), len(products), frozenset(query_tokens))
    cached = _fuzzy_match_cache_by_query.get(key)
    if cached is not None:
        return cached
    cached = build_fuzzy_match_cache(query_tokens, get_catalog_token_vocabulary(products))
    if len(_fuzzy_match_cache_by_query) >= FUZZY_MATCH_CACHE_MAX_SIZE:
        _fuzzy_match_cache_by_query.pop(next(iter(_fuzzy_match_cache_by_query)))
    _fuzzy_match_cache_by_query[key] = cached
    return cached


def fuzzy_hits_cached(query_tokens: set[str], field_tokens: frozenset[str], fuzzy_match_cache: dict[str, frozenset[str]]) -> int:
    """Same result as fuzzy_hits(query_tokens, field_tokens), but reuses a
    per-query build_fuzzy_match_cache() instead of calling edit_distance()
    again for every product."""
    hits = 0
    for query_token in query_tokens:
        matched_vocab = fuzzy_match_cache.get(query_token)
        if matched_vocab and (matched_vocab & field_tokens):
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


_bm25_index_cache: dict[tuple[int, int], BM25Index] = {}


def get_bm25_index(products: list[Product] | list[dict]) -> BM25Index:
    """Cached by products-list identity, same pattern as main.py's product/
    autocomplete search caches: a feed refresh creates a new list object, so a
    stale entry is simply never looked up again rather than needing explicit
    invalidation. Keyed by (id(products), len(products)), not id() alone -
    CPython can reuse a freed list's address for an unrelated new list, and
    id() alone would then wrongly hit this cache for different data
    (Sprint V2.2.1, caught by test_search_performance.py)."""
    key = (id(products), len(products))
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


@dataclass(slots=True)
class ProductTokenIndex:
    """Precomputed, per-product normalization/tokenization (Sprint V2.2.1).

    tokenize()/normalize() are pure functions of a field's text, which
    never changes between queries for the same product - recomputing them
    on every autocomplete keystroke for all ~2,300 products was the
    dominant cost in profiling (see docs/advisor-v2-architecture.md).
    Built once per products-list identity, same cache pattern as
    get_bm25_index() below, so a feed refresh (which creates a new list
    object) invalidates it automatically - no explicit rebuild call needed.
    """

    product_id: str
    title_normalized: str
    title_tokens: frozenset[str]
    brand_tokens: frozenset[str]
    category_parts: tuple[str, ...]
    category_part_tokens: tuple[frozenset[str], ...]
    category_tokens: frozenset[str]
    description_tokens: frozenset[str]


def _clean_field(value: str) -> str:
    """Same whitespace-collapse app.search.autocomplete_suggestions()'s
    add() already applies before normalize()/tokenize() - tokenize()
    itself is whitespace-run-insensitive (splits on any non-alnum run),
    but normalize() is not, so this keeps the precomputed index exactly
    equivalent to what both call sites computed inline before."""
    return " ".join(str(value or "").split())


def _build_product_token_entry(product: Product | dict) -> ProductTokenIndex:
    title = _clean_field(product_value(product, "title", ""))
    category_raw = str(product_value(product, "product_type", product_value(product, "category", "")))
    category_parts = tuple(
        cleaned for part in re.split(r"[>/|]", category_raw) if (cleaned := _clean_field(part))
    )
    category_part_tokens = tuple(frozenset(tokenize(part)) for part in category_parts)
    category_tokens: frozenset[str] = frozenset().union(*category_part_tokens) if category_part_tokens else frozenset()
    return ProductTokenIndex(
        product_id=str(product_value(product, "id", "")),
        title_normalized=normalize(title),
        title_tokens=frozenset(tokenize(title)),
        brand_tokens=frozenset(tokenize(_clean_field(product_value(product, "brand", "")))),
        category_parts=category_parts,
        category_part_tokens=category_part_tokens,
        category_tokens=category_tokens,
        description_tokens=frozenset(tokenize(str(product_value(product, "description", "")))),
    )


def build_product_token_index(products: list[Product] | list[dict]) -> dict[str, ProductTokenIndex]:
    index: dict[str, ProductTokenIndex] = {}
    for product in products:
        product_id = str(product_value(product, "id", ""))
        if not product_id:
            continue
        index[product_id] = _build_product_token_entry(product)
    return index


_product_token_index_cache: dict[tuple[int, int], dict[str, ProductTokenIndex]] = {}


def get_product_token_index(products: list[Product] | list[dict]) -> dict[str, ProductTokenIndex]:
    """Cached by products-list identity - see get_bm25_index() for why the
    key also includes len(products), not just id(products)."""
    key = (id(products), len(products))
    cached = _product_token_index_cache.get(key)
    if cached is None:
        cached = build_product_token_index(products)
        if len(_product_token_index_cache) > 4:
            _product_token_index_cache.clear()
        _product_token_index_cache[key] = cached
    return cached


_catalog_vocabulary_cache: dict[tuple[int, int], frozenset[str]] = {}


def get_catalog_token_vocabulary(products: list[Product] | list[dict]) -> frozenset[str]:
    """Distinct token set across every product's title/brand/category/
    description (~10k tokens for ~2,300 products, vs. hundreds of
    thousands of per-product token instances) - the input to
    build_fuzzy_match_cache(). Cached by products-list identity."""
    key = (id(products), len(products))
    cached = _catalog_vocabulary_cache.get(key)
    if cached is None:
        token_index = get_product_token_index(products)
        vocabulary: set[str] = set()
        for entry in token_index.values():
            vocabulary |= entry.title_tokens | entry.brand_tokens | entry.category_tokens | entry.description_tokens
        cached = frozenset(vocabulary)
        if len(_catalog_vocabulary_cache) > 4:
            _catalog_vocabulary_cache.clear()
        _catalog_vocabulary_cache[key] = cached
    return cached


def warm_search_indexes(products: list[Product] | list[dict]) -> None:
    """Build the BM25/token/vocabulary indexes for this products list right
    away (Sprint V2.2.1) instead of paying that cost on the first user
    autocomplete/search request after a feed refresh. Safe to call multiple
    times - every index below is cached by id(products), so a repeat call
    on the same list is a no-op lookup."""
    started_at = time.time()
    token_index = get_product_token_index(products)
    vocabulary = get_catalog_token_vocabulary(products)
    if BM25_ENABLED:
        get_bm25_index(products)
    logger.info(
        "Search indexes warmed: %d products, %d vocabulary tokens, %.3fs",
        len(token_index), len(vocabulary), time.time() - started_at,
    )


def search_products(products: list[Product] | list[dict], query: str, limit: int = 8) -> list[dict]:
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    normalized_query = strip_conversational_noise(query)
    raw_query_tokens = raw_tokens(query)
    wants_sushi_rice = {"ryza"} <= query_tokens and bool({"sushi", "susi"} & query_tokens)
    bm25_index = get_bm25_index(products) if BM25_ENABLED else None
    token_index = get_product_token_index(products)
    fuzzy_match_cache = get_fuzzy_match_cache(products, query_tokens)
    merchandising_rules = get_merchandising_rules()
    behavioral_rankings = get_behavioral_rankings() if BEHAVIORAL_RANKING_ENABLED else None

    ranked: list[tuple[float, bool, Product]] = []
    for product in products:
        product_id = str(product_value(product, "id", ""))
        if is_hidden(product_id, merchandising_rules):
            continue

        entry = token_index.get(product_id)
        if entry is None:
            entry = _build_product_token_entry(product)
        title_tokens = entry.title_tokens
        category_tokens = entry.category_tokens
        brand_tokens = entry.brand_tokens
        description_tokens = entry.description_tokens
        normalized_title = entry.title_normalized
        if not strict_product_match(raw_query_tokens, normalized_title):
            continue

        title_hits = len(query_tokens & title_tokens)
        brand_hits = len(query_tokens & brand_tokens)
        category_hits = len(query_tokens & category_tokens)
        description_hits = len(query_tokens & description_tokens)
        fuzzy_title_hits = fuzzy_hits_cached(query_tokens, title_tokens, fuzzy_match_cache)
        fuzzy_category_hits = fuzzy_hits_cached(query_tokens, category_tokens, fuzzy_match_cache)

        score = 0
        score += 8 * title_hits
        score += 5 * brand_hits
        score += 4 * category_hits
        score += description_hits
        score += 4 * fuzzy_title_hits
        score += 2 * fuzzy_category_hits
        score += sum(POPULARITY_BOOSTS.get(token, 0) for token in query_tokens & (title_tokens | category_tokens))

        if bm25_index is not None:
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
            score *= merchandising_multiplier(
                str(product_value(product, "brand", "")),
                str(product_value(product, "product_type", product_value(product, "category", ""))),
                merchandising_rules,
            )
            # Real customer report: "chcem sojovu omacku od kikkoman"
            # (I want soy sauce FROM Kikkoman) returned zero Kikkoman
            # products - every Kikkoman SKU has an explicit brand_hits
            # match (score += 5*brand_hits above) but one specific SKU
            # had a real below-baseline CTR (confirmed via /admin/
            # analytics/behavioral-rankings) eligible for the maximum
            # 0.5x behavioral penalty, enough to drop it below brands the
            # customer never named. When someone explicitly names a
            # product's own brand, that is a much stronger and more
            # certain relevance signal than general CTR popularity - it
            # should not be diluted by how other customers on average
            # engage with that brand.
            if behavioral_rankings is not None and brand_hits == 0:
                score *= behavioral_multiplier(
                    product_id,
                    behavioral_rankings["scores"],
                    behavioral_rankings["baseline_ctr"],
                    BEHAVIORAL_RANKING_WEIGHT,
                    BEHAVIORAL_MIN_RATIO,
                    BEHAVIORAL_MAX_RATIO,
                )
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

    results = [format_product(product) for _, _, product in ranked[:limit]]

    pins = pins_for_query(query, merchandising_rules)
    if pins:
        results = _apply_pins(results, pins, products, limit)

    return results


def _apply_pins(
    results: list[dict],
    pins: list[dict],
    products: list[Product] | list[dict],
    limit: int,
) -> list[dict]:
    working = list(results)
    present_ids = {item.get("id") for item in working}

    for pin in pins:
        sku = str(pin.get("sku", ""))
        if not sku or sku in present_ids:
            continue
        for product in products:
            if str(product_value(product, "id", "")) == sku:
                working.append(format_product(product))
                present_ids.add(sku)
                break

    for pin in pins:
        sku = str(pin.get("sku", ""))
        item = next((entry for entry in working if entry.get("id") == sku), None)
        if not item:
            continue
        working.remove(item)
        position = int(pin.get("position", 1) or 1)
        insert_at = max(0, min(position - 1, len(working)))
        working.insert(insert_at, item)

    return working[:limit]


def autocomplete_suggestions(products: list[Product] | list[dict], query: str, limit: int = 8) -> list[dict]:
    normalized_query = strip_conversational_noise(query)
    if len(normalized_query) < 2:
        return []

    query_tokens = tokenize(query)
    raw_query_tokens = raw_tokens(query)
    suggestions: dict[str, dict] = {}
    fuzzy_match_cache = get_fuzzy_match_cache(products, query_tokens)

    def add(label: str, kind: str, score: int, precomputed_tokens: frozenset[str] | None = None) -> None:
        clean = _clean_field(label)
        if not clean:
            return
        key = normalize(clean)
        if kind == "product" and not strict_product_match(raw_query_tokens, key):
            return
        if precomputed_tokens is not None:
            label_tokens = precomputed_tokens
            fuzzy_token_hits = fuzzy_hits_cached(query_tokens, label_tokens, fuzzy_match_cache)
        else:
            # Not from the catalog token vocabulary (e.g. a PHRASE_SYNONYMS
            # label) - the vocabulary-deduplicated cache above doesn't cover
            # it, so fall back to the exact original per-call computation.
            label_tokens = tokenize(clean)
            fuzzy_token_hits = fuzzy_hits(query_tokens, label_tokens)
        token_hits = len(query_tokens & label_tokens)
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

    token_index = get_product_token_index(products)
    for product in products:
        product_id = str(product_value(product, "id", ""))
        entry = token_index.get(product_id) or _build_product_token_entry(product)
        availability = str(product_value(product, "availability", ""))
        availability_score = 5 if availability in {"in_stock", "in stock"} else 0
        # label text stays the ORIGINAL (display-cased) field - only the
        # tokenization is precomputed/reused, never the label itself.
        add(str(product_value(product, "title", "")), "product", 60 + availability_score, entry.title_tokens)
        add(str(product_value(product, "brand", "")), "brand", 45 + availability_score, entry.brand_tokens)
        for part, part_tokens in zip(entry.category_parts, entry.category_part_tokens):
            add(part, "category", 35 + availability_score, part_tokens)

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
