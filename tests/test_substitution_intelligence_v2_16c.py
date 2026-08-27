"""
tests/test_substitution_intelligence_v2_16c.py  -  V2.16c evidence-grounded
substitution intelligence closure.

V2.16c audited the replacement_products candidate pipeline
(detect_replacement_subject() -> alternative_products_for_subject(), and
the detect_special_product_subject() legacy path that pre-empts it for 3
of 13 REPLACEMENT_SUBJECT_ALIASES entries) against the same "missing
evidence is UNKNOWN, never FALSE" principle V2.16b applied to product
search. Three real, reproducible defects were found and fixed, all
scoped to CANDIDATE QUALITY under an already-resolved replacement intent
- no intent/routing label was changed anywhere (rt0013's routing freeze,
see tests/test_rt0013_closure.py, is untouched: 10/10 still passing).

1. Gluten-free is the one dietary constraint the V2.16b catalog audit
   proved reliable (0 confirmed mistags via product_type's "Bezlepkove
   potraviny" breadcrumb). Before this fix, "bez lepku" / gluten-free
   language in a replacement query had ZERO effect on candidates -
   "sojova omacka" and "sojova omacka bez lepku" returned byte-identical
   lists, with a non-gluten-free product ranked #1 either way. Vegan/
   vegetarian are deliberately NOT filtered - that catalog mapping was
   proven unreliable and removed in V2.16b (a real chicken product was
   tagged "vegan").

2. detect_already_have_subject()'s ALREADY_HAVE_MARKERS used bare
   substring containment ("mam " in text), which also matches inside
   "nemam " (I do NOT have) - the opposite meaning. "Nemam mirin,
   potrebujem nahradu bez lepku." (I don't have mirin, I need a
   gluten-free substitute) was silently classified as
   already_have_subject="mirin" and routed to
   complement_products_for_subject() (a "goes well with what you have"
   cross-sell) - replacement_subject was never even reached. Root-caused
   live during this sprint's characterization.

3. detect_special_product_subject() is checked ahead of replacement_
   subject in _chat_impl()'s dispatch cascade and wins for 3 of 13
   REPLACEMENT_SUBJECT_ALIASES entries (fish sauce, rice vinegar, sushi
   rice - see docs/routing-debt.md V2.16c correction note), so an
   explicit gluten-free replacement request for one of those 3 silently
   bypassed the fix in (1) entirely. The intent label itself (incl.
   rt0013) is unchanged - only which function supplies candidates when
   gluten-free language is also present. The curated SPECIAL_PRODUCT_
   QUERIES bundles these subjects draw from are general-purpose (e.g.
   "gluten_free_sushi" = soy sauce + nori + rice + wasabi + ginger
   together), not subject-specific substitute lists, so a
   replacement_subject_matches_product() relevance sanity check is also
   applied - without it, "sushi ryza bez lepku" returned gluten-free soy
   sauce (reproduced live), which does not substitute for rice at all.
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


def _titles(r: dict) -> list[str]:
    return [str(p.get("title") or "") for p in (r.get("products") or [])]


class TestGlutenFreeFilterAlternativeProductsPath:
    """detect_replacement_subject() -> alternative_products_for_subject()
    - the primary, non-shadowed path (soy sauce is not one of the 3
    special_subject-shadowed aliases)."""

    def test_unconstrained_query_is_not_all_gluten_free(self):
        r = _chat("Cim nahradim sojovu omacku?", "v216c-gf-unconstrained")
        assert r.get("intent") == "replacement_products"
        assert any(p for p in (r.get("products") or []) if not m.product_is_gluten_free(p)), (
            "unconstrained query should not accidentally already be all-gluten-free "
            "(otherwise the constrained test below cannot prove the filter did anything)"
        )

    def test_gluten_free_query_returns_only_gluten_free_candidates(self):
        r = _chat("Potrebujem nahradu za sojovu omacku bez lepku.", "v216c-gf-constrained")
        assert r.get("intent") == "replacement_products"
        products = r.get("products") or []
        assert products, "expected real gluten-free soy sauce candidates in the catalog"
        assert all(m.product_is_gluten_free(p) for p in products)

    def test_gluten_free_query_differs_from_unconstrained(self):
        unconstrained = _chat("Cim nahradim sojovu omacku?", "v216c-gf-diff-a")
        constrained = _chat("Potrebujem nahradu za sojovu omacku bez lepku.", "v216c-gf-diff-b")
        ids_unconstrained = sorted(p.get("id") for p in (unconstrained.get("products") or []))
        ids_constrained = sorted(p.get("id") for p in (constrained.get("products") or []))
        assert ids_unconstrained != ids_constrained


class TestAlreadyHaveSubjectNegationFix:
    """detect_already_have_subject() must not fire on the negated "nemam"
    (I don't have) - only the genuine "mam"/"kupil som"/"vlastnim"
    (I have / I bought / I own) forms."""

    def test_negated_form_does_not_match(self):
        assert m.detect_already_have_subject("Nemam mirin, potrebujem nahradu bez lepku.") is None

    def test_positive_form_still_matches(self):
        assert m.detect_already_have_subject("Mam doma kimchi, co dalsie by sa hodilo?") == "kimchi"

    def test_positive_form_with_uz_still_matches(self):
        assert m.detect_already_have_subject("Uz mam sojovu omacku, co dalsie by sa hodilo?") == "sojova_omacka"

    def test_negated_replacement_query_reaches_replacement_products(self):
        r = _chat("Nemam mirin, potrebujem nahradu bez lepku.", "v216c-negation-live")
        assert r.get("intent") == "replacement_products"
        products = r.get("products") or []
        assert products
        assert all(m.product_is_gluten_free(p) for p in products)
        assert all("mirin" in title.lower() for title in _titles({"products": products}))

    def test_legitimate_already_have_query_still_gets_complement_products(self):
        r = _chat("Mam doma kimchi, co dalsie by sa hodilo?", "v216c-negation-control")
        assert r.get("intent") == "related_products"


class TestSpecialSubjectShadowGlutenFreeFix:
    """The 3 REPLACEMENT_SUBJECT_ALIASES entries detect_special_product_
    subject() pre-empts (fish sauce, rice vinegar, sushi rice) must also
    honor explicit gluten-free language, and must not leak off-topic
    candidates from the special_subject curated bundle."""

    def test_fish_sauce_gluten_free_returns_real_fish_sauce(self):
        r = _chat("Cim nahradim rybaciu omacku, potrebujem bezlepkovu verziu.", "v216c-shadow-fish")
        assert r.get("intent") == "replacement_products"
        products = r.get("products") or []
        assert products
        assert all(m.product_is_gluten_free(p) for p in products)
        assert all("rybacia om" in title.lower() or "rybacia om" in m.normalize(title) for title in _titles({"products": products}))

    def test_sushi_rice_gluten_free_returns_real_rice_not_soy_sauce(self):
        r = _chat("Nahrada za sushi ryzu, potrebujem bezlepkovu.", "v216c-shadow-sushi")
        assert r.get("intent") == "replacement_products"
        products = r.get("products") or []
        assert products
        assert all(m.product_is_gluten_free(p) for p in products)
        for p in products:
            assert "sojov" not in m.normalize(str(p.get("title") or "")), (
                "gluten-free soy sauce is not a sushi-rice substitute - "
                "the special_subject curated bundle leaking it was the bug this closes"
            )


class TestRt0013UnaffectedByV216c:
    """rt0013's locked message carries no gluten-free language, so none
    of this sprint's changes should touch it - the routing freeze (see
    tests/test_rt0013_closure.py) covers intent; this covers candidates."""

    def test_candidate_set_unchanged(self):
        r = _chat("nahrada za rybiu omacku vegan", "v216c-rt0013-control")
        assert r.get("intent") == "replacement_products"
        titles = " | ".join(t.lower() for t in _titles(r))
        assert "sójová omáčka" in titles or "sojova omacka" in m.normalize(titles)


class TestVeganVegetarianDeliberatelyNotFiltered:
    """V2.16b proved product_type-derived vegan/vegetarian signals
    unreliable (a real chicken product was tagged "vegan"). V2.16c must
    not silently add vegan/vegetarian filtering to the replacement path -
    only the empirically-clean gluten_free signal is used."""

    def test_no_product_is_vegan_helper_was_added(self):
        assert not hasattr(m, "product_is_vegan")
        assert not hasattr(m, "product_is_vegetarian")
