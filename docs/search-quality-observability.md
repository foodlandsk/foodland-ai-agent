# Search Quality Observability — Sprint V2.12.4

Dátum: 2026-08-20.

## Účel

V2.12.1–V2.12.3 opravili konkrétne retrieval bugy, ale **žiadna z nich
nebola nikdy zistená automatizovaným meraním** — všetky (Bug A/B/C/D,
taxonomy medzery pri "udon"/"glass noodles"/"chilli paste") boli nájdené
manuálnym testovaním a produkčným smoke-testingom. V2.12.4 **nemení
relevanciu vyhľadávania** — robí ju **pozorovateľnou**, aby budúca
regresia (alebo architektonické rozhodnutie pre V2.13) mala skutočný
produkčný dôkaz, nie len manuálnu vzorku.

**Invariant #1 (zadanie)**: meria sa REÁLNA zákaznícka cesta. Žiaden
paralelný "quality search" engine nebol postavený.

## Architektúra

```
POST /chat (execution_context resolved)
   |
_chat_impl() — existujúca V2.3-V2.5 retrieval kaskáda, NEZMENENÁ
   |
   |-- app.structured_search._log_shadow() (existujúci log point,
   |   V2.4-éry) teraz AJ stashne rozhodnutie do ContextVar
   |   (app.search_quality.stash_retrieval_decision) — nulová I/O réžia
   v
_chat_internal() — jediný zjednotený exit point pre VŠETKY _chat_impl
   |  vetvy (Section 79/80/81)
   |-- response["answered"] = _compute_answered(response)  (existujúce,
   |   V2.12 audit fix — nezmenené)
   |-- AK execution_context.emit_customer_analytics (V2.12.1, existujúce
   |   pole, rovnaká brána ako log_question/log_event):
   |     build_trace(...) + record_search_quality_trace(...)
   v
search_quality.jsonl (FOODLAND_DATA_DIR, append-only, rovnaký vzor ako
   events.jsonl/question_analytics.jsonl)
   |
   v
app.search_quality.aggregate_traces() / detect_anomalies() / reporty
```

## Prečo žiadny nový import main.py <-> app.search.py problém

`app/search_quality.py` je plne samostatný modul (žiadny import z
`app.main`) — presne rovnaký vzor ako `app.learning_events`. Dva
integračné body:

1. `app/structured_search.py::_log_shadow()` — jediné miesto, kde sa už
   počíta `retrieval_mode`/`family`/`constraint_count`/candidate counts
   (V2.4-éry, predtým len do Python loggeru). Teraz AJ volá
   `stash_retrieval_decision()` — obyčajné priradenie do `ContextVar`,
   bez I/O.
2. `app/main.py::_chat_internal()` — číta `pop_retrieval_decision()`,
   skladá `SearchQualityTrace` a zapíše ho, LEN AK
   `execution_context.emit_customer_analytics` (V2.12.1 existujúce
   pole).

Žiadny z ~24 `cached_search_products()` call sites, žiadna z ~13
`log_question(...)` vetiev v `_chat_impl()` nebola upravená — inštrumentácia
je na JEDNOM mieste (per-request `ContextVar` reset na začiatku
`_chat_impl`, čítanie na konci `_chat_internal`).

## Quality Trace — presná schéma

`app.search_quality.SearchQualityTrace`:

