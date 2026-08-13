"""
tests/test_intent.py  -  V2.1 CustomerIntent foundation

Pokryva app/intent.py:
- PRIMARY_INTENTS je stabilny, ocakavany zoznam
- LEGACY_INTENT_MAP pokryva kazdy legacy intent string, ktory app/main.py
  skutocne produkuje v /chat odpovedi (missing_composition, allergen_safety,
  faq, recipe, recipe_to_products, unknown, article_products,
  replacement_products, product_advice, related_products, product_search)
- map_legacy_intent() je bezpecny (neznamy/prazdny vstup -> product_search)
- build_customer_intent() spravne prenasa uz vypocitane signaly bez ich
  znovu-odvodzovania (compatibility adapter, nie nova NLU vrstva)
- CustomerIntent mutable defaulty (listy) nie su zdielane medzi instanciami

Nevyzaduje OPENAI_API_KEY ani fastapi/pydantic - app/intent.py je cisty
Python bez externych zavislosti.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.intent import (
    PRIMARY_INTENTS,
    LEGACY_INTENT_MAP,
    CustomerIntent,
    build_customer_intent,
    map_legacy_intent,
)


# Every legacy intent string app/main.py's chat() actually assigns to the
# response "intent" field (grep-verified against app/main.py). If a new
# legacy intent is introduced there without updating LEGACY_INTENT_MAP,
# this test must be extended too - it is the contract test for the
# compatibility adapter.
KNOWN_LEGACY_INTENTS_IN_MAIN = (
    "missing_composition",
    "allergen_safety",
    "faq",
    "recipe",
    "recipe_to_products",
    "unknown",
    "article_products",
    "replacement_products",
    "product_advice",
    "related_products",
    "product_search",
)


class TestPrimaryIntents:
    def test_expected_canonical_intents(self):
        assert set(PRIMARY_INTENTS) == {
            "product_search",
            "product_advice",
            "product_comparison",
            "category_discovery",
            "recipe_only",
            "recipe_to_products",
            "replacement",
            "cross_sell",
            "product_information",
            "allergen_safety",
            "faq",
            "availability_or_price",
            "conversation_followup",
            "general_culinary",
            "out_of_domain",
        }

    def test_no_duplicates(self):
        assert len(PRIMARY_INTENTS) == len(set(PRIMARY_INTENTS))


class TestLegacyIntentMap:
    def test_covers_every_legacy_intent_used_in_main(self):
        for legacy in KNOWN_LEGACY_INTENTS_IN_MAIN:
            assert legacy in LEGACY_INTENT_MAP, f"missing mapping for legacy intent {legacy!r}"

    def test_every_mapped_value_is_a_valid_primary_intent(self):
        for legacy, canonical in LEGACY_INTENT_MAP.items():
            assert canonical in PRIMARY_INTENTS, f"{legacy!r} maps to invalid {canonical!r}"

    @pytest.mark.parametrize("legacy,expected", [
        ("missing_composition", "faq"),
        ("allergen_safety", "allergen_safety"),
        ("faq", "faq"),
        ("recipe", "recipe_only"),
        ("recipe_to_products", "recipe_to_products"),
        ("unknown", "out_of_domain"),
        ("article_products", "product_information"),
        ("replacement_products", "replacement"),
        ("product_advice", "product_advice"),
        ("related_products", "cross_sell"),
        ("product_search", "product_search"),
    ])
    def test_specific_mappings(self, legacy, expected):
        assert map_legacy_intent(legacy) == expected


class TestMapLegacyIntent:
    def test_unknown_falls_back_to_product_search(self):
        assert map_legacy_intent("some_future_intent_nobody_mapped_yet") == "product_search"

    def test_empty_and_none_fall_back_to_product_search(self):
        assert map_legacy_intent("") == "product_search"
        assert map_legacy_intent(None) == "product_search"


class TestCustomerIntentDataclass:
    def test_defaults(self):
        ci = CustomerIntent()
        assert ci.primary_intent == "product_search"
        assert ci.subject is None
        assert ci.dietary_constraints == []
        assert ci.allergen_constraints == []
        assert ci.customer_has == []
        assert ci.language == "sk"
        assert ci.original_message == ""

    def test_mutable_defaults_not_shared_between_instances(self):
        a = CustomerIntent()
        b = CustomerIntent()
        a.allergen_constraints.append("lepok")
        assert b.allergen_constraints == []

    def test_invalid_primary_intent_is_corrected(self):
        ci = CustomerIntent(primary_intent="not_a_real_intent")
        assert ci.primary_intent == "product_search"

    def test_valid_primary_intent_is_kept(self):
        ci = CustomerIntent(primary_intent="cross_sell")
        assert ci.primary_intent == "cross_sell"


class TestBuildCustomerIntent:
    def test_basic_product_search(self):
        ci = build_customer_intent("mate ryzu?", "product_search", language="sk")
        assert ci.primary_intent == "product_search"
        assert ci.original_message == "mate ryzu?"
        assert ci.language == "sk"
        assert ci.legacy_intent == "product_search"
        assert ci.confidence == pytest.approx(0.9)

    def test_cross_sell_from_related_products(self):
        ci = build_customer_intent(
            "co este potrebujem k sushi", "related_products",
            subject="sushi", language="sk",
        )
        assert ci.primary_intent == "cross_sell"
        assert ci.subject == "sushi"

    def test_replacement_from_replacement_products(self):
        ci = build_customer_intent(
            "cim nahradim sojovu omacku", "replacement_products",
            subject="sojova_omacka",
        )
        assert ci.primary_intent == "replacement"
        assert ci.subject == "sojova_omacka"

    def test_allergen_safety_carries_allergen_constraints(self):
        ci = build_customer_intent(
            "ma to lepok?", "allergen_safety",
            allergen_constraints=["lepok"],
        )
        assert ci.primary_intent == "allergen_safety"
        assert ci.allergen_constraints == ["lepok"]

    def test_recipe_to_products_carries_recipe_and_use_case(self):
        ci = build_customer_intent(
            "co potrebujem na tom kha gai", "recipe_to_products",
            subject="tom_kha", recipe="tom_kha", use_case="tom_kha",
        )
        assert ci.primary_intent == "recipe_to_products"
        assert ci.recipe == "tom_kha"
        assert ci.requested_output == "shopping_list"

    def test_unmapped_legacy_intent_has_low_confidence(self):
        ci = build_customer_intent("hmm", "totally_unknown_legacy_value")
        assert ci.primary_intent == "product_search"
        assert ci.confidence == pytest.approx(0.4)

    def test_requested_output_defaults_per_primary_intent(self):
        assert build_customer_intent("x", "faq").requested_output == "answer"
        assert build_customer_intent("x", "allergen_safety").requested_output == "answer"
        assert build_customer_intent("x", "recipe").requested_output == "recipe"
        assert build_customer_intent("x", "product_search").requested_output == "products"

    def test_does_not_mutate_shared_default_lists_across_calls(self):
        ci1 = build_customer_intent("x", "allergen_safety", allergen_constraints=["lepok"])
        ci2 = build_customer_intent("y", "product_search")
        ci1.allergen_constraints.append("orechy")
        assert ci2.allergen_constraints == []
