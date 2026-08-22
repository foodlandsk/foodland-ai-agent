# V2.15b — Recommendation Signal Persistence, Correlation & Normalization Closure

Dátum: 2026-08-22. Baseline: `e41baf6` (V2.15a audit). Cieľ: uzavrieť
observability medzery, ktoré V2.15a našiel — NIE learning sprint, NIE
ranking sprint, NIE auto-promotion sprint. Žiadna zmena zákazníckeho
recommendation/retrieval správania. `AUTO_PROMOTION_ENABLED` nedotknuté.

## 1. Repository reality check

HEAD == origin/main == `e41baf6` pred zmenou, working tree čistý.
Baseline pred implementáciou: pytest 1599/1599, V2.10 35/39
(INTENT_ERROR=0), canary 10/10, consistency 0, trust 0 — všetko
nezávisle znovu-spustené a potvrdené zhodné s V2.15a záverom.

## 2. Re-overenie V2.15a nálezov (CONFIRMED, nie predpokladané)

| Nález | Klasifikácia |
|---|---|
| `question_analytics.jsonl`/`events.jsonl` nemajú zdieľaný kľúč | **CONFIRMED** — dôvod pre `interaction_id` (Section 4) |
| `/chat` nevie odlíšiť HTTP smoke test od zákazníka | **CONFIRMED** — uzavreté touto sprintou (Section 5) |
| `use_case_advice` nulové session prepojenie | **CONFIRMED, čiastočne zmiernené** — `decision_id` teraz existuje v odpovedi, plné session prepojenie (ako pri comparison) zostáva neuzavreté |
| `EVENTS_LOG_PATH`/`SEARCH_QUALITY_LOG_PATH` roztrieštené cesty | **CONFIRMED** — uzavreté touto sprintou (Section 6) |
| `AUTO_PROMOTION_ENABLED` štrukturálne `false` | **CONFIRMED, nezmenené** |

## 3. Architektúra pred/po

**Pred**: každý `/chat` response bol bez akéhokoľvek stabilného
korelačného identifikátora. `question_analytics.jsonl` a
`events.jsonl` sa dali spojiť len cez `session_id` + približný čas —
nespoľahlivé pri viacerých recommendation-family ťahoch v jednej
session (potvrdené V2.15a reformulačným auditom).

**Po**: `_chat_internal()` (jediný choke point, cez ktorý prechádza
KAŽDÁ odpoveď `_chat_impl()` bez ohľadu na to, ktorá interná vetva ju
vyprodukovala) generuje `interaction_id` raz za request a vkladá ho do:
odpovede (`response["interaction_id"]`), `question_analytics.jsonl`
(`log_question()`), a `SearchQualityTrace` (`search_quality.jsonl`).
Comparison/use_case_advice/basket_completion navyše generujú vlastný
`*_decision_id` pri KAŽDOM vyriešenom rozhodnutí.

## 4. Kanonická event obálka (implementované polia)

Nevytvorená nová, veľká schéma — len additívne polia na existujúcich
štruktúrach:

- `interaction_id` (str, 16 hex znakov, `secrets.token_hex(8)`) — na
  `/chat` odpovedi, `question_analytics.jsonl`, `search_quality.jsonl`.
- `comparison_decision_id` / `use_case_advice_decision_id` /
  `basket_decision_id` — na `/chat` odpovedi, len keď daná schopnosť
  skutočne rozhodla (plain product_search nikdy nemá tieto polia —
  overené testom `test_plain_product_search_has_no_decision_id`).

**Čo NIE JE implementované** (zámerne, Section 58 "Gate A" princíp —
neforsírovať downstream atribúciu): `decision_id` sa negeneruje do
samostatného durable logu s evidenciou/reason_codes. Je generovaný a
vrátený, nie ešte perzistovaný so svojím kontextom. Toto je čestne
zdokumentovaná, nie skrytá medzera — pozri Section 12.

## 5. Execution context — HTTP signalizácia (centrálna oprava)

Najzávažnejší V2.15a nález: `chat()` route nemala spôsob prijať
deklaráciu execution kontextu od HTTP volajúceho —
`isinstance(request, Request)` je vždy `True` pre reálne HTTP volanie.

