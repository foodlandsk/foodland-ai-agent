# Contextualization Risk & Hardening — V2.13b.1

Dátum: 2026-08-20.

## Prečo tento dokument existuje

V2.13b (`2970cdb`) opravil `regbug_rt0004`/`regbug_rt0010`, ale počas
vlastného regresného overovania odhalil tretiu, hlbšiu chybu:
`regbug_rt0011`, session-collision spôsobená mechanizmom
`contextualize_message()`. Táto oprava (V2.13b Section 8 tejto session's
histórie) bola úzko scoped na JEDEN rozhodovací bod
(`_related_products_forced`). Tento dokument zaznamenáva presnú
reprodukciu, root cause a SYSTEMICKÚ opravu (V2.13b.1), ktorá rieši
CELÚ triedu chyby, nie len jeden prípad.

## 1. Presná reprodukcia regbug_rt0011

Golden case (`eval/golden/regression_bugs.json`, `id=regbug_rt0011`):

```
query: "mám rád nepálivé jedlo, čo odporúčaš?"
expected_intent: product_search
must_include_title_substrings: [mochi, kokosové mlieko, jazmínová ryža, miso]
must_not_include_title_substrings: [EKO kraft box, spicy, hot, páliv]
critical: true
```

**Ako sa objavila**: nie priamo v tomto golden case (ten beží na čerstvej
session a prechádza), ale v `app.ranking_optimizer.evaluate_profile()`,
ktorý volá `app.evaluation.adapter.make_chat_fn()` a generuje
`session_id` z per-volanie reštartovaného počítadla
(`"eval-isolated-1"`, `"eval-isolated-2"`, ...). Keďže dva nezávislé
`evaluate_profile()` behy spracúvajú ten istý zoznam `critical=True`
golden prípadov v tom istom poradí, prípad na pozícii K dostane
IDENTICKÝ `session_id` v oboch behoch — a `app.main.session_memories`
je perzistentný globálny dict nikdy nevyčistený medzi takýmito behmi.

**Priama reprodukcia** (rovnaký `session_id`, ten istý dopyt dvakrát):

```
run1 (čerstvá session): intent=product_search
  Mirin, Jazmínová ryža, Ryžové rezance, Miso pasta, Mochi, Kokosové mlieko
run2 (rovnaká session, ten istý dopyt): intent=related_products  ← CHYBA
```

## 2. Root cause

`app.main.contextualize_message()` (pred V2.13b.1):

```python
def contextualize_message(message, memory):
    if not memory:
        return message
    parts = [message]
    if is_context_followup(message):
        # ... last_top_product_title alebo best_memory_subject carry-over
    for term in list(memory.get("diet_terms", []))[-2:]:   # <- BEZPODMIENEČNE
        if term and term not in normalize(" ".join(parts)):
            parts.append(term)
    return " ".join(parts).strip()
```

Diet-term append beží **bezpodmienečne**, mimo `is_context_followup()`
brány, ktorá chráni subject-carry-over vyššie. Na run1 zákazník povie
"nepálivé jedlo" — `detect_diet_terms()` zaznamená `["jemne", "pikantne"]`
do `memory["diet_terms"]` (vedľajší nález: `"nepaliv"` substring obsahuje
`"paliv"`, čo je AJ pozitívny "pikantne" marker — samostatná, menšia
nepresnosť v `detect_diet_terms()`, mimo scope tohto sprintu, keďže
`DIET_TERM_NEGATION_MARKERS` kontroluje len explicitné negačné slová
ako "nechcem", nie predpony ako "ne-" priamo na termíne). Na run2 (ten
istý dopyt, tá istá session) `contextualize_message()` vytvorí:

```
"mám rád nepálivé jedlo, čo odporúčaš? jemne pikantne"
```

Proti tomuto textu: `detect_special_product_subject()` → `"mild"`
(z "jemne"), `detect_related_subject()` → `"medium_spicy"`
(z "pikantne") — konflikt, ktorý V2.13b's `resolve_action_target_signal()`
existuje presne na to, aby arbitroval (Section 30-32 pôvodného V2.13b
zadania) — spolu s `_has_recipe_shopping_language()` vracajúcim `True`
(kvôli "odporúčaš"), toto spustilo `RELATED_PRODUCTS` namiesto
`PRODUCT_SEARCH`.

