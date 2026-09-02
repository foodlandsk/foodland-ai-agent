"""
tests/test_recommendation_explanation_v2_16e.py  -  V2.16e recommendation
explanation & decision transparency closure.

V2.16e characterized how the assistant currently explains (or fails to
explain) its own recommendations before implementing anything (Section
16 of the sprint spec) and found 2 real, live-reproduced defects:

1. A SEVERE, systemic data-quality defect: app.knowledge_builder's own
   AI-content-generation prompt template text ("profil urci podla
   nazvu produktu, kategorie a detailu na webe; nevymyslaj zlozenie" -
   an instruction TO an AI author, not a sentence ABOUT a product) was
   left as the literal cell value for 63/130 (48.5%) of the curated
   Products_AI "Chutovy profil - SK"/"Kucharsky tip - SK" records. One
   such record was reproduced live, verbatim, as the customer-facing
   answer to a "why this?" follow-up. Fixed at the two read sites
   (app.knowledge.best_product_advice_answer()/format_record()) via
   app.knowledge._is_broken_curation_placeholder() - a targeted guard
   for the exact known-broken pattern, not a data repair (that belongs
   to the curation pipeline, documented as data debt).

2. "Why this?"/"why not the other?" (Section 17 - explicitly named a
   CORE CAPABILITY) did not exist as a dedicated mechanism at all - a
   bare "preco"/"why" already matched app.main.is_article_info_intent()'s
   broad marker set, so a why-followup about an actual prior
   recommendation was silently swallowed by the FAQ/article-info
   cascade instead, reproduced live as two distinct non-answers (see
   app.explanation's module docstring for the exact live repro).
   Fixed with a new, small module (app.explanation) that re-explains
   the customer's LAST successfully resolved use_case_advice/
   comparison/basket_completion decision from the EXACT evidence
   already computed for it (app.session_state.get/set_last_explanation) -
   never a fresh, invented reason, never a new decision_id, never an
   LLM call.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m
import app.knowledge as knowledge_module
import app.explanation as explanation_module


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, limit: int = 8) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


class TestBrokenCurationPlaceholderGuard:
    """Fix 1 - direct unit coverage of the detector, plus a live repro
    that it no longer leaks."""

    def test_known_broken_pattern_detected(self):
        broken = "profil urci podla nazvu produktu, kategorie a detailu na webe; nevymyslaj zlozenie"
        assert knowledge_module._is_broken_curation_placeholder(broken) is True

    def test_real_prose_not_flagged(self):
        clean = "Jemne slana a umami chut, typicka pre tradicnu sojovu omacku."
        assert knowledge_module._is_broken_curation_placeholder(clean) is False

    def test_no_products_ai_record_leaks_via_format_record(self):
        leaked = []
        for record in m.knowledge["sections"]["Products_AI"]:
            formatted = knowledge_module.format_record("Products_AI", record)
            if knowledge_module._is_broken_curation_placeholder(formatted):
                leaked.append(record.get("Produkt (URL)") or record.get("ID"))
        assert leaked == []

    def test_best_product_advice_answer_never_returns_broken_placeholder(self):
        for record in m.knowledge["sections"]["Products_AI"]:
            url = record.get("Produkt (URL)")
            if not url:
                continue
            results = {"Products_AI": [{"record": record, "score": 1.0}]}
            answer = knowledge_module.best_product_advice_answer(results, matched_links={url})
            if answer:
                assert not knowledge_module._is_broken_curation_placeholder(answer), (
                    f"best_product_advice_answer() leaked a broken placeholder for {url!r}: {answer!r}"
                )


class TestWhyThisFollowup:
    """Fix 2 - Section 56 cases Q/S/T/U/V/W/X/Y."""

    def test_why_this_after_use_case_advice(self):
        _chat("Aku ryzu odporucas na sushi?", "v216e-t1")
        r = _chat("Preco mi odporucas tento?", "v216e-t1")
        assert r.get("intent") == "why_followup"
        answer = (r.get("answer") or "").lower()
        assert "sushi" in answer
        assert "zaradenie v katalogu" in m.normalize(answer) or "katalog" in m.normalize(answer)

    def test_why_this_unambiguous_single_basket_role(self):
        # Force a single-role explanation by directly seeding session
        # state - simpler and more robust than depending on catalog
        # contents always producing exactly one resolved basket role.
        memory = m.get_session_memory("v216e-t2")
        from app.session_state import set_last_explanation
        set_last_explanation(memory, {
            "workflow": "basket_completion",
            "use_case": "pho",
            "roles": [
                {"concept_id": "fish_sauce", "display_label_sk": "rybacia omáčka", "status": "RESOLVED_PRODUCT", "confidence": "MEDIUM", "product_id": "FL_1"},
            ],
        })
        r = _chat("Preco tento?", "v216e-t2")
        assert r.get("intent") == "why_followup"
        assert "rybacia om" in (r.get("answer") or "").lower()

    def test_why_this_ambiguous_multi_role_basket_clarifies(self):
        _chat("Co potrebujem na sushi?", "v216e-t3")
        r = _chat("Preco tento?", "v216e-t3")
        assert r.get("intent") == "why_followup"
        answer = (r.get("answer") or "").lower()
        assert "ktor" in answer  # "ktorú položku..." - a clarifying question, not a guess

    def test_why_not_other_after_clear_winner_comparison(self):
        _chat("Kikkoman sojova omacka alebo Yamasa sojova omacka?", "v216e-t4")
        r = _chat("Preco nie ten druhy?", "v216e-t4")
        assert r.get("intent") == "why_followup"
        answer = (r.get("answer") or "").lower()
        assert "nemam doklad" in m.normalize(answer) or "horsi" in m.normalize(answer)

    def test_no_fabricated_negative_reasoning(self):
        _chat("Kikkoman sojova omacka alebo Yamasa sojova omacka?", "v216e-t5")
        r = _chat("Preco nie ten druhy?", "v216e-t5")
        answer = m.normalize(r.get("answer") or "")
        for forbidden in ("je horsia kvalita", "je horsi produkt", "ma horsiu chut"):
            assert forbidden not in answer

    def test_no_saved_reason_is_honest_not_guessed(self):
        r = _chat("Preco mi odporucas tento?", "v216e-t6")
        assert r.get("intent") == "why_followup"
        assert "nemám" in (r.get("answer") or "").lower() or "nemam" in m.normalize(r.get("answer") or "")

    def test_genuine_informational_preco_unaffected(self):
        r = _chat("Preco je citronova trava aromaticka?", "v216e-t7")
        assert r.get("intent") != "why_followup"

    def test_no_internal_reason_code_leakage(self):
        _chat("Aku ryzu odporucas na sushi?", "v216e-t8")
        r = _chat("Preco mi odporucas tento?", "v216e-t8")
        answer = (r.get("answer") or "")
        for internal_term in ("reason_code", "product_type_fit", "decision_id", "EvidenceItem", "PROVENANCE"):
            assert internal_term not in answer


class TestWhyFollowupSessionHygiene:
    def test_hard_switch_away_from_why_context(self):
        _chat("Aku ryzu odporucas na sushi?", "v216e-t9")
        r = _chat("Kde mate predajnu?", "v216e-t9")
        assert r.get("intent") == "faq"

    def test_reset_clears_last_explanation(self):
        memory = m.get_session_memory("v216e-t10")
        from app.session_state import get_last_explanation
        _chat("Aku ryzu odporucas na sushi?", "v216e-t10")
        assert get_last_explanation(memory) is not None
        _chat("Zacnime odznova", "v216e-t10")
        assert get_last_explanation(memory) is None

    def test_cross_session_isolation(self):
        _chat("Aku ryzu odporucas na sushi?", "v216e-t11-A")
        r = _chat("Preco mi odporucas tento?", "v216e-t11-B")
        assert r.get("intent") == "why_followup"
        assert "nemám" in (r.get("answer") or "").lower() or "nemam" in m.normalize(r.get("answer") or "")


class TestPermanentRegressionControls:
    def test_rt0004_related_products(self):
        r = _chat("suvisiace produkty k sushi ryzi", "v216e-reg-rt0004")
        assert r.get("intent") == "related_products"

    def test_rt0010_allergen_safety(self):
        r = _chat("sojova omacka bez soje", "v216e-reg-rt0010")
        assert r.get("intent") == "allergen_safety"

    def test_rt0013_replacement_unaffected(self):
        r = _chat("nahrada za rybiu omacku vegan", "v216e-reg-rt0013")
        assert r.get("intent") == "replacement_products"

    def test_v216d_basket_continuation_unaffected(self):
        _chat("Co potrebujem na pho?", "v216e-reg-v216d")
        r = _chat("Co este potrebujem?", "v216e-reg-v216d")
        assert r.get("intent") == "basket_completion"

    def test_vegan_noodles_regression(self):
        r = _chat("veganske rezance", "v216e-reg-vegan")
        titles = " | ".join((p.get("title") or "").lower() for p in (r.get("products") or []))
        assert "kurac" not in titles and "chicken" not in titles

    def test_comparison_unsupported_qualitative_still_abstains(self):
        r = _chat("Ktora je najautentickejsia sojova omacka?", "v216e-reg-qual")
        assert r.get("intent") != "why_followup"
