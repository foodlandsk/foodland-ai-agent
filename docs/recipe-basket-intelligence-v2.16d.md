# Recipe / Basket Intelligence V2 (V2.16d)

Dátum: 2026-08-27. Baseline commit: `c3dcc97022a2f67ec71293f443fc1745ae49b710`
(HEAD, `origin/main`, čistý working tree okrem netrackovaného `.claude/`
— overené `git fetch`/`git status`/`git rev-parse`/`git log` pred
akoukoľvek zmenou. V2.16c je **`V2_16C_PRESENT_AND_RELEVANT`** — plne
prítomný na `origin/main`, CI zelené, živo overené na produkcii).

## 1. Prečo tento dokument existuje

V2.16d nadväzuje na V2.16b (product search) a V2.16c (substitution) —
rovnaký princíp aplikovaný na "čo potrebujem na X?"/"čo ešte
potrebujem?" recipe-to-basket cestu. Cieľ: zistiť, čo systém REÁLNE
vie o kompletnosti nákupného zoznamu, opraviť len živo reprodukované
chyby, a **nikdy** nefabrikovať množstvo/porcie/kompletnosť/
ekvivalenciu náhrady.

## 2. Existujúce primitíva (audit)

Tri paralelné mechanizmy existujú súčasne pre "čo potrebujem na X?" —
živo potvrdené, nie predpokladané:

| Use case | Mechanizmus | Vstupný bod |
|---|---|---|
| pho, sushi, kari | `app.basket_completion` (V2.14e) | `decide_basket_completion()`, role-based, `product_taxonomy_index` priamo |
| pad_thai, tom_kha | `app.recipe_shopping` (V2.8/V2.9) | `build_recipe_shopping_plan()` cez `app.recipe_graph`, session-continuity cez `resolve_recipe_followup()` |
| ramen | staršia, samostatná "shopping_list" cesta | `intent=related_products`, žiadny `recipe_shopping_plan`/`basket_roles` field |

`basket_completion.py`'s vlastný docstring toto explicitne priznáva:
pad_thai/tom_kha majú `recipe_subject` nastavený skôr, než sa
`decide_basket_completion()` vôbec vyhodnotí (`RECIPE_INTENT_MARKERS`
hardcoduje ich mená), takže sa táto funkcia pre ne vždy defer-uje —
BASKET_V1_ELIGIBLE_USE_CASES obsahuje pad_thai/tom_kha len formálne,
reálne beží len pre sushi/pho/kari. **Ramen nie je v žiadnom zozname**
(`app.use_case_advice.LIVE_USE_CASES` ho má pre single-role otázky, ale
`BASKET_V1_ELIGIBLE_USE_CASES` ho zámerne vylučuje — dokumentované v
`basket_completion.py`'s "RAMEN EXCLUSION" sekcii ako nezávislé
rozhodnutie).

Toto zodpovedá Sekcii 9 zadania ("nezdvojovať V2.8/V2.14e") — **žiadny
nový modul nebol vytvorený**, existujúca trojcestná architektúra
zostala nezmenená, opravy boli aplikované do existujúcich 3 miest.

## 3. `recipe_graph` — živo zmerané (nie V2.14 historické čísla)

```
recipe_count=53, dish_count=47, ingredient_concept_count=73
taxonomy_backed=28, recipe_curated=45, unresolved=4
substitution_edge_count=1 (fish_sauce -> sojova_omacka, context=vegan)
requirement values used: {'REQUIRED'} <- ŽIADNE optional/garnish rozlíšenie v reálnych dátach
sushi: present_in_graph=False (samostatný, nezávislý mechanizmus)
```

4 nevyriešené koncepty (cierna_soja, sweet_chili_omacka, cierne_hriby,
rendang_pasta) — **žiadny** z nich patrí medzi pho/sushi/kari/pad_thai/
tom_kha/ramen (Sekcia 28 cieľové use cases majú 0 nevyriešených
konceptov okrem pho's "korenie pho", ktoré je RECIPE_CURATED bez
lexikálnej zhody).

## 4. Kľúčové zistenie #1 — `use_case_advice` mohol "uniesť" basket dopyt

Živo reprodukované PRED opravou: `"Mam ryzove rezance a rybaciu
omacku. Co este potrebujem na pho?"` vrátilo `intent=use_case_advice`
s odpoveďou "Na pho je ryžové rezance vhodná voľba" — úplne ignorujúc
self-declared položky AJ samotnú otázku.

