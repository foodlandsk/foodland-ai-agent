 # Foodland AI Agent – Feature Roadmap & Aktuálny stav
**Dátum:** 2026-07-27  
**Autor:** Claude (Cowork session)  
**Kontext:** Hodnotenie 9 navrhovaných features voči aktuálnemu stavu codebase pred implementáciou Luigi's Box-štýlu.

---

## Súhrn aktuálneho stavu

| Vrstva | Stav | Poznámka |
|---|---|---|
| Chat endpoint `/chat` | ✅ produkčný | intent router, guardrails, rate limit, konverzačná pamäť, session_id, intent analytika |
| Vyhľadávanie | ⚠️ tokenové | weighted keyword scoring, SK morfológia, ~20 ručných synonymov – bez BM25/embeddings |
| Grounding | ⚠️ existuje, nevyužitý | `grounding.py` je kompletnyý (175 riadkov), ale nie je zadrôtovaný do `/chat` |
| Analytika | ⚠️ čiastočná | logovanie otázok (ts, hash, message, intent, session_id) – bez event-level trackingu |
| CrossSell | 🔴 bug | 2 140 CrossSell záznamov v knowledge.json je ignorovaných (BUG-04 z(architect analysis) |
| Autocomplete | 🔴 chíba | žiadny endpoint |
| Facety/filtre | 🔴 chíba | `/products/search` existuje bez filter params |
| Recommenders | 🔴 chýba | žiadne standalone widgety |
| Merchandising | 🔴 chýba | žiadny rules engine |
| Multilingual | ⚠️ SK-only | základná podpora, bez CZ/EN/HU/PL/VI |
| Widget UX | ⚠️ základný | chat funguje, bez feedback/quick prompts/click trackingu |

---

## Feature 1 – Autocomplete endpoint

**Popis:** `GET /autocomplete?q=...` → produkty, kategórie, značky, recepty, top otázky

### Aktuálny stav
Neexistuje. `/chat` robí full search len pri kompletnom dotazi. žiadne prefix/incremental matching.

### Čo treba
```
app/autocomplete.py  (nový súbor ~150 riadkov)
  autocomplete_products(q, products, limit=4) – prefix + token match
  autocomplete_categories(q, products, limit=3) - distinct product_type
  autocomplete_brands(q, products, limit=3) - distinct brand
  autocomplete_questions(q, top_questions_cache, limit=3) - z analytics

main.py
  GET /autocomplete?q=&limit= endpoint (~30 riadkov)
  cache top questions z question_analytics.jsonl (refresh každých 60s)
```

### Výstup
```json
{
  "products": [{"title": "...", "url": "...", "price": 2.99, "image": "..."}],
  "categories": ["Ramen", "Ryža", "Omáčky"],
  "brands": ["Ottogi", "Nongshim"],
  "top_questions": ["Ďo je to gochujang?", "Bezlepkové cestoviny"]
}
```

### Odhad práce
**2–3 dni** | Priorita: 🔴 Vysoká (viditeľnosť, quick win)

### Poznámky
- Recepty a articles vyžadujú prístup ku knowledge sekciám
- Trending otázky: použiť top-N z"question_analytics.jsonl" ako interim

---

## Feature 2 – Hybridné vyheľadávanie

**Popis:** BM25 + synonymá + embeddings + business boosts (dostupnosť, cena, popularita)

### Aktuálny stav
`app/search.py` (201 riadkov) – pure tokenové skórovanie:
- title × 8, brand × 5, category × 4, description × 1
- exact match v title: +12
- availability: +1 (iba tie-break)
- ~20 ručných synonymov pre konkrétne slová
- **Žiadne IDF váhy, žiadne embeddings, žiadne behavioral signals**

### Čo treba (postupne)

**Fáza 2a – BM25 (2–3 dni, bez infraštruktúry)**
```python
def build_bm25_index(products: list[Product]) -> BM25Index:
    # IDF = log((N - df + 0.5) / (df + 0.5))
    # BM25 score = sum(IDF × (tf × (k1+1)) / (tf + k1 × (1 - b + b × dl/avgdl)))
```

### Odhad práce
- Fáza 2a (BM25): **2–3 dni** | Priorita: 🟡 Stredná
- Fáza 2b (synonymá JSON): **1–2 dni** | Priorita: 🔴 Vysoká (SK/CZ/EN typy)
- Fáza 2c (embeddings): **1–2 týždne** | Priorita: 🟢 Nízka (infraštruktúra)
- Fáza 2d (behavioral): **závisí od event dát** | Priorita: 🟢 Nízka

---

## Feature 3 – Event analytika

**Popis:** Trackovanie impression, click, add_to_cart, search_submit, autocomplete_select, no_result, conversion

### Aktuálny stav
`log_question()` logguje len otázek + počet výsledkov + intent + session_id.  
Widget JS: žiadne event firing. Žiadny `POST /events` endpoint.

### Čo treba

Backend (1 deň):
```python
class EventRequest(BaseModel):
    session_id: str
    event_type: Literal["impression","click","add_to_cart","no_result",
                         "autocomplete_select","search_submit","conversion"]
    product_sku: str | None = None
    query: str | None = None
    position: int | None = None
```

Widget JS (1 deň):
```javascript
fireEvent({event_type: "impression", query: text, products: result.products.map(p=>p.sku)})
fireEvent({event_type: "click", product_sku: sku, query: currentQuery, position: idx})
```

### Odhad práce
**2–3 dni** | Priorita: 🔴 Vysoká (blokuje behavioral ranking, merchandising, recommenders)

---

## Feature 4 – Facet/filter API

**Popis:** `price_min/max`, `brand`, `availability`, `category`, `dietary`

### Aktuálny stav
`/chat` endpoint existuje, ale bez filter parametrov. `Product` dataclass má: `price`, `availability`, `brand`, `product_type`.

### Čo treba
```python
class ProductFilter(BaseModel):
    price_min: float | None = None
    price_max: float | None = None
    brand: list[str] | None = None
    availability: Literal["in_stock","out_of_stock","all"] = "all"
    category: list[str] | None = None
    dietary: list[str] | None = None
```

### Odhad práce
**2–3 dni** | Priorita: 🟡 Stredná

---

## Feature 5 – Recommender modely

**Popis:** `similar_products`, `frequently_bought_together`, `recipe_ingredients`, `basket_upsell`, `trending_products`

### Aktuálny stav
**BUG-04:** 2 140 CrossSell záznamov v `knowledge.json` je KOMPLETNE IGNOROVANÝCH.  
`related_products_for_subject()` používa iba 9 hardcoded kuchyňa-query párov.

### Čo treba

Quick win – CrossSell fix (0.5 dňa):
```python
def crosssell_from_knowledge(knowledge, subject, products_list, limit) -> list[dict]:
    nm_subject = normalize(subject)
    for record in knowledge.get("sections", {}).get("CrossSell", []):
        if nm_subject in normalize(record.get("Produkt", "")):
            queries = [record.get(f"Cross-sell {i}", "") for i in range(1, 6) if record.get(f"Cross-sell {i}")]
            results = []
            for q in queries:
                hits = search_products(products_list, q, 2)
                results.extend(hits)
            return results[:limit]
    return []
```

Nové endpointy (2–3 dni):
```
GET /recommend/similar?sku=&limit=
GET /recommend/recipe?name=&limit=
GET /recommend/trending?limit=
POST /recommend/basket
```

### Odhad práce
- CrossSell fix: **0.5 dňa** | Priorita: 🔴 Okamžitá (bug!, 2140 záznamov ignorovaných)
- Basic recommenders: **2–3 dni** | Priorita: 🟡 Stredná
- ML-based FBT/trending: **závisí od event dát** | Priorita: 🟢 Neskór

---

## Feature 6 – Merchandising pravidlá

**Popis:** Pin/hide/boost produkty, sezónne kampane, vypredané dole

### Aktuálny stav
Žiadny rules engine. Jediný "merchandising": `availability == "in_stock"` → +1 bod.

### Čo treba
```json
// data/merchandising.json
{"pins":[{"sku":"FL-001","query":"ramen","position":1}],"hidden":["FL-999"],"boosts":[{"brand":"Ottogi","multiplier":1.5}],"campaigns":[{"name":"Letná grillovačka","active_from":"2026-07-01","active_to":"2026-08-31","category":"Grilovacie omáčky","boost":2.0}]}
```

### Odhad práce
**2–3 dni** | Priorita: 🟢 Nízka (závisí od biznis pravidiel)

---

## Feature 7 – Lepšia práca s jazykmi

**Popis:** SK/CZ/EN/HU/PL/VI dotazy, typo tolerancia, systematický synonymický slovník

### Aktuálny stav
- `normalize()` odstráni diakritiku (SK → ASCII)
- ~20 hardcoded synonymov v `tokenize()`
- Stopwords: 44 SK slov
- **Žiadna EN/HU/PL/VI podpora, žiadna typo tolerancia**

### Čo treba

**Fáza 7a – Synonymický slovník JSON (1–2 dni):**
```json
{"ramen":["ramyon","ramien","instantné rezance"],"kimchi":["kimci","kimchee"],"bezlepkový":["gluten-free","gluten free","bez lepku","GF"],"gochujang":["gochudžang","gocujang"],"miso":["miso pasta"],"tofu":["sójový syr","bean curd"]}
```

**Fáza 7b – CZ/EN podpora (2–3 dni):**  
*Fáza 7c – Fuzzy matching / typo tolerancia (3–5 dní):**

### Odhad práce
- Fáza 7a (synonymá JSON): **1 –2 dni** | Priorita: 🔴 Vysoká (okamžitý dopad)
- Fáza 7b (CZ/EN): **2–3 dni** | Priorita: 🟡 Stredná
- Fáza 7c (fuzzy): **3–5 dní** | Priorita: 🟡 Stredná

---

## Feature 8 – Grounding zapojiť priamo do odpovedí

**Popis:** `grounding.py` existuje, treba ho zadrôtovať po každej AI odpovedi

### Aktuálny stav
`grounding.py` (175 riadkov) je kompletný a otestovaný, ale nie je volaný z `main.py`.  
v `/chat` je len `sanitize_answer_links()` – stripped-down verzia bez cenovej kontroly.

### Čo treba (QUICK WIN – ~20 riadkov v main.py)
```python
from app.grounding import validate_answer, collect_allowed_urls, collect_allowed_prices

allowed_urls = collect_allowed_urls(matches, knowledge_matches)
allowed_prices = collect_allowed_prices(matches)
grounding_result = validate_answer(answer_text, allowed_urls, allowed_prices=allowed_prices, strict_prices=True)
if grounding_result.has_violations:
    logger.warning("Grounding violations: %s", grounding_result.violations)
answer_text = grounding_result.sanitized_answer
```

### Odhad práce
**2–4 hodiny** | Priorita: 🔴 OKAMŽITÁ (kód je hotový, len treba zadrôtovať)

---

## Feature 9 – Widget rozšírenie

**Popis:** Quick prompts, feedback (👍/👎), "zobraziť viac", prefill z product detail, klik tracking

### Aktuálny stav
Widget (`widget.js`, 42K po refaktore) má:
- Chat s konverzačnou pamäťou ✅
- session_id ✅
- 3D Mei avatar (novo) & ✅
- Žiadny feedback mechanizmus
- Žiadne quick prompts
- Žiadny klik tracking

### Čo treba

Quick prompts (0.5 dňa) – len widget.js:
```javascript
const QUICK_PROMPTS = ["🍜 Odporúčaš ramen?", "🌶️ Čo je gochujang?", "🍱 Bezlepkové produkty"];
```

Feedback (0.5 dňa)– widget.js + `/events`:
```javascript
fireEvent({event_type: "feedback", rating: +1/-1, session_id})
```

### Odhad práce
- Quick prompts: **0.5 dňa** | Priorita: 🟡 Stredná
- Feedback: **0.5 dňa** | Priorita: 🔴 Vysoká (tréining dáta)
- Klik tracking: **1 deň** | Priorita: 🔴 Vysoká (závisí od `/events`)

---

## Prioritizovaný akčný plán

### Sprint A – Okamžité quick wins (1–2 dni)

| # | Feature | Čas | Súbory |
|---|---|---|---|
| A1 | Grounding zadrôtovať (F8) | 4h | `main.py` ~20 riadkov |
| A2 | CrossSell BUG-04 fix (F5) | 4h | `main.py` ~30 riadkov |
| A3 | Synonymický slovník JSON (F7a) | 1d | `data/synonyms.json` + `search.py` |
| A4 | Widget feedback (F9) | 4h | `widget.js` (potrebuje A5) |

### Sprint B – Core API rozšírenia (3–5 dní)

| # | Feature | Čas | Súbory |
|---|---|---|---|
| B1 | Event analytika `/events` (F3) | 2d | `main.py` + `widget.js` |
| B2 | Autocomplete endpoint (F1) | 2d | `app/autocomplete.py` + `main.py` |
| B3 | Recommend endpointy (F5) | 2d | `main.py` + nové route |
| B4 | Widget klik tracking (F9) | 1d | `widget.js` |

### Sprint C – Search quality (1 týždeň)

| # | Feature | Čas | Súbory |
|---|---|---|---|
| C1 | BM25 index (F2a) | 2d | `app/search.py` refaktor |
| C2 | Facet/filter API (F4) | 2d | `app/search.py` + `main.py` |
| C3 | CZ/EN synonymá (F7b) | 2d | `data/synonyms.json` rozšírenie |
| C4 | Merchandising rules (F6) | 2d | `app/merchandising.py` (nový) |

### Sprint D – ML & infraštruktúra (2–3 týždne)

| # | Feature | Závislosti | Stav |
|---|---|---|---|
| D1 | Embeddings + vector store | Cloud vector DB | ✅ Hotovo – lokálne embeddings (`app/embeddings.py`), `GET /search/semantic`, `POST /admin/embeddings/rebuild` |
| D2 | Behavioral ranking (CTR boosts) | 4+ týždne event dát | ✅ Hotovo – `app/behavioral.py`, zapojené do `search.py`; bezpečný cold-start (pooled baseline + hard `BEHAVIORAL_MIN_TOTAL_IMPRESSIONS` gate, default 1000) drží signál neaktívny, kým sa nenazbiera dostatok reálnej návštevnosti |
| D3 | FBT z add_to_cart dát | 4+ týždne event dát | ✅ Hotovo – `app/fbt.py`, zapojené do `basket_recommendations()`; rovnaký bezpečný gate (`FBT_MIN_ADD_TO_CART_EVENTS` default 200, `FBT_MIN_PAIR_COUNT` default 3) drží FBT páry neaktívne, kým nie je dosť add_to_cart dát |

### Sprint E – Posledný zvyšok Feature 9 (widget feedback)

| # | Feature | Súbory | Stav |
|---|---|---|---|
| E1 | Widget feedback (👍/👎) (zvyšok F9) | `app/widget.js` | ✅ Hotovo – tlačidlá pod každou odpoveďou asistenta posielajú `POST /events` s `event_type: "feedback"` a `rating: +1/-1` (backend kontrakt bol hotový už od B1); po kliknutí sa nahradia poďakovaním, aby sa predišlo duplicitnej spätnej väzbe |

Týmto je Feature 9 (Widget rozšírenie) kompletne hotová – quick prompts, prefill z product detail, "zobraziť viac" a klik tracking už boli hotové zo skorších šprintov, feedback bol posledný chýbajúci kúsok. **Všetkých 9 pôvodne navrhovaných features je teraz hotových.**

### Sprint F – Personalizácia (nad rámec pôvodných 9 features)

| # | Feature | Súbory | Stav |
|---|---|---|---|
| F1 | Personalizácia per-užívateľských odporúčaní | `app/main.py` | ✅ Hotovo |

**Stav pred šprintom:** personalizácia už existovala pre `/chat` (hlavný widget flow) a `/search/autocomplete` – perzistentný per-klientský profil (`user_memory`, keyed cez `client_id`, prežíva naprieč session) sleduje afinitu k značkám, kuchyniam, diétnym termínom a témam z každej doterajšej správy, a `personalize_products()`/`personalize_recipes()` podľa neho preraďujú výsledky.

**Čo pribudlo:** `/recommend/basket` zbieral `client_id` v request modeli, ale nikdy ho nepoužil. Teraz načíta rovnaký `user_memory` profil a preradí basket odporúčania podľa afinity cez existujúcu `personalize_products()` (reorder-only, takže správanie je bit-identické, keď profil neexistuje). Personalizácia je tak konzistentná naprieč všetkými hlavnými odporúčacími povrchmi (`/chat`, `/search/autocomplete`, `/recommend/basket`).

### Sprint G – Personalizácia: posledný odporúčací endpoint

| # | Feature | Súbory | Stav |
|---|---|---|---|
| G1 | Personalizácia `/recommend/similar` | `app/main.py` | ✅ Hotovo |

`/recommend/similar` bol jediný zostávajúci odporúčací endpoint bez `client_id`. Teraz prijíma voliteľný `client_id` query parameter, načíta `user_memory` profil a preradí odporúčania rovnakou `personalize_products()` (opäť reorder-only, bez zmeny správania bez `client_id`). Personalizácia je týmto kompletná naprieč všetkými odporúčacími povrchmi: `/chat`, `/search/autocomplete`, `/recommend/basket`, `/recommend/similar`. (`/recommend/trending` ostáva zámerne nepersonalizovaný – "trending" je globálny sociálny dôkaz, nie individuálne prispôsobenie.)

### Sprint H – Personalizácia: posledný verejný endpoint (GET /autocomplete)

| # | Feature | Súbory | Stav |
|---|---|---|---|
| H1 | Personalizácia `GET /autocomplete` | `app/main.py`, `app/autocomplete.py` | ✅ Hotovo |

Posledný verejný endpoint bez `client_id` (widget interne používa personalizovaný `/search/autocomplete` ako primárnu cestu, `/products/suggest` len ako fallback – tie už boli personalizované/nepotrebovali zmenu). `autocomplete_products()` teraz vracia aj `brand`, aby mal `personalize_products()` z čoho počítať afinitu; endpoint prijíma voliteľný `client_id` a preradí návrhy rovnakým mechanizmom ako všade inde. Tým je personalizácia hotová naprieč úplne všetkými verejnými vyhľadávacími/odporúčacími endpointmi.

### Sprint I – CZ/EN viacjazyčnosť: detekcia zámeru (Fáza 7b)

| # | Feature | Súbory | Stav |
|---|---|---|---|
| I1 | Detekcia zámeru rozumie aj EN/CZ dopytom | `app/main.py` | ✅ Hotovo (čiastočne) |

**Čo sa zistilo naživo:** pôvodná detekcia zámeru bola založená výhradne na slovenských kľúčových slovách/regexoch. Test "What soy sauce do you recommend for sushi?" sa mylne klasifikoval ako `recipe` zámer (chyba: `is_recipe_intent()` používal `token.startswith(("rec", "recep"))`, čo omylom zachytávalo aj anglické "recommend"/"record") a vrátil 3 náhodné recepty namiesto sójových omáčok.

**Čo sa opravilo:**
- `is_recipe_intent()` zúžený na skutočný koreň "recept" (SK aj CZ zdieľajú rovnaké slovo).
- Rozšírené markery pre FAQ/recept/náhodný recept/alergény/článok o anglické ekvivalenty a hŕstku CZ slov, ktoré sa líšia od SK aj po odstránení diakritiky (jak/ako, proč/prečo, rozdíl/rozdiel, článek/článok, vrácení/vrátenie).
- Opravená finálna vetva `detect_allergen_intent()`, ktorá kontrolovala len jednoduché "l" v "alerg" – anglické "allergy"/"allergic" (dvojité "l") cez ňu neprešlo ani po pridaní markera.
- System prompt v `/chat` už neodpovedá natvrdo po slovensky, ale v jazyku zákazníkovej otázky (predvolene slovensky, ak jazyk nie je jasný).

**Overené naživo** (lokálne aj na produkcii, s reálnymi OpenAI volaniami): EN/CZ otázky na recept, doručenie a alergény sa teraz správne smerujú a dostávajú relevantný kontext; slovenské dopyty bez zmeny správania.

**Zámerne mimo rozsahu:** endpointy s "fast path" (`should_use_fast_chat_answer`) stále vracajú slovenský template text okolo správne nájdených produktov/receptov – opravená bola len KLASIFIKÁCIA zámeru (aby zákazník dostal správny obsah), nie jazyk hotových šablónových viet. Rovnako neboli rozšírené hlbšie pomocné markery (`RELATED_INTENT_MARKERS`, `ALREADY_HAVE_MARKERS`, `SHOPPING_LIST_MARKERS`), ktoré ovplyvňujú len doplnkové odporúčania, nie hlavnú vetvu zámeru.

### Sprint J – CZ/EN viacjazyčnosť: anglické varianty fast-path šablón

| # | Feature | Súbory | Stav |
|---|---|---|---|
| J1 | Anglické varianty hardcoded šablónových odpovedí | `app/main.py` | ✅ Hotovo |

Dokončenie medzery zo Sprint I: `allergen_safety_answer()`, `recipe_answer()`, `random_recipes_answer()`, `recipe_products_answer()`, `shopping_list_answer()`, `fallback_answer()` a hardcoded reťazce pre "unknown"/"no match" teraz majú anglickú vetvu vedľa slovenskej. Pridaná `detect_query_language()` – jednoduchá heuristika (angličtina vs. všetko ostatné; SK/CZ sa zámerne nerozlišuje, českí zákazníci bežne čítajú slovenský text), vyžaduje ≥2 zásahy markerov, aby jedno anglické slovo (napr. názov produktu) nesprávne neprepočíta jazyk.

**Zámerne mimo rozsahu:** FAQ odpovede pochádzajú priamo z `knowledge.json` (dáta, nie kód) a zostávajú po slovensky – preložiť by ich znamenalo pridať EN obsah do knowledge base, nie len kód.

**Vedľajšia oprava:** pri úprave `fallback_answer()` sa odstránil nedosiahnuteľný mŕtvy kód (kód po nepodmienenom `return`), pozostatok podobný duplicitám z predošlého čistenia.

**Overené naživo** na produkcii aj lokálne: EN otázky na recept a vyhľadávanie produktov teraz dostávajú anglické šablónové odpovede so správnymi produktmi; slovenské dopyty bez zmeny.

### Sprint K – Admin dashboard

| # | Feature | Súbory | Stav |
|---|---|---|---|
| K1 | Vizuálny admin dashboard namiesto surových JSON endpointov | `app/admin_dashboard.html` | ✅ Hotovo |

Jednostránkový, samostatný HTML dashboard (`app/admin_dashboard.html`), automaticky dostupný cez existujúci `/static` mount na `/static/admin_dashboard.html` – žiadne nové backend routy ani auth logika, len UI nad existujúcimi `/admin/analytics/*` endpointmi. Token-gated na strane klienta: token sa zadá raz, uloží sa do `sessionStorage` (nie trvalo) a posiela sa ako `x-admin-token` pri každom volaní.

Záložky: Prehľad (súhrn + slabé miesta + odporúčané akcie), Otázky, Bez výsledku, Zámery, Eventy, Behavioral ranking (so stavom aktívne/neaktívne a vysvetlením cold-start gate), FBT (rovnako), Embeddings (tlačidlo na prebudovanie).

**Overené naživo** na produkcii s reálnym admin tokenom – všetkých 8 záložiek zobrazuje skutočné dáta, neplatný token aj prázdne stavy sa správne ošetrujú.

### Sprint L – Prvé nálezy z admin dashboardu: onigiri bug + 4 nové FAQ

| # | Feature | Súbory | Stav |
|---|---|---|---|
| L1 | Oprava zámeny onigiri → sushi | `app/main.py` | ✅ Hotovo |
| L2 | 4 nové FAQ z reálnych zákazníckych otázok | `data/knowledge.json`, `app/main.py` | ✅ Hotovo |

Dashboard z Sprintu K okamžite ukázal reálny problém: `RELATED_SUBJECT_ALIASES` mal "sushi" kontrolované pred "onigiri", a sushi alias "nigiri" je substring slova "onigiri" – každá otázka na onigiri sa mylne vyhodnotila ako sushi otázka a nikdy nenavrhla formu na onigiri. Opravené preradením poradia (presnejší subjekt "onigiri" sa kontroluje prv); overené, že skutočné "nigiri" otázky stále správne vedú na "sushi".

Pridané 4 FAQ záznamy zo skutočných zákazníckych otázok (sledovanie objednávky, kamenná predajňa – adresa Stará Vajnorská 19, Bratislava + hodiny, lehota na osobný odber, parita cien predajňa/e-shop) – obsah potvrdený majiteľom biznisu, adresa/hodiny predajne krížovo overené na foodland.sk/kontakt. Dve z týchto otázok (o predajni) sa predtým vôbec nedostali k FAQ vyhľadávaniu – `FAQ_INTENT_MARKERS` nemal žiadny marker pre "predajňa"/"store".

**Overené naživo** na produkcii: všetkých 5 opráv (4 FAQ + onigiri) funguje správne s aktuálnym obsahom.

### Sprint M – Support-escalation odpoveď pre "chýba zloženie"

| # | Feature | Súbory | Stav |
|---|---|---|---|
| M1 | Odpoveď na sťažnosti "zloženie na stránke chýba" | `app/main.py` | ✅ Hotovo |

Dashboard odhalil klaster nespokojných zákazníckych správ – všetky o tom, že zoznam zloženia chýba na konkrétnej produktovej stránke, a bot na to donekonečna odpovedal "skontrolujte zloženie v detaile produktu" (presne to, čo zákazník hovoril, že tam nie je). Jeden zákazník napísal, že bot je "dosť na nič".

Overil som, že náš produktový feed zloženie vôbec neobsahuje (len marketingový popis) – ide o reálnu obsahovú medzeru, nie niečo, čo dá vyriešiť vyhľadávanie. Pridaný `is_missing_composition_complaint()` detektor kontrolovaný pred `allergen_safety` vetvou, ktorý namiesto opakovania rovnakej neužitočnej rady nasmeruje zákazníka na podporu (eshop@foodland.sk, +421 2 4468 1527).

**Overené naživo** na produkcii s presným textom reálnych sťažností.

**Odporúčanie pre biznis:** produktový feed/stránky by mali obsahovať pole so zložením – bez neho bot (ani žiadny iný nástroj) nevie zákazníkom pri tejto konkrétnej otázke pomôcť inak než presmerovaním na podporu.

### Sprint N – Oprava holých nadväzujúcich otázok o konkrétnom produkte

| # | Feature | Súbory | Stav |
|---|---|---|---|
| N1 | Oprava follow-up otázok mimo rozpoznaných "dish subjects" | `app/main.py` | ✅ Hotovo |

Reálny prípad z dashboardu: zákazník sa spýtal na "Jujube eaglobe", dostal správny produkt, potom sa opýtal holou nadväzujúcou otázkou "Má kôstky?" a dostal úplne nesúvisiace produkty (Mirin, Dashi, Ponzu omáčka).

Dva súbežné bugy: (1) `is_context_followup()` nerozpoznávala "kôstky" ako signál nadväznosti vôbec; (2) po oprave tohto sa uplatnil starší mechanizmus, ktorý prepisoval kontext hrubým "subject" zo session pamäte – ten je znečistený AKÝMKOĽVEK zhodným produktom z predošlého vyhľadávania (jujube vyhľadávanie vrátilo aj nesúvisiace japonské rezance, čo označkovalo celú session ako "japonska_kuchyna"). Pridané nové pole `last_top_product_title` (najlepšia zhoda z POSLEDNÉHO vyhľadávania zákazníka, nie zašumený zoznam), ktoré má prednosť pred hrubým subjectom pri nadväzujúcich otázkach mimo rozpoznaných "dish subjects".

**Overené naživo** na produkcii s naozaj čistým klientským profilom (predošlé testy s rovnakým IP bez explicitného `client_id` boli skreslené vlastnou personalizáciou z opakovaného testovania) – nadväzujúca otázka teraz správne vráti jujube produkty, vrátane jedného explicitne označeného "bez kôstok".

---

### Sprint O – Doplnenie a oprava FAQ o doprave, platbe, predajni a vernostnom programe

| # | Feature | Súbory | Stav |
|---|---|---|---|
| O1 | 3 nové FAQ overené zo stránky/od zákazníka (parkovanie, pôvod produktov, vypredané produkty) | `data/knowledge.json` | ✅ Hotovo |
| O2 | Oprava zastaranej FAQ, ktorá tvrdila, že vernostný program neexistuje | `data/knowledge.json` | ✅ Hotovo |
| O3 | Oprava FAQ scoring bugu – špecifická pod-otázka prehrávala nad všeobecnou | `app/main.py` | ✅ Hotovo |
| O4 | Doplnenie slovenského markera "vernostn" do FAQ_INTENT_MARKERS | `app/main.py` | ✅ Hotovo |

Pri príprave FAQ pre bežné zákaznícke otázky (doprava, platba, vrátenie tovaru, predajňa) som si najprv overil fakty priamo z `foodland.sk/obchodne-podmienky`, `/o-nas`, `/kontakt` a `/doprava-platby/`, plus reálne parametre vernostného/kreditového programu priamo od zákazníka. Pri porovnaní s existujúcim obsahom `knowledge.json` sa ukázalo, že **väčšina týchto tém tam už bola** – veľmi podrobne (44 pôvodných FAQ záznamov vrátane presných detailov o kreditoch, doprave, platbe v predajni). Z 13 pôvodne pripravených nových FAQ som preto 9 duplicitných odstránil a ponechal len 3 skutočne nové (parkovanie, pôvod produktov, správanie pri vypredaní).

Pri tejto kontrole sa zároveň našli dva reálne produkčné bugy:
- **Zastaraná FAQ** (`Má Foodland vernostný program...?` → "Nie...") priamo protirečila susedným záznamom, ktoré podrobne popisujú kreditový systém. Opravená na správne "Áno, formou kreditov...".
- **Scoring bug** v `best_direct_faq_answer()`: pod-otázky v `knowledge.json` majú prázdne pole `Kategória` (vizuálne zoskupenie v zdrojovom hárku), čo znamenalo, že nikdy nezískali bonus za zhodu kategórie. Dôsledok: špecifická otázka "Dá sa v predajni platiť kartou?" prehrávala nad všeobecnou "Aké platobné metódy podporujete?", aj keď mala vyšší základný score. Opravené doplnením "forward-fill" kategórie z predchádzajúceho záznamu.
- **Chýbajúci marker**: `FAQ_INTENT_MARKERS` mal len anglické "loyalty", takže slovenská otázka o "vernostnom programe" vôbec nespadla do FAQ vetvy a skončila ako bežné vyhľadávanie produktov (ryža, poukazy). Doplnený marker "vernostn".

**Overené naživo** na produkcii – otázky o parkovaní, vernostnom programe aj platbe kartou v predajni teraz vracajú správne, konkrétne odpovede.

### Sprint O.1 – Oprava trackingu zásielok nájdená pri kontrole dashboardu

| # | Feature | Súbory | Stav |
|---|---|---|---|
| O5 | Oprava routovania "sledovanie zásielky/objednávky" do FAQ | `app/main.py` | ✅ Hotovo |

Po nasadení Sprint O som skontroloval dashboard (záložka "Bez výsledku") a našiel reálny, ten istý deň zaznamenaný no-result dotaz: **"sledovanie zasielok"**. Dva súbežné bugy:
- `FAQ_INTENT_MARKERS` mal marker "zasielk", ktorý nezachytáva genitív množného čísla "zásiel**ok**" (chýba "k" pred koncovkou), a žiadny marker pre "sledov" (tracking) – otázka preto vôbec nespadla do FAQ vetvy.
- Aj po oprave markerov mala otázka nulový token-overlap s existujúcou FAQ "Kde môžem sledovať stav objednávky?" (Sprint L), takže potrebovala vlastnú priamu skratku podľa vzoru existujúcich skratiek pre dopravu/platbu. Táto skratka musela byť vyhodnotená PRED skratkou pre "spôsoby doručenia" – slovo "zásiel" totiž spúšťa obe, takže poradie rozhoduje, ktorá (správna, špecifickejšia) odpoveď sa vráti.

**Overené naživo** – "sledovanie zasielok" teraz vracia správnu odpoveď o sledovaní objednávky cez zákaznícky účet namiesto všeobecnej informácie o spôsoboch doručenia.

---

### Sprint P – Systematický audit FAQ scoringu proti krátkym zákazníckym formuláciám

| # | Feature | Súbory | Stav |
|---|---|---|---|
| P1 | Audit všetkých 51 FAQ záznamov proti realistickým krátkym dotazom | – (analýza) | ✅ Hotovo |
| P2 | 9 nových priamych skratiek pre potvrdené vysoko-rizikové prípady | `app/main.py` | ✅ Hotovo |

Namiesto čakania na ďalšie reálne dáta z dashboardu sme sa opýtali: dá sa systematicky nájsť, kde bot dáva sebaisto znejúcu, ale vecne nesprávnu odpoveď pri bežnej krátkej formulácii (napr. "parkovanie" namiesto celej vety)? Otestovaných všetkých 51 FAQ záznamov s realistickými krátkymi dotazmi cez skutočný `is_faq_intent()` + `best_direct_faq_answer()` reťazec (nie izolovane).

**Prvý pokus bol plošná zmena scoring vzorca** (bonus keď všetky slová z dotazu zákazníka sú obsiahnuté v texte FAQ otázky). Regresný sken cez všetkých 51 prípadov ukázal, že táto zmena síce opravila niektoré prípady, ale ticho pokazila iné (napr. "sledovanie objednavky" začalo omylom vracať odpoveď o registrácii). Zmena bola zahodená v prospech bezpečnejšieho, cieleného prístupu.

**Namiesto toho** sme presne identifikovali 12 prípadov, kde otázka prejde cez FAQ bránu AJ dostane sebaisto znejúcu, ale nesprávnu odpoveď (nie len "nič nenájdené" – to je bezpečný fallback). Z toho 9 bolo reálne zavádzajúcich a dostalo vlastnú priamu skratku (rovnaký vzorec ako pri "sledovanie zasielok"):
- Dobierka (domov aj s kuriérom) miešaná s platbou kartou v predajni alebo so všeobecným prehľadom spôsobov doručenia
- "Do ktorých krajín doručujete" miešané so všeobecným prehľadom spôsobov doručenia
- Neprevzatie objednávky (no-show) miešané s "ako objednať" (úplne irelevantné)
- Vrátenie peňazí (všeobecne aj cez dobropis) miešané s kontaktom na reklamácie pri nesprávnom produkte
- Výmena tovaru v predajni prehrávala remízu s nesúvisiacou reklamáciou v predajni (obe majú rovnaký kategóriový bonus)
- Platnosť kreditov a upozornenie na vypršanie miešané so všeobecným úvodom o kreditovom programe (chýbal konkrétny fakt)

Zvyšné 3 hraničné prípady sme nechali tak – dva sú takmer duplicitné FAQ záznamy (odpoveď je vecne rovnaká, len z iného záznamu), tretí už obsahuje požadovaný fakt, len vnorený vo všeobecnejšom úvode.

**Overené naživo** na produkcii pre všetkých 9 opravených prípadov, plus regresne otestované proti zvyšných 42 FAQ záznamov, aby nová skratka nepokazila niečo, čo predtým fungovalo (žiadna regresia).

---

### Sprint Q – Oprava "Parkovanie" hláseného priamo používateľom

| # | Feature | Súbory | Stav |
|---|---|---|---|
| Q1 | Marker + priama skratka pre otázky o parkovaní | `app/main.py` | ✅ Hotovo |

Reálne nahlásené: *"na otazky Parkovanie, kde sa da zaparkovat odpovedal produktmi"*. Sprint P audit tento prípad síce zachytil (#48 v zozname 51), ale zaradil ho do kategórie "brána blokuje → bezpečný fallback" (`FAQ_INTENT_MARKERS` nemal žiadny marker pre parkovanie vôbec), takže sa nepovažoval za prioritný. Realita bola horšia než predpoklad: fallback na `product_search` nevrátil čistú "nič nenašiel" správu, ale náhodné nesúvisiace produkty (korenie, instantná polievka, džús) – zle vyzerajúca odpoveď, nie neutrálna.

Dva súbežné bugy: (1) chýbajúci marker "park" – oprava jedným riadkom; (2) aj s otvorenou bránou zdieľa "parkovanie" (podstatné meno) s vlastným textom FAQ otázky len koreň slova, nie "zaparkovať" (sloveso) – token-overlap dosiahol len skóre 1 z potrebných 3, takže potrebovala vlastnú priamu skratku podľa vzoru Sprint P.

**Ponaučenie:** kategória "brána blokuje" zo Sprint P auditu nie je automaticky nízko-riziková – ak fallback vráti nesúvisiace produkty namiesto čistého "nenašiel som", ide o rovnako zlý zákaznícky zážitok ako sebaisto znejúca zlá FAQ odpoveď.

**Overené naživo** na produkcii pre presné znenie nahlásenej otázky aj jej variácie.

---

### Sprint R – Kompletný FAQ prehľad + oprava posledného zastaraného záznamu

| # | Feature | Súbory | Stav |
|---|---|---|---|
| R1 | Export všetkých 51 FAQ o prevádzke ako referenčný dokument pre používateľa | – (dokument) | ✅ Hotovo |
| R2 | Oprava zastaranej odpovede "plánuje Foodland spustiť vernostný program?" | `data/knowledge.json` | ✅ Hotovo |

Na požiadanie som spracoval a odovzdal kompletný zoznam všetkých 51 produkčných FAQ o prevádzke (Nákup, Predajňa, Doprava, Platby, Reklamácie, Vrátenie tovaru, Registrácia, Vernostný program, Produkty), zoradených podľa kategórie ako referenčný dokument.

Pri manuálnej kontrole tohto exportu sa našiel posledný zvyšný zastaraný záznam: *"Plánuje Foodland v budúcnosti spustiť vernostný program?"* mal odpoveď "webová stránka takýto program neuvádza" – priamo protirečiacu susedným záznamom o fungujúcom kreditovom programe (rovnaký typ nekonzistencie, aký sme opravili pri inom zázname v Sprint O). V praxi to zákazníkom neškodilo (bot pri podobných otázkach reálne vracia správnu odpoveď z iného záznamu vďaka scoringu), ale samotný zápis v databáze bol zavádzajúci. Odpoveď zosúladená s ostatnými kredit-záznamami.

**Overené naživo** na produkcii.

---

### Sprint S – Oprava "alternatíva k Kikkoman sójovej omáčke" vracajúcej nesúvisiace produkty

| # | Feature | Súbory | Stav |
|---|---|---|---|
| S1 | Detekcia porovnávacej formulácie ("iná X ako Y") ako zámeru náhrady | `app/main.py` | ✅ Hotovo |
| S2 | Oprava kolízie "tamari" × "tamarind" v dopyte na náhrady sójovej omáčky | `app/main.py` | ✅ Hotovo |

Reálne nahlásené: zákazníci sa pýtali na alternatívu ku Kikkoman sójovej omáčke a dostali aj nesúvisiace produkty. Dva súbežné bugy:

- `detect_replacement_subject()` rozpoznávala len explicitné markery ("nahrad", "namiesto", "alternativ", "čím"). Formulácia **"iná sójová omáčka ako Kikkoman"** žiadny z nich neobsahuje, takže spadla do vetvy `related_products` (cross-sell) namiesto `replacement_products` – a cross-sell vrátil všeobecné "čo sa hodí spolu" páry (mirin, ryžový ocot) namiesto konkurenčných značiek. Pridaná detekcia porovnávacej konštrukcie "iná/iné/iný ... ako", chránená kontrolou hraníc slova (medzery na oboch stranách), aby sa nezachytávali náhodné zhody vo vnútri iných slov (napr. "vitamín**a** ako doplnok").
- Aj po správnom smerovaní do `replacement_products` mal dopyt pre "sojova omacka" ako prvý fallback query samostatné slovo **"tamari"**, ktoré sa v bežnom produktovom vyhľadávaní zhoduje aj s **"Tamarind"** (úplne iná vec – ovocie, nie omáčka). Výsledok obsahoval tamarindový džús, sušené tamarindy a polievkový základ namiesto sójových omáčok iných značiek. Dopyt spresnený na "tamari sojova omacka", čo problém úplne odstráni a navyše správne vytiahne konkurenčné značky (MEGACHEF, AYUKO, MARUKIN).

**Overené naživo** na produkcii – dotaz teraz vracia výhradne sójové omáčky vrátane alternatívnych značiek k Kikkoman.

---

### Sprint T – Systematické dočistenie náhrad + oprava "spôsoby dopravy"

| # | Feature | Súbory | Stav |
|---|---|---|---|
| T1 | Rozšírenie tamari/tamarind opravy na `rybacia omacka` a `tamari` subjekt | `app/main.py` | ✅ Hotovo |
| T2 | Oprava "spôsoby dopravy" vracajúcej náhodné produkty | `app/main.py` | ✅ Hotovo |

Po Sprint S som na požiadanie systematicky prešiel **všetky** dopyty v `REPLACEMENT_PRODUCT_QUERIES` (nie len sójovú omáčku) a našiel rovnaký bug ešte dvakrát: samostatné slovo "tamari" ako fallback dopyt aj pri kategórii **rybacia omáčka** a pri samotnom subjekte **tamari** – s tou istou Tamarind kontamináciou. Opravené rovnakým spôsobom (spresnenie na "tamari sojova omacka"). *(Poznámka: prvý pokus o opravu omylom upravil nesúvisiaci slovník `SPECIAL_PRODUCT_QUERIES`, ktorý má tiež kľúč "tamari" – vrátené späť a opravené na správnom mieste.)*

Popri tom nahlásené: **"spôsoby dopravy foodlandu"** vrátilo náhodné produkty (ryžu, darčekové poukazy). Dva súbežné bugy rovnakého typu ako pri "zásielok":
- Marker `"doprava"` (nominatív) sa nezhodoval so slovom **"dopravy"** (genitív) – skrátené na koreň "doprav", ktorý pokrýva všetky pády.
- Aj po otvorení brány chýbal spúšťač "doprav" pre samotnú skratku "spôsoby doručenia" – doplnené.
- Rozšírenie spúšťača ale spôsobilo novú regresiu: "kedy je doprava zadarmo?" (zdieľa koreň "doprav") by teraz nesprávne dostalo odpoveď o spôsoboch dopravy namiesto o zadarmo doprave. Opravené pridaním kombinovanej kontroly "zadarmo" + "doprav" (odolnej voči poradiu slov) do skratky pre cenu dopravy, vyhodnocovanej PRED skratkou pre spôsoby doručenia.

**Overené naživo** na produkcii pre všetky varianty vrátane regresného testu na "kedy je doprava zadarmo?".

---

### Sprint U – Všeobecná AI odpoveď na recepty/jedlá mimo databázy

| # | Feature | Súbory | Stav |
|---|---|---|---|
| U1 | `general_ai_recipe_answer()` – prísne ohraničená AI odpoveď pre recepty mimo databázy | `app/main.py` | ✅ Hotovo |
| U2 | Voliteľný `max_tokens` parameter pre `_call_openai_with_retry()` | `app/main.py` | ✅ Hotovo |

Na návrh používateľa: keď sa zákazník opýta na jedlo/recept, ktorý **nie je** v databáze receptov Foodlandu (napr. reálny dnešný prípad "Vindaloo" z dashboardu), bot doteraz odpovedal iba genericky "skúste napísať recept na kimchi alebo pad thai". Teraz namiesto toho skúsi krátku všeobecnú kulinársku odpoveď cez OpenAI – čo je to za jedlo, aké typy surovín sa naň zvyčajne používajú.

**Kľúčové bezpečnostné pravidlo** (rovnaký grounding princíp ako všade inde v projekte): systémový prompt explicitne zakazuje AI spomínať konkrétny názov produktu, značku, cenu, sklad alebo odkaz, akoby ich Foodland reálne predával – ide výhradne o všeobecnú kulinársku znalosť, nie o ponuku Foodlandu. Odpoveď vždy končí jasným upozornením, že presný recept v databáze nemáme. Ak OpenAI nie je nakonfigurované alebo volanie zlyhá, bot sa ticho vráti k pôvodnej generickej odpovedi – žiadna zmena správania pre prostredia bez API kľúča.

Po prvom nasadení sa pri live overení ukázalo, že odpoveď sa orezáva uprostred vety (zdieľaný OpenAI helper mal defaultný limit 120 tokenov, nastavený pre bežné 1–2-vetové odpovede appky, čo na vysvetlenie + disclaimer nestačilo). Opravené pridaním voliteľného `max_tokens` parametra do `_call_openai_with_retry()` (existujúce volania bez zmeny správania) a nastavením 280 tokenov pre tento konkrétny prípad.

**Overené naživo** na produkcii – kompletná, neorezaná odpoveď o jedle Vindaloo bez zmienky o konkrétnom Foodland produkte.

### Sprint U.1 – Oprava skutočnej cesty pre holý názov jedla

Po nasadení Sprint U prišlo hlásenie: reálny zákazník napísal len **"Vindaloo"** (bez slova "recept") a stále dostal starú generickú odpoveď "Nenašla som presný produkt...". Príčina: `is_recipe_intent()` vyžaduje kulinárske kľúčové slovo (recept, variť, pho, ramen...) – holý názov jedla bez takého slova sa vôbec nedostane do `recipe_subject` vetvy, kam bola AI odpoveď zapojená. Namiesto toho skončí v úplne inej, poslednej "nič sa nenašlo" vetve.

Zapojil som `general_ai_recipe_answer()` priamo do tejto skutočnej finálnej vetvy (`if not matches and not knowledge_matches`). Keďže sem teraz spadne AKÝKOĽVEK dotaz bez zhody (nielen jedlá – napr. názov produktu inej kategórie), rozšíril som prompt, aby si model najprv sám vyhodnotil, či ide vôbec o jedlo/recept/kulinárnu tému. Ak nie, odpovie doslovným kódovým slovom "NEURCITE", ktoré kód mapuje na `None` – zákazník tak pri nesúvisiacom dotaze dostane pôvodnú čestnú "nenašla som" správu namiesto vymyslenej kulinárskej odpovede na niečo, čo jedlo vôbec nie je.

**Overené naživo** – holé "Vindaloo" teraz dáva správnu AI odpoveď; kontrolný test na nesúvisiaci výraz ("babyMonster OREO") správne prešiel bežným produktovým vyhľadávaním (reálne produkty existujú), takže fallback sa ani nemusel použiť.

---

### Sprint V – Oprava "sake sety" (a podobných) vracajúcich len cross-sell namiesto skutočného produktu

| # | Feature | Súbory | Stav |
|---|---|---|---|
| V1 | `PRODUCT_SET_SIGNAL_TOKENS` – ruší cross-sell smerovanie pri set/sada/súprava dotazoch | `app/main.py` | ✅ Hotovo |

Reálne nahlásené: **"sake sety"** dostalo cross-sell odpoveď o rôznych fľašiach saké namiesto skutočných produktov **"Saké Set"**, ktoré v katalógu existujú a bežné vyhľadávanie by ich reálne našlo. Príčina: `detect_related_subject()` rozpozná "sake" ako podreťazec kdekoľvek vo vete – takže AKÝKOĽVEK dotaz obsahujúci toto slovo sa presmeruje do cross-sell vetvy skôr, než sa vôbec skúsi bežné vyhľadávanie.

Keďže slovo "set"/"sada"/"súprava" silno signalizuje, že zákazník chce konkrétny typ produktu (nie "čo sa hodí k X"), pridaná množina `PRODUCT_SET_SIGNAL_TOKENS` (set, sety, sada, súprava a ich pády, kit), ktorá pri zhode s tokenmi dotazu vynuluje `related_subject` – presne podľa vzoru, akým už kód rieši rovnaký konflikt pre `special_subject`. Bežné cross-sell formulácie ("čo sa hodí k sake", "sake na varenie") ostávajú nezmenené, keďže neobsahujú žiadne z týchto slov.

Na doplňujúcu požiadavku ("podobne ako ramen sety, sada, súprava") som overil aj ostatné kategórie – "ramen sety/sada" už fungovalo správne (aliasu "ramen" tento konflikt nepostihuje), ale slovo **"súprava"** (reálne používané v katalógu, napr. čajové súpravy) v zozname signálnych slov ešte chýbalo – doplnené pre robustnosť do budúcna.

**Overené naživo** – "sake sety" teraz vracia všetky 3 skutočné "Saké Set" produkty namiesto len fliaš saké.

---

### Sprint V.1 – Oprava "čajové sety" nachádzajúcich len Matcha sety

Nahlásené: **"Čajové sety nie sú matcha čajové sety"** – dotaz "cajove sety" vracal výhradne 17 produktov "Matcha set" (miska+metlička na prípravu matcha), ani jednu zo 4 skutočných "Japonská čajová súprava" (kanvica+šálky). Príčina: slovo "cajove" v dotaze (tvar prídavného mena) sa vôbec nezhodovalo so slovom "cajova" v názvoch produktov (iný pád/rod) – rovnaký typ chyby ako pri "doprava"/"dopravy". Opravené pridaním "cajov" prefixového synonyma do `data/synonyms.json`, podľa vzoru existujúcich "bezlepk"/"sojov" záznamov.

**Prvý pokus bol širší** – krížové prepojenie "set"/"sety" so "suprava"/"sada" ako synonymá (motivované rovnakým vzorom ako "sake sety" v Sprint V). To ale spôsobilo opačný problém: všetkých 17 Matcha setov začalo zrazu zodpovedať aj slovu "suprava", takže dlhšie názvy skutočných čajových súprav boli v BM25 rankingu (ktorý zvýhodňuje kratšie názvy) zaplavené ešte viac než predtým. Táto časť bola vrátená späť – nie je ani potrebná, keďže oprava zo Sprint V funguje výhradne cez routing (`PRODUCT_SET_SIGNAL_TOKENS`), nezávisle od synonymického slovníka.

**Overené naživo** – "cajove sety" teraz nájde skutočné čajové pomôcky/súpravy namiesto matcha setov; samostatný dotaz "matcha set" ostáva nezmenený.

---

### Sprint V.2 – Oprava "ako dlho trvá doručenie zásielok"

Nahlásené: otázka **"Ako dlho trvá doručenie zásielok?"** dostala odpoveď o *spôsoboch* dopravy (osobný odber/kuriér/Packeta) namiesto konkrétnej odpovede o *dobe trvania* doručenia (72 hodín/3 pracovné dni). Rovnaký vzorec ako pri "dobierka"/"krajiny" v Sprint P/T – obe otázky obsahujú slovo "doruc", a všeobecnejšia skratka pre "spôsoby doručenia" sa vyhodnotí skôr než konkrétnejšia.

Pridaná skratka pre "ako dlho trvá doručenie" (spúšťač: slovo "dlho" + doruc/zasiel/kurier), vyhodnocovaná PRED všeobecnou skratkou pre spôsoby doručenia.

**Overené naživo** – otázka teraz vracia správnu odpoveď o dobe doručenia; existujúce opravy z Sprint T (doprava zadarmo, spôsoby dopravy) ostávajú nezmenené.

---

### Sprint V.3 – Oprava "typy kariet" unesených témou kari (koreniaca zmes)

Nahlásené: *"Pri otázke na typy kariet doporučuje produkty, čo nie je správne"*. Otázky **"typy kariet"** a **"aký typ kariet prijímate"** (platobné karty) vracali produkty s kari korením/pastou namiesto odpovede o platobných metódach. Príčina: slovo **"kariet"** (karty, genitív množného čísla) obsahuje ako podreťazec slovo **"kari"** (koreniaca zmes) – a rozpoznávanie témy "kari" funguje na jednoduchom porovnaní podreťazca, takže si to nesprávne vyhodnotilo ako otázku o kari. Rovnaká trieda chyby ako "sake" unášajúce "sake sety" pred Sprint V.

Pridaný marker "kariet" a skratka smerujúca na existujúcu FAQ o platobných metódach – keďže sa vyhodnocuje skôr v poradí spracovania než rozpoznávanie témy "kari", vyrieši sa otázka správne skôr, než sa vôbec dostane ku kolízii. Legitímne otázky o kari ("recept na kari", "kari pasta") ostávajú nedotknuté.

**Overené naživo** – "typy kariet" teraz vracia správnu odpoveď o platobných metódach.

**Poznámka k dashboardu z pravidelnej kontroly:** preklep "ake typy akriet akceptuje" (písmená "a"/"k" preklopené) tento fix nepokrýva, keďže "akriet" neobsahuje "kari" ako podreťazec – ide o fuzzy-match kolíziu, nie substring kolíziu. Len 1 výskyt, nechané bez zásahu (naháňanie jednotlivých preklepov cez fuzzy-matching by bolo rizikovejšie než užitočné).

---

### Sprint V.4 – Oprava "Adresa firmy" vracajúcej nesúvisiaci produkt

Nájdené pri pravidelnej kontrole dashboardu: **"Adresa firmy"** a samostatné **"Adresa"** vrátili náhodný nesúvisiaci produkt (dashi vývar) namiesto adresy predajne. Slovo "adresa" vôbec nemalo marker vo `FAQ_INTENT_MARKERS`, takže sa nikdy nedostalo do FAQ vetvy. Pridaný marker a skratka smerujúca na existujúcu FAQ o kamennej predajni.

**Overené naživo** – "Adresa firmy" teraz vracia správnu adresu a otváracie hodiny.

---

### Sprint V.5 – Oprava "náhrada japonského čajníka" vracajúcej rezance a paličky

Nahlásené: **"Náhrada japonského čajníka"** vracalo instantné rezance, jedálne paličky a nože namiesto skutočných "Japonský čajník" produktov (existujú 3). Rovnaká trieda chyby ako "čajové/čajová" v Sprint V.1: slovo **"čajníka"** (genitív) sa nezhodovalo so slovom **"čajník"** v názvoch produktov, takže výsledky ovládlo len všeobecné prídavné meno "japonské/japonský", ktoré zdieľajú desiatky nesúvisiacich produktov.

Pridané prefixové synonymum "cajnik" pokrývajúce jeho pády, rovnakým spôsobom ako "cajov" predtým.

**Overené naživo** – "náhrada japonského čajníka" teraz vracia všetky 3 skutočné čajníky na prvých miestach. *(Poznámka: prvý overovací pokus kontroloval len text odpovede, ktorý sa nemenil – opravené overenie kontrolujúce skutočné produkty potvrdilo nasadenie.)*

---

### Sprint W – Pridanie reálneho receptu na Vindaloo

Používateľ upozornil, že recept na Vindaloo je "už v databáze Foodlandu" – po overení (lokálne aj naživo, 53 receptov, žiadny Vindaloo) sa ukázalo, že v skutočnosti chýbal. Používateľ následne poslal reálny odkaz: `foodland.sk/recepty/goanske-bravcove-vindaloo-bez-zemiakov/`.

Recept pridaný korektne, nielen ako záznam v `knowledge.json`:
- **Recept**: kuchyňa, názov, SK URL – iba overené polia, žiadne vymyslené odkazy pre ostatné jazykové mutácie (schéma nevyžaduje všetkých 7, stačí jeden `_url` field).
- **Mapovanie názvu na "subject"** (`RECIPE_TITLE_PRODUCT_SUBJECTS`), aby `detect_recipe_subject()` recept vôbec rozpoznal.
- **`RELATED_PRODUCT_QUERIES["vindaloo"]`**: koriandrové semienka, horčicové semienka, senovka grécka, sušené čili papričky, škorica, basmati ryža – každý výraz individuálne overený proti reálnemu katalógu pred pridaním, nie odhadnutý.
- **`MISSING_INGREDIENTS_BY_SUBJECT["vindaloo"]`**: čerstvé suroviny, ktoré Foodland nepredáva (bravčové mäso, cesnak, zázvor, ocot, cibuľa).

Všetky tri dátové štruktúry boli potrebné – tri existujúce kontrolné testy (vyžadujúce, aby mal každý recept namapovaný subject) chybu okamžite odhalili.

**Overené naživo** – "recept na vindaloo" teraz vracia skutočný recept z Foodland.sk namiesto AI fallbacku zo Sprint U.

---

### Sprint W.1 – Oprava holého "Vindaloo" stále padajúceho do AI fallbacku

Nahlásené hneď po Sprint W: holé **"Vindaloo"** (bez slova "recept") stále dávalo všeobecnú AI odpoveď a nepriložilo odkaz na skutočný recept. Príčina: `is_recipe_intent()` vyžaduje kulinárske slovo (recept/návod/postup...) – samotný názov jedla bez neho vôbec neprejde do receptovej vetvy a spadne do rovnakého "nič sa nenašlo" fallbacku zo Sprint U.1, aj keď recept už v databáze existuje.

Pridané "vindaloo" priamo do `RECIPE_INTENT_MARKERS`.

**Overené naživo** – holé "Vindaloo" teraz vracia skutočný recept s odkazom.

---

### Sprint X – Automatizovaný nástroj na hľadanie chýb (`scripts/consistency_audit.py`)

Po sérii Sprintov O–W.1, kde každú chybu nahlásil až reálny zákazník, padla otázka: *"Nechcem manuálne opravovať chyby, vieš navrhnúť spôsob overenia a opravy inak?"* Namiesto čakania na ďalšie hlásenia som postavil skript, ktorý aktívne hľadá presne tie dve triedy chýb, ktoré sa v tomto projekte opakovane vyskytli:

1. **Kolízie podreťazcov medzi markermi** – krátky marker použitý na routing (napr. "kari", "sake", "udon", "nigiri") je náhodou podreťazcom iného, nesúvisiaceho markeru (napr. "kariet", "sake sety", "gyudon", "onigiri") a v poradí kontroly vyhrá ten nesprávny. Presne trieda chýb zo Sprint V a V.3.
2. **Krehkosť voči skloňovaniu** – FAQ/recept sa nespozná pri inak skloňovanom tvare svojho kľúčového slova (napr. "čajníka" namiesto "čajník"). Trieda chýb zo Sprint V.1 a V.5.

Nástroj prehľadáva všetky routovacie slovníky (`FAQ_INTENT_MARKERS`, `RECIPE_INTENT_MARKERS`, `RELATED_SUBJECT_ALIASES`, `REPLACEMENT_SUBJECT_ALIASES`, `RECIPE_TITLE_PRODUCT_SUBJECTS`, `PREFIX_SYNONYMS`...) a hľadá páry, kde je jeden marker podreťazcom druhého bez toho, aby smerovali k rovnakému významu; známe a už overené bezpečné kolízie (napr. "nigiri"/"onigiri", "thai"/"padthai") sú v `KNOWN_SAFE_COLLISIONS`, aby sa neopakovane nehlásili.

**Prvý reálny nález**: "udon" je podreťazcom "gyudon" (hovädzia miska s ryžou – úplne iné jedlo), a keďže "udon" bol v oboch slovníkoch (`RELATED_SUBJECT_ALIASES`, `RECIPE_TITLE_PRODUCT_SUBJECTS`) skôr v poradí, každý dopyt na gyudon sa nesprávne vyhodnotil ako bežná otázka na udon rezance – existujúce a správne ingrediencie v `RELATED_PRODUCT_QUERIES["gyudon"]` (sójová omáčka, mirin, dashi, ryžový ocot) tak boli nedosiahnuteľné. Opravené rovnakým poradím ako pri onigiri/sushi. Pridaný regresný test, **overené naživo**: "čo potrebujem na gyudon" teraz vracia mirin a dashi namiesto udon rezancov.

Druhá kontrola (skloňovanie) generuje kandidátov na kontrolu, nie definitívny verdikt – Slovenčina nie je modelovaná presne, takže časť nálezov sú len rozumné odpovede na nejednoznačné, kontextu zbavené jednoslovné dopyty (napr. samotné "dopravy" bez slovesa/otázky), nie skutočné chyby. Manuálne overené naživo pre klaster okolo "doprava"/"dorucenie"/"dobierkou"/"reklamaciu" – všetky odpovede boli vecne správne, žiadna ďalšia oprava nebola potrebná.

Spustenie: `python scripts/consistency_audit.py` (obe kontroly), `--collisions`/`--declensions` samostatne.

---

### Sprint X.1 – Sémantické vyhľadávanie: overené a zamietnuté; opravené 3 zvyšné FAQ medzery

Navrhol som ako ďalší smer nasadiť existujúci (no nepoužívaný) `/search/semantic` endpoint (OpenAI embeddings nad produktmi) ako štrukturálne riešenie tried chýb z predošlých Sprintov. Pred nasadením som to overil naživo proti trom reálnym prípadom z tejto session:

- **FAQ/intent-routing chyby** (kariet, doprava, adresa) sú mimo dosahu úplne – endpoint prehľadáva len produktové embeddings, nie FAQ.
- Aj pri produktových prípadoch nebola relevancia jasne lepšia: "náhrada japonského čajníka" mala skutočný čajník až na 5. mieste, zaplavený paličkami a rezancami – rovnaký bug ako predtým, len cez iný mechanizmus.
- Reálne produkčné dáta (30 dní `/admin/analytics/summary`) ukázali len 10 unikátnych "no results" dopytov, z toho 8 boli FAQ otázky nesprávne padnuté do `product_search` intentu – sémantika nad produktmi by im nepomohla.

**Záver: nenasadené.** Náklad (ephemeral cache na Railway, nutný rebuild po každom deploy, latencia navyše) prevažuje nad zanedbateľným prínosom pri tomto objeme.

Namiesto toho som opravil klasickým spôsobom 3 zo zvyšných FAQ medzier z tej istej analýzy:

- **"Termín dodania"** – slovo "dodan" sa nenachádzalo v `FAQ_INTENT_MARKERS` ani nikde inde vo FAQ korpuse, takže sa dopyt vôbec nedostal do FAQ systému.
- **"Rýchlosť doručenia"** – dostal sa do FAQ systému cez "doruc", ale prehral proti všeobecnej skratke "spôsoby doručenia", ktorá kontrolovala len slovo "dlho", nie "rýchlosť".
- **Holé slovo "Predajňu"** – skórovalo len 1 zhodu tokenu voči FAQ o predajni (pod prahom ≥3 vo všeobecnom scoringu) a spadlo do prázdneho produktového vyhľadávania.

Pridaná skratka pre holé slovo "predajňu" je obmedzená na dopyty do 2 tokenov, aby nepreberala dlhšie vety s vlastným zámerom (napr. "dá sa v predajni platiť kartou?") – tento konkrétny regresný prípad odhalila plná test sada pred commitom a bol opravený pred nasadením.

**Overené naživo** – všetky tri dopyty teraz vracajú správnu FAQ odpoveď namiesto prázdneho výsledku.

---

### Sprint X.2 – Oprava "alternatíva ku značke X" vracajúcej viac tej istej značky

Používateľ upozornil, že treba prekontrolovať odpovede na "alternatíva/náhrada rybacej, sójovej omáčky značky X/Y". Po preskúmaní sa ukázalo, že **"alternativa ku Kikkoman sojovej omacke" vracala len ďalšie produkty značky KIKKOMAN** – presný opak toho, čo zákazník žiada. Dve súčasne pôsobiace príčiny:

1. `REPLACEMENT_SUBJECT_ALIASES` pre "sójová omáčka" obsahovalo len tvary "sojova omacka"/"sojovu omacku" – skloňovaný tvar "sojovej omacke" sa nezhodoval so žiadnym aliasom, takže `detect_replacement_subject()` spadol do fallbacku, ktorý ako "subject" použil celý zvyšný text vrátane značky ("kikkoman sojovej omacke"). Ten sa následne v poslednom fallbacku vyhľadal ako obyčajný text a slovo "kikkoman" vyhralo ako keyword zhoda.
2. Aj keď sa subjekt vyriešil správne, nič neodfiltrovalo spomenutú značku z výsledkov.

**Oprava**: doplnené skloňované tvary do aliasov (`sojovej omacke/omacky`, `rybacej omacky/omacke`, `rybacou/sojovou omackou`); nová funkcia `detect_mentioned_replacement_brand()`, ktorá rozpozná značku v dopyte (porovnáva len proti značkám skutočne predávaným v danej kategórii, aby sa minimalizovalo riziko falošnej zhody); `alternative_products_for_subject()` teraz prijíma `exclude_brand` a filtruje ňou všetky tri úrovne fallbacku (kurátorské Alternatívy, kategóriové dopyty, obyčajné vyhľadávanie).

Mimochodom opravené aj: **"Nemám Kikkoman sójovú omáčku, čo použiť?"** – prirodzená formulácia žiadosti o náhradu, ktorá nemala žiadny spúšťací marker vôbec (pridané "nemam"/"nemame").

**Overené naživo** – "alternativa ku Kikkoman sojovej omacke" vracia HEALTHY BOY/Marukin/Pearl River Bridge (žiadny Kikkoman); "cim nahradim Squid Brand rybaciu omacku" vracia Pearl River Bridge/Ayuko/Kikkoman (žiadny Squid Brand).

---

### Sprint Y – Externý code review: 5 nálezov, 4 opravené priamo + rozšírenie Sprint X.2

Používateľ poslal 5 nálezov z nezávislého code review s prosbou posúdiť odôvodnenosť a prípadne opraviť. Všetkých 5 sa potvrdilo ako reálne:

1. **`refresh_feed()` mohol potichu vymazať celý katalóg** – pri prázdnom SK feede sa `products` prepísalo na `[]` bez výnimky. Horšie, než nález popisoval: `load_multilang_feeds()` interne pohlcuje chyby per-jazyk (sieťová chyba, HTTP chyba, zlý XML) a kľúč jednoducho vynechá – bežný výpadok feedu teda nikdy nevyvolal výnimku, ktorú by `feed_refresh_loop()`-ov try/except zachytil. **Oprava**: guard – pri prázdnom novom katalógu sa ponechá starý a nastaví `last_feed_refresh_error`.
2. **PII v analytics logoch** – `log_question()`/`log_event()` hashovali identitu klienta, ale ukladali surový text otázky/query. **Oprava**: extrahovaná zdieľaná `redact_pii()` z `redact_memory_text()`, aplikovaná na oba log path.
3. **Chýbajúce prípony pre statické assety** – `app/mei-avatar.png`, `foodland-symbol.png`, `foodland-mei-avatar-rigged.glb` existujú v `app/`, ale `UTF8StaticFiles.ALLOWED_SUFFIXES` povoľovalo len textové formáty (momentálne nič na ne neodkazuje, ale pripravené pre budúcu avatar funkciu). **Oprava**: pridané `.png/.jpg/.jpeg/.webp/.svg/.glb`, bez vynúteného textového charsetu.
4. **README dokumentuje `POST /admin/reload-feed`, endpoint neexistuje** – aj `ADMIN_RELOAD_TOKEN`/`ADMIN_ANALYTICS_TOKEN` fallback (nález 5) sú prepojené otázky s reálnym prevádzkovým dopadom (nový privilegovaný endpoint vs. zmena auth správania existujúcich 9 admin endpointov naživo) – **zatiaľ neopravené, čaká na rozhodnutie používateľa**.

K tomu používateľ počas práce spresnil požiadavku zo Sprint X.2 explicitne: náhrada musí vždy zostať v rovnakej produktovej kategórii (sójová omáčka → sójová omáčka), nikdy iný produkt. Testovaním sa našiel súvisiaci, dovtedy neznámy prípad: **holá značka bez kategórie** ("alternativa Kikkoman", žiadne "sojova omacka") padala do obyčajného vyhľadávania podľa značky a vracala náhodné produkty Kikkoman naprieč kategóriami (kimchi základ, wok omáčka, teriyaki marináda) namiesto sójovej omáčky. Pridaná `resolve_unambiguous_sauce_brand()`: ak holá značka predáva iba JEDNU z dvoch sledovaných kategórií (overené: jedine MEGACHEF predáva obe, všetky ostatné značky v katalógu sú jednoznačné), rieši sa priamo na ňu.

**Chyba v procese overovania a jej dôsledok**: pri nasadzovaní tejto opravy sa produkcia naživo správala inak než rovnaký kód lokálne (prázdny zoznam produktov namiesto 6 alternatív) – napriek overenému zhodnému zdrojovému kódu na GitHube. Príčinu sa nepodarilo jednoznačne dohľadať; pri diagnostike sa zistilo, že `intent="replacement_products"` nikdy neprechádza rýchlou šablónovou odpoveďou (`should_use_fast_chat_answer()` ho nepovoľuje) – **každý testovací dopyt na `/chat` s touto témou teda reálne volá OpenAI**, aj keď textová odpoveď vyzerá ako pevná šablóna. Počas ladenia tohto konkrétneho problému to viedlo k opakovanému volaniu na OpenAI cez viacero testovacích požiadaviek – presne to, čomu sa malo predchádzať. Akonáhle to vyšlo najavo, ďalšie naživo-testovanie bolo okamžite zastavené.

Namiesto ďalšieho naživo-ladenia konkrétnej príčiny bola opravená všeobecnejšia trieda problému: `alternative_products_for_subject()` teraz, ak vylúčenie značky nechá všetky tri úrovne fallbacku prázdne, skúsi znova bez vylúčenia. AI-generovaná odpoveď pre `replacement_products` vždy tvrdí "nižšie sú alternatívy" bez ohľadu na to, či `matches` je prázdne – prázdny zoznam produktov teda predtým znamenal sebavedomo znejúcu odpoveď bez akéhokoľvek produktu pod ňou. Poistka zaručuje reálny, relevantný výsledok v oboch prípadoch.

**Stav overenia**: jediný finálny naživo test (po dôkladnom zvážení nákladu) potvrdil, že poistka funguje – zákazník už nikdy nedostane prázdny zoznam. Nepotvrdilo sa však, že `resolve_unambiguous_sauce_brand()` už funguje spoľahlivo priamo na produkcii pre holú značku (vrátila produkty Kikkoman namiesto konkurenčných značiek – poistka teda zafungovala, primárna cesta zatiaľ nie). Toto zostáva otvorené na budúce doladenie, ideálne bez opakovaného naživo-testovania cez `/chat` (napr. dočasným logovaním namiesto pokus-omyl).

---

### Sprint Y.1 – Automatický "trust audit runner" (`scripts/trust_audit.py`)

Priama reakcia na Sprint Y: namiesto ručného spot-checku dvoch značiek (Kikkoman, Squid Brand) po poistke proti prázdnym výsledkom vznikol nový skript, tretí v rade vedľa `consistency_audit.py` (routovacie kolízie/skloňovanie) a existujúcej test sady – tento kontroluje inú dimenziu: **či sa odpoveď bota niekedy môže rozchádzať s tým, čo naozaj našiel**.

Dva testy, oba úplne offline (žiadny FastAPI server, žiadne volanie na OpenAI):

1. **`--empty-alternatives`** – pre každú z 13 kategórií v `REPLACEMENT_SUBJECT_ALIASES` a KAŽDÚ značku, ktorá sa v nej reálne predáva, zavolá `alternative_products_for_subject(..., exclude_brand=znacka)` a overí, že výsledok nie je nikdy prázdny. Toto je systematické preverenie poistky zo Sprint Y naprieč celým katalógom (17+ značiek len pri sójovej omáčke), nielen dvomi ručne otestovanými prípadmi.
2. **`--pii-leak`** – sada syntetických správ s emailom/telefónom overuje, že `redact_pii()` ich vždy odstráni pred zápisom do analytics logu.

Dôvod, prečo to musí byť offline skript a nie opakované `/chat` požiadavky: `intent="replacement_products"` nikdy nejde cez rýchlu šablónu (`should_use_fast_chat_answer()`) – každý živý test tejto triedy chýb by teda reálne zavolal OpenAI, presne to, čo Sprint Y už raz spôsobilo neúmyselne.

**Výsledok prvého behu**: 0 nálezov v oboch kontrolách – poistka drží naprieč celým katalógom, nielen pri Kikkoman/Squid Brand.

Spustenie: `python scripts/trust_audit.py` (obe kontroly), `--empty-alternatives`/`--pii-leak` samostatne.

---

### Sprint Z – Pridanie reálneho receptu na Kuracie Karaage

Používateľ poslal odkaz na reálny recept: `foodland.sk/recepty/japonske-vyprazane-kura-kuracie-karaage/`. Na rozdiel od Vindaloo (Sprint W) mal "karaage" už existujúci `RELATED_PRODUCT_QUERIES` záznam (cross-sell fungoval ešte predtým, než recept existoval), ale chýbal záznam v `Recipes`, mapovanie názvu na subjekt aj `MISSING_INGREDIENTS_BY_SUBJECT`.

Pridané: záznam receptu do `knowledge.json`, `RECIPE_TITLE_PRODUCT_SUBJECTS`, `MISSING_INGREDIENTS_BY_SUBJECT["karaage"]` (kuracie stehná, čerstvý zázvor, citrón, biela kapusta – žiadne z nich Foodland nepredáva), a "karaage" priamo do `RECIPE_INTENT_MARKERS` (rovnaká oprava ako Sprint W.1, aby holé "Karaage" bez slova "recept" fungovalo tiež).

Pri overovaní proti reálnemu receptu (40–50g kukuričného škrobu na obaľovanie) sa zistilo, že kukuričný škrob v existujúcom cross-sell zozname úplne chýbal – pridaný, ale prvý pokus ho pridal na koniec zoznamu, takže sa pri predvolenom limite 6 produktov nikdy nezobrazil (`related_products_for_subject()` berie jeden produkt na dopyt v poradí zoznamu, a zoznam mal 7 položiek). Odhalil to nový regresný test pred commitom – zoznam preusporiadaný tak, aby škrob predbehol dve okrajovejšie položky (cesnak, sezamový olej).

**Overené naživo** – "recept na karaage" vracia skutočný recept z Foodland.sk (intent `recipe`, rýchla šablónová odpoveď bez volania na OpenAI).

---

### Sprint Z.1 – Oprava náhodných produktov pri "čo mám kúpiť, keď mám alergiu"

Skontroloval dashboard (bez nových kritických nálezov mimo už riešeného) a nahlásená chyba: **"Co ma kupit ked ma alergiu na lepok"** správne rozpoznalo alergén ("lepok") a vrátilo správnu bezpečnostnú odpoveď ("neodporúčam produkt len podľa názvu, overte zloženie"), ale k nej pripojilo 6 úplne nesúvisiacich produktov – liči nektár, senovku grécku, instantnú pho polievku, čili rezance, mangové čatní, massaman kari pastu.

Príčina: `allergen_product_query()` už správne rozpoznávalo gramaticky správne "čo mám kúpiť" ako všeobecnú žiadosť o odporúčanie (vráti "", teda žiadne produkty). Problém bol v poradí krokov – čistiaci krok (`cleanup_patterns`) najprv odstráni samostatné slovo "ma" (určené pre frázy typu "produkt MÁ lepok"), a až POTOM sa kontroluje, či je zvyšný text všeobecná žiadosť. Pri hovorovom "čo **ma** kúpiť" (namiesto "mám") sa teda "ma" odstránilo skôr, než sa vôbec stihlo porovnať s "čo mam kupit" – zvyšný pokrútený text ("co kupit ked alergiu na") sa potom použil ako doslovný vyhľadávací dopyt, čo vysvetľuje náhodné výsledky.

**Oprava**: pridané "co ma kupit"/"co si ma kupit" medzi rozpoznávané všeobecné frázy, plus nová kontrola na CELÝ pôvodný text (nie až po čistení) hneď po kontrole konkrétneho produktu – takže konkrétny produkt v otázke má stále prednosť, ale všeobecná žiadosť sa už zachytí skôr, než ju čistenie znetvorí.

**Overené naživo** – "Co ma kupit ked ma alergiu na lepok" teraz vracia iba bezpečnostnú odpoveď, žiadne produkty.

---

### Sprint Z.2 – Pridanie "ocot" ako related_subject a overenie Kikkoman opravy

Používateľ sa opýtal, či bot rozumie nadväzujúcim otázkam v konverzácii. Otestoval som naživo scenár "aký ocot máte?" → "čo mám kúpiť k tomu?" a zistil som, že "ocot" (na rozdiel od "ryžový ocot", ktorý má vlastný subjekt) nemal vôbec nastavené `RELATED_SUBJECT_ALIASES`, takže nadväzujúca otázka spadla do obyčajného vyhľadávania nad kontextovaným textom (ktorý obsahuje názov posledného produktu) – náhodou vrátilo ĎALŠIE octy namiesto skutočného odporúčania.

**Oprava**: pridaný subjekt "ocot" (kontrolovaný AŽ PO "ryzovy_ocot" – rovnaká trieda kolízie ako gyudon/udon, keďže "ocot" je podreťazec "ryzovy ocot"), s cross-sell zoznamom overeným proti katalógu (cukor, sezamový olej, sójová omáčka, cesnak, čili omáčka).

Prvý pokus omylom vložil zoznam do nesprávneho slovníka (`RECIPE_SHOPPING_CORE_QUERIES` namiesto `RELATED_PRODUCT_QUERIES` – obe majú zhodou okolností kľúč `"ryzovy_ocot"`, na ktorý som sa pri hľadaní miesta na vloženie omylom naviazal) – odhalilo sa to až testom skutočného výstupu funkcie, nie len kontrolou zápisu v slovníku.

**Zámerný kompromis** (potvrdený s používateľom): priama otázka "aký ocot máte?" teraz tiež ukáže krížový predaj namiesto samotných octov – rovnaké správanie ako existujúci "gochujang"/"kimchi". Zachované kvôli konzistencii, keďže oprava opravy by znamenala stratu pôvodnej opravy (obe otázky idú cez rovnakú funkciu, niet spôsobu ako rozlíšiť "ukáž mi produkt" od "ukáž mi čo sa hodí k nemu").

**Overené naživo** (dvoma po sebe idúcimi požiadavkami s rovnakým session_id, keďže `related_products` intent ide cez OpenAI, nie rýchlu šablónu) – druhá otázka teraz vracia zmysluplné položky (mirin, ryžový ocot, dashi, sladká čili omáčka, sezamový olej), nie náhodné produkty. Presné položky sa líšia od izolovaného testu, pretože nadväzujúci mechanizmus reťazí kontext na POSLEDNÝ zobrazený produkt (tentoraz sójová omáčka, keďže tá bola prvá v poradí prvej odpovede) – existujúca vlastnosť pamäte relácie, nie niečo nové zavedené touto opravou.

Mimochodom skontrolovaný dashboard kvôli nahláseným chybám pri dopytoch na KIKKOMAN: záznam "alternativa kikkoman" (count 29) má `last_seen` nezmenené od Sprint Y – ide o starú stopu z vtedajšieho testovania, nie o pokračujúci problém. Čerstvý naživo test ("alternativa Kikkoman") teraz správne vracia 6 produktov od iných značiek (Yan Wal Yun, Hutaku, ABC, Lee Kum Kee), žiadny Kikkoman – oprava zo Sprint Y funguje správne, žiadny ďalší zásah nebol potrebný.

---

### Sprint Z.3 – Dve reálne chyby pri priamych dopytoch na konkrétnu značku ("chcem X od Y")

Používateľ poslal screenshot: **"Chcem sojovu omacku od kikkoman"** vrátilo SEMPIO a DEK SOM BOON – ani jeden Kikkoman produkt, napriek tomu, že Kikkoman sójová omáčka je skladom a správne označená značkou (overené cez živý autocomplete). Predchádzajúci lokálny test s izolovaným volaním `cached_search_products` dal SPRÁVNY výsledok (samé Kikkoman), takže rozdiel musel byť niekde v plnom `search_products` pipeline, ktorý som postupne prešiel:

- `strict_product_match`, tokenizácia a `brand_hits` fungujú správne – "kikkoman" prežije tokenizáciu a každý Kikkoman SKU dostane bonus `+5*brand_hits`.
- Priamo skontrolovaný `/admin/analytics/behavioral-rankings` na produkcii: jeden reálny Kikkoman SKU (Ponzu variant, FL_6600) má skutočne podpriemernú CTR (17 zobrazení, 0 klikov oproti ~3,5% priemeru) – čo ho posadí na dno klampovaného rozsahu behaviorálneho násobiteľa (0,5×). Toto NIE je hypotéza, ale overený fakt z reálnych dát.

**Oprava**: keď zákazník výslovne pomenuje značku produktu (`brand_hits > 0`), behaviorálny násobiteľ sa na tento produkt vôbec neaplikuje – explicitná zhoda značky je oveľa silnejší a istejší signál relevancie než priemerná CTR popularita a nemal by sa ňou riediť. Bežné dopyty bez pomenovania značky fungujú nezmenené.

Pri diagnostike tohto problému používateľ ukázal **druhý, súvisiaci bug**: **"Yamasa sojova omacka"** dostalo odpoveď v štýle krížového predaja ("skvelo pasuje k tomu tamari sójová omáčka alebo mirin...") odporúčajúcu úplne INÚ značku (Kikkoman), nie samotnú Yamasa sójovku, ktorú si zákazník pýtal – podľa používateľa **"ten bug sa prejavuje u všetkých značiek"**.

Príčina: fráza "sójová omáčka" (a ~150 ďalších kategórií/jedál) je registrovaná v `RELATED_SUBJECT_ALIASES` pre krížový predaj ("čo sa hodí k X"). Táto zhoda sa spúšťa na akúkoľvek správu obsahujúcu danú frázu bez ohľadu na to, aká značka je pred ňou – a keďže `related_subject` smeruje priamo na krížový predaj, kód sa nikdy ani nepozrie, či si zákazník nepýta konkrétny pomenovaný produkt.

**Oprava**: znovupoužitá existujúca funkcia `detect_mentioned_replacement_brand()` (zo Sprint Y) – ak `related_subject` zachytí frázu A správa obsahuje reálnu značku, ktorá v danej kategórii skutočne predáva produkty, `related_subject` sa vynuluje a dopyt prejde do bežného vyhľadávania (rovnaká vrstva kaskády ako existujúci `PRODUCT_SET_SIGNAL_TOKENS` override zo Sprint V). Dopyty bez pomenovanej značky (napr. "aký ocot máte?") zostávajú nezmenené – zámerný kompromis zo Sprint Z.2 platí ďalej.

**Overené naživo** – "Yamasa sojova omacka" teraz vracia `intent: product_search` s produktmi YAMASA (4 zo 6 výsledkov); opätovne overené aj Kikkoman oprava ("chcem sojovu omacku od kikkoman" → všetkých 6 produktov Kikkoman).

---

### Sprint Z.4 – Jazyk odpovede, nechcený krížový predaj pri FAQ a doplnenie fráz pre cenu/dobu doručenia

Používateľ poslal dva súvisiace screenshoty z tej istej konverzácie:

1. **"What soy sauce do you recommend for sushi?"** (po anglicky) dostalo odpoveď **po slovensky**. `detect_query_language()` už správne rozpoznáva "en" (existujúci test to potvrdzuje), ale tento výsledok sa nikdy nedostal do promptu pre OpenAI – správa zákazníka bola obalená v celej slovenskej šablóne ("Otázka zákazníka:", "Zistený zámer:"...) bez akéhokoľvek explicitného pokynu na jazyk, čo pravdepodobne posúva model k prevažujúcemu jazyku vlastného kontextu napriek inštrukcii v systémovom prompte. **Oprava**: pridaný explicitný riadok "Jazyk odpovede: ..." s už vypočítanou hodnotou `query_language`, hneď za otázku zákazníka.
2. K tomu bola pripojená **nesúvisiaca produktová karta** (Wasabi omáčka) k logistickej otázke o vyzdvihnutí "na počkanie" – podľa používateľa *"pri takých otázkach nemá byť doporučenie produktov"*. Príčina: ani "pockanie" ani "odber" neboli v `FAQ_INTENT_MARKERS`, takže `is_faq_intent()` odmietol správu skôr, než sa vôbec dostala k deterministickému FAQ systému, a spadla až do všeobecnej AI odpovede, ktorej systémový prompt vždy pripojí návrh krížového predaja, ak sú priložené akékoľvek produkty. **Oprava**: pridané oba markery plus vyhradená skratka mieriaca presne na správnu FAQ.

Pri overovaní bol nahlásený aj **pôvodný spúšťač** tejto konverzácie: **"Kolko treba zaplatit za dopravu?"** vrátilo FAQ o spôsoboch doručenia namiesto ceny dopravy – skratka vyžadovala presnú frázu "kolko stoji doprava", nie flexibilnú kombináciu. **Oprava**: rozšírené na "kolko" + cenové sloveso (stoji/zaplatit/platit) + doprav/postovn/doruc. Pri overovaní sa našla aj susedná medzera – "kolko trva dorucenie" (doba namiesto ceny, "kolko" namiesto "ako dlho") – opravené párovaním "kolko" s "trva" špecificky, aby sa neprekrývalo s cenovou skratkou (overené obojsmerne: "kolko stoji dorucenie" → cena, "kolko trva dorucenie" → doba).

**Obsahové vylepšenie** (na základe podrobného zadania od používateľa): odpoveď na "kedy je doprava zadarmo" doteraz len konštatovala prah 49 €, bez vysvetlenia, od čoho závisí cena pod touto sumou. Prepísaná tak, aby vysvetlila dva reálne faktory (hmotnostná kategória – zistí sa až po vložení do košíka; spôsob platby – dobierka/prevod/platobná brána) a nasmerovala zákazníka na pokladňu, kde sa pred potvrdením objednávky zobrazí skutočná celková cena.

**Overené naživo**: "Kolko treba zaplatit za dopravu?" → FAQ s vysvetlením faktorov; "je osobny odber na pockanie" → FAQ bez produktov; anglická otázka o sushi → odpoveď po anglicky.

---

### Sprint Z.5 – Informačné otázky o produkte ("čo je X") unesené krížovým predajom (aplikovaná externá záplata)

Používateľ dodal hotovú záplatu (`productadvicefix.patch`) z paralelnej Claude Code relácie, riešiacu ďalšiu triedu chýb v tej istej rodine: otázky **"čo je X"**, **"na čo sa používa X"**, **"ako chutí X"** padali cez celú routovaciu kaskádu až do krížového predaja a dostávali odpoveď v štýle *"K X odporúčam tieto súvisiace produkty..."*, ktorá vôbec nezodpovedala na to, čo sa zákazník pýtal. Príčina: `is_article_info_intent()` nerozpoznávala "na čo sa používa" vôbec, a `detect_article_product_subject()` pokrýva len malý pevný zoznam ~11 tém (kimchi, pho, udon...) – čokoľvek iné prepadlo do cross-sell.

Záplatu som pred nasadením neprijal naslepo – vlastný commit message priznával, že jedna z overovacích dátových sád ešte nebola spustená, a uvádzaný počet testov (413) nesedel s aktuálnou sadou tohto repozitára (390), čo potvrdilo, že bola vyvinutá proti inej/staršej verzii kódu. Preto som ju sám nezávisle preveril: prečítal oba diffy proti reálnej štruktúre `knowledge.json` a potvrdil, že každé odkazované pole skutočne existuje (`Chutovy profil - SK`, `Pouzitie v kuchyni - SK` sú reálne, zákaznícky-orientované polia; `Kedy odporucit - SK` je naopak interná inštrukcia pre AI, nie text pre zákazníka – presne ako záplata tvrdila), prešiel celú routovaciu kaskádu a potvrdil, že nová logika mení iba VÝBER TEXTU odpovede, nie ktoré produkty sa zobrazia, spustil plnú test sadu (307/307) aj oba audit skripty (čisté), a doplnil 4 regresné testy, ktoré záplata sama neobsahovala.

**Overené naživo** – "co je gochujang" teraz vracia `intent: product_advice` s odpoveďou, ktorá najprv vysvetlí, čo gochujang je a ako chutí, až potom pripojí ľahké odporúčanie.

---

### Sprint Z.6 – Workflow s ryžou/ryžovarom a japonské nože unesené kuchyňovým krížovým predajom

Používateľ upozornil: *"Uprav workflow s ryžou, ryžovar... nie je dobrá logika"*, doložené niekoľkými screenshotmi: **"Mate ryzu?"** vrátilo ryžovú múku a ryžovary namiesto samotnej ryže; **"Korenie na ryzu"** aj **"Ryzovar mate?"** tiež vrátili nesprávnu položku z rodiny "ryž-".

Príčina bola bizarná: spúšťač pre `plain_rice` vyžadoval, aby zákazník doslova napísal **"nie ocot"**/**"nie ryžovar"** ("not vinegar"/"not rice cooker") ako explicitnú vylučovaciu vetu vo vlastnej otázke – žiadny reálny zákazník sa takto nepýta, takže táto vetva bola prakticky nedosiahnuteľná. Všetko teda padalo do obyčajného vyhľadávania, kde spoločný koreň "ryz" robí zrno/múku/ryžovar/ocot/rezance rovnocennými konkurentmi.

**Oprava**: prepracované na tri samostatné podtémy s reálnymi slovenskými frázami ako spúšťačmi namiesto umelej vylučovacej syntaxe – `rice_cooker` ("ryžovar"/"hrniec na ryžu"), `rice_seasoning` ("korenie"+"ryž"), `plain_rice` (holý koreň "ryz" bez ostatných kvalifikátorov) – každá s vlastným overeným zoznamom dopytov a vylúčení, aby sa navzájom nekontaminovali. Existujúce `sushi_rice`/`rice_vinegar` zostali nezmenené.

Pri vyšetrovaní si používateľ všimol súvisiaci prípad a požiadal o test: **"Japonske nože, nôž japonsky"**. Potvrdené: rovnaká trieda chyby, iný mechanizmus – tieto dopyty dostali odpoveď z krížového predaja **"japonska_kuchyna"** (sójová omáčka, mirin, dashi, wasabi, sushi ryža) namiesto skutočných nožov, pretože alias "japonsk" sa zhoduje s AKÝMKOĽVEK slovom začínajúcim naň, vrátane kuchynského vybavenia. Overené, že to postihuje celú kategóriu (paličky, taniere, misky, čajníky), nie len nože – opravené všeobecne: keď kuchyňová téma (*_kuchyna) zachytí správu SÚČASNE s konkrétnym kuchynským výrazom, prepadne do bežného vyhľadávania namiesto krížového predaja (rovnaký vzor ako existujúci override pre explicitnú značku tesne nad ním v kaskáde). Skutočná otázka na kuchyňu bez kuchynského výrazu zostáva nedotknutá.

**Overené naživo**: "mate ryzu" → skutočná ryža; "ryzovar mate" → skutočný ryžovar; "japonske noze" → skutočné nože. Plná test sada (312/312), collision audit čistý, 8 nových regresných testov.

---

### Sprint AA – CI pipeline, automatizované audit testy a oprava kódovania (mojibake) v main.py/docs/testoch

Po technickom audite (viď predchádzajúci záznam) používateľ požiadal priamo: *"Potrebujem aby si vykonal, commitol úpravy aby nevznikli tie chyby"*. Zamerané na bezpečné, priamo preventívne položky z auditu, ktoré sa dajú spoľahlivo otestovať a nasadiť bez rizika regresie – väčšie architektonické zmeny (presun na `workflows.py`, rozdelenie `main.py`, oddelenie admin tokenu) zámerne vynechané, popísané na konci.

**1. CI pipeline** (`.github/workflows/ci.yml`, nový) – beží na každý push/PR do `main`: `compileall` (zachytí syntax/kódovacie chyby už pri importe), plná testovacia sada (`pytest tests/test_core.py`), oba existujúce audit skripty (`consistency_audit.py --collisions`, `trust_audit.py`) a `check_deployment.py`. Doteraz repozitár nemal žiadnu ochrannú sieť – dokonca aj druhý, paralelný Claude Code session pracujúci na tomto repozitári (viditeľný napr. v `Claude-Session` trailer prijatej záplaty pre product advice) mohol commitnúť čokoľvek bez kontroly. Pridaný `requirements-dev.txt` (`-r requirements.txt` + `pytest`), keďže pytest doteraz nebol v žiadnom trackovanom requirements súbore.

**2. Audit skripty zapojené do bežného `pytest` behu** – `scripts/consistency_audit.py` a `scripts/trust_audit.py` doteraz existovali len ako standalone skripty spúšťané ručne pred commitom. Pridané 3 nové testy do `tests/test_core.py` (`test_audit_no_marker_alias_collisions`, `test_audit_no_empty_replacement_alternatives`, `test_audit_no_pii_leak_in_redaction`), ktoré volajú `check_collisions()`/`check_empty_alternatives()`/`check_pii_leak()` priamo a assertujú prázdny výsledok – teraz bežia automaticky pri každom `pytest`. Zámerne NEpridané ako hard gate: declension-robustness checky (`check_faq_declensions`, `check_recipe_declensions`) – ich vlastný docstring hovorí, že sú to "candidate generators, not a verdict" vyžadujúce ručnú triáž ako pri Sprint P, nie automatické zlyhanie buildu.

**3. Vedľajší nález – reálna existujúca chyba kódovania (mojibake)**: pri lokálnom overení nového CI kroku (`check_deployment.py`, kontroluje 5 konkrétnych Unicode kódových bodov typických pre CP1250/UTF-8 mojibake vo všetkých textových súboroch) skript zlyhal na 3 existujúcich súboroch – teda ide o predošlú, dovtedy nedetegovanú chybu, nie o niečo, čo tento zásah spôsobil. Rozšíreným allowlist-based skenom (namiesto pevného zoznamu 5 znakov) sa našli aj ďalšie prípady, ktoré pôvodný skript prehliadol (napr. slovo "týždeň" s jedným písmenom nahradeným za U+0114) – pevný zoznam markerov v `check_deployment.py` je teda neúplný a stojí za rozšírenie v budúcnosti.

Nájdené a opravené (byte-presný patch, zachované CRLF):
- `app/main.py` – slová "názov" a "Poznámka" mali písmeno "á" nahradené dvojicou nesprávnych znakov (klasická CP1250-vs-UTF-8 mojibake, kde UTF-8 bajty pre "á" boli preinterpretované ako CP1250); alias pre onigiri používal poľské "ż" namiesto slovenského "ž"; a najdôležitejšie – **slovo "alergénoch" malo "é" nahradené za "è" priamo v zákazníckej správe o alergénoch** (`allergen_term in ("alergeny","alerginy")` vetva) – toto jediné z nálezov sa reálne zobrazovalo zákazníkom.
- `docs/roadmap-features.md` – 7 miest (napr. "sezónne kampane", "Žiadny rules engine. Jediný...", "týždeň"), všetko len v dokumentácii, žiadny dopad na produkciu.
- `tests/test_integration.py` – 1 miesto, dekoratívny komentár, bez dopadu.

**Overené**: `check_deployment.py` prechádza (exit 0); `compileall app scripts` bez chýb; plná sada 315/315 passed (312 pôvodných + 3 nové audit testy), 0 volaní na OpenAI (celý beh je offline); `consistency_audit.py --collisions` čistý.

**Vedome nedodané v tomto zásahu** (z auditu, vyššie riziko regresie, potrebná samostatná diskusia): presun `/chat` na existujúci `app/workflows.py` (postavený a otestovaný, ale nepoužívaný), rozdelenie `app/main.py` (8270 riadkov, ~222 funkcií) na moduly, oddelenie admin tokenu od hlavnej konfigurácie.

---

## Záver

Codebase je solídna produkčná báza. Najväčšje okamžité príležitosti:

1. **Grounding** – kód hotový, 4 hodiny práce, zastaví halucinácie cien/URL
2. **CrossSell bug** – 2140 záznamov sa stráca, fix je 30 riadkov kódu
3. **Event analytika** – blokuje všetky behavioral features
(. **Synonymický slovníj** – nahradí 20 hardcoded if-blokov

Luigi's Box paritu je realistické dosiahnuť v **3 mesiacoch** pri sústredenom vývoji.

---

### Sprint V2.1 – Foodland AI Advisor V2: CustomerIntent foundation

**Zákaznícky problém / architektonická príčina:** `/chat` v `app/main.py` je jeden ~500-riadkový kaskádový if-blok, ktorý postupne počíta desiatky nezávislých booleovských signálov (`allergen_term`, `is_faq_query`, `recipe_subject`, `already_have_subject`, `special_subject`, `replacement_subject`, `related_subject`, `article_product_subject`, `cross_sell_matches`, `product_advice_context`...) a až na konci z nich odvodí jeden legacy `intent` string. `app/workflows.py` (Sprint 1, staršia analýza) už obsahuje `detect_workflow()`/`WorkflowResult`/`get_contract()` presne pre tento účel, ale nikdy nebol zapojený do `/chat` – reálne sa importuje iba `products_to_cart_candidates()`. Každá nová trieda chýb (Sprint V–Z.6 vyššie) sa doteraz opravovala pridaním ďalšej vetvy/výnimky do tejto kaskády – presne ten vzor "regression-driven spaghetti", ktorému má V2 architektúra zabrániť.

**V2 vylepšenie:** Pridaný `app/intent.py` – nová, samostatná (bez FastAPI/OpenAI závislostí) foundation vrstva:
- `CustomerIntent` dataclass s kanonickou schémou z V2 architektúry (`primary_intent`, `subject`, `brand`, `category`, `recipe`, `cuisine`, `use_case`, `dietary_constraints`, `allergen_constraints`, `customer_has`, `requested_output`, `language`, `confidence`, `original_message`).
- `PRIMARY_INTENTS` – 15 kanonických zámerov z V2 návrhu (`product_search`, `product_advice`, `product_comparison`, `category_discovery`, `recipe_only`, `recipe_to_products`, `replacement`, `cross_sell`, `product_information`, `allergen_safety`, `faq`, `availability_or_price`, `conversation_followup`, `general_culinary`, `out_of_domain`).
- `LEGACY_INTENT_MAP` + `map_legacy_intent()` – **compatibility adapter**, ktorý mapuje všetkých 11 legacy intent stringov, ktoré `/chat` reálne produkuje (`missing_composition→faq`, `allergen_safety→allergen_safety`, `faq→faq`, `recipe→recipe_only`, `recipe_to_products→recipe_to_products`, `unknown→out_of_domain`, `article_products→product_information`, `replacement_products→replacement`, `product_advice→product_advice`, `related_products→cross_sell`, `product_search→product_search`), s bezpečným fallbackom na `product_search` pre čokoľvek nezmapované.
- `build_customer_intent()` – čistá funkcia, ktorá poskladá `CustomerIntent` z **už vypočítaných** legacy signálov (nepridáva žiadnu novú NLU logiku, iba prenáša to, čo kaskáda už zistila).

**Migrované správanie:** `/chat` teraz na 7 miestach (všetky `log_question()` volania – missing_composition, allergen_safety, faq, random recipe, recipe_subject vetva, out_of_domain, hlavná product-search vetva) postaví `CustomerIntent` a zaloguje jeho `primary_intent`/`subject` do `question_analytics.jsonl` (nové, voliteľné polia s defaultom `""` – existujúci čitatelia logu nie sú ovplyvnení). **Žiadna existujúca routovacia vetva, odpoveď ani JSON kontrakt `/chat` sa nemenili** – ide o čisto aditívnu zmenu (nový import, nový parameter v `log_question()` s defaultom, nové kľúče v logovanom zázname). Toto je základ (V2.1), na ktorom V2.2 (product search routing) a V2.3 (recipe routing) postavia skutočné presmerovanie rozhodnutí cez `CustomerIntent`.

**Regresné testy:** nový `tests/test_intent.py` (29 testov) – kompletné pokrytie `LEGACY_INTENT_MAP` (všetkých 11 legacy hodnôt), fallback správanie `map_legacy_intent()`, `CustomerIntent` defaulty a immutabilita mutable-default polí naprieč inštanciami, `build_customer_intent()` pre reprezentatívne scenáre (product_search, cross_sell, replacement, allergen_safety, recipe_to_products).

**Testy – plný beh:** `tests/test_core.py` (312/312 pri repo štandardnom `-k` filtri), `tests/test_integration.py` (26/26, end-to-end `chat()` cez mock OpenAI), `tests/test_intent.py` (29/29 nové) → **367/367 spolu, 0 regresií**. `scripts/trust_audit.py` (empty-alternatives aj pii-leak) čisté. `scripts/consistency_audit.py` nezmenené voči predchádzajúcemu stavu (žiadne nové kolízie markerov, existujúce skloňovacie kandidáty sú nezmenené, nesúvisia s touto zmenou).

**Synthetic QA (before/after):** 13 reprezentatívnych scenárov naprieč rodinami z V2 sekcie 17 (ryža, sushi ryža vs. ryžovar, značka Kikkoman, replacement, recipe-to-products, recipe-only, product-information, cross-sell/customer_has, kuchynský riad, FAQ, alergén, out-of-domain) spustených priamo cez `chat()` pred aj po zmene – legacy `intent` pole identické pred/po (0 zmien v správaní). Po zmene navyše `primary_intent`/`subject` správne zachytené vo všetkých 13 prípadoch.

**Naživo overené:** Railway produkcia (`foodland-ai-agent-production.up.railway.app`) nebola v tomto behu dosiahnuteľná – sieťová politika tohto agentného prostredia zamietla `CONNECT` na tento hostiteľ (`403`, `gateway answered 403 to CONNECT (policy denial or upstream failure)`), podľa vlastných pravidiel proxy nemá zmysel to obchádzať. Zmena je zlúčená do `main` a nasadená cez Railway auto-deploy; **finálne overenie na produkcii treba spustiť zo session/prostredia, ktoré má prístup k `foodland-ai-agent-production.up.railway.app`**.

**Zostávajúca najvyššia priorita pre ďalšiu V2 iteráciu (zistené touto session zo synthetic QA, nie hypotéza):**
- `"co potrebujem na tom kha gai"` padá do `related_products` (cross_sell) namiesto `recipe_to_products` – `detect_recipe_subject()` nerozpoznáva "tom kha gai" skôr, než sa vyhodnotí cross-sell vetva.
- `"ma to lepok?"` (bez konkrétneho produktu) nie je zachytené ako `allergen_safety` – padá do `product_search`.
- `"aky je najlepsi film?"` (mimo-doménová otázka) nie je zachytené `detect_out_of_domain()` – padá do `product_search` namiesto refusal správy.

Tieto tri zistenia sú reálnym kandidátom na V2.2/V2.3 (product search routing / recipe routing) – práve typ systematickej slabiny, ktorú štandardizovaná `CustomerIntent` vrstva má postupne odstrániť namiesto ďalšej vetvy v kaskáde.

---

### Sprint V2.1.1 – Oprava "čo potrebujem na tom kha gai" (recipe_to_products routing gap)

**Zákaznícky problém:** `"co potrebujem na tom kha gai"` (nákupný zoznam bez slova "recept") dostal odpoveď z cross-sell vetvy (`intent: related_products`) namiesto `recipe_to_products`, hoci Tom Kha Gai má v `knowledge.json` reálnu, overenú Foodland receptovú kartu aj mapovanie chýbajúcich surovín (`MISSING_INGREDIENTS_BY_SUBJECT["tom_kha"]`).

**Architektonická príčina:** `is_recipe_intent()` (brána pred `detect_recipe_subject()`) vracia `True` iba pri slovách typu "recept"/"návod"/"ako pripravím"/"how to make" (`RECIPE_INTENT_MARKERS`) alebo pri holom tokene začínajúcom na "recept". Nákupno-zoznamová formulácia ("čo potrebujem na X"/"čo kúpiť na X") sa rozpoznáva úplne inou, samostatnou funkciou (`wants_recipe_products()`), ktorá sa ale používa AŽ POTOM, čo je `recipe_subject` už nájdený – nikdy nie ako vstupná brána. Bez slova "recept" tak správa nikdy nedosiahne `detect_recipe_subject()` a spadne až do neskoršej cross-sell vetvy, kde `tom_kha` je mimochodom tiež definovaný ako `RELATED_SUBJECT_ALIASES` téma – takže zákazník dostane produkty, ale bez receptovej karty, `missing_ingredients` a `shopping_list` polí, ktoré `recipe_to_products` workflow poskytuje.

**Zvažovaná, ale zamietnutá širšia oprava:** Prvý pokus rozšíril `is_recipe_intent()` štrukturálne – aby nákupno-zoznamová formulácia platila pre KAŽDÝ subjekt s reálnym overeným receptom (nie len tom_kha), overené cez nový `_SUBJECTS_WITH_VERIFIED_RECIPE` frozenset postavený nad `knowledge.json["Recipes"]`. Toto síce správne vylúčilo `kimchi`/`kimchi_ramen`/`sushi` (nemajú vlastný receptový záznam), ale **rozbilo 2 existujúce, zámerné testy**: `"nakupny zoznam na tom yum"` a `"nakupny zoznam na kimchi ramen"` už majú vlastné, starostlivo doladené cross-sell funkcie (`tom_yum_shopping_core_products()`, `kimchi_ramen_shopping_core_products()`) s vlastným poradím/vylúčeniami produktov, overenými existujúcimi testami – aj keď majú reálny recept (Tom Yum áno), zámerne zostávajú na `related_products` pre túto formuláciu. Široká oprava by tak menila správanie, ktoré nikto nežiadal opraviť, a vyžadovala by prehodnotenie ladenia týchto funkcií. Podľa V2 sekcie 27 (kontrolné prípady) bola táto oprava zamietnutá v prospech užšej.

**V2 vylepšenie (implementované):** Pridané `"tom kha"` do `RECIPE_INTENT_MARKERS` – rovnaký, už zavedený vzor ako existujúce položky `"vindaloo"`/`"karaage"` (Sprint V.6/Z, presne tá istá trieda chyby: holé meno jedla bez slova "recept" musí tiež spustiť recipe workflow). Minimálny, presne ohraničený zásah – žiadny iný subjekt (sushi, pho, ramen, kimchi, tom_yum, kimchi_ramen) nie je zmenou dotknutý.

**Migrované správanie:** `"co potrebujem na tom kha gai"`, `"co kupit na tom kha gai"` aj holé `"tom kha gai"` teraz vracajú `intent: recipe_to_products` s reálnou receptovou kartou ("Tom Kha Gai"), zoradenými produktmi (kokosové mlieko, galangal, citrónová tráva, kaffirové listy, rybacia omáčka, Tom Kha pasta) a `missing_ingredients`.

**Regresné testy:** `test_tom_kha_shopping_list_reaches_recipe_to_products_without_recept_word` (overuje `is_recipe_intent`/`detect_recipe_subject`/plný `chat()` beh vrátane receptovej karty) + kontrolný test `test_tom_kha_fix_does_not_change_neighboring_shopping_list_subjects` (sushi/pho/ramen/kimchi/tom_yum/kimchi_ramen zostávajú nezmenené – presne tie 2 prípady, ktoré odhalili prečo bola širšia oprava zlá).

**Testy – plný beh:** 369/369 (367 z predošlého behu + 2 nové), 0 regresií. `scripts/consistency_audit.py --collisions` aj `scripts/trust_audit.py` čisté.

**Naživo overené:** rovnaké obmedzenie ako Sprint V2.1 – Railway (`foodland-ai-agent-production.up.railway.app`) nedosiahnuteľné z tohto prostredia (proxy 403 policy denial). Treba overiť zo session s prístupom po merge.

---

### Sprint V2.1.2 – Oprava holej alergénovej otázky ("ma to lepok?")

**Zákaznícky problém:** `"ma to lepok?"` (bez pomenovaného produktu, bez slova "alergia"/"obsahuje"/"vhodné") spadlo cez `detect_allergen_intent()` úplne bez odpovede na alergén – namiesto bezpečnostnej odpovede dostal zákazník obyčajné produktové vyhľadávanie.

**Architektonická príčina:** `ALLERGEN_INTENT_MARKERS` (vstupná brána pred vyhľadaním konkrétneho alergénu v `ALLERGEN_TERMS`) vyžaduje explicitné bezpečnostné slovo (alerg/intoler/celiak/obsahuje/vhodn/zlozen/bezlepk/lakto...). Prirodzená otázka v tvare "má/je v tom/sú tam [alergén]?" toto slovo neobsahuje – hoci `ALLERGEN_TERMS` už správne obsahuje `"lepok": "lepok"` (aj ďalšie), vyhľadávací cyklus, ktorý by ho našiel, sa vôbec nespustí, lebo brána ho zastaví skôr.

**Zvažovaná širšia verzia:** Prvý pokus obišiel bránu pre AKÝKOĽVEK termín z `ALLERGEN_TERMS` v kombinácii so slovesom "má/je/sú". Testovanie ale odhalilo falošné pozitíva na generických produktových otázkach, ktoré náhodou obsahujú potravinové podstatné meno zhodné s alergénom: `"aku ma chut toto mlieko"` (aká chuť má toto mlieko - otázka o chuti) a `"kolko ma gramov toto mlieko"` (koľko má gramov - otázka o množstve) sa oba nesprávne zmenili na alergénovú odpoveď namiesto skutočnej odpovede na otázku. Príčina: "mlieko"/"ryby"/"vajcia"/"orechy" sú v `ALLERGEN_TERMS` aj bežné produktové slová, nie len alergény.

**V2 vylepšenie (implementované):** Nová `BARE_ALLERGEN_QUESTION_TERMS` – užšia podmnožina `ALLERGEN_TERMS` obmedzená na jednoznačné alergénové slová bez bežného produktového dvojvýznamu (lepok, gluten, arašidy, sezam, mäkkýše, krevety, sója). Kombinácia (sloveso "má/je/sú" AKO CELÉ SLOVO + termín z tejto užšej množiny) obchádza `ALLERGEN_INTENT_MARKERS` bránu; samotné vyhľadanie labelu naďalej používa plný `ALLERGEN_TERMS` slovník bez zmeny.

**Migrované správanie:** `"ma to lepok?"`, `"je v tom lepok?"`, `"ma to arasidy?"`, `"ma to sezam?"` teraz vracajú `intent: allergen_safety` s bezpečnou odpoveďou ("neodporúčam produkt len podľa názvu, overte zloženie na detaile produktu"), bez produktov. `"mate mlieko?"`, `"chcem kupit orechy"`, `"aku ma chut toto mlieko"`, `"kolko ma gramov toto mlieko"` zostávajú nezmenené (product_search).

**Regresné testy:** rozšírené `TestAllergenSafety` v `tests/test_core.py` o pozitívne prípady (lepok/arašidy/sezam s viacerými slovesami) aj kontrolné prípady (mlieko/ryby/orechy s rovnakým slovesným vzorom musia zostať `None`/`product_search`).

**Testy – plný beh:** 369/369, 0 regresií. `scripts/consistency_audit.py --collisions` aj `scripts/trust_audit.py` čisté.

**Naživo overené:** `LIVE_VERIFICATION_BLOCKED_BY_EXECUTION_ENVIRONMENT` – prístup na `foodland-ai-agent-production.up.railway.app` zamietnutý sieťovou politikou tohto vykonávacieho prostredia (proxy 403, nie chyba Foodland backendu ani Railway deploymentu). GitHub merge overený priamo (commit SHA v tomto behu). Treba dobehnúť zo session/prostredia s priamym prístupom na produkciu.

---

### Sprint V2.1.3 – Oprava mimo-doménovej otázky ("aky je najlepsi film?")

**Zákaznícky problém:** `"aky je najlepsi film?"` (a podobné všeobecné mimo-doménové otázky – politika, všeobecné znalosti, domáce úlohy) nedostali refusal odpoveď, ale **sebavedomo znejúcu, no nezmyselnú produktovú odpoveď**. Priamo otestované: `"kto je prezident slovenska?"` vrátilo *"Našla som tieto najrelevantnejšie produkty: Kľučenka good luck mačka, Tom Yum pasta, Collon sušienky..."* – toto je vážnejší problém, než pôvodne predpokladaný "chýbajúci refusal", pretože prezentuje náhodné produkty ako "najrelevantnejšie".

**Architektonická príčina:** `detect_out_of_domain()` je čisto negatívny, enumeratívny zoznam (`OUT_OF_DOMAIN_MARKERS`) konkrétnych mimo-doménových kategórií (bicykle, elektronika, oblečenie, nábytok, financie, cestovanie...). Takýto zoznam princípovo nemôže pokryť všetky témy, ktoré NIE sú o Foodland – chýbala napr. celá kategória zábava/médiá (filmy, seriály), všeobecné znalosti/politika a školské domáce úlohy.

**Reálna kolízia nájdená pred nasadením:** Prvý návrh použiť bare slová `"film"`/`"serial"` ako markery by **rozbil existujúcu funkciu** – `RELATED_SUBJECT_ALIASES["asian_snack"]` už obsahuje frázy `"na film"`, `"k filmu"`, `"na serial"`, `"k serialu"` (legitímna žiadosť o snack na filmový/seriálový večer). Overené automatickým kolíznym skriptom aj `scripts/consistency_audit.py --collisions` a naživo cez `chat()`: `"co si dat na film"` musí naďalej fungovať ako cross-sell na snacky, nie ako refusal.

**V2 vylepšenie (implementované):** Doplnené viacslovné, kolízne overené frázy do `OUT_OF_DOMAIN_MARKERS` v troch kategóriách: zábava/médiá (`"najlepsi film"`, `"najlepsi serial"`, `"aky film mi"`, `"dobry film odporuc"`, `"filmovu recenziu"`, `"herec vo filme"`), všeobecné znalosti/politika (`"kto je prezident"`, `"hlavne mesto"`, `"kto vyhral volby"`, `"politicku stranu"`) a domáce úlohy/škola (`"domacu ulohu"`, `"domaca uloha"`, `"domacou ulohou"`, `"domacej ulohy"`, `"referat na tema"` – viacero skloňovaných tvarov, keďže "domacou ulohou" bez tejto formy zostávalo nezachytené).

**Explicitne priznané obmedzenie (nie je to skryté):** Toto **NIE JE štrukturálna oprava** celej triedy chýb – zoznam zostáva principiálne neúplný (napr. "čo si myslíš o politike?", "odporúčaš mi dobrú knihu?" zostávajú nepokryté, zámerne nechané mimo rozsahu tejto opravy, aby sa predišlo riziku blokovania legitímnych produktových otázok generickými frázami ako "čo si myslíš o..."). Skutočná štrukturálna oprava (pozitívny signál "je toto o Foodland doméne" namiesto rastúceho negatívneho zoznamu) je zdokumentovaná v `docs/advisor-v2-architecture.md` ako kandidát na budúcu iteráciu.

**Regresné testy:** `test_out_of_domain_entertainment_trivia_and_school` (5 pozitívnych prípadov + plný `chat()` beh s overením `intent: unknown` a bez produktov) + kritický kontrolný test `test_out_of_domain_fix_does_not_break_asian_snack_cross_sell` (overuje, že `"co si dat na film"`/`"co si dat k filmu"`/`"nieco na serial"` naďalej správne vracajú `asian_snack` cross-sell, nie refusal).

**Testy – plný beh:** 373/373 (371 z predošlého behu + 2 nové), 0 regresií. `scripts/consistency_audit.py --collisions` aj `scripts/trust_audit.py` čisté.

**Naživo overené:** `LIVE_VERIFICATION_BLOCKED_BY_EXECUTION_ENVIRONMENT` – rovnaké obmedzenie ako predošlé dve opravy (proxy 403 tohto vykonávacieho prostredia, nie chyba Foodland backendu/Railway deploymentu). GitHub merge treba overiť priamo cez commit SHA po zlúčení; finálne naživo overenie treba spustiť zo session s priamym prístupom na produkciu.

---

### Sprint V2.1.4 – Oprava vlastnej regresie: sójová omáčka nesprávne padala do alergénovej odpovede

**Zákaznícky problém, zistený širším synthetic QA behom (25 scenárov naprieč porovnaním, cenou, dostupnosťou, kuchynským riadom, dietetickými požiadavkami):** `"co je lepsie svetla alebo tmava sojova omacka?"` (porovnanie svetlej a tmavej sójovej omáčky) a `"aka je cena kikkoman sojovej omacky?"` (cena Kikkoman sójovej omáčky) obe vrátili **alergénovú bezpečnostnú odpoveď o sóji** namiesto skutočnej odpovede na otázku – dve úplne bežné, vysokoobjemové otázky o vlajkovej produktovej kategórii obchodu.

**Príčina – vlastná regresia z minulého Sprintu (V2.1.2):** Pri oprave "ma to lepok?" (predošlý sprint) som do `BARE_ALLERGEN_QUESTION_TERMS` zahrnul aj `"soja"`/`"soj"` ako údajne jednoznačné alergénové slová. To bola chyba rovnakého druhu, akej som sa vtedy vedome vyhol pri `"mlieko"`/`"orech"`/`"ryb"`/`"vajc"` – **"sójová omáčka" je jedna z najpredávanejších kategórií tohto obchodu** (Kikkoman, Yamasa, Healthy Boy, Lee Kum Kee a ďalšie – téma desiatok predošlých Sprintov v tejto roadmape), nie len alergén. Keďže moja oprava obchádza bránu pri kombinácii slovesa "má/je/sú" + akéhokoľvek slova z `BARE_ALLERGEN_QUESTION_TERMS`, a slovo "je" je v slovenčine extrémne bežné, prakticky KAŽDÁ veta o sójovej omáčke obsahujúca "je" ("čo JE lepšie...", "aká JE cena...") sa nesprávne zmenila na alergénovú odpoveď.

**Ako bola nájdená:** Nie ručným hľadaním konkrétnej chyby, ale širším synthetic QA behom (25 scenárov naprieč porovnaním, cenou/dostupnosťou, kuchynským riadom, typmi/preklepmi, dietetickými požiadavkami, no-result prípadmi) spusteným ako súčasť pravidelného V2 loop postupu (krok "Measure" pred diagnostikou ďalšej slabiny) – presne postup, ktorý má tento typ regresie odhaliť skôr, než sa dostane do produkcie.

**Oprava:** Odstránené `"soja"`/`"soj"` z `BARE_ALLERGEN_QUESTION_TERMS` – rovnaké zaobchádzanie ako pri `"mlieko"`/`"orech"`. Zostávajúca množina (lepok, gluten, arašidy, sezam, mäkkýše, krevety) neobsahuje žiadne bežné produktové/kategóriové slovo z katalógu. Explicitná žiadosť o vyhnutie sa sóji ("bez sóje", "alergia na sóju") zostáva nezmenená – tá ide cez pôvodnú, staršiu `ALLERGEN_INTENT_MARKERS` bránu (`"bez soj"`/`"bez soja"`), nie cez bránu opravovanú touto ani predošlou opravou.

**Migrované správanie:** `"co je lepsie svetla alebo tmava sojova omacka?"` teraz vracia `intent: product_advice` s relevantnými produktmi; `"aka je cena kikkoman sojovej omacky?"` vracia `intent: product_search` s Kikkoman sójovými omáčkami. `"ma to lepok?"`, `"bez soje, co mate?"`, `"alergia na soju"` zostávajú nezmenené (alergénová odpoveď tam, kde je to správne).

**Regresné testy:** nový `test_bare_allergen_question_does_not_hijack_soy_sauce_questions` – 4 prípady sójovej omáčky musia byť `None` (nie alergén), 2 explicitné alergénové žiadosti o sóju musia zostať `"sóju"` (cez starú bránu, aby budúca zmena tejto brány neomylom "opravila" aj tento prípad naspäť).

**Testy – plný beh:** 374/374 (373 z predošlého behu + 1 nový), 0 regresií. `scripts/consistency_audit.py --collisions` aj `scripts/trust_audit.py` (empty-alternatives aj pii-leak) čisté.

**Naživo overené:** `LIVE_VERIFICATION_BLOCKED_BY_EXECUTION_ENVIRONMENT` – rovnaké obmedzenie ako predošlé opravy.

**Poučenie pre ďalšie V2 iterácie:** Každá nová "bezpečná" množina slov (ako `BARE_ALLERGEN_QUESTION_TERMS`) musí byť pred nasadením otestovaná nielen proti známym kontrolným prípadom z danej opravy, ale aj proti **širšiemu synthetic QA vzorku** naprieč inými kategóriami produktov – práve preto V2 loop krok "Measure" beží pred každou diagnózou, nie len raz na začiatku.

---

### Sprint V2.1.5 – Oprava kontaminácie session pamäte porovnávacou otázkou ("pikantnejšie")

**Ako bola nájdená:** Krok "Measure" tejto iterácie spustil širší synthetic QA beh (25 scenárov v jednej konverzácii/session – presne postup, ktorý minule odhalil regresiu so sójovou omáčkou). Tri dopyty neskoro v sekvencii vrátili prázdnu odpoveď bez produktov napriek tomu, že v izolácii fungovali správne: preklep značky (`"mate sojovu omacku kikoman"`), preklep produktu (`"gochuujang"`) a holá značka (`"kikkoman produkty"`) – všetky tri spadli do `intent: related_products` s 0 produktmi namiesto správneho `product_search` s reálnymi výsledkami.

**Príčina – kontaminácia cez session pamäť, nie chyba vo vyhľadávaní samotnom:** Bisekciou (postupné pridávanie predošlých správ do tej istej session) sa zistilo, že stačí JEDNA predošlá správa: `"gochujang vs sriracha, co je pikantnejsie?"` (porovnávacia otázka "ktoré je pikantnejšie"). `detect_diet_terms()` zachytáva holý podreťazec `"pikant"` – ten sa nachádza aj v porovnávacom tvare `"pikantnejsie"` ("pikantnejšie" bez diakritiky), takže táto porovnávacia OTÁZKA sa nesprávne zaznamenala ako trvalá stravovacia preferencia `"pikantne"` do `memory["diet_terms"]`. `contextualize_message()` potom **bezpodmienečne** (nie len pri follow-up otázkach) pripája posledné 2 `diet_terms` na koniec KAŽDEJ nasledujúcej správy v session, ak tam ešte nie sú. Výsledok: `"aku kategoriu produktov mate?"` sa interne zmenilo na `"aku kategoriu produktov mate? pikantne"`, čo `detect_related_subject()` vyhodnotilo ako tému `"medium_spicy"` (s nulovými reálnymi produktovými zhodami), a rovnaký mechanizmus poškodil aj neskoršie dopyty na Kikkoman/gochujang v tej istej konverzácii.

**Oprava:** Vylúčený porovnávací kmeň `"pikantnej"` (spoločný pre pikantnejší/pikantnejšia/pikantnejšie vo všetkých rodoch) z `detect_diet_terms()` detekcie – zostáva `"paliv"`/`"pikant"`/`"chilli"`/`"chili"` pre skutočné vyjadrenia preferencie (`"mam rad pikantne kimchi"`, existujúci a naďalej platný test `test_user_memory_persists_culinary_preferences`).

**Migrované správanie:** Porovnávacie otázky o pikantnosti už nezanechávajú stopu v `diet_terms`. Neskoršie, úplne nesúvisiace dopyty v tej istej konverzácii (preklepy značiek, holé značky, všeobecné kategóriové otázky) sa už nekontaminujú a vrátia reálne, relevantné produkty namiesto prázdnej odpovede.

**Zostávajúce, zámerne NEriešené v tejto iterácii:** `"aku kategoriu produktov mate?"` zostáva slabá odpoveď aj úplne izolovane (bez kontaminácie) – `category_discovery` nemá vlastný detektor vôbec, čo je už zdokumentovaná, samostatná medzera vo `V2.4` v `docs/advisor-v2-architecture.md`, nie súčasť tejto opravy.

**Regresné testy:** `test_diet_terms_does_not_treat_comparison_questions_as_preference` (3 porovnávacie tvary musia byť `[]`, 3 skutočné preferencie musia zostať `["pikantne"]`) + `test_comparison_question_does_not_contaminate_later_unrelated_messages` (end-to-end cez `contextualize_message()` – overuje, že kontaminácia reálne zmizla, nie len že `detect_diet_terms()` vracia iný výsledok v izolácii).

**Testy – plný beh:** 376/376 (374 z predošlého behu + 2 nové), 0 regresií. `scripts/consistency_audit.py --collisions` čisté. `scripts/trust_audit.py` (empty-alternatives aj pii-leak) čisté.

**Naživo overené:** `LIVE_VERIFICATION_BLOCKED_BY_EXECUTION_ENVIRONMENT` – rovnaké obmedzenie ako predošlé opravy (proxy 403 tohto vykonávacieho prostredia).

**Architektonické pozorovanie pre V2.6:** Táto oprava rieši jeden konkrétny falošný pozitívny prípad, nie samotný mechanizmus. `contextualize_message()` bezpodmienečne vkladá `diet_terms` do každej nasledujúcej správy bez kontroly relevancie (na rozdiel od `last_top_product_title`, ktorý sa pripája len pri `is_context_followup()`). Akékoľvek budúce falošné pozitívum v `detect_diet_terms()` alebo `detect_memory_subjects()` bude mať rovnaký rozsah škody – kontaminuje celý zvyšok konverzácie, nie len jednu odpoveď. Skutočná V2.6 štrukturálna oprava (aplikovať pamäť až po vyhodnotení explicitného zámeru, nie pred ním, podľa V2 sekcie 12) by toto riziko odstránila systematicky.

---

### Sprint V2.1.6 – Prvý detektor pre `category_discovery` ("aku kategoriu produktov mate?")

**Zákaznícky problém:** Všeobecné otázky o sortimente ("aku kategoriu produktov mate?", "aky sortiment mate?", "ake znacky predavate?") nemali žiadny dedikovaný handler. V praxi to viedlo k dvom zlým výsledkom, oba overené priamo cez `chat()`: buď prázdna odpoveď `"Našla som súvisiace informácie vo Foodland poradkyni."` bez produktov (dead-end), alebo – horšie – `cached_search_products()` vždy nájde NEJAKÚ zhodu cez token/fuzzy matching aj pre výplňové slová, takže napr. "ake znacky predavate?" sebavedomo vrátilo Arašidy Tom Yum, Pocky tyčinky a Arašidy vo wasabi ako "najrelevantnejšie produkty" – rovnaká trieda dôveryhodnostného problému ako mimo-doménová otázka zo Sprintu V2.1.3.

**Architektonická príčina:** `category_discovery` je kanonický V2 zámer (existuje v `app/intent.py` `PRIMARY_INTENTS` už od V2.1), ale v legacy `chat()` kaskáde nemal vôbec zodpovedajúci detektor – zdokumentovaná medzera vo fáze V2.4.

**Zvažované, ale zamietnuté:** Naivná verzia by mohla generovať zoznam kategórií priamo z `product_type` breadcrumb dát bez filtrovania – overené, že to obsahuje 127 rôznych "top-level" segmentov vrátane prierezových dietetických/marketingových značiek ("Vegánske potraviny", "Zdravé potraviny", "Super potraviny", "Darčekové sety"...), ktoré by pôsobili ako nezmyselný zoznam, nie skutočný prehľad oddelení. Namiesto vymýšľania kurátorovaného zoznamu (riziko halucinácie/neoverenej domény) bol použitý **skutočný, dátami podložený** prístup: top 8 kategórií podľa počtu produktov, s odfiltrovanou malou, explicitne zdokumentovanou množinou prierezových značiek.

**Reálna kolízia nájdená a vyriešená pred nasadením:** Substring-based marker (`"aky tovar mate"` ako `in` kontrola) by nesprávne zachytil dlhšie, konkrétne dopyty ako `"aky tovar mate na sushi?"` alebo `"co mate v ponuke na sushi"`. Namiesto substring zhody použitá **presná zhoda celej správy** (po normalizácii a odstránení koncovej interpunkcie) – overené kolízne testy aj `scripts/consistency_audit.py --collisions`.

**V2 vylepšenie (implementované):** `is_category_discovery_query()` (presná zhoda 6 fráz), `top_product_categories()` (top-N reálnych kategórií z `product_type`, filtrované cez `CATEGORY_DISCOVERY_NOISE`), `category_discovery_answer()` (grounded odpoveď s reálnymi názvami kategórií). Zapojené do `chat()` ako nová vetva hneď za `out_of_domain` (rovnaký vzor), s `intent="category_discovery"` namapovaným priamo na kanonický zámer v `app/intent.py`.

**Migrované správanie:** Všetkých 6 pokrytých fráz teraz vracia `intent: category_discovery` s odpoveďou typu *"Foodland.sk ponúka široký sortiment naprieč mnohými kategóriami, napríklad: Misy a misky, Vonné tyčinky, Nealkoholické nápoje... Napíšte mi, čo konkrétne hľadáte."* – žiadne vymyslené ani irelevantné produkty. Zámerne mimo rozsahu: `"co mate v ponuke?"` (príliš kolízne s "čo mate v ponuke na X"), `"co vsetko mate skladom?"` (existujúca `best_direct_faq_answer()` už dáva lepšiu, dostupnostne zameranú odpoveď pre túto konkrétnu formuláciu, keby bola volaná – zostáva ako budúci kandidát, nie súčasť tejto opravy).

**Regresné testy:** `test_category_discovery_detects_generic_inventory_questions` (6 pozitívnych fráz + plný `chat()` beh overujúci `intent`, žiadne produkty, a že odpoveď skutočne obsahuje reálny názov kategórie z katalógu) + `test_category_discovery_does_not_hijack_specific_product_questions` (6 kontrolných prípadov – konkrétne produktové/kuchynné dopyty musia zostať nedotknuté) + `test_top_product_categories_excludes_dietary_marketing_noise` (prierezové značky nesmú byť v zozname).

**Testy – plný beh:** 380/380 (377 z predošlého behu + 3 nové), 0 regresií. `scripts/consistency_audit.py --collisions` aj `scripts/trust_audit.py` (empty-alternatives aj pii-leak) čisté.

**Naživo overené:** `LIVE_VERIFICATION_BLOCKED_BY_EXECUTION_ENVIRONMENT` – rovnaké obmedzenie ako predošlé opravy (proxy 403 tohto vykonávacieho prostredia, nie chyba Foodland backendu/Railway deploymentu).

---

### Sprint V2.1.7 – Negovaná preferencia sa zaznamenala ako opak toho, čo zákazník povedal

**Ako bola nájdená:** Krok "Measure" tejto iterácie spustil nový synthetic QA vzorok (negácie, viac-kolové konverzácie, množstvo/cena, porovnania) namiesto priameho pokračovania na `product_comparison` feature (naplánovaný ako ďalší krok minule). Jeden z 18 scenárov – porovnávacia otázka o mirine a ryžovom occite – vrátila **polámanú, nezmyselnú odpoveď**: `"vyrazne umami, pikantne, fermentovane a slano-kysle podla typu produktu kimchi, bibimbap, marinady, polievky, ryzove misky a rychle korejske jedla"` namiesto zmysluplnej vety o mirine. V izolácii (bez predošlého kontextu) fungovala tá istá otázka správne – jasný signál na kontamináciu session pamäte, rovnaký vzor ako Sprint V2.1.5.

**Príčina:** Bisekciou sa zistilo, že prvá správa v konverzácii, `"nechcem nic pikantne"` ("nechcem nič pikantné"), sa nesprávne zaznamenala do `memory["diet_terms"]` ako **pozitívna** preferencia `"pikantne"` – presný opak toho, čo zákazník povedal. `detect_diet_terms()` totiž kontrolovala iba holý podreťazec `"pikant"`/`"paliv"` bez akéhokoľvek povedomia o negácii ("nechcem", "nemám rád" pred slovom úplne menia význam, ale kód ich ignoroval). Táto falošná preferencia sa potom cez `contextualize_message()` (rovnaký bezpodmienečný injection mechanizmus ako v Sprinte V2.1.5) vložila do neskoršej, úplne nesúvisiacej otázky o mirine, čo zmiatlo vyhľadávanie v Products_AI znalostiach a vrátilo útržok textu patriaci inému produktu (pravdepodobne gochujang/kimchi, súdiac podľa spomienky "kimchi, bibimbap").

**Toto je DRUHÝ výskyt rovnakej triedy chyby za dve po sebe idúce iterácie** (prvý bol porovnávací tvar "pikantnejšie" v Sprinte V2.1.5). Podľa V2 sekcie 20-21 (uprednostniť štrukturálnu opravu pred ďalšou jednorazovou výnimkou, keď sa rovnaká príčina opakuje) bola táto oprava navrhnutá všeobecnejšie než len ďalšie vylúčenie jedného konkrétneho tvaru.

**V2 vylepšenie (implementované):** Nová `DIET_TERM_NEGATION_MARKERS` ("nechcem", "nemam rad", "nemam rada", "neznasam", "nie som") – ak správa obsahuje ktorýkoľvek z týchto markerov KDEKOĽVEK, `detect_diet_terms()` vráti prázdny zoznam namiesto pokusu o presné vyhodnotenie, ktorá časť vety je negovaná. Toto je **hrubší** prístup než presné negačné parsovanie (zložená veta typu "nechcem sladké, chcem pikantné" by stratila aj druhú, skutočnú preferenciu), ale bezpečnejší zlyhávací režim – nikdy nezaznamenať opačnú preferenciu je dôležitejšie než zachytiť každý okrajový prípad. Oprava je zámerne všeobecná naprieč VŠETKÝMI kategóriami `detect_diet_terms()` (pikantné, vegán, vegetariánske, bezlepkové), nie len pre "pikantne".

**Migrované správanie:** `"nechcem nic pikantne"`, `"nemam rad pikantne jedla"`, `"neznasam pikantne"`, `"nechcem vegansky produkt"`, `"nie som vegan"`, `"nemam rad kokos"` už nezanechávajú žiadnu stopu v `diet_terms`. Skutočné preferencie (`"mam rad pikantne kimchi"`, `"som vegan"`, `"hladam bezlepkove produkty"`) zostávajú nezmenené. Porovnávacia otázka o mirine teraz naprieč celou konverzáciou vracia zmysluplnú odpoveď.

**Regresné testy:** `test_diet_terms_does_not_invert_negated_statements` (6 negovaných tvarov musia byť `[]`, 3 skutočné preferencie musia zostať nezmenené naprieč všetkými kategóriami, nie len pikantné) + `test_negated_spice_statement_does_not_corrupt_later_unrelated_answer` (end-to-end cez `contextualize_message()` s presne tou reálnou kombináciou správ, ktorá spôsobila polámanú odpoveď).

**Testy – plný beh:** 382/382 (380 z predošlého behu + 2 nové), 0 regresií. `scripts/consistency_audit.py --collisions` aj `scripts/trust_audit.py` (empty-alternatives aj pii-leak) čisté.

**Naživo overené:** `LIVE_VERIFICATION_BLOCKED_BY_EXECUTION_ENVIRONMENT` – rovnaké obmedzenie ako predošlé opravy.

**Architektonické odporúčanie:** Toto je už druhý nález presne tejto triedy chyby za dve iterácie. `docs/advisor-v2-architecture.md` (V2.6 riadok) teraz explicitne odporúča, aby ďalšia V2.6 iterácia riešila samotný `contextualize_message()` injection mechanizmus (aplikovať pamäť až po vyhodnotení explicitného zámeru, podľa V2 sekcie 12), nie ďalší jednotlivý detektor – tretí výskyt by mal byť signálom na túto väčšiu, štrukturálnu prácu namiesto ďalšej záplaty.

---

### Sprint V2.2.0 – Prvý katalógovo-riadený taxonomy beh: rodina "ryža" (Stage A, shadow mode)

**Zadanie:** Namiesto ručného klasifikovania Foodland katalógu podľa príkladov z promptu (výslovne zakázané zadaním) – najprv preskúmať **aktuálny** katalóg programaticky, až potom navrhnúť taxonómiu.

**Fáza 1-4 – profil katalógu (reálne čísla, nie odhady):** Nový `scripts/taxonomy_audit.py` (spustiteľný opakovane, žiadne hardcoded počty) vygeneroval z `data/products.json` a `data/knowledge.json`:

```
total_products = 2140
unique_brands = 368
unique_categories_top_level = 127
unique_categories_all_levels = 166
```

Detailná inšpekcia koreňa `ryz` (`--family ryz`) potvrdila presne tú triedu chyby, ktorú Sprint Z.6 už raz opravil ručne: **7 odlišných produktových podrodín** zdieľa jeden jazykový koreň – samotná ryža (69 produktov), ryžové rezance (63), ryžový ocot (23), ryžová múka (3), ryžový papier, ryžovar (má vlastnú reálnu katalógovú kategóriu `Ryžovary`), ryžový nápoj (2, len MEDIUM confidence).

**Fáza 9 – recepty/IntentMapping ako overený sémantický zdroj:** `data/knowledge.json["sections"]["IntentMapping"]` (318 záznamov) obsahuje kurátorovanú kategóriu `"Ryža / výber produktu"` (4 záznamy) s priamo použiteľným, overeným obsahom – napr. presne pre otázku "Aký je rozdiel medzi jazmínovou a basmati ryžou?" je poznámka "Porovnať arómu, zrnitosť, kuchyňu a použitie." Toto je grounded zdroj pre budúci `product_comparison` intent, nie vymyslený text.

**Fáza 5-11 – kanonická taxonómia, `docs/product-taxonomy-audit.md`:** Navrhnutá rodina `rice` s 8 podrodinami (7× HIGH confidence z jasného katalógového/kategóriového dôkazu, 1× MEDIUM z `rice_drink` s iba 2 produktmi – podľa Fázy 11 pravidla MEDIUM nesmie tvoriť tvrdé retrieval obmedzenie, preto sa v tejto iterácii do klasifikátora vôbec nezapája).

**V2 vylepšenie (implementované, Fáza 26 krok 11-13):** Nový `app/taxonomy.py` (`classify_rice_query()`) – frázovo založený klasifikátor bez akéhokoľvek ručne udržiavaného zoznamu SKU (Fáza 12: 2140 produktov sa neklasifikuje ručne, klasifikuje sa text dopytu/nazvu podľa opakovane použiteľných fráz). Poradie kontroly zámerne kopíruje existujúcu disciplínu z `RELATED_SUBJECT_ALIASES` (najšpecifickejšie frázy najprv – `"ryzovy ocot"` pred holým `"ryza"`), plus špeciálne pravidlo: `"aku ryzu odporucas na sushi?"` (ryža a sushi ako samostatné slová, nie zložená fráza) sa vyhodnotí rovnako ako `"sushi ryza"` – presne podľa overeného `IntentMapping` záznamu.

**Rollout Stage A (Fáza 16 – shadow/observation mode, zámerne, nie plné nasadenie):** `classify_rice_query()` je zapojené do `/chat` **výhradne na účely logovania** cez nový `log_taxonomy_shadow()` – zapisuje do `taxonomy_shadow.jsonl`, ale **nemení žiadne routovacie rozhodnutie, produkty ani text odpovede**. Overené priamo: identická štruktúra a obsah `/chat` odpovede pred aj po zmene pre viacero ryžových aj neryžových dopytov. Existujúca legacy rice logika (`SPECIAL_PRODUCT_QUERIES["plain_rice"/"sushi_rice"/"rice_vinegar"/"rice_cooker"/"rice_seasoning"/"rice_side"]` zo Sprintu Z.6) zostáva plne funkčná a nedotknutá – Stage B (skutočné nahradenie) je zámerne mimo rozsahu tejto iterácie a vyžaduje najprv porovnanie shadow logov s reálnymi dátami.

**Regresné a kolízne testy (Fáza 21-22):** nový `tests/test_taxonomy.py` (21 testov) – klasifikácia podľa reálnych zákazníckych fráz aj podľa **skutočných názvov produktov** vytiahnutých z `data/products.json` (nie vymyslené príklady), explicitný kolízny test (`test_collision_family_generates_distinct_subfamilies` – všetkých 6 členov kolíznej skupiny musí dostať RÔZNE podrodiny), špecifickosťový test (`ryzovar` musí vyhrať nad `plain_rice` aj v prítomnosti `"sushi ryzu"` v tej istej vete) a `TestShadowModeIntegrity` (čistá funkcia, žiadny vedľajší efekt na `/chat` odpoveď).

**Testy – plný beh:** 403/403 (382 z predošlého behu + 21 nových), 0 regresií. `scripts/consistency_audit.py --collisions` aj `scripts/trust_audit.py` čisté.

**Naživo overené:** `LIVE_VERIFICATION_BLOCKED_BY_EXECUTION_ENVIRONMENT` – rovnaké obmedzenie ako predošlé opravy (proxy 403 tohto vykonávacieho prostredia).

**Ďalší krok (mimo rozsahu tejto iterácie):** Po nazbieraní shadow dát z produkcie (keď bude dostupný prístup) porovnať `taxonomy_shadow.jsonl` voči skutočným `SPECIAL_PRODUCT_QUERIES` rozhodnutiam a `/admin/analytics/no-results`, rozhodnúť o Stage B pre `rice`, a až potom zvážiť druhú rodinu (`rezance`/nudle majú tiež silný katalógový aj `IntentMapping` dôkaz podľa `docs/product-taxonomy-audit.md`).

### Sprint V2.2.1 – Feed Foundation, Product Normalization & Taxonomy Engine (produktová úroveň)

**Zadanie** (externe nazvané "Sprint V2.1" v zadaní tejto iterácie – číslovanie sa prekrýva s existujúcou V2.1.x CustomerIntent líniou vyššie, preto tu pokračuje ako V2.2.1, priama nadväznosť na V2.2.0 vyššie): posunúť produktovú reprezentáciu od plochého `product_type` textu k štruktúrovanej `NormalizedProduct`/`ProductTaxonomy` vrstve, deterministicky, bez LLM volania za behu, bez ručného mapovania SKU, bez zmeny customer-facing správania.

**Kľúčový rozdiel oproti V2.2.0:** `classify_rice_query()` (V2.2.0) klasifikuje **text správy zákazníka** – vracia `family="rice"` pre celý jazykový zhluk vrátane ryžovaru, lebo ide o shadow analytics jedného jazykového zhluku, nie o identitu produktu. Táto iterácia pridáva DRUHÝ, nezávislý klasifikátor – `classify_product()`/`build_taxonomy_index()` v tom istom `app/taxonomy.py` – ktorý klasifikuje **produkt z katalógu** a garantuje mandatory invariant zo zadania: `family != word root` (`canonical_family("ryžovar")` musí byť `"kitchenware"`, nie `"rice"`).

**Feed (`app/feed.py`):** nový `parse_category_memberships(product_type)` – deterministický rozklad na plochý `category_memberships[]` (rozdelenie na `>`, orezanie whitespace, odstránenie prázdnych/duplicitných segmentov, zachovanie zdrojového poradia) – zámerne **nie strom** (živý feed mixuje rodinu/varietu/dietetický štítok/merchandising label v jednej ceste bez konzistentného poradia, napr. `Ryžový papier` a `Múka` zdieľajú tú istú leaf kategóriu `Múka, škrob & ryžový papier`). Sprístupnené ako odvodená `Product.category_memberships` `@property` (nie uložené pole – žiadna duplicita v `products.json`). Pridané nové polia zo živého feedu (`additional_image_links[]`, `unit_pricing_base_measure`, `shipping_weight`, `condition`, `identifier_exists`), všetky s bezpečným defaultom pre staré JSON snapshoty. Pridaná `find_duplicate_gtins()` – len detekcia (4 skupiny nájdené na aktuálnom katalógu), nikdy automatické zlúčenie produktov.

**Produktový normalizér (`app/product_normalizer.py`, nový modul):** čisto štrukturálne odvodeniny bez sémantiky – `extract_url_category()`, `parse_package_size()` (nejednoznačné tvary ako "10 ks"/"500 g / drained 300 g" sa zámerne NEODHADUJÚ), `normalize_brand()`/`title_search_form` (opätovne použité `app.search.normalize()`, žiadna konkurenčná implementácia).

**Taxonomy engine (`app/taxonomy.py`, rozšírenie):** `FAMILY_DEFINITIONS` – dátovo-riadený zoznam pravidiel (`FamilyRule`), najšpecifickejšie prvé, rovnaká kolízna disciplína ako existujúci `RICE_SUBFAMILY_PHRASES`. Pilotná rodina `rice` + 6 kolíznych susedných rodín (`noodles`/`vinegar`/`flour`/`rice_paper`/`kitchenware`/`beverages`), každé pravidlo podložené reálnym dôkazom zo živého feedu (nie príkladmi z promptu) – pozri `docs/product-taxonomy-audit.md` pre presné kategórie/tituly. `ProductTaxonomy` nesie `canonical_family`/`canonical_subfamily`/`attributes`/facety/`confidence` (HIGH/MEDIUM/LOW/UNKNOWN)/`evidence`/`taxonomy_version`. Nový `CategoryRole` (PRODUCT_FAMILY/VARIETY/DIETARY_FACET/.../UNKNOWN) a `CATEGORY_ALIASES` (`"Ryža na suši (sushi)"` + `"Suši ryža"` → jeden signál, Fáza 19 zadania). Query API pre budúci retrieval: `find_by_family()`, `find_by_attributes()`, `get_taxonomy()`.

**Integrácia do refresh pipeline (`app/main.py`):** nový globál `product_taxonomy_index` – postavený pri module-load (`load_products()`) aj v `refresh_feed()`, v lockstepe s `products`/`product_snapshot`/`translation_index` (atomický swap, `new_taxonomy_index` postavený PRED swapom, aby chyba v taxonómii nikdy nenechala index nesynchronizovaný so skutočným katalógom). Per-produkt failure isolation (`build_taxonomy_index()`) – jeden zlý produkt nikdy nezhodí celý refresh, dostane `UNKNOWN` a zostáva plne dostupný legacy vyhľadávaniu. **Žiadny customer-facing kód path v tejto iterácii `product_taxonomy_index` nečíta** – legacy search/routing beží bezo zmeny (overené: `search_products()`/`chat()` nezmenené, iba pridaný import a globál).

**Pokrytie (na committed `data/products.json`, 2 140 produktov):** `total_products=2140`, `classified_products=155` (`taxonomy_coverage=0.0724` – zámerne úzke, rice pilot only), `confidence_counts` HIGH=108/MEDIUM=39/LOW=8/UNKNOWN=1985, `canonical_family_count=7` (rice/noodles/vinegar/flour/rice_paper/kitchenware/beverages), `canonical_subfamily_count=8`. Rovnaké proporcie potvrdené aj na živom feede (2 325 produktov, `classified_products=166`, `taxonomy_coverage=0.0714`). Detail v `docs/product-taxonomy-audit.md`.

**Incident – dátová fixture regresia (nájdená CI, opravená, nie V2.1 kódová regresia):** prvý push tejto iterácie omylom obnovil `data/products.json` na živý feed (2 325 produktov) ako súčasť "vždy aktuálne čísla" požiadavky. To spôsobilo **3 skutočné CI test failures** – `test_search_autocomplete_boosts_favorite_brand`, `test_replacement_bare_brand_resolves_to_its_only_sauce_category`, `test_replacement_bare_brand_survives_contextualize_message_pollution` – lebo tieto testy sú napevno naviazané na presné zloženie pôvodnej fixture (napr. test explicitne komentuje "Kikkoman... only sell one of our two sauce categories"; živý feed medzičasom pridal `Kimchi základ KIKKOMAN`, čím sa tento predpoklad reálne zmenil). Overené lokálne pred aj po: 3/3 failing → 3/3 passing po vrátení `data/products.json` na pôvodný commitnutý stav (`git checkout 398d8db -- data/products.json`), **testy neboli upravované** – toto je presne "root cause, not green tests" disciplína zo zadania. Produkčný `refresh_feed()` je týmto nedotknutý – vždy číta skutočný živý feed; iba tento checked-in dev/test fixture súbor zostáva zámerne pinned na známy stav.

**Povinný kolízny test (overené na reálnych produktoch, nie vymyslených):** `canonical_family("Chantaboon ryžové rezance ... FARMER 400 g")=noodles`, `canonical_family("Ryžový ocot CHINKIANG GOLD PLUM 550ml")=vinegar`, `canonical_family("Lepkavá ryžová múka TAIKY 400g")=flour`, `canonical_family("Okrúhly ryžový papier ... TUFOCO 400g")=rice_paper`, `canonical_family("Elektrický hrniec na ryžu REMO 0,8 L")=kitchenware` – všetkých 6 členov jednej "ryz\*" kolíznej skupiny dostáva 6 odlišných hodnôt.

**Shadow interpretation (`scripts/taxonomy_audit.py --shadow-interpretation`):** pre všetkých 8 povinných dopytov zo zadania ("ryža", "jazmínová ryža", "basmati ryža", "ryža na sushi", "ryžové rezance", "ryžový ocot", "ryžový papier", "ryžovar") sa top-5 legacy search výsledok mapuje na presne JEDNU `family/subfamily` kombináciu – nulová krížová kontaminácia. Demonštruje, že štruktúrovaná reprezentácia existuje, bez zmeny `/chat` výstupu.

**Testy:** nový `tests/test_feed.py` (kategórie membership parsing, rozšírené polia, spätná kompatibilita, duplicate GTIN), nový `tests/test_product_normalizer.py` (URL kategória, package size, brand), rozšírený `tests/test_taxonomy.py` o produktovú úroveň (`TestClassifyProductRiceCollisions`, `TestClassifyProductAttributes`, `TestCategoryAliases`, `TestConfidenceLevels`, `TestUnknownProducts`, `TestBuildTaxonomyIndex`, `TestQueryApi`, `TestTaxonomyCoverage`). **Plný beh: 557/557, 0 regresií** (predošlý stav plus nové testy tejto iterácie). `scripts/consistency_audit.py --collisions` aj `scripts/trust_audit.py` bežia bezo zmeny.

**Performance:** na živom feede (2 325 produktov) – XML parse ~1.6s (nezmenené, network-bound), normalizácia celého katalógu ~0.03s, taxonomy klasifikácia celého katalógu ~0.08s. Zanedbateľný dopad na `refresh_feed()`. Žiadne LLM volanie v tomto pipeline.

**Dátová kvalita:** `find_duplicate_gtins()` nad živým feedom nahlásil 4 skupiny so zdieľaným GTIN medzi odlišnými Foodland product id – nahlásené, NEOPRAVENÉ (mimo rozsahu, oprava zdrojového katalógu nie je úloha AI advisora).

**Naživo overené:** `LIVE_VERIFICATION_BLOCKED_BY_EXECUTION_ENVIRONMENT` – rovnaké obmedzenie ako predošlé iterácie (proxy 403 policy denial pre Railway health-check z tohto vykonávacieho prostredia). Živý Foodland Merchant feed sám osebe **bol** dostupný priamo z tohto prostredia (stiahnutý úspešne cez `app/import_feed.py`), takže katalógové čísla vyššie sú z reálnych aktuálnych dát, nie z cache.

**Ďalší krok (mimo rozsahu tejto iterácie):** V2.2 – Structured Retrieval & Category-Aware Ranking: napojiť `find_by_family()`/`find_by_attributes()` na retrieval plan namiesto re-tokenizácie `product_type` per request, pod kontrolovaným rollout (rovnaký Stage A→B vzor). Migrácia `CustomerIntent`/`workflows.py` a plné prepnutie `/chat` na V2 routing zostáva zámerne mimo rozsahu.

### Sprint V2.2.2 – Intent-Aware Autocomplete & Structured Query Suggestions

**Zadanie** (externe nazvané "Sprint V2.2" – prekrýva sa číslom s existujúcim TODO riadkom "V2.2 Product routing" v `docs/advisor-v2-architecture.md`, ktorý je o niečom inom (`CustomerIntent`-driven `/chat` routing) a zostáva nezmenený; tento sprint pokračuje ako V2.2.2, priama nadväznosť na V2.2.1 vyššie): posunúť autocomplete od reťazcového prefix/token matchingu k hybridnému modelu – taxonómiou-podložené štruktúrované návrhy TAM, kde `product_taxonomy_index` (V2.1) pozná koncept, s bezpečným legacy fallbackom pre zvyšných ~92,9 % katalógu, ktorý je `taxonomy=UNKNOWN`.

**Dependency mapa pred implementáciou:** zistené TRI nezávislé autocomplete systémy: `GET /autocomplete` (legacy `{products,categories,brands,top_questions}`, `app/autocomplete.py`), `POST /products/suggest` (`app/search.py: autocomplete_suggestions()`), a **skutočne produkčný** `POST /search/autocomplete` (`app/main.py: search_autocomplete()`, jediný, ktorý `app/widget.js` reálne volá – potvrdené grepom, žiadny GET `/autocomplete` call site vo widgete). Widget už číta štruktúrovaný `data.suggestions[]` s `item.type`/`item.label`/`item.highlight` poľami (nie legacy shape) – pridanie nových `type` hodnôt a `action`/`constraints` polí je teda čisto aditívne, bezo zmeny existujúceho kontraktu.

**Nové zdroje návrhov (`app/autocomplete.py`):**
- `taxonomy_category_suggestions(query, concepts, limit)` – zhoduje dopyt s precomputed `taxonomy_concept_index` (`app/taxonomy.py: build_concept_index()`, nový – zoskupuje `product_taxonomy_index` podľa `concept_id` = `FamilyRule.rule_id`, len HIGH/MEDIUM confidence, s reálnym `product_count`). Každé `FamilyRule` v `FAMILY_DEFINITIONS` dostalo nové pole `display_label` (napr. `jasmine_rice` → `"Jazmínová ryža"`).
- `question_suggestions(knowledge, query, limit)` – zhoduje dopyt s 19 curated `data/knowledge.json["IntentMapping"]` záznamami typu `"* / výber produktu"` (overený zdroj, nie generovaný text); klasifikuje `comparison` vs `question` podľa markerov (`"rozdiel"`, `" vs "`, `"verzus"`).
- `_token_wise_match_score()` – nový, poradie-nezávislý multi-token prefix matcher (query aj kandidát rozdelené na tokeny, každý query token musí prefix-matchovať nejaký token kandidáta) – rieši Sekcie 24/25 zadania ("basmati r" aj "ryza basmati" musia nájsť "Basmati ryža"; "rozdiel jaz" musí nájsť porovnávaciu otázku).

**Kolízna invariant (Sekcia 13/36, overené na wired `search_autocomplete()`):** `"ryza"` dopyt vylučuje `Ryžové rezance`/`Ryžový ocot`/`Ryžový papier`/`Ryžovar` z `taxonomy_category` návrhov (presne opačne pre `"ryzov"` prefix) – vyplýva prirodzene zo slovenskej morfológie (4. znak sa líši: `ryza` vs `ryzov*`), žiadne špeciálne prípady navyše.

**Wiring (`app/main.py: search_autocomplete()`):** nové zdroje volané v spoločnom prefixe funkcie (pred fast/slow-path vetvou, takže platia pre obe cesty), skórované na konkurencieschopnú úroveň voči existujúcim exact-match produktom/intentom (`taxonomy_category` ~620-640, `comparison` ~580, `question` ~540 – porovnaj s existujúcim intent baseline ~500 a exact-product-match stropom ~660). `diverse_autocomplete_items()` soft_caps rozšírené o `taxonomy_category:4, question:2, comparison:1`. Nový globál `taxonomy_concept_index`, prestavovaný v lockstepe s `product_taxonomy_index` pri štarte aj v `refresh_feed()` (žiadny manuálny rebuild).

**UNKNOWN fallback (mandatory, Sekcia 9/61/77):** `"Kimchi základ KIKKOMAN"` (potvrdene `taxonomy=UNKNOWN`, žiadne pravidlo v `FAMILY_DEFINITIONS` naň nesedí) naďalej normálne vyskočí ako `product` návrh pre `"kikko"`/`"kimchi"` dopyt cez nezmenenú legacy cestu – overené testom `test_unknown_taxonomy_product_still_discoverable`.

**Personalizácia:** `personalize_products()` zostáva reorder-only (nezmenené), nové `taxonomy_category`/`question`/`comparison` typy vôbec nevidia `profile` – JONGGA-obľúbený profil nemôže injektovať nesúvisiaci návrh pre nesúvisiaci dopyt, ani prebiť explicitný `"basmati"` dopyt (overené testami).

**Widget (`app/widget.js`):** len `suggestionTypeLabel()` mapa rozšírená o `taxonomy_category → "Kategória"`, `question → "Otázka"`, `comparison → "Porovnanie"` (3 riadky, byte-precise patch, diff overený proti `--ignore-space-at-eol`). Klikacie správanie (`applySuggestion`) nezmenené – posiela `item.query`/`item.label` ako bežný chat dopyt, čo pre nové typy funguje prirodzene (napr. klik na "Jazmínová ryža" pošle presne tento text do `/chat`, ktorý existujúce legacy vyhľadávanie spracuje správne) – žiadna nová frontend logika pre `action`/`constraints` v tejto iterácii (tie sú pripravené pre budúci retrieval, `/chat` ich zatiaľ nekonzumuje).

**Testy:** nový `tests/test_autocomplete.py` (27 testov – `_token_wise_match_score`, `taxonomy_category_suggestions`, `question_suggestions`, čisté unit testy bez FastAPI závislosti), rozšírený `tests/test_taxonomy.py` o `TestConceptIndex` (7 testov), rozšírený `tests/test_core.py` o `TestTaxonomyAwareAutocomplete` (10 integračných testov nad reálnym katalógom) + `test_refresh_feed_rebuilds_taxonomy_concept_index`.

**Performance:** vlastné nové funkcie ~0.13 ms/dopyt (precomputed indexy, žiadne LLM). **Pred-existujúci nález** (potvrdené `cProfile`, nulová účasť nového kódu): `fuzzy_hits()`/`edit_distance()` v `app/search.py` prehľadáva celý katalóg per-token pre KAŽDÝ odlišný dopyt – ~700-2000 ms na prvý výskyt danej query string, opakovaný identický dopyt rýchly (~8 ms, existujúci per-string cache). Toto NIE JE spôsobené touto iteráciou (izolovane odmerané a profilované) – silný kandidát na samostatný performance sprint, mimo rozsahu tejto iterácie (Section 71/72 zadania explicitne zakazujú "overbuild").

**Ďalší krok (mimo rozsahu tejto iterácie):** (1) Performance sprint pre `fuzzy_hits`/`edit_distance` (vyššie) – priamo blokuje skutočný "rýchle ako klávesnica" UX cieľ zadania. (2) Result presentation / `action`+`constraints` consumer na frontende, keď bude V2.3 Structured Retrieval pripravené.

### Sprint V2.2.1 – Autocomplete Performance Optimization

**Zadanie:** vyriešiť pred-existujúci `fuzzy_hits`/`edit_distance` nález zo Sprintu V2.2.2 vyššie bez zmeny sémantiky (žiadna zmena poradia/labelov/typov návrhov).

**Bottleneck (potvrdené `cProfile` pred zmenou):** `search_products()` a `autocomplete_suggestions()` (`app/search.py`) prepočítavali `tokenize()`/`normalize()` pre title/brand/category/description KAŽDÉHO produktu pri KAŽDOM dopyte (rovnaký text, rovnaký výsledok, len znovu a znovu) a volali `edit_distance()` raz za KAŽDÚ inštanciu tokenu naprieč katalógom (~286 000 volaní pre jeden dopyt na 2 140 produktoch), hoci bežné slová (`"kg"`, `"omacka"`, `"ryza"`) sa opakujú naprieč stovkami produktov – `edit_distance(query_token, "ryza")` sa tak počítal stokrát namiesto raz.

**Implementované (`app/search.py`, mimo `main.py` až na 3 volania warmup/importu):**
1. `ProductTokenIndex` / `build_product_token_index()` / `get_product_token_index()` – precomputed per-produkt tokeny (title/brand/category/description), `id(products)`-keyed cache (rovnaký vzor ako existujúci `get_bm25_index()`). `search_products()` aj `autocomplete_suggestions()` teraz čítajú z tohto indexu namiesto opakovaného `tokenize()`/`normalize()`.
2. `get_catalog_token_vocabulary()` (~9 885 distinct tokenov pre 2 140 produktov) + `build_fuzzy_match_cache()`/`fuzzy_hits_cached()` – `edit_distance()` deduplikovaný na úroveň DISTINCT slovníka namiesto per-produkt inštancie. `get_fuzzy_match_cache()` navyše zdieľa výsledok medzi oboma volaniami (`search_products` aj `autocomplete_suggestions`) v rámci jedného `/search/autocomplete` requestu, keďže oba bežia nad rovnakým dopytom.
3. `warm_search_indexes()` – volané pri module-load aj v `refresh_feed()`, takže index sa staví PRED prvým užívateľským dopytom (Section 44 zadania: atomický index swap, žiadny čiastočne postavený stav).

**Objavený vedľajší nález (opravené):** `id(products)` samotné je nebezpečný cache kľúč – CPython môže znovu použiť pamäťovú adresu uvoľneného zoznamu pre nový, nesúvisiaci zoznam, čo by spôsobilo, že cache vráti dáta z INÉHO katalógu. Zachytené vlastným novým testom (`TestCatalogTokenVocabulary::test_vocabulary_is_union_across_catalog` zlyhal pri prvom behu presne takto). Opravené na `(id(products), len(products))` naprieč VŠETKÝMI `id(products)`-keyed cache v module – vrátane pôvodného, staršieho `get_bm25_index()`, ktorý mal ten istý latentný problém.

**Output equivalence (Section 5/30/36 zadania):** `git stash` pred-optimalizačnej verzie, zachytený skutočný "before" výstup pre všetkých 15 povinných dopytov zo zadania (`r, ry, ryža, ryza, jazm, jazmínová, basmati, ryžové, ryžový ocot, kikko, kimchi, miso, kokos, akú ryžu, rozdiel jazmínová basmati`), `git stash pop`, porovnané byte-presne s "after" výstupom: **0 rozdielov**. Rovnako 0 rozdielov pre pôvodnú V2.2.1-baseline sadu (15 ďalších reprezentatívnych dopytov).

**Performance (2 140 produktov, studený beh = prvý výskyt danej kombinácie query tokenov po `warm_search_indexes()`):**

```
                    PRED         PO
avg                 980.6 ms     24.5 ms
p50                 980.5 ms      8.4 ms
max                2253.3 ms    174.9 ms
teplý opakovaný dopyt  ~8 ms      ~8-12 ms  (nezmenené, cache-hit už predtým)
edit_distance volania (1 dopyt)  ~286 000   ~10 000-30 000
```

**Testy:** nový `tests/test_search_performance.py` (18 testov – ekvivalencia fuzzy cache, typo tolerancia, cache invalidation podľa `products` identity, `warm_search_indexes()`), rozšírený `tests/test_core.py` o `test_refresh_feed_rebuilds_search_performance_indexes`. **Plný beh: 624/624**, 0 regresií (bežal aj 286,95s namiesto pôvodných ~460-560s – vedľajší efekt: existujúce testy nad `search_autocomplete()`/`search_products()` sú teraz tiež rýchlejšie).

**Ďalší krok (mimo rozsahu tejto iterácie):** V2.3 – Structured Retrieval & Category-Aware Ranking (napojiť `find_by_family()`/`find_by_attributes()` na retrieval namiesto re-tokenizácie `product_type`), teraz bez performance prekážky z tejto iterácie.

### Sprint V2.3 – Taxonomy Expansion Across the Foodland Catalog

**Zadanie:** rozšíriť V2.1 rice-pilot taxonómiu na širokú, produkčne pripravenú taxonómiu naprieč hlavnými Foodland produktovými rodinami, s cieľom materiálne zvýšiť HIGH/MEDIUM pokrytie a zachovať sémantickú čistotu (žiadna "za každú cenu" 100 % klasifikácia).

**Discovery (živý feed, 2 319 produktov):** profil kategórií a titulkov identifikoval 9 nových vysoko-dôveryhodných kandidátnych rodín na základe reálnych dedikovaných kategórií (`Sójové omáčky` 97×, `Kari pasty` 31×, `Sezamový olej` 9×, `Čaj` 78×, `Kokosové mlieko a krémy`, `Pšeničné rezance` 45×, `Hoisin omáčky`, `Ustricové omáčky`, `Rybacie omáčky`, `Teriyaki omáčky`, `Instantné polievky` 179×, `Morské riasy` – nori/wakame/kelp). Zámerne VYNECHANÉ (nekonzistentné dôkazy, Section 96): `tofu` (žiadna dedikovaná kategória, väčšina "tofu" titulkov je o inom produkte s tofu prísadou), `wasabi` (titulkové zhody boli prevažne wasabi-príchuťové snacky a farba riadu, nie kondiment), `knives`/`chopsticks`/`pickled_ginger` (nulový výskyt presných termínov v tomto behu feedu).

**Implementované (`app/taxonomy.py`):** 9 nových kanonických rodín (`sauce`, `curry_paste`, `paste`, `coconut_product`, `oil`, `tea`, `seaweed`, `instant_food`, `frozen_food`) + rozšírenie existujúceho `noodles` (wheat_noodles, soba). Nové engine pole `exclude_title_phrases` na `FamilyRule` (collision guard, Section 45 zadania) – prvý reálny use case pre negatívne pravidlá popri existujúcich pozitívnych `category_terms`/`title_phrases`.

**Kritický nález a oprava (family purity audit, Section 53/58):** motor `classify_product()` prijíma zhodu KATEGÓRIE **alebo** TITULKU (nie AND). Toto je bezpečné len keď je kategória naozaj čistá. Manuálny purity audit (nie testy vopred – presne preto bol povinný) odhalil 7 pravidiel, kde zdieľaná/nečistá kategória spôsobovala nesprávnu klasifikáciu cez kategóriu samotnú, bez ohľadu na titulok:

```
gyoza                          – "Mrazené potraviny" chytilo 70 nesúvisiacich produktov (kalamáre, mochi zmrzlina, edamame)
soy_sauce/dark/light            – "Sójové omáčky" obsahuje aj čiernu fazuľu/poke/unagi/dumpling omáčky
coconut_water                   – "Kokosový nápoj" obsahuje aj kokosové želé dezerty
nori/wakame                     – "Morské riasy" mixuje nori+wakame+kelp/kombu spolu
massaman/panang/red/green curry – všetky 4 zdieľali "Kari pasty" → PRVÉ pravidlo (massaman) vyhrávalo pre KAŽDÝ produkt v kategórii (červená kari pasta klasifikovaná ako massaman!)
soba_noodles                    – bare "soba" chytal aj "yakisoba" (iný pokrm), instantnú soba polievku, keramický riad
teriyaki_sauce                  – bare "teriyaki" chytal instantné teriyaki-príchute polievky/rezance
```

Všetkých 7 opravených na title-only gating alebo `exclude_title_phrases`, s testami pokrývajúcimi presne tieto kolízne prípady (`tests/test_taxonomy_v23.py`).

**Pokrytie (živý feed, 2 319 produktov):**

```
                    PRED V2.3    PO V2.3
taxonomy_coverage    7.14 %       33.03 %
classified            166          766
HIGH                   111          538
MEDIUM                  45          218
LOW                     10           10
UNKNOWN               2159         1553
canonical_family_count   7           16
canonical_subfamily_count 8          27
```

Committed fixture (2 140 produktov, pinned test suite): `classified=720`, `coverage=33.64 %`, `HIGH=512 MEDIUM=200 LOW=8` — proporčne zhodné so živým feedom, potvrdzuje stabilitu naprieč feed verziami.

**V2.2 autocomplete kompatibilita (Section 47 zadania):** žiadna manuálna zmena v `app/autocomplete.py` potrebná – `taxonomy_category_suggestions()` beží nad `build_concept_index()`, ktorý je generický nad `FAMILY_DEFINITIONS`, takže všetkých 9 nových rodín sa automaticky objavilo v autocomplete konceptoch (napr. `"sojova"` teraz ponúkne `taxonomy_category: Sójová omáčka`).

**Testy:** nový `tests/test_taxonomy_v23.py` (40 testov – classification per rodina, kolízne testy pre všetky zdieľané-kategórie prípady vyššie, negatívne testy pre `tofu`/`wasabi` zostávajúce UNKNOWN). Aktualizovaný `tests/test_taxonomy.py` (6 testov zmenilo fixture z `"Gochujang pasta 500g"` – teraz legitímne klasifikované ako `paste/gochujang` – na `"Kimchi základ KIKKOMAN"`, overené ako stále genuinely UNKNOWN). **Plný beh: 665/665**, 0 regresií.

**Ďalší krok (mimo rozsahu tejto iterácie):** V2.4 — Structured Retrieval & Category-Aware Ranking.

### Sprint V2.4 – Structured Retrieval & Category-Aware Ranking

**Zadanie:** urobiť V2.1–V2.3 taxonómiu aktívne použiteľnou pre product retrieval namiesto len shadow/autocomplete použitia – zákaznícky dopyt sa má interpretovať ako štruktúrované obmedzenia (family/subfamily/attributes/brand/size/dietary), tie sa majú deterministicky nájsť v katalógu (retrieval), a až potom zoradiť (ranking) – nie fuzzy skóre naprieč celým katalógom s nádejou, že top výsledky sú relevantné.

**Implementované:** 4 nové moduly – `app/query_constraints.py` (`StructuredProductQuery`, `parse_structured_query()` reuse-uje `app.taxonomy.FAMILY_DEFINITIONS` na text dopytu namiesto druhej nezávislej taxonómie), `app/retrieval.py` (`StructuredProductIndex` – invertovaný index family/subfamily/attribute/brand/size → product id množiny, `retrieve_products()` – čistý prienik množín, EXACT/VALID/NEAREST rozlíšenie s deterministickou stupňovitou relaxáciou), `app/ranking.py` (`rank_candidates()` – 7-vrstvový lexikografický sort key: taxonomy confidence → explicit P3 satisfaction count → availability → lexical relevance → behavioral/merchandising/personalization súčin, v tomto poradí, takže popularita/personalizácia štrukturálne nemôžu prebiť explicitný zákaznícky constraint), `app/structured_search.py` (`hybrid_search_products()` – integračný bod so safe fallbackom na legacy `search_products()`, `retrieve_products_for_query()` – plný `RetrievalResult` pre budúce workflow volania, Section 84 zadania).

**Retrieval vs. ranking oddelenie (Section 2 zadania):** `app/retrieval.py` nikdy neskóruje – iba prienik množín. `app/ranking.py` nikdy nepridáva/neuberá kandidáta – iba mení poradie danej množiny. Overené testom `TestRankingInvariants` (ranking je vždy permutácia rovnakej množiny).

**Confidence gating namiesto per-rodina zoznamu (Section 10/41):** `StructuredProductIndex` obsahuje iba produkty s taxonómiou `HIGH`/`MEDIUM` (712/2140 = 33,3 % fixture, naprieč 15 rodinami). `LOW`/`UNKNOWN` produkty nikdy nevstupujú do indexu a ostávajú plne dostupné cez nezmenený legacy `search_products()` – bezpečnostný mechanizmus je teda na úrovni jednotlivého produktu, nie ručný "aktivovaný zoznam rodín", takže sa automaticky rozširuje s každou budúcou V2.x taxonomy expanziou bez zásahu do tohto kódu.

**Zapojenie do `app/main.py`:** presne na dvoch miestach cez `hybrid_cached_search_products()` – primárny `product_search` fallback v `chat()` (posledná `else` vetva pred replacement/cross-sell/special/recipe detekciami, ktoré zostávajú nezmenené) a `/products/search` endpoint. Feature-flag `V2_STRUCTURED_RETRIEVAL_ENABLED` (default `true`) pre okamžitý rollback bez deploymentu (Section 42). `refresh_feed()` prestavuje `normalized_product_index` v lockstepe s `product_taxonomy_index` – žiadny stale cache po feed refreshi (Section 54/55).

**Kritické nálezy pri implementácii (self-audit, nie čakanie na produkčný nález):**
1. Naivné pravidlo "subfamily/attributes sú tvrdý filter iba ak pravidlo nesie vlastný `attributes` tuple" fungovalo pre `rice` (bare "ryža" fallback nemá attributes), ale nesprávne ZŠIROKOVALO `sójová omáčka`/`instantné rezance`/`miso` na celú rodinu – väčšina sauce/paste/instant_food podrodinových pravidiel nemá `attributes` vôbec, no stále reprezentujú špecifický koncept. Opravené: len JEDNO pravidlo (`plain_rice`) je skutočne "generic family-only"; explicitný `frozenset` namiesto krehkej heuristiky.
2. `"ryža na sushi"` (anglický pravopis, iné poradie slov) sa nezhodovalo so žiadnou z 3 doslovných fráz v `sushi_rice` pravidle (tie sú produktovo-titulkovo orientované: `"sushi ryza"`, `"ryza na susi"`, `"susi ryza"`). Opravené rovnakým bare-token co-occurrence trikom, aký už používa `classify_rice_query()` z V2.1.
3. Relaxácia pôvodne zahadzovala čiastočný úspech (napr. správnu značku) a padala rovno na celú `valid_match_ids` množinu pri zlyhaní čo i len jedného P3 constraintu. Opravené na 3-stupňovú deterministickú relaxáciu (Section 18): skús bez size, potom bez brand, až potom bez oboch.

**Testy:** nový `tests/test_structured_retrieval.py` (44 testov na syntetickom, ale feed-reálne-znejúcom katalógu – rovnaká fixture disciplína ako `test_taxonomy_v23.py`): specificity monotonicity (`results("ryža") ⊇ results("jazmínová ryža") ⊇ results("FOODLAND jazmínová ryža 5 kg")`), kolízne testy (ryža vs rezance/ocot/múka/ryžovar/papier; sójová omáčka vs čierna fazuľa/tofu; kokosové mlieko vs voda/olej; kari pasta vs korenie/opačná varieta; miso pasta vs miso polievka), veľkostné testy (1000g==1kg, 500ml≠1l), brand testy, dietary test, UNKNOWN/LOW-confidence fallback, ranking invarianty, popularity override, personalization override, autocomplete handoff. **Plný beh: 709/709** (665 pred V2.4 + 44 nových), 0 regresií.

**Performance (Section 91):** parse+retrieve+rank ~1,09 ms/dopyt vs. legacy `search_products()` ~19,7 ms/dopyt (~18× rýchlejšie) – prienik malých invertovaných indexov namiesto plného katalógového skenu.

**Riziká/obmedzenia (úprimne):** `tea` rodina má v committed fixture 0 HIGH/MEDIUM produktov (fixture drift oproti živému feedu, rovnaký typ rozdielu ako V2.3 dokumentoval). Relaxácia je 3-stupňová, nie plný combinatorický prehľadávač – dostatočné pre V2.4 rozsah (Section 17: "Full presentation of this distinction belongs to V2.5"). Personalizácia nie je priamo zapojená do `hybrid_cached_search_products()` volania (`personalization_scores=None`) – existujúci `personalize_products()` postprocessing krok v `chat()` beží aj nad štruktúrovanými výsledkami (agnostický k pôvodu zoznamu), takže Section 35 je splnená end-to-end, ale priama `app.ranking` L6 vrstva je zatiaľ nevyužitá v produkčnej ceste. Detail: `docs/structured-retrieval-audit.md`.

**Ďalší krok (mimo rozsahu tejto iterácie):** V2.5 — Result Presentation Layer & Answer Composer.

### Sprint V2.5 – Result Presentation Layer, Show More/Show All & Answer Composer

**Zadanie:** premeniť V2.4 štruktúrovaný retrieval na skutočnú zákaznícku skúsenosť – zobraziť rozumnú počiatočnú podmnožinu, umožniť "Zobraziť viac"/"Zobraziť všetky" nad TOU ISTOU množinou (žiadne nové vyhľadávanie), skupinovať široké dopyty podľa reálnych kategórií, a vysvetliť výsledok prirodzeným jazykom bez LLM rozhodujúceho o produktoch/počtoch.

**Implementované:** `app/result_sets.py` (`ResultSet` – stabilný, id-only záznam s TTL store, `initial_page_ids()`/`next_page_ids()`/`remaining_ids()`), `app/presentation.py` (`build_result_set()` – 4 automaticky vyberané stratégie: `EXACT_MATCH` (≤3 exact zhody), `FILTERED_PRODUCT_LIST` (konkrétna varieta/subfamily), `GROUPED_DISCOVERY` (holá rodina, ≥2 koncepty), `NO_EXACT_MATCH` (0 exact, nearest > 0); `build_groups()` – zoskupenie podľa `ProductTaxonomy.concept_id`, reálne počty z aktuálnej validnej množiny, nikdy nevymyslené), `app/answer_composer.py` (deterministický, template-based text – **žiadne LLM volanie**, Section 24/50 zadania). `app/structured_search.py` rozšírené o `build_structured_result_set()` (orchestruje parse→retrieve→rank→present, podporuje follow-up merge cez `app.query_constraints.merge_constraints()`).

**Zapojenie do `app/main.py`:** nová najvyššou-prioritou vetva v `chat()` pre SHOW_MORE/SHOW_ALL frázy ("zobraz viac"/"zobraz vsetky"/"show more"/"show all"), aktivuje sa len keď existuje `active_result_set_id` v session memory – číta ULOŽENÝ `ResultSet`, žiadne nové vyhľadávanie, žiadne re-parsovanie krátkej frázy ako broad dopytu. Nový early-return pre `structured_presentation`, s vyššou prioritou než existujúci `should_use_fast_chat_answer()` – keď sa aplikuje, úplne obchádza OpenAI volanie.

**Kritický nález (self-audit pred nasadením):** pred-V2.1 `detect_special_product_subject()` obsahuje bare catch-all pravidlo `if "ryz" in normalized_message and not any(exclusion markers): return "plain_rice"`, ktoré zachytávalo presne mandátne V2.5 testovacie dopyty ("jazmínová ryža", "basmati ryža") skôr, než sa vôbec dostali do novej štruktúrovanej vetvy (`elif special_subject:` beží pred plain product_search `else:` vetvou). Opravené chirurgicky: keď `special_subject == "plain_rice"`, štruktúrovaný retrieval sa skúsi PRVÝ; ak vráti `None`, pôvodný `special_products_for_subject()` beží ako safety-net fallback presne ako predtým. Ostatných ~25 `special_subject` záznamov (mild/hot/kids_snack/rice_cooker/sushi_rice/vegan_asian/...) zostáva úplne nedotknutých – migrovaný je len ten jeden záznam, ktorý V2.3/V2.4 taxonómia genuinely nahrádza presnejším a stránkovateľným výsledkom.

**Overené naživo cez `app.main.chat()` (nie len izolované moduly):**
```
"jazminova ryza"        -> FILTERED_PRODUCT_LIST, matching_total=14, 4 zobrazené, has_more=true
"zobraz vsetky"         -> response_mode=result_set_continuation, 10 NOVÝCH produktov (4+10=14 presne), has_more=false
"ryza" (holý dopyt)     -> GROUPED_DISCOVERY, 78 produktov v 5 kategóriách (Basmati 20, Ryža 19, Jazmínová 14, Lepkavá 13, Sushi 12)
"jazminova ryza" -> "len 5 kg" -> merge zachoval family=rice/variety=jasmine, pridal package_size=5kg -> EXACT_MATCH, 1 produkt
"FOODLAND jazminova ryza 2 kg" -> NO_EXACT_MATCH, matching_total=0, 3 nearest (správna značka, iná veľkosť)
```

**Widget (`app/widget.js`, prírastková zmena, nie redesign):** existujúce klientske tlačidlo "Zobraziť viac" (ktoré doteraz len stránkovalo nad tým, čo už bolo poslané v `products[]`) teraz prijíma `hasServerMore` z `data.has_more`. Po vyčerpaní lokálneho batchu, ak server signalizuje viac, tlačidlo sa zmení na "Zobraziť všetky" a po kliku prepošle existujúci `/chat` formulár s kanonickou frázou "zobraz vsetky" – žiadny nový endpoint, žiadna nová fetch logika.

**Testy:** nový `tests/test_result_presentation.py` (22 testov – pagination completeness, Show All union bez prekryvu, related contamination naprieč všetkými stránkami, grouped discovery s reálnymi počtami, špecifická-vs-broad stratégia, follow-up constraint persistence vrátane "bez aktívneho ResultSetu sa nič nevymyslí", no-exact-match rozlíšenie, answer wording pravidlá, ranking stability, TTL store). **Plný beh: 731/731** (709 pred V2.5 + 22 nových), 0 regresií.

**Riziká/obmedzenia (úprimne):** `COMPARISON`/`USE_CASE_ADVICE`/`RECOMMENDATION`/`REPLACEMENT`/`RECIPE_SHOPPING` stratégie sú definované ako konštanty, ale zatiaľ sa automaticky nevyberajú – tieto zákaznícke zámery bežia naďalej cez existujúce, samostatne testované legacy cesty. Personalizácia sa pre štruktúrované odpovede teraz explicitne VYNECHÁVA (namiesto post-hoc aplikácie), aby stránkovanie ResultSetu zostalo stabilné naprieč viacerými "Zobraziť viac" kolami (Section 44 zadania). Detail: `docs/result-presentation-audit.md`.

**Ďalší krok (mimo rozsahu tejto iterácie):** V2.6 — Contextual Cross-Sell & Basket Intelligence.

### Sprint V2.6 – Contextual Cross-Sell & Basket Intelligence

**Zadanie:** odpovedať na "čo ešte by zákazníkovi genuinely pomohlo dokončiť tú istú úlohu?", nie "čo ešte môžeme ponúknuť". Cross-sell musí mať explicitnú eligibility bránu, roly pred produktmi, sémantickú validáciu proti FBT-ako-pravda, basket/duplicate exklúziu, a musí zostať malý a diverzný.

**Implementované:** nový modul `app/cross_sell.py` — `should_cross_sell()` (eligibility gate), `generate_candidates()` (role-first, multi-zdrojová generácia), `rank_candidates()` (deterministický, evidence-weighted). Roly = V2.3 taxonomy `concept_id`, mined zo **skutočných, už existujúcich curated dát**, nie vymyslené: `RECIPE_SHOPPING_CORE_QUERIES` (47 jedál z V2.1) normalizované cez `app.query_constraints.parse_structured_query()` (napr. `pad_thai` → `['rice_noodles', 'fish_sauce']`), a malá ručne overená podmnožina `SPECIAL_PRODUCT_QUERIES` (`sushi_rice`/`gluten_free_sushi`/`sushi_condiments`/`rice_seasoning` — po inšpekcii zámerne VYNECHANÉ generické témy ako "mild"/"hot"/"kids_snack", ktoré produkujú príliš agresívne páry). Curated `knowledge.json["CrossSell"]` (URL-resolved na product_id, overené 1000/1000 zhôd vo vzorke) a `app.fbt` posilňujú už ustanovené roly, nikdy nezavádzajú novú (Section 51 zadania).

**Kritický nález č.1 (pred nasadením):** priama curated `CrossSell` dáta pre reálny produkt jazmínovej ryže odporúčajú kari pastu + sójovú omáčku + MSG — presne ten typ "predpokladu kari", ktorý zadanie zakazuje pre holý dopyt (Section 31). Preto sa curated `CrossSell` NEPOUŽÍVA ako nezávislý spúšťač eligibility, iba na posilnenie roly už ustanovenej recipe/use_case kontextom.

**Kritický nález č.2 (self-audit):** prvá implementácia same-need exclúzie porovnávala `canonical_family` — príliš hrubé pre rodinu `sauce` (obsahuje sójovú/rybaciu/ustricovú/hoisin/čili omáčku ako navzájom odlišné doplnkové potreby). S family-level porovnaním by `fish_sauce` nikdy nemohla byť cross-sell kandidát pre sójovú omáčku, čo by ticho rozbilo presne Pad Thai scenár (Section 85). Opravené na `canonical_subfamily` porovnanie (fallback na `family` len keď `subfamily` je `None`, napr. curry pasta varianty).

**Zapojenie do `app/main.py`:** `should_cross_sell()`/`build_cross_sell()` sa volajú výhradne v novom V2.5 `structured_presentation` early-return bloku (t.j. iba pre FRESH primárnu odpoveď) — nikdy pre SHOW_MORE/SHOW_ALL pokračovanie (to sa vracia skôr vo funkcii a nikdy sem nedorazí, Section 36 automaticky splnené). Nový response field `cross_sell` (samostatný zoznam formátovaných produktov, nikdy nemieša do `products[]` ani nemení `matching_total`), plus `cross_sell_eligible`/`cross_sell_context_type`/`cross_sell_intro`.

**Overené naživo cez `app.main.chat()`:**
```
"ryza na sushi" -> primárne: 4× sushi ryža
  cross_sell_eligible=True, context=USE_CASE_COMPLETION
  -> Sójová omáčka (role=soy_sauce), Morské riasy SUSHINORI (role=nori), Ryžový ocot (role=rice_vinegar)
  0 prekryvov s primárnou množinou, 0 rovnakej-potreby (žiadna ďalšia ryža)

"jazminova ryza" -> cross_sell_eligible=False, reason="no_grounded_context" (konzervatívne, ako mandátne)
```

**Testy:** nový `tests/test_cross_sell.py` (21 testov — eligibility gate 7 scenárov, same-need contamination hard gate, duplicate exclusion, role generation zo skutočných dát, FBT sémantická validácia, multi-source ranking, role diversity/budget, reason grounding). **Plný beh: 752/752** (731 pred V2.6 + 21 nových), 0 regresií.

**Performance:** cross-sell pridáva ~0,19 ms/dopyt nad V2.4+V2.5 — zanedbateľné.

**Kritický nález pri živej verifikácii (pred nasadením):** `RECIPE_COMPLETION` bol štrukturálne nedosiahnuteľný v skutočnom `chat()` behu, hoci prešiel všetkými izolovanými testami. Príčina: routovacia kaskáda (`if already_have_subject: ... elif related_subject: ... else: <- V2.6 kód>`) zaručuje, že `related_subject` je vo `else:` vetve VŽDY nepravdivé (inak by sa kód tam nedostal vôbec) — pôvodná implementácia ale práve `related_subject` posielala do `should_cross_sell()`. Opravené použitím `memory_subject` (nezávisle perzistovaná session hodnota, kaskádou nikdy neprepisovaná). Overené naživo: "chcem robiť satay" → "kokosové mlieko" teraz správne ukáže sójovú omáčku, sezamový olej a červenú kari pastu ako recipe-completion cross-sell. Pri oprave sa najprv omylom použil štandardný Edit nástroj na `app/main.py` (byte-citlivý súbor), čo znormalizovalo line-endingy naprieč celým súborom (12 499 riadkov namiesto 11) — zachytené `git diff --stat` vs `--ignore-space-at-eol` kontrolou pred commitom, revertnuté a prerobené cez byte-safe patch skript.

**Riziká/obmedzenia (úprimne):** rozlíšenie SAMOTNEJ štruktúrovanej otázky ("akú ryžu?" má vedieť, že ide o sushi ryžu) je oddelený problém a stále závisí od pred-existujúceho `is_context_followup()` heuristického detektora (V2.1) — V2.6 ho zámerne nerozširuje (Section 34). Cross-sell recipe-kontext túto limitáciu už nemá (viď oprava vyššie). `BasketContext` je zámerne minimálny (žiadny reálny cart API v aktuálnej architektúre widgetu). Detail: `docs/cross-sell-audit.md`.

**Ďalší krok (mimo rozsahu tejto iterácie):** V2.7 — Workflow & Orchestration Migration.

### Sprint V2.7 – Workflow & Orchestration Migration

**Zadanie:** presunúť routovanie z ad-hoc `if/elif` kaskády v `app/main.py` smerom k čistej, testovateľnej orchestrácii — bez jednorazového prepisu, migrovať workflow po workflow, zachovať bezpečný legacy fallback.

**Kľúčový poznatok pred implementáciou:** `chat()`'s posledná `else:` vetva (post-V2.6) UŽ JE presne ten target flow, ktorý zadanie žiada — štruktúrovaný dopyt (V2.4) → retrieval (V2.4) → ranking (V2.4) → prezentácia (V2.5) → cross-sell eligibility (V2.6) → answer composer (V2.5). V2.7 túto cestu preto neprepisuje, ale **formalizuje** — pridáva explicitný, testovateľný label nad už prebehnutým rozhodnutím, presne v duchu Section 4/80 zadania ("Do not reimplement... Do NOT rewrite the entire system in one pass").

**Implementované:** nový modul `app/workflow_registry.py` — 11 stabilných `workflow_id` (`PRODUCT_LOOKUP`, `CATEGORY_BROWSE`, `ATTRIBUTE_SEARCH`, `USE_CASE_ADVICE`, `COMPARISON`, `REPLACEMENT`, `RECIPE_SHOPPING`, `FAQ_INFORMATIONAL`, `ORDER_TRACKING`, `SUPPORT_ESCALATION`, `LEGACY_FALLBACK`), `WorkflowContract` registry (`WORKFLOWS` dict — retrieval/presentation/cross_sell_policy/grounding/fallback per workflow), deterministický `select_workflow(RoutingSignals) -> WorkflowSelection`. Precedencia je 1:1 odvodená z REÁLNEHO poradia `if/elif` vetiev v `chat()` (Section 49), nie vymyslená — zdokumentovaná ako "interná routovacia mapa" v `docs/workflow-migration-audit.md`.

**Migračný stav (úprimný, nie ambiciózny):**
- **MIGRATED**: `PRODUCT_LOOKUP`, `CATEGORY_BROWSE`, `ATTRIBUTE_SEARCH` — tieto tri už bežia cez V2.4-V2.6 pipeline; V2.7 pridal live `workflow_id`/`workflow_confidence` do odpovede + analytický log, **bez zmeny existujúcej odpovede** (shadow-safe by construction, Section 20).
- **SHADOW**: `USE_CASE_ADVICE` (mimo V2.4 cesty), `COMPARISON`, `REPLACEMENT`, `RECIPE_SHOPPING`, `FAQ_INFORMATIONAL` — `select_workflow()` ich správne rozpozná a otestuje (viď mandátne scenáre nižšie), ale live zapojenie do `chat()` pre ich 8 samostatných early-return bodov je explicitne mimo rozsahu tejto iterácie (Section 5: migrovať postupne).
- **LEGACY**: `ORDER_TRACKING`, `SUPPORT_ESCALATION` — Foodland tieto funkcie vôbec nemá implementované; registry ich uvádza len pre úplnosť schémy (Section 6), nikdy sa neaktivujú (Section 80).

**Mandátne scenáre (Section 44, všetky overené):**
```
"jazmínová ryža"              -> ATTRIBUTE_SEARCH
"akú ryžu na sushi?"          -> USE_CASE_ADVICE
"jazmínová alebo basmati?"    -> COMPARISON
"alternatíva Kikkoman"        -> REPLACEMENT
"čo potrebujem na Pad Thai?"  -> RECIPE_SHOPPING
"čo je miso?"                 -> FAQ_INFORMATIONAL
"ukáž všetky"                 -> žiadny workflow_id (bypass, pure continuation)
"len 5 kg"                    -> follow-up refinement cez existujúci merge_constraints()
```

**Routing conflict (Section 48):** *"akú alternatívu ku Kikkoman na sushi?"* nesie zároveň `replacement_subject` aj sushi/use-case kontext. Keďže `replacement_subject` sa v reálnej kaskáde kontroluje skôr než štruktúrovaná cesta, `select_workflow()` správne vráti `REPLACEMENT` — overené testom.

**Kontext:** follow-up ("len 5 kg") a context switch (sushi → "kikkoman sójová omáčka") už fungujú cez existujúci V2.5/V2.6 mechanizmus (`memory_subject`, `merge_constraints()`) — V2.7 tento mechanizmus nemení, len ho pozoruje. Overené naživo: sushi kontext (`USE_CASE_ADVICE`) sa nepreleje do nasledujúceho nesúvisiaceho `PRODUCT_LOOKUP` dopytu v tej istej session.

**Testy:** nový `tests/test_workflow_registry.py` (27 testov — mandátne scenáre, fallback, precedencia/routing conflict, determinizmus, order/support cross-sell disabled, workflow contract integrity, end-to-end cez skutočný `chat()`). **Plný beh: 779/779** (752 pred V2.7 + 27 nových), 0 regresií.

**Riziká/obmedzenia (úprimne):** 5 SHADOW workflow nemá live `workflow_id` v `chat()` odpovedi — skutočné zapojenie live logovania pre ich early-return body je kandidát na ďalšiu fázu, nie zabudnutá práca. `main.py` routovacia kaskáda sa v tejto iterácii štrukturálne nezjednodušila (to by vyžadovalo prepísať 5+ samostatne testovaných legacy vetiev naraz) — `WORKFLOWS` registry je teraz jediný zdroj pravdy pre budúce postupné migrácie. Detail: `docs/workflow-migration-audit.md`.

### Sprint V2.8 – Recipe/Product Knowledge Graph & Ingredient Intelligence

**Zadanie:** naučiť Foodland AI Advisor chápať recepty a ingrediencie ako štruktúrovanú komerčnú znalosť — dish → recipe → ingredient → canonical ingredient concept → product concept → SKU — namiesto textového vyhľadávania, s explicitným substitučným grafom a reverse lookup ("čo môžem uvariť s X?").

**Kľúčový poznatok pred implementáciou (audit, `docs/recipe-knowledge-audit.md`):** CMS `Recipes` sekcia (58 záznamov) neobsahuje ŽIADNE ingrediencie, množstvá ani produktové odkazy — iba kuchyňu, SK názov a 7 lokalizovaných URL. Skutočný, produkčne overený ingrediencia-úrovne zdroj je `RECIPE_SHOPPING_CORE_QUERIES` (47 jedál, v produkcii od V2.1) doplnený o `MISSING_INGREDIENTS_BY_SUBJECT` (NOT_AVAILABLE suroviny) a `RECIPE_TITLE_PRODUCT_SUBJECTS` (dish alias index). V2.8 stavia graf na týchto reálnych dátach, nie na CMS Recipes.

**Implementované:** `app/ingredients.py` (deterministická normalizácia, kontrolovaný role slovník, `parse_quantity_text()`/`scale_quantity()`/`convert_to_base_unit()`), `app/recipe_graph.py` (`build_recipe_graph_index()` — ingrediencia-koncepty buď PRODUCT_TAXONOMY-backed cez skutočný V2.4 `retrieve_products_for_query()`+`rank_candidates()` [empiricky zistené, nie ručne mapované], alebo RECIPE_CURATED cez presné required/excluded frázy; `resolve_ingredient_products()`, reverse lookup, substitučný graf, graph integrity validácia), `app/recipe_shopping.py` (`build_recipe_shopping_plan()` — AVAILABLE/ALREADY_SATISFIED/NOT_AVAILABLE/UNKNOWN_MAPPING per ingrediencia, 4 oddelené coverage metriky, basket satisfaction, serving/package aritmetika). `scripts/recipe_graph_audit.py` (graph integrity + unresolved ingredient report, Section 68/69).

**Pokrytie:** 47 kurátorských jedál, 72 ingrediencia-konceptov (24 taxonomy-backed, 48 recipe-curated), 155 aliasov, 1 overená substitúcia (fish_sauce → vegánska náhrada, context=vegan), 15 priamych product→recipe odkazov (Products_AI), 4 ingrediencie bez aktuálneho katalógového pokrytia (čestne nahlásené, nie skryté).

**Zapojenie do `chat()`:** presne v bode, kde predtým bežal `recipe_shopping_core_products()` (`if recipe_subject:` vetva) — V2.8 plán prevezme produkt-selekciu pre 47 pokrytých jedál; zlyhanie alebo dish mimo grafu bezpečne padá na presne ten istý legacy kód ako pred V2.8 (Section 123). `sushi`/`tom_yum`/`kimchi_ramen` majú vlastné špecializované funkcie, V2.8 sa ich nedotýka. `RECIPE_SHOPPING` povýšené SHADOW → MIGRATED vo `workflow_registry.py` (rovnaké kritérium ako ostatné tri — primárna cesta je nový pipeline s explicitným legacy fallbackom).

**Kritické nálezy:**
1. **Ambiguous taxonomy resolution** (soy sauce) — žiadny z 47 jedál nešpecifikuje tmavá/svetlá sójová omáčka; keď sa dopyt zhoduje na viacerých `concept_id` naraz, rezolver sa zámerne vzdáva taxonomy-backed cesty namiesto vynúteného hádania (Section 92/141).
2. **Lexikálny scoring bug** (pho korenie ↔ Alphonso Mango) — prvá verzia lexikálneho rezolvera vracala prvú katalógovú zhodu bez skóre; bare `required_terms=("pho",)` zachytilo "Alphonso Mango Pyré" (obsahuje substring "pho"). Zachytené existujúcim regresným testom (`test_recipe_to_products_uses_phrase_subject_for_pho_bo_and_kimchi_ramen`), opravené identickým scoring systémom, aký už používa `app.main.recipe_core_product_candidates()`.
3. **Dish intent detection gap** ("Chcem robiť Pad Thai") — `is_recipe_intent()` vyžaduje marker ako "recept"/"ako pripravím"; mandátna V2.8 formulácia bez takého markera cez gate neprešla. Rovnaká trieda chyby ako existujúci "tom kha" fix — opravené identickým úzkym vzorom (`"pad thai"` pridané do `RECIPE_INTENT_MARKERS`). Čestne nahlásené: rovnaký gap existuje pre 56 z 60 dish markerov, mimo rozsahu tejto iterácie.

**Basket satisfaction:** implementované a otestované (`basket_product_ids` parameter, `basket_concept_ids()`), ale `ChatRequest` nemá žiadne cart/basket pole — `/chat` dnes nedostáva reálny signál o košíku, live zapojenie preto nie je možné bez API zmeny mimo rozsahu V2.8 (rovnaká SHADOW-capability disciplína ako V2.7).

**Testy:** `tests/test_recipe_graph.py` (24 — graph integrity, Pad Thai end-to-end, kolízne testy rice/soy/coconut/noodle, substitúcia, unresolved, multilingválne aliasy, reverse lookup, multi-ingredient discovery), `tests/test_recipe_shopping.py` (22 — plan building, basket satisfaction, quantity/serving/package aritmetika, 6 end-to-end `chat()` testov). **Plný beh: 825/825** (779 pred V2.8 + 46 nových), 0 regresií.

**Riziká/obmedzenia (úprimne):** žiadny reálny recept nemá štruktúrované množstvo/porcie — serving scaling a package count sú implementované a otestované, ale dnes voči živým dátam neaktívne (dormant). Required/optional/garnish nie je v zdrojových dátach rozlíšené — V2.8 konzervatívne označuje všetko ako REQUIRED. Basket satisfaction nemá live signál (vyššie). 56/60 dish markerov má rovnaký intent-detection gap ako Pad Thai mal pred touto iteráciou. Detail: `docs/ingredient-intelligence.md`, `docs/recipe-knowledge-audit.md`.

### Sprint V2.9 – Conversational Memory, Preference & Session Intelligence

**Zadanie:** naučiť Foodland AI Advisor sledovať prebiehajúcu nákupnú konverzáciu namiesto toho, aby každú správu spracovával ako novú, nezávislú otázku — perzistentné, ale explicitne oscopované constrainty/preferencie, ordinal referencie ("ten druhý"), pokračovanie receptu/porcií, a čisté zabudnutie pri zmene témy.

**Kľúčový poznatok pred implementáciou (audit, `docs/session-intelligence-audit.md`):** V2.5 `merge_constraints()` už rieši family/subfamily perzistenciu + package_size/brand override pre štruktúrovanú product retrieval cestu — V2.9 to nepremiestňuje. Chýbalo explicitné ODOBRATIE constraintu, a hlavne: **recepty (V2.8) nemali žiadnu konverzačnú kontinuitu vôbec** — `detect_recipe_subject()` sa volalo odznova každý ťah, žiadne pole nepamätalo aktívny recept. Priamym testom pred zmenou overené: "aké rezance?" po "Chcem robiť Pad Thai" padalo do generickej cross-sell vetvy namiesto pokračovania v recepte.

**Implementované:** nový modul `app/session_state.py` (žiadne nové úložisko — nové polia priamo v existujúcom process-local `session_memories` dict): `active_use_case`, `active_recipe_id`, `recipe_servings`, `last_recipe_ingredient_concept`, `selected_ingredient_products`, `recent_presentation_ids` + deterministické detektory (ordinal reference, cenová preferencia, veľkosť/značka odobratie, reset, recipe-followup rozpoznanie). `app/query_constraints.py: merge_constraints()` rozšírené o `remove_size`/`remove_brand`. `app/recipe_shopping.py: resolve_recipe_followup()` — hlavná nová schopnosť, plná recipe/servings kontinuita cez V2.8 gráf.

**Mandátny Pad Thai reťazec (Section 53, overený end-to-end cez skutočný `chat()`):**
```
"Chcem robiť Pad Thai pre 4. Čo potrebujem?"  -> 5 surovín, coverage 100%
"aké rezance?"                                 -> kandidáti na ryžové rezance
"ten druhý"                                    -> vybraný produkt označený ALREADY_SATISFIED
"a rybaciu omáčku?"                            -> kandidáti na rybaciu omáčku
"niečo lacnejšie"                              -> tí istí kandidáti zoradení podľa ceny
"nakoniec pre 8"                               -> servings=8, rezance ZOSTÁVAJÚ satisfied
"čo ešte potrebujem?"                          -> iba zostávajúce, nie znova rezance
"chcem kúpiť mlieko"                           -> hard switch: žiadny recipe_shopping_plan
```

**Kritické nálezy:**
1. Slovenské pádové tvary ("rybaciu omáčku" vs. kurátorská "rybacia omáčka") vyžadovali prefix-match namiesto presnej zhody tokenov pri priraďovaní správy k ingrediencii aktívneho receptu.
2. **Reálna regresia**: generické slová ako "omáčka" (spoločné naprieč desiatkami produktov) spôsobili, že "kikkoman sójová omáčka 1000 ml" (úplne nesúvisiaci konkrétny produktový dopyt) sa nesprávne priradil k Pad Thai fish_sauce role. Zachytené existujúcim V2.8 regresným testom pri plnom behu, opravené vylúčením zoznamu generických kategóriových slov z scoringu.
3. Audit pred zmenou odhalil, že sushi kontext ("aká ryžu?" po "chcem robiť sushi") vracal generickú, nie sushi-špecifickú ryžu — vyriešené `active_use_case="sushi"` narrowing (bare "ryža"/"ocot" → `sushi_rice`/`rice_vinegar`).
4. Testovaný scenár "sushi → hľadám Shin Ramyun" ukázal nesprávnu odpoveď AJ v úplne čerstvej session — potvrdené ako stateless nedostatok (nie session-kontaminácia), mimo rozsahu V2.9.

**Hard switch (Section 27/84):** recept aj use-case sa explicitne čistia, keď aktuálny ťah nie je pokračovaním — overené, že "chcem kúpiť mlieko" po Pad Thai shopping nenesie žiadny recept kontext ďalej.

**Testy:** `tests/test_session_intelligence.py` (19 — rice constraint matrix, sushi use-case matrix, plný Pad Thai reťazec, hard-switch kontaminačná matica, missing-state clarifikácia, reset, negácia/odobratie constraintu). Plný beh: **847/847** (828 pred V2.9 + 19 nových), 0 regresií.

**Riziká/obmedzenia (úprimne):** basket satisfaction funguje iba pre explicitne v konverzácii potvrdené výbery — `ChatRequest` stále nemá skutočné cart pole (rovnaké obmedzenie ako V2.8). Comparison continuity (Section 22) a replacement continuity (Section 25) neboli implementované — vyžadovali by ďalšiu kaskádovú chirurgiu v `chat()` bez toho, aby boli overené rovnako dôkladne ako recipe/sushi cesta; kandidát na ďalšiu iteráciu. Info→commerce ("čo je miso?" → "ktoré máte?") a product→recipe ("ukáž gochujang" → "čo s tým môžem uvariť?") transitions neboli zapojené live — V2.8 reverse lookup existuje a je otestovaný, ale nemá vlastný trigger v `chat()` tento šprint. Úložisko zostáva process-local (žiadny Redis/DB) — reštart Railway procesu vymaže session pamäť, čestne zdokumentované, nie riešené. Detail: `docs/session-intelligence.md`, `docs/session-intelligence-audit.md`.

**Ďalší krok (mimo rozsahu tejto iterácie):** V2.10 — Evaluation, Learning & Recommendation Quality Engine.

### Sprint V2.10 – Evaluation, Quality & Recommendation Intelligence Engine

**Zadanie:** postaviť trvalú, reprodukovateľnú evaluačnú vrstvu, ktorá objektívne odpovedá "urobila táto zmena Mei lepšou alebo horšou?" — namiesto spoliehania sa iba na unit testy a ručne vybrané produkčné dopyty.

**Kľúčový princíp (Section 115):** evaluátor existuje na to, aby NAŠIEL, kde je Mei zlá — nie aby dokázal, že je dobrá. Nikdy sa neoptimalizuje benchmark na vysoké skóre.

**Implementované:** nový balík `app/evaluation/` (schema, metriky, runner, konverzačný evaluátor, taxonomy quality, baseline/diff, loader, adapter) + `scripts/run_evaluation.py` CLI. Evaluátor beží cez SKUTOČNÝ `app.main.chat()` (Section 52 — nikdy druhá implementácia vyhľadávania), nikdy nemení runtime správanie. Golden dataset: 60 single-turn prípadov (`eval/golden/*.json`, reálne `app.taxonomy.FAMILY_DEFINITIONS` frázy, relevance počítaná proti aktuálnemu katalógu) + 4 multi-turn konverzácie (`eval/conversations/*.json`, priamo z overených V2.9 scenárov). 27 reálnych, predtým opravených produkčných bugov (`tests/regression_training_cases.jsonl`) konvertovaných do novej schémy ako trvalé regresné prípady (Section 91/92).

**Metriky:** eligibility precision, precision/recall/hit-rate@k, MRR, NDCG@k, duplicate rate, context contamination rate, taxonomy coverage+precision — všetko sémanticky (real taxonomy classification), nie lexikálne (Section 116).

**Kritické nálezy:**
1. **Nález v evaluátore samotnom**: prvá verzia adaptéra posielala všetkých 60 golden prípadov cez ROVNAKÚ session (prázdny `session_id` → zdieľaný anonymný fallback kľúč) — V2.9 session state unikal medzi nesúvisiacimi prípadmi (34/60 → 44/60 po oprave izolácie na unikátnu session per prípad). Presne tá trieda chyby, ktorú V2.9 existuje aby zabránila, teraz nájdená vo vlastnom testovacom nástroji.
2. **Reálny produkčný nález (neopravený tento šprint)**: bare dopyty na konkrétnu omáčku ("rybacia omáčka", "hoisin omáčka", "ustricová omáčka", "teriyaki omáčka", "čili cesnak omáčka") sa smerujú cez legacy `detect_related_subject()` cross-sell kaskádu namiesto čistej V2.4 `ATTRIBUTE_SEARCH` cesty — miešajú sa nesúvisiace variancie sójovej omáčky (Ponzu, Tamari) do výsledkov. Kritický golden prípad `sauce_fish_001` (Pad Thai ingrediencia) preto v baseline zlyháva. Zaznamenané, nahlásené, NEOPRAVENÉ (vyžadovalo by kaskádovú chirurgiu mimo rozsahu tohto sprintu) — prioritný kandidát pre V2.11.

**Baseline a quality gates:** prvý beh (`eval/baselines/v2.9.json`, commit `3e72ac5`) zaznamenáva 44/58 golden (75,9 %), 4/4 konverzácie, `context_contamination_rate=0,0`. Blokujúce CI brány (Section 38): iba (a) regresia KRITICKÉHO prípadu oproti baseline, (b) `context_contamination_rate > 0`, (c) `max_duplicate_rate > 0`. Existujúce, práve objavené zlyhania sú WARN, nezablokujú CI — baseline politika explicitne zdôvodnená v `docs/quality-gates.md` (Section 39-41: "use measured baseline before choosing thresholds").

**CI integrácia:** nový krok "Foodland quality suite (fast, blocking)" v `.github/workflows/ci.yml`, `python scripts/run_evaluation.py --fast` (39 kritických golden + 4 konverzácie, ~12s).

**Testy:** `tests/test_evaluation_engine.py` (30 — metrické výpočty, deliberate-failure detekcia dokazujúca, že evaluátor NIE JE "vždy prejde", baseline diff/gate logika, integrita datasetu), `tests/test_evaluation_golden.py` (1, plná pytest integrácia kritickej sady).

**Riziká/obmedzenia (úprimne):** cross-sell/recipe/autocomplete majú menej hĺbky pokrytia než rice/sauce taxonomy domény (bolo by potrebné rozšíriť dataset). NDCG implementovaný, ale bez graded-relevance prípadov v datasete (dormant, otestovaný len jednotkovo). Latency p99 (~1,4s pre jeden prípad) nebol hlbšie analyzovaný — pravdepodobne cold-search cesta, nie systémový problém. `related_subject`-vs-`ATTRIBUTE_SEARCH` precedenčný nález (vyššie) je najdôležitejšia otvorená otázka z tohto sprintu. Detail: `docs/evaluation-engine.md`, `docs/evaluation-dataset.md`, `docs/quality-gates.md`.

**Ďalší krok (mimo rozsahu tejto iterácie):** V2.11 — na základe nameraných V2.10 výsledkov, prioritne `related_subject`-vs-`ATTRIBUTE_SEARCH` precedenčná oprava.

### Sprint V2.11 – Ranking & Recommendation Optimization Engine

**Zadanie:** postaviť štruktúrovaný, vysvetliteľný, konfigurovateľný, category-aware, context-aware, evaluovateľný (cez V2.10), bezpečne-optimalizovateľný ranking engine, architektonicky pripravený na budúci V2.12 auto-learning systém — pri striktnom zachovaní invariantu, že V2.11 nikdy nemení eligibilitu produktu.

**Centrálny invariant (Section 3/8/9):** "V2.11 SMIE odpovedať 'ktorý validný produkt má byť prvý?' V2.11 NESMIE odpovedať 'ktorý produkt je validný?'" — eligibilitu vlastní výhradne V2.3 taxonómia / V2.4 retrieval / V2.8 recipe intelligence.

**Kľúčové zistenie z audit fázy (pred písaním kódu):** väčšina infraštruktúry, ktorú zadanie žiadalo, už existovala z predchádzajúcich šprintov — `app.behavioral.behavioral_multiplier()` malo Bayesian-vyhladenú CTR a ratio-clamping s nevyužitým `weight` parametrom, `app.cross_sell` malo už vlastný, architektonicky oddelený `rank_candidates()`/skóre systém. Skutočná medzera V2.11 nebola "postaviť normalizáciu od nuly", ale "spraviť existujúce, dobre postavené primitívy konfigurovateľnými/verzovanými/optimalizovateľnými" — táto scoping-úvaha priamo formovala rozsah implementácie.

**Implementované:** nové moduly `app/ranking_config.py` (`RankingProfile`/`RankingWeights` — validované s explicitnými hranicami, verzované a nemenné po uložení, family/category overrides s dedením, atomický `active.json` pointer swap pre okamžitý rollback bez redeploy), `app/ranking_features.py` (`RankingFeatures`/`explain_candidates()` — vysvetliteľnosť nad zdieľanými, nie duplikovanými, pomocnými funkciami z `app.ranking`), `app/ranking_optimizer.py` (bounded offline optimizer — deterministickí kandidáti podľa seedu, KAŽDÝ vyhodnotený cez skutočný V2.10 evaluation harness, multi-metric constrained objective, dve nezávislé bezpečnostné siete pre unsafe konfigurácie), `app/ranking_shadow.py` (baseline-vs-candidate porovnanie poradia in-process, nikdy nezasahuje do `active.json`), `scripts/ranking_cli.py` (`list`/`activate`/`explain`/`compare-profiles`/`optimize --save`). `app/ranking.py: rank_candidates()` rozšírené o voliteľný `ranking_profile` parameter — žiadny nový signál, iba konfigurovateľnosť nad existujúcimi troma soft signálmi (behavioral/merchandising/personalization), pri `ranking_profile=None` bit-presne identické s pred-V2.11 správaním.

**Dôkaz zachovania správania:** po zapojení do všetkých troch volaní `rank_candidates`-reťazca v `app/main.py`, `python scripts/run_evaluation.py --full` vrátil identických 44/58 golden, 4/4 konverzácie, rovnaké 3 kritické zlyhania ako baseline `eval/baselines/v2.9.json` — nulová zmena runtime správania pri predvolenom profile v1. Plný pytest, `consistency_audit.py` aj `trust_audit.py` nezmenené oproti pred-V2.11 stavu.

**Optimalizátor beží, ale úprimne nenašiel zlepšenie:** baseline má iba 1 `RANKING_ERROR` bucket zo 58 golden prípadov (zvyšné zlyhania sú `ELIGIBILITY_ERROR`/`RETRIEVAL_MISS`/`GROUNDING_ERROR`/`INTENT_ERROR`/`PRESENTATION_ERROR` — mimo rozsahu, čo `RankingProfile` môže vôbec ovplyvniť). Bounded search (`optimize --candidates 5 --seed 7`) preto odporúča ponechať default profil — zámerne nevyrobené žiadne umelé zlepšenie (Section 115/127).

**Testy:** `tests/test_ranking_config.py` (27 — bounds validácia vrátane deliberate-extreme reject, verzovanie/immutabilita, aktivácia/rollback), `tests/test_ranking_profile_wiring.py` (8 — default-preserved dôkaz, explicit-constraint-outranks-soft-signal invariant), `tests/test_ranking_optimizer.py` (11 — obe bezpečnostné siete, honest-no-improvement determinizmus), `tests/test_ranking_shadow.py` (4 — no-op na identickom profile, nedotknutosť `active.json`), `tests/test_cross_sell_ranking_isolation.py` (4 — architektonická separácia). Plný beh: **932/932** (878 pred V2.11 + 54 nových), 0 regresií.

**Riziká/obmedzenia (úprimne):** priestor pre reálne zlepšenie poradia je malý, kým `related_subject`-vs-`ATTRIBUTE_SEARCH` precedenčný nález z V2.10 zostáva neopravený (tá trieda chýb je retrieval/routing problém, nie ranking problém — `RankingProfile` ho principiálne nemôže vyriešiť). Optimizer používa jednoduchú bounded-perturbation stratégiu (nie Bayesian optimization/grid search) — dostatočné pre malý, dobre-ohraničený priestor váh tohto šprintu, ale kandidát na vylepšenie, ak sa priestor rozšíri. Plne automatizovaná apply-a-monitoruj slučka zámerne nepostavená (Section 130) — architektúra je pripravená (`optimize()` vracia priamo použiteľný `RankingProfile`), ale aktivácia zostáva ľudským krokom. Detail: `docs/ranking-engine.md`, `docs/ranking-profiles.md`, `docs/ranking-optimization.md`.

**Ďalší krok (mimo rozsahu tejto iterácie):** V2.12 — Controlled Auto-Learning & Self-Improvement Engine.

### Sprint V2.12 – Controlled Auto-Learning & Self-Improvement Engine

**Zadanie:** uzavrieť kontrolovanú slučku zlepšovania — Mei sa má vedieť učiť zo skutočnej zákazníckej interakcie, bez toho, aby smela potichu poškodiť sémantickú pravdu.

**Centrálny invariant (Section 141-146):** "BEHAVIOR MAY TEACH MEI 'which of these valid products customers tend to prefer', NEVER 'what this product IS'." `Learn ≠ Deploy` — každý naučený kandidát musí prejsť EVIDENCE→CANDIDATE→V2.10→SHADOW→APPROVAL→PRODUCTION. `NO_CHANGE > UNPROVEN_CHANGE`. `NO DATA > BAD LEARNING`.

**Kľúčové zistenie z audit fázy (pred písaním kódu):** repozitár už mal skutočný, end-to-end zadrôtovaný telemetria pipeline (`app.widget.js: fireEvent()` → `POST /events` → `events.jsonl`, čítaný `app.behavioral`/`app.fbt` od skoršieho šprintu) — reálny vektor typov je presne `impression`/`click`/`add_to_cart`/`no_result`/`autocomplete_select`/`search_submit`/`conversion` (definované, ale nikdy reálne odosielané — mŕtve)/`feedback`. V2.12-ová medzera nebola "postaviť zber udalostí", ale "naučiť sa z toho, čo sa už zbiera" — táto scoping-úvaha priamo formovala rozsah implementácie a viedla k čestnému zdokumentovaniu, ktoré časti zadania (napr. CROSS_SELL_*/RECIPE_* signály, samostatné AUTOCOMPLETE_SHOWN denominator) reálny event stream nevie podporiť bez novej frontend inštrumentácie, ktorú toto repo nemá.

**Implementované:** 7 nových modulov — `app/learning_events.py` (`LearningEvent` normalizácia/validácia/dedup nad reálnym streamom), `app/learning_signals.py` (`QueryProductSignal`/`QueryFamilySignal`/`ReformulationSignal`/`AutocompleteSignal` s position-bias normalizáciou využívajúcou skutočné poradie v `impression.product_skus`, Bayesian smoothing, confidence tiers, bot/anomaly cap), `app/learning_opportunities.py` (5 detektorov, detekcia nikdy nie je produkčná mutácia), `app/learning_candidates.py` (LOW-risk `RANKING_POSITION_ANOMALY` → `RankingProfile` kandidát, KAŽDÝ vyhodnotený cez skutočný V2.11 `evaluate_profile()` teda skutočný V2.10 harness), `app/learning_lifecycle.py` (plný promotion lifecycle, `approve_and_activate()` bezpodmienečne vyžaduje reálneho menovaného schvaľovateľa), `app/learning_cycle.py` (jediný orchestrátor zdieľaný medzi CLI a admin endpointmi). **Žiadny nový ranking systém** — priamy reuse V2.11 `evaluate_profile()`/`shadow_compare()`. Zapojené v `app/main.py` (byte-safe patch): 4 nové `/admin/learning/*` endpointy, `/health` pridáva agregátne `learning` pole, background `learning_cycle_loop()` (rovnaký vzor ako existujúci `feed_refresh_loop()`, defaultne vypnuté).

**Bezpečnostné mechanizmy (overené testami, nie len zadokumentované):**
1. Štrukturálny dôkaz proti "poisoningu" — kandidát generátor škáluje iba CELÚ rodinu (`RankingWeights` nemá pole pre konkrétny produkt), nikdy jeden produkt. Mandátny deliberate-poisoning test (Section 123) priamo nad `app.ranking.rank_candidates()` s maximálnou `behavioral_weight` a umelo vpichnutým "otráveným" produktom potvrdzuje, že explicitná zhoda stále vyhráva.
2. `approve_and_activate()` odmieta `approved_by` ∈ {"", "auto", "system", "automated", "bot", "cron"} bezpodmienečne, nezávisle od `LEARNING_AUTO_PROMOTION_ENABLED` (defaultne `false`).
3. Dve nezávislé siete pre unsafe kandidátov: bounds validácia PRED behom harness, kvalitná brána (reuse V2.10) PO behu.
4. Rollback je deterministický (`last_known_good` zaznamenaný PRED každou aktiváciou) a nikdy sa nespustí na business-metrický šum (reuse V2.10 brány, ktorá nemá CTR term).

**Zistená prevádzková medzera** (nie spôsobená týmto šprintom): `EVENTS_LOG_PATH` defaultne smeruje do dočasného adresára a Railway nemá nakonfigurovaný perzistentný volume — reálny nahromadený objem produkčných udalostí sa pravdepodobne stráca pri každom redeploy. Zdokumentované v `.env.example`, neopravené (infraštruktúrna zmena mimo rozsahu kódu).

**Čestný výsledok** (Section 137): toto prostredie nemá nahromadený reálny produkčný event log — `scripts/run_learning_cycle.py` proti aktuálnemu stavu vracia `insufficient_data`, nie fabrikované zlepšenie. Infraštruktúra je kompletná a otestovaná; tvrdiť opak by bolo priame porušenie zadania.

**Testy:** `tests/test_learning_events.py` (14), `tests/test_learning_signals.py` (15), `tests/test_learning_opportunities.py` (11), `tests/test_learning_candidates.py` (15), `tests/test_learning_lifecycle.py` (15), `tests/test_learning_cycle.py` (11), `tests/test_main_learning_endpoints.py` (11). Plný beh: **1024/1024** (932 pred V2.12 + 92 nových), 0 regresií.

**Riziká/obmedzenia (úprimne):** bez reálneho produkčného objemu nemožno potvrdiť, že minimum-support hranice (prevzaté z `app.fbt`-precedensu) sú správne kalibrované — budú vyžadovať prehodnotenie, keď/ak sa `EVENTS_LOG_PATH` presunie na perzistentné úložisko a nabehne skutočná prevádzka. Candidate generator pokrýva iba jeden typ zmeny (family-scoped `behavioral_weight`) — merchandising/personalization/FBT-weight learning ostávajú architektonicky pripravené (`RankingWeights` ich už má), ale negenerované tento šprint. Plne automatizovaná apply-a-monitoruj slučka zámerne nepostavená (Section 56) — `LEARNING_AUTO_PROMOTION_ENABLED` je dokumentovaný budúci rozširovací bod, nie niečo, čo tento kód volá. Detail: `docs/learning-engine.md`.

**Ďalší krok (mimo rozsahu tejto iterácie):** odporúčanie závisí od reálnych produkčných dát — priorita č. 1 je operatívna (Railway perzistentný `EVENTS_LOG_PATH`), nie kódová; kandidát na ďalšiu kódovú iteráciu je rozšírenie candidate generatora o merchandising/FBT-weight learning, keď/ak reálny objem preukáže, že je to potrebné.

### Sprint V2.12.1 – Production Hardening & Durable Learning Infrastructure

**Zadanie:** uzavrieť medzeru medzi "approval logika existuje" a "approval logika je dosiahnuteľná a prežije reálny Railway redeploy" – priama nadväznosť na V2.12, ktorého `approve_and_activate()`/`rollback_to_last_known_good()` nemali žiadny HTTP volací bod a ktorého runtime stav (ranking profily, learning history) defaultne mizol pri každom redeploy.

**Reálny nájdený bug (priorita č. 1 tohto šprintu):** `config/ranking_profiles/active.json` je git-trackovaný súbor. Bez explicitne nastaveného `FOODLAND_DATA_DIR` sa akákoľvek produkčná promócia ranking profilu ticho vrátila na commitnutý `v1` pointer pri ďalšom Railway redeploy – bez akejkoľvek chyby či upozornenia.

**Implementované (5 workstreamov):**
1. **Durable storage** – `app/storage_paths.py` (`FOODLAND_DATA_DIR` jeden prepínač namiesto siedmich nezávislých ciest), `app/durable_storage.py` (zdieľaný atomický zápis nahradzujúci 3 nezávislé implementácie), 3-stupňový fallback pre aktívny ranking profil (`active.json`→`last_known_good`→`DEFAULT_PROFILE`) s pozorovateľným `degraded` flagom v `/health`.
2. **Scoped admin auth** – `app/admin_auth.py`, trojúrovňová READ<OPERATIONS<PROMOTION autorizácia naprieč všetkými 14 pôvodnými `/admin/*` endpointami, legacy tokeny zachované na svojich pôvodných úrovniach, žiadny legacy token nikdy nezíska PROMOTION.
3. **Reálne approve/rollback endpointy** – `POST /admin/learning/candidates/{id}/approve`, `POST /admin/learning/rollback`, kandidáti trvalo uložení podľa ID, stale-candidate ochrana, idempotentné duplicitné volania.
4. **Explicitný Execution Context** – `app/execution_context.py` (CUSTOMER/EVALUATION/LEARNING/SHADOW/ADMIN_TEST), nahradzuje `isinstance(request, Request)` hotfix ako preferovaný signál pre rate-limiting a analytics suppression (pôvodná kontrola zachovaná ako fallback pre nemigrovaných volajúcich).
5. **Learning scheduler hardening** – overené, že periodická asyncio slučka prežije padnutý cyklus (scheduler-continuity test).

**Durabilita dokázaná, nie len tvrdená:** reálny Railway reštart AJ redeploy s aktivovaným testovacím kandidátom (dočasný, PROMOTION-scoped, env-flag-gated injection endpoint, odstránený po overení) – `active_ranking_config` prežilo oba nezmenené. Presne toto bol pôvodne rozbitý git-tracked-`active.json` scenár.

**Bezpečnostné invarianty (nezmenené, overené):** `AUTO_PROMOTION_ENABLED` zostáva `false`, `approve_and_activate()` bezpodmienečne vyžaduje reálneho menovaného schvaľovateľa, žiadna EVALUATION/LEARNING/SHADOW/ADMIN_TEST prevádzka nikdy nekontaminuje zákaznícku analytiku.

**Testy:** `tests/test_admin_auth.py` (17), `tests/test_durable_storage.py` (18), `tests/test_execution_context.py` (17), `tests/test_learning_approval_endpoints.py` (15), `tests/test_learning_cycle_hardening.py` (2), plus úpravy existujúcich testov po pridaní `answered` poľa a session-level opravách vykonaných v priebehu tej istej session. Plný beh: **1110/1110**, 0 regresií.

**Riziká/obmedzenia (úprimne):** `app/search.py`'s legacy scorer a ~25 sekundárnych `cached_search_products()` volaní zostávajú mimo rozsahu tohto šprintu – nie je to hardening problém, je to retrieval-kvalita problém (pozri V2.12.2/V2.12.3 nižšie). Detail: `docs/durable-learning-storage.md`, `docs/admin-security.md`, `docs/learning-approval-lifecycle.md`, `docs/internal-execution-context.md`, `docs/learning-operations-runbook.md`.

**Ďalší krok (mimo rozsahu tejto iterácie):** V2.12.2 — Query Semantics, Head-Concept & Constraint Enforcement (reálny produkčný nález: sémantické kontradikcie v product retrieval, napr. "kokosový olej" vracajúci kokosovú vodu/mlieko/krém).

### Sprint V2.12.2 – Query Semantics, Head-Concept & Constraint Enforcement

**Zadanie:** vybudovať všeobecnú sémantickú vrstvu obmedzení medzi dopytom zákazníka a product ranking – predpoklad zadania bol, že táto vrstva úplne chýba.

**Skutočný nález (líši sa od hypotézy zadania, Section 115-štýl požiadavka "nepapagájuj hypotézu"):** taxonomy-aware retrieval architektúra (`app.query_constraints`/`app.retrieval`/`app.taxonomy`/`app.ranking`, postavená v V2.3–V2.5) **už implementovala presne to, čo zadanie žiadalo** – head-concept extrakcia (`family`/`subfamily`), required-vs-preferred constrainty (`explicit_constraints`), skutočné set-intersection vylučovanie kontradiktórnych rodín. Nájdené boli **tri konkrétne chyby brániace konkrétnym dopytom dostať sa k tejto už existujúcej vrstve**, nie chýbajúci mechanizmus – žiadna nová paralelná architektúra nebola postavená (Section 8/22/92 zadania: "reuse rather than duplicate").

**Bug A** – `RELATED_INTENT_MARKERS` (321 fráz) obsahuje široké jednoslovné markery (`"rezanc"`, `"olej"`) určené na zachytenie skutočných receptových otázok, ktoré ale zametali aj holé produktové názvy ("ryžové rezance", "kokosový olej") do recept-companion cross-sell workflow namiesto priameho vyhľadania produktu. **Bug B** – `app/taxonomy.py` nemal žiadne `FamilyRule` pre `coconut_oil`/`coconut_cream`/`coconut_juice`/`coconut_vinegar`, hoci všetky štyri produkty reálne existujú v katalógu – bez pravidla dopyt nikdy nedosiahol `family`, vždy skončil na `LEGACY_FALLBACK`. **Bug D** – `SPECIAL_PRODUCT_QUERIES["sushi_rice"]`/`["rice_vinegar"]` sú legacy (pred-V2.4) hardcoded "bundle" vyhľadávania zlučujúce viacero nesúvisiacich pod-dopytov (napr. "sushi ryža" + "nori" + "ryžový ocot" + "wasabi") do jedného výsledku – cross-sell miešaný priamo do primárneho search výsledku. Druhá inštancia (rice_vinegar) nájdená až vlastným production smoke-testingom proti reálnemu Merchant feedu (2324 produktov), nie lokálnym statickým fixture snapshotom (2140 produktov) – dôkaz, prečo je live-feed validácia nevyhnutná, nie voliteľná.

**Oprava**: nový guard v `app/main.py` (`_query_resolves_to_confident_product_family()` + úzky, kurátorovaný `RECIPE_SHOPPING_LANGUAGE_MARKERS` zoznam) rieši Bug A; 4 nové `FamilyRule` v `app/taxonomy.py` riešia Bug B; zovšeobecnená supersession vetva (`elif special_subject in {"plain_rice", "sushi_rice", "rice_vinegar", "rice_cooker"} and ...`, s legacy fallback poistkou) rieši Bug D pre všetky bare-product-name `special_subject` hodnoty s vlastnou taxonomy rodinou – zámerne vynechala `rice_seasoning` (nemá vlastnú rodinu, migrácia by nesprávne rozšírila na generickú "rice").

**Výsledky:** V2.10 golden: **44/58 → 51/58** (+7), 3 kritické zlyhania → 1 (`rice_sushi_001`, `sauce_fish_001` opravené ako priamy dôsledok Bug D opravy; `regbug_rt0010` nedotknutý – bezpečnostný invariant "sójová omáčka bez sóje" = `max_products=0`, nie retrieval bug). Testy: `tests/test_query_semantics_v2122.py` (22, pozitívne aj negatívne assertions, Show More/follow-up preservation, brand/allergén regresné poistky). Plný beh: **1129/1129**, 0 nových regresií.

**Riziká/obmedzenia (úprimne, zdokumentované ako "Bug C"):** legacy `app/search.py::search_products()` – čisto additívny OR-based scorer bez minimálnej zhody tokenov – a jeho `PREFIX_SYNONYMS` mechanizmus (`data/synonyms.json`, injektuje generické korene ako `"kokos"`/`"ryz"` symetricky do dopytu AJ produktov) stále nemá žiadne taxonomy-aware vylučovanie. Používaný v ~25 sekundárnych `cached_search_products()` volaniach (cross-sell/replacement/FAQ fallback kontexty) – nedotknuté týmto šprintom, mimo rozsahu. Detail: `docs/query-semantics.md`.

**Ďalší krok (mimo rozsahu tejto iterácie):** V2.12.3 — Quality Closure (Bug C legacy scorer migrácia/hardening, `SPECIAL_PRODUCT_QUERIES`/`PREFIX_SYNONYMS` plný audit).

### Sprint V2.12.3 – Quality Closure, Legacy Retrieval Migration & Family-Purity Hardening

**Zadanie:** doriešiť "Bug C" (zdokumentovaný zvyškový dlh z V2.12.2 – legacy `app/search.py::search_products()` bez taxonomy povedomia) **na základe dôkazov, nie predpokladu** ("Do not state 'legacy scorer' as root cause unless the trace proves it"), doaudítovať `SPECIAL_PRODUCT_QUERIES`/`PREFIX_SYNONYMS`/bundle mechanizmy, spustiť sauce/paste/noodle/coconut/rice/brand/exact/UNKNOWN testovaciu maticu, vytvoriť čerstvý baseline bez prepísania historického `eval/baselines/v2.9.json`, explicitne klasifikovať `regbug_rt0010` ako `INTENTIONAL_SAFETY_BEHAVIOR` (nie retrieval bug).

**Dôkazová fáza (read-only research agent, celý call-graph):** `search_products()` má 2 call sites, `cached_search_products()` má **24 reálnych call sites** v `app/main.py` – žiadny neposiela StructuredQuery/taxonomy kontext, všetky volajú holým textom. `cached_search_products()` je navyše **bezpodmienečný fallback** samotného `hybrid_cached_search_products()`, kedykoľvek `parse_structured_query()` sebavedomo nerozpozná rodinu – legacy scorer teda beží aj na primárnej `/chat` ceste, nielen v 24 sekundárnych volaniach. `app/search.py` nemá a nemôže jednoducho získať prístup k `app.taxonomy` (kruhová závislosť – taxonomy už importuje search). `PREFIX_SYNONYMS` audit potvrdil naživo: `kokos`/`coconut` premosťuje 8 rodín, `ryz`/`rice` 10 rodín, `sojov`/`soy` 10 rodín, `rezance`/`noodles` naprieč `noodles`/`instant_food`.

**Zvolená stratégia (C – ohraničená tranzitná vrstva, nie A ani B):** migrácia 24 volajúcich (B) by zničila zámernú funkciu cross-sell/companion volaní (chcú súvisiace, nie identické produkty); prestavba `search.py` (A) by vyžadovala kruhový import alebo preposielanie StructuredQuery cez 24 miest – príliš invazívne. **Zvolené**: nová `_exclude_taxonomy_family_mismatches()` v `app/main.py`, volaná vnútri `cached_search_products()` – chráni všetkých 24 call sites naraz jedným miestom. Pre každé volanie interne rozpozná rodinu dopytu (`parse_structured_query`, funguje na holom texte) a vylúči kandidátov s inou, tiež rozpoznanou `canonical_family` z existujúceho `product_taxonomy_index`; neklasifikované produkty (66% katalógu) a nesebavedomé dopyty ostávajú nedotknuté; nikdy nevráti prázdny zoznam, ak vstup nebol prázdny (`LEGACY_SEARCH_FAMILY_GUARD_ENABLED` env flag).

**Sprievodné taxonomy medzery** (nájdené pri overovaní guardu, nie predpokladané): guard je len tak dobrý, ako rozpoznávanie rodiny pod ním – `"udon rezance"` sa mylne priraďovalo k `instant_food` cez generickú `"rezance"` frázu (produkty klasifikované správne cez kategóriu, dopyt-ako-text nie), čo guard aktívne premenilo na regresiu. Opravené: `wheat_noodles` dostalo `title_phrases=("udon",)`; nové `glass_noodles` pravidlo (14 reálnych produktov predtým mylne pod `instant_noodles`); `instant_noodles`'s exclude rozšírené o `omacka`/`sitko`/`shirataki`/`konjac` (sítko na rezance, konjac rezance, omáčky boli mylne "instantné rezance"); nové `chili_paste`/`tamarind_pasta` pravidlá (predtým `family=None` pre obe); anglické `title_phrases` doplnené do `soy_sauce`/`dark_soy_sauce`/`light_soy_sauce`/`fish_sauce`/`coconut_oil`/`rice_noodles` (systémová medzera – všetkých 7 testovaných anglických ekvivalentov predtým fungujúcich slovenských dopytov malo `family=None`).

**Interakcia s V2.12.2 Bug A guardom:** nové taxonomy pravidlá dali `"glass noodles"`/`"udon rezance"`/`"chilli paste"`/`"coconut oil"`/`"fish sauce"` vlastnú sebavedomú rodinu, čím existujúci Bug A guard automaticky presmeroval tieto dopyty z `RELATED_PRODUCT_QUERIES` bundlov (`sklenene_rezance`, `tamarind`) na priame vyhľadávanie – bez akejkoľvek zmeny v `RELATED_PRODUCT_QUERIES` samotnom.

**SPECIAL_PRODUCT_QUERIES audit:** zvyšných 21 z 25 kľúčov (4 migrované V2.12.2) potvrdených ako CONSTRAINT_BASED_LEGACY (diétne/pikantnosť jazyk, ktorému taxonomy prirodzene nerozumie) alebo bez taxonomy pokrytia – žiadna ďalšia migrácia opodstatnená dôkazmi. Detail: `docs/special-product-query-audit.md`.

**Výsledky:** V2.10 golden **51/58, 4/4 konverzačné, gate WARN** – identické s čerstvým baseline pred touto zmenou (0 nových regresií). Dve reálne regresie nájdené a opravené počas vlastného overovania (nie po nasadení): nová `chili_paste` fráza mylne predbehla existujúce `gochujang` pravidlo (Kórejské produkty majú v katalógu doslovný názov "Čili pasta Gochujang..."), opravené `exclude_title_phrases`; nová `tamarind_paste` subfamily/rule_id kolidovala s existujúcim recipe-graph konceptom (`tamarind_pasta`), premenované. Testy: `tests/test_query_semantics_v2123.py` (26, family-purity pozitívne aj negatívne assertions). Plný beh: **1132/1132**, 0 regresií.

**Ďalší krok:** subfamily-level presnosť v rámci tej istej rodiny (napr. miso vs. sójová fermentovaná pasta, tamarind vs. krevetová pasta) zámerne mimo rozsahu – rovnaký princíp, aký zadanie samo sankcionuje pre farbu curry pasty.

### Sprint V2.12.4 – Search Quality Observability & Production Relevance Monitoring

**Zadanie:** V2.12.1-V2.12.3 opravili konkrétne retrieval bugy, ale žiadna z nich nebola nikdy zistená automatizovaným meraním – všetky boli nájdené manuálnym testovaním. Zadanie explicitne nechce zmenu relevancie ("Do NOT implement another search engine. Do NOT optimize ranking weights simply because a metric is low. Measure first.") – cieľom je urobiť search relevanciu pozorovateľnou pred prípadným V2.13 workflow refaktorom.

**Architektúra (Invariant #1 – meria sa reálna zákaznícka cesta, žiadny paralelný engine):** dva integračné body, nulová zmena existujúcej retrieval logiky. `app.structured_search._log_shadow()` (existujúci V2.4 log point, predtým len do Python loggeru) teraz aj stashne rozhodnutie (`retrieval_mode`/`family`/candidate counts) do `ContextVar` (`app.search_quality.stash_retrieval_decision()` – obyčajné priradenie, nulová I/O réžia). `app.main._chat_internal()` (jediný zjednotený exit point pre všetkých ~13 `log_question(...)` vetiev `_chat_impl()`) číta stash po `_compute_answered()` a zapisuje `SearchQualityTrace` do `search_quality.jsonl`, ale LEN AK `execution_context.emit_customer_analytics` (V2.12.1 existujúce pole – rovnaká brána ako `log_question`/`log_event`). Nový modul `app/search_quality.py` je plne samostatný (žiadny import z `app.main`, rovnaký vzor ako `app.learning_events`) – žiadny z ~24 `cached_search_products()` call sites ani žiadna z existujúcich chat vetiev nebola upravená.

**Znovupoužitie namiesto duplikácie:** `app.learning_signals.detect_reformulations()` (V2.12, existujúce) sa znovupoužíva pre reformulation/Show-More analýzu zo skutočného `events.jsonl` – `search_quality.jsonl` je komplementárny, nie duplicitný zdroj (retrieval-decision snapshot vs. zákaznícka interakcia, korelovateľné cez `session_id`).

**Hard semantic canary:** `eval/search_quality_canaries.json` (10 kurátorovaných dopytov presne zo zadania Section 37, `expected_family`/`must_not_family` overené priamo proti katalógu). `scripts/run_search_quality_canary.py` a `POST /admin/search-quality/run` bežia cez skutočný `_chat_internal()` v `ADMIN_TEST` kontexte – overené testom, že 30 opakovaných behov nevytvorí ani jeden zákaznícky trace záznam (Section 39/94/127 mandátny test). Wrong-family leakage sa kontroluje proti skutočne vráteným produktom (`product_taxonomy_index`), nie len proti rozpoznanej rodine dopytu.

**Anomaly detection:** len rastúce rates s dostatočnou podporou (`SEARCH_QUALITY_MIN_SUPPORT_ANOMALY=50`) – `WARN` pri ≥30%, `CRITICAL` pri ≥75% relatívnom náraste; canary zlyhania sú vždy `CRITICAL`/`WARN` bez ohľadu na vzorku (tvrdé sémantické invarianty). `INSUFFICIENT_DATA` je platný, čestný výsledok (nikdy fabrikovaný záver pri nízkom objeme). Baseline promócia je výhradne explicitné/manuálne rozhodnutie (`save_quality_baseline()`), nikdy automatická po reporte.

**Admin endpointy:** `GET /admin/search-quality/{status,report,anomalies,canary}` (READ scope), `POST /admin/search-quality/run` (OPERATIONS scope – drahšia, stavová operácia). `AUTO_PROMOTION` zostáva `false` (Invariant #11) – žiadny anomaly detektor nemôže spustiť produkčnú zmenu. Verejné `/health` dostalo `search_quality` blok s len bezpečným agregátom (nikdy anomaly detail).

**Privacy:** žiadny raw query text v `search_quality.jsonl` – len `session_hash` (salted sha256) + `family`. Čítanie defenzívne re-filtruje `execution_mode == "CUSTOMER"` aj keď je zápisová brána už správna (druhá poistka proti internal-traffic poisoningu).

**Performance:** nameraný rozdiel CUSTOMER (s trace) vs. EVALUATION (bez trace) na 200 opakovaní: ~0.94ms/request absolútne – zanedbateľné voči reálnej produkčnej latencii dominovanej sieťou/OpenAI (V2.10 eval p95≈450ms).

**Výsledky:** V2.10 gate **51/58 nezmenené** (inštrumentácia nemení retrieval logiku). Testy: `tests/test_search_quality.py` (35 – customer trace emission, internal traffic exclusion vrátane 30-požiadavkového poisoning testu, legacy/semantic path metriky, no-result sémantika, canary pass/fail vrátane injected wrong-family prípadu, deployment-comparison anomaly detekcia, storage-failure resilience, admin endpoint scoping). Plný beh: **1196/1196**, 0 regresií. Detail: `docs/search-quality-observability.md`, `docs/production-relevance-monitoring.md`.

**Ďalší krok:** V2.13 workflow refaktor je opodstatnený LEN ak V2.12.3 retrieval closure zostáva stabilná A produkčné pozorovanie (tento sprint) neukáže nevyriešenú architektonickú search blokádu – zatiaľ nebol nahromadený dostatočný produkčný objem na promóciu baseline, takže toto rozhodnutie čaká na reálne dáta, nie je vynesené naslepo.

### Sprint V2.13a – AdvisorEngine Application Boundary & Internal Execution Unification

**Zadanie:** vytvoriť aplikačnú hranicu (transport/application separation) potrebnú pre V2.13b's WorkflowResolver, BEZ akejkoľvek zámernej zmeny routing precedencie, intent klasifikácie, retrievalu, rankingu, taxonómie, session sémantiky, recipe logiky, cross-sell, safety routingu ani presentation. Známe routing defekty musia zostať viditeľné ako baseline defekty – zadanie explicitne zakazuje "fix them while refactoring".

**Kľúčové zistenie (líši sa od predpokladu zadania):** `app.main._chat_internal()` už DNES bola takmer presne to, čo V2.13a žiada od `AdvisorEngine` – jediný zjednotený exit point pre všetkých ~13 vetiev `_chat_impl()` kaskády, execution-context-aware, s jedným miestom `SearchQualityTrace` emisie (V2.12.4). `chat()` HTTP route bola už tenký adaptér (`return _chat_internal(chat_request, request)`). Skutočná medzera nebola architektonická – bola v tom, že **duck-typed `_FakeRequest` shim bol nezávisle definovaný najmenej 6-krát** naprieč repozitárom (`app.evaluation.adapter` 2×, `scripts/run_search_quality_canary.py`, admin canary endpoint, testy) len na uspokojenie `get_client_key()`'s tvarovej požiadavky.

**Implementácia:** nový `app/advisor_engine.py` – `AdvisorRequest` (message/session_id/limit/conversation_history/client_id/`client_key` – nikdy FastAPI `Request`/headers/ASGI scope), `AdvisorResponse` (zámerne obyčajný `dict` typový alias, nie nová wrapper trieda – existujúci `/chat` response tvar je stabilný kontrakt pre ~40+ existujúcich test call sites, zadanie zakazuje redizajn), `AdvisorEngine.run()` deleguje CELÚ, NEZMENENÚ `_chat_internal()`/`_chat_impl()` kaskádu cez interný `_TrustedClientKeyRequest` shim (nahrádza 6 duplicitných definícií jednou). `chat()` HTTP route teraz rieši `isinstance(request, Request)` fallback + `get_client_key()` explicitne PRED volaním `AdvisorEngine` (rovnaký výsledok, len raz namiesto redundantne 2×). Migrovaní interní volajúci: `app.evaluation.adapter` (pokrýva V2.10 eval AJ V2.11 shadow AJ V2.12 learning tranzitívne), `scripts/run_search_quality_canary.py`, admin canary endpoint.

**Routing debt register:** `docs/routing-debt.md` – zo 7 zlyhaní V2.10 golden suite (51/58) len 2 sú skutočné routing/precedence defekty: `regbug_rt0004` ("súvisiace produkty k sushi ryži" – V2.12.2 Bug A guard potláča related_products, keď produktová rodina rezolvuje sebavedomo) a `regbug_rt0010` ("sójová omáčka bez sóje" – allergen/safety intent nemá prednosť pred product_search; oprava predošlej V2.12.3 klasifikácie `INTENTIONAL_SAFETY_BEHAVIOR` na presnejšie "routing/intent precedence gap"). Oba **charakterizované, NIE opravené** – testy dokazujú, že AdvisorEngine reprodukuje presne to isté existujúce správanie. `regbug_rt0013` označený `PENDING_SEMANTIC_PRODUCT_DECISION` (potrebuje ľudské rozhodnutie). Zvyšné 4 klasifikované ako evaluation wording mismatch / LLM textová variancia, nie routing.

**Overenie ekvivalencie (nie len architektonické, empirické):** `tests/test_advisor_engine.py` (18 testov) – AdvisorEngine vs. priame `_chat_internal()` volanie identické pre 13-dopytovú maticu (`answered`/`intent`/`workflow_id`/product ID poradie), multi-turn refinement sekvenciu (jazmínová ryža → 5kg → 1kg → lacnejšie), topic switch (sushi → Shin Ramyun), presne-raz vedľajšie efekty (1 `SearchQualityTrace` + 1 `question_analytics.jsonl` riadok na CUSTOMER volanie), `ContextVar` izolácia pod 20 súbežnými volaniami (cez `contextvars.copy_context().run()`, rovnaký mechanizmus ako Starlette), rate limiting (CUSTOMER cez engine limitovaný, EVALUATION nikdy), 30-volaniový internal-traffic-poisoning retest cez AdvisorEngine cestu.

**Výsledky:** V2.10 gate **51/58 nezmenené** (identické error buckets, identický critical failure). Hard canary **10/10 nezmenené**. Performance overhead AdvisorEngine vs. priame volanie: **~0.012ms/request (0.13% relatívne)** – prakticky nulový. Plný beh: **1214/1214** (1196 + 18 nových), 0 regresií. Detail: `docs/advisor-engine.md`, `docs/v2.13a-current-execution-map.md`, `docs/routing-debt.md`.

**Ďalší krok:** V2.13b (`TurnResolver` → `WorkflowResolver` → `WorkflowHandler`) je opodstatnený teraz, keď aplikačná hranica existuje a je empiricky overená ako behaviorálne ekvivalentná. Prvé dva mandátne routing testy pre V2.13b: `regbug_rt0004` (related-products fráza musí prebiť produktovú entitu) a `regbug_rt0010` (safety intent musí získať prednosť pred product retrieval).

### Sprint V2.13b – TurnResolver & Executable Workflow Resolution

**Zadanie:** vybudovať kauzálnu `TurnResolver` → `WorkflowResolver` architektúru, ktorá GENERICKY opraví `regbug_rt0004`/`regbug_rt0010`, bez prestavby retrievalu/rankingu/taxonómie, bez hardcodovania týchto dvoch konkrétnych golden dopytov.

**Implementácia:** nový `app/turn_resolver.py` (čistá signal-extraction vrstva nad UŽ existujúcimi detektormi) a `app/workflow_resolver.py` (`resolve_workflow(analysis) -> WorkflowResolution`, precedencia `RESULTSET_CONTINUATION > ALLERGEN_SAFETY > RELATED_PRODUCTS > LEGACY_FALLBACK`). Kauzálne zapojené do `_chat_impl()` na dvoch miestach – `rt0004` (special_subject už bezpodmienečne nenuluje related_subject, keď explicitný akčný jazyk signalizuje companion-request) a `rt0010` (safety má bezpodmienečne najvyššiu precedenciu, `allergen_product_query()`'s zámerný `""` signál sa už nezamieňa za "nerozpoznané").

**Kritický nález počas vlastného regresného overovania**: prvá verzia `resolve_action_target_signal()` nesprávne spúšťala RELATED_PRODUCTS aj bez skutočného special_subject/related_subject konfliktu – odhalené cez `regbug_rt0011` (session_id kolízia v `app.ranking_optimizer`), zúžené na overenie aj proti surovej správe. Táto konkrétna oprava sa neskôr ukázala ako príliš úzka (opravila jeden rozhodovací bod, nie celú triedu) – pozri Sprint V2.13b.1 nižšie.

**Výsledky:** V2.10 **51/58 → 53/58**, 0 kritických zlyhaní (predtým 1). Hard canary **10/10**. Testy: `tests/test_turn_resolver.py` (7), `tests/test_workflow_resolver.py` (10), `tests/test_routing_regressions.py` (16). Plný beh: **1247/1247**, 0 regresií. Detail: `docs/workflow-architecture.md`, `docs/workflow-precedence-v2.13b.md`, `docs/routing-debt.md`.

### Sprint V2.13b.1 – Contextualization Safety & Session Contamination Hardening

**Zadanie:** V2.13b's `regbug_rt0011` oprava bola úzko scoped na jeden rozhodovací bod. Tento sprint rieši SYSTEMICKÚ príčinu – `contextualize_message()`'s bezpodmienečná `diet_terms` injekcia do textu, ktorý kŕmi workflow-routing detektory – bez redizajnu retrievalu/rankingu/taxonómie/workflow precedencie.

**Root cause (plný audit `docs/contextualization-risk-v2.13b.1.md`)**: `contextualize_message()` pripája posledné 2 `diet_terms` z pamäte do KAŽDEJ nasledujúcej správy bezpodmienečne – mimo `is_context_followup()` brány, ktorá chráni legitímny subject-carryover o riadok vyššie. Leftover diet slová z jedného ťahu tak mohli manufacturovať falošný `special_subject`/`related_subject` konflikt na nesúvisiacom neskoršom ťahu v tej istej session.

**Zvažovaná a zamietnutá alternatíva**: plná `ContextMergePolicy`/`ContextConflict`/`provenance`-enum architektúra podľa pôvodného zadania. Po audite zistené, že Invariant "explicit current turn wins" je už štrukturálne zaručený `is_context_followup()`'s úzkou bránou (krátka/presná fráza bez vlastného predmetu) – konflikt so subject-carryoverom je principiálne nemožný, netreba naň novú arbitration vrstvu. Plná trieda-hierarchia by riešila hypotetické riziko bez dôkazu za výrazne väčší blast-radius.

**Implementácia**: nová `app.main._routing_message()` – identický `is_context_followup()`-gated subject-carryover, NIKDY `diet_terms`. Nahradila `contextual_message` na 9 routing-kritických miestach (`special_subject`, `related_subject`, `already_have_subject`, `replacement_subject`, `article_product_subject`, `resolve_action_target_signal()` + 4 refining guardy). `contextualize_message()` samotná nezmenená – naďalej kŕmi retrieval/knowledge search/recipe subject/cross-sell/odpoveďové texty, kde diet-term kontext je zámerná, testovaná hodnota.

**Výsledky:** V2.10 **53/58 nezmenené**, 0 kritických zlyhaní. `regbug_rt0011` teraz FIXED_V2_13B_1 (permanentný regresný test, generický – overený s odlišným diet termom). Testy: `tests/test_session_contamination_v2_13b_1.py` (14). Detail: `docs/contextualization-risk-v2.13b.1.md`, `docs/session-context-model.md`.

### Sprint V2.13c – Workflow Architecture Closure (partial)

**Zadanie:** urobiť `WorkflowResolver` autoritatívnym aj pre VYKONANIE (Invariant #1: resolver rozhoduje, executor vykonáva), nie len pre rozhodnutie – bez zmeny správania.

**Implementácia:** plný audit `_chat_impl()` (21 vetiev, `docs/workflow-inventory-v2.13c.md`). Nový `app/workflow_executor.py` (`WorkflowResult = dict`, rovnaké zdôvodnenie ako `AdvisorResponse`) – `execute_resultset_continuation()`, `execute_allergen_safety()`, oba mechanicky presunuté (nie duplikované) z pôvodných inline blokov.

**Rozsahové rozhodnutie**: migrované len 2 zo 4 `workflow_id` – jediné dve, ktoré sú súčasne resolver-driven AJ plne samostatné. `RELATED_PRODUCTS`'s vykonanie zdieľa ~250 riadkov prezentačnej logiky s 8 legacy vetvami – extrakcia by vyžadovala buď duplikáciu (zakázané), alebo oveľa väčšiu reštrukturalizáciu naraz (zakázané zadaním – incremental migration only).

**Výsledky:** V2.10 **53/58 nezmenené**, canary **10/10**. Testy: `tests/test_workflow_executor_v2_13c.py` (9). Plný beh: 0 regresií.

**Čestný výsledný stav**: **WORKFLOW_ARCHITECTURE_PARTIALLY_CLOSED**, nie CLOSED – `_chat_impl()` naďalej obsahuje ~9 vetiev nezávisle rozhodujúcich mimo `WorkflowResolver` (`LegacyWorkflowAdapter`, sankcionovaný už V2.13a/V2.13b, nie nová medzera). Detail: `docs/workflow-architecture.md`, `docs/workflow-inventory-v2.13c.md`, `docs/workflow-migration-v2.13c.md`.

**Ďalší krok:** Úplné uzavretie (`WORKFLOW_ARCHITECTURE_CLOSED`) by vyžadovalo viacsprintovú migráciu zvyšných ~9 legacy vetiev s dôkladným charakterizačným pokrytím každej – kandidát na budúcu iteráciu, ak sa ukáže opodstatnený (nie automaticky V2.14).

### Sprint V2.13d – Legacy Workflow Migration & Architecture Closure (partial)

**Zadanie:** dokončiť migráciu zvyšných legacy vetiev do kanonického `app.workflow_executor` – cieľ `WORKFLOW_ARCHITECTURE_CLOSED`.

**Kľúčové zistenie**: priame prečítanie aktuálneho kódu (nie opätovné použitie V2.13c dokumentácie) ukázalo, že V2.13c's odhad "~9 podobných vetiev" bol príliš zjednodušujúci. 6 z nich (`missing_composition`, `faq`, `random_recipe`, `reset`, `out_of_domain`, `category_discovery`) sú v skutočnosti PLNE samostatné, okamžité `return` bloky – rovnaký tvar ako `ALLERGEN_SAFETY`, ktorý V2.13c už úspešne migroval. Všetkých 6 migrovaných mechanickým presunom.

**Skutočný nález počas regresného overovania** (nie súčasť pôvodného zadania): `_chat_impl()` lokálne prevíaže meno `log_question` na no-op lambdu pod `EVALUATION`/`LEARNING`/`SHADOW`/`ADMIN_TEST` kontextom – funguje pre pôvodných ~13 volacích miest v TEJ ISTEJ funkcii, ale NEPREŽIJE presun cez modulovú hranicu. Executor handler volajúci `m.log_question(...)` vždy zasiahol skutočnú, bezpodmienečnú funkciu, čím ticho porušil analytics-izoláciu neinteraktívnych kontextov – týkalo sa VŠETKÝCH 7 handlerov volajúcich `log_question()` (aj V2.13c's `execute_allergen_safety` retroaktívne). Odhalené plným pytest behom (`tests/test_execution_context.py`), nie code review. Opravené explicitným `emit_customer_analytics: bool` parametrom v každom handleri.

**Rozsahové rozhodnutie**: zvyšné 2 jednotky (recipe stavový automat – reťaz vzájomne závislých early-return krokov, kde poradie a presné podmienky SÚ sémantika; commerce matches-dispatch pipeline vrátane `RELATED_PRODUCTS`'s vykonania – ~30+ vzájomne závislých lokálnych premenných, zistené priamym pokusom o extrakciu, nie predpokladom) zostávajú nemigrované. `BLOCKED_WITH_REASON`, nie prehliadnuté.

**Výsledky:** V2.10 **53/58 nezmenené**. Canary **10/10**. Testy: `tests/test_workflow_executor_v2_13d.py` (16). Plný beh: **1287/1287** (1271 + 16 nových), 0 regresií po oprave.

**Čestný výsledný stav**: **WORKFLOW_ARCHITECTURE_PARTIALLY_CLOSED**, nie CLOSED – ale s výrazne menším, presnejšie vymedzeným zvyškovým dlhom (2 jednotky namiesto 9 vetiev). Detail: `docs/workflow-architecture.md`, `docs/workflow-migration-v2.13d.md`.

**Ďalší krok:** Úplné uzavretie by vyžadovalo dedikovanú, dôkladne charakterizovanú migráciu recipe stavového automatu a commerce matches-dispatch pipeline – vzhľadom na ich preukázanú zložitosť (30+ premenných, stavovo závislé early-returny) kandidát na samostatný budúci sprint s rozsiahlym testovacím pokrytím pred akýmkoľvek presunom kódu, nie na pokračovanie súčasným tempom.

### Sprint V2.13e – Recipe State Machine Extraction

**Zadanie:** dokončiť migráciu recipe stavového automatu do kanonického `app.workflow_executor` – prísne podľa disciplíny OBSERVE→MAP→CHARACTERIZE→TEST→FREEZE→FORMALIZE→EXTRACT→COMPARE→REGRESSION, žiadne presúvanie kódu pred charakterizáciou.

**Kľúčové architektonické zistenie**: recipe logika v `_chat_impl()` pozostávala z 5 blokov (setup recipe-followup, ordinálna referencia, osirelý follow-up, hlavný `recipe_subject` handler, `recipe_followup_result` handler), ale 2 z nich (ordinálna referencia, osirelý follow-up) **nie sú recipe-špecifické** – sú to všeobecné session-continuity clarifikačné vzory, ktoré recipe stav používajú len ako súčasť gate podmienky. Priamy dôkaz: tieto 2 bloky majú podmienky PÁROVO VYLUČUJÚCE sa s recipe-vykonávajúcimi blokmi – pre daný ťah platí najviac jeden zo 4 blokov, čo umožnilo bezpečne presunúť len 2 skutočne recipe-špecifické terminálne bloky.

**Implementácia:** `app.workflow_executor.execute_recipe()` – hlavný `recipe_subject` handler (V2.8 recipe graph) + `recipe_followup_result` handler zlúčené do jednej funkcie, mechanicky presunuté. Charakterizácia PRED extrakciou: 19 testov (`tests/test_recipe_state_machine_v2_13e.py`) napísaných a spustených proti PRED-extrakčnej implementácii (19/19), potom extrakcia, potom rovnaké testy znova proti PO-extrakčnej implementácii (identický výsledok – dôkaz behaviorálnej parity).

**Výsledky:** V2.10 **53/58 nezmenené**. Canary **10/10**. Performance: 38,8 ms/volanie pred vs. 39,4 ms/volanie po (zanedbateľný rozdiel).

**Čestný výsledný stav**: **RECIPE_STATE_MACHINE_EXTRACTED**. Celkový architektonický stav zostáva **WORKFLOW_ARCHITECTURE_PARTIALLY_CLOSED** – zvyšný dlh znížený z 2 jednotiek na **1** (LEN commerce matches-dispatch pipeline). Detail: `docs/recipe-state-machine-v2.13e.md`, `docs/workflow-architecture.md`.

**Ďalší krok:** V2.13f-A – Commerce Pipeline Characterization (LEN charakterizácia, nie extrakcia) je kandidát na budúci sprint, ak sa ukáže opodstatnený. Neodporúča sa automaticky spustiť.

### Sprint V2.13f-A – Commerce Pipeline Characterization + GO/STOP Decision Gate

**Zadanie:** vykonať výhradne charakterizáciu (CFG, data-dependency graf, side-effect map, coupling klasifikácia, money-path analýza) poslednej zostávajúcej legacy jednotky – commerce matches-dispatch pipeline – BEZ akejkoľvek extrakcie, refaktoru či presunu kódu, a ukončiť explicitným rozhodnutím: `GO_TO_V2_13F_B`, `ACCEPT_PARTIALLY_CLOSED`, alebo `CHARACTERIZATION_INSUFFICIENT`. Zadanie explicitne: GO nie je predvolený výsledok, ACCEPT_PARTIALLY_CLOSED je platný úspešný výsledok, dôkazné bremeno je na extrakcii.

**Kľúčové zistenie**: priame prečítanie a enumerácia (nie odhad) potvrdili a spresnili V2.13d's "~30+ premenných" nález na presné číslo – **34 lokálnych premenných, 31 s reálnym fan-in** do terminálneho rozhodnutia, **8 vzájomne sa vylučujúcich terminálnych `return` miest** (oproti 2 u recipe stavového automatu), 6 z 9 vedľajších efektov bezpodmienečné a vykonané PRED terminálnym rozhodnutím. Naviac objavené (nie hľadané, vedľajší produkt charakterizácie) 2 nezávislé, reálne (nie hypotetické) nekonzistencie tvaru odpovede: 2 z 8 terminálnych vetiev (OpenAI transient-error, generický exception handler) vynechávajú kľúče `"memory"`/`"intent"` prítomné v každej inej vetve; `"response_mode"` chýba v 4 z 8. Oba priamo reprodukované testom, NEOPRAVENÉ (mimo rozsahu charakterizačnej sprinty).

**14-kritériový GO/STOP scorecard**: 6× FAIL, 4× PASS, 3× PARTIAL/LOW hodnota, 1× HIGH blast-radius – FAIL na všetkých kritériách s najvyššou váhou pre riziko (jednotný návratový kontrakt, ohraničený lokálny stav, izolácia vedľajších efektov, redukovateľnosť na čistú funkciu, dokázateľnosť mechanickým presunom, predošlé extrakčné pokusy). Zvážené a zamietnuté 3 extrakčné možnosti (jedna funkcia analogicky k `execute_recipe()`; rozdelenie na 3 funkcie podľa konceptuálnych švov; extrakcia len terminálneho fan-outu) – žiadna nesplnila latku V2.13e.

**Výsledky:** 13 nových charakterizačných testov (`tests/test_commerce_pipeline_v2_13f_a.py`), všetky PASS, priamo overujúce CFG/DFG/side-effect nálezy vyššie na reálnom katalógu (nie mock dáta). Plný beh: **1306/1306** pred aj po (žiadny kód sa nezmenil).

**Čestný výsledný stav**: **`ACCEPT_PARTIALLY_CLOSED`** – explicitne platný, úspešný koncový stav podľa zadania. Architektonický stav zostáva **WORKFLOW_ARCHITECTURE_PARTIALLY_CLOSED**: 9 z ~11 pôvodných vetiev na `app.workflow_executor`, táto jedna pipeline zostáva vedome, s úplnou formálnou charakterizáciou, na legacy ceste. Detail: `docs/commerce-pipeline-v2.13f-a.md`, `docs/workflow-architecture.md`.

**Ďalší krok:** žiadna ďalšia extrakcia sa po tomto STOP rozhodnutí v tejto sprinte nepokúša (zadanie to explicitne zakazuje). Samostatný, nízko-rizikový budúci kandidát: doplniť chýbajúce `"memory"`/`"intent"`/`"response_mode"` kľúče do 2–4 terminálnych vetiev (Sekcia 8 `docs/commerce-pipeline-v2.13f-a.md`) – malý, úzko vymedzený bugfix nezávislý od extrakčnej otázky.

### Sprint V2.13g – Response Contract Consistency Hardening & Architecture Closure

**Zadanie:** NIE workflow-refaktoring, NIE V2.13f-B – opraviť presne tie 2 nekonzistencie tvaru odpovede, ktoré V2.13f-A charakterizácia našla (chýbajúce `memory`/`intent` v 2 z 8 terminálnych vetiev commerce pipeline, chýbajúci `response_mode` v 4 z 8), zdokumentovať kanonický `/chat` response kontrakt, a formálne uzavrieť celý V2.13 architektonický program bez znovuotvorenia extrakčnej otázky.

**Nezávislé overenie**: pred implementáciou znovu prečítané `app/main.py` a `app/workflow_executor.py` priamo (nie prevzatie V2.13f-A dokumentu) – potvrdené identické riadkové čísla (žiadny drift od V2.13f-A baseline, HEAD stále `119b06b`), a navyše zistené (system-wide dôkaz): všetkých 9 `app.workflow_executor` handlerov už malo `memory`/`intent` bezpodmienečne – toto potvrdilo klasifikáciu oboch polí ako `REQUIRED_ALWAYS` naprieč CELÝM `/chat` kontraktom, nie len commerce pipeline. `response_mode` naopak malo len `RESULTSET_CONTINUATION` – potvrdené ako `REQUIRED_WHEN_APPLICABLE`, scoped na commerce/vyhľadávaciu rodinu odpovedí, nie univerzálna požiadavka.

**Frontend audit** (Section 11 zadania): `app/widget.js` nikdy nečíta `data.memory` ani `data.response_mode` (priamo overené grepom všetkých `data.\w+` výskytov) – pôvodné nekonzistencie teda neboli zákaznícky-viditeľný defekt, len kontraktová medzera pre iných konzumentov (`app.evaluation.conversation`'s `expected_response_mode` assertion, budúce analytics/admin nástroje). `app/widget.js` sa touto sprintou nemenil.

**Implementácia**: 6 terminálnych `return` blokov v `app/main.py` (byte-safe, anchor-based nahradenie s flexibilným CRLF/LF regexom kvôli historicky zmiešaným line endingom tohto súboru) – každý dopĺňa `intent`/`memory` z UŽ vypočítaných lokálnych premenných (`intent` z Fázy 4, `updated_profile` z Fázy 6 charakterizácie V2.13f-A, obe bezpodmienečne vypočítané pred terminálnym fan-outom) a jednu z 3 nových `response_mode` hodnôt: `"llm"` (OpenAI-zložená odpoveď), `"fallback"` (3 non-LLM fallback vetvy – no-API-key, transient error, generic exception, identická `fallback_answer()` kompozícia), `"no_match"` (2 nulové-výsledkové vetvy). Zámerne len 3 nové hodnoty, nie veľký nový enum (zadanie Section 10: "define exactly ONE clearly named fallback unless repository evidence requires otherwise" – evidencia 3 skutočne odlišných kompozičných mechanizmov odôvodnila 3, nie 1). Žiadne nové volanie, žiadne nové routovanie, žiadne pretriedenie 9 vedľajších efektov identifikovaných V2.13f-A charakterizáciou – priamo overené testom (presne-raz analytika aj cez OpenAI výnimku, presne-raz OpenAI volanie, execution-context izolácia nedotknutá).

**Testy**: `tests/test_commerce_pipeline_v2_13f_a.py` – trieda `TestTerminalReturnShapeInconsistency` premenovaná na `TestTerminalReturnShapeConsistency`, 4 testy aktualizované na assertovanie OPRAVENÉHO kontraktu namiesto zamrazenia pôvodnej chyby, s explicitným docstring vysvetlením prečo a kedy sa očakávanie zmenilo (Section 13 zadania – "update that expectation explicitly and document why"). Nový dedikovaný `tests/test_response_contract_v2_13g.py` (13 testov) – 8-vetvová kontraktová matica (`answer`/`products`/`intent`/`memory`/`response_mode` na každej z 8 vetiev) + mandatórne error-path regresie (presne-raz analytika, presne-raz OpenAI volanie napriek internému retry, žiadna duplicitná session mutácia, `evaluation_context()` analytics-suppression nedotknuté).

**Kontroly**: rt0004 (`related_products`, 6 produktov), rt0010 (`allergen_safety`, 0 produktov), rt0011 (`product_search` na oboch ťahoch, žiadna kontaminácia), recipe stavový automat (initial → shopping → followup → hard switch → allergen → reset, všetky správne), ResultSet continuity (Show More, size refinement 5kg, `result_set_id` konzistentné), commerce dopyty (jazmínová/basmati ryža, Kikkoman, Shin Ramyun, topic switch) – všetky nezmenené oproti V2.13f-A baseline.

**Výsledky:** Plný beh **1332/1332** (1319 + 13 nových), 0 regresií. V2.10 fast-mode **34/39 nezmenené** (identické error buckety pred/po opravou). Canary **10/10**, no anomalies. Consistency/trust/deployment audity čisté. `git diff --check` čistý (byte-safe patch prešiel bez neúmyselného celofilového posunu).

**Formálny výsledný stav**: **`RESPONSE_CONTRACT_HARDENED`** (V2.13g) + **`WORKFLOW_ARCHITECTURE_PARTIALLY_CLOSED_ACCEPTED`** (celý V2.13 program, formálne uzavretý) – vedomé, zdôvodnené architektonické rozhodnutie, nie nedokončená úloha. Commerce matches-dispatch pipeline zostáva presne 1 zámerne prijatá zostávajúca `legacy_primary_execution_branch_count` jednotka. `V2.13f-B` zostáva `STOPPED_BY_GO_STOP_DECISION` – táto sprinta ho neotvorila znova, len opravila povrchový kontrakt. Detail: `docs/response-contract-v2.13g.md`.

**Ďalší krok:** žiadne ďalšie V2.13 commerce extrakčné sprinty bez nového dôkazu (Section 33 zadania: opakované defekty spôsobené inline architektúrou, preukázaná neschopnosť implementovať požadovanú funkciu, podstatne silnejšie charakterizačné pokrytie, alebo nová architektúra znižujúca blast radius). Odporúčaný ďalší program: **V2.14 – zákaznícky-orientovaná commerce/recommendation inteligencia** (mimo rozsahu tejto sprinty, nezačaté).

### Sprint V2.14a – Recommendation Intelligence Foundation, Evidence Audit & Confidence Contract

**Zadanie:** AUDIT FIRST, CONTRACT SECOND, IMPLEMENTATION ONLY IF JUSTIFIED. Zistiť, akú recommendation inteligenciu Foodland už má, čo reálne dáta unesú ako dôkaz, a definovať bezpečný confidence kontrakt – NIE predpokladať potrebu nového recommendation enginu. `WORKFLOW_ARCHITECTURE_PARTIALLY_CLOSED_ACCEPTED` sa neotvára, V2.13f-B sa nerieši.

**Kľúčové zistenie #1 (existujúca infraštruktúra)**: `app.workflow_registry` už od V2.7 pozná `COMPARISON` aj `USE_CASE_ADVICE` ako pomenované `workflow_id` s vlastným kontraktom, oba `migration_status=SHADOW` – nálepka pre analytiku existuje, reálne vykonanie bolo vedome odložené ("re-platforming ... exactly the one-shot rewrite the spec forbids"). `USE_CASE_ADVICE` mechanizmus (`app.cross_sell`'s `USE_CASE_COMPLETION`) je reálny a deterministický, ale `_USE_CASE_TO_SOURCE_KEYS` obsahuje presne JEDNU hodnotu (`sushi`) – potvrdené priamo v kóde. `COMPARISON` sa spúšťa len keď existujúca FAQ odpoveď navyše obsahuje porovnávacie markery – nikdy pre priame porovnanie dvoch pomenovaných produktov, čo živý test priamo potvrdil ("Kikkoman alebo Yamasa?" vrátilo nesúvisiace produkty, nulová komparatívna logika).

**Kľúčové zistenie #2 (reálne dátové pokrytie, živo namerané, nie odhadnuté)**: taxonomy `canonical_family`/`canonical_subfamily` pokrýva 34,4% katalógu (HIGH=24,8% kategória-cesta-backed, MEDIUM=9,2%, LOW=0,4% len text, UNKNOWN=65,6% žiadne tvrdenie možné). Štruktúrované dietárne pole neexistuje vôbec (0%) – jediný reálny zdroj (`Products_AI.Atribúty`) pokrýva 2,4% katalógu. `price`/`unit_pricing_measure`/`brand` majú vysoké pokrytie (100%/75,4%/95,7%) a sú bezpečné pre štrukturálne porovnanie. Recipe graph: 47 jedál, 74 ingredient-role konceptov, presne 1 substitučná hrana.

**Evidence/confidence kontrakt**: nový, izolovaný `app/recommendation_evidence.py` – `EvidenceItem` (provenance `DATA_DERIVED`/`INFERRED`/`LLM_JUDGMENT`), `compute_confidence()` (`HIGH`/`MEDIUM`/`LOW`/`INSUFFICIENT`, štrukturálne dokázateľné, že `HIGH` nikdy nevznikne z čisto `LLM_JUDGMENT` evidencie), `decide()` (`RECOMMEND`/`CLARIFY`/`ABSTAIN`). **Nulové zapojenie do `/chat`** – žiadna zmena zákazníckeho správania (potvrdené `git diff --stat`, dotýka sa len 2 nových súborov).

**Testy**: `tests/test_recommendation_evidence_v2_14a.py` (24 testov) – Case A-E dôkazy zo zadania (silná evidencia→HIGH, čiastočná→MEDIUM/LOW, LLM-only nikdy HIGH vrátane vyčerpávajúceho sweepu sily 0,00–1,00, nedostatočná evidencia→ABSTAIN, chýbajúci use-case→CLARIFY), deterministická opakovateľnosť, unsupported-claim handling.

**Výsledky:** Plný beh **1356/1356** (1332 + 24 nových), 0 regresií. V2.10 fast-mode **34/39 nezmenené**. Canary **10/10**. Žiadna zmena retrieval/ranking/taxonomy/routing/cross-sell/recipe/session správania.

**Implementation gate**: **`GATE A`** – úzko vymedzená foundation (nie plný engine) odôvodnená existujúcimi znovupoužiteľnými primitívami a jasným, testovateľným evidence modelom; plná runtime recommendation/comparison logika by bola predčasná vzhľadom na zmerané dátové pokrytie.

**Čestný výsledný stav**: **`RECOMMENDATION_FOUNDATION_PARTIALLY_READY`** – evidence/confidence kontrakt hotový a testovaný, runtime dáta na broad best-choice/comparison/use-case pokrytie nie sú pripravené. Nie zlyhanie, dôkazom podložený záver. Detail: `docs/recommendation-intelligence-v2.14a.md`.

**Ďalší krok:** **V2.14b – Product Comparison & Best-Choice Foundation** (oživiť existujúci `COMPARISON` workflow_id pre štrukturálne porovnanie cena/veľkosť/značka/rodina, bez vymýšľania chuti/autentickosti), potom **V2.14c – Use-Case Intelligence Expansion** (rozšíriť `_USE_CASE_TO_SOURCE_KEYS` nad rámec sushi, kopírujúc `recipe_graph`'s 47-jedálový vzor). V2.14b sa nezačína automaticky.

### Sprint V2.14b – Evidence-Grounded Product Comparison & Recommendation Decision Foundation

**Zadanie:** vybudovať prvú produkčne nasadenú, evidence-grounded porovnávaciu schopnosť ("Kikkoman alebo Yamasa?", "ktorá je lacnejšia?", "porovnaj prvý a druhý") – s tvrdým bezpečnostným princípom, že Mei nesmie byť nútená vyhlásiť víťaza bez dostatočnej evidencie (`CLEAR_WINNER`/`CONDITIONAL_WINNER`/`TRADE_OFF`/`NO_MEANINGFUL_DIFFERENCE`/`CLARIFY`/`ABSTAIN`).

**Charakterizácia PRED**: 10 reprezentatívnych dopytov potvrdilo nulovú komparatívnu logiku dnes – "Kikkoman alebo Yamasa?" vracal nesúvisiace produkty (ryžový ocot Kikkoman + kimchi základ Kikkoman + sójová omáčka Yamasa), zatiaľ čo existujúca ordinálna-referencia infraštruktúra (V2.9) už správne rieši "žiadny kontext" prípad pre JEDEN ordinál (nie pre dvojicu).

**Implementácia**: nový `app/comparison.py` nad `app.recommendation_evidence` (V2.14a) – target resolution (ordinálny pár z result setu ALEBO explicitný textový pár cez `hybrid_cached_search_products`), goal model (CHEAPEST/BEST_VALUE/LARGEST_PACK/GENERAL_BEST/UNSUPPORTED_QUALITATIVE), decision model, deterministická (NIE LLM) kompozícia odpovede – čím sa "LLM override protection" dosahuje konštrukciou, nie behovou detekciou (žiadny generovaný text na prepísanie neexistuje).

**Tri reálne bezpečnostné nálezy PRI implementácii/regresii** (nie hypotézy): (1) holé značky bez kategórie ("Kikkoman alebo Yamasa?") sa nezávisle vyriešili na úplne odlišné typy produktov (kimchi základ vs. teriyaki omáčka) – opravené vyžadovaním zhodnej `canonical_family`/kategórie pred akceptovaním páru, inak `CLARIFY`; (2) surová cena pri veľmi odlišných veľkostiach balenia (150ml @ 4,17€ vs. 18L @ 50,57€) by vyrobila zavádzajúceho víťaza – opravené uprednostnením jednotkovej ceny kedykoľvek sú veľkosti porovnateľné; (3) plný regresný beh odhalil, že pôvodný trigger (znovupoužívajúci `app.workflow_registry._COMPARISON_MARKERS` doslovne) obsahoval `"rozdiel"`, čo rozbilo existujúci session-safety test – "aký je rozdiel medzi mirin a ryžovým octom?" je informačná FAQ otázka, nie žiadosť vybrať víťaza; `"rozdiel"` odstránený z causal triggeru, permanentný regresný test pridaný.

**Integrácia**: nová skorá, samostatná vetva v `_chat_impl()` (rovnaký vzor ako V2.13d/e migrácie cez `app.workflow_executor.execute_comparison()`), umiestnená PO allergen-safety/FAQ/random-recipe/reset kontrolách – priamo overené, že porovnávací jazyk (" alebo ") v allergen dopyte ("sójová omáčka bez sóje alebo laktózy, ktorá je bezpečnejšia?") nepretrhne bezpečnostnú precedenciu (zostáva `allergen_safety`, 0 produktov). `app/workflow_registry.py` nezmenený.

**Výsledky:** Plný beh **1401/1401** (1356 + 45 nových), 0 regresií po oprave nálezu #3. V2.10 fast-mode **34/39 nezmenené**, canary **10/10**. Presne 2 volania `hybrid_cached_search_products` na explicitný pár, **0 OpenAI volaní** (overené mockom) – žiadny nový LLM call pre porovnávaciu logiku.

**Čestný výsledný stav**: **`COMPARISON_INTELLIGENCE_LIVE`** – všetkých 9 podmienok integračnej brány (Section 28 zadania) splnených s priamym dôkazom. Aktivuje V2.7's dovtedy `SHADOW`-only `COMPARISON` workflow_id (nová, nezávislá vykonávacia cesta, nie zmena `select_workflow()`'s vlastného FAQ-gated mechanizmu). Detail: `docs/recommendation-comparison-v2.14b.md`.

**Ďalší krok:** **V2.14c – Use-Case Intelligence Expansion** (rozšíriť `app.cross_sell._USE_CASE_TO_SOURCE_KEYS` nad rámec jedinej hodnoty "sushi", kopírujúc `recipe_graph`'s 47-jedálový vzor) – hlavné zostávajúce obmedzenie po V2.14b je use-case evidence coverage, nie samotná porovnávacia mechanika. V2.14c sa nezačína automaticky.

### Sprint V2.14c – Evidence-Grounded Use-Case Intelligence Expansion

**Zadanie:** rozšíriť recommendation intelligence o "[produkt] na [kulinárske použitie]" otázky ("rybacia omáčka na pho", "ryža na sushi") – s tvrdým princípom "NO EVIDENCE → NO STRONG RECOMMENDATION" a explicitným povolením heterogénnej pripravenosti naprieč use cases (niektoré LIVE, iné SHADOW_ONLY/DATA_REQUIRED, bez toho, aby slabší prípad blokoval silnejší).

**Audit**: `use_case`/`cuisine` facets v `app.taxonomy` sú mŕtve polia (vždy `[]`), jediná reálna `use_case` hodnota v celej taxonomy je "sushi" (1 `FamilyRule`, 12 produktov). Kompletný per-use-case dátový audit (sushi/pho/ramen/pad_thai/tom_kha/kari) odhalil: ramen má reálnu taxonomy kolíziu (bare "ramen"/"rezance" → rovnaká `instant_noodles` rodina, 89 produktov, z toho 9 nepotravinových misiek – doteraz nezdokumentovaný data-quality bug); pho/pad_thai/tom_kha/kari majú reálne, čisté taxonomy rodiny pre niektoré (nie všetky) ingrediencie; `app.cross_sell.roles_for_recipe()` dôveruje len taxonomy-backed konceptom, takže 30-60% ingrediencií na jedlo sa dnes nikdy nedostane k zákazníkovi cez existujúci cross-sell mechanizmus.

**Implementácia**: nový `app/use_case_advice.py` – kanonický use-case resolver (vlastný, úzky alias slovník s povinnou "na X"/"pre X" prepozíciou), per-rolu evidence tabuľka (14 rolí naprieč 5 use cases) nad `app.recommendation_evidence` (V2.14a), priamy taxonomy-family filter na kandidátov (žiadny nový retrieval engine), deterministická (nie LLM) kompozícia odpovede – rovnaký bezpečnostný dizajn ako V2.14b comparison.

**5 reálnych regresií nájdených a opravených počas implementácie** (nie hypotézy): (1) rt0004 ("súvisiace produkty k sushi ryži") pôvodne aktivovalo use-case-advice namiesto `related_products` – opravené vylúčením companion-request markerov ("suvisiace", "doplnky"); (2) "chcem robiť Pad Thai" pôvodne aktivovalo CLARIFY namiesto protected V2.13e recipe flow – opravené `recipe_subject` guard parametrom (rovnaký fall-through kontrakt ako `execute_recipe()`); (3) plný V2.10 beh odhalil, že "červená kari pasta" (bare produktový názov, žiadna use-case otázka) sa nesprávne mapovalo na generickú `curry_paste` rodinu namiesto špecifického `red_curry_paste` konceptu (`curry_red_001` golden regresia) – hlavná príčina: use-case rozpoznávanie nevyžadovalo explicitnú "pre toto použitie" formuláciu; (4)-(5) rovnaká oprava (vyžadovanie "na X"/"pre X" prepozície + odstránenie CLARIFY zo zákazníckeho vstupného bodu, defer namiesto) vyriešila aj `regbug_rt0026` a `conv_sushi_matrix_001`. Všetkých 5 má permanentný regresný test.

**Ďalší reálny nález (nefixovaný, mimo rozsahu)**: "pad thai" a "tom kha" sú doslovne hardcoded v `RECIPE_INTENT_MARKERS` (V2.9-éra kód, predchádzajúci tejto sprinte) ako automatické recipe-intent spúšťače – ich use-case-advice logika v tejto sprinte je reálna, deterministická a plne otestovaná, ale PRAKTICKY nedosiahnuteľná zo skutočnej zákazníckej správy, pretože `detect_recipe_subject()` vždy vyhrá skôr. Oprava by vyžadovala zmenu recipe-intent precedencie, čo zadanie V2.14c Section 6/35 explicitne zakazuje v tejto sprinte.

**Výsledky:** Plný beh **1446/1446** (1401 + 45 nových), 0 regresií po oprave. V2.10 fast-mode **34/39 nezmenené** (po oprave, identické error buckety pred/po celej sprinte). Canary **10/10**. Žiadne nové OpenAI volanie (overené statickou inšpekciou zdrojového kódu).

**Čestný výsledný stav**: **`USE_CASE_INTELLIGENCE_LIVE_PARTIAL`** – sushi/pho/kari **LIVE** (3 use cases), pad_thai/tom_kha **SHADOW_ONLY** (2, evidencia reálna, zákaznícky nedosiahnuteľná kvôli existujúcej precedencii), ramen **DATA_REQUIRED** (1, reálna taxonomy kolízia). Heterogénna pripravenosť je explicitne platný, úspešný výsledok podľa zadania – silná sushi evidencia sa nikdy neprenáša na ramen/pho. Detail: `docs/use-case-intelligence-v2.14c.md`.

**Ďalší krok:** **V2.14d – Data Enrichment for Use-Case Coverage** (oprava `instant_noodles` `exclude_title_phrases` pre ramen kolíziu, vlastná `jasmine_rice` taxonomy subfamily, rozšírenie zásob galangal/citrónová tráva/kaffir listy) – hlavné zostávajúce obmedzenie po V2.14c je dátová kvalita konkrétnych taxonomy rodín, nie architektúra odporúčacieho enginu. Alternatívne V2.14d – Recommendation Observability & Feedback. V2.14d sa nezačína automaticky.

### Sprint V2.14d – Use-Case & Recipe Data-Quality Closure

**Zadanie:** oprava a validácia (nie rozšírenie) troch V2.14c nálezov – ramen taxonomy kolízia, RECIPE_COMPLETION coverage/precision, Pad Thai/Tom Kha use-case reachability – plus evidence-based Basket Completion readiness rozhodnutie. Explicitne NIE Basket Completion samotný.

**Ramen (Part A)**: root cause potvrdený priamou reprodukciou – `instant_noodles` FamilyRule bare title_phrase "ramen" bez kategórie na potvrdenie chytal 9 reálnych servírovacích misiek/lyžíc (žiadna z nich v kategórii "Instantné polievky"). Oprava: nové kategóriovo-riadené `FamilyRule` (`family="kitchenware"`, `subfamily="tableware"`, `category_terms=("stolovy riad",)`) pozicované pred `instant_noodles` – rovnaký precedenčný vzor ako existujúci `rice_cooker`. Blast radius matematicky overený bezpečný (268 produktov v kategórii, 0 už inak správne klasifikovaných). Legacy free-text vyhľadávanie ("miska na ramen") nedotknuté.

**RECIPE_COMPLETION (Part B)**: kvantifikovaná strata per-jedlo (19/28 = 67.9% pred opravou, rozmedzie 40-100%, nie uniformne "30-60%"). Každý nevyriešený koncept overený priamo proti katalógu – 2 (banh pho, bare "kari pasta") mali reálne, správne HIGH-klasifikované produkty, len chýbajúci QUERY-side title_phrase na už existujúcich pravidlách (`rice_noodles`, `curry_paste`) – opravené bez novej rodiny/pravidla. Zvyšných 7 (dashi, palmový cukor, arašidy, galangal, citrónová tráva, kaffirové listy, "korenie pho") sú reálny NO_TAXONOMY_MATCH dátový dlh, zámerne neopravený (Section 3 zadania zakazuje broad taxonomy expansion). Výsledná coverage: **21/28 (75.0%)**, 0 nových false positives.

**Pad Thai/Tom Kha routing (Part C)**: `app.turn_resolver.resolve_action_target_signal()` explicitne auditovaný a klasifikovaný `INSUFFICIENT_FOR_THIS_CLASS` (jeho `TurnAnalysis` nemá žiadne pole pre recipe_subject/use-case cieľ – rieši úplne iný konflikt). Root cause potvrdený priamou trasovacou maticou: `RECIPE_INTENT_MARKERS`'s bare "pad thai"/"tom kha" markery vyhrávali nad AKOUKOĽVEK správou obsahujúcou tieto reťazce bez ohľadu na kontext. Generická oprava (nie dish-špecifická): nová `_recipe_intent_is_bare_dish_marker_only()` + `app.use_case_advice.has_resolvable_role()` (znovupoužíva existujúce `resolve_use_case()`/`resolve_role()`, žiadna duplicitná tabuľka) – bare dish marker sa potlačí LEN keď je jediným recipe-signálom A existuje konkrétna, rozpoznateľná use-case rola. Explicitný recept/nákupný zoznam jazyk zostáva úplne nezmenený (16-bodová live matica, 0 regresií).

**Výsledky:** Plný beh **1470/1470** (1446 + 24 nových: 5 taxonomy + 7 cross_sell + 12 use_case_advice), 0 regresií. V2.10 fast-mode **34/39 nezmenené** (identické error buckety naprieč všetkými 3 časťami). Canary **10/10**. Taxonomy coverage 34.4% → **46.5%**.

**Per-use-case matica**: sushi/pho/kari **LIVE** (nezmenené), pad_thai/tom_kha **SHADOW_ONLY → LIVE** (routing fix), ramen **DATA_REQUIRED** (nezmenené – taxonomy kolízia pre tableware opravená, ale bare-word use-case kolízia zostáva).

**Čestný výsledný stav**: **`USE_CASE_RECIPE_DATA_QUALITY_PARTIAL`**. Basket readiness: **`BASKET_FOUNDATION_READY_WITH_LIMITATIONS`** (nie plné READY – ramen DATA_REQUIRED, reálne ingredient gaps pre pad_thai/tom_kha, 53.5% katalógu stále UNKNOWN taxonomy-wide, všetky mechanizmy SK-only). Detail: `docs/use-case-recipe-data-quality-v2.14d.md`.

**Ďalší krok:** cielené dátové obohatenie (7 NO_TAXONOMY_MATCH konceptov + ramen bare-word kolízia) pred V2.14e Basket Completion – odporúčané NIE preto, že bolo plánované, ale pretože Basket readiness scorecard ukazuje `READY_WITH_LIMITATIONS`, nie `READY`. V2.14e sa nezačína automaticky.

### Sprint V2.14e – Evidence-Grounded Basket Completion & Goal-Oriented Shopping Intelligence

**Kľúčový nález (pred akoukoľvek zmenou)**: `app.recipe_shopping.build_recipe_shopping_plan()` (V2.8) už implementuje presne požadovanú per-rolu status/coverage mechaniku (`AVAILABLE`/`ALREADY_SATISFIED`/`NOT_AVAILABLE`/`UNKNOWN_MAPPING`, `app.session_state.get_selected_ingredient_products()` pre "already covered") a je **už živo nasadené pre pad_thai/tom_kha** cez ich existujúci bare `RECIPE_INTENT_MARKERS` záznam – živo overené PRED implementáciou. Skutočná medzera: sushi/pho/kari nemajú prístup k tejto mechanike (sushi nemá `recipe_graph` záznam vôbec, pho/kari nemajú bare recipe marker), takže "čo potrebujem na pho/kari/sushi" padalo do `related_products` bez basketu.

**Architektúra**: nový `app/basket_completion.py` – required-role zoznam znovupoužíva `app.cross_sell.roles_for_recipe()`/`roles_for_use_case()` (V2.6, už taxonomy-podložené, už produkčne používané pre cross-sell) namiesto `app.use_case_advice._ROLE_TABLE` (ktorá je zámerne úzka, len 1 rola pre sushi) – kandidát generovanie cez `product_taxonomy_index` s PRESNOU `concept_id` zhodou (silnejšie než family/subfamily, žiadny lexical_filter workaround). `app.turn_resolver.resolve_action_target_signal()` opäť auditovaný a klasifikovaný `INSUFFICIENT_FOR_THIS_CLASS` (rovnaký dôvod ako vo V2.14d). Nová vetva v `_chat_impl()` sa vzdáva (`None`), keď `recipe_subject` je už nastavené – pad_thai/tom_kha teda VŽDY používajú existujúcu, nedotknutú V2.8/V2.9 cestu, tento modul pokrýva LEN sushi/pho/kari.

**2 reálne regresie nájdené a opravené** (nie hypotézy): (1) `regbug_rt0026` ("ramen na Pho polievku máte ingrediencie?") – bare "ingredien" marker (súčasť existujúceho `wants_recipe_products()`) bol príliš široký pre toto silnejšie basket tvrdenie – opravené užším, basket-špecifickým marker setom ("čo potrebujem"/"čo treba"/"čo mi chýba"/"čo ešte..."/"doplň"), nie plným znovupoužitím `wants_recipe_products()`; (2) "nákupný zoznam na sushi" kolidoval s existujúcim, obsahovo overeným `sushi_shopping_core_products()` mechanizmom – opravené vylúčením "nákupný zoznam"/"do košíka" z basket markerov (zákazník má aj tak plný prístup cez "čo potrebujem").

**Výsledky:** Plný beh **1517/1517** (1470 + 47 nových), 0 regresií po oprave. V2.10 fast-mode **34/39 nezmenené**. Canary **10/10**. Nameraná latencia basket_completion požiadavky ~7.5ms priemer – zanedbateľné. 0 nových LLM volaní (statický dôkaz).

**Per-use-case matica**: sushi/pho/kari **LIVE** (nový, tento modul, coverage 100%/80%/100%), pad_thai/tom_kha **LIVE** (existujúci V2.8/V2.9 mechanizmus, nedotknutý, coverage 60%/40% – reálne ingredient gaps, nie chyba), ramen **DATA_REQUIRED/EXCLUDED_FROM_BASKET_V1** (štrukturálne, dve nezávislé brány).

**Čestný výsledný stav**: **`BASKET_COMPLETION_LIVE_PARTIAL`**. Basket readiness (samostatné): 5 z 5 eligible use cases LIVE, heterogénna kvalita (40-100% coverage) explicitne akceptovaná – žiadny fake "kompletný košík" tam, kde reálna dátová medzera existuje (pho/pad_thai/tom_kha nikdy nevrátia `fully_resolved=True`). Detail: `docs/basket-completion-v2.14e.md`.

**Ďalší krok:** cielené dátové obohatenie (rovnaký zoznam ako V2.14d) pred akýmkoľvek V2.14f rozšírením (cart mutation, viacjazyčnosť, self-deklarácia pre pad_thai/tom_kha v prvej správe). V2.14f sa nezačína automaticky.

### Sprint V2.14f – Evidence-Grounded Recommendation Decision, Choice Explanation & Conversion Intelligence

**Kľúčový audit nález**: `app/comparison.py` (V2.14b) už implementuje takmer celý požadovaný recommendation-decision model pre vyriešený pár produktov – rozhodovacie stavy (CLEAR_WINNER/CONDITIONAL_WINNER/TRADE_OFF/NO_MEANINGFUL_DIFFERENCE/CLARIFY/ABSTAIN), evidence-grounded `reason_codes`, a `GOAL_UNSUPPORTED_QUALITATIVE` už explicitne routuje chuť/autenticitu/prémiovosť na ABSTAIN. Sprinta je preto primárne audit + oprava 2 reálnych, charakterizáciou objavených defektov, plus 1 nová, úzko ohraničená funkcia.

**2 reálne defekty nájdené a opravené**: (1) `app.use_case_advice.resolve_use_case()` vyžadoval doslovnú medzeru hneď za use-case aliasom – akákoľvek otázka končiaca "?" alebo s čiarkou hneď za aliasom sa vôbec nevyriešila (napr. "ktorá rybacia omáčka je najlepšia na pho?"). Oprava aplikovaná NA `resolve_use_case()`, ale zámerne NIE na `resolve_role()` – druhý reálny nález počas opravy ukázal, že rovnaká zmena tam spôsobuje NOVÚ regresiu (rolový marker preskočil cez čiarku ako sémantickú hranicu viet, unesúc `app.basket_completion`'s self-deklaračný ťah). (2) `"drahsia"` ("drahšia") bolo v `_CHEAPEST_MARKERS` – "je tá drahšia lepšia?" (Section 12 vlajkový príklad) sa vyriešilo ako GOAL_CHEAPEST a odpovedalo odporúčaním lacnejšieho produktu, nezmyselná odpoveď. Opravené odstránením + novou kombinovanou kontrolou (cenový smer + holé "lepšia") → GOAL_UNSUPPORTED_QUALITATIVE → čestný ABSTAIN.

**Nová funkcia**: comparison follow-up continuity – `app.session_state.get_active_comparison_pair()`/`set_active_comparison_pair()` (rovnaký vzor ako `active_recipe_id`) + `app.comparison.is_bare_comparison_followup()`/`resolve_comparison_targets_from_pair()`. Bare ťah ("Chcem lacnejšiu.", "Máte väčšie balenie?", "Je tá drahšia lepšia?") po úspešne vyriešenom porovnaní teraz znovupoužíva PRESNE tú istú `decide_comparison()`/`compose_comparison_answer()` cestu nad uloženým párom – žiadna nová rozhodovacia logika. Aktívny pár sa čistí pri resete, hard topic switch funguje prirodzene (bez markerov nič nefiltruje).

**Vedome NEIMPLEMENTOVANÉ**: bare "ktorú rybaciu omáčku mám kúpiť?" (žiadny pár, žiadny use-case rámec) zostáva `related_products` – klasifikované GATE A (audit only), keďže bezpečné riešenie by riskovalo zámenu ranking relevantnosti za recommendation nadradenosť bez samostatného dizajnu.

**Výsledky:** Plný beh **1553/1553** (1517 + 36 nových), 0 regresií po oprave 2 nálezov. V2.10 fast-mode **34/39 nezmenené**. Canary **10/10**. Nameraná latencia comparison follow-upu ~5.4ms priemer. 0 nových LLM volaní. `app/learning_lifecycle.py` sa nemenil, AUTO_PROMOTION nedotknuté.

**Čestný výsledný stav**: **`RECOMMENDATION_INTELLIGENCE_LIVE_PARTIAL`**. Detail: `docs/recommendation-decision-v2.14f.md`.

**Ďalší krok:** V2.14g (Recommendation Learning Signals & Feedback Loop) je vecne pripravený z hľadiska stability rozhodnutí, ale existujúci `log_question()` mechanizmus už poskytuje dostatočné signály bez nových telemetria polí – AUTO_PROMOTION musí zostať `false` v akejkoľvek budúcej sprinte bez samostatného schválenia. V2.14g sa nezačína automaticky.

### Sprint V2.14h – Ramen Data Readiness & Use-Case Closure

**Zadanie:** audit-first re-overenie, či ramen môže byť bezpečne
podporovaný existujúcou evidence-grounded architektúrou – zadanie
explicitne zakazovalo predpokladať kladnú odpoveď; `RAMEN_DATA_REQUIRED_CONFIRMED`
bol sankcionovaný ako rovnocenný, nie neúspešný výsledok.

**Kľúčové nálezy re-auditu** (živo overené proti `983ed4a`, nie kopírované
z V2.14c/d/e/f): pôvodný V2.14c dôvod vylúčenia ramenu (misky/riad v
`instant_noodles`) bol nezávisle vyriešený V2.14d tableware `FamilyRule`
– dnes 79 čistých produktov (76 HIGH/3 MEDIUM). Nový nález: samostatná
`wheat_noodles` rodina (32, HIGH) obsahuje 4 reálne domáce ramen rezance
oddelené od instantných balíčkov – bare-word taxonomy kolízia, ktorá
pôvodne blokovala ramen, už neexistuje. Korekcia: "dashi" nemá 0 dát (3
reálne SKU existujú), len 0 štruktúrovanej evidencie (`UNKNOWN` confidence,
žiadny `FamilyRule`) – zámerne vynechané z role tabuľky namiesto
fabrikovania role z neklasifikovanej evidencie.

**Implementácia (Gate B – use-case-advice-only, bez zmeny basketu):**
`"ramen"` pridané do `app.use_case_advice.LIVE_USE_CASES` + nová
`_ROLE_TABLE["ramen"]` (4 role: instant_noodles/miso/soy_sauce/wakame,
všetky `PROVENANCE_DATA_DERIVED`) – opravuje reálny, pred sprintou
reprodukovaný defekt, kde "akú omáčku/zeleninu na ramen?" padalo na
nepomáhajúci generický `product_search` dump. Basket completion pre
ramen zostáva nezmenené (beží nezávisle cez V2.8 `app.recipe_shopping`).

**Latentný defekt nájdený a opravený**: `BASKET_V1_ELIGIBLE_USE_CASES`
bol doslovný `tuple(LIVE_USE_CASES)` live-mirror – pridanie ramenu do
`LIVE_USE_CASES` by ho ticho urobilo aj basket-eligible, čo zadanie
explicitne zakazovalo. Opravené explicitným, nezávisle autorovaným
tuple v `app/basket_completion.py`.

**Výsledky:** Plný beh **1578/1578** (1553 + 25 nových), 0 regresií.
V2.10 fast-mode **34/39 nezmenené**. Canary **10/10**. Consistency 0
kolízií, trust 0 nálezov.

**Čestný výsledný stav**: **`RAMEN_USE_CASE_LIVE_WITH_LIMITATIONS`**
(role advice LIVE pre 4 role, dashi DATA_REQUIRED). Basket status
nezmenené. Detail: `docs/ramen-data-readiness-v2.14h.md`.

**Ďalší krok:** dashi `FamilyRule` autorstvo a domáca-ramen-rezance
rola z `wheat_noodles` sú konkrétne, dôkazmi podložené budúce kroky
(oba by vyžadovali vlastný blast-radius audit) – žiadny z nich
nezačatý touto sprintou. rt0013 zostáva nedotknuté a blokujúce pre
akúkoľvek súvisiacu prácu.

*(rt0013 bolo následne uzavreté v samostatnom rt0013-closure kroku:
`CLOSED_BY_HUMAN_SEMANTIC_DECISION` — pozri `docs/routing-debt.md`.
Dashi `FamilyRule` bola tiež následne autorovaná a zapojená do
`use_case_advice`'s ramen role tabuľky. Wheat_noodles rola bola
auditovaná a uzavretá ako `NOT_SAFE_TO_IMPLEMENT` — pozri
`docs/ramen-data-readiness-v2.14h.md`.)*

### Sprint V2.15a – Recommendation Observability, Signal Semantics & Learning Readiness Audit

**Zadanie:** audit-first zistenie, či existujúca infraštruktúra má dosť
spoľahlivé, kauzálne, izolované a durable signály na budúci
recommendation-learning pipeline. Explicitne NIE ranking-learning
sprint, NIE auto-promotion sprint, žiadna zmena zákazníckeho
recommendation/retrieval správania povolená.

**Najzávažnejší nález**: `POST /chat` nemá žiadny spôsob odlíšiť
externé HTTP volanie (curl/QA/monitoring/live smoke test) od reálneho
zákazníka – `isinstance(request, Request)` je vždy `True` pre HTTP
volanie, `ExecutionContext` mechanizmus je dosiahnuteľný len z
interných Python volajúcich. Každé doterajšie live production
overenie v tejto aj predchádzajúcich sprintách bolo teda
nerozlíšiteľné od zákazníckej prevádzky – zdokumentované ako
`OBSERVABILITY_GAP`, zámerne neopravené (vyžaduje novú architektúru).
Druhý kľúčový nález: `question_analytics.jsonl` (decision state) a
`events.jsonl` (produktové kliky/add_to_cart) nemajú zdieľaný kľúč –
kauzálna atribúcia je dnes len nespoľahlivé session_id+čas hádanie.

**AUTO_PROMOTION_ENABLED** dokázateľne `false` štrukturálne (nikdy
nekonzultovaná v žiadnej podmienke v celom `app/`, nie len aktuálne
nastavená) – `AUTO_PROMOTION_STATUS=DISABLED_AND_UNCHANGED`.

**Jediná runtime zmena**: `log_taxonomy_shadow()` nebol nikdy zapojený
do `execution_context` brány (na rozdiel od `log_question`) – každé
EVALUATION/LEARNING/SHADOW/ADMIN_TEST volanie ticho kontaminovalo
`taxonomy_shadow.jsonl`. Charakterizované testom PRED opravou (4/5
FAILED), opravené `if execution_context.emit_customer_analytics:`
guardom, byte-safe editované (main.py má mixné CRLF/LF).

**Výsledky:** Plný beh **1599/1599** (1593 + 6 nových), 0 regresií.
V2.10 fast-mode **35/39 nezmenené**. Canary **10/10**.

**Čestný výsledný stav**: **`OBSERVABILITY_GAPS_REQUIRE_CLOSURE`** –
`RANKING_LEARNING_READINESS=NOT_READY`,
`RECOMMENDATION_LEARNING_READINESS=PARTIAL`. Detail:
`docs/recommendation-learning-readiness-v2.15a.md`.

**Ďalší krok:** **V2.15b – Signal Persistence & Normalization** (nie
Learning Candidate Pipeline) – kľúčové medzery sú štrukturálne
(chýbajúci zdieľaný kľúč, chýbajúca HTTP-úrovňová execution-context
signalizácia), nie nedostatok dát. V2.15b sa nezačína automaticky.
