# V2.23a — Real Customer Learning Framework & Scenario Intake

## Central principle

Customer behavior is evidence of a problem. It is never evidence of the
correct answer. Current Mei/Advisor output is never ground truth. No
code path in `app/scenario_candidates.py` can treat either as a trusted
authority — see `FORBIDDEN_AUTHORITIES` and the tests in
`tests/test_scenario_candidates.py` that assert this.

## Why this is a new, separate system

The repository already has a "learning" framework — `app/learning_candidates.py`,
`app/learning_lifecycle.py`, `app/learning_cycle.py`,
`app/learning_opportunities.py`, `app/learning_signals.py`,
`app/learning_events.py`. That system turns **aggregate behavioral
metrics** (zero-result rate, reformulation rate, CTR anomalies) into
**ranking-weight candidates** (`RankingProfile` overrides), validated
through the V2.10 evaluation harness and promoted only by a named human
via `approve_and_activate()`.

This is a different problem: turning **one real customer's conversation
failure** into a **candidate benchmark scenario** (the same shape as
`eval/golden/*.json`), reviewed and promoted by a human separately. The
two systems share a *pattern* (append-only ledger, no auto-promotion,
named-human-required activation) but not a data model — `LearningCandidate`
is typed around `RankingProfile`; a scenario candidate is typed around a
customer query, expected intent/behavior, and entity state. Reusing the
existing module directly would have meant bolting an incompatible shape
onto it. Instead, this sprint reuses the *pattern* and the *lower-level
primitives* (see below) and gives the new concept its own, clearly-named
module: `app/scenario_candidates.py`.

## What was reused, not reinvented

| Existing component | Reused for |
|---|---|
| `app.main.redact_pii()` | email/phone redaction (same lazy-import pattern as `app.customer_audit._redact()`) |
| `eval/golden/*.json` ground-truth-authority vocabulary (`AUTHORITATIVE_DATA`, `EXISTING_CONTRACT`, `HUMAN_CURATED`, `VERIFIED_REPRODUCTION_CONTRACT`) | `ALLOWED_GROUND_TRUTH_STATUSES` / `TRUSTED_AUTHORITIES` — no new vocabulary invented for golden-facing fields |
| `app.learning_lifecycle._append_ledger` / `record_transition` pattern (immutable, append-only JSONL, never mutate in place) | `apply_human_review()` — a review is a new line, never an edit to the original candidate |
| `app.intent.CustomerIntent.customer_has` | confirms `ALREADY_HAVE` is **not** a new concept — see below |
| `app/main.py` `ALREADY_HAVE_MARKERS` / `ALREADY_HAVE_SUBJECT_MAP` / `ALREADY_HAVE_COMPLEMENT_QUERIES`, `app/recipe_shopping.py` `RECIPE_ALREADY_HAVE` | confirms a production mechanism for "exclude what the customer already has" already exists |

**Nothing in this sprint duplicates any of the above.** `app/scenario_candidates.py`
defines its *own* `ENTITY_STATES` vocabulary purely for describing state
on an intake record — it does not touch, call, or wrap the production
`detect_already_have_subject()` function.

## The `ALREADY_HAVE` gap this sprint found (not fixed)

`detect_already_have_subject()` (`app/main.py`) requires one of
`ALREADY_HAVE_MARKERS` ("mám ", "vlastním ", "kúpil som ", …) to appear
**literally**, in the same clause as the subject alias. Rice is already
in `ALREADY_HAVE_SUBJECT_MAP` as `"ryza"`.

