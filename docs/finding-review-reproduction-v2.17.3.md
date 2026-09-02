# Finding Review & Reproduction Layer (V2.17.3)

Dátum: 2026-09-02/03. Baseline commit: `d0008697139d6805dc142ecd5b573c0e055e0829`.

## 1. Účel

Nezávisle overuje, či V2.17.2 QA nález je skutočné, na kontrakte
založené porušenie — buď z nemenného historického dôkazu (OFFLINE),
alebo čerstvým, izolovaným behom tej istej sanitizovanej otázky cez
dnešný kód/dáta (ADMIN_TEST).

## 2. Čo toto NIE JE

`FINDING → HUMAN/ADMIN REVIEW → SAFE REPRODUCTION → CONTRACT
VERIFICATION → REPRODUCTION RESULT`, nikdy `FINDING → AUTOMATIC LABEL
→ AUTOMATIC FIX → AUTOMATIC DEPLOY`. **FINDING != BUG** — permanentný
princíp. `automatic_fix`/`automatic_deploy` sú natvrdo `false` na
každom výsledku; modul nikde needituje retrieval/ranking/odporúčania/
cross-sell/substitúcie/recepty/knowledge/Merchant dáta/produktové
dáta/zákaznícku pamäť/prompty/learning/promotion.

## 3-4. Vzťah k V2.17.1/V2.17.2 a princíp "REPRODUCED vyžaduje kontrakt"

Konzumuje výhradne `app.customer_qa`/`app.customer_audit`. Nález sa
NIKDY neoznačí REPRODUCED len preto, že odpoveď "vyzerá zle", poradie
produktov sa zmenilo, alebo zákazník klikol inak — len keď konkrétny,
registrovaný kontrakt/evaluátor dokáže porušenie z reálneho dôkazu.

## 7. Audit 8 V2.17.2 pravidiel — klasifikácia reprodukovateľnosti

**Všetkých 8 pravidiel klasifikovaných ako REPRODUCIBLE** — každé
vyhodnocuje polia UŽ prítomné v nemennom sanitizovanom historickom
zázname (text odpovede, `product_groups`, `has_more`/počty); žiadne
nezávisí od živého `/chat` správania, aktuálneho stavu katalógu, ani
ničoho, čo by vyžadovalo opätovné spustenie na overenie historickej
pravdivosti.

## 11-14. Contract registry

| rule_id | contract_id |
|---|---|
| QA_STRUCT_001 | CROSS_SELL_GROUP_SEPARATION_V2_17 |
| QA_STRUCT_002 | CROSS_SELL_ELIGIBILITY_CONSISTENCY_V2_17 |
| QA_STRUCT_003 | RESULT_GROUP_CONSISTENCY |
| QA_TRUST_001 | PROMPT_LEAK_PROTECTION_V2_16E |
| QA_TRUST_002 | PII_REDACTION_V2_17_1 |
| QA_STOCK_001 | STOCK_SEMANTICS_V2_17 |
| QA_COMPOSE_001/002/003 | RESPONSE_STRUCTURE_CONSISTENCY_V2_17_2 |

Evaluátor pre každý kontrakt je DOSLOVA tá istá `app.customer_qa`
pravidlová funkcia, ktorá pôvodne vyprodukovala nález — jeden zdroj
pravdy, žiadna duplicitná logika, no stále nezávislé re-overenie (iný
vstupný bod/volanie).

## 15. Contract evaluator

Vracia `{"finding": "...", ...}` alebo `None` — strojovo overiteľné
(existencia/neexistencia nálezu), plus stručné ľudské vysvetlenie v
`reproduction_evidence`.

## 17-19. OFFLINE reprodukcia

**Predvolený, preferovaný režim** (Section 18 "offline-first"). Znovu
vyhodnotí ROVNAKÝ kontrakt proti ROVNAKÉMU nemennému historickému
ťahu. Žiadne `/chat` volanie, žiadne riziko CUSTOMER kontaminácie,
žiadne vedľajšie účinky. Deterministický zo svojej podstaty — overené
testom `test_offline_does_not_call_chat` (sleduje, že
`advisor_engine.run()` sa zavolá 0-krát).

## 20-23. ADMIN_TEST aktívna reprodukcia

Jediný režim, kde `NOT_REPRODUCED` má reálny, dôkazom podložený
význam — "porušuje TO ISTÉ dnešný kód/dáta?". Znovu spustí sanitizovanú
`question` z historického nálezu (nikdy pôvodný `session_id`) cez
`app.advisor_engine` s natvrdo vynúteným `admin_test_context()`.

**Živo empiricky overené** (nie len predpokladané — Section 9): ADMIN_TEST
prevádzka NIKDY nedosiahne `customer_audit.jsonl` (`capture_customer_turn()`
je gate-ovaná na `is_customer_traffic`, čo je `False`). DOTKNE sa
`user_memory.json` (rovnaké V2.15b-ustanovené správanie ako každé iné
ADMIN_TEST volanie), ale výhradne cez pevný, jasne syntetický
`client_key="admin-test-reproduction"` — nikdy sa nedotkne skutočného
zákazníckeho profilu (overené testom, že `session_id`/`client_key`
pôvodného zákazníka sa nikdy neobjavia v `user_memory.json`).

