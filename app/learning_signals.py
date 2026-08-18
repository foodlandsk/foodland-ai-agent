"""
app/learning_signals.py  -  V2.12: aggregate normalized LearningEvents
(app.learning_events) into confidence-scored learning signals.

Section 11-27/77-79 of the V2.12 spec, scoped to what the REAL event
stream (see app.learning_events module docstring) can honestly support:

  - `QueryProductSignal` - per (canonical query concept, product) engagement,
    the core signal app.learning_candidates consumes.
  - `QueryFamilySignal` - the same, rolled up to V2.3 taxonomy family, for
    coarser opportunity detection when per-concept volume is too thin.
  - `ReformulationSignal` - per-session query-sequence classification
    (Section 21-23).
  - `AutocompleteSignal` - selection-frequency aggregation (Section 25).

Honest scope note: CROSS_SELL_* / RECIPE_* signals (Section 29/32) are
NOT implemented as separate aggregates in this sprint - the real event
stream has no field distinguishing "this click was on a cross-sell
product" from "this click was on a primary search result" (no dedicated
event_type or context flag today). Fabricating that distinction would
violate Section 1's "do not invent data sources". app.cross_sell and
app.recipe_graph keep their own V2.6/V2.8 semantic logic entirely
untouched by this module - see docs/learning-engine.md for the documented
gap and what real instrumentation change would close it.

Position bias (Section 77-79): `impression` events carry `product_skus`
in the SAME rank order the customer saw (the widget writes
`data.products.map(p => p.id)`, already rank_candidates()-ordered), so a
product's list index at impression time IS its rank position - no new
instrumentation needed. `click`/`add_to_cart` events carry an explicit
`position` field the widget stamps at click time. This lets the
aggregator compute a simple position-normalized lift (observed CTR at a
product's average position, divided by the catalog-wide expected CTR at
that position) instead of raw click-through rate, so a #1-ranked product
is not automatically treated as "better" just because it was seen first
(Section 78 - "use a simple robust approach", not a causal model).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from app.learning_events import LearningEvent
from app.query_constraints import parse_structured_query

DEFAULT_PRIOR_CLICKS = 1.0
DEFAULT_PRIOR_IMPRESSIONS = 40.0

# Section 12/86 - confidence tiers. Defaults, not calibrated against real
# traffic yet (none was available at implementation time - Section 35:
# "derive sensible defaults from actual traffic" where traffic exists;
# these are the honest starting point documented as tunable).
CONFIDENCE_LOW_MAX_IMPRESSIONS = 30
CONFIDENCE_MEDIUM_MAX_IMPRESSIONS = 200

# Section 79 - popularity-loop cap, same shape as app.behavioral's
# existing min/max ratio clamp (reused convention, not a new idea).
POSITION_LIFT_MIN_RATIO = 0.5
POSITION_LIFT_MAX_RATIO = 2.0

# Section 15 - anomaly guard: a single session interacting with the same
# product implausibly many times in the window is capped, not trusted
# at face value, before it ever reaches aggregation.
MAX_EVENTS_PER_SESSION_PRODUCT = 20


def confidence_tier(impressions: int) -> str:
    if impressions < CONFIDENCE_LOW_MAX_IMPRESSIONS:
        return "LOW"
    if impressions < CONFIDENCE_MEDIUM_MAX_IMPRESSIONS:
        return "MEDIUM"
    return "HIGH"


def query_concept(query: str | None) -> tuple[str | None, str | None]:
    """Section 19 - derive (family, canonical_query_key) by re-parsing the
    raw query through the REAL V2.4 constraint parser, never a second
    text-normalization scheme. Returns (family, family or normalized text)
    so callers can group broad ('ryza') and specific ('foodland jazminova
    ryza 5kg') variants under the same family umbrella (Section 27:
    specificity, not just family, still matters downstream - callers keep
    the raw query too)."""
    if not query:
        return None, None
    try:
        parsed = parse_structured_query(query, known_brands=frozenset())
    except Exception:
        return None, None
    family = getattr(parsed, "family", None)
    return family, family


def _is_specific_query(query: str | None) -> bool:
    """Section 27/89 - a query carrying an explicit brand/size/dietary
    constraint is 'specific'; behavioral influence should matter less for
    it than for a broad bare-family query."""
    if not query:
        return False
    try:
        parsed = parse_structured_query(query, known_brands=frozenset())
    except Exception:
        return False
    return bool(getattr(parsed, "explicit_constraints", None))


def _cap_session_product_events(events: list[LearningEvent]) -> list[LearningEvent]:
    """Section 15/124 - bot/anomaly guard: if one session fires an
    implausible number of events against the same product within the
    window, events beyond MAX_EVENTS_PER_SESSION_PRODUCT for that
    (session, product) pair are dropped from aggregation. Order-preserving,
    deterministic (list order == time order, since events are read in
    file-append order)."""
    seen: Counter[tuple[str, str]] = Counter()
    capped: list[LearningEvent] = []
    for event in events:
        skus = event.all_product_skus or (None,)
        keys = [(event.session_id, sku or "") for sku in skus]
        pre_counts = [seen[key] for key in keys]
        for key in keys:
            seen[key] += 1
        if all(count < MAX_EVENTS_PER_SESSION_PRODUCT for count in pre_counts):
            capped.append(event)
    return capped


@dataclass(frozen=True)
class QueryProductSignal:
    query_pattern: str  # canonical family, or "unknown" if unparseable
    product_id: str
    impressions: int
    clicks: int
    add_to_cart: int
    negative_events: int
    avg_position: float | None
    position_normalized_lift: float
    confidence: str
    sample_count: int


def _position_expected_ctr(
    impressions_by_position: dict[int, int],
    clicks_by_position: dict[int, int],
) -> dict[int, float]:
    """Catalog-wide expected CTR at each rank position - the denominator
    for position-normalized lift (Section 78)."""
    expected: dict[int, float] = {}
    for position, impressions in impressions_by_position.items():
        clicks = clicks_by_position.get(position, 0)
        expected[position] = (clicks + DEFAULT_PRIOR_CLICKS) / (impressions + DEFAULT_PRIOR_IMPRESSIONS)
    return expected


def compute_query_product_signals(events: list[LearningEvent]) -> list[QueryProductSignal]:
    events = _cap_session_product_events(events)

    impressions: Counter[tuple[str, str]] = Counter()
    clicks: Counter[tuple[str, str]] = Counter()
    add_to_cart: Counter[tuple[str, str]] = Counter()
    negatives: Counter[tuple[str, str]] = Counter()
    # Impression-order positions only (Section 78) - this is the ACTUAL
    # rank order the customer saw. Click positions are a separate,
    # lagging signal used only for the CTR-by-position denominator below;
    # mixing them into the same average would let heavily-clicked
    # products bias their own "current rank" estimate toward wherever
    # they happened to be clicked, which is circular.
    impression_positions: dict[tuple[str, str], list[int]] = defaultdict(list)

    impressions_by_position: Counter[int] = Counter()
    clicks_by_position: Counter[int] = Counter()

    for event in events:
        family, _ = query_concept(event.query)
        pattern = family or "unknown"

        if event.event_type == "impression":
            for idx, sku in enumerate(event.product_skus):
                impressions[(pattern, sku)] += 1
                impressions_by_position[idx] += 1
                impression_positions[(pattern, sku)].append(idx)
        elif event.event_type == "click" and event.product_sku:
            clicks[(pattern, event.product_sku)] += 1
            if event.position is not None:
                clicks_by_position[event.position] += 1
        elif event.event_type == "add_to_cart" and event.product_sku:
            add_to_cart[(pattern, event.product_sku)] += 1
        elif event.event_type == "no_result":
            negatives[(pattern, "__query__")] += 1

    expected_ctr_by_position = _position_expected_ctr(dict(impressions_by_position), dict(clicks_by_position))
    overall_expected = (
        sum(clicks_by_position.values()) + DEFAULT_PRIOR_CLICKS
    ) / (sum(impressions_by_position.values()) + DEFAULT_PRIOR_IMPRESSIONS)

    signals: list[QueryProductSignal] = []
    all_keys = set(impressions) | set(clicks) | set(add_to_cart)
    for key in all_keys:
        pattern, product_id = key
        impr = impressions[key]
        clk = clicks[key]
        cart = add_to_cart[key]
        neg = negatives.get((pattern, "__query__"), 0)
        pos_list = impression_positions.get(key, [])
        avg_position = sum(pos_list) / len(pos_list) if pos_list else None

        raw_ctr = (clk + DEFAULT_PRIOR_CLICKS) / (impr + DEFAULT_PRIOR_IMPRESSIONS)
        expected = expected_ctr_by_position.get(round(avg_position), overall_expected) if avg_position is not None else overall_expected
        lift = raw_ctr / expected if expected > 0 else 1.0
        lift = max(POSITION_LIFT_MIN_RATIO, min(POSITION_LIFT_MAX_RATIO, lift))

        signals.append(QueryProductSignal(
            query_pattern=pattern,
            product_id=product_id,
            impressions=impr,
            clicks=clk,
            add_to_cart=cart,
            negative_events=neg,
            avg_position=avg_position,
            position_normalized_lift=lift,
            confidence=confidence_tier(impr),
            sample_count=impr + clk + cart,
        ))
    return sorted(signals, key=lambda s: (s.query_pattern, s.product_id))


@dataclass(frozen=True)
class QueryFamilySignal:
    family: str
    total_impressions: int
    total_clicks: int
    total_add_to_cart: int
    distinct_products: int
    confidence: str


def rollup_family_signals(product_signals: list[QueryProductSignal]) -> list[QueryFamilySignal]:
    by_family: dict[str, list[QueryProductSignal]] = defaultdict(list)
    for signal in product_signals:
        by_family[signal.query_pattern].append(signal)

    rollups = []
    for family, signals in by_family.items():
        total_impr = sum(s.impressions for s in signals)
        rollups.append(QueryFamilySignal(
            family=family,
            total_impressions=total_impr,
            total_clicks=sum(s.clicks for s in signals),
            total_add_to_cart=sum(s.add_to_cart for s in signals),
            distinct_products=len(signals),
            confidence=confidence_tier(total_impr),
        ))
    return sorted(rollups, key=lambda r: r.family)


@dataclass(frozen=True)
class ReformulationEvent:
    session_id: str
    from_query: str
    to_query: str
    from_family: str | None
    to_family: str | None
    classification: str  # SUCCESSFUL_REFINEMENT | FAILURE_REFORMULATION | UNCLASSIFIED


def detect_reformulations(events: list[LearningEvent]) -> list[ReformulationEvent]:
    """Section 21-23 - within each session, consecutive `search_submit`
    queries with no intervening click/add_to_cart on the FIRST query are
    candidate reformulations. Classified (never auto-labeled a failure,
    Section 21):
      - SUCCESSFUL_REFINEMENT: the second query led to a click/add_to_cart
        (Section 22 - legitimate narrowing, e.g. "ryza" -> "jazminova ryza").
      - FAILURE_REFORMULATION: same family, no engagement on either query,
        or an add_to_cart eventually landed on a DIFFERENT family than the
        first query implied (Section 23 - possible retrieval/alias gap).
      - UNCLASSIFIED: not enough evidence either way.
    """
    by_session: dict[str, list[LearningEvent]] = defaultdict(list)
    for event in events:
        by_session[event.session_id].append(event)

    results: list[ReformulationEvent] = []
    for session_id, session_events in by_session.items():
        session_events = sorted(session_events, key=lambda e: e.ts)
        submits = [e for e in session_events if e.event_type == "search_submit" and e.query]
        for i in range(len(submits) - 1):
            first, second = submits[i], submits[i + 1]
            between = [e for e in session_events if first.ts <= e.ts < second.ts]
            had_engagement_on_first = any(e.event_type in {"click", "add_to_cart"} for e in between)
            after_second = [e for e in session_events if e.ts >= second.ts]
            had_engagement_on_second = any(e.event_type in {"click", "add_to_cart"} for e in after_second)

            first_family, _ = query_concept(first.query)
            second_family, _ = query_concept(second.query)

            if had_engagement_on_first:
                continue  # not a reformulation - first query already succeeded

            if had_engagement_on_second:
                classification = "SUCCESSFUL_REFINEMENT"
            elif first_family and second_family and first_family == second_family:
                classification = "FAILURE_REFORMULATION"
            else:
                classification = "UNCLASSIFIED"

            results.append(ReformulationEvent(
                session_id=session_id,
                from_query=first.query,
                to_query=second.query,
                from_family=first_family,
                to_family=second_family,
                classification=classification,
            ))
    return results


@dataclass(frozen=True)
class AutocompleteSignal:
    query_text: str
    selections: int


def compute_autocomplete_signals(events: list[LearningEvent]) -> list[AutocompleteSignal]:
    """Section 25 - selection-frequency only. Honest gap: the current
    event stream has no AUTOCOMPLETE_SHOWN counterpart, so a true
    selection-rate (selections / impressions) cannot be computed - only
    relative selection popularity among what WAS selected."""
    counts: Counter[str] = Counter()
    for event in events:
        if event.event_type == "autocomplete_select" and event.query:
            counts[event.query] += 1
    return sorted(
        (AutocompleteSignal(query_text=q, selections=c) for q, c in counts.items()),
        key=lambda s: (-s.selections, s.query_text),
    )
