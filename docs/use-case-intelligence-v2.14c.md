# V2.14c — Evidence-Grounded Use-Case Intelligence Expansion

Dátum: 2026-08-21. Baseline: `4eaf4df` (V2.14b), `pytest 1401/1401`, V2.10
fast-mode `34/39`, canary `10/10`. Pokračuje z V2.14b
(`COMPARISON_INTELLIGENCE_LIVE`) — rozširuje recommendation
intelligence o "[produkt] na [kulinárske použitie]" otázky.

## 1. Existujúce primitíva — audit

| Otázka zadania | Zistenie |
|---|---|
| A. Čo reprezentuje use-case znalosť? | `app.taxonomy`'s `FamilyRule.attributes=(("use_case","sushi"),)` — presne 1 hodnota v celej taxonomy, `ProductTaxonomy.use_case_facets`/`cuisine_facets` sú **mŕtve polia**, vždy `[]` (`app/taxonomy.py:848-849`). |
| B. Čo generuje use-case kandidátov? | `app.recipe_graph.resolve_ingredient_products()` — funguje pre 47 kurátorovaných jedál, ALE akceptuje aj slabšie `RECIPE_CURATED` (lexikálne) zdroje popri `PRODUCT_TAXONOMY`. |
| C. Čo vysvetľuje poradie kandidátov? | `app.ranking_features.explain_candidates()` — nepoužité tu (dev-only, V2.14a audit), nová logika používa priamy taxonomy filter namiesto duplicitného ranking enginu. |
| D. Čo mapuje recept→produkt? | `app.recipe_graph` (47 jedál) — ALE `app.cross_sell.roles_for_recipe()`/`roles_for_use_case()` (skutočný zákaznícky mechanizmus) dôveruje LEN `PRODUCT_TAXONOMY`-backed konceptom, nie `RECIPE_CURATED` — systematická medzera (30-60% ingrediencií na jedlo nedosiahne zákazníka cez cross-sell). |
| E. Ktoré sú reálne runtime mechanizmy? | `app.cross_sell`'s `USE_CASE_COMPLETION` (LEN sushi), `RECIPE_COMPLETION` (47 jedál, čiastočne). |
| F. Ktoré sú len shadow/mŕtve? | `app.workflow_registry.USE_CASE_ADVICE` (`migration_status=SHADOW`, spúšťa sa len cez `cross_sell_context_type=="USE_CASE_COMPLETION"`, ktorý má dnes presne 1 hodnotu). |
| G. Ktoré sú čiastočne znovupoužiteľné? | Taxonomy family/subfamily filter (priamo použité), `app.recommendation_evidence` (V2.14a, priamo znovupoužité). |
| H. Čo je genuinely nové? | Kanonický use-case resolver + per-role evidence tabuľka + decision/compose vrstva — `app/use_case_advice.py`. |

## 2. Reálny dátový audit (živo overené, nie odhad)

Kompletný per-use-case audit (sushi, pho, ramen, pad_thai, tom_kha,
kari/thajske_kari) v internom výskumnom zázname tejto sprinty —
kľúčové zistenia:

- **Presne 1** `use_case` atribút v CELEJ taxonomy (sushi_rice).
- **Ramen**: bare slovo "ramen"/"rezance" sa mapuje na ROVNAKÚ
  `instant_noodles` rodinu (89 produktov) bez ohľadu na to, či
  zákazník myslí instantnú polievku alebo suché rezance na domácu
  polievku — **navyše 9 z ~35 "ramen"-titulovaných produktov v tejto
  rodine sú misky/varešky** (chýbajúca `exclude_title_phrases`
  položka v `app/taxonomy.py` — reálny, nezávisle objavený, dosiaľ
  nezdokumentovaný data-quality bug, mimo rozsahu opravy tejto
  sprinty).
- **Pho**: `rice_noodles` (39, prevažne HIGH), `fish_sauce`/`hoisin_sauce`/`chili_sauce`
  (19/6/HIGH) sú čisté, dobre oddelené taxonomy rodiny — ALE
  `app.recipe_graph`'s vlastné "banh pho"/"korenie pho" ingrediencie
  sa NEVEDIA namapovať cez taxonomy (rozlišujú sa len cez zdieľaný,
  nediferencovaný 23-položkový lexikálny bucket).
- **Pad Thai / Tom Kha**: reálne, čisté taxonomy dáta existujú
  (rice_noodles, coconut_milk, tamarind_pasta) — ALE `"pad thai"`
  a `"tom kha"` sú DOSLOVA hardcoded v `RECIPE_INTENT_MARKERS`
  (`app/main.py:2569-2589`, V2.9-éra, pred touto sprintou) ako
  automatické recipe-intent spúšťače — akákoľvek správa obsahujúca
  tieto reťazce sa VŽDY vyrieši ako `recipe_subject`, takže táto
  sprinta ich nemôže sprístupniť zákazníkovi bez znovuotvorenia
  recipe-intent precedencie (Section 35 zadania to explicitne
  zakazuje).
