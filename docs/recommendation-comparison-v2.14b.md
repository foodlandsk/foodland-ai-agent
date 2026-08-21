# V2.14b — Evidence-Grounded Product Comparison & Recommendation Decision Foundation

Dátum: 2026-08-21. Baseline: `f1d2ccf` (V2.14a), `pytest 1356/1356`, V2.10
fast-mode `34/39`, canary `10/10`. Pokračuje priamo z V2.14a
(`RECOMMENDATION_FOUNDATION_PARTIALLY_READY`) — buduje PRVÚ produkčne
nasadenú, evidence-grounded porovnávaciu schopnosť.

## 1. Súčasné správanie PRED (charakterizácia)

Priamo spustené proti bežiacej aplikácii, 10 reprezentatívnych dopytov
(zadanie Section 7):

| Dopyt | Predtým |
|---|---|
| "Kikkoman alebo Yamasa?" | `product_search`/`fast`, nesúvisiace produkty (ryžový ocot Kikkoman, kimchi základ Kikkoman, sójová omáčka Yamasa) — nulová komparatívna logika |
| "Porovnaj Kikkoman a Yamasa." | Identické — rovnaký fast-path šum |
| "Ktorá z týchto dvoch je lacnejšia?" (bez kontextu) | Existujúca "nemám aktívny zoznam" clarifikácia (nesúvisiaci mechanizmus) |
| "Ktoré balenie sa viac oplatí?" (bez kontextu) | Nesprávne zasiahlo FAQ o platobných metódach (pred-existujúca, nesúvisiaca chyba, nie táto sprinta) |
| "Ktorý produkt je lepší?" | Fast-path šum |
| "Najlepšia ryža" | `CATEGORY_BROWSE`, zoskupený počet podľa subfamily — žiadne falošné "najlepšie" tvrdenie |
| "Najlepšia ryža na sushi" | `USE_CASE_ADVICE` result_set — žiadne explicitné "najlepšie" tvrdenie |
| "Ktorá chutí lepšie?" | Fast-path šum |
| "Je prvý alebo druhý výhodnejší?" (bez aktívneho zoznamu) | **Správne** existujúce "Prepáčte, ktorý presne máte na mysli?" (ordinal-reference fallback, V2.9) |
| "Porovnaj prvý a tretí produkt." (bez zoznamu) | Rovnaká správna clarifikácia |

Kľúčové zistenie: existujúca **ordinálna referencia** infraštruktúra
(`app.session_state.mentions_ordinal_reference`/`resolve_ordinal_reference`)
už správne rieši "žiadny predchádzajúci kontext" prípad — ale iba pre
JEDEN ordinál naraz (dizajnovaná pre "ten druhý" follow-up, nie
"prvý alebo druhý" porovnanie).

## 2. Existujúce primitíva znovupoužité

- `app.recommendation_evidence` (V2.14a) — `EvidenceItem`, `compute_confidence()`, provenance konštanty. **Nulová duplicita.**
- **Vlastný, užší trigger** (`" vs "`, `"verzus"`, `" alebo "` + slovná základňa `"porovna"`) — **NEznovupoužíva** `app.workflow_registry._COMPARISON_MARKERS` doslovne. Reálny nález pri plnom regresnom behu (nie hypotéza): tá nálepka obsahuje aj `"rozdiel"`, čo je bezpečné v `workflow_registry`'s vlastnom kontexte (čisto post-hoc analytická nálepka NAD už nájdenou FAQ odpoveďou), ale ako CAUSAL spúšťač príliš široké — "aký je rozdiel medzi mirin a ryžovým octom?" je bežná informačná/FAQ otázka (vysvetli konceptuálny rozdiel), nie žiadosť vybrať víťaza medzi dvoma kúpiteľnými SKU. Toto rozbilo existujúci `tests/test_session_contamination_v2_13b_1.py` test PRED opravou — `"rozdiel"` bol z triggeru odstránený, permanentný regresný test pridaný (`test_rozdiel_alone_is_not_a_causal_comparison_trigger`).
- `app.session_state.get_recent_presentation()` — rovnaký prístup k naposledy zobrazeným produktom, aký už dôveryhodne používa jedno-ordinálny follow-up handler.
- `app.main.hybrid_cached_search_products()` — na deterministické rozlíšenie textového fragmentu na top-1 produkt (žiadna nová NLU vrstva).
- `app.taxonomy.get_taxonomy()` — `canonical_family`/`confidence` pre kategóriovú kompatibilitu a popisnú evidenciu.
- `app.search.format_product()` — rovnaký tvar produktu, aký vracia zvyšok `/chat`.

