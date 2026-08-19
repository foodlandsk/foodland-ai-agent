"""
app/ranking_shadow.py  -  V2.11 shadow-mode ranking comparison.

Runs the SAME representative query list through the real app.main.chat()
pipeline twice - once under a baseline RankingProfile, once under a
candidate - entirely in-process via app.ranking_config.use_ranking_profile,
and diffs the resulting product ORDER (Section 61-64). No customer ever
sees a candidate's output: use_ranking_profile() never touches the
persisted config/ranking_profiles/active.json a live request reads, so
this module cannot leak into production traffic no matter how it is
called.

Note on `window_set_changed`: `chat()` only ever returns the top `limit`
ranked ids, not the full eligible candidate set - so when a query's true
candidate pool is larger than `limit`, a reordering can legitimately
change WHICH ids land in that visible top-N window even though the full
eligible set (owned entirely by retrieval, never by ranking - Section 3)
is untouched. `window_set_changed` reports that honestly as "the visible
page changed", not as an eligibility violation - call with a `limit`
larger than the query's candidate pool (see app.structured_search.
retrieve_products_for_query) when you need to assert the full set is
identical."""
from __future__ import annotations

from dataclasses import dataclass

from app.evaluation.adapter import make_chat_fn
from app.execution_context import shadow_context
from app.ranking_config import RankingProfile, use_ranking_profile

DEFAULT_SHADOW_QUERIES = (
    "jazmínová ryža",
    "basmati ryža",
    "ryža na sushi",
    "jazmínová ryža 5 kg",
    "kikkoman sójová omáčka",
    "rybacia omáčka",
    "kokosové mlieko",
    "curry pasta",
    "miso pasta",
    "gochujang",
    "shin ramyun",
)


@dataclass(frozen=True)
class ShadowQueryResult:
    query: str
    baseline_order: list[str]
    candidate_order: list[str]
    order_changed: bool
    window_set_changed: bool


@dataclass(frozen=True)
class ShadowComparisonReport:
    baseline_version: str
    candidate_version: str
    results: list[ShadowQueryResult]

    @property
    def queries_changed(self) -> int:
        return sum(1 for r in self.results if r.order_changed)

    @property
    def windows_with_set_changes(self) -> list[str]:
        """Informational, not a violation (see module docstring) - a
        reordering legitimately changes the visible top-N window whenever
        a query's candidate pool exceeds `limit`."""
        return [r.query for r in self.results if r.window_set_changed]

    def render(self) -> str:
        lines = [
            f"Shadow comparison: baseline={self.baseline_version} vs candidate={self.candidate_version}",
            f"{self.queries_changed}/{len(self.results)} quer{'y' if self.queries_changed == 1 else 'ies'} changed order",
        ]
        if self.windows_with_set_changes:
            lines.append(f"Note - visible top-N window set changed for (expected when candidate pool > limit): {self.windows_with_set_changes}")
        for r in self.results:
            marker = "CHANGED" if r.order_changed else "same"
            lines.append(f"  [{marker}] {r.query!r}: {r.baseline_order} -> {r.candidate_order}")
        return "\n".join(lines)


def shadow_compare(
    queries: list[str],
    baseline: RankingProfile,
    candidate: RankingProfile,
    *,
    limit: int = 8,
) -> ShadowComparisonReport:
    chat_fn = make_chat_fn(execution_context=shadow_context())
    results = []
    for query in queries:
        with use_ranking_profile(baseline):
            baseline_ids = [p.get("id") for p in chat_fn(query, limit).get("products", [])]
        with use_ranking_profile(candidate):
            candidate_ids = [p.get("id") for p in chat_fn(query, limit).get("products", [])]
        results.append(ShadowQueryResult(
            query=query,
            baseline_order=baseline_ids,
            candidate_order=candidate_ids,
            order_changed=baseline_ids != candidate_ids,
            window_set_changed=set(baseline_ids) != set(candidate_ids),
        ))
    return ShadowComparisonReport(baseline_version=baseline.version, candidate_version=candidate.version, results=results)
