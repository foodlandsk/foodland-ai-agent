# Recipe & Ingredient Knowledge Audit — Sprint V2.8

Dátum: 2026-08-16. Zdroj: aktuálny `data/knowledge.json` (post-V2.7, 58 receptov v CMS
sekcii `Recipes`), aktuálny `app/main.py` (RECIPE_SHOPPING_CORE_QUERIES,
MISSING_INGREDIENTS_BY_SUBJECT, RECIPE_TITLE_PRODUCT_SUBJECTS, SPECIAL_PRODUCT_QUERIES),
aktuálny `app/taxonomy.py` (V2.3 rule registry). Žiadne historické počty nie sú
prevzaté zo starších sprintov bez overenia.

## Kľúčové zistenie: CMS `Recipes` sekcia neobsahuje ingrediencie

`knowledge["sections"]["Recipes"]` (58 záznamov) má tento reálny, úplný
zoznam polí naprieč všetkými záznamami:

```
Kuchyňa, Recept (SK názov), SK, CZ, AT, EN, PL, HU, VI,
SK_url, CZ_url, AT_url, EN_url, PL_url, HU_url, VI_url
```

**Neobsahuje**: zoznam ingrediencií, množstvá, jednotky, počet porcií, kroky
prípravy, ani priame odkazy na produkty. Je to čisto CMS metadáta pre
lokalizované URL recept-článkov (jeden kanonický recept → 7 lokalizovaných
URL) + kuchyňa (cuisine) + SK názov.

Toto znamená, že zadanie V2.8 (Section 2) očakávajúce "ingredient lists,
quantities, units, servings... product links" priamo v Recipes datasete
**nie je splniteľné z tohto zdroja**. Namiesto vymýšľania dát (zakázané,
Section 139) V2.8 grounduje skutočnú ingredienciu-produkt inteligenciu na
inom, reálne existujúcom a v produkcii už používanom zdroji (nižšie).

## Skutočný zdroj ingrediencií: `RECIPE_SHOPPING_CORE_QUERIES`

`app/main.py:1954` obsahuje kurátorský slovník **47 jedál** (dish key →
zoznam `(display_name_sk, required_terms, excluded_terms)` trojíc), aktívne
používaný legacy RECIPE_SHOPPING cestou (`recipe_shopping_core_products()`)
od skoršej V2.1-éry. Toto JE reálna, overená, produkčne používaná
ingrediencia-úroveň dát — presne to, čo V2.8 potrebuje ako "recipe
ingredient" ground truth.

Príklad (`pad_thai`):
```
ryzove rezance   required=(rezance,)                 excluded=()
tamarind pasta   required=(tamarind,)                 excluded=()
rybacia omacka   required=(rybacia omacka,)            excluded=()
palmovy cukor    required=(cukor,)                     excluded=()
arasidy          required=(arasid,)                     excluded=()
```

47 dishes celkovo, 3–5 ingrediencií na jedlo, spolu ~190 recipe-ingredient
záznamov. Žiadne množstvá/jednotky/porcie nie sú prítomné — je to plochý
zoznam, nie štruktúrovaný recept.

## Doplnkový zdroj: `MISSING_INGREDIENTS_BY_SUBJECT`

`app/main.py:1895` — kurátorský slovník **52 subjectov** (superset
RECIPE_SHOPPING_CORE_QUERIES, vrátane dishes bez core queries ako
`sushi`, `vindaloo`, `karaage`, `tom_yum`, `ryza`, `gyoza`, `spring_roll`)
→ zoznam surovín, ktoré Foodland **nepredáva** (čerstvé mäso, zelenina,
bylinky, voda, soľ). Toto je priama ground truth pre `NOT_AVAILABLE` status
v RecipeShoppingPlan — nie je potrebné ju odvodzovať, už existuje a je
kurátorská.

## Dish/Recipe entity zdroj: `RECIPE_TITLE_PRODUCT_SUBJECTS`

`app/main.py:1571` — zoznam `(title_marker, dish_subject)` dvojíc používaný
obojsmerne: (a) na rozpoznanie dish subjectu z voľného textu dopytu
("chcem robiť pad thai" → marker "pad thai" nájdený → subject="pad_thai"),
(b) na priradenie subjectu k reálnemu Recipes CMS záznamu podľa titulku.
Toto je existujúci **dish alias index** — V2.8 ho znovu používa namiesto
vytvárania duplicitného.

## Substitúcie: iba jeden legitímny kurátorský zdroj

`SPECIAL_PRODUCT_QUERIES["vegan_fish_sauce_replacement"]` (`app/main.py`,
V2.6 cross-sell zdroj) obsahuje explicitný kurátorský substitučný zámer:
rybacia omáčka → vegánska náhrada (sójová omáčka / tamari / hubová
vegetariánska omáčka), kontext="vegan". Toto je **jediný** substitučný
vzťah v repozitári, ktorý má jasný, obhájiteľný pôvod (kurátor, nie lexikálna
podobnosť). `Alternatives` sekcia (2140 záznamov, 1:1 na produkt) je
produkt→produkt v rámci rovnakej kategórie (viď nižšie) — nie
ingrediencia-úroveň substitúcia, preto ju V2.8 nepoužíva ako zdroj
substitučného grafu (Section 37/38/40).

## `Alternatives` sekcia: produkt → produkt, nie koncept → koncept

