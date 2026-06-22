# Foodland AI Agent MVP

Toto je prva verzia backendu pre AI asistenta Foodland.sk nad Google Merchant feedom.

Backend vie:

- nacitat Google Merchant XML feed,
- nacitat Foodland Knowledge JSON,
- vyhladavat produkty podla nazvu, znacky, kategorie a popisu,
- vyhladavat FAQ, recepty, magazin, cross-sell, alternativy a Products_AI,
- vratit produktove vysledky cez API,
- odpovedat cez OpenAI, ak je nastavene `OPENAI_API_KEY`,
- fungovat aj bez OpenAI kluca ako produktovy vyhladavac.
- limitovat pocet otazok na IP adresu,
- zapisovat zakladnu analytiku otazok do JSONL suboru.

## Struktura

```text
app/
  feed.py          parser Google Merchant XML feedu
  search.py        jednoduche lokalne produktove vyhladavanie
  main.py          FastAPI backend
  import_feed.py   import XML do JSON
  import_knowledge.py import Excel knowledge tabuliek do JSON
  recipe_ingredients.py odporucane produkty k ingredienciam receptov
data/
  googleMerchant_sk_export.xml
  recipe_ingredients.json
```

## Lokalne spustenie

1. Skopirujte feed do:

```text
data/googleMerchant_sk_export.xml
```

2. Vytvorte `.env` podla `.env.example` a nastavte `OPENAI_API_KEY`.

3. Nainstalujte zavislosti:

```bash
pip install -r requirements.txt
```

4. Spustite backend:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

5. Otestujte:

```text
GET  http://localhost:8000/health
POST http://localhost:8000/products/search
POST http://localhost:8000/chat
POST http://localhost:8000/ask
```

Priklad tela requestu:

```json
{
  "message": "mate miso polievku?",
  "limit": 5
}
```

Kompatibilny `/ask` request:

```json
{
  "question": "recept na kimchi",
  "lang": "SK",
  "limit": 5
}
```

Odpoved obsahuje aj:

- `intent` - napr. `product`, `recipe`, `faq`, `cross_sell`, `alternative`,
- `mode` - `ai`, `search_only` alebo `fallback`,
- `lang` - jazykovy kod pouzity pre odpoved/karticky.
- `suggested_actions` - navrhnute dalsie kroky pre guided selling.

## Cloud deploy

Pre Railway alebo Render:

- build/install command: `pip install -r requirements.txt`
- start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- env:
  - `OPENAI_API_KEY`
  - `OPENAI_MODEL=gpt-4.1-mini`
  - `PRODUCT_FEED_PATH=https://www.foodland.sk/ed3d2c21991e3bef5e069713af9fa6ca/googleMerchant_sk_export.xml`
  - `KNOWLEDGE_JSON_PATH=data/knowledge.json`
  - `RECIPE_INGREDIENTS_PATH=data/recipe_ingredients.json`
  - `FEED_REFRESH_MINUTES=180`
  - `ALLOWED_ORIGINS=https://www.foodland.sk,https://foodland.sk`
  - `RATE_LIMIT_PER_MINUTE=12`
  - `ANALYTICS_LOG_PATH=data/question_analytics.jsonl`
  - `ERROR_LOG_PATH=data/backend_errors.jsonl`
  - `ANALYTICS_INCLUDE_IP=false`
  - `ANALYTICS_SALT=<nahodny tajny retazec>`

## Vercel deploy

Projekt obsahuje `pyproject.toml` s Vercel entrypointom:

```toml
[tool.vercel]
entrypoint = "app.main:app"
```

Ak Vercel vypise chybu typu `Found main.py but it does not export a top-level app`, skontrolujte, ze je v GitHub repozitari nahraty cely projekt aj s priecinkom `app/`, nie iba samotne subory z priecinka `app`.

Poznamka: Vercel Python bezi serverless sposobom. Pre dlhodoby background refresh feedu a lokalne JSONL analytics logy je vhodnejsi Railway/Render. Na Verceli sa feed nacita pri starte/cold starte funkcie a suborove logovanie nemusi byt perzistentne.

Neskor sa da pripojit domena:

```text
https://ai.foodland.sk
```

## Chat widget

Subor `app/widget.js` je jednoduchy embeddable widget. Po nasadeni backendu ho vlozite do Foodland.sk takto:

```html
<script>
  window.FoodlandAI = {
    apiBaseUrl: "https://ai.foodland.sk"
  };
</script>
<script src="https://ai.foodland.sk/static/widget.js"></script>
```

V tejto MVP verzii je widget ulozeny pri aplikacii. Pri produkcnom nasadeni treba bud:

- servirovat `widget.js` ako staticky subor z backendu,
- alebo ho vlozit priamo do sablony webu Foodland.sk.

