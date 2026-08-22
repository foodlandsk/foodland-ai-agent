# V2.15a — Recommendation Observability, Signal Semantics & Learning Readiness Audit

Dátum: 2026-08-22. Baseline: `4e0d65e` (rt0013 closure), pytest 1593/1593,
V2.10 fast-mode 35/39 (INTENT_ERROR=0), canary 10/10. Audit-first sprint —
cieľom nie je dokázať, že systém je pripravený na učenie, ale zistiť,
či je. Žiadna zmena zákazníckeho recommendation/retrieval správania.
Jediná runtime zmena: úzko ohraničená oprava kontaminácie (Section 8).

## 1. Existujúca observability infraštruktúra

**`app.search_quality`** (V2.12.4): `SearchQualityTrace` (17 polí, žiadny
raw query text — len `session_hash`). Emisia cez `ContextVar` (nie
globálny stav — bezpečné pod súbežnosťou). Perzistencia: JSONL append,
storage-failure nikdy nezhodí `/chat` (overené testom, ktorý blokuje log
adresár). Anomaly detekcia je deployment-window porovnanie (nikdy
auto-akcia), tvrdé sémantické kanáre (10 prípadov) obchádzajú štatistiku
úplne. Report je **len on-demand** — žiadny scheduled job ho nespúšťa
automaticky.

**Zistená nekonzistencia**: `SEARCH_QUALITY_LOG_PATH` (na rozdiel od
baseline/canary súborov v tom istom module) NEPOUŽÍVA
`app.storage_paths.resolve_path()` — vlastný hardcoded tempdir default,
obchádza `FOODLAND_DATA_DIR` jednotný gombík, kým `SEARCH_QUALITY_LOG_PATH`
nie je explicitne nastavený.

## 2. Existujúca learning infraštruktúra

Reálny lifecycle (`app.learning_lifecycle`):
`GENERATED → OFFLINE_PASSED → SHADOW → READY_FOR_APPROVAL → ACTIVE → MONITORED`.

| Stupeň | Stav |
|---|---|
| GENERATED→READY_FOR_APPROVAL | **ACTIVE**, dosiahnuteľné len cez admin/CLI trigger, nikdy automaticky |
| ACTIVE (promócia) | **MANUAL, human-gated** — `approve_and_activate()` bezpodmienečne odmieta `approved_by` ∈ {"", "auto", "system", "automated", "bot", "cron"}, nezávisle od `AUTO_PROMOTION_ENABLED` |
| MONITORED | **DEAD_CODE** — `mark_monitored()` má 0 volaní mimo vlastných testov |
| Automatický rollback trigger | **DEAD_CODE/UNWIRED** — `check_rollback_conditions()` definovaná, testovaná izolovane, nikdy nevolaná z `run_learning_cycle()` ani background loopu |
| Manuálny rollback | **ACTIVE** — `POST /admin/learning/rollback` |

`app.ranking_optimizer`/`app.ranking_features` — **dev-CLI-only**
(`scripts/ranking_cli.py`), nikdy importované v `app/main.py`, nikdy na
customer/admin HTTP ceste.

## 3. AUTO_PROMOTION — dôkaz, nie len aktuálna hodnota

`AUTO_PROMOTION_ENABLED = os.getenv("LEARNING_AUTO_PROMOTION_ENABLED", "false")...`
(`app/learning_lifecycle.py:57`) — **jediná definícia v celom repozitári**,
čítaná raz z env, nikdy nereassignovaná. Kritické: táto premenná sa
**nekonzultuje v ŽIADNEJ podmienke nikde v `app/`** — `approve_and_activate()`'s
skutočná brána je bezpodmienečná `approved_by` kontrola, nezávislá od
tohto flagu. Je vystavená LEN read-only v `/admin/learning/status`.
**Dôkaz je štrukturálny (absencia akéhokoľvek `if`-použitia), nie len
"dnes je nastavená na false".** Test: `test_auto_promotion_disabled_by_default`.

**AUTO_PROMOTION_STATUS: `DISABLED_AND_UNCHANGED`** — nezmenené touto sprintou,
overené kódom aj testom.

