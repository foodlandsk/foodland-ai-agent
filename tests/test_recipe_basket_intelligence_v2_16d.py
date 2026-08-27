"""
tests/test_recipe_basket_intelligence_v2_16d.py  -  V2.16d recipe/basket
intelligence closure.

V2.16d characterized the "co potrebujem na X" / "co este potrebujem?"
customer journey against actual HEAD before implementing anything
(Section 12 of the sprint spec) and found 3 real, live-reproduced gaps,
all fixed here with the smallest safe change - no new module, no
duplicated role-resolution logic, no fabricated quantity/serving/
completeness claims:

1. app.use_case_advice.decide_use_case_advice() could be hijacked by a
   self-declared inventory + basket request for the same use case
   ("Mam ryzove rezance a rybaciu omacku. Co este potrebujem na pho?"),
   answering as if RECOMMENDING the self-declared item instead of
   deferring to app.basket_completion's already-have-aware answer.
   Before this fix, protection against this exact collision depended
   entirely on incidental sentence punctuation immediately after the
   self-declared marker breaking resolve_role()'s literal
   trailing-space requirement (see that function's V2.14f docstring) -
   reliable only when the self-declared item happened to be followed by
   punctuation, not a space+conjunction. Fixed with an explicit,
   deterministic guard reusing app.basket_completion's own action-
   language detector.

2. app.basket_completion._self_declared_concept_ids() only ever
   extracted ONE concept per message (parse_structured_query() on the
   whole message), undercounting genuine multi-item declarations
   ("Mam ryzove rezance a rybaciu omacku..."). Fixed by parsing each
   punctuation/"a"-delimited segment separately and unioning matches -
   a strict improvement, the existing single-item regression
   (tests/test_basket_completion_v2_14e.py::TestCaseG_AlreadyCoveredRole)
   is unaffected.

3. app.basket_completion had NO session continuity at all - every
   follow-up after its first answer ("Co este potrebujem?", a further
   self-declared item) fell straight through to a generic "I don't
   understand" answer, confirmed live. Fixed by mirroring the existing
   app.recipe_shopping/app.session_state active-recipe pattern exactly:
   a new active_basket_use_case session field
   (app.session_state.get/set/clear_active_basket_use_case) + a new
   app.basket_completion.resolve_basket_followup() tried first in
   app.workflow_executor.execute_basket_completion() whenever a basket
   use case is already active, falling back to the original fresh-turn
   decide_basket_completion() path unchanged otherwise (zero behavior
   change for a session's first basket-related turn). A turn that does
   NOT continue the active basket (hard switch, unrelated aside) clears
   the state immediately - the same "not recognized -> drop it" policy
   app.main's own recipe-followup precedence already uses for
   active_recipe_id.

Deliberately NOT implemented this sprint (documented gaps, not fixed -
see docs/recipe-basket-intelligence-v2.16d.md): "cheaper alternative"/
"is this basket complete?" follow-ups (no per-role "last discussed"
tracking exists for basket_completion, unlike recipe_shopping's
last_recipe_ingredient_concept), serving/quantity scaling (no
Foodland recipe carries a structured quantity - a pre-existing,
re-confirmed data limitation, not something this sprint can fabricate),
bulk add-to-cart (no real cart-mutation seam exists to test against
safely).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m
import app.basket_completion as bc


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, limit: int = 8) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


class TestUseCaseAdviceDoesNotHijackBasketRequest:
    """Fix 1 - a self-declared inventory + basket request for a
    BASKET_V1_ELIGIBLE_USE_CASES use case must reach basket_completion,
    never a single-role use_case_advice RECOMMEND."""

    def test_two_item_declaration_reaches_basket_completion(self):
        r = _chat("Mam ryzove rezance a rybaciu omacku. Co este potrebujem na pho?", "v216d-t1")
        assert r.get("intent") == "basket_completion"

    def test_self_declared_role_marked_already_covered(self):
        r = _chat("Mam ryzove rezance a rybaciu omacku. Co este potrebujem na pho?", "v216d-t1b")
        statuses = {role["concept_id"]: role["status"] for role in r["basket_roles"]}
        assert statuses["rice_noodles"] == "ALREADY_COVERED"

    def test_bare_role_question_still_answered_by_use_case_advice(self):
        # Control: a genuine single-role question with NO basket-action
        # language must be completely unaffected by the new guard.
        r = _chat("aku ryzu na sushi?", "v216d-t1c")
        assert r.get("intent") == "use_case_advice"


class TestMultiItemSelfDeclaration:
    """Fix 2 - direct unit coverage of the segment-split extraction."""

    def test_two_resolvable_items_both_extracted(self):
        required = ["fish_sauce", "rice_noodles", "hoisin_sauce", "sriracha_sauce"]
        found = bc._self_declared_concept_ids(
            "Mam ryzove rezance a hoisin. Co este potrebujem na pho?", required,
        )
        assert found == {"rice_noodles", "hoisin_sauce"}

    def test_existing_single_item_regression_unaffected(self):
        required = ["fish_sauce", "rice_noodles"]
        found = bc._self_declared_concept_ids("mam ryzove rezance, co este potrebujem na pad thai?", required)
        assert found == {"rice_noodles"}

    def test_no_declaration_returns_empty(self):
        required = ["fish_sauce", "rice_noodles"]
        assert bc._self_declared_concept_ids("co potrebujem na pho?", required) == set()


class TestBasketFollowupContinuity:
    """Fix 3 - the core "co este potrebujem?" target."""

    def test_what_else_followup_after_pho(self):
        first = _chat("Co potrebujem na pho?", "v216d-t3a")
        assert first.get("intent") == "basket_completion"
        second = _chat("Co este potrebujem?", "v216d-t3a")
        assert second.get("intent") == "basket_completion"
        assert second.get("basket_use_case") == "pho"

    def test_what_else_followup_after_sushi(self):
        _chat("Co potrebujem na sushi?", "v216d-t3b")
        second = _chat("Co este potrebujem?", "v216d-t3b")
        assert second.get("intent") == "basket_completion"
        assert second.get("basket_use_case") == "sushi"

    def test_followup_without_prior_basket_falls_through(self):
        r = _chat("Co este potrebujem?", "v216d-t3c")
        assert r.get("intent") != "basket_completion"

    def test_hard_switch_to_different_use_case(self):
        _chat("Co potrebujem na pho?", "v216d-t3d")
        r = _chat("Co potrebujem na sushi?", "v216d-t3d")
        assert r.get("intent") == "basket_completion"
        assert r.get("basket_use_case") == "sushi"

    def test_informational_aside_answers_correctly_and_basket_still_resumes(self):
        # FAQ/allergen-safety run at a HIGHER precedence tier than
        # basket_completion (same tier ordering as the pre-existing
        # app.recipe_shopping mechanism - verified directly: pad_thai's
        # active_recipe_id shows the identical characteristic), so this
        # executor never runs for an FAQ-intercepted turn and cannot
        # clear state for it either. A benign informational aside is
        # correctly answered on its own terms and the basket resumes
        # afterward - consistent with, not a regression from, the
        # established recipe_shopping precedent.
        _chat("Co potrebujem na pho?", "v216d-t3e")
        r = _chat("Kde mate predajnu?", "v216d-t3e")
        assert r.get("intent") == "faq"
        r2 = _chat("Co este potrebujem?", "v216d-t3e")
        assert r2.get("intent") == "basket_completion"
        assert r2.get("basket_use_case") == "pho"

    def test_hard_switch_to_product_search(self):
        _chat("Co potrebujem na pho?", "v216d-t3f")
        r = _chat("Ukaz mi Kikkoman.", "v216d-t3f")
        assert r.get("intent") == "product_search"


class TestBasketStateResetAndIsolation:
    def test_reset_clears_basket_state(self):
        _chat("Co potrebujem na pho?", "v216d-t4a")
        _chat("Zacnime odznova", "v216d-t4a")
        r = _chat("Co este potrebujem?", "v216d-t4a")
        assert r.get("intent") != "basket_completion"

    def test_cross_session_isolation(self):
        _chat("Co potrebujem na pho?", "v216d-t4b-A")
        r = _chat("Co este potrebujem?", "v216d-t4b-B")
        assert r.get("intent") != "basket_completion"


class TestPermanentRegressionControls:
    """rt0004/rt0010/rt0011/rt0013 and V2.14 use-case controls must be
    completely unaffected by this sprint's changes."""

    def test_rt0004_related_products(self):
        r = _chat("suvisiace produkty k sushi ryzi", "v216d-reg-rt0004")
        assert r.get("intent") == "related_products"

    def test_rt0010_allergen_safety(self):
        r = _chat("sojova omacka bez soje", "v216d-reg-rt0010")
        assert r.get("intent") == "allergen_safety"

    def test_rt0013_replacement_unaffected(self):
        r = _chat("nahrada za rybiu omacku vegan", "v216d-reg-rt0013")
        assert r.get("intent") == "replacement_products"

    def test_vegan_noodles_regression(self):
        r = _chat("veganske rezance", "v216d-reg-vegan")
        titles = " | ".join((p.get("title") or "").lower() for p in (r.get("products") or []))
        assert "kurac" not in titles and "chicken" not in titles
