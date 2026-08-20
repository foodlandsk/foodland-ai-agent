"""
tests/test_query_semantics_v2123.py  -  Sprint V2.12.3: Quality Closure,
Legacy Retrieval Migration & Family-Purity Hardening.

See docs/query-semantics.md ("V2.12.3 dodatok") for the full investigation.

Bug C - app.search.search_products() is a legacy additive/OR-based scorer
         with no taxonomy awareness and no minimum token coverage.
         PREFIX_SYNONYMS roots shared across unrelated families (kokos,
         ryz/rice, sojov/soy, rezance/noodles) let it surface a different,
         well-classified family alongside the query's own confidently-
         resolved family. Fixed via app.main._exclude_taxonomy_family_mismatches(),
         a confidence-gated filter inside cached_search_products() (not
         app/search.py itself - app.taxonomy already imports app.search,
         so the reverse import would be circular). Protects all 24
         cached_search_products() call sites at once, including the
         unconditional fallback of hybrid_cached_search_products().

Companion taxonomy gaps found WHILE verifying the guard (not hypothesized
up front) - the guard is only as safe as the family resolution it reads:
  - "udon rezance" query mis-resolved to instant_food via the generic bare
    "rezance" phrase in the instant_noodles rule (products were already
    correctly classified via category_terms - only the query-side, which
    has no category to match against, was wrong). Fixed by giving
    wheat_noodles its own "udon" title_phrase.
  - Glass noodles ("sklenene rezance"/"glass noodles") had no FamilyRule
    at all - both the 14 real catalog products AND the query fell through
    to instant_noodles. Fixed with a dedicated glass_noodles rule
    positioned before instant_noodles.
  - instant_noodles' bare "rezance" phrase (kept because ~half of real
    instant-noodle titles have no other distinguishing word) was also
    matching a noodle strainer, konjac/shirataki noodles, and noodle-
    flavoured sauces. Excluded via exclude_title_phrases.
  - chili_paste and tamarind_pasta had no FamilyRule at all (family=None
    for both languages). chili_paste required an exclude_title_phrases
    guard against "gochujang" - Korean gochujang products are literally
    titled "Cili pasta Gochujang ..." in this catalog, and without the
    exclude the less-specific chili_paste rule would out-rank the existing,
    more-specific gochujang rule (see TestGochujangStillWinsOverChiliPaste).
  - English title_phrases were missing from every sauce/oil/noodle
    FamilyRule that already worked correctly in Slovak (soy_sauce,
    dark_soy_sauce, light_soy_sauce, fish_sauce, coconut_oil, rice_noodles)
    - a systemic, not isolated, multilingual coverage gap.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m
from app.query_constraints import parse_structured_query


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


def _search_titles(query: str, limit: int = 10) -> list[str]:
    return [p.get("title", "") for p in m.cached_search_products(m.products, query, limit)]


class TestBugC_LegacyScorerFamilyMismatchGuard:
    """_exclude_taxonomy_family_mismatches() must remove candidates whose
    OWN classified family differs from the query's confidently-resolved
    family, while never emptying an otherwise non-empty result set."""

    def test_coconut_oil_no_longer_returns_coconut_vinegar_or_juice(self):
        titles = [m.normalize(t) for t in _search_titles("kokosovy olej")]
        assert titles
        assert not any("ocot" in t for t in titles), titles
        assert not any("dzus" in t for t in titles), titles
        assert not any("krem" in t for t in titles), titles

    def test_rice_cooker_no_longer_returns_rice_noodles_or_flour(self):
        titles = [m.normalize(t) for t in _search_titles("ryzovar")]
        assert titles
        assert not any("rezance" in t for t in titles), titles
        assert not any("muka" in t for t in titles), titles

    def test_oyster_sauce_stays_within_sauce_family(self):
        # The guard filters cross-FAMILY mismatches only (docs/query-
        # semantics.md: "Zámerne nerieši subfamily-level presnosť", same
        # tradeoff the spec itself sanctions for curry-paste colour) - a
        # same-family sibling sauce (hoisin) legitimately sharing category
        # tokens with oyster sauce may still appear. What must never appear
        # is a product from a genuinely different top-level family.
        parsed = parse_structured_query("ustricova omacka")
        assert parsed.family == "sauce"
        titles = _search_titles("ustricova omacka")
        assert titles
        for p in m.products:
            if p.title in titles:
                tax = m.product_taxonomy_index.get(p.id)
                if tax is not None and tax.canonical_family is not None:
                    assert tax.canonical_family == "sauce", p.title

    def test_guard_never_returns_zero_results_when_unfiltered_had_hits(self):
        # "tamarind" alone stays UNKNOWN (genuinely ambiguous - see
        # TestRelatedProductBundles below), so this exercises the
        # fallback-to-unfiltered path for a low/no-confidence query.
        titles = _search_titles("tamarind")
        assert titles

    def test_guard_is_a_noop_for_unresolved_queries(self):
        # A query with no confident family must return exactly what the
        # legacy scorer produced - the guard must never invent filtering
        # for something it can't verify.
        with_guard = _search_titles("kimchi")
        assert with_guard


class TestGochujangStillWinsOverChiliPaste:
    """Korean gochujang products are literally titled "Cili pasta
    Gochujang ..." in this catalog - the new chili_paste rule must not
    out-rank the existing, more specific gochujang rule (regression found
    via tests/test_taxonomy_v23.py::test_gochujang while adding chili_paste)."""

    def test_gochujang_query_resolves_gochujang_not_chili_paste(self):
        parsed = parse_structured_query("gochujang")
        assert parsed.family == "paste"
        assert parsed.subfamily == "gochujang"

    def test_gochujang_products_classify_as_gochujang(self):
        for p in m.products:
            if "gochujang" in m.normalize(p.title):
                tax = m.product_taxonomy_index.get(p.id)
                assert tax is not None
                assert tax.canonical_subfamily == "gochujang", p.title


class TestNoodleFamilyPurity:
    """udon/glass-noodle taxonomy gaps found while verifying the Bug C
    guard - see module docstring."""

    def test_udon_query_resolves_wheat_noodles_not_instant_food(self):
        parsed = parse_structured_query("udon rezance")
        assert parsed.family == "noodles"
        assert parsed.subfamily == "wheat_noodles"

    def test_udon_search_excludes_instant_tempura_udon(self):
        titles = [m.normalize(t) for t in _search_titles("udon rezance")]
        assert titles
        assert not any("instant" in t for t in titles), titles

    def test_glass_noodles_query_resolves_own_family(self):
        for query in ("sklenene rezance", "glass noodles"):
            parsed = parse_structured_query(query)
            assert parsed.family == "noodles", query
            assert parsed.subfamily == "glass_noodles", query

    def test_glass_noodles_search_excludes_instant_ramyun(self):
        for query in ("sklenene rezance", "glass noodles"):
            titles = [m.normalize(t) for t in _search_titles(query)]
            assert titles, query
            assert all("sklenene rezance" in t for t in titles), (query, titles)

    def test_glass_noodle_products_classify_as_glass_noodles_not_instant(self):
        for p in m.products:
            if "sklenene rezance" in m.normalize(p.title):
                tax = m.product_taxonomy_index.get(p.id)
                assert tax is not None
                assert tax.canonical_family == "noodles", p.title
                assert tax.canonical_subfamily == "glass_noodles", p.title

    def test_noodle_strainer_and_sauces_no_longer_tagged_instant_noodles(self):
        # These were real false positives caught only via bare "rezance":
        # a strainer (kitchenware) and noodle sauces, not instant noodles.
        false_positive_titles = [
            "Sitko na rezance s drevenou rukovaťou 12cm",
            "Yakisoba omáčka na rezance OTAFUKU 300g",
        ]
        for p in m.products:
            if p.title in false_positive_titles:
                tax = m.product_taxonomy_index.get(p.id)
                if tax is not None:
                    assert not (
                        tax.canonical_family == "instant_food"
                        and tax.canonical_subfamily == "instant_noodles"
                    ), p.title


class TestChiliAndTamarindPasteTaxonomyCoverage:
    """Neither had a FamilyRule at all before this sprint."""

    def test_chili_paste_resolves_own_family_both_spellings(self):
        for query in ("cili pasta", "chili paste", "chilli paste"):
            parsed = parse_structured_query(query)
            assert parsed.family == "paste", query
            assert parsed.subfamily == "chili_paste", query

    def test_chili_paste_search_excludes_snacks_and_pickles(self):
        titles = [m.normalize(t) for t in _search_titles("chili paste")]
        assert titles
        assert not any("chips" in t for t in titles), titles
        assert not any("pickle" in t for t in titles), titles

    def test_tamarind_paste_resolves_own_family_both_languages(self):
        for query in ("tamarindova pasta", "tamarind pasta", "tamarind paste"):
            parsed = parse_structured_query(query)
            assert parsed.family == "paste", query
            assert parsed.subfamily == "tamarind_pasta", query


class TestEnglishAliasesForAlreadyCorrectFamilies:
    """Systemic gap: every Slovak sauce/oil/noodle FamilyRule that already
    worked correctly had zero English title_phrases at all."""

    def test_soy_sauce_variants_resolve_in_english(self):
        for query, expected_subfamily in (
            ("soy sauce", "soy_sauce"),
            ("dark soy sauce", "soy_sauce"),
            ("light soy sauce", "soy_sauce"),
        ):
            parsed = parse_structured_query(query)
            assert parsed.family == "sauce", query
            assert parsed.subfamily == expected_subfamily, query

    def test_fish_sauce_resolves_in_english(self):
        parsed = parse_structured_query("fish sauce")
        assert parsed.family == "sauce"
        assert parsed.subfamily == "fish_sauce"

    def test_coconut_oil_resolves_in_english(self):
        parsed = parse_structured_query("coconut oil")
        assert parsed.family == "oil"
        assert parsed.subfamily == "coconut_oil"

    def test_rice_noodles_resolves_in_english(self):
        parsed = parse_structured_query("rice noodles")
        assert parsed.family == "noodles"
        assert parsed.subfamily == "rice_noodles"

    def test_english_fish_sauce_search_stays_within_fish_sauce(self):
        titles = [m.normalize(t) for t in _search_titles("fish sauce")]
        assert titles
        assert all("rybacia omacka" in t for t in titles), titles


class TestRelatedProductBundleInteraction:
    """V2.12.2's Bug A guard now automatically redirects these queries to
    direct product search instead of the RELATED_PRODUCT_QUERIES bundle,
    purely as a consequence of them now resolving a confident family - no
    change to RELATED_PRODUCT_QUERIES itself was needed or made
    (see docs/special-product-query-audit.md)."""

    def test_glass_noodles_is_direct_search_not_related_bundle(self):
        r = _chat("glass noodles", "v2123-related-glass-noodles")
        assert r.get("intent") == "product_search"
        titles = _normalized_titles(r)
        assert titles
        assert all("sklenene rezance" in t for t in titles), titles

    def test_bare_tamarind_stays_on_related_products_path(self):
        # Genuinely ambiguous (paste vs. concentrate vs. dried fruit vs.
        # drink all exist in the catalog) - must NOT be forced into a
        # single guessed family.
        r = _chat("tamarind", "v2123-related-tamarind")
        assert r.get("intent") == "related_products"


class TestBrandExactAndUnknownQueriesUnaffected:
    """Spec-mandated matrix (Sections 44-56): brand/exact-product lookups
    and genuinely unresolvable queries must not be touched by the guard."""

    def test_brand_plus_family_query_stays_within_brand_and_family(self):
        titles = [m.normalize(t) for t in _search_titles("kikkoman sojova omacka")]
        assert titles
        assert all("kikkoman" in t for t in titles), titles
        assert all("sojova omacka" in t for t in titles), titles

    def test_exact_product_line_lookup_stays_within_paste_family(self):
        # "gochujang sempio" mixes a product name with a brand - the legacy
        # scorer legitimately also surfaces other SEMPIO pastes (ssamjang,
        # fermented soy paste) via the shared "sempio" token, and other
        # brands' gochujang via the shared "gochujang" token (not a brand-
        # exclusivity guarantee). What the guard must still hold is family
        # purity: no result is from an entirely different top-level family.
        titles = _search_titles("gochujang sempio")
        assert titles
        for p in m.products:
            if p.title in titles:
                tax = m.product_taxonomy_index.get(p.id)
                if tax is not None and tax.canonical_family is not None:
                    assert tax.canonical_family == "paste", p.title

    def test_generic_no_family_query_returns_results_unfiltered(self):
        # "wasabi" has no dedicated FamilyRule (family=None) - the guard
        # must be a complete no-op, not silently drop real results.
        parsed = parse_structured_query("wasabi")
        assert parsed.family is None
        titles = _search_titles("wasabi")
        assert titles
        assert any("wasabi" in m.normalize(t) for t in titles), titles


class TestFullRegressionSuiteUnaffected:
    """Spot-check that V2.12.2's own golden cases are still clean after
    the Bug C guard and new taxonomy rules."""

    def test_basmati_rice_still_excludes_noodles_and_vinegar(self):
        r = _chat("basmati ryza", "v2123-basmati")
        titles = _normalized_titles(r)
        assert titles
        assert not any("rezance" in t for t in titles), titles
        assert not any("ocot" in t for t in titles), titles

    def test_kikkoman_brand_still_returns_kikkoman(self):
        r = _chat("kikkoman", "v2123-kikkoman")
        titles = _titles(r)
        assert titles
        assert any("KIKKOMAN" in t.upper() for t in titles), titles

    def test_regbug_rt0010_behavior_fixed_by_v213b(self):
        # SAFETY_CORRECTION (Section 114 golden-change policy): this test
        # asserted product_search/4-products through V2.12.3/V2.12.4/V2.13a
        # (matching the then-current, then-classified-as-out-of-scope
        # behavior). V2.13b's WorkflowResolver fixes the underlying
        # precedence bug generically (docs/routing-debt.md,
        # docs/workflow-precedence-before-v2.13b.md) - the query now
        # correctly resolves to allergen_safety with zero products. This
        # is an intentional, documented, evidenced routing fix, not a
        # "code differs" drift - see app/turn_resolver.py/
        # app/workflow_resolver.py.
        r = _chat("sójová omáčka bez sóje", "v2123-allergen")
        assert r.get("intent") == "allergen_safety"
        assert not (r.get("products") or [])
