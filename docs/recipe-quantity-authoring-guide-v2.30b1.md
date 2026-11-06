# Recipe Quantity Authoring Guide — V2.30b.1

## Purpose

Foodland AI can already *display* a shopping list for a dish ("Nákupný
zoznam na sushi") and already has the code to **scale that list to a
requested number of servings** and **calculate how many packages to buy**.
That code has existed and been tested since V2.8 — but it has never
activated on a real dish, because no real dish in this repository carries
a trustworthy quantity (e.g. "300 g rice", "2 tbsp fish sauce") or a
baseline serving count ("this recipe serves 4").

V2.30a (read-only review) confirmed this exhaustively: **0 of 50 curated
dishes, 0 of 221 ingredient rows, have a structured quantity anywhere in
the repository** — not in the CMS `Recipes` section, not in
`RECIPE_SHOPPING_CORE_QUERIES`, not anywhere. See
`docs/recipe-knowledge-audit.md` for the full historical audit.

This sprint (V2.30b.1) does **not** add any real quantities. It prepares
a **draft authoring pack** — `data/editorial/recipe_quantity_authoring_v2_30b1.json`
— with every ingredient the production system already recognizes for 5
pilot dishes, and a blank slot for you (or Foodland's content team) to
fill in real numbers from a real Foodland-approved source.

**This file is not read by the live application.** Nothing in `app/`
references `data/editorial/` or this filename. Filling it in changes
nothing about what customers see until a future, separate sprint
explicitly wires approved data into production — and that sprint will
only use rows marked `APPROVED` below.

## What `base_servings` means

Every quantity you enter must be **for a specific number of people**. If
your source recipe says "300 g rice noodles" and serves 4 people, then:

```
base_servings = 4
```

and the rice noodles row gets:

```
quantity = 300
unit = "g"
```

If you don't know how many servings the quantities are for, **leave
`base_servings` as `null`**. A quantity without a serving baseline cannot
be scaled safely, so the system will simply never scale that dish —
which is the safe, correct behavior, not a bug.

## How to enter a quantity

- Enter **only** the quantity your approved Foodland source actually
  states for that ingredient, at that `base_servings` count.
- **Do not** estimate from how the product is packaged ("the bag is
  500 g, so I'll say 500 g").
- **Do not** derive a quantity from a customer's serving request — this
  file holds the *base* recipe quantity only; scaling happens later, in
  code that already exists.
- **Do not** use your own culinary knowledge, a general web recipe, or
  an AI-generated estimate. If you don't have a real number, leave it
  `null`. A `null` quantity is a correct, safe answer — it is not a
  failure.

## Allowed units

Prefer these four, because the existing package-count code only
converts between them safely:

```
g   kg   ml   l
```

If your actual Foodland source states the quantity in a different unit
(pieces, tablespoons, leaves, cloves, sheets, etc.), **record it
faithfully in that unit anyway** — do not force a bad conversion. Just
know that automatic "how many packages to buy" math will not run for
that ingredient yet (see `scaling_unit_readiness` below), only the
scaled *quantity* itself.

### Units NOT supported for automatic package-count math

```
ks (pieces)   tbsp   tsp   leaf   clove   bunch   slice
```

This is a known, intentional limitation of the current code (see
V2.30a). It is not something you need to work around — just enter the
real quantity in the real unit anyway.

## Required provenance

Every quantity you enter must eventually have a `source_reference` —
something another person could check. Examples:

- a Foodland CMS recipe ID
- a Foodland recipe article ID or URL
- an internal cookbook page/reference
- an editorial approval ticket number

**No anonymous numbers.** If you can't point to where a number came
from, it isn't ready to enter yet.

## Per-ingredient editorial fields (for your reference, don't need editing)

Each ingredient row already includes, pre-filled by this sprint, three
read-only fields to help you prioritize:

- `scaling_unit_readiness` — whether the ingredient is the kind of thing
  Foodland sells by weight/volume (`MASS_VOLUME_READY`) or not.
- `package_size_readiness` — whether the real candidate products Foodland
  currently sells for this ingredient have a structured package size
  (`PACKAGE_SIZE_READY`, `PARTIAL_PACKAGE_SIZE`, or
  `NO_STRUCTURED_PACKAGE_SIZE`).
- `candidate_products_sample` — up to 3 real products currently matched to
  this ingredient, so you can sanity-check whether the quantity you're
  about to enter actually makes sense against what Foodland sells.
- `notes` — any editorial flag already discovered. For example, the
  sushi `wasabi` row currently flags that its top matched products are
  *not* real wasabi paste (a matcha gift set and wasabi-flavored snacks) —
  worth resolving before you author a quantity for it.

## Approval workflow

Each dish, and each ingredient within it, has a status:

```
NEEDS_AUTHORING  →  AUTHORED  →  REVIEWED  →  APPROVED
                                           ↘  REJECTED
```

- `NEEDS_AUTHORING` — nothing entered yet (the starting state for every
  row in this draft).
- `AUTHORED` — you've entered a quantity/unit/source_reference.
- `REVIEWED` — a second person has checked it.
- `APPROVED` — ready for a future sprint to use. Requires `approved_by`
  and `approved_at` to be filled in, plus `source_reference` for every
  approved quantity.
- `REJECTED` — reviewed and found not trustworthy; leave quantity blank.

No row becomes eligible for production use before it reaches
`APPROVED` — this is enforced by the top-level `production_eligible`
flag (currently `false` for the whole file) and will be re-enforced by
whatever future sprint reads this data.

## Pilot dishes in this draft

5 dishes, 30 ingredient rows total:

| Dish | Ingredients |
|---|---|
| Pad Thai | 5 |
| Tom Kha Gai | 5 |
| Sushi | 6 |
| Tom Yum | 6 |
| Kimchi Ramen | 8 |

## V2.30b.1a update — Foodland website recipe sources

V2.30b.1a added a second valid provenance source to this pack:

```
FOODLAND_RECIPE_ARTICLE  — a recipe published on an official foodland.sk page
```

(alongside the original `FOODLAND_EDITORIAL` provenance used for rows still
awaiting a source). For each pilot dish, the canonical Foodland recipe page
used is recorded in the new top-level `source_manifest` array
(`dish_id`, `source_url`, `source_title`, `source_status`,
`base_servings_evidence_status`).

**What ingestion from a website source means in practice:**

- Only a quantity/unit/servings value **explicitly printed on the Foodland
  page** was entered — nothing was estimated, converted from packaging, or
  inferred by an AI model. Every `AUTHORED` row carries the literal source
  wording in `source_quantity_text` and the page URL in `source_reference`.
- Each row also carries a `mapping_confidence` (`EXACT`, `HIGH`,
  `AMBIGUOUS`, or `NO_MATCH`). Only `EXACT`/`HIGH` rows were allowed to move
  to `AUTHORED` automatically. `AMBIGUOUS` and `NO_MATCH` rows stay
  `NEEDS_AUTHORING` — for example, a kimchi ramen page that only says
  "2 tbsp grated seaweed" without naming `wakame` or `nori` specifically
  cannot be auto-assigned to either row.
- **Servings ambiguity is never resolved silently.** If a Foodland page
  states two different serving counts for the same dish (this happened for
  Tom Kha Gai — "4 osoby / 8 porcií" in one sentence), `base_servings` stays
  `null` and the dish gets a new `editorial_review_note` field explaining
  the conflict, instead of guessing which number is right.
- **Culinary/count units are preserved, never force-converted.** A
  quantity stated in `PL`/`lyžica` (tbsp), `list` (leaf), `plátok` (slice),
  `pohár` (cup), `stonka` (stalk), or `porcia` (portion) is recorded exactly
  as published, with `scaling_unit_readiness` set to
  `CULINARY_MEASURE_UNSUPPORTED` or `COUNT_UNIT_UNSUPPORTED` — the
  package-count math simply won't run for that row yet, same limitation
  as before this sprint.
- **A deterministic multiplier expression may be normalized.** "2 x 400 ml"
  was recorded as `quantity: 800, unit: "ml"` with the original "2 x 400ml"
  text kept in `source_quantity_text` — this is the one case where this
  sprint's rules allow arithmetic (exact, unit-safe, no density/culinary
  assumption involved).
- Ingredients a Foodland page mentions that aren't one of this dish's
  canonical pilot ingredient rows (e.g. chicken, lime, shrimp stock) are
  recorded for evidence only in the top-level
  `unmapped_foodland_recipe_ingredients` array — they are never added to
  production recipe-shopping definitions.
- `AUTHORED` still only means "grounded in a real, checkable Foodland
  source" — it is **not** `APPROVED`. A human editor must still review every
  row (right source page? right mapping? faithful extraction?) and set
  `approval_status`/`author_status` to `APPROVED` with `approved_by` and
  `approved_at` before any future sprint may use this data.

## What happens after you approve data

```
V2.30b.1   →  draft authoring pack (done)
V2.30b.1a  →  Foodland website source ingestion (done, partial - see
              source_manifest / unmapped_foodland_recipe_ingredients)
           ↓
   HUMAN AUTHORING + APPROVAL  (you / Foodland content team)
           ↓
V2.30b.2   →  approved-data validation (future sprint)
           ↓
V2.30c     →  production scaling activation / pilot validation (future sprint)
```

Nothing after this sprint happens automatically. A human must review the
authored rows, fill in the rest, and approve the data first.
