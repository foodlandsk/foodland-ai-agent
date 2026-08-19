# Reálne HTTP endpointy pre schválenie/rollback — Sprint V2.12.1 Part C

Dátum: 2026-08-19.

## Problém, ktorý táto časť rieši

`app.learning_lifecycle.approve_and_activate()` a
`rollback_to_last_known_good()` existovali od V2.12, ale **žiadny HTTP
endpoint ich nikdy nevolal** — schválenie/rollback boli dosiahnuteľné
iba z Python REPL alebo testov. Navyše `approve_and_activate()` očakáva
plnohodnotný `LearningCandidate` objekt (vrátane kompletného
`RankingProfile` s váhami) — taký objekt existoval len v pamäti toho
JEDNÉHO `run_learning_cycle()` volania, ktoré ho vygenerovalo, a nikde
inde nebol trvalo uložený. Railway worker proces, ktorý obsluhuje reálny
HTTP approval request, nemusí byť ten istý proces, ktorý cyklus spustil
— potreboval sa teda spôsob, ako kandidáta nájsť podľa ID nezávisle od
toho, ktorý proces ho vygeneroval.

## Trvalé úložisko kandidátov podľa ID

`app/learning_lifecycle.py` teraz obsahuje `candidates.jsonl`
(append-only, rovnaký vzor ako `ledger.jsonl`) — nie samostatný súbor na
kandidáta, pretože ID kandidáta (napr.
`candidate:HIGH_ZERO_RESULT:mlieko bez laktózy`) obsahuje voľný text a
nie je bezpečné meno súboru na každom OS vrátane Windows.

`run_shadow()` teraz na konci (presne v momente, keď kandidát dosiahne
`READY_FOR_APPROVAL`) zavolá `_persist_candidate_snapshot()`, ktorá
zapíše kompletný `RankingProfile.to_dict()` (nie len verziu — skutočné
navrhované váhy), spolu s `config_version_at_generation` (aktívna verzia
v čase generovania — základ pre stale-candidate ochranu nižšie).

`get_persisted_candidate(candidate_id)` vráti NAJNOVŠÍ snapshot pre dané
ID (ak rovnaká príležitosť vyprodukovala kandidáta s rovnakým ID vo
viacerých cykloch, vždy sa použije posledný).

## `POST /admin/learning/candidates/{id}/approve`

Vyžaduje `PROMOTION` scope (pozri `docs/admin-security.md`). Telo:

```json
{"approved_by": "meno.priezvisko", "expected_current_config_version": "v1"}
```

`app.learning_lifecycle.approve_candidate_by_id()`:

1. Načíta snapshot podľa ID; ak neexistuje → `LifecycleError` → HTTP 409.
2. **Idempotencia**: ak je snapshot's profil UŽ aktívny (duplicitné/
   opakované volanie), vráti `{"status": "already_active", ...}` bez
   druhej mutácie `last_known_good`/ledger — druhé volanie
   `approve_and_activate()` by inak zaznamenalo aktuálnu verziu ako
   "predchádzajúcu", čím by skorumpovalo rollback target.
3. **Stale-candidate ochrana**: ak volajúci pošle
   `expected_current_config_version` a reálna aktívna verzia sa medzitým
   zmenila (niekto iný už promoval/rollbackoval), vyhodí `LifecycleError`
   → HTTP 409, namiesto tichej promócie na vrchol zmeny, ktorú schvaľovateľ
   nikdy nevidel.
4. Rekonštruuje `LearningCandidate` zo snapshotu a volá
   `approve_and_activate()` — rovnaká bezpodmienečná kontrola reálneho
   ľudského `approved_by` ako predtým (Section 55), nezmenená.

## `POST /admin/learning/rollback`

Vyžaduje `PROMOTION` scope. Telo:

```json
{"reason": "dôvod rollbacku", "triggered_by": "meno.priezvisko", "expected_current_config_version": "v2-abc"}
```

`rollback_to_last_known_good()` rozšírená o:

- `triggered_by: str = "system"` — zaznamenané do ledger evidence;
  default `"system"` zachováva spätnú kompatibilitu s existujúcimi
  volaniami (napr. budúci automatický rollback z `check_rollback_
  conditions()`, ktorý zatiaľ nie je na žiadny endpoint napojený).
  HTTP endpoint vždy posiela reálnu identitu.
- `expected_current_config_version` — rovnaká stale-request ochrana ako
  pri approval.
- **Idempotencia**: ak je aktívna verzia UŽ rovnaká ako
  `last_known_good`, opakovaný rollback je bezpečný no-op (zaznamenaný
  do ledgeru s `evidence.idempotent=true`, ale nemení
  `last_known_good` znova).

Ak neexistuje žiadny `last_known_good` záznam, endpoint vráti
`{"status": "no_op", "reason": "no last_known_good recorded"}` (nie chybu
— nič nie je pokazené, len nie je čo vrátiť).

## `AUTO_PROMOTION_ENABLED` — nezmenené, zámerne

`app.learning_lifecycle.AUTO_PROMOTION_ENABLED` (env `LEARNING_AUTO_
PROMOTION_ENABLED`, default `false`) **zostáva vypnutý a nepoužitý**
touto sprint — je to zdokumentovaný budúci extension point (Section 56
V2.12 zadania), nie niečo, čo tento sprint aktivuje. `approve_and_
activate()` bezpodmienečne vyžaduje reálne, nie-automatizované
`approved_by` bez ohľadu na tento flag, a to platí aj pre nový HTTP
endpoint (pydantic `Field(min_length=1)` na `approved_by` je len prvá
vrstva — skutočná kontrola je v `approve_and_activate()` samotnej,
`_DISALLOWED_APPROVER_IDENTIFIERS = {"auto", "system", "automated", "bot", "cron", ""}`).

## Príklad end-to-end (curl)

```bash
# 1. Spusti cyklus (OPERATIONS token)
curl -X POST "$HOST/admin/learning/run-cycle?full=true" -H "X-Admin-Token: $OPS_TOKEN"

# 2. Pozri kandidátov (READ token)
curl "$HOST/admin/learning/candidates" -H "X-Admin-Token: $READ_TOKEN"

# 3. Schváľ konkrétneho kandidáta (PROMOTION token)
curl -X POST "$HOST/admin/learning/candidates/candidate:RANKING_POSITION_ANOMALY:ryza/approve" \
  -H "X-Admin-Token: $PROMOTION_TOKEN" -H "Content-Type: application/json" \
  -d '{"approved_by": "jan.novak", "expected_current_config_version": "v1"}'

# 4. Ak treba, rollback
curl -X POST "$HOST/admin/learning/rollback" \
  -H "X-Admin-Token: $PROMOTION_TOKEN" -H "Content-Type: application/json" \
  -d '{"reason": "regresia v CTR", "triggered_by": "jan.novak"}'
```

## Testovacia matica

`tests/test_learning_approval_endpoints.py` (15 testov): neznáme ID →
`LifecycleError`; úspešná aktivácia; idempotentné druhé volanie; stale
`expected_current_config_version` → chyba; zhodná verzia → úspech;
rollback so stale verziou → chyba; opakovaný rollback → idempotentný;
HTTP endpoint odmietne READ aj OPERATIONS token s 403; plný HTTP
approve→rollback cyklus end-to-end; neznáme ID cez HTTP → 409; stale cez
HTTP → 409; rollback bez histórie cez HTTP → no_op.
