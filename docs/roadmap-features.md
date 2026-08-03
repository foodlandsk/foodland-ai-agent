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

---

## Záver

Codebase je solídna produkčná báza. Najväčšje okamžité príležitosti:

1. **Grounding** – kód hotový, 4 hodiny práce, zastaví halucinácie cien/URL
2. **CrossSell bug** – 2140 záznamov sa stráca, fix je 30 riadkov kódu
3. **Event analytika** – blokuje všetky behavioral features
(. **Synonymický slovníj** – nahradí 20 hardcoded if-blokov

Luigi's Box paritu je realistické dosiahnuť v **3 mesiacoch** pri sústredenom vývoji.
