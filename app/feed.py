from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

GOOGLE_NS = "{http://base.google.com/ns/1.0}"

# Language codes supported by Foodland multi-language feeds.
FEED_LANGS: list[str] = ["sk", "cz", "de", "en", "hu", "pl"]


def parse_category_memberships(product_type: str) -> list[str]:
    """Split a raw ``g:product_type`` value into its ``>``-separated segments.

    This is deliberately NOT a parent/child tree (V2.1 taxonomy foundation,
    docs/product-taxonomy-audit.md): Foodland mixes product family, variety,
    dietary facet, cuisine facet and merchandising labels in one path with
    no consistent ordering. This function only extracts the flat list of
    distinct category labels a product belongs to - source order is kept
    (it is evidence for the taxonomy engine) but never treated as a
    hierarchy by itself.
    """
    if not product_type:
        return []
    segments = [s.strip() for s in product_type.split(">")]
    memberships: list[str] = []
    seen: set[str] = set()
    for segment in segments:
        if not segment or segment in seen:
            continue
        seen.add(segment)
        memberships.append(segment)
    return memberships


@dataclass(slots=True)
class Product:
    id: str
    title: str
    description: str
    product_type: str
    link: str
    image_link: str
    price: float | None
    sale_price: float | None
    currency: str
    brand: str
    availability: str
    gtin: str
    unit_pricing_measure: str
    lang: str = "sk"  # language mutation this product was loaded from
    additional_image_links: list[str] = field(default_factory=list)
    unit_pricing_base_measure: str = ""
    shipping_weight: str = ""
    condition: str = ""
    identifier_exists: str = ""

    @property
    def effective_price(self) -> float | None:
        return self.sale_price if self.sale_price is not None else self.price

    @property
    def category_memberships(self) -> list[str]:
        """Derived, not stored: avoids duplicating product_type in JSON."""
        return parse_category_memberships(self.product_type)


def parse_price(value: str | None) -> tuple[float | None, str]:
    if not value:
        return None, "EUR"

    match = re.match(r"^\s*([0-9]+(?:[.,][0-9]+)?)\s*([A-Z]{3})?\s*$", value)
    if not match:
        return None, "EUR"

    amount = float(match.group(1).replace(",", "."))
    currency = match.group(2) or "EUR"
    return amount, currency


def child_text(item: ET.Element, tag: str) -> str:
    element = item.find(tag)
    if element is None or element.text is None:
        return ""
    return element.text.strip()


def parse_google_merchant_feed(path_or_url: str, lang: str = "sk") -> list[Product]:
    """Parse a single Google Merchant XML feed and return Product list tagged with *lang*."""
    with open_feed(path_or_url) as source:
        tree = ET.parse(source)

    products: list[Product] = []
    for item in tree.findall(".//item"):
        price, currency = parse_price(child_text(item, f"{GOOGLE_NS}price"))
        sale_price, sale_currency = parse_price(child_text(item, f"{GOOGLE_NS}sale_price"))
        additional_images = [
            el.text.strip()
            for el in item.findall(f"{GOOGLE_NS}additional_image_link")
            if el.text and el.text.strip()
        ]

        products.append(
            Product(
                id=child_text(item, f"{GOOGLE_NS}id"),
                title=child_text(item, "title"),
                description=child_text(item, "description"),
                product_type=child_text(item, f"{GOOGLE_NS}product_type"),
                link=child_text(item, "link"),
                image_link=child_text(item, f"{GOOGLE_NS}image_link"),
                price=price,
                sale_price=sale_price,
                currency=sale_currency if sale_price is not None else currency,
                brand=child_text(item, f"{GOOGLE_NS}brand"),
                availability=child_text(item, f"{GOOGLE_NS}availability"),
                gtin=child_text(item, f"{GOOGLE_NS}gtin"),
                unit_pricing_measure=child_text(item, f"{GOOGLE_NS}unit_pricing_measure"),
                lang=lang,
                additional_image_links=additional_images,
                unit_pricing_base_measure=child_text(item, f"{GOOGLE_NS}unit_pricing_base_measure"),
                shipping_weight=child_text(item, f"{GOOGLE_NS}shipping_weight"),
                condition=child_text(item, f"{GOOGLE_NS}condition"),
                identifier_exists=child_text(item, f"{GOOGLE_NS}identifier_exists"),
            )
        )

    return products


