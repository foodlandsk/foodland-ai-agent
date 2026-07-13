# Foodland AI Agent

Deployment-ready backend a embeddable widget pre Foodland AI poradcu.

Backend vie:

- nacitat produkty z `data/products.json` alebo Google Merchant XML feedu,
- nacitat Foodland knowledge databazu z `data/knowledge.json`,
- vyhladavat produkty podla nazvu, znacky, kategorie a popisu,
- vyhladavat FAQ, recepty, magazin, cross-sell, alternativy a `Products_AI`,
- odpovedat cez OpenAI, ak je nastavene `OPENAI_API_KEY`,
- fungovat aj bez OpenAI kluca ako produktovy vyhladavac,
- limitovat pocet otazok na klienta,
- zapisovat anonymizovanu analytiku otazok do JSONL suboru,
- servirovat chat widget cez `/static/widget.js`.

## Struktura

```text
app/
  feed.py           Parser Google Merchant XML feedu
  search.py         Lokalne produktove vyhladavanie
  knowledge.py      Knowledge vyhladavanie
  main.py           FastAPI backend
  import_feed.py    Import XML feedu do JSON
  widget.js         Embeddable chat widget
  widget.html       Demo stranka widgetu
data/
  products.json     Produktovy export
  knowledge.json    Foodland knowledge export
docs/
  deployment-checklist.md
scripts/
  check_deployment.py
```

## Lokalne spustenie

1. Vytvorte `.env` podla `.env.example`.
2. Nainstalujte zavislosti:

```bash
pip install -r requirements.txt
```

3. Spustite backend:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

4. Otestujte:

```text
GET  http://localhost:8000/health
POST http://localhost:8000/products/search
POST http://localhost:8000/knowledge/search
POST http://localhost:8000/chat
GET  http://localhost:8000/static/widget.html
```

Priklad requestu:

```json
{
  "message": "mate miso polievku?",
  "limit": 5
}
```

## Deployment

Odporucane prostredie: Railway alebo Render.

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

`Procfile` a `railway.json` su uz pripravene.

## Env pre produkciu

```text
OPENAI_API_KEY=<secret>
OPENAI_MODEL=gpt-4.1-mini
PRODUCTS_JSON_PATH=data/products.json
PRODUCT_FEED_PATH=https://www.foodland.sk/ed3d2c21991e3bef5e069713af9fa6ca/googleMerchant_sk_export.xml
KNOWLEDGE_JSON_PATH=data/knowledge.json
FEED_REFRESH_MINUTES=180
ALLOWED_ORIGINS=https://www.foodland.sk,https://foodland.sk
RATE_LIMIT_PER_MINUTE=12
ANALYTICS_LOG_PATH=data/question_analytics.jsonl
ERROR_LOG_PATH=data/backend_errors.jsonl
ANALYTICS_INCLUDE_IP=false
ANALYTICS_SALT=<nahodny tajny retazec>
ADMIN_RELOAD_TOKEN=<volitelne>
LOG_LEVEL=INFO
```

Ak `OPENAI_API_KEY` nie je nastaveny, `/chat` vrati fallback odpoved z lokalneho vyhladavania.

## Widget embed

Po nasadeni backendu vlozte do Foodland.sk:

```html
<script>
  window.FoodlandAI = {
    apiBaseUrl: "https://ai.foodland.sk"
  };
</script>
<script src="https://ai.foodland.sk/static/widget.js"></script>
```

Demo:

```text
https://<backend-domain>/static/widget.html
https://<backend-domain>/static/widget.html?demo=1
```

## Kontrola balika

Pred nasadenim spustite:

```bash
python scripts/check_deployment.py
python -m compileall app scripts
```

Kontrola overi, ze v baliku nie su zle pomenovane root subory, ze existuju deployment subory a ze textove subory neobsahuju typicke mojibake znaky.

## Admin reload feedu

Endpoint:

```text
POST /admin/reload-feed
```

Header:

```text
x-admin-token: <ADMIN_RELOAD_TOKEN>
```

Ak `ADMIN_RELOAD_TOKEN` nie je nastaveny, admin reload je vypnuty.