- **Kari/thajske_kari**: `curry_paste` (11 HIGH + 20 MEDIUM variety),
  `coconut_milk` (17), `fish_sauce` (19) — čisté. Jasmínová ryža nemá
  VLASTNÚ taxonomy subfamily (spadá do širokého `plain_rice`, 66
  produktov, z toho len 15 jazmínových) — vyžaduje dodatočný lexikálny
  filter.

## 3. Use-case vocabulary

`app/use_case_advice.py._USE_CASE_ALIASES` — jediný zdroj pravdy pre
túto sprintu (nie roztrúsené naprieč modulmi, Section 83 zadania).
`"thajske_kari"`/`"thai curry"` zámerne zlúčené do kanonického
`"kari"` (taxonomy nerozlišuje red/green/panang/massaman cez
`canonical_subfamily`, všetkých 31 produktov má `subfamily=None`).

## 4. Per-use-case release matrix

| Use case | Resolution | Evidence | Grounding | Runtime | Status |
|---|---|---|---|---|---|
| **sushi** | Deterministic (alias+role) | rice/sushi_rice HIGH (12 produktov) | PASS | customer | **LIVE** |
| **pho** | Deterministic | noodles/rice_noodles, sauce/{fish,hoisin,chili}_sauce, MEDIUM-HIGH mix (6-39 produktov) | PASS | customer | **LIVE** |
| **kari** (vr. thajske_kari) | Deterministic | curry_paste, coconut_milk, plain_rice+lexikál, fish_sauce | PASS | customer | **LIVE** |
| **pad_thai** | Deterministic, evidencia reálna a testovaná | rice_noodles, tamarind_pasta, fish_sauce | PASS (testy) | **nedosiahnuteľné zákazníkom** — "pad thai" je hardcoded recipe-intent marker | **SHADOW_ONLY** |
| **tom_kha** | Deterministic, evidencia reálna a testovaná | coconut_milk, fish_sauce | PASS (testy) | **nedosiahnuteľné zákazníkom** — "tom kha" je hardcoded recipe-intent marker | **SHADOW_ONLY** |
| **ramen** | Zámerne nevyriešiteľné (alias nezaregistrovaný) | instant_noodles kolízia s nepotravinovými miskami | N/A | none | **DATA_REQUIRED** |

## 5. Evidence model

Znovupoužité z V2.14a bezo zmeny (`app.recommendation_evidence.EvidenceItem`,
`compute_confidence()`, `decide()`). Nová `app/use_case_advice.py` pridáva
LEN doménovú `RoleEvidence`/`UseCaseDecision` štruktúru nad tým istým
kontraktom — žiadny konkurenčný confidence model (Section 17 zadania).

## 6. DATA_DERIVED / INFERRED / LLM_JUDGMENT / FUTURE_DATA_REQUIRED

| Rola | Provenance | Sila | Dôvod |
|---|---|---|---|
| sushi/rice | DATA_DERIVED | 0.9 | HIGH taxonomy, category-backed |
| pho/pad_thai noodles | DATA_DERIVED | 0.8 | HIGH-capable taxonomy rodina |
| tom_kha/kari coconut_milk | DATA_DERIVED | 0.85 | HIGH-capable |
| sauce role (fish/hoisin/chili) | DATA_DERIVED | 0.6 | MEDIUM-HIGH mix, real taxonomy |
| curry_paste, tamarind_pasta | DATA_DERIVED | 0.55 | MEDIUM-only (žiadne category_terms) |
| kari/rice_jasmine | **INFERRED** | 0.6 | taxonomy match (plain_rice) + lexikálny filter ("jazmin") — 2 signály kombinované |
| galangal/lemongrass/kaffir (tom_kha aromatics) | **FUTURE_DATA_REQUIRED** | — | reálne, ale extrémne tenké zásoby (1/4/3 SKU) — vylúčené z v1 rozsahu, zdokumentované v backlogu |
| akékoľvek "chuť"/"autentickosť" tvrdenie | LLM_JUDGMENT (nikdy generované) | — | žiadne dáta, tento modul také tvrdenia nikdy nekomponuje |

## 7. Confidence contract

