# AdvisorEngine — Application Boundary (Sprint V2.13a)

Dátum: 2026-08-20.

## Prečo AdvisorEngine existuje

Pred V2.13a existovalo `app.main._chat_internal()` ako de-facto jednotný
interný vstupný bod (zaviedol ho V2.12.1 pre execution-context
rozlíšenie, V2.12.4 naň naviazal `SearchQualityTrace`). Fungovalo to
správne, ale **každý interný volajúci si nezávisle vytváral vlastný
duck-typed `_FakeRequest`** len preto, aby uspokojil
`app.main.get_client_key()`'s tvarovú požiadavku (`.headers`/`.client.host`)
— táto trieda bola nezávisle definovaná najmenej 6-krát naprieč
repozitárom (`app.evaluation.adapter` 2×, `scripts/run_search_quality_canary.py`,
`app.main`'s admin canary endpoint, viacero testovacích súborov).

`AdvisorEngine` (`app/advisor_engine.py`) toto DRY-uje na jedno miesto a
pridáva pomenovanú, dokumentovanú hranicu — bez zmeny SPRÁVANIA čohokoľvek
(overené empiricky, nie len architektonicky, viď `tests/test_advisor_engine.py`).

## Transport/aplikačná hranica

```
HTTP /chat  ──────────────┐
Evaluation (V2.10) ───────┤
Learning (V2.12, cez      ┤
  app.evaluation.adapter) ┼──►  AdvisorEngine.run()  ──►  app.main._chat_internal()
Shadow (V2.11, cez        │         (nezmenené)            (NEZMENENÉ, celá
  app.evaluation.adapter) │                                 ~1160-riadková
Canary (V2.12.4) ─────────┘                                 _chat_impl() kaskáda)
```

`AdvisorEngine.run()` NEKOPÍRUJE, NEPRESKLADÁVA a NEMENÍ žiadnu logiku
z `_chat_impl()`/`_chat_internal()` — deleguje na ňu celú, nezmenenú.
Toto JE zámerne "LegacyOrchestrationAdapter" vzor, ktorý zadanie
sankcionuje (Section 14/50) — `_chat_internal()` už spĺňala latku
(jedna funkcia, ktorú vie AdvisorEngine zavolať), takže samostatná
adaptérová trieda by bola len ceremónia navyše.

## AdvisorRequest

```python
@dataclass(frozen=True)
class AdvisorRequest:
    message: str
    session_id: str = ""
    limit: int = 6
    conversation_history: list[dict] = field(default_factory=list)
    client_id: str = ""
    client_key: str = "internal"
```

**Nesie `client_key`, nie `Request`/headers/ASGI scope.** `client_key`
je jediná "trusted metadata" hodnota, ktorú `app.main.get_client_key()`
skutočne potrebuje (odvodená z `X-Forwarded-For`/IP) — HTTP adaptér
(`chat()`) ju vypočíta raz, zo skutočného requestu, predtým než volá
`AdvisorEngine`; každý iný volajúci (eval, canary, ...) dodá vlastnú
stabilnú syntetickú hodnotu.

## AdvisorResponse

**Zámerne obyčajný `dict`, nie nová wrapper trieda.** Existujúci tvar
`/chat` odpovede (`answer`, `products`, `recipes`, `articles`,
`workflow_id`, `workflow_confidence`, `result_set_id`, `answered`,
`cross_sell`, ...) je už stabilný, testovaný kontrakt používaný ~40+
existujúcimi test call sites a verejným HTTP API — zadanie explicitne
zakazuje jeho redizajn (Section 60). `AdvisorResponse = dict[str, Any]`
je typový alias, ktorý pomenúva kontrakt (Section 16) bez vynúteného
unwrap kroku pre kohokoľvek.

## ExecutionContext zostáva jediným zdrojom pravdy

`AdvisorEngine.run(advisor_request, execution_context)` **vyžaduje**
explicitný `execution_context` (žiadny default `None`) — interní
volajúci musia vždy deklarovať svoj režim, presne ako V2.12.1's
Section 17 žiada. `chat()` HTTP route si sám rieši
`isinstance(request, Request)` fallback (nezmenené, kvôli existujúcej
testovacej sade s duck-typed requestmi) a odovzdá už-vyriešený kontext
do `AdvisorEngine`.

## Interní volajúci — pred a po

| Volajúci | Pred V2.13a | Po V2.13a |
|---|---|---|
| `app.main.chat()` (HTTP) | priamo `_chat_internal(chat_request, request)` | `AdvisorEngine.run(AdvisorRequest(...), resolved_context)` |
| `app.evaluation.adapter.make_chat_fn()` | vlastný `_FakeRequest` + `_chat_internal()` | `AdvisorEngine.run()` |
| `app.evaluation.adapter.make_session_chat_fn()` | vlastný `_FakeRequest` + `_chat_internal()` | `AdvisorEngine.run()` |
| `app.ranking_shadow` (V2.11) | cez `make_chat_fn()` | nezmenené volanie, tranzitívne migrované |
| `app.ranking_optimizer` (V2.12) | cez `make_chat_fn()`/`make_session_chat_fn()` | nezmenené volanie, tranzitívne migrované |
| `app.main.admin_search_quality_run()` (V2.12.4) | vlastný `_SearchQualityCanaryRequest` + `_chat_internal()` | `AdvisorEngine.run()` |
| `scripts/run_search_quality_canary.py` (V2.12.4) | vlastný `_FakeRequest` + `_chat_internal()` | `AdvisorEngine.run()` |

## Vedľajšie efekty — presne raz

`AdvisorEngine` sám nepridáva žiadny nový vedľajší efekt — všetky
(`log_question`, `log_event`, `SearchQualityTrace`, session mutation)
zostávajú presne tam, kde boli, vnútri `_chat_impl()`/`_chat_internal()`.
Overené testom (`TestExactlyOnceSideEffects`): jedno CUSTOMER volanie
cez `AdvisorEngine` emituje presne jeden `SearchQualityTrace` záznam a
presne jeden `question_analytics.jsonl` riadok.

## Izolácia (ContextVar, ExecutionContext, session)

`AdvisorEngine` je bezstavový (Section 45/46) — je bezpečné zdieľať
jednu inštanciu (`app.advisor_engine.advisor_engine` modulová
premenná) naprieč všetkými volaniami. Overené testom
(`TestContextVarIsolationUnderConcurrency`, cez
`contextvars.copy_context().run()` — rovnaký mechanizmus, aký Starlette
skutočne používa pre sync route handlery vo svojom threadpool): 20
súbežných volaní s rôznymi dopytmi nikdy neskrížia svoje retrieval
rozhodnutia.

## Rate limiting

Vyjadrené čisto cez `ExecutionContext.apply_rate_limit` — žiadny
`isinstance(Request)` check vnútri `AdvisorEngine` samotného. Overené:
`customer_context()` cez engine sa rate-limituje presne ako predtým;
`evaluation_context()`/iné interné kontexty nikdy.

## Čo zostáva nezmenené (Section 26/27, Invariant #2)

- Routing precedencia (`_chat_impl()`'s kaskáda vetiev)
- Intent klasifikácia
- Retrieval, ranking, taxonomy
- Session/ResultSet sémantika
- Recipe, cross-sell, safety routing logika
- `app.workflow_registry.select_workflow()` zostáva čisto observability
  label, nikdy router — `workflow_id`/`workflow_confidence` sa naďalej
  len prenášajú do odpovede, AdvisorEngine ich nereinterpretuje.

## V2.13b — čo AdvisorEngine NIE JE

`AdvisorEngine` nie je `WorkflowResolver`. Cieľová architektúra V2.13b:

```
AdvisorEngine
      ↓
TurnResolver
      ↓
WorkflowResolver
      ↓
WorkflowHandler
      ↓
Domain Services
```

Táto vrstva **nebola vybudovaná** v tomto sprinte. `docs/routing-debt.md`
dokumentuje presne dva prípady (`rt0004`, `rt0010`), ktoré V2.13b musí
riešiť ako prvé — oba boli v tomto sprinte len **charakterizované**
(zachytené testom, ktorý dokazuje, že AdvisorEngine reprodukuje presne
to isté, už-existujúce správanie), nie opravené.
