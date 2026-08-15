# Contextual Cross-Sell & Basket Intelligence — Sprint V2.6 audit

Dátum: 2026-08-15. Zdroj: committed `data/products.json` (2 140 produktov), V2.5 ResultSet (`docs/result-presentation-audit.md`), reálne curated dáta z `app/main.py` (`RECIPE_SHOPPING_CORE_QUERIES`, `SPECIAL_PRODUCT_QUERIES`) a `data/knowledge.json["CrossSell"]`.

## Architektúra

```
V2.5 ResultSet (primary, už rozhodnutý)
  -> should_cross_sell()              (app/cross_sell.py — eligibility gate)
  -> complementary roles              (grounded v curated dátach, nie vymyslené)
  -> generate_candidates()            (role-first, multi-source)
  -> same-need/duplicate exclusion    (subfamily-level, nie family-level)
  -> rank_candidates()                (deterministické, evidence-weighted)
  -> compose_cross_sell_intro()       (template text, žiadne LLM)
```

`app/cross_sell.py` je jediný nový modul. Nikdy neimportuje z `app/main.py`
(Section 110) — `set_data_sources()` sa volá raz z `main.py` po definícii
`RECIPE_SHOPPING_CORE_QUERIES`/`SPECIAL_PRODUCT_QUERIES`, ktoré cross-sell
modul iba ČÍTA.

## ELIGIBILITY (kedy sa cross-sell aktivuje a kedy nie)

`should_cross_sell()` je konzervatívny by default:

| situácia | eligible? | dôvod |
|---|---|---|
| holá varieta ("jazmínová ryža") | **NIE** | žiadny recipe/use_case kontext (Section 31/88) |
| use_case atribút na koncepte (napr. sushi_rice) | ÁNO | `USE_CASE_COMPLETION` |
| `related_subject` zodpovedá receptu v `RECIPE_SHOPPING_CORE_QUERIES` | ÁNO | `RECIPE_COMPLETION` |
| SHOW_MORE/SHOW_ALL pokračovanie | **NIE** | Section 36 — nikdy nový cross-sell počas stránkovania |
| `NO_EXACT_MATCH` / `GROUPED_DISCOVERY` stratégia | **NIE** | primárny problém ešte nevyriešený / príliš skoro (Section 31/41/42) |
| `EXACT_MATCH` bez kontextu | **NIE** | presné SKU vyhľadanie sa neplní nesúvisiacim cross-sellom (Section 40/87) |

