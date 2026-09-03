# Continuous Customer Intelligence Diagnostic Loop (V2.18a-c)

Dátum: 2026-09-03. Baseline commit: `31c0efd64481510109e9ab86e1081bbec78ceb89`.

## 1. Účel

Systematicky meria a odhaľuje slabiny inteligencie Foodland AI Advisora
BEZ zmeny zákazníckeho správania. `THE EVALUATOR EXISTS TO FIND WHERE
THE ADVISOR IS WEAK, NOT TO PROVE THAT THE ADVISOR IS GOOD.`

## 2. Vzťah k existujúcej V2.10 infraštruktúre

**Znovupoužité, nezmenené**: `app.evaluation.runner.run_golden_case()`,
`app.evaluation.conversation.run_conversation_case()`,
`app.evaluation.adapter.make_chat_fn()`/`make_session_chat_fn()`
(default `evaluation_context()`), `app.evaluation.loader` (25
regresných + 37 golden prípadov, 4 multi-turn konverzácie).

**Zistené pri audite**: `eval/golden/regression_bugs.json` NEMÁ
štruktúrovaný `status` field — len jeden prípad (rt0013) má neformálnu
prózu "CLOSED_BY_HUMAN_SEMANTIC_DECISION" v `note`. V2.18a to formalizuje
cez ADDITÍVNY overlay súbor (`eval/golden/v2_18_lifecycle_overlay.json`)
— pôvodný `regression_bugs.json` sa NIKDY needituje.

## 3-9. Filozofia, ground-truth authority, GROUND_TRUTH_PENDING

`Scenario.__post_init__()` (app/intelligence_diagnostics/scenario_schema.py)
je tvrdý enforcement bod: `CURRENT_MODEL_OUTPUT` NIE JE členom
`GROUND_TRUTH_AUTHORITIES` — pokus o jeho použitie vyhodí `ValueError`
pri konštrukcii, PRED akýmkoľvek skórovaním. Overené testom
`test_current_model_output_cannot_be_ground_truth_authority`.

`app.intelligence_diagnostics.real_customer_qa_bridge.finding_to_scenario_candidate()`
NIKDY nekopíruje historickú AI odpoveď ako očakávanú pravdu — buď
priradí úzko vymedzený V2.17.3 kontrakt (`VERIFIED_REPRODUCTION_CONTRACT`),
alebo `GROUND_TRUTH_PENDING`. Živo overené: **0 reálnych zákazníckych
konverzácií** doteraz prebehlo (V2.17.1/2/3 živé overenia), takže
`eval/golden/v2_18_curated_scenarios.json` neobsahuje ŽIADNY
`REAL_CUSTOMER_QA` záznam — fabrikovanie jedného by porušilo Section 58.

## 12-16. Scenario/persona schéma, capability taxonomy, multi-turn

`Scenario` obaľuje existujúci `GoldenCase`/`ConversationCase` (read-only
adaptácia) alebo je priamo autorovaný (CURATED/REAL_CUSTOMER_QA/
SAFE_MUTATION). Capability taxonómia znovupoužíva V2.10's
`error_buckets` vokabulár 1:1 kde existuje mapovanie (RETRIEVAL_MISS→
RETRIEVE, RANKING_ERROR→RANK, atď). `Persona` štrukturálne odmieta
citlivé demografické atribúty (`__post_init__` kontrola).

## 17-18. Sémantické kontrakty, product-order guard

`app.intelligence_diagnostics.invariant_evaluator` — malá, deterministická
vokabulár (`cross_sell_separate`, `no_stock_certainty_claim`,
`no_prompt_leak`, `intent==X`, `answer_contains:X`...), nikdy exact-prose.
Žiadny invariant nezávisí od poradia produktov — `RANK` klasifikácia sa
v žiadnom pravidle nepoužíva.

## 19-22. Safe Mutation Engine

4 implementované bezpečné typy: `TYPO`, `DIACRITICS_STRIP`,
`WORD_ORDER`, `POLITENESS_TOGGLE` — čisté, deterministické (žiadny
random/LLM). `UNSAFE_MUTATION_MARKERS` dokumentuje triedu transformácií
(negácia, zmena diétneho obmedzenia, zmena množstva), ktoré tento modul
NIKDY automaticky negeneruje — `mutate_scenario()` vyhodí `ValueError`
pre akýkoľvek neregistrovaný typ (fail-closed).

## 23-25. Real customer QA → scenario candidate

Viď bod 3-9 vyššie. Bridge mechanizmus je plne otestovaný (13 testov),
ale zámerne nemá žiadny reálny záznam v commitnutom curated súbore.

## 26-27. Scorecard, score comparability

`overall_score`, `stable_core_score` (len kanonické scenáre, bez
mutácií), `mutation_score` (len mutácie) — počítané samostatne
(`scripts/run_intelligence_benchmark.py`). `UNKNOWN`/`PENDING_GROUND_TRUTH`
nikdy nevstupujú do menovateľa skóre (`BenchmarkRun.scored_results()`).