Vzorka (`FL_11279`, Instant Tapioca Pearls): `Alternativa 1/2` sú vždy iný
produkt **v tej istej kategórii** (rovnaká podkategória, podobná cena/značka),
nikdy iný ingrediencia-koncept. Toto potvrdzuje, že `Alternatives` je zdroj
pre V2.7 `REPLACEMENT` workflow (produktová náhrada), nie pre V2.8
substitučný graf (Section 38 rozhodnutie: NEnormalizovať do
ingredient-graph, ponechať oddelené).

## `Products_AI` sekcia: reverse product→recipe evidencia (limitovaná)

130 záznamov, z toho **15** má vyplnené pole `Súvisiaci recept` (napr.
`FL_7279` → "Vegánske Pad Thai"). Toto je jediný priamy, kurátorský
produkt→recept odkaz v repozitári — používa sa ako HIGH-confidence seed pre
reverse lookup (Section 48/50), doplnený o odvodenú evidenciu z
`ingredient_to_recipes` indexu (nižšie confidence, evidence=`INFERRED`).

## Prienik s V2.3 taxonómiou

Z ~40 unikátnych ingrediencia-konceptov naprieč 47 core dishes, **cca 20**
má priamy zhodný `rule_id` vo `app/taxonomy.py` (napr. `fish_sauce`,
`soy_sauce`, `dark_soy_sauce`, `light_soy_sauce`, `oyster_sauce`,
`hoisin_sauce`, `sriracha_sauce`/`chili_sauce` rodina, `miso`, `gochujang`,
`coconut_milk`, `sesame_oil`, `rice_noodles`, `jasmine_rice`,
`basmati_rice`, `sushi_rice`, `rice_vinegar`, curry_paste rodina). Tieto
V2.8 mapuje 1:1 (`ingredient_concept_id = taxonomy rule_id`), so
`source=PRODUCT_TAXONOMY`, `confidence=HIGH`.

Zvyšné (tamarind, palmový cukor, arašidy, galangal, citrónová tráva,
kaffir listy, mirin, dashi, doenjang, tofu, garam masala, biryani pasta,
tandoori masala, sambal oelek, ssamjang, adzuki, shiitake, sinigang zmes,
bulgogi omáčka, tikka masala pasta, rendang pasta a i.) **nemajú** taxonomy
rule — V2.8 ich mapuje cez existujúce `required_terms`/`excluded_terms` ako
`source=RECIPE_CURATED`, `confidence=MEDIUM` (kurátorské, produkčne
overené, ale nie taxonomicky klasifikované).

**Chýbajúce taxonomy rules potvrdené**: `coconut_cream`, `coconut_oil` ako
samostatné rules v `app/taxonomy.py` neexistujú (iba `coconut_milk` a
`coconut_water`). Section 103 test (coconut_milk/cream/oil oddelené)
overuje sémantickú NEZLUČITEĽNOSŤ konceptov cez `resolve_ingredient_products`
vracajúce `NOT_AVAILABLE`/`UNKNOWN_MAPPING` pre coconut_cream/coconut_oil
namiesto ich falošného stotožnenia s coconut_milk — nie cez nové taxonomy
pravidlá (mimo rozsahu V2.8, žiadne coconut_cream/coconut_oil produkty
potvrdené v katalógu).

## Chýbajúce dáta — čestné obmedzenia (nie budú vymyslené)

- **Množstvá/jednotky/porcie**: 0 z 47 core dishes má štruktúrované
  množstvo. Serving scaling (Section 24) a package count (Section 29)
  ostávajú implementované ako testovaná, no v produkcii **neaktívna**
  schopnosť (žiadny reálny recept ju nevyužije, kým sa dataset nerozšíri).
- **Required vs Optional vs Garnish**: zdrojový dataset nerozlišuje. V2.8
  konzervatívne označuje všetky core-query ingrediencie ako `REQUIRED`
  (to je presne dôvod, prečo boli kurátorom označené ako "core") a
  nepridáva `OPTIONAL`/`GARNISH` flag bez dôkazu (Section 12: "only if
  current recipe knowledge supports it").
- **Substitúcie**: iba 1 kurátorský vzťah existuje (vyššie). V2.8
  neprodukuje ďalšie.

## Počty (aktuálne, k 2026-08-16)

```
Recipes (CMS):              58
RECIPE_SHOPPING_CORE_QUERIES dishes: 47
MISSING_INGREDIENTS_BY_SUBJECT subjects: 52
RECIPE_TITLE_PRODUCT_SUBJECTS aliases: 60+ marker->subject páry
SPECIAL_PRODUCT_QUERIES: 25 (1 substitučný: vegan_fish_sauce_replacement)
Products_AI: 130 (15 s priamym Súvisiaci recept odkazom)
Alternatives: 2140 (produkt->produkt, 1-2 na produkt)
Taxonomy rules (V2.3): ~45 rule_id, HIGH=513 MEDIUM=199 LOW=8 UNKNOWN=1420 produktov (0 failures)
```

## Dôsledok pre dizajn V2.8

V2.8 stavia canonical ingredient graph na `RECIPE_SHOPPING_CORE_QUERIES` +
`MISSING_INGREDIENTS_BY_SUBJECT` + `RECIPE_TITLE_PRODUCT_SUBJECTS` (existujúce,
produkčne overené dáta), obohatené o V2.3 taxonomy tam, kde sa zhoduje.
CMS `Recipes` sekcia sa používa iba pre DISH entity metadáta (kuchyňa,
lokalizované URL, SK názov) — presne to, čo reálne obsahuje. Toto je presne
duch Section 3 ("Do not destroy existing recipe knowledge... normalize it")
a Section 141 ("UNKNOWN > WRONG MAPPING").
