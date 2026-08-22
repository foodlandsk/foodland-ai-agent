# V2.14h — Ramen Data Readiness & Use-Case Closure

Dátum: 2026-08-22. Baseline: `983ed4a` (post-V2.14f), pytest 1553/1553,
V2.10 fast-mode 34/39, canary 10/10. Mandát zadania: **"Can the RAMEN use
case now be supported safely by the existing evidence-grounded
recommendation architecture?"** — audit-first, žiadny predpoklad kladnej
odpovede. `RAMEN_DATA_REQUIRED_CONFIRMED` bol explicitne rovnocenný
výsledok s `RAMEN_USE_CASE_LIVE` — tento dokument reportuje to, čo dôkazy
skutočne ukázali, nie aspiráciu.

## 1. Re-audit V2.14c/d/e/f nálezov (živo overené proti `983ed4a`, nie kopírované)

| Nález | Stav | Poznámka |
|---|---|---|
| `instant_noodles` = 89 produktov, 9 z toho misky/riad | **OUTDATED_BY_CURRENT_HEAD** | V2.14d pridal samostatné `tableware` `FamilyRule` PRED `instant_noodles` — dnes 79 produktov (76 HIGH / 3 MEDIUM), `tableware`=268, nulová kontaminácia. |
| `roles_for_recipe("ramen")` = `[instant_noodles, miso, soy_sauce, wakame]` | **CONFIRMED** | Identické, nezmenené od V2.14d. |
| "dashi" surovina sa nedá namapovať cez `parse_structured_query()` | **CONFIRMED, ale s korekciou významu** | Prázdny `concept_id` je pravda, ALE dôvod nie je "žiadne dáta" — pozri Section 4. |
| ramen bare-word kolízia s `instant_noodles` (instantná vs. domáca polievka) | **PARTIALLY_CONFIRMED, prehodnotené** | Kolízia na úrovni SEARCH RANKINGU stále existuje (Section 3), ale na úrovni TAXONOMY už kolízia neexistuje — suché ramen rezance žijú v úplne inej rodine (`wheat_noodles`). Pôvodný V2.14c dôvod vylúčenia (kontaminácia miskami) je vyriešený; hlbší dôvod (nemožnosť odlíšiť instantné/domáce) neplatí na taxonomy úrovni. |
| `app.recipe_shopping` už má `RECIPE_SHOPPING_CORE_QUERIES["ramen"]` a funguje živo (V2.8, nedotknuté V2.14 sériou) | **CONFIRMED** | `"co potrebujem na ramen"` → `related_products`, honestne degraduje (3 z ingrediencií mimo e-shop), nezmenené touto sprintou. |

## 2. Reálny dátový audit (živo overené proti `data/products.json`)

| concept_id | family/subfamily | počet | confidence |
|---|---|---|---|
| `instant_noodles` | instant_food/instant_noodles | 79 | 76 HIGH / 3 MEDIUM |
| `miso` | paste/miso | 4 | 4 MEDIUM |
| `soy_sauce` (+ dark/light varianty) | sauce/soy_sauce | 51 (+5) | **100% MEDIUM, 0 HIGH** |
| `wakame` | seaweed/wakame | 5 | 5 MEDIUM |
| `wheat_noodles` (NOVÝ nález) | noodles/wheat_noodles | 32 | 32 HIGH |
| `nori`, `sesame_oil`, `chili_sauce`/`sriracha_sauce`/`chili_paste` | rôzne | 8/8/~56 | prevažne HIGH |

**`soy_sauce` anomália vyšetrená a uzavretá**: nie je to shadowing efekt
(ako `curry_paste`/`red_curry_paste`) — CELÁ rodina (generic + dark +
light, 56 produktov) je 100% MEDIUM. Overené priamym dotazom na všetky 3
varianty. Je to reálny, štrukturálny strop z plytkej category-path
evidencie vo feede, nie bug. MEDIUM je už akceptovaná confidence úroveň
pre `use_case_advice` (rovnaká politika ako pri iných rolách), takže to
nie je blokujúce.

**`instant_noodles` 79 vs. predtým spomínaných 80**: overené ako presnosť
súčasného stavu (79 je pravda, potvrdené 3x nezávislými signálmi —
`tableware`=268 nezmenené, celkové taxonomy súčty identické, `data/products.json`
bez commitov od V2.14d) — nie regresia, len nepresnosť v skoršom
zhrnutí, nie v reálnych dátach.

