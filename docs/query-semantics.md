# Query Semantics, Head-Concept & Constraint Enforcement — Sprint V2.12.2 / V2.12.3

Dátum: 2026-08-19 (V2.12.2), 2026-08-20 (V2.12.3 doplnenie nižšie).

## V2.12.3 dodatok — Bug C (legacy scorer) a taxonomy family-purity

V2.12.2 vedome nechalo `app/search.py`'s legacy OR-based scorer nezmenený
(pozri "Čo NEBOLO opravené" nižšie) ako zdokumentovaný zvyškový dlh. V2.12.3
mandátovalo vyriešiť ho **na základe dôkazov, nie predpokladu** — zadanie
predpokladalo "legacy scorer je root cause", čo sa malo overiť, nie
predpokladať.

### Dôkazová báza (research agent, read-only, celý call-graph)

- `search_products()` má presne 2 call sites (obe v `cached_search_products()`).
  `cached_search_products()` má **24 reálnych call sites** v `app/main.py`
  (cross-sell, replacement, autocomplete, recommend/similar, recommend/recipe,
  basket, trending, FAQ, allergen matches, ...) — **žiadny z nich neposiela
  StructuredQuery ani taxonomy kontext**, všetky volajú s holým textovým
  reťazcom. Navyše `cached_search_products()` je aj **bezpodmienečný fallback**
  samotného `hybrid_cached_search_products()` — kedykoľvek `parse_structured_query()`
  sebavedomo nerozpozná rodinu, legacy scorer beží úplne rovnako aj na
  primárnej `/chat` ceste.
- `app/search.py` **nemá import ani žiadny prístup** k `app.taxonomy`/
  `app.query_constraints` — a nemôže ho jednoducho získať: `app.taxonomy`
  už importuje `app.search` (`search_normalize`), takže opačný import by
  vytvoril kruhovú závislosť.
- `PREFIX_SYNONYMS`/token synonymá (`data/synonyms.json`) overené naživo
  proti reálnemu katalógu: `kokos`/`coconut` premosťuje 8 rôznych rodín,
  `ryz`/`rice` premosťuje 10 rôznych rodín (vrátane `kitchenware/rice_cooker`
  — spotrebič, nie ingrediencia), `sojov`/`soy` premosťuje 10 rodín,
  `rezance`/`noodles` premosťuje `noodles` aj `instant_food` naprieč. Reálny,
  naživo potvrdený dôkaz kontaminácie (nie hypotéza).

### Zvolená stratégia: C — ohraničená tranzitná vrstva (nie A, nie B)

Migrácia volajúcich (B) nedáva zmysel pre 24 call sites — väčšina z nich
(cross-sell, "čo sa hodí k X", replacement) **zámerne** chce iné/súvisiace
produkty, nie striktnú zhodu rodiny; migráciou by sa zničil ich vlastný účel.
Prestavba `search.py` na plný taxonomy-aware engine (A) by vyžadovala buď
kruhový import, alebo preposielanie StructuredQuery cez všetkých 24 call
sites — príliš invazívne pre "no third search engine" mandát.

**Zvolené**: nová funkcia `_exclude_taxonomy_family_mismatches()` v
`app/main.py`, volaná vnútri `cached_search_products()` (chráni **všetkých**
24 call sites naraz vrátane hybrid-fallback cesty, jedno miesto). Mechanizmus:
pre KAŽDÝ jednotlivý `cached_search_products(query, ...)` volanie sa interne
zavolá `parse_structured_query(query)` (funguje na holom texte, netreba
katalóg) — ak dopyt sebavedome (HIGH/MEDIUM) rozpozná rodinu, kandidáti sa
prefiltrujú cez existujúci `product_taxonomy_index` (už postavený, žiadny
nový build): produkt s **inou, tiež rozpoznanou** `canonical_family` sa
vylúči; produkt bez klasifikácie (`UNKNOWN`, cca 66% katalógu) sa **vždy
ponechá** (rovnaká zásada ako `classify_product()`: absencia klasifikácie
nikdy neodstraňuje produkt). Filter nikdy nevráti prázdny zoznam, ak vstup
nebol prázdny — čiastočne správny výsledok je vždy lepší než tvrdá
nula (`LEGACY_SEARCH_FAMILY_GUARD_ENABLED` env flag pre rollback).

