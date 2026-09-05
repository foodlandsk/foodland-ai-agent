# V2.20 — Independent Scenario Factory & Holdout Architecture

## Purpose

The V2.18 benchmark (66 canonical scenarios + 244 safe mutations = 310
cases, currently 310/310 PASS) is a **regression core**: it answers
"did Foodland preserve previously-known-correct behavior?" It does not
answer "how intelligent is the Advisor on realistic customer problems
it has never been optimized against?" V2.20 builds an **independent
challenge benchmark** for that second question.

- **REGRESSION_CORE_V218** — the existing 310 cases. Frozen, immutable,
  unchanged by V2.20a (`eval/golden/regression_bugs.json`,
  `eval/golden/v2_18_curated_scenarios.json`).
- **V2.20 DEV/HOLDOUT** — new, independent scenarios
  (`eval/golden/v2_20_scenarios.json`), never executed against the
  Advisor during V2.20a. A future V2.20b sprint runs them blind.

## Program sequence

- **V2.20a** (this sprint): build the test. Scenario factory,
  taxonomy, difficulty model, ground-truth governance, DEV/HOLDOUT
  split, manifests. Zero Advisor executions.
- **V2.20b** (future, separately authorized): take the test. Blind
  execution of DEV then HOLDOUT, raw result storage, dimension
  scoring. No expectation edits, no fixing.
- **V2.20c** (future): failure intelligence map from the blind results.
- **V2.20d+** (future): human-selected bounded improvements.

## Blindness rule

No V2.20 scenario in `eval/golden/v2_20_scenarios.json` has ever been
executed through `/chat`, the Advisor engine, the evaluation adapter,
or shadow ranking. Ground truth was derived entirely from
`data/products.json`, `data/knowledge.json`, and existing production
contracts in `app/main.py`/`app/use_case_advice.py` — never from
observing a current model answer.

**Structural enforcement, not just discipline**: `app/intelligence_
diagnostics/v220_factory.py` never imports `app.main`, `app.advisor_
engine`, or `app.evaluation.adapter` (enforced by `tests/test_v220_
scenario_factory.py::TestBlindnessInvariant`, AST-based, not a
substring check). `app.intelligence_diagnostics.scenario_registry.
load_all_scenarios()` — the function `scripts/run_intelligence_
benchmark.py` and the 310-case regression core both call — never reads
`eval/golden/v2_20_scenarios.json`. V2.20 scenarios cannot enter the
existing execution path even by accident.

**Blind-run lock**: once a V2.20a freeze commit lands, no scenario
expectation may be edited between that commit and the first V2.20b
blind result. A factual error discovered before blind execution must
be fixed via a new, transparent version (new content hash, recorded
reason, prior manifest preserved in git history) — never a silent
edit.

## Capability taxonomy

Defined in `app/intelligence_diagnostics/scenario_schema.py::
CAPABILITIES` (additive — every V2.18 label is unchanged). V2.20a
additions: `CATEGORY_DISCOVERY`, `PRODUCT_TO_RECIPE`, `ALREADY_HAVE`,
`BUDGET_REASONING`, `QUANTITY_REASONING`, `MULTI_CONSTRAINT`,
`NEGATION`, `AMBIGUITY`, `CONSTRAINT_CHANGE`, `PREFERENCE`,
`PERSONALIZATION`, `DIETARY_SAFETY`, `INSUFFICIENT_DATA`,
`CULTURAL_AUTHENTICITY`. A scenario carries one `capability` (primary)
and zero or more `secondary_capabilities`.

Deliberately **not** added: `MULTILINGUAL`/`MIXED_LANGUAGE`/language
codes for CZ/DE/PL/HU/VI as first-class capabilities. Repository
inspection (V2.20a) confirmed `app.main.detect_query_language()` is a
binary sk/en heuristic; Czech/German/Polish/Hungarian/Vietnamese text
exists only as `Products_AI` marketing copy (130/2140 SKUs) in
`data/knowledge.json`, never as conversational language handling. See
"Language coverage" below.

