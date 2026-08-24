# V2.15e.1 — Resultset Continuation Attribution & Recommendation Causal Chain Closure

Dátum: 2026-08-24. HEAD pred sprintou: `356fd10` (V2.15e, `STRUCTURALLY_READY_EMPIRICALLY_INSUFFICIENT`).

## 1. Mandát

V2.15e (`docs/recommendation-learning-dataset-readiness-v2.15e.md`, §3)
identifikoval jednu konkrétnu medzeru v kauzálnom reťazci: "resultset
continuation (nový interaction_id, žiadny decision_id)". Táto sprinta
mala presne jednu otázku — **aký je SPRÁVNY identity/attribution model
pre "Zobraz viac"/"Zobraz všetky" pokračovanie výsledkov** — a explicitne
zakazovala vopred predpokladať, že odpoveďou je opätovné použitie toho
istého `interaction_id` (Model A). Poradie bolo: Audit → Charakterizácia
→ Rozhodnutie o identity modeli → Go/Stop gate → Minimálna oprava → JS
testy → Python testy → Plná regresia → Audity → Dokumentácia → Commit →
Push → CI → Railway → Bezpečná live verifikácia → Finálny report.

## 2. Re-verifikácia V2.15a–e (nezávisle, priamym čítaním kódu)

Všetky kľúčové invarianty potvrdené nezmenené: `interaction_id` sa
generuje nanovo pri **každom** `/chat` volaní (`secrets.token_hex(8)` v
`_chat_internal()`), `decision_id` zostáva backend-owned pre 3
capabilities (comparison/use_case_advice/basket_completion), rt0004/
rt0010/rt0011/rt0013 kontrolné testy prechádzajú, V2.14 use-case kontrolné
dopyty (sushi/pho/kari/pad_thai/tom_kha/ramen) nezmenené, V2.15c store-
location + kanonický Google Maps odkaz (`Stará Vajnorská 3308/19, 831 04
Bratislava`, `https://maps.app.goo.gl/3tFJ4P6w2pj88xAP8`) nezmenené,
V2.15d.2 authoritative-confirmation invariant nezmenený, V2.15d.3
execution-context izolácia na `/chat` aj `/events` nezmenená,
`AUTO_PROMOTION_ENABLED is False` nezmenené.

## 3. Identity inventár (pred zásahom)

| Identifikátor | Kde vzniká | Stabilita naprieč continuation |
|---|---|---|
| `interaction_id` | `secrets.token_hex(8)` v `_chat_internal()`, nanovo za KAŽDÝ `/chat` request | **NIE** (čestne nový, nie chyba) |
| `decision_id` | backend, len pre 3 capabilities (comparison/use_case_advice/basket_completion) | n/a — ordinary product_search ho nikdy nemá |
| `result_set_id` | `app.result_sets.create_result_set()`, `uuid.uuid4().hex`, mintnutý RAZ | **ÁNO** — `execute_resultset_continuation()` mutuje len `displayed_count` na TOM ISTOM uloženom objekte, nikdy ho neminta znova |
| `session_id` | klient, per-session | n/a (nadradený všetkým) |
| `client_id`/`client_hash` | salted hash | n/a |
| `product_id`/SKU | katalóg | n/a |
| `event_id` | `EventRequest.event_id`, voliteľný | n/a (duplicitná ochrana rieši `cartBtn.disabled`/`settled`/`clicked`, nie toto pole) |

**Kľúčové zistenie**: `result_set_id` **už existoval** a **už bol
identicky vracaný** v pôvodnej aj v continuation odpovedi `/chat`. Medzera
nebola chýbajúci backend koncept — bola to skutočnosť, že `app/widget.js`
ho nikdy nečítal ani neposielal ďalej.

## 4. Vyhodnotenie 5 kandidátnych modelov (A–E)

| Model | Popis | Verdikt |
|---|---|---|
| A | Rovnaký `interaction_id` naprieč continuation | **ZAMIETNUTÉ** — nový HTTP request je legitímne nová interakcia; vynútená identita by porušila princíp "nikdy nezachovávaj rozhodnutie cez sémantickú hranicu len kvôli ne-null hodnote" |
| B | Nový `interaction_id` + stabilný `root_interaction_id` | **NEPOTREBNÉ** — vyžadovalo by nový koncept, ktorý `result_set_id` už poskytuje |
| C | Nový `interaction_id` + stabilný `originating decision_id` | **NEAPLIKOVATEĽNÉ** — ordinary product_search (jediná cesta, ktorá cez `ResultSet` vôbec ide) nikdy nemá `decision_id`; fabrikovať by porušilo "decision_id musí zostať backend-owned, nikdy nevymyslený" |
| **D** | Nový `interaction_id` + stabilný `result_set_id` + originating `decision_id` (keď existuje) | **ZVOLENÉ, zjednodušené** — `result_set_id` už existuje a je už vrátený; `decision_id` legitímne zostáva null, keďže žiadny nikdy neexistoval pre tento variant D presne v tomto tvare |
| E | Iný existujúci repo-natívny mechanizmus | Preskúmané (session state, `active_result_set_id`) — toto JE mechanizmus pod Modelom D, nie samostatná alternatíva |