Koreňová príčina: `resolve_role()` (V2.14f) už MÁ ochranu proti presne
tomuto kolíznemu scenáru, ale len **náhodou** — jej vlastný docstring
priznáva, že funguje len vďaka tomu, že interpunkcia hneď za
self-declared markerom rozbije `resolve_role()`'s doslovnú
trailing-space kontrolu ("...rezance, co este..." s čiarkou → funguje;
"...rezance a rybaciu omacku. Co este..." s medzerou pred ďalšou
klauzulou → nefunguje). Overené priamo na existujúcom regresnom teste
(`tests/test_basket_completion_v2_14e.py::TestCaseG_AlreadyCoveredRole`)
— jeho správa má čiarku, čo je presne prípad, kedy náhodná ochrana
funguje.

**Oprava**: explicitný, deterministický guard v
`decide_use_case_advice()` — keď správa obsahuje basket-action jazyk
(`app.basket_completion._wants_basket_completion()`, znovu-použité cez
deferred import) PRE use case, ktorý je zároveň
`BASKET_V1_ELIGIBLE_USE_CASES`, funkcia sa defer-uje. Už nezávisí od
interpunkčnej náhody.

## 5. Kľúčové zistenie #2 — multi-item self-declaration bola orezaná na 1 položku

`_self_declared_concept_ids()` volalo `parse_structured_query()` na
CELÚ správu naraz — vracia najviac JEDEN `concept_id`. Živo overené:
pre 2-položkovú deklaráciu bolo `fish_sauce` naďalej ukázané ako
"ešte potrebné", hoci zákazník ho práve spomenul.

**Oprava**: rozdelenie správy na segmenty (interpunkcia + spojka " a ")
a volanie `parse_structured_query()` na KAŽDÝ segment zvlášť, zjednotenie
zhôd. Prísne zlepšenie (existujúci 1-položkový test zostáva presne
rovnaký, keďže jeho správa sa parsuje identicky ako jediný vlastný
segment).

**Zostávajúce, zdokumentované obmedzenie**: `parse_structured_query()`
sama osebe rozpoznáva prevažne nominatív ("rybacia omacka" áno,
akuzatív "rybaciu omacku" nie) — reálna slovenská veta "Mám X" ale
gramaticky VYŽADUJE akuzatív. Toto je zdieľaný, cross-cutting problém
mimo rozsahu tejto sprinty (Sekcia 87 — žiadny široký redesign
parsovania/vyhľadávania) — rovnaká trieda problému, akú V2.16c našlo
pre `REPLACEMENT_SUBJECT_ALIASES`. Zdokumentované ako data debt.

## 6. Kľúčové zistenie #3 — `basket_completion` nemalo ŽIADNU session kontinuitu

