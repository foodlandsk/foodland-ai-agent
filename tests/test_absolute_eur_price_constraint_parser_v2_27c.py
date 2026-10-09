"""
tests/test_absolute_eur_price_constraint_parser_v2_27c.py  -  V2.27c:
absolute EUR price constraint parser.

Context (V2.27a-c read-only architecture/contract review series,
docs/query-semantics.md): V2.26d closed budget_0001's ROUTING debt
(related_subject -> product_search), but nothing makes returned products
actually respect a stated EUR amount - that is FUTURE_PRICE_FILTERING_DEBT,
explicitly left open. V2.27a found a complete, working, inclusive-bounds
price-eligibility filter already exists (app.search.filter_products()/
_matches_price_range()) but is wired only to the standalone /products/
filter REST endpoint, never to /chat. V2.27b locked the exact parser
contract this file tests; V2.27c implements it.

This is a PARSER-ONLY test file: no /chat call, no FastAPI request, no
catalog dependency. Imports only PriceConstraint/extract_price_constraint
from app.query_constraints. The parser is NOT wired into /chat in this
sprint (that remains a separate, future, unauthorized integration sprint)
- these tests prove the pure function's contract only.

Deliberately narrower than app.main._has_budget_constraint_frame()
(V2.26d): that is a coarse ROUTING signal (bare "<digit> eur", no prefix
required - acceptable there because routing is low-stakes and already
protected by downstream guards). This parser is a future HARD ELIGIBILITY
input, so it requires an explicit accepted budget-frame word immediately
before the amount and fails open (returns None) on any ambiguity,
negation, strict/approximate language, or unsupported currency - a missed
constraint can be extended later, but a false hard constraint would
incorrectly exclude valid products (V2.27c Section AQ).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import pytest

from app.query_constraints import PriceConstraint, extract_price_constraint


class TestPositiveContract:
    """Section Y - supported absolute EUR upper-bound forms."""

    @pytest.mark.parametrize(
        "message,expected",
        [
            ("Mám 10 eur, akú rybaciu omáčku si za to môžem kúpiť?", PriceConstraint(price_max=10.0, source="mam_budget")),
            ("Mam 10 eur na rybaciu omacku.", PriceConstraint(price_max=10.0, source="mam_budget")),
            ("Mám rozpočet 5 eur na kari pastu.", PriceConstraint(price_max=5.0, source="rozpocet")),
            ("Chcem sriracha omáčku do 3 eur.", PriceConstraint(price_max=3.0, source="do")),
            ("max 10 eur", PriceConstraint(price_max=10.0, source="max")),
            ("max. 10 eur", PriceConstraint(price_max=10.0, source="max")),
            ("najviac 7 eur", PriceConstraint(price_max=7.0, source="najviac")),
        ],
    )
    def test_supported_upper_bound_forms(self, message, expected):
        assert extract_price_constraint(message) == expected

    def test_lower_bound_not_locked_by_v2_27b_returns_none(self):
        # V2.27b Section L explicitly DEFERRED "od X eur" - zero corpus
        # evidence for a genuine lower-bound budget query, and "od" is a
        # heavily overloaded Slovak preposition elsewhere (brand exclusion,
        # allergen phrasing, comparisons) in this corpus.
        assert extract_price_constraint("od 10 eur") is None

    def test_range_not_locked_by_v2_27b_returns_none(self):
        # V2.27b Section N explicitly DEFERRED range syntax - zero corpus
        # evidence and no existing range abstraction in StructuredProductQuery.
        assert extract_price_constraint("od 5 do 10 eur") is None
        assert extract_price_constraint("5 az 10 eur") is None


class TestDecimalNormalization:
    """Section AA - comma/dot decimal handling."""

    @pytest.mark.parametrize(
        "message,expected_value",
        [
            ("do 9,99 eur", 9.99),
            ("do 9.99 eur", 9.99),
            ("maximálne 12,50 eur", 12.5),
            ("maximálne 12.50 eur", 12.5),
        ],
    )
    def test_decimal_forms(self, message, expected_value):
        constraint = extract_price_constraint(message)
        assert constraint is not None
        assert constraint.price_max == expected_value


class TestCurrencySymbol:
    """Section AB - EUR/eur/€ case and symbol handling."""

    def test_uppercase_eur(self):
        assert extract_price_constraint("do 10 EUR") == PriceConstraint(price_max=10.0, source="do")

    def test_euro_sign_destroyed_by_normalize_is_handled_via_preprocessing(self):
        # app.search.normalize() silently deletes "€" (NFKD->ASCII drops
        # it with no trace, verified in V2.27b Section H) - the parser
        # must preprocess the RAW message before normalizing, not rely on
        # normalize() alone.
        assert extract_price_constraint("Chcem niečo do 9,99 €.") == PriceConstraint(price_max=9.99, source="do")

    def test_non_eur_currency_not_supported(self):
        assert extract_price_constraint("do 10 USD") is None
        assert extract_price_constraint("max 300 Kč") is None
        assert extract_price_constraint("10 usd") is None
        assert extract_price_constraint("300 czk") is None


class TestNegativeNonContractCases:
    """Section Z - the full non-interference/collision matrix."""

    @pytest.mark.parametrize(
        "message",
        [
            "niečo lacnejšie",
            "Koľko stojí jazmínová ryža Royal Umbrella 1kg?",
            "Potrebujem sriracha omáčku na 20 porcií.",
            "Koľko balení ryžového octu potrebujem na 5 litrov sushi ryže?",
            "Aké máte rybacie omáčky?",
            "Mám kimchi, čo sa k tomu hodí?",
            "Ako uvariť Ma Po Tofu?",
            "Aké sushi suroviny predávate?",
            "chcem robit sushi",
            "Chcem miso pastu na polievku.",
            "okolo 10 eur",
            "cca 10 eur",
            "asi 10 eur",
            "približne 10 eur",
            "pod 10 eur",
            "nad 10 eur",
            "menej ako 10 eur",
            "viac ako 10 eur",
        ],
    )
    def test_returns_none(self, message):
        assert extract_price_constraint(message) is None


class TestOwnershipCollision:
    """Section K/V - "mám <produkt>" must never be mistaken for a budget."""

    @pytest.mark.parametrize(
        "message",
        [
            "Mám doma kimchi, čo ešte potrebujem na Kimchi Jjigae?",
            "Mám už sriracha omáčku, čo iné mi odporúčate k rezancom?",
            "Mám kimchi, čo sa k tomu hodí?",
            "Mám sójovú omáčku.",
        ],
    )
    def test_ownership_phrases_return_none(self, message):
        assert extract_price_constraint(message) is None


class TestFalsePositiveGuards:
    """Section AC - a bare currency MENTION must never become a hard
    constraint, unlike the V2.26d routing helper's intentionally coarse
    bare "<digit> eur" signal."""

    @pytest.mark.parametrize(
        "message",
        [
            "Produkt stojí 10 eur.",
            "Cena je 10 eur.",
            "Minul som 10 eur.",
            "Ušetril som 10 eur.",
            "Doprava stojí 5 eur.",
            "Kupón má hodnotu 10 eur.",
        ],
    )
    def test_bare_currency_mention_returns_none(self, message):
        assert extract_price_constraint(message) is None


class TestMultipleValueAmbiguity:
    """Section AD - more than one competing EUR amount -> fail open."""

    @pytest.mark.parametrize(
        "message",
        [
            "do 10 eur alebo do 15 eur",
            "Mám 10 eur, možno 15 eur",
        ],
    )
    def test_ambiguous_multiple_amounts_return_none(self, message):
        assert extract_price_constraint(message) is None


class TestNegation:
    """Section S - a narrow, fixed negation-marker guard."""

    @pytest.mark.parametrize(
        "message",
        [
            "nemusí to byť do 10 eur",
            "nechcem limit 10 eur",
            "nemám rozpočet 10 eur",
            "nie do 10 eur",
        ],
    )
    def test_negated_statements_return_none(self, message):
        assert extract_price_constraint(message) is None


class TestZeroAndNegativeValues:
    """Section T - only strictly positive amounts are actionable."""

    @pytest.mark.parametrize(
        "message",
        [
            "do 0 eur",
            "do -5 eur",
            "od -1 eur",
        ],
    )
    def test_non_positive_amounts_return_none(self, message):
        assert extract_price_constraint(message) is None


class TestMultiConstraintCorpusNonInterference:
    """V2.26 multi_constraint_0003 - strict "pod" stays deferred even
    when co-occurring with an unrelated brand constraint the parser never
    inspects."""

    def test_pod_with_brand_returns_none(self):
        assert extract_price_constraint("Potrebujem rybaciu omáčku pod 5 eur, značka Megachef.") is None


class TestStructural:
    """Section AE - PriceConstraint is immutable."""

    def test_price_constraint_is_frozen(self):
        constraint = PriceConstraint(price_max=1.0)
        with pytest.raises(Exception):
            constraint.price_max = 2.0  # type: ignore[misc]

    def test_determinism(self):
        message = "Mám 10 eur, akú rybaciu omáčku si za to môžem kúpiť?"
        assert extract_price_constraint(message) == extract_price_constraint(message)
