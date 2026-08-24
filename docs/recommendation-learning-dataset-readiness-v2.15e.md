# V2.15e — Recommendation Learning Dataset Readiness & Causal Signal Quality Gate

Dátum: 2026-08-24. HEAD pred sprintou: `48b59ce` (`BASELINE_CONFIRMED`).

## 1. Mandát

Otázka tejto sprinty **nie je** "má Foodland dosť dát na learning?" ale
"sú dostupné signály dostatočne dobre definované, kauzálne priraditeľné,
odolné voči kontaminácii a sémanticky poctivé, aby mohli tvoriť budúci
learning dataset?" **GATE A (audit only)** bol zvolený — žiadny dataset
builder, žiadny zásah do `app/widget.js` ani runtime rankingu.
`AUTO_PROMOTION` nezmenené (`False`), overené testom aj priamo na
produkcii.

## 2. Re-verifikácia V2.15a–d.3 (nezávisle, nie prevzaté)

Všetky kľúčové zistenia **CONFIRMED** priamym čítaním kódu (nie
dokumentácie): `interaction_id` generovaný raz za `/chat` (vždy nový, aj
pri resultset continuation), `decision_id` kapacitne-špecifický pre 3
capabilities, `execution_context`/`learning_eligible` mechanizmus na
`/events` funguje presne ako zdokumentované, `AUTO_PROMOTION_ENABLED is False`,
`/admin/analytics/events-purge` vyžaduje presne `_SCOPE_PROMOTION`
nezmenené.

## 3. Observational unit model

```
interaction_id (vždy nový za /chat request, aj pri continuation)
    ↓
decision_id (LEN pre comparison/use_case_advice/basket_completion)
    ↓
candidate_product_ids / recommended_product_ids (v recommendation_decisions.jsonl)
    ↓
frontend exposure (product.interaction_id/decision_id stash, V2.15d.2)
    ↓
click / add_to_cart_attempt / add_to_cart(legacy) / add_to_cart_confirmed (events.jsonl)
```

**Reťaz sa láme** pri: resultset continuation (nový interaction_id,
žiadny decision_id), cross_sell/recipe_shopping/replacement_products
(žiadny decision objekt vôbec), explicit feedback (žiadna korelácia).

## 4. Signal inventory (evidence-backed)

| Signál | Zdroj | interaction_id | decision_id | execution_context | Kauzálna sila |
|---|---|---|---|---|---|
| recommendation decision | `recommendation_decisions.jsonl` | áno | áno (3 z 7 capabilities) | áno | OBSERVED (rozhodnutie samotné) |
| impression | `events.jsonl` | áno (V2.15d.2) | áno keď dostupné | áno | OBSERVED (exposure only) |
| click | `events.jsonl` | áno | áno keď dostupné | áno | OBSERVED (interakcia, nie kvalita) |
| add_to_cart_attempt | `events.jsonl` | áno | áno keď dostupné | áno | OBSERVED (iniciácia, nie výsledok) |
| add_to_cart (legacy) | `events.jsonl` | nie (widget ho neposiela na tomto mieste rovnako) | áno keď dostupné | áno | OBSERVED (believed-success) |
| add_to_cart_confirmed | `events.jsonl` | áno | áno keď dostupné | áno | OBSERVED (najsilnejší commerce signál, no NIE purchase) |
| feedback (thumbs) | `events.jsonl` | **nie** | **nie** | áno | OBSERVED, ale nepriraditeľné ku konkrétnemu rozhodnutiu |
| reformulation | offline batch (`app.learning_signals`) | n/a | n/a | n/a | INFERRED, nikdy live, `NEVER_USE_FOR_LEARNING` (nezmenené od V2.15a) |
| resultset continuation | `/chat` response | áno (nový!) | **nie** | áno | OBSERVED, ale attribution break |
| ABSTAIN/CLARIFY | `recommendation_decisions.jsonl` (`state`) | áno | áno | áno | OBSERVED, **nikdy failure** |
| purchase | — | — | — | — | `PURCHASE_SIGNAL_NOT_AVAILABLE` |

