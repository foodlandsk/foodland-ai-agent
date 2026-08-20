# Workflow Inventory — V2.13c

Dátum: 2026-08-20. Kompletný audit `app.main._chat_impl()` (`app/main.py`,
riadky 4152-5244, ~1092 riadkov) — každá vetva, ktorá môže materiálne
zmeniť vykonanie, klasifikovaná podľa taxonómie zo zadania V2.13c
(Section 7).

## Legenda klasifikácie

- `CANONICAL_WORKFLOW` — samostatná, WorkflowResolver-om rozhodnutá úloha s vlastným vykonaním.
- `WORKFLOW_PRECONDITION` — kontrola/výpočet PRED rozhodnutím, nie samotné rozhodnutie.
- `SESSION_CONTINUATION` — pokračovanie existujúceho stavu (ResultSet), nie nové rozhodnutie.
- `SAFETY_GATE` — bezpečnostná brána s najvyššou precedenciou.
- `LEGACY_ROUTING` — nezávislé rozhodnutie o type úlohy MIMO WorkflowResolver.
- `LEGACY_EXECUTION` — vykonanie SPRÁVNE rozhodnutej úlohy, ale inline v `_chat_impl()`, zdieľajúce shared-state pipeline s inými vetvami.
- `PRESENTATION_ONLY` — formátovanie/skladanie odpovede, nie rozhodnutie o úlohe.
- `TELEMETRY_ONLY` — logovanie, nemení vykonanie.
- `HTTP_BOUNDARY` — transport/API starosti (mimo `_chat_impl()`, v `chat()`/`_chat_internal()`).
- `DEAD_CODE` — nulové runtime referencie.

## Register vetiev (v poradí výskytu v `_chat_impl()`)

