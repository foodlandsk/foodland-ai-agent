# Ingredient Intelligence — Sprint V2.8 technical audit

Dátum: 2026-08-16. Zdroj kódu: `app/ingredients.py`, `app/recipe_graph.py`,
`app/recipe_shopping.py`, `app/workflow_registry.py` (RECIPE_SHOPPING
promoted to MIGRATED), `app/main.py` (wiring, byte-safe patches). Zdroj
dát: `docs/recipe-knowledge-audit.md` (Section 2 audit tento sprint).

## Prečo formalizácia nad `RECIPE_SHOPPING_CORE_QUERIES`, nie nad CMS `Recipes`

CMS `Recipes` sekcia (58 záznamov) neobsahuje ŽIADNE ingrediencie,
množstvá, jednotky, porcie ani produktové odkazy — iba `Kuchyňa`, SK
názov a 7 lokalizovaných URL. Skutočný, produkčne overený zdroj
ingrediencia-úrovne dát je `RECIPE_SHOPPING_CORE_QUERIES` (47 jedál,
`app/main.py`), doplnený o `MISSING_INGREDIENTS_BY_SUBJECT` (NOT_AVAILABLE
suroviny) a `RECIPE_TITLE_PRODUCT_SUBJECTS` (dish alias index). V2.8
CMS `Recipes` používa iba pre DISH entity metadáta (kuchyňa, lokalizované
URL), presne to, čo reálne obsahuje — nič nie je vymyslené.

## Entity/edge model (Section 4-6)

```
Dish (47, RECIPE_SHOPPING_CORE_QUERIES kľúče)
 └── recipe_ids -> RecipeRecord (53, CMS Recipes záznamy priradené cez
     RECIPE_TITLE_PRODUCT_SUBJECTS marker match)

RecipeIngredient (201, jeden na (dish_id, ingredient_concept_id))
 ├── ingredient_concept_id -> IngredientConcept
 ├── role (kontrolovaný slovník, Section 13)
 └── requirement = "REQUIRED" (viď nižšie prečo)

IngredientConcept (72)
 ├── concept_id (V2.3 taxonomy rule_id KEĎ existuje zhoda, inak slugify(display_name))
 ├── source: PRODUCT_TAXONOMY (24) | RECIPE_CURATED (48)
 ├── aliases (155 celkovo, SK + malá kurátorská multilingválna množina)
 └── SubstitutionEdge (1, fish_sauce -> sojova_omacka, context=vegan)
```

`concept_id` je NIKDY vymyslené ID pre taxonómiou pokryté koncepty — je
to priamo `FamilyRule.rule_id` z `app/taxonomy.py`, zistené EMPIRICKY
(Section 15/16/30): `resolve_ingredient_products()`/interný
`_resolve_taxonomy_concept()` zavolá skutočný V2.4
`retrieve_products_for_query()` s ingredienciou ako dopytom a použije
`concept_id` produktov, ktoré sa reálne zhodli — ak sa zhodnú na VIACERÝCH
rôznych `concept_id` (napr. holé "sójová omáčka" zasiahne `soy_sauce`
AJ `dark_soy_sauce` AJ `light_soy_sauce` v katalógu), rezolver sa
zámerne VZDÁ a spadne na RECIPE_CURATED lexikálnu vetvu namiesto
vynúteného hádania (Section 92/141 — "Parent fallback must be explicit").

## Role klasifikácia (Section 13)

Kontrolovaný slovník: `BASE/NOODLE/RICE/PROTEIN/SAUCE/SEASONING/PASTE/
OIL/ACID/SWEETENER/AROMATIC/VEGETABLE/HERB/GARNISH/TOPPING/WRAPPER/
BROTH/SOUP_BASE`. Pre PRODUCT_TAXONOMY koncepty: mapovanie z
`FamilyRule.family` (napr. `sauce`→SAUCE, `rice`→RICE, `noodles`→NOODLE).
Pre RECIPE_CURATED koncepty (žiadne taxonomy family): deterministická
keyword klasifikácia nad skutočným SK textom ingrediencie
(`app/ingredients.py: infer_lexical_role()`), fallback SEASONING keď
žiadne kľúčové slovo nesedí.