Widget teraz obsahuje:

- krajsi zeleny Foodland styl,
- minimalizacne tlacidlo,
- AI/GDPR upozornenie,
- produktove karticky s obrazkom, cenou a tlacidlom `Zobrazit produkt`,
- loading stav,
- error stav,
- zakladnu ochranu proti spamovaniu aj na strane klienta,
- mobilne rozlozenie.

Demo bez backendu je v:

```text
app/widget.html
```

Ak `widget.html` otvorite z Railway domeny, pouzije realny backend cez `window.location.origin`.

Demo rezim zapnete explicitne takto:

```text
https://.../static/widget.html?demo=1
```

Pri lokalnom otvoreni cez `file://` sa demo rezim zapne automaticky.

Konfiguracia:

```js
window.FoodlandAI = {
  apiBaseUrl: window.location.origin,
  demoMode: false
};
```

V produkcii odstrante `demoMode` alebo ho nastavte na `false`.

## Knowledge endpoints

Backend obsahuje aj knowledge vyhladavanie:

```text
POST /knowledge/search
```

Priklad:

```json
{
  "query": "ako funguju kredity"
}
```

Knowledge subor:

```text
data/knowledge.json
```

Je exportovany z Excel knowledge zdrojov a obsahuje:

- `Products_AI`
- `Recipes`
- `Magazine`
- `CrossSell`
- `Alternatives`
- `FAQ`
- `IntentMapping`

Opakovany import z jedneho komplet workbooku:

```bash
python app/import_knowledge.py --input-workbook data/Foodland_Knowledge_complete_v3_full.xlsx --output data/knowledge.json --version Foodland_Knowledge_complete_v3_full
```

Opakovany import zo zlozky so 7 zdrojovymi Excel tabulkami:

```bash
python app/import_knowledge.py --input-dir data/knowledge_sources --output data/knowledge.json
```

Ocakavane nazvy suborov v `data/knowledge_sources`:

- `foodland_products_ai_tabulka.xlsx`
- `foodland_recepty_jazykove_mutacie.xlsx`
- `foodland_magazin_clanky_jazykove_mutacie.xlsx`
- `foodland_crosssell_tabulka.xlsx`
- `foodland_alternativy_tabulka.xlsx`
- `foodland_faq_tabulka.xlsx`
- `foodland_intentmapping_tabulka.xlsx`

Poznamka: aktualny samostatny FAQ subor v zdrojovej zlozke moze mat menej riadkov ako komplet workbook. Pre presnu produkcnu verziu s 44 FAQ zaznamami pouzite komplet workbook.

## Produkty k receptom

Subor:

```text
data/recipe_ingredients.json
```

Obsahuje ingrediencie receptov a odporucane Foodland produkty k jednotlivym ingredienciam. Backend ho pouziva pri otazkach typu:

- `ake ingrediencie potrebujem na kimchi?`
- `produkty na recept kimchi`
- `co potrebujem na vyrobu kimchi?`

Taketo otazky vratia `intent: "recipe_ingredients"` a produkty sa zobrazia vo widgete ako bezne produktove karticky.

## Agentic seller prvky

Foodland poradca zostava bezpecny poradca, nie autonomny nakupca. Backend vsak vracia dalsie odporucane kroky:

```json
{
  "suggested_actions": [
    {"label": "Porovnať možnosti", "message": "Porovnaj kimchi"},
    {"label": "Čo sa k tomu hodí", "message": "Čo sa hodí ku kimchi?"}
  ]
}
```

Widget ich zobrazuje ako male tlacidla pod odpovedou. Zakaznik tak vie pokracovat v nakupnom rozhodovani bez pisania celej novej otazky.

## Meranie otazok

Kazda otazka cez `/chat` sa zapise do:

```text
data/question_analytics.jsonl
```

Format jedneho riadku:

```json
{"ts": 1781820000, "client_hash": "a1b2c3...", "endpoint": "chat", "lang": "SK", "mode": "search_only", "intent": "product", "message": "mate sushi ryzu?", "products_count": 4, "knowledge_summary": {}, "content_cards_count": 0}
```

Surova IP adresa sa defaultne neuklada. Ak ju z nejakeho dovodu potrebujete, zapnite `ANALYTICS_INCLUDE_IP=true`, ale pre produkciu odporucam zostat pri hashovanom identifikatore.

## Dalsie kroky

1. Nasadit backend na Railway alebo Render.
2. Nastavit `OPENAI_API_KEY`.
3. Vlozit chat widget na Foodland.sk.
4. Pridat pravidelny import feedu.
5. Doplnit FAQ a obchodne podmienky.
6. Pridat vektorove vyhladavanie pre lepsie odporucania.
7. Napojit objednavky a sklad, ak e-shop poskytne API.
