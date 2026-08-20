# Evaluation Engine — Sprint V2.10 technical documentation

Dátum: 2026-08-17. Zdroj kódu: `app/evaluation/` (nový balík: `schema.py`,
`metrics.py`, `runner.py`, `conversation.py`, `taxonomy_quality.py`,
`baseline.py`, `loader.py`, `adapter.py`), `scripts/run_evaluation.py`
(CLI), `eval/golden/*.json`, `eval/conversations/*.json`.

## Architektonické pravidlo (Section 4/52)

`app/evaluation` NIKDY nemení runtime správanie — nečíta ani nezapisuje
ranking váhy, taxonomy pravidlá, ani recipe mapovania. `app/evaluation/
runner.py` a `conversation.py` sú čisté funkcie prijímajúce `chat_fn`/
`taxonomy_index` ako argumenty — jediné miesto, ktoré importuje
`app.main` (skutočný, bežiaci `chat()`), je `app/evaluation/adapter.py`.
Toto NIE JE druhá implementácia vyhľadávania (Section 52) — každý golden
prípad prechádza presne tou istou `chat()` cestou ako reálny zákaznícky
dopyt.

## Prečo nie `scripts/run_customer_situation_tests.py`

Audit (Section 2) zistil existujúci `scripts/run_customer_situation_tests.py`
+ `tests/*.jsonl` súbory (customer_situations_1000, extended_customer_
situations_5000, atď.) — ale tento skript beží nad VLASTNOU, nezávislou
`fast_search_products()` implementáciou, nie nad skutočným `chat()`.
Presne to, čo Section 52 zakazuje ("Do not create a separate fake search
implementation"). V2.10 preto NEROZŠIRUJE tento skript — `tests/
regression_training_cases.jsonl` (27 reálnych, už opravených produkčných
bugov) bolo namiesto toho 1:1 konvertované do nového `eval/golden/
regression_bugs.json` schémy a beží cez skutočný `app.main.chat()`.

## Golden dataset (Section 5/6/54)

60 single-turn prípadov (`eval/golden/*.json`) + 4 multi-turn konverzácie
(`eval/conversations/*.json`). Každý query text je buď skutočná
`app.taxonomy.FAMILY_DEFINITIONS` `title_phrase`, alebo jej prirodzený
zákaznícky variant (Section 8) — nikdy vymyslený reťazec. Relevance
ground truth (`expected_concept_ids`) sa vyhodnocuje PROTI AKTUÁLNEMU
katalógu pri každom behu (real taxonomy classification), nie proti
hardcoded SKU zoznamu (Section 5) — prežije feed refresh bez ručnej
údržby.

## Metriky (`app/evaluation/metrics.py`, čisté funkcie)

`eligibility_precision`, `precision_at_k`/`recall_at_k`/`hit_rate_at_k`,
`reciprocal_rank`/`mrr`, `dcg_at_k`/`ndcg_at_k`, `duplicate_rate`,
`overlap_rate`. Sémantická korektnosť nad lexikálnou podobnosťou
(Section 116): "relevantný" produkt = zhoda `expected_concept_id` cez
SKUTOČNÚ taxonomy klasifikáciu vráteného produktu, nikdy substring v
titulku.

## Kritický nález č. 1: session kontaminácia medzi golden prípadmi

Prvá verzia `app/evaluation/adapter.py` posielala VŠETKY golden prípady
cez rovnakú (prázdnu → anonymnú fallback) session. Výsledok: 34/60 namiesto
44/60 pri prvom behu — V2.9 session state z jedného prípadu unikal do
ďalšieho, presne tá trieda chyby, ktorú V2.9 existuje aby zabránila.
Opravené: každé volanie `chat_fn()` dostáva vlastné, izolované
`session_id` (deterministický counter, nie skutočná náhoda — Section 45).

## Kritický nález č. 2: `related_subject` prekrýva ATTRIBUTE_SEARCH pre holé názvy omáčok

Reálny, systémový nález (nie chyba datasetu): bare dopyty na konkrétnu
omáčku ("rybacia omáčka", "hoisin omáčka", "ustricová omáčka", "teriyaki
omáčka", "čili cesnak omáčka") sa smerujú cez `detect_related_subject()`
legacy cross-sell kaskádu namiesto čistej V2.4 `ATTRIBUTE_SEARCH` cesty —
overené priamo (`m.detect_related_subject("rybacia omacka")` →
`"rybacia_omacka"`). Výsledok: odpoveď mieša Ponzu/Tamari/bezlepkovú
sójovú omáčku do výsledkov na rybaciu omáčku namiesto čistej,
eligible množiny. `sauce_fish_001` (kritický prípad, V2.8 Pad Thai
ingrediencia) preto v baseline zlyháva. **V2.10 túto príčinu NEOPRAVUJE**
(vyžadovalo by kaskádovú chirurgiu v `chat()` mimo rozsahu tohto sprintu,
Section 4) — zaznamenané ako baseline stav, prioritný kandidát pre V2.11.

## Konverzačný evaluátor (Section 29-34)

`app/evaluation/conversation.py: run_conversation_case()` beží CELÚ
sekvenciu na JEDNEJ zdieľanej session (na rozdiel od izolovaných golden
prípadov) — skóruje KAŽDÝ ťah nezávisle (Section 30), nie iba finálnu
odpoveď. 4 konverzácie: rice matrix, Pad Thai matrix (V2.9 vlajková
schopnosť), sushi matrix, RT0020/RT0021 (pôvodne 2 nezávislé prípady,
konvertované na skutočnú 2-ťahovú sekvenciu, keďže druhý ťah reálne
závisí od prvého).

## Baseline a quality gates (Section 38-41)

`eval/baselines/v2.9.json` — prvý beh (commit `3e72ac5`), 44/58 golden
(75.9%), 4/4 konverzácie, `context_contamination_rate=0.0`. Politika
(zdôvodnená v `app/evaluation/baseline.py`'s docstring): PRVÝ beh
zaznamená existujúce nálezy AKO SÚ (Section 115 — účelom je nájsť, kde
je Mei zlá, nie začať s čistým skóre). Blokujúce (FAIL) je iba:

- kritický golden/conversation prípad, ktorý bol PASSING v baseline a
  teraz FAILING (skutočná regresia),
- `context_contamination_rate > 0` (absolútny invariant, Section 32),
- `max_duplicate_rate > 0` (ResultSet nikdy nesmie opakovať SKU, Section 23).

Predtým existujúce zlyhania (`sauce_fish_001` atď.) zostávajú nahlásené
ako WARN, nie FAIL — nezablokujú každý budúci commit kým niekto neopraví
V2.4-éra kaskádu mimo rozsahu tohto sprintu.

## CLI (`scripts/run_evaluation.py`)

```bash
python scripts/run_evaluation.py --fast              # CI, ~12s, kritické prípady
python scripts/run_evaluation.py --full               # lokálne/release, všetky prípady
python scripts/run_evaluation.py --full --diff         # porovnanie s baseline
python scripts/run_evaluation.py --full --save-baseline <commit>
python scripts/run_evaluation.py --case rice_jasmine_001   # drilldown
```

## Testy evaluátora (Section 100/101)

`tests/test_evaluation_engine.py` (30 testov): metrické výpočty, deliberate-
failure detekcia (vloženie neoprávneného produktu, zlá ordinal referencia,
context contamination — evaluátor ich musí ODHALIŤ, nie potichu prejsť),
baseline diff/gate logika, integrita datasetu. `tests/
test_evaluation_golden.py` (1 test): kritická sada integrovaná priamo do
`pytest tests/ -q`.

## Ako znovu overiť

```bash
python -m pytest tests/test_evaluation_engine.py tests/test_evaluation_golden.py -q
python scripts/run_evaluation.py --full
```

## Vzťah k V2.12.4 (Search Quality Observability)

V2.10 zostáva autoritou pre kontrolovanú, deterministickú golden pravdu
(fixný dataset, fixná sada regresných prípadov). V2.12.4 pridáva
komplementárny, nie konkurenčný zdroj: skutočný produkčný dôkaz
(`search_quality.jsonl`, agregácie, hard canary). Žiadny z nich
nenahrádza druhý — produkčné správanie je evidencia, nie golden pravda
(V2.12.4 Invariant #3/#4). Pozri `docs/search-quality-observability.md`.
