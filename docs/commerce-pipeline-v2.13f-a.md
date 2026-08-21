# Commerce matches-dispatch pipeline — charakterizácia (V2.13f-A)

Dátum: 2026-08-21. **Toto zadanie je CHARAKTERIZÁCIA ONLY** — žiadny
riadok vykonávacej logiky v `app/main.py` nebol touto sprintou zmenený,
presunutý ani refaktorovaný. Jediné zmeny tejto sprinty: tento
dokument, `tests/test_commerce_pipeline_v2_13f_a.py` (13 nových
charakterizačných testov) a bežné sprint-dokumentačné aktualizácie
zdieľaných súborov (`docs/workflow-architecture.md`,
`docs/advisor-engine.md`, `docs/routing-debt.md`,
`docs/roadmap-features.md`).

Nadväzuje na `docs/workflow-migration-v2.13d.md` (prvý nález "~30+
vzájomne závislých premenných", nájdený PRI priamom pokuse o extrakciu)
a `docs/recipe-state-machine-v2.13e.md` (posledná úspešná extrakcia —
recipe stavový automat, teraz jediný ZOSTÁVAJÚCI legacy blok je presne
táto pipeline). Cieľ tejto sprinty: buď formálne dokázať, že extrakcia
je teraz bezpečná (`GO_TO_V2_13F_B`), alebo formálne a s dôkazmi
zdôvodniť, že architektúra zostáva `ACCEPT_PARTIALLY_CLOSED` — čo je
podľa zadania **platný, úspešný výsledok**, nie zlyhanie. Dôkazné
bremeno je na extrakcii, nie na zotrvaní.

## 1. Presné hranice (post-V2.13e riadkové čísla)

`app/main.py`, funkcia `_chat_impl()` (riadky 4161–5132):

- **Vstup do pipeline**: riadok 4513, `already_have_subject = detect_already_have_subject(routing_message)`.
- **Posledný `return` vnútri pipeline**: riadok 5099 (generický `except Exception` handler).
- **Koniec `_chat_impl()`**: riadok 5132 (pomocná funkcia `_compute_answered()` nasleduje na 5102, samostatná, zdieľaná aj inými volajúcimi — nie súčasť tejto pipeline).
- `_chat_internal()` začína na riadku 5133 — mimo rozsahu tejto charakterizácie.

Táto pipeline je **jediná zostávajúca `legacy_primary_execution_branch_count` jednotka** (`legacy_primary_execution_branch_count = 1`, nezmenené touto sprintou).

## 2. Inventár fáz (stage inventory)

| # | Fáza | Riadky | Popis |
|---|------|--------|-------|
| 1 | Detekcia subjektov + kolízne strážcovia | 4513–4653 | `already_have_subject`, `special_subject`, `replacement_subject`, `related_subject`, `_action_target_resolution` (TurnResolver/WorkflowResolver), 6 nezávislých guard-clause blokov ktoré prepisujú `related_subject`/`special_subject` na základe značiek v texte AJ na základe `memory`-stavu (`_active_use_case`, V2.9 sushi-narrowing) |
| 2 | Matches-dispatch (9-cestný `elif` reťazec) | 4654–4760 | Presne JEDNA z 9 vetiev priradí `matches` (a voliteľne `structured_presentation` cez walrus na riadku 4688 alebo 4741) |
| 3 | Post-dispatch normalizácia | 4761–4784 | `personalize_products`, `_track_presentation`, shopping-core prepisy (sushi/tom_yum/kimchi_ramen/generic), `sushi_rice` re-sort |
| 4 | Odvodenie `intent` | 4785–4809 | 6-úrovňový vnorený ternárny výraz nad `_related_products_forced`/`article_product_subject`/`replacement_subject`/`product_advice_context`/`special_subject`/`related_subject`/`cross_sell_matches` |
| 5 | Anotácia + cart/shopping-list výpočet | 4810–4837 | `annotate_recommendations`, `cart_candidates_for_response`, `missing_ingredients_for_subject`, `shopping_list_for_response`, `shopping_list_answer` |
| 6 | Perzistencia pamäte + analytika (bezpodmienečná) | 4838–4846 | `update_session_memory`, `update_user_memory`, `build_customer_intent`, `log_question` — **vykoná sa PRESNE RAZ, PRED rozhodnutím, ktorá z terminálnych vetiev nižšie vráti odpoveď** |
| 7 | 5-cestný terminálny fan-out | 4848–5099 | `structured_presentation` vetva (result_set) → zero-match fallback → fast-chat vetva → shopping-list vetva → OpenAI vetva (3 pod-vetvy: no-client / success / transient-error / generic-exception) |

## 3. Control-flow graf (textový)

```
[Fáza 1: signály + guardy] (vždy vykonané, môže mutovať `memory` cez
   _set_active_use_case/_clear_use_case_state PRED dispatchom)
        │
        ▼
[Fáza 2: 9-way elif dispatch] ── presne jedna vetva nastaví `matches`
   ├─ _related_products_forced            → related_products_for_subject
   ├─ already_have_subject                → complement_products_for_subject
   ├─ special_subject∈{rice bundle} + structured OK (walrus) → _format_result_set_products
   ├─ special_subject                     → special_products_for_subject
   ├─ replacement_subject                 → alternative_products_for_subject
   ├─ article_product_subject             → article_products_for_subject
   ├─ cross_sell_matches                  → (už vypočítané v Fáze 1)
   ├─ related_subject                     → related_products_for_subject
   └─ else                                → structured retrieval ALEBO hybrid_cached_search_products
        │
        ▼
[Fáza 3: normalizácia] → [Fáza 4: intent] → [Fáza 5: cart/shopping] → [Fáza 6: perzistencia+log, bezpodmienečné]
        │
        ▼
[Fáza 7: 5-way terminálny fan-out, PRESNE JEDNA vetva vráti]
   ├─ if structured_presentation is not None:              return (result_set shape, +12 polí navyše)
   ├─ if not matches and not knowledge_matches and not needs_knowledge: re-search, potom ↓
   ├─ if not matches and not knowledge_matches:             return (recipe alebo generic apology)
   ├─ if should_use_fast_chat_answer(...):                  return (response_mode="fast")
   ├─ if shopping_list_answer_text:                         return (response_mode="shopping_list")
   ├─ if not client (no OPENAI_API_KEY):                    return (BEZ response_mode)
   └─ try OpenAI call:
        ├─ success:                                          return (BEZ response_mode)
        ├─ RateLimitError/APITimeoutError/APIConnectionError: return (BEZ memory, BEZ intent) ← NÁLEZ
        └─ generic Exception:                                 return (BEZ memory, BEZ intent) ← NÁLEZ
```

Dispatch vetvy vo Fáze 2 sú **vzájomne sa vylučujúce zo samotnej
konštrukcie** (`elif` reťazec) — dôkaz nevyžaduje samostatnú analýzu
podmienok ako pri V2.13e (kde dve NEZÁVISLÉ `if` vetvy museli byť
dokázané disjunktné). Terminálny fan-out vo Fáze 7 je tiež vzájomne sa
vylučujúci (postupné `if`/`return`), ale je **hlboko závislý na
premenných vypočítaných vo Fázach 1–6**, nie na jednoduchom
prepínacom signáli.

## 4. Dátovo-závislostný graf — tabuľka premenných

Priame overenie enumeráciou (nie odhad): tento blok obsahuje **34
lokálnych premenných** vypočítaných vo Fázach 1–6, z ktorých **31 je
čítaných aspoň v jednej vetve Fázy 7** (fan-in do terminálneho
rozhodnutia). Vzorka s najvyšším fan-outom:

| Premenná | Vypočítaná | Čítaná na (počet miest) |
|---|---|---|
| `matches` | 1× (dispatch) | 3, 4, 5, 6, **7× vo Fáze 7** (každá vetva vracia `"products": matches`) + `products_context()`/`collect_allowed_urls/prices` v OpenAI vetve |
| `intent` | 1× (Fáza 4) | Fáza 5 (3×), Fáza 6 (2×), **6× vo Fáze 7** |
| `special_subject`/`replacement_subject`/`related_subject`/`article_product_subject`/`already_have_subject` | Fáza 1 (s viacnásobným prepisom `related_subject`/`special_subject` v rámci Fázy 1 samotnej) | dispatch (Fáza 2), `intent`-odvodenie (Fáza 4), `annotate_recommendations`/`cart_candidates_for_response`/`missing_ingredients_for_subject` (Fáza 5), `build_customer_intent` (Fáza 6) |
| `structured_presentation` | walrus v Fáze 2 (2 možné miesta) | Fáza 3 (`is None` branch), Fáza 6 (`active_result_set_id`), **rozhoduje CELÚ prvú vetvu Fázy 7** |
| `cart_candidates`/`missing_ingredients`/`shopping_list` | Fáza 5, reťazovo závislé jedna na druhej | 7× vo Fáze 7 (okrem `structured_presentation`-vetvy, ktorá má vlastnú nezávislú kópiu `cart_candidates`/`missing_ingredients`/`shopping_list` výpočtu — pozri nižšie) |
| `fallback_related_subject` | Fáza 6 (1 riadok) | výhradne ako `fallback_answer(...)` argument — **5 volaní** naprieč 5 rôznymi vetvami Fázy 7 |
| `product_advice_text`/`shopping_list_answer_text` | Fáza 5 | **5 volaní** ako `answer` fallback naprieč Fázou 7 |
| `_cross_sell_decision`/`_cross_sell_products`/`_workflow_selection` | vypočítané VÝHRADNE vnútri `structured_presentation`-vetvy (4865, 4881) | žiadna iná vetva Fázy 7 tieto polia vôbec nemá — **potvrdený nález z V2.13d, nie predpoklad** |

Toto číslo (34, z toho 31 s reálnym fan-in do Fázy 7) **prevyšuje**
V2.13d-éra odhad "~30+" — priame prečítanie aktuálneho kódu potvrdzuje,
že previazanosť sa oproti V2.13d nezmenšila (očakávané: táto pipeline
nebola V2.13d/e nijako upravovaná).

## 5. Mapa vedľajších efektov (side-effect map)

| Efekt | Riadok | Podmienené? | Poradie voči terminálnemu rozhodnutiu |
|---|---|---|---|
| `_set_active_use_case(memory, "sushi")` | 4623 | áno (sushi-narrowing) | **PRED** dispatchom (Fáza 1) |
| `_clear_use_case_state(memory)` | 4631 | áno (hard switch) | **PRED** dispatchom (Fáza 1) |
| `memory["active_result_set_id"] = ...` | 4764 | vždy (hodnota `""` ak `structured_presentation is None`) | **PRED** terminálnym fan-outom |
| `_track_presentation(memory, ...)` | 4765 | vždy | **PRED** terminálnym fan-outom |
| `update_session_memory(...)` | 4839 | vždy | **PRED** terminálnym fan-outom |
| `update_user_memory(...)` | 4840 | vždy | **PRED** terminálnym fan-outom |
| `log_question(...)` | 4846 | vždy (interne no-op ak `not execution_context.emit_customer_analytics`, cez lokálny rebind na riadku 4199 — **rovnaký function-scope, teda BEZ V2.13d cross-module shadowing bugu**, priamo overené `TestSideEffectsFireExactlyOnceAcrossAllTerminalBranches`) | **PRED** terminálnym fan-outom |
| `logger.info("workflow_selected...")` | 4893 | len v `structured_presentation`-vetve | VNÚTRI konkrétnej terminálnej vetvy |
| `log_backend_error(...)` | 5068, 5085 | len v OpenAI transient-error / generic-exception vetve | VNÚTRI konkrétnej terminálnej vetvy |

**Zistenie**: 6 zo 9 vedľajších efektov sú bezpodmienečné a nastanú
skôr, než sa vôbec rozhodne, ktorá z 8 terminálnych vetiev vráti
odpoveď. To znamená, že prípadná extrakcia "len terminálneho fan-outu"
(Fáza 7 samostatne) by musela dostať `memory`/session-store ako
**už-zmutovaný** vstup, nie ako niečo, čo sama počíta — deliteľné, ale
nie bez starostlivého poradia parametrov. Priamo overené testom
(`TestSideEffectsFireExactlyOnceAcrossAllTerminalBranches`): `log_question`
sa vykoná presne raz aj keď terminálna vetva skončí OpenAI výnimkou.

## 6. Coupling classifikácia: **HIGH**

Kritériá pre HIGH (oproti MEDIUM u recipe stavového automatu v
V2.13e, ktorý mal len ~15 premenných a 2 čisté terminálne bloky):

- 34 lokálnych premenných, 31 s reálnym fan-in do finálneho rozhodnutia (Sekcia 4).
- 8 terminálnych `return` miest (Sekcia 3), nie 2 (V2.13e malo presne 2).
- Aspoň 3 polia (`_cross_sell_decision`, `_cross_sell_products`, `_workflow_selection`) vypočítané VÝHRADNE v jednej vetve, nedostupné v ostatných — asymetrická štruktúra dát, nie symetrická.
- 6 bezpodmienečných vedľajších efektov PRED terminálnym rozhodnutím (Sekcia 5) — v recipe stavovom automate boli vedľajšie efekty (memory update, log_question) vždy AŽ NA KONCI KAŽDÉHO z 2 terminálnych blokov, nikdy pred spoločným bodom vetvenia.

## 7. Money-path analýza

`matches`→`cart_candidates`→`shopping_list` je priamy tok k
zákazníckym nákupným odporúčaniam (nie doslovná platba, ale
komerčne-kritický: nesprávny produkt/cena v týchto poliach = reálna
strata dôvery/tržieb). Táto pipeline je **najviac premávaný** zo
všetkých zvyšných/predtým migrovaných jednotiek — spracúva KAŽDÝ plain
`product_search`, `replacement_products`, `article_products`,
`related_products`, `already_have`/complement, a cross-sell dopyt.
Naproti tomu V2.13c/d/e migrovali `RESULTSET_CONTINUATION`,
`ALLERGEN_SAFETY`, `missing_composition`, `faq`, `random_recipe`,
`reset`, `out_of_domain`, `category_discovery` a recipe stavový
automat — každý z nich je buď nízko-frekvenčný (reset, faq,
out_of_domain), alebo bezpečnostne-kritický ale úzko vymedzený
(allergen), alebo už dôkladne charakterizovaný stavový automat s
malým počtom premenných (recipe). **Blast radius chyby v tejto
pipeline je vyšší než súčet všetkých doteraz migrovaných jednotiek.**

## 8. Nové nálezy tejto sprinty (charakterizácia, NIE oprava)

Priamo potvrdené testom (`tests/test_commerce_pipeline_v2_13f_a.py::TestTerminalReturnShapeInconsistency`),
nie predpoklad z čítania kódu:

1. **`memory`/`intent` chýbajú v 2 z terminálnych vetiev**: `RateLimitError`/`APITimeoutError`/`APIConnectionError` (5066–5082) a generický `except Exception` (5083–5099) **nevracajú kľúče `"memory"` ani `"intent"`**, hoci každá INÁ terminálna vetva tejto istej funkcie ich vracia. Reprodukované pod DEFAULT nastavením (`FOODLAND_FAST_RESPONSES=true`) cez `replacement_subject` dopyt, ktorého odvodený `intent="replacement_products"` obchádza `should_use_fast_chat_answer()`'s allowlist — **toto je reálne dosiahnuteľné v produkcii**, nie hypotetické, kedykoľvek OpenAI zlyhá na tejto triede dopytov.
2. **`response_mode` chýba v 4 z terminálnych vetiev**: prítomné len v `structured_presentation` (`"result_set"`), fast (`"fast"`) a shopping-list (`"shopping_list"`) vetvách; chýba v no-client-fallback, OpenAI-success, a oboch exception vetvách.

**Toto zadanie tieto nálezy VEDOME NEOPRAVUJE** (Invariant #1–#3:
žiadna zmena vykonávacej logiky) — sú zdokumentované ako kandidát na
samostatnú, úzko vymedzenú, nízko-rizikovú budúcu opravu (pridanie 2–3
chýbajúcich kľúčov do 2 `return` dictov), **nezávislú od
extrakčného rozhodnutia nižšie**. Charakterizačné testy tento
SÚČASNÝ (nekonzistentný) tvar zamrazujú ako regression-net presne tak,
ako je — zmena vyžaduje vedomú aktualizáciu testov, nie tichý drift.

## 9. Zvážené extrakčné možnosti

**Možnosť A — celá pipeline ako jedna funkcia** (analogicky k
`execute_recipe()`): zamietnuté v V2.13d priamym pokusom (~30+
premenných v jednom byte-safe patchi bez priebežného testu) a znovu
potvrdené touto sprintou (34 premenných, 31 s fan-in, Sekcia 4).

**Možnosť B — rozdelenie na 3 funkcie podľa Sekcie 2/3
konceptuálnych švov** (`resolve_commerce_dispatch()` → `persist_and_annotate()`
→ `compose_commerce_response()`): existuje reálny konceptuálny
šev (Sekcia 2 fáza 1–2 vs. 3–6 vs. 7), ale rozhranie medzi krokmi by
muselo prenášať 15–20 z tých istých 34 premenných ako parametre/návratové
hodnoty — nezmenšuje riziko extrakcie, len ho rozdeľuje na 3 menšie,
stále netriviálne byte-safe patche, KAŽDÝ vyžadujúci vlastné
charakterizačné pokrytie porovnateľné s touto celou sprintou. Odhad:
3× rozsah V2.13e pri neistom bezpečnostnom prínose.

**Možnosť C — extrahovať LEN Fázu 7 (terminálny fan-out) samostatne**:
najlákavejšia (Fázy 1–6 by zostali nezmenené, len fan-out by sa presunul),
ale Sekcia 5 ukazuje, že 6 bezpodmienečných vedľajších efektov musí
prebehnúť PRED touto fázou a 2 z 8 vetiev majú už teraz nekonzistentný
tvar (Sekcia 8) — extrakcia by buď zmrazila túto nekonzistenciu do
API kontraktu novej funkcie (nežiaduce), alebo by ju musela opraviť
súbežne s presunom (porušuje Invariant #1: charakterizácia, nie
oprava, v TEJTO sprinte).

Žiadna zo zvážených možností nespĺňa latku, akú V2.13e dosiahlo pre
recipe stavový automat (2 terminálne bloky, ~15 premenných, dôkaz
vzájomnej výlučnosti dvoch susedných blokov postačujúci na bezpečné
presunutie v JEDNOM byte-safe patchi s okamžitým testom).

## 10. GO/STOP scorecard (14 kritérií)

| # | Kritérium | Verdikt | Dôkaz |
|---|---|---|---|
| 1 | Jeden dobre definovaný vstup/výstup? | **FAIL** | 8 terminálnych `return` miest (Sekcia 3), nie 1–2 ako pri predošlých extrakciách |
| 2 | Ohraničený, enumerovateľný lokálny stav? | **FAIL** | 34 premenných, 31 s fan-in (Sekcia 4) |
| 3 | Vedľajšie efekty izolované na hraniciach, nie preplietané v strede toku? | **FAIL** | 6 z 9 vedľajších efektov bezpodmienečné PRED terminálnym rozhodnutím (Sekcia 5) |
| 4 | Adekvátne charakterizačné testovacie pokrytie na zachytenie driftu? | **PASS** (po tejto sprinte) | 13 nových testov (`test_commerce_pipeline_v2_13f_a.py`) cielených presne na coupling body zistené v Sekciách 4/5/8 |
| 5 | Jednotný návratový kontrakt naprieč terminálnymi vetvami? | **FAIL** | 2 z 8 vetiev chýba `memory`/`intent`; `response_mode` chýba v 4 z 8 (Sekcia 8) |
| 6 | Jasná vzájomná výlučnosť medzi dispatch vetvami? | **PASS** | `elif` reťazec, výlučnosť z konštrukcie (Sekcia 3) |
| 7 | Žiadna cross-branch mutácia zdieľaných premenných PO dispatchi? | **PASS** | Post-dispatch kód (Fázy 3–6) len ČÍTA `special_subject`/`related_subject`/atď., nikdy ich nepreprisuje |
| 8 | Money-path pokrytý existujúcou regresnou sadou pred akoukoľvek zmenou? | **PARTIAL** | Široko pokryté existujúcou sadou (1306 testov) + touto sprintou, ale nie kombinatoricky vyčerpávajúco pre všetky 9 dispatch vetiev × 8 terminálnych vetiev |
| 9 | Extrakcia redukovateľná na jednu čistú funkciu (vstupy→výstupy, žiadny closure nad `_chat_impl` lokálami)? | **FAIL** | Vyžadovalo by ~20+ explicitných parametrov, zrkadlí V2.13d nález |
| 10 | Behaviorálna parita dokázateľná mechanickým/byte-safe presunom? | **FAIL** | Walrus-priradenie `structured_presentation` vo vnútri `elif` podmienky + 587 riadkov prepletenej kontroly toku robí čisté "extract block" nemožné bez reštrukturalizácie |
| 11 | Identifikovateľné, nezávisle testovateľné pod-koncepty vnútri jednotky? | **PARTIAL** | Konceptuálny šev existuje (Sekcia 2/9, Možnosť B), ale nezmenšuje riziko, len ho delí na 3 rovnako netriviálne kroky |
| 12 | Predošlé extrakčné pokusy / dôkaz z minulých šprintov? | **FAIL** | V2.13d priamy pokus explicitne odložený s dôkazom; V2.13e uspelo len na výrazne menšej, samostatnejšej jednotke |
| 13 | Rizikovo-vážená hodnota extrakcie (odomkne niečo, alebo je len kozmetická)? | **LOW hodnota** | Jediná zostávajúca `legacy_primary_execution_branch_count` jednotka je už plne zdokumentovaná a izolovaná; oba nájdené bugy (Sekcia 8) sú opraviteľné NEZÁVISLE od extrakcie, malým cieleným patchom |
| 14 | Blast radius chyby (zákaznícky viditeľný, tržbovo-relevantný)? | **HIGH** | Najviac premávaná zo všetkých doteraz charakterizovaných/migrovaných jednotiek (Sekcia 7) |

**Súhrn**: 6× FAIL, 4× PASS, 3× PARTIAL/LOW, 1× HIGH-risk. Väčšina
kritérií — vrátane všetkých, ktoré priamo merajú extrakčné riziko
(#1, #2, #3, #5, #9, #10, #12) — zlyháva. Kritériá, ktoré PASSujú
(#6, #7), potvrdzujú len že DISPATCH časť je čistá — nie že CELÁ
pipeline (vrátane terminálneho fan-outu, kde je previazanosť
najvyššia) je bezpečná na presun.

## 11. Rozhodnutie

# `ACCEPT_PARTIALLY_CLOSED`

Architektúra zostáva `WORKFLOW_ARCHITECTURE_PARTIALLY_CLOSED`:
`app.workflow_executor` vykonáva 9 z pôvodných ~11 legacy vetiev
(V2.13c: 2, V2.13d: +6, V2.13e: +1 [recipe stavový automat, ktorý sám
nahradil 2 pôvodné vetvy]). Táto commerce matches-dispatch pipeline
zostáva jediná, VEDOME ponechaná, dôkladne zdokumentovaná zostávajúca
jednotka — nie prehliadnutie, ale opakovane (V2.13c, V2.13d, teraz aj
formálne V2.13f-A so scorecard dôkazom) potvrdený, evidovaný stav
architektúry.

**Toto je platný, úspešný výsledok tejto sprinty**, presne ako zadanie
V2.13f-A explicitne predpokladá (`ACCEPT_PARTIALLY_CLOSED IS A VALID
SUCCESSFUL RESULT`). Dôkazné bremeno bolo na extrakcii; scorecard
(Sekcia 10) ho neuniesol na 7 z 14 kritérií vrátane všetkých kritérií
s najvyššou váhou pre bezpečnosť (#1/#2/#3/#5/#9/#10).

**Čo TÁTO sprinta napriek tomu dosiahla** (nie nulový výsledok):
- Formálny CFG/DFG/side-effect-map/coupling-dôkaz nahrádzajúci doterajší neformálny odhad "~30+ premenných" presným číslom (34, 31 s fan-in) a menovitým zoznamom.
- 13 nových charakterizačných testov, ktoré zamrazujú súčasné správanie tejto pipeline vrátane 2 novo-nájdených nekonzistencií tvaru odpovede — regresná sieť pre akúkoľvek BUDÚCU zmenu, aj keby to nebola extrakcia.
- Presná identifikácia 2 nezávislých, nízko-rizikových bugov (Sekcia 8) ako samostatný budúci kandidát, oddelený od extrakčnej otázky.
- Explicitné zdôvodnenie PREČO ani rozdelenie na menšie kroky (Možnosť B/C, Sekcia 9) neznižuje riziko dostatočne v rámci rozsahu jednej charakterizovanej sprinty.

Žiadna "malá kozmetická" extrakcia sa po tomto rozhodnutí
nevykonáva (zadanie explicitne zakazuje pokračovať v "upratovaní" po
STOP rozhodnutí).

## 12. Testy tejto sprinty

`tests/test_commerce_pipeline_v2_13f_a.py` (13 testov, všetky PASS,
priamo overujúce túto charakterizáciu, nie predpoklad):

- `TestStructuredPresentationBranchShape` (2) — result_set-only polia.
- `TestTerminalReturnShapeInconsistency` (4) — Sekcia 8 nálezy, priamo reprodukované cez OpenAI mock.
- `TestSideEffectsFireExactlyOnceAcrossAllTerminalBranches` (2) — `log_question` presne raz, aj cez OpenAI výnimku.
- `TestDispatchBranchesProduceDistinctSubjects` (3) — 9-way dispatch skutočne funguje na reálnom katalógu.
- `TestFastAndShoppingListBranchesIncludeMemoryAndIntent` (2) — kontrolná skupina k nálezu #1.
