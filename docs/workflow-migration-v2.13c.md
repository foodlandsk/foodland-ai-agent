# Workflow Migration Ledger — V2.13c

Dátum: 2026-08-20. Stav pre každý zo 4 kanonických `workflow_id`, ktoré
`app.workflow_resolver.resolve_workflow()` môže vrátiť (viď
`docs/workflow-inventory-v2.13c.md` pre plný audit `_chat_impl()`).

| workflow_id | Resolver owner | Staré miesto vykonania | Nové miesto vykonania | Charakterizačný test | Stav migrácie | Legacy vetva odstránená? | Overené v produkcii? |
|---|---|---|---|---|---|---|---|
| `RESULTSET_CONTINUATION` | `app.workflow_resolver` (V2.13b, nezmenené) | inline v `_chat_impl()`, riadky 4204-4231 | `app.workflow_executor.execute_resultset_continuation()` | `tests/test_workflow_executor_v2_13c.py::TestResultSetContinuationHandlerUnit`, `TestIntegrationParity::test_resultset_continuation_end_to_end`, `test_show_all_end_to_end` | **DONE** | ÁNO — kód presunutý, nie duplikovaný (inline blok teraz volá handler) | ÁNO (live smoke test) |
| `ALLERGEN_SAFETY` | `app.workflow_resolver` (V2.13b, nezmenené) | inline v `_chat_impl()`, riadky 4272-4307 | `app.workflow_executor.execute_allergen_safety()` | `tests/test_workflow_executor_v2_13c.py::TestAllergenSafetyHandlerUnit`, `TestIntegrationParity::test_allergen_safety_end_to_end`, `TestNoShadowRouterForMigratedWorkflows::test_allergen_safety_resolution_matches_execution` | **DONE** | ÁNO | ÁNO (live smoke test) |
| `RELATED_PRODUCTS` | `app.workflow_resolver` (V2.13b, nezmenené) | inline v `_chat_impl()`, riadok 4767 (`matches` dispatch) + zdieľaná prezentačná pipeline riadky ~4874-5240 | **nezmenené** — zostáva inline | `tests/test_workflow_executor_v2_13c.py::TestNoShadowRouterForMigratedWorkflows::test_related_products_resolution_matches_execution` (dokazuje resolver↔execution zhodu, nie migráciu) | **NOT_MIGRATED_THIS_SPRINT** (`LEGACY_EXECUTION`, zdokumentované) | N/A | N/A |
| `LEGACY_FALLBACK` | `app.workflow_resolver` (V2.13b, nezmenené) | celá zvyšná `_chat_impl()` kaskáda (~9 vetiev, `docs/workflow-inventory-v2.13c.md`) | **nezmenené** | existujúca rozsiahla test sada (`test_core.py`, `test_result_presentation.py`, `test_recipe_graph.py`, `test_recipe_shopping.py`, `test_cross_sell.py`, ...) | **NOT_MIGRATED_THIS_SPRINT** (`LegacyWorkflowAdapter`, zámerne zachovaná, V2.13a/b/c zhodne) | N/A | N/A |

## Prečo len 2 zo 4

Pozri `docs/workflow-inventory-v2.13c.md`, sekcia "Prečo NIE JE vetva
#14 (RELATED_PRODUCTS) migrovaná" pre plné odôvodnenie. Skrátene:
`RESULTSET_CONTINUATION` a `ALLERGEN_SAFETY` sú JEDINÉ dve, ktoré sú
SÚČASNE (i) rozhodnuté `WorkflowResolver`-om AJ (ii) plne samostatné
(okamžitý `return`, nulová závislosť na zdieľanej `matches`→
`structured_presentation`→odpoveď pipeline). `RELATED_PRODUCTS`'s
vykonanie zdieľa ~250 riadkov prezentačnej logiky s 8 ďalšími legacy
vetvami — extrakcia by buď duplikovala túto logiku (zakázané), alebo by
vyžadovala oveľa väčšiu, rizikovejšiu reštrukturalizáciu naraz (zakázané
Section 36 "no big-bang rewrite").

## Postup migrácie (dodržaný presne podľa Section 36 zadania)

1. Charakterizácia (workflow inventory) — `docs/workflow-inventory-v2.13c.md`.
2. Zavedenie executor kontraktu — `app/workflow_executor.py` (`WorkflowResult = dict[str, Any]`, rovnaké zdôvodnenie ako `AdvisorResponse`, Section 64/Invariant #13).
3. Migrácia NAJJEDNODUCHŠEJ, najizolovanejšej vetvy najprv — `ALLERGEN_SAFETY` (12 riadkov, okamžitý return).
4. Fokusované testy — `tests/test_workflow_executor_v2_13c.py`.
5. Migrácia druhej vetvy — `RESULTSET_CONTINUATION`.
6. Fokusované testy znova.
7. Odstránenie legacy vetvy AŽ PO overení parity — v tomto prípade "odstránenie" = kód bol PRESUNUTÝ (nie duplikovaný), takže k tomuto kroku došlo atomicky s migráciou (žiadna dočasná duplicitná cesta nebola potrebná, keďže obe vetvy mali jediné volacie miesto).

Žiadna "dual execution" (Section 38) nebola potrebná — obe migrácie boli
mechanické presuny (copy-then-delete-original v jednom byte-safe patchi),
overené priamym porovnaním pred/po správania cez `git stash` a live
`chat()` volania, nie súbežným behom dvoch implementácií.
