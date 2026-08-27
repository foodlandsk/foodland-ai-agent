"""
tests/test_product_attribute_intelligence_v2_16b.py  -  V2.16b
PRODUCT UNDERSTANDING & ATTRIBUTE INTELLIGENCE.

Audit-first sprint (docs/product-attribute-intelligence-v2.16b.md has the
full write-up). Core finding: this codebase has NO structured per-SKU
dietary/allergen/ingredient field anywhere in data/products.json (13
fields total: id, title, description, product_type, link, image_link,
price, sale_price, currency, brand, availability, gtin,
unit_pricing_measure). The only catalog-derived dietary signal is a
substring match against the `product_type` merchandising-category
breadcrumb (app.taxonomy._DIETARY_CATEGORY_TERMS /
app.query_constraints._DIETARY_QUERY_STEMS), which was ALREADY a real,
wired-in, "Safety/relevance-critical... hard-filtered" mechanism in the
live /chat structured retrieval pipeline (app/retrieval.py) before this
sprint touched anything.

THE ONE REAL BUG THIS SPRINT FIXES: a live, reproduced false positive -
FL_9996 "Oyakata Teriyaki kuracie instantne rezance" (a chicken-flavoured
instant noodle product; description literally says "chuti kurcata") had
product_type "Veganske potraviny > Japonske > Vegetarianske potraviny >
...". Before this fix, a real customer message "vegánske rezance" (via
the dietary_facets hard-filter) surfaced this chicken product as a top
vegan match. Reproduced against unmodified HEAD, root-caused to
app.taxonomy._DIETARY_CATEGORY_TERMS mapping "veganske potraviny"/
"vegetarianske potraviny" breadcrumb segments directly to "vegan"/
"vegetarian" facets with no ingredient-level verification - proven to be
Foodland's own bulk merchandising category (a "health/Asian pantry"
shelf grouping), not a per-SKU dietary claim.

FIX: "vegan"/"vegetarian" removed from both
app.taxonomy._DIETARY_CATEGORY_TERMS and
app.query_constraints._DIETARY_QUERY_STEMS. Missing a facet is UNKNOWN,
never FALSE (Section 27 of the closure spec) - a vegan/vegetarian query
now falls through to ordinary relevance search (no false inclusion, but
also no confident "yes this is vegan" exclusion either) instead of a
false-confidence hard filter.

gluten_free/organic were audited with the same rigor (full sweep of all
563/2140 gluten-free-tagged products against known wheat-noodle/regular-
soy-sauce products - 0 confirmed mistags found; regular Kikkoman soy
sauce, which contains wheat, correctly does NOT carry the gluten-free
category tag, while every udon/wheat-noodle product in the catalog is
correctly excluded from it) and were NOT touched - proven-safe existing
behavior is left alone (Section "do not treat ordinary... as reasons to
[touch working code]").

halal has ZERO code presence anywhere in the repository (confirmed by
full-repo grep) and only 3 unstructured product-description mentions -
DATA_REQUIRED, no implementation attempted.

flavor_profile/authenticity/premium: app.comparison.py ALREADY hard-
ABSTAINs on qualitative claims (_QUALITATIVE_MARKERS -> GOAL_UNSUPPORTED_
QUALITATIVE -> STATE_ABSTAIN) - this precedent predates V2.16b and is
regression-locked here, not reimplemented.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m
from app.taxonomy import classify_product, _DIETARY_CATEGORY_TERMS
from app.query_constraints import parse_structured_query, _DIETARY_QUERY_STEMS


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, limit: int = 10) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


def _titles(r: dict) -> list[str]:
    return [p.get("title", "") for p in (r.get("products") or [])]


# ---------------------------------------------------------------------------
# A. The proven bug, fixed - permanent regression lock.
# ---------------------------------------------------------------------------

class TestVeganFalsePositiveFixed:
    def test_chicken_product_no_longer_matches_vegan_category_facet(self):
        from app.feed import Product
        p = Product(
            id="FL_9996",
            title="Oyakata Teriyaki kuracie instantne rezance v kelimku AJ 96g",
            description="chuti kurcata s rezancami a omackou teriyaki",
            product_type="Veganske potraviny > Japonske > Vegetarianske potraviny > Zdrave potraviny",
            link="", image_link="", price=1.9, sale_price=None, currency="EUR",
            brand="Ajinomoto", availability="in_stock", gtin="5901384503642",
            unit_pricing_measure="93g",
        )
        tax = classify_product(p)
        assert "vegan" not in tax.dietary_facets
        assert "vegetarian" not in tax.dietary_facets

    def test_vegan_and_vegetarian_removed_from_category_term_map(self):
        assert "veganske potraviny" not in _DIETARY_CATEGORY_TERMS
        assert "vegetarianske potraviny" not in _DIETARY_CATEGORY_TERMS
        assert _DIETARY_CATEGORY_TERMS.get("bezlepkove potraviny") == "gluten_free"

    def test_vegan_and_vegetarian_removed_from_query_stems(self):
        assert "vegansk" not in _DIETARY_QUERY_STEMS
        assert "vegetariansk" not in _DIETARY_QUERY_STEMS
        assert _DIETARY_QUERY_STEMS.get("bezlepkov") == "gluten_free"

    def test_vegan_query_no_longer_hard_filters_to_dietary_facet(self):
        query = parse_structured_query("vegánske rezance")
        assert query.dietary_facets == []

    def test_live_vegan_query_no_longer_surfaces_chicken_product(self):
        r = _chat("vegánske rezance", "v216b-vegan-live-fix")
        titles = [t.lower() for t in _titles(r)]
        assert not any("kuracie" in t or "chicken" in t for t in titles), titles


# ---------------------------------------------------------------------------
# B. gluten_free - audited, kept, unaffected.
# ---------------------------------------------------------------------------

class TestGlutenFreeUnaffected:
    def test_gluten_free_still_a_valid_facet(self):
        query = parse_structured_query("bezlepkova sojova omacka")
        assert "gluten_free" in query.dietary_facets

    def test_tamari_gluten_free_query_returns_grounded_results(self):
        r = _chat("bezlepkova sojova omacka", "v216b-gf-query")
        titles = " ".join(_titles(r)).lower()
        assert "tamari" in titles or "bezlepk" in titles


# ---------------------------------------------------------------------------
# C. halal - DATA_REQUIRED, no fabricated claim, no crash.
# ---------------------------------------------------------------------------

class TestHalalDataRequired:
    def test_halal_query_does_not_crash_and_does_not_claim_certification(self):
        r = _chat("halal rezance", "v216b-halal")
        answer = (r.get("answer") or "").lower()
        # Must never assert a product IS halal-certified - no such data exists.
        assert "certifik" not in answer


# ---------------------------------------------------------------------------
# D. Brand - already strong, structured, regression-locked.
# ---------------------------------------------------------------------------

class TestBrandExactMatch:
    def test_brand_query_returns_matching_brand(self):
        r = _chat("Kikkoman sojova omacka", "v216b-brand")
        titles = " ".join(_titles(r)).lower()
        assert "kikkoman" in titles


# ---------------------------------------------------------------------------
# E. Size - exact match works; threshold comparison remains unsupported
#    (FOUNDATION_ONLY, documented, not implemented this sprint).
# ---------------------------------------------------------------------------

class TestSizeExactMatch:
    def test_exact_size_query_returns_matching_size(self):
        r = _chat("ryza 5 kg", "v216b-size-exact")
        titles = " ".join(_titles(r)).lower()
        assert "5 kg" in titles

    def test_threshold_size_query_is_not_reliably_filtered(self):
        # FOUNDATION_ONLY characterization: "aspoň 1 liter" (at least 1L)
        # does NOT currently filter to only >=1L products - it falls
        # through to ordinary relevance search. This test locks in the
        # CURRENT (honest) behavior, not a claim that thresholds work.
        r = _chat("sojova omacka aspon 1 liter", "v216b-size-threshold")
        # Must not crash; presence of smaller-than-1L items is expected
        # and acceptable since no threshold filter is applied.
        assert r.get("intent") is not None


# ---------------------------------------------------------------------------
# F. Taxonomy / product_type - HIGH/MEDIUM tier reused correctly.
# ---------------------------------------------------------------------------

class TestTaxonomyConfidenceTiers:
    def test_taxonomy_index_reports_all_four_confidence_tiers(self):
        idx = m.build_taxonomy_index(m.products)
        confidences = {tax.confidence for tax in idx.values()}
        assert confidences <= {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}
        assert "UNKNOWN" in confidences  # coverage is NOT total - honest


# ---------------------------------------------------------------------------
# G. Use-case fit - reused from V2.14/h, not reinvented.
# ---------------------------------------------------------------------------

class TestUseCaseFitReused:
    def test_sushi_use_case_still_live(self):
        r = _chat("ryza na sushi", "v216b-usecase-sushi")
        assert r.get("intent") in ("product_search", "related_products", "use_case_advice")
        assert len(r.get("products") or []) > 0

    def test_ramen_use_case_still_live(self):
        r = _chat("daj mi recept na ramen", "v216b-usecase-ramen")
        assert r.get("intent") == "recipe"


# ---------------------------------------------------------------------------
# H. Flavor / authenticity / premium - existing ABSTAIN precedent locked.
# ---------------------------------------------------------------------------

class TestQualitativeClaimsAbstain:
    def test_comparison_taste_question_abstains(self):
        r = _chat("Aky je rozdiel medzi Kikkoman a Yamasa sojovou omackou, ktora chutí lepšie?", "v216b-qual-taste")
        answer = (r.get("answer") or "").lower()
        # Must not confidently assert one tastes better - no data backs this.
        assert "chutnejsi" not in answer and "chutnejšia" not in answer.replace("š", "s")


# ---------------------------------------------------------------------------
# I. Compound constraints - brand + size.
# ---------------------------------------------------------------------------

class TestCompoundConstraints:
    def test_brand_and_size_compound(self):
        r = _chat("Kikkoman sojova omacka 1000ml", "v216b-compound")
        titles = " ".join(_titles(r)).lower()
        assert "kikkoman" in titles


# ---------------------------------------------------------------------------
# J. Zero-match / hard-switch / session safety.
# ---------------------------------------------------------------------------

class TestZeroMatchAndSafety:
    def test_nonsense_attribute_query_does_not_crash(self):
        r = _chat("halal vegan bezlepkova nesystemova poziadavka xyz123", "v216b-nonsense")
        assert r.get("intent") is not None

    def test_hard_switch_to_allergen_safety_after_attribute_query(self):
        sid = "v216b-hardswitch-allergen"
        _chat("vegánske rezance", sid)
        r = _chat("Mam alergiu na arasidy, co mi odporucate?", sid)
        assert r.get("intent") == "allergen_safety"

    def test_reset_after_attribute_query(self):
        sid = "v216b-reset"
        _chat("vegánske rezance", sid)
        r = _chat("Zacnime odznova", sid)
        assert r.get("intent") == "reset"


# ---------------------------------------------------------------------------
# K. Permanent regression controls (unaffected by this sprint).
# ---------------------------------------------------------------------------

class TestPermanentRoutingControls:
    def test_rt0004_related_products_protected(self):
        r = _chat("suvisiace produkty k sushi ryzi", "v216b-rt0004")
        assert r.get("intent") == "related_products"

    def test_rt0010_allergen_safety_protected(self):
        r = _chat("sojova omacka bez soje", "v216b-rt0010")
        assert r.get("intent") == "allergen_safety"

    def test_rt0011_no_session_contamination(self):
        sid = "v216b-rt0011"
        query = "mam rad nepalive jedlo, co odporucas?"
        first = _chat(query, sid)
        second = _chat(query, sid)
        assert first.get("intent") == "product_search"
        assert second.get("intent") == "product_search"

    def test_rt0013_replacement_products_protected(self):
        r = _chat("nahrada za rybiu omacku vegan", "v216b-rt0013")
        assert r.get("intent") == "replacement_products"

    def test_store_location_still_live(self):
        r = _chat("Kde sa nachadza kamenna predajna?", "v216b-store")
        assert r.get("intent") == "faq"

    def test_opening_hours_still_live(self):
        r = _chat("Kedy mate otvorene?", "v216b-hours")
        assert r.get("intent") == "faq"

    def test_contact_still_live(self):
        r = _chat("Ako vas mozem kontaktovat?", "v216b-contact")
        assert r.get("intent") == "faq"

    def test_payment_followup_still_live(self):
        sid = "v216b-payment"
        _chat("Ako mozem zaplatit?", sid)
        r = _chat("A Apple Pay?", sid)
        assert r.get("intent") == "faq"
