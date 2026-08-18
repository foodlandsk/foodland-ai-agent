"""
app/learning_opportunities.py  -  V2.12: detect LearningOpportunity from
aggregated signals (app.learning_signals). Detection creates evidence,
never a production mutation (Section 34) - app.learning_candidates is the
only module allowed to turn a LOW-RISK opportunity into an actual
RankingProfile candidate, and only RANKING_POSITION_ANOMALY /
LOW_TOP1_SELECTION opportunities are ever eligible for that (both operate
purely on already-semantically-valid same-family products' soft-ranking
order - Section 3/26). Every other opportunity type here is
`proposed_action_type=REVIEW_REQUIRED` by construction and can never
become an automatic candidate (Section 39/41/42).

Honest scope note (mirrors app.learning_signals' docstring): opportunity
types the V2.12 spec lists conceptually but that the real event stream
cannot support without new frontend instrumentation - AUTOCOMPLETE_LOW_
CONVERSION (no impression denominator for autocomplete), CROSS_SELL_LOW_
ENGAGEMENT / CROSS_SELL_STRONG_ALTERNATIVE (no event field distinguishes
a cross-sell click from a primary-search click) - are NOT implemented
here. NEW_QUERY_CLUSTER and TAXONOMY_GAP_CANDIDATE are merged into one
detector (`detect_taxonomy_gap_candidates`) since, with the real data
available, they are the same observation: a recurring query the taxonomy
cannot classify at all.
"""
from __future__ import annotations

import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from app.learning_events import LearningEvent
from app.learning_signals import QueryProductSignal, ReformulationEvent, query_concept

# Section 35 - minimum support before a detector may even emit an
# opportunity. Defaults follow the same precedent app.fbt.py already set
# (FBT_MIN_ADD_TO_CART_EVENTS=200/FBT_MIN_PAIR_COUNT=3 - a catalog-wide
# volume gate plus a per-item gate) - no real production traffic was
# available to calibrate against at implementation time, so these are the
# honest, documented starting point (Section 35: derive sensible
# defaults; env-overridable so ops can tune once real volume is known).
MIN_SUPPORT_RANKING_ANOMALY = int(os.getenv("LEARNING_MIN_SUPPORT_RANKING_ANOMALY", "200"))
MIN_SUPPORT_TOP1 = int(os.getenv("LEARNING_MIN_SUPPORT_TOP1", "100"))
MIN_SUPPORT_REFORMULATION = int(os.getenv("LEARNING_MIN_SUPPORT_REFORMULATION", "10"))
MIN_SUPPORT_ZERO_RESULT = int(os.getenv("LEARNING_MIN_SUPPORT_ZERO_RESULT", "5"))
MIN_SUPPORT_TAXONOMY_GAP = int(os.getenv("LEARNING_MIN_SUPPORT_TAXONOMY_GAP", "5"))

TYPE_RANKING_POSITION_ANOMALY = "RANKING_POSITION_ANOMALY"
TYPE_LOW_TOP1_SELECTION = "LOW_TOP1_SELECTION"
TYPE_HIGH_REFORMULATION_RATE = "HIGH_REFORMULATION_RATE"
TYPE_HIGH_ZERO_RESULT = "HIGH_ZERO_RESULT"
TYPE_TAXONOMY_GAP_CANDIDATE = "TAXONOMY_GAP_CANDIDATE"

ACTION_RANKING_WEIGHT_ADJUSTMENT = "RANKING_WEIGHT_ADJUSTMENT"
ACTION_REVIEW_REQUIRED = "REVIEW_REQUIRED"


@dataclass(frozen=True)
class LearningOpportunity:
    id: str
    type: str
    scope: str
    evidence: dict
    confidence: str
    sample_size: int
    affected_queries: tuple[str, ...]
    affected_products: tuple[str, ...]
    proposed_action_type: str


def _opportunity_id(type_: str, scope: str) -> str:
    return f"{type_}:{scope}"