Výber: **Model D, zjednodušený faktom, že pre ordinary search žiadny
`decision_id` legitímne nikdy neexistuje.** `result_set_id` = stabilný
koreň. `interaction_id` = čestne nový za request. `decision_id` = null
(nikdy fabrikovaný).

## 5. Charakterizácia súčasného správania (pred opravou)

Priamym `_chat_internal()` testom cez `customer_context()`:

- Pôvodné hľadanie ("jazmínová ryža"): `result_set_id` vrátený, `has_more=True`.
- "zobraz viac" v tej istej session: `intent="product_search"`,
  `result_set_id` **identický** s pôvodným, `interaction_id`
  **odlišný** (čestne).
- Druhé pokračovanie ("zobraz všetky"): `result_set_id` stále identický
  naprieč všetkými 3 volaniami; 3 odlišné `interaction_id`.
- Nová nesúvisiaca otázka po hľadaní: nový `result_set_id` (korektná
  rotácia).
- Tvrdý prepnutie témy (search → comparison): `result_set_id` chýba
  (comparison nikdy `ResultSet` nevytvára — korektne, nič nevymyslené).
- Reset ("Začnime odznova"): nasledujúce "zobraz viac" nerezolvuje ako
  `result_set_continuation` — aktívny result set korektne vymazaný.
- Cross-session izolácia: dve session nikdy nezdieľajú `result_set_id`;
  "zobraz viac" v session bez predchádzajúceho hľadania nerezolvuje ako
  continuation.
- Frontend stash logika sa **nepreskakuje** pre continuation — beží
  identický `form.addEventListener("submit", ...)` handler ako pri
  pôvodnom hľadaní, keďže continuation odpoveď má `intent:
  "product_search"` (nie `"recipe"`, jediný vylúčený intent). Chyba
  nebola v preskočenej ceste kódu, ale v HODNOTÁCH, ktoré sa
  ukladali (chýbajúci `result_set_id`).

## 6. Historické 4 `add_to_cart_confirmed` eventy — kauzálne vyšetrenie

Priamym čítaním `GET /admin/analytics/events-detail?session_id=X&days=90`
(OPERATIONS scope) pre obe historické session_id, zoradené podľa
timestampu, s porovnaním `interaction_id` naprieč sekvenciou
impression→click→attempt→confirmed:

**Verdikt: `PROVEN_OTHER_CAUSE`** — nie `PROVEN_CONTINUATION_BREAK`.
Obe historické session nemajú v celej 90-dňovej histórii žiadny "zobraz
viac"/"zobraz všetky" event. Boli to obyčajné product_search nákupy, kde
k žiadnemu recommendation decision nikdy nedošlo — `decision_id: None`
je tu korektný a čestný stav, nie artefakt zlomenej atribúcie. Sprinta
sa vyhla pasci vytvorenia kauzálneho príbehu bez dôkazu.

## 7. Implementačná brána

**GATE B — Minimálna propagačná oprava.** Žiadny nový identifikátor
nebol potrebný. `result_set_id` už existoval, už bol backend-correct a
už bol vracaný — jediné chýbajúce bolo jeho prenesenie cez `app/widget.js`
do `fireEvent()` payloadov a `EventRequest`/`log_event()` na backende.

## 8. Implementácia

**`app/main.py`** (+13 riadkov): `EventRequest.result_set_id: str | None`
(voliteľné, `max_length=64`); `log_event()` ho persistuje do
`events.jsonl` — `None` pre každý event, ktorý nikdy `ResultSet`
nevytvoril (comparison/use_case_advice/basket_completion), a pre každé
pred-V2.15e.1 `app/widget.js` odoslanie.

**`app/widget.js`** (+30/-5 riadkov, byte-safe patch): `result_set_id`
sa ukladá na každý produktový objekt v OBOCH vetvách (`data.products`
aj `cartCandidatesToProducts()` fallback) — presne na tom istom mieste,
kde sa už ukladá `interaction_id`/`decision_id` — a je zahrnutý vo
všetkých 5 `fireEvent()` volaniach v `renderCard()` (view klik, cart
klik, `add_to_cart_attempt`, legacy `add_to_cart`, `add_to_cart_confirmed`)
plus v `impression` evente. Nikdy fabrikovaný — vždy `|| null`.

Smoke test potvrdil: `result_set_id` identický naprieč continuation,
`interaction_id` korektne odlišný, comparison/basket_completion majú
`result_set_id: None` (žiadny leak do capabilít, ktoré `ResultSet`
nikdy nevytvorili).

