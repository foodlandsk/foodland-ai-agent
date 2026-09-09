"""
tests/test_v221_scorer.py  -  V2.21a scorer unit + self-integrity tests.

Every fixture in this file is a hand-authored FAKE dict shaped like an
app.evaluation.adapter.make_chat_fn() result. Nothing here imports or
calls app.main / app.advisor_engine / app.evaluation.adapter, or any
other Advisor-execution path (Section 43 - "Do not call Advisor").
"""
from __future__ import annotations

from app.intelligence_diagnostics.v221_scorer import (
    ERROR,
    FAIL,
    PASS,
    score_invariant,
    score_scenario,
)


def _result(**kwargs) -> dict:
    base = {"intent": None, "answer": "", "products": [], "cross_sell": []}
    base.update(kwargs)
    return base


# --------------------------------------------------------------------
# intent_is
# --------------------------------------------------------------------


class TestIntentIs:
    def test_pass_exact_match(self):
        r = score_invariant("intent_is:product_search", _result(intent="product_search"))
        assert r.state == PASS

    def test_pass_one_of_alternatives(self):
        r = score_invariant("intent_is:faq|out_of_domain", _result(intent="faq"))
        assert r.state == PASS

    def test_fail_wrong_intent(self):
        r = score_invariant("intent_is:product_search", _result(intent="faq"))
        assert r.state == FAIL
        assert "faq" in r.observed


# --------------------------------------------------------------------
# products_nonempty / products_empty
# --------------------------------------------------------------------


class TestProductsNonempty:
    def test_pass(self):
        r = score_invariant("products_nonempty", _result(products=[{"id": "FL_1"}]))
        assert r.state == PASS

    def test_fail(self):
        r = score_invariant("products_nonempty", _result(products=[]))
        assert r.state == FAIL


class TestProductsEmpty:
    def test_pass(self):
        r = score_invariant("products_empty", _result(products=[]))
        assert r.state == PASS

    def test_fail(self):
        r = score_invariant("products_empty", _result(products=[{"id": "FL_1"}]))
        assert r.state == FAIL


# --------------------------------------------------------------------
# answer_nonempty / answer_contains_semantic_concept
# --------------------------------------------------------------------


class TestAnswerNonempty:
    def test_pass(self):
        r = score_invariant("answer_nonempty", _result(answer="Mame 3 produkty."))
        assert r.state == PASS

    def test_fail_blank(self):
        r = score_invariant("answer_nonempty", _result(answer="   "))
        assert r.state == FAIL


class TestAnswerContainsSemanticConcept:
    def test_pass_diacritic_fold(self):
        r = score_invariant(
            "answer_contains_semantic_concept:nemam overene",
            _result(answer="Presne udaje nemám overené, odporúčam pozrieť etiketu."),
        )
        assert r.state == PASS

    def test_pass_one_of_alternatives(self):
        r = score_invariant(
            "answer_contains_semantic_concept:dobierka|kartou",
            _result(answer="Mozete platit kartou."),
        )
        assert r.state == PASS

    def test_fail(self):
        r = score_invariant(
            "answer_contains_semantic_concept:dobierka",
            _result(answer="Mame 3 produkty na sklade."),
        )
        assert r.state == FAIL


# --------------------------------------------------------------------
# product_family / expected_group_membership
# --------------------------------------------------------------------


class TestProductFamily:
    def test_pass(self):
        r = score_invariant(
            "product_family:ryza",
            _result(products=[{"id": "FL_1", "product_type": "Potraviny > Ryza > Suši ryža"}]),
        )
        assert r.state == PASS

    def test_fail(self):
        r = score_invariant(
            "product_family:ryza",
            _result(products=[{"id": "FL_1", "product_type": "Potraviny > Omacky"}]),
        )
        assert r.state == FAIL

    def test_expected_group_membership_is_aliased(self):
        r1 = score_invariant("product_family:omack", _result(products=[{"product_type": "Omacky"}]))
        r2 = score_invariant("expected_group_membership:omack", _result(products=[{"product_type": "Omacky"}]))
        assert r1.state == r2.state == PASS


# --------------------------------------------------------------------
# product_title_contains_any / product_title_forbidden
# --------------------------------------------------------------------


