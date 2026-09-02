# Recommendation Explanation & Decision Transparency (V2.16e)

Dátum: 2026-09-02. Baseline commit: `ef05f2706d315c6ea64263bafd120b805d7eae6a`
(HEAD, `origin/main`, čistý working tree okrem netrackovaného `.claude/`
— overené `git fetch`/`git status`/`git rev-parse`/`git log` pred
akoukoľvek zmenou. V2.16c aj V2.16d sú plne prítomné, presne na
očakávaných SHA).

## 1. Prečo tento dokument existuje

V2.16e nemení, ČO systém odporúča — len PREČO a AKO to vysvetľuje.
Princíp: viac vysvetliteľnosti, nikdy viac špekulácie. Audit najprv,
implementácia len tam, kde charakterizácia dokázala reálnu medzeru.

## 2. Existujúca evidence architektúra (audit)

Priamo overené čítaním kódu:

- **`app.recommendation_evidence`** (V2.14a) — `EvidenceItem`
  (reason_code/provenance/strength), `compute_confidence()`
  (štrukturálne nemôže vrátiť HIGH len z `LLM_JUDGMENT`), `decide()`
  → RECOMMEND/CLARIFY/ABSTAIN. Zdieľaný základ pre comparison/
  use_case_advice/basket_completion.
- **`app.comparison`** (V2.14b) — **plne deterministický, ŽIADEN LLM
  call**. `_QUALITATIVE_MARKERS` → `GOAL_UNSUPPORTED_QUALITATIVE` →
  hard `STATE_ABSTAIN`. Reason-code vocab: `price_fit`,
  `unit_price_fit`, `size_fit`, `brand_fit`, `product_type_fit`. Už
  DNES implementuje presne princípy tejto sprinty (deterministické
  "lacnejší na 100 ml" tvrdenia, honest ABSTAIN pre chuť/autentickosť).
- **`app.use_case_advice`** (V2.14c) — deterministický, `RoleEvidence`
  s `reason_code` v ROVNAKOM vocab priestore ako comparison
  (`product_type_fit`/`use_case_fit`), confidence-riadená
  asertivita textu ("odporúčam" HIGH vs. "je vhodná voľba" MEDIUM).
- **`app.basket_completion`** (V2.14e) — deterministický, každá rola
  má `EvidenceItem("product_type_fit", ...)`, čestne rozlišuje
  `fully_resolved` vs. čiastočné pokrytie s explicitne vymenovanými
  nevyriešenými konceptmi.
- **`app.answer_composer`** (V2.5) — deterministický, len pre
  `product_search`/`category_browse` (žiadne "prečo", len fakty:
  "Máme N produktov v kategórii X").
- **`app.grounding.validate_answer()`** — mechanicky overuje URL a
  ceny v LLM-generovanej odpovedi. **Neoveruje** dietary/kvalitatívne/
  autentickosť tvrdenia (Sekcia 5 nižšie).

## 3. LLM v odpovedi — kde a ako je obmedzený

Jediný živý LLM call pre customer-facing text je `response_mode="llm"`
fallback v `app/main.py` (~riadok 5429+), použitý pre
`replacement_products`/`related_products`/generický product-advice,
keď štruktúrovaný `answer_composer` cestu nedosiahne. System prompt
explicitne inštruuje: "Používaj iba poskytnutý kontext...
Nevymýšľaj ceny, sklad ani vlastnosti produktu... Pri otázke 'čím
nahradiť X' odporúčaj podobné alternatívy, nie cross-sell doplnky."
Toto je PROMPT-úrovňová inštrukcia, nie štrukturálna záruka —
`validate_answer()` po vygenerovaní kontroluje len URL/ceny.
**Žiadny nový LLM call nebol pridaný touto sprintou** (Section 66:
očakávané 0, potvrdené).

## 4. Kľúčové zistenie #1 — systémový leak internej AI-šablóny do zákazníckeho textu

**SEVERITY: vysoká, živo reprodukované.** `app.knowledge_builder`'s
vlastná AI-content-generation prompt šablóna (`"<1 predajný
argument>"` a pod.) zostala ako DOSLOVNÁ hodnota bunky pre veľkú časť
kurátorovaného `Products_AI` datasetu (130 záznamov):

