# V2.15e.2 — Explicit Feedback → Recommendation Decision Correlation & Signal Integrity Closure

Dátum: 2026-08-24. HEAD pred sprintou: `376c0ae` (V2.15e.1, `ATTRIBUTION_STRUCTURE_READY`).

## 1. Mandát

V2.15e identifikoval, že `app/widget.js`'s `vote()` neposiela
`decision_id` — explicitná spätná väzba (👍/👎) je pozorovateľná, ale
nie je spoľahlivo priraditeľná ku konkrétnemu recommendation
rozhodnutiu. Táto sprinta uzatvára presne túto medzeru, **bez zmeny
významu** 👍/👎.

## 2. Repository reality check

HEAD potvrdený `376c0ae` (zhoduje sa s očakávanou baseline). Working
tree čistý (len pred-existujúci netrackovaný `.claude/`). Žiadny reset
nebol potrebný.

## 3. Re-verifikácia V2.15e nálezu

**CONFIRMED** priamym čítaním `app/widget.js:1435-1438` (pred zásahom):
`vote(rating)` volalo `fireEvent({ event_type: "feedback", rating:
rating, query: query || null })` — žiadny `interaction_id`,
`decision_id` ani `result_set_id`. Nález je presný, nie zastaraný.

## 4. Inventár toku spätnej väzby

```
odpoveď /chat prichádza (data.interaction_id, decisionId, data.result_set_id
   uz existuju ako response-local premenne v submit handleri, riadok ~2017)
    ↓
addFeedbackControls(text)  ← PRED opravou: žiadne ID sa neposielali ďalej
    ↓
vote(rating) [closure nad `query`, `wrap`, `answered`]
    ↓
fireEvent({event_type:"feedback", rating, query})
    ↓
POST /events → EventRequest (interaction_id/decision_id/result_set_id
    UŽ EXISTUJÚ ako generické, voliteľné polia od V2.15d/V2.15e.1)
    ↓
log_event() → events.jsonl (UŽ perzistuje tieto polia bez ohľadu na
    event_type)
```

**Kľúčové zistenie**: backend nepotreboval ŽIADNU zmenu. Medzera bola
výhradne v `app/widget.js` — presne tie isté hodnoty (`data.interaction_id`,
`decisionId`, `data.result_set_id`), ktoré V2.15d.2/V2.15e.1 už používajú
pre korešpondenciu klikov na produkty, boli v tej istej funkcii dostupné
o 23 riadkov nižšie, no nikdy sa nepreniesli do `addFeedbackControls()`.

## 5. Čo dnes hodnotí 👍?