class TestProductTitleContainsAny:
    def test_pass(self):
        r = score_invariant(
            "product_title_contains_any:tamari|sojova omacka",
            _result(products=[{"title": "Tamari sójová omáčka 250ml"}]),
        )
        assert r.state == PASS

    def test_fail(self):
        r = score_invariant(
            "product_title_contains_any:tamari",
            _result(products=[{"title": "Rybacia omacka"}]),
        )
        assert r.state == FAIL


class TestProductTitleForbidden:
    def test_pass_when_absent(self):
        r = score_invariant(
            "product_title_forbidden:sriracha",
            _result(products=[{"title": "Kikkoman sojova omacka"}]),
        )
        assert r.state == PASS

    def test_fail_when_present(self):
        r = score_invariant(
            "product_title_forbidden:sriracha",
            _result(products=[{"title": "Sriracha chilli omacka"}]),
        )
        assert r.state == FAIL


# --------------------------------------------------------------------
# product_brand / forbidden_brand
# --------------------------------------------------------------------


class TestProductBrand:
    def test_pass(self):
        r = score_invariant("product_brand:kikkoman", _result(products=[{"brand": "Kikkoman"}]))
        assert r.state == PASS

    def test_fail(self):
        r = score_invariant("product_brand:kikkoman", _result(products=[{"brand": "Megachef"}]))
        assert r.state == FAIL


class TestForbiddenBrand:
    def test_pass_when_absent(self):
        r = score_invariant("forbidden_brand:aroy-d", _result(products=[{"brand": "Megachef"}]))
        assert r.state == PASS

    def test_fail_when_present(self):
        r = score_invariant("forbidden_brand:aroy-d", _result(products=[{"brand": "Aroy-D"}]))
        assert r.state == FAIL


# --------------------------------------------------------------------
# cross_sell_nonempty / cross_sell_separate (Section 44)
# --------------------------------------------------------------------


class TestCrossSellNonempty:
    def test_pass(self):
        r = score_invariant("cross_sell_nonempty", _result(cross_sell=[{"id": "FL_2"}]))
        assert r.state == PASS

    def test_fail(self):
        r = score_invariant("cross_sell_nonempty", _result(cross_sell=[]))
        assert r.state == FAIL


class TestCrossSellSeparate:
    """Section 44 - explicitly prove primary and cross_sell IDs are
    evaluated separately, and that overlap is caught."""

    def test_pass_disjoint_sets(self):
        r = score_invariant(
            "cross_sell_separate",
            _result(products=[{"id": "FL_1"}, {"id": "FL_2"}], cross_sell=[{"id": "FL_3"}]),
        )
        assert r.state == PASS

    def test_fail_on_overlap(self):
        r = score_invariant(
            "cross_sell_separate",
            _result(products=[{"id": "FL_1"}, {"id": "FL_2"}], cross_sell=[{"id": "FL_2"}, {"id": "FL_3"}]),
        )
        assert r.state == FAIL
        assert "FL_2" in r.observed

    def test_pass_when_both_empty(self):
        r = score_invariant("cross_sell_separate", _result(products=[], cross_sell=[]))
        assert r.state == PASS


# --------------------------------------------------------------------
# requires_uncertainty (Section 45)
# --------------------------------------------------------------------


class TestRequiresUncertainty:
    def test_pass_valid_hedge_sk(self):
        r = score_invariant(
            "requires_uncertainty",
            _result(answer="Pri alergii na sezam vam nechcem odporucit produkt len podla nazvu. Overte zlozenie."),
        )
        assert r.state == PASS

    def test_pass_valid_hedge_en(self):
        r = score_invariant(
            "requires_uncertainty",
            _result(answer="I don't have verified nutrition data for this product, please check the label."),
        )
        assert r.state == PASS

    def test_fail_invalid_certainty(self):
        r = score_invariant(
            "requires_uncertainty",
            _result(answer="Tento produkt ma presne 120 kalorii na 100g."),
        )
        assert r.state == FAIL


# --------------------------------------------------------------------
# no_stock_certainty_claim (Section 45)
# --------------------------------------------------------------------


class TestNoStockCertaintyClaim:
    def test_pass_valid_no_claim(self):
        r = score_invariant(
            "no_stock_certainty_claim",
            _result(answer="Na vyber je osobny odber alebo doruceni kurierom."),
        )
        assert r.state == PASS

    def test_fail_invalid_certainty(self):
        r = score_invariant(
            "no_stock_certainty_claim",
            _result(answer="Tento produkt je urcite skladom."),
        )
        assert r.state == FAIL


