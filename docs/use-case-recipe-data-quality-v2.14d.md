# V2.14d — Use-Case & Recipe Data-Quality Closure

Dátum: 2026-08-22. Baseline: `f30610f` (V2.14c + CI hotfix), pytest 1446/1446,
V2.10 fast-mode 34/39, canary 10/10. Toto NIE JE Basket Completion - táto
sprinta opravuje a validuje základy, na ktorých môže byť Basket Completion
neskôr postavené (Section 35 zadania).

## 1. Baseline

- HEAD == `origin/main` == `f30610f` pred zmenami, working tree čisté
  (okrem predexistujúceho netrackovaného `.claude/`).
- pytest 1446/1446, V2.10 fast-mode 34/39 (identické error buckety), canary
  10/10, consistency audit 0 kolízií, trust audit 0 nálezov, deployment
  check OK - všetko overené priamo pred akoukoľvek zmenou.

## 2. Repository reality check

Žiadny drift: `4b63d66` (V2.14c) a `f30610f` (CI hotfix) sú priami predkovia
HEAD. Žiadna neznáma nekomitnutá práca. Bezpečné pokračovať bez resetu.

## 3. V2.14c findings re-verification

| Finding | Klasifikácia | Dôkaz |
|---|---|---|
| A. Ramen/instant_noodles taxonomy kolízia s nepotravinovými miskami | **CONFIRMED** | Priama reprodukcia: `classify_product()` na "Japonská Miska Ramen Set Dragon" vrátil `family=instant_food, subfamily=instant_noodles, confidence=MEDIUM` pred opravou. |
| B. RECIPE_COMPLETION stráca 30-60% konceptov na jedlo | **CONFIRMED (spresnené)** | Reálne namerané rozmedzie 0-60% strát (nie uniformne 30-60%) - pozri Sekciu 8. |
| C. Pad Thai/Tom Kha use-case-advice nedosiahnuteľné kvôli recipe-intent precedencii | **CONFIRMED** | Priama trasovacia matica (Sekcia 12): "aké rezance na pad thai" pred opravou vracalo `intent=recipe`, nie `use_case_advice`. |

## 4. Ramen taxonomy audit

