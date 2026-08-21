# V2.14a — Recommendation Intelligence Foundation, Evidence Audit & Confidence Contract

Dátum: 2026-08-21. Baseline: `3adcd68` (V2.13g), `pytest 1332/1332`,
V2.10 fast-mode `34/39`, canary `10/10`. **Audit-first sprint** — cieľom
nie je nový recommendation engine, ale zistiť, čo Foodland už reálne
má, čo dáta reálne unesú, a definovať bezpečný confidence kontrakt.
Rozhodnutie o implementácii je založené na dôkaze, nie na predpoklade.

## 1. Existujúci inventár schopností

Priamo prečítané a overené (nie prevzaté zo starších dokumentov):

| Modul | Čo reálne robí | Klasifikácia |
|---|---|---|
| `app.cross_sell` | Role-first candidate generation, same-need exclusion cez `canonical_subfamily` (`_same_primary_need()`), deterministické poradie (`_SOURCE_PRIORITY`), deterministický `reason_code` z `FAMILY_DEFINITIONS_BY_ID.display_label` (žiadny LLM) | **EXISTING_REUSABLE** — kompletačná logika, NIE best-choice |
| `app.ranking_features.explain_candidates()` | Deterministický rozklad skóre na `l1_confidence/l2_explicit_hits/l3_availability/l4_relevance` + soft multipliers, znovupoužíva presne tie isté funkcie ako `app.ranking` | **EXISTING_NEEDS_EXTENSION** — solídne, ale len `scripts/ranking_cli.py` (dev-only), nikdy nedosiahne `/chat` |
| `app.recipe_graph` | 47 kurátorovaných jedál → 74 ingredient-role konceptov (27 taxonomy-backed, 47 lexicky kurátorovaných) → produkty; presne 1 substitučná hrana (fish_sauce→soy_sauce, vegan) | **EXISTING_NEEDS_EXTENSION** — deterministické, ale úzko vymedzené |
| `app.taxonomy` | `canonical_family`/`canonical_subfamily` + confidence tiers HIGH/MEDIUM/LOW/UNKNOWN, kategória-cesta vs. iba-názov rozlíšenie | **EXISTING_NEEDS_EXTENSION** — solídny model, pokrytie limitované (Sekcia 3) |
| `app.structured_search`/`app.retrieval` | `STRUCTURED_EXACT/FILTERED/BROAD/LEGACY_FALLBACK` režimy, tvrdé (nie skórované) obmedzenie podľa family/subfamily/attributes/dietary | **EXISTING_REUSABLE** |
| `app.workflow_registry` | `COMPARISON` a `USE_CASE_ADVICE` **UŽ EXISTUJÚ** ako pomenované `workflow_id` (V2.7), obidva `migration_status=SHADOW` — nálepka pre analytiku, žiadna reálna vykonávacia logika | `COMPARISON`: **NEW_CAPABILITY_REQUIRED** (nálepka existuje, mechanizmus nie); `USE_CASE_ADVICE`: **EXISTING_NEEDS_EXTENSION** (skutočne funguje, ale len pre 1 use_case hodnotu — pozri Sekciu 4) |
| `app.grounding.validate_answer()` | Overuje URL a ceny v LLM odpovedi | **EXISTING_REUSABLE**, ale **nekontroluje porovnávacie/kvalitatívne tvrdenia** (Sekcia 11) |
| `app.main.recommendation_group/recommendation_reason` | Paralelný, menej prísny keyword-bucket klasifikátor (nie `canonical_subfamily`-aware) | **EXISTING_NEEDS_EXTENSION** / kandidát na budúce zjednotenie s taxonomy |
| Goal-classification vrstva (recommend vs. find vs. compare vs. alternative) | `product_comparison` je deklarovaný v `app.intent.PRIMARY_INTENTS`, ale **žiadny detektor ho nikdy nevytvára** (potvrdené grepom) | **NEW_CAPABILITY_REQUIRED** |