## 4. Signal inventár (skrátené — plný detail v jednotlivých sekciách nižšie)

| Signál | Zdroj | Session-linked? | Durable? | Execution-context gated? |
|---|---|---|---|---|
| `question_analytics.jsonl` (log_question) | `/chat` | áno (`session_id`) | áno | **áno**, overené (3 call sites) |
| `taxonomy_shadow.jsonl` (log_taxonomy_shadow) | `/chat` | nie (client_hash only) | áno | **NIE bolo — opravené touto sprintou (Section 8)** |
| `events.jsonl` (log_event) | `POST /events` z widgetu | áno (**rovnaký** `sessionId` ako `/chat`) | áno | n/a — nič interné toto volá (viď Section 9) |
| `backend_errors.jsonl` | OpenAI/response chyby | **nie** (chýba client_hash/session_id) | áno | nie (zámerné — chyba je zaujímavá aj interne) |
| `SearchQualityTrace` | retrieval decision | čiastočne (session_hash) | áno | áno (ContextVar + explicitný re-check) |

## 5. Sémantika signálov — taxonómia

- **EXPOZÍCIA/IMPRESSION**: `impression` event (widget). NIKDY nie je
  pozitívna spätná väzba.
- **SYSTÉMOVÉ ROZHODNUTIE**: comparison/use_case/basket decision states.
  NIKDY nie je zákaznícky súhlas.
- **ZÁKAZNÍCKA INTERAKCIA**: `click`, `add_to_cart`, `autocomplete_select`,
  `feedback` (rating) — reálne, pozorovateľné.
- **ZÁKAZNÍCKY VÝSLEDOK**: `add_to_cart` je najbližšie k tomuto (viď
  Section 20). Checkout/purchase/order — **NEEXISTUJE**.
- **NEGATÍVNY/KOREKTÍVNY**: reformulácia (viď Section 16) — nespoľahlivá.
- **INTERNÝ/SYNTETICKÝ**: EVALUATION/ADMIN_TEST/SHADOW/LEARNING —
  MUSIA byť vylúčené zo zákazníckych metrík (viď Section 9 pre kritickú
  medzeru).

`impression → positive preference` = **FORBIDDEN_INFERENCE**, explicitne
nepoužité nikde v kóde.

## 6. Kauzálna atribúcia — centrálne zistenie

**Dve nezávislé, NEPREPOJITEĽNÉ log streamy**:
- `question_analytics.jsonl` — má `session_id`, `intent`, `subject`
  (napr. `decision.state` pre comparison) — **žiadne product ID**.
- `events.jsonl` — má `session_id`, `product_sku`, `position`, `query` —
  **žiadny workflow_id, decision state, reason_codes, result_set_id,
  cross_sell_role**.

Žiadny zdieľaný kľúč (`decision_id`/`turn_id`) medzi nimi. Jediné možné
offline spojenie je `session_id` + približný čas — nespoľahlivé,
keďže jedna session bežne obsahuje viac recommendation-family ťahov
(potvrdené reformulačným auditom, Section 16). **Žiadny plný
request/response transkript log (decision state + zobrazené produkty
spolu) neexistuje.**

## 7. Per-capability readiness matica

| Schopnosť | Decision state v odpovedi? | Evidence/reason/confidence? | Session link na ďalšie ťahy? | Kauzálne atribuovateľné? |
|---|---|---|---|---|
| Comparison | áno | len confidence, nie evidence/reason_codes/winner_id | áno, len pre goal-keyword follow-up | **čiastočne** (len goal follow-up), zlomené pre ordinal/klik |
| Use-case advice | áno | len confidence | **ŽIADNE** — `active_use_case` je nesúvisiaci legacy V2.9 mechanizmus | **fundamentálne zlomené** |
| Basket completion | áno, bohaté per-role | confidence per role | číta, ale nikdy nezapisuje `selected_ingredient_products` | **zlomené** — write-side slučky nikdy nezavretá týmto modulom |
| Recipe shopping | áno, bohaté per-ingredient | confidence per ingredient | **áno — jediná plne uzavretá in-session slučka** | atribuovateľné v rámci session, **nie durable** |
| Cross-sell | áno (eligible/context_type) | **áno — najbohatšie**, per-product role/reason/evidence | nesledované oddelene od primárneho result setu | zlomené pre durable atribúciu (klik neprenáša cross_sell_role) |
| Replacement products (rt0013) | **nie** | **nie**, len šablónová veta | áno cez generický result-set mechanizmus | zlomené — nerozlíšiteľné od bežného vyhľadávania na schema úrovni |
| Result-set continuation | n/a | n/a | `result_set_id` perzistuje správne | **zlomené pre produktovú úroveň** — žiadny klik nenesie `result_set_id` |
| Ramen use-case (V2.14h) | áno | rovnaké ako iné use-case role | rovnaké obmedzenia ako use_case_advice | rovnaké ako use_case_advice |

