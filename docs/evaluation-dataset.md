# Evaluation Dataset — Sprint V2.10

Dátum: 2026-08-17. `dataset_version: "1.0"`.

## Štruktúra

```
eval/golden/*.json          - single-turn prípady (GoldenCase)
eval/conversations/*.json   - multi-turn sekvencie (ConversationCase)
eval/baselines/v2.9.json    - uložený baseline snapshot
eval/reports/latest.{json,md} - posledný beh (negenerované do gitu okrem README)
```

## Domény (`eval/golden/`)

| Súbor | Prípadov | Poznámka |
|---|---|---|
| `rice.json` | 12 | Section 33/116 kolízne páry (ryža vs. rezance/ocot/papier/ryžovar/múka) |
| `sauces.json` | 7 | Sójová/rybacia/ustricová/hoisin/teriyaki/sriracha/čili-cesnak |
| `pastes_and_curry.json` | 5 | Kari pasty (V2.3 historický bug: red curry ↔ massaman), miso, gochujang |
| `noodles.json` | 4 | Ryžové/soba/instantné rezance, Shin Ramyun (známy stateless nález) |
| `coconut_oil_misc.json` | 5 | Kokosové mlieko/voda, sezamový olej, nori/wakame |
| `regression_bugs.json` | 25 | 1:1 konverzia z `tests/regression_training_cases.jsonl` (27 pôvodných − 2 presunuté do konverzácie) |

## Konverzácie (`eval/conversations/`)

| Súbor | Sekvencia |
|---|---|
| `v29_rice_matrix.json` | jazmínová ryža → 5kg → 1kg → lacnejšie → ukáž všetky |
| `v29_padthai_matrix.json` | Pad Thai pre 4 → rezance → druhý → rybacia omáčka → lacnejšie → pre 8 → čo chýba → mlieko (hard switch) |
| `v29_sushi_matrix.json` | sushi → ryža → ocot |
| `regression_bugs.json` | RT0020/RT0021 (kimchi na výrobu → na výrobu) |

## Politika verzionovania (Section 55/56)

Zmena `expected_*` poľa v existujúcom prípade musí byť viditeľná v `git
diff` a mať dôvod (commit message). Nikdy sa automaticky neprepisuje iba
preto, že aktuálny systém vracia niečo iné — to by skrylo regresiu.
Pridanie NOVÉHO prípadu nevyžaduje zmenu `dataset_version`; zmena
SÉMANTIKY existujúceho prípadu áno.

## Ako pridať nový prípad

1. Nájdi skutočnú `app.taxonomy.FAMILY_DEFINITIONS` frázu alebo overenú
   prirodzenú formuláciu (nikdy nevymýšľaj).
2. `expected_concept_ids`/`must_not_concept_ids` — použi skutočné
   `rule_id` hodnoty z `app/taxonomy.py`.
3. Over ručne cez `python scripts/run_evaluation.py --case <id>` pred
   commitom.
4. Ak prípad reprezentuje predtým opravený produkčný bug, nastav
   `"source": "regression_bug"` a `"critical": true` (Section 91/92).