Zámerne **nerieši subfamily-level** presnosť (napr. miso pasta vs. sójová
fermentovaná pasta, tamarindová pasta vs. krevetová pasta zostávajú v rámci
tej istej `family="paste"` zmiešané) — to je rovnaký "neprepracovávaj
subfamily presnosť" princíp, aký si zadanie samo vyžiadalo pre farbu curry
pasty (červená/zelená/žltá).

### Sprievodné taxonomy medzery — nájdené PRI overovaní guardu, nie predpokladané

Guard je len tak dobrý, ako rozpoznávanie rodiny, na ktorom stojí. Pri
overovaní `"udon rezance"` guard **obrátene** vymazal správne produkty
(čerstvé udon rezance) a ponechal nesprávne (instantné tempura udon) —
pretože **samotný dopyt** sa mylne priradil k `instant_food` cez generickú
frázu `"rezance"` v `instant_noodles` pravidle (produkty samotné sa
klasifikovali správne cez `category_terms`, ale dopyt-ako-holý-text nemá
kategóriu, len title_phrases). Toto by predtým bolo len tiché, neaktívne
skreslenie — guard ho aktívne premenil na regresiu, takže muselo byť
opravené v rovnakom commite:

- `wheat_noodles` pravidlo dostalo `title_phrases=("udon",)` +
  `exclude_title_phrases` proti kolízii s keramickou sadou miskou "Udon
  Misky" (rovnaký vzor ako existujúci `soba`/"miska" guard).
- Nové `glass_noodles` pravidlo (`family="noodles"`, `category_terms=
  ("sklenene rezance",)`) — 14 reálnych katalógových produktov bolo
  predtým mylne klasifikovaných ako `instant_food/instant_noodles` cez tú
  istú generickú `"rezance"` frázu (potvrdené priamo, nielen pre dopyt, ale
  aj pre produkty samotné).
- `instant_noodles`'s `exclude_title_phrases` rozšírené o `omacka`/`sitko`/
  `shirataki`/`konjac` — bez toho generická `"rezance"` fráza (nutná,
  pretože ~polovica reálnych instantných rezancov v katalógu nemá v názve
  nič iné rozlišujúce) mylne klasifikovala aj sítko na rezance (kuchynský
  riad), konjac/shirataki rezance a omáčky-na-rezance ako instantné
  rezance.
- Nové `chili_paste` a `tamarind_pasta` pravidlá (predtým žiadne pravidlo
  neexistovalo pre ani jedno — `"čili pasta"` aj `"tamarindová pasta"` mali
  `family=None/UNKNOWN`). `chili_paste` musí `exclude_title_phrases=
  ("gochujang", ...)`, pretože kórejské gochujang produkty majú v katalógu
  doslovný názov "Čili pasta Gochujang ..." — bez exclude by menej
  špecifické pravidlo vyhralo pred existujúcim `gochujang` pravidlom
  (nájdené cez `test_taxonomy_v23.py::test_gochujang`, opravené pred
  commitom).
- Anglické `title_phrases` aliasy doplnené do existujúcich, už správnych
  pravidiel: `soy_sauce`/`dark_soy_sauce`/`light_soy_sauce`/`fish_sauce`/
  `coconut_oil`/`rice_noodles` — systematicky testované: **všetkých 7
  anglických ekvivalentov predtým správne fungujúcich slovenských dopytov
  malo `family=None`** (žiadne pravidlo v `FAMILY_DEFINITIONS` nemalo
  anglickú frázu vôbec), potvrdzujúce systémovú, nie izolovanú medzeru.
  `data/synonyms.json` doplnené o `"chilli paste"→"chili pasta"` (dvojité
  L, chýbajúci variant popri existujúcom `"chili paste"`).

### Interakcia s V2.12.2 Bug A guardom (nezamýšľaný, ale správny bonus)

`detect_related_subject()` malo bundle `RELATED_PRODUCT_QUERIES["sklenene_rezance"]`
(sklenené rezance + sójová omáčka + sezamový olej + rybacia omáčka +
gochujang + shiitake ako JEDNA zlúčená odpoveď) — presne ten istý
"bundle merge" vzor ako Bug D. Keďže `"glass noodles"`/`"sklenene rezance"`
teraz **sebavedome** rozpoznávajú vlastnú rodinu vďaka novému
`glass_noodles` pravidlu, V2.12.2's `_query_resolves_to_confident_product_family()`
guard (Bug A) ich teraz **automaticky** presmeruje na priame vyhľadávanie
namiesto `related_products_for_subject()` bundlu — bez toho, aby bolo
potrebné čokoľvek meniť v `RELATED_PRODUCT_QUERIES` samotnom. Rovnaký efekt
pre `"udon rezance"`, `"chilli paste"`, `"coconut oil"`, `"fish sauce"`.
Bare/nejednoznačné dopyty (napr. holé `"tamarind"` — katalóg má reálne
odlišné produkty: pastu, koncentrát, sušené ovocie, nápoj) zámerne zostávajú
na `related_products` ceste, pretože sa NEDÁ bezpečne odhadnúť jedna rodina
z jedného nejednoznačného slova — to je správne, nie chyba.

