# Workflow Architecture — TurnResolver & WorkflowResolver (V2.13b, hardened V2.13b.1)

Dátum: 2026-08-20 (V2.13b), aktualizované 2026-08-20 (V2.13b.1 — vstupný
text pre routing-kritické detektory sprísnený, pozri poslednú sekciu).

## Cieľ

Nahradiť rozptýlené/ad-hoc rozhodovanie o workflow (labelovanie AŽ PO
tom, čo legacy kaskáda už rozhodla — V2.7's `select_workflow()`) za
KAUZÁLNU architektúru, presne pre 2 mandátne prípady (`regbug_rt0004`,
`regbug_rt0010`), bez prestavby celej ~1160-riadkovej `_chat_impl()`
kaskády naraz (Section 61 zadania to explicitne povoľuje — "thin
adapters over existing logic are acceptable").

```
AdvisorEngine.run()
      ↓
app.main._chat_impl()
      │
      ├── [existujúce vetvy: missing_composition, faq (skorý check),
      │    random recipe, reset, recipe follow-up, ordinal, ...]
      │
      ├── allergen_term computed (existujúce, detect_allergen_intent())
      │   ↓
      │   TurnResolver.resolve_safety_signal()  ──► TurnAnalysis
      │   ↓
      │   WorkflowResolver.resolve_workflow()   ──► WorkflowResolution
      │   ↓
      │   ak workflow_id == ALLERGEN_SAFETY: ✅ KAUZÁLNE vykoná safety vetvu, return
      │
      ├── special_subject/related_subject computed (existujúce)
      │   ↓
      │   TurnResolver.resolve_action_target_signal() ──► TurnAnalysis
      │   ↓
      │   WorkflowResolver.resolve_workflow()   ──► WorkflowResolution
      │   ↓
      │   ak workflow_id == RELATED_PRODUCTS: ✅ KAUZÁLNE volá
      │      related_products_for_subject() PRED celou special_subject/
      │      replacement_subject/article_product_subject/cross_sell
      │      elif kaskádou (nie len flag, skutočne prvá podmienka)
      │
      └── [LegacyWorkflowAdapter: zvyšná ~11-vetvová kaskáda,
           NEZMENENÁ — special_subject bundle search, replacement,
           article, cross_sell, recipe, category_discovery, FAQ,
           plochý product_search fallback]
```

## TurnAnalysis (`app/turn_resolver.py`)

Čistý, bezstavový dátový nosič. Polia (len tie, ktoré má skutočné
použitie — Section 15 zadania):

```python
@dataclass(frozen=True)
class TurnAnalysis:
    normalized_message: str
    safety_intent: str | None
    safety_has_product_evidence: bool
    safety_zero_product_signal: bool
    related_products_requested: bool
    related_products_anchor: str | None
    active_result_set_continuation: bool
    evidence: tuple[str, ...]
```

Tri vstupné body (nie jeden — pozri `docs/v2.13a-current-execution-map.md`
prečo signály vznikajú v dvoch rôznych bodoch kaskády, nie na jednom
mieste):

- `resolve_safety_signal(message, *, allergen_term, allergen_product_query_result, related_subject)`
- `resolve_action_target_signal(contextual_message, *, special_subject, related_subject, has_recipe_shopping_language, resolves_confident_product_family)`
- `resolve_resultset_continuation_signal(message, *, active_result_set_id, wants_continuation)`

**Nič nerobí retrieval, ranking, ani generovanie odpovede** — každý
vstupný parameter je UŽ vypočítaná hodnota z existujúcich, dôkladne
odladených detektorov (`detect_allergen_intent()`, `detect_related_subject()`,
`_has_recipe_shopping_language()`, ...). TurnResolver ich len
INTERPRETUJE, nikdy neduplikuje.

## WorkflowResolution (`app/workflow_resolver.py`)

```python
@dataclass(frozen=True)
class WorkflowResolution:
    workflow_id: str
    confidence: str  # HIGH | MEDIUM | LOW
    reason: str
    evidence: tuple[str, ...]
    fallback_used: bool
```

`resolve_workflow(analysis) -> WorkflowResolution` — čistá funkcia,
žiadne I/O. Presné poradie: `docs/workflow-precedence-v2.13b.md`.

## Workflow Execution Map

| workflow_id | Handler/Executor | Migration status |
|---|---|---|
| `RESULTSET_CONTINUATION` | `app.main._chat_impl()`'s existujúci Show More/Show All blok (nezmenený) | NATIVE (už pred V2.13b, teraz formálne pomenované) |
| `ALLERGEN_SAFETY` | `app.main._chat_impl()`'s existujúca allergen_safety vetva (`allergen_product_matches()`, `allergen_safety_answer()`) — teraz spúšťaná `resolve_workflow()`'s rozhodnutím namiesto inline boolean podmienky | NATIVE |
| `RELATED_PRODUCTS` | `app.main.related_products_for_subject()` (existujúca, znovupoužitá) — teraz PRVÁ podmienka v matches-dispatch kaskáde, nie posledný `elif` | NATIVE |
| `PRODUCT_LOOKUP`/`CATEGORY_BROWSE`/`ATTRIBUTE_SEARCH`/`RECIPE_SHOPPING` | V2.4-V2.8 štruktúrovaný pipeline | LEGACY_ADAPTER (nezmenené, V2.4-V2.8) |
| `FAQ_INFORMATIONAL`/`COMPARISON`/`REPLACEMENT`/`USE_CASE_ADVICE` | existujúce legacy vetvy | LEGACY_ADAPTER (V2.7 `select_workflow()` label, nezmenené) |
| `ORDER_TRACKING`/`SUPPORT_ESCALATION` | neimplementované (Foodland nemá tieto schopnosti) | LEGACY (žiadna zmena) |
| všetko ostatné (recept, missing_composition, reset, category_discovery, out_of_domain, ...) | existujúce vetvy `_chat_impl()` | LEGACY_ADAPTER |

## `app.workflow_registry.select_workflow()` — stále aktívny, iný účel

**Nie je nahradený.** Pokrýva 11 `WorkflowContract` typov vrátane tých,
ktoré `resolve_workflow()` nerieši (`PRODUCT_LOOKUP`, `CATEGORY_BROWSE`,
`FAQ_INFORMATIONAL`, `COMPARISON`, `REPLACEMENT`, ...). Volá sa AŽ PO
tom, čo `resolve_workflow()` (nový) už rozhodol NEPOUŽIŤ natívny
workflow (t.j. dopyt padol do `LegacyWorkflowAdapter`) — zostáva čistý
observability label pre TÚTO zostávajúcu kaskádu, presne ako pred
V2.13b. Žiadne dvojité smerovanie (Section 84) — keď `resolve_workflow()`
vráti natívny workflow, `_chat_impl()` sa vráti skôr, než `select_workflow()`
dostane šancu bežať.

## `app/workflows.py` — potvrdené mŕtve, ponechané

`WORKFLOW_CONTRACTS`, `detect_workflow()`, `WORKFLOW_PRIORITY`,
`get_contract()`, `WorkflowResult`, `build_grounded_ids()` — nulové
runtime referencie (overené `grep`-om cez celý `app/main.py`). Jediná
používaná funkcia z tohto súboru je `products_to_cart_candidates()`
(čistá utilita, importovaná do `main.py`). Section 135 zadania vyžaduje
odstránenie LEN ak "zero runtime references AND unique useful contracts
migrated AND tests migrated AND full suite passes" — kód je mŕtvy, ale
**nebol odstránený** v tomto sprinte (mimo scope, riziko bez benefitu —
nemá žiadne testy odkazujúce naň, odstránenie by bolo čisto kozmetické).
Zdokumentované ako `DEAD_CODE_RETAINED`, kandidát na V2.13c cleanup.

## SearchQualityTrace rozšírenie (Section 88/129, čisto aditívne)

`resolved_workflow: str | None`, `resolver_reason: str | None` — nové,
voliteľné polia (`= None` default), pridané AŽ NA KONIEC `SearchQualityTrace`
dataclass (žiadna zmena existujúcej schémy, žiadna migrácia potrebná).
Naplnené LEN keď `resolve_workflow()` vráti natívny (nie `LEGACY_FALLBACK`)
workflow — rovnaký `ContextVar` stash/pop vzor ako V2.12.4's retrieval-
decision (`app.workflow_resolver.stash_resolution()`/`pop_last_resolution()`).

## Testy

- `tests/test_turn_resolver.py` — signal extraction izolovane od
  vykonania (Section 107).
- `tests/test_workflow_resolver.py` — precedencia, konfliktová matica,
  cez konštruované `TurnAnalysis` objekty priamo, žiadne retrieval
  (Section 108).
- `tests/test_routing_regressions.py` — široká kontrolná matica cez
  skutočný `chat()`, dôkaz nulového neočakávaného driftu (Section 143).
- `tests/test_advisor_engine.py` — `rt0004`/`rt0010` charakterizačné
  testy prevedené na `FIXED_ROUTING_REGRESSION`/`FIXED_SAFETY_ROUTING_REGRESSION`.

## V2.13b.1 — vstupný text pre routing-kritické detektory (hardening)

`special_subject`, `related_subject`, `already_have_subject`,
`replacement_subject`, `article_product_subject` a
`resolve_action_target_signal()`'s vstup teraz čítajú
`app.main._routing_message()` namiesto `contextual_message` —
`contextualize_message()`'s bezpodmienečná `diet_terms` prípona (mimo
`is_context_followup()` brány) dokázateľne manufacturovala falošné
`special_subject`/`related_subject` konflikty na nesúvisiacich neskorších
ťahoch (`regbug_rt0011`). Plný root cause, audit a scope rozhodnutia:
`docs/contextualization-risk-v2.13b.1.md`, `docs/session-context-model.md`.
TurnResolver/WorkflowResolver samotné (`app/turn_resolver.py`,
`app/workflow_resolver.py`) sú nezmenené — dostávajú teraz len čistejší
vstupný text.
