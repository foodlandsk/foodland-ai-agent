# Workflow Architecture — TurnResolver, WorkflowResolver & WorkflowExecutor (V2.13b, hardened V2.13b.1, executor V2.13c)

Dátum: 2026-08-20 (V2.13b), aktualizované 2026-08-20 (V2.13b.1 — vstupný
text pre routing-kritické detektory sprísnený; V2.13c — kanonický
`WorkflowExecutor` pre 2 zo 4 `workflow_id`, pozri poslednú sekciu).

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

## V2.13c — WorkflowExecutor (kanonická vykonávacia hranica, ČIASTOČNÉ)

Nový `app/workflow_executor.py` — `WorkflowResult = dict[str, Any]`
(zámerne obyčajný `dict`, rovnaké zdôvodnenie ako `AdvisorResponse`
z V2.13a), `execute_resultset_continuation()`, `execute_allergen_safety()`.
Obe funkcie sú PRESUNUTÝ (nie duplikovaný) kód z ich pôvodných inline
blokov v `_chat_impl()` — mechanický, byte-safe presun, overený
identickým správaním pred/po (`git stash` porovnanie + priame `chat()`
volania).

**Migrované** (2 zo 4 `workflow_id`, ktoré `resolve_workflow()` môže
vrátiť): `RESULTSET_CONTINUATION`, `ALLERGEN_SAFETY` — JEDINÉ dve, ktoré
sú súčasne (i) rozhodnuté resolverom AJ (ii) plne samostatné (okamžitý
`return`, nulová závislosť na zdieľanej `matches`→
`structured_presentation`→odpoveď pipeline).

**Nemigrované** (zámerne, zdokumentované): `RELATED_PRODUCTS` (rozhodnutie
zostáva resolver-driven od V2.13b, ale VYKONANIE zostáva inline —
zdieľa ~250 riadkov prezentačnej logiky s 8 legacy vetvami) a
`LEGACY_FALLBACK` (celá `LegacyWorkflowAdapter` kaskáda, ~9 vetiev).
Plný audit a zdôvodnenie: `docs/workflow-inventory-v2.13c.md`,
migračný register: `docs/workflow-migration-v2.13c.md`.