**Kľúčový nález**: `app.workflow_registry` už v roku V2.7 **explicitne predpokladal** potrebu `COMPARISON` (aj `USE_CASE_ADVICE`) workflow — meno a kontrakt (`WorkflowContract`) existuje, ale reálne vykonanie bolo vedome odložené (`SHADOW`, "re-platforming ... exactly the one-shot rewrite the spec forbids"). V2.14 teda **nezačína od nuly** — vypĺňa už pomenované, ale prázdne miesto.

## 2. Cross-sell audit (detail)

`should_cross_sell()` (`app/cross_sell.py`) má DVE reálne, deterministické cesty ku kontextovej evidencii:
- **`RECIPE_COMPLETION`**: `related_subject` je jedno zo 47 kurátorovaných jedál → role z `_RECIPE_ROLE_INDEX`.
- **`USE_CASE_COMPLETION`**: `structured_query.attributes["use_case"]` je nastavené → role z `_USE_CASE_ROLE_INDEX`.

`_USE_CASE_TO_SOURCE_KEYS` (jediný zdroj `USE_CASE_ROLE_INDEX`) obsahuje **presne JEDNU hodnotu**: `{"sushi": ("sushi_rice", "gluten_free_sushi", "sushi_condiments")}`. To znamená: `USE_CASE_ADVICE`/`USE_CASE_COMPLETION` mechanizmus JE reálny a deterministický, ale dnes pokrýva **len sushi**. Žiadny iný use case (pho, curry, ramen, biryani, Pad Thai...) nemá zodpovedajúci vstup — potvrdené priamo v kóde, nie predpokladané.

## 3. Ranking features / explainability audit

`RankingFeatures.explain_candidates()` je matematicky solídny (rovnaké funkcie ako produkčný `app.ranking.rank_candidates()`), ale **nikdy nie je volaný z `/chat`** — jediní konzumenti sú `scripts/ranking_cli.py` a `tests/test_ranking_profile_wiring.py`. Toto je najbližšia existujúca vec k "prečo je produkt A nad produktom B", ale je to dev/ops nástroj, nie zákaznícka schopnosť.

## 4. Recipe graph audit

Živé štatistiky (`app.main.recipe_graph_index.stats`, spustené priamo):

```
recipe_count=53 dish_count=47 ingredient_concept_count=74
ingredient_concept_taxonomy_backed=27 ingredient_concept_recipe_curated=47
ingredient_product_mapping_count=70 unresolved_ingredient_concept_count=4
reverse_product_to_dish_count=15 substitution_edge_count=1 build_issue_count=0
```

Recipe graph JE deterministický most RECIPE→ROLE→PRODUCT, ale úzko
vymedzený: 47 jedál, 74 konceptov (63,5% z nich len lexicky kurátorovaných,
nie taxonomy-overených), spätná väzba produkt→recept len pre 15 produktov
(0,7% katalógu), substitučný graf má **presne 1 hranu**.

## 5. Taxonomy audit

Živo overené (`build_taxonomy_index`, zhoduje sa s produkčným štartovacím logom):

```
2140 produktov: HIGH=531 (24,8%) MEDIUM=197 (9,2%) LOW=8 (0,4%) UNKNOWN=1404 (65,6%)
```

- **HIGH** = zhoda cez skutočnú kategóriovú cestu Foodlandu (`product_type`) — štrukturálny dôkaz.
- **MEDIUM/LOW** = len textová zhoda v názve, degradované o 1-2 úrovne.
- **UNKNOWN** (65,6% katalógu) = žiadne family/subfamily tvrdenie možné vôbec.

**Dôsledok**: akékoľvek "best choice"/"use-case fit" tvrdenie generalizovateľné na "celý katalóg" má reálne dátové krytie len pre ~34% produktov.

## 6. Reálny audit katalógových dát

Živo namerané (`data/products.json`, 2140 produktov):

