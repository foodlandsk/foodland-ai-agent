# Evidence-Grounded Substitution Intelligence V2 (V2.16c)

Dátum: 2026-08-27. Baseline commit: `5a1b8c1900f5616e050e4a6428327f7fb8cb3a36`
(HEAD, `origin/main`, žiadne uncommitted zmeny okrem netrackovaného
`.claude/` — overené `git fetch`/`git status`/`git rev-parse` pred
akoukoľvek zmenou, presne zodpovedá stavu po V2.16b).

## 1. Prečo tento dokument existuje

V2.16c nadväzuje na V2.16b: kým V2.16b auditoval **product search**
proti princípu "missing evidence is UNKNOWN, not FALSE", V2.16c
aplikuje ten istý princíp na **replacement_products** (substitučný)
pipeline — `detect_replacement_subject()` →
`alternative_products_for_subject()`, a legacy
`detect_special_product_subject()` cestu, ktorá ju pre časť subjektov
predbieha. Cieľ nebol "odpovedať na každú substitučnú otázku", ale
zistiť, ktoré substitučné odporúčania katalóg reálne dokáže podložiť, a
opraviť len to, čo je live-reprodukovateľná chyba — nie stavať nový
špekulatívny framework.

**rt0013 freeze** (Section 4 zadania) bol počas celej sprinty
rešpektovaný: `replacement_products` intent pre `"náhrada za rybiu
omáčku vegan"` sa nikdy nezmenil (10/10 `tests/test_rt0013_closure.py`
prechádza nezmenené, vrátane
`test_vegan_word_does_not_change_candidate_set`). Zmenená bola len
**kvalita kandidátov** pod už-rozhodnutým intentom, a len pre
gluten-free — nikdy pre vegan/vegetariánske tvrdenia.

## 2. Existujúce substitučné primitíva (audit)

Priamo overené čítaním kódu (`app/main.py`, `app/recipe_graph.py`,
`app/use_case_advice.py`, `app/recipe_shopping.py`,
`app/recommendation_evidence.py`) a `data/knowledge.json`:

- **`REPLACEMENT_SUBJECT_ALIASES`** (`app/main.py`) — 13 kurátorovaných
  subjektov: rybacia omacka, sojova omacka, gochujang, mirin, ryzovy
  ocot, kokosove mlieko, miso pasta, sriracha, hoisin omacka, tamari,
  tamarind, ryzove rezance, sushi ryza.
- **`detect_replacement_subject()`** — vyžaduje explicitný marker
  ("nahrad", "namiesto", "alternativ", "nemam"...) + zhodu s aliasom;
  bez zhody padá na generický cleaned-text/autocomplete fallback.
- **`alternative_products_for_subject()`** — 3-úrovňová kaskáda:
  `Alternatives` knowledge lookup → `REPLACEMENT_PRODUCT_QUERIES`
  (kurátorované query listy, 10/13 subjektov pokrytých) → generický
  fallback search.
- **`SPECIAL_PRODUCT_QUERIES`** (`app/main.py`, samostatný, väčší
  legacy slovník) + **`detect_special_product_subject()`** —
  vyhodnotený PRED `replacement_subject` v `_chat_impl()`'s
  dispatch kaskáde (Sekcia 3 — kľúčové zistenie).
- **`app.recipe_graph`** — `SubstitutionEdge`/`get_substitutes()`:
  reálny, ale **úplne nedosiahnuteľný (dead code)** mechanizmus. Presne
  1 hrana v celom systéme (fish_sauce→soy_sauce, context="vegan",
  confidence="MEDIUM"), zostavená priamo zo `SPECIAL_PRODUCT_QUERIES`.
  Overené `grep`: `get_substitutes`/`SubstitutionEdge` sa nikde v
  `app/` mimo `recipe_graph.py` samotného nevolajú/neimportujú. Žiadny
  živý chat-path ju nepoužíva — nezmenené, bez zásahu.
- **`app.recommendation_evidence`** (`EvidenceItem`,
  `compute_confidence()`, `decide()` → RECOMMEND/CLARIFY/ABSTAIN) —
  reálny evidence-gate framework, ale jeho konzumenti sú
  `workflow_executor.py`, `use_case_advice.py`, `basket_completion.py`,
  `comparison.py`. **Replacement kaskáda ho nepoužíva** — potvrdené,
  nezmenené (Sekcia 6 rieši, prečo to V2.16c nemení).
- **`app.comparison._QUALITATIVE_MARKERS`** → `STATE_ABSTAIN` —
  existujúci precedens presne pre princíp tejto sprinty (nikdy
  netvrdiť neoverateľné chuť/autentickosť/prémiovosť tvrdenia).
