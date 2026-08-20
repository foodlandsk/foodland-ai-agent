# Workflow Precedence — V2.13b (source of truth)

Dátum: 2026-08-20. Nahrádza `docs/workflow-precedence-before-v2.13b.md`
ako aktuálny stav (ten zostáva ako historický baseline záznam).

## Precedencia (najvyššia najprv)

| Priorita | Workflow | Vyžadované signály | Blokujúce signály | Kontext | Príklad | Fallback |
|---|---|---|---|---|---|---|
| 1 | `RESULTSET_CONTINUATION` | aktívne `active_result_set_id` + Show More/Show All marker | — | vyžaduje predchádzajúci ResultSet v session pamäti | "zobraz viac" | žiadny — vždy deterministické |
| 2 | `ALLERGEN_SAFETY` | `safety_intent` (= `detect_allergen_intent()` výstup) je nie-None | — (žiadne, ani `related_products_requested`) | žiadny špecifický | "sójová omáčka bez sóje" | `LegacyWorkflowAdapter` (missing_composition/faq/... kaskáda) |
| 3 | `RELATED_PRODUCTS` | `related_products_requested` (explicitná companion-jazyk fráza) **A** `related_products_anchor` (nie-None `related_subject`) | — | žiadny špecifický | "súvisiace produkty k sushi ryži" | `LegacyWorkflowAdapter` |
| 4 | `LEGACY_FALLBACK` | (žiadny z vyššie uvedených nezhoduje) | — | — | "jazmínová ryža", "Kikkoman", FAQ, recept, ... | `app.main._chat_impl()`'s existujúca ~11-vetvová kaskáda, NEZMENENÁ |

## Prečo presne toto poradie

1. **RESULTSET_CONTINUATION** je vždy prvá — nie je to nová interpretácia
   dopytu, je to čistá kontinuácia už zobrazeného stavu (Section 35/36
   zadania). Toto správanie existovalo pred V2.13b nezmenené; V2.13b ho
   len formálne pomenúva.
2. **ALLERGEN_SAFETY** má prednosť pred ČÍMKOĽVEK iným (Invariant #3) —
   overené priamym testom, že safety vyhráva aj keď `related_subject`
   ZÁROVEŇ zhoduje (`TestSafetyPrecedence::test_safety_outranks_related_products_conflict`).
3. **RELATED_PRODUCTS** vyžaduje OBOJE — explicitnú akciu ("súvisiace",
   "hodí sa", "pasuje", ...) A anchor. Samotný anchor (napr. bare "sushi
   ryža") NIKDY nestačí (Section 74/77 — kontrolné testy).
4. Všetko ostatné zostáva v `LegacyWorkflowAdapter` — nezmenené,
   nedotknuté V2.13b.

## Čo TIETO DVE tabuľky (`RoutingSignals`/`select_workflow()` z V2.7 vs.
## `TurnAnalysis`/`resolve_workflow()` z V2.13b) NIE SÚ

`app.workflow_registry.select_workflow()` (V2.7) **zostáva aktívny** —
NIE je nahradený, pretože pokrýva úplne iný, širší priestor (11
`WorkflowContract` typov vrátane `PRODUCT_LOOKUP`/`CATEGORY_BROWSE`/
`ATTRIBUTE_SEARCH`/`RECIPE_SHOPPING`/`FAQ_INFORMATIONAL`/`COMPARISON`/
`REPLACEMENT`/...), zatiaľ čo nový `app.workflow_resolver.resolve_workflow()`
pokrýva PRESNE 2 natívne, kauzálne workflows (+ 1 už-existujúcu
kontinuáciu). Toto NIE JE "dvoch konkurenčných resolverov" situácia
(Section 136 zákaz) — pracujú na RÔZNYCH vrstvách:

- `resolve_workflow()` (nový) beží PRVÝ, vnútri `_chat_impl()`, a jeho
  rozhodnutie KAUZÁLNE riadi vykonanie pre presne 2 prípady.
- `select_workflow()` (V2.7, nezmenený) beží AŽ NESKÔR, len pre tie
  prípady, ktoré padli do `LegacyWorkflowAdapter` — je to čisto
  observability label pre TÚTO zostávajúcu kaskádu, presne ako predtým.

Keď `resolve_workflow()` vráti `ALLERGEN_SAFETY`/`RELATED_PRODUCTS`,
`_chat_impl()` sa vráti VČAS a `select_workflow()` sa pre tento turn
vôbec nevolá — žiadne dvojité smerovanie (Section 84).

## Konfliktová matica (Section 71-77, overené testom)

| Kombinácia | Rozhodnutie | Test |
|---|---|---|
| RELATED_PRODUCTS akcia + PRODUCT_ENTITY (sushi ryža anchor) | `RELATED_PRODUCTS` | `test_workflow_resolver.py::TestRelatedProductsPrecedence` |
| SAFETY + PRODUCT_ENTITY (sójová omáčka anchor) | `ALLERGEN_SAFETY` | `test_workflow_resolver.py::TestSafetyPrecedence` |
| Bare product entity, žiadna explicitná akcia | `LEGACY_FALLBACK` (ostáva product_search) | `test_routing_regressions.py::TestProductSearchControls` |
| Bare alergén slovo v názve produktu, žiadny "bez X" | `LEGACY_FALLBACK` (ostáva product_search) | `test_routing_regressions.py::test_plain_soy_sauce_remains_product_search_not_safety` |
| RELATED_PRODUCTS akcia na inom anchore ako sushi (curry pasta, gochujang) | `RELATED_PRODUCTS` | `test_routing_regressions.py::TestRelatedProductsGenericAcrossAnchors` |