Živo potvrdené PRED opravou: po úvodnej `"Co potrebujem na pho?"`
odpovedi, KAŽDÝ nasledujúci ťah ("Co este potrebujem?", "Ukaz mi
lacnejsiu alternativu.", "Je tento kosik kompletny?") padol na
generickú "Nemám aktívny nákupný zoznam..." odpoveď. Toto je presne
Sekcia 30 ("core target") tejto sprinty.

**Oprava** (minimálna, mirror existujúceho vzoru z
`app.recipe_shopping`/`app.session_state`'s `active_recipe_id`):

- `app.session_state.get_active_basket_use_case()`/
  `set_active_basket_use_case()`/`clear_basket_state()` — nová, malá
  session field, presne v tvare `active_use_case`/`active_recipe_id`.
  `selected_ingredient_products` (existujúci, zdieľaný store) sa
  **znovupoužíva bez zmeny**.
- `app.basket_completion.resolve_basket_followup()` — nová funkcia,
  zdieľa `_build_basket_decision()` s pôvodným `decide_basket_completion()`
  (extrahovaná spoločná logika, žiadna duplikácia). Vracia None (a
  volajúci vyčistí stav) pri: chýbajúcom aktívnom basket use case,
  `recipe_subject` už rozhodnutom, companion-request správe, EXPLICITNE
  inak pomenovanom use case (hard switch), alebo správe, ktorá nie je
  ani rozpoznateľná basket-akcia ani nová self-declared položka.
- `app.workflow_executor.execute_basket_completion()` — najprv skúsi
  `resolve_basket_followup()` (len keď je aktívny basket use case —
  **nulová zmena správania pre prvý ťah každej session**), pri None
  vyčistí stav a padne na pôvodnú `decide_basket_completion()` cestu
  nezmenenú. Pri úspechu nastaví `active_basket_use_case`.
- `app.session_state.apply_reset()` — pridané `clear_basket_state()`
  (predtým chýbalo, reset by nechal basket stav nažive).

**Sebaopravená regresia (nájdená plnou regresnou sadou, nie live
verifikáciou)**: prvá verzia `resolve_basket_followup()` akceptovala AJ
holú self-declared položku (bez explicitného basket-akčného jazyka) ako
trigger pre pokračovanie. Toto spôsobilo, že bežné NÁSLEDNÉ vyhľadávanie
produktu ("sushi ryza" hneď po "co potrebujem na sushi") bolo mylne
preinterpretované ako self-declaration namiesto normálneho
`product_search`/cross-sell ťahu — pokazilo to existujúci
`tests/test_decision_observability_expansion_v2_15e_3.py`'s cross_sell
charakterizačný test (3 zlyhania, `cross_sell_eligible=None` namiesto
`True`). Oprava: `resolve_basket_followup()` teraz vyžaduje EXPLICITNÝ
basket-akčný jazyk (`_wants_basket_completion()`) — holá self-declarácia
bez akčnej frázy je zámerne ponechaná ako nezavedená medzera (Sekcia 31
— "nehádať"), nie implementovaná touto sprintou. Po oprave: plná
regresná sada 1965/1965 (pozri Sekciu 22).

**Dôležitá nuancia, overená priamo, nie predpokladaná**: FAQ/allergen
safety bežia na VYŠŠEJ precedenčnej úrovni než `basket_completion`
(rovnako ako existujúci `recipe_shopping` mechanizmus — overené na
`pad_thai`: informačná odbočka "Kde mate predajnu?" NEVYMAŽE aktívny
recept, `"Co este potrebujem?"` po nej správne pokračuje). Basket
kontinuita je zámerne **konzistentná** s týmto existujúcim správaním,
nie prísnejšia — informačná odbočka nezruší aktívny košík, len
explicitný hard switch (iný use case, product search, comparison,
replacement, allergen) ho vymaže.

## 7. Charakterizácia (pred implementáciou, Sekcia 12)

| Prípad | Správanie PRED | Správanie PO |
|---|---|---|
| A-E. "co potrebujem na X" (pho/sushi/pad_thai/tom_kha/ramen) | 3 rôzne mechanizmy, zdokumentované vyššie | nezmenené (mimo scope tejto opravy) |
| F. 2-item self-declare + "co este" na pho | `use_case_advice` únos, nesprávna odpoveď | `basket_completion`, `rice_noodles=ALREADY_COVERED` |
| H/H2. "co este potrebujem?" po pho/sushi | generický fallback | správny basket_completion, rovnaký use case |
| I. "lacnejšia alternatíva" po basket | generický fallback | **nezmenené** (mimo scope, pozri Sekciu 11) |
| J. "nemate tuto, cim nahradim?" po basket | `replacement_products`, ale kandidáti nesúvisia s konkrétnou rolou (žiadny aktívny-ingredient kontext) | **nezmenené** (mimo scope) |
| K/L. "pre 6 ľudí"/"dve porcie" bez explicitnej akcie | vôbec nedosiahne recipe/basket systém | **nezmenené** (dáta na škálovanie neexistujú) |
| M. "je kosik kompletny?" | irelevantný product_search | **nezmenené** (mimo scope) |
| N. "pridaj vsetko do kosika" | mis-routing na `product_comparison` | **nezmenené** (mimo scope, Sekcia 37 — bulk add nie je autorizované) |
| O-S. hard switches | všetky správne fungovali už predtým | nezmenené, znovu-overené |
| T. reset | fungoval, ale nevyprázdnil basket stav (ten predtým ani neexistoval) | teraz aj `clear_basket_state()` |
| U. cross-session izolácia | OK (nebolo čo unikať) | OK, znovu-overené s novým stavom |

## 8. Recipe requirement model (Sekcia 13)

Dáta podporujú presne **REQUIRED** (jediná používaná hodnota naprieč
201 ingredient-role hranami) a **NOT_AVAILABLE** (kurátorovaný,
explicitný zoznam — čerstvé suroviny ako vajcia/limetka/bylinky, ktoré
Foodland nepredáva). **Žiadny OPTIONAL/GARNISH rozdiel v dátach
neexistuje** (aj "arašidy" pre pad_thai, sémanticky GARNISH rola, je v
dátach REQUIRED) — model preto zámerne NEROZLIŠUJE optional/core
(Sekcia 70 — dáta to nepodporujú, nevymýšľať).

## 9. Already-have model (Sekcia 15)

Jediné autoritatívne zdroje "zákazník toto už má":
1. `selected_ingredient_products` (session, explicitná voľba — ordinal
   referencia "tie druhé", nikdy z toho, že bol produkt len zobrazený).
2. Self-declarácia v TEJTO správe (`_self_declared_concept_ids()`,
   teraz multi-segment, Sekcia 5).

**Nikdy**: odporúčaný produkt, kliknutý produkt, zobrazený produkt.

## 10. Missing-role model (Sekcia 17)

Reálne používané stavy (zo `STATUS_*` konštánt): `RESOLVED_PRODUCT`,
`ALREADY_COVERED`, `NO_CATALOG_PRODUCT`, plus `unresolved_concepts`
(raw text, žiadny concept_id vôbec neexistuje). `AMBIGUOUS` je
definovaný v kóde pre úplnosť, ale v praxi nedosiahnuteľný (kandidáti sú
deterministicky zoradení) — rovnaký vzor ako `use_case_advice`'s
CLARIFY stav.

## 11. Completeness contract (Sekcia 18/19)

`fully_resolved=True` **výlučne** znamená "všetky MODELOVANÉ role sú
RESOLVED_PRODUCT/ALREADY_COVERED A `unresolved_concepts` je prázdne" —
NIE "toto je celý recept v reálnom svete". Živo overené: pho má
`coverage=1.0` (všetky 4 modelované role vyriešené) ale
`fully_resolved=False`, pretože "korenie pho" je známy, ale
nevyriešiteľný koncept — **nikdy sa nestratí v metrike**, customer-facing
text ho explicitne vymenuje ("Pre tieto položky zatiaľ nemám
dostatočne spoľahlivé produktové priradenie: korenie pho").

## 12. Quantity/serving audit (Sekcia 20/21) — Gate: `SERVING_SCALING_DATA_REQUIRED`

**Žiadny** reálny Foodland recept (0/53) nesie štruktúrované množstvo.
`PlanIngredient.quantity`/`package_count` sú vždy `None` pre reálne
dáta — škálovací kód (`scale_plan_quantities`/`package_count_for`)
existuje a je testovaný proti syntetickým fixture dátam, ale je
dormant proti živým dátam (rovnaký stav ako pred touto sprintou,
znovu-overené, nezmenené). `extract_requested_servings_lenient()` je
volaný len VNÚTRI `resolve_recipe_followup()` (t.j. len keď je recept
už aktívny cez pad_thai/tom_kha cestu) — bare prvý ťah so servings
jazykom ("Chcem variť pho pre 6 ľudí") vôbec nedosiahne recipe/basket
systém (padá na `related_products`/`product_search`), živo overené,
nezmenené touto sprintou.

## 13. Substitution dependency (Sekcia 10)

V2.16c je plne prítomný a relevantný. `replacement_products` mechanizmus
je generický a NEZÁVISLÝ od basket/recipe rolí — vie odpovedať na
"čím nahradím X", ale nie je (a nebol pred touto sprintou) prepojený s
KONKRÉTNOU rolou/konceptom, ktorá práve chýba v aktívnom košíku. Prípad
J (Sekcia 7 vyššie) toto demonštruje: bez aktívneho-ingredient kontextu
vráti generické kandidáty, nie substitúciu pre konkrétnu chýbajúcu
rolu. **Zámerne neopravené touto sprintou** — vyžadovalo by to nový
"aktívna-rola-v-diskusii" tracking mechanizmus pre basket_completion
(podobný `last_recipe_ingredient_concept`), čo presahuje minimálny
rozsah (Sekcia 47 — najmenšia bezpečná voľba).

## 14. Dietary/allergen safety (Sekcia 26/27)

Nedotknuté. `allergen_safety_answer()` zostáva vyššej precedencie než
basket_completion aj recipe_shopping — živo overené (`"Som alergicky
na soju, cim nahradim sojovu omacku?"` po aktívnom pho košíku →
`intent=allergen_safety`, nezmenené). Žiadny nový dietary/vegan/
gluten-free filter nebol pridaný do basket rolí — V2.16b/V2.16c
záver (len gluten_free je spoľahlivý signál) sa tu nepoužíva, pretože
basket role candidate generation (`generate_role_candidates`) filtruje
len na taxonómiu (concept_id + confidence), nie na dietary_facets —
nezmenené touto sprintou, mimo rozsahu.

## 15. Stock/availability (Sekcia 72/73) — Gate: `CATALOG_PRESENCE_ONLY`

Žiadne pole pre live stock/skladovú dostupnosť neexistuje v
`data/products.json` (13 polí, žiadne `availability`-realtime pole
mimo statického `availability` reťazca z feedu). Basket/recipe
odporúčania sú **katalógová prítomnosť**, nie potvrdená skladová
dostupnosť — nezmenené, zdokumentované ako pred-existujúci limit.

## 16. Per-recipe readiness matrix (Sekcia 82, živo zmerané)

| Use case | Modelované role | Vyriešené | Nevyriešené | Already-have | Substitúcia | Role completeness | Quantity dáta | Serving | Stav |
|---|---|---|---|---|---|---|---|---|---|
| sushi | 4 (sushi_rice, nori, rice_vinegar, soy_sauce) | 4/4 | 0 | ÁNO (multi-item) | generická, nie role-viazaná | **COMPLETE** | žiadne | nerozpoznané na 1. ťahu | `RECIPE_BASKET_INTELLIGENCE_LIVE` |
| pho | 4 (fish_sauce, rice_noodles, hoisin_sauce, sriracha_sauce) | 4/4 | 1 ("korenie pho") | ÁNO (multi-item, opravené) | generická | **COMPLETE_WITH_LIMITATIONS** (1 known gap, čestne priznaný) | žiadne | nerozpoznané na 1. ťahu | `RECIPE_BASKET_INTELLIGENCE_LIVE_WITH_LIMITATIONS` |
| kari | 4 (curry_paste, coconut_milk, jasmine_rice, fish_sauce) | 4/4 | 0 | ÁNO (multi-item) | generická | **COMPLETE** | žiadne | nerozpoznané na 1. ťahu | `RECIPE_BASKET_INTELLIGENCE_LIVE` |
| pad_thai | 5 (rice_noodles, tamarind_pasta, fish_sauce, palmovy_cukor, arasidy) | 5/5 (100% recipe_shopping_coverage) | 0 modelovaných; 4 explicitne NOT_AVAILABLE (vajce/tofu, klíčky, limetka, cibuľka) | LEN ordinal-selection (žiadna same-turn self-deklarácia) | generická | **COMPLETE_KNOWN_RECIPE_GRAPH** | žiadne (dormant kód) | rozpoznané len vo followupe | `RECIPE_BASKET_INTELLIGENCE_LIVE_WITH_LIMITATIONS` (staršia recipe_shopping cesta, nie basket_completion) |
| tom_kha | 5 (coconut_milk, galangal, citronova_trava, kaffirove_listy, fish_sauce) | 5/5 (100%) | 0 modelovaných; 4 NOT_AVAILABLE (mäso/tofu, huby, limetka, koriander) | LEN ordinal-selection | generická | **COMPLETE_KNOWN_RECIPE_GRAPH** | žiadne | rozpoznané len vo followupe | `RECIPE_BASKET_INTELLIGENCE_LIVE_WITH_LIMITATIONS` |
| ramen | 5 v `recipe_graph` (instant_noodles, dashi, miso, sojova_omacka, wakame) | neaplikovateľné — samostatný mechanizmus, `intent=related_products`, žiadny `basket_roles`/`recipe_shopping_plan` | neznáme (nie je expozované) | nie | generická | **DATA_INCOMPLETE** (mechanizmus nevystavuje rovnaký kontrakt) | žiadne | nie | `RECIPE_BASKET_FOUNDATION_ONLY` |

## 17. Per-capability readiness matrix (Sekcia 83)

| Kapacita | Gate | Stav | Evidencia | Limitácie |
|---|---|---|---|---|
| recipe/basket role planning | D | LIVE (pho/sushi/kari/pad_thai/tom_kha) | Sekcia 16 | ramen chýba |
| already-have detekcia (session) | D | LIVE | `selected_ingredient_products` | nezmenené touto sprintou |
| already-have detekcia (self-declare, same-turn) | C | LIVE_WITH_LIMITATIONS | Sekcia 5, opravené na multi-item | limitované pádovým pokrytím `parse_structured_query` |
| missing-role výpočet | D | LIVE | `STATUS_*` vocab | — |
| role completeness | D | LIVE, čestné (Sekcia 11) | `fully_resolved` | — |
| "čo ešte potrebujem?" kontinuita | C→D | **NOVÉ, LIVE** (táto sprinta) | Sekcia 6/7 | len pre basket_completion (pho/sushi/kari) |
| quantity completeness | A | AUDIT_ONLY/DATA_REQUIRED | Sekcia 12 | 0/53 receptov má štruktúrované množstvo |
| serving-count rozpoznanie | B | FOUNDATION_READY | len vo followupe existujúceho receptu | prvý ťah ho nedosiahne |
| serving scaling | A | DATA_REQUIRED | žiadne dáta | — |
| substitučný fallback pre chýbajúcu rolu | A | AUDIT_ONLY | Sekcia 13 | generický, nie role-viazaný |
| "lacnejšia alternatíva"/"väčšie balenie" followup | A | AUDIT_ONLY | Sekcia 7 riadok I | žiadny "posledná diskutovaná rola" tracking pre basket_completion |
| bulk add-to-cart | A | `BULK_ADD_TO_CART_NOT_IN_SCOPE` | Sekcia 37 explicitne zakazuje | žiadny bezpečný cart-mutation seam |
| stock awareness | A | `CATALOG_PRESENCE_ONLY` | Sekcia 15 | žiadne live stock dáta |

## 18. Zostávajúci data debt

- `parse_structured_query()` pádové pokrytie (nominatív-heavy) — zdieľaný
  problém naprieč V2.16c aj V2.16d, mimo rozsahu oboch.
- Ramen nemá basket_completion/recipe_shopping kontrakt — vlastný,
  nezávislý mechanizmus s iným response shape.
- 0 receptov s množstvom → serving scaling zostáva navždy dormant, kým
  business dáta neposkytnú štruktúrované množstvá.

## 19. Zostávajúci architektonický debt

- Trojcestné rozdelenie (basket_completion / recipe_shopping / ramen
  legacy) nebolo zjednotené — Sekcia 9 to explicitne nevyžadovala bez
  dôkazu skutočnej medzery, a konvergencia bola aplikovaná len tam, kde
  charakterizácia dokázala reálnu chybu (Sekcie 4-6), nie widescale.
- `basket_completion` nemá "posledná diskutovaná rola" tracking
  (`recipe_shopping` má `last_recipe_ingredient_concept`) — potrebné
  pre "lacnejšia alternatíva"/"väčšie balenie" followupy, budúci malý
  sprint.

## 21. Testy a plná regresná sada

Nový súbor `tests/test_recipe_basket_intelligence_v2_16d.py` (18 testov,
pokrýva všetky 3 opravy + regresné kontroly rt0004/rt0010/rt0013/
vegan-noodles). Cielený beh (`test_basket_completion_v2_14e.py` +
`test_recipe_shopping.py` + `-k "use_case or basket or recipe"` naprieč
celou `tests/`): 322 passed, 0 failed. Plná regresná sada
(`pytest tests/ -q`): **1965 passed, 0 failed** (po sebaoprave zo
Sekcie 6 — prvý beh mal 3 zlyhania, root-caused a opravené v rámci tejto
sprinty, nie skryté). V2.10 (--fast --diff): Gate WARN (rovnaké 4
pred-existujúce zlyhania), **0 regresií**. Consistency audit: 0
kolízií. Trust audit: 0 zero-match, 0 PII únikov.

## 22. Byte-safety

4 zmenené súbory (`app/session_state.py`, `app/use_case_advice.py`,
`app/basket_completion.py`, `app/workflow_executor.py`) — všetky
jednotné-EOL (nie zmiešané ako `app/main.py`), diff overený
`git diff --stat`/`--check`: 182+ riadkov, žiadny whole-file rewrite
artefakt, žiadne trailing-whitespace varovania nad rámec štandardného
CRLF/LF git upozornenia.

## 23. AUTO_PROMOTION

**AUTO_PROMOTION = FALSE** (nezmenené). Žiadny learning/ranking kód
nebol dotknutý. `NEXT_PROGRAM_PHASE = WAIT_FOR_EMPIRICAL_DATA`
nezmenené, V2.15f nezačaté.