- **`app.main.allergen_safety_answer()`** — vyššia-precedenčná safety
  vrstva, nikdy netvrdí bezpečnosť produktu, vždy presmeruje na
  overenie detailu. Nedotknuté V2.16c zmenami (overené: `Som alergicky
  na soju, cim nahradim sojovu omacku?` → `intent=allergen_safety`,
  nezmenené).
- **`data/knowledge.json::sections.Alternatives`** (2140 záznamov, 1 na
  produkt) — priamo overené vzorkou: pole `"Alternativa 1"`/`"Alternativa
  2"` obsahuje vlastný text `"...alternativa v kategorii X - rovnaka
  znacka, podobna cena"`. Toto je **generický** same-category/brand/
  price "podobné produkty" dataset, **NIE** substitučne-špecifický —
  potvrdené priamym čítaním dát, nie len predpokladom.

## 3. Kľúčové zistenie: `special_subject` tieni `replacement_subject`

`app/main.py`'s `_chat_impl()` matches-dispatch kaskáda (cca. riadok
5099+) má poradie:

```
elif special_subject in {"plain_rice","sushi_rice","rice_vinegar","rice_cooker"}
     and V2_STRUCTURED_RETRIEVAL_ENABLED and (structured retrieval succeeds):
    ...
elif special_subject:
    matches = special_products_for_subject(...)
elif replacement_subject:
    matches = alternative_products_for_subject(...)
```

`detect_special_product_subject()` aj `detect_replacement_subject()` sa
**oba** vyhodnotia pre každú správu (riadky 4891-4894), ale
`special_subject` má prednosť v `elif` kaskáde. Živo overené: pre presne
3 z 13 `REPLACEMENT_SUBJECT_ALIASES` subjektov (rybacia omacka,
ryzovy ocot, sushi ryza) **oba** detektory súčasne rozpoznávajú
subjekt, a `special_subject` vyhráva — vrátane samotného rt0013 dopytu
(`"nahrada za rybiu omacku vegan"` → `special_subject=
"vegan_fish_sauce_replacement"`, nie `alternative_products_for_subject()`
cez `Alternatives`, ako doteraz nesprávne opisoval
`docs/routing-debt.md` — opravené, pozri Sekciu 8).

Toto **nemení intent** (obe cesty vracajú `replacement_products`) — mení
len to, KTORÁ funkcia dodáva kandidátov. Dôsledok pred touto sprintou:
explicitná gluten-free požiadavka pre tieto 3 subjekty by aj po opravení
`alternative_products_for_subject()` (Sekcia 5) zostala **úplne
ignorovaná**, pretože ten kód by sa nikdy nevykonal.

## 4. Druhé zistenie: negovaná "nemam" fixovala `already_have_subject`

`detect_already_have_subject()` (predtým `app/main.py:9443`) používal
holú substring-kontrolu (`"mam " in normalized_text`). Slovenské "mám"
sa po `normalize()` (diakritika preč, lowercase) stane "mam" — ale to
isté platí pre koncovku negovaného "ne**mam**" (nemám = nemám). Bez
kontroly ľavej hranice slova `"mam "` je nájdené aj vnútri `"nemam "`
napriek **opačnému** významu.

Živo reprodukované PRED opravou: `"Nemam mirin, potrebujem nahradu bez
lepku."` (nemám mirin, potrebujem bezlepkovú náhradu) bol tichý
klasifikovaný ako `already_have_subject="mirin"` a smerovaný na
`complement_products_for_subject()` ("čo sa hodí k tomu, čo už máte" —
cross-sell), takže `replacement_subject` sa nikdy ani nevyhodnotil.
Zákazník dostal 4 úplne nesúvisiace produkty namiesto bezlepkovej
mirin náhrady.

Toto je **nezávislé** od Sekcie 3 — mirin nie je jeden z 3
`special_subject`-tieňovaných subjektov, `already_have_subject` je
vyhodnotený ešte skôr než oboje.

## 5. Implementácia (3 minimálne, evidence-podložené zmeny)

Všetky zmeny v `app/main.py`, diff overený `git diff --stat`
(94 riadkov, žiadny whole-file EOL rewrite — pozri Sekciu 9).

