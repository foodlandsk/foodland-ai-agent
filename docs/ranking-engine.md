# Ranking Engine — Sprint V2.11

Dátum: 2026-08-17.

## Centrálny invariant (Section 3/8/9 zadania)

> V2.11 SMIE odpovedať "ktorý validný produkt má byť prvý?"
> V2.11 NESMIE odpovedať "ktorý produkt je validný?"

Eligibilitu (ktoré produkty vôbec smú byť v kandidátnej množine) vlastní
výhradne V2.3 taxonómia / V2.4 retrieval / V2.8 recipe intelligence.
`app/ranking.py: rank_candidates()` dostáva už-validnú množinu a iba ju
**permutuje** — nikdy nepridáva, nikdy neodoberá (`test_ranking_is_a_
permutation`, `tests/test_structured_retrieval.py`). V2.11 tento kontrakt
nezmenilo, iba ho formalizovalo a spravilo konfigurovateľným.

## Vrstvy (nezmenené od V2.4, teraz explicitne pomenované)

`app/ranking.py: rank_candidates()` triedi kandidátov podľa striktného
lexikografického kľúča:

```
(-l1_confidence, -l2_explicit_hits, -l3_availability, -l4_relevance, -soft, product_id)
```

| Vrstva | Čo meria | Môže ju prebiť soft signál? |
|---|---|---|
| L1 confidence | taxonomy HIGH/MEDIUM/LOW/UNKNOWN | Nie |
| L2 explicit hits | koľko explicitných brand/size constraintov produkt spĺňa | Nie |
| L3 availability | in_stock vs. nie | Nie |
| L4 relevance | title/brand token overlap s dopytom | Nie |
| soft | behavioral × merchandising × personalization | (je posledná vrstva) |

Pretože `soft` sa porovnáva AŽ POSLEDNÝ, žiadna kombinácia váh v
`RankingWeights` (viď `docs/ranking-profiles.md`) nemôže spôsobiť, že
produkt s horším L1–L4 skóre prebehne produkt s lepším — to je
matematický dôsledok tuple-porovnania v Pythone, nie behavioral pravidlo,
ktoré by sa dalo obísť zlou konfiguráciou. Overené priamo testom
`TestExplicitConstraintOutranksSoftSignals` (`tests/test_ranking_profile_
wiring.py`) — aj s `personalization_cap=1.0` a maximálnou personalizáciou
pre nesprávnu značku produkt bez explicitnej zhody značky ostáva za
produktmi so zhodou.

## `app/ranking_features.py` — explainability

`RankingFeatures` je čisto-nazerná (read-only) dataclass, ktorá vypočíta
TIE ISTÉ hodnoty, aké `rank_candidates()` interne používa (zdieľané
privátne funkcie `_CONFIDENCE_RANK`, `_explicit_attribute_hits()`,
`_in_stock()`, `_relevance_score()` — Section 6 zadania: "do not
duplicate existing signals"). `explain_candidates()` vracia zoznam
`RankingFeatures` už zoradený presne v poradí, aké by `rank_candidates()`
vrátil — overené testom `test_explain_candidates_order_matches_rank_
candidates_order`.

CLI drilldown:

```
python scripts/ranking_cli.py explain --query "jazmínová ryža" --limit 8
```

vypíše pre každého kandidáta jeden riadok:

```
FL_10913: confidence=2 explicit_hits=0 in_stock=1 relevance=4 | soft=1.0000 (behavioral=1.0000 x merchandising=1.0000 x personalization=1.0000)
```

## Čo V2.11 NEZMENILO

- `app/retrieval.py` (eligibilita) — nedotknuté.
- `app/cross_sell.py` — vlastný, nezávislý `rank_candidates()`/skóre
  systém (role priority + curated/FBT evidence bonusy), bez akéhokoľvek
  prepojenia na `app.ranking_config`. Overené `tests/test_cross_sell_
  ranking_isolation.py` (signature check — `ranking_profile` nie je
  parametrom `app.cross_sell.rank_candidates()`).
- Predvolené správanie `rank_candidates()` pri `ranking_profile=None`
  (alebo explicitnom `RankingProfile` s default váhami) — bit-presne
  identické pred/po V2.11 (viď `docs/ranking-profiles.md`, sekcia
  "Dôkaz zachovania správania").

## Súvisiace dokumenty

- `docs/ranking-profiles.md` — `RankingProfile`/`RankingWeights`,
  verzovanie, aktivácia/rollback.
- `docs/ranking-optimization.md` — bounded offline optimizer, shadow
  mode, quality gates pre kandidátne konfigurácie.
