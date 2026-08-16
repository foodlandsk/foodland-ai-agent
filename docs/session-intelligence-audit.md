# Session Intelligence Audit — Sprint V2.9

Dátum: 2026-08-16. Zdroj: aktuálny `app/main.py` (post-V2.8, commit
`58991b5`) pred akoukoľvek V2.9 zmenou.

## Aktuálny stav pred V2.9

### Úložisko

`session_memories: dict[str, dict] = {}` (`app/main.py:274`) — **process-local
in-memory dict**, žiadny Redis, žiadna DB. TTL/pruning už existuje
(`SESSION_MEMORY_TTL_SECONDS`, `SESSION_MEMORY_MAX_SESSIONS`,
`prune_session_memories()`). `get_session_memory(memory_key)` vytvorí/vráti
záznam; `session_memory_key(session_id, client_key)` — keď `session_id` je
neprázdny (widget ho vždy posiela), použije sa priamo ako kľúč;
`client_id`/`client_key` sú fallback pre anonymné session.

**Dôsledok pre V2.9 (Section 32)**: nová session inteligencia sa stavia
NAD tento existujúci dict (nové kľúče v tom istom `memory` zázname), nie
ako druhé úložisko. Obmedzenie zdieľané so zvyškom systému: reštart
Railway procesu vymaže všetku session pamäť; viacero worker procesov (ak
by boli nasadené) by mali NEZDIEĽANÚ pamäť. Toto je čestne zdokumentované
obmedzenie, nie niečo, čo V2.9 rieši (mimo rozsahu — vyžadovalo by
externé úložisko, ktoré aktuálna Railway architektúra nemá).

### Existujúci mechanizmus kontextu (pred V2.9)

- `contextualize_message(message, memory)` — **bezpodmienečne** vkladá
  `last_top_product_title` (alebo `best_memory_subject`) a posledné 2
  `diet_terms` do KAŽDEJ nasledujúcej správy, PRED akoukoľvek intent
  detekciou. Toto je presne ten mechanizmus, ktorý `docs/advisor-v2-
  architecture.md`'s "V2.6 Context/personalizácia" riadok už označil ako
  štrukturálne riziko.
- `merge_constraints(base, addition)` (`app/query_constraints.py`, V2.5) —
  **už funguje** pre family/subfamily perzistenciu + package_size/brand
  override (cez `or`, addition vyhráva keď je pravdivá) pre STRUKTUROVANÚ
  retrieval cestu (`special_subject=="plain_rice"` a finálna `else:`
  vetva). **Chýbalo**: explicitné ODOBRATIE constraintu (Section 10/21) —
  `or` nevie vyjadriť "zruš toto pole", iba "nahraď ak je nové pravdivé".
- `active_result_set_id` (V2.5) — ResultSet perzistuje cez `memory`, ale
  iba pre štruktúrovanú product retrieval cestu, nie pre recepty.

### Kritický reálny nález: recepty NEMAJÚ ŽIADNU konverzačnú kontinuitu

`detect_recipe_subject(contextual_message)` sa volá **odznova, nezávisle,
každý ťah** — žiadne pole v `memory` neuchováva "ktorý recept je aktívny".
Overené priamym testom pred V2.9 zmenou:

```
"Chcem robiť Pad Thai. Čo potrebujem?"  -> 5 surovín, coverage 100%
"aké rezance?"                          -> recipe_subject=None, padá do
                                            generic cross-sell vetvy,
                                            NIE recipe continuity
```

Toto je presne ten problém, ktorý Section 16/17/53 V2.9 zadania žiada
vyriešiť — a je to REÁLNY, nie hypotetický nález.

### Kritický reálny nález: "aká ryžu?" v sushi kontexte vracia generickú ryžu

```
"chcem robiť sushi"  -> related_subject="sushi" (cez detect_related_subject)
"aká ryžu?"           -> related_subject="ryza" (bare, generic)
                       -> vráti Basmati/restovaná ryža s bazalkou,
                          NIE sushi ryžu
```

Potvrdzuje Section 15/26/52 nález — žiadne `active_use_case` pole
existovalo pred V2.9.

### Overené: NIE je to skutočná "hard switch" kontaminácia

Testovaný scenár "sushi → hľadám Shin Ramyun" vracal nesprávne (dashi/
miso/ramen rezance namiesto Shin Ramyun) **aj v úplne čerstvej session
bez akejkoľvek predchádzajúcej histórie** — je to STATELESS nedostatok
(`"ramyun"` reťazec spúšťa `related_subject`/cross-sell vetvu bez ohľadu
na kontext), nie session-kontaminácia. Mimo rozsahu V2.9 (nie je to
session problém), zaznamenané v RIZIKÁ.

### Widget (`app/widget.js`)

`session_id` (generovaný per session) a `client_id` (`localStorage`
`"foodland_ai_client_id"`) sa už posielajú v každom `/chat` requeste.
`ChatRequest` (Pydantic model, `app/main.py`) polia: `message, limit,
conversation_history, session_id, client_id` — **žiadne `cart`/`basket`
pole**. Widget neposiela žiadnu štruktúrovanú "klikol na produkt #2" akciu
— "Zobraziť viac"/"Zobraziť všetky" fungujú tak, že JS nastaví
`input.value` na frázu a odošle bežný chat formulár (V2.5 mechanizmus,
nezmenené). **Dôsledok**: ordinal reference ("ten druhý") sa musí
rozpoznať z TEXTU správy, nie zo štruktúrovanej UI udalosti.

## Zhrnutie medzier oproti V2.9 zadaniu (pred implementáciou)

| Oblasť | Stav pred V2.9 |
|---|---|
| Family/subfamily perzistencia (rice test) | **Existuje** (V2.5 `merge_constraints`) |
| Package size override | **Existuje** (`or` v `merge_constraints`) |
| Package size/brand ODOBRATIE | Chýba |
| Recipe/servings kontinuita | **Úplne chýba** |
| Ordinal reference ("ten druhý") | Chýba |
| `active_use_case` (sushi rice narrowing) | Chýba |
| Reset fráza | Chýba |
| Hard switch clearing | Chýba (žiadne pole na vyčistenie) |
| Basket-satisfaction pre recepty | V2.8 malo capability, žiadny session trigger |

Toto je presný, overený rozsah práce pre V2.9 — nie prevzatý zo zadania
naslepo, ale potvrdený priamym testovaním aktuálneho kódu pred zmenou.