| Pole | Kontaminované | Zdroj konzumácie |
|---|---|---|
| `Chutovy profil - SK` | **63/130 (48,5 %)** | `best_product_advice_answer()` (priamy zákaznícky text) + `format_record()` (LLM kontext) |
| `Kucharsky tip - SK` | **63/130 (48,5 %)** | `format_record()` (LLM kontext) |
| `AI popis – SK` | 63/130 (48,5 %) | vkladá `Chutovy profil` inline |
| `Predajny argument - SK` | **130/130 (100 %)** | nekonzumované v `/chat` ceste (overené grep) — data debt, nie live bug |
| `Agenticky dalsi krok - SK` | **130/130 (100 %)** | nekonzumované v `/chat` ceste — data debt, nie live bug |
| `Pouzitie v kuchyni - SK`, `Nakupne odporucanie - SK`, `Kedy odporucit - SK`, `Pozor / overit - SK` | 0/130 čisté | — |

Príklad reálnej hodnoty poľa `Chutovy profil - SK`: `"profil urci
podla nazvu produktu, kategorie a detailu na webe; nevymyslaj
zlozenie"` — toto je INŠTRUKCIA PRE AI AUTORA, nie veta o produkte.
Živo reprodukované: `"Preco prave tento?"` po `"Kikkoman 1l"` vrátilo
tento presný fragment ako zákaznícku odpoveď.

**Oprava**: `app.knowledge._is_broken_curation_placeholder()` — malý,
cielený guard s presnými, živo-overenými markermi, aplikovaný na
oboch konzumných miestach (`best_product_advice_answer()`,
`format_record()`). Kontaminovaná hodnota sa správa ako CHÝBAJÚCA
(prázdny string), nie ako neplatný vstup — zostávajúce čisté polia
(`usage`, `advisor_note`, `Kedy odporucit`, `Pozor/overit`) nedotknuté.
**Oprava zdrojových dát patrí kurátorskému/generovaciemu pipeline, nie
tejto sprinte** — zdokumentované ako data debt (Sekcia 12).
Permanentný regresný test: `scripts/trust_audit.py --broken-curation-content`
(nový, offline, žiadny `/chat`/OpenAI call).

## 5. Kľúčové zistenie #2 — "Prečo tento?" neexistovalo ako mechanizmus

