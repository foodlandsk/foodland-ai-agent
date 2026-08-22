# V2.14e — Evidence-Grounded Basket Completion & Goal-Oriented Shopping Intelligence

Dátum: 2026-08-22. Baseline: `284f07f` (V2.14d + korekcia), pytest 1470/1470,
V2.10 fast-mode 34/39, canary 10/10.

## 1. Repository reality check

HEAD == `origin/main` == `284f07f` pred zmenami, žiadny drift, čistý working
tree (okrem predexistujúceho `.claude/`). Zadanie explicitne očakávalo túto
presnú SHA — zhoda potvrdená priamo (`git rev-parse HEAD`).

## 2. Existujúce primitíva — audit (PRED implementáciou)

Najdôležitejší nález celej sprinty: **`app.recipe_shopping.build_recipe_shopping_plan()`
(V2.8) už implementuje presne to, čo toto zadanie požaduje** — per-rolu
status (`AVAILABLE`/`ALREADY_SATISFIED`/`NOT_AVAILABLE`/`OPTIONAL`/`UNKNOWN_MAPPING`),
coverage metriky, `app.session_state.get_selected_ingredient_products()`/
`mark_ingredient_selected()` pre "already covered" stav, a je **už živo
nasadené pre pad_thai/tom_kha** (dosiahnuté cez ich bare `RECIPE_INTENT_MARKERS`
záznam + `wants_recipe_products()`). Priamo overené naživo PRED akoukoľvek
zmenou:

| Dopyt | Pred V2.14e |
|---|---|
| "co potrebujem na pad thai" | `recipe_to_products`/`RECIPE_SHOPPING`, plný plán |
| "co potrebujem na tom kha gai" | `recipe_to_products`/`RECIPE_SHOPPING`, plný plán |
| "co potrebujem na sushi" | `related_products` (žiadny plán - sushi nemá `recipe_graph` záznam) |
| "co potrebujem na pho" | `related_products` (žiadny plán - pho nemá bare recipe marker) |
| "co potrebujem na kari" | `related_products` (rovnaká medzera) |
| "co potrebujem na ramen" | `related_products` (bezpečné, žiadny fake basket) |

**Skutočná medzera** (nie "chýba všetko"): sushi/pho/kari nemajú prístup k
tejto už existujúcej, kvalitnej mechanike, pretože nemajú bare
`RECIPE_INTENT_MARKERS` záznam. V2.14e uzatvára presne TÚTO medzeru, nie
nanovo stavia Basket Completion od nuly.

Ostatné audity:
- `app.use_case_advice` (V2.14c): odpovedá na PRESNE JEDNU rolu na ťah,
  zámerne (nikdy basket).
- `app.cross_sell.roles_for_recipe()`/`roles_for_use_case()` (V2.6):
  taxonomy-podložený zoznam rolí per jedlo, už produkčne používaný pre
  cross-sell. **Toto sa stalo hlavným zdrojom "required roles" pre V2.14e**
  (Sekcia 5 nižšie).
- `app.comparison` (V2.14b): rieši "ktorý z DVOCH UŽ VYRIEŠENÝCH produktov je
  lepší" - nie "aký produkt vôbec sedí na túto rolu". Nepoužité priamo -
  V2.14e namiesto toho znovupoužíva rovnaký deterministický
  `(confidence != HIGH, cena)` tie-break, aký už `app.use_case_advice.generate_candidates()`
  používa.
- `app.turn_resolver.resolve_action_target_signal()` (V2.13b): rieši INÝ
  konflikt (`special_subject` vs `related_subject`), jeho `TurnAnalysis`
  nemá pole pre basket/use-case cieľ - **nepoužité priamo** (rovnaká
  klasifikácia `INSUFFICIENT_FOR_THIS_CLASS` ako vo V2.14d pre Pad
  Thai/Tom Kha routing).

## 3. V2.14d findings re-verification

| Tvrdenie V2.14d | Stav |
|---|---|
| Taxonomy coverage ~46.5% | **CONFIRMED** (996/2140 non-UNKNOWN) |
| RECIPE_COMPLETION baseline 21/28 = 75.0% | **CONFIRMED** (nezmenené, V2.14e nezasahuje do taxonomy) |
| dashi/palmový cukor/arašidy/galangal/citrónová tráva/kaffirové listy/"korenie pho" bez taxonomy | **CONFIRMED**, znovu overené priamo |
| Pad Thai/Tom Kha dosiahnuteľné cez generickú precedenciu | **CONFIRMED** |
| Ramen zostáva DATA_REQUIRED | **CONFIRMED** |
| `"miska na ramen"` query-side limit | **CONFIRMED**, nedotknuté |

