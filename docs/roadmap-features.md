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