**Prečo V2.13b's pôvodná oprava (raw-message double-check na
`_related_products_forced`) rt0011 opravila, ale nie CELÚ triedu**: tá
oprava vyžadovala, aby `special_subject`/`related_subject` boli
overiteľné aj proti surovej správe — čo správne zablokovalo TENTO jeden
rozhodovací bod. Ale `special_subject`/`related_subject` SAMOTNÉ (V2.13b
neponechané nezmenené) sa naďalej počítali z kontaminovaného
`contextual_message` a používali sa ĎALEJ v kaskáde (elif dispatch,
intent ternary, `already_have_subject`/`replacement_subject`, brand/
kitchenware guardy, `article_product_subject`) — ktorýkoľvek iný dopyt s
INÝM náhodným kolíznym diet-term párom mohol vyvolať INÚ chybnú cestu.

## 3. Audit — čo presne contextualize_message() robí

Jediné produkčné volacie miesto: `app/main.py`, `_chat_impl()`
(`contextual_message = contextualize_message(chat_request.message, memory)`).
Výsledná premenná `contextual_message` sa ďalej používa na ~20 miestach
v `_chat_impl()`. Klasifikácia každej transformácie a jej použití
(Section 6/7/33 zadania):

| Transformácia | Klasifikácia | Riziko |
|---|---|---|
| `is_context_followup()`-gated posledný produkt/subjekt | `EXPLICIT_FOLLOWUP_RESOLUTION` | NÍZKE — štrukturálne bezpečné (gate vyžaduje krátku/presnú frázu, explicitná aktuálna správa s vlastným predmetom túto vetvu nikdy nezasiahne) |
| posledné 2 `diet_terms`, bezpodmienečne | `DIET_TERM_INJECTION` | **VYSOKÉ** — potvrdený koreň `regbug_rt0011` a dvoch skorších sprintov (V2.1.5 "pikantnejšie", V2.1.7 negácia) |

Downstream konzumenti `contextual_message` rozdelení podľa rizika:

| Konzument | Riadi workflow/routing? | V2.13b.1 akcia |
|---|---|---|
| `special_subject`, `related_subject`, `already_have_subject`, `replacement_subject` | **ÁNO** — priamo | presunuté na `_routing_message()` |
| `_action_target_analysis` (TurnResolver) | **ÁNO** | presunuté na `_routing_message()` |
| PRODUCT_SET_SIGNAL_TOKENS/brand/confident-family/kitchenware guardy nad `related_subject` | **ÁNO** — refinujú vyššie | presunuté na `_routing_message()` |
| `article_product_subject` | **ÁNO** — priamo v intent ternary | presunuté na `_routing_message()` |
| `recipe_subject`, `search_knowledge()`, `cross_sell_products_for_message()`, štruktúrovaný retrieval `query=`, `hybrid_cached_search_products()` fallback, odpoveďové texty | NIE — retrieval/knowledge/odpoveď, nie voľba workflow | **ponechané na `contextual_message` bezo zmeny** (Section 35/64 — retrieval sa nesmie prestavať; žiadny aktuálny dôkaz kontaminácie tu, Section 88 — nehľadať bez dôkazu) |
| OpenAI system/user prompt (`_call_openai_with_retry`) | NIE | **už PRED V2.13b.1 používal `chat_request.message` (surový)**, nie `contextual_message` — Section 58 "no user-quoted text alteration" bolo splnené už predtým, overené auditom, nie predpokladané |

## 4. Oprava — `app.main._routing_message()`

Nová funkcia vedľa `contextualize_message()` (rovnaký `is_context_followup()`
gate pre subject-carryover, **nikdy** diet_terms append):

```python
def _routing_message(message, memory):
    if not memory:
        return message
    parts = [message]
    if is_context_followup(message):
        if memory.get("last_top_product_title"):
            parts.append(memory["last_top_product_title"])
        else:
            subject = best_memory_subject(memory)
            if subject:
                parts.append(subject.replace("_", " "))
    return " ".join(parts).strip()
```