## 4. Basket V1 eligible use cases

```python
BASKET_V1_ELIGIBLE_USE_CASES = ("sushi", "pho", "pad_thai", "tom_kha", "kari")
```

Explicitná registrácia (`app/basket_completion.py`), zámerne NIE bare alias
na `app.use_case_advice.LIVE_USE_CASES` (hoci sa dnes zhodujú) - budúca
nová `LIVE_USE_CASE` položka nemusí byť automaticky basket-ready.

## 5. Ramen exclusion

**Štrukturálne, nie špeciálny prípad.** Dve nezávislé brány: (1) "ramen"
nie je v `app.use_case_advice.LIVE_USE_CASES`, takže `resolve_use_case()`
nikdy nevráti "ramen"; (2) `BASKET_V1_ELIGIBLE_USE_CASES` ho ani neobsahuje.
Permanentný regresný test (`TestCaseF_RamenExcluded`, 4 testy) dokazuje
priamo na `decide_basket_completion()`, že žiadna z otestovaných formulácií
("čo potrebujem na ramen", "doplň mi košík na ramen", "čo mi chýba na
ramen") nikdy nevstúpi do Basket V1 - živo overené aj cez celý `/chat`.

## 6. Existing primitives audit → Basket Completion architecture

```
resolve_use_case(message)            <- app.use_case_advice (V2.14c), znovupoužité
        |
required_roles_for_use_case(use_case)
        |-- sushi:  app.cross_sell.roles_for_use_case("sushi")   (V2.6)
        |-- ostatné: app.cross_sell.roles_for_recipe(dish_key)   (V2.6)
        |
generate_role_candidates(concept_id) <- app.taxonomy.product_taxonomy_index,
        |                                concept_id-presná zhoda, HIGH/MEDIUM only
        |
already_covered? <- app.session_state.get_selected_ingredient_products()
        |            (V2.9, existujúci stav) ALEBO self-declared v tej istej
        |            správe (parse_structured_query, V2.14d-opravená cesta)
        |
BasketRole(status=RESOLVED_PRODUCT|ALREADY_COVERED|NO_CATALOG_PRODUCT)
```

Nový modul `app/basket_completion.py` odôvodnený rovnakou latkou ako
`app.use_case_advice` (V2.14c Section 39): žiadny existujúci modul
nevlastní "vyrieš VŠETKY roly pre jedlo naraz do jednej štruktúry s
explicitným statusom per rola" naprieč všetkými 5 use cases naraz (sushi
nemá `recipe_graph` záznam vôbec).

## 7. Role model

`BasketRole(concept_id, display_label_sk, status, recommended_product_id,
alternative_product_ids, confidence)`. Status vokabulár (Section 8):
`RESOLVED_PRODUCT`, `ALREADY_COVERED`, `NO_CATALOG_PRODUCT`, `AMBIGUOUS`
(definovaný, v V1 nedosiahnuteľný - rovnaký precedens ako `CLARIFY` v
`app.use_case_advice`). `UNRESOLVED_ROLE` sa NEPOUŽÍVA ako rola (žiadny
concept_id existuje pre tieto koncepty) - namiesto toho samostatný
`unresolved_concepts: tuple[str, ...]` zoznam raw textu (Section 30).

## 8. Already-covered logic

Dva nezávislé zdroje, OBOJE existujúce: (1) `app.session_state.get_selected_ingredient_products(memory)`
- rovnaký stav, aký pad_thai/tom_kha's existujúci mechanizmus už používa
(konzistencia naprieč oboma cestami); (2) self-deklarácia v TEJ ISTEJ
správe cez `parse_structured_query()` (živo overené: "mám ryžové rezance,
čo ešte potrebujem na pho?" → `rice_noodles` rola = `ALREADY_COVERED`,
ostatné 3 role `RESOLVED_PRODUCT`). Žiadny nový perzistentný stav.

## 9. Role deduplication

Štrukturálne zaručené: required-role zoznam je vždy PRESNE 1 záznam per
concept_id (zdroj `roles_for_recipe()`/`roles_for_use_case()` už
deduplikuje). Viacero kandidátov na tú istú rolu sa nikdy nepočíta ako
viacero required rolí - top kandidát je `recommended_product_id`, zvyšok
`alternative_product_ids` (Section 18).

## 10. Evidence model

Znovupoužité z `app.recommendation_evidence` (V2.14a) bezo zmeny -
`EvidenceItem(reason_code="product_type_fit", provenance=DATA_DERIVED,
source="app.taxonomy", strength=0.7)` → `compute_confidence()`. Žiadny
nový confidence systém.

## 11. V2.14a / V2.14b / V2.14c / V2.14d integrácia