## 3. Ramen ≠ instant_noodles — audit rozšírených rodín (Section 6 zadania)

Priamy audit `product_taxonomy_index` (nie predpoklad) našiel **samostatnú**
`wheat_noodles` rodinu (32 produktov, 100% HIGH), oddelenú od
`instant_noodles`. Z toho **4 produkty majú v názve doslova "ramen"**
(HAKUBAKU, MISTER MIE, GOLDEN TURTLE, AYUKO) — reálne suché/domáce
ramen rezance, nie instantné balíčky. Zvyšok rodiny sú iné ázijské
rezance (udon, somen, jjajang, yakisoba) — NIE ramen.

Toto priamo vysvetľuje a rieši pôvodnú V2.14c obavu: "instantné vs.
domáce rezance" nie sú v tej istej taxonomy rodine — sú od seba čisto
oddelené. Search ranking (nie taxonomy) je miesto, kde sa dnes miešajú
(bare "ramen"/"rezance" dotaz vráti len instantné značkové produkty,
viď Section 3 nižšie) — ale to je JEDNA úroveň nad taxonomy a mimo
rozsahu úprav tejto sprinty (vyžadovalo by zmenu search rankingu, nie
use-case advice).

**Rozhodnutie**: NEPRIDÁVAM novú "domáce ramen rezance" rolu vyčlenenú z
`wheat_noodles` (napr. title-substring "ramen") v tejto sprinte — vyžadovalo
by to nový taxonomy koncept a vlastný blast-radius audit (Section 12
zadania), čo je mimo úzkeho rozsahu Gate B. Zdokumentované ako konkrétny,
dôkazmi podložený budúci krok (nie vágne TODO) v Section 7.

## 4. Dashi — korekcia nálezu

Pôvodné tvrdenie "dashi nemá dáta" bolo **nepresné**. Priamy title-search
v celom katalógu našiel **3 reálne SKU**: `Dashi Bonito Stock SHIMAYA 40g`,
`Dashinomoto bonito rybací prášok 1kg`, `Dashima sušený kelp PAKU PAKU 100g`
— všetky s `confidence=UNKNOWN`, `family=None` (žiadne `FamilyRule` ich
nezaberá). Skutočný stav: **dáta existujú, štruktúrovaná evidencia nie**.

Toto sa prejavilo aj live: `"mam neveganske jedlo rad, odporuc mi ramen"`
→ `related_products` intent NAŠIEL tieto dashi produkty (cez menej prísny
lexikálny/curated cross-sell mechanizmus), zatiaľ čo `use_case_advice`'s
striktnejší `concept_id`-based mechanizmus by ich (správne) nikdy
nepoužil ako evidenciu — presne tak, ako má.

**Rozhodnutie**: dashi rola sa NEPRIDÁVA do `_ROLE_TABLE["ramen"]`.
Autorstvo novej `dashi` `FamilyRule` je reálna taxonomy zmena vyžadujúca
vlastný blast-radius audit — mimo rozsahu tejto sprinty. Zdokumentované
ako presný, akčný `DATA_REQUIRED` bod (Section 7), nie fabrikovaná rola
z `UNKNOWN` evidencie (čo by porušilo confidence gate tohto modulu).

## 5. Charakterizácia 8 zákazníckych zámerov (Section 14 zadania)

| Zámer | Príklad | Stav PRED V2.14h | Stav PO V2.14h |
|---|---|---|---|
| A. Bare product search | "ramen rezance" | `product_search` | **nezmenené** (chránené framing-preposition gate) |
| B. Recipe request | "recept na ramen" / "co potrebujem na ramen" | `related_products` (V2.8) | **nezmenené** |
| C. Use-case advice | "ake rezance na ramen?" | `product_search` (chybný fallback na instant_noodles dump) | **`use_case_advice`/RECOMMEND** |
| D. Ingredient/role advice | "aku omacku na ramen?" | `product_search` (rovnaký chybný fallback) | **`use_case_advice`/RECOMMEND** |
| E. Basket completion | (rovnaké ako B, `recipe_subject` má prednosť) | V2.8 mechanizmus | **nezmenené** (basket independence, Section 6) |
| F. Comparison | "porovnaj Samyang Buldak a Nissin Demae" | `product_comparison` (funguje) | **nezmenené** |
| G. Unsupported qualitative | "ktory ramen je najlepsi?" | `product_search` (žiadne tvrdenie, len non-answer) | **nezmenené** — cross-cutting medzera (nie ramen-špecifická), mimo rozsahu |
| H. Non-food/bowl search | "miska na ramen" | `product_search` (známy V2.14d limit) | **nezmenené** — už zdokumentované, neprehĺbené |