## 18. Prečo CUSTOMER nie je nikdy dosiahnuteľný

`reproduce_admin_test()` neprijíma `execution_context` parameter vôbec
— `admin_test_context()` je natvrdo volaný interne. `POST
/admin/qa/reproductions` prijíma LEN `{"qa_id": "..."}` — žiadne pole
pre execution_context v request schéme, takže volajúci nemá spôsob,
ako CUSTOMER požadovať.

## 22-23. READ vs OPERATIONS hranica

- `GET /admin/qa/reproductions/status`, `GET
  /admin/qa/reproductions/{qa_id}` (OFFLINE) — `SCOPE_READ`, keďže
  nikdy nespúšťajú `/chat`.
- `POST /admin/qa/reproductions` (ADMIN_TEST) — `SCOPE_OPERATIONS`
  minimum. READ token dostane `403` (overené živo aj testom).

## 24-25. Storage a deduplikácia

Žiadne — ON-READ, rovnaký precedens ako V2.17.2. Žiadny
`customer_qa_reproductions.jsonl`. `reproduction_id =
sha256(f"{qa_id}:{contract_id}:{mode}:{evaluator_version}")[:24]` —
deterministický, stabilný.

## 27. Sémantika výsledkov

`REPRODUCED, NOT_REPRODUCED, INSUFFICIENT_EVIDENCE, NOT_REPRODUCIBLE,
STALE, INVALID_FINDING, BLOCKED_BY_DATA` — všetkých 7 deklarovaných.
V tejto sprinte reálne dosiahnuteľné: `REPRODUCED`, `NOT_REPRODUCED`
(len ADMIN_TEST), `INSUFFICIENT_EVIDENCE` (qa_id nenájdený/chýbajúci
kontext), `NOT_REPRODUCIBLE` (neregistrovaný rule_id). `STALE`,
`INVALID_FINDING`, `BLOCKED_BY_DATA` sú podporované ako platné hodnoty,
ale žiadny z 8 aktuálnych kontraktov ich netriggeruje — poctivo
zdokumentované, nie vynútené (viď bod 51-53 nižšie).

## 28. Historical vs. current drift

`STALE` by sa hodilo pre prípad, keď referencovaný produkt už
neexistuje v katalógu — ale ŽIADNY z 8 kontraktov to nevyžaduje na
vyhodnotenie porušenia (napr. "Skladom" bolo povedané v čase T1 — to
je nemenný fakt bez ohľadu na to, čo sa deje s katalógom teraz).

## 33-35. Cross-sell/stock/order guardy

Všetky SPLNENÉ — evaluátory sú doslova tie isté V2.17.2 funkcie,
takže dedia rovnaké garancie. Žiadny kontrakt v registri obsahuje
"ORDER"/"RANK" v názve (overené testom).

## 36. UNDERSTAND/RETRIEVE ground-truth limitácia

Zachovaná — žiadny kontrakt pre tieto klasifikácie neexistuje (rovnaké
zdôvodnenie ako V2.17.2).

## 40-42. Testy

`tests/test_customer_qa_reproduction_v2_17_3.py` — 60 testov
pokrývajúcich všetkých 60 požadovaných prípadov.

## 47. Vedľajší efekt na existujúci V2.17.2 test

`tests/test_customer_qa_v2_17_2.py::test_qa_routes_are_get_only`
pôvodne tvrdilo "každá `/admin/qa/*` trasa je len GET" — pravdivé pre
V2.17.2 rozsah. V2.17.3 zámerne, bezpečne rozšírilo o JEDNU explicitne
autorizovanú, OPERATIONS-scoped POST trasu. Opravené na správny,
aktuálny invariant (inšpekčné trasy zostávajú GET-only; jediná execution
trasa je vyňatá a exhaustívne testovaná vlastnou V2.17.3 sadou) —
rovnaký vzor ako V2.17 rt0013 precedens, nie oslabenie bezpečnosti.

## 50-53. Výkon, nulové LLM/search volania

Nulový dopad na `/chat` (OFFLINE aj status endpoint nikdy nevolajú
`/chat`; ADMIN_TEST beží len na explicitnú admin požiadavku). Overené
testom, že zdrojový kód modulu neobsahuje `openai`/`search_products(`.

## Známe obmedzenia

- `STALE`/`INVALID_FINDING`/`BLOCKED_BY_DATA` nemajú zatiaľ trigger
  podmienku — poctivo zdokumentované, nie vynútené fabrikáciou.
- Žiadna perzistentná história reprodukcií (ON-READ).
- `INVALID_FINDING` vyžaduje ľudské rozhodnutie — tento modul ho
  nikdy automaticky nepriradí.

## Budúca hranica

Táto sprinta sa zastavuje po dôkaze. Budúca oprava/generovanie
regresných testov z REPRODUCED nálezov vyžaduje samostatný, explicitný
mandát — V2.17.3 NEVYTVÁRA žiadny automatický commit.
