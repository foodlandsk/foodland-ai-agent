"""
tests/test_rt0013_closure.py  -  rt0013 semantic closure.

regbug_rt0013 ("náhrada za rybiu omáčku vegan") sat PENDING_SEMANTIC_PRODUCT_DECISION
since V2.13b: the runtime returned replacement_products while the golden
case expected product_search, and it was genuinely unclear which side
was wrong.

The human product/business decision is now authoritative:

    ACTION     = replacement
    TARGET     = fish_sauce
    CONSTRAINT = vegan
    -> canonical workflow = replacement_products

Reproduction (before any change) showed the runtime ALREADY resolved
this correctly, via the existing, generic detect_replacement_subject()
mechanism (app/main.py) - "nahrad" as an explicit marker +
REPLACEMENT_SUBJECT_ALIASES["rybacia omacka"] containing "rybiu omacku".
No runtime code was changed for this closure - only
eval/golden/regression_bugs.json::regbug_rt0013's expected_intent
(product_search -> replacement_products) and this test file.

REPLACEMENT QUALITY is a SEPARATE, independently audited dimension from
ROUTING CORRECTNESS (Section 3 of the closure spec). Audited finding,
documented here rather than silently assumed: the word "vegan" in this
query currently does NOT act as a real, deterministic constraint - the
candidate list (curated "Alternatives" knowledge keyed only by the
"rybacia omacka" subject, via alternative_products_for_subject()) is
identical whether or not "vegan" appears in the message at all. The 4
returned products' catalog descriptions show no contradicting evidence
(no bonito/fish-derived ingredients mentioned; one is explicitly labeled
"vegetariánska"), but there is no DATA_DERIVED/structured vegan
attribute anywhere in the taxonomy backing this (consistent with V2.14a's
finding that the dietary field is 0% structured). This is a real,
disclosed REPLACEMENT_QUALITY_DATA_LIMITATION, not a routing defect -
rt0013 closes on the routing question regardless.
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


class TestRt0013PrimaryCase:
    """The exact golden-case query, permanently locked to the human
    semantic decision's canonical workflow."""

    QUERY = "náhrada za rybiu omáčku vegan"

    def test_resolves_to_replacement_products(self):
        r = _chat(self.QUERY, "rt0013-primary")
        assert r.get("intent") == "replacement_products"

    def test_returns_seasoning_alternatives_not_packaging(self):
        r = _chat(self.QUERY, "rt0013-primary-titles")
        titles = " | ".join(p.get("title", "").lower() for p in (r.get("products") or []))
        for expected in ("sójová omáčka", "tamari", "hubová vegetariánska omáčka"):
            assert expected.lower() in titles
        for forbidden in ("dressing box", "fľaštičky", "miska", "obal"):
            assert forbidden not in titles


class TestRt0013Generalization:
    """Section 17 of the closure spec: the routing decision must be
    generic (detect_replacement_subject()'s existing "nahrad" marker +
    REPLACEMENT_SUBJECT_ALIASES mechanism), not a query-specific hack -
    proven by rephrasing the same request several ways."""

    def test_reordered_constraint(self):
        r = _chat("vegan náhrada za rybiu omáčku", "rt0013-gen-reorder")
        assert r.get("intent") == "replacement_products"

    def test_cim_nahradit_phrasing(self):
        r = _chat("čím nahradiť rybiu omáčku vegan", "rt0013-gen-cim")
        assert r.get("intent") == "replacement_products"

    def test_without_vegan_constraint_still_replacement(self):
        # ACTION=replacement + TARGET=fish_sauce alone is already
        # sufficient - CONSTRAINT is additive, not required for routing.
        r = _chat("náhrada za rybiu omáčku", "rt0013-gen-no-vegan")
        assert r.get("intent") == "replacement_products"


class TestRt0013VeganConstraintHonesty:
    """Documents, rather than hides, the real replacement-quality
    limitation found during closure: "vegan" is not currently a
    deterministic filter - the candidate list is identical with or
    without it. This is a disclosed data limitation, not a routing
    defect, and must not be silently fixed by fabricating vegan
    evidence (Section 14 of the closure spec)."""

    def test_vegan_word_does_not_change_candidate_set(self):
        with_constraint = _chat("náhrada za rybiu omáčku vegan", "rt0013-honesty-with")
        without_constraint = _chat("náhrada za rybiu omáčku", "rt0013-honesty-without")
        ids_with = sorted(p.get("id") for p in (with_constraint.get("products") or []))
        ids_without = sorted(p.get("id") for p in (without_constraint.get("products") or []))
        assert ids_with == ids_without


class TestRt0013NegativeControls:
    """A plain fish-sauce product query (no replacement language) must
    remain ordinary product_search - the fix must not over-trigger."""

    def test_bare_fish_sauce_query_stays_product_search(self):
        r = _chat("rybacia omacka", "rt0013-neg-bare")
        assert r.get("intent") == "product_search"


class TestRt0013SafetyRegressionControls:
    """Section 18 of the closure spec - rt0004/rt0010/rt0011 must be
    completely unaffected, since no runtime code changed for rt0013."""

    def test_rt0004_related_products_protected(self):
        r = _chat("súvisiace produkty k sushi ryži", "rt0013-rt0004")
        assert r.get("intent") == "related_products"

    def test_rt0010_allergen_safety_protected(self):
        r = _chat("sójová omáčka bez sóje", "rt0013-rt0010")
        assert r.get("intent") == "allergen_safety"

    def test_rt0011_no_session_contamination(self):
        # Same repeated-query shape as the canonical
        # tests/test_session_contamination_v2_13b_1.py::TestRegbugRt0011PermanentRegression
        # regression - stale diet-term carry-over must not manufacture a
        # special_subject/related_subject conflict on the repeated turn.
        sid = "rt0013-rt0011"
        query = "mám rád nepálivé jedlo, čo odporúčaš?"
        first = _chat(query, sid)
        second = _chat(query, sid)
        assert first.get("intent") == "product_search"
        assert second.get("intent") == "product_search"
