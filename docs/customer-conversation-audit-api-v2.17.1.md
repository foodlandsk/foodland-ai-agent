# Customer Conversation Read-Only Audit API (V2.17.1)

Dátum: 2026-09-02. Baseline commit: `9ec17e1c894f5641f0fc3de860e7284cdb359914`.

## 1. Účel

Read-only, privacy-conscious observability vrstva: umožňuje operátorovi
nahliadnuť do REÁLNEJ zákazníckej konverzácie spolu so SKUTOČNOU
štruktúrou odpovede, akú Foodland AI zákazníkovi zobrazila — čo sa
zákazník pýtal, čo backend pochopil, čo odpovedal, ktoré skupiny
produktov vrátil a ktoré korelačné identifikátory (interaction_id/
decision_id/result_set_id) k tomuto ťahu patria.

## 2. Čo toto NIE JE

Nie je to learning sprint, evaluátor, ani generátor tréningových
labelov. `capture_customer_turn()` len POZORUJE už dokončenú odpoveď —
nikdy neopakuje intent/search/ranking/cross-sell/LLM. Nezapisuje sa do
rankingu/learningu/promotion. `AUTO_PROMOTION` zostáva `FALSE`.

## 3. Hranica ľudského vyšetrovania

Audit API je nástroj pre ČLOVEKA, ktorý vyšetruje konkrétny prípad
(sťažnosť, podozrivú odpoveď, otázku "čo videl tento zákazník?") —
nie automatizovaný pipeline. Žiadny záznam sa automaticky nekonvertuje
na kvalitatívny label (impression != preferencia, click !=
odporúčaná kvalita, atď. — Section 4 špecifikácie).

## 4. Privacy model

Znovupoužité, overené mechanizmy projektu — žiadny konkurenčný privacy
model:
- `app.main.redact_pii()` (email/telefón regex redakcia) — aplikovaná
  na `question`/`answer` PRED perzistenciou.
- Rovnaký salted-hash vzor ako `log_question()`/`log_event()`:
  `sha256(f"{salt}:audit:{identity}")[:24]`, salt z `ANALYTICS_SALT`.
  Salt sa nikdy neexponuje.

## 5. PII redakcia

`_redact()` v `app/customer_audit.py` volá `app.main.redact_pii()`
lazy importom (rovnaký vzor ako `app.advisor_engine`'s deferred
`import app.main` — modul zostáva ľahký a importovateľný samostatne
bez nutnosti načítať celý katalóg). Redakcia prebieha PRED zápisom,
nikdy "vyčistiť neskôr".

## 6. Conversation hashing (Section 9)

`conversation_hash = sha256(f"{salt}:audit:{session_id alebo client:client_key}")[:24]`.
`session_id` má prednosť; `client_key` (IP-odvodený) je len fallback
pre prázdny `session_id`. Nikdy sa neukladá surový identifikátor vedľa
hashu. Účel: zoskupiť ťahy tej istej konverzácie, NIE identifikovať
konkrétneho človeka.

## 7. Uložené polia

```json
{
  "ts": 1788373871,
  "conversation_hash": "...",
  "question": "...",
  "answer": "...",
  "status_code": 200,
  "latency_ms": 84.2,
  "interaction_id": "...",
  "decision_id": "...",
  "result_set_id": "...",
  "intent": "product_search",
  "workflow_id": "LEGACY_FALLBACK",
  "response_mode": "result_set",
  "has_more": true,
  "matching_total": 12,
  "displayed_count": 4,
  "cross_sell_eligible": true,
  "product_groups": {
    "products": [...],
    "cross_sell": [...]
  }
}
```

`decision_id` je normalizovaný z prvého prítomného z
`comparison_decision_id`/`use_case_advice_decision_id`/
`basket_decision_id`/`recipe_shopping_decision_id` — čistý dict-lookup,
žiadna business logika sa nespúšťa znova (Section 7 to explicitne
povoľuje).

## 8. Zámerne NEuložené polia

Surová IP, surové `client_id`, surové `session_id`, cookies, hlavičky,
authorization/admin tokeny, celý `conversation_history`, systémové
prompty, LLM prompty, secrets, hodnoty environment premenných, ľubovoľné
metadáta requestu, plné product objekty (len explicitný allowlist),
`cross_sell_evidence` (interná evidence štruktúra).

## 9. Sémantika skupín produktov (GUARD 1)

Skutočná schéma `/chat` odpovede NEMÁ samostatné polia `alternatives`/
`substitutes`/`replacement_products` — tieto koncepty sú nesené poľom
`intent` (napr. `intent="replacement_products"`), nie samostatnými
poľami. Audit preto verne reprezentuje realitu: `product_groups.products`
(primárne zhody, sémantika daná `intent`) a `product_groups.cross_sell`
(oddelené, nikdy zlúčené) — presne to jediné skutočné oddelenie, ktoré
backend robí. Žiadne vymyslené polia, ktoré aktuálna odpoveď
neexponuje (Section 7: "repository reality wins").

Cross-sell sa NIKDY prekopíruje do `products` a NIKDY sa v audit module
prehodnocuje/preraďuje — `_summarize_product_group()` len filtruje na
allowlist a orezáva na 24 produktov, poradie a členstvo preberá 1:1
z už-dokončenej odpovede.

## 10. Stock/availability sémantika (GUARD 2)

