# Product Understanding & Attribute Intelligence (V2.16b)

Dátum: 2026-08-27. Baseline commit: `4b721301ddedd0ebdac9d2de004a012d7a01aa64`
(HEAD, `origin/main`, žiadne uncommitted zmeny okrem netrackovaného
`.claude/` — overené `git fetch`/`git status`/`git rev-parse`, presne
zodpovedá očakávanému stavu zo zadania).

## 1. Prečo tento dokument existuje

V2.16b je **audit-first** sprint: cieľom nie je "odpovedať na každú
atribútovú otázku", ale zistiť, ktoré atribúty katalóg reálne dokáže
dokázať. Princíp zadania: "Missing evidence is UNKNOWN, not FALSE."

## 2. Existujúce primitíva (audit)

Priamo overené čítaním kódu (`app/taxonomy.py`, `app/query_constraints.py`,
`app/product_normalizer.py`, `app/recommendation_evidence.py`,
`app/comparison.py`, `app/use_case_advice.py`, `app/recipe_graph.py`,
`app/cross_sell.py`, `app/recipe_shopping.py`, `app/session_state.py`,
`app/search.py`):

- **Taxonomy** (`app.taxonomy.classify_product`): family/subfamily s
  confidence HIGH/MEDIUM/LOW/UNKNOWN, plus `_DIETARY_CATEGORY_TERMS`
  (predtým 4 termy, teraz 2 — pozri Sekciu 4).
- **Query constraints** (`app.query_constraints.parse_structured_query`):
  brand (z reálnej katalógovej sady), package size (regex,
  kg/g/ml/l), dietary facets (rovnaká 2-term sada).
- **Comparison** (`app.comparison`): `_QUALITATIVE_MARKERS` už DNES
  hard-ABSTAINuje na chuť/autentickosť/prémiovosť tvrdenia
  (`GOAL_UNSUPPORTED_QUALITATIVE` → `STATE_ABSTAIN`) — existujúci
  precedens presne pre princíp tejto sprinty.
- **Allergen safety** (`app.main.allergen_safety_answer`): NIKDY
  netvrdí, že produkt je bezpečný — vždy presmeruje na overenie
  detailu produktu. Existujúci precedens pre vegan/gluten-free/halal.
- **Use-case fit** (`app.use_case_advice.LIVE_USE_CASES`): `sushi, pho,
  pad_thai, tom_kha, kari, ramen` — rozšírené z V2.14a-only-"sushi" na
  6 hodnôt (V2.14c/h), evidencia = taxonomy HIGH/MEDIUM zhoda.
- **Recipe graph**: presne 1 substitučná hrana (fish_sauce→soy_sauce,
  vegan context), nezmenené.
- **`diet_terms`** (`app.session_state`/`app.main`): preferenčný,
  soft-retrieval-bias signál (nie safety filter), negation-gated,
  session-scoped (deque, max 4), vylúčený z routingu (`regbug_rt0011`
  precedens), vyčistený pri resete. Nepoužíva sa na filtrovanie/
  vylučovanie produktov.
- **`Chutovy profil - SK`** (`Products_AI`, 130/2140 = 6,1% katalógu):
  kurátorovaný flavor-profile text, ALE ŽIVO zobrazovaný zákazníkom
  (`app.knowledge.best_product_advice_answer()`) bez evidence-gate.
  Vlastný text sa sám varuje: "neprezentuj ich ako zaruku bez
  overenia detailu produktu." Ponechané tak, ako je — narrow, real
  CURATED_KNOWLEDGE, žiadny nový kód pridaný ani odobraný.

## 3. Katalógový profil (živo nameraný, 2140 produktov)

`data/products.json` má presne 13 polí, **ŽIADNE** štruktúrované
ingrediencie/alergény/diétne pole:
`id, title, description, product_type, link, image_link, price,
sale_price, currency, brand, availability, gtin, unit_pricing_measure`.

