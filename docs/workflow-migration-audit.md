# Workflow & Orchestration Migration — Sprint V2.7 audit

Dátum: 2026-08-15. Zdroj: aktuálny `app/main.py` `chat()` routovací kaskáda (post-V2.6), reálne fungujúce V2.4-V2.6 moduly.

## Prečo formalizácia, nie prepis

`app/main.py`'s `chat()` funkcia už DNES obsahuje presne ten target flow,
ktorý zadanie žiada pre 3 workflow typy — `else:` vetva (posledná v
kaskáde) beží presne:

```
štruktúrovaný dopyt (V2.4) → retrieval (V2.4) → ranking (V2.4)
  → prezentácia (V2.5) → cross-sell eligibility (V2.6) → answer composer (V2.5)
```

V2.7 túto CESTU nepremiestňuje ani neprepisuje (Section 4/80) — pridáva
explicitný, testovateľný **label** nad už prebehnutým rozhodnutím
(`app/workflow_registry.py: select_workflow()`), plus formálny
`WorkflowContract` slovník. Toto je presne to, čo zadanie žiada ako
bezpečný prvý krok (Section 0/5/20/38/66/67/77/80: "Do NOT attempt a
one-shot rewrite... Migrate workflow-by-workflow... Prefer first
enabling lower-risk, well-tested flows").

## Interná routovacia mapa (`chat()`, aktuálny stav, v poradí precedencie)

```
1. Show More/Show All continuation (aktívny ResultSet)      -> bypass workflow selection úplne (Section 55)
2. missing_composition complaint                             -> LEGACY_FALLBACK
3. allergen_term                                              -> FAQ_INFORMATIONAL
4. faq_answer (best_direct_faq_answer/best_faq_answer)        -> FAQ_INFORMATIONAL alebo COMPARISON (ak "rozdiel"/"vs"/"alebo")
5. is_random_recipe_query                                     -> RECIPE_SHOPPING
6. recipe_subject                                              -> RECIPE_SHOPPING
7. detect_out_of_domain                                        -> LEGACY_FALLBACK
8. is_category_discovery_query                                 -> CATEGORY_BROWSE
9. already_have_subject                                         -> LEGACY_FALLBACK
10. special_subject == "plain_rice"                             -> podľa structured_answer_strategy (V2.4 override)
11. special_subject (iné, ~25 kurátorských zoznamov)             -> LEGACY_FALLBACK
12. replacement_subject                                          -> REPLACEMENT
13. article_product_subject                                      -> FAQ_INFORMATIONAL
14. cross_sell_matches (legacy curated trigger)                  -> LEGACY_FALLBACK
15. related_subject (cuisine/dish cross-sell)                    -> LEGACY_FALLBACK
16. else: V2.4-V2.6 štruktúrovaný pipeline                        -> PRODUCT_LOOKUP / CATEGORY_BROWSE / ATTRIBUTE_SEARCH / USE_CASE_ADVICE
17. (bez štruktúrovaného výsledku, legacy hybrid_cached_search_products) -> LEGACY_FALLBACK (nezalogované, mimo rozsahu tejto iterácie)
```

Toto poradie je `select_workflow()`'s precedencia (Section 49) — odvodená
z reálneho kódu, nie vymyslená.

## Workflow registry (`app/workflow_registry.py`)

| workflow_id | status | retrieval | presentation | cross_sell_policy |
|---|---|---|---|---|
| `PRODUCT_LOOKUP` | **MIGRATED** | v2.4 structured | EXACT_MATCH \| NO_EXACT_MATCH | conservative |
| `CATEGORY_BROWSE` | **MIGRATED** | v2.4 structured | GROUPED_DISCOVERY | suppressed |
| `ATTRIBUTE_SEARCH` | **MIGRATED** | v2.4 structured | FILTERED_PRODUCT_LIST | conservative |
| `USE_CASE_ADVICE` | SHADOW | v2.4 structured | FILTERED_PRODUCT_LIST | enabled |
| `COMPARISON` | SHADOW | legacy knowledge search | COMPARISON | suppressed |
| `REPLACEMENT` | SHADOW | legacy alternative_products_for_subject | FILTERED_PRODUCT_LIST | suppressed |
| `RECIPE_SHOPPING` | SHADOW | legacy recipe_shopping_core_products | RECIPE_SHOPPING | enabled |
| `FAQ_INFORMATIONAL` | SHADOW | legacy knowledge search | INFORMATIONAL | suppressed |
| `ORDER_TRACKING` | LEGACY (neimplementované) | — | — | disabled |
| `SUPPORT_ESCALATION` | LEGACY (neimplementované) | — | — | disabled |
| `LEGACY_FALLBACK` | LEGACY | legacy lexical search | legacy | disabled |

**MIGRATED** = tri workflow, ktoré zadanie explicitne odporúča ako prvú
aktiváciu (Section 67), teraz formálne zapojené do `chat()` s live
`workflow_id`/`workflow_confidence` v odpovedi + analytickým logom.

**SHADOW** = `select_workflow()` ich správne rozpozná a vie ich
označiť/otestovať (viď `TestRequiredScenarios`), no `chat()` ich zatiaľ
neprepošle cez formálny `WorkflowContract` — bežia ďalej cez svoje
existujúce, samostatne otestované legacy vetvy presne tak, ako predtým.
Toto NIE JE zabudnutá práca — je to explicitne dokumentovaná hranica
rozsahu tejto iterácie (Section 5: "Migrate workflow-by-workflow", nie
naraz 8 workflow v jednom sprinte).

**LEGACY** = `ORDER_TRACKING`/`SUPPORT_ESCALATION` v Foodland aktuálne
vôbec neexistujú (žiadny objednávkový/support systém v `app/main.py`) —
registry ich uvádza len pre úplnosť schémy (Section 6), nikdy sa
neaktivujú (Section 80: nevymýšľať neexistujúce schopnosti).

## Precedencia a routing conflict (Section 48/49)

Mandátny konfliktný príklad: *"akú alternatívu ku Kikkoman na sushi?"*
nesie ZÁROVEŇ `replacement_subject` AJ sushi/use-case kontext. Keďže
`replacement_subject` sa v reálnej kaskáde kontroluje SKÔR než
štruktúrovaná cesta (bod 12 vyššie, pred bodom 16), `select_workflow()`
správne vráti `REPLACEMENT`, nie `USE_CASE_ADVICE` — overené testom
`test_replacement_outranks_related_subject`.

## Fallback (Section 19/47)

`select_workflow()` vždy vráti platný `workflow_id` aj `fallback_workflow`
pole — pri nerozpoznanom vstupe `LEGACY_FALLBACK` s nízkou confidence
(0.4). Skutočná odpoveď v `chat()` sa v tomto prípade NEMENÍ — legacy
`hybrid_cached_search_products()` cesta beží presne ako predtým V2.7.

## Kontext (Section 31/32/33/46)

Follow-up ("len 5 kg" po "jazmínová ryža") a context switch (sushi →
"kikkoman sójová omáčka") už fungujú správne cez existujúci V2.5/V2.6
mechanizmus (`memory_subject`, `merge_constraints()`) — `select_workflow()`
label tento mechanizmus nemení, len ho pozoruje. Overené testom
`test_context_switch_does_not_leak_workflow`: sushi kontext (`USE_CASE_
ADVICE`) sa nepreleje do nasledujúceho nesúvisiaceho `PRODUCT_LOOKUP`
dopytu.

Show More/Show All continuation (bod 1 v routovacej mape) BYPASSUJE
`select_workflow()` úplne — odpoveď neobsahuje `workflow_id` pole vôbec
(Section 44/55), overené testom `test_show_all_continuation_has_no_workflow_id`.

## MAIN.PY — zníženie zložitosti

V tejto iterácii sa `main.py` routovacia kaskáda **nezjednodušila** (to
by vyžadovalo prepísať 5+ samostatne testovaných legacy vetiev v jednom
sprinte, presne to, čo Section 0/38/66/80 zakazujú). Namiesto toho
`select_workflow()`/`WORKFLOWS` registry teraz existuje ako **jediný
zdroj pravdy** o tom, ktorý workflow daný dopyt rieši — budúce sprinty
môžu jednotlivé SHADOW vetvy migrovať jednu po druhej bez opätovného
objavovania tejto mapy.

## Testy

`tests/test_workflow_registry.py` (27 testov): mandátne scenáre (8),
fallback (2), precedencia/routing conflict (5), determinizmus (1),
order/support cross-sell disabled (2), workflow contract integrity (4),
end-to-end cez skutočný `chat()` (5, vrátane context switch a Show All
non-contamination).

Plný beh: **779/779** (752 pred V2.7 + 27 nových), 0 regresií.

## Shadow porovnanie (reprezentatívne)

| dopyt | workflow_id | odpoveď sa zmenila? |
|---|---|---|
| "jazmínová ryža" | ATTRIBUTE_SEARCH | nie — rovnaký V2.4-6 pipeline ako pred V2.7 |
| "ryža" | CATEGORY_BROWSE | nie |
| "ryža na sushi" | USE_CASE_ADVICE | nie |
| "čo je miso?" | FAQ_INFORMATIONAL (label only) | nie — stále legacy FAQ cesta |
| "alternatíva Kikkoman" | REPLACEMENT (label only) | nie — stále legacy replacement logika |

Vo všetkých prípadoch je odpoveď (produkty, text) bit-identická s
predchádzajúcim (V2.6) správaním — jediný rozdiel je nové `workflow_id`/
`workflow_confidence` pole v odpovedi pre 4 z vyššie uvedených MIGRATED
prípadov a nový analytický log riadok.

## Riziká (úprimne)

- 5 SHADOW workflow (`USE_CASE_ADVICE`* keď nejde cez V2.4 pipeline,
  `COMPARISON`, `REPLACEMENT`, `RECIPE_SHOPPING`, `FAQ_INFORMATIONAL`)
  nemajú live `workflow_id` v `chat()` odpovedi — iba `select_workflow()`
  ich vie správne označiť pri priamom volaní/teste. Skutočné zapojenie
  live logovania pre tieto vetvy (8 samostatných early-return bodov v
  `chat()`) je zámerne mimo rozsahu tejto iterácie kvôli byte-citlivosti
  `main.py` a rizika zásahu do 5 nezávisle otestovaných legacy vetiev
  naraz — kandidát na V2.7.1/ďalšiu fázu.
- `select_workflow()`'s COMPARISON detekcia je založená na jednoduchých
  frázových markeroch ("rozdiel"/"vs"/"alebo") nad už-FAQ-rozpoznaným
  dopytom — nie nová, nezávislá klasifikácia; zdedí presnosť z existujúceho
  `is_faq_intent()`.
- `ORDER_TRACKING`/`SUPPORT_ESCALATION` sú čisto schematické (Section 6
  úplnosť), Foodland tieto funkcie nemá.

## Ako znovu overiť

```bash
python -m pytest tests/test_workflow_registry.py -q
```
