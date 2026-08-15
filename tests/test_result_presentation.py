"""
tests/test_result_presentation.py  -  Sprint V2.5 Result Presentation Layer,
Show More / Show All & Answer Composer.

Same synthetic-but-feed-realistic catalog discipline as
tests/test_structured_retrieval.py (independent local fixture - not
imported across test files, matching that file's own precedent).

Covers the V2.5 spec's mandatory test set: pagination completeness
(Section 41/42), Show All union (Section 56/84), grouped discovery counts
(Section 59), specific-vs-broad strategy selection (Section 60/61),
follow-up constraint persistence (Section 62), no-exact-match distinction
(Section 58), and answer wording rules (Section 65/66).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.answer_composer import compose_answer, compose_continuation_answer, compose_show_more_label
from app.feed import Product
from app.presentation import (
    EXACT_MATCH,
    FILTERED_PRODUCT_LIST,
    GROUPED_DISCOVERY,
    NO_EXACT_MATCH,
    build_result_set,
)
from app.product_normalizer import normalize_catalog
from app.query_constraints import parse_structured_query
from app.ranking import rank_candidates
from app.result_sets import advance_displayed_count, clear_all_result_sets, get_result_set, show_all
from app.retrieval import get_structured_index, retrieve_products
from app.structured_search import build_structured_result_set
from app.taxonomy import build_taxonomy_index


def make_product(**overrides) -> Product:
    base = dict(
        id="FL_TEST", title="", description="", product_type="", link="",
        image_link="", price=10.0, sale_price=None, currency="EUR", brand="",
        availability="in_stock", gtin="", unit_pricing_measure="",
    )
    base.update(overrides)
    return Product(**base)


def build_catalog() -> list[Product]:
    products = []
    # 12 jasmine rice products across 3 brands/sizes - enough to exercise
    # multi-page pagination (page_size=4 -> 3 full pages).
    brands = ["FOODLAND", "LAILA", "VINASEED"]
    for i in range(12):
        brand = brands[i % 3]
        size_kg = [1, 5, 10][(i // 3) % 3]
        products.append(make_product(
            id=f"FL_J{i}", title=f"Jazmínová ryža {brand} {size_kg} kg",
            product_type="Ryža > Jazmínová ryža", brand=brand,
            unit_pricing_measure=f"{size_kg} kg",
        ))
    # 8 basmati rice products - a second, distinct group for GROUPED_DISCOVERY.
    for i in range(8):
        products.append(make_product(
            id=f"FL_B{i}", title=f"Basmati ryža BRAND{i} 1 kg",
            product_type="Ryža > Basmati ryža", brand=f"BRAND{i}",
            unit_pricing_measure="1 kg",
        ))
    # 5 sushi rice products - a third group.
    for i in range(5):
        products.append(make_product(
            id=f"FL_S{i}", title=f"Sushi ryža BRAND{i} 1 kg",
            product_type="Ryža na sushi (Sushi)", brand=f"BRAND{i}",
            unit_pricing_measure="1 kg",
        ))
    # collision guards: different family entirely, must never leak into
    # "ryza" grouped discovery or jasmine pagination.
    products.append(make_product(id="FL_RN", title="Ryžové rezance THAI 400g", product_type="Ryžové rezance", brand="THAI"))
    products.append(make_product(id="FL_RV", title="Ryžový ocot MIZKAN 500ml", product_type="Octy", brand="MIZKAN"))
    return products


CATALOG = build_catalog()
TAXONOMY_INDEX = build_taxonomy_index(CATALOG)
NORMALIZED_INDEX = normalize_catalog(CATALOG)
INDEX = get_structured_index(CATALOG, TAXONOMY_INDEX, NORMALIZED_INDEX)
PRODUCTS_BY_ID = {p.id: p for p in CATALOG}
NOW = 1_700_000_000.0


def make_result_set(query_text: str, base_query=None):
    return build_structured_result_set(
        query_text, CATALOG, TAXONOMY_INDEX, NORMALIZED_INDEX,
        catalog_version=1, taxonomy_version=1, now=NOW, base_query=base_query,
    )


class TestPaginationCompleteness:
    """Section 41/42 - union of all pages == complete valid set, no dupes."""

    def test_full_pagination_covers_every_valid_id_exactly_once(self):
        rs = make_result_set("jazminova ryza")
        assert rs.matching_total == 12
        seen = list(rs.initial_page_ids())
        while rs.has_more:
            advance_displayed_count(rs, rs.page_size)
            seen = rs.ranked_product_ids[: rs.displayed_count]
        assert len(seen) == 12
        assert len(set(seen)) == 12  # no duplicates
        assert set(seen) == set(rs.ranked_product_ids)

    def test_has_more_false_after_last_page(self):
        rs = make_result_set("jazminova ryza")
        while rs.has_more:
            advance_displayed_count(rs, rs.page_size)
        assert rs.has_more is False
        assert rs.displayed_count == 12


class TestShowAllUnion:
    """Section 56/84 - initial ids + Show All remainder == full valid ranked set."""

    def test_show_all_union_equals_full_set(self):
        rs = make_result_set("jazminova ryza")
        initial_ids = set(rs.initial_page_ids())
        remaining_ids = set(rs.remaining_ids())
        assert initial_ids | remaining_ids == set(rs.ranked_product_ids)
        assert initial_ids & remaining_ids == set()  # no overlap
        show_all(rs)
        assert rs.displayed_count == len(rs.ranked_product_ids)
        assert rs.has_more is False


class TestRelatedContamination:
    """Section 57 - basmati/rice-noodles/rice-vinegar must never appear in
    a jasmine ResultSet's pagination, at any page."""

    def test_no_contamination_across_all_pages(self):
        rs = make_result_set("jazminova ryza")
        show_all(rs)
        for product_id in rs.ranked_product_ids:
            assert product_id.startswith("FL_J"), f"unexpected contamination: {product_id}"


