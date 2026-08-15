"""
tests/test_taxonomy.py  -  V2 catalog-first product taxonomy, rice family

Pokryva app/taxonomy.py (classify_rice_query):
- kazda podrodina rozpoznana zo skutocnych nazvov produktov z
  data/products.json (nie vymyslenych priladov), zdovodnene v
  docs/product-taxonomy-audit.md
- presne tie kolizne pripady, ktore historicky sposobili produkcne chyby
  (Sprint Z.6 v roadmape): "ryza" vs "ryzove rezance" vs "ryzovy ocot" vs
  "ryzova muka" vs "ryzovy papier" vs "ryzovar" musia klasifikovat na
  ROZDIELNE podrodiny, nie vsetky na plain_rice
- shadow-mode integrita: /chat odpoved sa NESMIE zmenit pridanim
  klasifikatora (Stage A, pozri docs/advisor-v2-architecture.md)

Nevyzaduje OPENAI_API_KEY. app/taxonomy.py je cisty Python bez externych
zavislosti okrem injektovanej normalize() funkcie.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.taxonomy import (
    RICE_SUBFAMILY_CONFIDENCE,
    TaxonomyMatch,
    ProductTaxonomy,
    FAMILY_DEFINITIONS,
    build_concept_index,
    build_taxonomy_index,
    classify_product,
    classify_rice_query,
    find_by_attributes,
    find_by_family,
    get_taxonomy,
    taxonomy_coverage,
)
from app.feed import Product
from app.search import normalize


class TestRiceSubfamilyClassification:
    @pytest.mark.parametrize("query,expected_subfamily", [
        ("mate basmati ryzu?", "plain_rice"),
        ("aku ryzu mate", "plain_rice"),
        ("hladam jazminovu ryzu", "plain_rice"),
        ("aky je rozdiel medzi jazminovou a basmati ryzou?", "plain_rice"),
        ("sushi ryza mate?", "sushi_rice"),
        ("aku ryzu odporucas na sushi", "sushi_rice"),
        ("hladam ryzove rezance na pad thai", "rice_noodles"),
        ("mate ryzovy ocot?", "rice_vinegar"),
        ("hladam ryzovu muku", "rice_flour"),
        ("mate ryzovy papier na jarne zavitky", "rice_paper"),
        ("ryzovar mate?", "rice_cooker"),
        ("hladam hrniec na ryzu", "rice_cooker"),
        ("gochujang pasta 500g", None),
        ("mate ryzove rezance na ramen", "rice_noodles"),
    ])
    def test_classifies_real_customer_phrasing(self, query, expected_subfamily):
        match = classify_rice_query(query, normalize)
        assert match.subfamily == expected_subfamily, query

    def test_classifies_real_catalog_product_titles(self):
        # Grounded in actual data/products.json titles (Phase 21: synthetic
        # tests derived from real catalog products, not invented examples).
        real_titles = [
            ("Basmati ryža - LAILA - 1 kg", "plain_rice"),
            ("Jazmínová ryža FOODLAND 18 kg", "plain_rice"),
            ("Suši ryža japonská HARUKA 1 kg", "sushi_rice"),
            ("Chantaboon ryžové rezance tyčinky 3 mm FARMER 400 g", "rice_noodles"),
            ("Ochutený ryžový ocot na sushi ryžu KIKKOMAN 300ml", "rice_vinegar"),
            ("Lepkavá ryžová múka TAIKY 400g", "rice_flour"),
            ("Okrúhly ryžový papier na čerstvé jarné rolky TUFOCO 400g", "rice_paper"),
            ("Elektrický hrniec na ryžu REMO 0,8 L | 350 W", "rice_cooker"),
        ]
        for title, expected in real_titles:
            match = classify_rice_query(title, normalize)
            assert match.subfamily == expected, title

    def test_collision_family_generates_distinct_subfamilies(self):
        # The exact class of bug documented in roadmap Sprint Z.6: a
        # shared "ryz" linguistic root must not collapse distinct product
        # families into one. Every one of these must classify differently.
        collision_group = [
            ("mate ryzu?", "plain_rice"),
            ("mate ryzove rezance?", "rice_noodles"),
            ("mate ryzovy ocot?", "rice_vinegar"),
            ("mate ryzovu muku?", "rice_flour"),
            ("mate ryzovy papier?", "rice_paper"),
            ("mate ryzovar?", "rice_cooker"),
        ]
        results = [classify_rice_query(q, normalize).subfamily for q, _ in collision_group]
        expected = [sub for _, sub in collision_group]
        assert results == expected
        # Every collision-group query resolved to a distinct subfamily.
        assert len(set(results)) == len(results)

    def test_rice_cooker_checked_before_plain_rice_even_with_sushi_context(self):
        # Specificity invariant (roadmap-features.md Phase 23 analogue):
        # a more specific compound term must win over the generic root,
        # even when a second, unrelated rice-family word ("sushi ryzu")
        # also appears in the same message.
        match = classify_rice_query("ryzovar mate na sushi ryzu?", normalize)
        assert match.subfamily == "rice_cooker"

    def test_all_subfamilies_have_a_confidence_level(self):
        match_subfamilies = set()
        for query in (
            "ryza", "sushi ryza", "ryzove rezance", "ryzovy ocot",
            "ryzova muka", "ryzovy papier", "ryzovar",
        ):
            match = classify_rice_query(query, normalize)
            assert match.subfamily is not None
            match_subfamilies.add(match.subfamily)
        for subfamily in match_subfamilies:
            assert RICE_SUBFAMILY_CONFIDENCE[subfamily] in ("HIGH", "MEDIUM", "LOW")

    def test_no_match_returns_none_subfamily_and_none_confidence(self):
        match = classify_rice_query("mate kimchi?", normalize)
        assert match == TaxonomyMatch(family="rice", subfamily=None, confidence="NONE", matched_phrase=None)


class TestShadowModeIntegrity:
    """Stage A rollout (docs/advisor-v2-architecture.md): the taxonomy
    classifier must be pure observation - it must never change /chat's
    routing decision, products, or response shape."""

    def test_classify_rice_query_is_a_pure_function(self):
        # Same input always produces the same output; no side effects,
        # no dependency on mutable global state, so wiring it into every
        # /chat call is safe regardless of call order.
        a = classify_rice_query("mate basmati ryzu?", normalize)
        b = classify_rice_query("mate basmati ryzu?", normalize)
        assert a == b

    def test_log_taxonomy_shadow_only_writes_on_a_real_match(self, tmp_path, monkeypatch):
        import app.main as main

        log_path = tmp_path / "taxonomy_shadow.jsonl"
        monkeypatch.setenv("TAXONOMY_SHADOW_LOG_PATH", str(log_path))

        main.log_taxonomy_shadow("mate basmati ryzu?", "127.0.0.1", classify_rice_query("mate basmati ryzu?", normalize))
        main.log_taxonomy_shadow("gochujang pasta 500g", "127.0.0.1", classify_rice_query("gochujang pasta 500g", normalize))

        assert log_path.exists()
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        import json
        record = json.loads(lines[0])
        assert record["family"] == "rice"
        assert record["subfamily"] == "plain_rice"
        assert "message" in record and "client_hash" in record


def make_product(**overrides) -> Product:
    base = dict(
        id="FL_TEST", title="", description="", product_type="", link="",
        image_link="", price=None, sale_price=None, currency="EUR", brand="",
        availability="in_stock", gtin="", unit_pricing_measure="",
    )
    base.update(overrides)
    return Product(**base)


class TestClassifyProductRiceCollisions:
    """Sprint V2.1 product-level engine (docs/product-taxonomy-audit.md).

    Distinct from TestRiceSubfamilyClassification above: classify_product()
    classifies a catalog PRODUCT's real identity, not a customer message.
    canonical_family("ryžové rezance") etc. must NOT be "rice" - grounded in
    real data/products.json titles and category paths (verified live-feed
    evidence gathered for this sprint).
    """

    def test_plain_rice_family_is_rice(self):
        p = make_product(
            title="Basmati ryža - LAILA - 1 kg",
            product_type="Vegánske potraviny > Super potraviny > Basmati ryža > Ryža",
        )
        tax = classify_product(p)
        assert tax.canonical_family == "rice"
        assert tax.canonical_subfamily == "plain_rice"
        assert tax.attributes.get("variety") == "basmati"

    def test_rice_noodles_family_is_not_rice(self):
        p = make_product(
            title="Chantaboon ryžové rezance tyčinky 3 mm FARMER 400 g",
            product_type="Zdravé potraviny > Bezlepkové potraviny > Ryžové rezance > Rezance, niťovky a cestoviny",
        )
        tax = classify_product(p)
        assert tax.canonical_family != "rice"
        assert tax.canonical_family == "noodles"
        assert tax.canonical_subfamily == "rice_noodles"

    def test_rice_vinegar_family_is_not_rice(self):
        p = make_product(
            title="Ryžový ocot CHINKIANG GOLD PLUM 550ml",
            product_type="Vegetariánske potraviny > Zdravé potraviny > Ocot > Koreniny a ochucovadlá",
        )
        tax = classify_product(p)
        assert tax.canonical_family != "rice"
        assert tax.canonical_family == "vinegar"
        assert tax.canonical_subfamily == "rice_vinegar"

    def test_rice_flour_family_is_not_rice(self):
        p = make_product(
            title="Lepkavá ryžová múka TAIKY 400g",
            product_type="Múka > Múka, škrob & ryžový papier",
        )
        tax = classify_product(p)
        assert tax.canonical_family != "rice"
        assert tax.canonical_family == "flour"
        assert tax.canonical_subfamily == "rice_flour"

    def test_rice_paper_family_is_not_rice(self):
        p = make_product(
            title="Okrúhly ryžový papier na čerstvé jarné rolky TUFOCO 400g",
            product_type="Obaľovacia zmes, tempura & panko > Zdravé potraviny > Ryžový papier > Múka, škrob & ryžový papier",
        )
        tax = classify_product(p)
        assert tax.canonical_family != "rice"
        assert tax.canonical_family == "rice_paper"

    def test_rice_cooker_family_is_not_rice(self):
        p = make_product(
            title="Elektrický hrniec na ryžu REMO 0,8 L | 350 W",
            product_type="Potreby na výrobu suši > Ryžovary > Kuchynský riad > Kuchynské náradie a pomôcky > Kuchynské potreby",
        )
        tax = classify_product(p)
        assert tax.canonical_family != "rice"
        assert tax.canonical_family == "kitchenware"
        assert tax.attributes.get("object_type") == "rice_cooker"

    def test_collision_group_generates_distinct_canonical_families(self):
        collision_group = [
            make_product(title="Basmati ryža - LAILA - 1 kg", product_type="Basmati ryža > Ryža"),
            make_product(title="Chantaboon ryžové rezance tyčinky 3 mm FARMER 400 g", product_type="Ryžové rezance > Rezance, niťovky a cestoviny"),
            make_product(title="Ryžový ocot CHINKIANG GOLD PLUM 550ml", product_type="Ocot > Koreniny a ochucovadlá"),
            make_product(title="Lepkavá ryžová múka TAIKY 400g", product_type="Múka > Múka, škrob & ryžový papier"),
            make_product(title="Ryžový papier na čerstvé jarné rolky TUFOCO 400g", product_type="Ryžový papier > Múka, škrob & ryžový papier"),
            make_product(title="Komerčný ryžovar CUCKOO SR 4600 GL 4,6L", product_type="Ryžovary > Kuchynský riad"),
        ]
        families = [classify_product(p).canonical_family for p in collision_group]
        assert families == ["rice", "noodles", "vinegar", "flour", "rice_paper", "kitchenware"]
        assert len(set(families)) == len(families)


class TestClassifyProductAttributes:
    def test_sushi_rice_use_case_attribute(self):
        p = make_product(
            title="Suši ryža japonská HARUKA 1 kg",
            product_type="Zdravé potraviny > Bezlepkové potraviny > Ryža na suši (sushi) > Sushi ingrediencie > Suši ryža > Ryža",
        )
        tax = classify_product(p)
        assert tax.canonical_family == "rice"
        assert tax.canonical_subfamily == "sushi_rice"
        assert tax.attributes.get("use_case") == "sushi"

    def test_jasmine_variety(self):
        p = make_product(title="Thajská Jazmínová ryža Golden Coral 1 kg", product_type="Jazmínová ryža > Ryža")
        tax = classify_product(p)
        assert tax.attributes.get("variety") == "jasmine"

    def test_glutinous_variety_distinct_from_rice_flour(self):
        grain = make_product(title="Lepkavá ryža ABC 1kg", product_type="Ryža")
        flour = make_product(title="Lepkavá ryžová múka TAIKY 400g", product_type="Múka")
        assert classify_product(grain).attributes.get("variety") == "glutinous"
        assert classify_product(flour).canonical_family == "flour"

    def test_noodles_ingredient_base_attribute(self):
        p = make_product(title="Hnedé ryžové rezance PHO GAO LUT 400g", product_type="Ryžové rezance")
        tax = classify_product(p)
        assert tax.attributes.get("ingredient_base") == "rice"


class TestCategoryAliases:
    """Two catalog labels for the same sushi-rice set (Section 19)."""

    def test_ryza_na_susi_and_susi_ryza_resolve_the_same_way(self):
        variant_a = make_product(title="Suši ryža KIMPO 1 kg", product_type="Ryža na suši (sushi) > Suši ryža > Ryža")
        variant_b = make_product(title="Suši ryža OBENTO 1 kg", product_type="Suši ryža > Ryža")
        tax_a = classify_product(variant_a)
        tax_b = classify_product(variant_b)
        assert tax_a.canonical_subfamily == tax_b.canonical_subfamily == "sushi_rice"


class TestConfidenceLevels:
    def test_category_match_is_high_confidence(self):
        p = make_product(title="Niečo", product_type="Ryžovary")
        tax = classify_product(p)
        assert tax.confidence == "HIGH"

    def test_title_only_match_is_downgraded_from_category_confidence(self):
        p = make_product(title="ryzovar", product_type="Nesúvisiaca kategória")
        tax = classify_product(p)
        assert tax.canonical_family == "kitchenware"
        assert tax.confidence == "MEDIUM"


class TestUnknownProducts:
    def test_unrelated_product_is_unknown_not_dropped(self):
        p = make_product(title="Kimchi základ KIKKOMAN 1180g", product_type="Kórejské > Pasty")
        tax = classify_product(p)
        assert tax.canonical_family is None
        assert tax.confidence == "UNKNOWN"
        assert isinstance(tax, ProductTaxonomy)

    def test_unknown_product_still_gets_dietary_facets(self):
        p = make_product(
            title="Kimchi základ KIKKOMAN 1180g",
            product_type="Vegánske potraviny > Kórejské > Pasty",
        )
        tax = classify_product(p)
        assert tax.canonical_family is None
        assert "vegan" in tax.dietary_facets


class TestBuildTaxonomyIndex:
    def test_indexes_every_product_by_id(self):
        products = [
            make_product(id="FL_1", title="Basmati ryža", product_type="Ryža"),
            make_product(id="FL_2", title="Kimchi základ KIKKOMAN 1180g", product_type=""),
        ]
        index = build_taxonomy_index(products)
        assert set(index.keys()) == {"FL_1", "FL_2"}
        assert index["FL_1"].canonical_family == "rice"
        assert index["FL_2"].canonical_family is None

    def test_one_bad_product_does_not_break_the_batch(self):
        good = make_product(id="FL_1", title="Basmati ryža", product_type="Ryža")

        class Broken:
            id = "FL_broken"

            @property
            def category_memberships(self):
                raise RuntimeError("boom")

        index = build_taxonomy_index([good, Broken()])
        assert index["FL_1"].canonical_family == "rice"
        assert index["FL_broken"].confidence == "UNKNOWN"

    def test_taxonomy_version_is_set(self):
        p = make_product(id="FL_1", title="Basmati ryža", product_type="Ryža")
        index = build_taxonomy_index([p])
        assert index["FL_1"].taxonomy_version >= 1


class TestQueryApi:
    def _index(self):
        return build_taxonomy_index([
            make_product(id="FL_1", title="Basmati ryža", product_type="Basmati ryža > Ryža"),
            make_product(id="FL_2", title="Jazmínová ryža FOODLAND 5 kg", product_type="Jazmínová ryža > Ryža"),
            make_product(id="FL_3", title="Ryžový ocot X", product_type="Ocot"),
        ])

    def test_find_by_family(self):
        index = self._index()
        rice_ids = find_by_family(index, "rice")
        assert set(rice_ids) == {"FL_1", "FL_2"}

    def test_find_by_attributes(self):
        index = self._index()
        jasmine_ids = find_by_attributes(index, variety="jasmine")
        assert jasmine_ids == ["FL_2"]

    def test_get_taxonomy_returns_none_for_unknown_id(self):
        index = self._index()
        assert get_taxonomy(index, "FL_missing") is None
        assert get_taxonomy(index, "FL_1") is not None


class TestTaxonomyCoverage:
    def test_coverage_stats_computed_from_index(self):
        index = build_taxonomy_index([
            make_product(id="FL_1", title="Basmati ryža", product_type="Basmati ryža > Ryža"),
            make_product(id="FL_2", title="Kimchi základ KIKKOMAN 1180g", product_type=""),
        ])
        stats = taxonomy_coverage(index)
        assert stats["total_products"] == 2
        assert stats["classified_products"] == 1
        assert stats["taxonomy_coverage"] == 0.5
        assert stats["families"]["rice"] == 1


class TestConceptIndex:
    """Sprint V2.2 autocomplete: app.taxonomy.build_concept_index()."""

    def test_every_rule_has_a_display_label(self):
        for rule in FAMILY_DEFINITIONS:
            assert rule.display_label, f"{rule.rule_id} is missing display_label"

    def test_classify_product_sets_concept_id_on_match(self):
        p = make_product(title="Basmati ryža - LAILA - 1 kg", product_type="Basmati ryža > Ryža")
        tax = classify_product(p)
        assert tax.concept_id == "basmati_rice"

    def test_classify_product_leaves_concept_id_empty_on_unknown(self):
        p = make_product(title="Kimchi základ KIKKOMAN 1180g", product_type="")
        tax = classify_product(p)
        assert tax.concept_id == ""

    def test_concept_index_groups_and_counts_real_products(self):
        products = [
            make_product(id="FL_1", title="Basmati ryža A", product_type="Basmati ryža > Ryža"),
            make_product(id="FL_2", title="Basmati ryža B", product_type="Basmati ryža > Ryža"),
            make_product(id="FL_3", title="Jazmínová ryža C", product_type="Jazmínová ryža > Ryža"),
        ]
        index = build_taxonomy_index(products)
        concepts = build_concept_index(index)
        by_id = {c["concept_id"]: c for c in concepts}
        assert by_id["basmati_rice"]["product_count"] == 2
        assert by_id["basmati_rice"]["label"] == "Basmati ryža"
        assert by_id["jasmine_rice"]["product_count"] == 1

    def test_concept_index_excludes_low_confidence(self):
        # rice_wine/rice_drink rules only match via title (no category_terms),
        # so their real confidence is downgraded HIGH->MEDIUM base "MEDIUM"->LOW -
        # LOW must never surface as a proactive suggestion concept.
        products = [make_product(id="FL_1", title="Kórejský ryžový nápoj Woongjin 500ml", product_type="Nealkoholické nápoje")]
        index = build_taxonomy_index(products)
        concepts = build_concept_index(index)
        assert not any(c["concept_id"] == "rice_drink" for c in concepts)

    def test_concept_index_excludes_unknown_products(self):
        products = [make_product(id="FL_1", title="Kimchi základ KIKKOMAN 1180g", product_type="")]
        index = build_taxonomy_index(products)
        concepts = build_concept_index(index)
        assert concepts == []

    def test_concept_index_attributes_come_from_the_rule(self):
        products = [make_product(id="FL_1", title="Jazmínová ryža X", product_type="Jazmínová ryža > Ryža")]
        index = build_taxonomy_index(products)
        concepts = build_concept_index(index)
        jasmine = next(c for c in concepts if c["concept_id"] == "jasmine_rice")
        assert jasmine["attributes"] == {"variety": "jasmine"}
        assert jasmine["family"] == "rice"
        assert jasmine["subfamily"] == "plain_rice"
