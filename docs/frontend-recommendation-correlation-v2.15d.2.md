# V2.15d.2 — Frontend Recommendation Interaction & Confirmed Add-to-Cart Correlation

Dátum: 2026-08-23.

## 1. Mandát a hranica

Uzavrieť chýbajúci frontend segment korelačného reťazca:
`interaction_id → decision_id → product_id → frontend interakcia →
potvrdená akcia v košíku`. **Nie learning sprint** — `AUTO_PROMOTION`
zostáva `False`, žiadna ranking zmena, žiadny nový learning label.

## 2. Baseline

HEAD pred touto sprintou: `84a7d00` (V2.15d.1). pytest 1664/1664,
V2.10 35/39, canary 10/10.

## 3. Re-verifikácia V2.15d/V2.15d.1

**CONFIRMED** (priamo overené, nie prevzaté zo starého reportu):
- `interaction_id` pridaný unconditionally do KAŽDEJ `/chat` odpovede
  (`app/main.py:5351` v aktuálnom stave).
- `comparison_decision_id`/`use_case_advice_decision_id`/
  `basket_decision_id` sú kapacitne-špecifické polia (nie generický
  `decision_id`), vždy najviac JEDNO prítomné naraz (cascade v
  `_chat_impl()` sa vracia skoro z prvého zhodujúceho workflow).
- `format_product()` zachováva `id` pole — kanonický product identifier.
- `fireEvent()` už mal try/catch + `.catch(()=>{})` failure isolation
  (nezmenené touto sprintou).
- `EventRequest` už mal `interaction_id`/`decision_id`/`event_id` ako
  voliteľné polia (V2.15d) — **BACKEND_EXISTS_NOT_EXPOSED** potvrdené:
  polia existovali v schéme, ale `app/widget.js` ich nikdy nečítal ani
  neposielal.

## 4. fireEvent() inventúra (8 volaní pred touto sprintou)

| # | event_type | `data` (plná /chat odpoveď) v scope? | `product` v scope? |
|---|---|---|---|
| autocomplete_select | nie | nie |
| feedback | nie | nie |
| click (view link) | **nie** (len `product`) | áno |
| click (cart button) | **nie** | áno |
| add_to_cart | **nie** | áno |
| search_submit | nie (pred fetch) | nie |
| no_result | **áno** | nie |
| impression | **áno** | nie (má `data.products`) |

Kľúčové zistenie: `data` (plná odpoveď s `interaction_id`/decision
poľami) je v scope len vo `form.addEventListener("submit", ...)`
handleri — NIE vo vnútri `renderCard()`/click handlerov, keďže
`addProducts(data.products, text, ...)` posiela len `data.products`,
`text`, `hasServerMore`, nikdy `data` samotné.

## 5. Riešenie: stash na produktoch (najmenšia bezpečná zmena)

Namiesto pretiahnutia nových argumentov cez `addProducts()`/`renderCard()`
signatúry (Section 16 zakazuje nový globálny stav, Section 37 zakazuje
široký refaktoring IIFE), hneď po `const data = await askBackend(text);`
sa vypočíta `decisionId` a pred renderovaním sa "opečiatkuje" na KAŽDÝ
produkt objekt:

```js
data.products.forEach(function (p) {
  p.interaction_id = data.interaction_id || null;
  p.decision_id = decisionId;
});
```

`renderCard()`/click handlery odteraz čítajú `product.interaction_id`/
`product.decision_id` presne tak, ako už dávno čítali `product.id`.
Nulová zmena signatúr, nulová zmena control flow, nulová zmena poradia
renderovania.

## 6. Decision ID rozlíšenie (Section 13/14)

```js
const decisionId = data.comparison_decision_id || data.basket_decision_id || data.use_case_advice_decision_id || null;
```

Bezpečné, pretože tieto tri polia sa NIKDY nevyskytujú súčasne (overené
priamo v `app/main.py`/`app/workflow_executor.py` — každý `_execute_*`
sa vracia skoro s vlastným dictom). Pre bežné `product_search` (žiadna
z troch dekízií) je `decisionId = null` — **nefabrikuje sa nič**.

## 7. Tri odlíšené sémantiky (Section 18-23) — najrizikovejšia časť sprinty

Priama analýza `submitRealAddToCartForm()` odhalila kritický
architektonický fakt: **Promise sa doteraz resolvovala identicky** bez
ohľadu na to, či úspech prišiel z autoritatívneho XHR-potvrdenia alebo
z 2.5s fallback-timera (hádanie) — volajúci kód to nevedel rozlíšiť.

**Fix**: `finish(err, authoritative)` — `resolve({authoritative})`:
- XHR intercept potvrdil `data.success===true` → `finish(null, true)`
- fallback timer (len keď interceptovanie samotné zlyhá) → `finish(null, false)`
- `addToCart()` vracia `{attempted, authoritative}`, propaguje sa až
  do click handlera.