def detect_ranking_position_anomalies(product_signals: list[QueryProductSignal]) -> list[LearningOpportunity]:
    """Section 26/33/88 - within a family, does the CURRENT rank order
    (proxied by avg_position, lower = ranked first) disagree with what
    position-normalized behavioral lift suggests? Only fires among
    products that are ALREADY semantically valid members of the same
    family (Section 3 - this never looks across families); the actual
    'is candidate B semantically as valid as A' question stays entirely
    with V2.4/V2.10 downstream in app.learning_candidates, this detector
    only surfaces the observation."""
    by_family: dict[str, list[QueryProductSignal]] = defaultdict(list)
    for signal in product_signals:
        if signal.avg_position is not None:
            by_family[signal.query_pattern].append(signal)

    opportunities = []
    for family, signals in by_family.items():
        total_impressions = sum(s.impressions for s in signals)
        if total_impressions < MIN_SUPPORT_RANKING_ANOMALY or len(signals) < 2:
            continue

        by_rank = sorted(signals, key=lambda s: s.avg_position)
        by_lift = sorted(signals, key=lambda s: -s.position_normalized_lift)

        if by_rank[0].product_id == by_lift[0].product_id:
            continue  # current #1 by rank already agrees with #1 by behavioral lift

        current_first = by_rank[0]
        lift_leader = by_lift[0]
        if lift_leader.position_normalized_lift <= current_first.position_normalized_lift * 1.1:
            continue  # not a meaningfully large disagreement, not worth flagging

        opportunities.append(LearningOpportunity(
            id=_opportunity_id(TYPE_RANKING_POSITION_ANOMALY, family),
            type=TYPE_RANKING_POSITION_ANOMALY,
            scope=family,
            evidence={
                "current_rank1_product": current_first.product_id,
                "current_rank1_lift": current_first.position_normalized_lift,
                "behavioral_leader_product": lift_leader.product_id,
                "behavioral_leader_lift": lift_leader.position_normalized_lift,
                "total_impressions": total_impressions,
            },
            confidence=current_first.confidence,
            sample_size=total_impressions,
            affected_queries=(family,),
            affected_products=(current_first.product_id, lift_leader.product_id),
            proposed_action_type=ACTION_RANKING_WEIGHT_ADJUSTMENT,
        ))
    return opportunities


def detect_low_top1_selection(product_signals: list[QueryProductSignal]) -> list[LearningOpportunity]:
    """Section 33 - for a family with a clear behavioral front-runner,
    is the current #1-ranked product actually capturing a healthy share
    of clicks? A very low share alongside a strong lift leader elsewhere
    is the same underlying signal as a ranking anomaly, reported
    separately because the spec asks for it as its own detector."""
    by_family: dict[str, list[QueryProductSignal]] = defaultdict(list)
    for signal in product_signals:
        if signal.avg_position is not None:
            by_family[signal.query_pattern].append(signal)

    opportunities = []
    for family, signals in by_family.items():
        total_clicks = sum(s.clicks for s in signals)
        total_impressions = sum(s.impressions for s in signals)
        if total_impressions < MIN_SUPPORT_TOP1 or total_clicks == 0:
            continue

        rank1 = min(signals, key=lambda s: s.avg_position)
        top1_share = rank1.clicks / total_clicks
        if top1_share >= 0.2:
            continue  # healthy enough share - not an opportunity

        opportunities.append(LearningOpportunity(
            id=_opportunity_id(TYPE_LOW_TOP1_SELECTION, family),
            type=TYPE_LOW_TOP1_SELECTION,
            scope=family,
            evidence={"rank1_product": rank1.product_id, "rank1_click_share": top1_share, "total_clicks": total_clicks},
            confidence=rank1.confidence,
            sample_size=total_clicks,
            affected_queries=(family,),
            affected_products=(rank1.product_id,),
            proposed_action_type=ACTION_REVIEW_REQUIRED,
        ))
    return opportunities


