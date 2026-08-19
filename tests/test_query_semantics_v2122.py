"""
tests/test_query_semantics_v2122.py  -  Sprint V2.12.2: Query Semantics,
Head-Concept & Constraint Enforcement.

Golden semantic regression matrix against the REAL catalog through the
REAL customer-facing app.main.chat() pipeline (not a simplified helper -
see docs/query-semantics.md for why: the three real production bugs this
sprint fixed were only reproducible through the full pipeline, not
through app.search.search_products()/cached_search_products() alone).

Root cause (see docs/query-semantics.md for the full investigation):
the taxonomy-aware structured retrieval engine (app.query_constraints /
app.retrieval / app.ranking, built in V2.3-V2.5) already implements real
head-concept extraction and family-contradiction exclusion correctly -
the customer-facing bugs were three specific defects PREVENTING these
queries from ever reaching that engine, not a missing architecture:

  Bug A - RELATED_INTENT_MARKERS contains broad single-word markers
          ("rezanc", "olej") that swept bare PRODUCT NAME queries
          ("ryzove rezance", "kokosovy olej") into the recipe-ingredient-
          companion workflow instead of direct product search.
  Bug B - app.taxonomy had no coconut_oil/coconut_cream/coconut_juice/
          coconut_vinegar FamilyRule at all, so "kokosovy olej" could
          never resolve a family and always hit LEGACY_FALLBACK.
  Bug D - SPECIAL_PRODUCT_QUERIES["sushi_rice"]/["rice_vinegar"] are
          legacy (pre-V2.4) hardcoded BUNDLE searches ("sushi ryza" +
          "nori" + "ryzovy ocot" + "wasabi"; "ryzovy ocot" + "rice
          vinegar" + "ocot sushi") that intercepted these queries before
          structured retrieval ever ran, mixing cross-sell/wrong-family
          items directly into primary search results. rice_vinegar was
          found via this sprint's OWN production smoke-testing (not part
          of the original hypothesis) - proof that "fix the semantic
          class of error, not individual queries" mattered in practice:
          the fix generalizes to every bare-product-name special_subject
          that has its OWN correct taxonomy family (plain_rice,
          sushi_rice, rice_vinegar, rice_cooker), while deliberately
          leaving constraint-based curated lists (gluten_free_sushi,
          medium_spicy, dairy_replacement, tamari, rice_seasoning - which
          has NO dedicated taxonomy family and would incorrectly widen to
          plain "rice" if migrated) on their existing legacy path.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import pytest

import app.main as m


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, limit: int = 8) -> dict:
    return m._chat_internal(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


def _titles(response: dict) -> list[str]:
    return [p.get("title", "") for p in (response.get("products") or [])]


def _normalized_titles(response: dict) -> list[str]:
    return [m.normalize(t) for t in _titles(response)]


class TestBugA_BareProductNameNotSweptIntoRelatedProducts:
    """RELATED_INTENT_MARKERS' broad single-word markers ("rezanc", "olej")
    must not override a confidently-resolved bare product-name query."""

    def test_ryzove_rezance_is_direct_product_search(self):
        r = _chat("ryzove rezance", "v2122-a-rezance")
        assert r["intent"] == "product_search"
        titles = _normalized_titles(r)
        assert titles, "expected real rice noodle products"
        assert all("rezance" in t or "rezanc" in t for t in titles), titles
        # Negative: none of the recipe-companion sauces/coconut-milk that
        # used to leak in via related_products_for_subject("ryzove_rezance").
        forbidden = ("rybacia omacka", "sojova omacka", "sriracha", "kokosove mlieko", "chili omacka")
        assert not any(f in t for t in titles for f in forbidden), titles

    def test_kokosovy_olej_is_direct_product_search(self):
        r = _chat("kokosovy olej", "v2122-a-olej")
        assert r["intent"] == "product_search"
        titles = _normalized_titles(r)
        assert titles, "expected real coconut oil products"
        assert all("olej" in t for t in titles), titles
        forbidden = ("voda", "dzus", "mlieko", "krem", "cips")
        assert not any(f in t for t in titles for f in forbidden), titles

    def test_genuine_companion_question_is_not_broken_by_the_guard(self):
        """Regression case found during this sprint's own verification
        (regbug_rt0005 in the V2.10 golden suite): "čo sa hodí ku
        gochujang?" is a REAL companion/cross-sell question and must
        keep returning related_products, not get swept into direct
        product search just because "gochujang" resolves confidently."""
        r = _chat("co sa hodi ku gochujang?", "v2122-a-gochujang")
        assert r["intent"] == "related_products"
        titles = _normalized_titles(r)
        for expected in ("kimchi", "sezamovy olej", "ryza", "ramen"):
            assert any(expected in t for t in titles), (expected, titles)


class TestBugB_CoconutOilTaxonomyCoverage:
    """app.taxonomy previously had no coconut_oil/coconut_cream/
    coconut_juice/coconut_vinegar FamilyRule at all."""

    def test_coconut_oil_resolves_its_own_family(self):
        from app.query_constraints import parse_structured_query
        parsed = parse_structured_query("kokosovy olej")
        assert parsed.family == "oil"
        assert parsed.subfamily == "coconut_oil"

    def test_coconut_cream_resolves_its_own_family(self):
        from app.query_constraints import parse_structured_query
        parsed = parse_structured_query("kokosovy krem")
        assert parsed.family == "coconut_product"
        assert parsed.subfamily == "coconut_cream"

    def test_coconut_juice_resolves_its_own_family(self):
        from app.query_constraints import parse_structured_query
        parsed = parse_structured_query("kokosovy dzus")
        assert parsed.family == "coconut_product"
        assert parsed.subfamily == "coconut_juice"

    def test_coconut_vinegar_resolves_its_own_family(self):
        from app.query_constraints import parse_structured_query
        parsed = parse_structured_query("kokosovy ocot")
        assert parsed.family == "vinegar"
        assert parsed.subfamily == "coconut_vinegar"

    def test_coconut_milk_query_never_returns_coconut_oil(self):
        r = _chat("kokosove mlieko", "v2122-b-milk")
        titles = _normalized_titles(r)
        assert titles
        assert not any("olej" in t for t in titles), titles

    def test_coconut_oil_query_never_returns_coconut_milk(self):
        r = _chat("kokosovy olej", "v2122-b-oil")
        titles = _normalized_titles(r)
        assert titles
        assert not any("mlieko" in t for t in titles), titles


class TestBugD_SushiRiceNoLongerBundlesCrossSell:
    """SPECIAL_PRODUCT_QUERIES["sushi_rice"] used to merge nori/wasabi/
    rice-vinegar searches directly into the primary "sushi ryza" result -
    Search vs. Cross-sell (spec Section 34)."""

    def test_sushi_rice_direct_search_excludes_condiments(self):
        r = _chat("sushi ryza", "v2122-d-sushi")
        assert r["intent"] == "product_search"
        titles = _normalized_titles(r)
        assert titles
        assert all("ryza" in t or "ryža" in t for t in _titles(r)) or all("ryza" in t for t in titles), titles
        forbidden = ("nori", "wasabi", "ocot", "morske riasy")
        assert not any(f in t for t in titles for f in forbidden), titles

    def test_show_more_stays_within_sushi_rice_only(self):
        r1 = _chat("sushi ryza", "v2122-d-sushi-showmore", limit=4)
        assert len(r1.get("products") or []) == 4
        r2 = _chat("zobraz viac", "v2122-d-sushi-showmore", limit=4)
        titles = _normalized_titles(r2)
        forbidden = ("nori", "wasabi", "ocot", "morske riasy")
        assert not any(f in t for t in titles for f in forbidden), titles


class TestBugD_RiceVinegarAndRiceCookerAlsoDeBundled:
    """Found via this sprint's own production smoke-testing (not the
    original hypothesis): SPECIAL_PRODUCT_QUERIES["rice_vinegar"]
    includes the sub-query "ocot sushi", which pulled sushi-kit and
    rice-flour products directly into a plain "ryzovy ocot" search - the
    same bundle-search class of bug as sushi_rice (Bug D above)."""

    def test_rice_vinegar_special_subject_excludes_unrelated_products(self):
        r = _chat("ryzovy ocot", "v2122-d2-vinegar")
        assert r["intent"] == "product_search"
        titles = _normalized_titles(r)
        assert titles
        assert all("ocot" in t for t in titles), titles
        forbidden = ("sushi set", "muka", "papier", "vlocky")
        assert not any(f in t for t in titles for f in forbidden), titles

    def test_rice_cooker_special_subject_stays_rice_cooker_only(self):
        r = _chat("ryzovar", "v2122-d2-cooker")
        assert r["intent"] == "product_search"
        titles = _normalized_titles(r)
        assert titles
        assert all("ryzovar" in t or "hrniec" in t for t in titles), titles

    def test_rice_seasoning_deliberately_left_on_legacy_path(self):
        """rice_seasoning has NO dedicated taxonomy family - migrating it
        would make parse_structured_query() fall back to plain "rice"
        family and lose the "seasoning mix" qualifier entirely (verified
        during this sprint's own fix - a real near-miss, not a
        hypothetical). Must NOT be in the generalized migration set."""
        from app.query_constraints import parse_structured_query
        parsed = parse_structured_query("koreniaca zmes na ryzu")
        assert parsed.family in (None, "rice")  # no dedicated "rice_seasoning" family exists


class TestAlreadyCleanQueriesStayClean:
    """basmati/jasmine/rice-vinegar/rice-paper were already correctly
    scoped by the pre-existing V2.3/V2.4 taxonomy engine - regression
    guard against ever breaking these while fixing the three bugs above."""

    def test_basmati_rice_excludes_noodles_vinegar_paper(self):
        r = _chat("basmati ryza", "v2122-clean-basmati")
        titles = _normalized_titles(r)
        assert titles
        assert all("basmati" in t for t in titles), titles
        forbidden = ("rezance", "ocot", "papier")
        assert not any(f in t for t in titles for f in forbidden), titles

    def test_jasmine_rice_excludes_other_rice_products(self):
        r = _chat("jazminova ryza", "v2122-clean-jasmine")
        titles = _normalized_titles(r)
        assert titles
        assert all("jazminov" in t for t in titles), titles
        forbidden = ("susi", "sushi", "rezance", "ryzovar")
        assert not any(f in t for t in titles for f in forbidden), titles

    def test_rice_vinegar_excludes_rice_paper(self):
        r = _chat("ryzovy ocot", "v2122-clean-vinegar")
        titles = _normalized_titles(r)
        assert titles
        assert all("ocot" in t for t in titles), titles
        assert not any("papier" in t for t in titles), titles

    def test_rice_paper_excludes_flour_starch(self):
        r = _chat("ryzovy papier", "v2122-clean-paper")
        titles = _normalized_titles(r)
        assert titles
        assert all("papier" in t for t in titles), titles
        forbidden = ("skrob", "muka")
        assert not any(f in t for t in titles for f in forbidden), titles


class TestBrandAndExactProductRegression:
    def test_kikkoman_still_returns_kikkoman_products_across_families(self):
        r = _chat("kikkoman", "v2122-brand-kikkoman")
        titles = _normalized_titles(r)
        assert titles
        assert all("kikkoman" in t for t in titles), titles

    def test_exact_product_title_lookup_still_works(self):
        r = _chat("Royal Umbrella jazminova ryza", "v2122-exact-product")
        titles = _normalized_titles(r)
        assert any("royal umbrella" in t for t in titles), titles


class TestFollowUpPreservesConstraints:
    def test_basmati_then_cheaper_stays_basmati(self):
        _chat("basmati ryza", "v2122-followup-basmati")
        r2 = _chat("lacnejsiu", "v2122-followup-basmati")
        titles = _normalized_titles(r2)
        assert titles
        assert all("basmati" in t for t in titles), titles


class TestAllergenSafetyUnaffected:
    def test_allergen_answer_still_answered_with_zero_products(self):
        r = _chat("mam alergiu na lepok, co by ste doporucili?", "v2122-allergen")
        assert r["intent"] == "allergen_safety"
        assert r["products"] == []
        assert r["answered"] is True
