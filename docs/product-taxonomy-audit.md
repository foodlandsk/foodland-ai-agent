# Foodland katalógová taxonómia — prvý discovery audit (V2 Taxonomy Phase 1-11)

Tento dokument je vygenerovaný z **aktuálneho** stavu `data/products.json` a
`data/knowledge.json` skriptom `scripts/taxonomy_audit.py`
(`python3 scripts/taxonomy_audit.py --json <out>.json`). Žiadne číslo tu
nie je ručne odhadnuté — všetko je prepočítané zo zdrojových dát pri
každom behu. Re-generuj po každom refreshi feedu.

Dátum tohto behu: 2026-08-14. Zdroj: `data/products.json` (2 140 produktov
v čase tohto behu — **nepovažuj toto číslo za fixné**, vždy over aktuálny
počet).

## Fáza 1 — Profil katalógu (reálne čísla)

```
total_products               = 2140
unique_brands                = 368
unique_categories_top_level  = 127
unique_categories_all_levels = 166
```

Top 10 značiek podľa počtu produktov: EMRO AZIATICA (137), EDO JAPAN (117),
HEM (79), LOBO (51), COCK BRAND (48), LIMPEXT (45), TRS (40), Lee Kum Kee
(37), ASIA EXPRESS (35), Thai Agri Foods (35).

Top-level kategórie sú z veľkej časti **prierezové atribútové značky**, nie
navigačné oddelenia — "Vegánske potraviny" (206), "Zdravé potraviny" (192),
"Vegetariánske potraviny" (85), "Super potraviny" (62), "Sušené produkty"
(84) dominujú počtom, ale nehovoria nič o produktovej identite. Skutočné
navigačné kategórie (Misy a misky 97, Vonné tyčinky 89, Nealkoholické
nápoje 70, Zmes korenia a ochucovadlá 60, Kórejské 57, Sójové omáčky 31,
Potreby na výrobu suši 25...) sú užitočnejšie pre taxonómiu produktovej
rodiny. Toto potvrdzuje rozhodnutie zo Sprintu V2.1.6 (`category_discovery`)
odfiltrovať tieto prierezové značky z odpovede o sortimente.

Balenia v názvoch: g (1151×), ml (434×), cm (298× — hlavne kuchynský riad),
kg (90×), ks (46×), l (20×), mm (17×).

## Fáza 2-4 — Kandidátne produktové rodiny a cross-category kolízie

Skript testoval hypotézy koreňov (`ryz`, `soj`, `kokos`, `caj`, `susi`/
`sushi`, `mlieko`...) proti reálnym title tokenom. Najvýznamnejšia,
opakovane historicky problémová kolízia (Sprint Z.6 v roadmape, viacero
predošlých produkčných chýb) je koreň **`ryz`** (ryža):

| token (normalizovaný) | počet produktov | reálny príklad |
|---|---|---|
| `ryza` | 69 | Basmati ryža – LAILA – 1kg |
| `ryzove` | 63 | Červené ryžové rezance SAVIVA 400g |
| `ryzovy` | 23 | Ryžový ocot CHINKIANG GOLD PLUM 550ml |
| `ryze` | 9 | Múka z lepkavej ryže COCK BRAND 400g |
| `ryzu` | 7 | Elektrický hrniec na ryžu REMO |
| `ryzova` | 3 | Ryžová múka COCK BRAND 400g |
| `ryzovar` | 2 | Komerčný ryžovar CUCKOO |

Manuálnou inšpekciou (`python3 scripts/taxonomy_audit.py --family ryz`)
tento jeden lingvistický koreň reálne pokrýva **najmenej 7 odlišných
produktových podrodín**:

1. samotná ryža (zrno) — basmati, jazmínová, lepkavá/glutinous, čierna...
2. ryžové rezance (rice noodles) — samostatná kategória potravín
3. ryžový ocot (rice vinegar) — koreninová/ocotová kategória
4. ryžová múka (rice flour) — mučná/pekárenská kategória
5. ryžový papier (rice paper) — obaľovacia/wrap kategória
6. ryžovar / hrniec na ryžu (rice cooker) — **má vlastnú reálnu katalógovú
   kategóriu `Ryžovary`**, teda ide o overenú, nie len odvodenú rodinu
