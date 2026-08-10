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
  cache top questions z question_analytics.jsonl (refresh kΌždých 60s)
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
- ~20 ručnùch synonymov pre konkrétne slová
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

**Popis:** Pin/hide/boost produkty, sez�2înné kampane, vypredané dole

### Aktuálny stav
�}iadny rules engine. Edinrý "merchandising": `availability == "in_stock"` → +1 bod.

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
const QUICK_PROMPTS = ["🍜 Odporüčtdt
‛ramen", 🌶️ Ďo je gochujang?", "🍱 Bezlepkové produkty"];
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

### Sprint C – Search quality (1 týzĔn)

| # | Feature | Čas | Súbory |
|---|---|---|---|
| C1 | BM25 index (F2a) | 2d | `app/search.py` refaktor |
| C2 | Facet/filter API (F4) | 2d | `app/search.py` + `main.py` |
| C3 | CZ/EN synonymá (F7b) | 2d | `data/synonyms.json` rozšírenie |
| C4 | Merchandising rules (F6) | 2d | `app/merchandising.py` (nový) |

### Sprint D – ML & infraštruktúra (2Ϊ�N týždeň)

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

## Záver

Codebase je solídna produkčná báza. Najväčšje okamžité príležitosti:

1. **Grounding** – kód hotový, 4 hodiny práce, zastaví halucinácie cien/URL
2. **CrossSell bug** – 2140 záznamov sa stráca, fix je 30 riadkov kódu
3. **Event analytika** – blokuje všetky behavioral features
(. **Synonymický slovníj** – nahradí 20 hardcoded if-blokov

Luigi's Box paritu je realistické dosiahnuť v **3 mesiacoch** pri sústredenom vývoji.
