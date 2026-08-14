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

from app.taxonomy import RICE_SUBFAMILY_CONFIDENCE, TaxonomyMatch, classify_rice_query
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