**Implementácia**: `chat()` teraz prijíma voliteľné hlavičky
`X-Execution-Context` a `X-Admin-Token`. Override na `ADMIN_TEST`
nastane LEN keď:
1. `x_execution_context == "ADMIN_TEST"` (presná zhoda), A
2. `resolve_token_scope(x_admin_token)` vráti `OPERATIONS` alebo
   `PROMOTION` (READ nestačí — bypass rate limitu je reálna schopnosť,
   nie len read-only).

**Fail-closed dôkaz** (testované): chýbajúca hlavička, zlý token,
chýbajúci token, zlá hodnota hlavičky, alebo READ-scope token —
všetky ponechajú `resolved_context` úplne nezmenené (reálny zákaznícky
request nikdy tieto hlavičky neposiela, takže je byte-for-byte
nedotknutý). Autorizovaný OPERATIONS/PROMOTION token + správna
hlavička → `ADMIN_TEST` kontext → 0 zápisov do `question_analytics.jsonl`,
0 rate limit (overené testom). Nezneužíva ani neoslabuje existujúcu
admin token infraštruktúru — znovupoužíva presne ten istý
`resolve_token_scope()` mechanizmus, aký už používa každý `/admin/*`
endpoint.

**Dôsledok pre budúce live overenia**: od tohto commitu, live
production smoke testy MÔŽU byť spustené s `X-Execution-Context: ADMIN_TEST`
+ platný OPERATIONS/PROMOTION token a NEBUDÚ sa počítať ako zákaznícka
prevádzka. Live overenie tejto sprinty (Section 15) toto priamo
demonštruje.

## 6. Durable storage normalizácia

`SEARCH_QUALITY_LOG_PATH` (`app/search_quality.py`) a `EVENTS_LOG_PATH`
readery (`app/behavioral.py`, `app/fbt.py`, `app/learning_events.py`)
a `PRODUCT_EMBEDDINGS_PATH` (`app/embeddings.py`) — všetky prepojené na
`app.storage_paths.resolve_path()`, rovnaký `FOODLAND_DATA_DIR` gombík,
aký už používa `app.main`'s writer. Explicitný per-variable override
stále vyhráva (nezmenené pre produkciu, kde `EVENTS_LOG_PATH` je už
explicitne nastavený). Uzatvára riziko: budúce odstránenie tejto
redundantnej env var by predtým ticho odpojilo readery od writera bez
akejkoľvek chyby.

## 7. Idempotency/duplicity

Nebola pridaná deduplication vrstva — V2.15a/b oba explicitne povoľujú
toto vynechať, ak by to vyžadovalo neprimeranú infraštruktúru
(Section 10 zadania). `interaction_id`/`decision_id` sú generované
presne raz za logickú udalosť, čo je krok smerom k idempotency-readiness,
ale nerieši klientsky retry duplicitne zapisujúci `question_analytics.jsonl`
(zdokumentované ako pretrvávajúci, nie skrytý gap).

## 8. Signal semantics — nezmenené, overené

Žiadna zmena v tom, čo sa počíta ako pozitívny/negatívny signál.
Impression≠preferencia, klik≠nákup, reformulácia≠negatívna spätná
väzba — nedotknuté (žiadny kód v `app.learning_signals` sa nemenil).

## 9. Per-capability korelačná matica

| Capability | Stav pred | Stav po |
|---|---|---|
| comparison | decision state v odpovedi, žiadny decision_id | **CORRELATED_WITH_LIMITATIONS** — decision_id pridaný |
| use_case_advice | nulové session prepojenie | **OBSERVABLE_NOT_CORRELATED → čiastočne CORRELATED_WITH_LIMITATIONS** — decision_id pridaný, session prepojenie zostáva neuzavreté |
| basket_completion | číta, nikdy nezapisuje selection state | **CORRELATED_WITH_LIMITATIONS** — decision_id pridaný, write-side slučka zostáva neuzavretá |
| recipe_shopping | najsilnejšie in-session prepojenie | **nezmenené** (referenčná implementácia, nedotknutá) |
| cross_sell | najbohatšie per-produktové evidence tagy | **nezmenené** — klik stále nenesie cross_sell_role (vyžadovalo by frontend zásah, mimo rozsahu, Section 11 nižšie) |
| replacement_products | žiadny decision state | **nezmenené** — rt0013 uzávierka zachovaná, žiadne nové tvrdenie o vegan evidencii |
| resultset_continuation | `result_set_id` perzistuje, klik ho nenesie | **nezmenené** — vyžadovalo by frontend zásah |