## 5. OBSERVED/DERIVED/INFERRED/FORBIDDEN matica

| Pole | Klasifikácia |
|---|---|
| `event_type` (napr. click, add_to_cart_confirmed) | OBSERVED |
| `product_sku`/`product_id` | OBSERVED |
| `decision_id`, `interaction_id` | OBSERVED (keď prítomné) |
| `execution_context`, `learning_eligible` | DERIVED (server-side resolvované) |
| "click = preferencia" | **FORBIDDEN_FOR_LEARNING** |
| "žiadny klik = negatívum" | **FORBIDDEN_FOR_LEARNING** |
| "add_to_cart_confirmed = nákup" | **FORBIDDEN_FOR_LEARNING** |
| "reformulation = nespokojnosť" | **FORBIDDEN_FOR_LEARNING** |
| "ABSTAIN/CLARIFY = zlyhanie" | **FORBIDDEN_FOR_LEARNING** |
| "systémom vybraný produkt = ground truth" | **FORBIDDEN_FOR_LEARNING** |
| "neexponovaný produkt = negatívum" | **FORBIDDEN_FOR_LEARNING** |

## 6. Learning label candidate matica

| Label | Zdroj | Sila | Capabilities | Klasifikácia |
|---|---|---|---|---|
| `add_to_cart_confirmed` (po comparison/use_case/basket decision_id) | events.jsonl + recommendation_decisions.jsonl join | najsilnejšia dostupná | comparison/use_case/basket | `EMPIRICAL_DATA_REQUIRED` (štruktúrne READY, empiricky 0 pozorovaní so spojeným decision_id) |
| `click` (po decision_id) | rovnaké | stredná (engagement, nie kvalita) | comparison/use_case/basket | `EMPIRICAL_DATA_REQUIRED` |
| `thumbs_up`/`thumbs_down` | events.jsonl | silná explicitná, ale nepriraditeľná | žiadna (chýba korelácia) | `STRUCTURAL_ONLY` (potrebuje frontend fix najprv) |
| `impression` bez akcie | events.jsonl | žiadna (exposure only) | všetky | `NEVER_USE_FOR_LEARNING` ako label sama osebe |
| `reformulation` | offline batch | slabá, viacvýznamová | n/a | `NEVER_USE_FOR_LEARNING` |
| `ABSTAIN`/`CLARIFY` state | recommendation_decisions.jsonl | n/a (nie label, kontext) | comparison/use_case | `STRUCTURAL_ONLY` — použiteľné len ako kontext/filter, nikdy ako negatívny label |

## 7. Per-capability readiness matica

| Capability | decision_id | STRUCTURAL_READINESS | EMPIRICAL_READINESS |
|---|---|---|---|
| comparison | áno | `READY_WITH_LIMITATIONS` | `EMPIRICAL_DATA_REQUIRED` |
| use_case_advice | áno | `READY_WITH_LIMITATIONS` | `EMPIRICAL_DATA_REQUIRED` |
| basket_completion | áno | `READY_WITH_LIMITATIONS` | `EMPIRICAL_DATA_REQUIRED` |
| cross_sell | nie | `STRUCTURAL_GAP` | n/a |
| recipe_shopping | nie | `STRUCTURAL_GAP` | n/a |
| replacement_products | nie (legacy detektor) | `STRUCTURAL_GAP` | n/a |
| ordinary product_search | n/a (correctly null) | `NOT_APPLICABLE` (žiadna dedikovaná decision) | n/a |

## 8. Bias a limitácie (musia zostať zdokumentované, nie vyriešené)

- **Selection bias**: systém pozoruje správanie len pre produkty, ktoré
  sám vybral zobraziť. Nevystavené produkty NIKDY nesmú byť negatívne
  príklady.