### Overené, zámerne neopravené reziduá

Filter odstraňuje len KRÍŽOVÉ kontaminácie medzi rozpoznanými rodinami;
nemôže (a nemal by) odstrániť šum z **neklasifikovaných** (66% katalógu)
produktov zdieľajúcich lexikálny koreň (napr. `"kokosový olej"` stále
obsahuje kokosový karamel/nápoj/čipsy — tri neklasifikované produkty
zostávajúce z pôvodných siedmich). Toto je vlastná hranica prístupu
"filtrovať, nie prestavať" — rozšírenie by vyžadovalo pridávanie pravidiel
pre každý jednotlivý dlhý chvost katalógu, čo je mimo rozsahu (zadanie
Section 8: "Do not invent large new dictionaries").

## Skutočná príčina (nie hypotéza zo zadania)

Zadanie predpokladalo, že chýba celá architektúra sémantických obmedzení
(„head concept", „required vs preferred constraints", „contradiction
filter") a treba ju postaviť od základu. **Skutočnosť je iná**: táto
architektúra už existuje a funguje správne — `app.query_constraints`
(`StructuredProductQuery` s `family`/`subfamily`/`attributes`/
`explicit_constraints`), `app.retrieval` (skutočné set-intersection
vylučovanie, nikdy len scoring), `app.taxonomy` (`FamilyRule` systém s
HIGH/MEDIUM/LOW/UNKNOWN confidence tiers) a `app.ranking` (dokázateľne
len preusporadúva už oprávnenú množinu, nikdy nič nepridáva ani
neodstraňuje) — všetko postavené v sprintoch V2.3–V2.5.

Skutočný nález: **tri konkrétne, samostatné chyby bránili konkrétnym
dopytom vôbec sa dostať k tomuto už existujúcemu, správne fungujúcemu
mechanizmu.** Žiadna nová architektúra nebola potrebná — presne v duchu
zadania „Reuse rather than duplicate" (Section 22/92), len sa musel
odstrániť to, čo tomu bránilo.

## Bug A — príliš široké markery zametali holé produktové dopyty

`RELATED_INTENT_MARKERS` (321 fráz) úmyselne obsahuje aj široké
jednoslovné markery ako `"rezanc"` a `"olej"`, aby zachytilo skutočné
recepty ("čo ešte chýba do rezancov?"). Problém: **rovnaký marker
zachytáva aj holý produktový názov** — `"ryzove rezance"` (ryžové
rezance, produkt) obsahuje `"rezanc"`, `"kokosovy olej"` (kokosový olej,
produkt) obsahuje `"olej"`. `detect_related_subject()` tak tieto dopyty
posielalo do `related_products_for_subject()` — funkcie vracajúcej
odporúčania k RECEPTU (rybacia omáčka, sójová omáčka, sriracha, kokosové
mlieko pre "ryžové rezance"; nesúvisiace kokosové produkty pre "kokosový
olej") namiesto priameho vyhľadania produktu.

**Oprava** (`app/main.py`, nová funkcia `_query_resolves_to_confident_product_family()`
+ `_has_recipe_shopping_language()` s úzkym, kurátorovaným zoznamom
`RECIPE_SHOPPING_LANGUAGE_MARKERS`): keď dopyt taxonomy engine
sebavedomo (HIGH/MEDIUM) priradí k vlastnej rodine A zároveň neobsahuje
žiadny skutočný recept-jazyk marker, `related_subject` sa vynuluje —
rovnaký vzor ako existujúce brand/kitchenware "collision guardy" o pár
riadkov nižšie.

**Nájdená regresia počas vlastného overovania**: prvá verzia tohto guardu
omylom vypla aj skutočnú cross-sell otázku "čo sa hodí ku gochujang?"
(V2.10 golden case `regbug_rt0005`), pretože "gochujang" má vlastné
HIGH-confidence taxonomy pravidlo a môj úzky zoznam nezahŕňal "hodí"/
"hodia"/"pasuje". Opravené pridaním týchto markerov do
`RECIPE_SHOPPING_LANGUAGE_MARKERS` — dôkaz, prečo má zmysel mať
samostatný, úzky zoznam namiesto opätovného použitia celého širokého
`RELATED_INTENT_MARKERS`.

## Bug B — chýbajúce taxonomy pravidlo pre kokosový olej

`app/taxonomy.py`'s `FAMILY_DEFINITIONS` obsahovalo pravidlá pre
`coconut_milk` a `coconut_water`, ale **žiadne** pre `coconut_oil`,
`coconut_cream`, `coconut_juice` ani `coconut_vinegar` — hoci všetky
štyri produkty reálne existujú v katalógu. Bez pravidla
`parse_structured_query()` nikdy nevráti `family`, `retrieve_products()`
bezpodmienečne vráti `LEGACY_FALLBACK` a dopyt sa nikdy nedostane k
taxonomy-aware vylučovaniu — dokonca aj cez `hybrid_search_products`,
nielen cez priamy legacy engine.

**Oprava**: pridané 4 nové `FamilyRule` záznamy (`coconut_oil`→
family="oil", `coconut_cream`/`coconut_juice`→family="coconut_product",
`coconut_vinegar`→family="vinegar"), založené na reálnych kategóriách z
`data/products.json` (rovnaký dôkazný štandard ako existujúce pravidlá).

## Bug D — sushi_rice legacy bundle search obchádzal V2.4/V2.5

`detect_special_product_subject()` rozpoznáva `"sushi ryz"`/`"susi ryz"`
ako `special_subject = "sushi_rice"` — legacy mechanizmus predchádzajúci
taxonomy engine. `SPECIAL_PRODUCT_QUERIES["sushi_rice"]` je **hardcoded
zoznam šiestich samostatných vyhľadávaní** (`"sushi ryza"`, `"ryza na
sushi"`, `"susi ryza"`, `"nori"`, `"ryzovy ocot"`, `"wasabi"`), ktorých
výsledky sa zlúčia do jedného zoznamu — čiže "sushi ryža" (produkt)
doslovne vracia aj morské riasy nori, wasabi pastu a ryžový ocot priamo
v search výsledkoch. Presne "Search vs Cross-sell" porušenie (Section
34/106 zadania).

Overené priamym testom `retrieve_products()`: taxonomy engine už
KOREKTNE klasifikuje sushi ryžu (`family=rice, subfamily=sushi_rice`),
nori (`family=seaweed`) a ryžový ocot (`family=vinegar`) ako odlišné
rodiny — štrukturálne vylúčenie už funguje, len sa nikdy nevolalo.

**Oprava**: rozšírená existujúca `plain_rice` supersession vetva (V2.4/
V2.5 už dávnejšie nahradila legacy `plain_rice` bare-`"ryz"` detektor)
aj o `sushi_rice` — `elif special_subject in {"plain_rice", "sushi_rice"} and ...`.
Rovnaká bezpečnostná poistka ako predtým: ak štruktúrované vyhľadávanie
zlyhá/vráti `None`, spadne späť na legacy bundle, nikdy sa nič nerozbije.

**Druhý nález počas vlastného production smoke-testingu (nie z pôvodnej
hypotézy)**: rovnaký problém mal aj `special_subject = "rice_vinegar"`
— `SPECIAL_PRODUCT_QUERIES["rice_vinegar"]` obsahuje pod-dopyt
`"ocot sushi"`, ktorý cez legacy OR-based scorer (Bug C) doslovne
vrátil japonský sushi set a lepkavú ryžovú múku priamo do výsledkov pre
holý dopyt "ryzový ocot". Namiesto opravy len tejto jednej hodnoty som
opravu **zovšeobecnil**: `elif special_subject in {"plain_rice", "sushi_rice", "rice_vinegar", "rice_cooker"} and ...`
— presne tie special_subject hodnoty, ktoré taxonomy engine vie
spoľahlivo priradiť k VLASTNEJ, správnej rodine (`rice`, `rice`+`sushi_rice`,
`vinegar`+`rice_vinegar`, `kitchenware`+`rice_cooker`). **Zámerne
vynechané**: `rice_seasoning` — nemá vlastné taxonomy pravidlo, takže by
sa `parse_structured_query()` vrátil len na generickú rodinu `rice` a
stratil by kvalifikátor "koreniaca zmes" (overené priamo pri tejto
oprave — skutočný near-miss, nie hypotéza). Všetky ostatné
`special_subject` hodnoty (`gluten_free_sushi`, `medium_spicy`, `hot`,
`tofu_seaweed`, `dairy_replacement`, `tamari`, `sushi_condiments`, ...)
sú skutočné kurátorované zoznamy pre otázky založené na obmedzeniach
("veľmi pikantné, nie sladké"), ktoré taxonomy engine prirodzene
nerozumie — zámerne ponechané na legacy ceste.

## Čo NEBOLO opravené v tomto sprinte (vedomé rozhodnutie)

`app/search.py`'s legacy OR-based scorer (žiadna minimálna zhoda
tokenov, `PREFIX_SYNONYMS` z `data/synonyms.json` injektuje generické
korene ako `"kokos"`/`"ryz"` do všetkých produktov so zdieľaným
koreňom) **zostáva nezmenený**. Používa sa v ~25 volaniach
(`cached_search_products`) pre cross-sell/replacement/FAQ fallback
kontexty — nie pre primárnu zákaznícku cestu pre 8 cieľových dopytov
tohto sprintu (tie všetky prechádzajú cez `hybrid_cached_search_products`/
štruktúrované vyhľadávanie, ktoré je už korektné). Toto je zdokumentovaný
zvyškový architektonický dlh, nie prehliadnutie — oprava by vyžadovala
buď migráciu množstva call sites, alebo pridanie taxonomy-aware
vylučovania priamo do legacy scoreru, čo je mimo rozsahu tohto sprintu
(pozri odporúčanie na konci finálneho reportu).

## Architektúra (existujúca, len teraz skutočne dosiahnuteľná)

```
USER QUERY
   |
detect_special_product_subject() / detect_related_subject()
   | (V2.12.2: teraz korektne NEVYNucuje legacy cestu pre plain_rice/sushi_rice/
   |  bare product-name dopyty, ktoré taxonomy engine vie sebavedomo priradiť)
   v
app.query_constraints.parse_structured_query()
   |-- family / subfamily (EXPLICIT constraint)
   |-- attributes (brand/size/dietary - INFERRED, "preferred")
   |-- confidence (HIGH/MEDIUM/LOW/UNKNOWN)
   v
app.retrieval.retrieve_products()
   |-- set-intersection vylúčenie proti family_index[family]
   |-- STRUCTURED_EXACT / STRUCTURED_FILTERED / STRUCTURED_BROAD / LEGACY_FALLBACK
   v
app.ranking.rank_candidates()
   |-- l1-l4 tuple (taxonomy confidence, explicit hits, availability, relevance)
   |-- soft multiplier (behavioral/merchandising/personalization) - striktne AŽ PO l1-l4
   v
RESULT PRESENTATION (ResultSet, Show More/Show All = slicing, nie re-search)
   v
Follow-up (merge_constraints() - family vždy zdedené, brand/size/dietary/price sa dopĺňajú)
```

## UNKNOWN taxonomy — recall zostáva chránený

Produkty s `LOW`/`UNKNOWN` taxonomy confidence sa nikdy nezaraďujú do
štruktúrovaného indexu (`retrieval.py:44,77`) — vždy prechádzajú cez
legacy vyhľadávanie ako fallback, takže presný názov produktu je
nájditeľný aj bez taxonomy pokrytia. Toto správanie sme neposunuli.

## Testovacia matica

`tests/test_query_semantics_v2122.py` (19 testov) — všetky proti
reálnemu katalógu cez reálny `app.main._chat_internal()` pipeline (nie
zjednodušený helper, presne podľa požiadavky zadania Section 6):
Bug A/B/D regresné testy s pozitívnymi AJ negatívnymi assertions
(zakázané rodiny musia chýbať), regresný test na `regbug_rt0005`-triedu
nálezu (skutočná companion otázka nesmie byť rozbitá guardom), Show More
zostáva v rámci sushi rice, basmati/jazmínová ryža/ryžový ocot/ryžový
papier zostávajú čisté (regresná poistka), brand (Kikkoman) aj presný
názov produktu fungujú, follow-up ("lacnejšiu") zachováva basmati
obmedzenie, allergen_safety `answered=True` nezmenené.

## Výsledky

V2.10 golden suite: **44/58 → 51/58** (+7), 3 pôvodné critical failures
→ 1 (`regbug_rt0010`, nedotknutý, mimo rozsahu tohto sprintu) — 2 z 3
(`rice_sushi_001`, `sauce_fish_001`) opravené ako priamy dôsledok Bug D
opravy. Gate: WARN (nikdy nebolo FAIL v commitnutom stave). Zero nových
critical regresií.