- **V2.14a**: evidence/confidence kontrakt znovupoužitý bezo zmeny.
- **V2.14b**: `app/comparison.py` sa nemenil - namiesto priameho volania
  znovupoužitý rovnaký deterministický tie-break vzor, aký
  `app.use_case_advice` už zaviedol.
- **V2.14c**: `resolve_use_case()`/`is_companion_request()` znovupoužité
  priamo (import), žiadna duplicitná alias tabuľka.
- **V2.14d**: `app.taxonomy`/RECIPE_COMPLETION opravy (banh pho, kari
  pasta, tableware) sa prejavujú automaticky (rovnaký `product_taxonomy_index`),
  nedotknuté touto sprintou.

## 12. Partial basket policy

`fully_resolved = True` LEN keď KAŽDÁ required rola je
`RESOLVED_PRODUCT`/`ALREADY_COVERED` A `unresolved_concepts` je prázdny.
Pho preto NIKDY nevráti `fully_resolved=True` (má "korenie pho" bez
taxonomy) - overené priamo testom.

## 13. No-catalog / unresolved / ambiguous cases

- `NO_CATALOG_PRODUCT`: rola má concept_id, ale 0 kandidátov v katalógu
  (v praxi nedosiahnuté dnešnými datami, ale reálny, testovaný kód).