Bezo zmeny z V2.14a. Kritický invariant zachovaný: LLM_JUDGMENT nikdy
nevytvorí HIGH confidence (tento modul navyše NIKDY negeneruje
LLM_JUDGMENT evidenciu vôbec — `app/use_case_advice.py` neobsahuje
žiadnu referenciu na OpenAI klienta, priamo overené testom).
**Confidence sa NEPRENÁŠA medzi use cases** — každé volanie
`decide_use_case_advice()` počíta evidenciu nezávisle pre presne 1
rolu v 1 use case; silná evidencia pre sushi nijako neovplyvňuje
confidence pre pho/kari.

## 8. RECOMMEND / CLARIFY / ABSTAIN

`UseCaseDecision.state` podporuje všetky tri, ALE **CLARIFY sa
zámerne nikdy nevracia zo zákazníckeho vstupného bodu**
(`decide_use_case_advice()`) v tejto sprinte — reálny nález pri
plnom regresnom behu (Sekcia 10) ukázal, že bare use-case zmienka
("chcem robiť sushi") už má existujúci, správny mechanizmus
(`related_subject` companion produkty), ktorý CLARIFY tichoby
predbehol. Namiesto CLARIFY sa v tomto prípade vracia `None`
(delegovanie na existujúcu kaskádu) — `CLARIFY` stav zostáva reálnou,
otestovanou cestou v `UseCaseDecision`/`compose_use_case_answer()`
pre budúce použitie, len nie je dosiahnuteľný z tejto sprinty
zapojeného vstupu. `ABSTAIN` sa vracia, keď rola/use case rozpozná,
ale kandidáti neexistujú (Section 87 — čestné no-match správanie).

## 9. Conflict handling

"Chcem ryžu na sushi, ale nie sushi ryžu" — `has_explicit_exclusion()`
deteguje negačný marker ("nie"/"nechcem"/"bez"/"okrem") bezprostredne
pred rolovým markerom/popisným menom → `decide_use_case_advice()`
vracia `None` (nevnucuje vylúčenú rodinu, deleguje na existujúcu
kaskádu, ktorá má vlastné, nezmenené spracovanie tejto formulácie).

## 10. UNKNOWN taxonomy policy

`generate_candidates()` filtruje na `confidence in {HIGH, MEDIUM}` –
`LOW`/`UNKNOWN` sa nikdy nepoužijú ako jediný základ tvrdenia ani sa
neprezentujú (Section 20). Priamo testované
(`TestUnknownTaxonomyPolicy`).

## 11. Candidate generation

Priamy filter nad existujúcim `product_taxonomy_index`
(`app.taxonomy.get_taxonomy()`) — **žiadny paralelný retrieval engine**
(Section 21). Poradie: HIGH pred MEDIUM, potom cena vzostupne —
deterministické, bez novej "ranking" logiky.

## 12. V2.14b comparison integrácia

Nezávislé, prirodzene disjunktné konštrukciou (comparison vyžaduje 2
vyriešené ciele, use-case-advice vyžaduje presne 1 rolu) — priamo
overené testom (`TestComparisonStability`). `app/comparison.py` sa
nemenil.

## 13. Comparative claim grounding

Žiadny LLM v rozhodovacej/kompozičnej ceste (rovnaký bezpečnostný
dizajn ako V2.14b) — priamo overené statickou inšpekciou zdrojového
kódu (`TestNoNewLlmCall`). Odpovede používajú len 2 úrovne istoty
("odporúčam" pre HIGH, "vhodná voľba" pre MEDIUM/nižšie), Section 95.

## 14. Allergen safety

Kriticky overené: "sójová omáčka bez sóje na ramen" zostáva
`allergen_safety`, 0 produktov — vetva je umiestnená AŽ PO existujúcej
allergen-safety kontrole v `_chat_impl()`'s kaskáde.

## 15. Related products (rt0004)

**Reálna regresia nájdená a opravená** (nie hypotéza): "súvisiace
produkty k sushi ryži" pôvodne aktivovala use-case-advice namiesto
`related_products`, pretože obsahuje "sushi" aj "ryzi" (rolový marker).
Opravené explicitným vylúčením companion-request markerov
("suvisiace", "doplnky") — `is_companion_request()`.

## 16. Session safety

Topic switch (sushi→Shin Ramyun) overený bez kontaminácie. Žiadny
nový trvalý "aktívny use case" pamäťový kľúč sa nezavádza.

## 17. ResultSet continuity

Size refinement po use-case-advice ťahu netestuje pád (products pole
vždy prítomné) — use-case-advice nezapisuje `active_result_set_id`.

## 18. Recipe controls

**Druhá reálna regresia nájdená a opravená**: "chcem robiť Pad Thai"
pôvodne aktivovala CLARIFY namiesto recipe flow. Opravené pridaním
`recipe_subject` guard parametra — `execute_use_case_advice()` vracia
`None` hneď, keď `recipe_subject` je pravdivý, presne rovnaký
fall-through kontrakt ako `execute_recipe()`.

