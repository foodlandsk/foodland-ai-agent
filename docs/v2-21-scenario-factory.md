# V2.21a — Independent Fresh Scenario Factory & Reproducible Scoring Architecture

## Why V2.21 exists

V2.20 (`docs/v2-20-scenario-factory.md`) closed with DEV 69/69 and HOLDOUT
22/22 — every currently-known revealed failure in that benchmark generation
has been fixed or validly classified as a non-app defect. Re-running the
same 106 V2.20 scenarios against the current Advisor would no longer be a
measurement of anything: every scenario has already been individually
tuned against. V2.21 is a **new, independently authored** generation
whose contracts were established without ever inspecting how the current
Advisor answers them — the same blind-benchmark discipline V2.20 used for
its first run, applied to fresh material.

**V2.21a is not an Advisor repair sprint.** Its only job is to build the
benchmark: author scenarios, establish ground truth, write and prove a
scorer, split DEV/HOLDOUT, freeze everything, and stop. `NEW_V221_ADVISOR_
EXECUTIONS = 0` for the entire sprint — not even a single scenario was run
against the Advisor to check whether the wording "worked." Execution is
V2.21b's job, and only V2.21b's.

## Closing V2.20's one architectural gap

V2.20's scenarios and split were fully committed and reproducible, but the
scoring implementation that produced the historical 67/91 and DEV 69/69 /
HOLDOUT 22/22 numbers was an ad-hoc script that was never committed — a
fresh clone of this repository cannot re-derive those exact numbers from
committed code alone (a Claude session had to hand-reconstruct a scorer
for a subset of invariant types to independently re-verify DEV/HOLDOUT in
a later session, per `roadmap-features.md`'s own audit trail). V2.21 closes
this gap structurally: `app/intelligence_diagnostics/v221_scorer.py` is
the single, committed, deterministic scorer — every invariant type used
by any SCORED V2.21 scenario has an executable handler in that file, and
`app/intelligence_diagnostics/v221_factory.py::validate_scenarios()`
hard-fails the freeze if a scenario declares an invariant the scorer
cannot execute (Section 36/51/78).

## Architecture

| Artifact | Path | Role |
|---|---|---|
| Scenario data model | `app/intelligence_diagnostics/scenario_schema.py` | Reused unchanged from V2.18/V2.20 — `Scenario`/`Persona`/`ScenarioTurn`, already proven and tested; V2.21 adds no new schema, only new capability labels |
| Factory | `app/intelligence_diagnostics/v221_factory.py` | Load/validate/split/manifest/freshness-check. Reuses V2.20's generic split/hash/manifest primitives directly (`app.intelligence_diagnostics.v220_factory`) rather than duplicating proven logic |
| Scorer | `app/intelligence_diagnostics/v221_scorer.py` | Deterministic, local, offline invariant registry. No LLM judge, no network, no Advisor import |
| Scenario data | `eval/golden/v2_21_scenarios.json` | 143 scenarios |
| Manifest | `eval/golden/v2_21_manifest.json` | DEV/HOLDOUT counts, hashes, catalog snapshot, distributions |
| V2.21b runner | `scripts/run_v221_benchmark.py` | Prepared in V2.21a, **not invoked with `--execute-advisor` until V2.21b** |
| Scorer tests | `tests/test_v221_scorer.py` | Fake-fixture unit tests, self-integrity proofs |
| Factory tests | `tests/test_v221_scenario_factory.py` | Schema/validation/split/manifest/freshness tests, blindness-invariant tests |
| Runner tests | `tests/test_v221_runner.py` | Mock-based default-safety, execution-context, session-isolation proofs |

None of the modules above import `app.main`, `app.advisor_engine`, or
`app.evaluation.adapter` at module load time — proven structurally (AST
inspection, not just discipline) in
`tests/test_v221_scenario_factory.py::TestBlindnessInvariant` and
`tests/test_v221_runner.py::TestDefaultNoExecution`.

## Capability taxonomy

V2.21 reuses the full V2.18/V2.20 capability vocabulary
(`app.intelligence_diagnostics.scenario_schema.CAPABILITIES`) unchanged,
plus six genuinely new labels with no prior equivalent
(`app.intelligence_diagnostics.v221_factory.V221_NEW_CAPABILITIES`):
`TYPO_ROBUSTNESS`, `MULTI_TURN_STATE`, `BRAND_CONSTRAINT`, `KITCHENWARE`,
`RELATED_PRODUCTS`, `GENERAL_CULINARY`.

## Ground-truth sources

Every SCORED scenario's authority is one of `EXISTING_CONTRACT`,
`EXISTING_GOLDEN`, `AUTHORITATIVE_DATA`, `HUMAN_CURATED`,
`VERIFIED_REPRODUCTION_CONTRACT` — never `CURRENT_MODEL_OUTPUT` (enforced
at construction time by `Scenario.__post_init__`, the same hard guard
V2.20 relies on). Concretely, V2.21's ground truth comes from:

- **`data/products.json`** (2140 products, snapshot `products_c2881106d6efc60e`) — read directly for real titles/brands/prices/categories. Authority: `AUTHORITATIVE_DATA`.
- **`data/knowledge.json`'s `FAQ` section** (52 real Q&A pairs) — every V2.21 FAQ scenario paraphrases a real entry, never copies it verbatim. Authority: `AUTHORITATIVE_DATA`.
- **`app.main`'s static `REPLACEMENT_PRODUCT_QUERIES` and recipe-ingredient dictionaries**, read as plain data (never executed) — same pattern the existing `v220_replacement_0011` contract already established. Authority: `EXISTING_CONTRACT`.
- **Existing frozen V2.20 contracts** for capability shapes V2.20 already validated (e.g. `AMBIGUITY`, `OUT_OF_DOMAIN` both reuse V2.20's exact `answer_nonempty`-only contract shape rather than a fresh, unverified assumption — see the worked correction below). Authority: `EXISTING_CONTRACT`.

Where none of the above could establish independent ground truth (a
subjective "which is best" judgment, an open-ended recommendation basket,
a culinary-technique explanation with no committed answer-content
reference), the scenario is `GROUND_TRUTH_PENDING` — 24 of 143 scenarios.
PENDING scenarios remain in the dataset and in coverage reporting, are
excluded from the scored denominator, and must never silently become
PASS or FAIL (Section 29).

**A worked example of the discipline this enforces**: the first draft of
this dataset's `OUT_OF_DOMAIN` scenarios asserted `products_empty` as the
expected contract — a plausible-sounding but unverified assumption about
how the Advisor's fallback path behaves for weather/sports/medical
queries. Cross-checking against V2.20's own already-frozen
`v220_out_of_domain_0001`/`0002` scenarios showed the established,
already-proven contract is `answer_nonempty` only. The draft was corrected
to match that precedent rather than inventing a new, unverified assumption
— exactly the kind of self-correction Section 2's blindness rule exists to
force by removing "just check what it actually returns" as an option.

## Scorer

`app/intelligence_diagnostics/v221_scorer.py`'s invariant grammar is
`TYPE` (bare) or `TYPE:ARG` (`ARG` may be `|`-separated alternatives).
Registry (`score_invariant()`):

| Invariant | Checks |
|---|---|
| `intent_is:X\|Y` | `result["intent"]` is one of the alternatives |
| `products_nonempty` / `products_empty` | `result["products"]` is/isn't empty |
| `answer_nonempty` | `result["answer"]` is non-blank |
| `answer_contains_semantic_concept:X\|Y` | normalized answer contains any alternative |
| `product_family:X` / `expected_group_membership:X` | any product's category path contains X (aliased handlers) |
| `product_title_contains_any:X\|Y` | any product title contains any alternative |
| `product_title_forbidden:X\|Y` | no product title contains any alternative |
| `product_brand:X` / `forbidden_brand:X` | brand presence/absence across returned products |
| `cross_sell_nonempty` | `result["cross_sell"]` is non-empty |
| `cross_sell_separate` | zero product-id overlap between `products` and `cross_sell` |
| `requires_uncertainty` | answer contains a defined hedge phrase (sk+en) |
| `no_stock_certainty_claim` | answer contains no absolute stock-certainty phrase |
| `no_allergen_certainty_without_evidence` | answer contains no absolute allergen-certainty phrase |

Unknown invariant type → `ERROR`, always — never silently `PASS` or
ordinary `FAIL` (proven in `TestUnknownInvariant`/
`TestMalformedInputSelfIntegrity`). Result states: `PASS`, `FAIL`,
`PENDING`, `ERROR`; a scenario's aggregate state is `ERROR` if any
invariant errored, else `FAIL` if any failed, else `PASS`.

Normalization: NFKD-decompose + drop combining marks + lowercase — an
independent reimplementation of `app.search.normalize()`'s algorithm with
zero import coupling, so `ryžový`/`ryzovy`, `omáčka`/`omacka`,
`sójová`/`sojova` compare equal while negation words, numbers, and brand
letters survive unchanged.

## Freshness

`v221_factory.check_textual_freshness()` compares every V2.21 message
against the full V2.18 (`scenario_registry.load_all_scenarios()`, 66
scenarios) + V2.20 (`v220_factory.load_v220_scenarios()`, 106 scenarios)
historical corpus — 200 historical messages total. Two categories:
`exact_duplicates` (identical normalized text) and `near_duplicates`
(≥90% token-Jaccard overlap). This is a **textual** check only
(`TEXTUAL_DUPLICATE_CHECK`), not proof of semantic independence
(`AUTHORING_INDEPENDENCE_REVIEW` is a separate, human judgment this
document's authoring process itself represents). The first draft flagged
two bare single-word queries (`"gochujang"`, `"ryzovy ocot"`) as exact
duplicates of existing V2.18 golden cases; both were reworded before
freeze. Final result: 0 exact, 0 near duplicates against the historical
corpus, 0 internal semantic duplicates within V2.21 itself.

## Split

Stratified-every-Kth by difficulty (the same algorithm and rationale as
V2.20's `assign_split()`, reused directly), `holdout_fraction=0.25`.
Result: **109 DEV / 34 HOLDOUT** (23.8% holdout), scored counts 92/17
(DEV) and 27/7 (HOLDOUT). HOLDOUT spans 24 distinct capabilities and
includes safety-sensitive and multi-turn cases. The split was computed
once, from scenario metadata that existed before any Advisor execution
occurred (there was none) — not adjusted after seeing any result, because
no result exists yet.

## V2.21 HOLDOUT is a governance holdout, not a secret

Per Section 55: V2.21's HOLDOUT lives in the same repository as DEV, in
the same `eval/golden/v2_21_scenarios.json` file. Its independence comes
from being frozen *before* Advisor execution and never being tuned
against before V2.21b runs it — not from being hidden from the repository
author. Do not describe a future V2.21b result as "external" or "secret"
holdout evaluation; the correct term is `FIRST_FROZEN_V221_EVALUATION` or
`V221_FIRST_BLIND_RUN`.

## V2.21b protocol (binding for whoever runs it)

1. Start from these frozen V2.21a artifacts. Do not add, remove, or
   reword any scenario first.
2. Verify hashes: `python scripts/run_v221_benchmark.py` (no flags) must
   report 0 hard errors and 0 manifest mismatches before proceeding.
3. Record `EXECUTION_SHA` (`git rev-parse HEAD` at run time).
4. Run DEV first: `python scripts/run_v221_benchmark.py --split DEV --execute-advisor`.
5. Make **no intervention** based on DEV results — no fix, no reword, no
   contract change, no PENDING relabeling.
6. Run HOLDOUT: `python scripts/run_v221_benchmark.py --split HOLDOUT --execute-advisor`.
7. Make **no intervention** based on HOLDOUT results either.
8. Store raw + scored results under `eval/results/v2_21_b/` (never
   overwrite a prior run's directory).
9. Preserve the first blind result forever, the same way V2.20's
   `67/91 = 73.6%` remains immutable regardless of later fixes.
10. Do not fix anything discovered in this same sprint. A revealed
    failure becomes its own bounded repair sprint later (the same shape
    V2.20's `replacement_0011` investigation followed), never an
    in-the-moment patch.
11. Stop.

**Once DEV has been executed, no fix may occur before HOLDOUT runs** —
fixing anything between the two runs would let DEV results leak into
HOLDOUT's supposedly-independent measurement, exactly the failure mode
this two-phase protocol exists to prevent.

## Running the validator yourself

```
python scripts/run_v221_benchmark.py
```

reports scenario/error/warning counts and manifest verification, and
never imports `app.evaluation.adapter` — confirmed by
`tests/test_v221_runner.py::TestDefaultNoExecution`. Running with
`--execute-advisor` is V2.21b, not part of this document's own claims.
