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


def make_chat_fn():
    """Returns a `chat_fn(query, limit) -> dict` closure over the real,
    already-imported app.main.chat() - same code path a live customer
    request takes, deterministic (LOCAL_TESTING avoids network egress:
    same fixture data/products.json every run, Section 45).

    Each call gets its OWN isolated session_id, one per (query, limit)
    pair. A real, load-bearing bug was found building this adapter: an
    early version sent every golden case through the SAME session (empty
    session_id -> the same anonymous fallback key for the whole run,
    app.main.session_memory_key), so V2.9 session state from one golden
    case leaked into the next - the exact class of contamination bug
    V2.9 itself exists to prevent. Fixed by giving every independent
    single-turn case a fresh, isolated session (Section 45 - the fix
    itself must stay deterministic, so the id is derived from the query
    text and an incrementing counter, never real randomness)."""
    import app.main as m

    class _FakeRequest:
        class client:
            host = "127.0.0.1"
        headers = {}

    counter = {"n": 0}

    def chat_fn(query: str, limit: int) -> dict:
        counter["n"] += 1
        session_id = f"eval-isolated-{counter['n']}"
        request = m.ChatRequest(message=query, limit=limit, session_id=session_id)
        return m.chat(request, _FakeRequest())

    return chat_fn


def get_taxonomy_index() -> dict:
    import app.main as m
    return m.product_taxonomy_index


def make_session_chat_fn():
    """Session-aware variant for conversation-sequence evaluation
    (Section 29) - one FakeRequest, caller supplies session_id per turn."""
    import app.main as m

    class _FakeRequest:
        class client:
            host = "127.0.0.1"
        headers = {}

    def chat_fn(query: str, limit: int, session_id: str) -> dict:
        request = m.ChatRequest(message=query, limit=limit, session_id=session_id)
        return m.chat(request, _FakeRequest())

    return chat_fn


def get_session_memory(session_id: str) -> dict:
    import app.main as m
    return m.get_session_memory(session_id)
