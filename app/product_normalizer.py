"""
app/product_normalizer.py  -  V2.1 generic deterministic product normalization

Sits between the raw feed parser (app/feed.py) and the semantic taxonomy
engine (app/taxonomy.py): it derives structural facts that hold for ANY
product family (search-form text, URL category slug, package size, brand
match key) with no Foodland-specific product knowledge. Taxonomy decides
WHAT a product is; this module only makes the raw fields easier to match
against, deterministically and without guessing.

No LLM calls, no network access, no per-SKU manual mapping. A NormalizedProduct
is a compact companion object keyed by product id - it does not duplicate
description/image data already on Product (Sprint V2.1, docs/product-taxonomy-audit.md).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse

from app.feed import Product
from app.search import normalize

logger = logging.getLogger(__name__)

# "2 x 200 g", "20 x 25 g" - explicit multipack count + per-unit size.
_MULTIPACK_RE = re.compile(
    r"(?P<count>\d+)\s*[xX×]\s*(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>kg|g|ml|l|ks)\b"
)
# "500 g", "1kg", "250 ml" - a single value + unit, nothing else attached.
_SIMPLE_SIZE_RE = re.compile(r"^\s*(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>kg|g|ml|l|ks)\s*$")


@dataclass(frozen=True, slots=True)
class PackageSize:
    raw: str
    value: float | None = None
    unit: str | None = None
    multipack_count: int | None = None

    @property
    def is_structured(self) -> bool:
        return self.value is not None and self.unit is not None


def parse_package_size(unit_pricing_measure: str, title: str = "") -> PackageSize:
    """Deterministic package-size parse. Prefers the structured feed field.

    Falls back to the title only for the simple "N unit" / "N x M unit"
    shapes. Anything else (drained-weight combos, unlabeled counts, etc.)
    is preserved as `raw` with value/unit left None rather than guessed -
    ambiguous quantities are not inferred (docs/product-taxonomy-audit.md,
    package size normalization).
    """
    source = (unit_pricing_measure or "").strip()
    if not source:
        source = (title or "").strip()
    if not source:
        return PackageSize(raw="")

    normalized_source = source.lower().replace(",", ".")

    multipack = _MULTIPACK_RE.search(normalized_source)
    if multipack:
        return PackageSize(
            raw=source,
            value=float(multipack.group("value")),
            unit=multipack.group("unit"),
            multipack_count=int(multipack.group("count")),
        )

    simple = _SIMPLE_SIZE_RE.match(normalized_source)
    if simple:
        return PackageSize(raw=source, value=float(simple.group("value")), unit=simple.group("unit"))

    return PackageSize(raw=source)


def extract_url_category(link: str) -> str:
    """First path segment of a Foodland product URL, e.g.
    'https://www.foodland.sk/ryzove-rezance/xyz/' -> 'ryzove-rezance'.

    A signal only (docs/product-taxonomy-audit.md, URL category signal) -
    never treated as a definitive classification by itself.
    """
    if not link:
        return ""
    path = urlparse(link).path.strip("/")
    if not path:
        return ""
    return path.split("/", 1)[0]


def normalize_brand(brand: str) -> str:
    """Ascii-folded, lowercased brand matching key. Missing brand -> ''."""
    return normalize(brand or "")


@dataclass(frozen=True, slots=True)
class NormalizedProduct:
    product_id: str
    title: str
    title_search_form: str
    url_category: str
    package_size: PackageSize
    brand: str
    brand_normalized: str


def normalize_product(product: Product) -> NormalizedProduct:
    """Pure, deterministic per-product normalization. No I/O, no LLM calls."""
    return NormalizedProduct(
        product_id=product.id,
        title=product.title,
        title_search_form=normalize(product.title),
        url_category=extract_url_category(product.link),
        package_size=parse_package_size(product.unit_pricing_measure, product.title),
        brand=product.brand,
        brand_normalized=normalize_brand(product.brand),
    )


def normalize_catalog(products: Iterable[Product]) -> dict[str, NormalizedProduct]:
    """Batch-normalize a catalog with per-product failure isolation.

    A single malformed product must not break normalization for the rest
    of the feed refresh (docs/product-taxonomy-audit.md, failure isolation).
    """
    index: dict[str, NormalizedProduct] = {}
    for product in products:
        try:
            index[product.id] = normalize_product(product)
        except Exception:
            logger.warning("Product normalization failed for id=%s", getattr(product, "id", "?"), exc_info=True)
    return index