Udalosti:
- **`click`** (nezmenené, teraz s `interaction_id`/`decision_id`)
- **`add_to_cart_attempt`** (NOVÉ) — fireuje sa PRED `try{}`, znamená
  len "zákazník inicioval mechanizmus", nič viac.
- **`add_to_cart`** (legacy, NEZMENENÉ miesto/sémantika — zachované pre
  spätnú kompatibilitu s `app.fbt`/`app.behavioral`/`app.learning_signals`,
  ktoré kľúčujú presne na tento reťazec).
- **`add_to_cart_confirmed`** (NOVÉ) — fireuje sa LEN keď
  `cartResult.authoritative === true`. Fallback-guess túto vetvu nikdy
  nedosiahne.

## 8. Duplicitné potvrdenie — už štrukturálne nemožné

Overené priamo v kóde: `finish()` má `settled` guard (volateľné len
raz), a intercept-vs-fallback vetvy sú VZÁJOMNE VYLUČUJÚCE (fallback
beží LEN keď sa samotné nastavenie interceptovania synchrónne zlyhá —
vtedy real XHR event nikdy nepríde). "Neskorý úspech po fallbacku"
(Section 66-67) je preto štrukturálne nemožný, nie len ošetrený.

## 9. event_id / idempotencia

**`EVENT_ID_NOT_REQUIRED_FOR_CURRENT_FLOW`** — `cartBtn.disabled = true`
je prvý riadok click handlera (synchrónne, pred akoukoľvek async prácou),
takže druhé kliknutie na to isté tlačidlo je nemožné (disabled tlačidlo
nefireuje click). Kombinované s bodom 8 vyššie, evidencia nepodporuje
potrebu event_id v tomto toku.

## 10. Backend zmena (jediná)

`EventRequest.event_type` Literal rozšírený o `"add_to_cart_attempt"`/
`"add_to_cart_confirmed"` (aditívne, `"add_to_cart"` nezmenené).
`log_event()` už persistoval `interaction_id`/`decision_id`/`event_id`
z V2.15d — žiadna ďalšia backend zmena potrebná.

## 11. Capability scope

- `comparison`, `use_case_advice`, `basket_completion`: **CORRELATED**
  (majú reálny `decision_id`).
- `cross_sell`, `recipe_shopping`, `replacement_products`: **NOT_CORRELATED**
  — žiadny existujúci decision_id objekt, fabrikovanie zakázané (Section 15/45-47).
- Bežné `product_search`: **CORRELATED** len s `interaction_id`, `decision_id=null` (očakávané, správne).

## 12. Privacy / execution context

Žiadne nové PII — len opaque IDs. `learning_eligible` sémantika
nedotknutá (frontend eventy vôbec nemajú toto pole — pridáva sa len na
BACKENDOVEJ `recommendation_decisions.jsonl` strane z V2.15d, nie na
`events.jsonl`). Execution context frontend nemôže niesť bezpečne (žiadny
mechanizmus na to) — zdokumentované ako limitácia, nevymyslené.

## 13. Testy

`tests/js/widget.test.mjs`: 7 pôvodných + 12 nových testov (23 spolu) —
decision-id rozlíšenie, 3 odlíšené event typy, poradie attempt-pred-try,
confirmed-gated-na-authoritative, fallback=false/authoritative=true,
no-purchase-fabrication, no-learning-call, telemetry failure isolation
nezmenená. Všetky regexy krížovo overené cez Python pred pushom.

`tests/test_frontend_recommendation_correlation_v2_15d_2.py`: 16 nových
backend testov — nové event_type literály, `purchase` odmietnutý,
perzistencia korelačných polí, `/events` endpoint end-to-end,
`AUTO_PROMOTION` nezmenené, rt0004/rt0010/rt0013/V2.15c kontroly.

## 14. Regresia

pytest, V2.10, canary, audity — pozri finálny report.

## 15. Event volume delta

Úspešné potvrdené pridanie do košíka: predtým 2 eventy (`click`,
`add_to_cart`), teraz 4 (`click`, `add_to_cart_attempt`, `add_to_cart`,
`add_to_cart_confirmed`). Fallback-guess úspech: 3 eventy (bez
`_confirmed`). Zlyhanie: nezmenené (1 event, `click`).

## 16. Finálny stav

**`FRONTEND_INTERACTION_CORRELATION_READY_CONFIRMED_CART_TEST_LIMITED`**
— štruktúra je live-nasadená a staticky/backend-testovaná, ale reálny
end-to-end confirmed-cart test na produkcii nebol vykonaný (Section 90
explicitne zakazuje manipulovať reálny zákaznícky košík len kvôli
testu) — `CONFIRMED_CART_LIVE_TEST_NOT_SAFE`, legitímny výsledok.

## 17. V2.15e

Zostáva mimo automatického spustenia. Dataset je teraz kauzálne bohatší
(decision→product→interaction reťazec kompletný), ale confirmed-cart
live-test limitácia a chýbajúci purchase signál znamenajú, že formálne
posúdenie pripravenosti patrí do samostatnej, budúcej sprinty.