7. ryžový nápoj (rice drink) — nápojová kategória

Toto potvrdzuje presne triedu chyby zdokumentovanú v Sprinte Z.6
("workflow s ryžou/ryžovarom") — zdieľaný jazykový koreň nesmie
znamenať rovnakú produktovú rodinu.

Ďalšie kandidátne rodiny s reálnym katalógovým dôkazom (nie vyčerpávajúci
zoznam, len najsilnejšie signály z tohto behu): `rezanc`/`nudl` (rezance,
174 produktov spolu s pluralizovanými tvarmi), `soj` (sójová omáčka, 85
produktov), `kokos` (kokosové produkty, 68 produktov), `caj` (čaj, 100
produktov vrátane príslušenstva), `susi`/`sushi` (78 produktov).

## Fáza 9 — Recepty a IntentMapping ako sémantický dôkaz

`data/knowledge.json["sections"]["IntentMapping"]` (318 záznamov) obsahuje
**overenú kurátorovanú** taxonómiu zákazníckych zámerov, nezávislú od tohto
auditu. Relevantné typy zámerov s reálnym počtom výskytov:

```
6  Omáčky / výber produktu
4  Ryža / výber produktu
4  Rezance / výber produktu
3  Kari / výber produktu
2  Kokosové mlieko / výber produktu
2  Pálivosť / preference
```

Konkrétne overené záznamy pre "Ryža / výber produktu" (priamo použiteľné
ako grounded obsah, nie vymyslené):

```
"Akú ryžu použiť na sushi?"
  → Sushi ryža — "Preferovať sushi ryžu a krátkozrnnú ryžu."
"Akú ryžu použiť ku kari?"
  → Ryža ku kari — "Odporučiť jazmínovú alebo basmati podľa kuchyne."
"Aký je rozdiel medzi jazmínovou a basmati ryžou?"
  → Porovnanie ryže — "Porovnať arómu, zrnitosť, kuchyňu a použitie."
"Potrebujem lepivú ryžu na mango sticky rice."
  → Lepkavá ryža — "Odporučiť glutinous/sticky rice."
```

Toto je priamy, overený zdroj obsahu pre `product_comparison` intent
(porovnanie jazmínová vs. basmati) aj pre `product_advice` (ryža podľa
použitia) — presne tie dva kanonické zámery, ktoré v legacy kóde nemajú
detektor (zdokumentované v `docs/advisor-v2-architecture.md`, V2.4).

Podobne "Rezance / výber produktu" potvrdzuje, že rezance sa delia podľa
**použitia** (pad thai → ploché ryžové rezance, ramen → ramen/instantné,
japchae → sklenené/batátové), nie len podľa suroviny.

## Fáza 5-6 — Kanonická taxonómia (návrh): `rice` (ryža)

Vybraná ako JEDINÁ rodina pre prvú implementáciu (Fáza 26, krok 11) —
najsilnejší kombinovaný dôkaz: vysoký počet produktov (69+ priamo, 173+
naprieč podrodinami), opakovaná história produkčných chýb (Sprint Z.6),
overená IntentMapping podpora, a jasná existujúca čiastočná legacy
implementácia (`SPECIAL_PRODUCT_QUERIES` už má `plain_rice`, `sushi_rice`,
`rice_vinegar`, `rice_side`, `rice_cooker`, `rice_seasoning`) na ktorú sa
dá nadviazať, nie ju nahradiť.

