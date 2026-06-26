from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.search import normalize


@dataclass(slots=True)
class WorkflowResult:
    workflow: str
    confidence: float
    allowed_sources: list[str]
    rules: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_workflow(
    message: str,
    *,
    recipe_mode: bool,
    ingredient_mode: bool,
    crosssell_mode: bool,
    compare_mode: bool,
    alternative_mode: bool,
    has_faq: bool,
    has_products: bool,
    has_content: bool,
) -> WorkflowResult:
    normalized = normalize(message)

    if ingredient_mode:
        return WorkflowResult(
            workflow="recipe_to_products",
            confidence=0.94,
            allowed_sources=["Recipes", "recipe_ingredients", "products"],
            rules=[
                "one_best_product_per_ingredient",
                "no_duplicate_products",
                "no_weak_substitutes",
                "show_missing_ingredients_when_not_mapped",
            ],
            trace={"reason": "ingredient_query"},
        )

    if recipe_mode:
        return WorkflowResult(
            workflow="recipe_only",
            confidence=0.9,
            allowed_sources=["Recipes"],
            rules=["recipes_only", "no_product_cards"],
            trace={"reason": "recipe_query_without_ingredients"},
        )

    if has_faq and not has_products:
        return WorkflowResult(
            workflow="faq",
            confidence=0.9,
            allowed_sources=["FAQ"],
            rules=["deterministic_answer", "no_product_suggestions"],
            trace={"reason": "faq_match_without_products"},
        )

    if alternative_mode:
        return WorkflowResult(
            workflow="alternatives",
            confidence=0.88,
            allowed_sources=["Alternatives", "products"],
            rules=["no_original_product_as_alternative", "product_urls_must_exist"],
            trace={"reason": "alternative_marker"},
        )

    if compare_mode:
        confidence = 0.85 if has_products else 0.62
        if not has_products and is_broad_followup(normalized):
            confidence = 0.45
        return WorkflowResult(
            workflow="product_compare",
            confidence=confidence,
            allowed_sources=["Alternatives", "CrossSell", "products", "Products_AI"],
            rules=["same_or_related_category_only", "compare_price_pack_brand_availability"],
            warnings=[] if confidence >= 0.6 else ["comparison_needs_product_context"],
            trace={"reason": "compare_marker"},
        )

    if crosssell_mode:
        return WorkflowResult(
            workflow="cross_sell",
            confidence=0.86,
            allowed_sources=["CrossSell", "products"],
            rules=["related_products_only", "product_urls_must_exist"],
            trace={"reason": "crosssell_marker"},
        )

    if has_content and is_explicit_content_question(normalized):
        return WorkflowResult(
            workflow="content",
            confidence=0.86,
            allowed_sources=["Magazine", "Recipes", "IntentMapping", "Products_AI"],
            rules=["content_urls_only", "may_include_product_context"],
            trace={"reason": "explicit_content_question"},
        )

    if has_products:
        return WorkflowResult(
            workflow="product_search",
            confidence=0.8,
            allowed_sources=["products", "Products_AI"],
            rules=["products_must_exist_in_feed"],
            trace={"reason": "product_matches"},
        )

    if has_content:
        return WorkflowResult(
            workflow="content",
            confidence=0.78,
            allowed_sources=["Magazine", "Recipes", "IntentMapping"],
            rules=["content_urls_only"],
            trace={"reason": "content_match"},
        )

    return WorkflowResult(
        workflow="unknown",
        confidence=0.2,
        allowed_sources=[],
        rules=["safe_no_result"],
        warnings=["no_confident_workflow"],
        trace={"reason": "no_match"},
    )


def is_broad_followup(normalized: str) -> bool:
    broad_markers = [
        "porovnaj ceny podobnych produktov",
        "porovnaj podobne produkty",
        "lacnejsia alternativa",
        "najdi alternativy",
    ]
    return any(marker in normalized for marker in broad_markers)


def is_explicit_content_question(normalized: str) -> bool:
    markers = [
        "co je",
        "co znamena",
        "vysvetli",
        "aky je rozdiel",
        "rozdiel medzi",
        "ako sa pouziva",
        "na co je",
    ]
    return any(marker in normalized for marker in markers)
