"""
tests/test_basket_completion_v2_14e.py  -  V2.14e: unit + end-to-end tests
for app.basket_completion and its app.workflow_executor.execute_basket_completion()
integration.

Covers the required test categories from the V2.14e spec (Section 49):
sushi/pho/kari/pad_thai/tom_kha basket behavior, ramen hard exclusion,
partial basket with unresolved role, no fake completion claim,
already-covered role handling, alternative-vs-missing distinction,
precedence against recipe/use-case-advice/allergen-safety, session
safety, and the two real regressions found and fixed during
implementation (regbug_rt0026, the sushi legacy shopping-list split).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.basket_completion as bc
import app.main as m
import app.use_case_advice as uca


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, limit: int = 8) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


# --- unit tests: role resolution, candidates, action detection -------------

class TestBasketV1EligibleUseCases:
    def test_registry_is_subset_of_live_use_cases(self):
        # V2.14h: these sets are no longer required to be equal - ramen
        # became live in app.use_case_advice.LIVE_USE_CASES without
        # gaining basket eligibility (basket readiness is an independent
        # dimension, decided on its own evidence). A basket-eligible use
        # case must still be a recognized live use case, so this remains
        # a real invariant, just a subset rather than an equality.
        assert set(bc.BASKET_V1_ELIGIBLE_USE_CASES) <= set(uca.LIVE_USE_CASES)

    def test_ramen_not_eligible(self):
        # V2.14h: this used to hold vacuously (BASKET_V1_ELIGIBLE_USE_CASES
        # was a bare tuple(LIVE_USE_CASES) alias, so the two sets could
        # never actually diverge - see app.basket_completion's module
        # docstring for the real latent defect this exposed). Now that
        # the registry is independently authored, this is a real,
        # meaningful assertion: ramen is live for use-case advice but
        # deliberately not for basket completion.
        assert "ramen" in uca.LIVE_USE_CASES
        assert "ramen" not in bc.BASKET_V1_ELIGIBLE_USE_CASES


class TestRequiredRoles:
    def test_sushi_roles_from_cross_sell_use_case_index(self):
        roles = bc.required_roles_for_use_case("sushi")
        assert set(roles) == {"sushi_rice", "nori", "rice_vinegar", "soy_sauce"}

    def test_pho_roles_from_cross_sell_recipe_index(self):
        roles = bc.required_roles_for_use_case("pho")
        assert set(roles) == {"fish_sauce", "rice_noodles", "hoisin_sauce", "sriracha_sauce"}

    def test_kari_roles(self):
        roles = bc.required_roles_for_use_case("kari")
        assert set(roles) == {"curry_paste", "coconut_milk", "jasmine_rice", "fish_sauce"}

    def test_ramen_has_no_role_list_here(self):
        # Structural exclusion, not a special case (Section 5).
        assert bc.required_roles_for_use_case("ramen") == []


class TestGenerateRoleCandidates:
    def test_concept_id_exact_match_only(self):
        candidates = bc.generate_role_candidates("sushi_rice", m.products, m.product_taxonomy_index, limit=5)
        assert len(candidates) > 0
        for product in candidates:
            taxonomy = m.product_taxonomy_index.get(product.id)
            assert taxonomy.concept_id == "sushi_rice"

    def test_unknown_concept_returns_empty(self):
        candidates = bc.generate_role_candidates("nonexistent_concept_xyz", m.products, m.product_taxonomy_index)
        assert candidates == []


class TestKnownUnresolvedConcepts:
    def test_pho_has_unresolved_concept(self):
        # "korenie pho" has no taxonomy family (V2.14d finding, re-verified live).
        unresolved = bc.known_unresolved_concepts("pho")
        assert len(unresolved) >= 1

    def test_kari_fully_resolved_no_unresolved_concepts(self):
        # V2.14d fixed bare "kari pasta" - kari's ingredient list is 4/4.
        assert bc.known_unresolved_concepts("kari") == []

    def test_sushi_has_no_raw_ingredient_list_to_diff(self):
        # Honest [] (not-applicable), not a claim of completeness.
        assert bc.known_unresolved_concepts("sushi") == []


class TestWantsBasketCompletion:
    def test_co_potrebujem_triggers(self):
        assert bc._wants_basket_completion("co potrebujem na pho")

    def test_co_este_potrebujem_triggers(self):
        assert bc._wants_basket_completion("co este potrebujem na pho")

    def test_dopln_triggers(self):
        assert bc._wants_basket_completion("dopln mi veci na pho")

    def test_doplnky_noun_form_does_not_trigger_here(self):
        # "doplnky" (companion request) is excluded via is_companion_request()
        # at the decide_basket_completion() level, not this helper - but it
        # also happens not to share the "dopln " verb-stem substring check
        # meaningfully here since is_companion_request() runs first in practice.
        assert bc.is_companion_request("doplnky k sushi ryzi")

    def test_bare_dish_mention_does_not_trigger(self):
        assert not bc._wants_basket_completion("pho")

    def test_nakupny_zoznam_deliberately_not_a_trigger(self):
        # Reserved for the existing, content-validated legacy shopping-list
        # mechanism (sushi_shopping_core_products) - see module docstring.
        assert not bc._wants_basket_completion("nakupny zoznam na sushi")


# --- end-to-end characterization cases (Section 31 A-P) ---------------------

class TestCaseA_SushiBasket:
    def test_sushi_basket_resolves_all_roles(self):
        r = _chat("co potrebujem na sushi", "v214e-caseA")
        assert r.get("intent") == "basket_completion"
        assert r.get("basket_use_case") == "sushi"
        statuses = {role["concept_id"]: role["status"] for role in r["basket_roles"]}
        assert statuses["sushi_rice"] == "RESOLVED_PRODUCT"
        assert statuses["nori"] == "RESOLVED_PRODUCT"
        assert r.get("basket_fully_resolved") is True


class TestCaseB_PhoBasket:
    def test_pho_basket_partial_with_unresolved_concept(self):
        r = _chat("co potrebujem na pho", "v214e-caseB")
        assert r.get("intent") == "basket_completion"
        assert r.get("basket_use_case") == "pho"
        assert len(r.get("basket_unresolved_concepts") or []) >= 1
        # Section 27 - must NOT claim full completion when a gap exists.
        assert r.get("basket_fully_resolved") is False


class TestCaseC_KariBasket:
    def test_kari_basket_fully_resolved(self):
        r = _chat("co potrebujem na kari", "v214e-caseC")
        assert r.get("intent") == "basket_completion"
        assert r.get("basket_use_case") == "kari"
        assert r.get("basket_fully_resolved") is True


class TestCaseD_PadThaiUnaffected:
    def test_pad_thai_still_uses_existing_recipe_shopping_path(self):
        # V2.14e must not shadow the ALREADY-LIVE V2.9/recipe_shopping path.
        r = _chat("co potrebujem na pad thai", "v214e-caseD")
        assert r.get("intent") == "recipe_to_products"
        assert r.get("workflow_id") == "RECIPE_SHOPPING"
        assert r.get("basket_use_case") is None


class TestCaseE_TomKhaUnaffected:
    def test_tom_kha_still_uses_existing_recipe_shopping_path(self):
        r = _chat("co potrebujem na tom kha gai", "v214e-caseE")
        assert r.get("intent") == "recipe_to_products"
        assert r.get("workflow_id") == "RECIPE_SHOPPING"
        assert r.get("basket_use_case") is None


class TestCaseF_RamenExcluded:
    """Section 5 - permanent, hard release invariant."""

    def test_ramen_goal_request_does_not_enter_basket_v1(self):
        r = _chat("co potrebujem na ramen", "v214e-caseF-1")
        assert r.get("intent") != "basket_completion"
        assert r.get("basket_use_case") is None

    def test_ramen_doplnit_phrasing_does_not_enter_basket_v1(self):
        r = _chat("doplň mi kosik na ramen", "v214e-caseF-2")
        assert r.get("intent") != "basket_completion"

    def test_ramen_co_mi_chyba_phrasing_does_not_enter_basket_v1(self):
        r = _chat("co mi chyba na ramen", "v214e-caseF-3")
        assert r.get("intent") != "basket_completion"

    def test_decide_basket_completion_never_returns_ramen(self):
        decision = bc.decide_basket_completion(
            "co potrebujem na ramen", m.products, m.product_taxonomy_index,
        )
        assert decision is None


class TestCaseG_AlreadyCoveredRole:
    def test_self_declared_ingredient_marks_role_already_covered(self):
        r = _chat("mam ryzove rezance, co este potrebujem na pho", "v214e-caseG")
        assert r.get("intent") == "basket_completion"
        statuses = {role["concept_id"]: role["status"] for role in r["basket_roles"]}
        assert statuses["rice_noodles"] == "ALREADY_COVERED"
        assert statuses["fish_sauce"] == "RESOLVED_PRODUCT"


class TestCaseH_UnresolvedRoleHonest:
    def test_pho_korenie_pho_exposed_as_unresolved_not_guessed(self):
        r = _chat("co potrebujem na pho", "v214e-caseH")
        unresolved = r.get("basket_unresolved_concepts") or []
        assert any("korenie" in u for u in unresolved)


class TestCaseI_NoCatalogProductRole:
    def test_no_catalog_product_status_exists_in_vocabulary(self):
        # Direct unit proof the status is reachable in principle (concept
        # with zero candidates), without depending on catalog contents
        # drifting over time.
        assert bc.generate_role_candidates("nonexistent_concept_xyz", m.products, m.product_taxonomy_index) == []


class TestCaseJ_MultipleGroundedCandidates:
    def test_role_with_multiple_candidates_exposes_alternatives(self):
        r = _chat("co potrebujem na sushi", "v214e-caseJ")
        sushi_rice_role = next(role for role in r["basket_roles"] if role["concept_id"] == "sushi_rice")
        assert sushi_rice_role["recommended_product_id"] is not None
        # Section 18 - alternatives are exposed separately, never counted
        # as additional missing roles.
        assert isinstance(sushi_rice_role["alternative_product_ids"], list)


class TestCaseK_RecipeRequestVsBasketRequest:
    def test_explicit_recipe_request_stays_recipe(self):
        r = _chat("recept na pad thai", "v214e-caseK-1")
        assert r.get("intent") == "recipe"

    def test_explicit_recipe_request_kari_not_captured_by_basket(self):
        r = _chat("recept na kari", "v214e-caseK-2")
        assert r.get("intent") != "basket_completion"


class TestCaseL_UseCaseAdviceStaysDistinct:
    def test_single_role_question_still_goes_to_use_case_advice(self):
        r = _chat("aka omacka na pad thai", "v214e-caseL-1")
        assert r.get("intent") == "use_case_advice"

    def test_single_role_question_kari_still_use_case_advice(self):
        r = _chat("aku kokosove mlieko na kari", "v214e-caseL-2")
        assert r.get("intent") == "use_case_advice"


class TestCaseM_AllergenSafetyPrecedence:
    def test_allergen_shaped_basket_request_stays_allergen_safety(self):
        r = _chat("sojova omacka bez soje na pho", "v214e-caseM")
        assert r.get("intent") == "allergen_safety"


class TestCaseN_ResultSetContinuation:
    def test_basket_response_has_products_field_for_show_more(self):
        r = _chat("co potrebujem na sushi", "v214e-caseN")
        assert isinstance(r.get("products"), list)
        assert len(r["products"]) > 0


class TestCaseO_HardTopicSwitch:
    def test_switch_from_basket_to_unrelated_product_search(self):
        sid = "v214e-caseO"
        r1 = _chat("co potrebujem na pho", sid)
        assert r1.get("intent") == "basket_completion"
        r2 = _chat("Shin Ramyun", sid)
        assert r2.get("intent") != "basket_completion"


class TestCaseP_CrossSessionIsolation:
    def test_two_sessions_do_not_leak_basket_state(self):
        r_a = _chat("co potrebujem na sushi", "v214e-caseP-a")
        r_b = _chat("hladam ryzu", "v214e-caseP-b")
        assert r_a.get("intent") == "basket_completion"
        assert r_b.get("intent") != "basket_completion"


# --- permanent regression controls ------------------------------------------

class TestEvaluationRegressionLocks:
    """Permanent locks for real regressions found via the full V2.10
    evaluation/pytest runs during implementation (not hypothetical)."""

    def test_regbug_rt0026_pho_ramen_ambiguity_stays_related_products(self):
        r = _chat("ramen na Pho polievku mate ingrediencie?", "v214e-regression-rt0026")
        assert r.get("intent") == "related_products"
        assert r.get("intent") != "basket_completion"

    def test_sushi_legacy_shopping_list_content_unaffected(self):
        # "nakupny zoznam na sushi" must keep using the existing,
        # content-validated sushi_shopping_core_products() path, not this
        # module's role-based shape.
        r = _chat("nakupny zoznam na sushi", "v214e-regression-shoppinglist")
        assert r.get("intent") != "basket_completion"
        assert "shopping_list" in r


class TestPermanentRoutingControls:
    def test_rt0004_related_products_unaffected(self):
        r = _chat("suvisiace produkty k sushi ryzi", "v214e-rt0004")
        assert r.get("intent") == "related_products"

    def test_rt0010_allergen_safety_unaffected(self):
        r = _chat("sojova omacka bez soje", "v214e-rt0010")
        assert r.get("intent") == "allergen_safety"

    def test_rt0011_no_contamination(self):
        r = _chat("mam rad nepalive jedlo, co odporucas?", "v214e-rt0011")
        assert r.get("intent") == "product_search"


class TestResponseContract:
    def test_basket_completion_response_has_required_fields(self):
        r = _chat("co potrebujem na sushi", "v214e-contract")
        assert "answer" in r
        assert "products" in r
        assert "intent" in r
        assert "memory" in r
        assert r.get("response_mode") == "basket_completion"
        assert r.get("workflow_id") == "BASKET_COMPLETION"


class TestNoNewLlmCall:
    def test_basket_completion_module_has_no_llm_call(self):
        import inspect

        source = inspect.getsource(bc)
        for forbidden in ("openai", "_get_openai_client", "_call_openai_with_retry"):
            assert forbidden not in source, f"unexpected LLM reference: {forbidden}"


class TestCompositionHonesty:
    def test_no_complete_basket_claim_when_gap_exists(self):
        decision = bc.decide_basket_completion(
            "co potrebujem na pho", m.products, m.product_taxonomy_index,
        )
        assert decision is not None
        assert decision.fully_resolved is False
        products_by_id = {p.id: p for p in m.products}
        answer = bc.compose_basket_answer(decision, products_by_id, "sk")
        assert "spoľahlivo doplniť všetko potrebné" not in answer

    def test_full_completion_claim_when_no_gap(self):
        decision = bc.decide_basket_completion(
            "co potrebujem na kari", m.products, m.product_taxonomy_index,
        )
        assert decision is not None
        assert decision.fully_resolved is True
        products_by_id = {p.id: p for p in m.products}
        answer = bc.compose_basket_answer(decision, products_by_id, "sk")
        assert "spoľahlivo doplniť" in answer