def detect_high_reformulation_rate(reformulations: list[ReformulationEvent]) -> list[LearningOpportunity]:
    """Section 21-23 - never auto-labels a single reformulation a
    failure; only a recurring PATTERN of FAILURE_REFORMULATION within one
    family, above minimum support, becomes an opportunity - and always
    REVIEW_REQUIRED (a retrieval/alias/routing issue, not something a
    RankingProfile weight can fix - Section 23/39)."""
    by_family: Counter[str] = Counter()
    failures_by_family: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    for r in reformulations:
        if not r.from_family:
            continue
        by_family[r.from_family] += 1
        if r.classification == "FAILURE_REFORMULATION":
            failures_by_family[r.from_family] += 1
            if len(examples[r.from_family]) < 5:
                examples[r.from_family].append(f"{r.from_query} -> {r.to_query}")

    opportunities = []
    for family, total in by_family.items():
        failures = failures_by_family.get(family, 0)
        if total < MIN_SUPPORT_REFORMULATION or failures == 0:
            continue
        rate = failures / total
        if rate < 0.3:
            continue

        opportunities.append(LearningOpportunity(
            id=_opportunity_id(TYPE_HIGH_REFORMULATION_RATE, family),
            type=TYPE_HIGH_REFORMULATION_RATE,
            scope=family,
            evidence={"failure_rate": rate, "failures": failures, "total_reformulations": total, "examples": examples[family]},
            confidence="MEDIUM" if total < 50 else "HIGH",
            sample_size=total,
            affected_queries=tuple(examples[family]),
            affected_products=(),
            proposed_action_type=ACTION_REVIEW_REQUIRED,
        ))
    return opportunities


def detect_high_zero_result(events: list[LearningEvent]) -> list[LearningOpportunity]:
    """Section 24 - clusters recurring no_result events by raw query
    text. Distinguishing 'no catalog product exists' from 'parser/
    retrieval failure' would require re-running retrieval for every
    clustered query against the CURRENT catalog (expensive to do inside
    a pure detector) - left to app.learning_candidates / a human reviewer
    to actually re-check before acting, so this detector reports the
    cluster, always REVIEW_REQUIRED, never assumes which case it is."""
    counts: Counter[str] = Counter()
    for event in events:
        if event.event_type == "no_result" and event.query:
            counts[event.query.strip().lower()] += 1

    opportunities = []
    for query_text, count in counts.items():
        if count < MIN_SUPPORT_ZERO_RESULT:
            continue
        opportunities.append(LearningOpportunity(
            id=_opportunity_id(TYPE_HIGH_ZERO_RESULT, query_text),
            type=TYPE_HIGH_ZERO_RESULT,
            scope=query_text,
            evidence={"occurrences": count},
            confidence="MEDIUM" if count < 20 else "HIGH",
            sample_size=count,
            affected_queries=(query_text,),
            affected_products=(),
            proposed_action_type=ACTION_REVIEW_REQUIRED,
        ))
    return sorted(opportunities, key=lambda o: -o.sample_size)


def detect_taxonomy_gap_candidates(events: list[LearningEvent]) -> list[LearningOpportunity]:
    """Section 41 (merged with Section 33's NEW_QUERY_CLUSTER, see module
    docstring) - recurring search_submit queries the V2.4 taxonomy cannot
    classify into any family at all. Always REVIEW_REQUIRED/HIGH RISK
    (Section 38/39/41 - taxonomy changes are never auto-applied)."""
    counts: Counter[str] = Counter()
    for event in events:
        if event.event_type == "search_submit" and event.query:
            family, _ = query_concept(event.query)
            if family is None:
                counts[event.query.strip().lower()] += 1

    opportunities = []
    for query_text, count in counts.items():
        if count < MIN_SUPPORT_TAXONOMY_GAP:
            continue
        opportunities.append(LearningOpportunity(
            id=_opportunity_id(TYPE_TAXONOMY_GAP_CANDIDATE, query_text),
            type=TYPE_TAXONOMY_GAP_CANDIDATE,
            scope=query_text,
            evidence={"occurrences": count},
            confidence="MEDIUM" if count < 20 else "HIGH",
            sample_size=count,
            affected_queries=(query_text,),
            affected_products=(),
            proposed_action_type=ACTION_REVIEW_REQUIRED,
        ))
    return sorted(opportunities, key=lambda o: -o.sample_size)


def detect_all_opportunities(
    product_signals: list[QueryProductSignal],
    reformulations: list[ReformulationEvent],
    events: list[LearningEvent],
) -> list[LearningOpportunity]:
    """Section 95 - all detectors, ranked by confidence then sample_size
    (never by revenue alone, Section 95)."""
    confidence_rank = {"HIGH": 2, "MEDIUM": 1, "LOW": 0}
    all_opportunities = (
        detect_ranking_position_anomalies(product_signals)
        + detect_low_top1_selection(product_signals)
        + detect_high_reformulation_rate(reformulations)
        + detect_high_zero_result(events)
        + detect_taxonomy_gap_candidates(events)
    )
    return sorted(all_opportunities, key=lambda o: (-confidence_rank.get(o.confidence, 0), -o.sample_size))
