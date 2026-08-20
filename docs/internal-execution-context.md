# Explicitný interný Execution Context — Sprint V2.12.1 Part D

Dátum: 2026-08-19.

## Problém, ktorý táto časť rieši

Commit `8936188` (počas produkčnej opravy v tejto session) zaviedol
hotfix: `_chat_impl()` volá `enforce_rate_limit()` iba keď
`isinstance(request, Request)` — pravda pre reálny FastAPI/Starlette
request, nepravda pre `app.evaluation.adapter`'s duck-typed
`_FakeRequest` stub. Bol to správny a nutný hotfix (skutočný `429` v
produkcii po ~12 interných volaniach z learning cyklu), ale bol to
**hotfix, nie cieľová architektúra** (zadanie Section 48) — interpretoval
ZÁMER volajúceho ("som interný nástroj") z NÁHODY tvaru objektu, ktorý
sa mu podarilo poslať ako druhý argument, namiesto toho, aby ho volajúci
explicitne deklaroval.

## `app/execution_context.py` — päť módov

```python
class ExecutionMode(str, Enum):
    CUSTOMER = "CUSTOMER"
    EVALUATION = "EVALUATION"
    LEARNING = "LEARNING"
    SHADOW = "SHADOW"
    ADMIN_TEST = "ADMIN_TEST"

@dataclass(frozen=True)
class ExecutionContext:
    mode: ExecutionMode
    apply_rate_limit: bool
    emit_customer_analytics: bool
```

| Mód | `apply_rate_limit` | `emit_customer_analytics` | Kto ho používa |
|---|---|---|---|
| `CUSTOMER` | True | True | `POST /chat` (reálna prevádzka) |
| `EVALUATION` | False | False | `app.evaluation.adapter` (V2.10 golden/conversation suite) |
| `LEARNING` | False | False | `app.ranking_optimizer.evaluate_profile()` (V2.12 candidate scoring) |
| `SHADOW` | False | False | `app.ranking_shadow.shadow_compare()` |
| `ADMIN_TEST` | False | False | rezervované pre budúci diagnostický nástroj — zatiaľ nikde nevolané |

Iba `CUSTOMER` kedykoľvek aplikuje zákaznícky rate limit alebo zapisuje
do `question_analytics.jsonl` cez `log_question()`. Každý iný mód volá
ten istý reálny `_chat_impl()` pipeline pre rovnaké garancie správnosti,
aké dostane zákazník (Section 43: nikdy druhý ranking/search systém) —
len bez vedľajších efektov, ktoré sa naň nevzťahujú.

## Zapojenie do `_chat_impl()`

```python
def _chat_impl(chat_request, request, execution_context=None):
    if execution_context is None:
        execution_context = _customer_context() if isinstance(request, Request) else _evaluation_context()

    client_key = get_client_key(request)
    if execution_context.apply_rate_limit:
        enforce_rate_limit(client_key)

    _real_log_question = globals()["log_question"]
    log_question = _real_log_question if execution_context.emit_customer_analytics else (lambda *a, **kw: None)
    ...
```

`log_question` je lokálne prebindovaný na začiatku funkcie namiesto
úpravy ~13 volacích miest roztrúsených po ~1000-riadkovom tele funkcie —
funguje to, pretože lokálne priradenie robí meno lokálnym pre CELÉ telo
funkcie v Pythone; skutočná globálna funkcia sa musí načítať cez
`globals()["log_question"]` (nie holý názov), inak by pravá strana
priradenia sama narazila na `UnboundLocalError`.

**Fallback zachovaný, nie odstránený** (Section 59 zadania): keď
volajúci nepošle `execution_context` explicitne, `isinstance(request,
Request)` kontrola stále rozhoduje presne ako pred týmto sprintom — toto
je čisto prídavná zmena. Desiatky existujúcich testov volajú `m.chat(...,
_FakeRequest())` priamo a spoliehajú sa na tento fallback; `chat()`
(skutočný `@app.post("/chat")` endpoint) preto **zámerne NEVYNucuje**
`customer_context()` — iba interní volajúci, ktorí chcú explicitne
deklarovať mód, volajú namiesto neho zdieľaný `_chat_internal()` helper
priamo.

```python
def _chat_internal(chat_request, request, execution_context=None) -> dict:
    response = _chat_impl(chat_request, request, execution_context=execution_context)
    response["answered"] = _compute_answered(response)
    return response

@app.post("/chat")
def chat(chat_request, request) -> dict:
    return _chat_internal(chat_request, request)  # bez explicitného contextu -> isinstance fallback
```

## Migrovaní volajúci

- `app.evaluation.adapter.make_chat_fn()` / `make_session_chat_fn()` —
  teraz prijímajú `execution_context=None` (default `evaluation_
  context()`) a volajú `m._chat_internal()` namiesto `m.chat()`.
  `_FakeRequest` stub zostáva nezmenený (framework `get_client_key()`
  stále potrebuje niečo s `.headers`/`.client.host` tvarom, a nie je
  dosiahnuteľný z reálneho HTTP — pozri pôvodný komentár k hotfixu) —
  zmenilo sa len TO, ktoré správanie spúšťa, nie samotný stub.
- `app.ranking_shadow.shadow_compare()` — volá
  `make_chat_fn(execution_context=shadow_context())` explicitne.
- `app.ranking_optimizer.evaluate_profile()` — volá `make_chat_fn(...)`
  aj `make_session_chat_fn(...)` s `execution_context=learning_context()`
  explicitne (jediné miesto, kde `evaluate_profile()` reálne beží — z
  `app.learning_candidates.generate_candidate()`).

## Testovacia matica

`tests/test_execution_context.py` (17 testov): factory funkcie (CUSTOMER
má oba flagy True, ostatné štyri majú oba False, 5 módov je navzájom
odlišných); explicitný `EVALUATION` context PREBIJE reálny Request
objekt (dôkaz, že nový signál sa naozaj konzultuje, nie že isinstance
vždy vyhrá); symetricky explicitný `CUSTOMER` context rate-limituje aj
`_FakeRequest`; žiadny context → isinstance fallback funguje presne ako
predtým; `EVALUATION`/`SHADOW`/`LEARNING` context nikdy nezapíše do
`question_analytics.jsonl`, `CUSTOMER` context zapíše; `make_chat_fn()`
defaultuje na EVALUATION a prijíma explicitný override;
`ranking_shadow`/`ranking_optimizer` zdrojový kód skutočne obsahuje
volanie s príslušným kontextom (nie len že existuje, ale že sa reálne
používa).

## V2.13a — AdvisorEngine teraz vyžaduje explicitný kontext

`app.advisor_engine.AdvisorEngine.run(advisor_request, execution_context)`
nemá default `None` pre `execution_context` — každý volajúci cez tento
nový vstupný bod MUSÍ deklarovať svoj režim explicitne (Section 17
vyžaduje presne toto). `isinstance(request, Request)` fallback zostáva
**iba** vnútri `app.main._chat_impl()`/`chat()` (kvôli existujúcej
veľkej testovacej sade s duck-typed requestmi, ktorá tento fallback
stále využíva) — `AdvisorEngine` sám o sebe už tento fallback
nepotrebuje ani nekonzultuje. Detail: `docs/advisor-engine.md`.
