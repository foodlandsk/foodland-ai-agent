from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.feed import Product
from app.knowledge import clean_recommendation_title
from app.search import normalize, tokenize


RULE_NOISE_TOKENS = {
    "cross",
    "doplnky",
    "hodi",
    "hodia",
    "k tomu",
    "kupit",
    "odporuc",
    "odporucit",
    "produkt",
    "produkty",
    "suvisiace",
    "suvisiaci",
}


@dataclass(slots=True)
class RuleRecommendation:
    card: dict[str, Any]
    score: int
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CrossSellRuleResult:
    cards: list[dict[str, Any]]
    trace: dict[str, Any]


def recommend_cross_sell_from_rules(
    query: str,
    knowledge: dict[str, Any],
    products: list[Product],
    limit: int = 4,
    shown_product_ids: set[str] | None = None,
) -> CrossSellRuleResult:
    shown_product_ids = shown_product_ids or set()
    product_by_url = {normalize_url(product.link): product for product in products if product.link}
    query_tokens = tokenize(query) - RULE_NOISE_TOKENS
    recommendations: list[RuleRecommendation] = []
    seen_keys: set[str] = set()

    for record in knowledge.get("sections", {}).get("CrossSell", []):
        source_product = clean_recommendation_title(str(record.get("Produkt") or ""))
        source_tokens = tokenize(source_product)
        category_tokens = tokenize(str(record.get("Kategoria") or ""))
        source_overlap = query_tokens & source_tokens
        category_overlap = query_tokens & category_tokens
        source_phrase = source_product and normalize(source_product) in normalize(query)

        if not source_overlap and not source_phrase:
            continue

        source_score = 20 if source_phrase else 8 * len(source_overlap)
        if category_overlap:
            source_score += min(3, len(category_overlap))
        if source_tokens and query_tokens and len(query_tokens & source_tokens) >= 2:
            source_score += 12

        for index in range(1, 6):
            title = clean_recommendation_title(str(record.get(f"Cross-sell {index}") or ""))
            url = str(record.get(f"Cross-sell {index}_url") or "").strip()
            if not title or not url:
                continue

            key = normalize_url(url) or normalize(title)
            if key in seen_keys or key in shown_product_ids:
                continue
            if normalize(title) == normalize(source_product):
                continue

            product = product_by_url.get(normalize_url(url))
            score = source_score + max(0, 8 - index)
            reasons = ["cross_sell_rule"]

            if product and product.availability == "in_stock":
                score += 3
                reasons.append("in_stock")
            if product and product.effective_price is not None:
                score += 1
                reasons.append("has_price")

            seen_keys.add(key)
            recommendations.append(
                RuleRecommendation(
                    card=build_cross_sell_card(
                        title=title,
                        url=url,
                        source_product=source_product,
                        product=product,
                        score=score,
                        reasons=reasons,
                    ),
                    score=score,
                    reasons=reasons,
                )
            )

    recommendations.sort(key=lambda item: item.score, reverse=True)
    cards = [item.card for item in recommendations[:limit]]
    return CrossSellRuleResult(
        cards=cards,
        trace={
            "engine": "cross_sell_rules_v1",
            "query_tokens": sorted(query_tokens),
            "candidates": len(recommendations),
            "returned": len(cards),
        },
    )