**Existujúci `COMPARISON` workflow_id** (`app.workflow_registry`, V2.7)
bol doteraz `migration_status=SHADOW` — nálepka sa priraďovala len keď
`faq_answer_found AND _looks_like_comparison(message)`, nikdy causal
vykonanie. **Tento mechanizmus (v `select_workflow()`) sa touto
sprintou NEMENÍ** — V2.14b pridáva NOVÝ, nezávislý spúšťač
(`app.comparison.looks_like_comparison_request()`), znovupoužívajúci
iba string hodnotu `"COMPARISON"` pre `workflow_id` pole v odpovedi,
nie samotný `select_workflow()` mechanizmus. `app/workflow_registry.py`
nebol touto sprintou vôbec upravený (Section 29 — najmenšia
kompatibilná integrácia, nie kompetujúci router).

## 3. Comparison target resolution

Presne 2 deterministické cesty (Section 8):

1. **Ordinálny pár** — 2+ ordinálne slová v jednej správe ("prvý alebo
   druhý") + `get_recent_presentation(memory)`. Ak oba indexy sú v
   rozsahu a odkazujú na odlišné produkty → vyriešené.
2. **Explicitný pár** — rozdelenie textu na spojkách (`" alebo "`,
   `" vs "`, `" verzus "`, `" a "`) po overení, že správa vyzerá ako
   porovnanie; každý fragment sa vyrieši cez existujúci
   `hybrid_cached_search_products(fragment, limit=1)`.

**Bezpečnostný nález počas implementácie** (nie hypotetický): holé
značky bez kategórie ("Kikkoman alebo Yamasa?") sa nezávisle vyriešili
na "Kimchi základ KIKKOMAN 1180g" vs. "Teriyaki Thick omáčka YAMASA
1100g" — dva úplne odlišné typy produktov, ticho spárované. Pridaná
**kategóriová kompatibilita** (`_same_product_category()`): explicitný
pár sa akceptuje len ak obe strany zdieľajú `canonical_family` (ak
taxonomy pozná oboje) alebo prvý segment `product_type`. Bez tejto
zhody → `None` → **CLARIFY**, nie fabrikovaný pár (Section 8 explicitne
vyžaduje presne toto).

Nevyriešiteľné/nejednoznačné cieľové rozlíšenie teraz vracia REÁLNU
`CLARIFY` odpoveď zákazníkovi (nie tiché prepadnutie do bežnej
kaskády) — presne pre prípady, keď správa OBSAHUJE porovnávací jazyk,
ale nedá sa bezpečne vyriešiť.

## 4. Comparison goal model

Deterministická klasifikácia kľúčovými slovami (Section 9), **žiadny
nový veľký ontológiový systém**: `CHEAPEST`, `BEST_VALUE`,
`LARGEST_PACK`/`SMALLEST_PACK`, `GENERAL_BEST` (predvolené), a
explicitne rozpoznaný `UNSUPPORTED_QUALITATIVE` (chuť, autentickosť,
prémiovosť, obľúbenosť, zdravosť) — smeruje priamo na `ABSTAIN`, nie na
`GENERAL_BEST` s irelevantnou evidenciou (Section 15).

## 5. Porovnateľné dimenzie

| Dimenzia | Zdroj | Pokrytie (V2.14a audit) |
|---|---|---|
| `price_fit` | `effective_price` | 100% |
| `unit_price_fit` | `price / unit_pricing_measure`, LEN pri zhodnej jednotke | 75,4% priamo, viac s title-fallbackom (nepoužitý tu) |
| `size_fit` | `unit_pricing_measure`, LEN pri zhodnej jednotke | 75,4% |
| `brand_fit` | `brand` | 95,7% (popisné, nikdy samostatný víťaz) |
| `product_type_fit` | `taxonomy.canonical_family`, len HIGH tier | 24,8% (popisné) |

**Nepodporené dimenzie** (žiadne dáta): chuť, autentickosť, prémiovosť,
obľúbenosť, zdravosť — vždy `ABSTAIN`.

## 6. Evidence provenance

Znovupoužité z V2.14a bez zmeny: `DATA_DERIVED` (cena, veľkosť,
značka), `INFERRED` (nepoužité v tejto sprinte — žiadna V2.14b
dimenzia si to nevyžiadala), `LLM_JUDGMENT` (nikdy generovaná touto
sprintou — pozri Sekciu 12).

## 7. Reason codes

`price_fit`, `unit_price_fit`, `size_fit`, `brand_fit`,
`product_type_fit` — presne tie, ktoré majú reálne dátové krytie
(Sekcia 5). `flavor_profile_fit`/`authenticity`/`premium_position`/
`popularity` **neboli zavedené** (zadanie Section 12 to explicitne
zakazuje bez skutočnej deterministickej evidencie).

## 8. Recommendation confidence

Znovupoužité `app.recommendation_evidence.compute_confidence()`
bezo zmeny — žiadny nový confidence model. Kritický invariant
(HIGH nikdy z čisto LLM_JUDGMENT) zostáva v platnosti, keďže V2.14b
nikdy negeneruje LLM_JUDGMENT evidenciu vôbec.

## 9. Comparison decision model

`CLEAR_WINNER` / `CONDITIONAL_WINNER` / `TRADE_OFF` /
`NO_MEANINGFUL_DIFFERENCE` / `CLARIFY` / `ABSTAIN`
(`app.comparison.ComparisonDecision`).

### CLEAR_WINNER
Vyžaduje evidenciu relevantnú k skutočnému cieľu zákazníka (Sekcia 15).
**Nález pri implementácii**: pre `GENERAL_BEST` porovnávanie surovej
`effective_price` bez ohľadu na veľkosť balenia by mohlo vyrobiť
zavádzajúceho víťaza (150ml @ 4,17 € vs. 18L @ 50,57 € — samozrejme
lacnejšie v absolútnom vyjadrení, ale nezmyselné porovnanie). Opravené:
`GENERAL_BEST` uprednostňuje **jednotkovú cenu** pred surovou cenou,
kedykoľvek sú veľkosti balenia porovnateľné (rovnaká jednotka); surová
cena sa použije len keď sú veľkosti rovnaké alebo neznáme.

### CONDITIONAL_WINNER
Keď rôzne dimenzie uprednostňujú rôzne produkty bez dominancie — vždy
sprevádzané konkrétnou otázkou ("Je pre Vás dôležitejšia cena, alebo
veľkosť balenia?").

### TRADE_OFF
Rezervovaný stav v kóde (`STATE_TRADE_OFF`); v aktuálnej `GENERAL_BEST`
implementácii `CONDITIONAL_WINNER` pokrýva presne ten istý prípad s
konkrétnejšou otázkou — `TRADE_OFF` zostáva dostupný pre budúce
rozšírenie (napr. keď je príliš veľa konfliktných dimenzií na
jednoduchú otázku).

### NO_MEANINGFUL_DIFFERENCE
Keď je evidencia rovnaká (rovnaká cena, rovnaká veľkosť) — nevymýšľa
rozdiel (Sekcia 18).

### CLARIFY
Vracia sa keď (a) cieľové rozlíšenie zlyhá ALE správa vyzerá ako
porovnanie (Sekcia 3), alebo keď cieľ je nerozpoznaný.

### ABSTAIN
Vracia sa pre `UNSUPPORTED_QUALITATIVE` ciele, chýbajúce cenové dáta,
alebo nekompatibilné/chýbajúce jednotky pri `BEST_VALUE`.

## 10. Ranking vs. recommendation

**Explicitne overené** (Sekcia 21): `app.comparison` nikdy nečíta
žiadne pole súvisiace s vyhľadávacím poradím (`rank`/`position`) —
evidencia pochádza výhradne z `price`/`unit_pricing_measure`/`brand`/
`taxonomy`. Test `test_evidence_functions_never_reference_rank_or_position`
priamo inšpektuje zdrojový kód modulu a potvrdzuje neprítomnosť týchto
referencií. Identické produkty s umelo pridaným `_synthetic_rank` poľom
vždy vrátia `NO_MEANINGFUL_DIFFERENCE`, nikdy víťaza podľa poradia.

## 11. Comparative claim grounding

Klasifikácia (Section 24): `SUPPORTED` (napr. `A.price < B.price` →
"A je lacnejšie"), `SUPPORTED_INFERENCE` (napr. jednotková cena
odvodená z ceny + veľkosti), `UNSUPPORTED` (chuť, autentickosť —
nikdy vygenerované, pretože `GOAL_UNSUPPORTED_QUALITATIVE` smeruje
priamo na `ABSTAIN` skôr, než by sa akákoľvek veta o chuti/
autentickosti vôbec skladala). Žiadne tvrdenie neopúšťa
`compose_comparison_answer()` bez zodpovedajúcej `EvidenceItem`.

## 12. `validate_answer()` audit

`app.grounding.validate_answer()` overuje **len URL a ceny** v LLM
odpovedi — **nekontroluje porovnávacie/kvalitatívne tvrdenia**
(potvrdené priamym čítaním, V2.14a aj znova V2.14b). **Rozhodnutie**:
namiesto rozšírenia `validate_answer()` (čo by vyžadovalo, aby videla
štruktúrovanú `ComparisonDecision` evidenciu, ktorú dnes nemá k
dispozícii) alebo budovania druhého grounding frameworku, V2.14b
**úplne obchádza problém**: `compose_comparison_answer()` nikdy
nevolá LLM, takže neexistuje generovaný text, ktorý by bolo treba
validovať. `validate_answer()` sa touto sprintou nemení a naďalej
chráni len OpenAI-generated cesty (nezmenené).

## 13. LLM override protection

**Dosiahnuté konštrukciou, nie behom** (Sekcia 26). `app.comparison`
neobsahuje ŽIADNU referenciu na `_get_openai_client`/
`_call_openai_with_retry`/`openai` — priamo overené statickou
inšpekciou zdrojového kódu (`test_comparison_module_never_references_openai`,
`test_handler_never_touches_openai`). Neexistuje voľný text, ktorý by
LLM mohol "prepísať" cez `TRADE_OFF`/`ABSTAIN` rozhodnutie, pretože
žiadny LLM nikdy nekomponuje porovnávaciu odpoveď. Testy priamo
overujú, že `CONDITIONAL_WINNER`/`ABSTAIN` odpovede neobsahujú frázy
ako "celkovo by som vybrala"/"jednoznačne najlepší"/"odporúčam".

## 14. Customer-facing integration

**Rozhodnutie: integrované.** Nový, samostatný, skorý blok v
`_chat_impl()` (`app/main.py`, po allergen-safety/FAQ/random-recipe/
reset, pred recipe detekciou) volajúci `app.workflow_executor.execute_comparison()`
— presne ten istý vzor ako `missing_composition`/`faq`/`random_recipe`/
`reset`/`category_discovery`/`recipe` (V2.13d/e). Vracia `None` keď
správa vôbec nevyzerá ako porovnanie (Section 8/19) — každý iný
existujúci branch zostáva úplne nedotknutý pre akýkoľvek
neporovnávací ťah. Diff: `app/main.py` +26 riadkov (1 import + 1 nový
early-return blok), `git diff --check` čistý.

**Prečo je toto bezpečné integrovať teraz** (Section 28 gate, splnené
všetkých 9 podmienok A-I): úzky, prísne testovaný spúšťač (porovnávací
jazyk MUSÍ byť prítomný, cieľové rozlíšenie MUSÍ uspieť na presne 2
odlišné, kategóriovo-kompatibilné produkty) prirodzene minimalizuje
kolízne riziko s existujúcim routovaním — potvrdené priamym testom
(`sojova omacka bez soje alebo laktozy, ktora je bezpecnejsia?`
zostáva `allergen_safety`, nie porovnanie, vďaka umiestneniu PO
bezpečnostnej kontrole).

## 15. Workflow / routing

Nová vetva sa NEROZHODUJE cez `app.turn_resolver`/`app.workflow_resolver`
(tie zostávajú presne pri 4 hodnotách: `RESULTSET_CONTINUATION`,
`ALLERGEN_SAFETY`, `RELATED_PRODUCTS`, `LEGACY_FALLBACK`) — je to nový
samostatný sub-prípad `LEGACY_FALLBACK`-triedy skorých vetiev, presne
ako 6 vetiev, ktoré V2.13d migrovalo. `app.workflow_registry` sa
nemenil (Sekcia 2).

## 16. ResultSet continuity

Overené: Show More (`result_set_continuation`), veľkostné zúženie
(5kg), topic switch — všetko nezmenené. `execute_comparison()`
**nikdy nezapisuje** `active_result_set_id`/`recent_presentation_ids`
— porovnanie nie je stránkovaný result set, takže nekonkuruje
existujúcemu vlastníkovi tohto stavu (Section 32 — "ResultSet
ownership must remain exactly once").

## 17. Session safety

Overené: porovnanie → nesúvisiaci dopyt vracia normálny
`product_search`/`result_set`, žiadna "lepkavosť" porovnávacieho
stavu (žiadny nový memory kľúč sa nezavádza na trvalé sledovanie
"aktívneho porovnania").

## 18. Allergen safety

**Kriticky overené**: "sójová omáčka bez sóje alebo laktózy, ktorá je
bezpečnejšia?" (obsahuje " alebo ", teoreticky by mohlo spustiť
porovnávaciu detekciu) zostáva `allergen_safety`, 0 produktov — vďaka
umiestneniu porovnávacej vetvy AŽ PO existujúcej allergen-safety
kontrole v `_chat_impl()`'s kaskáde (Section 31).

## rt0004 / rt0010 / rt0011 / rt0013

Všetky nezmenené: rt0004 `related_products`, rt0010 `allergen_safety`
+ 0 produktov, rt0011 `product_search` na oboch ťahoch. rt0013 zostáva
`PENDING_SEMANTIC_PRODUCT_DECISION`, nedotknuté.

## Response contract

Žiadna regresia na existujúcich vetvách (V2.13g `REQUIRED_ALWAYS`:
`answer`/`products`/`intent`/`memory` zachované). Nová vetva pridáva
`response_mode="comparison"`, `workflow_id="COMPARISON"`,
`comparison_decision`/`comparison_goal`/`comparison_confidence` ako
aditívne, spätne kompatibilné polia (Section 46).

## Observability

`log_question()`'s existujúci `subject` parameter nesie
`comparison_decision` state (napr. `"CLEAR_WINNER"`) — žiadny nový
telemetrický systém, žiadne dodatočné logovanie citlivého textu
(Section 42/43).

## Execution context

`execute_comparison()` prijíma `emit_customer_analytics` explicitne a
gatuje svoje vlastné `log_question()` volanie presne ako všetkých
9 existujúcich `workflow_executor` handlerov — žiadny nový výskyt
V2.13d's cross-module shadowing bugu.

## Performance / Search call count / LLM call count

Overené priamo: presne 2 volania `hybrid_cached_search_products` (po
jednom na fragment) pre explicitný pár, 0 pre ordinálny pár (číta len
už uloženú `recent_presentation_ids`). **0 OpenAI klientských volaní**
— priamo overené mockom (`_get_openai_client` nikdy nezavolaný počas
celého porovnávacieho ťahu).

## Testy

`tests/test_comparison_v2_14b.py` (45 testov): Cases A-L z mandátnej
rozhodovacej matice, claim grounding matica, ranking≠recommendation
invariant, unit-price bezpečnosť (g vs. ml nikdy porovnané),
`execute_comparison()` handler testy (CLARIFY, plný kontrakt, no-OpenAI
statická inšpekcia), reálne katalógové dáta (nie len syntetické),
permanentný regresný zámok pre nález "rozdiel" (Sekcia 2 vyššie) —
priamo pomenúva `tests/test_session_contamination_v2_13b_1.py`'s
existujúci test, ktorý túto reálnu chybu prvý raz odhalil pri plnom
regresnom behu.

## Známe obmedzenia

- Explicitný pár vyžaduje, aby OBE fragmenty patrili do rovnakej
  kategórie/rodiny — inak CLARIFY namiesto skutočného porovnania (napr.
  "Kikkoman alebo Yamasa?" bez kategórie).
- `TRADE_OFF` stav je v kóde definovaný, ale `GENERAL_BEST` logika ho
  aktuálne nikdy nevracia (vždy `CONDITIONAL_WINNER` namiesto neho) —
  budúce rozšírenie môže rozlíšiť tieto dva stavy jemnejšie.
- Jednotková cena porovnáva len rovnaké jednotky (g s g, ml s ml) —
  žiadna konverzia kg↔g/l↔ml (nepotrebná: reálne dáta používajú len
  "g"/"ml", V2.14a audit).
- Multi-jazyčná podpora obmedzená na SK/EN šablóny (Section 37 -
  žiadna nová 7-jazyková ontológia).

## Dátové obmedzenia (z V2.14a auditu, nezmenené)

Taxonomy 34,4% pokrytie, dietárne dáta 0% štruktúrované, `use_case`
vocabulary = 1 hodnota (nedotknuté touto sprintou).

## Architecture metrics

`competing_primary_router_count=0`, `legacy_primary_execution_branch_count=1`
(commerce pipeline, nezmenené), `resolver_output_without_execution_path=0`,
`resolver_output_without_canonical_executor=0`, `duplicate_executor_count=0`,
`resolved_executed_mismatch_count=0`. `app.workflow_registry`'s
`COMPARISON` kontrakt zostáva formálne `SHADOW` (jeho vlastný FAQ-gated
mechanizmus sa nezmenil) — V2.14b's nová vykonávacia cesta je
nezávislá, dokumentovaná tu, nie retroaktívna zmena V2.7 kontraktu.

## Final release decision

# **`COMPARISON_INTELLIGENCE_LIVE`**

Všetkých 9 podmienok Section 28 splnených s dôkazom (Sekcia 14 vyššie).

## V2.14c readiness

Comparison mechanika je zdravá (deterministická, testovaná,
produkčne nasadená). Hlavné zostávajúce obmedzenie je **use-case
evidence coverage** (1 hodnota: "sushi") — presne podmienka, ktorú
zadanie Section 60 uvádza ako odôvodnenie pre V2.14c.

## Odporúčaný ďalší krok

**V2.14c — Use-Case Intelligence Expansion**: rozšíriť
`app.cross_sell._USE_CASE_TO_SOURCE_KEYS` nad rámec "sushi" (pho,
curry, ramen, Pad Thai, biryani), kopírujúc `app.recipe_graph`'s
existujúci 47-jedálový vzor. V2.14c sa nezačína automaticky.
