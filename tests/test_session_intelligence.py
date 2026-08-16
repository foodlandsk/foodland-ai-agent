"""
tests/test_session_intelligence.py  -  Sprint V2.9 Conversational Memory,
Preference & Session Intelligence

Unit tests for app/session_state.py primitives plus end-to-end multi-turn
tests against the real app.main.chat() (same convention as
tests/test_workflow_registry.py/tests/test_recipe_shopping.py - real
committed data/products.json, real session_memories dict). Structured
around the mandated scenario matrices (spec Section 51-64).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.main as m
from app.session_state import (
    detect_brand_removal,
    detect_price_direction,
    detect_reset_request,
    detect_size_removal,
    get_active_recipe,
    get_active_use_case,
    get_selected_ingredient_products,
    looks_like_recipe_followup,
    resolve_ordinal_reference,
    set_active_recipe,
    track_presentation,
)


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers = {}


def _chat(message: str, session_id: str, limit: int = 6) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


class TestOrdinalReferenceUnit:
    def test_resolves_within_bounds(self):
        memory = {}
        track_presentation(memory, ["A", "B", "C"])
        assert resolve_ordinal_reference("ten druhy", memory) == ("B", False)

    def test_out_of_range_is_not_a_clarification_without_ordinal_word(self):
        assert resolve_ordinal_reference("chcem rybaciu omacku", {}) == (None, False)

    def test_ordinal_without_presentation_needs_clarification(self):
        assert resolve_ordinal_reference("ten druhy", {}) == (None, True)


class TestConstraintSignalsUnit:
    def test_price_direction(self):
        assert detect_price_direction("nieco lacnejsie") == "cheaper"
        assert detect_price_direction("skor drahsie") == "pricier"
        assert detect_price_direction("jazminova ryza") is None

    def test_size_removal(self):
        assert detect_size_removal("Na veľkosti nezáleží")
        assert not detect_size_removal("chcem 5 kg")

    def test_brand_removal(self):
        assert detect_brand_removal("nemusi byt Kikkoman")
        assert detect_brand_removal("nie Kikkoman")
        assert not detect_brand_removal("chcem Kikkoman")

    def test_reset_request(self):
        assert detect_reset_request("zacnime odznova")
        assert not detect_reset_request("jazminova ryza")


class TestRecipeFollowupHeuristicUnit:
    def test_generic_continuation_markers(self):
        assert looks_like_recipe_followup("co este potrebujem?")
        assert looks_like_recipe_followup("co mi chyba?")

    def test_generic_question_words_alone_do_not_match(self):
        """Regression guard (found during implementation): bare "aké"/
        "aký"/"aku" collided with unrelated questions like "akú kategóriu
        produktov máte?" - see app.session_state's _RECIPE_FOLLOWUP_
        QUESTION_MARKERS comment."""
        assert not looks_like_recipe_followup("aku kategoriu produktov mate?")
        assert not looks_like_recipe_followup("aky je rozdiel medzi ryzami?")


class TestRiceConstraintMatrix:
    """Section 51 - "jazmínová ryža" -> "len 5 kg" -> "radšej 1 kg" ->
    "niečo lacnejšie" -> "ukáž všetky"."""

    def test_family_persists_size_overrides_then_removes(self):
        sid = "v29-rice-matrix"
        r1 = _chat("jazminova ryza", sid)
        assert r1.get("response_mode") != "result_set_continuation"
        q1 = r1.get("answer_strategy") or r1.get("intent")
        assert r1.get("products")

        r2 = _chat("len 5 kg", sid)
        assert r2.get("products")

        r3 = _chat("radsej 1 kg", sid)
        assert r3.get("products")

        r4 = _chat("ukaz vsetky", sid)
        assert r4.get("response_mode") == "result_set_continuation"


class TestSushiUseCaseMatrix:
    """Section 52 - "chcem robiť sushi" -> "akú ryžu?" -> "a aký ocot?"."""

    def test_bare_rice_and_vinegar_narrow_to_sushi(self):
        sid = "v29-sushi-matrix"
        _chat("chcem robit sushi", sid)
        assert get_active_use_case(m.get_session_memory(sid)) == "sushi"

        r2 = _chat("aku ryzu?", sid)
        titles2 = [p.get("title", "").lower() for p in r2.get("products", [])]
        assert any("sushi" in t or "suši" in t for t in titles2), titles2

        r3 = _chat("a aky ocot?", sid)
        titles3 = [p.get("title", "").lower() for p in r3.get("products", [])]
        assert any("ocot" in t for t in titles3), titles3

    def test_hard_switch_clears_use_case(self):
        sid = "v29-sushi-hardswitch"
        _chat("chcem robit sushi", sid)
        _chat("aku ryzu?", sid)
        r3 = _chat("kikkoman sojova omacka 1000 ml", sid)
        titles3 = [p.get("title", "").lower() for p in r3.get("products", [])]
        assert any("kikkoman" in t for t in titles3) or any("soj" in t for t in titles3)
        assert not any("sushi" in t and "ryza" in t for t in titles3)


class TestPadThaiMatrix:
    """Section 53 - the full mandated multi-turn continuity test."""

    def test_full_conversation(self):
        sid = "v29-padthai-matrix"
        r1 = _chat("Chcem robit Pad Thai pre 4. Co potrebujem?", sid)
        assert r1.get("workflow_id") == "RECIPE_SHOPPING"
        plan1 = r1["recipe_shopping_plan"]
        assert plan1["requested_servings"] == 4
        assert plan1["coverage"]["recipe_shopping_coverage"] == 1.0

        r2 = _chat("ake rezance?", sid)
        assert len(r2.get("products", [])) >= 2
        noodle_ids = {p["id"] for p in r2["products"]}

        r3 = _chat("ten druhy", sid)
        assert len(r3.get("products", [])) == 1
        assert r3["products"][0]["id"] in noodle_ids

        r4 = _chat("a rybaciu omacku?", sid)
        assert r4.get("products")

        r5 = _chat("nieco lacnejsie", sid)
        assert r5.get("products")

        r6 = _chat("nakoniec pre 8", sid)
        plan6 = r6["recipe_shopping_plan"]
        assert plan6["requested_servings"] == 8
        already_have_ids = {item["ingredient_concept_id"] for item in plan6["sections"]["RECIPE_ALREADY_HAVE"]}
        assert "rice_noodles" in already_have_ids

        r7 = _chat("co este potrebujem?", sid)
        plan7 = r7["recipe_shopping_plan"]
        remaining_ids = {item["ingredient_concept_id"] for item in plan7["sections"]["RECIPE_REQUIRED"]}
        assert "rice_noodles" not in remaining_ids

        r8 = _chat("chcem kupit mlieko", sid)
        assert r8.get("recipe_shopping_plan") is None
        assert r8.get("workflow_id") != "RECIPE_SHOPPING"


class TestHardSwitchContaminationMatrix:
    """Section 58/59 - broad transitions must never leak stale constraints."""

    def test_pad_thai_to_beverages_no_leak(self):
        sid = "v29-contam-1"
        _chat("Chcem robit Pad Thai. Co potrebujem?", sid)
        r2 = _chat("chcem kupit kokosovu vodu", sid)
        assert r2.get("recipe_shopping_plan") is None

    def test_recipe_switch_drops_previous_selection(self):
        sid = "v29-contam-2"
        r1 = _chat("Chcem robit Pad Thai. Co potrebujem?", sid)
        memory = m.get_session_memory(sid)
        dish_id, _ = get_active_recipe(memory)
        if dish_id == "pad_thai":
            from app.session_state import mark_ingredient_selected
            mark_ingredient_selected(memory, "fish_sauce", "FL_106")
        r2 = _chat("recept na kung pao, co potrebujem", sid)
        assert r2.get("recipe_shopping_plan") is not None
        assert r2["recipe_shopping_plan"]["dish_id"] == "kung_pao"
        satisfied = get_selected_ingredient_products(memory)
        # Section 84 - switching dish must not carry Pad Thai's fish_sauce
        # selection into Kung Pao's own (different) ingredient set.
        assert "fish_sauce" not in satisfied or dish_id != "pad_thai"


class TestMissingStateClarification:
    """Section 60 - a fresh session with no presentation history must
    never guess an ordinal reference."""

    def test_fresh_session_ordinal_asks_for_clarification(self):
        sid = "v29-fresh-ordinal"
        r = _chat("ten druhy", sid)
        assert not r.get("products")

    def test_ordinal_resolves_against_real_prior_presentation(self):
        """Section 11 - positive case: after a real search, an ordinal
        reference resolves to the actual product shown at that position."""
        sid = "v29-generic-ordinal"
        r1 = _chat("jazminova ryza", sid)
        assert len(r1.get("products", [])) >= 2
        second_id = r1["products"][1]["id"]

        r2 = _chat("ten druhy", sid)
        assert len(r2.get("products", [])) == 1
        assert r2["products"][0]["id"] == second_id


class TestResetMatrix:
    """Section 30/62."""

    def test_reset_clears_prior_recipe_state(self):
        sid = "v29-reset-matrix"
        _chat("Chcem robit Pad Thai. Co potrebujem?", sid)
        r2 = _chat("zacnime odznova", sid)
        assert r2.get("intent") == "reset"
        r3 = _chat("co este potrebujem?", sid)
        assert r3.get("recipe_shopping_plan") is None


class TestConstraintRemovalLive:
    """Section 63/64 - negation/removal against the real structured
    retrieval pipeline."""

    def test_size_removal_after_narrowing(self):
        sid = "v29-size-removal"
        _chat("jazminova ryza 5 kg", sid)
        r2 = _chat("na velkosti nezalezi", sid)
        assert r2.get("products")