```
canonical_family_id: rice
display_name: Ryža
aliases: ryza, ryze, ryzu, ryzou, rice, gao, com (VI základ)

subfamilies:
  plain_rice        confidence=HIGH   evidence=69 products, IntentMapping "Ryža/výber produktu"
  sushi_rice         confidence=HIGH   evidence=existing SPECIAL_PRODUCT_QUERIES + IntentMapping "sushi ryža"
  rice_noodles        confidence=HIGH   evidence=63 products distinct category (rezance), IntentMapping "Rezance/výber produktu"
  rice_vinegar         confidence=HIGH   evidence=23 products, distinct category "Ocot"
  rice_flour             confidence=HIGH   evidence=distinct category "Múka, škrob & ryžový papier"
  rice_paper               confidence=HIGH   evidence=distinct category "Obaľovacia zmes, tempura & panko"
  rice_cooker                confidence=HIGH   evidence=distinct real catalog category "Ryžovary"
  rice_drink                   confidence=MEDIUM evidence=2 products only ("ryžový nápoj")

P1 (identity) attributes: subfamily (which of the above), variety (basmati/
  jazmínová/lepkavá-glutinous/hnedá-brown/čierna-black/riceberry)
P2 (selection/use-case) attributes: cuisine (thajska/japonska/vietnamska/
  korejska), use_case (sushi/kari/dezert-sticky-rice/bežné varenie)
P3 (preference/commercial) attributes: brand, package_size

collision_risks: rice_noodles, rice_vinegar, rice_flour, rice_paper,
  rice_cooker, rice_drink all share the "ryz*" linguistic root with
  plain_rice and with each other - MUST be disambiguated by compound
  phrase, not root stem alone (already handled for the 4 subjects that
  exist in SPECIAL_PRODUCT_QUERIES; rice_flour, rice_paper, rice_drink
  are NOT yet in legacy special-product routing).

related_recipe_roles: base ingredient (sushi, kari, plov), seasoning
  (rice_vinegar in sushi), wrapping (rice_paper in spring rolls)
```

## Fáza 11 — Confidence pravidlo pre tento audit

Iba `plain_rice`, `sushi_rice`, `rice_noodles`, `rice_vinegar`,
`rice_flour`, `rice_paper`, `rice_cooker` majú HIGH confidence (jasný
katalógový/kategóriový dôkaz). `rice_drink` má MEDIUM (len 2 produkty) —
podľa Fázy 11 pravidla MEDIUM smie ovplyvniť ranking, nesmie tvoriť tvrdé
retrieval obmedzenie. V tejto prvej iterácii sa `rice_drink` nezapája do
klasifikátora vôbec (žiadne customer-facing správanie sa nemení pre
žiadnu podrodinu v tomto behu — pozri Fáza 16 nižšie).

## Fáza 12 — Bez ručného mapovania 2000+ SKU

`app/taxonomy.py` (pridané touto iteráciou) neobsahuje žiadny zoznam
`product_id`. Klasifikácia beží nad `title`/`product_type` poľami
existujúcich produktov pomocou malej, opakovane použiteľnej sady
frázových pravidiel na rodinu. Nové produkty pribudnuté do feedu sa
klasifikujú automaticky bez zmeny kódu, pokiaľ zodpovedajú existujúcim
frázovým vzorom; produkty mimo tejto rodiny jednoducho nedostanú
klasifikáciu (žiadny hard-coded SKU zoznam).

## Fáza 16 — Rollout stage tohto behu

**Stage A (shadow/observation mode) — implementované touto iteráciou.**
`app/taxonomy.py` poskytuje `classify_rice_query()`, ktorá sa v `/chat`
volá **len na účely analytics logovania** (rovnaký, už zavedený a
bezpečný vzor ako `app/intent.py` `CustomerIntent` v Sprinte V2.1) —
NEMENÍ žiadne existujúce routovacie rozhodnutie, produkty, ani text
odpovede. Skutočné nahradenie legacy `SPECIAL_PRODUCT_QUERIES` rice
logiky (Stage B) je zámerne mimo rozsahu tohto behu — vyžaduje najprv
overenie zhody cez produkčné dáta (blokované `LIVE_VERIFICATION_BLOCKED_BY_EXECUTION_ENVIRONMENT`
v tomto vykonávacom prostredí).

## Ako znovu spustiť tento audit

```bash
python3 scripts/taxonomy_audit.py                        # plný výpis
python3 scripts/taxonomy_audit.py --family ryz            # detail jednej rodiny
python3 scripts/taxonomy_audit.py --json audit_raw.json   # surové dáta na ďalšie spracovanie
python3 scripts/taxonomy_audit.py --taxonomy-engine       # V2.1 product-level taxonomy coverage
python3 scripts/taxonomy_audit.py --shadow-interpretation # legacy search vs V2.1 taxonomy, 8 required queries
```

