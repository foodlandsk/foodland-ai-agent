# Session Context Model — V2.13b.1

Dátum: 2026-08-20.

Popisuje, ako `_chat_impl()` (`app/main.py`) rozlišuje medzi tým, čo
zákazník napísal TERAZ, a tým, čo si systém pamätá zo session — po
V2.13b.1's oprave `regbug_rt0011`'s triedy chyby (`docs/contextualization-risk-v2.13b.1.md`).

## Dve textové reprezentácie jedného ťahu

```
chat_request.message                    <- SUROVÁ, nikdy nemenená
        │
        ├──► contextual_message = contextualize_message(message, memory)
        │     (subject/product-title carry-over PRI is_context_followup(),
        │      + diet_terms VŽDY)
        │     → retrieval query text, knowledge search, recipe_subject,
        │       cross_sell, answer composition
        │
        └──► routing_message = _routing_message(message, memory)
              (rovnaký subject/product-title carry-over PRI
               is_context_followup(), NIKDY diet_terms)
              → special_subject, related_subject, already_have_subject,
                replacement_subject, article_product_subject,
                TurnResolver's resolve_action_target_signal()
```

`chat_request.message` samotná sa **nikdy nemutuje** — obe odvodené
hodnoty sú nové stringy, pôvodná zostáva nedotknutá a je presne to, čo
sa posiela do OpenAI promptu (`_call_openai_with_retry`) ako "Otázka
zákazníka" — zákazník nikdy neuvidí ani LLM nedostane vlastné slová
"prepísané" session pamäťou.

## Prečo dve, nie jedna štruktúrovaná trieda

Zvažovaná plná `SessionContext`/`ContextMergePolicy`/`TurnAnalysis`
architektúra s explicitnými `provenance` enumami bola po audite
zamietnutá ako neprimeraná preukázanému riziku — pozri
`docs/contextualization-risk-v2.13b.1.md`, sekcia 5. Dve jasne pomenované
stringové hodnoty s odlišným kontraktom (jedna smie niesť preferenčný
kontext pre vyhľadávanie/odpoveď, druhá nikdy nesmie niesť preferenčný
kontext pre routing) dosahujú rovnaký invariant s výrazne menším
zásahom do existujúceho, dôkladne testovaného kódu.

## `is_context_followup()` — jediná brána pre subject-carryover

```python
def is_context_followup(message: str) -> bool:
    normalized_message = normalize(message).strip()
    if len(tokenize(normalized_message)) <= 3 and any(
        marker in normalized_message
        for marker in ("k tomu", "co este", "este nieco", "dopln",
                        "hodia", "odporuc", "kostk", "a co", "a este")
    ):
        return True
    return normalized_message in {
        "co k tomu", "a co k tomu", "co este", "a este nieco",
        "co odporucas", "doplnky", "ake doplnky", "co chyba", "co mi chyba",
    }
```

Poznámka: `tokenize()` vracia MNOŽINU tokenov vrátane odvodených tvarov
(napr. "omacky" expanduje na `{omacka, omacky, omacku}`), takže
`len(...) <= 3` je prísnejšie, než sa na prvý pohľad zdá — zámerné
(úzka brána, nie náhoda), overené priamym testom pri návrhu opravy.

**Prečo toto štrukturálne zaručuje "explicit current turn wins"
(Invariant #3)**: gate vyžaduje buď (a) presnú zhodu z malej množiny
krátkych fráz, alebo (b) ≤3 tokenov OBSAHUJÚCICH follow-up marker.
Správa, ktorá pomenúva vlastný konkrétny produkt/tému, je takmer vždy
dlhšia alebo neobsahuje tieto markery — teda principiálne nemôže súčasne
spĺňať gate AJ niesť vlastný explicitný predmet. Preto nie je potrebná
samostatná "conflict resolution" logika pre tento carry-over — konflikt
je štrukturálne nemožný, nie len ošetrený.

## `diet_terms` — kam smie a kam nesmie

| Cieľ | `diet_terms` povolené? | Prečo |
|---|---|---|
| `contextual_message` (retrieval/knowledge/answer) | ÁNO, nezmenené | žiadny preukázaný routing dôsledok; test `test_diet_preference_is_remembered` dokazuje zámernú hodnotu |
| `routing_message` (workflow-rozhodujúce detektory) | **NIE, nikdy** | preukázaný koreň `regbug_rt0011` + 2 skoršie sprinty rovnakej triedy |
| `user_profile["diet_terms"]` (personalizačné skóre, `app.main`) | ÁNO, samostatný mechanizmus | nikdy neprechádza cez `contextualize_message()`, nesúvisí s týmto sprintom |
| OpenAI prompt | NIE, priamo | `_call_openai_with_retry` dostáva `chat_request.message` (surové), nie `contextual_message`/`routing_message` — overené auditom, nezmenené |

## Trvalé (persistent) vs. dočasné (temporary) polia v `memory`

| Pole | Trvá cez celú session? | Poznámka |
|---|---|---|
| `subjects`, `diet_terms`, `product_titles`, `recipe_titles` | ÁNO (deque s `maxlen`) | V2.9 dizajn, nezmenené V2.13b.1 |
| `active_use_case`, `active_recipe_id`, `recipe_servings` | ÁNO, explicitne čistené pri hard-switch (V2.9 Section 27/84, `_clear_use_case_state()`) | nezmenené |
| `active_result_set_id` | ÁNO, do vyčerpania/nahradenia | nezmenené |
| veľkosť/cena z jedného ťahu (napr. "5kg") | NIE — nepretrváva ako samostatné pole, ovplyvňuje len okamžitý `matches` výsledok cez retrieval query text | nezmenené V2.13b.1 |

V2.13b.1 nemení TRVANLIVOSŤ žiadneho poľa — mení iba KTORÝ text
routing-kritické detektory čítajú.

## Súvisiace dokumenty

- `docs/contextualization-risk-v2.13b.1.md` — plný audit, root cause, scope rozhodnutia.
- `docs/workflow-architecture.md`, `docs/workflow-precedence-v2.13b.md` — V2.13b TurnResolver/WorkflowResolver (nezmenené V2.13b.1, len ich vstupný text je teraz čistejší).
- `docs/routing-debt.md` — `regbug_rt0011` záznam.
