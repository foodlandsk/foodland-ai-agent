# Recipe State Machine — V2.13e

Dátum: 2026-08-21. Plný audit recipe-relevantného kódu v `_chat_impl()`
(`app/main.py`, aktuálne riadky ~4363-4593), postavený na priamom
prečítaní kódu a priamom testovaní `chat()`, nie na predpoklade.

## Prečo "stavový automat", nie 5 nezávislých vetiev

Recipe logika pozostáva z 5 blokov, ktoré sa PRIAMO odvolávajú na
výsledok PREDCHÁDZAJÚCEHO bloku (`_recipe_followup_result`,
`recipe_subject`) — poradie a presné podmienky sú sémantika, nie
štylistická náhoda.

## Register blokov (v poradí výskytu)

| # | Riadky (V2.13d HEAD) | Blok | Podmienka | Vykoná | Vracia? |
|---|---|---|---|---|---|
| A | 4370-4381 | Setup: `_active_recipe_id_before`, `_recipe_followup_result` | `_active_recipe_id_before and not recipe_subject` | `_resolve_recipe_followup()`, prípadne `_clear_recipe_state(memory)` (side effect, ak followup zlyhal) | NIE — len pripraví stav pre B/C/D/E |
| B | 4389-4420 | Ordinálna referencia ("ten druhý") | `_recipe_followup_result is None and not recipe_subject and len(tokenize)<=4 and _mentions_ordinal_reference(...)` | `_resolve_ordinal_reference()` | ÁNO, ak `_ordinal_product_id` alebo `_ordinal_needs_clarification` |
| C | 4431-4448 | Osirelý follow-up ("čo ešte potrebujem?" bez aktívneho kontextu) | `_recipe_followup_result is None and not recipe_subject and (_looks_like_recipe_followup(...) or price_direction bez aktívneho ResultSetu)` | clarifikačná odpoveď | ÁNO, vždy keď podmienka platí |
| D | 4450-4558 | Hlavný `recipe_subject` blok (V2.8 recipe graph) | `recipe_subject` truthy | `recipe_results`, `recipe_related_product_subject`, `_build_recipe_shopping_plan`, `_set_active_recipe` (side effect) | ÁNO, vždy keď `recipe_subject` truthy |
| E | 4560-4593 | Recipe follow-up výsledok | `_recipe_followup_result is not None` | formátovanie `_recipe_followup_result` (3 druhy: `_RF_INGREDIENT`, `_RF_SELECTED`, `.plan`) | ÁNO, vždy keď `_recipe_followup_result is not None` |

## Kľúčové zistenie: B a C NIE SÚ recipe-špecifické

Napriek tomu, že sedia MEDZI recipe-followup výpočtom (A) a recipe
vykonaním (D/E), bloky B a C sú VŠEOBECNÉ session-continuity
clarifikačné vzory (ordinálna referencia na AKÝKOĽVEK naposledy
zobrazený zoznam, nie len recept; "niečo lacnejšie" bez aktívneho
ResultSetu) — recipe stav používajú LEN ako súčasť GATE podmienky
(aby sa vyhli dvojitému spracovaniu, keď `_recipe_followup_result`
alebo `recipe_subject` už turn spracovali). Toto ich klasifikuje ako
**SESSION_CONTINUATION_FALLBACK**, nie **RECIPE_EXECUTION**.

## Dôkaz vzájomnej výlučnosti B/C vs D/E (základ bezpečnej extrakcie)

- B aj C vyžadujú `_recipe_followup_result is None AND not recipe_subject`.
- D vyžaduje `recipe_subject` truthy — **vzájomne vylučujúce sa** s B/C's `not recipe_subject`.
- E vyžaduje `_recipe_followup_result is not None` — **vzájomne vylučujúce sa** s B/C's `_recipe_followup_result is None`.

Pre daný ťah môže platiť **najviac JEDNA** z {B, C, D, E}. Overené aj
priamym čítaním podmienok B a C — obe vyhodnocujú len READ-ONLY
detektory (`_mentions_ordinal_reference`, `_resolve_ordinal_reference`,
`_looks_like_recipe_followup`, `_detect_price_direction`) bez
vedľajších efektov na `memory`, takže PORADIE vyhodnotenia B/C vs D/E
nemá žiadny pozorovateľný vplyv na výsledok — presunutie D+E PRED B+C
(namiesto MEDZI A a B) je **behaviorálne identické**, keďže žiadny
ťah nemôže spĺňať podmienky oboch skupín naraz.

**Dôsledok pre extrakciu**: D+E môžu byť bezpečne extrahované do
JEDNEJ funkcie volanej HNEĎ PO bloku A, s B/C ponechanými presne na
mieste (nezmenené, stále v `_chat_impl()`) — bez zmeny pozorovateľného
správania.

## Dôkaz, že D/E sú skutočne terminálne

