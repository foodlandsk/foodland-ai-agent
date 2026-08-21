# Workflow Migration Ledger — V2.13d

Dátum: 2026-08-21. Pokračovanie `docs/workflow-migration-v2.13c.md` —
V2.13c migroval 2 zo 4 `workflow_id` (`RESULTSET_CONTINUATION`,
`ALLERGEN_SAFETY`). V2.13d re-auditoval zvyšných ~9 `LEGACY_ROUTING`/
`LEGACY_EXECUTION` vetiev priamo v aktuálnom kóde (nie len z V2.13c
dokumentácie) a zistil, že ich skutočná zložitosť je VÝRAZNE
nerovnomerná — nie jednotná "9 podobných vetiev", ako V2.13c's pôvodná
klasifikácia predpokladala.

## Migrované V2.13d

| vetva | staré miesto | nové miesto | testy | stav |
|---|---|---|---|---|
| `missing_composition` | inline, ~13 riadkov, okamžitý return | `execute_missing_composition()` | `tests/test_workflow_executor_v2_13d.py::TestMissingCompositionIntegration` | **DONE** |
| `faq` | inline, ~16 riadkov, okamžitý return | `execute_faq()` | `TestFaqIntegration` | **DONE** |
| `random_recipe` | inline, ~16 riadkov, okamžitý return | `execute_random_recipe()` | `TestRandomRecipeIntegration` | **DONE** |
| `reset` | inline, ~15 riadkov, okamžitý return | `execute_reset()` | `TestResetIntegration` (vrátane state-mutation parity — `subjects`/`diet_terms`/`active_result_set_id` clear presne raz) | **DONE** |
| `out_of_domain` (`unknown`) | inline, ~17 riadkov, okamžitý return | `execute_out_of_domain()` | `TestOutOfDomainIntegration` | **DONE** |
| `category_discovery` | inline, ~12 riadkov, okamžitý return | `execute_category_discovery()` | `TestCategoryDiscoveryIntegration` | **DONE** |

Všetkých 6 je mechanický, verbatim presun (rovnaký vzor ako V2.13c) —
žiadna zmena logiky, len relokácia. Overené: `git diff --stat` ==
`git diff --ignore-space-at-eol --stat` (byte-safe), priame `chat()`
porovnanie pred/po, plný pytest beh.

### Skutočný nález: `log_question()` lokálne tienenie neprežije presun cez modul

Plný pytest beh po prvej verzii migrácie odhalil 3 zlyhania v
`tests/test_execution_context.py::TestExecutionContextSuppressesCustomerAnalytics`
— `EVALUATION`/`SHADOW`/`LEARNING` kontext stále zapisoval do
`question_analytics.jsonl`, hoci nemal. Root cause: `_chat_impl()`
lokálne PREVIAZE meno `log_question` na začiatku funkcie
(`log_question = _real_log_question if execution_context.emit_customer_analytics
else (lambda *a, **k): None`) — toto funguje pre VŠETKÝCH pôvodných
~13 volacích miest v TEJ ISTEJ funkcii bez potreby upravovať každé
zvlášť, ale je to čisto lokálne k `_chat_impl()`'s vlastnému telu.
Keď `app.workflow_executor`'s handler zavolá `m.log_question(...)`,
Python vyhľadá meno v MODULE-LEVEL scope `app.main`, nie v
`_chat_impl()`'s lokálnom scope — teda vždy zasiahne SKUTOČNÚ,
bezpodmienečnú funkciu, úplne obchádzajúc potlačenie.

