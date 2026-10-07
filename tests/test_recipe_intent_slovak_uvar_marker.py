"""
tests/test_recipe_intent_slovak_uvar_marker.py  -  Contract 2 fix.

Context (V2.24q-z read-only contract review series, docs/query-semantics.md):
RECIPE_INTENT_MARKERS had no entry for the Slovak "uvar" (cook/boil) verb
stem - unlike its Czech sibling "jak uvarim", which already existed. A bare
"Ako uvariť <jedlo>?" question fell through is_recipe_intent() entirely and
got misrouted into related_products (generic cross-sell) instead of the
recipe workflow (app.workflow_executor.execute_recipe(), called ahead of the
related_subject guard chain - app/main.py ~line 5114).

Fix: added the bare stem "ako uvar" to RECIPE_INTENT_MARKERS, matching the
existing bare-stem pattern elsewhere in that tuple (e.g. "tom kha", "pad
thai") rather than enumerating every conjugation ("ako uvarim"/"ako
uvaris"/"ako uvarite"/"ako uvarit").

Blast radius verified read-only (in-memory monkeypatch, V2.24z-adjacent
review) before this fix was implemented: exactly 1/93 DEV golden scenario
newly triggers is_recipe_intent() - v222_recipe_only_0005 itself. No other
DEV scenario, and no other test file containing the substring "uvar"
(test_already_have_entity_state_v2_23g.py, test_core.py,
test_scenario_candidates.py - all use "čo ... uvariť"/"čo ... uvarím"
phrasing with no "ako", and none call is_recipe_intent() in their
assertions anyway).
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


class TestAkoUvarMarker:
    def test_is_recipe_intent_fires(self):
        assert m.is_recipe_intent(m.normalize("Ako uvariť Ma Po Tofu?"))

    def test_detect_recipe_subject_resolves(self):
        assert m.detect_recipe_subject("Ako uvariť Ma Po Tofu?") == "mapo_tofu"

    def test_end_to_end_recipe_intent_not_related_products(self):
        r = _chat("Ako uvariť Ma Po Tofu?", "v224z-recipe-uvar-mapotofu")
        assert r.get("intent") != "related_products"
        assert (r.get("answer") or "").strip()

    def test_conjugated_forms_also_match(self):
        # Bare-stem marker should catch other conjugations too, without
        # separate entries per form.
        assert m.is_recipe_intent(m.normalize("Ako uvarim rybaciu polievku?"))
        assert m.is_recipe_intent(m.normalize("Ako uvaríte kimchi jjigae?"))


class TestOwnershipCompanionPhrasingUnaffected:
    """The 3 other test files containing 'uvar' use a different frame
    ('čo ... uvariť/uvarím', no 'ako') that must stay on its existing
    already-have/companion path, not be swept into recipe_intent."""

    def test_co_k_nej_uvarit_is_not_ako_uvar(self):
        assert not m.is_recipe_intent(m.normalize("Mám ryžu, čo k nej uvariť?"))

    def test_co_s_nim_uvarim_is_not_ako_uvar(self):
        assert not m.is_recipe_intent(m.normalize("Mám tofu, čo s ním uvarím?"))

    def test_varenie_pocas_dazdivych_dni_is_not_ako_uvar(self):
        assert not m.is_recipe_intent(m.normalize("Varenie pocas dazdivych dni, co uvarit?"))