The canonical seed query **"Čo variť k ryži?"** ("What to cook with/for
rice?") contains no such marker — it implies possession through "what
goes with X" framing, not an explicit "I have X" statement. Confirmed by
direct inspection: this phrasing does not and cannot trigger
`detect_already_have_subject()` today.

This is real, narrow, and well-characterized evidence for a **future**
bounded-repair candidate (same discipline as the V2.22 FAQ repair
chain). It is **not fixed in V2.23a** — Advisor Behavior Freeze (mandate
Section 31) applies; this document and the candidate record in
`eval/candidates/real_customer/candidates.jsonl` (`rc-c444e16673f0`) are
the entire output of this finding for this sprint.

## The `ORDER_SUPPORT` / `INVOICE_SUPPORT` gap this sprint found (not fixed)

No equivalent of `ORDER_SUPPORT`, `ACCOUNT_SUPPORT`, or `INVOICE_SUPPORT`
exists in `app.intent.PRIMARY_INTENTS`, nor is there a dedicated FAQ
marker/shortcut for "faktúra"/"posledná objednávka"/"stav objednávky"
framed as an account-support request rather than a store-policy FAQ (the
closest existing FAQ entries — #45 order tracking, #17 damaged item —
answer *adjacent* but not this* concept). The canonical seed
**"Dobrý deň, potrebovala by som faktúru k poslednej objednávke."**
currently falls through to plain `product_search` (confirmed: no
existing marker/shortcut recognizes it).

Same status as above: documented, recorded as a `HIGH`-risk pending
candidate (`rc-186acdd43f93`), **not fixed**.

## Lifecycle (no step may be skipped)

```
REAL_CUSTOMER_EVENT
  -> SANITIZED_CANDIDATE      build_candidate() — app/scenario_candidates.py
  -> HUMAN_REVIEW             apply_human_review() — append-only event
  -> GROUND_TRUTH_PENDING     default status; stays here until review resolves
  -> VALIDATED_SCENARIO       human sets a TRUSTED authority via review
  -> REGRESSION/GOLDEN CANDIDATE   future sprint: manual promotion into eval/golden
  -> ACCEPTED_TEST -> REPRODUCTION -> ROOT_CAUSE -> BOUNDED_REPAIR
     -> POST-REPAIR VALIDATION      existing V2.22-style bounded-repair discipline, unchanged
```

There is no function anywhere in this framework that goes directly from
`REAL_CUSTOMER_EVENT` to a golden/regression file.

## Storage

`eval/candidates/real_customer/candidates.jsonl` — git-tracked, reviewed
via normal PR diff, like `eval/golden/*.json` already is. **Not** a
Railway runtime/persistent-volume path (deliberately — see
`app/scenario_candidates.py` module docstring) — production traffic
cannot write here; only the offline CLI, run by a human, can.

`eval/candidates/real_customer/reviews.jsonl` — append-only human review
decisions, keyed by `candidate_id`.

## Intake

`scripts/add_learning_candidate.py` — offline CLI. No new HTTP endpoint,
no new auth surface (mandate Section 34). An operator runs it locally,
reads the printed sanitization summary, visually re-checks the output
for any remaining name/address/identifier, then commits the resulting
diff.

## Privacy / sanitization — honest limitations

Automatic redaction covers: email, phone (`app.main.redact_pii`), and a
conservative order/invoice-reference digit pattern and a conservative
capitalized-word-pair name heuristic (`app/scenario_candidates.py`).

**Regex cannot reliably strip every personal name or address.** This is
stated explicitly, not glossed over: the CLI's printed sanitization
summary always ends with "please visually confirm no PII remains before
committing," regardless of whether any pattern fired. The operator —
not the tool — is the final privacy gate before a candidate is
committed to a git-tracked file.

## Governance invariants enforced structurally (not just by convention)

- `build_candidate()` has no parameter that can set `ground_truth_status`
  or `ground_truth_authority` — every candidate is `GROUND_TRUTH_PENDING`
  with `ground_truth_authority=None` at creation, with no way to override.
- `ScenarioCandidate.__post_init__` rejects any `ground_truth_authority`
  in `FORBIDDEN_AUTHORITIES` (`CURRENT_MODEL_OUTPUT`, `CUSTOMER_CLICKED_THIS`,
  `CUSTOMER_PURCHASED_THIS`, `MODEL_MAJORITY_VOTE`, `ADVISOR_OUTPUT`,
  `AI_GENERATED`) and rejects any non-`PENDING` status without a trusted
  authority.
- `HumanReview.__post_init__` requires a non-empty `reviewer` identity
  and, for `APPROVE_AS_SCENARIO`, requires both a trusted `authority` and
  a non-empty `expected_behavior`.
- `apply_human_review()` only ever appends a new line to `reviews.jsonl`
  — there is no function in this module that edits an existing candidate
  or review record in place.
- `find_duplicate()` compares exact normalized text only — no model/
  embedding similarity is used as duplicate-detection authority.
- Nothing in this module imports or calls `app.main.chat()`, any
  retrieval/ranking/composition function, or writes to `eval/golden/`.

## Known technical debt / deferred work (documented, not implemented)

- No dashboard beyond `summarize()`'s plain counters (Section 26 of the
  mandate explicitly defers this).
- Near-duplicate (same failure family, different text) linking is not
  automated — a human must notice and link related candidates manually.
- Multi-turn `conversation_context` schema exists and round-trips, but
  no CLI flag populates it yet (single-turn intake only in this sprint's
  CLI); multi-turn intake would need its own, separate CLI ergonomics
  pass.
- The `ALREADY_HAVE` and `ORDER_SUPPORT`/`INVOICE_SUPPORT` gaps above are
  recorded, not fixed.