**5.1 `product_is_gluten_free()`** (nová helper funkcia) — rovnaký
katalógový signál ako `app.taxonomy._DIETARY_CATEGORY_TERMS`/
`app.query_constraints._DIETARY_QUERY_STEMS` už používajú pre
gluten_free (`product_type` breadcrumb obsahuje "Bezlepkove
potraviny") — znovupoužitý, nie duplicitne odvodený. **Zámerne bez**
vegan/vegetariánskeho ekvivalentu — to mapovanie bolo v V2.16b
dokázané nespoľahlivé (reálny kuracie produkt označený "vegan") a
odstránené.

**5.2 Gluten-free post-filter na `elif replacement_subject:`** — keď
`is_gluten_free_search(chat_request.message)` je `True`: filtruj
kandidátov na `product_is_gluten_free`; ak prázdne, rozšír priamym
katalógovým hľadaním (`f"bezlepkova {replacement_subject}"`) a znovu
filtruj — teraz AJ na `product_is_gluten_free`, AJ na
`replacement_subject_matches_product()` (existujúca relevance-kontrola,
zabraňuje aby rozšírené hľadanie vrátilo produkt, ktorý sa netýka
pôvodného subjektu, len náhodou obsahuje "bezlepkova").

**5.3 Ten istý filter na `elif special_subject:`** (uzatvára Sekciu 3
medzeru) — aplikovaný **len keď** `replacement_subject` je tiež
nastavený (t.j. táto správa je skutočne substitučná požiadavka, ktorú
legacy `special_subject` cesta ticho obsluhuje) A správa obsahuje
explicitný gluten-free jazyk. rt0013's zamknutý vegan dopyt nemá
gluten-free jazyk → `is_gluten_free_search()` vráti `False` → táto
vetva sa vôbec nevykoná, kandidáti zostanú byte-identické (overené
priamo, pozri Sekciu 7). Relevance-kontrola (`replacement_subject_
matches_product`) aplikovaná AJ na primárny (nerozšírený) zoznam
kandidátov, pretože `SPECIAL_PRODUCT_QUERIES` bundly sú všeobecné (napr.
`"gluten_free_sushi"` = sójová omáčka + nori + ryža + wasabi + zázvor
spolu), nie subjekt-špecifické substitučné listy — bez tejto kontroly
`"sushi ryza bez lepku"` živo vrátil bezlepkovú sójovú omáčku, čo nie
je náhrada za ryžu.

**5.4 `detect_already_have_subject()` word-boundary oprava** — markery
sa teraz kontrolujú s vynúteným ľavým hraničným znakom slova
(padding medzerou na oboch stranách pred substring-kontrolou), takže
"nemam " už nesplní marker "mam " (chýba medzera bezprostredne pred
"mam"), zatiaľ čo legitímne "uz mam "/začiatok-vety "mam " zostáva
nezmenené.

Vegan/vegetariánske tvrdenia **neboli** pridané nikam do filtra —
zostávajú `STRUCTURAL_GAP_REMAINS_ACCEPTED` z rovnakého dôvodu ako
product search v V2.16b: katalóg nemá spoľahlivý per-SKU signál.

## 6. Prečo `recommendation_evidence`/`recipe_graph` neboli pripojené

Zadanie explicitne pripúšťa oba výsledky ako platné
(`SUBSTITUTION_DECISION_OBJECT_JUSTIFIED` vs.
`STRUCTURAL_GAP_REMAINS_ACCEPTED`). Rozhodnutie: **STRUCTURAL_GAP_
REMAINS_ACCEPTED** pre formálny evidence-object framework v tejto
sprinte. Dôvody:

1. `recipe_graph`'s jediná hrana je odvodená z toho istého
   `SPECIAL_PRODUCT_QUERIES` slovníka, ktorý `special_products_for_
   subject()` už priamo číta — pripojenie by len duplikovalo existujúci
   dátový zdroj cez nový objekt, bez novej evidencie.
2. `recommendation_evidence`'s `compute_confidence()` HIGH úroveň je
   štrukturálne nedosiahnuteľná len z `LLM_JUDGMENT` evidencie — žiadny
   zo substitučných zdrojov (Alternatives, REPLACEMENT_PRODUCT_QUERIES,
   SPECIAL_PRODUCT_QUERIES) nie je `DATA_DERIVED` v zmysle, aký tento
   framework vyžaduje pre plnú dôveru.
3. Section 5 zadania explicitne varuje pred širokým prestavaním
   replacement routingu — pripojenie evidence-gate by znamenalo zmeniť
   KTO rozhoduje o zobrazení kandidátov, nie len filtrovať ich kvalitu
   v rámci už-rozhodnutého intentu (rozdiel medzi Sekciou 5 a týmto
   dokumentom).

Namiesto toho: **candidate-quality filter v rámci existujúcej
kaskády** (Sekcia 5) — menší blast radius, priamo testovateľný,
neinvazívny do intent-rozhodovania.

## 7. Regresné kontroly (živo overené)

| Kontrola | Správa | Výsledok |
|---|---|---|
| rt0013 lock | `nahrada za rybiu omacku vegan` | `replacement_products`, kandidáti byte-identické (žiadny gluten-free jazyk → nová vetva sa nespustí) |
| rt0013 test suite | `tests/test_rt0013_closure.py` | 10/10 passed, nezmenené |
| rt0004 | `súvisiace produkty k sushi ryži` | `related_products`, nedotknuté |
| rt0010 | `sójová omáčka bez sóje` / `Som alergicky na soju, cim nahradim sojovu omacku?` | `allergen_safety`, nedotknuté |
| rt0011 | opakovaný dopyt, session kontaminácia | bez zmeny |
| soy sauce gf | `Potrebujem nahradu za sojovu omacku bez lepku.` | 5 produktov, všetky `product_is_gluten_free=True` (predtým: identické s nekonštrainovaným dopytom) |
| mirin negation fix | `Nemam mirin, potrebujem nahradu bez lepku.` | teraz `replacement_products`, 2 skutočné mirin produkty, oba gluten-free (predtým: 4 nesúvisiace produkty cez `complement_products_for_subject`) |
| fish sauce shadow fix | `Cim nahradim rybaciu omacku, potrebujem bezlepkovu verziu.` | 8 skutočných rybacích omáčok, všetky gluten-free (predtým: nefiltrovaný zoznam, gluten-free jazyk ignorovaný) |
| sushi rice shadow fix | `Nahrada za sushi ryzu, potrebujem bezlepkovu.` | 8 skutočných sushi ryží, gluten-free (predtým bez relevance-kontroly: leak bezlepkovej sójovej omáčky) |
| already_have positive control | `Mam doma kimchi, co dalsie by sa hodilo?` | `related_products` (already_have_subject cesta), nezmenené |
| already_have positive control 2 | `Uz mam sojovu omacku, co dalsie by sa hodilo?` | `already_have_subject="sojova_omacka"` rozpoznané, nezmenené |

## 8. Aktualizácia `docs/routing-debt.md`

Pridaná V2.16c korekčná poznámka (bez zmeny stavu rt0013) — pôvodný
opis "skutočný mechanizmus je `detect_replacement_subject()` + curated
`Alternatives` knowledge lookup" bol pre samotný rt0013 dopyt nepresný
(Sekcia 3). Historický kontext ponechaný, len opravené TO, ČO reálne
beží.

## 9. Byte/EOL bezpečnosť

`app/main.py` má pred-existujúce zmiešané CRLF/LF riadkovanie (aj v
rámci jednej funkcie — priamo overené na `detect_already_have_subject`
regióne). Zmeny aplikované byte-precíznou rekonštrukciou z
`git show HEAD:app/main.py`, každý hunk s vlastným, lokálne správnym
EOL, nikdy cez priamy Edit tool na tomto súbore (potvrdená história
whole-file rewrite rizika z V2.16a/a.1/b). `git diff --stat`: 94
riadkov (91 insert/3 delete) na ~10 000-riadkovom súbore — potvrdené
minimálne, žiadny whole-file rewrite artefakt.

## 10. Testy

`tests/test_substitution_intelligence_v2_16c.py` — nový súbor,
pokrýva všetky 3 zmeny (5 test-tried: gluten-free filter na
`alternative_products_for_subject` ceste, `detect_already_have_subject`
negation fix, special_subject shadow fix pre fish sauce aj sushi rice,
rt0013 nedotknutosť, explicitná kontrola že vegan/vegetariánsky
helper nebol pridaný). Plná regresná sada (`pytest tests/ -q`) spustená
s izolovaným `--basetemp` (Windows shared-tmp-dir kontaminácia, známy
problém z V2.16a.1) — výsledok pozri commit message / CI.

## 11. Zostávajúce štrukturálne medzery (accepted, nie táto sprinta)

- Morfologické pokrytie `REPLACEMENT_SUBJECT_ALIASES`/`SPECIAL_PRODUCT_
  QUERIES` je len nominatív/pár pádov (napr. "ryzovy ocot" nerozpozná
  "ryzoveho octu" v genitíve) — živo reprodukované počas tejto sprinty,
  ale ide o širšie pokrytie slovenskej deklinácie naprieč 13+
  subjektami, mimo minimálneho rozsahu tejto sprinty.
- `use_case_advice.py`'s `LIVE_USE_CASES` cesta môže vrátiť skôr než sa
  `replacement_subject` vôbec vyhodnotí, keď je v správe prítomná
  use-case fráza (napr. "tom kha") — samostatná, nezávislá medzera od
  Sekcie 3, vyžadujúca vlastný, samostatne overený zásah do
  `_chat_impl()`'s poradia; neriešená v tejto sprinte (Section 5
  zadania — nemeniť široko replacement routing).
- Vegan/vegetariánske substitučné tvrdenia zostávajú bez štruktúrovanej
  evidencie (rovnaké ako V2.16b pre product search).
