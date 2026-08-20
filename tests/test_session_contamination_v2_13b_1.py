"""
tests/test_session_contamination_v2_13b_1.py  -  V2.13b.1: session
context contamination hardening. Verifies the systemic fix (routing-
critical detectors now consume app.main._routing_message(), which never
carries the unconditional diet-term tail contextualize_message() used
to append) rather than just the single regbug_rt0011 query. Every case
here is tested end-to-end through the real chat() pipeline, same
session_id reused across turns where the scenario requires it
(Invariant #10 - no query-specific guards; these are generic scenarios,
not the one hardcoded golden phrase).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, limit: int = 8) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


def _titles(response: dict) -> list[str]:
    return [p.get("title", "") for p in (response.get("products") or [])]


class TestRegbugRt0011PermanentRegression:
    """Section 39 - the exact session sequence that exposed the bug must
    become a permanent test, not just a one-off manual verification."""

    QUERY = "mám rád nepálivé jedlo, čo odporúčaš?"

    def test_repeated_query_same_session_stays_product_search(self):
        sid = "sc-rt0011-permanent"
        first = _chat(self.QUERY, sid)
        second = _chat(self.QUERY, sid)
        assert first.get("intent") == "product_search"
        assert second.get("intent") == "product_search", (
            "stale diet-term carry-over ('jemne'/'pikantne' from this same "
            "query's own text) must not manufacture a special_subject/"
            "related_subject conflict on the repeated turn"
        )

    def test_repeated_query_returns_required_non_spicy_products(self):
        # eval/golden/regression_bugs.json::regbug_rt0011 exact assertions.
        sid = "sc-rt0011-permanent-products"
        _chat(self.QUERY, sid)
        second = _chat(self.QUERY, sid)
        titles = [m.normalize(t) for t in _titles(second)]
        for required in ("mochi", "kokosove mlieko", "jazminova ryza", "miso"):
            assert any(required in t for t in titles), f"missing required product: {required}"
        for forbidden in ("eko kraft box", "spicy", "hot", "paliv"):
            assert not any(forbidden in t for t in titles), f"forbidden product leaked: {forbidden}"


class TestDietTermDoesNotHijackUnrelatedProduct:
    """Section 40/41 - DIET -> NEW PRODUCT: a stored diet preference must
    not become false routing evidence for a later, unrelated explicit
    product request."""

    def test_diet_preference_then_specific_brand_lookup_stays_product_search(self):
        sid = "sc-diet-then-brand"
        _chat("mám rád pikantné jedlo", sid)
        r = _chat("mate sojovu omacku kikkoman", sid)
        assert r.get("intent") == "product_search"
        assert _titles(r)

    def test_diet_preference_then_unrelated_comparison_question_not_corrupted(self):
        sid = "sc-diet-then-comparison"
        _chat("hladam bezlepkove veci", sid)
        r = _chat("aky je rozdiel medzi mirin a rizovym octom?", sid)
        assert r.get("answered") is True


class TestRelatedProductsActionNotSticky:
    """Section 72 - a prior RELATED_PRODUCTS workflow must not make the
    next unrelated query also RELATED_PRODUCTS."""

    def test_related_products_then_new_search_does_not_stay_related(self):
        sid = "sc-related-not-sticky"
        first = _chat("čo sa hodí ku gochujang?", sid)
        assert first.get("intent") == "related_products"
        second = _chat("Shin Ramyun", sid)
        assert second.get("intent") == "product_search"
        assert any("ramyun" in m.normalize(t) or "shin" in m.normalize(t) for t in _titles(second))


class TestSafetyContextNotSticky:
    """Section 47/71 - a prior ALLERGEN_SAFETY workflow must not make a
    later, unrelated plain product search also resolve to safety."""

    def test_safety_then_unrelated_search_stays_product_search(self):
        sid = "sc-safety-not-sticky"
        first = _chat("sójová omáčka bez sóje", sid)
        assert first.get("intent") == "allergen_safety"
        second = _chat("jazmínová ryža", sid)
        assert second.get("intent") == "product_search"
        assert _titles(second)


class TestProductFamilyCollisionOnTopicSwitch:
    """Section 43/104 - a strong new product/topic must not inherit the
    previous family via routing_message contamination."""

    def test_rice_then_shin_ramyun_no_rice_contamination(self):
        sid = "sc-family-switch"
        first = _chat("jazmínová ryža", sid)
        assert first.get("intent") == "product_search"
        second = _chat("Shin Ramyun", sid)
        titles = [m.normalize(t) for t in _titles(second)]
        assert titles
        assert not any("ryza" in t and "ramyun" not in t for t in titles)


class TestLegitimateContextRetention:
    """Section 48 - this is a hardening sprint, not a "clear all context"
    sprint. Legitimate follow-ups must keep working identically."""

    def test_show_more_still_continues_result_set(self):
        sid = "sc-retain-showmore"
        first = _chat("basmati ryza", sid, limit=3)
        assert first.get("has_more") is True or first.get("matching_total", 0) > 3
        second = _chat("zobraz viac", sid)
        assert second.get("response_mode") == "result_set_continuation"

    def test_size_refinement_still_narrows_within_topic(self):
        sid = "sc-retain-refinement"
        first = _chat("jazmínová ryža", sid)
        assert first.get("intent") == "product_search"
        second = _chat("5kg", sid)
        titles = [m.normalize(t) for t in _titles(second)]
        assert titles
        assert any("5" in t for t in titles)

    def test_bare_followup_still_resolves_last_subject(self):
        # Mirrors tests/test_core.py::TestSessionMemory::test_followup_uses_last_subject
        # but through the full chat() pipeline rather than calling
        # contextualize_message() directly - proves the is_context_followup()
        # gated subject carry-over (shared by contextualize_message() and
        # the new _routing_message()) still reaches routing correctly.
        sid = "sc-retain-bare-followup"
        _chat("chcem variť sushi", sid)
        r = _chat("a čo k tomu?", sid)
        assert r.get("intent") in ("related_products", "product_search")
        assert _titles(r)


class TestCrossSessionIsolation:
    """Section 80/81 - interleaved sessions must never leak state into
    each other, independent of the routing_message hardening."""

    def test_diet_term_in_one_session_does_not_leak_into_another(self):
        session_a = "sc-isolation-a"
        session_b = "sc-isolation-b"
        _chat("mám rád pikantné jedlo", session_a)
        r_b = _chat("jazmínová ryža", session_b)
        assert r_b.get("intent") == "product_search"
        assert _titles(r_b)

    def test_interleaved_sessions_do_not_cross_contaminate_routing(self):
        session_a = "sc-interleave-a"
        session_b = "sc-interleave-b"
        _chat("mám rád nepálivé jedlo, čo odporúčaš?", session_a)
        _chat("čo sa hodí ku gochujang?", session_b)
        r_a = _chat("mám rád nepálivé jedlo, čo odporúčaš?", session_a)
        r_b = _chat("čo sa hodí ku gochujang?", session_b)
        assert r_a.get("intent") == "product_search"
        assert r_b.get("intent") == "related_products"


class TestRoutingMessageDoesNotCarryDietTerms:
    """Direct unit-level lock on the fix itself - app.main._routing_message()
    must never include diet_terms, even when contextualize_message() (the
    unchanged, still-diet-term-carrying function used for retrieval/
    knowledge search/answer composition) does."""

    def test_routing_message_excludes_diet_terms_contextualize_message_includes(self):
        m.session_memories.clear()
        key = m.session_memory_key("sc-unit-routing-message", "127.0.0.1")
        memory = m.get_session_memory(key)
        m.update_session_memory(key, "mám rád pikantné jedlo", "product_advice", [], [], {})

        contextual = m.contextualize_message("aké omáčky odporúčaš?", memory)
        routing = m._routing_message("aké omáčky odporúčaš?", memory)

        assert "pikant" in m.normalize(contextual), "contextualize_message() behavior must stay unchanged"
        assert "pikant" not in m.normalize(routing), "routing_message() must never carry diet_terms"

    def test_routing_message_still_carries_legitimate_followup_subject(self):
        m.session_memories.clear()
        key = m.session_memory_key("sc-unit-routing-message-subject", "127.0.0.1")
        memory = m.get_session_memory(key)
        m.update_session_memory(key, "Chcem variť sushi", "product_search", [], [], {})

        routing = m._routing_message("a co k tomu?", memory)
        assert "sushi" in m.normalize(routing)
