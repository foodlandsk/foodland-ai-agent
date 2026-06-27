from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.feed import Product
from app.search import format_product, normalize, tokenize


@dataclass(slots=True)
class ProductTypeRule:
    product_type: str
    include_any: tuple[str, ...]
    include_all: tuple[str, ...] = ()
    exclude_any: tuple[str, ...] = ()


# V9: deterministic product graph. The goal is not to classify every Foodland item
# perfectly, but to prevent dangerous/absurd recommendations by enforcing product
# families before ranking alternatives or culinary cross-sell.
TYPE_RULES: tuple[ProductTypeRule, ...] = (
    ProductTypeRule("coconut_jelly_drink", ("napoj", "drink", "coco", "kokos"), ("kokos",), ("mlieko", "milk", "cream")),
    ProductTypeRule("coconut_drink", ("kokosovy napoj", "coconut drink", "kokosova voda", "coconut water", "kokosovy nektar")),
    ProductTypeRule("coconut_cream", ("kokosovy krem", "coconut cream", "cream coconut", "creme de coco")),
    ProductTypeRule("coconut_milk_cooking", ("kokosove mlieko", "coconut milk", "kokosove mleko", "kokosove mlieko", "kokosove mlieko"), (), ("napoj", "drink", "jelly", "zele", "želé", "sladkost")),
    ProductTypeRule("rice_flour", ("ryzova muka", "rice flour", "muka z lepkavej ryze", "glutinous rice flour")),
    ProductTypeRule("starch", ("skrob", "starch", "tapioca starch", "ryzovy skrob")),
    ProductTypeRule("sriracha_sauce", ("sriracha",)),
    ProductTypeRule("chili_sauce", ("chilli omacka", "chili omacka", "cili omacka", "sweet chilli", "chilli sauce", "chili sauce")),
    ProductTypeRule("fish_sauce", ("rybacia omacka", "fish sauce", "nuoc mam", "nam pla")),
    ProductTypeRule("soy_sauce", ("sojova omacka", "soy sauce", "shoyu", "tamari")),
    ProductTypeRule("oyster_sauce", ("ustricova omacka", "oyster sauce")),
    ProductTypeRule("sushi_rice", ("sushi ryza", "susi ryza", "ryza na sushi", "ryza na susi")),
    ProductTypeRule("rice_vinegar", ("ryzovy ocot", "rice vinegar", "sushi vinegar")),
    ProductTypeRule("nori", ("nori", "morske riasy", "seaweed")),
    ProductTypeRule("gochujang", ("gochujang", "gocujang", "korejska cili pasta", "korejska chilli pasta")),
    ProductTypeRule("gochugaru", ("gochugaru", "korejske cili", "korejske chilli", "korean chili flakes", "korean chilli flakes")),
    ProductTypeRule("kimchi", ("kimchi", "kimci")),
    ProductTypeRule("rice_noodles", ("ryzove rezance", "rice noodles", "vermicelli", "banh pho", "pad thai rezance")),
    ProductTypeRule("instant_noodles", ("instantne rezance", "instant noodles", "ramyun", "ramen instant")),
    ProductTypeRule("curry_paste", ("kari pasta", "curry paste", "red curry", "green curry", "yellow curry", "panang curry", "massaman")),
    ProductTypeRule("jasmine_rice", ("jasminova ryza", "jasmine rice")),
)

QUERY_TYPE_MARKERS: dict[str, tuple[str, ...]] = {
    "coconut_milk_cooking": ("kokosove mlieko", "kokosovym mliekom", "kokosoveho mlieka", "coconut milk"),
    "coconut_cream": ("kokosovy krem", "coconut cream"),
    "sriracha_sauce": ("sriracha",),
    "chili_sauce": ("chilli omacka", "chili omacka", "cili omacka", "sweet chilli", "sweet chili"),
    "fish_sauce": ("rybacia omacka", "fish sauce", "nuoc mam"),
    "soy_sauce": ("sojova omacka", "soy sauce", "shoyu"),
    "oyster_sauce": ("ustricova omacka", "oyster sauce"),
    "sushi_rice": ("sushi ryza", "susi ryza", "ryza na sushi", "ryza na susi"),
    "rice_vinegar": ("ryzovy ocot", "rice vinegar"),
    "gochujang": ("gochujang", "gocujang"),
    "gochugaru": ("gochugaru",),
    "kimchi": ("kimchi", "kimci"),
    "rice_noodles": ("ryzove rezance", "rice noodles", "pho rezance", "pad thai rezance"),
    "curry_paste": ("kari pasta", "curry paste"),
    "jasmine_rice": ("jasminova ryza", "jasmine rice"),
}