Skript nemá žiadne hardcoded počty produktov ani kategórií — všetko
prepočíta nanovo z `data/products.json` a `data/knowledge.json` pri
každom behu.

---

# Sprint V2.1 — Feed Foundation, Product Normalization & Taxonomy Engine

Dátum tohto behu: 2026-08-14. Zdroj: committed `data/products.json`
(**2 140 produktov**) — rovnaký snapshot, aký používa existujúca pinned
testovacia sada (`tests/test_core.py`). Nepovažuj toto číslo za fixné.

**Poznámka k dátam:** počas tejto iterácie bol `data/products.json`
krátko obnovený zo živého feedu (2 325 produktov, overené priamo z
`app/import_feed.py` — živý feed bol z tohto prostredia dostupný), no
tento refresh spôsobil **3 reálne test failures** v CI
(`test_search_autocomplete_boosts_favorite_brand`,
`test_replacement_bare_brand_resolves_to_its_only_sauce_category`,
`test_replacement_bare_brand_survives_contextualize_message_pollution`)
– tieto testy sú zámerne napevno naviazané na presné zloženie tejto
konkrétnej fixture (napr. "Kikkoman predáva iba sójovú omáčku" prestalo
platiť, keď živý feed pridal "Kimchi základ KIKKOMAN"). Príčina bola
potvrdená ako **rozdiel v dátach, nie regresia V2.1 kódu** – opravené
vrátením `data/products.json` na pôvodný commitnutý stav namiesto úpravy
testov. Produkčný `refresh_feed()` naďalej vždy načítava skutočný živý
feed (pozri Fáza "Integrácia do refresh pipeline" nižšie) – iba tento
checked-in dev/test fixture súbor zostáva zámerne pinned.

## Feed

`app/feed.py` teraz zachováva viac zo zdrojového feedu:

- `parse_category_memberships(product_type)` — deterministický rozklad
  `g:product_type` na plochý zoznam `category_memberships[]` (rozdelenie
  na `>`, orezanie whitespace, odstránenie prázdnych/duplicitných
  segmentov, zachovanie zdrojového poradia). **Nie strom** — Fáza 4
  vyššie ukazuje presne prečo (napr. `Ryžový papier` a `Múka` zdieľajú tú
  istú leaf kategóriu `Múka, škrob & ryžový papier`).
- `Product.category_memberships` — odvodená `@property`, nie uložené
  pole (žiadna duplicita v `products.json`).
- Nové polia zo živého feedu: `additional_image_links[]` (opakované
  `g:additional_image_link`), `unit_pricing_base_measure`,
  `shipping_weight`, `condition`, `identifier_exists` — všetky s
  bezpečným defaultom pre staré JSON snapshoty (spätná kompatibilita
  overená `tests/test_feed.py::TestBackwardCompatibility`).
- `find_duplicate_gtins()` — len detekcia, nikdy automatické zlúčenie
  produktov (Foodland product id zostáva primárna identita).

## Produktový normalizér (`app/product_normalizer.py`, nový modul)

Čisto štrukturálne odvodeniny, žiadna sémantika:

- `extract_url_category(link)` — prvý segment cesty URL (napr.
  `ryzove-rezance`, `basmati-ryza`) ako doplnkový signál.
- `parse_package_size(unit_pricing_measure, title)` — štruktúrovaná
  veľkosť balenia (`value`, `unit`, `multipack_count`); nejednoznačné
  tvary ("10 ks", "500 g / drained 300 g") sa zámerne NEODHADUJÚ —
  zostávajú v `raw` s `value=None`.
- `normalize_brand()` / `title_search_form` — opätovne používajú
  existujúce `app.search.normalize()`, žiadna konkurenčná
  normalizačná implementácia.

## Taxonómia — produktová úroveň (nové v `app/taxonomy.py`)

