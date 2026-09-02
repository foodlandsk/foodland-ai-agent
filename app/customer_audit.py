"""
app/customer_audit.py  -  V2.17.1: Customer Conversation Read-Only Audit API.

WHAT THIS IS: a read-only, privacy-conscious observability layer so a human
operator can inspect a REAL customer conversation together with the ACTUAL
Foodland AI response structure that customer was shown - what they asked,
what the backend understood, what it answered, which product groups it
returned, and which correlation identifiers (interaction_id/decision_id/
result_set_id) belong to that turn.

WHAT THIS IS NOT: not a learning sprint, not an evaluator, not a training-
label generator, not a ranking/promotion mechanism. `capture_customer_turn()`
appends an observation of an ALREADY-COMPLETED response - it never reruns
intent classification, search, ranking, cross-sell generation, or the LLM,
and it never feeds back into ranking/learning/promotion. AUTO_PROMOTION
stays FALSE; nothing here changes that.

CAPTURE BOUNDARY: called from app.main._chat_internal(), the single choke
point every /chat response (every workflow branch alike) already passes
through to get its interaction_id attached (V2.15b) - the same place the
existing search-quality trace already hooks in for the same reason. Gated
on `execution_context.is_customer_traffic` so only real CUSTOMER traffic
(never EVALUATION/LEARNING/SHADOW/ADMIN_TEST) is durably recorded. Runs
strictly AFTER the response dict is complete; captures a bounded, allow-
listed copy of it. A capture failure is caught internally and never
propagates - it cannot turn a valid /chat into an error, a different
response, or a duplicate response (Section 19 of the V2.17.1 spec).

PRIVACY MODEL: reuses the project's existing, proven mechanisms rather
than inventing a competing one -
  - app.main.redact_pii() (email/phone regex redaction), applied to
    question and answer BEFORE persistence, imported lazily (mirrors the
    deferred-import pattern app.advisor_engine already uses for the same
    reason: app.main is heavy and this module must not force-load it at
    import time, including for a fresh CI process that imports this
    module in isolation for testing).
  - The exact same salted-hash pattern app.main.log_question()/log_event()
    already use for `client_hash`: sha256(f"{salt}:...") truncated to 24
    hex chars, salt from ANALYTICS_SALT. Never the raw session_id/
    client_id/IP - only this one-way hash, and the salt is never exposed.

Never persisted: raw IP, raw client_id, raw session_id, headers, cookies,
authorization/admin tokens, full conversation_history, system prompts,
LLM prompts, secrets, env values, arbitrary request metadata, full product
objects (only an explicit small field allowlist), or internal-only fields
(cross_sell_evidence, taxonomy traces, etc.).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from app.storage_paths import resolve_path

logger = logging.getLogger(__name__)

_LOG_ENV_VAR = "CUSTOMER_AUDIT_LOG_PATH"
_LOG_FILENAME = "customer_audit.jsonl"

# Bounds (Section 8 of the spec) - defensive caps so one pathological
# response can never make a single audit record unbounded.
_QUESTION_MAX_CHARS = 1000
_ANSWER_MAX_CHARS = 5000
_TITLE_MAX_CHARS = 240
_REASON_MAX_CHARS = 500
_PRODUCTS_PER_GROUP_MAX = 24

# The only per-product fields ever persisted (Section 8: "never persist
# arbitrary full product objects"). Deliberately excludes description,
# embeddings, internal ranking scores, and cross_sell_evidence (structured
# evidence payload - useful for the backend decision, not for a compact
# audit row; GUARD 4 errs toward not persisting more than needed).
_PRODUCT_FIELD_ALLOWLIST = (
    "id",
    "title",
    "brand",
    "price",
    "sale_price",
    "effective_price",
    "currency",
    "availability",
    "link",
    "recommendation_group",
    "recommendation_reason",
    "cross_sell_role",
    "cross_sell_reason",
)

# Every workflow branch names its decision id differently
# (app/workflow_executor.py: comparison_decision_id, use_case_advice_
# decision_id, basket_decision_id, recipe_shopping_decision_id) while the
# structured_presentation/product_search branch has none at all (it uses
# result_set_id instead). Normalizing to one `decision_id` audit field is
# a pure dict-key lookup - no business logic is re-run to produce it
# (Section 7 explicitly allows this kind of safe normalization).
_DECISION_ID_KEYS = (
    "comparison_decision_id",
    "use_case_advice_decision_id",
    "basket_decision_id",
    "recipe_shopping_decision_id",
)


def _log_path() -> Path:
    return resolve_path(_LOG_ENV_VAR, _LOG_FILENAME)


def _conversation_hash(session_id: str, client_key: str) -> str:
    """Groups audit turns as the same conversation without ever storing a
    raw identifier. session_id is preferred (stable per browser session,
    already what the rest of the app keys memory/state on); client_key
    (IP-derived) is only a fallback for the rare case of an empty
    session_id, exactly as Section 9 specifies."""
    salt = os.getenv("ANALYTICS_SALT", "")
    identity = session_id.strip() or f"client:{client_key}"
    digest = hashlib.sha256(f"{salt}:audit:{identity}".encode("utf-8")).hexdigest()
    return digest[:24]


def _redact(text: str) -> str:
    # Deferred import (same reasoning app.advisor_engine documents for its
    # own deferred `import app.main`): app.main is a heavy module that
    # loads the catalog and warms search indexes on import, and this
    # module must be importable on its own (e.g. by tests) without paying
    # that cost. Safe here specifically because this function only ever
    # runs at call time, by which point app.main has already finished
    # importing this module - never at this module's own import time.
    from app.main import redact_pii

    return redact_pii(text or "")


def _bounded_text(value: Any, max_chars: int) -> str:
    text = str(value or "").strip()
    return text[:max_chars]


def _summarize_product(product: dict) -> dict:
    summary: dict[str, Any] = {}
    for field in _PRODUCT_FIELD_ALLOWLIST:
        if field not in product:
            continue
        value = product.get(field)
        if value is None:
            continue
        if field == "title":
            value = _bounded_text(value, _TITLE_MAX_CHARS)
        elif field in ("recommendation_reason", "cross_sell_reason"):
            value = _bounded_text(value, _REASON_MAX_CHARS)
        summary[field] = value
    return summary


def _summarize_product_group(products: Any) -> list[dict]:
    if not isinstance(products, list):
        return []
    bounded = products[:_PRODUCTS_PER_GROUP_MAX]
    return [_summarize_product(p) for p in bounded if isinstance(p, dict)]


def _first_present(response: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = response.get(key)
        if value:
            return str(value)
    return None


def capture_customer_turn(
    *,
    chat_request: Any,
    client_key: str,
    response: dict,
    latency_ms: float,
    status_code: int = 200,
) -> None:
    """Append one sanitized observation of an ALREADY-COMPLETED customer
    turn. Never raises - a capture failure is logged and swallowed so it
    can never affect the customer's actual /chat response (Section 19).
    Caller is responsible for gating this on real CUSTOMER traffic
    (execution_context.is_customer_traffic) before calling."""
    try:
        session_id = str(getattr(chat_request, "session_id", "") or "")
        question = _redact(str(getattr(chat_request, "message", "") or ""))
        answer = _redact(str(response.get("answer") or ""))

        record = {
            "ts": int(time.time()),
            "conversation_hash": _conversation_hash(session_id, client_key),
            "question": _bounded_text(question, _QUESTION_MAX_CHARS),
            "answer": _bounded_text(answer, _ANSWER_MAX_CHARS),
            "status_code": int(status_code),
            "latency_ms": round(float(latency_ms), 1),
            "interaction_id": response.get("interaction_id") or None,
            "decision_id": _first_present(response, _DECISION_ID_KEYS),
            "result_set_id": response.get("result_set_id") or None,
            "intent": response.get("intent") or None,
            "workflow_id": response.get("workflow_id") or None,
            "response_mode": response.get("response_mode") or None,
            "has_more": bool(response.get("has_more")) if "has_more" in response else None,
            "matching_total": response.get("matching_total"),
            "displayed_count": response.get("displayed_count"),
            "cross_sell_eligible": bool(response.get("cross_sell_eligible")) if "cross_sell_eligible" in response else None,
            "product_groups": {
                # GUARD 1: `products` and `cross_sell` stay separate keys,
                # exactly as they are separate, non-overlapping fields in
                # the real /chat response (app.cross_sell.build_cross_sell
                # already excludes primary-match ids before this point) -
                # never merged into one generic list. `products` itself
                # already carries whatever specific semantics `intent`
                # names for this turn (product_search/replacement_products/
                # related_products/article_products/product_advice/...) -
                # the audit does not invent separate alternatives/
                # substitutes/replacement_products arrays the actual
                # response schema does not expose (Section 7: repository
                # reality wins over the spec's conceptual example).
                "products": _summarize_product_group(response.get("products")),
                "cross_sell": _summarize_product_group(response.get("cross_sell")),
            },
        }
        _append_record(record)
    except Exception:
        logger.warning("Customer audit capture failed (non-fatal)", exc_info=True)


def _append_record(record: dict) -> None:
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_turns(days: int) -> list[dict]:
    path = _log_path()
    if not path.exists():
        return []
    safe_days = max(1, min(int(days or 7), 90))
    since = int(time.time()) - safe_days * 86400
    turns: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    # Section 6/14/21(#43): one corrupted row must never
                    # make the whole audit endpoint unavailable.
                    continue
                if not isinstance(record, dict):
                    continue
                ts = int(record.get("ts", 0) or 0)
                if ts >= since:
                    turns.append(record)
    except Exception:
        logger.warning("Failed to read customer audit log %s", path, exc_info=True)
        return []
    return turns


def read_audit_turns(
    days: int = 7,
    limit: int = 100,
    conversation_hash: str | None = None,
    intent: str | None = None,
    q: str | None = None,
) -> list[dict]:
    """READ-only accessor for GET /admin/audit/conversations. Newest
    first, bounded by `limit`. Filters operate only on already-redacted,
    already-persisted fields - no raw customer text is ever touched here."""
    safe_limit = max(1, min(int(limit or 100), 500))
    turns = _read_turns(days)

    if conversation_hash:
        turns = [t for t in turns if t.get("conversation_hash") == conversation_hash]
    if intent:
        wanted = intent.strip().lower()
        turns = [t for t in turns if str(t.get("intent") or "").strip().lower() == wanted]
    if q:
        needle = q.strip().lower()
        if needle:
            turns = [
                t for t in turns
                if needle in str(t.get("question") or "").lower()
                or needle in str(t.get("answer") or "").lower()
            ]

    turns.sort(key=lambda t: t.get("ts", 0), reverse=True)
    return turns[:safe_limit]


def audit_status() -> dict:
    """READ-only accessor for GET /admin/audit/status. Only non-sensitive
    operational information - no paths beyond a boolean existence check,
    no salts, no tokens, no customer identity."""
    from app.storage_paths import is_data_dir_configured

    path = _log_path()
    turns_last_24h = _read_turns(1)
    return {
        "readonly": True,
        "durable_data_dir_configured": is_data_dir_configured(),
        "log_exists": path.exists(),
        "turns_last_24h_up_to_500": min(len(turns_last_24h), 500),
    }