ALTERNATIVE_ALLOWED_TYPES: dict[str, set[str]] = {
    "coconut_milk_cooking": {"coconut_milk_cooking", "coconut_cream"},
    "coconut_cream": {"coconut_cream", "coconut_milk_cooking"},
    "sriracha_sauce": {"sriracha_sauce", "chili_sauce"},
    "chili_sauce": {"chili_sauce", "sriracha_sauce"},
    "fish_sauce": {"fish_sauce"},
    "soy_sauce": {"soy_sauce"},
    "oyster_sauce": {"oyster_sauce"},
    "sushi_rice": {"sushi_rice"},
    "rice_vinegar": {"rice_vinegar"},
    "gochujang": {"gochujang"},
    "gochugaru": {"gochugaru"},
    "kimchi": {"kimchi"},
    "rice_noodles": {"rice_noodles"},
    "curry_paste": {"curry_paste"},
    "jasmine_rice": {"jasmine_rice"},
}

CROSS_SELL_TARGET_TYPES: dict[str, list[str]] = {
    "coconut_milk_cooking": ["curry_paste", "jasmine_rice", "fish_sauce", "rice_noodles"],
    "coconut_cream": ["curry_paste", "jasmine_rice", "fish_sauce"],
    "sushi_rice": ["nori", "rice_vinegar", "soy_sauce"],
    "rice_noodles": ["fish_sauce", "soy_sauce", "chili_sauce"],
    "fish_sauce": ["rice_noodles", "curry_paste", "chili_sauce"],
    "soy_sauce": ["rice_noodles", "nori", "chili_sauce"],
    "kimchi": ["gochujang", "rice_noodles", "jasmine_rice"],
    "gochujang": ["kimchi", "rice_noodles", "soy_sauce"],
    "curry_paste": ["coconut_milk_cooking", "jasmine_rice", "fish_sauce"],
}

NEGATIVE_TYPE_PAIRS = {
    ("coconut_milk_cooking", "rice_flour"),
    ("coconut_milk_cooking", "starch"),
    ("coconut_milk_cooking", "coconut_drink"),
    ("coconut_milk_cooking", "coconut_jelly_drink"),
    ("sushi_rice", "rice_vinegar"),
}


def classify_product_type(product: Product | dict[str, Any]) -> str:
    if isinstance(product, dict):
        title = str(product.get("title") or "")
        category = str(product.get("product_type") or "")
        description = str(product.get("description") or "")
    else:
        title = product.title
        category = product.product_type
        description = product.description
    text = normalize(" ".join([title, category, description]))

    for rule in TYPE_RULES:
        if rule.include_all and not all(marker in text for marker in map(normalize, rule.include_all)):
            continue
        if rule.exclude_any and any(marker in text for marker in map(normalize, rule.exclude_any)):
            continue
        if any(marker in text for marker in map(normalize, rule.include_any)):
            return rule.product_type
    return "unknown"


def detect_query_product_type(query: str) -> str | None:
    normalized = normalize(query)
    for product_type, markers in QUERY_TYPE_MARKERS.items():
        if any(normalize(marker) in normalized for marker in markers):
            return product_type

    tokens = tokenize(query)
    if "kokos" in tokens and "mlieko" in tokens:
        return "coconut_milk_cooking"
    if "sriracha" in tokens:
        return "sriracha_sauce"
    if "sushi" in tokens and "ryza" in tokens:
        return "sushi_rice"
    if "rybacia" in tokens and "omacka" in tokens:
        return "fish_sauce"
    if "sojova" in tokens and "omacka" in tokens:
        return "soy_sauce"
    return None


