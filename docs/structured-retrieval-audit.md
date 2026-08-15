# Structured Retrieval & Category-Aware Ranking — Sprint V2.4 audit

Dátum: 2026-08-15. Zdroj: committed `data/products.json` (2 140 produktov,
rovnaká fixture ako pinned test suite), taxonómia z Sprint V2.3
(`taxonomy_coverage` = 33,64 %, 16 kanonických rodín, 27 podrodín).

## Architektúra

```
query text
  -> StructuredProductQuery   (app/query_constraints.py: parse_structured_query)
  -> RetrievalResult          (app/retrieval.py: retrieve_products)
       exact_match_ids / valid_match_ids / nearest_match_ids
  -> ranked product ids       (app/ranking.py: rank_candidates)
  -> formatted product dicts  (app.search.format_product)
```

`app/structured_search.py` je jediný integračný bod: `hybrid_search_products()`
(drop-in náhrada za `search_products(products, query, limit)`) a
`retrieve_products_for_query()` (plný `RetrievalResult` pre budúce
workflow volania, Section 84 zadania — `retrieve_products(structured_query,
context)` tvar, nie „parsuj celú chat odpoveď v search vrstve").

Retrieval a ranking sú striktne oddelené moduly (Section 2 zadania):
`app/retrieval.py` nikdy neskóruje, iba prienik množín; `app/ranking.py`
nikdy nepridáva/neuberá kandidáta, iba mení poradie.

## Query model — explicit vs. inferred

`StructuredProductQuery` (`app/query_constraints.py`) nesie `family`,
`subfamily`, `attributes`, `brand`, `package_size`, `dietary_facets` +
`explicit_constraints: set[str]` + `constraint_sources: dict[str,str]`
(`EXPLICIT` / `INFERRED_HIGH` / `INFERRED_MEDIUM`).

**Kľúčové pravidlo:** family/subfamily/attributes sa parsujú **reuse-om V2.3
taxonómie** (`app.taxonomy.FAMILY_DEFINITIONS`), nie druhou nezávislou
taxonómiou (Section 7 zadania) — rovnaký most-specific-first,
collision-guarded zoznam pravidiel, ktorý klasifikuje produkty, klasifikuje
aj text dopytu (title-only cesta, keďže dopyt nemá „kategóriu"). Vďaka tomu:

- `"ryžový ocot"` → `vinegar/rice_vinegar`, NIE `rice` (Section 8)
- `"ryžové rezance"` → `noodles/rice_noodles`, NIE `rice`
- `"sójová omáčka"` → `sauce/soy_sauce`, nie celá `sauce` rodina

**Generic-family-only výnimka:** iba `plain_rice` pravidlo (bare "ryža" v
akomkoľvek páde) sa NEpremieta na tvrdý subfamily/attribute filter — inak by
široký dopyt "ryža" nesprávne vylúčil sushi/jazmínovú/basmati ryžu z
vlastnej rodiny (poruší specificity monotonicity, Section 26). Každé INÉ
zhodné pravidlo (napr. `soy_sauce`, `instant_noodles`, `miso`) už vyžaduje
kvalifikovanú/zloženú frázu na zhodu vôbec — samotná zhoda JE explicitný
tvrdý filter, aj keď pravidlo nenesie vlastný `attributes` tuple (väčšina
sauce/paste/seaweed/instant_food podrodinových pravidiel ho nemá).

**Sushi-rice špeciálny prípad:** `"ryža na sushi"` (anglický pravopis,
odlišné poradie slov než produktový titulok `"sushi ryža"`) sa rieši
rovnakým bare-token co-occurrence trikom, aký už používa
`classify_rice_query()` (message-level shadow classifier z V2.1) — nie
nová logika.

## Retrieval modes

`STRUCTURED_EXACT` (explicitná brand/size), `STRUCTURED_FILTERED`
(explicitná subfamily/attributes/dietary), `STRUCTURED_BROAD` (iba family),
`LEGACY_FALLBACK` (rodina nerozpoznaná).

## Confidence gating (Section 10)

`StructuredProductIndex` (`app/retrieval.py`) obsahuje **iba** produkty s
taxonómiou `HIGH` alebo `MEDIUM` — z 2 140 produktov je to **712**
produktov (33,3 %) naprieč **15 rodinami** (`tea` má v tejto fixture 0
produktov, preto 15 nie 16), **25 podrodinami**, **18** distinct
attribute (kľúč,hodnota) pármi, **157** značiek, **4** dietetické facety
(`gluten_free`, `vegan`, `vegetarian`, `organic`). `LOW`/`UNKNOWN` produkty
(67 % katalógu) nikdy nevstupujú do indexu — ostávajú plne dostupné cez
nezmenený `search_products()` legacy fallback (Section 71/72, overené
testom `test_low_confidence_product_absent_from_structured_index` a
`test_tofu_is_unknown_and_uses_legacy_fallback`).

## EXACT / VALID / NEAREST (Section 17/18/28)

`retrieve_products()` počíta `valid_match_ids` (P1 identita + P2 selekcia:
family/subfamily/attributes/dietary, vždy tvrdo filtrované) a
`exact_match_ids` (navyše P3 komerčné: brand/package_size, len ak boli
explicitne uvedené). Ak je `exact_match_ids` prázdna, deterministická
stupňovitá relaxácia (Section 18) skúša v poradí:

1. relax `package_size`, drž `brand` (veľkosť je menej identity-blízka)
2. relax `brand`, drž `package_size`
3. relax obe → celá `valid_match_ids` množina

Výsledok sa označí `nearest_match_ids` + `relaxed_constraints` (napr.
`["package_size=2.0kg"]`) — nikdy sa nepredstiera ako exact match
(overené `TestRelaxationMetadata`).

## Ranking layers (Section 30, `app/ranking.py`)

Lexikografický sort key, nie jeden opaque súčet — nižšia vrstva nikdy
nemôže prebiť vyššiu:

1. **L1 taxonomy confidence** (HIGH > MEDIUM)
2. **L2 explicit P3 satisfaction count** (koľko z explicitného brand/size
   tento konkrétny produkt spĺňa — implementuje Section 31: Foodland+
   jazmínová+5kg musí byť nad Foodland+jazmínová+1kg musí byť nad
   Iná-značka+jazmínová+5kg)
3. **L3 availability** (in_stock)
4. **L4 relevance** (ľahký title/brand token-overlap tie-break nad už
   malou, už-validnou množinou — nie plný fuzzy sken katalógu)
5. **L5-L7 soft multiplier** (behavioral CTR × merchandising × personalizácia,
   kombinované do JEDNÉHO finálneho tie-breaku, striktne pod L1-L4)
6. **deterministický tie-break**: product id (Section 46/47)

Keďže L5-L7 sedí striktne pod L1-L4 v sort key, popularita/personalizácia
**štrukturálne nemôžu** prebiť explicitný zákaznícky constraint — nie je to
len konvencia, je to vlastnosť tuple-sort-u (overené
`TestPopularityOverride`/`TestPersonalizationOverride`).

## Aktivované rodiny a fallback

Štrukturovaný retrieval je aktívny pre **každú** rodinu s aspoň jedným
HIGH/MEDIUM produktom v aktuálnej taxonómii (žiadny ručný per-rodina
zoznam) — bezpečnostný mechanizmus je confidence gating na úrovni
produktu (vyššie), nie rodiny. Feature flag
`V2_STRUCTURED_RETRIEVAL_ENABLED` (default `true`) umožňuje okamžitý
rollback bez deploymentu (Section 42).

Legacy `search_products()` zostáva fallback pre:
- nerozpoznanú/UNKNOWN rodinu (`tofu`, `wasabi` — rovnaké vedomé V2.3
  rozhodnutia, teraz overené aj na retrieval úrovni)
- LOW-confidence klasifikáciu
- akúkoľvek neočakávanú výnimku v štruktúrovanej ceste (`hybrid_search_products`
  má `try/except` s fallbackom, Section 82 — nikdy nie single point of failure)
- prázdny formátovaný výsledok po ranking kroku (defenzívne)

Zapojené v `app/main.py` na **presne dvoch** miestach — primárny
customer-facing `product_search` fallback v `chat()` a `/products/search`
endpoint. Recipe/replacement/cross-sell/special-subject interné vyhľadávania
(`cached_search_products()` volané z `sushi_shopping_core_products()` a pod.)
**zostávajú nezmenené** (Section 37/38/86/87 — cross-sell/alternatives sa do
primárneho matchingu nemiešajú).

## Testy (`tests/test_structured_retrieval.py`, 44 testov)

- **Specificity monotonicity** (Section 26/65, `TestSpecificityMonotonicity`):
  `results("ryža") ⊇ results("jazmínová ryža") ⊇ results("FOODLAND
  jazmínová ryža 5 kg")`, overené na syntetickom katalógu aj nad
  `sójová omáčka` reťazcom.
- **Kolízne testy** (Section 66, `TestCollisionProtection`): ryža vylučuje
  ryžové rezance/ocot/múku/ryžovar/papier; sójová omáčka vylučuje čiernu
  fazuľu omáčku a tofu; kokosové mlieko vylučuje kokosovú vodu AJ kokosový
  olej; kari pasta vylučuje kari korenie AJ opačnú varietu; miso pasta
  vylučuje instantnú miso polievku.
- **Veľkostné testy**: `5000 g == 5 kg` (exact match), `500 ml != 1 l`
  (`size_matches()` priamo).
- **Brand testy**: explicitná značka zužuje množinu; známa značka bez
  zhodného produktu correctly relaxuje (nie crash).
- **Dietary test**: `bezlepková sójová omáčka` vylučuje produkt bez
  `gluten_free` facetu.
- **UNKNOWN/LOW-confidence fallback**: `tofu`/`wasabi` → `LEGACY_FALLBACK`;
  štrukturálny invariant že index obsahuje iba HIGH/MEDIUM.
- **Ranking invarianty** (Section 73): ranking je permutácia (rovnaká
  množina, rovnaká dĺžka), behaviorálny signál nemení validnú množinu,
  determinizmus (dva behy → identický výsledok).
- **Popularity override** (Section 74): produkt so správnou veľkosťou musí
  byť nad produktom s nesprávnou veľkosťou aj keď má ten druhý extrémne
  vysokú CTR.
- **Personalization override** (Section 75): explicitný brand dopyt úplne
  ignoruje personalizačné skóre pre inú značku (tá sa ani nemôže objaviť
  mimo exact množiny).
- **Autocomplete handoff** (Section 50): `query_from_constraints()` —
  server-known constraints z klik-akcie sa použijú priamo, žiadne
  reparsovanie textu.

Plný beh: **709/709** (665 pred V2.4 + 44 nových), 0 regresií.

## Performance (Section 91, `data/products.json`, teplé cache, 6 reprezentatívnych dopytov)

```
parse_structured_query():                    0.027 ms/dopyt
parse + retrieve_products():                  0.038 ms/dopyt
parse + retrieve + rank_candidates() (plné):  1.09  ms/dopyt
legacy search_products() (pre porovnanie):    19.7  ms/dopyt
```

Štruktúrovaný retrieval je pri porovnateľných dopytoch **~18× rýchlejší**
než plný lexikálny/fuzzy sken (Section 56 — očakávané, keďže ide o prienik
malých invertovaných indexov, nie sken celého katalógu). Pamäť:
`StructuredProductIndex` ukladá iba `product_id` reťazce v množinách
(žiadna duplicitná `Product` dáta, Section 92) — pre 712 indexovaných
produktov rádovo desiatky KB.

## Nález pri produkčnej live verifikácii (Section 96), opravený pred dokončením

Live overenie na produkcii (`kikkoman sojova omacka` a `sojova omacka` proti
skutočnému katalógu) odhalilo, že V2.3-era pravidlá `soy_sauce`/
`dark_soy_sauce`/`light_soy_sauce` (title-only, bez `category_terms`) chytali
akýkoľvek produkt, ktorého titulok len SPOMÍNA "sójová omáčka" ako príchuťový
popis – napr. `"Instantné rezance NISSIN Demae Ramen Sójová omáčka 100 g"`
(instantné rezance, nie fľaša sójovej omáčky). V shadow-mode V2.3 bola táto
nesprávna klasifikácia neviditeľná; s aktívnym V2.4 retrievalom sa stala
priamo zákazníkovi viditeľným nesprávnym výsledkom pre dopyt "sójová
omáčka". Opravené pridaním `exclude_title_phrases=("instantna",
"instantne")` na všetky 3 pravidlá – rovnaký guard, aký už mala
`teriyaki_sauce` pre identickú kolíznu triedu z V2.3. Po oprave:
`HIGH=513 MEDIUM=199` (predtým 512/200), 709/709 testov, overené aj priamo
na produkcii po redeployi. Toto je presne ten typ nálezu, pre ktorý Section
96 ("does every primary returned product satisfy the interpreted query?")
existuje – nie zlyhanie, ale dôkaz, že kontrola funguje.

## Zostávajúce riziká (úprimne, nie vyhladené)

- `tea` rodina má v aktuálnej fixture 0 HIGH/MEDIUM produktov (hoci V2.3
  audit report ju uvádza s dôkazom v živom feede) — fixture drift medzi
  `data/products.json` a živým feedom, rovnaký typ rozdielu ako V2.3
  dokumentoval, nie regresia tejto iterácie.
- Relaxácia (Section 17/18) je 3-stupňová, nie plný "skús všetky
  kombinácie constraint-ov" prehľadávač — dostatočné pre V2.4 rozsah
  (metadata musí existovať, plná prezentácia patrí V2.5), ale pri budúcom
  rozšírení o viac P3 dimenzií (napr. price range) bude treba
  všeobecnejší algoritmus.
- `dietary_facets` detekcia v dopyte je fráza-based na malej sade koreňov
  (`bezlepkov`, `vegansk`, `vegetariansk`, `bio`) — pokrýva presne to, čo
  V2.3 taxonómia vie dokázať z reálnych category memberships, nič viac.
- Personalizácia nie je zapojená priamo do `hybrid_cached_search_products()`
  volania v `app/main.py` (parameter `personalization_scores` zostáva
  `None`) — existujúci `personalize_products()` postprocessing krok v
  `chat()` beží AJ nad štruktúrovanými výsledkami (agnostický k pôvodu
  zoznamu), takže Section 35 je splnená end-to-end, ale priama
  `app.ranking` L6 vrstva je zatiaľ nevyužitá v produkčnej ceste —
  kandidát na prepojenie v budúcej iterácii, ak sa ukáže potrebné.

## Ako znovu overiť

```bash
python -m pytest tests/test_structured_retrieval.py -q
python -c "from app.feed import load_products_json; from app.taxonomy import build_taxonomy_index; from app.product_normalizer import normalize_catalog; from app.retrieval import get_structured_index; p=load_products_json('data/products.json'); print(get_structured_index(p, build_taxonomy_index(p), normalize_catalog(p)).family_index.keys())"
```
