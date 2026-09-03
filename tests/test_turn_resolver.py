"""
tests/test_turn_resolver.py  -  V2.13b: TurnResolver signal extraction,
tested independently from execution (Section 107). Reuses app.main's
real, already-well-gated detectors as inputs - this file does not
duplicate their logic, only verifies TurnResolver's own interpretation
of their outputs.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.main as m
from app.turn_resolver import resolve_action_target_signal, resolve_safety_signal


def _safety(query: str):
    return resolve_safety_signal(
        query,
        allergen_term=m.detect_allergen_intent(query),
        allergen_product_query_result=m.allergen_product_query(query),
        related_subject=m.detect_related_subject(query),
    )


def _action_target(query: str):
    return resolve_action_target_signal(
        query,
        special_subject=m.detect_special_product_subject(query),
        related_subject=m.detect_related_subject(query),
        has_recipe_shopping_language=m._has_recipe_shopping_language(query),
        resolves_confident_product_family=m._query_resolves_to_confident_product_family(query),
    )


class TestSafetySignalExtraction:
    def test_soy_sauce_without_soy_has_safety_intent_and_zero_product_signal(self):
        analysis = _safety("sójová omáčka bez sóje")
        assert analysis.safety_intent == "sóju"
        assert analysis.safety_zero_product_signal is True
        assert analysis.safety_has_product_evidence is False

    def test_plain_soy_sauce_has_no_safety_intent(self):
        analysis = _safety("sojova omacka")
        assert analysis.safety_intent is None

    def test_explicit_allergy_question_with_no_named_product_has_zero_product_signal(self):
        # V2.18d.3 (C2): before the fix, allergen_product_query()'s free-
        # text fallback returned the leftover message itself as a "query"
        # whenever nothing else matched, so this bare allergy statement
        # (no specific product named) incidentally produced
        # has_product_evidence=True - an artifact of that fallback's
        # fragility, not a deliberate signal (unlike the "bez sóje" case
        # above, which has an explicit, documented zero-product design).
        # Naming no product must behave the same as the explicit-zero
        # case: no product evidence.
        analysis = _safety("mam alergiu na soju")
        assert analysis.safety_intent == "sóju"
        assert analysis.safety_zero_product_signal is True
        assert analysis.safety_has_product_evidence is False


class TestActionTargetSignalExtraction:
    def test_related_products_phrase_with_anchor_is_requested(self):
        analysis = _action_target("súvisiace produkty k sushi ryži")
        assert analysis.related_products_requested is True
        assert analysis.related_products_anchor == "sushi"

    def test_bare_product_name_is_not_requested(self):
        analysis = _action_target("sushi ryza")
        assert analysis.related_products_requested is False
        assert analysis.related_products_anchor is None

    def test_bare_generic_ingredient_is_not_requested(self):
        analysis = _action_target("ryža")
        assert analysis.related_products_requested is False

    def test_companion_question_without_special_subject_is_not_arbitrated(self):
        # V2.13b regbug_rt0011 finding: this resolver's ONLY job is to
        # arbitrate a special_subject-vs-related_subject CONFLICT (the
        # evidenced rt0004 bug). Without a special_subject there is no
        # conflict to arbitrate - "co sa hodi ku gochujang?" already
        # reaches related_products correctly via the unmodified legacy
        # `elif related_subject:` cascade (see
        # tests/test_routing_regressions.py::TestRelatedProductsGenericAcrossAnchors),
        # so this resolver must stay silent (related_products_requested=False)
        # here, not just "also happen to agree". An earlier, broader
        # version of this resolver ignored special_subject entirely and
        # fired on any related_subject + action language - that let
        # contextualize_message()'s stale session diet-term injection
        # manufacture spurious related_subject/special_subject matches on
        # unrelated later turns (discovered via a real regression in
        # eval/golden regbug_rt0011, "mam rad nepalive jedlo, co
        # odporucas?" on a polluted session).
        analysis = _action_target("čo sa hodí ku gochujang?")
        assert analysis.related_products_requested is False
        assert analysis.related_products_anchor is None

    def test_related_subject_without_special_subject_conflict_is_not_arbitrated_even_with_action_language(self):
        # Directly locks in the rt0011 fix at the signal level: even when
        # the caller (app.main) passes a truthy related_subject and
        # has_recipe_shopping_language=True, the resolver must not treat
        # it as a request unless special_subject is ALSO present -
        # otherwise session-context-derived related_subject values (never
        # validated against the raw current-turn text) can hijack
        # dispatch for turns that never actually asked for related
        # products.
        analysis = resolve_action_target_signal(
            "mám rád nepálivé jedlo, čo odporúčaš? jemne pikantne",
            special_subject=None,
            related_subject="medium_spicy",
            has_recipe_shopping_language=True,
            resolves_confident_product_family=False,
        )
        assert analysis.related_products_requested is False
        assert analysis.related_products_anchor is None


class TestSignalsAreDeterministic:
    def test_same_query_produces_same_analysis(self):
        a1 = _safety("sójová omáčka bez sóje")
        a2 = _safety("sójová omáčka bez sóje")
        assert a1 == a2