## Required vs Optional vs Garnish (Section 12) — čestné obmedzenie

Zdrojový dataset (`RECIPE_SHOPPING_CORE_QUERIES`) nerozlišuje required
od optional/garnish — je to plochý zoznam "core" surovín. V2.8 preto
konzervatívne označuje VŠETKY ako `REQUIRED` (presne to, čo "core"
znamená v pôvodnej kurácii) a nepridáva `OPTIONAL`/`GARNISH` flag bez
dôkazu. `role=GARNISH` (napr. arašidy pri Pad Thai) existuje ako
komerčná klasifikácia ("čo to JE"), nie ako tvrdenie o povinnosti nákupu.

## Substitúcie (Section 35-40)

Presne JEDEN kurátorský vzťah: `fish_sauce -> sojova_omacka`
(context=`vegan`, source=`CURATED_SPECIAL_QUERIES`, z
`SPECIAL_PRODUCT_QUERIES["vegan_fish_sauce_replacement"]`). Žiadne iné
substitúcie neboli vymyslené — `Alternatives` sekcia (2140 záznamov) je
produkt→produkt v rámci rovnakej kategórie, nie ingrediencia-koncept
úroveň (overené vzorkou, `docs/recipe-knowledge-audit.md`), preto nie je
použitá ako zdroj substitučného grafu.

## Kritický nález č. 1: ambiguous taxonomy resolution (soy sauce)

Žiadny z 47 jedál nešpecifikuje "tmavá"/"svetlá" sójová omáčka — vždy len
"sójová omáčka". `retrieve_products_for_query("sojova omacka", ...)`
korektne vracia produkty naprieč `soy_sauce`/`dark_soy_sauce`/
`light_soy_sauce` (V2.4 správanie, nezmenené). Keďže `_resolve_taxonomy_
concept()` vyžaduje ZHODU na jednom `concept_id`, tento prípad sa
zámerne vzdáva taxonomy-backed rezolúcie a padá na RECIPE_CURATED
(`sojova_omacka`, lexikálne required_terms). Toto NIE JE chyba — je to
presne Section 92 ("no silent parent-fallback guessing") v praxi.

## Kritický nález č. 2: lexikálny scoring (pho korenie ↔ Alphonso Mango)

Prvá verzia `lexical_candidates()` vrátila prvú zhodu v poradí katalógu
BEZ skóre. `required_terms=("pho",)` (pre "korenie pho"/"banh pho") je
čistý substring test — a "pho" je substring slova "Alphonso". Bez
skóre by "Alphonso Mango Pyré" vyhrala ako jediný kandidát namiesto
skutočného korenia na pho polievku. Zachytené `pytest`-om (existujúci
test `test_recipe_to_products_uses_phrase_subject_for_pho_bo_and_
kimchi_ramen` zlyhal pri plnom regresnom behu) — opravené pridaním
IDENTICKÉHO scoring systému, aký už používa produkčne overená
`app.main.recipe_core_product_candidates()` (celá fráza v title +80,
required-term count +35 každý, token overlap +12 každý), zoradené
zostupne. Overené: `korenie pho` teraz rezolvuje na
"Korenie na Vietnamskú hovädziu polievku Pho Bo ONG CHA VA 75g".

## Zapojenie do `chat()` (Section 46/54/55/122/123)

V `if recipe_subject:` vetve, presne v bode, kde predtým bežal
`recipe_shopping_core_products()`: ak `V2_STRUCTURED_RETRIEVAL_ENABLED`
a `recipe_product_subject` je jedno z 47 pokrytých jedál,
`build_recipe_shopping_plan()` sa pokúsi prevziať produkt-selekciu.
Zlyhanie (výnimka alebo dish mimo grafu) → bezpečný pád na presne ten
istý legacy kód, aký bežal pred V2.8 (Section 123 — V2.8 zlyhanie nikdy
nesmie zlomiť recipe shopping). `sushi`/`tom_yum`/`kimchi_ramen` majú
vlastné špecializované funkcie a V2.8 sa ich zámerne nedotýka (Section 5).