**Stav**: `WORKFLOW_ARCHITECTURE_PARTIALLY_CLOSED` — nie
`WORKFLOW_ARCHITECTURE_CLOSED`. Hlavný `_chat_impl()` naďalej obsahuje
~9 vetiev, ktoré nezávisle rozhodujú o type úlohy MIMO
`WorkflowResolver` (FAQ, recipe, replacement, article, category
discovery, out-of-domain, reset, missing-composition, random-recipe) —
toto NIE JE nová medzera objavená V2.13c, je to ten istý
`LegacyWorkflowAdapter`, ktorý V2.13a/V2.13b explicitne sankcionovali
ako prijateľný rozsah (Section 61/62 zadania V2.13b). Úplné uzavretie by
vyžadovalo rozsiahlejšiu, viacsprintovú migráciu s dôkladným
charakterizačným pokrytím každej vetvy — mimo rozsahu jedného sedenia
bez neprimeraného rizika (Section 36 zadania V2.13c: "no big-bang
rewrite... migrate incrementally").

## V2.13d — 6 ďalších migrovaných vetiev + kľúčový nález

Priame prečítanie aktuálneho kódu (nie opätovné použitie V2.13c's
dokumentácie) ukázalo, že V2.13c's "9 podobných vetiev" bolo príliš
zjednodušujúce. Skutočnosť: 6 z nich (`missing_composition`, `faq`,
`random_recipe`, `reset`, `out_of_domain`, `category_discovery`) sú
PLNE samostatné, okamžité `return` bloky — presne v tom istom tvare ako
`ALLERGEN_SAFETY`, ktorý V2.13c už úspešne migroval. Migrované do
`app/workflow_executor.py` (`execute_missing_composition()`,
`execute_faq()`, `execute_random_recipe()`, `execute_reset()`,
`execute_out_of_domain()`, `execute_category_discovery()`).

**Kľúčový nález** (odhalený plným pytest behom, nie code review):
`_chat_impl()` lokálne prevíaže meno `log_question` na no-op lambdu,
keď `execution_context.emit_customer_analytics` je `False` — funguje
pre všetkých ~13 pôvodných volacích miest v TEJ ISTEJ funkcii, ale
NEPREŽIJE presun cez modulovú hranicu. Executor handler volajúci
`m.log_question(...)` vždy zasiahne SKUTOČNÚ, bezpodmienečnú funkciu,
čím ticho poruší `EVALUATION`/`LEARNING`/`SHADOW`/`ADMIN_TEST` izoláciu
od `question_analytics.jsonl`. Týkalo sa VŠETKÝCH 7 handlerov
volajúcich `log_question()` (V2.13c's `execute_allergen_safety` +
V2.13d's 6 nových) — opravené explicitným `emit_customer_analytics: bool`
parametrom, ktorý každý handler sám kontroluje. Detail:
`docs/workflow-migration-v2.13d.md`.

**Nemigrované aj po V2.13d** (2 zostávajúce jednotky, presnejšie
vymedzené než V2.13c's odhad): (1) recipe stavový automat
(`recipe_followup`/ordinal-reference/orphaned-followup pre-checks +
hlavný `recipe_subject` blok — reťaz vzájomne závislých krokov, nie
sekvencia nezávislých blokov), (2) zdieľaná commerce matches-dispatch
pipeline (`already_have_subject`, `special_subject` bundly,
`replacement_subject`, `article_product_subject`, `cross_sell_matches`
fallback, `related_subject` fallback, plochý `product_search`, +
`RELATED_PRODUCTS`'s vlastné vykonanie — ~30+ vzájomne závislých
lokálnych premenných, zistené priamym pokusom o extrakciu). Plné
zdôvodnenie: `docs/workflow-migration-v2.13d.md`.

**Stav po V2.13d**: `WORKFLOW_ARCHITECTURE_PARTIALLY_CLOSED` (nie
`CLOSED`) — ale s výrazne menším, presnejšie vymedzeným zvyškovým
dlhom (2 jednotky namiesto 9 vetiev).

## V2.13e — recipe stavový automat extrahovaný

Postup presne podľa OBSERVE→MAP→CHARACTERIZE→TEST→FREEZE→FORMALIZE→
EXTRACT→COMPARE→REGRESSION disciplíny (žiadne presúvanie kódu pred
charakterizáciou). Plný audit: `docs/recipe-state-machine-v2.13e.md`.

**Kľúčové architektonické zistenie**: recipe logika v `_chat_impl()`
pozostávala z 5 blokov (A: setup `_recipe_followup_result`; B: ordinálna
referencia; C: osirelý follow-up; D: hlavný `recipe_subject` blok; E:
`recipe_followup_result` handling), ale **B a C NIE SÚ recipe-špecifické**
— sú to všeobecné session-continuity clarifikačné vzory (ordinálna
referencia na AKÝKOĽVEK naposledy zobrazený zoznam, nie len recept),
ktoré recipe stav používajú LEN ako súčasť gate podmienky. Priamy dôkaz:
podmienky B/C (`_recipe_followup_result is None AND not recipe_subject`)
sú PÁROVO VYLUČUJÚCE sa s D's (`recipe_subject` truthy) a E's
(`_recipe_followup_result is not None`) podmienkami — pre daný ťah môže
platiť najviac jedna z {B, C, D, E}, čo umožňuje presunúť D+E do JEDNEJ
funkcie volanej HNEĎ PO bloku A (namiesto ich pôvodného preloženia MEDZI
B a C) bez zmeny pozorovateľného správania — dokázané, nie predpokladané.

**Implementácia**: `app.workflow_executor.execute_recipe()` — Blok D
(hlavný `recipe_subject` handler, V2.8 recipe graph) a Blok E
(`recipe_followup_result` handler, 3 druhy: `_RF_INGREDIENT`,
`_RF_SELECTED`, `.plan`) zlúčené do jednej funkcie, mechanicky presunuté
(nie duplikované). Bloky B (ordinálna referencia) a C (osirelý
follow-up) zostávajú nezmenené, na svojom pôvodnom mieste v
`_chat_impl()` — správne klasifikované ako `SESSION_CONTINUATION_FALLBACK`,
nie recipe execution.

**Charakterizácia pred extrakciou**: 19 nových testov
(`tests/test_recipe_state_machine_v2_13e.py`) napísaných a spustených
PROTI PRED-extrakčnej implementácii (všetkých 19 prešlo), až POTOM
extrakcia, potom ROVNAKÝCH 19 testov znova PROTI po-extrakčnej
implementácii (identický výsledok — dôkaz behaviorálnej parity).

**Stav**: `RECIPE_STATE_MACHINE_EXTRACTED`. Celkový architektonický
stav zostáva `WORKFLOW_ARCHITECTURE_PARTIALLY_CLOSED` — zvyšný dlh:
JEDNA jednotka (commerce matches-dispatch pipeline vrátane
`RELATED_PRODUCTS`'s vykonania), dole z 2 pred V2.13e. Commerce pipeline
zostáva explicitne MIMO rozsahu tohto sprintu (zadanie V2.13e Section
54 — "must not be extracted or refactored in this sprint").

## V2.13f-A — commerce pipeline charakterizácia, `ACCEPT_PARTIALLY_CLOSED`

CHARACTERIZATION ONLY sprint (Section 1–3 invariant zadania: žiadna
extrakcia, refaktor ani presun vykonávacej logiky). Cieľ: formálny
CFG/data-dependency graf/side-effect map/coupling klasifikácia/money-path
analýza poslednej zostávajúcej `legacy_primary_execution_branch_count`
jednotky, ukončený explicitným 14-kritériovým GO/STOP scorecard
rozhodnutím. Plný audit: `docs/commerce-pipeline-v2.13f-a.md`.

**Zistenie**: 34 lokálnych premenných (31 s reálnym fan-in do
terminálneho rozhodnutia), 8 vzájomne sa vylučujúcich terminálnych
`return` miest (oproti 2 u recipe stavového automatu v V2.13e), 6 z 9
vedľajších efektov bezpodmienečné a vykonané PRED terminálnym
rozhodnutím, 3 polia (`cross_sell_*`, `workflow_selection`) vypočítané
výhradne v jednej z 8 vetiev. Naviac nájdené (nie predpokladané) 2
nekonzistencie tvaru odpovede: 2 z 8 terminálnych vetiev (OpenAI
transient-error, generický exception handler) vynechávajú kľúče
`"memory"`/`"intent"`, ktoré má každá iná vetva; `"response_mode"`
chýba v 4 z 8. Oba nálezy priamo reprodukované charakterizačnými
testami, NEOPRAVENÉ touto sprintou (mimo rozsahu — CHARACTERIZATION
ONLY), zdokumentované ako nezávislý budúci low-risk bugfix kandidát.

**Scorecard výsledok**: 6× FAIL, 4× PASS, 3× PARTIAL/LOW, 1× HIGH-risk
zo 14 kritérií — vrátane FAIL na všetkých kritériách s najvyššou váhou
pre extrakčnú bezpečnosť (jednotný návratový kontrakt, ohraničený
lokálny stav, izolácia vedľajších efektov, redukovateľnosť na čistú
funkciu, dokázateľnosť mechanickým presunom).

**Rozhodnutie**: **`ACCEPT_PARTIALLY_CLOSED`** — explicitne platný,
úspešný výsledok podľa zadania (nie zlyhanie, dôkazné bremeno bolo na
extrakcii). Architektonický stav zostáva
`WORKFLOW_ARCHITECTURE_PARTIALLY_CLOSED`: 9 z ~11 pôvodných vetiev na
`app.workflow_executor`, táto jedna pipeline zostáva vedome na legacy
ceste, teraz s úplnou formálnou charakterizáciou namiesto
neformálneho odhadu. 13 nových charakterizačných testov
(`tests/test_commerce_pipeline_v2_13f_a.py`) zamrazujú súčasné
správanie ako regresnú sieť pre akúkoľvek budúcu zmenu tejto pipeline.
Žiadna ďalšia extrakcia sa po tomto rozhodnutí v tejto sprinte
nepokúša (zadanie to explicitne zakazuje po STOP rozhodnutí).
