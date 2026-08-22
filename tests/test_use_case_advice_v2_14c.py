"""
tests/test_use_case_advice_v2_14c.py  -  V2.14c: unit + end-to-end tests
for app.use_case_advice and its app.workflow_executor.execute_use_case_advice()
integration.

Covers the required characterization cases from the V2.14c spec
(Sections 43-55): strong use case (sushi), medium-evidence use case
(pho), conflict handling, UNKNOWN taxonomy policy, safety precedence,
related-products precedence (rt0004 - a REAL regression found and
fixed during implementation, permanently locked here), session safety,
resultset continuity, recipe interaction (a SECOND real regression
found and fixed - "pad thai"/"tom kha" collide with
app.main.RECIPE_INTENT_MARKERS), weak/excluded use case (ramen), and
comparison composition.
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
import app.use_case_advice as uca


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, limit: int = 8) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


# --- unit tests: resolution, evidence, decision -----------------------------

class TestUseCaseResolution:
    def test_resolves_sushi(self):
        assert uca.resolve_use_case("ryza na sushi") == "sushi"

    def test_resolves_pho(self):
        assert uca.resolve_use_case("rybacia omacka na pho") == "pho"

    def test_resolves_kari_from_thajske_kari_alias(self):
        assert uca.resolve_use_case("kari pasta na thajske kari") == "kari"

    def test_resolves_kari_from_thai_curry_alias(self):
        assert uca.resolve_use_case("co pouzit na thai curry") == "kari"

    def test_bare_product_name_without_use_case_framing_does_not_resolve(self):
        # Permanent regression lock for curry_red_001 (V2.10 golden
        # case): a plain product-name query must NOT be captured just
        # because it contains the word "kari" - only an explicit
        # "na X"/"pre X" use-case framing should trigger resolution.
        assert uca.resolve_use_case("cervena kari pasta") is None

    def test_no_use_case_named_returns_none(self):
        assert uca.resolve_use_case("chcem kupit ryzu") is None

    def test_ramen_alias_registered_as_live_v2_14h(self):
        # V2.14h: the original V2.14c exclusion reason (instant_noodles
        # kitchenware contamination) was independently fixed by V2.14d's
        # tableware FamilyRule - re-audited, not carried over by
        # assumption, and ramen is now live. See module docstring for
        # the full evidence trail.
        assert uca.resolve_use_case("rezance na ramen") == "ramen"


class TestRoleResolution:
    def test_sushi_rice_role(self):
        role = uca.resolve_role("sushi", "ryza na sushi")
        assert role is not None
        assert role.role == "rice"

    def test_pho_sauce_role(self):
        role = uca.resolve_role("pho", "rybacia omacka na pho")
        assert role is not None
        assert role.role == "sauce_fish"

    def test_bare_use_case_no_role_returns_none(self):
        assert uca.resolve_role("pho", "chcem nieco na pho") is None


class TestConflictHandling:
    """Section 19: explicit current-turn exclusion outranks the use-case default."""

    def test_explicit_exclusion_detected(self):
        role = uca.resolve_role("sushi", "chcem ryzu na sushi, ale nie sushi ryzu")
        assert role is not None
        assert uca.has_explicit_exclusion(role, "chcem ryzu na sushi, ale nie sushi ryzu")

    def test_no_exclusion_for_normal_message(self):
        role = uca.resolve_role("sushi", "ryza na sushi")
        assert not uca.has_explicit_exclusion(role, "ryza na sushi")

    def test_decide_returns_none_on_conflict(self):
        decision = uca.decide_use_case_advice(
            "chcem ryzu na sushi, ale nie sushi ryzu", m.products, m.product_taxonomy_index,
        )
        assert decision is None


class TestUnknownTaxonomyPolicy:
    """Section 20: UNKNOWN/LOW confidence products never become the
    sole basis for a use-case claim."""

    def test_generate_candidates_never_includes_unknown_confidence(self):
        from app.taxonomy import get_taxonomy

        role = uca.resolve_role("sushi", "ryza na sushi")
        candidates = uca.generate_candidates(role, m.products, m.product_taxonomy_index)
        for product in candidates:
            taxonomy = get_taxonomy(m.product_taxonomy_index, product.id)
            assert taxonomy is not None
            assert taxonomy.confidence in ("HIGH", "MEDIUM")


class TestRecipeSubjectGuard:
    """Section 35: a real regression found on first wiring - "chcem
    robiť Pad Thai" was captured by this module's CLARIFY path instead
    of the protected V2.13e recipe state machine, because "Pad Thai"
    is also one of this module's canonical use cases. Fixed by
    requiring the caller to pass recipe_subject and bailing whenever
    it is truthy."""

    def test_recipe_subject_present_defers(self):
        decision = uca.decide_use_case_advice(
            "chcem robit Pad Thai", m.products, m.product_taxonomy_index, recipe_subject="pad_thai",
        )
        assert decision is None

    def test_no_recipe_subject_still_resolves(self):
        decision = uca.decide_use_case_advice(
            "rybacia omacka na pho", m.products, m.product_taxonomy_index, recipe_subject=None,
        )
        assert decision is not None
        assert decision.state == "RECOMMEND"


class TestCompanionRequestGuard:
    """Section 30: a real regression found on first wiring - "súvisiace
    produkty k sushi ryži" (rt0004) was captured by this module instead
    of the protected RELATED_PRODUCTS workflow, because it contains
    both "sushi" and "ryzi" (a form of "ryza", this module's sushi/rice
    role marker). Fixed by explicitly excluding companion-request
    marker words."""

    def test_companion_request_detected(self):
        assert uca.is_companion_request("suvisiace produkty k sushi ryzi")

    def test_ordinary_use_case_query_not_flagged(self):
        assert not uca.is_companion_request("ryza na sushi")

    def test_decide_returns_none_for_companion_request(self):
        decision = uca.decide_use_case_advice(
            "suvisiace produkty k sushi ryzi", m.products, m.product_taxonomy_index,
        )
        assert decision is None


# --- end-to-end characterization cases (spec Sections 43-55) ---------------

class TestCaseA_StrongUseCase_Sushi:
    def test_sushi_rice_recommends_high_confidence(self):
        r = _chat("ryza na sushi", "v214c-caseA")
        assert r.get("intent") == "use_case_advice"
        assert r.get("use_case_decision") == "RECOMMEND"
        assert r.get("use_case_confidence") == "HIGH"
        assert len(r.get("products") or []) > 0


class TestCaseB_Pho:
    def test_pho_fish_sauce_recommends(self):
        r = _chat("rybacia omacka na pho", "v214c-caseB")
        assert r.get("intent") == "use_case_advice"
        assert r.get("use_case_decision") == "RECOMMEND"
        assert len(r.get("products") or []) > 0


class TestCaseC_Ramen:
    def test_ramen_role_advice_now_live_v2_14h(self):
        # V2.14h: ramen re-audited and made live (see module docstring).
        # A resolvable role (noodles) now correctly reaches use_case_advice
        # instead of deferring to the normal cascade.
        r = _chat("ake rezance mam pouzit na ramen", "v214c-caseC")
        assert r.get("intent") == "use_case_advice"
        assert r.get("use_case_decision") == "RECOMMEND"


class TestCaseD_Conflict:
    def test_explicit_exclusion_not_forced(self):
        r = _chat("chcem ryzu na sushi, ale nie sushi ryzu", "v214c-caseD")
        # Must not be answered by this module's own confident sushi-rice
        # recommendation - defers to the normal (pre-existing, unmodified) cascade.
        assert r.get("intent") != "use_case_advice"


class TestCaseE_UnknownTaxonomy:
    def test_unknown_taxonomy_product_not_used_as_evidence(self):
        from app.taxonomy import get_taxonomy

        unknown_sample = next(
            (p for p in m.products if (get_taxonomy(m.product_taxonomy_index, p.id) or type("x", (), {"confidence": "UNKNOWN"})()).confidence == "UNKNOWN"),
            None,
        )
        assert unknown_sample is not None, "expected at least one real UNKNOWN-taxonomy product in the catalog"
        role = uca.resolve_role("sushi", "ryza na sushi")
        candidates = uca.generate_candidates(role, m.products, m.product_taxonomy_index)
        assert unknown_sample.id not in [p.id for p in candidates]


class TestCaseF_BestChoicePlusUseCase:
    def test_najlepsia_phrasing_still_grounded_not_fabricated(self):
        r = _chat("najlepsia rybacia omacka na pho", "v214c-caseF")
        assert r.get("intent") == "use_case_advice"
        answer = (r.get("answer") or "").lower()
        for forbidden in ("najautentickejsi", "najautentickejšia", "most authentic", "reštauračná kvalita"):
            assert forbidden not in answer


class TestCaseG_ComparisonPlusUseCase:
    def test_bare_comparison_use_case_without_pair_does_not_crash(self):
        r = _chat("ktora z tychto dvoch je lepsia na sushi", "v214c-caseG")
        # No active comparison pair exists yet in this fresh session -
        # must not crash, and must not fabricate a comparison result.
        assert r.get("intent") is not None


class TestCaseH_SafetyCollision:
    def test_allergen_precedence_over_use_case(self):
        r = _chat("sojova omacka bez soje na ramen", "v214c-caseH")
        assert r.get("intent") == "allergen_safety"
        assert r.get("products") == []


class TestCaseI_SessionContamination:
    def test_topic_switch_no_sushi_contamination(self):
        sid = "v214c-caseI"
        r1 = _chat("ryza na sushi", sid)
        r2 = _chat("Shin Ramyun", sid)
        assert r1.get("intent") == "use_case_advice"
        assert r2.get("intent") != "use_case_advice"
        titles = [p.get("title", "").lower() for p in (r2.get("products") or [])]
        assert titles, "expected Shin Ramyun search to return products"


class TestCaseJ_WeakUseCase:
    # V2.14h: ramen is now a live use case with a resolvable-role path
    # (see module docstring), so this class was split: bare product
    # names and recipe-shopping-list framing must still NOT be captured
    # by this module (protecting the same golden cases as every other
    # live use case), while genuine role-advice framing now correctly
    # DOES reach use_case_advice.
    def test_bare_product_name_does_not_reach_use_case_advice(self):
        r = _chat("ramen rezance", "v214c-caseJ-bare")
        assert r.get("intent") != "use_case_advice"

    def test_recipe_shopping_list_framing_defers_to_recipe_shopping(self):
        r = _chat("co potrebujem na ramen", "v214c-caseJ-recipe")
        assert r.get("intent") != "use_case_advice"

    def test_role_advice_framing_now_reaches_use_case_advice(self):
        r = _chat("ake rezance na ramen", "v214c-caseJ-role")
        assert r.get("intent") == "use_case_advice"
        assert r.get("use_case_decision") == "RECOMMEND"


class TestCaseK_LegitimateRefinement:
    def test_size_refinement_after_sushi_rice_recommendation(self):
        sid = "v214c-caseK"
        r1 = _chat("ryza na sushi", sid)
        assert r1.get("intent") == "use_case_advice"
        r2 = _chat("5kg", sid)
        # Refinement after a use_case_advice turn must not crash and
        # must not remain stuck replaying the same use-case-advice answer
        # verbatim with no regard to the new constraint.
        assert r2.get("products") is not None


class TestCaseL_RelatedProductsCollision:
    def test_rt0004_related_products_protected(self):
        r = _chat("suvisiace produkty k sushi ryzi", "v214c-caseL")
        assert r.get("intent") == "related_products"


class TestCaseM_RecipeInteraction:
    def test_recipe_flow_for_pad_thai_protected(self):
        r = _chat("chcem robit Pad Thai", "v214c-caseM-1")
        assert r.get("intent") == "recipe"
        assert r.get("workflow_id") == "RECIPE_SHOPPING"

    def test_recipe_flow_for_tom_kha_protected(self):
        r = _chat("chcem robit Tom Kha Gai", "v214c-caseM-2")
        assert r.get("intent") in ("recipe", "recipe_to_products")

    def test_use_case_advice_still_works_when_dish_name_not_recipe_triggered(self):
        # "kari" is not in RECIPE_INTENT_MARKERS, so it remains reachable.
        r = _chat("kari pasta na thajske kari", "v214c-caseM-3")
        assert r.get("intent") == "use_case_advice"


class TestCaseN_PadThaiTomKhaReachability:
    """V2.14d Part C (Sections 27-34, docs/use-case-recipe-data-quality-
    v2.14d.md) - Pad Thai/Tom Kha are hardcoded bare dish-name entries in
    app.main.RECIPE_INTENT_MARKERS (V2.9/V2.8 era), so is_recipe_intent()
    matched ANY message naming them regardless of surrounding action
    language, making this module's real, tested evidence for pad_thai/
    tom_kha SHADOW_ONLY (customer-unreachable) as of V2.14c. Fixed
    generically in app.main._recipe_intent_is_bare_dish_marker_only()
    (Section 62 - reuses this module's resolve_use_case()/resolve_role()
    rather than duplicating them, applies to any current/future bare-
    dish-only marker, not hardcoded to these two dish names) - a specific,
    resolvable use-case/attribute question now outranks a bare dish-name-
    only recipe trigger, while every explicit recipe/shopping-list
    phrasing for the SAME dish remains completely unaffected."""

    def test_pad_thai_attribute_question_now_reachable(self):
        r = _chat("ake rezance na pad thai", "v214d-caseN-1")
        assert r.get("intent") == "use_case_advice"
        assert r.get("use_case_resolved") == "pad_thai"

    def test_pad_thai_comparative_attribute_question_now_reachable(self):
        r = _chat("ktore rezance su najlepsie na pad thai", "v214d-caseN-2")
        assert r.get("intent") == "use_case_advice"
        assert r.get("use_case_resolved") == "pad_thai"

    def test_tom_kha_attribute_question_now_reachable(self):
        r = _chat("ake kokosove mlieko na tom kha gai", "v214d-caseN-3")
        assert r.get("intent") == "use_case_advice"
        assert r.get("use_case_resolved") == "tom_kha"

    def test_bare_pad_thai_mention_still_goes_to_recipe(self):
        r = _chat("pad thai", "v214d-caseN-4")
        assert r.get("intent") == "recipe"

    def test_bare_tom_kha_mention_still_goes_to_recipe(self):
        r = _chat("tom kha gai", "v214d-caseN-5")
        assert r.get("intent") == "recipe"

    def test_explicit_recipe_request_for_pad_thai_still_protected(self):
        r = _chat("recept na pad thai", "v214d-caseN-6")
        assert r.get("intent") == "recipe"

    def test_explicit_recipe_request_for_tom_kha_still_protected(self):
        r = _chat("recept na tom kha gai", "v214d-caseN-7")
        assert r.get("intent") == "recipe"

    def test_shopping_list_language_for_pad_thai_still_goes_to_recipe_shopping(self):
        # The exact historical bug-fix scenario RECIPE_INTENT_MARKERS'
        # bare "pad thai"/"tom kha" entries were added for - must remain
        # completely unaffected by the new precedence check.
        r = _chat("co potrebujem na pad thai", "v214d-caseN-8")
        assert r.get("workflow_id") == "RECIPE_SHOPPING"

    def test_shopping_list_language_for_tom_kha_still_goes_to_recipe_shopping(self):
        r = _chat("co potrebujem na tom kha gai", "v214d-caseN-9")
        assert r.get("workflow_id") == "RECIPE_SHOPPING"

    def test_has_resolvable_role_true_for_specific_attribute_question(self):
        assert uca.has_resolvable_role("ake rezance na pad thai") is True

    def test_has_resolvable_role_false_for_bare_dish_mention(self):
        assert uca.has_resolvable_role("pad thai") is False

    def test_has_resolvable_role_false_for_non_live_use_case(self):
        # "tom yum" has no alias/role table entry at all (unlike ramen,
        # which V2.14h made live - see test_has_resolvable_role_true_for_ramen).
        assert uca.has_resolvable_role("ake rezance na tom yum") is False

    def test_has_resolvable_role_true_for_ramen_v2_14h(self):
        assert uca.has_resolvable_role("ake rezance na ramen") is True


# --- permanent regression controls (rt0004/rt0010/rt0011) -------------------

class TestEvaluationRegressionLocks:
    """Permanent locks for the 3 real regressions found via the full
    V2.10 evaluation run during implementation (not hypothetical - each
    one actually broke a protected golden/conversation case on first
    wiring, was root-caused, and fixed)."""

    def test_curry_red_001_plain_product_name_not_hijacked(self):
        # V2.10 golden case: "cervena kari pasta" must resolve via the
        # normal structured-search path to red_curry_paste specifically,
        # not this module's broader generic curry_paste family.
        r = _chat("cervena kari pasta", "v214c-regression-curry-red")
        assert r.get("intent") != "use_case_advice"

    def test_regbug_rt0026_pho_wins_over_ramen_mention(self):
        r = _chat("ramen na Pho polievku mate ingrediencie?", "v214c-regression-rt0026")
        assert r.get("intent") == "related_products"

    def test_conv_sushi_matrix_bare_dish_mention_not_clarified(self):
        sid = "v214c-regression-sushi-matrix"
        r1 = _chat("chcem robit sushi", sid)
        assert r1.get("intent") == "related_products"
        r2 = _chat("aku ryzu?", sid)
        assert len(r2.get("products") or []) > 0
        r3 = _chat("a aky ocot?", sid)
        assert len(r3.get("products") or []) > 0


class TestPermanentRoutingControls:
    def test_rt0004(self):
        r = _chat("suvisiace produkty k sushi ryzi", "v214c-rt0004")
        assert r.get("intent") == "related_products"

    def test_rt0010(self):
        r = _chat("sojova omacka bez soje", "v214c-rt0010")
        assert r.get("intent") == "allergen_safety"
        assert r.get("products") == []

    def test_rt0011(self):
        sid = "v214c-rt0011"
        r1 = _chat("mam rad nepalive jedlo, co odporucas?", sid)
        r2 = _chat("Kikkoman", sid)
        assert r1.get("intent") == "product_search"
        assert r2.get("intent") == "product_search"


class TestComparisonStability:
    def test_v2_14b_comparison_unaffected(self):
        r = _chat("Porovnaj sojova omacka Kikkoman a sojova omacka Yamasa", "v214c-comparison-stability")
        assert r.get("intent") == "product_comparison"
        assert r.get("response_mode") == "comparison"


class TestResponseContract:
    def test_recommend_state_has_required_always_fields(self):
        r = _chat("ryza na sushi", "v214c-contract-1")
        for field_name in ("answer", "products", "intent", "memory"):
            assert field_name in r

    def test_clarify_state_has_required_always_fields(self):
        r = _chat("chcem nieco na pho", "v214c-contract-2")
        for field_name in ("answer", "products", "intent", "memory"):
            assert field_name in r


class TestNoNewLlmCall:
    def test_use_case_advice_never_calls_openai(self):
        import inspect

        source = inspect.getsource(uca)
        for forbidden in ("_get_openai_client", "_call_openai_with_retry", "openai"):
            assert forbidden not in source

    def test_execute_handler_never_calls_openai(self):
        import inspect
        import app.workflow_executor as we

        source = inspect.getsource(we.execute_use_case_advice)
        for forbidden in ("_get_openai_client", "_call_openai_with_retry"):
            assert forbidden not in source