Toto NIE JE niečo, čo "verbatim code motion" samo zachytí — presun
MENÍ, na čo sa bare `log_question(...)` odkaz rozhoduje, práve preto,
že presúva kód cez modulovú hranicu. Nájdené AŽ plným pytest behom
(nie code review), presne preto je Section 92 zadania ("plná regresia
po KAŽDEJ migračnej skupine") kriticky dôležitá.

**Oprava**: každý handler, ktorý volá `log_question()`, teraz prijíma
explicitný `emit_customer_analytics: bool` parameter a sám ho
kontroluje pred volaním. `_chat_impl()`'s volacie miesta odovzdávajú
`emit_customer_analytics=execution_context.emit_customer_analytics`.
Týka sa VŠETKÝCH 7 handlerov, ktoré `log_question()` volajú (V2.13c's
`execute_allergen_safety` + V2.13d's 6 nových) —
`execute_resultset_continuation` nie je dotknutý (pôvodný kód
`log_question()` vôbec nevolal).

**Kľúčové zistenie oproti V2.13c's pôvodnej klasifikácii**: V2.13c
zaradil TIETO ISTÉ vetvy do "vyžadujú big-bang extrakciu, zdieľajú
prezentačnú pipeline" — po priamom prečítaní aktuálneho kódu riadok po
riadku sa ukázalo, že to bolo príliš opatrné zovšeobecnenie. Každá z
týchto 6 vetiev je v skutočnosti PLNE samostatná (okamžitý `return`,
nulová závislosť na `matches`/`structured_presentation`), presne v tom
istom tvare ako `ALLERGEN_SAFETY`, ktorý V2.13c už úspešne migroval.

## NEMIGROVANÉ V2.13d — `BLOCKED_WITH_REASON`, s dôkazom

### Recipe (`recipe_subject` + `recipe_followup`/ordinal/orphaned-followup pre-checks)

**Nie je to jedna vetva** — je to reťaz VZÁJOMNE ZÁVISLÝCH krokov:
`_active_recipe_id_before`/`_recipe_followup_result` (V2.9 recipe
follow-up rezolúcia) → ordinal-reference clarifikácia (podmienená
`_recipe_followup_result is None`) → orphaned-followup clarifikácia
(podmienená rovnakým) → hlavný `if recipe_subject:` blok (V2.8 recipe
graph, ~100 riadkov). Každý krok má VLASTNÝ early-return a VLASTNÚ
podmienku závislú na výsledku PREDCHÁDZAJÚCEHO kroku — toto nie je
sekvencia nezávislých "skús-a-ak-nevyjde-pokračuj" blokov (ako Group A),
je to stavový automat, kde poradie a presné podmienky SÚ sémantika
(V2.9's 19 testov práve túto krehkosť dokumentujú).

### Zdieľaná commerce/matches-dispatch pipeline (replacement, article, category-bundles, cross-sell fallback, plain product_search, + `RELATED_PRODUCTS`'s vlastné vykonanie)

**Priamy dôkaz zložitosti** (nájdený PRI pokuse o extrakciu, nie
predpokladaný): jediný súvislý blok od výpočtu `already_have_subject`
po finálny `return` má **~30+ vzájomne závislých lokálnych premenných**
prechádzajúcich cez viacero štádií (`matches` walrus-priradené vnútri
`elif` podmienky cez `structured_presentation`, `is_shopping_list_request`
vypočítané AŽ PO `matches`, `intent` odvodené z 6 rôznych signálov
naraz, `cart_candidates`/`missing_ingredients`/`shopping_list` reťazovo
závislé na `matches`+`intent`, `_cross_sell.build_cross_sell()` a
`_select_workflow()` volané len v JEDNEJ z dvoch return-vetiev). Presun
tohto ako JEDNEJ funkcie by vyžadoval bezchybne zachytiť všetkých ~30
závislostí v jednom byte-safe patchi bez akéhokoľvek priebežného testu
medzi krokmi — presne ten "big-bang" prístup, ktorý toto aj predošlé
zadanie (Section 36, Invariant #14) explicitne zakazujú bez rozsiahleho
charakterizačného pokrytia, ktoré toto sedenie nemá k dispozícii.

**Prečo to NIE JE prehliadnutie**: V2.13c aj V2.13d nezávisle prišli k
tomu istému záveru PO priamom prečítaní kódu (nie z predpokladu) — toto
je opakovane potvrdená, evidovaná realita architektúry, nie
neochota skúsiť.

**Rozsah zostávajúceho dlhu PO V2.13d** (presnejšie než V2.13c-éra
odhad "9 vetiev"): 2 zostávajúce jednotky —
1. Recipe stavový automat (recipe_followup + ordinal + orphaned-followup + recipe_subject).
2. Commerce matches-dispatch + zdieľaná prezentačná pipeline (obsahuje interne: `already_have_subject`, `special_subject` bundly, `replacement_subject`, `article_product_subject`, `cross_sell_matches` fallback, `related_subject` fallback, plochý `product_search`, a `RELATED_PRODUCTS`'s vlastné vykonanie).

## `RELATED_PRODUCTS` execution gap — stav po V2.13d

**Nezatvorené.** `_related_products_forced` (V2.13b, nezmenené) zostáva
PRVOU podmienkou v tej istej zdieľanej `matches`-dispatch kaskáde ako
pred V2.13d — jeho VYKONANIE stále zdieľa ~30-premennú pipeline s 7
ďalšími legacy vetvami z rovnakého dôvodu vyššie. `resolved_workflow ==
executed_workflow` zostáva PRAVDA (overené testom,
`app.workflow_resolver` rozhoduje kauzálne, `_related_products_forced`
skutočne riadi, ktorá `matches`-vetva sa spustí) — týka sa to ROZHODNUTIA,
nie FYZICKÉHO umiestnenia vykonávacieho kódu v `app.workflow_executor`.