## 10. Learning readiness (posúdenie, nie implementácia)

`LEARNING_READINESS_PARTIAL` — korelačný základ existuje pre 3 z 7
schopností teraz, ale ŽIADNA durable evidencia-plus-decision_id väzba
ešte neexistuje (Section 4). Toto NIE JE autorizácia začať learning
pipeline.

## 11. Frontend — zámerne nedotknuté

`app/widget.js` sa v tejto sprinte NEMENIL. Dôvod: tento repozitár nemá
žiadnu JS testovaciu infraštruktúru, a widget beží priamo na živej
zákazníckej stránke foodland.sk — akákoľvek chyba by okamžite ovplyvnila
reálnych zákazníkov bez možnosti to najprv otestovať tak dôkladne, ako
Python zmeny v tomto repozitári (plná pytest suite, CI, staging
overenie). Klasifikácia frontend event inštrumentácie:
`CAN_BE_SAFELY_INSTRUMENTED` (prepojenie `interaction_id`/`decision_id`
do `fireEvent()` volaní pri kliku/add_to_cart), ale **nie vykonané**.
Toto je konkrétny, ohraničený budúci krok — nie vágne "frontend by mal
robiť viac".

## 12. Zvyšné medzery (kategorizované, nie skryté)

- **OBSERVABILITY**: decision_id nie je durable logovaný spolu s
  evidenciou/reason_codes (Section 4) — vyžadovalo by nový log súbor +
  testy, mimo rozsahu tejto konkrétnej implementácie.
- **OBSERVABILITY**: frontend nikdy neprenáša `interaction_id`/`decision_id`
  späť do `/events` volaní (Section 11) — vyžaduje frontend zásah.
- **OBSERVABILITY**: `cross_sell`/`resultset_continuation` klik-úrovňová
  atribúcia zostáva zlomená (rovnaký dôvod).
- **ARCHITECTURAL**: idempotency/deduplication vrstva neexistuje
  (Section 7).
- **SEMANTIC-HUMAN**: rt0013 replacement quality limitation, qualitative
  "best", bare ramen — všetky nedotknuté, mimo rozsahu.

## 13. Testy

Nové súbory: `tests/test_signal_correlation_v2_15b.py` (10 testov —
interaction_id prítomnosť/distinctness/naprieč schopnosťami/durable
logy, decision_id prítomnosť/distinctness/absencia pre plain search),
`tests/test_storage_paths_v2_15b.py` (5 testov — FOODLAND_DATA_DIR
konsolidácia, explicitný override stále vyhráva, legacy tempdir default
nezmenený). Rozšírené: `tests/test_execution_context.py` +14 (5 nových
`TestExecutionContextSuppressesTaxonomyShadow` z V2.15a zostávajú
nedotknuté + 9 nových `TestChatHttpAdminTestOverride` testov pre
fail-closed HTTP signalizáciu).

## 14. AUTO_PROMOTION_STATUS: `DISABLED_AND_UNCHANGED`

Žiadny súbor v `app/learning_lifecycle.py`, `app/ranking_config.py`,
`app/ranking_optimizer.py` sa v tejto sprinte nemenil (overené `git diff
--stat`). `AUTO_PROMOTION_ENABLED` zostáva štrukturálne `false`, presne
ako V2.15a dokázal.

## 15. Regresie a nasadenie

Plný beh, V2.10, canary, consistency, trust, deployment check — pozri
finálny Slovak report pre presné čísla. Live production kontrola tejto
sprinty prvýkrát využíva vlastný nový mechanizmus (Section 5) —
overenie beží ako `ADMIN_TEST`, nie ako nerozlíšiteľná zákaznícka
prevádzka.

## 16. Odporúčaný ďalší krok

Vzhľadom na `LEARNING_READINESS_PARTIAL` a jasne ohraničený zvyšný dlh
(Section 12), odporúčaný ďalší krok je **pokračovanie V2.15b prác**
(decision_id durable logging + frontend inštrumentácia), NIE V2.15c
Learning Candidate Pipeline. V2.15c sa nezačína automaticky.