Status per capabilitu (Section 56 vokabulár):

| Capability | Status |
|---|---|
| product_search | OBSERVABLE_NOT_LEARNING_READY |
| comparison | READY_WITH_LIMITATIONS |
| recommendation_decision (agregát) | READY_WITH_LIMITATIONS |
| use_case_advice | NOT_OBSERVABLE (session link) |
| basket_completion | OBSERVABLE_NOT_LEARNING_READY |
| recipe_shopping | READY_WITH_LIMITATIONS (in-session only) |
| related_products | OBSERVABLE_NOT_LEARNING_READY |
| replacement_products | NOT_OBSERVABLE |
| cross_sell | OBSERVABLE_NOT_LEARNING_READY |
| resultset_continuation | NOT_OBSERVABLE (produktová úroveň) |

## 8. KRITICKÉ ZISTENIE: `/chat` nevie odlíšiť live smoke-test od zákazníka

`chat()` (`main.py`): `resolved_context = _customer_context() if isinstance(request, Request) else _evaluation_context()`.
**Každý HTTP request** (vrátane curl/QA/monitoring/Claude Code live
verifikácie) dorazí ako reálny `starlette.requests.Request` objekt —
`isinstance` je VŽDY `True` pre externé HTTP volanie. Neexistuje žiadne
HTTP hlavičkové pole, request field, alebo admin-token mechanizmus,
ktorý by externému volajúcemu umožnil deklarovať "toto je ADMIN_TEST/
EVALUATION". `ExecutionContext` mechanizmus je dosiahnuteľný LEN
z interných Python volajúcich (evaluation harness, ranking_shadow,
ranking_optimizer, admin canary funkcie) — nikdy cez reálny HTTP round-trip.

**Dôsledok**: každé externé HTTP volanie na `/chat` (vrátane VŠETKÝCH
live production smoke testov vykonaných v tejto aj predchádzajúcich
V2.14/rt0013 sprintách) je nerozlíšiteľné od reálneho zákazníka —
podlieha rate limitu, zapisuje do `question_analytics.jsonl`, počíta sa
ako `CUSTOMER`-mode `SearchQualityTrace`, aktualizuje session/user
memory, a počíta sa do `/admin/analytics/*` agregátov.

**Klasifikácia: `OBSERVABILITY_GAP`, NEOPRAVENÉ v tejto sprinte** —
oprava by vyžadovala novú HTTP-úrovňovú signalizáciu (napr. admin-token-
gated hlavička), čo je nová architektúra, nie úzko ohraničená oprava
(Section 52/53). Odporúčaný V2.15b kandidát.

## 9. Oprava: `log_taxonomy_shadow()` kontaminácia (jediná runtime zmena tejto sprinty)

**Nález**: `log_taxonomy_shadow()` (`main.py`) nebol NIKDY zapojený do
`execution_context` brány (predchádza `app.execution_context` — V2
catalog-first taxonomia je staršia sprinta). Na rozdiel od `log_question`
(ktorý má lokálny rebind trik), táto funkcia sa volala bezpodmienečne —
každé EVALUATION/LEARNING/SHADOW/ADMIN_TEST volanie ticho znečisťovalo
`taxonomy_shadow.jsonl` presne ako reálna zákaznícka správa.