def find_alternative_products(
    query: str,
    products: list[Product],
    limit: int = 4,
    shown_product_ids: set[str] | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    shown_product_ids = shown_product_ids or set()
    source_type = detect_query_product_type(query)
    if not source_type:
        return [], {"engine": "product_graph_v1", "reason": "no_source_type"}

    allowed = ALTERNATIVE_ALLOWED_TYPES.get(source_type, {source_type})
    candidates: list[tuple[int, Product, str]] = []
    for product in products:
        if product.id in shown_product_ids or normalize(product.link) in shown_product_ids:
            continue
        ptype = classify_product_type(product)
        if ptype not in allowed:
            continue
        if (source_type, ptype) in NEGATIVE_TYPE_PAIRS:
            continue
        score = score_product_for_type(product, ptype, source_type)
        candidates.append((score, product, ptype))

    candidates.sort(key=lambda item: item[0], reverse=True)
    formatted = []
    for score, product, ptype in candidates[:limit]:
        item = format_product(product)
        item["product_type_ai"] = ptype
        item["relationship"] = "alternative"
        item["graph_score"] = score
        formatted.append(item)
    return formatted, {
        "engine": "product_graph_v1",
        "source_type": source_type,
        "allowed_types": sorted(allowed),
        "candidates": len(candidates),
        "returned": len(formatted),
    }


def find_cross_sell_products(
    query: str,
    products: list[Product],
    limit: int = 4,
    shown_product_ids: set[str] | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    shown_product_ids = shown_product_ids or set()
    source_type = detect_query_product_type(query)
    if not source_type:
        return [], {"engine": "product_graph_v1", "reason": "no_source_type"}
    target_types = CROSS_SELL_TARGET_TYPES.get(source_type, [])
    if not target_types:
        return [], {"engine": "product_graph_v1", "source_type": source_type, "reason": "no_cross_sell_targets"}

    candidates: list[tuple[int, Product, str]] = []
    for product in products:
        if product.id in shown_product_ids or normalize(product.link) in shown_product_ids:
            continue
        ptype = classify_product_type(product)
        if ptype not in target_types:
            continue
        priority = target_types.index(ptype)
        score = 80 - priority * 8 + score_product_for_type(product, ptype, source_type)
        candidates.append((score, product, ptype))

    candidates.sort(key=lambda item: item[0], reverse=True)
    formatted = []
    seen_types: set[str] = set()
    # Prefer diversity: one strong product per target type first.
    for score, product, ptype in candidates:
        if ptype in seen_types and len(seen_types) < min(len(target_types), limit):
            continue
        item = format_product(product)
        item["product_type_ai"] = ptype
        item["relationship"] = "cross_sell"
        item["graph_score"] = score
        formatted.append(item)
        seen_types.add(ptype)
        if len(formatted) >= limit:
            break
    for score, product, ptype in candidates:
        if len(formatted) >= limit:
            break
        if any(x.get("id") == product.id for x in formatted):
            continue
        item = format_product(product)
        item["product_type_ai"] = ptype
        item["relationship"] = "cross_sell"
        item["graph_score"] = score
        formatted.append(item)
    return formatted, {
        "engine": "product_graph_v1",
        "source_type": source_type,
        "target_types": target_types,
        "candidates": len(candidates),
        "returned": len(formatted),
    }


def score_product_for_type(product: Product, product_type: str, source_type: str) -> int:
    text = normalize(" ".join([product.title, product.product_type, product.brand, product.description]))
    score = 0
    if product.availability == "in_stock":
        score += 12
    if product.effective_price is not None:
        score += 4
    title = normalize(product.title)
    category = normalize(product.product_type)

    # Product-family specific boosts and guards.
    if product_type == "coconut_milk_cooking":
        if "kokosove mlieko" in title or "coconut milk" in title:
            score += 45
        if "kokosove" in title and "mlieko" in title:
            score += 25
        if any(x in text for x in ["muka", "flour", "skrob", "starch", "napoj", "drink", "zele", "jelly"]):
            score -= 100
    elif product_type == "coconut_cream":
        score += 35
        if "cream" in title or "krem" in title:
            score += 20
    elif product_type == "sushi_rice":
        score += 40 if "sushi" in title or "susi" in title else 0
    elif product_type == "sriracha_sauce":
        score += 45 if "sriracha" in title else 0
    elif product_type == "fish_sauce":
        score += 40 if "rybacia" in title or "fish sauce" in title else 0
    elif product_type == "curry_paste":
        score += 35 if "kari" in title or "curry" in title else 0
    elif product_type == "jasmine_rice":
        score += 35 if "jasmin" in title or "jasmine" in title else 0

    # Keep real e-shop categories relevant, but never let them override family rules.
    if category:
        score += 2
    return score