## 19. Cross-sell relationship

`app.cross_sell` sa nemenil. Use-case-advice odpovedá na INÚ otázku
("ktorý produkt VYHOVUJE tomuto použitiu") než cross-sell ("aké sú
DOPLNKY k tomuto produktu") — žiadne zlúčenie sémantiky (Section 36).

## 20. Implementované zmeny

- `app/use_case_advice.py` (nový modul).
- `app/workflow_executor.py`: `execute_use_case_advice()` (nová funkcia).
- `app/main.py`: 1 import + 1 nová skorá vetva v `_chat_impl()` (+26 riadkov).
- `tests/test_use_case_advice_v2_14c.py` (45 testov).

## 21. Neimplementované / zamietnuté

- Ramen customer-facing rozšírenie (DATA_REQUIRED — taxonomy bug).
- Tom Kha aromatiká (galangal/citrónová tráva/kaffir listy) — FUTURE_DATA_REQUIRED (príliš tenké zásoby).
- Oprava `instant_noodles` taxonomy exclude_title_phrases (mimo rozsahu — zmena `app/taxonomy.py` by vyžadovala vlastnú charakterizáciu).
- Riešenie "pad thai"/"tom kha" recipe-intent kolízie (vyžadovalo by zmenu `RECIPE_INTENT_MARKERS`/recipe precedencie — Section 6/35 explicitne zakazuje).

## 22. Reálne nájdené a opravené regresie (zhrnutie)

1. **rt0004** (`suvisiace produkty k sushi ryzi`) — companion-request marker exclusion.
2. **"chcem robiť Pad Thai"** — recipe_subject guard.
3. **`curry_red_001`** (V2.10 golden) — vyžadovanie "na X"/"pre X" framing prepozície pred use-case aliasom.
4. **`regbug_rt0026`** — vyriešené fixom #3 (žiadna rola sa nenašla → `None`, nie CLARIFY).
5. **`conv_sushi_matrix_001`** — CLARIFY odstránené zo zákazníckeho vstupného bodu.

Všetkých 5 má permanentný regresný test.

## 23. Testy

`tests/test_use_case_advice_v2_14c.py` (45): 13 povinných charakterizačných prípadov (A-M), 5 regresných zámkov, unit testy pre rozlíšenie/rolu/konflikt/UNKNOWN politiku/no-LLM dôkaz.

## 24. Full test suite

**1446/1446** (1401 baseline + 45 nových), 0 regresií po oprave.

## 25. V2.10 evaluation

Fast-mode **34/39 nezmenené** (identické error buckety pred/po oprave) — PRED opravou 3 kritické regresie (curry_red_001, regbug_rt0026, conv_sushi_matrix_001), PO oprave návrat na presný baseline.

## 26. Search quality canary

**10/10**, no anomalies.

## 27. Performance / Search / LLM call count

Žiadne nové LLM volanie (overené statickou inšpekciou). Kandidát generovanie = 1 lineárny prechod cez `products` s O(1) taxonomy lookupom na produkt — žiadny nový sieťový/disk I/O.

## 28. Známe obmedzenia

- Ramen customer-facing nedostupný (data quality).
- Pad Thai/Tom Kha use-case-advice mechanicky funguje, ale zákaznícky nedosiahnuteľný (recipe-intent kolízia).
- Jasmínová ryža vyžaduje lexikálny filter (žiadna vlastná taxonomy subfamily).
- Tom Kha aromatiká vylúčené (tenké zásoby).

## 29. Dátový backlog (prioritizovaný)

1. **Vysoká priorita**: `instant_noodles` `exclude_title_phrases` doplniť o "miska"/"misky"/"lyzica" (oprava existujúceho data-quality bugu, nezávislá od tejto sprinty).
2. **Stredná priorita**: samostatná `ramen_noodles` (dry) subfamily oddelená od `instant_noodles`.
3. **Stredná priorita**: `jasmine_rice` vlastná taxonomy subfamily (namiesto širokého `plain_rice`).
4. **Nízka priorita**: galangal/citrónová tráva/kaffir listy — rozšíriť sklad pred customer-facing použitím.

## 30. Odporúčaný ďalší krok

Vzhľadom na to, že hlavné zostávajúce obmedzenie je **dátová kvalita
konkrétnych taxonomy rodín** (ramen kolízia, jasmine rice
subfamily), nie architektúra samotná odporúčacieho enginu, odporúčaný
ďalší program je **dátovo-orientovaný** (V2.14d — Data Enrichment for
Use-Case Coverage), nie ďalšia architektonická vrstva. Alternatívne
V2.14d — Recommendation Observability & Feedback, ak sa uprednostní
meranie skutočného zákazníckeho dopadu pred ďalším rozširovaním
pokrytia.