**Section 17 zadania túto schopnosť explicitne nazýva "CORE
CAPABILITY".** Živo overené PRED opravou: holé `"preco"`/`"prečo"`
už bolo zachytené `app.main.is_article_info_intent()`'s širokým
markerom (pre genuine informačné otázky ako "prečo je citrónová tráva
aromatická?"), takže "why"-followup o SKUTOČNOM predchádzajúcom
odporúčaní bol ticho pohltený FAQ/article-info kaskádou:

- `"Preco mi odporucas tento?"` po `use_case_advice` odpovedi →
  reinterpretované ako čerstvé doslovné vyhľadávanie produktu →
  `"Áno, ryža na sushi v tomto variante máme v ponuke:"` (úplná
  non-odpoveď).
- `"Preco prave tento?"` po `product_search` → pristálo na
  nesúvisiacom Products_AI zázname a vrátilo fragment jeho textu
  doslovne (kombinované so Zistením #1 vyššie, v tomto konkrétnom
  prípade to bol rozbitý template placeholder).

**Oprava** (Sekcia 50 Gate C — "small evidence→customer-reason
adapter", nie nový evidence framework):

- `app.session_state.get/set/clear_last_explanation()` — malé, nové
  session pole, presne v tvare `active_recipe_id`/`active_use_case`/
  `active_basket_use_case`. Vyčistené pri reset (`apply_reset()`).
- `app.explanation` (nový, malý modul) — `looks_like_why_followup()`
  (úmyselne užšie než `is_article_info_intent()`'s bare "preco" —
  vyžaduje demonštratívum "tento"/"ten druhý" alebo sloveso
  "odporúčaš" súčasne), `compose_why_answer()` (deterministický,
  ŽIADEN LLM, znovupoužíva PRESNE tú istú `reason_code` slovnú
  zásobu ako `app.comparison`/`app.use_case_advice`/
  `app.basket_completion` — žiadny nový reason-code namespace).
- `execute_use_case_advice()`/`execute_comparison()`/
  `execute_basket_completion()` (`app/workflow_executor.py`) — každý
  po vlastnom (nezmenenom) rozhodnutí uloží malý, serializovateľný
  súhrn cez `set_last_explanation()`. **Žiadny nový decision_id** —
  znovupoužíva existujúce rozhodnutie (Section 47).
- `execute_why_followup()` — nový executor, zaradený do kaskády
  hneď po `basket_completion` (main.py), pred recipe-followup/
  article-info blokom, presne tam kde bol "preco" predtým ticho
  pohltený.

**Nejednoznačnosť (Section 18)**: `use_case_advice` je vždy
jednoznačné (1 rola/rodina na ťah). `comparison` len pri
`CLEAR_WINNER` (inak čestne vysvetlí, že jednoznačný víťaz
neexistuje). `basket_completion` len keď PRESNE 1 rola má vyriešený
produkt — inak CLARIFY s vymenovaním všetkých položiek (živo
overené: `"Preco tento?"` po sushi košíku s 4 rolami → "Ktorú
položku presne máte na mysli? V tomto zozname mám viac produktov:
...").

**"Prečo nie ten druhý?" (Section 19)**: nikdy nevymýšľa negatívny
dôvod pre porazeného. Živo overené: `"Vybrala som ho na základe:
cena - nemám doklad na to, že ten druhý produkt je horší, len že
tento vyhráva v tomto porovnaní."`

## 6. Explanation claim model (Section 12)

Existujúce primitíva už postačujú — **žiadna nová ontológia**
(Section 12 zadania: "Do not create unnecessary ontology if existing
primitives suffice"). `compute_confidence()`'s HIGH/MEDIUM/LOW/
INSUFFICIENT + `decide()`'s RECOMMEND/CLARIFY/ABSTAIN už POKRÝVAJÚ
FACT/SUPPORTED_RELATION/LIMITATION/UNKNOWN triedy zo zadania:
RECOMMEND+HIGH ≈ SUPPORTED_RELATION s asertívnym tónom, ABSTAIN ≈
UNKNOWN, `missing_dimensions`/`abstain_reason` ≈ LIMITATION.

## 7. Prečo `recommendation_evidence`/nová evidence trieda nebola rozšírená

Section 50 explicitne preferuje B/C/D pred F ("large explanation
framework", neautorizované bez dôkazu nevyhnutnosti). Charakterizácia
dokázala presne 2 reálne medzery (Sekcie 4-5) — obe vyriešené malými,
cielenými zmenami reusujúcimi existujúcu evidenciu. Žiadny dôkaz
nevyžadoval nový evidence systém.

## 8. Per-workflow readiness matrix (Section 74/80)

| Workflow | Evidencia | Customer-safe dôvody | Limitácie | Gate | Stav |
|---|---|---|---|---|---|
| `product_search` | žiadna štruktúrovaná (relevance) | exact match/brand/size/typ (existujúci `answer_composer`) | — | D | LIVE (nezmenené) |
| `product_advice` | Products_AI (taste/usage) | taste/usage text | 63/130 bolo rozbitých, teraz opravené | C→D | LIVE_WITH_LIMITATIONS (data debt zostáva) |
| `product_comparison` | `ComparisonDecision` (plne deterministické) | price/unit_price/size/brand/product_type | qualitative → ABSTAIN | D | LIVE |
| `use_case_advice` | `RoleEvidence` | product_type_fit/use_case_fit | MEDIUM confidence hedge | D | LIVE |
| `replacement_products` | žiadna štruktúrovaná (V2.16c audit) | generický "podobná alternatíva" text | žiadna dietary equivalence claim | C | LIVE_WITH_LIMITATIONS (nezmenené touto sprintou) |
| `recipe_shopping` | `RecipeShoppingPlan` (deterministické) | AVAILABLE/ALREADY_SATISFIED/NOT_AVAILABLE | žiadne quantity dáta | C | LIVE_WITH_LIMITATIONS (nezmenené) |
| `basket_completion` | `BasketRole` (deterministické) | product_type_fit, ALREADY_COVERED | nejednoznačnosť pri >1 role | D | LIVE |
| `cross_sell` | curated + FBT | RECIPE_COMPLETION/USE_CASE_COMPLETION/PRODUCT_COMPLEMENT intro | frontend rendering gap (V2.15e.3, nezmenené) | C | LIVE_WITH_LIMITATIONS (nezmenené) |
| `attribute_query` | V2.16b taxonomy | brand/size/gluten_free | vegan/vegetarian/halal zostáva UNKNOWN | C | LIVE_WITH_LIMITATIONS (nezmenené) |
| **`why_followup`** | **znovupoužitá z 3 zdrojov vyššie** | **product_type_fit/use_case_fit/price_fit/...** | **CLARIFY pri nejednoznačnosti, honest "no reason" bez kontextu** | **D (nové)** | **LIVE (táto sprinta)** |

## 9. Ranking invariance (Section 63/79)

Overené priamo — identické product ID/poradie pred a po zmene pre
reprezentatívne dopyty (`"Co potrebujem na pho?"`, `"Co potrebujem na
sushi?"`, `"nahrada za rybiu omacku vegan"`, `"Aku ryzu odporucas na
sushi?"`) — **ŽIADNA zmena kandidátov ani poradia**. Očakávané, keďže
žiadna zmena tejto sprinty sa nedotkla retrieval/ranking kódu.

## 10. LLM/search call count (Section 66/67)

**0 nových LLM callov** — `app.explanation.compose_why_answer()` je
plne deterministický. **0 nových search callov pre "why" followup** —
znovupoužíva len session-uložené produkty, nikdy nevolá retrieval
znova.

## 11. Testy a kvalita

- Nový súbor `tests/test_recommendation_explanation_v2_16e.py`
  (21 testov, pokrýva oba nálezy + regresné kontroly).
- Rozšírený `scripts/trust_audit.py` o `--broken-curation-content`
  (permanentný, offline regresný test pre Zistenie #1).
- Cielená regresia (`basket_completion`/`recipe_shopping`/
  `substitution`/`decision_observability`/`rt0013`): 142 passed.
- Plná regresná sada, V2.10, consistency: pozri finálny report.

## 12. Zostávajúci data debt

- `Products_AI`'s `Predajny argument - SK`/`Agenticky dalsi krok -
  SK` sú 100 % kontaminované rozbitou šablónou — momentálne
  nekonzumované v `/chat`, teda nie live bug, ale ak sa niekedy
  zapoja, VYŽADUJÚ regeneráciu zdrojových dát (kurátorský/generovací
  pipeline, mimo rozsahu tejto sprinty).
- `replacement_products` nemá štruktúrovanú evidenciu (V2.16c
  zistenie, nezmenené) — "why this substitute" preto nie je
  pripojené do `app.explanation` (žiadny zdroj evidencie na
  znovupoužitie).
- `recipe_shopping`/`cross_sell` majú vlastné, nezávislé "why"
  potreby, ktoré táto sprinta zámerne nerieši (mimo minimálneho
  rozsahu).

## 13. Zostávajúci architektonický debt

- `app.explanation`'s "posledná diskutovaná rola" pre basket je
  binárna (presne 1 vyriešená rola = jednoznačné) — nerozlišuje
  "zákazník práve pýtal na konkrétnu rolu" kontext, ktorý
  `recipe_shopping`'s `last_recipe_ingredient_concept` už má. Budúce
  malé rozšírenie by mohlo túto kontextovú stopu znovupoužiť.

## 14. AUTO_PROMOTION

**AUTO_PROMOTION = FALSE** (nezmenené). `NEXT_PROGRAM_PHASE =
WAIT_FOR_EMPIRICAL_DATA` nezmenené. V2.15f nezačaté. Žiadny learning/
ranking kód nebol dotknutý.