def recommend_live_related_products(
    query: str,
    knowledge: dict[str, Any],
    products: list[Product],
    limit: int = 4,
    shown_product_ids: set[str] | None = None,
) -> CrossSellRuleResult:
    shown_product_ids = shown_product_ids or set()
    product_by_url = {normalize_url(product.link): product for product in products if product.link}
    query_tokens = tokenize(query) - RULE_NOISE_TOKENS
    if not query_tokens:
        return CrossSellRuleResult(cards=[], trace={"engine": "live_related_products_v1", "returned": 0})

    recommendations: list[RuleRecommendation] = []
    seen_keys: set[str] = set()
    normalized_query = normalize(query)
    scored_sources: dict[str, int] = {}

    for record in knowledge.get("sections", {}).get("Product_Related_Live", []):
        source_product = clean_recommendation_title(str(record.get("Source Product Title (SK)") or ""))
        if not source_product:
            continue
        source_tokens = tokenize(source_product)
        source_overlap = query_tokens & source_tokens
        source_phrase = normalize(source_product) in normalized_query
        if not source_phrase and len(source_overlap) < 2:
            continue
        score = 30 if source_phrase else 8 * len(source_overlap)
        if source_tokens and query_tokens and len(query_tokens & source_tokens) >= 3:
            score += 10
        key = normalize(source_product)
        scored_sources[key] = max(scored_sources.get(key, 0), score)

    if not scored_sources:
        return CrossSellRuleResult(
            cards=[],
            trace={
                "engine": "live_related_products_v1",
                "query_tokens": sorted(query_tokens),
                "candidates": 0,
                "returned": 0,
            },
        )

    best_source_score = max(scored_sources.values())
    source_score_floor = max(16, best_source_score - 4)

    for record in knowledge.get("sections", {}).get("Product_Related_Live", []):
        source_product = clean_recommendation_title(str(record.get("Source Product Title (SK)") or ""))
        source_key = normalize(source_product)
        source_base_score = scored_sources.get(source_key, 0)
        if source_base_score < source_score_floor:
            continue

        title = clean_recommendation_title(str(record.get("Related Item Title") or ""))
        url = str(record.get("Related Item Link") or "").strip()
        if not title or not url:
            continue

        key = normalize_url(url) or normalize(title)
        if key in seen_keys or key in shown_product_ids:
            continue
        if normalize(title) == normalize(source_product):
            continue

        product = product_by_url.get(normalize_url(url))
        score = source_base_score
        stock_qty = parse_int(record.get("Stock Qty"))
        availability = str(record.get("Availability") or "")
        if "skladom" in normalize(availability):
            score += 4
        if stock_qty > 0:
            score += min(5, stock_qty // 20)
        price_current = parse_price_value(record.get("Price Current"))
        if price_current is not None:
            score += 1

        reasons = ["live_related_product"]
        if product and product.availability == "in_stock":
            score += 3
            reasons.append("feed_in_stock")

        seen_keys.add(key)
        recommendations.append(
            RuleRecommendation(
                card=build_live_related_card(
                    title=title,
                    url=url,
                    source_product=source_product,
                    product=product,
                    price_current=price_current,
                    stock_qty=stock_qty,
                    availability=availability,
                    score=score,
                    reasons=reasons,
                ),
                score=score,
                reasons=reasons,
            )
        )

    recommendations.sort(key=lambda item: item.score, reverse=True)
    cards = [item.card for item in recommendations[:limit]]
    return CrossSellRuleResult(
        cards=cards,
        trace={
            "engine": "live_related_products_v1",
            "query_tokens": sorted(query_tokens),
            "candidates": len(recommendations),
            "returned": len(cards),
        },
    )


def build_cross_sell_card(
    *,
    title: str,
    url: str,
    source_product: str,
    product: Product | None,
    score: int,
    reasons: list[str],
) -> dict[str, Any]:
    card: dict[str, Any] = {
        "type": "cross_sell",
        "title": title,
        "source_product": source_product,
        "subtitle": f"Hodi sa k: {source_product}" if source_product else "Suvisiaci produkt",
        "url": url,
        "button_label": "Zobrazit produkt",
        "rule_engine": "cross_sell_rules_v1",
        "rule_score": score,
        "rule_reasons": reasons,
    }
    if product:
        card.update(
            {
                "image_link": product.image_link,
                "effective_price": product.effective_price,
                "currency": product.currency,
                "availability": product.availability,
                "brand": product.brand,
            }
        )
    return card


def build_live_related_card(
    *,
    title: str,
    url: str,
    source_product: str,
    product: Product | None,
    price_current: float | None,
    stock_qty: int,
    availability: str,
    score: int,
    reasons: list[str],
) -> dict[str, Any]:
    card: dict[str, Any] = {
        "type": "cross_sell",
        "title": title,
        "source_product": source_product,
        "subtitle": f"Hodi sa k: {source_product}" if source_product else "Suvisiaci produkt",
        "url": url,
        "button_label": "Zobrazit produkt",
        "rule_engine": "live_related_products_v1",
        "rule_score": score,
        "rule_reasons": reasons,
        "stock_qty": stock_qty,
    }
    if product:
        card.update(
            {
                "image_link": product.image_link,
                "effective_price": product.effective_price,
                "currency": product.currency,
                "availability": product.availability,
                "brand": product.brand,
            }
        )
    else:
        if price_current is not None:
            card["effective_price"] = price_current
            card["currency"] = "EUR"
        if availability:
            card["availability"] = "in_stock" if "skladom" in normalize(availability) else availability
    return card


def parse_price_value(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(value: Any) -> int:
    text = str(value or "").strip()
    try:
        return int(float(text.replace(",", ".")))
    except ValueError:
        return 0


def normalize_url(value: str) -> str:
    return value.strip().split("?", 1)[0].rstrip("/")