## Difficulty model

Defined in `scenario_schema.py::DIFFICULTIES`, assigned by the author
at authoring time — never derived from or adjusted to match Advisor
performance.

| Level | Name | Definition |
|---|---|---|
| L1 | DIRECT | One clear intent, 0–1 constraints, explicit product/category. |
| L2 | COMPOSED | One primary intent, 2 constraints, straightforward reasoning. |
| L3 | MULTI_CONSTRAINT | 3+ interacting constraints, or meaningful comparison/replacement. |
| L4 | CONTEXTUAL | Multi-turn, changed constraint, already-have, negation, ambiguity resolution. |
| L5 | ADVERSARIAL_REALISTIC | Realistic ambiguity, conflicting constraints, insufficient evidence, complex reasoning. Never nonsense/benchmarkese. |

## Language coverage

**SK (primary) + EN only**, evidence-based per above. Achieved
distribution (106 scenarios): SK 91, EN 15 (~14%). No CZ/DE/PL/HU/VI
scenarios were authored — including them would have required inventing
conversational behavior the Advisor doesn't have, which V2.20a's own
blindness principle forbids as firmly as inventing product truth would.

## Ground-truth governance

Allowed authorities (`scenario_schema.py::GROUND_TRUTH_AUTHORITIES`,
unchanged from V2.18): `EXISTING_CONTRACT`, `EXISTING_GOLDEN`,
`AUTHORITATIVE_DATA`, `HUMAN_CURATED`, `VERIFIED_REPRODUCTION_
CONTRACT`. Forbidden, structurally rejected at `Scenario.__post_init__`
construction time: `CURRENT_MODEL_OUTPUT`.

A scenario whose correct behavior cannot be established from
repository data is `GROUND_TRUTH_PENDING` — retained as documented
future work, excluded from the scored denominator, never guessed. 15
of 106 V2.20a scenarios are PENDING, mostly `CULINARY_REVIEW_REQUIRED`
(quantity scaling, subjective taste comparisons, fermentation
technique) or `CATALOG_REVIEW_REQUIRED` (multi-SKU price totals,
per-SKU vegan claims — the latter explicitly because V2.16b already
found and removed an unreliable breadcrumb-based vegan/vegetarian
tagging attempt after it mis-tagged a chicken product).

## Catalog snapshot policy

`app.intelligence_diagnostics.v220_factory.compute_catalog_snapshot()`
hashes `data/products.json` content (SHA-256) rather than using a
wall-clock timestamp — reproducible from the file alone. Every
`catalog_dependency=true` scenario carries a `catalog_snapshot_id`
matching the frozen manifest's snapshot. Frozen at V2.20a: 2,140
products, snapshot `products_c2881106d6efc60e`, as-of commit
`77d106799d6ef650cadcb6d6436b5ab31eb017fc`.

**Stale-truth lifecycle**: `VALID` → `STALE_CANDIDATE` (catalog
changed in a way that might invalidate the scenario) → `REQUIRES_
REVALIDATION` → `RETIRED_WITH_HISTORY` (never silently deleted — a
scenario whose product disappeared from the catalog is retired with
its history preserved, not erased). No V2.20a scenario asserts an
exact SKU expectation unless the SKU identity itself is the contract
(e.g. an explicit price lookup) — most use `product_title_contains_
any`/`product_title_forbidden` membership checks instead (Section
39/40 of the originating mandate), tolerant of catalog reordering.

## DEV / HOLDOUT split

`app.intelligence_diagnostics.v220_factory.assign_split()`:
stratifies by **difficulty only** (not the full capability×difficulty×
language triple — with ~106 scenarios across ~25 capabilities, that
triple produces strata too small for a meaningful holdout cut; an
earlier draft of this algorithm proved this empirically, producing a
6% holdout with zero L4/L5/EN coverage before being corrected). Within
each difficulty bucket, scenarios sort by `(language, safety_sensitive,
capability, scenario_id)` before every-4th-item is assigned to
HOLDOUT — fully deterministic, no `random`/`time` involved
(`split_algorithm_version = "stratified_every_kth_v1"`).

