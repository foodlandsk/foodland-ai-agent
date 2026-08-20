# Controlled Auto-Learning & Self-Improvement Engine — Sprint V2.12

Dátum: 2026-08-18.

## Centrálny invariant (Section 141-146 zadania)

> Správanie SMIE naučiť Mei: "ktorý z týchto validných produktov
> zákazníci zvyknú preferovať?"
> Správanie NESMIE naučiť Mei: "čo tento produkt JE."

`Learn ≠ Deploy`: každý naučený kandidát musí prejsť EVIDENCE → CANDIDATE
→ V2.10 → SHADOW → APPROVAL → PRODUCTION, nikdy skratkou. `NO_CHANGE >
UNPROVEN_CHANGE`: motor smie (a v tomto behu aj skutočne) uzavrieť, že
súčasný ranking je už lepší. `NO DATA > BAD LEARNING`: nedostatočný dôkaz
= nič sa nedeje, nikdy sa nevyrobí falošný záver (Section 137).

## Architektúra (7 nových modulov, 0 nových ranking systémov)

```
events.jsonl (existujúci V2.x telemetria stream)
      |
app/learning_events.py       - validácia, normalizácia, dedup
      |
app/learning_signals.py      - QueryProductSignal/QueryFamilySignal/
      |                         ReformulationSignal/AutocompleteSignal
      |                         (position-bias, Bayesian smoothing,
      |                         confidence tiers, bot/anomaly cap)
      |
app/learning_opportunities.py - detektory (LearningOpportunity, nikdy
      |                          produkčná mutácia)
      |
app/learning_candidates.py    - LOW-RISK opportunity -> RankingProfile
      |                          kandidát cez app.ranking_optimizer.
      |                          evaluate_profile() (V2.11+V2.10 reuse)
      |
app/learning_lifecycle.py     - SHADOW -> READY_FOR_APPROVAL -> ACTIVE
      |                          (ľudské schválenie POVINNÉ) -> MONITORED
      |                          -> ROLLED_BACK
      |
app/learning_cycle.py         - orchestrátor (collect->aggregate->
                                 detect->generate->shadow->report),
                                 zdieľaný medzi CLI a admin endpointmi
```

Žiadny z týchto modulov nevytvára druhý ranking systém - `app.learning_
candidates` volá priamo `app.ranking_optimizer.evaluate_profile()`
(presne ten istý kód V2.11 optimalizátora), ktorý interne beží cez
skutočný V2.10 `app.evaluation` harness. `app.learning_lifecycle.run_
shadow()` volá priamo `app.ranking_shadow.shadow_compare()`.

## 1. Audit fáza — čo už existovalo (Section 1-2 zadania)

Pred písaním kódu som preveril skutočný stav repozitára. Kľúčové
zistenie: Foodland už mal **skutočný, end-to-end zadrôtovaný** telemetria
pipeline predchádzajúci tento šprint — `app.widget.js: fireEvent()` →
`POST /events` → `EventRequest` (`app/main.py`) → `log_event()` →
`EVENTS_LOG_PATH` (JSONL). Reálny vektor typov: `impression`, `click`,
`add_to_cart`, `no_result`, `autocomplete_select`, `search_submit`,
`conversion` (definované v schéme, ale **nikdy reálne odosielané**
widgetom — mŕtve), `feedback`. `app.behavioral`/`app.fbt` už tento stream
čítali (CTR ranking, FBT páry) — V2.12 je prvý šprint, ktorý ho číta pre
čokoľvek iné.

**Zistená prevádzková medzera** (nie spôsobená týmto šprintom, dôležitá
pre interpretáciu akéhokoľvek reálneho behu): `EVENTS_LOG_PATH` defaultne
smeruje do `tempfile.gettempdir()` a Railway nemá nakonfigurovaný
perzistentný volume (`railway.json` neobsahuje `volumes` blok) — reálny
nahromadený objem produkčných udalostí sa preto pravdepodobne stráca pri
každom redeploy/reštarte, pokiaľ ops explicitne nenastaví `EVENTS_LOG_
PATH` na perzistentné úložisko. Toto je zdokumentované v `.env.example`,
nie automaticky opravené (mimo rozsahu tohto šprintu — vyžadovalo by
Railway infraštruktúrnu zmenu, nie kódovú).