Žiadny kód PO bloku E (celá zvyšná commerce cascade, `already_have_subject`
cez finálny `return`) neodkazuje na `recipe_subject`,
`_recipe_followup_result` ani `_active_recipe_id_before` (overené `grep`
naprieč celým zvyškom `_chat_impl()`). Po E sú tieto premenné mŕtve —
potvrdzuje, že D+E sú skutočne posledné dva miesta, kde sa "recipe"
môže rozhodnúť o výsledku tohto ťahu.

## Skutočné stavy (odvodené z kódu, nie vynútené)

| Stav | Ako sa doň vstupuje | Čo produkuje |
|---|---|---|
| `NO_RECIPE_CONTEXT` | žiadny `_active_recipe_id_before`, žiadny `recipe_subject` | fallthrough na B/C/commerce |
| `RECIPE_FOLLOWUP_RESOLUTION_ATTEMPTED` | `_active_recipe_id_before` existuje, `recipe_subject` nie | Blok A volá `_resolve_recipe_followup()` |
| `RECIPE_FOLLOWUP_INGREDIENT` | `_recipe_followup_result.kind == _RF_INGREDIENT` | kandidátne produkty pre konkrétnu ingredienciu (Blok E) |
| `RECIPE_FOLLOWUP_SELECTED` | `_recipe_followup_result.kind == _RF_SELECTED` | jeden vybraný produkt (Blok E) |
| `RECIPE_FOLLOWUP_REMAINING_PLAN` | `_recipe_followup_result.plan is not None` | zvyšné dostupné ingrediencie z plánu (Blok E) |
| `RECIPE_DISCOVERY` | `recipe_subject` truthy, žiadny V2.8 plán (`recipe_shopping_plan is None`) | recepty + `general_ai_recipe_answer`/`recipe_answer` (Blok D) |
| `RECIPE_SHOPPING_ACTIVE` | `recipe_subject` truthy, V2.8 plán zostavený (`recipe_shopping_plan is not None`) | `_set_active_recipe(memory, ...)` — TOTO je JEDINÝ bod, kde sa recept stáva "aktívnym" pre budúce ťahy |
| `HARD_TOPIC_SWITCH` (implicitný) | `_resolve_recipe_followup()` vráti `None` | `_clear_recipe_state(memory)` (Blok A) |

**Kľúčové zistenie**: `active_recipe` sa nastavuje LEN keď sa skutočne
zostaví V2.8 `recipe_shopping_plan` (Section 16 V2.9 zadania, komentár
v kóde) — samotné "chcem robiť Pad Thai" bez nákupného úmyslu
(`wants_recipe_products()` vracia `False`) NEnastaví aktívny recept,
takže nasledujúci ťah nemá k čomu nadviazať. Priamo overené (Section
Characterization nižšie).

## Presné vstupy/výstupy blokov D a E (extrakčná hranica)

**Vstupy** (z `_chat_impl()`'s lokálneho scope): `recipe_subject`,
`_recipe_followup_result`, `chat_request`, `contextual_message`,
`knowledge`, `knowledge_matches`, `knowledge_sections`, `articles`,
`user_profile`, `products`, `recipe_graph_index`,
`product_taxonomy_index`, `normalized_product_index`, `memory`,
`memory_key`, `profile_key`, `client_key`, `session_id`,
`query_language`, `execution_context.emit_customer_analytics` (V2.13d
lekcia — `log_question` lokálne tienenie neprežije presun cez modul).

**Výstupy**: kompletný `/chat` response dict (`WorkflowResult`), presne
tak ako predtým — žiadna zmena kontraktu.

**Vedľajšie efekty** (presne raz, nezmenené): `update_session_memory`,
`update_user_memory`, `_set_active_recipe` (len Blok D, len keď je plán
zostavený), `log_question` (gated).

## Precedencia (nezmenená, len re-sekvenovaná bez zmeny výsledku)

```
ResultSet continuation (V2.13c executor)
        ↓ nie
Allergen safety (V2.13b/V2.13c executor)
        ↓ nie
[6 V2.13d migrovaných vetiev: missing_composition/faq/random_recipe/reset/out_of_domain/category_discovery]
        ↓ nie
Blok A: recipe-followup setup (nezmenené miesto)
        ↓
NOVÉ: execute_recipe(recipe_subject, _recipe_followup_result, ...) — Blok D+E ako JEDNA funkcia
        ↓ vráti None
Blok B: ordinálna referencia (nezmenené miesto, nezmenená logika)
        ↓ nie
Blok C: osirelý follow-up (nezmenené miesto, nezmenená logika)
        ↓ nie
commerce matches-dispatch cascade (nezmenené, V2.13f-A kandidát)
```

## Známy zvyškový dlh (nezmenené, mimo scope V2.13e)

- `recipe_graph_index`/`recipe_shopping` moduly samotné (V2.8) — nezmenené, extrakcia sa ich logiky nedotýka.
- Commerce matches-dispatch cascade (replacement/article/cross-sell/plain search) — explicitne MIMO scope tohto sprintu (Section 54 zadania).
- `article_product_subject`/`is_article_info_intent` — súčasť commerce cascade, nie recipe.