## 9. JS testy

`tests/js/widget.test.mjs` rozšírený o 6 nových `node:test` prípadov
(static source-inspection, keďže lokálne nie je dostupný Node.js — každý
regex bol krížovo overený Python `re` proti reálnemu `app/widget.js`
zdroju pred commitom): stash na oboch vetvách produktov, žiadna
samostatná/obchádzateľná continuation-only vetva (presne 2 stash miesta),
všetkých 5 `fireEvent()` volaní obsahuje `result_set_id`, `impression`
event ho obsahuje, a žiadne `result_set_id` priradenie nie je hardcoded
literál — všetky sú `data.result_set_id || null` alebo
`product.result_set_id || null`.

## 10. Python testy

`tests/test_resultset_continuation_attribution_v2_15e_1.py` — 24 testov:
stabilita `result_set_id` naprieč jedným aj dvomi continuation krokmi,
korektná odlišnosť `interaction_id`, nulový `result_set_id` pre
comparison/use_case_advice/basket_completion, hranice (nová otázka/tvrdý
prepnutie/reset), cross-session izolácia, `EventRequest`
spätná kompatibilita (pole voliteľné, legacy záznamy bez poľa čitateľné),
`log_event()` perzistencia, EVALUATION context stále nelogovaný,
zlyhanie zápisu eventu neprerušuje volanie, `AUTO_PROMOTION_ENABLED`
stále `False`, a plná kontrolná matica (rt0004/rt0010/rt0011/rt0013,
V2.15c store-location).

## 11. Regresné výsledky

- Plná pytest sada: **1782 passed** (1758 baseline + 24 nových), 0 failures, 1907.06s.
- V2.10 fast eval: **35/39 (89.7%)** — nezmenené oproti baseline.
- Search-quality canary: **10/10 PASS** — nezmenené.
- Trust audit: 0 nálezov (PII redaction, replacement queries).
- Consistency audit: nálezy o FAQ deklinačnej robustnosti — **PRE_EXISTING**,
  mimo rozsahu tejto sprinty (žiadna zmena sa nedotkla FAQ/deklinačnej
  logiky).

## 12. Byte-safety audit

`git diff --stat` == `git diff --ignore-space-at-eol --stat` presne pre
všetky 3 zmenené súbory (`app/main.py`, `app/widget.js`,
`tests/js/widget.test.mjs`). `git diff --check` nahlásil "trailing
whitespace" len na 5 riadkoch v CR-terminated regióne `app/widget.js` —
identický, už zdokumentovaný benígny artefakt (skutočné CR bajty v git
blobe, nie poškodenie). Learning/ranking/promotion súbory (`app/
learning_lifecycle.py`, `app/ranking_optimizer.py` a pod.) neboli touto
sprintou vôbec dotknuté.

## 13. Zamrazenia (nezmenené)

`AUTO_PROMOTION_ENABLED = False`. Žiadna zmena zákazníckeho správania
(oprava je čisto atribučná/telemetrická). Feedback→decision_id korelácia,
cross_sell/recipe_shopping/replacement_products decision-logging
rozšírenie a akýkoľvek dataset builder zostávajú explicitne mimo
rozsahu tejto sprinty.

## 14. Zostávajúci dlh

- Feedback (thumbs) eventy stále nemajú `decision_id`/`result_set_id`
  koreláciu — mimo rozsahu tejto sprinty (patrí do budúcej úzko-
  rozsahovej sprinty, ako navrhnuté v V2.15e §15).
- `cross_sell`/`recipe_shopping`/`replacement_products` stále nemajú
  žiadny decision objekt — štrukturálna medzera, nie táto sprinta.
- Empirický objem `result_set_id`-korelovaných eventov je momentálne 0
  (funkcia je nová) — štrukturálna pripravenosť ≠ empirická dostatočnosť.

## 15. Finálny stav

- `ATTRIBUTION_STRUCTURE_READY` (result_set_id koreň je teraz plne
  prenesený end-to-end: backend → frontend stash → fireEvent → /events →
  log_event → events.jsonl)
- `EMPIRICAL_DATA_STILL_INSUFFICIENT` (funkcia je nová, 0 produkčných
  pozorovaní s vyplneným `result_set_id` k dátumu nasadenia)
- `V2.15f NOT STARTED`
- `PRODUCTION_EVENTS_PURGE_INVOKED_BY_V2_15E = NO`
- `LIVE_SYNTHETIC_TEST_EVENT_CREATED`: pozri finálny report, sekcia live
  verifikácie.

## 16. Záverečný princíp

Nulový/`None` `result_set_id` alebo `decision_id` je vždy lepší ako
fabrikovaný. Nový `interaction_id` je akceptovateľný, pokiaľ kauzálny
pôvod zachováva správny samostatný mechanizmus (`result_set_id`).
Štrukturálna korektnosť predchádza empirickému objemu.
