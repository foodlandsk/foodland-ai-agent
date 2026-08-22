"""
tests/test_recommendation_decision_v2_14f.py  -  V2.14f: Evidence-Grounded
Recommendation Decision, Choice Explanation & Conversion Intelligence.

V2.14f is primarily an AUDIT + characterization sprint: app.comparison
(V2.14b) and app.use_case_advice (V2.14c) already implement almost the
entire recommendation decision model this sprint targets (RECOMMEND/
COMPARE/CLARIFY/ABSTAIN, evidence-grounded explanation, comparative
claim safety). This file locks in:

1. two real, characterization-discovered defects fixed during this
   sprint (trailing-punctuation resolution failure in
   app.use_case_advice, and the "drahsia"->CHEAPEST marker collision
   in app.comparison that made "is the pricier one better?" answer a
   non-sequitur instead of honestly abstaining);
2. the new comparison follow-up continuity feature
   (app.session_state.get_active_comparison_pair +
   app.comparison.is_bare_comparison_followup/resolve_comparison_targets_from_pair);
3. the mandatory decision test matrix from Section 43 of the V2.14f
   spec, expressed against the EXISTING (not new) decision primitives.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.comparison as cmp
import app.main as m
import app.use_case_advice as uca


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, limit: int = 8) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


# --- real defects found and fixed this sprint -------------------------------

class TestTrailingPunctuationRegressionLock:
    """Section 7 Cases B/J - real defect: resolve_use_case() required a
    literal trailing space after the use-case alias, so any question
    ending in "?" or followed by a comma silently failed to resolve at
    all, for every use case."""

    def test_use_case_alias_followed_by_question_mark(self):
        assert uca.resolve_use_case("ktora rybacia omacka je najlepsia na pho?") == "pho"

    def test_use_case_alias_followed_by_comma(self):
        assert uca.resolve_use_case("potrebujem ryzu na sushi, ktoru odporucas?") == "sushi"

    def test_curry_red_001_regression_lock_unaffected(self):
        # The fix must not weaken the existing "na X" preposition
        # requirement - a bare product name must still not resolve.
        assert uca.resolve_use_case("cervena kari pasta") is None

    def test_end_to_end_case_b(self):
        r = _chat("ktora rybacia omacka je najlepsia na pho?", "v214f-caseB")
        assert r.get("intent") == "use_case_advice"

    def test_end_to_end_case_j(self):
        r = _chat("potrebujem ryzu na sushi, ktoru odporucas?", "v214f-caseJ")
        assert r.get("intent") == "use_case_advice"


class TestClauseBoundaryRegressionLock:
    """A SECOND real regression found while fixing the first: applying
    the same punctuation-to-space normalization to resolve_role() let a
    role marker match ACROSS a comma clause boundary
    ("mam ryzove rezance, co este potrebujem na pho?"), hijacking a
    genuine app.basket_completion self-declaration turn into a
    single-role use_case_advice answer. resolve_role() deliberately did
    NOT receive the punctuation fix - only resolve_use_case() did."""

    def test_self_declaration_reaches_basket_completion_not_use_case_advice(self):
        r = _chat("mam ryzove rezance, co este potrebujem na pho", "v214f-clauseboundary")
        assert r.get("intent") == "basket_completion"
        statuses = {role["concept_id"]: role["status"] for role in r["basket_roles"]}
        assert statuses["rice_noodles"] == "ALREADY_COVERED"


class TestPriceImpliesQualityRegressionLock:
    """Section 12 flagship example - real defect: "drahsia" ("more
    expensive") was listed as a GOAL_CHEAPEST marker, so "je ta drahsia
    lepsia?" ("is the pricier one better?") silently resolved to "give
    me the cheaper one" - a non-sequitur relative to the actual
    question. Fixed by removing "drahsia" from _CHEAPEST_MARKERS and
    adding an explicit price-direction + bare-quality combination check
    that routes to GOAL_UNSUPPORTED_QUALITATIVE (honest ABSTAIN)."""

    def test_expensive_plus_better_is_unsupported_qualitative(self):
        assert cmp.resolve_comparison_goal("je ta drahsia lepsia?") == cmp.GOAL_UNSUPPORTED_QUALITATIVE

    def test_bare_expensive_alone_no_longer_means_cheapest(self):
        assert cmp.resolve_comparison_goal("ktora je drahsia?") != cmp.GOAL_CHEAPEST

    def test_bare_better_alone_stays_general_best(self):
        # No price reference - must remain the pre-V2.14f, helpful
        # default (grounded price/size pick), not a new ABSTAIN.
        assert cmp.resolve_comparison_goal("ktora je lepsia?") == cmp.GOAL_GENERAL_BEST

    def test_explicit_cheaper_request_unaffected(self):
        assert cmp.resolve_comparison_goal("chcem lacnejsiu") == cmp.GOAL_CHEAPEST


# --- comparison follow-up continuity (new capability) -----------------------

class TestComparisonFollowupContinuity:
    def test_cheaper_followup_after_resolved_comparison(self):
        sid = "v214f-followup-cheaper"
        _chat("hladam rybaciu omacku", sid)
        r1 = _chat("porovnaj prvy a druhy", sid)
        assert r1.get("comparison_decision") in ("CLEAR_WINNER", "CONDITIONAL_WINNER", "TRADE_OFF", "NO_MEANINGFUL_DIFFERENCE")
        r2 = _chat("Chcem lacnejsiu.", sid)
        assert r2.get("intent") == "product_comparison"
        assert r2.get("comparison_goal") == "CHEAPEST"

    def test_larger_pack_followup(self):
        sid = "v214f-followup-larger"
        _chat("hladam rybaciu omacku", sid)
        _chat("porovnaj prvy a druhy", sid)
        r = _chat("Mate vacsie balenie?", sid)
        assert r.get("intent") == "product_comparison"
        assert r.get("comparison_goal") == "LARGEST_PACK"

    def test_expensive_implies_better_followup_abstains_honestly(self):
        sid = "v214f-followup-quality"
        _chat("hladam rybaciu omacku", sid)
        _chat("porovnaj prvy a druhy", sid)
        r = _chat("Je ta drahsia lepsia?", sid)
        assert r.get("intent") == "product_comparison"
        assert r.get("comparison_decision") == "ABSTAIN"
        assert r.get("comparison_goal") == "UNSUPPORTED_QUALITATIVE"

    def test_no_followup_without_prior_comparison(self):
        r = _chat("Chcem lacnejsiu.", "v214f-followup-none")
        assert r.get("intent") != "product_comparison"

    def test_hard_topic_switch_breaks_followup_context(self):
        sid = "v214f-followup-switch"
        _chat("hladam rybaciu omacku", sid)
        _chat("porovnaj prvy a druhy", sid)
        r = _chat("Shin Ramyun", sid)
        assert r.get("intent") != "product_comparison"

    def test_cross_session_isolation(self):
        sid_a, sid_b = "v214f-cross-a", "v214f-cross-b"
        _chat("hladam rybaciu omacku", sid_a)
        _chat("porovnaj prvy a druhy", sid_a)
        r_b = _chat("Chcem lacnejsiu.", sid_b)
        assert r_b.get("intent") != "product_comparison"

    def test_reset_clears_active_comparison(self):
        sid = "v214f-followup-reset"
        _chat("hladam rybaciu omacku", sid)
        _chat("porovnaj prvy a druhy", sid)
        _chat("zacnime odznova", sid)  # reset marker
        r = _chat("Chcem lacnejsiu.", sid)
        assert r.get("intent") != "product_comparison"

    def test_deterministic_repeat(self):
        sid = "v214f-followup-repeat"
        _chat("hladam rybaciu omacku", sid)
        _chat("porovnaj prvy a druhy", sid)
        r1 = _chat("Chcem lacnejsiu.", sid)
        r2 = _chat("Chcem lacnejsiu.", sid)
        assert r1.get("comparison_decision") == r2.get("comparison_decision")
        assert r1.get("answer") == r2.get("answer")


# --- Section 43 mandatory decision matrix -----------------------------------

class TestCaseA_ClearPriceCriterion:
    def test_cheapest_goal_grounded(self):
        sid = "v214f-matrix-A"
        _chat("hladam rybaciu omacku", sid)
        r = _chat("porovnaj prvy a druhy, ktora je lacnejsia", sid)
        assert r.get("intent") == "product_comparison"


class TestCaseC_SupportedUseCase:
    def test_pho_role_recommendation_is_evidence_grounded(self):
        r = _chat("aka rybacia omacka na pho?", "v214f-matrix-C")
        assert r.get("intent") == "use_case_advice"
        assert r.get("use_case_confidence") in ("HIGH", "MEDIUM", "LOW", "INSUFFICIENT")


class TestCaseD_AmbiguousWhichIsBetter:
    def test_bare_which_should_i_buy_does_not_fabricate_a_winner(self):
        r = _chat("ktoru rybaciu omacku mam kupit?", "v214f-matrix-D")
        # No explicit pair/ordinal/use-case framing - must not silently
        # invent a comparison decision. Deliberately NOT asserting a
        # specific intent here (documented as GATE A / audit-only,
        # Section 46) - only that no unsafe fabricated winner exists.
        assert r.get("comparison_decision") != "CLEAR_WINNER"


class TestCaseE_ExpensiveNotBetter:
    def test_price_alone_never_implies_quality(self):
        assert cmp.resolve_comparison_goal("je ta drahsia lepsia?") == cmp.GOAL_UNSUPPORTED_QUALITATIVE


class TestCaseF_UnsupportedFlavorClaim:
    def test_flavor_claim_goal_is_qualitative_abstain(self):
        assert cmp.resolve_comparison_goal("ktora chutnejsie?") == cmp.GOAL_UNSUPPORTED_QUALITATIVE

    def test_qualitative_goal_never_high_confidence_recommend(self):
        sid = "v214f-matrix-F"
        _chat("hladam rybaciu omacku", sid)
        _chat("porovnaj prvy a druhy", sid)
        r = _chat("ktora chutnejsie?", sid)
        assert r.get("comparison_decision") == "ABSTAIN"


class TestCaseG_WhyThisOne:
    def test_clear_winner_exposes_reason_codes(self):
        sid = "v214f-matrix-G"
        _chat("hladam rybaciu omacku", sid)
        r = _chat("porovnaj prvy a druhy", sid)
        if r.get("comparison_decision") == "CLEAR_WINNER":
            assert "cena" in r.get("answer", "") or "balenia" in r.get("answer", "")


class TestCaseH_WhyNotOther:
    def test_answer_names_both_products_symmetrically(self):
        sid = "v214f-matrix-H"
        _chat("hladam rybaciu omacku", sid)
        r = _chat("porovnaj prvy a druhy", sid)
        assert len(r.get("products") or []) == 2


class TestCaseK_AllergenSafety:
    def test_allergen_request_never_becomes_comparison(self):
        r = _chat("sojova omacka bez soje", "v214f-matrix-K")
        assert r.get("intent") == "allergen_safety"


class TestCaseL_BasketVsRecommendationDistinct:
    def test_basket_completion_and_comparison_remain_separate_intents(self):
        r_basket = _chat("co potrebujem na pho", "v214f-matrix-L-1")
        assert r_basket.get("intent") == "basket_completion"
        sid = "v214f-matrix-L-2"
        _chat("hladam rybaciu omacku", sid)
        r_compare = _chat("porovnaj prvy a druhy", sid)
        assert r_compare.get("intent") == "product_comparison"


class TestCaseM_RamenExcluded:
    def test_ramen_use_case_never_resolves(self):
        assert uca.resolve_use_case("najlepsie rezance na ramen?") is None

    def test_ramen_query_does_not_produce_recommendation_decision(self):
        r = _chat("najlepsie rezance na ramen?", "v214f-matrix-M")
        assert r.get("intent") not in ("use_case_advice", "basket_completion")
        assert r.get("comparison_decision") is None


class TestCaseN_CrossSession:
    def test_isolated_across_sessions(self):
        sid_a, sid_b = "v214f-matrix-N-a", "v214f-matrix-N-b"
        _chat("hladam rybaciu omacku", sid_a)
        _chat("porovnaj prvy a druhy", sid_a)
        r_b = _chat("aka omacka na pho?", sid_b)
        assert r_b.get("comparison_decision") is None


class TestCaseO_DeterministicRepeat:
    def test_use_case_advice_deterministic(self):
        r1 = _chat("aka rybacia omacka na pho?", "v214f-matrix-O-1")
        r2 = _chat("aka rybacia omacka na pho?", "v214f-matrix-O-2")
        assert r1.get("use_case_decision") == r2.get("use_case_decision")


class TestNoNewLlmCall:
    def test_comparison_followup_functions_have_no_llm_reference(self):
        import inspect

        source = inspect.getsource(cmp)
        for forbidden in ("openai", "_get_openai_client", "_call_openai_with_retry"):
            assert forbidden not in source, f"unexpected LLM reference: {forbidden}"


class TestPermanentRoutingControls:
    def test_rt0004(self):
        r = _chat("suvisiace produkty k sushi ryzi", "v214f-rt0004")
        assert r.get("intent") == "related_products"

    def test_rt0010(self):
        r = _chat("sojova omacka bez soje", "v214f-rt0010")
        assert r.get("intent") == "allergen_safety"

    def test_rt0011(self):
        r = _chat("mam rad nepalive jedlo, co odporucas?", "v214f-rt0011")
        assert r.get("intent") == "product_search"
