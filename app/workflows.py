"""
app/workflows.py  -  Sprint 1: Workflow Engine

Strukturovany workflow router podla roadmap Foodland Agentic AI.

Kazdy workflow ma:
1. intent
2. vstupne parametre
3. povolene zdroje dat (allowed_sources)
4. pravidla kvality
5. vystupny format (WorkflowResult)
6. analyticky event (tracked v result.intent)

Pouzitie:
    from app.workflows import detect_workflow, run_workflow, WorkflowResult
    result = run_workflow(message, products, knowledge, limit)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


# Feature flags
# Kazdy workflow mozno okamzite vypnut env premennou bez deploymentu:
#   WORKFLOW_DISABLE=recipe_to_products,cross_sell

def _disabled_workflows() -> set[str]:
    raw = os.getenv("WORKFLOW_DISABLE", "")
    return {w.strip() for w in raw.split(",") if w.strip()}


@dataclass
class WorkflowResult:
    """Standardizovany vystup kazdeho workflowu."""
    intent: str
    answer: str = ""
    products: list[dict] = field(default_factory=list)
    recipes: list[dict] = field(default_factory=list)
    cart_candidates: list[dict] = field(default_factory=list)
    knowledge: dict[str, int] = field(default_factory=dict)
    allowed_sources: list[str] = field(default_factory=list)
    missing_ingredients: list[str] = field(default_factory=list)
    warning: str = ""
    grounded_product_ids: set[str] = field(default_factory=set)


WORKFLOW_PRIORITY = [
    "allergen_safety",
    "faq",
    "recipe_only",
    "recipe_to_products",
    "out_of_domain",
    "cross_sell",
    "special_products",
    "product_search",
]


def detect_workflow(
    message: str,
    *,
    detect_allergen_fn,
    detect_faq_fn,
    detect_recipe_subject_fn,
    detect_out_of_domain_fn,
    detect_special_fn,
    detect_related_fn,
) -> str:
    """
    Vrati nazov workflowu s najvyssou prioritou pre danu spravu.
    Pouziva callbacky z app.main, aby nevznikla kruhova zavislost.
    """
    disabled = _disabled_workflows()

    if "allergen_safety" not in disabled and detect_allergen_fn(message):
        return "allergen_safety"

    if "faq" not in disabled and detect_faq_fn(message):
        return "faq"

    recipe_subj = detect_recipe_subject_fn(message)
    if recipe_subj:
        from app.search import normalize
        nm = normalize(message)
        has_product_intent = any(m in nm for m in (
            "produkty", "ingrediencie", "suroviny", "nakupny zoznam",
            "co potrebujem", "co treba", "co kupit", "co mi chyba",
            "mam doma", "chyba mi",
        ))
        wf = "recipe_to_products" if has_product_intent else "recipe_only"
        if wf not in disabled:
            return wf
        other = "recipe_only" if wf == "recipe_to_products" else "recipe_to_products"
        if other not in disabled:
            return other

    if "out_of_domain" not in disabled and detect_out_of_domain_fn(message):
        return "out_of_domain"

    if "cross_sell" not in disabled and detect_related_fn(message):
        return "cross_sell"

    if "special_products" not in disabled and detect_special_fn(message):
        return "special_products"

    return "product_search"


WORKFLOW_CONTRACTS: dict[str, dict] = {
    "allergen_safety": {
        "allowed_sources": ["FAQ", "Products_AI"],
        "rules": [
            "never_assert_allergen_free_by_name_only",
            "always_refer_to_product_detail",
            "no_invented_composition",
        ],
        "output_fields": ["answer", "products", "knowledge"],
    },
    "faq": {
        "allowed_sources": ["FAQ"],
        "rules": [
            "deterministic_from_faq_table",
            "no_product_upsell_after_faq",
        ],
        "output_fields": ["answer", "knowledge"],
    },
    "recipe_only": {
        "allowed_sources": ["Recipes", "Magazine"],
        "rules": [
            "only_foodland_recipes",
            "no_invented_recipes",
            "no_product_push_if_recipe_only_asked",
        ],
        "output_fields": ["answer", "recipes", "knowledge"],
    },
    "recipe_to_products": {
        "allowed_sources": ["Recipes", "Products_AI", "CrossSell", "Alternatives", "products"],
        "rules": [
            "one_best_product_per_ingredient",
            "no_duplicate_products",
            "no_weak_substitutes",
            "show_missing_ingredients_when_not_mapped",
        ],
        "output_fields": ["answer", "products", "missing_ingredients", "cart_candidates", "knowledge"],
    },
    "cross_sell": {
        "allowed_sources": ["CrossSell", "Products_AI", "products"],
        "rules": [
            "group_by_role",
            "each_product_has_reason",
            "no_repeat_of_original_product",
        ],
        "output_fields": ["answer", "products", "cart_candidates", "knowledge"],
    },
    "special_products": {
        "allowed_sources": ["Products_AI", "Alternatives", "products"],
        "rules": [
            "apply_exclude_terms",
            "no_duplicate_products",
        ],
        "output_fields": ["answer", "products", "knowledge"],
    },
    "product_search": {
        "allowed_sources": ["products", "Products_AI", "CrossSell", "Alternatives"],
        "rules": [
            "no_invented_prices_or_availability",
            "no_invented_urls",
            "show_effective_price",
        ],
        "output_fields": ["answer", "products", "knowledge"],
    },
    "out_of_domain": {
        "allowed_sources": [],
        "rules": ["return_fixed_refusal_message"],
        "output_fields": ["answer"],
    },
}


def get_contract(intent: str) -> dict:
    """Vrati kontrakt pre dany workflow. Bezpecny fallback na product_search."""
    return WORKFLOW_CONTRACTS.get(intent, WORKFLOW_CONTRACTS["product_search"])


def build_grounded_ids(products: list[dict]) -> set[str]:
    """Vrati mnozinu product_id ktore LLM smie spominat - zaklad grounding checku."""
    ids: set[str] = set()
    for p in products:
        pid = p.get("id")
        if pid:
            ids.add(str(pid))
    return ids


def products_to_cart_candidates(products: list[dict], reason: str = "") -> list[dict]:
    """
    Prevedie zoznam produktov na cart_candidates schema.
    Klient doplni: idempotency_key = f"{session_id}-{product_id}"
    """
    return [
        {
            "product_id": p.get("id", ""),
            "title": p.get("title", ""),
            "quantity": 1,
            "reason": reason or "odporucany produkt",
            "price": p.get("effective_price"),
            "currency": p.get("currency", "EUR"),
            "link": p.get("link", ""),
        }
        for p in products
        if p.get("id")
    ]

