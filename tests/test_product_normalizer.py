"""
tests/test_product_normalizer.py  -  V2.1 generic deterministic product
normalization (app.product_normalizer). No taxonomy/semantic logic here -
just URL category extraction, package size parsing and brand/title search
forms (docs/product-taxonomy-audit.md).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.feed import Product
from app.product_normalizer import (
    extract_url_category,
    normalize_brand,
    normalize_catalog,
    normalize_product,
    parse_package_size,
)


def make_product(**overrides) -> Product:
    base = dict(
        id="FL_1", title="Basmati ryža - LAILA - 1 kg", description="",
        product_type="Ryža > Basmati ryža", link="https://www.foodland.sk/basmati-ryza/basmati-ryza-laila-1-kg/",
        image_link="", price=3.49, sale_price=None, currency="EUR", brand="LAILA",
        availability="in_stock", gtin="123", unit_pricing_measure="1kg",
    )
    base.update(overrides)
    return Product(**base)


class TestExtractUrlCategory:
    def test_first_path_segment(self):
        assert extract_url_category("https://www.foodland.sk/ryzove-rezance/xyz-produkt/") == "ryzove-rezance"

    def test_nested_path_still_uses_first_segment(self):
        assert extract_url_category(
            "https://www.foodland.sk/kuchynske-naradie-a-pomocky/asahi-ozdoby-na-sushi-1000-ks/"
        ) == "kuchynske-naradie-a-pomocky"

    def test_empty_link_returns_empty_string(self):
        assert extract_url_category("") == ""

    def test_link_without_path_returns_empty_string(self):
        assert extract_url_category("https://www.foodland.sk") == ""


class TestParsePackageSize:
    def test_simple_grams(self):
        size = parse_package_size("400g")
        assert size.value == 400.0
        assert size.unit == "g"
        assert size.multipack_count is None

    def test_simple_kilograms_with_space(self):
        size = parse_package_size("1 kg")
        assert size.value == 1.0
        assert size.unit == "kg"

    def test_comma_decimal(self):
        size = parse_package_size("2,2 l")
        assert size.value == 2.2
        assert size.unit == "l"

    def test_multipack_from_title_fallback(self):
        size = parse_package_size("", "Nejaký produkt 2 x 200 g balenie")
        assert size.multipack_count == 2
        assert size.value == 200.0
        assert size.unit == "g"

    def test_ambiguous_pack_count_not_inferred(self):
        # "10 ks" alone has no per-unit weight - preserved raw, not guessed.
        size = parse_package_size("10 ks")
        assert size.raw == "10 ks"

    def test_drained_weight_combo_not_inferred(self):
        size = parse_package_size("500 g / drained 300 g")
        assert size.value is None
        assert size.unit is None
        assert size.raw == "500 g / drained 300 g"

    def test_empty_input_returns_empty_raw(self):
        size = parse_package_size("", "")
        assert size.raw == ""
        assert size.is_structured is False

    def test_prefers_structured_field_over_title(self):
        size = parse_package_size("500g", "Produkt s iným balením 2 x 250 g")
        assert size.value == 500.0
        assert size.unit == "g"
        assert size.multipack_count is None


class TestNormalizeBrand:
    def test_ascii_folds_and_lowercases(self):
        assert normalize_brand("LAILA") == "laila"

    def test_missing_brand_is_valid_empty_string(self):
        assert normalize_brand("") == ""
        assert normalize_brand(None) == ""


class TestNormalizeProduct:
    def test_produces_search_form_without_destroying_original_title(self):
        p = make_product(title="Jazmínová ryža FOODLAND 5 kg")
        norm = normalize_product(p)
        assert norm.title == "Jazmínová ryža FOODLAND 5 kg"
        assert norm.title_search_form == "jazminova ryza foodland 5 kg"

    def test_url_category_and_package_size_populated(self):
        p = make_product()
        norm = normalize_product(p)
        assert norm.url_category == "basmati-ryza"
        assert norm.package_size.value == 1.0
        assert norm.package_size.unit == "kg"

    def test_is_pure_deterministic_function(self):
        p = make_product()
        assert normalize_product(p) == normalize_product(p)


class TestNormalizeCatalog:
    def test_batch_keys_by_product_id(self):
        products = [make_product(id="FL_1"), make_product(id="FL_2", title="Iný produkt")]
        index = normalize_catalog(products)
        assert set(index.keys()) == {"FL_1", "FL_2"}

    def test_one_bad_product_does_not_break_the_batch(self):
        good = make_product(id="FL_1")

        class Broken:
            id = "FL_broken"

            @property
            def title(self):
                raise ValueError("boom")

        products = [good, Broken()]
        index = normalize_catalog(products)
        assert "FL_1" in index
        assert "FL_broken" not in index