**Dôležité:** toto je DRUHÝ, nezávislý klasifikátor popri
`classify_rice_query()` z Fázy 16 vyššie. `classify_rice_query()`
klasifikuje **text správy zákazníka** a zámerne vracia `family="rice"`
pre celý jazykový zhluk (vrátane ryžovaru) — slúži len na shadow
analytics jedného jazykového zhluku. Nový `classify_product()`/
`build_taxonomy_index()` klasifikuje **produkt z katalógu** a garantuje
mandatory invariant zo sekcie V2.1 zadania: `family != word root`.

`FAMILY_DEFINITIONS` (dátovo-riadený zoznam pravidiel, najšpecifickejšie
prvé — rovnaká kolízna disciplína ako existujúci `RICE_SUBFAMILY_PHRASES`)
pokrýva pilotnú rodinu `rice` a jej kolízne susedné rodiny, každé pravidlo
podložené reálnym dôkazom zo živého feedu:

| rule_id | canonical_family | canonical_subfamily | confidence (category/title) | reálny dôkaz |
|---|---|---|---|---|
| plain_rice (+jasmine/basmati/glutinous varianty) | `rice` | `plain_rice` | HIGH / MEDIUM | leaf kategórie `Ryža`, `Jazmínová ryža`, `Basmati ryža` |
| sushi_rice | `rice` | `sushi_rice` | HIGH / MEDIUM | aliasované kategórie `Ryža na suši (sushi)` + `Suši ryža` |
| rice_noodles | `noodles` | `rice_noodles` | HIGH / MEDIUM | leaf kategória `Ryžové rezance` |
| rice_vinegar | `vinegar` | `rice_vinegar` | — / HIGH | generická kategória `Ocot`, titulok `ryžový ocot` |
| rice_flour | `flour` | `rice_flour` | — / HIGH | generická kategória `Múka`, titulok `ryžová múka` |
| rice_paper | `rice_paper` | — | HIGH / MEDIUM | leaf kategória `Ryžový papier` |
| rice_cooker | `kitchenware` | `rice_cooker` | HIGH / MEDIUM | leaf kategória `Ryžovary` |
| rice_wine, rice_drink | `beverages` | `rice_wine` / `rice_drink` | — / MEDIUM | titulky "Makgeolli"/"ryžové víno", "ryžový nápoj" |

### Povinná kolízna invariant (overené `tests/test_taxonomy.py::TestClassifyProductRiceCollisions`)

Nad reálnymi produktmi zo živého feedu (nie vymyslenými príkladmi):

```
canonical_family("Chantaboon ryžové rezance ... FARMER 400 g")  = noodles     (≠ rice)
canonical_family("Ryžový ocot CHINKIANG GOLD PLUM 550ml")        = vinegar     (≠ rice)
canonical_family("Lepkavá ryžová múka TAIKY 400g")               = flour       (≠ rice)
canonical_family("Okrúhly ryžový papier ... TUFOCO 400g")        = rice_paper  (≠ rice)
canonical_family("Elektrický hrniec na ryžu REMO 0,8 L")         = kitchenware (≠ rice)
canonical_family("Basmati ryža - LAILA - 1 kg")                  = rice
```

Všetkých 6 produktov v jednej kolíznej skupine ("ryz\*" koreň) dostáva
šesť odlišných `canonical_family` hodnôt — presne mandatory invariant zo
zadania tohto sprintu.

### Pokrytie (V2.1 engine, `--taxonomy-engine`, beh na 2 140 produktoch)

```
total_products        = 2140
classified_products   = 155
taxonomy_coverage      = 0.0724   (rice pilot only - zámerne úzke, nie odhad)
confidence_counts      = HIGH=108  MEDIUM=39  LOW=8  UNKNOWN=1985
canonical_family_count    = 7   (rice, noodles, vinegar, flour, rice_paper, kitchenware, beverages)
canonical_subfamily_count = 8

families:      rice=78  noodles=39  vinegar=10  beverages=8  rice_paper=8  kitchenware=7  flour=5
subfamilies:   plain_rice=66  rice_noodles=39  sushi_rice=12  rice_vinegar=10
               rice_cooker=7  rice_wine=6  rice_flour=5  rice_drink=2
```