| Pole | Pokrytie | Poznámka |
|---|---|---|
| `price` | 100% | `sale_price` vždy striktne < `price` (1012/1012, 0 anomálií) |
| `sale_price` | 47,3% | bezpečné pre "akciová cena" tvrdenia |
| `brand` | 95,7% | ~6,4% hodnôt sú právnické/dovozné mená, nie spotrebiteľská značka |
| `gtin` | 85,1% | identita/de-dup, nie odporúčací obsah |
| `unit_pricing_measure` (veľkosť balenia) | 75,4% priamo štruktúrované, +3,6pp title-regex fallback | zvyšných ~21% nemá parsovateľnú veľkosť vôbec |
| `description` | 100% (1 prázdny) | voľný text, nie atribút-tagovaný |
| **dietárny atribút** | **0% štruktúrované pole neexistuje** | jediný reálny zdroj: `Products_AI.Atribúty`, 52/2140 = **2,4% katalógu** |
| ingrediencie/zloženie | ~1,2% (voľný text) | nepoužiteľné ako dôkaz |
| krajina pôvodu | ~0,05% (voľný text) | nepoužiteľné ako dôkaz |
| `Recipes` (55 CMS záznamov) | 0 ingrediencií/množstiev | len kuchyňa + lokalizované URL, žiadna surová dátová hodnota naviac |

## 7. Súčasné recommendation-štýlové správanie (charakterizácia)

Priamo spustené proti bežiacej aplikácii (bez zmeny správania):

| Dopyt | intent | response_mode | workflow_id | Pozorovanie |
|---|---|---|---|---|
| "Akú jazmínovú ryžu odporúčaš?" | `related_products` | `fallback` | — | Generický kurátorovaný "related products" bundle, nie evidence-based "best" |
| "Ktorá ryža je najlepšia na sushi?" | `product_search` | `result_set` | `USE_CASE_ADVICE` | `USE_CASE_COMPLETION` skutočne zasiahol (jediný fungujúci use case), ale odpoveď je plochý kategóriový výpis, žiadne explicitné "najlepšie" tvrdenie |
| "Akú rybaciu omáčku odporúčaš na pho?" | `related_products` | `fallback` | — | Rovnaký generický bundle vzor |
| "Ktorá sójová omáčka je najlepšia na sushi?" | `product_search` | `result_set` | `PRODUCT_LOOKUP` | 56 produktov v kategórii, ŽIADNE sushi-špecifické zúženie napriek otázke |
| **"Kikkoman alebo Yamasa?"** | `product_search` | `fast` | `None` | **Porovnanie úplne neobslúžené** — vrátil zmiešané, nesúvisiace produkty (ryžový ocot Kikkoman + kimchi základ Kikkoman + sójová omáčka Yamasa), nulová komparatívna logika |
| "Odporuč mi dobré rezance na Pad Thai." | `recipe` | — | `RECIPE_SHOPPING` | Recipe stavový automat, nezmenené |
| "Čo mám kúpiť na Tom Kha Gai?" | `recipe_to_products` | — | `RECIPE_SHOPPING` | Recipe stavový automat, nezmenené |
| "Chcem lacnejšiu alternatívu." (bez kontextu) | `product_search` | — | `None` | Padá na "nemám aktívny zoznam" clarifikáciu (existujúci, nesúvisiaci mechanizmus) |
| **"Ktorý z týchto produktov je lepší?"** (bez kontextu) | `product_search` | `fast` | `None` | **Porovnávacia otázka úplne ignorovaná**, vráti nesúvisiaci fast-path šum |

**Kontrolné dopyty** (rt0004/rt0010/rt0011, Show More, size refinement, topic switch, recipe) — všetky nezmenené oproti V2.13g baseline, potvrdené.

## 8. Recommendation goal — zistenia

