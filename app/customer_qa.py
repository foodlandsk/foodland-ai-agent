"""
app/customer_qa.py  -  V2.17.2: Customer QA Analyzer & Evidence Layer.

WHAT THIS IS: a deterministic, evidence-based QA analysis layer on top of
the V2.17.1 sanitized customer conversation audit
(app.customer_audit.read_audit_turns()). Helps a human operator find
which real customer conversations show STRUCTURAL evidence of a possible
problem, at which architectural layer it plausibly belongs, and what
exact evidence supports that - never an automatic verdict, never a
training label, never a production behavior change.

    OBSERVATION (V2.17.1) -> ANALYSIS (this module) -> EVIDENCE -> HUMAN
    INVESTIGATION

    never:

    OBSERVATION -> AUTOMATIC LABEL -> LEARNING -> RANKING CHANGE -> DEPLOY

WHAT THIS IS NOT: not a learning sprint, not an evaluator, not a
training-label generator. `analyze_turn()`/`qa_findings()` only ever READ
already-persisted, already-sanitized app.customer_audit records - they
never touch retrieval/ranking/recommendation/cross-sell/learning/
promotion, never call an LLM, never call search, and never write to
customer_audit.jsonl (that stream is immutable input here - Section 31).
AUTO_PROMOTION stays FALSE; nothing here changes that.

ARCHITECTURE: ON-READ analysis, not a separate persisted findings store.
GET /admin/qa/findings reads sanitized audit turns fresh and runs the
deterministic rules in-memory on every request. Chosen over a persisted
`customer_qa_findings.jsonl` (Section 18/22's option B) because it is
strictly simpler and trivially satisfies every guard at once: zero
duplicate-finding risk (Section 19 - nothing is ever appended, so there
is nothing to deduplicate), zero /chat latency impact (Section 32 -
analysis only runs when an admin GETs the endpoint, never in the
customer request path), zero new runtime storage to manage, and full
reproducibility (same audit data + same rule version always yields the
same findings). `qa_id` is still a stable, deterministic hash per
(interaction/conversation identity, rule_id, rule_version) purely for
finding IDENTITY across repeated reads - not because anything is
persisted.

WARNING BUILT INTO THIS MODULE'S OWN DESIGN (Section 4 - the "observation
!= truth" guard): every rule here checks a STRUCTURAL or TEXTUAL
contradiction in the already-recorded response - never a behavioral
signal (click/no-click/cart/feedback) and never a subjective preference.
A rule firing means "the response contradicts its own stated structure"
or "a known-bad text pattern is present," not "the recommendation was
wrong." PASS means no configured rule found a problem - never "the
answer was objectively perfect" (Section 25).
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Callable

from app.customer_audit import read_audit_turns

logger = logging.getLogger(__name__)

# Section 5/6 - the canonical classification taxonomy. UNDERSTAND/
# RETRIEVE/RANK/GROUND/DATA are declared here (repository-reality-wins:
# they are real, named categories a future rule MAY use) but this sprint
# deliberately implements NO rule that emits them yet - see docs/
# customer-qa-analyzer-v2.17.2.md "false-negative philosophy" for why:
# assessing retrieval completeness or ranking correctness needs ground
# truth this module does not have; a sanitized audit record alone cannot
# prove what SHOULD have been retrieved. Fabricating such a rule from
# insufficient evidence would violate Section 4/Section 12's own
# "implement only rules supported by strong evidence" mandate. Only
# COMPOSE/PRESENT/CROSS_SELL/SAFETY_TRUST have real rules below, each
# backed by a structural or known-pattern check on data actually present
# in the record.
CLASSIFICATIONS = (
    "UNDERSTAND",
    "RETRIEVE",
    "RANK",
    "COMPOSE",
    "GROUND",
    "PRESENT",
    "CROSS_SELL",
    "DATA",
    "SAFETY_TRUST",
)

SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
CONFIDENCE_LEVELS = ("LOW", "MEDIUM", "HIGH")
STATUSES = ("PASS", "FINDING", "UNCERTAIN")

RECOMMENDED_ACTIONS = (
    "NO_ACTION",
    "REVIEW_CONVERSATION",
    "CHECK_CATALOG_DATA",
    "CHECK_KNOWLEDGE",
    "CHECK_RETRIEVAL",
    "CHECK_RANKING",
    "CHECK_PRESENTATION",
    "CREATE_REPRODUCTION_TEST",
    "SECURITY_REVIEW",
)

_ANSWER_EXCERPT_MAX_CHARS = 300

# Section 6 COMPOSE examples: the answer's own natural-language claim
# contradicts the structural data in the same record. Markers are
# lowercase, diacritic-stripped substrings (same loose-match convention
# app.knowledge._is_broken_curation_placeholder() already uses) since
# Slovak customer-facing copy is not guaranteed diacritic-consistent.
_NO_RESULTS_MARKERS = ("nenasla som", "nenasiel som", "nenaslo sa", "ziadne produkty")
_ALTERNATIVES_CLAIM_MARKERS = ("alternativ", "nahrad")
_CROSS_SELL_CLAIM_MARKERS = ("hodi sa k tomu", "hodi sa aj", "co sa hodi")

# Section 14 stock guard - the exact forbidden wording V2.17 removed from
# app/widget.js. "Dostupne na Foodland.sk" (the V2.17 replacement) is
# deliberately NOT flagged - it is catalog-presence wording, not a live-
# stock claim, and must not be treated as evidence of a problem.
_FORBIDDEN_STOCK_MARKERS = ("skladom", "potvrdena skladova zasoba", "overena dostupnost na sklade")


def _strip_diacritics_lower(text: str) -> str:
    # Same normalization the answer text itself already goes through
    # loosely - a plain .lower() is sufficient here because every marker
    # list above is itself diacritic-free, matching the established
    # app.knowledge._is_broken_curation_placeholder() convention (a
    # substring match against .lower() text, not a full normalize()).
    return str(text or "").lower()


def _qa_id(identity: str, rule_id: str, rule_version: str) -> str:
    digest = hashlib.sha256(f"{identity}:{rule_id}:{rule_version}".encode("utf-8")).hexdigest()
    return digest[:24]


def _turn_identity(turn: dict) -> str:
    return str(turn.get("interaction_id") or f"{turn.get('conversation_hash', '')}:{turn.get('ts', 0)}")


def _answer_excerpt(turn: dict) -> str:
    answer = str(turn.get("answer") or "")
    return answer[:_ANSWER_EXCERPT_MAX_CHARS]


def _evidence(turn: dict, extra: dict | None = None) -> dict:
    evidence = {
        "question": str(turn.get("question") or ""),
        "answer_excerpt": _answer_excerpt(turn),
        "intent": turn.get("intent"),
        "workflow_id": turn.get("workflow_id"),
        "groups": {
            "products": turn.get("product_groups", {}).get("products", []),
            "cross_sell": turn.get("product_groups", {}).get("cross_sell", []),
        },
    }
    if extra:
        evidence.update(extra)
    return evidence


def _make_finding(
    turn: dict,
    *,
    rule_id: str,
    rule_version: str,
    classification: str,
    severity: str,
    confidence: str,
    finding: str,
    recommended_action: str,
    evidence_extra: dict | None = None,
) -> dict:
    assert classification in CLASSIFICATIONS
    assert severity in SEVERITIES
    assert confidence in CONFIDENCE_LEVELS
    assert recommended_action in RECOMMENDED_ACTIONS
    identity = _turn_identity(turn)
    return {
        "qa_id": _qa_id(identity, rule_id, rule_version),
        "rule_id": rule_id,
        "rule_version": rule_version,
        "conversation_hash": turn.get("conversation_hash"),
        "interaction_id": turn.get("interaction_id"),
        "decision_id": turn.get("decision_id"),
        "result_set_id": turn.get("result_set_id"),
        "classification": classification,
        "severity": severity,
        "confidence": confidence,
        "finding": finding,
        "evidence": _evidence(turn, evidence_extra),
        "recommended_action": recommended_action,
        # Section 9/26 - a hard-coded false constant, never computed from
        # the finding, so a future rule cannot accidentally set it true.
        # V2.17.2 has no fix/deploy/train/promote action anywhere in this
        # module (Section 24/26) - this field exists purely so a reader
        # of the JSON does not have to infer that from the module's
        # source code.
        "automatic_production_change": False,
    }


# ---------------------------------------------------------------------
# Rule family A - structural consistency (Section 12.A, 13)
# ---------------------------------------------------------------------

def _rule_cross_sell_overlaps_products(turn: dict) -> dict | None:
    """QA_STRUCT_001 - app.cross_sell.build_cross_sell() has excluded
    every primary-match id from its candidates since V2.6 (exclude_ids =
    structured_presentation.ranked_product_ids); V2.17 made cross-sell
    customer-visible on the strength of that guarantee. If a product id
    ever appears in BOTH groups in the same turn, that guarantee was
    structurally violated for a real customer - a genuine backend
    contract break, not a preference judgment (Section 13's cross-sell
    guard: matches != cross_sell must always hold)."""
    groups = turn.get("product_groups") or {}
    product_ids = {p.get("id") for p in groups.get("products") or [] if p.get("id")}
    cross_sell_ids = {p.get("id") for p in groups.get("cross_sell") or [] if p.get("id")}
    overlap = product_ids & cross_sell_ids
    if not overlap:
        return None
    return _make_finding(
        turn,
        rule_id="QA_STRUCT_001",
        rule_version="1",
        classification="CROSS_SELL",
        severity="MEDIUM",
        confidence="HIGH",
        finding=f"Product id(s) {sorted(overlap)} appear in both `products` and `cross_sell` for the same turn - the backend's own dedup guarantee (cross_sell never overlaps primary matches) did not hold.",
        recommended_action="CREATE_REPRODUCTION_TEST",
        evidence_extra={"overlapping_ids": sorted(overlap)},
    )


def _rule_cross_sell_eligible_but_empty(turn: dict) -> dict | None:
    """QA_STRUCT_002 - cross_sell_eligible=True is the backend's own
    claim that a customer-visible cross-sell section exists for this
    turn; an empty cross_sell array contradicts that claim. Low severity
    (the widget's own frontend guard - `crossSellProducts.length > 0` -
    already prevents this from ever rendering an empty section to the
    customer) but still a genuine metadata inconsistency worth a human
    look."""
    if turn.get("cross_sell_eligible") is not True:
        return None
    groups = turn.get("product_groups") or {}
    if groups.get("cross_sell"):
        return None
    return _make_finding(
        turn,
        rule_id="QA_STRUCT_002",
        rule_version="1",
        classification="CROSS_SELL",
        severity="LOW",
        confidence="HIGH",
        finding="cross_sell_eligible=True but the cross_sell product group is empty for this turn.",
        recommended_action="CHECK_PRESENTATION",
    )


def _rule_has_more_contradicts_counts(turn: dict) -> dict | None:
    """QA_STRUCT_003 - has_more=True asserts there are more results
    beyond what was shown; matching_total/displayed_count are the same
    turn's own counts of that claim. If displayed_count already covers
    (or exceeds) matching_total, has_more cannot honestly be True.
    Requires both counts to be present ints - never guesses from a
    missing field (Section 4 - missing evidence is UNKNOWN, not FALSE)."""
    if turn.get("has_more") is not True:
        return None
    matching_total = turn.get("matching_total")
    displayed_count = turn.get("displayed_count")
    if not isinstance(matching_total, int) or not isinstance(displayed_count, int):
        return None
    if displayed_count < matching_total:
        return None
    return _make_finding(
        turn,
        rule_id="QA_STRUCT_003",
        rule_version="1",
        classification="PRESENT",
        severity="LOW",
        confidence="HIGH",
        finding=f"has_more=True but displayed_count ({displayed_count}) already covers matching_total ({matching_total}).",
        recommended_action="CHECK_PRESENTATION",
        evidence_extra={"matching_total": matching_total, "displayed_count": displayed_count},
    )


# ---------------------------------------------------------------------
# Rule family B - trust / safety (Section 12.B, 14, 29)
# ---------------------------------------------------------------------

def _rule_prompt_leak_marker(turn: dict) -> dict | None:
    """QA_TRUST_001 - reuses app.knowledge._is_broken_curation_placeholder()
    (the exact, proven V2.16e permanent guard - the same real incident
    where curation-pipeline prompt-template text leaked into a customer-
    facing answer), applied here to the AUDITED answer text rather than
    a Products_AI record. Detects the same known pattern surviving into
    what a real customer actually saw. Deliberately does NOT read or
    expose the underlying system prompt/template itself (Section 29) -
    only reports THAT the pattern matched."""
    from app.knowledge import _is_broken_curation_placeholder

    answer = str(turn.get("answer") or "")
    if not answer or not _is_broken_curation_placeholder(answer):
        return None
    return _make_finding(
        turn,
        rule_id="QA_TRUST_001",
        rule_version="1",
        classification="SAFETY_TRUST",
        severity="CRITICAL",
        confidence="MEDIUM",
        finding="Customer-facing answer contains a known internal curation-template pattern (V2.16e prompt-leak signature).",
        recommended_action="SECURITY_REVIEW",
    )


def _rule_pii_pattern_in_stored_text(turn: dict) -> dict | None:
    """QA_TRUST_002 - defense-in-depth: question/answer are redacted by
    app.main.redact_pii() BEFORE persistence (V2.17.1), so this SHOULD
    never fire. If a literal email pattern is still present in the
    ALREADY-STORED (supposedly redacted) text, that is real evidence the
    redaction step itself was bypassed or incomplete for this turn -
    high severity, since it means PII may already be durably persisted."""
    import re

    email_pattern = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    for field in ("question", "answer"):
        text = str(turn.get(field) or "")
        if email_pattern.search(text) and "[email]" not in text:
            return _make_finding(
                turn,
                rule_id="QA_TRUST_002",
                rule_version="1",
                classification="SAFETY_TRUST",
                severity="HIGH",
                confidence="HIGH",
                finding=f"Stored `{field}` still contains an email-like pattern despite the V2.17.1 redaction step.",
                recommended_action="SECURITY_REVIEW",
            )
    return None


def _rule_forbidden_stock_wording(turn: dict) -> dict | None:
    """QA_STOCK_001 (Section 14) - "Skladom" was removed from app/
    widget.js in V2.17 precisely because data/products.json's
    availability field is a static catalog-presence flag, never live
    warehouse stock. If that forbidden wording still reaches a customer-
    facing answer through any other path (e.g. an AI-generated answer,
    not the widget template), it is the same false-certainty claim V2.17
    already classified as a release blocker. "Dostupne na Foodland.sk"
    is explicitly NOT flagged - it is the correct, truthful wording."""
    answer_lower = _strip_diacritics_lower(turn.get("answer"))
    for marker in _FORBIDDEN_STOCK_MARKERS:
        if marker in answer_lower:
            return _make_finding(
                turn,
                rule_id="QA_STOCK_001",
                rule_version="1",
                classification="SAFETY_TRUST",
                severity="MEDIUM",
                confidence="MEDIUM",
                finding=f'Answer contains forbidden stock-certainty wording ("{marker}") not supported by catalog-presence-only data.',
                recommended_action="SECURITY_REVIEW",
            )
    return None


# ---------------------------------------------------------------------
# Rule family C - response/structure consistency (Section 12.C)
# ---------------------------------------------------------------------

def _rule_no_results_claim_but_products_present(turn: dict) -> dict | None:
    """QA_COMPOSE_001 - the answer text asserts nothing was found while
    the same turn's own product_groups.products is non-empty. Text-
    pattern based (MEDIUM confidence, not HIGH - a marker phrase could
    in principle appear in an unrelated grammatical context)."""
    answer_lower = _strip_diacritics_lower(turn.get("answer"))
    if not any(marker in answer_lower for marker in _NO_RESULTS_MARKERS):
        return None
    products = (turn.get("product_groups") or {}).get("products") or []
    if not products:
        return None
    return _make_finding(
        turn,
        rule_id="QA_COMPOSE_001",
        rule_version="1",
        classification="COMPOSE",
        severity="MEDIUM",
        confidence="MEDIUM",
        finding="Answer text claims nothing was found, but the `products` group for this turn is non-empty.",
        recommended_action="REVIEW_CONVERSATION",
    )


def _rule_alternatives_claim_but_empty(turn: dict) -> dict | None:
    """QA_COMPOSE_002 - the answer text claims alternatives/cross-sell
    exist below it, but the corresponding group is empty. Only checks
    the alternatives claim against `products` (the group that carries
    replacement_products/alternatives semantics per intent - Section 9
    of docs/customer-conversation-audit-api-v2.17.1.md) and the cross-
    sell claim against `cross_sell` specifically, never conflating the
    two (Section 13's cross-sell guard)."""
    answer_lower = _strip_diacritics_lower(turn.get("answer"))
    groups = turn.get("product_groups") or {}

    if any(marker in answer_lower for marker in _ALTERNATIVES_CLAIM_MARKERS) and not groups.get("products"):
        return _make_finding(
            turn,
            rule_id="QA_COMPOSE_002",
            rule_version="1",
            classification="COMPOSE",
            severity="LOW",
            confidence="MEDIUM",
            finding="Answer text references alternatives/substitutes, but the `products` group for this turn is empty.",
            recommended_action="REVIEW_CONVERSATION",
        )
    if any(marker in answer_lower for marker in _CROSS_SELL_CLAIM_MARKERS) and not groups.get("cross_sell"):
        return _make_finding(
            turn,
            rule_id="QA_COMPOSE_003",
            rule_version="1",
            classification="COMPOSE",
            severity="LOW",
            confidence="MEDIUM",
            finding="Answer text references cross-sell companions, but the `cross_sell` group for this turn is empty.",
            recommended_action="REVIEW_CONVERSATION",
        )
    return None


# Ordered so structural/high-confidence rules run first - order does not
# affect which rules fire (every rule is independently evaluated against
# the same turn), only the order findings appear within one turn's list.
_RULES: tuple[Callable[[dict], dict | None], ...] = (
    _rule_cross_sell_overlaps_products,
    _rule_cross_sell_eligible_but_empty,
    _rule_has_more_contradicts_counts,
    _rule_prompt_leak_marker,
    _rule_pii_pattern_in_stored_text,
    _rule_forbidden_stock_wording,
    _rule_no_results_claim_but_products_present,
    _rule_alternatives_claim_but_empty,
)


def _is_evidence_insufficient(turn: dict) -> bool:
    """Section 25/31 - UNCERTAIN is a first-class result, not a failure
    mode. A turn predating a schema field (Section 31 - historical
    records must be handled defensively, never destructively repaired)
    or missing the minimum fields every rule needs to run meaningfully
    cannot be honestly called PASS - PASS should mean "the configured
    rules ran and found nothing," not "we had too little to check."""
    if "answer" not in turn or "product_groups" not in turn:
        return True
    if not str(turn.get("answer") or "").strip() and turn.get("intent") is None:
        return True
    return False


def analyze_turn(turn: dict) -> dict:
    """Runs every rule against one sanitized audit turn. Returns a QA
    result: {status, turn context ids, findings}. status is exactly one
    of PASS / FINDING / UNCERTAIN (Section 25) - never forced into a
    failure category when evidence is merely absent."""
    if _is_evidence_insufficient(turn):
        status = "UNCERTAIN"
        findings: list[dict] = []
    else:
        findings = [f for f in (rule(turn) for rule in _RULES) if f is not None]
        status = "FINDING" if findings else "PASS"
    return {
        "status": status,
        "conversation_hash": turn.get("conversation_hash"),
        "interaction_id": turn.get("interaction_id"),
        "decision_id": turn.get("decision_id"),
        "result_set_id": turn.get("result_set_id"),
        "ts": turn.get("ts"),
        "findings": findings,
    }


def analyze_turns(turns: list[dict]) -> list[dict]:
    return [analyze_turn(t) for t in turns]


def qa_findings(
    days: int = 7,
    limit: int = 100,
    classification: str | None = None,
    severity: str | None = None,
    conversation_hash: str | None = None,
    q: str | None = None,
) -> list[dict]:
    """READ-only accessor for GET /admin/qa/findings. Reads sanitized
    audit turns fresh (Section 22 option A - ON-READ), runs the
    deterministic rules in-memory, and returns a FLAT list of individual
    findings (PASS turns contribute nothing - see qa_status() for
    aggregate PASS/FINDING/UNCERTAIN counts), newest turn first."""
    safe_limit = max(1, min(int(limit or 100), 500))
    # Over-fetch turns before the flat-findings limit is applied, since
    # one turn can yield zero or several findings - reading the same
    # bounded window read_audit_turns() already caps (days<=90) keeps
    # this bounded without a second, unbounded pass over the log.
    turns = read_audit_turns(days=days, limit=500, conversation_hash=conversation_hash, q=q)
    results = analyze_turns(turns)

    flat: list[dict] = []
    for turn, result in zip(turns, results):
        for f in result["findings"]:
            flat.append({**f, "ts": turn.get("ts")})

    if classification:
        wanted = classification.strip().upper()
        flat = [f for f in flat if f.get("classification") == wanted]
    if severity:
        wanted_sev = severity.strip().upper()
        flat = [f for f in flat if f.get("severity") == wanted_sev]

    flat.sort(key=lambda f: f.get("ts", 0), reverse=True)
    return flat[:safe_limit]


def qa_conversation(conversation_hash: str, days: int = 90) -> list[dict]:
    """READ-only accessor for GET /admin/qa/conversations/{hash} - every
    QA result (PASS/FINDING/UNCERTAIN, in full, not just findings) for
    one conversation, newest turn first."""
    turns = read_audit_turns(days=days, limit=500, conversation_hash=conversation_hash)
    turns.sort(key=lambda t: t.get("ts", 0), reverse=True)
    return analyze_turns(turns)


def qa_status(days: int = 1) -> dict:
    """READ-only accessor for GET /admin/qa/status. Only non-sensitive
    aggregate counts - never raw customer text, never identifiers beyond
    the same hashed conversation_hash the audit layer already exposes."""
    turns = read_audit_turns(days=days, limit=500)
    results = analyze_turns(turns)
    pass_count = sum(1 for r in results if r["status"] == "PASS")
    finding_count = sum(1 for r in results if r["status"] == "FINDING")
    uncertain_count = sum(1 for r in results if r["status"] == "UNCERTAIN")
    total_findings = sum(len(r["findings"]) for r in results)
    return {
        "readonly": True,
        "days": days,
        "turns_analyzed": len(turns),
        "pass_count": pass_count,
        "finding_count": finding_count,
        "uncertain_count": uncertain_count,
        "total_findings": total_findings,
        "rule_count": len(_RULES),
    }
