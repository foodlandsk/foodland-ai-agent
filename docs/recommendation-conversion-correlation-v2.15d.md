# V2.15d — Durable Recommendation Decision Logging & Frontend Conversion Correlation

Dátum: 2026-08-23.

## 1. Mandát a hranica

Cieľom V2.15d je uzavrieť observabilitu medzi rozhodnutím odporúčania
(comparison/use_case_advice/basket_completion) a jeho durable záznamom.
**Nie je to learning sprint** — `AUTO_PROMOTION_ENABLED` zostáva `False`,
žiadna ranking logika, žiadny promotion mechanizmus sa nemenil.

## 2. Repository reality check

HEAD pred touto sprintou: `295f86c` (V2.15c). Žiadne necommitnuté zmeny,
žiadny nesúlad s očakávanou baseline (1644 testov, V2.10 35/39, canary
10/10, AUTO_PROMOTION=false).

## 3. Audit (4 paralelné Explore agenty)

Kľúčové zistenie: `comparison_decision_id`/`use_case_advice_decision_id`/
`basket_decision_id` už existovali (V2.15b), boli vrátené vo frontend
odpovedi, ale — podľa vlastného komentára v kóde — "generated and
returned, not yet persisted anywhere on its own". `interaction_id` bol
generovaný raz za /chat request, ale nikdy neprenesený do 3 V2.14
executorov, takže ich `log_question()` volania mali vždy prázdny
`interaction_id` v `question_analytics.jsonl`.

`app/widget.js` (2041 riadkov): žiadna JS testovacia infraštruktúra
(potvrdené — žiadny `package.json`, žiadne `*.test.js`), a **Node.js nie
je v tomto prostredí vôbec dostupný** (`node --version` zlyhá) — teda
nie je možné ani syntaxovo overiť zmenu pred nasadením.

## 4. GATE rozhodnutie: GATE A

Vzhľadom na absolútnu absenciu akéhokoľvek JS overovacieho nástroja
(nie len testov — ani syntax check) pre 2041-riadkový, zákaznícky
viditeľný, produkčný widget súbor, a vzhľadom na to, že V2.15b už raz
urobila rovnaké vedomé rozhodnutie ponechať `widget.js` nedotknutý,
**GATE A** (bezpečné durable backend decision logging) je zvolená
úroveň. Frontend product-click/add-to-cart korelácia je klasifikovaná
**`NOT_SAFE_TO_IMPLEMENT_THIS_SPRINT`** — nie navrhnutá a odmietnutá pre
zložitosť, ale odložená pre chýbajúci bezpečnostný nástroj (žiadny
spôsob overiť, že zmena nezlomí produkčný chat pre všetkých
zákazníkov).

## 5. Implementácia

- `app.main.log_recommendation_decision()` — nový, samostatný durable
  JSONL stream (`recommendation_decisions.jsonl`, cez
  `app.storage_paths.resolve_path()`, V2.15b normalizácia), korelujúci
  `interaction_id` + `decision_id` + kandidátske/odporúčané product IDs
  + `reason_codes`/`confidence` + `execution_context` +
  `learning_eligible`.
- Volaný z `execute_comparison`/`execute_use_case_advice`/
  `execute_basket_completion` (`app/workflow_executor.py`), gate-ovaný
  novým `should_log_decision` flagom: **True len pre CUSTOMER a
  ADMIN_TEST** — nikdy EVALUATION/LEARNING/SHADOW (tie bežia v
  testovacom/optimalizačnom objeme, nesmú zapisovať na disk pri každom
  volaní).
- `learning_eligible` flag: `True` len pre skutočnú CUSTOMER prevádzku.
  ADMIN_TEST záznamy SA logujú (aby živá produkčná verifikácia mala čo
  čítať späť), ale vždy s `learning_eligible=False` — žiadny event sa
  nestáva training labelom len tým, že existuje.
- `interaction_id` teraz prechádza aj do existujúcich `log_question()`
  volaní v týchto 3 executoroch — opravuje reálnu, predtým
  nezistenú medzeru.