| Pole | Pokrytie |
|---|---|
| brand | 2047/2140 (95,7%) — nezmenené od V2.14a |
| unit_pricing_measure | 1613/2140 (75,4%) — nezmenené od V2.14a |
| gtin | 1822/2140 (85,1%) |
| taxonomy HIGH | 798/2140 (37,3%) — **zlepšené** z V2.14a 24,8% |
| taxonomy MEDIUM | 193/2140 (9,0%) |
| taxonomy UNKNOWN | 1141/2140 (53,3%) — zlepšené z 65,6%, stále väčšina |
| product_type "vegansk" breadcrumb | 251/2140 (11,7%) |
| product_type "vegetariansk" breadcrumb | 378/2140 (17,7%) |
| product_type "bezlepkov" breadcrumb | 563/2140 (26,3%) |
| product_type "bio potraviny" breadcrumb | 24/2140 (1,1%) |
| halal (akékoľvek pole) | **0** |

## 4. Re-verifikácia V2.14a zistení

| V2.14a zistenie | Stav teraz |
|---|---|
| taxonomy 24,8%/9,2%/0,4%/65,6% | **IMPROVED** → 37,3%/9,0%/0,4%/53,3% |
| brand 95,7% | **CONFIRMED**, nezmenené |
| unit_pricing_measure 75,4% | **CONFIRMED**, nezmenené |
| dietárny atribút 0% štruktúrované, 2,4% cez Products_AI | **IMPROVED** čiastočne — Products_AI narástol na 130 záznamov (6,1%), ALE zároveň **OBJAVENÁ NOVÁ CHYBA**: `product_type` breadcrumb dietary facet (vegan/vegetarian) bol živo **NESPOĽAHLIVÝ** (Sekcia 5) |
| use_case len "sushi" | **IMPROVED** → 6 hodnôt (V2.14c/h) |
| flavor/authenticity/premium = 0% dát, LLM_ONLY | **CONFIRMED**, nezmenené — `comparison.py` už ABSTAINuje |
| rt0013 substitučná hrana = 1 | **CONFIRMED**, nezmenené (mimo rozsahu) |

## 5. KRITICKÝ NÁLEZ: živá, reprodukovaná vegan/vegetarian chyba

