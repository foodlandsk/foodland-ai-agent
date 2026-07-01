from __future__ import annotations

from app.feed import Product
from app.search import normalize_url


def grounding_warnings(
    products: list[dict],
    cards: list[dict],
    product_items: list[Product],
) -> list[str]:
    warnings: list[str] = []
    product_ids = {product.id for product in product_items if product.id}
    product_urls = {normalize_url(product.link) for product in product_items if product.link}

    for product in products:
        product_id = str(product.get("id") or "")
        product_url = normalize_url(str(product.get("link") or ""))
        if product_id and product_id in product_ids:
            continue
        if product_url and product_url in product_urls:
            continue
        warnings.append(f"ungrounded_product:{product.get('title') or product_id or product_url}")

    for card in cards:
        card_type = str(card.get("type") or "")
        card_url = normalize_url(str(card.get("url") or ""))
        if card_type in {"cross_sell", "alternative"} and card_url and card_url not in product_urls:
            warnings.append(f"ungrounded_product_card:{card.get('title') or card_url}")

    return warnings
