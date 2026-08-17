# Ranking Profiles — Sprint V2.11

Dátum: 2026-08-17.

## Čo je `RankingProfile`

Verzovaný, validovaný balík váh pre tri existujúce soft signály, ktoré
`app/ranking.py: rank_candidates()` už počítalo pred V2.11 (Section
10-14/58-60 zadania):

```python
@dataclass(frozen=True)
class RankingWeights:
    behavioral_weight: float = 1.0        # -> behavioral_multiplier(weight=...)
    behavioral_min_ratio: float = 0.5     # -> behavioral_multiplier(min_ratio=...)
    behavioral_max_ratio: float = 2.0     # -> behavioral_multiplier(max_ratio=...)
    merchandising_exponent: float = 1.0   # -> merchandising_multiplier(...) ** exponent
    personalization_cap: float = 1.0      # ceiling pre personalization_score pred +1.0
```

`RankingProfile` = `{version, name, description, default: RankingWeights,
family_overrides: dict[family_id, RankingWeights]}`. `weights_for(family)`
vráti override, ak existuje pre danú V2.3 rodinu, inak `default` — presne
dedenie žiadané Section 11/12/58.

## Dôkaz zachovania správania (Section 106 zadania)

`RankingWeights()` bez argumentov reprodukuje presne hardcoded konštanty,
aké `app.ranking`/`app.behavioral` mali PRED V2.11:

| Pole | Default hodnota | Pred-V2.11 ekvivalent |
|---|---|---|
| `behavioral_weight` | 1.0 | `behavioral_multiplier()`'s vlastný default |
| `behavioral_min_ratio`/`max_ratio` | 0.5 / 2.0 | `behavioral_multiplier()`'s vlastné defaulty |
| `merchandising_exponent` | 1.0 | `x ** 1.0 == x` (no-op) |
| `personalization_cap` | 1.0 | hardcoded `min(1.0, ...)` v starom `rank_candidates()` |

`rank_candidates(..., ranking_profile=None)` je zámerne ekvivalentné
`rank_candidates(..., ranking_profile=RankingProfile(default=RankingWeights()))`
— overené `test_none_profile_and_default_profile_produce_identical_order`
a `test_none_profile_matches_explicit_default_weights_profile`
(`tests/test_ranking_profile_wiring.py`).

Živý dôkaz nad celým golden datasetom (V2.10): po zapojení `ranking_
profile=get_active_ranking_profile()` do všetkých troch volaní v
`app/main.py` vrátil `python scripts/run_evaluation.py --full` **identické**
44/58 golden, 4/4 konverzácie, rovnaké 3 kritické zlyhania (`regbug_
rt0010`, `rice_sushi_001`, `sauce_fish_001`) ako baseline `eval/baselines/
v2.9.json` — nulová zmena runtime správania pri predvolenom profile v1.

## Validácia a bezpečné hranice (Section 110/111)

```python
BEHAVIORAL_WEIGHT_BOUNDS = (0.0, 3.0)
BEHAVIORAL_MIN_RATIO_BOUNDS = (0.1, 1.0)
BEHAVIORAL_MAX_RATIO_BOUNDS = (1.0, 4.0)
MERCHANDISING_EXPONENT_BOUNDS = (0.0, 3.0)
PERSONALIZATION_CAP_BOUNDS = (0.0, 1.0)
```

Konfigurácia mimo týchto hraníc vyhodí `RankingProfileError` — pri
`save_ranking_profile()`, `load_ranking_profile()` aj pri vstupe do
`use_ranking_profile()`. `personalization_cap` je zámerne zhora ohraničený
na `1.0` (nie vyššie) — to je numerická podmienka, ktorá drží aktuálny
strop pre soft-signál rovnaký alebo prísnejší, nikdy uvoľnenejší, než mal
pred V2.11.

## Verzovanie a rollback (Section 13/14/99-101)

Verzie sú **nemenné** — `save_ranking_profile()` odmietne prepísať
existujúci `config/ranking_profiles/<version>.json`, kým nie je explicitne
`overwrite=True`. Aktivácia je atomický pointer swap
(`config/ranking_profiles/active.json`, write-to-tmp + `os.replace()`):

```
python scripts/ranking_cli.py list
python scripts/ranking_cli.py activate v1
```

Rollback = aktivácia staršej verzie, nič viac — žiadny redeploy, žiadna
zmena kódu:

```
python scripts/ranking_cli.py activate v1   # naspäť na predchádzajúcu
```

`get_active_ranking_profile()` má rezolučné poradie: explicitný
`use_ranking_profile()` override (optimizer/shadow/testy) > perzistovaný
`active.json` pointer > vstavaný `DEFAULT_PROFILE` (bezpečný fallback, ak
`config/ranking_profiles/` chýba alebo je poškodený).

## Family/category overrides

```python
profile.with_family_override("rice", behavioral_weight=1.5)
```

vytvorí novú `RankingProfile` s `family_overrides["rice"]` = kompletná
`RankingWeights` (nešpecifikované polia zdedené z `default` cez
`dataclasses.replace()` — Section 12). `weights_for("sauce")` zostáva
nedotknuté (overené `test_with_family_override_inherits_unspecified_
fields_from_default`).

## `config/ranking_profiles/`

- `v1.json` — checked-in default profil (identický s `DEFAULT_PROFILE`).
- `active.json` — pointer, **nie** je checked-in ako súčasť logiky (je
  runtime stav, generovaný `set_active_ranking_profile_version()`), ale
  commitnutý so štartovacou hodnotou `v1` pre reprodukovateľné nasadenie.

## Testy

`tests/test_ranking_config.py` (27) — bounds validácia (vrátane
deliberate-extreme reject), verzovanie/immutabilita, aktivácia/rollback,
`use_ranking_profile()` override + nested restore.