Žiadna vrstva dnes nerozlišuje "odporuč X" vs. "nájdi X" vs. "porovnaj X" vs. "alternatíva k X" s reálnou routovacou váhou. `TurnResolver`/`WorkflowResolver` (V2.13b, najprísnejšia routovacia vrstva) pozná len 4 výstupy: `RESULTSET_CONTINUATION`, `ALLERGEN_SAFETY`, `RELATED_PRODUCTS`, `LEGACY_FALLBACK`. **Nezavádzame nový `recommendation_goal` enum** — `product_comparison`/`replacement` už existujú ako mená (`app.intent`, `app.workflow_registry`), len nie sú zapojené. Budúca práca by mala tieto MENÁ oživiť, nie vytvárať paralelné.

## 9. Use-case pripravenosť

**Nízka, ale nie nulová.** Mechanizmus (`USE_CASE_COMPLETION`) je reálny a deterministický, ale vocabulary má presne 1 hodnotu (`sushi`). Rozšírenie na pho/curry/ramen/Pad Thai/biryani by vyžadovalo:
1. Nové `use_case` atribúty v `app.structured_search`'s query parseri.
2. Zodpovedajúce `_USE_CASE_TO_SOURCE_KEYS` záznamy.
Toto je dátovo-kurátorský, nie architektonický problém — šablóna (`recipe_graph`'s 47-jedálový vzor) už existuje na kopírovanie.

## 10. Product comparison pripravenosť

**Prakticky nulová pre kvalitatívne porovnanie, ale deterministicky podporovateľná pre ŠTRUKTURÁLNE porovnanie.** `COMPARISON` workflow je SHADOW-only, spúšťa sa len keď `faq_answer_found AND _looks_like_comparison(message)` — teda LEN pre otázky, ktoré náhodou zasiahnu existujúci FAQ záznam, nikdy pre priame porovnanie dvoch pomenovaných produktov ("Kikkoman alebo Yamasa?"). Živý test to potvrdil (Sekcia 7).

Deterministicky dostupné porovnávacie dimenzie DNES (zo Sekcie 6): `price` (100%), `unit_pricing_measure` veľkosť (75,4%), `brand` (95,7%), `canonical_family`/`canonical_subfamily` (len HIGH tier, 24,8%), `availability` (100%, ale bez variancie — nerozlišuje). **Chuť, autentickosť, "prémiovosť" nemajú ŽIADNE dátové krytie** (pôvod textu ~0,05%) — akékoľvek takéto tvrdenie by bolo `LLM_JUDGMENT` bez podkladu.

## 11. Evidence model

`app/recommendation_evidence.py` (nový, izolovaný, NEPRIPOJENÝ do `/chat`):

```python
EvidenceItem(reason_code: str, provenance: str, source: str, strength: float, customer_visible: bool = True)
```

Obyčajný `frozen dataclass`, nie wrapper hierarchia (rovnaké zdôvodnenie ako `WorkflowResult`/`AdvisorResponse` v predošlých sprintoch — najjednoduchší tvar, ktorý robí prácu).

## 12. DATA_DERIVED evidencia

Priamo z katalógového auditu (Sekcia 6): `price`/`sale_price`, `unit_pricing_measure` (veľkosť), `brand`, `gtin`, `canonical_family`/`canonical_subfamily` **len HIGH tier**. Tieto sú bezpečné ako vysoko-silná (`strength >= 0.75`) evidencia.

## 13. INFERRED evidencia

Deterministické pravidlo nad dôveryhodnými dátami: `app.cross_sell`'s role-match (`USE_CASE_COMPLETION`/`RECIPE_COMPLETION`), `app.recipe_graph`'s ingredient-role→product mapovanie (27 taxonomy-backed konceptov silnejšie než 47 lexicky kurátorovaných), taxonomy MEDIUM/LOW tier (slabšia, ale reprodukovateľná inferencia).

## 14. LLM_JUDGMENT evidencia

Akékoľvek kvalitatívne tvrdenie bez štruktúrovaného poľa za sebou: chuť, autentickosť, "vyváženosť", "prémiovosť", "obľúbenosť u zákazníkov" (bez reálnych behaviorálnych dát na túto úroveň). `app.grounding.validate_answer()` toto **nekontroluje** — kontroluje len URL a ceny, nie porovnávacie tvrdenia (priamo overené čítaním `app/grounding.py`). Toto je reálne, zdokumentované (nie opravené v tejto sprinte) riziko — pozri Sekciu "Riziká".

## 15. Reason-code matica

| reason_code | zdroj | provenance | pokrytie | bezpečné pre HIGH? | zákaznícky viditeľné? | rozhodnutie |
|---|---|---|---|---|---|---|
| `product_type_fit` | `app.taxonomy` HIGH tier | DATA_DERIVED | 24,8% katalógu | áno | áno | **KEEP_WITH_LIMITATIONS** (len HIGH tier) |
| `use_case_fit` | `app.cross_sell` USE_CASE_COMPLETION | INFERRED | len "sushi" dnes | čiastočne (s ≥2 evidenciami) | áno | **KEEP_WITH_LIMITATIONS** (rozšíriť vocabulary) |
| `recipe_role_fit` | `app.recipe_graph` | INFERRED | 47 jedál, 74 konceptov | čiastočne | áno | **KEEP_WITH_LIMITATIONS** |
| `constraint_fit` | `app.structured_search` tvrdé obmedzenia | DATA_DERIVED | podľa family/attribút pokrytia | áno | áno | **KEEP** |
| `dietary_fit` | žiadne štruktúrované pole; `Products_AI.Atribúty` | DATA_DERIVED (tenké) | 2,4% katalógu | nie (príliš nízke pokrytie) | áno, s viditeľným obmedzením | **FUTURE_DATA_REQUIRED** |
| `size_fit` | `unit_pricing_measure` | DATA_DERIVED | 75,4% (+3,6pp regex) | áno | áno | **KEEP** |
| `price_fit` | `price`/`sale_price` | DATA_DERIVED | 100%/47,3% | áno | áno | **KEEP** |
| `ranking_strength` | `app.ranking_features` | DATA_DERIVED/INFERRED zmes | interné, nie customer-facing dnes | čiastočne | nie priamo (potrebuje preklad) | **KEEP_WITH_LIMITATIONS** |
| `popularity` | žiadny reálny agregát dnes | — | — | nie | — | **REJECT** (žiadne dáta) |
| `brand_fit` | `brand` pole | DATA_DERIVED | 95,7% (6,4% sú právnické mená) | áno, s výnimkou právnických mien | áno | **KEEP_WITH_LIMITATIONS** |
| `culinary_fit` | `app.recipe_graph` role | INFERRED | úzke (47 jedál) | čiastočne | áno | **KEEP_WITH_LIMITATIONS** |
| `flavor_profile_fit` | žiadne dáta | LLM_JUDGMENT | 0% | nie | len s explicitným "podľa všeobecnej znalosti" rámcovaním | **LLM_ONLY** |
| `authenticity` | žiadne dáta (pôvod ~0,05%) | LLM_JUDGMENT | ~0% | nie | nie ako fakt | **REJECT** ako DATA/INFERRED tvrdenie, **LLM_ONLY** ako opatrne rámcovaný názor |
| `premium_position` | žiadne dáta | LLM_JUDGMENT | 0% | nie | nie | **REJECT** |
| `value_for_money` | `price`/`unit_pricing_measure` pomer | INFERRED (jednotková cena) | 75,4%×100% | čiastočne | áno | **KEEP_WITH_LIMITATIONS** |

## 16. Confidence kontrakt

`app.recommendation_evidence.compute_confidence()`:

- `INSUFFICIENT` — žiadna evidencia.
- `LOW` — len `LLM_JUDGMENT` evidencia (ľubovoľná sila), ALEBO slabá `DATA_DERIVED`/`INFERRED` evidencia (`strength < 0.5`).
- `MEDIUM` — aspoň 1 `DATA_DERIVED`/`INFERRED` položka so `strength >= 0.5`.
- `HIGH` — aspoň 2 silné (`strength >= 0.75`) `DATA_DERIVED`/`INFERRED` položky, ALEBO 1 veľmi silná (`strength >= 0.9`).

**Štrukturálny dôkaz invariantu** (nie len konvencia): `HIGH` je dosiahnuteľné len z vetvy za `if not grounded: return LOW` — teda `grounded` (ne-LLM evidencia) musí byť neprázdna, inak funkcia už vrátila `LOW` skôr. Overené 24 testami vrátane vyčerpávajúceho sweepu sily 0,00–1,00 pre LLM-only evidenciu (`test_llm_only_property_exhaustive_strength_sweep`).

## 17. RECOMMEND / CLARIFY / ABSTAIN politika

`app.recommendation_evidence.decide()`, precedencia:
1. `missing_customer_info=True` (volajúci určil, že chýba zákaznícka informácia) → **CLARIFY** (okrem prípadu nulovej evidencie, kde CLARIFY by nemalo čo doplniť → ABSTAIN).
2. `INSUFFICIENT` confidence → **ABSTAIN**.
3. Žiadna zmysluplná diferenciácia kandidátov → **ABSTAIN**.
4. `LOW` confidence spôsobené VÝHRADNE `LLM_JUDGMENT` evidenciou → **ABSTAIN** (nie RECOMMEND so slabým odôvodnením).
5. Inak → **RECOMMEND**.

ABSTAIN neznamená vrátiť nič — volajúci môže stále zobraziť faktické kandidátov, len bez tvrdenia "toto je najlepšie".

## 18. Best choice vs. ranking

`app.ranking.rank_candidates()`'s skóre dnes reprezentuje **textovú relevanciu + taxonomy confidence + explicitné zhody + dostupnosť + merchandising/behavioral/personalization multiplikátory** (`app.ranking_features`) — **NIE** use-case fit. Pozícia #1 v rankingu ≠ "najlepšie pre tento účel". Toto je centrálna architektonická hranica pre V2.14b: "best choice" tvrdenie vyžaduje explicitné use-case/porovnávacie zdôvodnenie NAD rámec existujúceho poradia, nie len prevzatie prvého výsledku.

## 19. Chýbajúce dáta

- Štruktúrované dietárne/alergénové polia pri celom katalógu (dnes 0%, len 2,4% cez `Products_AI`).
- Zloženie/ingrediencie (1,2% voľný text).
- Krajina pôvodu (0,05%).
- Množstvá/porcie v receptoch (0 z 47 jedál).
- Substitučný graf nad rámec 1 hrany.
- Reálny agregát obľúbenosti/popularity nezávislý od `app.learning_signals`'s interných kvalitatívnych signálov.
- `use_case` vocabulary nad rámec "sushi".

## 20. Implementation gate

# **GATE A — Foundation implementation justified, úzko vymedzené**

Zdôvodnenie: znovupoužiteľné primitíva existujú (`app.cross_sell`, `app.taxonomy`, `app.ranking_features`, `app.recipe_graph`), evidence model je jasný, confidence je deterministický a testovateľný, a nová **izolovaná** foundation (nulové zapojenie do `_chat_impl()`) nemení zákaznícke správanie vôbec. Plná runtime recommendation/comparison engine by bola predčasná (dátové pokrytie 24,8-34,4% taxonomy, 1 use_case hodnota, 0-2,4% dietárne dáta) — GATE A je zámerne úzky, nie GATE A na celý V2.14b rozsah.

## Implementované zmeny

- `app/recommendation_evidence.py` (nový, ~150 riadkov, čisté funkcie, žiadny import z `app.main`, žiadny zavolaný z akéhokoľvek zákazníckeho path).
- `tests/test_recommendation_evidence_v2_14a.py` (24 testov, dôkazy prípadov A-E zo zadania Sekcia 43).
- **Nulová zmena** `app/main.py`, `app/cross_sell.py`, `app/ranking_features.py`, `app/recipe_graph.py`, `app/taxonomy.py`, `app/workflow_registry.py`, `app/widget.js` — potvrdené `git diff --stat`.

## Testy

24 nových testov: `EvidenceItem` validácia (3), Case A silná evidencia→HIGH (3), Case B čiastočná evidencia→MEDIUM/LOW (3), Case C LLM-only nikdy HIGH vrátane vyčerpávajúceho sweepu (6), Case D nedostatočná evidencia→ABSTAIN (3), Case E chýbajúci use-case→CLARIFY (3), deterministická opakovateľnosť (2), unsupported-claim handling (1).

## Riziká

1. `app.grounding.validate_answer()` nekontroluje porovnávacie/kvalitatívne tvrdenia (len URL/ceny) — LATENTNÉ riziko v existujúcom OpenAI system prompte (`"Odporúčam tiež...", "Skvelo sa hodí k..."` jazyk), ale živá charakterizácia (Sekcia 7) nenašla ŽIADNY aktuálny výskyt neopodstatneného "najlepší" tvrdenia — riziko štrukturálne prítomné, nie momentálne manifestujúce sa. Neopravené v tejto sprinte (Section 21 zadania to výslovne povoľuje, ak riziko nie je závažné a oprava by nebola malá).
2. Taxonomy pokrytie (34,4%) sa mohlo od V2.3/V2.4 zlepšiť pridaním nových `FamilyRule` (V2.12.x), ale žiadne aktualizované číslo nebolo odvtedy commitnuté — toto sedenie poskytuje prvé aktuálne, živo overené číslo.
3. `rt0013` substitučný prípad ("náhrada za rybaciu omáčku vegan") sa priamo prekrýva s recipe_graph's JEDINOU substitučnou hranou (fish_sauce→soy_sauce, vegan) — budúci evidence framework by mal prirodzené miesto na reprezentáciu tohto rozhodnutia, ale **rt0013 sa touto sprintou nerieši** (explicitný non-goal).

## Explicitné non-goals (dodržané)

Nerozšírené V2.13f-B, nerozobratá commerce pipeline, nezmenené routing/retrieval/ranking/taxonomy/cross-sell/recipe/session správanie, žiadny nový admin write endpoint, `AUTO_PROMOTION` nezmenené (`false`), žiadne nové LLM volanie, žiadny vymyslený flavor/authenticity atribút, `rt0013` neriešené.

## Odporúčané poradie V2.14b/V2.14c

# **NEXT: V2.14b — Product Comparison & Best-Choice Foundation**

Zdôvodnenie: deterministické porovnávacie dimenzie (`price` 100%, `unit_pricing_measure` 75,4%, `brand` 95,7%, `canonical_family` HIGH tier 24,8%) sú DNES dostatočne pokryté na úzko vymedzené, čestné štrukturálne porovnanie dvoch pomenovaných produktov (cena/veľkosť/značka/rodina/dostupnosť) — bez potreby vymýšľať chuť/autentickosť. `COMPARISON` workflow_id už existuje (len SHADOW) — V2.14b ho môže oživiť namiesto vytvárania nového mena. Naproti tomu use-case vocabulary rozšírenie (V2.14c) je viac dátovo-kurátorská práca (kopírovanie `recipe_graph`-štýlového vzoru na nové use cases) — hodnotnejšie vykonať AŽ PO tom, čo evidence/confidence kontrakt (táto sprinta) je overený v praxi na užšom, rýchlejšie dodateľnom probléme.

**V2.14c — Use-Case Intelligence Expansion**: rozšírenie `_USE_CASE_TO_SOURCE_KEYS` nad rámec "sushi" (pho, curry, ramen, Pad Thai, biryani), využívajúc `app.recipe_graph`'s existujúci 47-jedálový vzor ako šablónu.

## V2.14a FINAL STATUS

# **RECOMMENDATION_FOUNDATION_PARTIALLY_READY**

Evidence/confidence kontrakt je hotový a testovaný. Runtime dáta na broad best-choice/comparison/use-case pokrytie NIE SÚ pripravené (taxonomy 34,4%, use_case 1 hodnota, dietary 2,4%) — toto NIE JE zlyhanie sprinty, je to správny, dôkazom podložený záver podľa Section 45 zadania.
