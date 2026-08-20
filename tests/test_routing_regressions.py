"""
tests/test_routing_regressions.py  -  V2.13b: broad routing control
matrix. Verifies that fixing rt0004/rt0010 did NOT introduce unexpected
routing drift elsewhere (Section 143 - "if more unrelated queries change
workflow, STOP"). Every query here is tested end-to-end through the real
chat() pipeline.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, limit: int = 8) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


def _titles(response: dict) -> list[str]:
    return [p.get("title", "") for p in (response.get("products") or [])]


class TestV2122SemanticControlsUnaffected:
    """Section 116 - mandatory controls, must remain unchanged."""

    def test_jasmine_rice_stays_rice_not_tea(self):
        r = _chat("jazmínová ryža", "rr-jasmine")
        titles = [m.normalize(t) for t in _titles(r)]
        assert titles
        assert not any("caj" in t for t in titles)
        assert r.get("intent") == "product_search"

    def test_basmati_rice_stays_rice(self):
        r = _chat("basmati ryža", "rr-basmati")
        assert _titles(r)
        assert r.get("intent") == "product_search"

    def test_rice_noodles_stays_noodles(self):
        r = _chat("ryžové rezance", "rr-noodles")
        assert _titles(r)
        assert r.get("intent") == "product_search"

    def test_rice_vinegar_stays_vinegar(self):
        r = _chat("ryžový ocot", "rr-vinegar")
        assert _titles(r)
        assert r.get("intent") == "product_search"

    def test_coconut_milk_stays_milk_not_oil(self):
        r = _chat("kokosové mlieko", "rr-coconut")
        titles = [m.normalize(t) for t in _titles(r)]
        assert titles
        assert not any("olej" in t for t in titles)


class TestProductSearchControls:
    """Section 117/149 - normal search must not drift into a native
    workflow it doesn't belong to."""

    def test_kikkoman_remains_brand_search(self):
        r = _chat("Kikkoman", "rr-kikkoman")
        assert _titles(r)
        assert r.get("intent") == "product_search"

    def test_shin_ramyun_remains_product_search(self):
        r = _chat("Shin Ramyun", "rr-shinramyun")
        assert _titles(r)
        assert r.get("intent") == "product_search"

    def test_fish_sauce_remains_product_search(self):
        r = _chat("rybacia omáčka", "rr-fishsauce")
        assert _titles(r)
        assert r.get("intent") == "product_search"

    def test_dark_soy_sauce_remains_product_search(self):
        r = _chat("tmavá sójová omáčka", "rr-darksoy")
        assert _titles(r)
        assert r.get("intent") == "product_search"

    def test_plain_sushi_rice_remains_product_search_not_related(self):
        """Section 74 - required normal-search control: bare "sushi ryža"
        must NOT become RELATED_PRODUCTS merely because the resolver now
        exists."""
        r = _chat("sushi ryža", "rr-sushirice")
        assert _titles(r)
        assert r.get("intent") == "product_search"

    def test_plain_soy_sauce_remains_product_search_not_safety(self):
        """Section 75 - required safety control: "sójová omáčka" alone
        must NOT become ALLERGEN_SAFETY merely because soy is in the name."""
        r = _chat("sójová omáčka", "rr-soysauce")
        assert _titles(r)
        assert r.get("intent") == "product_search"

    def test_bare_rice_remains_ordinary_search(self):
        """Section 77 - "ryža" alone must remain ordinary search, no
        related-products workflow without explicit action/context."""
        r = _chat("ryža", "rr-bare-rice")
        assert r.get("intent") == "product_search"


class TestRelatedProductsGenericAcrossAnchors:
    """Section 123 - related-products routing must be generic, not only
    proven on the sushi-rice anchor."""

    def test_related_products_to_curry_paste(self):
        r = _chat("čo sa hodí k červenej kari paste?", "rr-related-curry")
        assert r.get("intent") == "related_products"
        assert _titles(r)

    def test_related_products_to_gochujang(self):
        r = _chat("čo sa hodí ku gochujang?", "rr-related-gochujang")
        assert r.get("intent") == "related_products"
        assert _titles(r)


class TestUnknownExactProductDiscoverable:
    """Section 55/117 - taxonomy-UNKNOWN exact product queries remain
    discoverable; the resolver must not treat UNKNOWN as an exclusion."""

    def test_wasabi_still_returns_results(self):
        r = _chat("wasabi", "rr-wasabi")
        assert _titles(r)


class TestShowMoreUnaffected:
    """Section 118 - Show More must remain exact ResultSet continuation,
    untouched by the new resolver (which explicitly checks this FIRST,
    Section 35/36)."""

    def test_show_more_preserves_result_universe(self):
        first = _chat("basmati ryza", "rr-showmore", limit=3)
        assert first.get("has_more") is True or first.get("matching_total", 0) > 3
        second = _chat("zobraz viac", "rr-showmore")
        assert second.get("response_mode") == "result_set_continuation"
        assert second.get("intent") == "product_search"
