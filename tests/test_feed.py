"""
tests/test_feed.py  -  V2.1 feed foundation: category memberships, extended
fields, backward compatibility (docs/product-taxonomy-audit.md).

Covers app.feed.parse_category_memberships() in isolation (Section 10:
one/multiple memberships, whitespace, duplicates, empty segments, missing
product_type, unusually long lists) plus the feed parser's handling of the
extra Google Merchant fields (additional_image_link, unit_pricing_base_measure,
shipping_weight, condition, identifier_exists) and duplicate-GTIN detection.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.feed import (
    GOOGLE_NS,
    Product,
    find_duplicate_gtins,
    load_products_json,
    parse_category_memberships,
    parse_google_merchant_feed,
)


class TestParseCategoryMemberships:
    def test_single_membership(self):
        assert parse_category_memberships("Ryžovary") == ["Ryžovary"]

    def test_multiple_memberships_preserve_source_order(self):
        raw = "Vegánske potraviny > Super potraviny > Basmati ryža > Ryža"
        assert parse_category_memberships(raw) == [
            "Vegánske potraviny", "Super potraviny", "Basmati ryža", "Ryža",
        ]

    def test_trims_whitespace_around_segments(self):
        raw = "  Ryža  >   Basmati ryža  "
        assert parse_category_memberships(raw) == ["Ryža", "Basmati ryža"]

    def test_removes_duplicate_segments_preserving_first_occurrence(self):
        raw = "Ryža > Ryža > Basmati ryža"
        assert parse_category_memberships(raw) == ["Ryža", "Basmati ryža"]

    def test_removes_empty_segments(self):
        raw = "Ryža >  > Basmati ryža >"
        assert parse_category_memberships(raw) == ["Ryža", "Basmati ryža"]

    def test_missing_product_type_returns_empty_list(self):
        assert parse_category_memberships("") == []
        assert parse_category_memberships(None) == []

    def test_unusually_long_membership_list(self):
        raw = " > ".join(f"Kategória {i}" for i in range(40))
        result = parse_category_memberships(raw)
        assert len(result) == 40
        assert result[0] == "Kategória 0"
        assert result[-1] == "Kategória 39"

    def test_preserves_unicode(self):
        raw = "Zdravé potraviny > Bezlepkové potraviny > Ryžový papier"
        result = parse_category_memberships(raw)
        assert "Zdravé potraviny" in result
        assert "Ryžový papier" in result

    def test_does_not_infer_hierarchy_just_a_flat_list(self):
        # Same six-level compound path style used in real Foodland data;
        # this must stay a flat list, never a nested parent->child object.
        raw = (
            "Vegánske potraviny > Super potraviny > Vegetariánske potraviny "
            "> Zdravé potraviny > Bezlepkové potraviny > Basmati ryža > Ryža"
        )
        result = parse_category_memberships(raw)
        assert isinstance(result, list)
        assert all(isinstance(x, str) for x in result)
        assert len(result) == 7


class TestProductCategoryMembershipsProperty:
    def _make_product(self, product_type: str) -> Product:
        return Product(
            id="FL_1", title="t", description="", product_type=product_type,
            link="", image_link="", price=None, sale_price=None, currency="EUR",
            brand="", availability="in_stock", gtin="", unit_pricing_measure="",
        )

    def test_property_matches_module_function(self):
        p = self._make_product("Ryža > Basmati ryža")
        assert p.category_memberships == parse_category_memberships(p.product_type)

    def test_not_serialized_as_a_stored_field(self):
        from dataclasses import asdict
        p = self._make_product("Ryža > Basmati ryža")
        data = asdict(p)
        assert "category_memberships" not in data


class TestExtendedFeedFields:
    FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">
<channel><title>Test</title>
<item>
  <g:id>FL_1</g:id>
  <title>Basmati ryža - LAILA - 1 kg</title>
  <description>desc</description>
  <g:product_type>Vegánske potraviny &gt; Basmati ryža &gt; Ryža</g:product_type>
  <link>https://www.foodland.sk/basmati-ryza/basmati-ryza-laila-1-kg/</link>
  <g:image_link>https://img.example/main.jpg</g:image_link>
  <g:additional_image_link>https://img.example/alt1.jpg</g:additional_image_link>
  <g:additional_image_link>https://img.example/alt2.jpg</g:additional_image_link>
  <g:price>3.49 EUR</g:price>
  <g:brand>LAILA</g:brand>
  <g:availability>in_stock</g:availability>
  <g:gtin>1234567890123</g:gtin>
  <g:unit_pricing_measure>1kg</g:unit_pricing_measure>
  <g:unit_pricing_base_measure>1kg</g:unit_pricing_base_measure>
  <g:shipping_weight>1.0 kg</g:shipping_weight>
  <g:condition>new</g:condition>
  <g:identifier_exists>yes</g:identifier_exists>
</item>
<item>
  <g:id>FL_2</g:id>
  <title>Minimal product</title>
  <description></description>
  <g:product_type></g:product_type>
  <link></link>
  <g:image_link></g:image_link>
  <g:price>1 EUR</g:price>
  <g:availability>in_stock</g:availability>
</item>
</channel></rss>"""

    def _parse(self, tmp_path):
        xml_path = tmp_path / "feed.xml"
        xml_path.write_text(self.FEED_XML, encoding="utf-8")
        return parse_google_merchant_feed(str(xml_path))

    def test_repeated_additional_images_preserved_in_order(self, tmp_path):
        products = self._parse(tmp_path)
        p = products[0]
        assert p.additional_image_links == [
            "https://img.example/alt1.jpg", "https://img.example/alt2.jpg",
        ]

    def test_optional_fields_extracted(self, tmp_path):
        products = self._parse(tmp_path)
        p = products[0]
        assert p.unit_pricing_base_measure == "1kg"
        assert p.shipping_weight == "1.0 kg"
        assert p.condition == "new"
        assert p.identifier_exists == "yes"

    def test_missing_optional_fields_default_safely(self, tmp_path):
        products = self._parse(tmp_path)
        p = products[1]
        assert p.additional_image_links == []
        assert p.unit_pricing_base_measure == ""
        assert p.shipping_weight == ""
        assert p.condition == ""
        assert p.identifier_exists == ""

    def test_product_type_preserved_verbatim(self, tmp_path):
        products = self._parse(tmp_path)
        assert products[0].product_type == "Vegánske potraviny > Basmati ryža > Ryža"

    def test_category_memberships_derived_from_preserved_product_type(self, tmp_path):
        products = self._parse(tmp_path)
        assert products[0].category_memberships == ["Vegánske potraviny", "Basmati ryža", "Ryža"]


