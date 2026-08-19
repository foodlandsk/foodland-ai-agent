# Learning Engine — prevádzkový runbook — Sprint V2.12.1

Dátum: 2026-08-19.

Praktický návod pre ops/on-call osobu. Predpokladá `ADMIN_READ_TOKEN`/
`ADMIN_OPERATIONS_TOKEN`/`ADMIN_PROMOTION_TOKEN` už nakonfigurované
(pozri `docs/admin-security.md`) a `$HOST` = produkčná URL.

## 1. Overenie trvalého úložiska po deployi

```bash
curl "$HOST/health" | jq .durable_storage
```

Skontrolujte:
- `foodland_data_dir_configured` má byť `true` v produkcii.
- `ranking_profile_dir_uses_git_tracked_default` má byť `false` — ak je
  `true`, akákoľvek promócia sa pri ďalšom redeploy stratí (vráti sa na
  commitnutý `v1`). Oprava: nastavte `FOODLAND_DATA_DIR` (alebo priamo
  `RANKING_PROFILE_DIR`) na cestu pod pripojeným Railway volume.
- `learning_history_dir_uses_unmounted_default` má byť `false` — ak je
  `true`, `ledger.jsonl`/`last_known_good.json`/`candidates.jsonl` sa pri
  redeploy vyprázdnia (stratený audit trail aj rollback target).
- `active_ranking_profile_degraded` má byť `false`. Ak je `true`, pozri
  sekciu 4 nižšie.

Po zmene `FOODLAND_DATA_DIR` v Railway dashboarde spravte reálny
redeploy (nie len restart) a znova skontrolujte — pozri sekciu 5 pre
rozdiel medzi restart/redeploy testom.

## 2. Spustenie learning cyklu manuálne

```bash
curl -X POST "$HOST/admin/learning/run-cycle?full=true" -H "X-Admin-Token: $OPS_TOKEN"
```

`full=true` = kompletná V2.10 evaluačná sada (pomalšie, presnejšie);
bez neho beží len critical-case rýchla verzia (default pre periodický
job, ak `LEARNING_CYCLE_MINUTES > 0`).

## 3. Kontrola a schválenie kandidáta

```bash
# Kandidáti z posledného cyklu
curl "$HOST/admin/learning/candidates" -H "X-Admin-Token: $READ_TOKEN" | jq .

# Aktuálny stav (aktívna verzia, last_known_good, auto-promotion flag)
curl "$HOST/admin/learning/status" -H "X-Admin-Token: $READ_TOKEN" | jq .

# Schválenie (POZOR: expected_current_config_version = "active_ranking_config"
# z /admin/learning/status práve teraz - ak sa medzičasom zmenila, endpoint
# vráti 409, nie tichú promóciu na niečo iné, než ste videli)
curl -X POST "$HOST/admin/learning/candidates/<ID>/approve" \
  -H "X-Admin-Token: $PROMOTION_TOKEN" -H "Content-Type: application/json" \
  -d '{"approved_by": "vase.meno", "expected_current_config_version": "v1"}'
```

Odpoveď `"status": "already_active"` znamená, že kandidát je už
aktívny (bezpečný no-op, typicky pri dvojkliku).
Odpoveď HTTP 409 znamená buď neznáme ID, alebo stale
`expected_current_config_version` — pred opakovaním si znova pozrite
`/admin/learning/status`.

## 4. Rollback

```bash
curl -X POST "$HOST/admin/learning/rollback" \
  -H "X-Admin-Token: $PROMOTION_TOKEN" -H "Content-Type: application/json" \
  -d '{"reason": "popis problému", "triggered_by": "vase.meno"}'
```

`"status": "no_op"` = žiadny `last_known_good` záznam (nič sa
nepromovalo od posledného čistého štartu — nie je čo vrátiť).
`"status": "rolled_back"` obsahuje `profile_version`, na ktorú sa
vrátilo — overte cez `/admin/learning/status`.

**Degradovaný stav** (`active_ranking_profile_degraded: true` v
`/health`): systém automaticky spadol na `last_known_good` alebo
zabudovaný `DEFAULT_PROFILE` (zákaznícka prevádzka nie je nikdy prerušená
— degradovaný stav je pozorovateľný, nie výpadok). Skontrolujte
`config/ranking_profiles/active.json` (alebo cestu podľa
`RANKING_PROFILE_DIR`) na disku/volume — je pravdepodobne poškodený
alebo chýba jeho cieľová verzia. Oprava: `POST /admin/learning/candidates/
{id}/approve` na akéhokoľvek platného kandidáta (obnoví `active.json`
korektne cez atomický zápis), alebo manuálne opravte súbor a reštartujte
proces, aby sa cache vyprázdnila.

## 5. Overenie perzistencie po Railway redeploy (restart AJ redeploy)

Restart (rovnaký image, nový proces) a redeploy (nový image z aktuálneho
git stavu) sú DVE odlišné hrozby pre trvalosť:
- **Restart** overuje, že volume mount prežije reštart procesu.
- **Redeploy** overuje NAVYŠE, že NIXPACKS build nerematerializuje
  git-trackovaný `config/` obsah cez pripojený volume (presne toto bol
  pôvodný `active.json` bug).

Postup:
1. Zapíšte marker (napr. promujte testovacieho kandidáta, alebo
   spustite cyklus a poznamenajte si `learning_cycle_id`).
2. V Railway dashboarde spravte **Restart** (nie redeploy) služby.
3. `curl "$HOST/admin/learning/status"` — `active_ranking_config` a
   `last_known_good` musia zodpovedať tomu, čo bolo pred restartom.
4. Spravte skutočný **redeploy** (nový commit alebo "Redeploy" v
   dashboarde, ktorý znovu zbuilduje image).
5. Zopakujte krok 3 — `EVENTS_LOG_PATH` bol takto overený už pred týmto
   sprintom; po nastavení `FOODLAND_DATA_DIR` zopakujte rovnaký test aj
   pre `RANKING_PROFILE_DIR`/`LEARNING_HISTORY_DIR`.

## 6. Bežné problémy

| Príznak | Príčina | Riešenie |
|---|---|---|
| `/admin/*` vráti 404 | žiadny admin token nie je nastavený | nastavte aspoň `ADMIN_READ_TOKEN` |
| `/admin/*` vráti 401 | token nesedí so žiadnym nakonfigurovaným | skontrolujte presnú hodnotu env premennej |
| `/admin/*` vráti 403 | token je platný, ale na nízky scope | použite token so scope OPERATIONS/PROMOTION |
| approve/rollback vráti 409 "stale" | aktívna verzia sa zmenila od posledného pohľadu | znova `GET /admin/learning/status`, zopakujte s aktuálnou verziou |
| approve vráti 409 "no persisted candidate" | kandidát nikdy nedosiahol `READY_FOR_APPROVAL` (napr. `LEARNING_SHADOW_ENABLED=false`), alebo bol vygenerovaný pred reštartom procesu bez trvalého `LEARNING_HISTORY_DIR` | over `learning_history_dir_uses_unmounted_default` v `/health` |
| `active_ranking_profile_degraded: true` | poškodený/chýbajúci `active.json` alebo jeho cieľová verzia | pozri sekciu 4 |

## 7. Čo tento sprint NEROBÍ (zámerne)

`LEARNING_AUTO_PROMOTION_ENABLED` zostáva `false` a nepoužitý —
promócia VŽDY vyžaduje reálne `POST .../approve` volanie s menom
schvaľovateľa. Žiadny cron/scheduler v tomto repozitári nikdy nevolá
`approve_and_activate()` automaticky.