`app/workflow_registry.py`: `RECIPE_SHOPPING` povýšené SHADOW → MIGRATED
(rovnaké kritérium, aké už spĺňajú `PRODUCT_LOOKUP`/`CATEGORY_BROWSE`/
`ATTRIBUTE_SEARCH` — primárna cesta je nový pipeline, s explicitným
legacy fallbackom; MIGRATED nikdy neznamenalo "nikdy nespadne na
legacy"). `RoutingSignals.recipe_shopping_plan_used` rozlišuje
confidence 0.9 (V2.8 plán skutočne použitý) od 0.85 (recipe_subject
rozpoznaný, ale legacy cesta — nezmenené V2.7 správanie).

## Kritický nález č. 3: dish intent detection gap ("Chcem robiť Pad Thai")

`is_recipe_intent()` vyžaduje marker ako "recept"/"navod"/"ako pripravim"
— holé "chcem robit pad thai. co potrebujem?" (presne mandátna V2.8
formulácia, Section 100/142) cez tento gate NEPREJDE bez markera. Toto
je ROVNAKÁ trieda chyby, akú dokumentuje existujúci komentár v kóde pre
`"tom kha"` (skutočný user report: "co potrebujem na tom kha gai" padalo
do generickej cross-sell vetvy). Opravené identickým, úzkym vzorom —
pridané `"pad thai"` do `RECIPE_INTENT_MARKERS` (jeden bare dish marker,
nie generické rozšírenie). **Čestné zistenie**: rovnaký gap existuje pre
56 z 60 dish markerov v `RECIPE_TITLE_PRODUCT_SUBJECTS` (overené
skriptovo) — systematická oprava (napr. zjednotenie dvoch nezávislých
marker zoznamov) je mimo rozsahu tejto iterácie a je uvedená v RIZIKÁ.

## Basket satisfaction (Section 56-58) — implementované, nie live-zapojené

`build_recipe_shopping_plan(..., basket_product_ids=...)` a
`basket_concept_ids()` sú reálne, otestované funkcie (viď
`TestBasketSatisfaction` v `tests/test_recipe_shopping.py` — basket
položka korektne označí `ALREADY_SATISFIED`, nesúvisiaca položka
neurobí nič). **Čestné zistenie**: `ChatRequest` (`app/main.py`) nemá
žiadne cart/basket pole — `/chat` dnes nedostáva žiadny reálny signál
o obsahu košíka zákazníka (overené v schéme). Live zapojenie preto nie
je možné bez novej API zmeny mimo rozsahu V2.8 — presne tá istá
SHADOW-capability disciplína, akú V2.7 zaviedol pre svojich 5 workflow.

## Testy

`tests/test_recipe_graph.py` (24): graph integrity, Pad Thai end-to-end,
kolízne testy (rice/soy/coconut/noodle rodiny), substitúcia, unresolved,
multilingválne aliasy, reverse lookup, multi-ingredient discovery,
atomický rebuild determinizmus.

`tests/test_recipe_shopping.py` (22): plan building, basket satisfaction,
`summarize_plan()` JSON tvar, quantity parsing (numerické aj
"podľa chuti"), serving scaling aritmetika, package count (matching/
incompatible/unknown units), 6 end-to-end `chat()` testov (Pad Thai
live plán, legacy fallback pre vindaloo, context switch bez kontaminácie,
cross-sell oddelenosť, Show More/All nezmenené, Kung Pao ako druhý
nezávislý príklad).

Plný beh: **825/825** (779 pred V2.8 + 24 + 22), 0 regresií.

## Ako znovu overiť

```bash
python -m pytest tests/test_recipe_graph.py tests/test_recipe_shopping.py -q
python scripts/recipe_graph_audit.py
```