Nízke celkové `taxonomy_coverage` (~7 %) je OČAKÁVANÉ a správne — rice je
zámerne jediná implementovaná pilotná rodina (sekcia "Rice pilot" tohto
sprintu), nie odhad celého katalógu. Zvyšných 1 985 produktov má
`confidence=UNKNOWN`, `canonical_family=None` a zostáva plne dostupných
legacy vyhľadávaniu (žiadny produkt sa nestráca). Na aktuálnom živom
feede (2 325 produktov, overené priamo) sú čísla proporčne rovnaké
(`classified_products=166`, `taxonomy_coverage=0.0714`, rovnakých
7 rodín/8 podrodín) — pozri poznámku k dátam vyššie.

## Shadow interpretation (`--shadow-interpretation`, 8 povinných dopytov)

Pre každý z 8 povinných dopytov: legacy search dnes už (vďaka existujúcim
`SPECIAL_PRODUCT_QUERIES`) vracia správne produkty, ale bez štruktúrovanej
identity. Nová V2.1 taxonómia teraz vie vysvetliť PREČO sú tieto výsledky
správne — top-5 legacy výsledok pre každý dopyt sa mapuje na presne JEDNU
`family/subfamily` kombináciu, nulová krížová kontaminácia:

```
"ryža"            -> rice/sushi_rice (3), rice/plain_rice (2)
"jazmínová ryža"  -> rice/plain_rice (5)
"basmati ryža"    -> rice/plain_rice (5)
"ryža na sushi"   -> rice/sushi_rice (5)
"ryžové rezance"  -> noodles/rice_noodles (5)
"ryžový ocot"     -> vinegar/rice_vinegar (5)
"ryžový papier"   -> rice_paper/- (5)
"ryžovar"         -> kitchenware/rice_cooker (5)
```

(beh na committed `data/products.json`, 2 140 produktov; rovnaký nulovo-kontaminovaný výsledok potvrdený aj na živom feede, 2 325 produktov)

Toto NEMENÍ žiadne `/chat` správanie (žiadny customer-facing kód číta
`product_taxonomy_index`) — demonštruje len, že štruktúrovaná
reprezentácia existuje a je pripravená pre budúce V2.2 retrieval.

## Dátová kvalita

`find_duplicate_gtins()` beží nad aktuálnym katalógom ako súčasť auditu;
zistenia sa reportujú, produkty sa NIKDY automaticky nezlučujú len na
základe zhodného GTIN (Foodland product id zostáva primárna identita).

Na committed `data/products.json` (2 140 produktov) nájdených **5 skupín**
so zdieľaným GTIN medzi dvoma odlišnými Foodland product id (napr.
`FL_10393`/`FL_6472`, `FL_2812`/`FL_3818`) — pravdepodobne varianty
alebo duplicitné zdrojové záznamy na strane merchant feedu (na živom
feede, 2 325 produktov, 4 skupiny — mierne odlišné zloženie katalógu).
Nahlásené, NEOPRAVENÉ (mimo rozsahu tohto sprintu — oprava zdrojového
katalógu nie je úloha AI advisora).

## Migrácia — čo je shadow, čo je customer-facing

- **Shadow / interné dáta only:** `product_taxonomy_index` (rebuild v
  `refresh_feed()`), `classify_product()`, `build_taxonomy_index()`,
  `find_by_family()`/`find_by_attributes()`/`get_taxonomy()` query API.
  Žiaden `/chat` kód path ich číta.
- **Customer-facing, nezmenené:** legacy `SPECIAL_PRODUCT_QUERIES`,
  `search_products()`, celá existujúca `/chat` routovacia kaskáda.
- **Ďalší odporúčaný krok (V2.2):** Structured Retrieval & Category-Aware
  Ranking — napojiť `find_by_family()`/`find_by_attributes()` na
  retrieval plan namiesto re-tokenizácie `product_type` per request, pod
  kontrolovaným rollout (rovnaký Stage A→B vzor ako `classify_rice_query()`).

---

# Sprint V2.3 — Taxonomy Expansion Across the Foodland Catalog

