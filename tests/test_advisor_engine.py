"""
tests/test_advisor_engine.py  -  Sprint V2.13a: AdvisorEngine Application
Boundary & Internal Execution Unification.

Central rule (Section 5): OLD APPLICATION BEHAVIOR and NEW ADVISORENGINE
BEHAVIOR must be equivalent - even for known routing defects. This file
proves that equivalence empirically (not just architecturally), and
separately characterizes the two known routing defects (rt0004, rt0010)
plus, at the time, one case pending human semantic review (rt0013)
WITHOUT fixing any of them (Invariant #2/#3).

rt0013 UPDATE (rt0013 semantic closure): the human product decision has
since been made (ACTION=replacement, TARGET=fish_sauce, CONSTRAINT=vegan
-> replacement_products) and the golden case
(eval/golden/regression_bugs.json::regbug_rt0013) updated accordingly -
runtime code was never changed, since it already resolved this query
correctly (GOLDEN_EXPECTATION_OUTDATED, not a routing defect). See
docs/routing-debt.md. The equivalence test below is left in place
unmodified - it never asserted a specific intent value, only that legacy
and AdvisorEngine agree, which remains true and still worth locking in.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m
from app.advisor_engine import AdvisorEngine, AdvisorRequest, advisor_engine
from app.execution_context import customer_context, evaluation_context


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


class _FakeRequestForClientKey:
    def __init__(self, host: str) -> None:
        self.client = type("client", (), {"host": host})()
        self.headers: dict = {}


def _legacy_chat(message: str, session_id: str, context=None) -> dict:
    # V2.13c fix: client_key must be unique per (session_id, side) pair,
    # not the single hardcoded "127.0.0.1" this and _engine_chat() used
    # to share. user_memory_key() falls back to a hash of client_key
    # when client_id is empty, so sharing one client_key means
    # _legacy_chat() and _engine_chat() shared ONE mutable
    # personalization profile (app.main.user_memories) - not just with
    # each other, but with every OTHER test in the suite that also
    # hardcodes "127.0.0.1". personalization_score() reads accumulated
    # profile counters (subjects/diet_terms/product_titles/brands), so
    # whichever side's profile happened to carry more cross-test
    # accumulation at that point in the run could get a different
    # ranking tie-break - not a real behavior difference. This
    # intermittently failed on a different query each run ("sojova
    # omacka"/"suvisiace produkty k sushi ryzi" locally, "Kikkoman" in a
    # clean CI checkout). An earlier fix attempt gave only the legacy
    # side a distinct-but-fixed host, which made legacy permanently
    # FRESH while engine kept the suite-shared "127.0.0.1" identity -
    # trading intermittent flakiness for a consistent asymmetry instead
    # of removing it. Deriving the client_key from session_id (already
    # unique per call site throughout this file) keeps both sides
    # equally fresh and mutually isolated, with no dependency on test
    # execution order.
    return m._chat_internal(
        m.ChatRequest(message=message, session_id=session_id),
        _FakeRequestForClientKey(f"{session_id}.legacy"),
        execution_context=context,
    )


def _engine_chat(message: str, session_id: str, context=None) -> dict:
    request = AdvisorRequest(message=message, session_id=session_id, client_key=f"{session_id}.engine")
    return advisor_engine.run(request, context or evaluation_context())


_COMPARABLE_FIELDS = ("answered", "intent", "workflow_id", "response_mode", "no_result" if False else "has_more")


def _product_ids(response: dict) -> list[str]:
    return [p.get("id") for p in (response.get("products") or [])]


def _assert_equivalent(legacy: dict, engine: dict, *, context_label: str) -> None:
    assert legacy.get("answered") == engine.get("answered"), context_label
    assert legacy.get("intent") == engine.get("intent"), context_label
    assert legacy.get("workflow_id") == engine.get("workflow_id"), context_label
    assert _product_ids(legacy) == _product_ids(engine), context_label
    assert legacy.get("result_set_id") is not None or engine.get("result_set_id") is not None or "result_set_id" not in legacy, context_label


class TestAdvisorEngineIsIdentityPreservingWrapper:
    """AdvisorEngine.run() must produce byte-identical structured results
    to the legacy direct _chat_internal() call for the same inputs -
    it is a boundary, not a reimplementation."""

    def test_class_and_singleton_both_work(self):
        engine = AdvisorEngine()
        r1 = engine.run(AdvisorRequest(message="basmati ryza", session_id="ae-t1", client_key="k"), evaluation_context())
        r2 = advisor_engine.run(AdvisorRequest(message="basmati ryza", session_id="ae-t1b", client_key="k"), evaluation_context())
        assert r1.get("intent") == r2.get("intent") == "product_search"

    def test_engine_matches_legacy_for_product_search(self):
        legacy = _legacy_chat("basmati ryza", "ae-cmp-1", evaluation_context())
        engine = _engine_chat("basmati ryza", "ae-cmp-2", evaluation_context())
        _assert_equivalent(legacy, engine, context_label="basmati ryza")

    def test_engine_matches_legacy_for_recipe(self):
        legacy = _legacy_chat("recept na kokosove kura", "ae-cmp-3", evaluation_context())
        engine = _engine_chat("recept na kokosove kura", "ae-cmp-4", evaluation_context())
        _assert_equivalent(legacy, engine, context_label="recept na kokosove kura")

    def test_engine_matches_legacy_for_faq(self):
        legacy = _legacy_chat("ako mozem zaplatit?", "ae-cmp-5", evaluation_context())
        engine = _engine_chat("ako mozem zaplatit?", "ae-cmp-6", evaluation_context())
        _assert_equivalent(legacy, engine, context_label="faq")

    def test_engine_matches_legacy_for_allergen_query(self):
        legacy = _legacy_chat("sójová omáčka bez sóje", "ae-cmp-7", evaluation_context())
        engine = _engine_chat("sójová omáčka bez sóje", "ae-cmp-8", evaluation_context())
        _assert_equivalent(legacy, engine, context_label="allergen")

    def test_engine_customer_context_matches_chat_http_route(self):
        """The AdvisorEngine path chat() itself now uses (customer_context,
        real client_key derivation) must match a direct customer-context
        engine call with an equivalent client_key."""
        via_http_route = m.chat(m.ChatRequest(message="kokosovy olej", session_id="ae-http-1"), _FakeRequest())
        via_engine_direct = _engine_chat("kokosovy olej", "ae-http-2", customer_context())
        _assert_equivalent(via_http_route, via_engine_direct, context_label="kokosovy olej via chat() vs engine")


class TestBehaviorEquivalenceMatrix:
    """Section 31/32 - representative single-turn matrix, AdvisorEngine
    vs. legacy direct call, structured-field comparison."""

    QUERIES = (
        "jazmínová ryža",
        "basmati ryža",
        "ryžové rezance",
        "ryžový ocot",
        "sushi ryža",
        "Kikkoman",
        "Shin Ramyun",
        "rybacia omáčka",
        "tmavá sójová omáčka",
        "kokosové mlieko",
        "súvisiace produkty k sushi ryži",
        "sójová omáčka bez sóje",
        "náhrada za rybiu omáčku",
    )

    def test_matrix_structured_fields_match(self):
        mismatches = []
        for i, query in enumerate(self.QUERIES):
            legacy = _legacy_chat(query, f"ae-matrix-legacy-{i}", evaluation_context())
            engine = _engine_chat(query, f"ae-matrix-engine-{i}", evaluation_context())
            if (
                legacy.get("answered") != engine.get("answered")
                or legacy.get("intent") != engine.get("intent")
                or legacy.get("workflow_id") != engine.get("workflow_id")
                or _product_ids(legacy) != _product_ids(engine)
            ):
                mismatches.append((query, legacy.get("intent"), engine.get("intent")))
        assert not mismatches, f"UNEXPECTED_BEHAVIOR_DRIFT: {mismatches}"


class TestMultiTurnEquivalence:
    """Section 37 - multi-turn product refinement sequence, compared
    turn-by-turn between legacy and AdvisorEngine execution."""

    def _run_sequence(self, chat_fn, session_id: str) -> list[dict]:
        turns = ["jazmínová ryža", "len 5 kg", "radšej 1 kg", "lacnejšie"]
        responses = []
        for turn in turns:
            responses.append(chat_fn(turn, session_id, evaluation_context()))
        return responses

    def test_multi_turn_rice_refinement_matches(self):
        legacy_responses = self._run_sequence(_legacy_chat, "ae-multiturn-legacy")
        engine_responses = self._run_sequence(_engine_chat, "ae-multiturn-engine")
        assert len(legacy_responses) == len(engine_responses)
        for i, (legacy, engine) in enumerate(zip(legacy_responses, engine_responses)):
            assert legacy.get("intent") == engine.get("intent"), f"turn {i}"
            assert _product_ids(legacy) == _product_ids(engine), f"turn {i}"


class TestTopicSwitchEquivalence:
    """Section 36 - sushi -> Shin Ramyun must not leak stale context,
    identically in both paths."""

    def test_topic_switch_matches(self):
        legacy_1 = _legacy_chat("sushi ryza", "ae-topic-legacy", evaluation_context())
        legacy_2 = _legacy_chat("Shin Ramyun", "ae-topic-legacy", evaluation_context())
        engine_1 = _engine_chat("sushi ryza", "ae-topic-engine", evaluation_context())
        engine_2 = _engine_chat("Shin Ramyun", "ae-topic-engine", evaluation_context())
        assert _product_ids(legacy_2) == _product_ids(engine_2)
        assert legacy_2.get("intent") == engine_2.get("intent")


class TestCharacterization_rt0004_FIXED_ROUTING_REGRESSION:
    """V2.13a labeled this KNOWN_ROUTING_DEFECT_PENDING_V2_13B; V2.13b's
    WorkflowResolver (app.workflow_resolver, app.turn_resolver) fixes it
    generically - see docs/routing-debt.md and
    docs/workflow-precedence-before-v2.13b.md for the exact root cause
    (detect_special_product_subject() unconditionally nulled
    related_subject with no regard for explicit companion-language,
    "súvisiace"). This test now asserts the FIXED behavior and guards
    against it silently regressing back to product_search."""

    QUERY = "súvisiace produkty k sushi ryži"

    def test_resolves_to_related_products_not_plain_search(self):
        legacy = _legacy_chat(self.QUERY, "ae-rt0004-legacy", evaluation_context())
        engine = _engine_chat(self.QUERY, "ae-rt0004-engine", evaluation_context())
        assert legacy.get("intent") == engine.get("intent") == "related_products"
        assert _product_ids(legacy) == _product_ids(engine)
        # The anchor (sushi rice) must still inform the results, but the
        # PRIMARY workflow must return complementary products, not more
        # sushi rice packages (the old defect signature).
        titles = [p.get("title", "").lower() for p in (legacy.get("products") or [])]
        assert titles
        assert not all("ryž" in t or "ryz" in t for t in titles), "still returning only more rice, not complements"


class TestCharacterization_rt0010_FIXED_SAFETY_ROUTING_REGRESSION:
    """V2.13a labeled this KNOWN_SAFETY_ROUTING_GAP_PENDING_V2_13B;
    V2.13b's WorkflowResolver fixes it generically - see
    docs/routing-debt.md. Root cause: allergen_product_query() returning
    "" (a deliberate zero-safe-product signal for e.g. "bez soj") was
    conflated with "not applicable" by the old guard's boolean logic."""

    QUERY = "sójová omáčka bez sóje"

    def test_resolves_to_allergen_safety_with_no_unsupported_claim(self):
        legacy = _legacy_chat(self.QUERY, "ae-rt0010-legacy", evaluation_context())
        engine = _engine_chat(self.QUERY, "ae-rt0010-engine", evaluation_context())
        assert legacy.get("intent") == engine.get("intent") == "allergen_safety"
        # No unsupported "this product is soy-free" claim: zero products.
        assert _product_ids(legacy) == _product_ids(engine) == []
        assert legacy.get("answered") is True


