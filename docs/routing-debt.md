# Routing Debt Register

Dátum: 2026-08-20. Vytvorené počas V2.13a (AdvisorEngine Application
Boundary sprint) zo 7 zlyhaní V2.10 golden suite pri commite `5f7303d`
(V2.12.4 HEAD). Toto NIE JE zoznam vecí opravených v V2.13a — V2.13a je
čisto architektonická extrakcia (aplikačná hranica), nulová zmena
routing/intent/retrieval sémantiky (Invariant #2). Tento register je
vstupný dôkazový základ pre V2.13b (TurnResolver + WorkflowResolver).

## Prečo tento dokument existuje

51/58 na V2.10 nie je len jedno číslo — každé zo 7 zlyhaní má inú
príčinu a inú relevanciu pre budúcu prácu. Zmiešanie "toto je routing
bug" s "toto je pravopisný nesúlad v testovacom datasete" by viedlo
V2.13b k riešeniu nesprávnych vecí. Tento register drží presnú,
overenú klasifikáciu.

## Register

| case_id | query | current_intent | current_workflow | expected_semantic_behavior | failure_class | root_cause | confidence | target_sprint | status |
|---|---|---|---|---|---|---|---|---|---|
| `regbug_rt0004` | "súvisiace produkty k sushi ryži" | `related_products` | `RELATED_PRODUCTS` | related/complementary products (nori, ryžový ocot, wasabi, nakladaný zázvor) | — | (opravené) — presný root cause bol JEDEN RIADOK PRED pôvodnou V2.13a hypotézou: `detect_special_product_subject()` (hrubší, substring-based detektor) vždy nastavil `special_subject="sushi_rice"` a `if special_subject: related_subject = None` (main.py, pred V2.13b) toto BEZPODMIENEČNE nulovalo `related_subject`, skôr než sa jemnejší V2.12.2 Bug A guard (`_has_recipe_shopping_language`) vôbec dostal ku slovu — ten sám osebe fungoval správne. Pozri `docs/workflow-precedence-before-v2.13b.md`. | HIGH | V2.13b | **FIXED_V2_13B** — `app.turn_resolver.resolve_action_target_signal()` + `app.workflow_resolver.resolve_workflow()`, kauzálne (workflow rozhodnutie priamo riadi, ktorá vetva sa vykoná, main.py `_related_products_forced`). V2.10: golden case teraz PREJDE. |
| `regbug_rt0010` | "sójová omáčka bez sóje" | `allergen_safety` | `ALLERGEN_SAFETY` | `allergen_safety` — 0 produktov + bezpečnostné upozornenie | — | (opravené) — `allergen_product_query()` už DÁVNEJŠIE korektne vracalo `""` ako zámerný "0 bezpečných produktov" signál pre `"bez soj"`/`"bez soja"`, ale pôvodná guard podmienka (`allergen_term and (allergen_product_query(...) or not detect_related_subject(...))`) traktovala prázdny string ako "nerozpoznané", takže zhoda s `detect_related_subject()` (aj keď nesúvisiaca s bezpečnosťou) blokovala celú allergen_safety vetvu. Pozri `docs/workflow-precedence-before-v2.13b.md`. | HIGH | V2.13b | **FIXED_V2_13B** — `app.turn_resolver.resolve_safety_signal()` + `app.workflow_resolver.resolve_workflow()`, SAFETY má najvyššiu precedenciu bezpodmienečne (Invariant #3). Generický fix — funguje pre AKÝKOĽVEK `allergen_term`, ktorý `detect_allergen_intent()` už rozpoznáva, nie hardcoded na túto jednu frázu. V2.10: golden case teraz PREJDE, `answered=True`, `products=[]`. |
| `regbug_rt0013` | "náhrada za rybiu omáčku vegan" | `replacement_products` | — | golden case očakáva `product_search`; systémové správanie (`replacement_products`) je architektonicky plausibilné pre doslovné "náhrada za X" | INTENT_ERROR | nejasné, či je chybný systém alebo golden case | — | — | **PENDING_SEMANTIC_PRODUCT_DECISION — HUMAN_REVIEW_REQUIRED** |
| `regbug_rt0002` | "potrebujem niečo bez lepku k sushi" | `product_search` | — | (zhoda s očakávaním) | RETRIEVAL_MISS | golden case očakáva anglický prepis `'sushi ryža'`, katalóg/produkty používajú slovenský `'Suši ryža'` | — | — | **CLOSED — evaluation/text normalization artifact, nie routing** |
| `regbug_rt0006` | "čo k červenej kari paste?" | `related_products` | — | (zhoda s očakávaním) | RETRIEVAL_MISS | golden case očakáva `'rybia omáčka'`, katalóg má `'Rybacia omáčka'` (iný gramatický tvar) — produkt je fakticky prítomný | — | — | **CLOSED — lexical/evaluation wording mismatch, nie routing** |
| `regbug_rt0022` | "potrebujem recept na kimchi" | `recipe` | `RECIPE_SHOPPING` | (zhoda s očakávaním, intent aj workflow správne) | GROUNDING_ERROR | AI-generovaný text neobsahuje presne očakávané slová `'kapustu'`/`'fermentovat'` | — | — | **CLOSED — generated-answer textual variance, nie routing** |
| `regbug_rt0024` | "ako môžem zaplatiť?" | `faq` | — | (zhoda s očakávaním, intent správny) | GROUNDING_ERROR | FAQ odpoveď neobsahuje presne slovo `'Dobierka'` | — | — | **CLOSED — generated-answer textual variance, nie routing** |

## V2.13b — mandátne prípady VYRIEŠENÉ (Invariant #4/#5 zo zadania V2.13a)

### A) `regbug_rt0004` — FIXED_V2_13B

```
"súvisiace produkty k sushi ryži"
Workflow: RELATED_PRODUCTS (predtým: product_search/LEGACY_FALLBACK)
```

`app.turn_resolver.resolve_action_target_signal()` rozlišuje ACTION
("súvisiace produkty" — explicitná companion-jazyk fráza, znovupoužíva
existujúci `RECIPE_SHOPPING_LANGUAGE_MARKERS`) od TARGET (`related_subject
= "sushi"`) — akcia teraz kauzálne prebíja hrubší `special_subject`
substring match. Overené naživo aj testom
(`tests/test_advisor_engine.py::TestCharacterization_rt0004_FIXED_ROUTING_REGRESSION`,
`tests/test_routing_regressions.py::TestRelatedProductsGenericAcrossAnchors`
— funguje generický na viacerých anchoroch, nie len sushi ryža).

### B) `regbug_rt0010` — FIXED_V2_13B

```
"sójová omáčka bez sóje"
Workflow: ALLERGEN_SAFETY (predtým: product_search/PRODUCT_LOOKUP)
```

`app.turn_resolver.resolve_safety_signal()` + `app.workflow_resolver`'s
SAFETY-vždy-najvyššia-precedencia (Invariant #3) — funguje pre AKÝKOĽVEK
`allergen_term`, ktorý `detect_allergen_intent()` (existujúci, dôkladne
odladený detektor) rozpozná, nie hardcoded na túto konkrétnu frázu.
Overené: `tests/test_advisor_engine.py::TestCharacterization_rt0010_FIXED_SAFETY_ROUTING_REGRESSION`,
`tests/test_turn_resolver.py`, `tests/test_workflow_resolver.py`.

**V2.10 dopad**: 51/58 → **53/58**, 0 critical failures (predtým 1:
`regbug_rt0010`). Zvyšných 5 zlyhaní nezmenených, presne tie isté ako
pred V2.13b (rt0002/rt0006 lexikálny nesúlad, rt0013 human review, rt0022/
rt0024 LLM textová variancia) — nulový neočakávaný routing drift (Section
143 zadania).

### C) `regbug_rt0011` — FIXED_V2_13B_1

```
"mám rád nepálivé jedlo, čo odporúčaš?" (opakovaný v tej istej session)
Workflow: PRODUCT_SEARCH (predtým, pri opakovaní: RELATED_PRODUCTS)
```

**root_cause**: `SESSION_CONTEXT_CONTAMINATION`, nie primárny
WorkflowResolver defekt — `resolve_action_target_signal()` samotný
pracoval korektne nad tým, čo dostal; problém bol, že
`contextualize_message()` mu bezpodmienečne (mimo `is_context_followup()`
brány) dodával stale `diet_terms` z pamäte, ktoré manufacturovali
`special_subject`/`related_subject` konflikt neexistujúci v aktuálnom
ťahu. Objavené cez `app.ranking_optimizer.evaluate_profile()`'s
session_id kolíziu (dva nezávislé eval behy s rovnakým `session_id` na
tej istej pozícii golden zoznamu). Detail root cause + plný audit:
`docs/contextualization-risk-v2.13b.1.md`.

**fix**: nová `app.main._routing_message()` — rovnaký
`is_context_followup()`-gated subject-carryover ako
`contextualize_message()`, nikdy diet_terms. Nahradila
`contextual_message` na 9 routing-kritických miestach
(`special_subject`, `related_subject`, `already_have_subject`,
`replacement_subject`, `article_product_subject`,
`resolve_action_target_signal()` a jeho 4 refining guardy). Generický
fix (nie hardcoded na "jemne"/"pikantne" ani na túto jednu frázu) —
overené s odlišným diet termom v `tests/test_session_contamination_v2_13b_1.py`.
`contextualize_message()` sama zostáva nezmenená (naďalej kŕmi retrieval/
knowledge/answer composition, kde diet-term kontext je zámerná, testovaná
hodnota — `test_diet_preference_is_remembered`).

## Čo tento dokument NIE JE

- Nie je zoznam vecí opravených v V2.13a (V2.13a routing nemení vôbec).
- Nie je dôkaz, že systém je "rozbitý" — 51/58 s presne diagnostikovanými
  2 skutočnými routing medzerami (z 25 celkových critical golden
  prípadov) je solídny stav pre produkčný systém tejto veľkosti.
- Nie je konečný zoznam všetkých routing medzier — len tých, ktoré V2.10
  golden suite momentálne meria. Produkčný monitoring (V2.12.4
  `search_quality.jsonl`) môže časom odhaliť ďalšie, akonáhle sa
  nahromadí dostatočný objem.

## Ako pridávať nové záznamy

Pri objavení novej routing medzery (manuálnym testovaním, produkčným
monitoringom, alebo novým golden case zlyhaním): pridaj riadok do
tabuľky vyššie s rovnakou disciplínou — `root_cause` musí byť overený
priamym testom (`parse_structured_query`, `select_workflow`, atď.), nie
odhad. Nemiešaj `evaluation wording mismatch` s `workflow architecture
defect` — sú to odlišné triedy problémov vyžadujúce odlišnú akciu.
