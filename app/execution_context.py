"""
app/execution_context.py  -  V2.12.1 Part D: explicit internal execution
context.

Before this module, app.main._chat_impl() (then just chat()) decided
whether to rate-limit and log customer analytics with a single implicit
signal: `isinstance(request, Request)` - true for a real FastAPI/
Starlette request, false for app.evaluation.adapter's `_FakeRequest`
stand-in used by every internal caller (the V2.10 evaluation suite,
V2.11's shadow comparison, V2.12's candidate scoring). That check is a
correct hotfix for a real production incident (a learning cycle's
internal chat() calls tripped the customer-facing rate limiter - see
commit 8936188) but it is inference, not declaration: a caller's INTENT
("I am the evaluation harness") is derived from an accident of which
object shape it happened to pass as its second argument, rather than
stated up front.

Five modes, each an explicit, auditable declaration of why chat() is
being invoked:

  CUSTOMER    - real end-user traffic via POST /chat. Rate-limited,
                counted in customer analytics (log_question). The only
                mode where session-state writes touch a REAL customer's
                session.
  EVALUATION  - app.evaluation's golden/conversation suite (V2.10).
                Deterministic, high-volume, must never rate-limit itself
                or pollute customer-facing analytics.
  LEARNING    - app.ranking_optimizer.evaluate_profile() scoring a
                candidate profile for app.learning_candidates - same
                harness as EVALUATION, distinct label for observability.
  SHADOW      - app.ranking_shadow.shadow_compare() comparing baseline
                vs candidate order for the SAME query. Never touches
                config/ranking_profiles/active.json.
  ADMIN_TEST  - reserved for an operator manually exercising chat()
                through /admin tooling to sanity-check behavior without
                it counting as real traffic. Not currently wired to any
                endpoint - defined so a future admin diagnostic tool has
                an explicit mode to declare rather than inventing a sixth
                implicit convention.

Only CUSTOMER ever applies the customer-facing rate limit or writes to
question_analytics.jsonl via log_question(). Every other mode calls the
SAME real app.main._chat_impl() pipeline for the SAME correctness
guarantees a customer gets (Section 43's "never build a second ranking/
search system" applies here too) - just without side effects that do not
apply to internal tooling.

Migration note (Section 59): app.main._chat_impl() still falls back to
`isinstance(request, Request)` whenever no explicit ExecutionContext is
passed, so this is a strictly additive change - every existing caller
that has not been migrated to pass an explicit context keeps exactly its
pre-V2.12.1 behavior. The isinstance check is NOT removed by this
module; it becomes a documented fallback rather than the only mechanism.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ExecutionMode(str, Enum):
    CUSTOMER = "CUSTOMER"
    EVALUATION = "EVALUATION"
    LEARNING = "LEARNING"
    SHADOW = "SHADOW"
    ADMIN_TEST = "ADMIN_TEST"


@dataclass(frozen=True)
class ExecutionContext:
    mode: ExecutionMode
    apply_rate_limit: bool
    emit_customer_analytics: bool

    @property
    def is_customer_traffic(self) -> bool:
        return self.mode is ExecutionMode.CUSTOMER


def customer_context() -> ExecutionContext:
    return ExecutionContext(mode=ExecutionMode.CUSTOMER, apply_rate_limit=True, emit_customer_analytics=True)


def evaluation_context() -> ExecutionContext:
    return ExecutionContext(mode=ExecutionMode.EVALUATION, apply_rate_limit=False, emit_customer_analytics=False)


def learning_context() -> ExecutionContext:
    return ExecutionContext(mode=ExecutionMode.LEARNING, apply_rate_limit=False, emit_customer_analytics=False)


def shadow_context() -> ExecutionContext:
    return ExecutionContext(mode=ExecutionMode.SHADOW, apply_rate_limit=False, emit_customer_analytics=False)


def admin_test_context() -> ExecutionContext:
    return ExecutionContext(mode=ExecutionMode.ADMIN_TEST, apply_rate_limit=False, emit_customer_analytics=False)