- **Position bias**: `position` pole existuje v `EventRequest`, ale nie
  je systematicky analyzované — click signály sú position-confounded.
- **Counterfactual limitation**: systém nevie, čo by zákazník preferoval
  z produktov, ktoré neboli zobrazené — široké pairwise preference
  learning nie je podporené.
- **Jazykový rozsah**: takmer výhradne slovenčina (V2.14 recommendation
  intelligence je SK-scoped) — žiadny multilingválny nárok.

## 9. Empirické počty (produkcia, 90 dní, cez `/admin/analytics/events-summary`)

```
total_events: 1283
click: 78, search_submit: 585, impression: 409, add_to_cart(legacy): 36,
no_result: 115, autocomplete_select: 26, feedback: 23,
add_to_cart_attempt: 7, add_to_cart_confirmed: 4
unique_sessions: 210
```

**Kritické zistenie zo vzorky 200 najnovších eventov**: **0 z 200** malo
nenulové `decision_id`; 42/200 malo `interaction_id`; len 52/200 malo
`execution_context="CUSTOMER"` tag (zvyšok sú legacy pred-V2.15d.3
záznamy bez tagu, traktované ako CUSTOMER). Toto NIE JE dôkaz chyby —
comparison/use_case/basket sú úzke capabilities, ich frekvencia v
reálnej prevádzke je nízka. Je to čestný dôkaz nedostatočného
empirického objemu.

## 10. Duplicitné riziko

`event_id` **nebolo pridané** — dôkazmi podložené, že `cartBtn.disabled`
guard + `submitRealAddToCartForm()`'s `settled`/`clicked` flags už
štrukturálne zabraňujú duplicitným confirmed-cart eventom (nezmenené od
V2.15d.2, znovu-overené priamo v kóde tejto sprinty).

## 11. Kontaminácia

`HISTORICAL_SYNTHETIC_EVENTS_REMOVED` potvrdené (V2.15d.3 + follow-up).
`/admin/analytics/events-purge` **NEBOL** touto sprintou volaný —
`PRODUCTION_EVENTS_PURGE_INVOKED_BY_V2_15E = NO`. `LIVE_SYNTHETIC_TEST_EVENT_CREATED = NO`
(žiadny nový syntetický event nebol vytvorený — verifikácia použila
existujúce read-only admin endpointy).

## 12. Dataset builder

**GATE A** — audit only. Žiadny builder implementovaný. Odôvodnenie:
nízky empirický objem by produkoval prakticky prázdny dataset; budovanie
infraštruktúry teraz by vytvorilo falošný dojem pripravenosti.

## 13. Testy

`tests/test_learning_dataset_readiness_v2_15e.py` — 19 testov: resultset
continuation attribution break, feedback bez korelácie, reformulation
nikdy live/negatívna, ABSTAIN/CLARIFY nikdy failure, end-to-end kauzálny
reťazec pre 3 capabilities, ordinary search nikdy nefabrikuje decision_id,
EVALUATION exclusion, AUTO_PROMOTION freeze, purchase rejected,
štrukturálne medzery (cross_sell/recipe_shopping) dôkazom neprítomnosti.

## 14. Finálny stav

**`STRUCTURALLY_READY_EMPIRICALLY_INSUFFICIENT`**

- `STRUCTURAL_READINESS` = `READY_WITH_LIMITATIONS` (3 z 7 capabilities)
- `EMPIRICAL_READINESS` = `INSUFFICIENT_DATA`

## 15. V2.15f

Nezačína sa automaticky. Odporúčaný ďalší krok: NIE dataset builder,
ale (a) frontend fix pre feedback→decision_id korelácia (malý, izolovaný),
(b) počkať na prirodzený nárast objemu comparison/use_case/basket
interakcií, (c) zvážiť cross_sell decision logging ako samostatnú,
úzko-rozsahovú sprintu predtým, než sa V2.15f formálne posúdi.