def load_multilang_feeds() -> dict[str, list[Product]]:
    """Load all configured language feed mutations.

    Reads env vars ``PRODUCT_FEED_PATH_SK`` (or ``PRODUCT_FEED_PATH`` for
    backward-compat), ``PRODUCT_FEED_PATH_CZ``, ``PRODUCT_FEED_PATH_DE``,
    ``PRODUCT_FEED_PATH_EN``, ``PRODUCT_FEED_PATH_HU``, ``PRODUCT_FEED_PATH_PL``.

    Returns a dict ``{lang_code: [Product, ...]}``.  Missing / unconfigured
    languages are silently skipped.
    """
    result: dict[str, list[Product]] = {}

    # SK: accept both PRODUCT_FEED_PATH (legacy) and PRODUCT_FEED_PATH_SK
    sk_path = os.getenv("PRODUCT_FEED_PATH_SK") or os.getenv("PRODUCT_FEED_PATH") or ""
    paths = {
        "sk": sk_path,
        "cz": os.getenv("PRODUCT_FEED_PATH_CZ", ""),
        "de": os.getenv("PRODUCT_FEED_PATH_DE", ""),
        "en": os.getenv("PRODUCT_FEED_PATH_EN", ""),
        "hu": os.getenv("PRODUCT_FEED_PATH_HU", ""),
        "pl": os.getenv("PRODUCT_FEED_PATH_PL", ""),
    }

    for lang, path in paths.items():
        if not path:
            continue
        try:
            products = parse_google_merchant_feed(path, lang=lang)
            result[lang] = products
            logger.info("Loaded %d products from %s feed (%s).", len(products), lang.upper(), path[:60])
        except Exception as exc:
            logger.error("Failed to load %s feed from %s: %s", lang.upper(), path[:60], exc)

    return result


def multilang_translation_index(lang_feeds: dict[str, list[Product]]) -> dict[str, dict[str, Product]]:
    """Build a translation index: ``{product_id: {lang: Product}}``.

    Useful for knowledge_builder to look up the CZ/DE/EN/HU/PL title and
    description of a product when building multilang Products_AI entries.
    """
    index: dict[str, dict[str, Product]] = {}
    for lang, products in lang_feeds.items():
        for p in products:
            index.setdefault(p.id, {})[lang] = p
    return index


def open_feed(path_or_url: str):
    if path_or_url.startswith(("http://", "https://")):
        return urllib.request.urlopen(path_or_url, timeout=30)
    return Path(path_or_url).open("rb")


def save_products(products: Iterable[Product], output_path: str | Path) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps([asdict(product) for product in products], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_products_json(path: str | Path) -> list[Product]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    # `lang` field may be absent in older JSON snapshots – default to "sk".
    return [Product(**{**item, "lang": item.get("lang", "sk")}) for item in data]


def find_duplicate_gtins(products: Iterable[Product]) -> dict[str, list[str]]:
    """Report GTIN values shared by more than one distinct product id.

    Detection only (Product Identity, docs/product-taxonomy-audit.md): the
    Foodland product id remains primary identity. A shared GTIN is never
    used to merge two products - it is just surfaced here for the taxonomy
    audit report.
    """
    by_gtin: dict[str, set[str]] = defaultdict(set)
    for product in products:
        if product.gtin:
            by_gtin[product.gtin].add(product.id)
    return {gtin: sorted(ids) for gtin, ids in by_gtin.items() if len(ids) > 1}