## 2. LearningEvent model — čestný rozsah (Section 5-9)

`app/learning_events.py: LearningEvent` je normalizácia REÁLNEHO streamu,
nie vymyslená bohatšia schéma. Polia ako `ranking_config_version`,
`query_class`, `workflow`, `result_set_id`, `recipe_id`, `ingredient_role`
zo zadania Section 5 **nie sú** v reálnom evente — `query_class` sa preto
DOPOČÍTAVA pri čítaní cez skutočný V2.4 `app.query_constraints.parse_
structured_query()` (žiadna nová inštrumentácia potrebná), zvyšné polia
zostávajú čestne nedostupné a zdokumentované ako budúce rozšírenie
(Section 1: "do not invent data sources").

Validácia (Section 8): odmietnuté sú neznáme `event_type`, prázdny/príliš
dlhý `session_id`, neplatný `position`, `product_sku` mimo aktuálneho
katalógu (nikdy potichu neprejde ako "validný" produkt). Deduplikácia
(Section 16) cez deterministický hash z (ts, session_id, event_type,
product_sku, position, query).

## 3. Signály — position bias, cold start, popularity loop (Section 11-27/77-79)

`impression` eventy nesú `product_skus` v PRESNE tom poradí, aké
zákazník videl (widget zapisuje `data.products.map(p => p.id)`, už
`rank_candidates()`-zoradené) — index v zozname JE pozícia, žiadna nová
inštrumentácia. `position_normalized_lift` delí pozorovanú CTR produktu
katalógovo-priemernou očakávanou CTR na jeho priemernej pozícii (Section
78: "jednoduchý robustný prístup", nie kauzálny model), a je capnutý na
`[0.5, 2.0]` — rovnaký vzor ako existujúci `app.behavioral.behavioral_
multiplier()`. Nový produkt bez histórie jednoducho **nemá** signál (nie
nulové/záporné skóre) — sémantický ranking rozhoduje výhradne sám
(Section 80, overené `TestColdStart`).

**Čestná medzera**: CROSS_SELL_*/RECIPE_* signály (Section 29/32) nie sú
implementované ako samostatné agregáty — reálny event stream nemá pole
rozlišujúce "toto kliknutie bolo na cross-sell produkt" od "toto
kliknutie bolo na primárny výsledok vyhľadávania". Vymyslieť toto
rozlíšenie by porušilo Section 1. `app.cross_sell`/`app.recipe_graph`
zostávajú týmto šprintom úplne nedotknuté (overené `TestArchitectural
IsolationFromHighRiskDomains`).

## 4. Opportunity detektory (Section 33-42)

Implementované: `RANKING_POSITION_ANOMALY`, `LOW_TOP1_SELECTION`,
`HIGH_REFORMULATION_RATE`, `HIGH_ZERO_RESULT`, `TAXONOMY_GAP_CANDIDATE`
(zlúčené s `NEW_QUERY_CLUSTER` — s reálnymi dátami je to to isté
pozorovanie). Minimum support hranice (`LEARNING_MIN_SUPPORT_*` env,
default 200/100/10/5/5) nasledujú presne ten istý precedens ako `app.fbt`
(`FBT_MIN_ADD_TO_CART_EVENTS=200`/`MIN_PAIR_COUNT=3`) — bez reálnej
produkčnej prevádzky na kalibráciu, čestne zdokumentované ako
štartovacie hodnoty (Section 35).

**Detekcia nikdy nie je produkčná mutácia** — vytvára iba
`LearningOpportunity` (Section 34).

## 5. Risk classes a candidate generator (Section 37-42)

| Opportunity type | Risk | proposed_action_type |
|---|---|---|
| `RANKING_POSITION_ANOMALY` | **LOW** | `RANKING_WEIGHT_ADJUSTMENT` |
| `LOW_TOP1_SELECTION` | MEDIUM | `REVIEW_REQUIRED` |
| `HIGH_REFORMULATION_RATE` | MEDIUM | `REVIEW_REQUIRED` |
| `HIGH_ZERO_RESULT` | HIGH | `REVIEW_REQUIRED` |
| `TAXONOMY_GAP_CANDIDATE` | HIGH | `REVIEW_REQUIRED` |