Použitá namiesto `contextual_message` presne na 9 miestach vo
`_chat_impl()` — všetky ROUTING-CRITICAL detektory z tabuľky vyššie
(`already_have_subject`, `special_subject`, `replacement_subject`,
`related_subject`, `_action_target_analysis`, `PRODUCT_SET_SIGNAL_TOKENS`
guard, brand override guard, confident-family guard, kitchenware guard,
`article_product_subject`). `contextualize_message()` samotná **nebola
zmenená** — jej existujúci kontrakt a testy (`tests/test_core.py::TestSessionMemory`,
vrátane `test_diet_preference_is_remembered`) zostávajú v platnosti
bezo zmeny, pretože stále slúži retrieval/knowledge/odpoveďovým
konzumentom presne ako predtým.

## 5. Prečo nie plná `ContextMergePolicy`/`ContextConflict` architektúra

Pôvodné zadanie navrhuje `SessionContext`/`ContextMergePolicy`/
`ContextConflict` triedy s explicitnými `provenance` enumami
(`EXPLICIT_THIS_TURN`, `ACTIVE_RESULTSET_CONTEXT`, ...). Po audite
(Section 3 vyššie) sa ukázalo, že:

1. **Invariant #3** ("explicit current-turn input outranks conflicting
   inherited context") je už štrukturálne zaručený `is_context_followup()`'s
   gate na subject-carryover — gate vyžaduje krátku/presnú frázu bez
   vlastného predmetu, takže explicitná aktuálna správa s VLASTNÝM
   predmetom túto vetvu principiálne nikdy nezasiahne. Netreba novú
   precedence-arbitration triedu na niečo, čo je už nemožné.
2. Jediný SKUTOČNE preukázaný kontaminačný mechanizmus bol diet-term
   injekcia — jeden `for` cyklus, jedna bezpodmienečná podmienka. Plná
   trieda-hierarchia s 7 `scope` enumami a `ContextConflict` objektmi by
   riešila hypotetické riziká bez dôkazu (zadanie samo, Section 88:
   "do not chase... without evidence"), s výrazne väčším blast-radiusom
   (desiatky call sites by museli migrovať na nový typ) za rovnaký
   výsledok.
3. Section 55 zadania explicitne pripúšťa výsledok "NARROWED" — presne
   toto: `contextualize_message()` zostáva, no jej rizikovejšia
   polovica (diet-term injekcia) už nekŕmi routing-kritické detektory.

**Status podľa Section 98 zadania**: `contextualize_message()` =
**RETAINED_FOR_RETRIEVAL_AND_ANSWER_CONTEXT_ONLY** (nie
`ROUTING_CRITICAL`). Nová `_routing_message()` = jediný vstup pre
workflow-rozhodujúce detektory.

## 6. Čo NEBOLO zmenené (vedomé rozhodnutie, nie prehliadnutie)

- `recipe_subject` (`detect_recipe_subject(contextual_message)`) —
  potenciálne tiež "routing-critical" (rozhoduje RECIPE_SHOPPING), ale
  BEZ aktuálneho dôkazu kontaminácie a s rozsiahlym existujúcim pokrytím
  (V2.8 47 testov, V2.9 Pad Thai matica) — ponechané, zdokumentované ako
  auditovné, no neoverené riziko pre budúci sprint, ak sa objaví dôkaz.
- Retrieval query text (`query=contextual_message`,
  `hybrid_cached_search_products(contextual_message, ...)`),
  `cross_sell_products_for_message()`, `search_knowledge()` — ponechané
  bezo zmeny (Section 35/64 zadania: nesmie sa prestavať retrieval).
- `session_memory_context()` (existujúca, ale NEPOUŽÍVANÁ funkcia,
  `app/main.py` riadok ~4043) — štruktúrovaný, diet-term-safe LLM-context
  builder už existuje v kóde, ale nikde sa nevolá. Mimo scope pripojiť
  ho (žiadny dôkaz, že OpenAI prompt aktuálne potrebuje viac kontextu,
  než už dostáva cez `chat_request.message` + `matches` + `knowledge_matches`).

## 7. Trieda chyby, nie len inštancia (Invariant #11)

Táto oprava je generická nad `memory["diet_terms"]` obsahom — funguje
identicky pre AKÝKOĽVEK diet term (`jemne`, `pikantne`, `veganske`,
`vegetarianske`, `bezlepkove`), nie hardcoded na "jemne"/"pikantne" z
`regbug_rt0011`. Overené testom
(`tests/test_session_contamination_v2_13b_1.py::TestDietTermDoesNotHijackUnrelatedProduct`)
s ODLIŠNÝM diet termom ("pikantné") a odlišnými nadväzujúcimi dopytmi.