# --------------------------------------------------------------------
# no_allergen_certainty_without_evidence (Section 46)
# --------------------------------------------------------------------


class TestNoAllergenCertaintyWithoutEvidence:
    def test_pass_hedged(self):
        r = score_invariant(
            "no_allergen_certainty_without_evidence",
            _result(answer="Odporucam overit zlozenie priamo na etikete produktu."),
        )
        assert r.state == PASS

    def test_fail_unjustified_certainty(self):
        r = score_invariant(
            "no_allergen_certainty_without_evidence",
            _result(answer="Tento produkt urcite neobsahuje lepok."),
        )
        assert r.state == FAIL


# --------------------------------------------------------------------
# Unknown invariant -> ERROR (Section 38/87)
# --------------------------------------------------------------------


class TestUnknownInvariant:
    def test_unknown_type_is_error(self):
        r = score_invariant("totally_made_up_invariant", _result())
        assert r.state == ERROR

    def test_unknown_type_with_arg_is_error(self):
        r = score_invariant("totally_made_up_invariant:foo", _result())
        assert r.state == ERROR


# --------------------------------------------------------------------
# Malformed input self-integrity (Section 84/87)
# --------------------------------------------------------------------


class TestMalformedInputSelfIntegrity:
    def test_result_not_a_dict_is_error_not_pass_or_silent_fail(self):
        r = score_invariant("products_nonempty", None)  # type: ignore[arg-type]
        assert r.state == ERROR

    def test_result_missing_products_key_fails_cleanly_not_crash(self):
        r = score_invariant("products_nonempty", {})
        assert r.state == FAIL

    def test_products_containing_non_dict_items_does_not_crash(self):
        r = score_invariant("product_title_contains_any:foo", {"products": ["not-a-dict", 42, None]})
        assert r.state == FAIL

    def test_error_is_never_silently_pass(self):
        r = score_invariant("nonexistent_invariant_xyz", _result(products=[{"id": "FL_1"}]))
        assert r.state != PASS
        assert r.state == ERROR

    def test_error_is_never_silently_ordinary_fail(self):
        # ERROR and FAIL are distinguishable states, not collapsed into one.
        r_error = score_invariant("nonexistent_invariant_xyz", _result())
        r_fail = score_invariant("products_nonempty", _result(products=[]))
        assert r_error.state == ERROR
        assert r_fail.state == FAIL
        assert r_error.state != r_fail.state


# --------------------------------------------------------------------
# score_scenario aggregation (Section 39/87)
# --------------------------------------------------------------------


class TestScoreScenario:
    def test_all_pass_is_pass(self):
        s = score_scenario(
            "v221_fake_0001",
            ("intent_is:product_search", "products_nonempty"),
            _result(intent="product_search", products=[{"id": "FL_1"}]),
        )
        assert s.state == PASS
        assert s.failed == ()
        assert s.errored == ()

    def test_one_fail_makes_scenario_fail(self):
        s = score_scenario(
            "v221_fake_0002",
            ("intent_is:product_search", "products_nonempty"),
            _result(intent="faq", products=[{"id": "FL_1"}]),
        )
        assert s.state == FAIL
        assert len(s.failed) == 1

    def test_one_error_makes_scenario_error_even_if_others_pass(self):
        s = score_scenario(
            "v221_fake_0003",
            ("products_nonempty", "not_a_real_invariant"),
            _result(products=[{"id": "FL_1"}]),
        )
        assert s.state == ERROR
        assert len(s.errored) == 1

    def test_error_takes_precedence_over_fail_in_reported_state(self):
        s = score_scenario(
            "v221_fake_0004",
            ("products_nonempty", "not_a_real_invariant"),
            _result(products=[]),
        )
        assert s.failed  # products_nonempty genuinely failed
        assert s.errored  # unknown invariant genuinely errored
        assert s.state == ERROR  # ERROR is reported distinctly, not silently collapsed to FAIL

    def test_empty_invariants_is_pass_by_vacuous_truth(self):
        s = score_scenario("v221_fake_0005", (), _result())
        assert s.state == PASS
        assert s.invariant_results == ()
