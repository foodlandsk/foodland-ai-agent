# V2.15e.3 — Decision Observability Expansion (cross_sell / recipe_shopping / replacement_products)

Dátum: 2026-08-25. HEAD pred sprintou: `2bb1ea5` (V2.15e.2,
`FEEDBACK_CORRELATION_FOUNDATION_READY`).

## 1. Mandát

V2.15e.2 klasifikoval `cross_sell`/`recipe_shopping`/`replacement_products`
ako `STRUCTURAL_GAP`. Táto sprinta preskúmala každú z troch kapacít
**nezávisle**, s explicitným zákazom optimalizovať na 7/7 pokrytie.
Výsledok je zámerne heterogénny — presne ako spec predpokladal.

## 2. Repository reality check

HEAD potvrdený `2bb1ea5` (zhoduje sa s očakávanou baseline). Working
tree čistý. Žiadny reset potrebný.

## 3. Kritický princíp (9 otázok pred akýmkoľvek decision objektom)

Pred návrhom modelu pre každú kapacitu: aká je akcia, kandidáti, skutočné
rozhodnutie, dôkaz, vybraný produkt/rola, kandidátna množina, abstencia,
a je downstream akcia zákazníka priraditeľná? Odpovede nižšie per kapacita.

## 4. PART A — cross_sell audit

`app.cross_sell.build_cross_sell()` počíta **skutočné, dôkazmi podložené
rozhodnutie**: `CrossSellDecision` (eligible/reason/context_type/
complementary_roles) + `CrossSellCandidate` per rola (product_id, role,
evidence, reason_code, score). Empiricky overené priamym behom
(`sushi ryža` po `co potrebujem na sushi` kontexte): `cross_sell_eligible=True`,
3 kandidáti (soy_sauce/nori/rice_vinegar), každý s reálnym evidence tagom.

**Kľúčový nález**: `app/widget.js` **nikdy nečíta `data.cross_sell`**
(grep-overené: 0 výskytov v celom súbore). Produkty sa vrátia v API
odpovedi ako samostatné pole, ale zákazník ich nikdy neuvidí.

## 5. cross_sell — vyhodnotenie modelov

| Model | Verdikt |
|---|---|
| CS-A/B/C (akýkoľvek decision_id) | Technicky implementovateľné, ale **korelácia nikdy nemôže nastať** (produkt sa nikdy nezobrazí) |
| **CS-D** (žiadny formálny decision objekt) | **ZVOLENÉ** |

## 6. cross_sell — zvolený model

