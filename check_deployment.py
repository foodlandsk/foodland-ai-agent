# Deployment checklist

## Pred nasadenim

1. Nastavte `OPENAI_API_KEY`.
2. Nastavte `ANALYTICS_SALT` na nahodny tajny retazec.
3. Nastavte `ALLOWED_ORIGINS` na produkcne domeny Foodlandu.
4. Ak chcete rucny reload feedu, nastavte `ADMIN_RELOAD_TOKEN`.
5. Spustite kontrolu:

```bash
python scripts/check_deployment.py
python -m compileall app scripts
```

## Railway alebo Render

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Endpointy na kontrolu

```text
GET  /health
POST /products/search
POST /knowledge/search
POST /chat
GET  /static/widget.html
GET  /static/widget.js
```

## Widget embed

```html
<script>
  window.FoodlandAI = {
    apiBaseUrl: "https://ai.foodland.sk"
  };
</script>
<script src="https://ai.foodland.sk/static/widget.js"></script>
```