**Charakterizácia pred opravou**: nový test
`tests/test_execution_context.py::TestExecutionContextSuppressesTaxonomyShadow`
reprodukoval kontamináciu na aktuálnom HEAD (4/5 testov FAILED pred
opravou — EVALUATION/SHADOW/LEARNING/ADMIN_TEST všetky zapisovali).

**Oprava**: `if execution_context.emit_customer_analytics:` guard,
identický vzor ako `log_question`'s existujúca brána. Žiadna zmena
zákazníckeho správania (CUSTOMER context sa správa identicky).

**Prečo toto spĺňa "Allowed Small Fix" (Section 53)**: (1) audit dokázal,
že signál tvrdil sémantiku, ktorú nemal — "len CUSTOMER sa počíta" bol
porušený invariant; (2) redukuje kontamináciu; (3) nemení zákaznícke
správanie; (4) nevytvára automatické učenie; (5) ohraničený blast radius
(1 funkcia, 1 call site); (6) charakterizačný test existoval PRED opravou.

Byte-safe editovaný (main.py má mixné CRLF/LF) — `git diff --stat` ==
`git diff --ignore-space-at-eol --stat` (9 riadkov zmenených v oboch),
`git diff --check` exit 0.

## 10. `POST /events` — nie aktívne kontaminovaný, ale štrukturálne nechránený

Overené: **žiadny interný Python volajúci nikdy nevolá `log_event()`**
mimo samotného `/events` route handlera (grep celého repozitára). Preto
dnes nie je aktívne kontaminovaný internou traffic — jediný zdroj je
reálny HTTP z widgetu. ALE na rozdiel od `/chat`, `/events` nemá ŽIADNY
mechanizmus na signalizáciu execution-context vôbec — bezpečné dnes len
preto, že nič interné ho nevolá, nie preto, že by bol strážený. Rovnaká
trieda medzery ako Section 8, menšieho rozsahu. Zdokumentované, nie
opravené (vyžadovalo by novú signalizačnú vrstvu).

## 11. Frontend/widget observability

`app/widget.js`'s jediný telemetrický kanál je `fireEvent()` → `POST /events`.
**Žiadny Google Analytics/gtag/dataLayer/Facebook pixel nikde v repozitári**
— všetka telemetria ide priamo na Foodland backend, nie do tretej strany.

| Interakcia | Stav |
|---|---|
| Product card klik ("Zobraziť") | OBSERVABLE |
| Add-to-cart klik | OBSERVABLE (click aj add_to_cart events) |
| Search submit | OBSERVABLE |
| No-result | OBSERVABLE |
| Impression (zoznam) | OBSERVABLE |
| Autocomplete select | OBSERVABLE |
| Feedback (👍/👎) | OBSERVABLE |
| **Recipe card link klik** | **NOT_OBSERVABLE** — žiadny listener |
| **Article card link klik** | **NOT_OBSERVABLE** — žiadny listener |
| **"Show more" lokálne odhalenie dávky** | **NOT_OBSERVABLE** — žiadny event |
| Comparison-špecifický výber | **NEEXISTUJE** ako vlastný event_type |

**`fireEvent()` používa PRESNE ten istý `sessionId`, aký sa posiela na
`/chat`** (`widget.js`) — toto je genuinný, silný pozitívny nález:
click/add_to_cart/feedback SÚ kauzálne prepojiteľné na konkrétnu chat
session cez zdieľaný session_id.

## 12. Reálny conversion signál — silnejší, než sa čakalo

`addToCart(product)` (`widget.js`) nie je simulácia: načíta REÁLNU
produktovú stránku foodland.sk do skrytého iframe a klikne na SKUTOČNÉ
tlačidlo "DO KOŠÍKA" tej stránky, čaká na jej vlastné AJAX potvrdenie
úspechu, až potom vystrelí `add_to_cart` event. `conversion` event_type
je **schema-definovaný, ale NIKDY nevystrelený widgetom** — mŕtvy kód,
explicitne priznaný v `app/learning_events.py`'s vlastnom docstringu.
`TRENDING_EVENT_WEIGHTS["conversion"]=8` (najvyššia váha) je preto
nedosiahnuteľná vetva.