class TestExactlyOnceSideEffects:
    """Section 39/40 - one CUSTOMER turn through AdvisorEngine must emit
    each applicable side effect exactly once, never duplicated by the
    engine boundary itself."""

    def test_one_customer_call_emits_exactly_one_quality_trace(self, tmp_path, monkeypatch):
        import app.search_quality as sq
        log_path = tmp_path / "sq.jsonl"
        monkeypatch.setattr(sq, "SEARCH_QUALITY_LOG_PATH", str(log_path))
        advisor_engine.run(AdvisorRequest(message="basmati ryza", session_id="ae-once-1", client_key="k"), customer_context())
        traces = sq.load_search_quality_traces(days=1, path=str(log_path))
        assert len(traces) == 1

    def test_one_customer_call_emits_exactly_one_question_analytics_line(self, tmp_path, monkeypatch):
        log_path = tmp_path / "questions.jsonl"
        monkeypatch.setenv("ANALYTICS_LOG_PATH", str(log_path))
        advisor_engine.run(AdvisorRequest(message="basmati ryza", session_id="ae-once-2", client_key="k"), customer_context())
        lines = log_path.read_text(encoding="utf-8").strip().splitlines() if log_path.exists() else []
        assert len(lines) == 1


class TestContextVarIsolationUnderConcurrency:
    """Section 42/56 - concurrent AdvisorEngine calls (different queries,
    different resolved families) must never leak each other's retrieval
    decision. Uses contextvars.copy_context().run() per submission, the
    same context-isolation mechanism Starlette actually uses for sync
    route handlers dispatched to its threadpool - a plain
    ThreadPoolExecutor.submit() alone would not reproduce that isolation."""

    def test_concurrent_calls_do_not_cross_contaminate_family(self):
        import contextvars
        from concurrent.futures import ThreadPoolExecutor

        queries = ["basmati ryza", "sojova omacka", "kokosovy olej", "udon rezance", "sushi ryza"] * 4

        def run_one(i, query):
            ctx = contextvars.copy_context()
            return ctx.run(lambda: _engine_chat(query, f"ae-concurrent-{i}", evaluation_context()))

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(run_one, i, q) for i, q in enumerate(queries)]
            results = [f.result() for f in futures]

        for query, result in zip(queries, results):
            titles = [p.get("title", "").lower() for p in (result.get("products") or [])]
            if "basmati" in query:
                assert all("ryž" in t or "ryz" in t for t in titles), (query, titles)
            if "sojova" in query:
                assert all("sój" in t or "soj" in t for t in titles), (query, titles)


