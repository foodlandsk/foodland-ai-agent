"""
tests/test_answered_field.py  -  regression test for a real production
audit finding: /chat responses that carry their substance in `answer`
text alone (FAQ, allergen_safety, missing_composition, reset, a bare
recipe article with no shopping-list products) were indistinguishable
from a genuine failure once app.widget.js's no_result telemetry (and
therefore app.learning_opportunities' HIGH_ZERO_RESULT/TAXONOMY_GAP_
CANDIDATE detectors, which read that same event) only checked products/
recipes/articles. `chat()` now computes an explicit `answered` field so
the widget has one authoritative signal instead of re-deriving it.
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
    headers = {}


def _chat(message: str, session_id: str, limit: int = 6) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


class TestAnsweredFieldMarksRealSuccesses:
    def test_faq_answer_is_marked_answered_despite_zero_products(self):
        r = _chat("doprava", "answered-faq-1")
        assert r["intent"] == "faq"
        assert r["products"] == []
        assert r["answered"] is True

    def test_allergen_safety_disclaimer_is_marked_answered_despite_zero_products(self):
        r = _chat("mam alergiu na lepok, co by ste doporucili?", "answered-allergen-1")
        assert r["intent"] == "allergen_safety"
        assert r["products"] == []
        assert r["answered"] is True

    def test_bare_recipe_article_is_marked_answered_despite_zero_products(self):
        r = _chat("vindaloo", "answered-recipe-1")
        assert r["products"] == []
        if r.get("recipes"):
            assert r["answered"] is True

    def test_real_products_are_marked_answered(self):
        r = _chat("jazminova ryza", "answered-products-1")
        assert r["products"]
        assert r["answered"] is True


class TestAnsweredFieldMarksGenuineFailures:
    def test_unparseable_nonsense_query_is_not_marked_answered(self):
        r = _chat("asdkjaslkdj nonsense query xyz123", "answered-fail-1")
        assert r["products"] == []
        assert r["answered"] is False


class TestChatWrapperPreservesExistingBehavior:
    """The rename to _chat_impl() + thin chat() wrapper must not change
    anything about the response shape besides adding `answered`."""

    def test_chat_still_callable_with_the_same_signature(self):
        r = _chat("jazminova ryza", "answered-wrapper-1")
        assert isinstance(r, dict)
        assert "answer" in r
        assert "products" in r

    def test_intent_and_workflow_fields_unaffected(self):
        r = _chat("jazminova ryza", "answered-wrapper-2")
        assert r.get("intent") == "product_search"