Iba `RANKING_POSITION_ANOMALY` (LOW risk) sa niekedy stane skutočným,
automatizovateľne-vyhodnotiteľným `RankingProfile` kandidátom —
`base_profile.with_family_override(family, behavioral_weight=...)`,
malý ohraničený krok (`LEARNING_BEHAVIORAL_WEIGHT_STEP`, default 0.3)
smerom podľa dôkazu, vždy vo vnútri V2.11 validovaných hraníc. **Štruk­
turálny dôkaz proti "poisoning"**: `RankingWeights` nemá pole pre
konkrétny produkt — kandidát môže iba škálovať CELÚ rodinu, nikdy
zvýhodniť jeden konkrétny produkt (overené `TestCandidateNeverProposes
APerProductOverride`).

Každý LOW-risk kandidát beží cez **skutočný** `app.ranking_optimizer.
evaluate_profile()` → skutočný V2.10 harness. Rozhodnutia: `REJECTED`
(dve nezávislé siete: bounds validácia PRED behom, kvalitná brána PO
behu), `REVIEW_REQUIRED` (MEDIUM/HIGH risk, nikdy nespustí harness),
`SHADOW_ELIGIBLE` (prešiel bránou A preukázal skutočné, nie iba
neutrálne, zlepšenie — `MIN_IMPROVEMENT_MARGIN`, Section 48).

## 6. Shadow → schválenie → aktivácia → rollback (Section 50-64)

`app.learning_lifecycle.run_shadow()` volá priamo `app.ranking_shadow.
shadow_compare()` — nikdy sa nedotkne `config/ranking_profiles/
active.json`, teda nikdy neexponuje kandidáta reálnemu zákazníkovi
(overené `TestShadowDoesNotAffectCustomerOutput`).

**`approve_and_activate()` bezpodmienečne vyžaduje reálneho, menovaného
schvaľovateľa** — `approved_by=""/"auto"/"system"/"automated"/"bot"/
"cron"` je vždy odmietnuté, bez ohľadu na `LEARNING_AUTO_PROMOTION_
ENABLED` (ktorý navyše defaultne `false`, Section 55/56). Toto nie je
mäkké odporúčanie — je to jediná funkcia v celom kóde, ktorá vôbec smie
zapísať do `active.json`, a jej prvý riadok logiky to vynucuje
(overené `TestApprovalGate`).

Rollback (`rollback_to_last_known_good()`) je deterministický — vždy
konfigurácia aktívna BEZPROSTREDNE pred poslednou aktiváciou, zaznamenaná
DO `last_known_good.json` PRED prepnutím, nikdy heuristický odhad.
`check_rollback_conditions()` reuse-uje presne tú istú V2.10 `evaluate_
quality_gates()` bránu — tá nikdy neblokuje na CTR/business metrikách
(Section 61), takže automatický rollback sa NIKDY nespustí kvôli šumu.

Audit trail: `config/learning_history/ledger.jsonl` — append-only, žiadny
riadok sa nikdy needituje ani nemaže (Section 63/64/105).

## 7. Orchestrátor, harmonogram, feature flags (Section 70-104)

`app/learning_cycle.py: run_learning_cycle()` je jediný orchestrátor —
CLI (`scripts/run_learning_cycle.py`) aj admin endpointy ho volajú
rovnako, žiadna duplicitná logika. Nezávislé flagy (Section 99):
`LEARNING_ENGINE_ENABLED`, `LEARNING_CANDIDATE_GENERATION_ENABLED`,
`LEARNING_SHADOW_ENABLED` (všetky default `true` — bezpečné, keďže iba
ČÍTAJÚ existujúci event stream), `LEARNING_AUTO_PROMOTION_ENABLED`
(default `false`). Vypnutie V2.12 nikdy nevypne V2.11 (overené
`TestDisablingLearningNeverDisablesRanking`).