Živý audit `instant_food/instant_noodles` rodiny (89 produktov pred opravou):
77 HIGH (kategória "Instantné polievky"), 12 MEDIUM (titulová zhoda bez
kategórie). Z 12 MEDIUM: **3 TRUE_POSITIVE** (reálne jedlé instantné
rezance mimo "Instantné polievky" kategórie - Mendake, KING COOK, VINALY)
a **9 FALSE_POSITIVE** (japonské servírovacie misky/bambusová lyžica -
"Japonské Ramen misky sada 2 ks", "Ramen lyžica bambusová", "Japonská
Miska Ramen Set Dragon") - všetkých 9 malo `category_memberships` vrátane
"Stolový riad"/"Kuchynské potreby", NIKDY "Instantné polievky".

## 5. Ramen root cause

**Klasifikácia: TITLE_TOKEN_COLLISION.** `instant_noodles` FamilyRule má
bare title_phrase `"ramen"` bez kategórie na potvrdenie - akýkoľvek
produkt s "ramen" v názve, ktorý nie je v kategórii "Instantné polievky",
sa napriek tomu classifikuje ako instant_food (MEDIUM confidence,
degradácia z HIGH bázy). `exclude_title_phrases` už existujúce na tomto
pravidle (`"polievka", "koreniaca pasta", "omacka", "sitko", "shirataki",
"konjac"`) neobsahovalo "miska"/"misky"/"lyzica" (presne zhoda s
V2.14c-om zdokumentovaným, dosiaľ neopraveným nálezom).

## 6. Ramen fix

**Nové, kategóriovo-riadené `FamilyRule`** (`rule_id="tableware"`,
`family="kitchenware"`, `subfamily="tableware"`, `category_terms=("stolovy
riad",)`), pozicované PRED `instant_noodles` (first-match-wins). Rovnaký
precedenčný vzor ako existujúci `rice_cooker` (kategória-only pravidlo).
**Nie** lexikálny title-exclude (hoci `soba`/`wheat_noodles` pravidlá
už tento vzor používajú pre QUERY-side rozlíšenie bez kategórie) - kategória
je silnejší, generickejší signál dostupný tu, pretože ide o PRODUKTOVÚ
klasifikáciu s reálnymi category_memberships, nie o holý text dotazu.
Žiadny hand-coded SKU zoznam.

## 7. Ramen blast radius

`"stolovy riad"` kategória: **268 produktov CELKOVO** v katalógu, z toho
pred opravou 259 UNKNOWN + 9 instant_noodles (presne náš problém) + **0**
už inak správne klasifikovaných - matematicky bezpečná zmena (žiadny
produkt nestratil existujúcu správnu klasifikáciu). Po oprave: HIGH
531→799 (+268, presná zhoda), MEDIUM 197→188 (-9, presná zhoda), UNKNOWN
1404→1145 (-259, presná zhoda). `"miska na ramen"`/`"ramen bowl"` legacy
free-text search naďalej správne nájde servírovacie misky (nie je
taxonomy-gated). Real edible instant ramen (Shin Ramyun, Buldak, ...)
zostáva nezmenené `instant_food/instant_noodles`.

## 8. RECIPE_COMPLETION baseline

Per-dish coverage PRED opravou (`app.cross_sell.roles_for_recipe()` -
distinct koncepty vyriešené / celkový počet ingrediencií):

| Jedlo | Coverage (pred) |
|---|---|
| pho | 3/5 (60%) |
| ramen | 4/5 (80%) |
| pad_thai | 3/5 (60%) |
| tom_kha | 2/5 (40%) |
| kari | 3/4 (75%) |
| thajske_kari | 4/4 (100%) |

Celkovo 19/28 (67.9%) - reálne rozmedzie 40-100% podľa jedla, nie
uniformne "30-60% strát" ako naznačoval V2.14c popis, ale konzistentné s
tým, že VŠETKY jedlá okrem thajske_kari majú reálnu, nenulovú stratu.

## 9. RECIPE_COMPLETION loss analysis / rejection reasons

Každý nevyriešený koncept overený PRIAMO proti katalógu (`cached_search_products`)
a taxonomy (`classify_product`):

| Koncept | Dôvod | Reálny produkt existuje? |
|---|---|---|
| "banh pho" (pho) | **SEARCH_QUERY_EXPANSION_ERROR** - produkt HIGH-klasifikovaný cez kategóriu, ale QUERY text nemal zodpovedajúci title_phrase | Áno (5 produktov) |
| "kari pasta" bare (kari) | **SEARCH_QUERY_EXPANSION_ERROR** - rovnaký vzor | Áno (5 produktov) |
| "korenie pho" (pho) | **NO_TAXONOMY_MATCH** | Áno (5 produktov, žiadne FamilyRule) |
| "dashi" (ramen) | **NO_TAXONOMY_MATCH** | Áno (4 produkty) |
| "palmovy cukor" (pad_thai) | **NO_TAXONOMY_MATCH** | Áno (5 produktov) |
| "arasidy" (pad_thai) | **NO_TAXONOMY_MATCH** | Áno (5 produktov) |
| "galangal" (tom_kha) | **NO_TAXONOMY_MATCH** (FUTURE_DATA_REQUIRED - tenké zásoby) | Áno (3 produkty) |
| "citronova trava" (tom_kha) | **NO_TAXONOMY_MATCH** (FUTURE_DATA_REQUIRED) | Áno (5 produktov) |
| "kaffirove listy" (tom_kha) | **NO_TAXONOMY_MATCH** (FUTURE_DATA_REQUIRED) | Áno (5 produktov) |

## 10. Safe lexical recovery

Opravené LEN 2 koncepty s preukázateľne bezpečným, generickým riešením:
pridanie chýbajúcej `title_phrase` na UŽ EXISTUJÚCE, správne HIGH-confidence
pravidlá (`rice_noodles` += `"banh pho"`, `curry_paste` += `"kari pasta"`,
`"curry pasta"`) - **žiadna nová rodina, žiadne nové pravidlo**. Overené,
že variety-specifické pravidlá (`red_curry_paste`, `green_curry_paste`,
`panang_curry_paste`, `massaman_curry_paste`) si zachovávajú prednosť
(first-match-wins, pozicované pred generickým `curry_paste` pravidlom) -
`"cervena kari pasta"` naďalej rieši `red_curry_paste`, nie generickú
rodinu. Ostatných 7 konceptov (skutočný NO_TAXONOMY_MATCH bez akéhokoľvek
FamilyRule) **zámerne NEOPRAVENÉ** - Section 3/13 zadania zakazujú "broad
taxonomy expansion" v tejto sprinte; sú zdokumentované ako dátový dlh
(Sekcia 21).

## 11. Coverage before/after

| Jedlo | Coverage PRED | Coverage PO | Status |
|---|---|---|---|
| pho | 3/5 (60%) | **4/5 (80%)** | IMPROVED_SAFE |
| kari | 3/4 (75%) | **4/4 (100%)** | IMPROVED_SAFE |
| ramen | 4/5 (80%) | 4/5 (80%) | NO_SAFE_IMPROVEMENT ("dashi" NO_TAXONOMY_MATCH) |
| pad_thai | 3/5 (60%) | 3/5 (60%) | NO_SAFE_IMPROVEMENT (palm sugar/arašidy NO_TAXONOMY_MATCH) |
| tom_kha | 2/5 (40%) | 2/5 (40%) | NO_SAFE_IMPROVEMENT (aromatiká FUTURE_DATA_REQUIRED) |
| thajske_kari | 4/4 (100%) | 4/4 (100%) | unchanged (už plné) |

Celkovo 19/28 (67.9%) → **21/28 (75.0%)**.

## 12. Precision before/after

**0 nových false positives kdekoľvek** - overené: (a) variety-precedencia
kari pasty nezmenená, (b) plný V2.10 eval 34/39 identický pred/po
(rovnaké error buckety), (c) canary 10/10 nezmenené, (d) 46+28+57 = 131
taxonomy/cross_sell/use_case_advice testov, všetky PASS.

## 13. ABSTAIN behavior

`roles_for_recipe()` pre `pad_thai`/`tom_kha` naďalej vracia LEN skutočne
vyriešené koncepty (3, resp. 2) - nikdy nehádaný korešpondent pre
"arasidy"/"galangal"/atď. Trvalo zamknuté testami
(`test_tom_kha_aromatics_correctly_abstain_not_invented`,
`test_pad_thai_untaxonomized_ingredients_correctly_abstain`).

## 14. Action/target resolver audit

`app.turn_resolver.resolve_action_target_signal()` (V2.13b, rt0004's
fix point) explicitne preskúmaný a otestovaný pred akoukoľvek zmenou.
**Klasifikácia: INSUFFICIENT_FOR_THIS_CLASS.** Dôvod: jeho `TurnAnalysis`
dataclass nemá ŽIADNE pole pre `recipe_subject`/use-case cieľ - jeho
JEDINÁ zodpovednosť je arbitrácia `special_subject` vs. `related_subject`
konfliktu (vyžaduje OBOJE + `has_recipe_shopping_language`, aby vôbec
niečo vrátil). Pad Thai/Tom Kha problém je architektonicky INÁ otázka:
konflikt medzi `recipe_subject` (z `RECIPE_INTENT_MARKERS`) a use-case
rozpoznaním - úplne iný pár detektorov, ktoré `resolve_action_target_signal()`
vôbec nepozná. Rozšírenie TEJTO funkcie by ju urobilo nekonzistentnou s
jej vlastným, úzko definovaným poslaním (Section 29A vyžaduje dôkaz pred
rozšírením - poskytnutý).

## 15. Pad Thai routing

**Root cause (dôkaz pred opravou):** `RECIPE_INTENT_MARKERS` obsahuje
bare `"pad thai"` (V2.8-éra fix pre "chcem robiť Pad Thai"), `is_recipe_intent()`
vracia `True` pre AKÚKOĽVEK správu obsahujúcu tento substring, bez ohľadu
na okolitý jazyk. `"aké rezance na pad thai"` → `recipe_subject` nastavené
→ `execute_use_case_advice()` sa (podľa V2.14c kontraktu) vzdáva → recept
vyhráva namiesto use-case-advice.

**Oprava:** Generická, nie dish-špecifická. Nová `_BARE_DISH_RECIPE_MARKERS
= ("tom kha", "pad thai")` (podmnožina `RECIPE_INTENT_MARKERS`) +
`_recipe_intent_is_bare_dish_marker_only()` (True LEN ak je bare-dish
marker JEDINÝM dôvodom recipe-intent zhody - žiadny iný recipe marker,
žiadny "recept*" token, žiadny `wants_recipe_products()` shopping-list
signál). Keď je True A `app.use_case_advice.has_resolvable_role()`
(nová, znovupoužíva `resolve_use_case()`/`resolve_role()` - ŽIADNA
duplicitná alias/role tabuľka) nájde konkrétnu rolu, `recipe_subject` sa
pre tento ťah potlačí (`None`), čím use_case_advice preberá vetvu.

## 16. Tom Kha routing

Rovnaký mechanizmus, rovnaká oprava (generická, nie hardcoded pre
konkrétne meno jedla).

## 17. Recipe intent preservation

Explicitne overené naprieč celou maticou (Sekcia 30 nižšie) - `"recept
na pad thai"`, `"recept na tom kha gai"`, `"co potrebujem na pad thai"`,
`"co potrebujem na tom kha gai"` (PRESNE historický scenár, pre ktorý
boli bare markery pôvodne pridané) zostávajú **úplne nezmenené** →
`recipe`/`RECIPE_SHOPPING`.

## 18. Live routing characterization matrix (pred → po)

| # | Správa | Pred | Po |
|---|---|---|---|
| A | "pad thai" | recipe | recipe (nezmenené) |
| B | "recept na pad thai" | recipe | recipe (nezmenené) |
| C | "co potrebujem na pad thai" | recipe_to_products | recipe_to_products (nezmenené) |
| D | "ake rezance na pad thai" | recipe | **use_case_advice** |
| E | "ktore rezance su najlepsie na pad thai" | recipe | **use_case_advice** |
| F | "tom kha gai" | recipe | recipe (nezmenené) |
| G | "recept na tom kha gai" | recipe | recipe (nezmenené) |
| H | "co potrebujem na tom kha gai" | recipe_to_products | recipe_to_products (nezmenené) |
| I | "ake kokosove mlieko na tom kha gai" | recipe | **use_case_advice** |
| J | "ktore kokosove mlieko je lepsie na tom kha gai" | recipe | **use_case_advice** |
| K | "pho" | product_search | product_search (nezmenené) |
| L | "aka rybacia omacka na pho" | use_case_advice | use_case_advice (nezmenené) |
| M | "sushi" | product_search | product_search (nezmenené) |
| N (rt0004) | "suvisiace produkty k sushi ryzi" | related_products | related_products (nezmenené) |
| O | "ramen" | product_search | product_search (nezmenené) |
| P | "ake rezance na ramen" | product_search | product_search (nezmenené) |

## 19. rt0004 / rt0010 / rt0011 / rt0013

rt0004 (riadok N vyššie), rt0010 ("sojova omacka bez soje" →
`allergen_safety`), rt0011 ("mam rad nepalive jedlo, co odporucas?" →
`product_search`) - **všetky trvalo zamknuté testami, všetky nezmenené**.
rt0013 zostáva `PENDING_SEMANTIC_PRODUCT_DECISION` - touto sprintou sa
NEDOTÝKA (Section 44 zadania).

## 20. Session safety / ResultSet continuity

Nezmenené - žiadna zmena session/memory logiky v žiadnej z troch častí.
V2.13b/V2.13b.1 testy (78 testov naprieč `test_recipe_state_machine_v2_13e.py`,
`test_workflow_executor_v2_13d.py`, `test_query_semantics_v2123.py`,
`test_session_contamination_v2_13b_1.py`) všetky PASS bezo zmeny.

## 21. Retrieval / ranking / taxonomy impact

Žiadna zmena ranking váh. 2 nové title_phrases (Sekcia 10), 1 nové
FamilyRule (Sekcia 6) - všetko deterministické, žiadny nový sieťový/LLM
call. Taxonomy coverage (non-UNKNOWN) 34.4% → **46.5%** (996/2140).

## 22. Recommendation evidence / V2.14a confidence contract

Nezmenené a nedotknuté - `app.recommendation_evidence` sa nemenil.
LLM_JUDGMENT naďalej nikdy negeneruje HIGH confidence.

## 23. V2.14b comparison compatibility

Nezmenené - `app/comparison.py` sa nemenil, disjunktnosť s use-case-advice
naďalej platí (žiadny nový test regresie).

## 24. V2.14c use-case compatibility

Sushi/pho/kari zostávajú presne také, aké boli (žiadna zmena ich
mechanizmu) - len Pad Thai/Tom Kha reachability sa zmenila.

## 25. Per-use-case readiness matrix (finálna, V2.14d)

| Use case | V2.14c status | V2.14d status | Dôkaz |
|---|---|---|---|
| sushi | LIVE | **LIVE** (nezmenené) | |
| pho | LIVE | **LIVE** (coverage 60%→80% pre RECIPE_COMPLETION, use-case-advice nedotknuté) | |
| kari | LIVE | **LIVE** (coverage 75%→100%) | |
| pad_thai | SHADOW_ONLY | **LIVE** (routing fix, Sekcia 15/18) | |
| tom_kha | SHADOW_ONLY | **LIVE** (routing fix, Sekcia 16/18) | |
| ramen | DATA_REQUIRED | **DATA_REQUIRED** (nezmenené - taxonomy kolízia opravená pre TABLEWARE, ale bare "ramen"/"rezance" stále mapuje na `instant_noodles` bez ohľadu na zámer zákazníka; `use_case_advice` alias pre ramen zostáva zámerne nezaregistrovaný) | |

## 26. Basket readiness scorecard

| Kritérium | Hodnotenie | Dôkaz |
|---|---|---|
| Recipe concept coverage | PARTIAL | 21/28 (75%), rozmedzie 40-100% podľa jedla |
| Product-role mapping precision | PASS | 0 nových false positives, variety-precedencia overená |
| Taxonomy support | PARTIAL | 46.5% netriedy pokrytie katalógu (996/2140), zvyšok UNKNOWN |
| Lexical fallback precision | PASS | Len 2 bezpečné, overené obnovy; 7 NO_TAXONOMY_MATCH správne ponechaných |
| False-positive rate | PASS | Ramen kolízia opravená, 0 nových side-efektov (matematicky overené) |
| Use-case routing reachability | PASS | 5/6 use cases LIVE (up from 3/6) |
| Comparison compatibility | PASS | Disjunktnosť nezmenená |
| Same-need exclusion | PASS | `app.cross_sell` nezmenené, testy PASS |
| ABSTAIN safety | PASS | Overené explicitne testami (Sekcia 13) |
| Session isolation | PASS | Nedotknuté, 78 V2.13b/b.1 testov PASS |
| Catalog coverage | PARTIAL | 53.5% katalógu stále UNKNOWN taxonomy-wide |
| Multilingual risk | **FAIL (známe obmedzenie)** | Všetky opravy tejto sprinty sú výhradne slovenské lexikálne mechanizmy (title_phrases, RECIPE_INTENT_MARKERS, use_case_advice aliasy) - žiadna multi-jazyková podpora nebola overená ani tvrdená, konzistentné s celou V2.14 sériou |

## 27. Basket readiness decision

**`BASKET_FOUNDATION_READY_WITH_LIMITATIONS`**

Základné bezpečnostné mechanizmy (precision, same-need exclusion, ABSTAIN,
session isolation) sú preukázateľne spoľahlivé pre 5 z 6 auditovaných
use cases. Nie je to plné `READY`, pretože: (a) ramen zostáva
DATA_REQUIRED, (b) pad_thai/tom_kha majú reálne, neopravené ingredient
gaps (palm sugar, arašidy, galangal, citrónová tráva, kaffirové listy),
(c) katalógovo-široké taxonomy pokrytie je stále len 46.5%, (d) všetky
mechanizmy sú slovenčina-only.

## 28. Remaining data/architectural debt

1. **Vysoká priorita**: 7 NO_TAXONOMY_MATCH konceptov s reálnymi
   produktmi bez FamilyRule (dashi, palmový cukor, arašidy, "korenie
   pho", galangal, citrónová tráva, kaffirové listy) - vyžaduje
   samostatnú, plnohodnotnú taxonomy-rozširujúcu sprintu.
2. **Vysoká priorita**: ramen bare-word taxonomy kolízia (instant_noodles
   vs. suché rezance na domácu polievku) - nevyriešená, `use_case_advice`
   pre ramen zostáva zámerne nezaregistrovaný.
3. **Stredná priorita**: multi-jazyková podpora (SK-only mechanizmy
   naprieč celou V2.14 sériou).
4. **Nízka priorita**: `app.cross_sell.roles_for_recipe()`'s vlastná
   architektonická medzera (dôveruje LEN taxonomy-backed konceptom,
   nikdy `RECIPE_CURATED` lexikálnym) zostáva - táto sprinta ju
   zmiernila (2 recovery), nie odstránila.

## 29. V2.14d final status

**`USE_CASE_RECIPE_DATA_QUALITY_PARTIAL`**

## 30. V2.14e readiness

Basket Completion (V2.14e) je odporúčaná ĎALŠIA ÚVAHA, ale nie
bezpodmienečne najbližší krok - vzhľadom na `BASKET_FOUNDATION_READY_WITH_LIMITATIONS`
(nie plné READY) a reálny, priamo zdokumentovaný dátový dlh (Sekcia 28,
položky 1-2), odporúčaný ďalší krok je cielené obohatenie dát
(Sekcia 31), nie priamo Basket Completion.