Surové pole `availability` (napr. `"in_stock"`) sa ukladá NEINTERPRETOVANÉ,
presne ako ho backend má. Audit vrstva ho NIKDY nekonvertuje na
"Skladom"/"confirmed in stock"/"live stock available" — zachováva V2.17
sémantiku (`"Dostupné na Foodland.sk"` = katalógová dostupnosť, nie
overená skladová zásoba).

## 11. READ-scope autorizácia

Oba nové endpointy používajú existujúci `app.admin_auth.require_admin_scope()`
s `SCOPE_READ` — rovnaký mechanizmus ako každý iný `/admin/analytics/*`
GET endpoint. Žiadny nový autentifikačný systém.

## 12. Storage path

`app.storage_paths.resolve_path("CUSTOMER_AUDIT_LOG_PATH", "customer_audit.jsonl")`
— nasleduje `FOODLAND_DATA_DIR`, keď je nakonfigurovaný, presne ako
`events.jsonl`/`question_analytics.jsonl` a ostatné runtime logy.

## 13. FOODLAND_DATA_DIR správanie

Keď je `FOODLAND_DATA_DIR` nastavený (napr. Railway volume), audit log
sa automaticky presunie pod tento trvalý zväzok. Keď nie je nastavený,
správanie je identické ako pred touto sprintou (dočasný adresár) — bez
zmeny lokálneho vývoja/CI.

## 14. Parametre endpointov

`GET /admin/audit/conversations`: `days` (1–90, default 7), `limit`
(1–500, default 100), `conversation_hash` (presná zhoda), `intent`
(case-insensitive presná zhoda), `q` (case-insensitive substring cez
`question`/`answer`, žiadny regex, žiadny filesystem prístup).

`GET /admin/audit/status`: bez parametrov.

## 15. Izolácia zlyhania (Section 19)

`capture_customer_turn()` je celá obalená v `try/except` (nikdy
nevyhodí výnimku) a volajúce miesto v `_chat_internal()` má DRUHÚ,
redundantnú `try/except` vrstvu — rovnaký double-safety vzor, aký už
`_record_search_quality_trace()` používa. Zlyhanie zápisu (napr.
neprístupný disk) nikdy nezmení HTTP status, obsah odpovede, ani
nevytvorí duplicitnú odpoveď/event. Overené testom (blokujúca cesta
namiesto adresára → `/chat` stále vracia 200 s nezmeneným obsahom).

## 16. interaction_id / decision_id / result_set_id

Preberané priamo z už-dokončenej `response` dict (rovnaké hodnoty, aké
zákazník/frontend dostal) — nikdy nový/vymyslený identifikátor.

## 17. Stav engagement korelácie

**FOUNDATION_ONLY.** V2.17.1 zámerne NEpridáva `clicked_product_skus`/
`add_to_cart_*`/`feedback` polia do audit záznamu — Section 17
špecifikácie to nerobí release-blockerom a explicitne povoľuje odložiť
to na budúcu sprintu, ak by si to vyžadovalo riskantnú architektúru
alebo duplicitné ukladanie eventov. Existujúci `events.jsonl` (cez
`interaction_id`/`decision_id`/`result_set_id`) je teoreticky
korelovateľný, ale táto sprinta to nerobí, aby zostala v minimálnom,
evidence-justified rozsahu.

## 18. Retencia

**ŽIADNA AUTOMATICKÁ RETENČNÁ POLITIKA V2.17.1.** Žiadny purge endpoint
nebol vytvorený (Section 16 to explicitne zakazuje). Budúca retencia je
samostatné privacy/operations rozhodnutie mimo rozsahu tejto sprinty.

## 19. Výkon

Nulové nové externé sieťové volania, nulové nové LLM volania, nulové
nové search volania. Jeden bounded append operation per dokončený
CUSTOMER ťah. Filtrovanie pri čítaní je bounded (`days`≤90, `limit`≤500).

## 20. Bezpečnosť/trust

`scripts/trust_audit.py` beží čisto (0 PII únikov). Nový endpoint
nevystavuje systémové prompty, prompt šablóny, interný kontext, ani
environment premenné. Vracia JSON (nie HTML), takže XSS downstream
rendering rizika sú na zodpovednosti budúceho admin dashboardu, nie
tejto API vrstvy.

## 21. Testy

`tests/test_customer_audit_v2_17_1.py` — 47 testov pokrývajúcich
všetkých 44 požadovaných prípadov zo Section 21 špecifikácie (capture
izolácia podľa execution context, PII redakcia, privacy exkluzie,
conversation hashing, product allowlist, GUARD 1/2/3 sémantika,
failure isolation, admin autorizácia, query parametre, malformed JSONL
handling, newest-first ordering).

## 22. Produkčné použitie

Operátor s READ-scope admin tokenom môže:
```
GET /admin/audit/status
GET /admin/audit/conversations?days=1&limit=20
GET /admin/audit/conversations?conversation_hash=<hash>
GET /admin/audit/conversations?q=bezlepok
```

## 23. Budúca Admin Dashboard integrácia

Mimo rozsahu tejto sprinty (Section 38 to explicitne zakazuje ako
release blocker). Budúci dashboard by mohol zobraziť: čas, otázku,
odpoveď, intent, workflow, product_groups, a (po budúcej explicitnej
sprinte) engagement koreláciu.
