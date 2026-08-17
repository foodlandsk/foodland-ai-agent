# Ranking Optimization — Sprint V2.11

Dátum: 2026-08-17.

## Filozofia (Section 45-58/115/127 zadania)

> Cieľom je nájsť skutočné zlepšenie, nikdy ho vyrobiť.

Optimizer NIKDY nevyhodnocuje kandidátnu konfiguráciu voči syntetickej
proxy metrike — každý kandidát beží cez **skutočný V2.10 evaluation
harness** (`app.evaluation`, ten istý `chat()` volaný živým zákazníkom).
Nikdy neoptimalizuje jedinú metriku — objektívna funkcia je vážený
priemer piatich metrík naraz (pass_rate, eligibility precision,
precision@5, recall@5, MRR), takže kandidát nemôže "vyhrať" tým, že
jednu metriku nahustí na úkor druhej. Nikdy automaticky neaktivuje
víťaza — `optimize()` iba ODPORÚČA, aktivácia je samostatný, explicitný
krok cez `scripts/ranking_cli.py activate` (plné auto-apply je zámerne
V2.12, nie táto iterácia — Section 130).

## Architektúra

```
app/ranking_optimizer.py
├── generate_candidate_profiles(base, n, seed)
│     bounded, deterministická (daným seedom) perturbácia base.default
│     v rozmedzí RankingWeights' vlastných validovaných hraníc
├── evaluate_profile(profile, fast=...)
│     1. profile.validate() — okamžitý reject mimo-hraníc konfigurácie,
│        BEZ behu evaluation suite (prvá bezpečnostná sieť)
│     2. use_ranking_profile(profile): beží app.evaluation golden +
│        conversation suite cez skutočný chat() (druhá bezpečnostná sieť —
│        evaluate_quality_gates() z app.evaluation.baseline)
│     3. vráti CandidateEvaluation(summary, gate, objective, rejected)
└── optimize(base, n_candidates, seed, fast)
      vyhodnotí base + n kandidátov, zahodí GATE_FAIL kandidátov,
      odporučí najlepšieho PREŽIVŠIEHO podľa objective — alebo
      úprimne odporučí ponechať base, ak nikto nezlepšil
```

## Dve bezpečnostné siete pre deliberately unsafe konfigurácie (Section 110-112)

1. **Bounds validácia** (`RankingWeights.validate()`) — konfigurácia mimo
   `BEHAVIORAL_WEIGHT_BOUNDS` atď. (napr. `behavioral_weight=50.0`) je
   odmietnutá OKAMŽITE, `evaluate_profile()` ani nespustí suite. Overené
   `test_out_of_bounds_behavioral_weight_rejected_without_running_suite`
   a dvomi ďalšími (personalization_cap, merchandising_exponent).
2. **Quality gate cez skutočný harness** (`evaluate_quality_gates()`,
   zdieľané s V2.10) — konfigurácia NA HRANICI validného rozsahu (napr.
   `behavioral_weight=3.0` — maximum, ale stále validné) MUSÍ prejsť
   cez skutočný pipeline; ak by spôsobila regresiu kritického prípadu,
   `context_contamination_rate>0`, alebo `max_duplicate_rate>0`, gate
   vráti `FAIL` a kandidát je zahodený. Overené
   `test_valid_but_extreme_config_still_runs_through_real_harness` —
   dokazuje, že druhá sieť je skutočne dosiahnuteľná (kandidát sa
   naozaj vyhodnotí), nielen teoreticky existuje.

## Reálny výsledok behu (nie hypotéza — skutočný beh na fixture katalógu)

```
python scripts/ranking_cli.py optimize --candidates 5 --seed 7
```

```json
{
  "base_profile_version": "v1",
  "baseline_gate": "WARN",
  "baseline_objective": 0.7237,
  "improved": false,
  "n_candidates": 5,
  "n_rejected": 0,
  "n_survivors": 5,
  "recommendation": {
    "note": "no candidate improved on the base profile within this search - keeping current defaults",
    "version": "v1"
  }
}
```

Toto NIE je zlyhanie optimalizátora — je to čestný nález priamo
predpovedaný audit fázou tohto sprintu: V2.10 baseline (`eval/baselines/
v2.9.json`) má iba **1 `RANKING_ERROR`** bucket z 58 golden prípadov (7
`ELIGIBILITY_ERROR`, 4 `RETRIEVAL_MISS`, 3 `GROUNDING_ERROR`, 3
`INTENT_ERROR`, 1 `PRESENTATION_ERROR` — všetky mimo rozsahu rankingu,
teda mimo toho, čo `RankingProfile` môže vôbec ovplyvniť). Priestor pre
reálne, poctivé zlepšenie samotného poradia je preto malý — presne to,
čo by mal optimizer hlásiť, nie skryť umelým vylepšením jednej metriky.

## Shadow mode (Section 61-64)

`app/ranking_shadow.py: shadow_compare()` beží ROVNAKÝ zoznam dopytov
dvakrát — raz pod baseline profilom, raz pod kandidátom — cez
`use_ranking_profile()`, čo nikdy nezapíše do `config/ranking_profiles/
active.json`. Žiadny zákazník preto nemôže vidieť výstup kandidáta
(overené `test_active_pointer_unaffected_by_shadow_compare`).

```
python scripts/ranking_cli.py compare-profiles --baseline default --candidate v1
```

Report rozlišuje `order_changed` (poradie sa zmenilo) od
`window_set_changed` (viditeľné top-N okno sa zmenilo — **očakávané**,
nie porušenie, keď kandidátna množina presiahne `limit`; `ChatRequest.
limit` je navyše tvrdo obmedzený na max. 12 na HTTP úrovni, nezávisle od
rankingu). Skutočný invariant — že CELÁ eligibilná množina sa nikdy
nemení — je overený priamo nad `rank_candidates()` (nie cez `chat()`'s
stránkovaný výstup) v `tests/test_ranking_profile_wiring.py` a
`tests/test_structured_retrieval.py::TestRankingInvariants`.

## CLI zhrnutie

```
python scripts/ranking_cli.py list
python scripts/ranking_cli.py activate <version>          # aj rollback
python scripts/ranking_cli.py explain --query "..." [--profile v1]
python scripts/ranking_cli.py compare-profiles --baseline v1 --candidate v1
python scripts/ranking_cli.py optimize --candidates 8 --seed 1 [--full] [--save]
```

`optimize --save` uloží odporúčaného kandidáta ako novú verziu (súbor
`config/ranking_profiles/candidate-<seed>-<i>.json`) — **neaktivuje ju**.
Aktivácia je vždy samostatný, explicitný krok.

## Testy

`tests/test_ranking_optimizer.py` (11) — bounds/determinism generátora,
obe bezpečnostné siete, honest-no-improvement správanie.
`tests/test_ranking_shadow.py` (4) — no-op na identickom profile,
nedotknutosť `active.json`, plná-množina invariant pri limite nad
veľkosťou kandidátnej množiny.

## Čo je zámerne MIMO rozsahu (V2.12 kandidát)

Plne automatizovaná slučka "nájdi kandidáta → aktivuj → sleduj → rollback
ak zlyhá" bez ľudského schválenia — `app/ranking_optimizer.py` je na to
architektonicky pripravené (`optimize()` vracia štruktúrovaný
`RankingProfile` objekt pripravený na `save_ranking_profile()`/
`set_active_ranking_profile_version()`), ale túto slučku táto iterácia
zámerne nezapája (Section 130 zadania).