**Interpretácia A/D**: celá práve vyrenderovaná odpoveď asistenta ("Bola
táto odpoveď užitočná?" — text UI labelu explicitne potvrdzuje toto).
NIE hodnotenie konkrétneho produktu. Toto zostáva **nezmenené** — sprinta
pridáva len korelačné metadáta, nepredefinováva sémantiku hlasovania.

## 6. Čo dnes hodnotí 👎?

Symetricky: explicitná negatívna spätná väzba k práve vyrenderovanej
odpovedi ako celku.

## 7. Dostupnosť `interaction_id`

Vždy dostupný — `data.interaction_id` existuje pre KAŽDÚ `/chat`
odpoveď bez výnimky.

## 8. Dostupnosť `decision_id`

Dostupný len keď `data.comparison_decision_id` /
`data.basket_decision_id` / `data.use_case_advice_decision_id` je
neprázdne — presne tá istá `decisionId` premenná, ktorú V2.15d.2 už
počíta pre klik-korešpondenciu. Pre ordinary search/FAQ/store_location
zostáva `null` — nikdy fabrikovaný.

## 9. Dostupnosť `result_set_id`

Dostupný, keď `data.result_set_id` je neprázdne (ordinary search vrátane
"Zobraz viac" pokračovania). `null` pre comparison/use_case_advice/
basket_completion (tie `ResultSet` nikdy nevytvárajú).

## 10. Politika `product_id`

**Nepridané.** Hlasovanie hodnotí celú odpoveď, nie konkrétny produkt —
pridanie `product_id` by fabrikovalo produktovú kauzalitu, ktorú UI
nikdy neponúkalo.

## 11. Vyhodnotenie identity modelov (A–D)

| Model | Popis | Verdikt |
|---|---|---|
| A | len najnovší `interaction_id` | Nedostatočný — stráca sa jediný signál, ktorý odlišuje comparison/use_case/basket od ordinary search |
| B | + legitímny `decision_id` | Čiastočne správny, ale ignoruje `result_set_id` pre ordinary search/continuation prípady |
| **C** | + `decision_id` (keď legitímny) + `result_set_id` (keď užitočný) | **ZVOLENÉ** |
| D | iná existujúca identita odpovede | Preskúmané — `result_set_id`/`decision_id`/`interaction_id` UŽ SÚ presne táto identita |

## 12. Zvolený identity model

**Model C.** `interaction_id` (vždy), `decision_id` (len keď legitímny,
inak `null`), `result_set_id` (len keď existuje, inak `null`) — presne
tie isté tri hodnoty, ktoré response-local scope submit handlera už mal
vypočítané pre inú korešpondenciu (V2.15d.2/V2.15e.1). Žiadny nový
identifikátor.

## 13. Implementačná brána

**GATE B — Minimálna widget propagácia.** `EventRequest` už mal
generické `interaction_id`/`decision_id`/`result_set_id` polia platné
pre AKÝKOĽVEK `event_type` (vrátane `"feedback"`) od V2.15d/V2.15e.1;
`log_event()` ich už perzistuje bez ohľadu na `event_type`. **Nulová
zmena backend schémy.**

## 14. Implementácia

Byte-safe patch `app/widget.js` (3 miesta, +17/-3 riadkov, LF región):

1. `addFeedbackControls(query)` → `addFeedbackControls(query,
   interactionId, decisionId, resultSetId)`.
2. `vote()`'s `fireEvent` teraz zahŕňa `interaction_id: interactionId ||
   null, decision_id: decisionId || null, result_set_id: resultSetId ||
   null`.
3. Volanie `addFeedbackControls(text)` → `addFeedbackControls(text,
   data.interaction_id || null, decisionId, data.result_set_id ||
   null)` — presne tá istá `decisionId` premenná, ktorá sa už používa o
   pár riadkov nižšie pre stash na produkty, nie druhostupňovo počítaná.

## 15. Widget patch — response-local state

Žiadny nový globálny/mutovateľný stav. `addFeedbackControls()` je
volaná RAZ za odpoveď a jej `vote()` closure zachytáva presne tie tri
parametre danej odpovede — staršia/novšia odpoveď nemôže "zdediť" cudziu
identitu, pretože každé volanie má vlastný, nezávislý closure scope.

## 16. Backend schéma

Nezmenená. `EventRequest.interaction_id`/`decision_id`/`result_set_id`
existovali už pred touto sprintou (V2.15d/V2.15e.1), aplikovateľné na
akýkoľvek `event_type`.

## 17. Comparison feedback

Correlated. `decision_id` = `data.comparison_decision_id`, potvrdené
testom `test_comparison_response_exposes_decision_id`.

## 18. use_case_advice feedback

Correlated. Rovnaký mechanizmus, `data.use_case_advice_decision_id`.

## 19. basket_completion feedback

Correlated. `data.basket_decision_id`.

## 20. Ordinary search feedback

`interaction_id` prítomný, `decision_id` = `null` — **nikdy
fabrikovaný**. Testom overené (`test_ordinary_search_has_no_decision_id`).

## 21. FAQ / store_location feedback

`decision_id` = `null` (informačná odpoveď nikdy nevlastní recommendation
decision). Testom overené.

## 22. Continuation feedback ("Zobraz viac")

Charakterizované priamo: `result_set_id` stabilný (rovnaký ako pôvodné
hľadanie), `interaction_id` čestne nový, `decision_id` = `null` (ordinary
product_search continuation nikdy nevlastní decision object — toto NIE
JE chyba, je to čestný odraz reality, keďže continuation cesta žiadny
decision nikdy nevytvára).

## 23. Tvrdý prepnutie témy

Každá odpoveď má vlastný, nezávislý `decisionId`/`data` scope — staršie
`decision_id` nemôže "prežiť" do novšej odpovede. Testom overené
(`test_hard_topic_switch_does_not_carry_previous_decision_id`) aj
negative control testom s dvomi po sebe idúcimi comparison rozhodnutiami
(D1 ≠ D2).

## 24. Reset

Po resete má nasledujúca odpoveď čerstvé `data`/`decisionId` — žiadny
globálny stav vo `addFeedbackControls()` nikdy neexistoval, takže reset
triviálne nemá čo vyčistiť na frontende; backend-side testom overené, že
nová odpoveď po resete nenesie starý `decision_id`.

## 25. Null attribution policy

Nulový `decision_id`/`result_set_id` je vždy uprednostnený pred
fabrikovaným. Žiadne odvodzovanie z `session_id`/timestampu/textu
otázky.

## 26. Legacy feedback

Staré `feedback` eventy bez korelačných polí zostávajú validné a
čitateľné (`interaction_id`/`decision_id`/`result_set_id` sú a vždy boli
voliteľné). Klasifikované `LEGACY_UNCORRELATED`.

## 27. Vote switching / duplicity

**Nezmenené.** `answered` flag zabezpečuje "prvý hlas vyhráva" — po
prvom kliku (👍 alebo 👎) sa tlačidlá odstránia z DOM
(`wrap.innerHTML = ""`), ďalšie hlasovanie na tú istú odpoveď nie je
možné. Toto je existujúci produktový dizajn, nie chyba — sprinta ho
nemení.

## 28. Execution context

`/events` už aplikuje identický execution-context mechanizmus na
VŠETKY `event_type` vrátane `"feedback"` (žiadne osobitné vetvenie podľa
typu eventu). Testom overené: `CUSTOMER` → durably logged,
`EVALUATION` → nikdy logged, `ADMIN_TEST` → logged s
`learning_eligible=False`.

## 29. `learning_eligible`

Zachované konzervatívne — korelovaná spätná väzba je stále LEN
pozorovaný signál, nikdy runtime learning trigger.

## 30. Privacy

Žiadne nové PII. Korelačné polia sú výhradne technické ID
(alfanumerické, max_length limitované), nie osobné údaje.

## 31. Store location kontrola

`Stará Vajnorská 3308/19, 831 04 Bratislava` +
`https://maps.app.goo.gl/3tFJ4P6w2pj88xAP8` — nezmenené, testom overené.

## 32. Resultset continuation kontrola

V2.15e.1 model (nový `interaction_id` + stabilný `result_set_id`)
zachovaný nezmenený a znovu-testovaný.

## 33. Confirmed cart kontrola

V2.15d.2 `authoritative` invariant nezmenený.

## 34. Learning/ranking freeze

`app/learning_lifecycle.py`, ranking súbory nedotknuté. Zdrojový kód
`app/widget.js` obsahuje 0 výskytov `AUTO_PROMOTION`/`learning_lifecycle`/
`ranking_optimizer`/`ranking_config` (testom overené).

## 35. `AUTO_PROMOTION`

**`False`** pred aj po sprinte (testom overené priamo z
`app.learning_lifecycle.AUTO_PROMOTION_ENABLED`).

## 36. Počet LLM volaní

**0 nových.** Táto sprinta je čisto korelačná/telemetrická.

## 37. Počet search volaní

**0 nových.**

## 38. Performance

Frontend: konštantný čas (3 dodatočné parametre v existujúcom volaní
funkcie). Backend: nulová dodatočná záťaž (polia už existovali v schéme).

## 39. JS testy

`tests/js/widget.test.mjs` rozšírený o 10 nových `node:test` prípadov
(static source-inspection, krížovo overené Python `re` proti reálnemu
`app/widget.js` zdroju pred commitom, keďže Node.js nie je lokálne
dostupný): signature zmena, fireEvent propagácia, call site reuse
existujúcej `decisionId`, no-fabrication kontrola, ordering, no stale
global var, `answered` gate nezmenený, žiadny `product_id`/`product_sku`
v feedback payloade, žiadny learning/ranking string, existujúcich 5
`fireEvent()` volaní nezmenených.

## 40. Python testy

`tests/test_feedback_decision_correlation_v2_15e_2.py` — 26 testov
(charakterizačné, spustené AJ pred implementáciou, keďže backend sa
nemenil): legitímna decision korelácia (comparison/use_case/basket),
no-fabrication (ordinary search/FAQ), continuation, hard-switch +
negative control (D1≠D2), reset, cross-session izolácia, `EventRequest`
spätná kompatibilita, malformed/overlong ID handling, execution-context
izolácia (CUSTOMER/EVALUATION/ADMIN_TEST), `AUTO_PROMOTION` freeze,
storage failure izolácia, plná kontrolná matica (rt0004/rt0010/rt0011/
rt0013, store-location, V2.15e.1 resultset continuation).

## 41. Plná testovacia sada

Pozri finálny report — spustená po implementácii, očakávaný nárast o
26 (Python) + 10 (JS) oproti V2.15e.1 baseline (1782).

## 42. V2.10

Očakávané nezmenené (35/39) — sprinta nemení routing ani recommendation
sémantiku.

## 43. Canary

Očakávané nezmenené (10/10).

## 44. Consistency/Trust audit

FAQ deklinačné nálezy zostávajú `PRE_EXISTING` (nesúvisia s touto
sprintou). Trust audit očakávaný čistý.

## 45. Diff/byte-safety

`git diff --stat` == `git diff --ignore-space-at-eol --stat` presne pre
`app/widget.js`. `git diff --check` **čistý** (patch je celý v LF
regióne, nedotkol sa žiadneho CR riadka).

## 46. Dokumentácia

Tento súbor + minimálne dodatky do `docs/roadmap-features.md` a
`docs/routing-debt.md`.

## 47. Zamrazenia

`AUTO_PROMOTION=False` nezmenené. Žiadna zmena zákazníckeho správania —
UI text, tlačidlá, `answered`-gate, celé vizuálne správanie feedbacku sú
bit-identické; mení sa len to, čo sa POSIELA na `/events` popri
existujúcom `rating`/`query`.

## 48. Zostávajúci dlh

- Empirický objem korelovanej spätnej väzby je k dátumu nasadenia 0
  (funkcia je nová) — štrukturálna pripravenosť ≠ empirická dostatočnosť.
- `cross_sell`/`recipe_shopping`/`replacement_products` stále nemajú
  decision objekt — feedback na tieto odpovede zostáva `decision_id=null`
  štrukturálne (nie chyba tejto sprinty).
- Historická spätná väzba spred tejto sprinty zostáva
  `LEGACY_UNCORRELATED` navždy — žiadne spätné odvodzovanie.

## 49. Finálny stav

Pozri finálny Slovenský report (samostatná správa) pre presné evidence-backed
hodnoty vrátane CI/Railway/live verifikácie.

## 50. Ďalší krok

V2.15f sa nezačína automaticky. Kandidáti: V2.15e.3 (cross_sell/
recipe_shopping/replacement_products decision observability), alebo
čakanie na empirický objem correlated feedbacku.