- `EventRequest`/`log_event()`: pridané voliteľné (`None` default,
  spätne kompatibilné) polia `interaction_id`/`decision_id`/`event_id`
  — pripravené pre BUDÚCU frontend sprintu s poriadnym JS nástrojom,
  `app/widget.js` ich zatiaľ nevypĺňa.

## 6. Bezpečnostné invarianty overené

- 0 zmien rankingu/promotion/learning súborov (byte-identické).
- `app/widget.js` byte-identický.
- `AUTO_PROMOTION_ENABLED is False` — overené testom.
- Failure isolation: nefunkčná log cesta (`RECOMMENDATION_DECISIONS_LOG_PATH`
  ukazujúca na neexistujúci disk) nezlomí zákaznícku odpoveď — overené.
- Žiadne fabrikované decision_id — obyčajný `product_search` ťah
  neprodukuje žiadny záznam v novom streame.

## 7. Testy

`tests/test_recommendation_decision_correlation_v2_15d.py` — 20 testov:
decision logging pre všetky 3 typy, execution-context izolácia
(EVALUATION nelogauje, ADMIN_TEST loguje s `learning_eligible=False`),
interaction_id propagation fix, failure isolation, no-fabrication
kontrola, AUTO_PROMOTION kontrola, EventRequest spätná kompatibilita,
a plná rt0004/rt0010/rt0011/rt0013/V2.15c regresná matica.

## 8. Regresia

Plná sada: **1664/1664** (1644 + 20 nových). V2.10 fast: 35/39, 0
INTENT_ERROR. Canary: 10/10. Consistency audit: len pred-existujúce
FAQ-deklinačné nálezy (nesúvisiace, nezmenené touto sprintou). Trust
audit: 0 nálezov.

## 9. Per-capability matica

| Kapacita | Stav |
|---|---|
| Decision logging (comparison) | **LIVE** |
| Decision logging (use_case_advice) | **LIVE** |
| Decision logging (basket_completion) | **LIVE** |
| Decision logging (replacement_products) | **NOT_AVAILABLE** — žiadny decision objekt/decision_id existuje pre túto legacy cestu (rt0013 routing), fabrikovanie ID zakázané |
| Cross-sell correlation | **FOUNDATION_ONLY** — evidence tagy existujú na produktoch, žiadny decision_id/durable log |
| Recipe-shopping correlation | **FOUNDATION_ONLY** — vlastný korelačný model existuje, nezapojený do nového streamu |
| Product exposure/click/add-to-cart | **NOT_SAFE_TO_IMPLEMENT_THIS_SPRINT** — blokované chýbajúcim JS overovacím nástrojom |
| Purchase attribution | **NOT_AVAILABLE** — žiadny reálny checkout/order signál v systéme |
| Execution-context izolácia | **LIVE** |
| Idempotency (event_id) | **FOUNDATION_ONLY** — pole pripravené v schéme, žiadny aktívny dedup mechanizmus |
| AUTO_PROMOTION | **DISABLED_AND_UNCHANGED** |

## 10. Finálny release status

**`DECISION_LOGGING_LIVE_FRONTEND_PARTIAL`** — backend decision logging
je plne funkčný a testovaný; frontend korelácia zostáva foundation-only
kvôli chýbajúcemu bezpečnostnému nástroju, nie architektonickému limitu.

## 11. V2.15e GO/STOP

**`V2_15E_STOP_CORRELATION_INSUFFICIENT`** — bez frontend product-click/
add-to-cart korelácie (blokovanej touto sprintou z bezpečnostných
dôvodov, nie neochoty) chýba posledný článok reťazca
(decision → exposure → click → cart) potrebný pre zmysluplnú offline
learning dataset konštrukciu. Odporúčaný ďalší krok NIE JE V2.15e, ale
malá, samostatná sprinta na zavedenie JS testovacej/syntax-check
infraštruktúry (napr. Node.js dostupnosť + jednoduchý linter/syntax
check v CI) pred akýmkoľvek ďalším zásahom do `app/widget.js`.