Harmonogram: rovnaký `asyncio.create_task` + `while True: sleep; run`
vzor ako existujúci `feed_refresh_loop()` (Section 9 audit — repozitár
nemá žiadnu inú scheduler infraštruktúru, žiadny cron v GitHub Actions
ani Railway), gated `LEARNING_CYCLE_MINUTES` (default `0` = vypnuté —
Section 73/74: konzervatívna počiatočná kadencia, ops zapne až keď
reálna prevádzka odôvodní interval). Manuálny trigger: `POST /admin/
learning/run-cycle` (rovnaký `require_admin_token()` vzor ako
existujúcich 10 `/admin/*` endpointov).

Fail-safe (Section 100/101): `run_learning_cycle()` nikdy nevyhodí
výnimku von — interná chyba sa zaznamená ako `"status": "error"` v
reporte, zákaznícke vyhľadávanie beží bezo zmeny. Async princíp (Section
102): celý cyklus beží mimo request cesty (`asyncio.to_thread` v
background loope, alebo v threadpool-e pri sync admin endpointe).

## 8. Reálny výsledok — čestne (Section 137)

Tento repozitár/fixture prostredie nemá nahromadený reálny produkčný
event log (a ako zdokumentované v Section 1 vyššie, ani produkcia sama
nemusí mať perzistentný `EVENTS_LOG_PATH` nastavený). `python scripts/
run_learning_cycle.py` proti aktuálnemu stavu vracia **honest `insufficient_
data`** alebo `completed` s nulovými/minimálnymi príležitosťami — presne
očakávané, nie chyba. Infraštruktúra je kompletná a otestovaná; tvrdiť
"motor sa naučil lepší ranking" bez skutočného objemu by bolo priamo
zakázané fabrikovanie (Section 137).

## 9. Testy (Section 106-125)

- `tests/test_learning_events.py` (14) — validácia, dedup.
- `tests/test_learning_signals.py` (15) — agregácia, position bias, cold
  start, popularity loop guard, bot anomaly guard, reformulation.
- `tests/test_learning_opportunities.py` (11) — minimum support, detekcia.
- `tests/test_learning_candidates.py` (15) — reálny end-to-end beh cez
  V2.10/V2.11, risk klasifikácia, gate reason mapping, **deliberate
  poisoning test** (Section 123, mandatory) a **specific query
  protection** (Section 114) priamo nad `app.ranking.rank_candidates()`
  s maximálnou možnou `behavioral_weight` váhou, architektonická izolácia
  od cross-sell/recipe/taxonomy.
- `tests/test_learning_lifecycle.py` (15) — shadow non-leakage, approval
  gate (vrátane pokusov o `approved_by="auto"` a variantov), rollback,
  audit trail.
- `tests/test_learning_cycle.py` (11) — insufficient-data honesty,
  disabled-engine, plný cyklus, nezávislé feature flagy.
- `tests/test_main_learning_endpoints.py` (11) — admin auth gating,
  `/health` iba agregátne polia (Section 98).

Plný beh: **1024/1024** (932 pred V2.12 + 92 nových), 0 regresií.

## Súvisiace dokumenty

- `docs/ranking-engine.md`, `docs/ranking-profiles.md`, `docs/ranking-
  optimization.md` (V2.11) — všetko reuse-ované, nič neduplikované.
- `docs/evaluation-engine.md`, `docs/quality-gates.md` (V2.10) — každý
  V2.12 kandidát beží cez tento presný harness.
- `docs/search-quality-observability.md` (V2.12.4) — produkčný quality
  monitor môže vysoko-dôveryhodné anomálie (napr. `LEGACY_FALLBACK_SPIKE`)
  exportovať ako evidenciu pre `app.learning_opportunities`, ale
  ANOMÁLIA != AUTOMATICKÝ KANDIDÁT — prechádza tým istým risk lifecycle
  (`REVIEW_REQUIRED` by construction pre všetko okrem `RANKING_POSITION_
  ANOMALY`/`LOW_TOP1_SELECTION`). `AUTO_PROMOTION` zostáva `false` pre
  oba sprinty.