Dátum tohto behu: 2026-08-15. Zdroj: aktuálny živý feed (2 319 produktov,
overené priamo z tohto prostredia) + committed `data/products.json`
(2 140 produktov, rovnaká fixture ako pinned test suite).

## Nové rodiny (16 celkovo, +9 oproti V2.1 pilotu)

Každé pravidlo podložené reálnym dôkazom zo živého feedu (kategórie +
tituly), nie vymyslenými príkladmi — pozri `app/taxonomy.py:
FAMILY_DEFINITIONS` pre presné pravidlá.

| family | subfamily-y | dôkaz (kategória) |
|---|---|---|
| `sauce` | soy_sauce(+dark/light), oyster_sauce, fish_sauce, hoisin_sauce, teriyaki_sauce, black_bean, chili_sauce(+sriracha/sweet/garlic) | Sójové omáčky, Ustricové omáčky, Rybacie omáčky, Hoisin omáčky, Teriyaki omáčky, Čili omáčky (+ 3 dedikované sub-kategórie) |
| `curry_paste` | (attributes.variety: red/green/massaman/panang) | Kari pasty (čistá, dedikovaná kategória) |
| `paste` | miso, gochujang, black_bean | Pasty korenia (titulkovo gated — kategória je príliš zmiešaná) |
| `coconut_product` | coconut_milk, coconut_water | Kokosové mlieko a krémy (čistá); Kokosový nápoj (titulkovo gated) |
| `oil` | sesame_oil | Sezamový olej (čistá, dedikovaná) |
| `noodles` (rozšírené) | +wheat_noodles, +soba | Pšeničné rezance, Pohánkové rezance |
| `instant_food` | instant_noodles, instant_soup | Instantné polievky (titulkovo rozlíšené: "rezance/ramyeon/ramen" vs "polievka") |
| `tea` | — | Čaj (čistá, dedikovaná) |
| `seaweed` | nori, wakame | Morské riasy (titulkovo gated — kategória mixuje nori/wakame/kelp) |
| `frozen_food` | dumplings | (bez category_terms — "Mrazené potraviny" pokrýva všetko mrazené) |

## Kritický nález počas implementácie: "category OR title", nie AND

Motor `classify_product()` prijíma pravidlo, ak sedí KATEGÓRIA **alebo**
TITULOK (nie nutne oboje). Toto je bezpečné, keď je kategória naozaj
čistá (napr. `Sezamový olej`), ale **nebezpečné**, keď viacero pravidiel
zdieľa tú istú širokú/nečistú kategóriu — prvé pravidlo v poradí vyhrá
len na základe kategórie, bez ohľadu na titulok.

Zachytené manuálnym family purity auditom (Section 53/58 zadania), nie
testami vopred — presne preto bol purity audit povinný krok:

1. **`gyoza`** pôvodne malo `category_terms=("mrazene potraviny",)` →
   zachytilo 70 nesúvisiacich produktov (kalamáre, mochi zmrzlina,
   edamame, citrónová tráva) namiesto len knedličiek. Opravené na
   title-only `"gyoza"`.
2. **`soy_sauce`/`dark_soy_sauce`/`light_soy_sauce`** mali
   `category_terms=("sojove omacky",)` → kategória obsahuje aj čiernu
   fazuľu omáčku, poke omáčku, unagi omáčku, dumpling omáčku. Opravené
   na title-only.
3. **`coconut_water`** malo `category_terms=("kokosovy napoj",)` →
   kategória obsahuje aj kokosové želé dezerty. Opravené na title-only.
4. **`nori`/`wakame`** mali `category_terms=("morske riasy",)` →
   kategória obsahuje nori AJ wakame AJ kelp/kombu spolu. Opravené na
   title-only (aj odstránené `"susena zelenina"` z wakame, ktoré
   zachytilo sušenú cibuľu).
5. **`massaman_curry_paste`/`panang`/`red`/`green` curry pasty** —
   všetky 4 zdieľali `category_terms=("kari pasty",)` → PRVÉ pravidlo v
   poradí (`massaman`) vyhrávalo pre KAŽDÝ produkt v tejto kategórii bez
   ohľadu na titulok (červená kari pasta bola klasifikovaná ako
   massaman!). Opravené na title-only pre všetky 4 variety pravidlá,
   generický `curry_paste` fallback si kategóriu ponechal.