**Žiadny.** Dôvod presahuje "nie je čas": durably logovať rozhodnutie,
ktoré zákazník nikdy neuvidí, by vytvorilo **permanentne-nulové-engagement**
záznamy, ktoré by budúci dataset builder mohol nesprávne interpretovať
ako reálny negatívny signál — presne to, čo V2.15e's OBSERVED/DERIVED/
INFERRED/FORBIDDEN matica zakazuje ("žiadny klik = negatívum" je
`FORBIDDEN_FOR_LEARNING"). Pridanie renderovania do widgetu by bola
UX/produktová zmena, explicitne mimo rozsahu tejto observability sprinty
(Section 45: "Do NOT change UX").

## 7. cross_sell — brána

**GATE A — STRUCTURAL_GAP_ACCEPTED.**

## 8. cross_sell — implementácia

Žiadna. `app/cross_sell.py`, `app/main.py`'s cross_sell integrácia,
`app/widget.js` nedotknuté.

## 9. cross_sell — finálny stav

`STRUCTURAL_GAP_ACCEPTED` (`FRONTEND_RENDERING_GAP`, nie chyba decision
modelu — ten je už kvalitný).

## 10. PART B — recipe_shopping audit

`app.recipe_shopping.build_recipe_shopping_plan()` vracia
`RecipeShoppingPlan` s per-ingredient `PlanIngredient` (ingredient_concept_id,
role, requirement, **status** [AVAILABLE/ALREADY_SATISFIED/NOT_AVAILABLE/
OPTIONAL/UNKNOWN_MAPPING], selected_product_id, **candidate_product_ids**,
confidence). Toto je štrukturálne **identické** s `app.basket_completion`'s
existujúcim rozhodnutím (ktoré už má `basket_decision_id`) — obe sú
multi-role odporúčania s per-role kandidátmi a jedným finálnym výberom.

**Kľúčový rozdiel oproti cross_sell**: `recipe_products` sa zlučujú
PRIAMO do primárneho `data.products` poľa (`app/workflow_executor.py`'s
`execute_recipe()`, riadok ~471-473) — teda **už dnes plne renderované a
interaktívne**. Empiricky overené: `co potrebujem na pad thai` →
`intent=recipe_to_products`, `recipe_shopping_plan` prítomný, 5 produktov
v `data.products`, `recipe_graph_index.dishes_by_id` obsahuje 47 jedál.

## 11. recipe_shopping — vyhodnotenie modelov

| Model | Verdikt |
|---|---|
| RS-A (jeden decision_id za celý plán) | **ZVOLENÉ** — presný precedens `execute_basket_completion()` |
| RS-B (decision_id per rola) | Zamietnuté — zbytočná komplexita, `reason_codes`/candidate union v jednom zázname to už pokrýva čestne |
| RS-C (root + sub-decisions) | Zamietnuté — "Do NOT create nested decision graphs without strong evidence" |
| RS-D (žiadny nový objekt) | Zamietnuté — dôkazy jasne podporujú model, produkty sú už renderované |

## 12. recipe_shopping — zvolený model

**Model RS-A**, mirror `execute_basket_completion()`'s presného vzoru:
`candidate_product_ids` = union `ing.candidate_product_ids` cez všetky
ingrediencie; `recommended_product_ids` = `selected_product_id` per
ingrediencia; `reason_codes` = zoradená množina statusov; `state` =
`FULLY_RESOLVED`/`PARTIALLY_RESOLVED` podľa `missing_required_count`.

## 13. recipe_shopping — brána

**GATE C — minimálny backend + widget korešpondencia.**

## 14. recipe_shopping — implementácia

`app/workflow_executor.py`'s `execute_recipe()` (+56 riadkov, CRLF
región): pridané `interaction_id`/`should_log_decision`/`learning_eligible`
parametre (zhoda so 3 súrodeneckými executor funkciami); mintuje
`_recipe_decision_id` LEN keď `recipe_shopping_plan is not None` (V2.8
štruktúrovaná cesta — legacy `recipe_shopping_core_products()` fallback
zostáva čestne `None`, nemá dôkazovú štruktúru); volá
`log_recommendation_decision()` identicky ako basket_completion.

**Follow-up vetva** (`recipe_followup_result`): decision_id sa mintuje
LEN pre `RECIPE_FOLLOWUP_PLAN_UPDATE` kind s neprázdnym `.plan` — NIE pre
`RECIPE_FOLLOWUP_INGREDIENT` (prehliadanie kandidátov pre jednu
ingredienciu nie je systémové odporúčanie) ani `RECIPE_FOLLOWUP_SELECTED`
(echo zákazníkovho vlastného explicitného výberu, nie odporúčanie
systému — priradenie decision_id by falošne implikovalo, že systém
"rozhodol", že tento produkt je najlepší, keď v skutočnosti zákazník
sám povedal ktorý chce).

`app/main.py` (+4 riadky, LF región): import
`RECIPE_FOLLOWUP_PLAN_UPDATE as _RF_PLAN_UPDATE`; `_execute_recipe()`
volanie teraz posiela `interaction_id`/`should_log_decision`/
`learning_eligible` (identický vzor ako use_case_advice/basket_completion
volania o pár riadkov vyššie).

`app/widget.js` (+1/-1, CRLF región): `decisionId` rezolúcia rozšírená o
`|| data.recipe_shopping_decision_id` — jedna dodatočná `||` klauzula,
zachováva existujúci reťazec aj `null` terminátor.

## 15. recipe_shopping — finálny stav

`DECISION_OBSERVABILITY_LIVE`.

## 16. PART C — replacement_products audit

`app.main.alternative_products_for_subject()` je **3-vrstvová fallback
kaskáda** (kurátorské `knowledge.json["Alternatives"]` → hardkódovaný
`REPLACEMENT_PRODUCT_QUERIES` zoznam → rovnaká-kategória fallback
vyhľadávanie) — vracia PRVÚ neprázdnu vrstvu, **bez per-kandidát
evidence/confidence** v návratovej hodnote. Toto NIE JE vyhodnotená
voľba medzi kandidátmi (na rozdiel od cross_sell/recipe_shopping) — je
to "ktorá stratégia vyhľadávania prvá zabrala."

**REPLACEMENT_QUALITY_DATA_LIMITATION** (potvrdené priamym testom):
"vegan" obmedzenie sa **deterministicky nefiltruje** — dopyt "náhrada za
rybiu omáčku vegan" prechádza rovnakou kaskádou ako bez slova "vegan",
bez akéhokoľvek dietetického filtra.

## 17. replacement_products — vyhodnotenie modelov

| Model | Verdikt |
|---|---|
| RP-A (candidate-set decision, žiadny víťaz) | Bezpečný v princípe, ale pozri §18 |
| RP-B (jeden vybraný náhradník) | Zamietnuté — žiadny evaluovaný výber neexistuje, fabrikovalo by "víťaza" |
| RP-C (decision per typ náhrady) | Zamietnuté — žiadna rola/typ štruktúra existuje |
| **RP-D** (žiadny decision objekt) | **ZVOLENÉ** |

## 18. replacement_products — zvolený model

**Žiadny.** Aj keď RP-A (candidate-set bez víťaza) by teoreticky bol
čestný, jeho implementácia by vyžadovala zásah do **veľkého zdieľaného
cascade bloku** v `app/main.py` (rovnaký kód, ktorý obsluhuje aj
`related_products`/`article_products`/ordinary search), nie izolovanú
executor funkciu ako comparison/use_case/basket/recipe — riziko
regresie mnohých golden/canary prípadov a **rt0013's uzavretého
routingu** prevažuje nad prínosom pre mechanizmus bez dôkazovej
štruktúry. Section 26's "human-semantic blocker" otázky ("má sa prvá
kurátorská alternatíva považovať za preferovanú?", "má sa vegan
predpokladať z názvu?") tiež zostávajú nezodpovedané — nie som
oprávnený hádať.

## 19. replacement_products — brána

**GATE A — STRUCTURAL_GAP_ACCEPTED** (nie striktne
`REPLACEMENT_DECISION_REQUIRES_HUMAN_SEMANTIC_DECISION`, keďže dôvod nie
je len nejednoznačnosť sémantiky, ale aj architektonické riziko —
zdokumentované ako kombinovaný dôvod).

## 20. replacement_products — implementácia

Žiadna. `app/main.py`'s replacement cascade nedotknutý.

## 21. replacement_products — finálny stav

`STRUCTURAL_GAP_ACCEPTED` (`DATA_QUALITY_AND_ARCHITECTURE_RISK`).

## 22. rt0013 status

**Znovu-overené, NEOTVORENÉ.** "náhrada za rybiu omáčku vegan" →
`replacement_products`, testom potvrdené nezmenené.

## 23. REPLACEMENT_QUALITY_DATA_LIMITATION

Zachovaná, zdokumentovaná testom
(`test_replacement_quality_data_limitation_vegan_not_deterministically_filtered`)
— nie "opravená" touto sprintou, čestne ponechaná ako známy limit.

## 24. interaction_id/result_set_id sémantika

Nezmenené — `interaction_id` vždy nový za `/chat`, `result_set_id`
stabilný cez continuation (V2.15e.1 nedotknuté).

## 25. Nové decision_id polia

Len `recipe_shopping_decision_id` — additive, voliteľné, nikdy
fabrikované. Žiadny generický `decision_id` refaktoring (Section 32 —
"do not rush").

## 26. Durable decision logging

`log_recommendation_decision()` (V2.15d infra) znovu-použitá presne, bez
nového paralelného JSONL streamu.

## 27. Frontend korešpondencia

Jedna dodatočná `||` klauzula v existujúcej `decisionId` rezolúcii —
žiadny druhý korelačný mechanizmus.

## 28. Feedback korešpondencia

`recipe_shopping_decision_id` je teraz súčasťou tej istej `decisionId`
premennej, ktorú V2.15e.2's feedback `vote()` už používa — feedback na
recipe_to_products odpoveď teraz môže niesť legitímny
`recipe_shopping_decision_id`, bez akejkoľvek zmeny vo feedback kóde
samotnom.

## 29-34. Event semantics / execution context / privacy / performance

Nezmenené. Žiadne nové PII. `execution_context`/`learning_eligible`
zdedené presne rovnako ako comparison/use_case/basket. 0 nových LLM/
search volaní — čisto metadátová práca.

## 35-40. JS testy / Python testy / regresia

4 nové JS testy (static source-inspection, krížovo overené Python `re`).
30 nových Python testov (`tests/test_decision_observability_expansion_v2_15e_3.py`)
— charakterizácia napísaná PRED implementáciou (24/30 passed pred
zásahom, presne 6 recipe_shopping testov failed ako očakávané, potvrdilo
presnosť auditu). Po implementácii: 30/30. Pozri finálny report pre plnú
regresiu/V2.10/canary/audit výsledky.

## 41. Diff/byte-safety

`app/workflow_executor.py` (CRLF súbor, iný od main.py/widget.js mixed
konvencie) — `--stat` == `--ignore-space-at-eol --stat` presne, `--check`
čistý. `app/main.py` +4 riadky LF región, čisté. `app/widget.js` +1/-1
riadok, `--check` len na už-zdokumentovanom benígnom CR artefakte.

## 42. Learning/ranking freeze

`app/learning_lifecycle.py`, ranking súbory nedotknuté.
`AUTO_PROMOTION_ENABLED` nezmenené (`False`).

## 43. Per-capability finálna matica

| Capability | Decision objekt | decision_id | Durable log | Frontend korel. | Finálny stav |
|---|---|---|---|---|---|
| comparison | áno (V2.14) | áno | áno | áno | `DECISION_OBSERVABILITY_LIVE` |
| use_case_advice | áno (V2.14) | áno | áno | áno | `DECISION_OBSERVABILITY_LIVE` |
| basket_completion | áno (V2.14e) | áno | áno | áno | `DECISION_OBSERVABILITY_LIVE` |
| **recipe_shopping** | áno (V2.8, teraz logged) | **áno (nové)** | **áno (nové)** | **áno (nové)** | **`DECISION_OBSERVABILITY_LIVE`** |
| cross_sell | áno (V2.6) | nie | nie | nie (nikdy renderované) | `STRUCTURAL_GAP_ACCEPTED` |
| replacement_products | nie (raw cascade) | nie | nie | nie | `STRUCTURAL_GAP_ACCEPTED` |
| ordinary product_search | n/a | null (čestne) | n/a | n/a | `NOT_APPLICABLE` |

## 44. Globálny release status

**`DECISION_OBSERVABILITY_EXPANDED_WITH_LIMITATIONS`** — jedna z troch
kapacít (recipe_shopping) plne live, dve zostávajú vedome a
zdokumentovane `STRUCTURAL_GAP_ACCEPTED` z odlišných, evidence-backed
dôvodov (frontend rendering gap vs. data quality/architecture risk).

## 45. Zostávajúci štrukturálny dlh

cross_sell zostáva nekorelovateľný, kým sa nepridá frontend rendering
(mimo rozsahu observability sprinty). replacement_products zostáva bez
evidence štruktúry a bez dietetického filtrovania (`REPLACEMENT_QUALITY_DATA_LIMITATION`).

## 46. Empirical data status

Nové: `recipe_shopping_decision_id` korelovaný objem je k dátumu
nasadenia 0 (funkcia je nová).

## 47. NEXT_PROGRAM_PHASE

**`WAIT_FOR_EMPIRICAL_DATA`.**

## 48. WAIT_FOR_EMPIRICAL_DATA politika

Žiadne ďalšie observability architektúra sa nepridáva len preto, že by
sa dala merať. Systém teraz zbiera reálne CUSTOMER signály prirodzene.
Sledovanie len cez existujúce bezpečné read-only agregáty. Žiadne
syntetické CUSTOMER eventy, simulované konverzie, fabrikovaný feedback,
auto-training, auto-promotion.

## 49. V2.15f status

**NOT STARTED.** Môže byť zvážený len po samostatnom budúcom prompte,
ktorý sa pýta: koľko korelovaných rozhodnutí/feedbackov/klikov/
confirmed-cart eventov existuje per capability, aké selection/position
biasy zostávajú, je negatívny label stále nedostatočný, je empirický
objem zmysluplný.