class TestGroupedDiscovery:
    """Section 15/16/59 - broad query groups by real, non-hallucinated counts."""

    def test_broad_query_uses_grouped_discovery(self):
        rs = make_result_set("ryza")
        assert rs.answer_strategy == GROUPED_DISCOVERY
        assert len(rs.groups) >= 2

    def test_group_counts_are_real(self):
        rs = make_result_set("ryza")
        counts = {g["label"]: g["product_count"] for g in rs.groups}
        assert counts.get("Jazmínová ryža") == 12
        assert counts.get("Basmati ryža") == 8
        assert counts.get("Ryža na sushi") == 5

    def test_groups_exclude_different_family_products(self):
        rs = make_result_set("ryza")
        total_grouped = sum(g["product_count"] for g in rs.groups)
        assert total_grouped == 25  # 12 + 8 + 5, never the rice-noodle/vinegar products


class TestSpecificVsBroadStrategy:
    """Section 60/61 - specific queries use a flat list, not grouped discovery."""

    def test_specific_variety_query_uses_filtered_list(self):
        rs = make_result_set("jazminova ryza")
        assert rs.answer_strategy == FILTERED_PRODUCT_LIST

    def test_brand_and_size_query_uses_exact_match(self):
        rs = make_result_set("FOODLAND jazminova ryza 1 kg")
        assert rs.answer_strategy == EXACT_MATCH
        assert rs.matching_total >= 1