**Kritický nález z návrhu (dôležitý, nie kozmetický):** priama curated
`CrossSell` sekcia v `knowledge.json` pre reálny produkt jazmínovej ryže
odporúča kari pastu, sójovú omáčku, čili omáčku a MSG — presne ten typ
"predpokladu kari" zápisu, ktorý zadanie explicitne zakazuje pre holý
dopyt (Section 31: *"Do not immediately recommend curry paste + coconut
milk"*). Preto sa curated `CrossSell` dáta v V2.6 používajú **iba na
posilnenie roly, ktorú už ustanovil recipe/use_case kontext** — nikdy
ako samostatný spúšťač eligibility.

## ZDROJE (hierarchia dôkazov, Section 9)

1. **RECIPE** — `RECIPE_SHOPPING_CORE_QUERIES` (47 jedál, kurátorský
   zoznam ingrediencií na jedlo), každá ingrediencia normalizovaná cez
   `app.query_constraints.parse_structured_query()` na kanonický
   `concept_id` (Section 11). Príklad: `pad_thai` → `['rice_noodles',
   'fish_sauce']` (tamarind pasta, palmový cukor, arašidy nemajú
   taxonomy koncept — čestne vynechané, nie odhadnuté).
2. **USE_CASE (curated)** — malá, ručne overená podmnožina
   `SPECIAL_PRODUCT_QUERIES` (`sushi_rice`, `gluten_free_sushi`,
   `sushi_condiments`, `rice_seasoning`) — položky, ktoré popisujú AKO
   produkt použiť, nie generické marketingové témy ("mild"/"hot"/
   "kids_snack" boli po inšpekcii zámerne vynechané presne z vyššie
   uvedeného dôvodu). Príklad: `sushi` → `['nori', 'rice_vinegar',
   'soy_sauce']` (+ samotný `sushi_rice`, ktorý sa vylúči ako primárna
   potreba).
3. **CURATED CrossSell** — `knowledge.json["CrossSell"]`, per-produkt,
   `Cross-sell N_url` vyriešené na `product_id` porovnaním s
   `product.link` (overené: 1000/1000 URL v testovacej vzorke sa
   zhodovalo). Používa sa iba na posilnenie/pridanie do už schválenej
   role (nikdy nezavádza novú rolu — Section 51).
4. **FBT** — `app.fbt.fbt_recommendations()`, validované sémanticky pred
   akýmkoľvek použitím (nižšie).

## FBT — ako sa surová behaviorálna korelácia nedostane nad sémantiku

FBT kandidát sa **nikdy** nepoužije, pokiaľ:
- nemá `concept_id` v taxonómii, ktorý je súčasťou už ustanovených
  `complementary_roles` (Section 15/16 — FBT nesmie sám o sebe vytvoriť
  novú rolu), **a**
- nespĺňa `_same_primary_need()` kontrolu (ak FBT navrhne ďalší produkt
  rovnakej podrodiny ako primárny — napr. inú sójovú omáčku k sójovej
  omáčke — je to ALTERNATÍVA, nie cross-sell, a je tvrdo odmietnutý bez
  ohľadu na silu FBT signálu, Section 17/29/51/91).

FBT teda funguje výhradne ako **posilnenie/tie-break** existujúceho
kandidáta (Section 16), nikdy ako nezávislý zdroj eligibility.

## BASKET INTELLIGENCE

`exclude_ids` = celá `ResultSet.ranked_product_ids` množina (nielen
zobrazená stránka) — žiadny primárny/nearest produkt sa nemôže objaviť
ako cross-sell (Section 21/83, overené testom, 0 prekryvov).

Skutočný "košík"/cart stav **nie je v aktuálnej architektúre widgetu
exponovaný** (Section 19: *"Do not invent cart state if widget/backend
does not currently expose it"*) — V2.6 preto zámerne NEIMPLEMENTUJE
`BasketContext` nad neexistujúcimi dátami. Namiesto toho sa spolieha na
`ResultSet`-based exclúziu (čo bolo zákazníkovi PRÁVE ukázané ako
primárny výsledok) ako jediný poctivo dostupný "basket" signál.

## SAME-NEED EXCLÚZIA — granularita (kritický nález)

Prvá implementácia porovnávala `canonical_family` (napr. "sauce") — to
je **príliš hrubé**: `family="sauce"` zahŕňa sójovú, rybaciu, ustricovú,
hoisin aj čili omáčku, ktoré sú navzájom genuinely odlišné doplnkové
potreby, nie substitúty. S family-level porovnaním by `fish_sauce`
NIKDY nemohla byť cross-sell kandidát pre sójovú omáčku — čo by tichým
spôsobom rozbilo presne scénar Pad Thai (Section 85).

Opravené na **`canonical_subfamily`** porovnanie (fallback na `family`
iba keď `subfamily` je `None`, napr. curry pasta varianty, kde rôzne
príchute SÚ navzájom substitúty). Overené testom
`test_subfamily_level_not_family_level_exclusion`.

## RANKING (Section 25)

Lexikografické zoradenie: (1) `-score` (zdroj priorita: RECIPE=4 >
USE_CASE=3 > CURATED=2 > FBT=1, s multi-source bonusom pri zhode), (2)
`product_id` (deterministický tie-break, Section 47).

## ROLE BUDGET (Section 22/23/24)

`DEFAULT_MAX_PRODUCTS = 3`. Jeden produkt na rolu (žiadne 3 sójové
omáčky pre jednu potrebu) — role diversity overená testom.

## PRÍKLADY (živý beh cez `app.main.chat()`, nie izolovaný modul)

**Sushi use-case:**
```
"ryza na sushi" -> primárne: 4× sushi ryža
cross_sell_eligible=True, context=USE_CASE_COMPLETION
cross_sell_intro="K tomu sa vám môže hodiť aj:"
  - Sójová omáčka menej soli KIKKOMAN (role=soy_sauce)
  - Morské riasy polovičné SUSHINORI (role=nori)
  - Ryžový ocot MIZKAN (role=rice_vinegar)
```

**Pad Thai recept (simulovaný `related_subject="pad_thai"`):**
```
"sójová omáčka" -> primárne: 56 sójových omáčok
cross_sell_eligible=True, context=RECIPE_COMPLETION
  - PHO GA instantná polievka (role=rice_noodles)
  - Rybacia omáčka SQUID BRAND (role=fish_sauce)
```

**Generický dopyt (konzervatívne správanie):**
```
"jazmínová ryža" -> cross_sell_eligible=False, reason="no_grounded_context"
```

**Potlačený prípad:**
```
"FOODLAND jazmínová ryža 2 kg" (NO_EXACT_MATCH) -> cross_sell_eligible=False
```

## QUALITY

- **Same-need kontaminácia:** 0 (hard-tested, `TestSameNeedContamination`).
- **Duplicitné IDs medzi primary a cross-sell:** 0 (hard-tested).
- **Slabé odporúčania:** FBT-only kandidáti bez role zhody sa nikdy nezobrazia (overené testom).

## TESTY

`tests/test_cross_sell.py` (21 testov): eligibility gate (7 scenárov),
same-need contamination (3), duplicate exclusion (1), role generation
zo skutočných curated dát (3), FBT sémantická validácia (2), multi-source
ranking (2), role diversity/budget (2), reason text grounding (1).

Plný beh: **752/752** (731 pred V2.6 + 21 nových), 0 regresií.

## PERFORMANCE

Cross-sell pridáva ~0,19 ms/dopyt (1,35 → 1,54 ms) nad V2.4+V2.5 —
zanedbateľné v porovnaní s network/OpenAI latenciou. Bez plných
katalógových skenov — role lookup je O(1) cez precomputed `concept_id`
index.

## RIZIKÁ (úprimne)

- Plná dvoj-ťahová konverzačná perzistencia ("Chcem robiť sushi." →
  "Akú ryžu?") závisí od PRE-EXISTUJÚCEHO `is_context_followup()`
  heuristického detektora vo `app/main.py` (z V2.1), ktorý nerozpoznáva
  "akú ryžu?" ako pokračovanie bez explicitného markera ("k tomu",
  "odporúč", ...). V2.6 tento mechanizmus zámerne nerozširuje (Section
  34: *"Use current conversation-state architecture. Do not invent a
  separate memory system"*) — jednoťahové dopyty s explicitným
  use_case/receptom (napr. "ryža na sushi") fungujú spoľahlivo cez
  skutočný `chat()`, overené naživo.
- `BasketContext` (Section 19) je zámerne minimálny — žiadny reálny
  cart API v aktuálnej architektúre, takže V2.6 exclúzia sa opiera iba
  o aktuálny `ResultSet`, nie o históriu celej konverzácie/objednávky.
- Curated `CrossSell` dáta (`knowledge.json`) obsahujú zjavne
  marketingovo orientované páry (kari pasta k ryži) — V2.6 ich preto
  používa iba ako posilňovač, nikdy ako nezávislý spúšťač; budúca
  iterácia by mohla curated dáta prehodnotiť/prečistiť priamo pri
  zdroji namiesto obchádzania v aplikačnej vrstve.

## Ako znovu overiť

```bash
python -m pytest tests/test_cross_sell.py -q
```