Reálny, pred touto sprintou reprodukovaný defekt: zámery C a D dopadali
na generický `product_search` fallback vracajúci "Máme 79 produktov v
kategórii Instantné rezance" bez ohľadu na to, že zákazník sa pýtal na
omáčku alebo zeleninu — negenerický, nepomáhajúci non-answer. Toto je
presne to, čo Gate B opravuje.

## 6. Rozhodnutie: Gate B (use-case-advice-only, bez zmeny basketu)

Dôkazy: 4 reálne, dátovo podložené role (`instant_noodles`, `miso`,
`soy_sauce`, `wakame`) sú priamo znovupoužiteľné z existujúcej
`app.cross_sell.roles_for_recipe("ramen")` — žiadna nová taxonomy.
Bare-word nejednoznačnosť ramen/instantné rezance už rieši generický
`_USE_CASE_FRAMING_PREPOSITIONS` mechanizmus (rovnaký ako pre kari/pho) —
nie nová, ramen-špecifická logika. Basket completion pre ramen už
funguje nezávisle cez V2.8 (Section 1), takže `BASKET_V1_ELIGIBLE_USE_CASES`
sa NEROZŠIRUJE (Section 8).

Implementácia (`app/use_case_advice.py`): `"ramen"` pridané do
`LIVE_USE_CASES`, `_USE_CASE_ALIASES`, a nová `_ROLE_TABLE["ramen"]`
so 4 rolami (noodles→`instant_noodles`, paste_miso→`miso`,
sauce_soy→`soy_sauce`, topping_wakame→`wakame`), všetky
`PROVENANCE_DATA_DERIVED`. Dashi zámerne vynechané (Section 4).

## 7. Zvyšný dátový dlh (presné, akčné položky — nie vágne TODO)

1. **Dashi FamilyRule**: 3 reálne SKU (Section 4), `UNKNOWN` confidence.
   Autorovanie novej `FamilyRule` + blast-radius audit — konkrétny,
   ohraničený budúci krok.
2. **"Domáce ramen rezance" rola z `wheat_noodles`**: 4 reálne, HIGH
   confidence SKU identifikované (Section 3) — vyžaduje title-substring
   koncept + vlastný blast-radius audit pred pridaním ako samostatná rola.
3. **Zámer G (qualitative "najlepší")**: cross-cutting medzera cez celý
   katalóg (nie ramen-špecifická) — bare search na kvalitatívnu otázku
   vráti len zoznam bez tvrdenia (bezpečné, ale nepomáhajúce). Mimo
   rozsahu tejto sprinty.
4. **Zámer H (miska/riad search)**: existujúci, už zdokumentovaný V2.14d
   limit — nezhoršený, neopravený.
5. `soy_sauce` 100% MEDIUM strop (Section 2) — akceptovaný, nie bug.

## 8. Latentný defekt nájdený a opravený: `BASKET_V1_ELIGIBLE_USE_CASES`

Reálny, touto sprintou prvýkrát odhalený problém: `app/basket_completion.py`
definoval `BASKET_V1_ELIGIBLE_USE_CASES = tuple(LIVE_USE_CASES)` — holý
live-mirror, napriek tomu, že vlastný komentár tvrdil "kept separately
named... a future LIVE_USE_CASES addition is not automatically
basket-ready". Pridanie `"ramen"` do `LIVE_USE_CASES` by TICHO
udelilo aj basket eligibility — presne to, čo Section 20 zadania
explicitne zakazuje ("ramen must NOT be auto-added to
BASKET_V1_ELIGIBLE_USE_CASES merely because use-case advice becomes
possible"). Odhalené testom `TestRamenBasketIndependence` (nový,
tento sprint) a testom `test_ramen_not_eligible` (V2.14e, existujúci —
prešiel doteraz len vďaka tomu, že sa sady nikdy predtým nerozišli).