class TestRateLimiting:
    """Section 24/59 - customer HTTP requests remain rate limited;
    internal AdvisorEngine execution (EVALUATION/ADMIN_TEST/...) is not,
    expressed purely through ExecutionContext, no isinstance(Request)
    check inside AdvisorEngine itself."""

    def test_customer_context_is_rate_limited_through_engine(self, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
        req = AdvisorRequest(message="basmati ryza", session_id="ae-ratelimit-1", client_key="ratelimit-test-key")
        advisor_engine.run(req, customer_context())
        advisor_engine.run(req, customer_context())
        with __import__("pytest").raises(m.HTTPException):
            advisor_engine.run(req, customer_context())

    def test_evaluation_context_is_never_rate_limited_through_engine(self, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "1")
        req = AdvisorRequest(message="basmati ryza", session_id="ae-ratelimit-2", client_key="ratelimit-test-key-2")
        for _ in range(5):
            advisor_engine.run(req, evaluation_context())


class TestInternalTrafficPoisoning:
    """Section 57 - mandatory: many EVALUATION/ADMIN_TEST AdvisorEngine
    calls must never increment the customer quality sample."""

    def test_many_internal_engine_calls_do_not_poison_customer_metrics(self, tmp_path, monkeypatch):
        import app.search_quality as sq
        from app.execution_context import admin_test_context
        log_path = tmp_path / "sq.jsonl"
        monkeypatch.setattr(sq, "SEARCH_QUALITY_LOG_PATH", str(log_path))
        for i in range(15):
            advisor_engine.run(AdvisorRequest(message=f"sojova omacka {i}", session_id=f"ae-poison-{i}", client_key="k"), evaluation_context())
        for i in range(15):
            advisor_engine.run(AdvisorRequest(message=f"rybacia omacka {i}", session_id=f"ae-poison-b-{i}", client_key="k"), admin_test_context())
        assert sq.load_search_quality_traces(days=1, path=str(log_path)) == []
        assert sq._read_raw_traces(days=1, path=str(log_path)) == []


class TestCharacterization_rt0013_CLOSED_BY_HUMAN_SEMANTIC_DECISION:
    """Section 30 - captured for equivalence only, NOT used as a
    migration acceptance criterion beyond "AdvisorEngine == legacy".
    rt0013 itself is now CLOSED (see module docstring) - this class name
    reflects that, but the test body is unchanged since it never
    encoded the old, now-corrected golden expectation."""

    QUERY = "náhrada za rybiu omáčku"

    def test_current_behavior_reproduced_not_judged(self):
        legacy = _legacy_chat(self.QUERY, "ae-rt0013-legacy", evaluation_context())
        engine = _engine_chat(self.QUERY, "ae-rt0013-engine", evaluation_context())
        assert legacy.get("intent") == engine.get("intent")
        assert _product_ids(legacy) == _product_ids(engine)


class TestCharacterization_rt0003_rt0027_FIXED_C2_ALLERGEN_PRODUCT_LEAKAGE:
    """V2.18d.3 (V2.18d.2 cluster C2) - end-to-end regression, through the
    real AdvisorEngine boundary rather than just the allergen_product_query()
    unit (see tests/test_core.py's
    test_allergen_product_query_robust_to_surface_variation). A general
    allergen-safety question (no specific product named) must return
    intent=="allergen_safety" with an EMPTY products list even under a
    single typo or a two-word reorder - previously, the query-builder
    fallback's exact-phrase matching broke under that variation and
    attached real catalog products (once, literally the allergen itself -
    "arasiidy" fuzzy-matched real peanut products) to what should have
    been a product-free safety disclaimer."""

    CASES = (
        "alergia na arašiidy, čo môžem kúpiť?",
        "na alergia arašidy, čo môžem kúpiť?",
        "mam alergiu na lepok, čo by ste dopuruučili?",
    )

    def test_no_products_attached_under_surface_variation(self):
        for i, message in enumerate(self.CASES):
            response = _engine_chat(message, f"ae-c2-{i}", evaluation_context())
            assert response.get("intent") == "allergen_safety", (message, response.get("intent"))
            assert _product_ids(response) == [], (message, _product_ids(response))

    def test_canonical_allergen_cases_still_functional(self):
        # Unaffected by the fix - a customer naming a specific known
        # product alongside an allergy question must still get it back.
        response = _engine_chat("je gochujang bez lepku?", "ae-c2-canonical", evaluation_context())
        assert response.get("intent") == "allergen_safety"
        assert _product_ids(response), "gochujang should still be attached"


class TestCharacterization_rt0024_FIXED_C3_FAQ_TOPIC_MISMATCH:
    """V2.18d.4 (V2.18d.2 cluster C3) - end-to-end regression through the
    real AdvisorEngine boundary. A generic "how can I pay?" question must
    resolve to the complete payment-methods FAQ answer, not the narrower
    "yes, card payment works in our physical store" record it previously
    lost to on raw keyword overlap (see
    tests/test_core.py::TestFAQ::test_faq_generic_payment_question_gets_full_methods_list
    for the query-builder unit coverage)."""

    def test_generic_payment_question_gets_full_methods_answer(self):
        response = _engine_chat("ako mozem zaplatit?", "ae-c3-generic", evaluation_context())
        assert response.get("intent") == "faq"
        normalized = m.normalize(response.get("answer") or "")
        assert "dobierka" in normalized
        assert "kartou" in normalized

    def test_instore_card_question_still_functional(self):
        response = _engine_chat("Mozem zaplatit kartou priamo v predajni?", "ae-c3-instore", evaluation_context())
        assert response.get("intent") == "faq"
        assert "predajni" in m.normalize(response.get("answer") or "")


class TestCharacterization_rt0002_FIXED_C6_WORD_ORDER_FRAGILITY:
    """V2.18d.8 (V2.18d.6 cluster C6) - end-to-end regression through the
    real AdvisorEngine boundary. "Niečo potrebujem bez lepku k sushi"
    (object-fronted, natural Slovak word order) must resolve identically
    to "Potrebujem niečo bez lepku k sushi" - both are the same request.
    Root cause: app.main._has_recipe_shopping_language()'s "co
    potrebujem" marker matched inside "nieco potrebujem" via a bare
    substring check (see
    tests/test_core.py::TestV2_18d8_RecipeShoppingLanguageWordBoundary
    for the marker-level unit coverage)."""

    def test_object_fronted_phrasing_matches_canonical_intent(self):
        canonical = _engine_chat("Potrebujem niečo bez lepku k sushi", "ae-c6-canonical", evaluation_context())
        fronted = _engine_chat("Niečo potrebujem bez lepku k sushi", "ae-c6-fronted", evaluation_context())
        assert canonical.get("intent") == fronted.get("intent") == "product_search"

    def test_object_fronted_phrasing_still_attaches_gluten_free_products(self):
        response = _engine_chat("Niečo potrebujem bez lepku k sushi", "ae-c6-fronted-products", evaluation_context())
        assert _product_ids(response), "gluten-free sushi products should still be attached"


class TestCharacterization_V219A01_FIXED_SHOPPING_LIST_CO_BOUNDARY:
    """V2.19b (V2.19a finding V219A-01) - end-to-end regression through
    the real AdvisorEngine boundary. Same root cause and same fix shape
    as C6/V2.18d.8, but in the sibling function wants_shopping_list() /
    SHOPPING_LIST_MARKERS, which that narrower fix deliberately left
    untouched. Both phrasings of the rt0002 pair must now be
    byte-identical in answer text, not just intent (see
    tests/test_core.py::TestV2_19b_ShoppingListCoBoundary for the
    marker-level unit coverage)."""

    def test_object_fronted_phrasing_produces_identical_answer_text(self):
        canonical = _engine_chat("Potrebujem niečo bez lepku k sushi", "ae-v219a01-canonical", evaluation_context())
        fronted = _engine_chat("Niečo potrebujem bez lepku k sushi", "ae-v219a01-fronted", evaluation_context())
        assert canonical.get("intent") == fronted.get("intent") == "product_search"
        assert canonical.get("answer") == fronted.get("answer")
        assert _product_ids(canonical) == _product_ids(fronted)
