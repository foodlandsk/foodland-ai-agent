"""Merchandising rules: pin/hide/boost products and run time-bounded
category campaigns, loaded from a JSON rules file so business rules can
change without a code deploy.

Deliberately has no dependency on Product/format_product (app.search /
app.feed) - search.py depends on this module, so importing anything from
those back into here would create a circular import. Everything here
operates on plain strings/dicts; search.py resolves rule matches against
actual products.
"""
from __future__ import annotations

import json
import os
import unicodedata
from datetime import date, datetime


def _normalize(value: str) -> str:
    """Diacritic-stripped, lowercased comparison key - duplicated from
    app.search.normalize() rather than imported, since search.py depends on
    this module and importing back would create a circular import."""
    ascii_text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    return ascii_text.strip().lower()


def load_merchandising_rules(path: str | None = None) -> dict:
    resolved_path = path or os.getenv("MERCHANDISING_JSON_PATH", "data/merchandising.json")
    try:
        with open(resolved_path, encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        raw = {}

    return {
        "pins": raw.get("pins") or [],
        "hidden": {str(sku) for sku in (raw.get("hidden") or [])},
        "boosts": raw.get("boosts") or [],
        "campaigns": raw.get("campaigns") or [],
    }


def is_hidden(product_id: str, rules: dict) -> bool:
    return product_id in rules.get("hidden", ())


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def campaign_is_active(campaign: dict, today: date) -> bool:
    active_from = _parse_date(campaign.get("active_from", ""))
    active_to = _parse_date(campaign.get("active_to", ""))
    if active_from and today < active_from:
        return False
    if active_to and today > active_to:
        return False
    return True


def merchandising_multiplier(brand: str, category: str, rules: dict, today: date | None = None) -> float:
    """Combined multiplier from brand boosts and active category campaigns.
    1.0 = no effect; multiple matching rules stack multiplicatively."""
    today = today or date.today()
    multiplier = 1.0
    normalized_brand = _normalize(brand)
    normalized_category = _normalize(category)

    for boost in rules.get("boosts", []):
        boost_brand = _normalize(str(boost.get("brand", "")))
        if boost_brand and boost_brand == normalized_brand:
            multiplier *= float(boost.get("multiplier", 1.0) or 1.0)

    for campaign in rules.get("campaigns", []):
        campaign_category = _normalize(str(campaign.get("category", "")))
        if campaign_category and campaign_category in normalized_category and campaign_is_active(campaign, today):
            multiplier *= float(campaign.get("boost", 1.0) or 1.0)

    return multiplier


def pins_for_query(query: str, rules: dict) -> list[dict]:
    """Pins whose configured query matches the given search query (substring,
    case-insensitive, diacritic-insensitive), or unconditional pins with no
    query set at all."""
    normalized_query = _normalize(query)
    matching = []
    for pin in rules.get("pins", []):
        pin_query = _normalize(str(pin.get("query", "")))
        if not pin_query or pin_query in normalized_query:
            matching.append(pin)
    return matching