**Oprava**: `BASKET_V1_ELIGIBLE_USE_CASES` je teraz explicitný,
samostatne autorovaný tuple `("sushi", "pho", "pad_thai", "tom_kha", "kari")`
— nezávislý od `LIVE_USE_CASES`. Test `test_registry_matches_live_use_cases`
(rovnosť sád) prepísaný na `test_registry_is_subset_of_live_use_cases`
(podmnožina) — správny invariant, keďže basket-ready use case musí byť
aj use-case-advice-live, ale nie naopak.

## 9. Testy

Nový `tests/test_ramen_readiness_v2_14h.py` (24 testov): rozlíšenie
use case/rolí, end-to-end role advice pre všetky 4 role, ochrana bare
product name / rt0004 companion / negation / allergen precedencie,
basket independence, evidence provenance (nikdy `LLM_JUDGMENT`, nikdy
`UNKNOWN` confidence produkt). Aktualizované (nie vymazané) stale
testy v `test_use_case_advice_v2_14c.py` (3 triedy), `test_recommendation_decision_v2_14f.py`
(`TestCaseM`), `test_basket_completion_v2_14e.py` (registry invariant) —
každý prepísaný tak, aby overoval SKUTOČNÉ, overené správanie, nie aby
len prešiel.

## 10. Regresie

Plný `pytest`: **1578/1578** (1553 + 25 nových: 24 v
`test_ramen_readiness_v2_14h.py` + 1 čistý nárast z rozdelenia/doplnenia
existujúcich test tried v `test_use_case_advice_v2_14c.py`). V2.10 fast-mode: **34/39**, identické
error buckety (`GROUNDING_ERROR: 2, INTENT_ERROR: 1, RETRIEVAL_MISS: 2`),
nezmenené. Canary: **10/10 PASS**, no anomalies. Consistency: **0 kolízií**.
Trust: **0 nálezov**. Deployment check: **passed**.

Sushi/pho/kari/pad_thai/tom_kha kontroly, rt0004/rt0010/rt0011 routing
regresie, curry_red_001 golden case — všetky nedotknuté, overené live.

## 11. Final release status

**RAMEN**: `RAMEN_USE_CASE_LIVE_WITH_LIMITATIONS`

**BASKET**: nezmenené — ramen basket completion beží nezávisle cez V2.8
`app.recipe_shopping` (nie cez `app.basket_completion`), `BASKET_V1_ELIGIBLE_USE_CASES`
ramen neobsahuje (zámerne, Section 6/8).

**Kapacitná matica** (per-capability):

| Schopnosť | Stav |
|---|---|
| Product search | LIVE |
| Recipe (shopping list) | LIVE_WITH_LIMITATIONS (dashi mimo e-shopu, honestne) |
| Use-case advice | LIVE_WITH_LIMITATIONS (4 role, dashi vynechané) |
| Role/ingredient advice | LIVE_WITH_LIMITATIONS |
| Comparison | LIVE |
| Cheapest/size/price-per-unit | LIVE (cez comparison) |
| Qualitative "best" | ABSTAIN (honest non-answer, cross-cutting) |
| Flavor profile / authenticity | EXCLUDED (žiadne štruktúrované dáta, nikdy nefabrikované) |
| Basket completion | LIVE_WITH_LIMITATIONS (cez V2.8, nezávisle od tejto sprinty) |
| Session continuation | LIVE (dedený mechanizmus, nedotknutý) |

## 12. V2.14 séria — uzavretie

V2.14a (evidence primitive) → V2.14b (comparison) → V2.14c (use-case
advice, ramen vylúčené) → V2.14d (tableware fix) → V2.14e (basket
completion) → V2.14f (comparison follow-up) → V2.14h (ramen re-audit,
Gate B, latentný basket-independence bug fix). Zvyšný dlh je
zdokumentovaný a dôkazmi podložený (Section 7), nie zabudnuté TODO.

## 13. V2.15a pripravenosť (posúdenie, nie začiatok)

Kandidáti pre budúcu prácu, v poradí podľa dôkazov: (1) dashi
`FamilyRule` autorstvo, (2) domáce ramen rezance rola z `wheat_noodles`,
(3) qualitative "najlepší" zámer naprieč celým katalógom (nie
ramen-špecifické), (4) rt0013 (nedotknuté, zostáva blokujúce pre
akúkoľvek súvisiacu prácu). Žiadny z týchto bodov nie je začatý touto
sprintou.
