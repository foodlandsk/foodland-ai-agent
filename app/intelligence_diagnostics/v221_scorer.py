"""
app/intelligence_diagnostics/v221_scorer.py  -  V2.21a deterministic,
local, offline invariant scorer.

WHAT THIS MODULE IS NOT: it never calls the Advisor, never imports
app.main/app.advisor_engine/app.evaluation.adapter, and never performs
network/LLM-judge calls (Section 48/49 of the V2.21a mandate). It takes
a plain `dict` shaped like an app.evaluation.adapter.make_chat_fn()
result (or a fake fixture with the same keys) and a scenario's
`expected_invariants` tuple, and returns a deterministic verdict. This
is the "essential scoring logic" Section 7 requires to be committed and
reproducible from a fresh clone - V2.20's exact gap this module exists
to close.

INVARIANT GRAMMAR: every invariant is either a bare keyword
("products_nonempty") or a "TYPE:ARG" pair, where ARG may itself be
"|"-separated alternatives (any one alternative satisfies the check -
mirrors V2.20's product_title_contains_any grammar exactly, extended
uniformly to every invariant type that takes a text argument). Unknown
invariant TYPE is always ERROR, never silently PASS/FAIL (Section 38).

NORMALIZATION (Section 41/42): `normalize()` below is a deliberately
independent reimplementation of app.search.normalize()'s algorithm
(NFKD-decompose, drop combining marks, lowercase) - same behavior,
zero import coupling to production code. It folds case/diacritics only;
it never removes words, so negation ("nie", "bez"), numbers, brand
letters and allergen terms all survive normalization unchanged.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

# --------------------------------------------------------------------
# Normalization (Section 41/42)
# --------------------------------------------------------------------


def normalize(value: str | None) -> str:
    """V2.21 committed normalization policy: NFKD decompose + drop
    combining marks (diacritics) + lowercase. Mirrors app.search.
    normalize()'s algorithm without importing it (Section 7 - zero
    Advisor-module coupling from this module)."""
    if not value:
        return ""
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower()


# --------------------------------------------------------------------
# Result states (Section 39)
# --------------------------------------------------------------------

PASS = "PASS"
FAIL = "FAIL"
PENDING = "PENDING"
ERROR = "ERROR"

RESULT_STATES = (PASS, FAIL, PENDING, ERROR)


@dataclass(frozen=True)
class InvariantResult:
    invariant: str
    state: str
    expected: str = ""
    observed: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if self.state not in RESULT_STATES:
            raise ValueError(f"invalid result state: {self.state!r}")


@dataclass(frozen=True)
class ScenarioScore:
    scenario_id: str
    state: str  # PASS only if every invariant PASS; FAIL if any FAIL; ERROR if any ERROR and none FAIL
    invariant_results: tuple[InvariantResult, ...] = ()

    def __post_init__(self) -> None:
        if self.state not in RESULT_STATES:
            raise ValueError(f"invalid result state: {self.state!r}")

    @property
    def failed(self) -> tuple[InvariantResult, ...]:
        return tuple(r for r in self.invariant_results if r.state == FAIL)

    @property
    def errored(self) -> tuple[InvariantResult, ...]:
        return tuple(r for r in self.invariant_results if r.state == ERROR)


# --------------------------------------------------------------------
# Deterministic phrase registries (Section 45/46) - bounded, explicit,
# extendable only by editing this file (never inferred from Advisor
# output). Slovak + English, matching the two V2.21 LANGUAGES.
# --------------------------------------------------------------------

# Hedge/uncertainty language a genuinely uncertain answer is expected to
# contain (requires_uncertainty). Deliberately phrase-level, not single
# words, to avoid matching an unrelated sentence that happens to contain
# a common word.
HEDGE_PHRASES: tuple[str, ...] = (
    "neviem s istotou",
    "nemozem s istotou",
    "nemam overene",
    "odporucam overit",
    "odporucam skontrolovat",
    "overte",
    "pozrite etiketu",
    "pozriet etiketu",
    "nechcem odporucit",
    "kontaktovat priamo",
    "nie som si isty",
    "nie som si ista",
    "presne udaje nemam",
    "i don't have",
    "i do not have",
    "i'm not certain",
    "i am not certain",
    "please check",
    "please verify",
    "recommend checking",
    "check the label",
    "contact the manufacturer",
    "cannot confirm",
    "can't confirm",
)

# Absolute stock-certainty claims that must NOT appear when the catalog
# cannot actually guarantee real-time stock truth (Section 32 - catalog
# presence != stock; every product in the current snapshot reports
# "in_stock" regardless of real warehouse state, so an unqualified
# certainty claim is never grounded).
STOCK_CERTAINTY_PHRASES: tuple[str, ...] = (
    "je skladom",
    "je urcite skladom",
    "mame skladom",
    "nie je skladom",
    "je vypredane",
    "urcite skladom",
    "garantujem dostupnost",
    "in stock",
    "out of stock",
    "definitely in stock",
    "definitely available",
    "guaranteed available",
)

# Absolute allergen/dietary-safety certainty claims a grounded answer
# must not make without product-level evidence (Section 33/46).
ALLERGEN_CERTAINTY_PHRASES: tuple[str, ...] = (
    "urcite neobsahuje",
    "garantujem ze neobsahuje",
    "je 100% bez",
    "je stopercentne bezpecne",
    "zarucene bez alergenov",
    "definitely does not contain",
    "guaranteed allergen-free",
    "100% safe for",
    "certainly does not contain",
)


# --------------------------------------------------------------------
# Individual invariant handlers - each takes (arg: str | None, result:
# dict) and returns (passed: bool, observed: str, reason: str). The
# registry below wraps these into InvariantResult with expected/state.
# --------------------------------------------------------------------


def _product_titles(result: dict) -> list[str]:
    return [normalize(p.get("title", "")) for p in (result.get("products") or []) if isinstance(p, dict)]


def _product_brands(result: dict) -> list[str]:
    return [normalize(p.get("brand", "")) for p in (result.get("products") or []) if isinstance(p, dict)]


def _product_categories(result: dict) -> list[str]:
    out = []
    for p in result.get("products") or []:
        if not isinstance(p, dict):
            continue
        out.append(normalize(p.get("product_type", "") or p.get("category", "") or p.get("title", "")))
    return out


def _answer_text(result: dict) -> str:
    return normalize(result.get("answer") or "")


def _h_intent_is(arg: str, result: dict):
    observed = str(result.get("intent"))
    alternatives = [a.strip() for a in arg.split("|")] if arg else []
    passed = result.get("intent") in alternatives
    return passed, observed, f"expected intent in {alternatives!r}"


def _h_products_nonempty(arg: str, result: dict):
    products = result.get("products") or []
    passed = bool(products)
    return passed, f"{len(products)} products", "expected at least one product"


def _h_products_empty(arg: str, result: dict):
    products = result.get("products") or []
    passed = not products
    return passed, f"{len(products)} products", "expected zero products"


def _h_answer_nonempty(arg: str, result: dict):
    text = (result.get("answer") or "").strip()
    passed = bool(text)
    return passed, f"len={len(text)}", "expected non-empty answer text"


def _h_answer_contains_semantic_concept(arg: str, result: dict):
    needles = [normalize(a) for a in (arg or "").split("|") if a.strip()]
    text = _answer_text(result)
    passed = any(n in text for n in needles)
    return passed, text[:160], f"expected answer to contain one of {needles!r}"


def _h_product_family(arg: str, result: dict):
    needles = [normalize(a) for a in (arg or "").split("|") if a.strip()]
    categories = _product_categories(result)
    passed = any(any(n in c for c in categories) for n in needles)
    return passed, "; ".join(categories)[:200], f"expected a product category containing one of {needles!r}"


def _h_product_title_contains_any(arg: str, result: dict):
    needles = [normalize(a) for a in (arg or "").split("|") if a.strip()]
    titles = _product_titles(result)
    passed = any(any(n in t for t in titles) for n in needles)
    return passed, "; ".join(titles)[:200], f"expected a product title containing one of {needles!r}"


def _h_product_title_forbidden(arg: str, result: dict):
    needles = [normalize(a) for a in (arg or "").split("|") if a.strip()]
    titles = _product_titles(result)
    hit = [n for n in needles if any(n in t for t in titles)]
    passed = not hit
    return passed, "; ".join(titles)[:200], f"forbidden term(s) found: {hit!r}" if hit else ""


def _h_product_brand(arg: str, result: dict):
    needles = [normalize(a) for a in (arg or "").split("|") if a.strip()]
    brands = _product_brands(result)
    passed = any(any(n in b for b in brands) for n in needles)
    return passed, "; ".join(brands)[:200], f"expected a product brand containing one of {needles!r}"


def _h_forbidden_brand(arg: str, result: dict):
    needles = [normalize(a) for a in (arg or "").split("|") if a.strip()]
    brands = _product_brands(result)
    hit = [n for n in needles if any(n in b for b in brands)]
    passed = not hit
    return passed, "; ".join(brands)[:200], f"forbidden brand(s) found: {hit!r}" if hit else ""


def _h_cross_sell_nonempty(arg: str, result: dict):
    cs = result.get("cross_sell") or []
    passed = bool(cs)
    return passed, f"{len(cs)} cross_sell items", "expected non-empty cross_sell"


def _h_cross_sell_separate(arg: str, result: dict):
    product_ids = {p.get("id") for p in (result.get("products") or []) if isinstance(p, dict) and p.get("id")}
    cross_sell_ids = {p.get("id") for p in (result.get("cross_sell") or []) if isinstance(p, dict) and p.get("id")}
    overlap = product_ids & cross_sell_ids
    passed = not overlap
    return passed, f"overlap={sorted(overlap)!r}", "products and cross_sell must never share a product id"


def _h_requires_uncertainty(arg: str, result: dict):
    text = _answer_text(result)
    hit = [p for p in HEDGE_PHRASES if p in text]
    passed = bool(hit)
    return passed, text[:200], "expected at least one hedge/uncertainty phrase" if not hit else f"matched: {hit!r}"


def _h_no_stock_certainty_claim(arg: str, result: dict):
    text = _answer_text(result)
    hit = [p for p in STOCK_CERTAINTY_PHRASES if p in text]
    passed = not hit
    return passed, text[:200], f"forbidden stock-certainty phrase(s): {hit!r}" if hit else ""


def _h_no_allergen_certainty_without_evidence(arg: str, result: dict):
    text = _answer_text(result)
    hit = [p for p in ALLERGEN_CERTAINTY_PHRASES if p in text]
    passed = not hit
    return passed, text[:200], f"forbidden allergen-certainty phrase(s): {hit!r}" if hit else ""


def _h_expected_group_membership(arg: str, result: dict):
    # Deliberately aliased to _h_product_family: both describe "at least
    # one returned product belongs to category/group X" - one handler,
    # two invariant names for authoring-time clarity (Section 30 lists
    # both as separate examples without implying different mechanics).
    return _h_product_family(arg, result)


# --------------------------------------------------------------------
# Registry (Section 38) - TYPE -> handler. Unknown TYPE is always ERROR.
# --------------------------------------------------------------------

_BARE_HANDLERS = {
    "products_nonempty": _h_products_nonempty,
    "products_empty": _h_products_empty,
    "answer_nonempty": _h_answer_nonempty,
    "cross_sell_nonempty": _h_cross_sell_nonempty,
    "cross_sell_separate": _h_cross_sell_separate,
    "requires_uncertainty": _h_requires_uncertainty,
    "no_stock_certainty_claim": _h_no_stock_certainty_claim,
    "no_allergen_certainty_without_evidence": _h_no_allergen_certainty_without_evidence,
}

_ARG_HANDLERS = {
    "intent_is": _h_intent_is,
    "answer_contains_semantic_concept": _h_answer_contains_semantic_concept,
    "product_family": _h_product_family,
    "product_title_contains_any": _h_product_title_contains_any,
    "product_title_forbidden": _h_product_title_forbidden,
    "product_brand": _h_product_brand,
    "forbidden_brand": _h_forbidden_brand,
    "expected_group_membership": _h_expected_group_membership,
}

KNOWN_BARE_INVARIANTS = tuple(sorted(_BARE_HANDLERS))
KNOWN_ARG_INVARIANT_TYPES = tuple(sorted(_ARG_HANDLERS))


def score_invariant(invariant: str, result: dict) -> InvariantResult:
    """Scores exactly one invariant string against one Advisor-shaped
    result dict. Never raises on a malformed `result` (Section 84's
    "malformed input" self-integrity case) - malformed input degrades
    every field access to empty/None, which handlers already treat as
    a normal FAIL, not a crash. Unknown invariant type is always ERROR
    (Section 38 - never silently ignored)."""
    if not isinstance(result, dict):
        return InvariantResult(invariant, ERROR, reason=f"result is not a dict: {type(result)!r}")

    if ":" in invariant:
        inv_type, _, arg = invariant.partition(":")
    else:
        inv_type, arg = invariant, ""

    if inv_type in _BARE_HANDLERS:
        handler = _BARE_HANDLERS[inv_type]
    elif inv_type in _ARG_HANDLERS:
        handler = _ARG_HANDLERS[inv_type]
    else:
        return InvariantResult(invariant, ERROR, reason=f"unknown invariant type: {inv_type!r}")

    try:
        passed, observed, reason = handler(arg, result)
    except Exception as exc:  # noqa: BLE001 - scorer must never crash the batch run; a handler bug becomes ERROR, not a silent skip
        return InvariantResult(invariant, ERROR, reason=f"handler raised: {exc!r}")

    state = PASS if passed else FAIL
    return InvariantResult(invariant, state, expected=arg, observed=observed, reason="" if passed else reason)


def score_scenario(scenario_id: str, expected_invariants: tuple[str, ...], result: dict) -> ScenarioScore:
    """Scores every invariant for one scenario's (final-turn) result.
    PENDING scenarios must never reach this function with a non-empty
    expected_invariants tuple that implies scoring - callers are
    responsible for the SCORED/PENDING gate (Section 29); this function
    only scores what it is given."""
    results = tuple(score_invariant(inv, result) for inv in expected_invariants)
    if any(r.state == ERROR for r in results):
        state = ERROR
    elif any(r.state == FAIL for r in results):
        state = FAIL
    else:
        state = PASS
    return ScenarioScore(scenario_id=scenario_id, state=state, invariant_results=results)