class TestFollowUpConstraintPersistence:
    """Section 13/62 - "len 5 kg" after "jazmínová ryža" must keep
    family=rice/variety=jasmine, not restart interpretation."""

    def test_follow_up_merges_into_base_query(self):
        base = make_result_set("jazminova ryza")
        narrowed = make_result_set("len 5 kg", base_query=base.structured_query)
        assert narrowed is not None
        assert narrowed.structured_query.family == "rice"
        assert narrowed.structured_query.attributes.get("variety") == "jasmine"
        assert narrowed.structured_query.package_size.value == 5.0
        for product_id in narrowed.ranked_product_ids:
            assert product_id.startswith("FL_J")  # still jasmine only

    def test_follow_up_without_base_query_does_not_hallucinate_family(self):
        # "len 5 kg" alone (no active ResultSet) has no family - must not
        # silently invent one.
        result = make_result_set("len 5 kg", base_query=None)
        assert result is None


class TestNoExactMatch:
    """Section 22/58 - exact=0 with nearest>0 must be explicitly distinguished."""

    def test_no_exact_match_strategy_and_separate_nearest_tier(self):
        rs = make_result_set("FOODLAND jazminova ryza 2 kg")  # no 2kg Foodland exists
        assert rs.answer_strategy == NO_EXACT_MATCH
        assert rs.matching_total == 0
        assert len(rs.nearest_match_ids) > 0
        for product_id in rs.nearest_match_ids:
            assert product_id.startswith("FL_J")


class TestAnswerWordingRules:
    """Section 65/66 - mechanically testable semantic rules, not exact prose."""

    def test_no_exact_match_wording_only_for_that_strategy(self):
        rs_no_match = make_result_set("FOODLAND jazminova ryza 2 kg")
        answer = compose_answer(rs_no_match)
        assert "nevidím" in answer or "nevidim" in answer

        rs_filtered = make_result_set("jazminova ryza")
        answer2 = compose_answer(rs_filtered)
        assert "nevidím" not in answer2 and "nevidim" not in answer2

    def test_matching_total_appears_in_filtered_list_answer(self):
        rs = make_result_set("jazminova ryza")
        answer = compose_answer(rs)
        assert str(rs.matching_total) in answer

    def test_grouped_discovery_answer_lists_real_group_counts(self):
        rs = make_result_set("ryza")
        answer = compose_answer(rs)
        for group in rs.groups[: rs.displayed_count]:
            assert group["label"] in answer
            assert f"({group['product_count']})" in answer

    def test_cross_sell_wording_not_used_for_primary_results(self):
        rs = make_result_set("jazminova ryza")
        answer = compose_answer(rs)
        assert "k tomu sa" not in answer.lower()

    def test_continuation_answer_does_not_repeat_query_description(self):
        rs = make_result_set("jazminova ryza")
        answer = compose_continuation_answer(rs, revealed_count=4)
        assert "jazmín" not in answer.lower()  # doesn't re-describe the query, per Section 9


class TestResultSetStore:
    """Section 47 - unknown/forged result_set_id resolves to None, not an error."""

    def test_unknown_result_set_id_returns_none(self):
        clear_all_result_sets()
        assert get_result_set("forged-nonexistent-id", NOW) is None

    def test_expired_result_set_returns_none(self):
        rs = make_result_set("jazminova ryza")
        far_future = rs.expires_at + 1
        assert get_result_set(rs.result_set_id, far_future) is None

    def test_valid_result_set_is_retrievable(self):
        rs = make_result_set("jazminova ryza")
        fetched = get_result_set(rs.result_set_id, NOW)
        assert fetched is not None
        assert fetched.result_set_id == rs.result_set_id


class TestRankingStability:
    """Section 43/46 - ranked_product_ids is fixed at creation; pagination
    never reshuffles it."""

    def test_ranked_order_unchanged_across_pagination(self):
        rs = make_result_set("jazminova ryza")
        original_order = list(rs.ranked_product_ids)
        advance_displayed_count(rs, rs.page_size)
        show_all(rs)
        assert rs.ranked_product_ids == original_order

    def test_show_more_label_reflects_remaining_count(self):
        rs = make_result_set("jazminova ryza")
        label = compose_show_more_label(rs)
        assert str(rs.remaining_count) in label or "viac" in label.lower()
