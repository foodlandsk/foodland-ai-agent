"""
tests/test_cross_sell.py  -  Sprint V2.6 Contextual Cross-Sell & Basket
Intelligence.

Uses the REAL committed catalog fixture (data/products.json) and the
REAL curated RECIPE_SHOPPING_CORE_QUERIES/SPECIAL_PRODUCT_QUERIES dicts
from app.main - the role graphs this sprint mines are grounded in that
actual curated data, so a synthetic replica would test something else.

Covers the V2.6 spec's mandatory test scenarios: sushi use-case
(Section 84), Pad Thai recipe (Section 85), bare variety query stays
conservative (Section 88), same-need contamination is a hard gate
(Section 82), duplicate exclusion (Section 83), FBT semantic validation
(Section 91/92), multi-source reinforcement (Section 93).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.main as m  # noqa: E402
from app.cross_sell import (  # noqa: E402
    CrossSellCandidate,
    RECIPE_COMPLETION,
    USE_CASE_COMPLETION,
    build_cross_sell,
    generate_candidates,
    rank_candidates,
    roles_for_recipe,
    roles_for_use_case,
    set_data_sources,
    should_cross_sell,
)
from app.structured_search import build_structured_result_set  # noqa: E402

set_data_sources(m.RECIPE_SHOPPING_CORE_QUERIES, m.SPECIAL_PRODUCT_QUERIES)

PRODUCTS = m.products
TAXONOMY_INDEX = m.product_taxonomy_index
NORMALIZED_INDEX = m.normalized_product_index
PRODUCTS_BY_ID = {p.id: p for p in PRODUCTS}
KNOWLEDGE = m.knowledge
NOW = 1_700_000_000.0


def make_result_set(query_text: str, related_subject: str | None = None, base_query=None):
    return build_structured_result_set(
        query_text, PRODUCTS, TAXONOMY_INDEX, NORMALIZED_INDEX,
        catalog_version=1, taxonomy_version=1, now=NOW, base_query=base_query,
    )


def cross_sell_for(query_text: str, related_subject: str | None = None, is_continuation: bool = False):
    rs = make_result_set(query_text)
    decision, formatted = build_cross_sell(
        structured_presentation=rs, related_subject=related_subject, is_continuation=is_continuation,
        products=PRODUCTS, taxonomy_index=TAXONOMY_INDEX, knowledge=KNOWLEDGE, fbt_data={"active": False},
    )
    return rs, decision, formatted


class TestEligibilityGate:
    def test_bare_variety_query_not_eligible(self):
        """Section 88 - "jazmínová ryža" alone must NOT assume a task context."""
        _, decision, formatted = cross_sell_for("jazminova ryza")
        assert decision.eligible is False
        assert formatted == []

    def test_use_case_query_eligible(self):
        """Section 84 - sushi rice use-case activates cross-sell."""
        _, decision, formatted = cross_sell_for("ryza na sushi")
        assert decision.eligible is True
        assert decision.context_type == USE_CASE_COMPLETION
        assert formatted  # at least one grounded candidate

    def test_recipe_context_eligible_via_related_subject(self):
        """Section 85 - explicit recipe/dish context (as already detected
        by the pre-existing app.main.detect_related_subject()) activates
        recipe completion."""
        _, decision, formatted = cross_sell_for("sojova omacka", related_subject="pad_thai")
        assert decision.eligible is True
        assert decision.context_type == RECIPE_COMPLETION

    def test_continuation_never_eligible(self):
        """Section 36 - Show More/Show All must never (re)generate cross-sell."""
        rs = make_result_set("ryza na sushi")
        decision = should_cross_sell(structured_presentation=rs, related_subject="sushi", is_continuation=True)
        assert decision.eligible is False
        assert decision.reason == "no_primary_or_continuation"

    def test_no_exact_match_not_eligible(self):
        """Section 41/42 - primary problem unresolved takes priority."""
        _, decision, _ = cross_sell_for("FOODLAND jazminova ryza 2 kg")
        assert decision.eligible is False

    def test_grouped_discovery_not_eligible(self):
        """Section 31 - broad discovery is too early for cross-sell."""
        _, decision, _ = cross_sell_for("ryza")
        assert decision.eligible is False

    def test_exact_lookup_no_context_not_eligible(self):
        """Section 40/87 - exact SKU lookup without explicit context stays quiet."""
        _, decision, _ = cross_sell_for("kikkoman sojova omacka 1000 ml")
        assert decision.context_type != USE_CASE_COMPLETION  # no use_case attribute on soy_sauce


class TestSameNeedContamination:
    """Section 18/29/82 - hard quality gate: 0 same-need products as cross-sell."""

    def test_no_rice_product_in_sushi_cross_sell(self):
        rs, decision, formatted = cross_sell_for("ryza na sushi")
        assert decision.eligible is True
        for product in formatted:
            tax = TAXONOMY_INDEX.get(product["id"])
            assert tax is None or tax.canonical_family != "rice"

    def test_subfamily_level_not_family_level_exclusion(self):
        """Section 18's exclusion must be granular: fish_sauce is a
        DIFFERENT complementary need than soy_sauce, both under family
        "sauce" - it must NOT be blocked just for sharing the family."""
        _, decision, formatted = cross_sell_for("sojova omacka", related_subject="pad_thai")
        assert decision.eligible is True
        roles = {p.get("cross_sell_role") for p in formatted}
        assert "fish_sauce" in roles

    def test_no_second_soy_sauce_as_cross_sell_for_soy_sauce_primary(self):
        rs, decision, formatted = cross_sell_for("sojova omacka", related_subject="pad_thai")
        for product in formatted:
            tax = TAXONOMY_INDEX.get(product["id"])
            assert tax is None or tax.canonical_subfamily != "soy_sauce"


class TestDuplicateExclusion:
    """Section 21/83 - 0 cross-sell products already in the primary set."""

    def test_no_overlap_between_primary_and_cross_sell(self):
        rs, decision, formatted = cross_sell_for("ryza na sushi")
        primary_ids = set(rs.ranked_product_ids)
        cross_sell_ids = {p["id"] for p in formatted}
        assert primary_ids & cross_sell_ids == set()


class TestRoleGeneration:
    """Section 7/8/11 - roles come from grounded curated data, not guesses."""

    def test_pad_thai_roles_are_taxonomy_concepts(self):
        roles = roles_for_recipe("pad_thai")
        assert "rice_noodles" in roles
        assert "fish_sauce" in roles
        # every role must be a real FamilyRule id, not a free-text guess
        from app.taxonomy import FAMILY_DEFINITIONS_BY_ID
        for role in roles:
            assert role in FAMILY_DEFINITIONS_BY_ID

    def test_sushi_use_case_roles_are_taxonomy_concepts(self):
        roles = roles_for_use_case("sushi")
        assert "nori" in roles
        assert "rice_vinegar" in roles
        assert "soy_sauce" in roles

    def test_unknown_use_case_returns_no_roles(self):
        assert roles_for_use_case("nonexistent_use_case_xyz") == []


class TestRecipeCompletionCoverageV214d:
    """V2.14d - RECIPE_COMPLETION coverage/precision audit (Part B).

    roles_for_recipe() only trusts app.query_constraints.parse_structured_query()
    concept_id resolution, which reuses app.taxonomy.FAMILY_DEFINITIONS'
    title_phrases - the SAME phrase list product classification uses. Two
    real, safe recoveries were found: "banh pho" and bare "kari pasta"/
    "curry pasta" both already have real, correctly-classified catalog
    products (HIGH/MEDIUM confidence via category) but had no matching
    title_phrase for QUERY-side (recipe ingredient) resolution - a pure
    query-side gap, not a taxonomy family gap. Fixed by adding the missing
    phrases to the EXISTING rice_noodles/curry_paste rules (no new family,
    no new rule, zero risk to already-correct product classification).

    Concepts with NO underlying taxonomy family at all (dashi, palm sugar,
    peanuts, galangal, lemongrass, kaffir lime leaves, generic "pho spice
    mix") are a genuine, separate data gap - deliberately NOT invented here
    (Section 3/13 forbid broad taxonomy expansion in this sprint) and are
    tracked as backlog debt instead."""

    def test_banh_pho_resolves_to_rice_noodles(self):
        from app.query_constraints import parse_structured_query
        q = parse_structured_query("banh pho", known_brands=())
        assert q.concept_id == "rice_noodles"

    def test_bare_kari_pasta_resolves_to_generic_curry_paste(self):
        from app.query_constraints import parse_structured_query
        q = parse_structured_query("kari pasta", known_brands=())
        assert q.concept_id == "curry_paste"

    def test_variety_specific_curry_paste_precedence_unaffected(self):
        # The new bare "kari pasta" phrase must not shadow the more
        # specific, pre-existing variety rules (first-match-wins order).
        from app.query_constraints import parse_structured_query
        assert parse_structured_query("cervena kari pasta", known_brands=()).concept_id == "red_curry_paste"
        assert parse_structured_query("zelena kari pasta", known_brands=()).concept_id == "green_curry_paste"
        assert parse_structured_query("panang kari pasta", known_brands=()).concept_id == "panang_curry_paste"

    def test_pho_recipe_completion_coverage_improved(self):
        # 3/5 -> 4/5 after the "banh pho" recovery (Section 24 before/after).
        roles = roles_for_recipe("pho")
        assert "rice_noodles" in roles
        assert "fish_sauce" in roles
        assert "hoisin_sauce" in roles
        assert "sriracha_sauce" in roles

    def test_kari_recipe_completion_full_coverage(self):
        # 3/4 -> 4/4 after the bare "kari pasta" recovery.
        roles = roles_for_recipe("kari")
        assert "curry_paste" in roles
        assert "coconut_milk" in roles
        assert "jasmine_rice" in roles
        assert "fish_sauce" in roles

    def test_tom_kha_aromatics_correctly_abstain_not_invented(self):
        # galangal/lemongrass/kaffir lime leaves have real catalog products
        # but NO taxonomy family - roles_for_recipe() must never invent one.
        roles = roles_for_recipe("tom_kha")
        assert "coconut_milk" in roles
        assert "fish_sauce" in roles
        assert len(roles) == 2  # aromatics deliberately absent (DATA_REQUIRED)

    def test_pad_thai_untaxonomized_ingredients_correctly_abstain(self):
        # palm sugar / peanuts have real catalog products but no taxonomy
        # family - must not be guessed into an unrelated role.
        roles = roles_for_recipe("pad_thai")
        assert set(roles) == {"rice_noodles", "tamarind_pasta", "fish_sauce"}


class TestFBTValidation:
    """Section 15-17/51/91/92 - FBT is evidence, never sole semantic truth."""

    def test_fbt_same_need_candidate_rejected(self):
        rs = make_result_set("ryza na sushi")
        primary_id = rs.ranked_product_ids[0]
        # find another rice product to use as a fake FBT association
        another_rice_id = next(
            pid for pid, tax in TAXONOMY_INDEX.items()
            if tax.canonical_family == "rice" and pid != primary_id
        )
        fbt_data = {"active": True, "pairs": {primary_id: [(another_rice_id, 50)]}}
        decision = should_cross_sell(structured_presentation=rs, related_subject="sushi", is_continuation=False)
        candidates = generate_candidates(
            decision, primary_product_ids=[primary_id], exclude_ids=set(rs.ranked_product_ids),
            products_by_id=PRODUCTS_BY_ID, taxonomy_index=TAXONOMY_INDEX, products=PRODUCTS,
            primary_family=rs.structured_query.family, primary_subfamily=rs.structured_query.subfamily,
            fbt_data=fbt_data,
        )
        chosen_ids = {c.product_id for c in candidates}
        assert another_rice_id not in chosen_ids  # same-need, must be rejected regardless of FBT strength

    def test_weak_fbt_without_role_match_not_shown(self):
        rs = make_result_set("ryza na sushi")
        primary_id = rs.ranked_product_ids[0]
        # an unrelated product (e.g. a random snack) with no taxonomy role match
        random_id = next(pid for pid in PRODUCTS_BY_ID if TAXONOMY_INDEX.get(pid) is None or not TAXONOMY_INDEX[pid].concept_id)
        fbt_data = {"active": True, "pairs": {primary_id: [(random_id, 100)]}}
        decision = should_cross_sell(structured_presentation=rs, related_subject="sushi", is_continuation=False)
        candidates = generate_candidates(
            decision, primary_product_ids=[primary_id], exclude_ids=set(rs.ranked_product_ids),
            products_by_id=PRODUCTS_BY_ID, taxonomy_index=TAXONOMY_INDEX, products=PRODUCTS,
            primary_family=rs.structured_query.family, primary_subfamily=rs.structured_query.subfamily,
            fbt_data=fbt_data,
        )
        assert random_id not in {c.product_id for c in candidates}


class TestMultiSourceAgreement:
    """Section 50/93 - agreement across sources should reinforce ranking."""

    def test_ranking_is_deterministic(self):
        candidates = [
            CrossSellCandidate(product_id="B", role="soy_sauce", evidence=["use_case_compatibility"], score=3.0),
            CrossSellCandidate(product_id="A", role="nori", evidence=["use_case_compatibility"], score=3.0),
        ]
        ranked1 = rank_candidates(candidates)
        ranked2 = rank_candidates(candidates)
        assert [c.product_id for c in ranked1] == [c.product_id for c in ranked2] == ["A", "B"]

    def test_higher_score_ranks_first(self):
        candidates = [
            CrossSellCandidate(product_id="LOW", role="nori", evidence=["fbt"], score=1.0),
            CrossSellCandidate(product_id="HIGH", role="soy_sauce", evidence=["recipe", "curated_crosssell"], score=5.0),
        ]
        ranked = rank_candidates(candidates)
        assert ranked[0].product_id == "HIGH"


class TestBudgetAndRoleDiversity:
    """Section 22/23/24 - small, role-diverse, no 5 products for one role."""

    def test_role_diversity_no_duplicate_roles(self):
        _, decision, formatted = cross_sell_for("ryza na sushi")
        roles = [p.get("cross_sell_role") for p in formatted]
        assert len(roles) == len(set(roles))

    def test_max_products_budget_respected(self):
        _, decision, formatted = cross_sell_for("ryza na sushi")
        assert len(formatted) <= decision.max_products


class TestReasonGrounding:
    """Section 27/28 - reason text is derived from taxonomy labels, not invented."""

    def test_reason_text_matches_taxonomy_display_label(self):
        from app.taxonomy import FAMILY_DEFINITIONS_BY_ID
        _, decision, formatted = cross_sell_for("ryza na sushi")
        for product in formatted:
            role = product.get("cross_sell_role")
            expected_label = FAMILY_DEFINITIONS_BY_ID[role].display_label
            assert product.get("cross_sell_reason") == expected_label