Pred akoukoľvek zmenou kódu: `app.retrieval`'s dietary_facets
hard-filter (komentár v kóde: **"Safety/relevance-critical - hard-
filtered, not scored"**) bol UŽ ŽIVO zapojený do hlavného `/chat`
structured retrieval pipeline (nie nová vec tejto sprinty).

Živý dôkaz proti nezmenenému HEAD:

```
Zákaznícka otázka: "vegánske rezance"
Vrátené (top výsledok): "Oyakata Teriyaki kuracie instantné rezance v kelímku AJ 96g"
(popis: "...s kombinuje skutočne japonskú chuť KURČAŤA s rezancami...")
product_type: "Vegánske potraviny > Japonské > Vegetariánske potraviny > ..."
```

Toto NIE JE hypotetické riziko — je to reprodukovateľná, živá chyba na
nezmenenom HEAD. Koreňová príčina: `product_type` breadcrumb je
Foodlandova VLASTNÁ merchandising kategória (obchodná polička "zdravé/
ázijské potraviny"), nie ingredient-audited certifikácia. Potvrdené
ďalšími blast-radius kontrolami (Sekcia 6).

## 6. Blast-radius audit — vegan/vegetarian vs. gluten_free (asymetria)

| Facet | Test | Výsledok |
|---|---|---|
| vegan | Chicken product v "vegánske" kategórii? | **ÁNO — DEFINITÍVNY DÔKAZ** (FL_9996) |
| gluten_free | 563 "bezlepkových" produktov proti známym pšeničným rezancom/sójovej omáčke | **0 potvrdených chýb** — bežná Kikkoman sójová omáčka (obsahuje pšenicu) správne NIE JE v bezlepkovej kategórii; VŠETKÝCH 31 pšeničných rezancov správne VYLÚČENÝCH |
| gluten_free | 1 nejednoznačný kandidát (Panda sušienky) | Bez ingredienčných dát neoveriteľné — nie definitívny dôkaz chyby |

**Rozhodnutie**: vegan/vegetarian breadcrumb mapping ODSTRÁNENÝ
(preukázateľne rozbitý). gluten_free/organic PONECHANÉ (nepreukázateľne
rozbité, rovnaký zdroj dát, ale žiadny nájdený protipríklad po
extenzívnom testovaní) — "do not touch what's not proven broken."

## 7. Attribute Evidence Model

| Trieda | Definícia | Použité pre |
|---|---|---|
| DATA_DERIVED | Explicitné štruktúrované pole | brand, price, unit_pricing_measure |
| DETERMINISTICALLY_DERIVED | Objektívne odvodené pravidlo | taxonomy HIGH tier, package size parsing |
| CURATED_KNOWLEDGE | Human-authored, per-produkt | `Chutovy profil`, `Kuchyňa` (Products_AI, 6,1%) |
| LEXICAL_HINT_ONLY | Slovo v title/description | nedostatočné samo osebe |
| LLM_JUDGMENT | Neverifikovateľná interpretácia | flavor/authenticity/premium bez dát |
| UNKNOWN | Žiadny dôkaz | halal, ingrediencie, pôvod |

## 8. Attribute Safety Model

- **LOW_RISK**: brand, size, product_type, use_case_fit.
- **MEDIUM_RISK**: spicy (preferenčný signál, nie verifikovaný), vegetarian.
- **HIGH_RISK**: vegan, gluten_free, halal, allergen — vyžadujú pozitívny
  štruktúrovaný/kurátorovaný dôkaz, nikdy len breadcrumb kategóriu.

## 9-22. Per-attribute audit

### 9. BRAND
DATA_DERIVED, 95,7% pokrytie. **Gate D — LIVE**, nezmenené.

### 10. SIZE / VOLUME / WEIGHT
DATA_DERIVED (`unit_pricing_measure`, 75,4% + regex fallback).
Presné zhody ("5 kg") **Gate D — LIVE**. Prahové dopyty ("aspoň 1
liter", "väčšie balenie") **NIE SÚ** spoľahlivo filtrované — živo
overené (`"sojova omacka aspon 1 liter"` vráti 150-300ml produkty).
**Gate B — FOUNDATION_ONLY** pre threshold porovnania — dáta existujú,
ale query-parsing/retrieval-filtering logika na porovnávacie operátory
neexistuje. Zámerne NEIMPLEMENTOVANÉ túto sprintu (vyžadovalo by zmenu
centrálnej `app/retrieval.py` indexovej štruktúry — `size_index` je
kľúčovaný presnou hodnotou, nie rozsahom — mimo "minimal implementation"
rámca a riziko širšieho blast radius na kritickú retrieval cestu).

### 11. PRODUCT_TYPE / TAXONOMY
DATA_DERIVED (HIGH) / DETERMINISTICALLY_DERIVED (MEDIUM/LOW).
HIGH=37,3%, MEDIUM=9,0%, LOW=0,4%, UNKNOWN=53,3%. **Gate C —
LIVE_WITH_LIMITATIONS** (už správne používané len HIGH/MEDIUM v
`use_case_advice.generate_candidates()`).

### 12. VEGAN
**KRITICKÝ NÁLEZ** — pozri Sekciu 5/6. Jediný zdroj (`product_type`
breadcrumb) preukázateľne nespoľahlivý. **Gate A — DATA_REQUIRED.**
Oprava: breadcrumb mapping odstránený, žiadna nová vegan dáta
vymyslené.

### 13. VEGETARIAN
Rovnaký zdroj, rovnaký preukázaný problém (ten istý FL_9996 produkt bol
tagovaný AJ ako "vegetariánsky"). **Gate A — DATA_REQUIRED.**

### 14. GLUTEN_FREE
Rovnaký zdroj ako vegan (breadcrumb), ale BEZ preukázanej chyby po
extenzívnom teste (Sekcia 6). **Gate C — LIVE_WITH_LIMITATIONS**
(existujúci filter ponechaný nezmenený — nepreukázateľne rozbité
správanie sa netrhá). Žiadne NOVÉ zákaznícke tvrdenie "áno, je bez
lepku" nebolo pridané — filter len zužuje výsledky, netvrdí nič navyše.

### 15. HALAL
**Gate A — DATA_REQUIRED.** Nulová kódová prítomnosť kdekoľvek v
repozitári (potvrdené full-repo grep), len 3 neštruktúrované zmienky v
`description` texte. Žiadna implementácia.

### 16. ALLERGENS
Existujúci, robustný, safety-first mechanizmus (`allergen_safety_answer`)
NIKDY netvrdí bezpečnosť — vždy presmeruje na overenie. **Gate D — LIVE**
(existujúci mechanizmus, nezmenený, nerozšírený).

### 17. SPICY / HEAT
`detect_diet_terms()`'s "pikantne"/"jemne" — preferenčný retrieval-bias
signál (nie hard filter, nie verifikovaný atribút), `SPECIAL_PRODUCT_
QUERIES["hot"/"mild"/"medium_spicy"]` — kurátorované lexikálne zoznamy.
Žiadna numerická Scoville hodnota nikde. **Gate B — SPICY_WITH_
LIMITATIONS** (soft signál, nie false-claim riziko rovnakej triedy ako
vegan — nezmenené).

### 18. USE_CASE_FIT
6 live hodnôt (sushi/pho/pad_thai/tom_kha/kari/ramen), taxonomy-backed.
**Gate C — LIVE_WITH_LIMITATIONS**, nezmenené (explicitný non-goal
zadania: "do not invent new cuisine fit").

### 19. RECIPE_ROLE_FIT
Reuse `recipe_graph`, 47 jedál, 74 konceptov. **Gate C —
LIVE_WITH_LIMITATIONS**, nezmenené.

### 20. FLAVOR_PROFILE
CURATED_KNOWLEDGE pre 130/2140 (6,1%) cez `Products_AI.Chutovy profil`,
už živo zobrazované. **Gate C — LIVE_WITH_LIMITATIONS** (úzke pokrytie,
kurátorovaný, nie fabrikovaný text; vlastný obsah sa sám varuje pred
nadmerným tvrdením). Pre zvyšných 93,9% katalógu: **Gate A —
DATA_REQUIRED**, žiadne LLM-vymyslené flavor tvrdenia.

### 21. AUTHENTICITY
**Gate A — DATA_REQUIRED**, potvrdené 0% dát. `comparison.py` už
ABSTAINuje, nezmenené.

### 22. PREMIUM_POSITIONING
**Gate A — DATA_REQUIRED**, potvrdené 0% dát (cena sama nie je dôkaz).
`comparison.py` už ABSTAINuje, nezmenené.

## 23. Conflict policy

Nezistený žiadny nový konflikt (žiadne nové štruktúrované pole
pridané, ktoré by mohlo konfliktovať s iným). Existujúci precedens:
pri konflikte klasifikovať ako `CONFLICTING_DATA`, nevyberať pohodlnú
hodnotu — v tejto sprinte sa neuplatnilo (žiadny nový conflicting
scenár vytvorený).

## 24. Missingness policy

Chýbajúci atribút = UNKNOWN, nikdy FALSE. Priamo aplikované vo fixe:
odstránenie vegan/vegetarian mappingu znamená, že tieto produkty teraz
nemajú ŽIADNY dietary facet (namiesto nesprávneho), čo spôsobí, že
vegan/vegetarian dopyt padne cez normálne relevance search namiesto
falošne-istého hard filtra.

## 25. Attribute Constraint Model

Žiadny nový formálny `AttributeConstraint` framework vytvorený —
existujúci `StructuredProductQuery.dietary_facets` (V2.4) už postačuje
a bol len OPRAVENÝ (odstránenie 2 nespoľahlivých hodnôt), nie
nahradený.

## 26. Compound constraints

Brand+size compound overené živo funkčné (`"Kikkoman sojova omacka
1000ml"`). Vegan+use_case nebolo implementované (vegan zostáva
DATA_REQUIRED, teda žiadny compound naň nemôže byť postavený).

## 27. Zero-match policy

Nezmenené — žiadny nový "silent relax" mechanizmus pridaný. Fix
skutočne PRIDÁVA k tomuto princípu: predtým falošne-istý vegan filter
teraz namiesto toho čestne padá do relevance search (nie do
fabrikovaného "0 výsledkov s vysvetlením", ale ani do falošného
vegan-potvrdenia).

## 28. Partial-match policy

Nezmenené, mimo rozsahu implementácie (žiadny nový compound-so-partial-
evidence mechanizmus vytvorený).

## 29. Follow-up attribute context

Nezmenené — žiadny nový "Máte väčšie?"/"Je to vegan?" follow-up
mechanizmus implementovaný túto sprintu (mimo minimal-scope fixu).

## 30. diet_terms session audit

Pozri Sekciu 2. Potvrdené: preferenčný, nie safety-filter, session-
scoped, resetom vyčistený, vylúčený z routingu. Nezmenené touto
sprintou.

## 31. REPLACEMENT_PRODUCTS / rt0013

Nezmenené, rt0013 zostáva `CLOSED_BY_HUMAN_SEMANTIC_DECISION`. Vegan
nebol pridaný ako actual attribute constraint pre replacement kandidátov
— zostáva `REPLACEMENT_QUALITY_DATA_LIMITATION_REMAINS` (vegan dáta sú
teraz DATA_REQUIRED namiesto nespoľahlivého breadcrumb, čo je presne
ten istý stav, len s vyššou integritou — žiadna regresia).

## 32. Allergen safety control

Nezmenené a neoslabené — `allergen_safety_answer()` mechanizmus
netknutý, žiadny silent downgrade.

## 33. Qualitative best freeze

Nezmenené — `comparison.py`'s `_QUALITATIVE_MARKERS` ABSTAIN
mechanizmus netknutý, regresne zamknutý novým testom.

## 34. Implementation gates

Pozri Sekcie 9-22 pre kompletnú per-attribute maticu. Zhrnutie: 2
atribúty (vegan, vegetarian, halal) = Gate A; 2 (size-threshold, spicy)
= Gate B; 5 (gluten_free, taxonomy, use_case, recipe_role, flavor) =
Gate C; 3 (brand, allergen-safety-mechanism, size-exact) = Gate D.

## 35. Implemented changes

- `app/taxonomy.py`: `_DIETARY_CATEGORY_TERMS` — odstránené `"veganske
  potraviny"`/`"vegetarianske potraviny"` mapovania (2 riadky).
- `app/query_constraints.py`: `_DIETARY_QUERY_STEMS` — odstránené
  `"vegansk"`/`"vegetariansk"` mapovania (2 riadky).
- `tests/test_taxonomy.py`: 1 existujúci test prepísaný (starý,
  teraz-nesprávny predpoklad nahradený gluten_free príkladom), 1 nový
  regresný test pridaný.
- `tests/test_product_attribute_intelligence_v2_16b.py`: 27 nových
  testov (bug-fix regresný zámok, gluten_free nezmenené, halal
  bez fabrikácie, brand/size, taxonomy, use-case, qualitative-abstain,
  compound, zero-match/hard-switch/reset, rt0004/10/11/13 + V2.15c/
  V2.16a/a.1 kontroly).
- **`app/widget.js` NEZMENENÝ.**
- **Nulová zmena** `app/comparison.py`, `app/use_case_advice.py`,
  `app/recipe_graph.py`, `app/cross_sell.py`, `app/recommendation_
  evidence.py`, `app/main.py`, `app/session_state.py`, `app/retrieval.py`,
  `app/structured_search.py` — potvrdené `git diff --stat`.

## 36. Widget status
**WIDGET_PATCH_NOT_REQUIRED.**

## 37. JS tests
**NOT_REQUIRED_WIDGET_UNCHANGED.**

## 38-45. Testy a audity
Pozri finálny report pre presné počty (BEFORE/AFTER/V2.10/canary/
consistency/trust).

## 46-47. LLM/search call count
0 nových LLM volaní. 0 nových catalog-search volaní — fix je čisto
odstránenie 2 dict entries, žiadna nová logika ani volanie.

## 48. Performance
Zanedbateľné — menší (2-entry kratší) dictionary lookup, žiadny nový
I/O.

## 49. Privacy
Žiadne zmeny.

## 50-51. Learning/ranking freeze, AUTO_PROMOTION
Nezmenené. `AUTO_PROMOTION_ENABLED` default `False`, netknuté.

## 64-65. Remaining debt

**Dátový dlh:**
- Halal: vyžaduje business-owner-dodané certifikačné dáta.
- Vegan/vegetarian: vyžaduje buď per-SKU certifikáciu, alebo
  ingredient-level dáta dostatočne kompletné na bezpečné deterministické
  odvodenie (dnes ~1,2% voľný text, nepoužiteľné).
- Gluten-free: aktuálny breadcrumb signál nie je certifikačnej kvality
  — odporúčaná budúca práca: buď získať skutočnú certifikáciu, alebo
  aspoň pridať explicitný "nie je to certifikovaný údaj" disclaimer do
  akejkoľvek budúcej zákazníckej odpovede, ktorá by ho priamo citovala.

**Architektonický dlh:**
- Size-threshold queries ("aspoň X", "väčšie ako X") vyžadujú rozšírenie
  `app/retrieval.py`'s `size_index` z presnej hodnoty na rozsahové
  vyhľadávanie — zámerne mimo rozsahu tejto sprinty.
- `Chutovy profil` (flavor) customer-facing cesta
  (`best_product_advice_answer()`) nemá evidence-gate — funguje dnes
  bezpečne len vďaka tomu, že ide o skutočne kurátorovaný text s
  vlastným internым diskutovaním, nie fabrikáciou; budúca práca by
  mohla formálne prepojiť na `recommendation_evidence.EvidenceItem`.

## 65a. Live verification — vedľajší, PRED-EXISTUJÚCI nález (mimo rozsahu)

Live production matrix (Sekcia 46 finálneho reportu) odhalila, že
`"Kde sa nachádza kamenná predajňa?"` (store_location dopyt) teraz
niekedy vyhráva cez generický FAQ scorer proti CONTACT záznamu (V2.16a.1)
namiesto pôvodného store_location záznamu — odpoveď obsahuje telefón/
email NAVYŠE k adrese, nie namiesto nej (žiadny fabrikovaný ani chýbajúci
fakt, len iný poradový víťaz medzi dvoma pravdivými FAQ záznamami).
**Overené ako PRED-EXISTUJÚCE** — reprodukované na aktuálnom lokálnom
kóde, ktorý V2.16b nezmenil v `app/main.py`/`data/knowledge.json` vôbec
(len `app/taxonomy.py`/`app/query_constraints.py`). Príčina: V2.16a.1's
nový contact FAQ záznam obsahuje plný adresný text vo svojej `Odpoveď`
(zámerne, pre úplnosť kontaktnej odpovede), čo spôsobuje prekrytie
tokenov s store_location dopytmi, ktoré netrafia žiadny dedikovaný
skratkový blok. **Mimo rozsahu V2.16b** (Sekcia 5 zadania explicitne
zakazuje broad zmeny informational FAQ routingu túto sprintu) — nie je
to fabrikácia ani bezpečnostný problém, len UX polish príležitosť pre
budúcu úzku uzávierku.

## 66. Recommended next step

Žiadna ďalšia broad attribute-framework sprint nie je odporúčaná bez
nových dát. Ak business poskytne halal/vegan/gluten-free certifikačné
dáta (aj čiastočné), úzka data-closure sprint (analogická V2.16a.1)
by mohla tieto Gate A atribúty posunúť na Gate C/D. Alternatívne:
`V2.16c Substitution Intelligence V2` (rozšírenie recipe_graph
substitučného grafu nad rámec 1 hrany) je legitímna, dátovo-nezávislá
ďalšia práca, keďže recipe_graph je deterministický a už má šablónu.
