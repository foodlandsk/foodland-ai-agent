from __future__ import annotations

import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


GOOGLE_NS = "{http://base.google.com/ns/1.0}"


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

    @property
    def effective_price(self) -> float | None:
        return self.sale_price if self.sale_price is not None else self.price


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


def parse_google_merchant_feed(path_or_url: str) -> list[Product]:
    with open_feed(path_or_url) as source:
        tree = ET.parse(source)

    products: list[Product] = []
    for item in tree.findall(".//item"):
        price, currency = parse_price(child_text(item, f"{GOOGLE_NS}price"))
        sale_price, sale_currency = parse_price(child_text(item, f"{GOOGLE_NS}sale_price"))

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
            )
        )

    return products


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
    return [Product(**item) for item in data]
