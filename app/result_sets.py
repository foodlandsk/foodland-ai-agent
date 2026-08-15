"""
app/result_sets.py  -  V2.5 ResultSet model + TTL store

A ResultSet is the stable, server-held record of "everything that matched
a structured query" (V2.4's RetrievalResult, ranked) plus how much of it
has been shown so far. Presentation (app/presentation.py) decides initial
`displayed_count`; Show More/Show All (wired in app/main.py) advance it
without ever re-deriving membership from raw text (Section 9/10/41 of the
V2.5 spec) - continuation is pure pagination over `ranked_product_ids`.

Stores product IDs only, never duplicated Product objects (Section 3/48).
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

DEFAULT_TTL_SECONDS = 1800
MAX_STORED_RESULT_SETS = 20000


@dataclass
class ResultSet:
    result_set_id: str
    raw_query: str
    structured_query: object  # app.query_constraints.StructuredProductQuery

    answer_strategy: str

    matching_total: int  # primary valid matches only (Section 5) - never includes nearest/alternative
    ranked_product_ids: list[str]  # full ordered primary set (exact, or nearest/valid tier used as primary)

    exact_match_ids: list[str] = field(default_factory=list)
    nearest_match_ids: list[str] = field(default_factory=list)
    alternative_ids: list[str] = field(default_factory=list)

    groups: list[dict] = field(default_factory=list)  # GROUPED_DISCOVERY only

    displayed_count: int = 0
    page_size: int = 4

    catalog_version: int = 0
    taxonomy_version: int = 0

    created_at: float = 0.0
    expires_at: float = 0.0

    @property
    def has_more(self) -> bool:
        return self.displayed_count < len(self.ranked_product_ids)

    @property
    def remaining_count(self) -> int:
        return max(0, len(self.ranked_product_ids) - self.displayed_count)

    def initial_page_ids(self) -> list[str]:
        return self.ranked_product_ids[: self.displayed_count]

    def next_page_ids(self) -> list[str]:
        """Next page_size ids after what's already displayed (SHOW_MORE)."""
        return self.ranked_product_ids[self.displayed_count : self.displayed_count + self.page_size]

    def remaining_ids(self) -> list[str]:
        """Every id not yet displayed (SHOW_ALL)."""
        return self.ranked_product_ids[self.displayed_count :]


_result_sets: dict[str, ResultSet] = {}


def create_result_set(
    *,
    raw_query: str,
    structured_query: object,
    answer_strategy: str,
    ranked_product_ids: list[str],
    matching_total: int,
    exact_match_ids: list[str] | None = None,
    nearest_match_ids: list[str] | None = None,
    alternative_ids: list[str] | None = None,
    groups: list[dict] | None = None,
    displayed_count: int,
    page_size: int,
    catalog_version: int,
    taxonomy_version: int,
    now: float,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> ResultSet:
    _prune_expired(now)
    result_set_id = uuid.uuid4().hex
    result_set = ResultSet(
        result_set_id=result_set_id,
        raw_query=raw_query,
        structured_query=structured_query,
        answer_strategy=answer_strategy,
        matching_total=matching_total,
        ranked_product_ids=list(ranked_product_ids),
        exact_match_ids=list(exact_match_ids or []),
        nearest_match_ids=list(nearest_match_ids or []),
        alternative_ids=list(alternative_ids or []),
        groups=list(groups or []),
        displayed_count=min(displayed_count, len(ranked_product_ids)),
        page_size=page_size,
        catalog_version=catalog_version,
        taxonomy_version=taxonomy_version,
        created_at=now,
        expires_at=now + ttl_seconds,
    )
    if len(_result_sets) >= MAX_STORED_RESULT_SETS:
        oldest_key = min(_result_sets, key=lambda k: _result_sets[k].created_at)
        _result_sets.pop(oldest_key, None)
    _result_sets[result_set_id] = result_set
    return result_set


def get_result_set(result_set_id: str, now: float) -> ResultSet | None:
    """Section 47: caller only ever gets a ResultSet back if the id is
    genuinely known server-side and not expired - a forged/guessed id
    simply resolves to None, same treatment as "no active result set"."""
    if not result_set_id:
        return None
    result_set = _result_sets.get(result_set_id)
    if result_set is None:
        return None
    if now > result_set.expires_at:
        _result_sets.pop(result_set_id, None)
        return None
    return result_set


def advance_displayed_count(result_set: ResultSet, additional: int) -> None:
    result_set.displayed_count = min(len(result_set.ranked_product_ids), result_set.displayed_count + additional)


def show_all(result_set: ResultSet) -> None:
    result_set.displayed_count = len(result_set.ranked_product_ids)


def _prune_expired(now: float) -> None:
    if len(_result_sets) <= MAX_STORED_RESULT_SETS:
        expired = [key for key, rs in _result_sets.items() if now > rs.expires_at]
    else:
        expired = sorted(_result_sets, key=lambda k: _result_sets[k].expires_at)[: len(_result_sets) - MAX_STORED_RESULT_SETS]
    for key in expired:
        _result_sets.pop(key, None)


def clear_all_result_sets() -> None:
    """Test/utility helper - not used by production request handling."""
    _result_sets.clear()
