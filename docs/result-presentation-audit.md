# Result Presentation Layer, Show More / Show All & Answer Composer — Sprint V2.5 audit

Dátum: 2026-08-15. Zdroj: committed `data/products.json` (2 140 produktov), V2.4 structured retrieval (`docs/structured-retrieval-audit.md`).

## Architektúra

```
V2.4 RetrievalResult + ranked ids   (app.retrieval / app.ranking)
  -> ResultSet                      (app/result_sets.py)
  -> Presentation Policy            (app/presentation.py: build_result_set)
  -> Answer Composer                (app/answer_composer.py: compose_answer)
  -> chat() response                (app/main.py, additive fields)
```

`app/structured_search.py: build_structured_result_set()` is the single
orchestration entry point: parses/merges the query, runs V2.4 retrieval +
ranking, then hands off to `app.presentation.build_result_set()`. Returns
`None` whenever structured retrieval cannot confidently answer (UNKNOWN
family, LOW confidence, internal error) — caller falls back to the
unchanged legacy chat answer path (Section 39/82).

V2.5 never redefines product validity (Section 2/89): `ResultSet.
ranked_product_ids` is exactly V2.4's `exact_match_ids` (or `nearest_
match_ids`/`valid_match_ids` as fallback tiers) in ranked order — this
module only decides how much of it to reveal and how to describe it.

## ResultSet schema (`app/result_sets.py`)

```python
ResultSet(
    result_set_id, raw_query, structured_query,
    answer_strategy,
    matching_total,            # primary valid matches ONLY (Section 5)
    ranked_product_ids,        # full ordered set, ids only (Section 3/48)
    exact_match_ids, nearest_match_ids, alternative_ids,
    groups,                    # GROUPED_DISCOVERY only
    displayed_count, page_size,
    catalog_version, taxonomy_version,
    created_at, expires_at,
)
```

`matching_total = len(exact_match_ids)` uniformly: when no brand/size was
explicit, V2.4 already sets `exact_match_ids == valid_match_ids` (nothing
to relax), so this is the full valid count; when relaxation happened
(NO_EXACT_MATCH), it is correctly `0`, with the nearest tier reported
separately — never folded into the primary count (Section 22).

In-memory TTL store (`DEFAULT_TTL_SECONDS = 1800`, `MAX_STORED_RESULT_
SETS = 20000`), same pattern as `app/main.py`'s `session_memories`. An
unknown or expired `result_set_id` resolves to `None`, never an error
(Section 47) — a forged id is indistinguishable from "no active result
set".

## Presentation Policy (`app/presentation.py`)

Four strategies actually auto-selected this sprint from V2.4's own
output, no new intent detection required (Section 23/52):

| strategy | trigger | initial | page |
|---|---|---|---|
| `EXACT_MATCH` | explicit brand/size, ≤3 exact matches | 3 | 3 |
| `FILTERED_PRODUCT_LIST` | explicit subfamily/attributes/dietary, or >3 exact matches | 4 | 4 |
| `GROUPED_DISCOVERY` | family only, ≥2 distinct concepts in the valid set | 5 groups | groups |
| `NO_EXACT_MATCH` | 0 exact, nearest tier non-empty | 3 (nearest) | 3 |

`COMPARISON`/`USE_CASE_ADVICE`/`RECOMMENDATION`/`REPLACEMENT`/`RECIPE_
SHOPPING` are **deliberately not** auto-selected here — they already have
dedicated, tested legacy detectors/handlers in `app/main.py` (comparison
questions, `alternative_products_for_subject()`, recipe shopping-core
functions, ...) and folding them into ResultSet is a larger, separate
effort than "make V2.4 retrieval pageable" (Section 52 — controlled
activation; those workflows keep their current presentation for now).

### Grouping

`build_groups()` groups the valid set by `ProductTaxonomy.concept_id`
(the same per-FamilyRule concept `build_concept_index()` already uses for
V2.2 autocomplete) — not by raw `subfamily`, since two rules can share a
subfamily (jasmine/basmati both → `plain_rice`) but are still distinct
customer-facing concepts (Section 15/16). Counts come from the CURRENT
`valid_match_ids` only — never the whole catalog, never hallucinated.

If fewer than 2 concepts exist in a "broad" query's valid set, the
strategy demotes to `FILTERED_PRODUCT_LIST` — a "group of one" serves the
customer worse than a flat list (Section 59).

For `GROUPED_DISCOVERY`, the ResultSet's pagination unit becomes GROUPS
(one representative product id per group), not raw products — "Show
More" on a broad query reveals more group cards; seeing every product
inside one group is a **group drill-down** (Section 18): a fresh,
narrower ResultSet built via `app.query_constraints.query_from_
constraints()` with that concept's `family`/`subfamily`/`attributes` —
the same V2.2 autocomplete handoff mechanism V2.4 already exposed.

## Show More / Show All (`app/main.py`, top-of-`chat()` branch)

A new, highest-priority branch (checked immediately after session memory
lookup, before allergen/FAQ/recipe/etc. detection) recognizes exact
continuation phrases (`SHOW_MORE_PHRASES`/`SHOW_ALL_PHRASES` — "zobraz
viac", "zobraz vsetky", "show more", "show all", ...) **only when an
`active_result_set_id` exists in session memory**. When it fires:

1. resolve the stored `ResultSet` (`None` if expired/unknown/catalog changed → falls through to normal routing, Section 45/47),
2. compute the newly-revealed slice (`next_page_ids()` or `remaining_ids()`) **before** mutating `displayed_count`,
3. return only that increment as `products` (the frontend appends), with `matching_total`/`has_more`/`result_set_id` unchanged in meaning.

No new search, no re-parsing of "zobraz vsetky" as a broad query text —
membership and order come entirely from the stored `ranked_product_ids`
(Section 9/10/14).

## Legacy collision found and resolved

`app/main.py`'s pre-V2.1 `detect_special_product_subject()` has a broad
catch-all rule — `if "ryz" in normalized_message and not any(exclusion
markers): return "plain_rice"` — that intercepted **exactly** the two
mandated V2.5 test queries ("jazmínová ryža", "basmati ryža") before they
ever reached the new structured branch, since `elif special_subject:` is
checked earlier in the cascade than the plain product-search `else:`.

Fixed surgically: when `special_subject == "plain_rice"`, structured
retrieval is now tried **first**; only if it returns `None` does the
original `special_products_for_subject()` legacy call run as a safety-net
fallback (Section 39/82). Every other `special_subject` entry (`mild`,
`hot`, `kids_snack`, `rice_cooker`, `sushi_rice`, `vegan_asian`, ...) is
completely untouched — this migrates only the one entry V2.3/V2.4's
taxonomy engine genuinely supersedes with a more precise, pageable
answer, not the whole legacy mechanism.

## Follow-up constraint persistence (Section 13)

`app.query_constraints.merge_constraints(base, addition)` keeps `family`/
`subfamily`/`attributes` from the base query and layers in any new
explicit brand/size/dietary from the follow-up. `build_structured_result_
set()` only merges when the follow-up's own parse has **no family of its
own** — a message that names a new concept is treated as a fresh query,
not a narrowing, so "jazmínová ryža" → "sójová omáčka" correctly starts
over rather than nonsensically merging two families.

## Answer Composer (`app/answer_composer.py`)

Deterministic, template-based — **not an LLM call** (Section 24/50): the
composer never decides product validity, counts, or which ids belong; it
only phrases what `app.presentation` already decided. This keeps every
wording rule mechanically testable and keeps the primary structured path
free of OpenAI cost/latency/non-determinism. Sidesteps Slovak noun
declension (genitive plural of an arbitrary taxonomy label is not
mechanically derivable) by phrasing counts as `N produktov v kategórii
"Label"` rather than inflecting the label.

Wired into `chat()` as a **new, higher-priority early return** than the
existing `should_use_fast_chat_answer()` fast path — whenever structured
presentation applies, it always wins over the generic OpenAI/fallback
answer, with zero OpenAI calls for that turn.

## Testy (`tests/test_result_presentation.py`, 22 tests)

Pagination completeness (union of all pages = full valid set, no dupes,
`has_more=False` after the last page), Show All union (initial ∪
remainder = full ranked set, no overlap), related contamination (every
page of a jasmine ResultSet stays 100% jasmine), grouped discovery (real,
non-hallucinated per-concept counts), specific-vs-broad strategy
selection, follow-up constraint persistence (merged query keeps
family/variety, adds size; a bare follow-up with no active ResultSet
never hallucinates a family), no-exact-match distinction, answer wording
rules (no-exact-match language only on that strategy, matching_total
appears in the answer, group labels/counts appear verbatim, no cross-sell
phrasing on primary results, continuation text never re-describes the
query), ResultSet store (unknown/expired id → `None`, valid id
retrievable), ranking stability across pagination.

Plný beh: **731/731** (709 pred V2.5 + 22 nových), 0 regresií.

## Performance

Building a full ResultSet (parse + retrieve + rank + strategy + grouping)
adds negligible overhead over V2.4's own retrieve+rank cost (same
in-memory set operations, plus one pass to bucket by `concept_id` for
`GROUPED_DISCOVERY`). Show More/Show All continuation is a slice of an
already-materialized `ranked_product_ids` list — O(page_size), no
re-retrieval, strictly faster than a fresh search (Section 49/80).

## Widget (`app/widget.js`)

Incremental, not a redesign (Section 71): the existing client-side
"Zobraziť viac" button (which only ever paginated over whatever was
already in the current response's `products[]`) now also accepts a
`hasServerMore` flag from `data.has_more`. When the locally-held batch is
exhausted but the server has more, the button switches to "Zobraziť
všetky" and — on click — resubmits the existing `/chat` form with the
canonical phrase `"zobraz vsetky"`, reusing the exact same request flow
already wired to the new backend continuation branch. No new endpoints,
no new fetch plumbing.

## Cross-sell foundation (Section 34/35)

`ResultSet.alternative_ids` exists in the schema (currently always `[]`
this sprint) and the response never mixes anything into `matching_total`
or the primary `products[]` beyond the ResultSet's own ranked ids. Full
contextual cross-sell intelligence is explicitly out of scope — V2.6.

## Zostávajúce riziká (úprimne, nie vyhladené)

- `COMPARISON`/`USE_CASE_ADVICE`/`RECOMMENDATION`/`REPLACEMENT`/`RECIPE_
  SHOPPING` strategies are defined as constants but not yet auto-selected
  from a RetrievalResult — those customer intents still use their
  existing, separately-tested legacy answer paths untouched this sprint.
- Only the `plain_rice` legacy `special_subject` entry was migrated to
  try structured retrieval first; other rice-adjacent legacy entries
  (`rice_side`, `mild`, `gluten_free_sushi`, ...) that also happen to
  contain rice phrases were deliberately left alone — they encode
  curated, multi-ingredient topic logic structured retrieval does not
  attempt to replicate this sprint.
- Personalization is not wired into `rank_candidates()`'s
  `personalization_scores` parameter for the primary structured path
  (same documented gap as V2.4) — and is now explicitly **skipped**
  (rather than applied post-hoc) for structured responses, to keep
  ResultSet pagination stable across pages (Section 44) instead of
  silently reordering between turns.
- Widget Show More/Show All reuses the chat form's canonical phrase
  rather than a dedicated structured action/button distinct from typed
  text — sufficient for this sprint's scope, but a true semantic
  `SHOW_MORE`/`SHOW_ALL` UI action (Section 39/73, decoupled from literal
  phrase matching) would be more robust for accessibility/i18n in V2.6+.

## Ako znovu overiť

```bash
python -m pytest tests/test_result_presentation.py -q
```
