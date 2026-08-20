# Routing Precedence Before V2.13b (baseline map)

Dátum: 2026-08-20. Zmapované PRED akoukoľvek zmenou (Section 26: "map the
existing branch precedence... before implementing resolver"). Commit
`4812c91` (V2.13a HEAD). Presné čísla riadkov v `app/main.py::_chat_impl()`.

## Presné poradie vetiev (kaskáda, prvý match vyhráva)

| # | Riadok | Signál | Ako sa počíta | Známy defekt |
|---|---|---|---|---|
| 0 | 4160 | `active_result_set_id` + Show More/Show All | `memory.get("active_result_set_id")` + `is_show_all_query`/`is_show_more_query` | žiadny — už dnes kauzálne, čistá kontinuácia ResultSet |
| 1 | 4213 | `is_missing_composition_complaint()` | regex na sťažnosť "chýba zloženie" | žiadny |
| 2 | 4227 | `allergen_term and (allergen_product_query(...) or not detect_related_subject(...))` | `detect_allergen_intent()` + 2 pomocné funkcie | **rt0010** — `allergen_product_query()` vracia `""` ako ZÁMERNÝ "0 produktov, safety-only" signál (napr. pre `"bez soj"`/`"bez soja"`), ale guard ho traktuje ako "nerozpoznané", takže `not detect_related_subject(...)` musí byť aj True, inak safety vetva vôbec nevystrelí |
| 3 | 4248 | `is_faq_query` + `faq_answer` | `is_faq_intent()` + `best_direct_faq_answer()`/`best_faq_answer()` | žiadny |
| 4 | 4264 | `is_random_recipe_query` | `is_random_recipe_intent()` | žiadny |
| 5 | 4284 | `_detect_reset_request()` | explicitný reset marker | žiadny |
| 6 | ~4300-4380 | recipe follow-up (aktívny recept, ordinal, atď.) | `_active_recipe_id_before`, `recipe_subject` | žiadny zaznamenaný |
| 7 | ~4390 | orphaned follow-up / clarification | `_orphaned_followup` | žiadny zaznamenaný |
| 8 | 4400+ | `recipe_subject` (nová recept otázka) | `detect_recipe_subject()` | žiadny |
| 9 | recipe_followup_result | recept multi-turn nadväznosť | `app.recipe_shopping` | žiadny |
| 10 | `detect_out_of_domain()` | markerová zhoda | žiadny |
| 11 | `is_category_discovery_query()` | presná fráza zhoda | žiadny |
| 12 | 4563-4744 | **special_subject / related_subject kaskáda** (pozri nižšie) | viaceré detektory | **rt0004** |
| 13 (fallback) | 4746+ | `hybrid_cached_search_products()` / štruktúrovaný retrieval | V2.4 pipeline | žiadny |

## Detail: special_subject / related_subject kaskáda (rt0004 presný root cause)

```python
# main.py:4563-4568
already_have_subject = detect_already_have_subject(contextual_message)
special_subject = detect_special_product_subject(contextual_message)
replacement_subject = detect_replacement_subject(contextual_message)
related_subject = detect_related_subject(contextual_message)
if special_subject:
    related_subject = None          # <-- TOTO nuluje related_subject BEZČIA OHĽADU na jazyk
```

**Presne overené** priamym volaním pre `"súvisiace produkty k sushi ryži"`:

| Funkcia | Výsledok |
|---|---|
| `detect_special_product_subject(q)` | `"sushi_rice"` (hrubý substring match na "sushi ryž*") |
| `detect_related_subject(q)` | `"sushi"` (jemnejší, sémantickejší detektor) |
| `_has_recipe_shopping_language(q)` | `True` (**"suvisiace" JE v `RECIPE_SHOPPING_LANGUAGE_MARKERS`**) |
| `_query_resolves_to_confident_product_family(q)` | `True` |

**Dôležitá korekcia oproti V2.13a hypotéze**: pôvodne som predpokladal, že chýba marker `"suvisiace"` v `RECIPE_SHOPPING_LANGUAGE_MARKERS`. **To je nesprávne** — marker TAM JE (pridaný pri V2.12.2's `regbug_rt0005` regresnej oprave) a guard na riadku 4590 (`if related_subject and not _has_recipe_shopping_language(...) and ...`) **správne NEnuluje** `related_subject`. Problém je O RIADOK SKÔR: `special_subject = "sushi_rice"` sa nastaví PRVÝ (hrubší, staršou substring-based detekciou), a `if special_subject: related_subject = None` (riadok 4567) nuluje `related_subject` **bezpodmienečne**, ešte predtým, než sa jemnejší guard na riadku 4590 vôbec dostane ku slovu. Potom `special_subject in {"plain_rice", "sushi_rice", "rice_vinegar", "rice_cooker"}` (V2.12.2's migrácia) postaví štruktúrovaný výsledok PRE PLAIN SUSHI RICE, presne akoby to bol obyčajný produktový dopyt.

**Klasifikácia**: `special_subject`-detektor je HRUBŠÍ a má VYŠŠIU precedenciu ako `related_subject`-detektor, a nikdy nekonzultuje, či správa obsahuje explicitný companion/action jazyk — presne to, čo Invariant #1 zo zadania V2.13b opisuje ako "product recognition (special_subject='sushi_rice') automaticky = PRODUCT_SEARCH, namiesto ACTION('súvisiace') + TARGET('sushi rice')".

## Audit `app/workflow_registry.py` / `app/workflows.py`

| Konštrukt | Klasifikácia |
|---|---|
| `app.workflow_registry.WORKFLOWS` (11 `WorkflowContract` záznamov) | **USEFUL** — stabilný slovník workflow_id + migration_status, hodnotný ako canonical vocabulary zdroj pre V2.13b |
| `app.workflow_registry.select_workflow()` | **DECORATIVE/DUPLICATE** dnes — číta už-vypočítané signály a vracia LABEL, nikdy neriadi vykonanie (potvrdené `docs/v2.13a-current-execution-map.md`). V2.13b ho nahrádza skutočným `WorkflowResolver`-om |
| `app.workflow_registry.RoutingSignals` | **USEFUL** ako predloha (rovnaké polia, aké potrebuje `TurnAnalysis`, len bez akčno/cieľového rozlíšenia) |
| `app.workflows.WORKFLOW_CONTRACTS`, `detect_workflow()`, `WORKFLOW_PRIORITY`, `get_contract()` | **DEAD** — potvrdené `grep`-om, nikde sa nevolajú okrem `products_to_cart_candidates()` (čistá utilita, zostáva) |
| `app.workflows.WorkflowResult`, `build_grounded_ids()` | **DEAD** rovnako — nepoužívané |

## Rozhodnutie pre V2.13b

Vzhľadom na rozsah (13 vetiev, ~1000 riadkov, hlboko previazané so session/personalizáciou), V2.13b **nerefaktoruje celú kaskádu**. Namiesto toho (Section 61/62 zadania to explicitne povoľuje):

- `TurnResolver`/`WorkflowResolver` sa zavolajú RAZ, hneď po tom, čo existujúce detektory (`allergen_term`, `special_subject`, `related_subject`, ...) sú vypočítané — nie duplicitne.
- Pre **presne 2 mandátne prípady** (ALLERGEN_SAFETY, RELATED_PRODUCTS) `WorkflowResolution` **kauzálne** riadi, ktorá vetva sa spustí — nahrádza ad-hoc boolean podmienky na riadkoch 4227 a 4567 volaním resolvera.
- Všetkých ostatných ~11 vetiev zostáva **nezmenených**, teraz explicitne pomenovaných `LegacyWorkflowAdapter` (Section 62 — nie skryté, dokumentované).
- `RESULTSET_CONTINUATION` (Show More, riadok 4160) je už dnes kauzálna — V2.13b ju len formálne pomenúva cez `WorkflowResolution`, bez zmeny logiky.
