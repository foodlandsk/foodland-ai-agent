# Production Relevance Monitoring — Runbook (V2.12.4)

Dátum: 2026-08-20. Doplnok k `docs/search-quality-observability.md`
(architektúra/schéma) — tento dokument je operačný runbook (Section 117).

## Ako skontrolovať aktuálny stav

```bash
curl -H "x-admin-token: $ADMIN_READ_TOKEN" \
  https://<prod>/admin/search-quality/status
```

Vráti: `production_quality_baseline_present`, `last_canary_ran_at`,
`last_canary_all_passed`, `active_ranking_config`. Verejné `/health`
(bez tokenu) má zúženú, bezpečnú verziu (`search_quality_monitor_enabled`,
`last_quality_report_status`, `last_canary_status`,
`production_quality_baseline_present`) — nikdy anomaly detail.

## Ako vygenerovať report

```bash
curl -H "x-admin-token: $ADMIN_READ_TOKEN" \
  "https://<prod>/admin/search-quality/report?days=1"
```

Lacná operácia (READ scope) — číta už zalogované `search_quality.jsonl`
traces a agreguje na mieste, nespúšťa žiadne retrieval volania. Ak
`current.overall.status == "INSUFFICIENT_DATA"`, report to hovorí
priamo — **nikdy nefabrikuje záver** pri nízkom objeme.

## Ako spustiť canary

```bash
curl -X POST -H "x-admin-token: $ADMIN_OPERATIONS_TOKEN" \
  https://<prod>/admin/search-quality/run
```

Vyžaduje OPERATIONS scope (drahšia, stavovú operáciu — ukladá výsledok).
Beží cez skutočný `_chat_internal()` v `ADMIN_TEST` kontexte — **nikdy**
nekontaminuje zákaznícke metriky (overené `TestCanaryExecutionContextIsolation`,
30 opakovaných behov v teste bez jediného customer trace záznamu).

Lokálne/CI ekvivalent:

```bash
python scripts/run_search_quality_canary.py          # čitateľný výstup
python scripts/run_search_quality_canary.py --json    # strojovo čitateľné
```

## Ako preskúmať anomálie

```bash
curl -H "x-admin-token: $ADMIN_READ_TOKEN" \
  "https://<prod>/admin/search-quality/anomalies?days=1"
```

Každá anomália má `type`/`severity`/`current_value`/`baseline_value`/
`delta`/`sample_size`/`confidence`/`evidence`. `severity=CRITICAL` z
`WRONG_FAMILY_LEAKAGE`/`CANARY_SEMANTIC_FAILURE` je vždy tvrdý invariant
(nezávisí od vzorky) — vyžaduje okamžitú kontrolu. `WARN`/`CRITICAL` z
rate-based typov (`LEGACY_FALLBACK_SPIKE`, `NO_RESULT_SPIKE`,
`UNKNOWN_FALLBACK_SPIKE`) vyžadujú aspoň `SEARCH_QUALITY_MIN_SUPPORT_ANOMALY`
(default 50) vzoriek — inak sa vôbec nevygenerujú.

## Ako porovnať nasadenia (deployment comparison)

1. Po nasadení, ktoré sa má stať novým baseline, počkaj na dostatočný
   pozorovací okno (Section 105/106 — nie automaticky, ľudské
   rozhodnutie).
2. `GET /admin/search-quality/report` → over `sample_size` a
   `current.overall.status == "OK"`.
3. Ak akceptovateľné (žiadne CRITICAL anomálie, kritické canary prešli):
   `save_quality_baseline(metrics, deployment_version=..., ranking_config_version=...)`
   — zatiaľ len cez priame Python volanie (žiadny dedikovaný "promote"
   admin endpoint v tomto sprinte — zámerne, Section 57: promócia je
   kontrolované rozhodnutie, nie samoobslužné tlačidlo bez preskúmania).
4. Ďalší `GET /admin/search-quality/report` odteraz porovnáva voči tomuto
   baseline automaticky (`detect_anomalies` sa spustí zakaždým, keď
   baseline existuje a current je `OK`).

## Ako rozlíšiť INSUFFICIENT_DATA od PASS/FAIL

`status` pole je vždy jedno z `OK`/`INSUFFICIENT_DATA` — nikdy
`PASS`/`FAIL` samo o sebe (to je len pre canary `passed` bool).
`INSUFFICIENT_DATA` znamená doslova "nedosť dát na záver", nie
"zlyhanie" ani "úspech" — traktuj ho ako "skús znova neskôr s väčším
`days` oknom alebo počkaj na viac prevádzky".

## Ako overiť úložisko monitoringu

```bash
curl -H "x-admin-token: $ADMIN_READ_TOKEN" \
  https://<prod>/admin/search-quality/status
```

`production_quality_baseline_present: false` pred prvou manuálnou
promóciou je OČAKÁVANÉ, nie chyba. Ak zápis do `search_quality.jsonl`
zlyhá (napr. FOODLAND_DATA_DIR nedostupný), zákaznícky `/chat` **naďalej
funguje bezo zmeny** (overené `TestStorageFailureDoesNotBreakServing`) —
monitoring len tichým spôsobom degraduje (žiadne nové traces), nikdy
neblokuje request.

## Post-deploy postup (Section 106/107)

1. Nasadenie gatuje na: V2.10 offline eval + hard canary + technický
   health (`/health`) — **nie** na zákazníckych behaviorálnych
   metrikách (tie potrebujú čas na nahromadenie).
2. Po propagácii nasadenia (Railway delay — over `/health` opakovane s
   odstupom, nie hneď) spusti `POST /admin/search-quality/run`.
3. Skontroluj `canary_all_passed`. Akékoľvek `CRITICAL` = zastav a over
   pred pokračovaním.
4. Až POTOM začni bežné pozorovacie okno pre behaviorálny report.