| Pole | Zdroj |
|---|---|
| `session_hash` | salted sha256 (rovnaký vzor ako `log_event`'s `client_hash`) |
| `execution_mode` | `ExecutionContext.mode.value` |
| `retrieval_path` | `STRUCTURED_EXACT`/`STRUCTURED_FILTERED`/`STRUCTURED_BROAD`/`LEGACY_FALLBACK`/`NON_STRUCTURED_WORKFLOW` |
| `family` | `StructuredProductQuery.family` (z `_log_shadow`) |
| `intent` | `response["intent"]` |
| `constraint_count`/`exact_candidate_count`/`valid_candidate_count`/`nearest_candidate_count` | z `RetrievalResult` (V2.4) |
| `legacy_fallback_used`/`zero_exact_match` | z `_log_shadow` |
| `visible_product_count` | `len(response["products"])` |
| `no_result`/`answered` | `_compute_answered()` (existujúce, V2.12 fix zachovaný) |
| `latency_ms` | meraný okolo `_chat_impl()` volania |
| `deployment_version` | `RAILWAY_GIT_COMMIT_SHA` env (Railway build-time), inak `None` |
| `ranking_config_version` | `get_active_ranking_profile_version()` |
| `taxonomy_version` | `app.taxonomy.TAXONOMY_VERSION` |

**Žiadne raw query text.** `NON_STRUCTURED_WORKFLOW` je čestná kategória
pre chat vetvy (recept, replacement, cross-sell), ktoré štruktúrovaný
retrieval nikdy nevolajú vôbec — nie chyba, architektonický fakt.

## Search paths

Presne skutočné `app.retrieval` hodnoty (`STRUCTURED_EXACT`/
`STRUCTURED_FILTERED`/`STRUCTURED_BROAD`/`LEGACY_FALLBACK`) plus
`NON_STRUCTURED_WORKFLOW` — žiadna vymyslená kategória.

## Metriky (Section 11-18, 43-45)

`aggregate_traces()` počíta globálne + per-`family`/per-`intent`:
`semantic_path_rate`, `legacy_fallback_rate`, `unknown_fallback_rate`
(`family=None` + `LEGACY_FALLBACK`), `no_result_rate`,
`contradiction_filtered_rate` (`exact_candidate_count < valid_candidate_count`).
Jazyková segmentácia (Section 44) je **zámerne odložená** — repozitár
dnes nemá per-request language detektor a stavať ho len pre telemetriu
by porušilo Invariant #1.

Každý segment vyžaduje `SEARCH_QUALITY_MIN_SUPPORT_SEGMENT` (default 20)
vzoriek, inak `status=INSUFFICIENT_DATA` — nikdy fabrikovaný záver
(Section 34/73).

## Reformulation & Show More — znovupoužité, nie duplikované

`app.learning_signals.detect_reformulations()` (V2.12, existujúce) už
klasifikuje `SUCCESSFUL_REFINEMENT`/`FAILURE_REFORMULATION`/`UNCLASSIFIED`
zo skutočného `events.jsonl` stream (search_submit/click/add_to_cart).
V2.12.4 toto **znovupoužíva** namiesto duplikovania — `search_quality.jsonl`
a `events.jsonl` sú dva odlišné, komplementárne zdroje (retrieval-decision
snapshot vs. zákaznícka interakcia), korelovateľné cez `session_id`, nikdy
duplicitné (Section 28).

## Hard Semantic Canary (Section 37-40, 100-103)

`eval/search_quality_canaries.json` — 10 kurátorovaných dopytov (presne
zo Section 37), s `expected_family`/`must_not_family` overenými priamo
proti reálnemu katalógu pri autorovaní (nie odhad). `scripts/run_search_quality_canary.py`
spúšťa cez **skutočný** `_chat_internal()` v `ADMIN_TEST` kontexte —
nikdy `CUSTOMER` (overené testom
`TestCanaryExecutionContextIsolation`). Wrong-family leakage sa
kontroluje proti **skutočne vráteným produktom** (cez
`product_taxonomy_index`), nie len proti rozpoznanej rodine dopytu.

## Anomaly Detection (Section 52-54, 108-110)

`detect_anomalies(baseline, current)` — len RASTÚCE rates s dostatočnou
podporou (`SEARCH_QUALITY_MIN_SUPPORT_ANOMALY`, default 50) sa
označujú: `WARN` pri ≥30% relatívnom náraste, `CRITICAL` pri ≥75%.
Canary zlyhania (`canary_anomalies()`) sú VŽDY `CRITICAL`/`WARN` podľa
`criticality` bez ohľadu na vzorku (Section 54 — tvrdé sémantické
invarianty obchádzajú štatistický prah). Anomaly id je deterministický
(`type:scope`) — opakované reporty nikdy negenerujú duplicitné/premenované
anomálie (Section 109).

## Durabilita a promócia baseline

`save_quality_baseline()`/`load_quality_baseline()` — `FOODLAND_DATA_DIR`
cez `app.storage_paths`/`app.durable_storage` (rovnaká infraštruktúra ako
V2.12.1 ranking config). **Nikdy sa nevolá automaticky** — promócia
current stavu na nový baseline je explicitné, ľudské/kontrolované
rozhodnutie (Section 57/129), nie súčasť tohto sprintu (žiadny reálny
produkčný objem ešte nebol pozorovaný dosť dlho na to, aby bol baseline
zodpovedne nastavený — pozri finálny report).

## Privacy & Retention (Section 9/49/71)

- `search_quality.jsonl`: **žiadny raw query text**, len `session_hash`
  (nevratný bez `ANALYTICS_SALT`) + `family` (už beztak najbezpečnejšia
  kanonizácia, akú V2 telemetria používa).
- Čítanie (`load_search_quality_traces`) **defenzívne re-filtruje**
  `execution_mode == "CUSTOMER"` aj keď zápisová brána je už správna —
  druhá poistka proti internal-traffic poisoningu (Section 94).
- Retencia: `search_quality.jsonl` rastie neobmedzene bez externej log
  rotácie — **rovnaký, už existujúci, nezdokumentovaný gap** ako
  `events.jsonl`/`question_analytics.jsonl` (žiadny z nich nemá
  automatické mazanie). Odporúčanie pre prevádzku: periodická rotácia/
  archivácia na úrovni infraštruktúry (mimo rozsahu kódu tohto šprintu,
  Section 120/121 — nebolo vytvorené nekontrolované rastenie disku,
  ale ani nový problém, len existujúci nezdokumentovaný stav).

## Performance (Section 68-70, 119)

Nameraný rozdiel medzi CUSTOMER (s trace) a EVALUATION (bez trace)
volaním na 200 opakovaní: **~0.94ms/request absolútne (~12% relatívne
voči už veľmi rýchlemu ~7.6ms lokálnemu baseline bez siete/OpenAI)**.
V produkcii, kde reálna latencia je dominovaná sieťou/OpenAI volaniami
(stovky ms, pozri V2.10 eval p95≈450ms), je tento overhead zanedbateľný
v absolútnom aj relatívnom vyjadrení. Cache-hit cesta (opakovaný dopyt)
má overhead cca 0.0025ms (ContextVar read/write, žiadne I/O naviac).

## Admin endpointy (Section 62-64)

| Endpoint | Scope | Účel |
|---|---|---|
| `GET /admin/search-quality/status` | READ | agregovaný bezpečný stav |
| `GET /admin/search-quality/report` | READ | čerstvá agregácia z už zalogovaných traces (lacné, žiadne retrieval volania) |
| `GET /admin/search-quality/anomalies` | READ | len anomaly časť reportu |
| `GET /admin/search-quality/canary` | READ | posledný ULOŽENÝ canary výsledok (nespúšťa nový beh) |
| `POST /admin/search-quality/run` | OPERATIONS | spustí skutočný canary beh (ADMIN_TEST kontext) + report, uloží výsledok |

`AUTO_PROMOTION` zostáva `false` — žiadny anomaly detektor nemôže
spustiť produkčnú zmenu (Section 61/130, Invariant #11).

## Testy

`tests/test_search_quality.py` (35 testov) — pokrýva Section 79-99
mandátnu maticu: customer trace emission, internal traffic exclusion
(vrátane 30-požiadavkového poisoning testu, Section 94), legacy/semantic
path metriky, no-result sémantika (`answered`/`no_result` vždy
komplementárne), canary pass/fail (vrátane skutočného injected wrong-family
prípadu), deployment-comparison anomaly detekcia (dostatočná vs.
nedostatočná podpora), storage-failure resilience (customer chat
funguje aj keď je quality log path nezapisovateľný), ranking/deployment
version polia, family segmentácia, privacy (žiadny raw text v trace),
a admin endpoint scoping (READ vs OPERATIONS).