**`HOLDOUT_IS_NOT_SECRET = TRUE`** — both splits live in this
repository. This is a governance boundary (not casually re-inspected
after every fix, not rewritten to accommodate Advisor results), not
cryptographic secrecy. **`AUTHOR_HAS_SEEN_HOLDOUT = TRUE`** — Claude
authored both DEV and HOLDOUT in the same pass; this is acceptable
per the originating mandate (Section 110), but V2.20b must still
execute HOLDOUT without editing expectations. A future, stronger
`HOLDOUT_EXTERNAL` layer (human/external custody, only manifest
hash/count/distribution stored in-repo) is recommended but not
implemented here.

Frozen split (106 total, 91 SCORED + 15 PENDING):

| | count | scored | pending | difficulties | languages | multi-turn | safety |
|---|---|---|---|---|---|---|---|
| DEV | 81 | 69 | 12 | L1-L5 | sk 74/en 7 | 3 | 5 |
| HOLDOUT | 25 | 22 | 3 | L1-L4 | sk 24/en 1 | 2 | 2 |

L5 (3 scenarios project-wide) and EN (8 project-wide) are too few to
guarantee proportional HOLDOUT representation at this benchmark size —
documented small-sample limitation, not a stratification bug.

## Scoring contract primitives

`app/intelligence_diagnostics/invariant_evaluator.py` gained 4 new,
purely-additive primitives for V2.20 (existing V2.10/V2.18 invariants
unchanged, verified via the full 310-case regression run before/after):
`product_title_contains_any:a|b|c`, `product_title_forbidden:x`,
`min_products:N`, `requires_uncertainty` (checks for the same
disclaimer vocabulary this project's own allergen/dietary abstention
answers already use). Most V2.20 scenarios reuse existing primitives
(`intent==X`, `products_nonempty`/`products_empty`, `answer_contains:`,
`cross_sell_separate`, `no_stock_certainty_claim`) unchanged.

## Future V2.20b scoring dimensions (design only, not calculated now)

Micro (overall pass rate), macro (equal-weight per-capability,
documenting small-sample caveats), per-difficulty, per-language,
single- vs multi-turn, safety-sensitive, multi-constraint. `PENDING`
is always excluded from the scored denominator and never silently
converted to `PASS`. **No target score is defined** — a low blind
score is valuable evidence, not a release failure; V2.20a's own
completion never depended on and does not require Advisor performing
well on unseen material.

## V2.20b handoff contract (do not execute now)

1. Verify commit SHA matches this document's frozen inputs (below).
2. Verify `eval/golden/v2_20_manifest.json` against a fresh
   `verify_manifest()` call.
3. Verify `eval/golden/v2_20_scenarios.json` content hash.
4. Refuse any scenario-expectation edit from this point forward.
5. Run DEV blind (via `app.evaluation.adapter.make_chat_fn`/`make_
   session_chat_fn`, EVALUATION context, never CUSTOMER).
6. Run HOLDOUT blind, same mechanism.
7. Store raw deterministic results (no interpretation yet).
8. Calculate the scoring dimensions above.
9. Do not fix anything found.
10. Produce a failure inventory (evidence, not verdicts).
11. STOP for human review.

## V2.20a frozen inputs (immutable until a new, versioned freeze)

- Commit: see `docs/routing-debt.md` V2.20a entry / git history for
  the exact SHA this document was frozen alongside.
- `eval/golden/v2_20_scenarios.json` — 106 scenarios, 91 SCORED / 15
  PENDING.
- `eval/golden/v2_20_manifest.json` — DEV (81) / HOLDOUT (25) manifests
  with content hashes, capability/difficulty/language distributions,
  catalog snapshot `products_c2881106d6efc60e`.
- `factory_version`: `v220a.1`. `split_algorithm_version`:
  `stratified_every_kth_v1`.
