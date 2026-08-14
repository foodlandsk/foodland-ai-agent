"""
tests/test_autocomplete.py  -  V2.2 intent-aware autocomplete: taxonomy-
grounded category concepts and curated question/comparison suggestions
(app.autocomplete.taxonomy_category_suggestions / question_suggestions).

Pure unit tests over app/autocomplete.py's new V2.2 functions - no
FastAPI/main.py dependency, no network. Grounded in real family/subfamily
concepts from app.taxonomy.FAMILY_DEFINITIONS and real IntentMapping
question text (see data/knowledge.json), not invented examples.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.autocomplete import (
    _token_wise_match_score,
    question_suggestions,
    taxonomy_category_suggestions,
)


def make_concept(label, family, subfamily=None, attributes=None, product_count=10, concept_id=None):
    return {
        "concept_id": concept_id or label,
        "label": label,
        "family": family,
        "subfamily": subfamily,
        "attributes": attributes or {},
        "product_count": product_count,
    }


RICE_CONCEPTS = [
    make_concept("Ryža", "rice", "plain_rice", concept_id="plain_rice", product_count=19),
    make_concept("Jazmínová ryža", "rice", "plain_rice", {"variety": "jasmine"}, concept_id="jasmine_rice", product_count=14),
    make_concept("Basmati ryža", "rice", "plain_rice", {"variety": "basmati"}, concept_id="basmati_rice", product_count=20),
    make_concept("Lepkavá ryža", "rice", "plain_rice", {"variety": "glutinous"}, concept_id="glutinous_rice", product_count=13),
    make_concept("Ryža na sushi", "rice", "sushi_rice", {"use_case": "sushi"}, concept_id="sushi_rice", product_count=12),
    make_concept("Ryžové rezance", "noodles", "rice_noodles", {"ingredient_base": "rice"}, concept_id="rice_noodles", product_count=39),
    make_concept("Ryžový ocot", "vinegar", "rice_vinegar", {"source": "rice"}, concept_id="rice_vinegar", product_count=10),
    make_concept("Ryžová múka", "flour", "rice_flour", {"ingredient_base": "rice"}, concept_id="rice_flour", product_count=5),
    make_concept("Ryžový papier", "rice_paper", None, {}, concept_id="rice_paper", product_count=8),
    make_concept("Ryžovar", "kitchenware", "rice_cooker", {"object_type": "rice_cooker"}, concept_id="rice_cooker", product_count=7),
]


class TestTokenWiseMatchScore:
    def test_full_prefix_scores_highest(self):
        assert _token_wise_match_score("basmati r", "basmati ryza") == 100

    def test_word_order_independent(self):
        forward = _token_wise_match_score("ryza basmati", "basmati ryza")
        reverse = _token_wise_match_score("basmati ryza", "basmati ryza")
        assert forward > 0
        assert reverse == 100

    def test_partial_multi_token_query(self):
        assert _token_wise_match_score("rozdiel jaz", "aky je rozdiel medzi jazminovou a basmati ryzou") > 0

    def test_no_match_returns_zero(self):
        assert _token_wise_match_score("gochujang", "basmati ryza") == 0

    def test_empty_query_returns_zero(self):
        assert _token_wise_match_score("", "basmati ryza") == 0


class TestTaxonomyCategorySuggestions:
    def test_broad_rice_query_excludes_collision_families(self):
        # Section 13/36 invariant: "ryza" must not surface rice noodles/
        # vinegar/paper/cooker as rice varieties.
        results = taxonomy_category_suggestions("ryza", RICE_CONCEPTS, limit=10)
        labels = {r["label"] for r in results}
        assert "Ryžové rezance" not in labels
        assert "Ryžový ocot" not in labels
        assert "Ryžový papier" not in labels
        assert "Ryžovar" not in labels
        assert "Ryža" in labels

    def test_ryzov_prefix_surfaces_collision_family_concepts(self):
        # Section 13 example: "ryžov" MAY suggest Ryžový ocot / Ryžovar.
        results = taxonomy_category_suggestions("ryzov", RICE_CONCEPTS, limit=10)
        labels = {r["label"] for r in results}
        assert "Ryžový ocot" in labels
        assert "Ryžovar" in labels
        assert "Ryža" not in labels
        assert "Jazmínová ryža" not in labels

    def test_compound_concept_recognized(self):
        results = taxonomy_category_suggestions("jazm", RICE_CONCEPTS, limit=4)
        assert len(results) == 1
        assert results[0]["label"] == "Jazmínová ryža"

    def test_word_order_variant_matches(self):
        forward = taxonomy_category_suggestions("basmati ryza", RICE_CONCEPTS, limit=4)
        reverse = taxonomy_category_suggestions("ryza basmati", RICE_CONCEPTS, limit=4)
        assert any(r["label"] == "Basmati ryža" for r in forward)
        assert any(r["label"] == "Basmati ryža" for r in reverse)

    def test_diacritic_and_ascii_forms_equivalent(self):
        with_diacritics = taxonomy_category_suggestions("ryža", RICE_CONCEPTS, limit=4)
        ascii_form = taxonomy_category_suggestions("ryza", RICE_CONCEPTS, limit=4)
        assert {r["label"] for r in with_diacritics} == {r["label"] for r in ascii_form}

    def test_structured_action_payload(self):
        results = taxonomy_category_suggestions("jazm", RICE_CONCEPTS, limit=4)
        item = results[0]
        assert item["type"] == "taxonomy_category"
        assert item["action"] == "APPLY_CONSTRAINTS"
        assert item["constraints"]["family"] == "rice"
        assert item["constraints"]["variety"] == "jasmine"
        assert item["query"] == "Jazmínová ryža"

    def test_product_count_reflects_input_not_fabricated(self):
        results = taxonomy_category_suggestions("basmati", RICE_CONCEPTS, limit=4)
        assert results[0]["product_count"] == 20

    def test_empty_query_returns_nothing(self):
        assert taxonomy_category_suggestions("", RICE_CONCEPTS, limit=4) == []

    def test_no_match_returns_empty_list_not_error(self):
        assert taxonomy_category_suggestions("gochujang", RICE_CONCEPTS, limit=4) == []

    def test_respects_limit(self):
        results = taxonomy_category_suggestions("ryza", RICE_CONCEPTS, limit=2)
        assert len(results) <= 2

    def test_empty_concept_list_is_safe(self):
        assert taxonomy_category_suggestions("ryza", [], limit=4) == []


RICE_KNOWLEDGE = {
    "sections": {
        "IntentMapping": [
            {
                "Typ zámeru": "Ryža / výber produktu",
                "Zámer (príklad otázky/vyhľadávania)": "Akú ryžu použiť na sushi?",
            },
            {
                "Typ zámeru": "Ryža / výber produktu",
                "Zámer (príklad otázky/vyhľadávania)": "Aký je rozdiel medzi jazmínovou a basmati ryžou?",
            },
            {
                "Typ zámeru": "Ryža / výber produktu",
                "Zámer (príklad otázky/vyhľadávania)": "Potrebujem lepivú ryžu na mango sticky rice.",
            },
            {
                "Typ zámeru": "Magazín / edukácia",
                "Zámer (príklad otázky/vyhľadávania)": "Aký je rozdiel medzi ryžou a inými obilninami vo všeobecnosti?",
            },
        ]
    }
}


class TestQuestionSuggestions:
    def test_grounded_use_case_question(self):
        results = question_suggestions(RICE_KNOWLEDGE, "aku ryzu", limit=3)
        labels = [r["label"] for r in results]
        assert "Akú ryžu použiť na sushi?" in labels

    def test_comparison_question_classified_distinctly(self):
        results = question_suggestions(RICE_KNOWLEDGE, "rozdiel jaz", limit=3)
        assert results
        assert results[0]["type"] == "comparison"
        assert results[0]["label"] == "Aký je rozdiel medzi jazmínovou a basmati ryžou?"

    def test_only_sources_from_vyber_produktu_records(self):
        # The Magazín/edukácia record also contains "rozdiel" but must be
        # excluded - only curated "výber produktu" (product-choice) records
        # are grounded enough to suggest (Section 19).
        results = question_suggestions(RICE_KNOWLEDGE, "rozdiel ryzou", limit=5)
        labels = [r["label"] for r in results]
        assert "Aký je rozdiel medzi ryžou a inými obilninami vo všeobecnosti?" not in labels

    def test_structured_action_payload(self):
        results = question_suggestions(RICE_KNOWLEDGE, "aku ryzu", limit=3)
        assert results[0]["action"] == "ASK_QUESTION"
        assert results[0]["query"] == results[0]["label"]

    def test_word_order_independent(self):
        results = question_suggestions(RICE_KNOWLEDGE, "jazminova rozdiel", limit=3)
        assert any(r["type"] == "comparison" for r in results)

    def test_no_duplicate_questions(self):
        results = question_suggestions(RICE_KNOWLEDGE, "ryzu", limit=10)
        labels = [r["label"] for r in results]
        assert len(labels) == len(set(labels))

    def test_empty_query_returns_nothing(self):
        assert question_suggestions(RICE_KNOWLEDGE, "", limit=3) == []

    def test_no_match_returns_empty_list(self):
        assert question_suggestions(RICE_KNOWLEDGE, "gochujang", limit=3) == []

    def test_missing_intent_mapping_section_is_safe(self):
        assert question_suggestions({"sections": {}}, "aku ryzu", limit=3) == []

    def test_non_dict_knowledge_is_safe(self):
        assert question_suggestions(None, "aku ryzu", limit=3) == []

    def test_respects_limit(self):
        results = question_suggestions(RICE_KNOWLEDGE, "ryzu", limit=1)
        assert len(results) <= 1
