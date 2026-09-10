"""
app/workflows.py

Historical note: this module originally hosted a Sprint 1 workflow-engine
prototype (WorkflowResult, detect_workflow(), WORKFLOW_CONTRACTS,
get_contract(), build_grounded_ids()) that was designed and tested but
never wired into /chat - app.main routes intents directly. Confirmed dead
via grep (see docs/workflow-precedence-before-v2.13b.md) and removed.

products_to_cart_candidates() is the one function from this module that
app.main actually imports and uses; it remains here.

Usage:
    from app.workflows import products_to_cart_candidates
"""
from __future__ import annotations


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
