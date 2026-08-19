# Trvalé úložisko runtime stavu — Sprint V2.12.1 Part A

Dátum: 2026-08-19.

## Problém, ktorý táto časť rieši

`docs/runtime-state-inventory.md` (Section 8 zadania) zdokumentoval, že
každý runtime-zapisovaný stav defaultne končí buď v `/tmp` (mizne pri
každom reštarte kontajnera), alebo v git-trackovanom/negitovanom
`config/...` priečinku (mizne alebo sa vracia na commitnutú hodnotu pri
každom Railway redeploy). Najzávažnejšie zistenie: `config/ranking_
profiles/active.json` je **git-trackovaný**, takže reálna produkčná
promócia kandidáta bola pred týmto sprintom ticho vrátená na commitnutý
`v1` pointer pri ďalšom redeploy — bez akejkoľvek chyby či upozornenia.

## `FOODLAND_DATA_DIR` — jeden prepínač namiesto siedmich

Pred týmto sprintom šesť rôznych miest (`app/main.py`, `app/embeddings.py`,
`app/behavioral.py`, `app/fbt.py`, `app/learning_events.py`) nezávisle
hardcodovalo `Path(tempfile.gettempdir()) / "foodland-ai-agent"`. Zabudnúť
prepísať čo i len jednu z týchto premenných znamenalo, že práve TÁTO
jedna časť stavu ticho resetuje pri každom deploy, zatiaľ čo ostatné
prežijú — presne to sa stalo pred týmto sprintom.

`app/storage_paths.py` teraz definuje:

```python
def data_dir() -> Path:
    configured = os.getenv("FOODLAND_DATA_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "foodland-ai-agent"

def resolve_path(env_var: str, filename: str) -> Path:
    explicit = os.getenv(env_var, "").strip()
    if explicit:
        return Path(explicit)
    return data_dir() / filename

def resolve_dir(env_var: str, subdir: str, *, legacy_default: str) -> Path:
    explicit = os.getenv(env_var, "").strip()
    if explicit:
        return Path(explicit)
    if is_data_dir_configured():
        return data_dir() / subdir
    return Path(legacy_default)
```

`app/main.py`'s `DEFAULT_RUNTIME_LOG_DIR` (jeden bod, na ktorom závisí
šesť `*_LOG_PATH`/`*_PATH` premenných) teraz volá `_foodland_data_dir()`
namiesto vlastného výpočtu — nastavenie `FOODLAND_DATA_DIR` v Railway
prostredí teda automaticky prepojí `ANALYTICS_LOG_PATH`,
`ERROR_LOG_PATH`, `TAXONOMY_SHADOW_LOG_PATH`, `EVENTS_LOG_PATH`,
`USER_MEMORY_PATH` aj `PRODUCT_EMBEDDINGS_PATH` na jeden trvalý koreň,
pokiaľ nemajú explicitný vlastný override.

`RANKING_PROFILE_DIR` a `LEARNING_HISTORY_DIR` používajú `resolve_dir()`
namiesto `resolve_path()`: keď `FOODLAND_DATA_DIR` NIE JE nastavený,
zostávajú presne na pôvodnom `config/ranking_profiles` /
`config/learning_history` (žiadna zmena správania pre lokálny vývoj ani
CI), ale keď nastavený JE, presúvajú sa pod ten istý koreň ako všetko
ostatné — **presne táto vlastnosť opravuje git-tracked-reversion bug**:
`active.json` už nie je zapisovaný do git-trackovanej cesty, keď je
`FOODLAND_DATA_DIR` nakonfigurovaný.

`EVENTS_LOG_PATH` bol už pred týmto sprintom overený na reálnom Railway
volume (`/data/foodland-ai-agent/events.jsonl`, prežil reálny redeploy aj
reštart). Zvyšné premenné vyžadujú, aby operátor nastavil
`FOODLAND_DATA_DIR` na ten istý pripojený volume — pozri
`docs/learning-operations-runbook.md`.

## Zdieľaný atomický zápis (`app/durable_storage.py`)

Pred týmto sprintom existovali DVE nezávislé, správne implementácie
temp-súbor-potom-`os.replace()` vzoru (`ranking_config.py`,
`learning_lifecycle.py`) a JEDEN trvalý JSON writer bez akejkoľvek
atomicity (`USER_MEMORY_PATH` v `app/main.py` — obyčajný `write_text()`
prepis). `app/durable_storage.py` teraz poskytuje jednu otestovanú
implementáciu:

