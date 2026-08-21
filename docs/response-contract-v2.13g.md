# Canonical `/chat` Response Contract (V2.13g)

Dátum: 2026-08-21. Nadväzuje na `docs/commerce-pipeline-v2.13f-a.md`
(nálezy #1-#3 v Sekcii 8 tam) — táto sprinta ich nezávisle overuje
priamo proti aktuálnemu kódu a OPRAVUJE ich, bez akejkoľvek zmeny
retrieval/ranking/routing/taxonomy logiky ani extrakcie commerce
pipeline (tá zostáva `ACCEPT_PARTIALLY_CLOSED`, pozri
`docs/commerce-pipeline-v2.13f-a.md`).

## 1. Rozsah

Táto sprinta harduje **verejný `/chat` response kontrakt**, konkrétne:

- 8 terminálnych `return` miest commerce matches-dispatch pipeline (`app/main.py`, riadky ~4936–5108 po tejto zmene).
- Klasifikáciu polí naprieč CELÝM `/chat` kontraktom (commerce pipeline + `app.workflow_executor`'s 9 handlerov + recipe stavový automat) ako referenčný kontext — **nie** zmenu týchto ostatných handlerov (mimo rozsahu, Section 2 zadania V2.13g).

## 2. Klasifikácia polí

| Pole | Klasifikácia | Dôkaz |
|---|---|---|
| `answer` | **REQUIRED_ALWAYS** | Prítomné v každom zo 17 skúmaných return miest (8 commerce + 9 executor) bez výnimky. |
| `products` | **REQUIRED_ALWAYS** | Rovnako, vždy prítomné (aj ako `[]`). |
| `intent` | **REQUIRED_ALWAYS** | Prítomné vo všetkých 9 `workflow_executor` handleroch (`grep "intent"` → 9/9) a po tejto oprave vo všetkých 8 commerce vetvách. |
| `memory` | **REQUIRED_ALWAYS** | Identický dôkaz ako `intent` — `public_user_memory_summary(updated_profile)` vo všetkých 9 executor handleroch, teraz aj vo všetkých 8 commerce vetvách. |
| `response_mode` | **REQUIRED_WHEN_APPLICABLE** (scoped na commerce pipeline) | LEN `execute_resultset_continuation()` z `app.workflow_executor` ho nastavuje (`"result_set_continuation"`) — ostatných 8 executor handlerov (allergen/missing_composition/faq/recipe/reset/out_of_domain/category_discovery) ho **zámerne nemá** (nie je to defekt — tieto typy odpovedí nemajú "response composition mode" v zmysle result_set/fast/shopping_list/llm/fallback rozlíšenia, ktoré dáva zmysel len pre produktovo-vyhľadávaciu rodinu odpovedí). V rámci commerce pipeline samotnej je teraz **REQUIRED_ALWAYS** (viď nižšie). |
| `articles`, `cart_candidates`, `missing_ingredients`, `shopping_list`, `knowledge` | **REQUIRED_WHEN_APPLICABLE** | Prítomné, keď má vetva čo hlásiť (napr. 2 zero-match vetvy commerce pipeline legitímne nemajú `articles`/`cart_candidates` — nie je čo anotovať, keď `matches=[]` a `knowledge_matches={}` boli vyprázdnené skôr). Vynucovanie týchto polí na zero-match vetvách by bolo umelé, nie kontraktovo správne (Section 6 zadania: "Do NOT assume all fields should necessarily have identical semantic values"). |
| `workflow_id`, `workflow_confidence` | **OPTIONAL** | Len `structured_presentation`-vetva commerce pipeline a `RESULTSET_CONTINUATION` ich majú — analytický label, nie kontraktová nutnosť pre klienta. |
| `result_set_id`, `matching_total`, `displayed_count`, `has_more`, `answer_strategy`, `groups`, `cross_sell*` | **OPTIONAL** | Výhradne `structured_presentation`-vetva. |
| `warning` | **OPTIONAL** | Len 2 error-vetvy (transient error, generic exception). |
| `error`/`error_code` | **INTERNAL_ONLY / NEEXISTUJE** | `/chat` nikdy nevracia strojovo-čitateľný error kód zákazníkovi — chyby sa vždy tlmočia ako `answer` text + `warning` (Section 12 zadania: nezmeniť na fake success, ale ani nepridávať nový error-kód mechanizmus, ktorý zadanie nevyžaduje). |

## 3. Response_mode vocabulary (commerce pipeline, po V2.13g)

Existujúci slovník pred touto sprintou: `"result_set"`, `"fast"`,
`"shopping_list"` (+ `"result_set_continuation"` v `workflow_executor`,
mimo tejto pipeline). 4 z 8 commerce vetiev nemali žiadnu hodnotu.
Namiesto vymýšľania veľkého nového enumu (zadanie Section 10: "Do NOT
invent many new response modes... define exactly ONE clearly named
fallback unless repository evidence requires otherwise") — priamy dôkaz
(Section 25/26 nižšie) ukázal, že chýbajúce vetvy skladajú odpoveď
**3 skutočne odlišnými mechanizmami**, ktoré si zaslúžia odlíšenie pre
budúce monitorovanie (napr. vysoký podiel `"fallback"` signalizuje
OpenAI výpadky, vysoký podiel `"no_match"` signalizuje retrieval/
taxonomy medzery — `app.evaluation.conversation`'s `expected_response_mode`
assertion mechanizmus už dnes vie tieto hodnoty čítať):

| Nová hodnota | Vetvy | Mechanizmus |
|---|---|---|
| `"llm"` | OpenAI success (L5055-5065 pred, teraz +1 kľúč) | Odpoveď zložená živým OpenAI volaním — pôvodný, pred-V2.5 default mód, doteraz jediný bez vlastného mena. |
| `"fallback"` | no-OPENAI_API_KEY, OpenAI transient-error, generic exception | Rovnaká `fallback_answer(...)`/`product_advice_text`/`shopping_list_answer_text` kompozícia, bez LLM volania — 3 rôzne spúšťače, identický výstupný mechanizmus. |
| `"no_match"` | zero-match + recipe-answer, zero-match + generic ospravedlnenie | `not matches and not knowledge_matches` — commerce dispatch nenašiel nič; recipe-answer sub-vetva síce vráti text (cez `general_ai_recipe_answer()`), ale zo štruktúrovaného-vyhľadávacieho hľadiska je to rovnaký "nulový výsledok" stav ako jej sesterská vetva. |

Žiadna existujúca hodnota (`"result_set"`/`"fast"`/`"shopping_list"`)
nebola zmenená ani znovupoužitá pre nesúvisiaci prípad — 3 nové hodnoty
sú disjunktné od existujúcich aj medzi sebou.

## 4. Error-path sémantika (Section 12 zadania)

Obe opravené error-vetvy (transient error, generic exception) **zostávajú
error-vetvami** — nezmenené: `logger.warning`/`logger.error`,
`log_backend_error(...)`, `"warning"` text, HTTP 200 (nezmenené,
existujúce správanie — `/chat` nikdy nevracalo iný HTTP status kód pre
tieto prípady, to nie je táto sprinta zaviedla ani nezmenila), retry
logika (`@retry` dekorátor na `_call_openai_with_retry`, nezmenený).
Jediná zmena: teraz navyše hlásia `intent`/`memory`/`response_mode` —
**tie isté hodnoty**, aké by táto istá požiadavka dostala na
`"fallback"`-ceste bez chyby, nič nové sa nevymýšľa ani nezakrýva.

## 5. Implementácia (byte-safe, `app/main.py`)

6 terminálnych `return` blokov upravených (presné anchor-based
byte-safe nahradenie, `git diff --stat` vs `--ignore-space-at-eol
--stat` overené, žiadny neúmyselný celofilový posun):

1. Zero-match + recipe-answer (pôvodne riadok 4939): `+memory`, `+response_mode`.
2. Zero-match + generic ospravedlnenie (pôvodne 4940-4947): `+intent`, `+memory`, `+response_mode`.
3. No-`OPENAI_API_KEY` fallback (pôvodne 4980-4990): `+response_mode`.
4. OpenAI success (pôvodne 5055-5065): `+response_mode`.
5. OpenAI transient-error (pôvodne 5069-5082): `+intent`, `+memory`, `+response_mode`.
6. Generický exception (pôvodne 5086-5099): `+intent`, `+memory`, `+response_mode`.

Každá pridaná hodnota číta **už vypočítanú** lokálnu premennú (`intent`
z Fázy 4, `updated_profile` z Fázy 6 — obe bezpodmienečne vypočítané
PRED celým terminálnym fan-outom, `docs/commerce-pipeline-v2.13f-a.md`
Sekcia 5) — **žiadne nové volanie, žiadne nové routovanie, žiadne nové
LLM/search volanie, žiadne pretriedenie vedľajších efektov** (Section
8/9/24/25 zadania — priamo overené, pozri nižšie).

## 6. Frontend kompatibilita (Section 11 zadania)

`app/widget.js` konzumuje z `/chat` odpovede: `data.answer`,
`data.answered`, `data.products`, `data.recipes`, `data.articles`,
`data.intent` (len `===`/`!==` porovnanie s `"allergen_safety"`/
`"recipe"`, bezpečné aj pri `undefined`), `data.has_more`,
`data.cart_candidates`, `data.missing_ingredients`,
`data.shopping_list`. **`data.memory` a `data.response_mode` frontend
NIKDY nečíta** — priamo overené (`grep "data\.\w+" app/widget.js`,
žiadny výskyt). Znamená to, že pôvodné 2 nekonzistencie neboli
zákaznícky-viditeľný defekt (widget by sa nesprával inak s/bez týchto
polí) — sú to kontraktové medzery relevantné pre INÉ konzumenty:
`app.evaluation.conversation`'s `expected_response_mode` assertion
(priamo číta `response.get("response_mode")`), budúce admin/analytics
nástroje, a testovacia sada samotná. **`app/widget.js` sa touto
sprintou nemení** — backend-only oprava plne postačuje.

## 7. Vedľajšie efekty a poradie (Section 24/25 zadania)

Žiadny z 9 vedľajších efektov (`docs/commerce-pipeline-v2.13f-a.md`
Sekcia 5) sa nepresunul, nezdvojil ani nezmenil poradie — pridané
kľúče čítajú premenné vypočítané v NEZMENENOM poradí, výhradne v už
existujúcich `return` výrazoch (nie v novom kóde medzi vedľajšími
efektmi a `return`). Search/LLM call count: nezmenené — žiadna z 6
opravených vetiev získala nové volanie `hybrid_cached_search_products`/
`_build_structured_result_set`/`_call_openai_with_retry`/ekvivalent;
error-vetvy naďalej nevolajú OpenAI znova po zlyhaní (retry logika je
plne obsiahnutá v `_call_openai_with_retry()`'s `@retry` dekorátore,
nezmenená).

## 8. Execution context (Section 16 zadania)

`memory`/`intent` pridané do error-vetiev čítajú `updated_profile`
(z `update_user_memory()`, zavolané bezpodmienečne vo Fáze 6 — pred
akýmkoľvek OpenAI volaním) — **žiadna nová `log_question()`/analytics
emisia**, žiadna zmena `emit_customer_analytics` brány. `TestExecutionContextSuppressesCustomerAnalytics`-štýl testy
(`tests/test_execution_context.py`) zostávajú nedotknuté a naďalej
prechádzajú (Section 16/27 overenie nižšie).

## 9. Čo sa NEMENILO (Section 2 zadania, explicitne)

Retrieval, ranking, taxonomy, query semantics, product ordering,
recommendation logika, cross-sell logika, recipe logika, session
contextualization, `_routing_message()`/`contextual_message` sémantika,
personalizácia, `AUTO_PROMOTION` (`false`, nezmenené),
`app.workflow_executor`'s 9 handlerov (nedotknuté — mimo rozsahu),
`WorkflowResolver`/`TurnResolver`/`AdvisorEngine` (nedotknuté),
commerce pipeline **NEBOLA extrahovaná ani presunutá** — len jej
existujúcich 6 terminálnych `return` výrazov dostalo doplnené kľúče.

## 10. Permanentné regresné testy

- `tests/test_commerce_pipeline_v2_13f_a.py::TestTerminalReturnShapeConsistency` (predtým `TestTerminalReturnShapeInconsistency`) — 4 testy, teraz assertujú OPRAVENÝ kontrakt namiesto zamrazenia pôvodnej chyby, s explicitným docstring vysvetlením zmeny (Section 13 zadania).
- `tests/test_response_contract_v2_13g.py` (nový, dedikovaný súbor per Section 13 zadania — "only if a test logically does not belong in the existing characterization file") — 8-vetvová matica assertujúca REQUIRED_ALWAYS polia (`answer`, `products`, `intent`, `memory`, `response_mode`) naprieč všetkými 8 commerce terminálnymi vetvami, plus mandatórne error-path regresie (Section 14 zadania: no duplicate analytics, no duplicate session mutation, no duplicate search, no extra LLM call, execution context rules).
