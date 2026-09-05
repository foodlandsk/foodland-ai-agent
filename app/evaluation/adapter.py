"""
app/evaluation/adapter.py  -  V2.10 production adapter

The ONLY module in app/evaluation that imports app.main (a heavy module -
loads the catalog, warms search indexes). Everything else in this package
takes a `chat_fn`/`taxonomy_index` as plain arguments so it stays cheap to
unit test (Section 100) and provably decoupled from the running app
(Section 52 - the evaluator observes, it never becomes a second
implementation of search).
"""
from __future__ import annotations

import os

# The evaluation suite makes far more chat() calls per minute than a real
# customer ever would (Section 45 - deterministic, batched, no network) -
# raise the same way tests/test_core.py and tests/test_integration.py
# already do for the exact same reason, rather than requiring a running
# eval to somehow throttle itself against a customer-facing safety limit
# it isn't subject to. setdefault() so an explicit env var always wins.
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

# V2.19d: MODULE-level, not per-closure - make_chat_fn() is called fresh
# by every test file, every benchmark run, and app.ranking_shadow.
# shadow_compare() itself, each producing its OWN closure. A per-closure
# counter starting at 0 makes every closure's first call collide on the
# same "eval-isolated-1" identifier, silently defeating the isolation it
# was meant to provide the moment more than one closure exists in the
# same process (which is the normal case, not an edge case). One shared
# counter guarantees every call across the whole process gets a
# genuinely unique ordinal, while staying deterministic (Section 45 -
# no real randomness).
_call_counter = {"n": 0}


def make_chat_fn(*, execution_context=None):
    """Returns a `chat_fn(query, limit) -> dict` closure over the real
    Advisor application boundary (V2.13a: app.advisor_engine.AdvisorEngine
    - see docs/advisor-engine.md) - same code path a live customer request
    takes, deterministic (LOCAL_TESTING avoids network egress: same
    fixture data/products.json every run, Section 45).

    V2.12.1 Part D: calls the Advisor with an explicit ExecutionContext
    (default EVALUATION) rather than app.main.chat() - see
    app/execution_context.py's module docstring.

    V2.13a: previously constructed its own duck-typed `_FakeRequest` and
    called app.main._chat_internal() directly - now goes through
    AdvisorEngine, which owns that shim internally (one implementation
    instead of a copy in every internal caller, see
    docs/v2.13a-current-execution-map.md). Behavior is unchanged -
    AdvisorEngine.run() delegates to the exact same _chat_internal().

    Each call gets its OWN isolated session_id, one per (query, limit)
    pair. A real, load-bearing bug was found building this adapter: an
    early version sent every golden case through the SAME session (empty
    session_id -> the same anonymous fallback key for the whole run,
    app.main.session_memory_key), so V2.9 session state from one golden
    case leaked into the next - the exact class of contamination bug
    V2.9 itself exists to prevent. Fixed by giving every independent
    single-turn case a fresh, isolated session (Section 45 - the fix
    itself must stay deterministic, so the id is derived from the query
    text and an incrementing counter, never real randomness).

    V2.19d (docs/routing-debt.md V2.19c state-isolation audit): the
    isolation above only ever covered session_id - client_key was a
    single hardcoded "eval-adapter" for every call. app.main.user_memory_key()
    derives its personalization-profile key from client_key (hashed)
    whenever client_id is empty, which it always is here, so EVERY
    caller of this adapter - every V2.10 golden case, every V2.18/19
    benchmark scenario, every app.ranking_shadow.shadow_compare() call -
    shared and mutated ONE personalization profile. Confirmed via a
    controlled ablation (V2.19c) to measurably change an unrelated
    later query's candidate set. Reusing the already-unique session_id
    as client_key closes this the same way session_id itself was fixed
    above - one isolated identity per call, no shared bucket. Doing so
    also surfaced that the counter itself was per-closure, not
    per-process: every fresh make_chat_fn() call (every test file,
    every benchmark run, shadow_compare() internally) restarted its own
    counter at 0, so two different closures' first calls both produced
    "eval-isolated-1" - collision, not isolation. _call_counter is
    module-level so every call across the whole process gets a
    genuinely unique ordinal."""
    from app.advisor_engine import advisor_engine, AdvisorRequest
    from app.execution_context import evaluation_context

    ctx = execution_context if execution_context is not None else evaluation_context()

    def chat_fn(query: str, limit: int) -> dict:
        _call_counter["n"] += 1
        session_id = f"eval-isolated-{_call_counter['n']}"
        request = AdvisorRequest(message=query, limit=limit, session_id=session_id, client_key=session_id)
        return advisor_engine.run(request, ctx)

    return chat_fn


def get_taxonomy_index() -> dict:
    import app.main as m
    return m.product_taxonomy_index


def make_session_chat_fn(*, execution_context=None):
    """Session-aware variant for conversation-sequence evaluation
    (Section 29) - caller supplies session_id per turn. See make_chat_fn()
    above for why this goes through AdvisorEngine with an explicit
    ExecutionContext (default EVALUATION) instead of app.main.chat().

    V2.19d: client_key is derived from the caller's session_id (not a
    shared constant - see make_chat_fn()'s V2.19d note for the full
    root cause), so different scenarios/sessions get isolated
    personalization profiles while every turn of the SAME multi-turn
    conversation still shares one profile - that continuity is
    intentional (Section 29's whole point), not the bug."""
    from app.advisor_engine import advisor_engine, AdvisorRequest
    from app.execution_context import evaluation_context

    ctx = execution_context if execution_context is not None else evaluation_context()

    def chat_fn(query: str, limit: int, session_id: str) -> dict:
        request = AdvisorRequest(message=query, limit=limit, session_id=session_id, client_key=f"eval-session-{session_id}")
        return advisor_engine.run(request, ctx)

    return chat_fn


def get_session_memory(session_id: str) -> dict:
    import app.main as m
    return m.get_session_memory(session_id)