```python
def atomic_write_text(path: Path, content: str) -> None: ...
def atomic_write_json(path: Path, payload) -> None: ...
```

Zápis do dočasného súboru V TOM ISTOM priečinku ako cieľ (aby bol finálny
`os.replace()` na tom istom filesystéme, a teda atomický), `fsync()` pred
`replace()`, `finally: os.remove(tmp_path)` ak dočasný súbor zostal.
Garancia: čitateľ vidí buď kompletný starý obsah, alebo kompletný nový —
nikdy torn/čiastočný zápis, bez ohľadu na to, kedy proces spadne.

Použité teraz na: `active.json` (ranking_config), verziované profily
(ranking_config), `last_known_good.json` (learning_lifecycle),
`user_memory.json` (main.py — predtým jediný neatomický trvalý writer).

## Degradovaný fallback reťazec pre aktívny ranking profil

Pred týmto sprintom: `active.json` → `DEFAULT_PROFILE` (dvojstupňové).
Teraz (`app/ranking_config.py: get_active_ranking_profile()`):

```
active.json (a jeho cieľová verzia)
      | (chyba: chýbajúci/poškodený pointer alebo verzia)
last_known_good.json (V2.12 rollback target — recyklovaný ako 2. poistka)
      | (chyba: chýba alebo je poškodený)
DEFAULT_PROFILE (hardcoded, identické s pred-V2.11 správaním)
```

`is_active_profile_degraded() -> bool` reportuje, či posledné rozlíšenie
muselo opustiť primárnu cestu (`active.json`). Toto NIE JE cachované
oddelene od samotného profilu — odráža posledné reálne rozlíšenie, nie
vek cache. `pointer_exists = ACTIVE_POINTER_PATH.exists()` rozlišuje
"pointer nikdy neexistoval" (normálny stav pred prvou promóciou, NIE
degradovaný) od "pointer existuje, ale je nepoužiteľný" (degradovaný).

Test coverage: `tests/test_durable_storage.py::TestActiveProfileFallbackChain`
— zdravý stav, poškodený pointer bez last_known_good, poškodený pointer
S last_known_good, chýbajúci verzia-súbor, a že sa `degraded` flag vráti
na `False` po oprave.

## `/health` — pozorovateľnosť namiesto tichého predpokladu

Section 111/112 zadania: trvalé úložisko musí byť pozorovateľné, nie
predpokladané. `GET /health` teraz obsahuje blok `durable_storage`:

```json
{
  "durable_storage": {
    "foodland_data_dir_configured": false,
    "foodland_data_dir": "/tmp/foodland-ai-agent",
    "ranking_profile_dir": "config/ranking_profiles",
    "ranking_profile_dir_uses_git_tracked_default": true,
    "active_ranking_profile_degraded": false,
    "learning_history_dir": "config/learning_history",
    "learning_history_dir_uses_unmounted_default": true,
    "learning_history_dir_exists": false
  }
}
```

`*_uses_git_tracked_default` / `*_uses_unmounted_default` je `true`
presne vtedy, keď daná cesta stále sedí na pôvodnom nebezpečnom defaulte
— t.j. ani `FOODLAND_DATA_DIR`, ani vlastný override nie sú nastavené.
Toto pole je priamo návod pre ops: `true` = táto časť stavu NEPREŽIJE
ďalší redeploy.

## Čo zostáva známa medzera (vedomé rozhodnutie, nie prehliadnutie)

`ANALYTICS_LOG_PATH`, `ERROR_LOG_PATH`, `TAXONOMY_SHADOW_LOG_PATH`,
`USER_MEMORY_PATH`, `PRODUCT_EMBEDDINGS_PATH` sú teraz **schopné** byť
trvalé (dedia z `FOODLAND_DATA_DIR`, ak je nastavený), ale samotné
nastavenie `FOODLAND_DATA_DIR` v Railway prostredí je operátorský krok
mimo rozsahu tohto repozitára — pozri `docs/learning-operations-runbook.md`
pre presný postup a `/health`'s `durable_storage` blok pre overenie, že
sa to naozaj stalo.