| # | Riadky | Vetva | Trigger | Rozhoduje resolver? | Retrieval? | Session mutation? | ResultSet? | Klasifikácia |
|---|---|---|---|---|---|---|---|---|
| 1 | 4204-4231 | Show More/Show All (`active_result_set_id`) | `is_show_more_query`/`is_show_all_query` nad `active_result_set_id` | ÁNO (V2.13b `RESULTSET_CONTINUATION`, formálne pomenované, precedencia #1) | NIE — číta uložený ResultSet | `update_session_memory` | ÁNO — pokračuje existujúci | `SESSION_CONTINUATION` → **CANONICAL_WORKFLOW (migrované V2.13c)** |
| 2 | 4258-4269 | `is_missing_composition_complaint` | presná fráza detektor | NIE (mimo WorkflowResolver) | NIE | `update_session_memory` | NIE | `LEGACY_ROUTING` (nízke riziko — jednoúčelová, žiadny konflikt s inými vetvami) |
| 3 | 4272-4307 | Allergen safety | `_resolve_safety_signal`+`_resolve_workflow` | ÁNO (V2.13b `ALLERGEN_SAFETY`, precedencia #2) | ÁNO — `allergen_product_matches()` | `update_session_memory` | NIE | `SAFETY_GATE` → **CANONICAL_WORKFLOW (migrované V2.13c)** |
| 4 | 4310-4317 | FAQ (early, pred recept/ostatné) | `is_faq_intent`+`best_direct_faq_answer` | NIE | NIE — knowledge lookup | `update_session_memory` (v return bloku) | NIE | `LEGACY_ROUTING`/`LEGACY_EXECUTION` |
| 5 | 4326-4333 | Random recipe | `is_random_recipe_intent` | NIE | NIE | ÁNO | NIE | `LEGACY_ROUTING`/`LEGACY_EXECUTION` |
| 6 | 4346-4350 | Reset request | `_detect_reset_request` | NIE | NIE | `_clear_use_case_state`/reset | NIE | `LEGACY_ROUTING` (session-state operácia, nie commerce workflow) |
| 7 | 4371-4413 | Recipe orphaned-followup edge cases | `_active_recipe_id_before`, viacero podmienok | NIE | ČIASTOČNE | ÁNO | ČIASTOČNE | `LEGACY_ROUTING`/`LEGACY_EXECUTION` |
| 8 | 4449-4543 | Recipe subject (`recipe_subject`) | `detect_recipe_subject(contextual_message)` | NIE | ÁNO — `recipe_results`/`recipe_graph` | ÁNO | NIE (recipe má vlastný shopping plán) | `LEGACY_ROUTING`/`LEGACY_EXECUTION` — **NAJVÄČŠÍ, najkomplexnejší blok** (V2.8 recipe graph integrácia) |
| 9 | 4559-4582 | Recipe followup (`_recipe_followup_result`) | `resolve_recipe_followup()` (V2.9) | NIE | ÁNO | ÁNO | NIE | `LEGACY_ROUTING`/`LEGACY_EXECUTION` |
| 10 | 4594-4599 | Out-of-domain | `detect_out_of_domain` | NIE | NIE | ÁNO | NIE | `LEGACY_ROUTING` |
| 11 | 4612-4617 | Category discovery | `is_category_discovery_query` | NIE | NIE — agreguje `product_type` | ÁNO | NIE | `LEGACY_ROUTING`/`LEGACY_EXECUTION` |
| 12 | 4589-4592 | `already_have_subject`/`special_subject`/`replacement_subject`/`related_subject` výpočet | 4 legacy detektory nad `routing_message` (V2.13b.1) | ČIASTOČNE — `related_subject`/`special_subject` konflikt rieši WorkflowResolver (`RELATED_PRODUCTS`), zvyšok nie | NIE (len signál) | NIE | NIE | `WORKFLOW_PRECONDITION` |
| 13 | 4615-4629 | `_action_target_analysis`/`_related_products_forced` | `resolve_action_target_signal`+`resolve_workflow` | ÁNO (V2.13b `RELATED_PRODUCTS`, precedencia #3) | NIE (rozhodnutie, nie vykonanie) | NIE | NIE | `WORKFLOW_PRECONDITION` (rozhodnutie) |
| 14 | 4767-4844 | Matches-dispatch `elif` reťaz (`_related_products_forced`/`already_have_subject`/bundle special_subject/`special_subject`/`replacement_subject`/`article_product_subject`/`cross_sell_matches`/`related_subject`) | rôzne legacy detektory + #13's rozhodnutie ako PRVÁ podmienka | ČIASTOČNE — len prvá podmienka (RELATED_PRODUCTS) je resolver-driven, zvyšných 7 sú legacy | ÁNO — rôzne (`complement_products_for_subject`, `special_products_for_subject`, `replacement_products_for_subject`, `article_products_for_subject`, `search_products`/hybrid) | NIE (mení len `matches`) | NIE | `LEGACY_ROUTING` (7/8 vetiev) + `LEGACY_EXECUTION` (RELATED_PRODUCTS's `matches` vetva, keďže zdieľa downstream pipeline s ostatnými 7) |
| 15 | 4874-4959 | Sushi/tom_yum/kimchi_ramen shopping bundle special-casing + `structured_presentation` výpočet | `special_subject`, `is_shopping_list_request` | NIE | ÁNO (V2.5 `build_structured_result_set`) | NIE | ÁNO (ak structured_presentation != None) | `LEGACY_EXECUTION`/`PRESENTATION_ONLY` |
| 16 | 4960-5010 | `structured_presentation` early-return | `structured_presentation is not None` | NIE (label `select_workflow()` beží tu, V2.7, observability only) | NIE (retrieval už hotové) | ÁNO | ÁNO | `PRESENTATION_ONLY` |
| 17 | 5035-5089 | No-result / fast-answer / shopping-list-answer early-returns | rôzne | NIE | NIE | ÁNO | NIE | `PRESENTATION_ONLY` |
| 18 | 5090-5240 | OpenAI odpoveď (hlavná "catch-all" cesta) | fallback pre všetko, čo sa nevrátilo skôr | NIE (`select_workflow()` label only) | NIE (retrieval už hotové vyššie) | ÁNO | ÁNO (cross-sell, ResultSet) | `PRESENTATION_ONLY` |
| 19 | 4152-4197 | Setup (session/profile load, execution_context resolve, rate limit) | — | — | — | — | — | `WORKFLOW_PRECONDITION`/`HTTP_BOUNDARY`-adjacent |
| 20 | 5245-5279 | `_chat_internal()` — SearchQualityTrace emisia, exactly-once wrapper | — | — | — | — | — | `TELEMETRY_ONLY` |
| 21 | 5280+ | `chat()` HTTP route | — | — | — | — | — | `HTTP_BOUNDARY` (V2.13a AdvisorEngine) |

## Legacy moduly

| Modul | Klasifikácia | Poznámka |
|---|---|---|
| `app.workflow_registry.select_workflow()` | `ANALYTICS_ONLY` | 11 `WorkflowContract` typov, čisto observability label pre vetvy #4-11/14-18 (LEGACY_ROUTING/EXECUTION), volaný AŽ PO tom, čo `_chat_impl()` už rozhodol nepoužiť natívny resolver. Nezmenené od V2.7. |
| `app.workflows` (`detect_workflow`, `WORKFLOW_CONTRACTS`) | `DEAD` | Nulové runtime referencie, potvrdené V2.13b auditom, nezmenené. |
| `app.turn_resolver` | `AUTHORITATIVE` | Signal extraction pre vetvy #1, #3, #13. |
| `app.workflow_resolver` | `AUTHORITATIVE` | Precedencia pre vetvy #1, #3, #13. |
| `app.workflow_executor` (NOVÝ, V2.13c) | `EXECUTION_SUPPORT` | Formálne vykonanie vetiev #1 a #3 (jediné dve, ktoré sú súčasne resolver-driven AJ plne samostatné — nezdieľajú downstream pipeline). |

## Shadow routing — nájdené inštancie

Vetvy #2, #4-11 (9 vetiev) rozhodujú NEZÁVISLE od WorkflowResolver, MIMO
jeho precedencie. Toto **NIE JE nová chyba objavená V2.13c** — je to
presne to, čo V2.13b's `docs/workflow-architecture.md` už zdokumentoval
ako `LegacyWorkflowAdapter`, explicitne sankcionované V2.13a/V2.13b
zadaniami (Section 61/62) ako prijateľný rozsah. Tieto vetvy MEDZI SEBOU
navzájom nekolidujú (každá má vlastný, disjunktný detektor a beží v
pevnom poradí `if/elif` kaskády) — nejde o AMBIGUITU (dve vetvy súperiace
o ten istý ťah), ale o SEKVENČNÚ kaskádu, kde WorkflowResolver jednoducho
nie je jediným rozhodcom pre TIETO konkrétne úlohy.

**Skutočná shadow-routing AMBIGUITA** (WorkflowResolver hovorí X, ale
`_chat_impl()` môže napriek tomu zvoliť Y) bola nájdená a opravená
presne DVAKRÁT, v predchádzajúcich sprintoch: `regbug_rt0004`/`regbug_rt0010`
(V2.13b) a `regbug_rt0011` (V2.13b.1). Po ich oprave: **0 aktívnych
ambiguít** pre vetvy #1, #3, #13, kde WorkflowResolver skutočne rozhoduje.

## Shadow execution — nájdené inštancie

Vetva #14's `_related_products_forced` časť je jediný prípad "resolver
rozhodol správne, ale vykonanie je inline a zdieľané s inou logikou" —
`matches = related_products_for_subject(...)` je prvá podmienka v
`elif` reťazi zdieľanej so 7 legacy vetvami, a VŠETKY (vrátane tejto)
following zdieľajú tú istú downstream `structured_presentation`/
odpoveď-skladaciu pipeline (~200 riadkov, vetvy #15-18). Klasifikované
ako `LEGACY_EXECUTION`, nie routing chyba — presne podľa Section 9
zadania ("A branch may correctly rely on WorkflowResolver but still
execute its workflow inline... classify this as LEGACY_EXECUTION, not
necessarily routing debt").

## Prečo NIE JE vetva #14 (RELATED_PRODUCTS) migrovaná do samostatného executora

Skutočné vykonanie "RELATED_PRODUCTS workflow" pozostáva z DVOCH fáz:
(a) výber `matches` (vetva #14, ~2 riadky, triviálne extrahovateľné) a
(b) prezentácia/skladanie odpovede (vetvy #15-18, ~250 riadkov, ZDIEĽANÉ
s 8 ďalšími legacy vetvami vrátane `already_have_subject`,
`replacement_subject`, `article_product_subject`, holého `product_search`
fallbacku). Extrahovanie LEN fázy (a) do "executora" by bola kozmetická
zmena bez skutočného architektonického prínosu (Section 35 zadania:
"main.py reduction is a consequence, not a KPI"). Extrahovanie AJ fázy
(b) by vyžadovalo buď duplikovať 250 riadkov zdieľanej prezentačnej
logiky (zakázané Section 19: "should not duplicate presentation
algorithms") alebo vykonať oveľa hlbšiu reštrukturalizáciu oddeľujúcu
"výber kandidátov" od "prezentácia" ako dva formálne stupne naprieč
VŠETKÝMI vetvami naraz — presne ten veľký, rizikový zásah, ktorý Section
36 ("NO BIG-BANG REWRITE... migrate incrementally") a Invariant #14
("delete legacy execution only after parity is proven") explicitne
žiadajú robiť POSTUPNE, nie v jednom sprinte bez rozsiahleho
charakterizačného pokrytia každej z 8 zdieľajúcich vetiev.

**Rozhodnutie**: vetvy #1 (`RESULTSET_CONTINUATION`) a #3 (`ALLERGEN_SAFETY`)
sú JEDINÉ dve, ktoré sú SÚČASNE (i) rozhodnuté WorkflowResolver-om AJ
(ii) plne samostatné (immediate `return`, nulová závislosť na zdieľanej
`matches`/`structured_presentation` pipeline) — migrované do
`app/workflow_executor.py` tento sprint. Vetva #13/#14's rozhodovacia
časť (`_related_products_forced`) zostáva presne tam, kde bola (V2.13b,
nezmenená) — je to AUTORITATÍVNE rozhodnutie, len jeho VYKONANIE
(fáza b) zostáva zdieľané. Toto je vedomé, zdokumentované
`WORKFLOW_ARCHITECTURE_PARTIALLY_CLOSED` rozhodnutie, nie prehliadnutie.