**Skutočný "conversion-adjacent" signál = `add_to_cart`**, real, session-
linked, position-linked, durable (`events.jsonl`, potvrdené na
perzistentnom volume). Checkout/payment/order-completion krok
**NEEXISTUJE** nikde.

## 13. Pozitívna spätná väzba — politika

Kvalifikuje sa (s dôkazom):
- Explicitný `feedback` rating (👍/👎) — **jediný skutočne explicitný signál v celom systéme**.
- `add_to_cart` — silný implicitný pozitívny signál (real cart mutation).

NEKVALIFIKUJE sa (default):
- impression, systémové odporúčanie, absencia reformulácie, koniec session, "show more", follow-up otázka, produkt v result sete.

## 14. Negatívna spätná väzba — politika

| Signál | Klasifikácia |
|---|---|
| Explicitný 👎 feedback | NEGATIVE_CONFIRMED |
| `FAILURE_REFORMULATION` (rovnaká rodina, žiadna angažovanosť) | NEGATIVE_PROBABLE — ale viď Section 16 pre limity detektora |
| Hard topic switch | NOT_NEGATIVE (potvrdené: detektor to môže nesprávne označiť ako SUCCESSFUL_REFINEMENT, nikdy nie negatívne — bezpečná chyba smerom, ale stále chyba) |
| Comparison/recipe/basket follow-up | AMBIGUOUS pre generický reformulačný detektor (nevidí session_state) |
| Size/price refinement bez re-menovania produktu | AMBIGUOUS (detektor ich necháva UNCLASSIFIED, nesprávne ich neoznačuje ako negatívne — správne, ale z nesprávneho dôvodu) |

## 15. Konverzné signály

Repo-wide grep: `checkout`, `purchase`, `transaction` — **NOT_FOUND**
nikde ako kód. `order` — všetky výskyty sú o sort/rank poradí, nie
o objednávke (potvrdený presne ten "arasidy"-štýl false-positive, na
ktorý audit upozorňoval). Jediný reálny conversion-adjacent signál je
`add_to_cart` (Section 12). Basket completion (V2.14e) je odporúčacia
funkcia, NIE cart/purchase integrácia — nemá prístup k `events.jsonl`.

## 16. Reformulačná infraštruktúra — session-scoped, nie session-aware

`app.learning_signals.detect_reformulations()` pracuje čisto nad
`events.jsonl`'s `search_submit` prúdom, zoskupeným podľa `session_id`.
**Nemá ŽIADNU viditeľnosť do `app.session_state`** — nevidí
`active_comparison_pair`, `active_recipe_id`, `active_use_case`, ani
`is_bare_comparison_followup`. Klasifikácia: SUCCESSFUL_REFINEMENT (2.
dopyt dostal klik), FAILURE_REFORMULATION (rovnaká rodina, žiadna
angažovanosť), inak UNCLASSIFIED.

Konkrétne dôsledky (overené proti testom aj kódu):
- **Hard topic switch** ("jazmínová ryža"→"Shin Ramyun"): ak druhý dopyt
  dostane klik, NESPRÁVNE označené `SUCCESSFUL_REFINEMENT` (nevie
  rozlíšiť refinement od nesúvisiaceho prepnutia témy, ktoré náhodou
  uspelo).
- **Size refinement** ("jazmínová ryža"→"5kg"): `5kg` nemá family →
  `UNCLASSIFIED`, nie nesprávne penalizované, ale ani správne rozpoznané
  ako refinement.
- **Comparison/recipe/basket follow-upy**: úplne slepé miesto — rovnaká
  bucket ako obyčajný reformulovaný dopyt.

**Verdikt**: session-*scoped*, ale nie session-*aware*. Offline batch
klasifikátor, nikdy surfacovaný v `/chat` odpovedi.

## 17. Result-set continuation ("Show More")

