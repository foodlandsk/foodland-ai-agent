"""
app/answer_composer.py  -  V2.5 Answer Composer

Deterministic, template-based natural language - NOT an LLM call
(Section 24/50: the composer never decides product validity, counts, or
which IDs belong; it only phrases what app.presentation already decided).
This keeps every wording rule mechanically testable (Section 65) and keeps
the primary structured-retrieval answer path free of OpenAI cost/latency/
non-determinism, matching the same "no LLM in deterministic pipeline"
discipline app/taxonomy.py and app/retrieval.py already follow.

Sidesteps Slovak noun declension (genitive plural of arbitrary taxonomy
labels is not mechanically derivable) by phrasing counts as "N produktov
v kategórii "Label"" rather than inflecting the label itself.
"""
from __future__ import annotations

from app.presentation import EXACT_MATCH, FILTERED_PRODUCT_LIST, GROUPED_DISCOVERY, NO_EXACT_MATCH
from app.result_sets import ResultSet
from app.taxonomy import FAMILY_DEFINITIONS_BY_ID


def _concept_label(structured_query) -> str:
    rule = FAMILY_DEFINITIONS_BY_ID.get(getattr(structured_query, "concept_id", "") or "")
    return rule.display_label if rule is not None and rule.display_label else ""


def compose_answer(result_set: ResultSet) -> str:
    strategy = result_set.answer_strategy
    query = result_set.structured_query
    label = _concept_label(query)

    if strategy == EXACT_MATCH:
        return _compose_exact_match(result_set, label)
    if strategy == NO_EXACT_MATCH:
        return _compose_no_exact_match(result_set, label)
    if strategy == GROUPED_DISCOVERY:
        return _compose_grouped_discovery(result_set)
    if strategy == FILTERED_PRODUCT_LIST:
        return _compose_filtered_list(result_set, label)
    # Defensive fallback - should not be reached for a strategy this
    # module actually produces (app.presentation only emits the four above).
    return _compose_filtered_list(result_set, label)


def _compose_exact_match(result_set: ResultSet, label: str) -> str:
    n = result_set.matching_total
    if n == 1:
        return "Áno, túto variantu máme v ponuke:" if not label else f"Áno, {label.lower()} v tomto variante máme v ponuke:"
    return "Tieto varianty máme v ponuke:"


def _compose_filtered_list(result_set: ResultSet, label: str) -> str:
    n = result_set.matching_total
    shown = min(result_set.displayed_count, n)
    category = f' v kategórii "{label}"' if label else ""
    if n <= shown:
        return f"Máme {n} produktov{category}:"
    return f"Máme {n} produktov{category}. Tu sú najrelevantnejšie:"


def _compose_no_exact_match(result_set: ResultSet, label: str) -> str:
    nearest_n = len(result_set.nearest_match_ids)
    if nearest_n:
        return f"Presne tento variant momentálne v ponuke nevidím. Najbližšie možnosti ({nearest_n} nájdených):"
    return "Presne tento variant momentálne v ponuke nevidím."


def _compose_grouped_discovery(result_set: ResultSet) -> str:
    n = result_set.matching_total
    group_count = len(result_set.groups)
    lines = [f"Máme {n} produktov v {group_count} kategóriách. Tu sú tie najväčšie:"]
    for group in result_set.groups[: result_set.displayed_count]:
        lines.append(f"- {group['label']} ({group['product_count']})")
    return "\n".join(lines)


def compose_continuation_answer(result_set: ResultSet, revealed_count: int) -> str:
    """SHOW_MORE/SHOW_ALL response text - Section 9 requires the SAME
    ResultSet, so this never re-describes the query, only what just got
    revealed and what (if anything) is still left."""
    if result_set.answer_strategy == GROUPED_DISCOVERY:
        if result_set.has_more:
            return f"Tu sú ďalšie kategórie ({revealed_count}):"
        return f"Tu sú posledné kategórie ({revealed_count}):"
    if result_set.has_more:
        return f"Tu je ďalších {revealed_count}:"
    return f"Tu je zvyšných {revealed_count}:"


def compose_show_more_label(result_set: ResultSet) -> str:
    """Section 39 - contextual microcopy, semantic action stays SHOW_MORE/
    SHOW_ALL server-side; this is just the SK default text (localization
    infra can translate per Section 40, not hardcoded backend behavior)."""
    remaining = result_set.remaining_count
    if result_set.answer_strategy == GROUPED_DISCOVERY:
        return f"Zobraziť ďalšie kategórie ({remaining})"
    if remaining <= result_set.page_size:
        return f"Zobraziť všetkých {len(result_set.ranked_product_ids)}"
    return "Zobraziť viac"