class TestBackwardCompatibility:
    def test_old_json_snapshot_without_v21_fields_still_loads(self, tmp_path):
        # Simulates a products.json written before this sprint - no
        # additional_image_links / unit_pricing_base_measure / etc keys.
        import json
        old_style = [{
            "id": "FL_1", "title": "Basmati ryža", "description": "d",
            "product_type": "Ryža", "link": "https://x", "image_link": "https://y",
            "price": 3.49, "sale_price": None, "currency": "EUR", "brand": "LAILA",
            "availability": "in_stock", "gtin": "123", "unit_pricing_measure": "1kg",
        }]
        path = tmp_path / "old_products.json"
        path.write_text(json.dumps(old_style), encoding="utf-8")

        products = load_products_json(str(path))
        assert len(products) == 1
        p = products[0]
        assert p.product_type == "Ryža"
        assert p.additional_image_links == []
        assert p.category_memberships == ["Ryža"]

    def test_product_type_attribute_access_still_works(self):
        p = Product(
            id="FL_1", title="t", description="", product_type="Ryža > Basmati ryža",
            link="", image_link="", price=None, sale_price=None, currency="EUR",
            brand="", availability="in_stock", gtin="", unit_pricing_measure="",
        )
        assert p.product_type == "Ryža > Basmati ryža"


class TestDuplicateGtinDetection:
    def _product(self, id_, gtin):
        return Product(
            id=id_, title="t", description="", product_type="", link="",
            image_link="", price=None, sale_price=None, currency="EUR",
            brand="", availability="in_stock", gtin=gtin, unit_pricing_measure="",
        )

    def test_no_duplicates_when_gtins_unique(self):
        products = [self._product("FL_1", "111"), self._product("FL_2", "222")]
        assert find_duplicate_gtins(products) == {}

    def test_detects_shared_gtin_across_distinct_product_ids(self):
        products = [
            self._product("FL_1", "999"),
            self._product("FL_2", "999"),
            self._product("FL_3", "111"),
        ]
        dupes = find_duplicate_gtins(products)
        assert dupes == {"999": ["FL_1", "FL_2"]}

    def test_does_not_merge_products_just_reports(self):
        products = [self._product("FL_1", "999"), self._product("FL_2", "999")]
        dupes = find_duplicate_gtins(products)
        # Both product ids remain distinct entries, never collapsed into one.
        assert len(dupes["999"]) == 2

    def test_empty_gtin_never_counts_as_a_duplicate(self):
        products = [self._product("FL_1", ""), self._product("FL_2", "")]
        assert find_duplicate_gtins(products) == {}