`ResultSet` (uuid, TTL 1800s) perzistuje cez `active_result_set_id` a
skutočne kontinuuje rovnaký server-side kandidátny zoznam. ALE: žiadny
klik/add_to_cart event nenesie `result_set_id`, číslo stránky, alebo
príznak "z prvej stránky vs. Show More stránky". `resolve_resultset_continuation_signal()`
(`app.turn_resolver`) je **definovaná, ale NIKDY nevolaná nikde v bežiacej
aplikácii** — mŕtvy kód, reálna Show-More cesta ju obchádza úplne.

## 18. Execution-context izolácia — mechanizmus a pokrytie

5 módov (`CUSTOMER/EVALUATION/LEARNING/SHADOW/ADMIN_TEST`), jedno pole
(`emit_customer_analytics`) na `ExecutionContext` dataclass. **3 nezávislé
gating implementácie** pre rovnaké rozhodnutie existujú dnes (lokálny
rebind v `_chat_impl()`, `_chat_internal()`'s vlastný re-check pred
`SearchQualityTrace`, `workflow_executor.py`'s per-call-site guardy) —
konzistentné dnes, ale vyžadujú, aby si niekto pamätal aktualizovať
všetky tri pri budúcom pridaní loggingu (rovnaký typ rizika, aký
spôsobil V2.13d bug).

**Test pokrytie pred touto sprintou**: EVALUATION/SHADOW/LEARNING
end-to-end overené pre `question_analytics.jsonl`; **ADMIN_TEST chýbal**
v tejto konkrétnej end-to-end triede (len štrukturálne, cez dataclass
pole) — doplnené touto sprintou (Section 9/tento dokument, nová
`test_admin_test_context_never_writes_question_analytics`).

## 19. Cross-session izolácia

Nezávisle overená pre recipe_shopping (`selected_ingredient_products`
je keyovaný `session_memory_key` = kombinácia session_id+client_key,
žiadny zdieľaný mutable stav naprieč session objektmi — rovnaký vzor,
aký V2.13b.1 už dokázal pre `contextualize_message()`). Basket/use-case/
comparison session state (`app/session_state.py`) rovnako per-session
keyované — žiadny nový cross-session zdieľaný stav objavený touto
sprintou.

## 20. Durable storage — zhrnutie

| Položka | FOODLAND_DATA_DIR-aware? | Atomický zápis? |
|---|---|---|
| question_analytics/backend_errors/taxonomy_shadow/events.jsonl | áno | nie (append) |
| user_memory.json | áno | áno |
| search_quality.jsonl | **NIE** (vlastný hardcoded default) | nie |
| events.jsonl (READ strana: behavioral.py/fbt.py/learning_events.py) | **NIE** — každý nezávisle hardcoduje vlastný tempdir default | n/a |
| product_embeddings.json | nie | nie (plain overwrite) |
| config/ranking_profiles/*.json | podmienene (len ak FOODLAND_DATA_DIR nastavené) | áno |

**Reálne riziko zistené**: `log_event()` (writer) a `behavioral.py`/
`fbt.py`/`learning_events.py` (readers) sa dnes zhodujú LEN preto, že
`EVENTS_LOG_PATH` je explicitne nastavený v Railway (potvrdené pamäťou
z 2026-08-18). Keby operátor niekedy konsolidoval len na
`FOODLAND_DATA_DIR` a odstránil redundantný `EVENTS_LOG_PATH`, writer by
začal písať na nové miesto, kým readery by ticho čítali z prázdnej
ephemeral cesty — bez chyby, tiché nulovanie FBT/behavioral/reformulačných
signálov. Zdokumentované, neopravené (mimo úzkeho rozsahu tejto sprinty).

Žiadna rotácia/retencia logov nikde — neobmedzený rast (žiadny doklad
tvrdí opak, takže nejde o porušený sľub, len o medzeru).

## 21. Duplicitné/idempotency riziko

Žiadny `request_id`/nonce na `/chat` ani `/events`. Klient nemá retry
logiku (`fetch` bez retry, `.catch` len potichu zahodí chybu), ale
sieťový výpadok PO úspešnom serverovom spracovaní + manuálne opätovné
odoslanie by vyprodukovalo nerozlíšiteľný duplicitný záznam. Tenacity
retry na OpenAI volaní je plne vnútri `_call_openai_with_retry()` —
`log_question()` sa volá presne raz na request bez ohľadu na počet
interných retry pokusov (nekontaminuje).

## 22. Recommendation evidence linkage

`app.recommendation_evidence`'s `EvidenceItem`/`reason_codes`/`confidence`
NIKDY nedosiahne perzistovaný event alebo dokonca celý `/chat` response
dict pre 4 z 6 modulov (use_case_advice, replacement_products majú
najhoršie pokrytie). Basket completion je NAJLEPŠIE inštrumentovaný
(per-role status+confidence v odpovedi). Cross-sell má NAJBOHATŠIE
per-produktové značenie (`cross_sell_role`/`reason`/`evidence`), ale
toto sa stráca v okamihu kliku (klik event nenesie tieto polia).

**Samostatný, staršpecifický "recommendation_reason" systém** (legacy,
`main.py`) — generický, keyword-bucket šablónový text (napr. "Je to
praktický doplnok...") pre `related_products`/`replacement_products`/
`product_search`/`article_products`/`recipe_to_products`. NIE prepojený
s V2.14a evidence primitívom vôbec — dva úplne oddelené "prečo" systémy
existujú súbežne.

## 23. rt0013 replacement quality limitation — potvrdené, nerozšírené

Zachovaná rt0013 uzávierka bez opätovného otvorenia. `"vegan"` v takomto
dopyte NEfunguje ako deterministické obmedzenie (identický zoznam
kandidátov s/bez neho) — budúce učenie NESMIE interpretovať prítomnosť
slova "vegan" ako dôkaz, že vrátené produkty spĺňajú vegan obmedzenie.

## 24. Bare "ramen" architektonický dlh — nedotknuté

Žiadna zmena query routingu. Žiadny spoľahlivý produkčný signál
(reformulačný detektor by tento prípad klasifikoval nespoľahlivo, viď
Section 16) momentálne existuje na kvantifikáciu tejto nejednoznačnosti.
Zostáva evidence-gated architektonická otázka.

## 25. Qualitative "best" dlh — nedotknuté

Nepokúšané implementovať. Slabé engagement signály (klik/add_to_cart)
NESMÚ byť interpretované ako dôkaz kvality/chuti/autenticity — žiadny
mechanizmus v tomto systéme robí alebo by mal robiť takýto skok.

## 26. Learning Label Candidate Matrix

| Kandidát | Zdroj | Kauzálna sila | Kontaminačné riziko | Perzistencia | Status |
|---|---|---|---|---|---|
| `recommendation_impression` | widget `impression` | nízka (nie je preferencia) | nízke | áno | QUALITY_MONITORING only |
| `recommendation_selected` (klik) | widget `click` | stredná (position-linked) | nízke | áno | WEAK_LABEL_ONLY |
| `recommendation_rejected` | neexistuje explicitne | n/a | n/a | n/a | FORBIDDEN_INFERENCE ak odvodené z absencie kliku |
| `recommendation_reformulated` | `detect_reformulations()` | **nízka** — konfunduje topic-switch/refinement/follow-up | stredné-vysoké | áno (offline) | NEVER_USE_FOR_LEARNING bez ďalšej práce |
| `comparison_followup` | `active_comparison_pair` + goal marker | stredná, len pre uznané frázy | nízke | nie (session-only) | OFFLINE_ANALYSIS |
| `basket_completion_followup` | `selected_ingredient_products` | vysoká keď existuje, ale basket_completion ju nikdy nezapisuje | n/a | nie | NOT_READY (write-side chýba) |
| `product_clicked` | widget `click` | vysoká (session+position) | nízke | áno | WEAK_LABEL_ONLY |
| `product_added_to_cart` | widget `add_to_cart`, real cart mutation | **najvyššia dostupná** | nízke (real AJAX-confirmed) | áno | TRAINING_LABEL kandidát (s výhradami zo Section 6) |
| `purchase_attributed` | NEEXISTUJE | n/a | n/a | n/a | NEEXISTUJE |
| `zero_result_recovery` | `no_result` event + nasledujúci dopyt | stredná | stredné | áno | OFFLINE_ANALYSIS |
| `clarification_resolved` | CLARIFY je customer-facing nedosiahnuteľný vo väčšine modulov | n/a | n/a | n/a | NOT_APPLICABLE |
| `abstain_followup` | žiadny explicitný mechanizmus | n/a | n/a | n/a | UNOBSERVED |

## 27. Ranking learning readiness: **NOT_READY**

Nemožno spoľahlivo rozlíšiť "zobrazené, ale ignorované" od "nikdy
nezobrazené" (klik events nenesú `result_set_id` ani úplný candidate
set). Position bias korekcia EXISTUJE (`app.learning_signals`'
position-normalized lift, `[0.5,2.0]` clamp) ale je postavená na
neúplnom impression→click reťazci (žiadny cross_sell/replacement/
use-case tag na kliku).

## 28. Recommendation learning readiness: **PARTIAL**

Comparison/basket/recipe majú aspoň DECISION STATE v odpovedi; cross-sell
má najbohatšie per-produktové dôkazy. Ale ŽIADNY z nich má durable,
uzavretú slučku (decision → shown → customer reaction, spojiteľné jedným
kľúčom). Recipe shopping je najbližšie k READY (in-session), ale
nepretrváva.

## 29. rt0004/rt0010/rt0011/rt0013 — kontrolné overenie

Všetky štyri zostávajú nedotknuté touto sprintou (žiadna zmena routingu).
Overené naživo (Section "Live Control Matrix" nižšie).

## 30. Zhrnutie testov

Nové/aktualizované: `tests/test_execution_context.py` — 5 nových testov
(`TestExecutionContextSuppressesTaxonomyShadow`) + 1 nový test
(`test_admin_test_context_never_writes_question_analytics`). Žiadny
existujúci test oslabený.

## 31. Definícia zvyšného dlhu (kategorizovaný)

- **OBSERVABILITY_GAP (najzávažnejšie)**: `/chat` nevie odlíšiť smoke-test
  od zákazníka (Section 8). Vyžaduje V2.15b architektonickú prácu.
- **OBSERVABILITY_GAP**: žiadny zdieľaný kľúč medzi `question_analytics.jsonl`
  a `events.jsonl` (Section 6).
- **OBSERVABILITY_GAP**: `resolve_resultset_continuation_signal()` mŕtvy
  kód, žiadny klik nesie `result_set_id`.
- **OBSERVABILITY_GAP**: `use_case_advice`/`replacement_products` majú
  nulové session prepojenie.
- **ARCHITECTURAL**: reformulačný detektor session-scoped, nie
  session-aware — konfunduje topic-switch/refinement/recommendation-family
  follow-up.
- **ARCHITECTURAL**: `EVENTS_LOG_PATH` roztrieštená cesta (4 nezávislé
  hardcoded defaulty), funguje len vďaka explicitnej env var zhode.
- **DATA**: `conversion` event_type schema-definovaný, nikdy nevystrelený.
- **SEMANTIC-HUMAN**: rt0013 replacement quality limitation (Section 23),
  qualitative "best" (Section 25), bare ramen (Section 24) — všetky
  nedotknuté, čakajú na produktové/dátové rozhodnutia mimo tejto sprinty.
- **LEARNING-OBSERVABILITY**: `MONITORED` stav a automatický rollback
  trigger sú definované, testované izolovane, ale nikdy nezapojené do
  reálneho behu.

## 32. V2.15b odporúčanie

**`V2.15b — Signal Persistence & Normalization`** (nie Learning Candidate
Pipeline). Dôvod: kľúčové medzery sú štrukturálne (chýbajúci zdieľaný
kľúč, chýbajúca execution-context signalizácia na HTTP úrovni, roztrieštené
cesty) — pred akýmkoľvek pokusom o učenie musí existovať spôsob, ako
1) bezpečne odlíšiť internú od zákazníckej HTTP prevádzky, a 2) spojiť
decision-level dáta s product-level engagement jedným kľúčom.