## 28-34. Failure triage, root cause, clustering, reprodukcia

`classify_likely_layer()` vracia `ROOT_CAUSE_UNCERTAIN` keď error_buckets
mapujú na VIAC než jednu vrstvu alebo sú prázdne — nikdy nevynucuje
jednoznačnú klasifikáciu z nejednoznačného dôkazu. `cluster_failures()`
je čistý deterministický groupby `(capability, likely_layer)`, zoradený
podľa veľkosti — žiadny opaque ML clustering.

`app.intelligence_diagnostics.synthetic_reproduction.reproduce_synthetic_failure()`
znovu spustí scenár cez ČERSTVÉ EVALUATION-context volanie a znovu
overí ROVNAKÝ kontrakt. `automatic_fix`/`automatic_deploy` sú natvrdo
`False` v každom výsledku — nikde v module neexistuje fix/deploy akcia.
`recommended_next_action` znovupoužíva presne tú istú obmedzenú
vokabulár, akú už `app.customer_qa_reproduction.NEXT_ACTIONS` ustanovil.

## Živý beh benchmarku (2026-09-03, commit 31c0efd)

- 66 kanonických scenárov (37 EXISTING_GOLDEN + 25 REGRESSION_BUG + 4 CURATED)
- 244 bezpečných mutácií vygenerovaných pre všetky scored, single-turn scenáre
- **overall_score = 0.861, stable_core_score = 0.939, mutation_score = 0.840**
- PASS=267, FAIL=43, UNKNOWN=0, PENDING=0
- 4 failure clustre (najväčší: 31 prípadov, RETRIEVE kapabilita/vrstva)
- Všetkých 43 FAIL nezávisle reprodukovaných (REPRODUCED_SYNTHETIC_FAILURE)
- 3 ROOT_CAUSE_UNCERTAIN

**Významné zistenie**: `mutation_score` (0.840) je citeľne nižšie než
`stable_core_score` (0.939) — Advisor je krehkejší na povrchovú
variáciu (preklepy/diakritika/poradie slov/zdvorilosť) než čistý
kanonický golden set naznačuje. Konkrétny príklad:
`regbug_rt0010` ("sójová omáčka bez sóje") zlyháva pri
DIACRITICS_STRIP variante ("sojova omacka bez soje") — bežný spôsob,
akým slovenskí zákazníci píšu bez diakritiky.

## 35-37. Trust/safety, stock, cross-sell guardy

Trust audit čistý (0 únikov). Stock/cross-sell invarianty overené
priamo cez znovupoužité V2.17 kontrakty vo `v2_18_curated_scenarios.json`
(oba PASS živo).

## 40-42. Storage, generation immutability, versioning

`app.intelligence_diagnostics.generation_history` — append-only JSONL
cez `storage_paths.resolve_path()`. `invalidate_generation()` nikdy
neprepisuje pôvodný záznam — pridáva NOVÝ záznam s odkazom naň (overené
testom `test_historical_generation_not_silently_rewritten`).

## Byte-safety

**Nula zmien v `app/main.py` alebo `app/widget.js`** — každá zmena
tejto sprinty je nový, aditívny súbor. Toto je najsilnejší možný dôkaz
behavior-neutrality: neexistuje diff v žiadnom zákaznícky-relevantnom
súbore, ktorý by bolo treba auditovať.

## Testy

`tests/test_intelligence_diagnostics_v2_18.py` — 76 testov pokrývajúcich
všetkých 75 požadovaných prípadov (V2.18a: 1-25, V2.18b: 26-50, V2.18c: 51-75).

## Známe obmedzenia

- `RETRIEVE`/`GROUND` sú jediné vrstvy s reálnymi zlyhaniami v tomto
  behu — `UNDERSTAND`/`RANK`/`COMPOSE`/`PRESENT` nemali žiadny FAIL
  (nie preto, že by tam neboli slabiny, ale preto, že benchmark ich
  zatiaľ nedostatočne pokrýva — poctivo priznané, nie skryté).
- Mutation engine má len 4 typy; word-order swap je naivný (prehodí len
  prvé dve slová) — dostatočný na preukázanie konceptu, nie vyčerpávajúci.
- Žiadny REAL_CUSTOMER_QA scenár zatiaľ neexistuje (0 reálnej
  prevádzky) — bridge mechanizmus pripravený a otestovaný, čaká na
  prvé reálne dáta.

## V2.18d.1 hranica (budúca, NEIMPLEMENTOVANÁ)

Táto sprinta sa zastavuje presne pri dôkaze. Budúci mandát by mohol
vybrať JEDEN reprodukovaný nález (napr. diacritics-strip fragilitu
regbug_rt0010) pre minimálnu opravu — vyžaduje samostatný, explicitný
ľudský mandát a NEZAHŔŇA Railway nasadenie bez ďalšieho schválenia.
