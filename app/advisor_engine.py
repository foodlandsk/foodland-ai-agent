"""
app/advisor_engine.py  -  V2.13a: AdvisorEngine application boundary.

WHAT THIS IS: a thin, named seam between transport (HTTP, or any internal
caller) and the existing production orchestration in app.main. It exists
so CUSTOMER, EVALUATION, LEARNING, SHADOW, ADMIN_TEST and CANARY execution
can all reach the Advisor through one function, without any of them
needing to construct a duck-typed FastAPI Request just to satisfy
app.main.get_client_key()'s shape - a pattern that, before this module,
was independently re-implemented in at least 6 places across the repo
(see docs/v2.13a-current-execution-map.md).

WHAT THIS IS NOT (Invariant #1/#2, V2.13a spec): this is not the V2.13b
WorkflowResolver. AdvisorEngine.run() delegates to app.main._chat_internal()
/_chat_impl() completely unchanged - not one line of routing, intent
classification, retrieval, ranking, taxonomy, session, or presentation
logic was moved, copied, or altered to create this module. The entire
~1160-line _chat_impl() cascade is, for V2.13a's purposes, the
"LegacyOrchestrationAdapter" the spec asks for - it already meets that
bar (a single function AdvisorEngine can call), so no separate adapter
class was introduced merely to have one (Section 14: do not move the
monolith just to relabel it).

Target architecture (V2.13a, current):

    HTTP /chat -> AdvisorEngine.run() -> app.main._chat_internal() (unchanged)
    Evaluation/Learning/Shadow/Canary -> AdvisorEngine.run() -> same

Target architecture (V2.13b, NOT built here):

    AdvisorEngine -> TurnResolver -> WorkflowResolver -> WorkflowHandler -> Domain Services
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AdvisorRequest:
    """Application-level request contract (Section 15). Deliberately does
    NOT carry a FastAPI Request, HTTP headers, or ASGI scope - only
    `client_key`, the one piece of already-resolved, trusted metadata
    app.main.get_client_key() would otherwise derive from a real request
    (source IP / X-Forwarded-For). The HTTP adapter resolves that before
    calling in; every other caller (evaluation, canary, ...) supplies its
    own stable synthetic value."""

    message: str
    session_id: str = ""
    limit: int = 6
    conversation_history: list[dict] = field(default_factory=list)
    client_id: str = ""
    client_key: str = "internal"


# AdvisorResponse (Section 16): deliberately a plain dict, not a new
# wrapper class. The existing /chat response shape (answer, products,
# recipes, articles, workflow_id, workflow_confidence, result_set fields,
# answered, cross_sell, ...) is already a stable, tested, documented
# contract used by ~40+ existing call sites and the public HTTP API - Section
# 60 explicitly forbids redesigning it. Wrapping it in a dataclass here
# would only add an unwrap step to every caller for zero behavioral gain.
# The type alias exists so this module still names the contract, per
# Section 16, without forcing a migration nobody asked for.
AdvisorResponse = dict[str, Any]


class _TrustedClientKeyRequest:
    """Internal-only shim (Section 19: "Do not pass raw FastAPI Request
    through the engine merely for convenience"). app.main.get_client_key()
    reads `.headers.get("x-forwarded-for")` and `.client.host` - this
    gives it exactly that shape, pre-loaded with an already-resolved
    client_key, so get_client_key() returns it verbatim without parsing
    any real headers. Never constructed by, or exposed to, any
    AdvisorEngine caller - it exists only inside this module, replacing
    the ad-hoc `_FakeRequest` classes previously duplicated across
    app/evaluation/adapter.py, scripts/run_search_quality_canary.py, and
    app/main.py's own admin canary endpoint."""

    class client:
        host = ""

    headers: dict = {}

    def __init__(self, client_key: str) -> None:
        self.client = type(self).client()
        self.client.host = client_key or "internal"
        self.headers = {}


class AdvisorEngine:
    """Application entry point (Section 13). One instance is stable to
    reuse across calls (Section 46/55) - it holds no per-request state of
    its own; all per-request state already lives in app.main's module-
    level catalog/index globals (Section 45 - not redesigned here) and the
    V2.12.4 ContextVar (isolated per request by Starlette's context
    handling, Section 42 - unchanged by this module)."""

    def run(self, advisor_request: AdvisorRequest, execution_context) -> AdvisorResponse:
        """Delegates entirely to app.main._chat_internal() - the existing,
        unchanged, single unified exit point for every chat() workflow
        branch (see docs/v2.13a-current-execution-map.md). Deferred import
        (not at module load time) for the same reason app.learning_events/
        app.evaluation.adapter defer it: app.main is a heavy module (loads
        the catalog, warms search indexes) that importing this module
        should not force on unrelated callers/tests."""
        import app.main as _main

        chat_request = _main.ChatRequest(
            message=advisor_request.message,
            limit=advisor_request.limit,
            conversation_history=advisor_request.conversation_history,
            session_id=advisor_request.session_id,
            client_id=advisor_request.client_id,
        )
        shim_request = _TrustedClientKeyRequest(advisor_request.client_key)
        return _main._chat_internal(chat_request, shim_request, execution_context=execution_context)


# Module-level singleton (Section 46) - safe to share since AdvisorEngine
# itself is stateless; app.main's own globals remain the single source of
# truth for catalog/index/config state, unchanged by this module.
advisor_engine = AdvisorEngine()
