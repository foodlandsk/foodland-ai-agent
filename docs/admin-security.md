# Trojúrovňová admin autorizácia — Sprint V2.12.1 Part B

Dátum: 2026-08-19.

## Problém, ktorý táto časť rieši

Pred týmto sprintom malo všetkých 14 `/admin/*` endpointov jednu plochú
kontrolu: `ADMIN_ANALYTICS_TOKEN` ALEBO `ADMIN_RELOAD_TOKEN`, obe rovnako
oprávnené na čokoľvek. Token vydaný čisto na čítanie analytics dashboardu
mal presne rovnaký dosah ako token, ktorý (po Part C) môže promovať
learning kandidáta do produkčného ranking configu — nebolo možné vydať
read-only prístup bez toho, aby ste zároveň vydali promotion power.

## Tri úrovne, hierarchicky (`app/admin_auth.py`)

| Scope | Význam | Kto z legacy tokenov |
|---|---|---|
| `READ` | Čítanie analytics/learning statusu/histórie. Žiadny vedľajší efekt. | `ADMIN_ANALYTICS_TOKEN` |
| `OPERATIONS` | Spustenie feed refresh, embeddings rebuild, learning-cycle run. Reálna práca, ale NIKDY nepresúva `config/ranking_profiles/active.json`. | `ADMIN_RELOAD_TOKEN` |
| `PROMOTION` | Schválenie kandidáta alebo rollback. Jediný scope, ktorý mení, čo je živé pre reálnych zákazníkov. | žiadny legacy token |

Vyššia úroveň automaticky spĺňa nižšiu (numerický rank:
`READ=1, OPERATIONS=2, PROMOTION=3`, `require_admin_scope()` porovnáva
`rank[granted] >= rank[required]`). Token nastavený vo viacerých env
premenných naraz sa vyhodnotí na svoj NAJVYŠŠÍ scope, nikdy nižší.

`ADMIN_PROMOTION_TOKEN` je úplne nová premenná — žiadny existujúci
(legacy) token ju nikdy nezíska automaticky. Toto je zámerne
jednosmerná migrácia: existujúce nasadenie s iba `ADMIN_ANALYTICS_TOKEN`/
`ADMIN_RELOAD_TOKEN` funguje bez zmeny (obe zostávajú presne pri svojom
pôvodnom rozsahu), ale nikto nezíska promotion oprávnenie, ktoré si
explicitne nevyžiadal.

## Chybové kódy

- **404** — žiadny admin token nie je vôbec nakonfigurovaný (rovnaké
  správanie ako pred týmto sprintom — endpoint sa tvári, že neexistuje).
- **401** — predložený token nesedí so žiadnym nakonfigurovaným tokenom.
- **403** — predložený token je platný, ale na nižší scope, než endpoint
  vyžaduje.

## Endpoint → scope mapovanie (všetkých 16, vrátane Part C)

| Endpoint | Metóda | Scope | Prečo |
|---|---|---|---|
| `/admin/analytics/summary` | GET | READ | len čítanie |
| `/admin/analytics/top-questions` | GET | READ | len čítanie |
| `/admin/analytics/no-results` | GET | READ | len čítanie |
| `/admin/analytics/intents` | GET | READ | len čítanie |
| `/admin/analytics/tasks` | GET | READ | len čítanie |
| `/admin/analytics/events-summary` | GET | READ | len čítanie |
| `/admin/analytics/behavioral-rankings` | GET | READ | len čítanie |
| `/admin/analytics/fbt-pairs` | GET | READ | len čítanie |
| `/admin/learning/status` | GET | READ | len čítanie |
| `/admin/learning/candidates` | GET | READ | len čítanie |
| `/admin/learning/history` | GET | READ | len čítanie |
| `/admin/embeddings/rebuild` | POST | OPERATIONS | mení stav (embeddings), stojí OpenAI $ |
| `/admin/feed/refresh` | POST | OPERATIONS | mení in-process katalóg/index |
| `/admin/learning/run-cycle` | POST | OPERATIONS | zapisuje report + ledger, ale dosiahne max `READY_FOR_APPROVAL`, nikdy `ACTIVE` |
| `/admin/learning/candidates/{id}/approve` | POST | **PROMOTION** | jediná cesta, ktorá mení `active.json` |
| `/admin/learning/rollback` | POST | **PROMOTION** | rovnako citlivé ako promócia |

## Testovacia matica (`tests/test_admin_auth.py`, `tests/test_learning_approval_endpoints.py`)

17 testov pre `app.admin_auth` samostatne (žiadny token → 404 na
každom scope; READ token → READ prejde, OPERATIONS/PROMOTION 403; rovnako
pre OPERATIONS a PROMOTION tokeny; legacy tokeny mapované správne;
nesprávny/chýbajúci token → 401; rovnaká hodnota v dvoch env premenných
naraz sa vyhodnotí na vyšší scope). Plus 4 end-to-end testy pri
approve/rollback endpointoch overujúce, že READ aj OPERATIONS token sú
explicitne odmietnuté s 403 pri pokuse o promóciu.

## Ako vydať nový token (Railway)

1. Vygenerujte náhodný secret (napr. `openssl rand -base64 32`).
2. Nastavte príslušnú env premennú v Railway dashboarde:
   `ADMIN_READ_TOKEN`, `ADMIN_OPERATIONS_TOKEN`, alebo
   `ADMIN_PROMOTION_TOKEN`.
3. Redeploy nie je potrebný okamžite pre kontrolu existencie (`any_admin_
   token_configured()` sa vyhodnocuje za behu z `os.getenv()`), ale
   Railway aj tak reštartuje proces pri zmene env premennej.
4. Volajte s hlavičkou `X-Admin-Token: <secret>`.

Odporúčanie: `ADMIN_PROMOTION_TOKEN` dajte iba osobám, ktoré majú reálne
schvaľovať/rollbackovať ranking zmeny — pozri
`docs/learning-approval-lifecycle.md`.
