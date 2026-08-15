"""
tests/test_search_performance.py  -  Sprint V2.2.1 autocomplete performance
optimization: precomputed per-product token index, catalog-wide token
vocabulary, and a query-level fuzzy match cache.

The bottleneck this sprint fixed: search_products()/autocomplete_suggestions()
called tokenize()/normalize() and edit_distance() once per (product, field)
INSTANCE on every distinct autocomplete query (~292k edit_distance() calls
per query, ~700-2000ms cold). These functions must produce results IDENTICAL
to the original per-call computation - only faster (see docs/advisor-v2-
architecture.md for before/after numbers and the equivalence verification
methodology used before committing this change).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.feed import Product
from app.search import (
    build_fuzzy_match_cache,
    build_product_token_index,
    fuzzy_hits,
    fuzzy_hits_cached,
    get_catalog_token_vocabulary,
    get_fuzzy_match_cache,
    get_product_token_index,
    normalize,
    search_products,
    tokenize,
    warm_search_indexes,
)


def make_product(**overrides) -> Product:
    base = dict(
        id="FL_1", title="Basmati ryža", description="", product_type="Ryža > Basmati ryža",
        link="", image_link="", price=None, sale_price=None, currency="EUR", brand="TILDA",
        availability="in_stock", gtin="", unit_pricing_measure="",
    )
    base.update(overrides)
    return Product(**base)


class TestProductTokenIndex:
    def test_index_matches_manual_tokenization(self):
        p = make_product(title="Jazmínová ryža FOODLAND 5 kg", brand="FOODLAND")
        index = build_product_token_index([p])
        entry = index["FL_1"]
        assert entry.title_tokens == tokenize("Jazmínová ryža FOODLAND 5 kg")
        assert entry.brand_tokens == tokenize("FOODLAND")
        assert entry.title_normalized == normalize("Jazmínová ryža FOODLAND 5 kg")

    def test_category_parts_split_same_as_original(self):
        p = make_product(product_type="Vegánske potraviny > Jazmínová ryža > Ryža")
        index = build_product_token_index([p])
        entry = index["FL_1"]
        assert entry.category_parts == ("Vegánske potraviny", "Jazmínová ryža", "Ryža")

    def test_category_tokens_is_union_of_all_parts(self):
        p = make_product(product_type="Basmati ryža > Ryža")
        index = build_product_token_index([p])
        entry = index["FL_1"]
        assert entry.category_tokens == tokenize("Basmati ryža") | tokenize("Ryža")

    def test_missing_product_id_skipped(self):
        p = make_product(id="")
        index = build_product_token_index([p])
        assert index == {}

    def test_cache_keyed_by_products_list_identity(self):
        products_a = [make_product(id="FL_1")]
        products_b = [make_product(id="FL_1")]
        index_a = get_product_token_index(products_a)
        index_a_again = get_product_token_index(products_a)
        index_b = get_product_token_index(products_b)
        assert index_a is index_a_again
        assert index_a is not index_b


class TestCatalogTokenVocabulary:
    def test_vocabulary_is_union_across_catalog(self):
        products = [
            make_product(id="FL_1", title="Basmati ryža", brand="TILDA"),
            make_product(id="FL_2", title="Kimchi základ", brand="KIKKOMAN"),
        ]
        vocab = get_catalog_token_vocabulary(products)
        assert "basmati" in vocab or "ryza" in vocab
        assert "kimchi" in vocab

    def test_cache_keyed_by_products_list_identity(self):
        products_a = [make_product(id="FL_1", title="Basmati ryža")]
        products_b = [make_product(id="FL_2", title="Kimchi základ")]
        vocab_a = get_catalog_token_vocabulary(products_a)
        vocab_b = get_catalog_token_vocabulary(products_b)
        assert vocab_a != vocab_b


class TestFuzzyMatchCacheEquivalence:
    def test_short_query_tokens_excluded_from_fuzzy_path(self):
        # Section 11: avoid expensive fuzzy work for very short input.
        vocab = frozenset({"ryza", "omacka"})
        cache = build_fuzzy_match_cache({"ry"}, vocab)
        assert cache == {}

    def test_cached_result_matches_uncached_fuzzy_hits(self):
        vocab = frozenset({"ryzou", "omacka", "kokosove"})
        query_tokens = {"ryzu"}
        cache = build_fuzzy_match_cache(query_tokens, vocab)
        field_tokens = frozenset({"ryzou"})
        assert fuzzy_hits_cached(query_tokens, field_tokens, cache) == fuzzy_hits(query_tokens, field_tokens)

    def test_no_match_when_nothing_within_edit_distance(self):
        vocab = frozenset({"gochujang", "miso"})
        cache = build_fuzzy_match_cache({"ryzu"}, vocab)
        assert fuzzy_hits_cached({"ryzu"}, frozenset({"miso"}), cache) == 0

    def test_typo_tolerance_preserved(self):
        # "kokosove mliko" (typo of "mlieko") must still fuzzy-match -
        # this is the exact real-world case the cache must not break.
        vocab = frozenset({"mlieko", "kokosove"})
        query_tokens = tokenize("kokosove mliko")
        cache = build_fuzzy_match_cache(query_tokens, vocab)
        assert fuzzy_hits_cached(query_tokens, frozenset({"mlieko"}), cache) >= 1


class TestQueryLevelFuzzyMatchCache:
    def test_reused_for_identical_query_tokens(self):
        products = [make_product(id="FL_1")]
        cache_a = get_fuzzy_match_cache(products, {"ryzu"})
        cache_b = get_fuzzy_match_cache(products, {"ryzu"})
        assert cache_a is cache_b

    def test_distinct_for_different_query_tokens(self):
        products = [make_product(id="FL_1")]
        cache_a = get_fuzzy_match_cache(products, {"ryzu"})
        cache_b = get_fuzzy_match_cache(products, {"miso"})
        assert cache_a is not cache_b

    def test_distinct_for_different_products_identity(self):
        products_a = [make_product(id="FL_1")]
        products_b = [make_product(id="FL_1")]
        cache_a = get_fuzzy_match_cache(products_a, {"ryzu"})
        cache_b = get_fuzzy_match_cache(products_b, {"ryzu"})
        assert cache_a is not cache_b


class TestSearchProductsStillWorks:
    def test_returns_expected_shape(self):
        products = [
            make_product(id="FL_1", title="Basmati ryža TILDA 1kg", brand="TILDA"),
            make_product(id="FL_2", title="Jazmínová ryža FOODLAND 5kg", brand="FOODLAND", product_type="Jazmínová ryža > Ryža"),
        ]
        results = search_products(products, "ryza", 8)
        assert results
        assert all("id" in r for r in results)

    def test_typo_query_still_finds_product(self):
        products = [make_product(id="FL_1", title="Kokosové mlieko CHAOKOH 400ml", brand="CHAOKOH")]
        results = search_products(products, "kokosove mliko", 8)
        assert any(r["id"] == "FL_1" for r in results)


class TestFeedRefreshInvalidation:
    def test_new_products_list_gets_fresh_index_and_vocabulary(self):
        products_v1 = [make_product(id="FL_1", title="Basmati ryža")]
        products_v2 = [make_product(id="FL_2", title="Jazmínová ryža")]

        index_v1 = get_product_token_index(products_v1)
        index_v2 = get_product_token_index(products_v2)
        assert "FL_1" in index_v1 and "FL_1" not in index_v2
        assert "FL_2" in index_v2 and "FL_2" not in index_v1


class TestWarmSearchIndexes:
    def test_populates_token_index_and_vocabulary(self):
        products = [make_product(id="FL_warm_test", title="Basmati ryža")]
        warm_search_indexes(products)
        index = get_product_token_index(products)
        vocabulary = get_catalog_token_vocabulary(products)
        assert "FL_warm_test" in index
        assert vocabulary
