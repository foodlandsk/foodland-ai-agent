# Quality Gates — Sprint V2.10

Dátum: 2026-08-17.

## Filozofia (Section 38/83-85)

Nie každá metrika blokuje CI. Rozlišujeme:

- **BLOCKING** (gate=`FAIL`, CI červená) — iba explicitný, úzky zoznam.
- **REPORTING** (gate=`WARN`, CI zelená, ale viditeľné v reporte) —
  všetko ostatné.

## Blokujúce brány (aktuálny stav)

1. **Kritický golden/conversation prípad regresoval** — bol `passed=true`
   v `eval/baselines/v2.9.json`, teraz `passed=false`.
2. **`context_contamination_rate > 0`** — absolútny invariant
   (Section 32), nikdy nie je prijateľné, bez ohľadu na baseline.
3. **`max_duplicate_rate > 0`** — ResultSet nikdy nesmie vrátiť
   duplicitné SKU (Section 23).

## Reportovacie metriky (nikdy neblokujú samé osebe)

`pass_rate`, `avg_eligibility_precision`, `avg_precision_at_5`,
`avg_recall_at_5`, `mrr`, `taxonomy.coverage_ratio`, latency percentily,
non-critical prípad regresie.

## Prečo takto (nie väčšia prísnosť hneď)

Section 38: "Use measured baseline before choosing final numeric
thresholds. Do not invent arbitrary percentages without baseline
evidence." Prvý beh (`eval/baselines/v2.9.json`, commit `3e72ac5`) už
obsahuje 3 zlyhávajúce kritické prípady (`regbug_rt0010`,
`rice_sushi_001`, `sauce_fish_001`) — reálne, existujúce medzery
objavené TÝMTO sprintom, nie zapríčinené ním. Blokovať CI na niečo, čo
V2.10 sám objavil pri prvom behu, by znamenalo buď (a) potichu zjemniť
dataset, aby prešiel (Section 56/84 to explicitne zakazuje), alebo (b)
zablokovať každý budúci commit kým sa neopraví V2.4-éra kaskádová
príčina mimo rozsahu tohto sprintu (Section 4). Namiesto toho: baseline
zaznamenáva realitu, brána chráni pred ĎALŠÍM zhoršením.

## Ako sprísniť v budúcnosti

Keď V2.11 (alebo neskorší sprint) opraví `related_subject`-vs-
`ATTRIBUTE_SEARCH` precedenciu (dokumentované v
`docs/evaluation-engine.md` "Kritický nález č. 2"), nový beh
`--save-baseline` zaznamená `sauce_fish_001` ako passing — odvtedy by
JEHO opätovné zlyhanie už bolo skutočnou regresiou a zablokovalo by CI.
Tento mechanizmus prirodzene sprísňuje bránu s každým skutočným zlepšením,
bez potreby ručne meniť čísla prahov.

## CI integrácia

`.github/workflows/ci.yml`: krok "Foodland quality suite (fast, blocking)"
beží `python scripts/run_evaluation.py --fast` (39 kritických golden +
4 konverzácie, ~12s lokálne) hneď po plnej pytest sade. Exit kód 1 iba
pri gate=`FAIL`.