6. **`soba_noodles`** — bare `"soba"` titulok chytal aj `"yakisoba"`
   (iný, pšeničný pokrm), instantnú soba POLIEVKU, a keramickú misku s
   produktovou radou "Soba". Opravené `exclude_title_phrases`.
7. **`teriyaki_sauce`** — bare `"teriyaki"` chytal instantné
   teriyaki-príchute polievky/rezance. Opravené `exclude_title_phrases`.

**Zovšeobecnené pravidlo pre budúce iterácie:** ak viac ako jedno
pravidlo v `FAMILY_DEFINITIONS` zdieľa presne ten istý `category_terms`
reťazec, VŽDY over, či je tá kategória naozaj sémanticky čistá (family
purity check, Section 53) — ak nie, alebo ak zdieľanú kategóriu používa
viac než jedno pravidlo naraz, jednotlivé (špecifickejšie) pravidlá
musia byť title-gated, kategória smie zostať len na generickom fallbacku.

## Pokrytie (živý feed, 2 319 produktov)

```
classified_products = 766 / 2319   (taxonomy_coverage = 33.03 %, pred V2.3 = 7.14 %)
confidence_counts = HIGH=538  MEDIUM=218  LOW=10  UNKNOWN=1553   (pred V2.3 UNKNOWN=2159)
canonical_family_count = 16   (pred V2.3 = 7)
canonical_subfamily_count = 27   (pred V2.3 = 8)

families: instant_food=212  sauce=177  noodles=86  rice=79  tea=77
          curry_paste=31  coconut_product=22  seaweed=16  paste=12
          vinegar=12  beverages=10  oil=9  kitchenware=7  rice_paper=7
          frozen_food=5  flour=4
```

Committed fixture (2 140 produktov, rovnaký ako pinned testy):
`classified=720`, `coverage=33.64 %`, `HIGH=512 MEDIUM=200 LOW=8
UNKNOWN=1420` — proporčne zhodné so živým feedom.

## Vedomé rozhodnutia NEklasifikovať (Section 96 — pozitívny výsledok, nie zlyhanie)

- **`tofu`** — nekonzistentné dôkazy (dedikovaná kategória neexistuje,
  väčšina "tofu" titulkov je o gyoza plnke/čili paste s tofu kúskami/
  miso polievke s tofu, nie o samotnom tofu produkte). Radšej UNKNOWN
  než hádanie.
- **`wasabi`** — titulkové zhody boli prevažne wasabi-PRÍCHUŤOVÉ
  snacky (arašidy, edamame, krekry) a keramický riad s produktovou
  radou "Wasabi" (farba/dizajn, nie ingrediencia), nie samotný wasabi
  kondiment. Title/category sa nezhodovali (Section 40) → UNKNOWN.
- **`knives`/`chopsticks`/`pickled_ginger`** — nulový výskyt presných
  hľadaných termínov v živom feede pri tomto behu — žiadne dáta na
  podloženie pravidla, nič nevymyslené.
- **`bowls`/tableware rozšírenie** — kategória `Misy a misky`/`Stolový
  riad` mixuje gastro obalové misky (takeaway) a keramický japonský
  riad bez čistého rozlíšenia — mimo rozsahu tejto iterácie.

## Zostávajúce top UNKNOWN oblasti (vstup pre ďalšiu iteráciu)

Najväčšie zostávajúce kategórie bez rodiny (z pôvodného profilu, Fáza 1):
`Kuchynské potreby` (343 leaf, len rice_cooker pokrytý), `Sladkosti a
občerstvenie` (282, snacky/sušienky/cukríky nepokryté), `Dekorácie a
darčeky` (67), `Vonné tyčinky` (40, nie potravina), `Konzervované
produkty` (51, generická konzervovaná kategória).

## Ako znovu overiť

```bash
python3 scripts/taxonomy_audit.py --taxonomy-engine
python3 scripts/taxonomy_audit.py --shadow-interpretation
```