- `unresolved_concepts`: koncepty BEZ taxonomy vôbec (dashi, palmový
  cukor, arašidy, galangal, citrónová tráva, kaffirové listy, "korenie
  pho") - znovu odvodené naživo z `RECIPE_SHOPPING_CORE_QUERIES` cez
  `parse_structured_query()`, NIE hardcoded snapshot.
- `AMBIGUOUS`: definovaný, nedosiahnutý (Section 8).

## 14. Coverage vs correctness

Coverage formula (Section 28 zadania):

```
coverage = (RESOLVED_PRODUCT_count + ALREADY_COVERED_count) / total_required_roles
```

Nepočíta optional/cross-sell/ambiguous. **0 nových false positives** -
overené: (a) plný V2.10 eval 34/39 identický, (b) 47 nových testov, (c)
`concept_id`-presná zhoda (silnejšia než family/subfamily, žiadny
lexical_filter workaround).

## 15. Per-use-case quality matrix

| use_case | required roles | resolved | unresolved concepts | coverage | status |
|---|---|---|---|---|---|
| sushi | 4 | 4 | 0 | **100%** | **LIVE** (nový, V2.14e) |
| pho | 4 | 4 | 1 (korenie pho) | **80%** | **LIVE** (nový, V2.14e) |
| kari | 4 | 4 | 0 | **100%** | **LIVE** (nový, V2.14e) |
| pad_thai | 3 | 3 | 2 (palmový cukor, arašidy) | **60%** | **LIVE** (existujúci V2.8/V2.9 mechanizmus, nedotknutý) |
| tom_kha | 2 | 2 | 3 (galangal, citrónová tráva, kaffirové listy) | **40%** | **LIVE** (existujúci V2.8/V2.9 mechanizmus, nedotknutý) |
| ramen | N/A | N/A | N/A | N/A | **DATA_REQUIRED / EXCLUDED_FROM_BASKET_V1** |

## 16. Routing precedence

Nová vetva v `_chat_impl()`, pozicovaná PO `use_case_advice` (Section 22:
jednorolová otázka zostáva odlišná od basket požiadavky) a PRED recipe
detekciou. `decide_basket_completion()` sa vzdáva (`None`), keď
`recipe_subject` je už nastavené - pad_thai/tom_kha teda VŽDY používajú
existujúcu, nedotknutú cestu. Živo overená 16-bodová matica (Section 22
zadania) - 0 regresií.

**2 reálne regresie nájdené a opravené počas implementácie** (nie
hypotézy):
1. `regbug_rt0026` ("ramen na Pho polievku máte ingrediencie?") - bare
   "ingredien" marker (súčasť `wants_recipe_products()`) bol príliš
   široký pre TOTO novo pridané, silnejšie tvrdenie ("tu je celý váš
   basket"). Opravené: basket-špecifický, užší marker set (`co
   potrebujem`/`co treba`/`co mi chyba`/`co chyba`/`co ešte
   ...`/`dopĺň`), nie plné znovupoužitie `wants_recipe_products()`.
2. "nákupný zoznam na sushi" kolidoval s existujúcim, obsahovo
   overeným `sushi_shopping_core_products()` mechanizmom
   (`test_sushi_shopping_list_uses_buyable_core_items_not_water`).
   Opravené: `"nakupny zoznam"`/`"do kosika"` zámerne vylúčené z basket
   markerov - zákazník má aj tak plný prístup cez `"čo potrebujem"`.

## 17. Allergen safety

Nedotknuté - `allergen_safety` vetva beží PRED touto (aj pred use_case_advice
aj comparison). "sójová omáčka bez sóje na pho" → `allergen_safety`,
overené priamo.

## 18. Session safety / ResultSet continuity / Recipe controls

Hard topic switch, cross-session izolácia, opakovaná rovnaká požiadavka
(determinizmus) - všetko priamo otestované a potvrdené. "recept na X"
zostáva `recipe`, nedotknuté.

## 19. rt0004 / rt0010 / rt0011 / rt0013

Všetky tri live-overené a trvalo zamknuté testami, nezmenené. rt0013
nedotknuté, zostáva `PENDING_SEMANTIC_PRODUCT_DECISION`.

## 20. Retrieval / ranking / taxonomy impact

Žiadna zmena. `generate_role_candidates()` číta ten istý
`product_taxonomy_index`, žiadne nové pravidlo, žiadna nová ranking
váha.

## 21. LLM call count / Search call count / Performance

**0 nových LLM volaní** (statický test `TestNoNewLlmCall`). Presne 1
lineárny prechod cez `products` per rolu (rovnaký vzor ako
`app.use_case_advice.generate_candidates()`, už akceptovaný). Nameraná
latencia basket_completion požiadavky: **~7.5ms priemer** (10 opakovaní),
zanedbateľné voči celkovej `/chat` latencii.

## 22. Observability / Privacy

Response obsahuje kompaktné polia (`basket_use_case`, `basket_coverage`,
`basket_fully_resolved`, `basket_roles`, `basket_unresolved_concepts`) -
žiadny nový paralelný analytics systém, `emit_customer_analytics`
rešpektované rovnako ako všetky ostatné V2.14 executory. Žiadne nové PII
uloženie.

## 23. Tests

`tests/test_basket_completion_v2_14e.py` (47 testov) - 16 charakterizačných
prípadov (A-P zo Section 31), 2 permanentné regresné zámky, unit testy
pre role/kandidátov/action-detekciu, response-contract, no-LLM statický
dôkaz, honesty (no-fake-completion) testy.

## 24. Full test suite

**1517/1517** (1470 baseline + 47 nových), 0 regresií po oprave.

## 25. V2.10 evaluation

Fast-mode **34/39 nezmenené** (identické error buckety) - po oprave 1
kritickej regresie (`regbug_rt0026`) počas implementácie.

## 26. Search quality canary

**10/10**, no anomalies.

## 27. Audits

Consistency 0 kolízií, trust 0 nálezov, deployment check passed.

## 28. Final release status

**Global**: `BASKET_COMPLETION_LIVE_PARTIAL`

**Basket readiness** (samostatné od global statusu): 5 z 5
`BASKET_V1_ELIGIBLE_USE_CASES` sú LIVE (2 nové cez tento modul + 2
existujúce, nedotknuté + implicitne sushi počítané v "2 nové"), ramen
ostáva `DATA_REQUIRED`/`EXCLUDED_FROM_BASKET_V1`. Heterogénna kvalita
(40-100% coverage) je explicitne akceptovaná - žiadny fake "100%
complete basket" tam, kde reálna dátová medzera existuje.

## 29. Remaining debt

1. Rovnaký dátový dlh ako V2.14d (7 NO_TAXONOMY_MATCH konceptov, ramen
   bare-word kolízia, `structured_search`'s tableware-signal limit) -
   nedotknuté, nezhoršené.
2. Self-deklarácia v TEJ ISTEJ správe ("mám X, čo ešte...") funguje LEN
   pre sushi/pho/kari (tento modul) - pad_thai/tom_kha's existujúci
   `app.recipe_shopping` mechanizmus podporuje explicitnú voľbu len ako
   FOLLOW-UP (ordinálna referencia), nie v prvej správe. Zdokumentované,
   nie opravené (mimo rozsahu - vyžadovalo by zásah do V2.8/V2.9 kódu).
3. Multi-jazyková podpora zostáva SK-only (konzistentné s celou V2.14
   sériou).
4. rt0013 nedotknuté.

## 30. V2.14f readiness

Vzhľadom na `BASKET_COMPLETION_LIVE_PARTIAL` (nie plné LIVE naprieč
100% coverage) a jasne zdokumentovaný, ohraničený dátový dlh, odporúčaný
ďalší krok je cielené dátové obohatenie (rovnaké položky ako V2.14d
Section 28) PRED akýmkoľvek V2.14f rozšírením (napr. cart mutation,
viacjazyčnosť, alebo self-deklarácia pre pad_thai/tom_kha). V2.14f sa
nezačína automaticky.
