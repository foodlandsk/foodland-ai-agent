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
  main.py               FastAPI backend - /chat routing kaskada, vsetky endpointy
  feed.py               Parser Google Merchant XML feedu
  search.py             Lokalne produktove vyhladavanie a ranking
  knowledge.py          Knowledge vyhladavanie (FAQ, recepty, Products_AI...)
  grounding.py          Post-hoc kontrola odpovede (URL/ceny) - zapojene do /chat
  behavioral.py         CTR-based reranking z realnych udalosti (cold-start safe)
  merchandising.py      Pin/hide/boost/campaign multiplikatory (config zatial prazdny)
  embeddings.py         Lokalne semanticke vyhladavanie (/search/semantic)
  autocomplete.py       Napoveda pre /search/autocomplete
  fbt.py                "Frequently bought together" z realnych kosikov
  knowledge_builder.py  Zostavenie knowledge.json zo zdrojovych dat
  workflows.py          Deklaratívna workflow vrstva (detect_workflow/WORKFLOW_CONTRACTS)
                         - NIE JE zapojena do /chat, pozri docs/workflow-migration-audit.md
  intent.py             CustomerIntent - V2 kanonicka schema, len pre analytiku (aditivne)
  taxonomy.py           V2 katalogovo-riadena klasifikacia (zatial shadow-mode, rodina "ryza")
  import_feed.py        Import XML feedu do JSON
  widget.js             Embeddable chat widget
  widget.html           Demo stranka widgetu
data/
  products.json     Produktovy export
  knowledge.json    Foodland knowledge export
docs/
  deployment-checklist.md
  roadmap-features.md          Chronologicky log kazdeho sprintu/opravy
  workflow-migration-audit.md  Mapa workflows.py -> skutocny /chat
  advisor-v2-architecture.md   V2 CustomerIntent architektura
  product-taxonomy-audit.md    V2 taxonomy audit
scripts/
  check_deployment.py     Pred-deploy kontrola (chybajuce subory, mojibake)
  consistency_audit.py    Kolizie marker/alias skratiek naprie routovacimi tabulkami
  trust_audit.py          Prazdne alternativy, PII leaky v redakcii
  taxonomy_audit.py       V2 katalogovo-riadeny audit taxonomie
tests/
  test_core.py         Hlavna sada (search, knowledge, grounding, main.py routing)
  test_integration.py  End-to-end /chat cez mock OpenAI
  test_intent.py        CustomerIntent/LEGACY_INTENT_MAP
  test_taxonomy.py      V2 taxonomy klasifikacia
```

Poznamka k testom: lokalne (Windows) niektore testy (`TestMerchandising`, `TestEmbeddings`,
`TestBehavioralRanking`, `TestFbt`, `TestUserMemory`, `TestAdminAnalytics` a pod.) zlyhavaju s
`PermissionError` na `pytest`-ovom docasnom priecinku - je to specificke pre tento vyvojarsky
stroj (poskodene opravnenia v `%TEMP%\pytest-of-<user>`), nie realny bug. GitHub Actions CI
(cisty checkout na kazdy beh) tento problem nema a spusta plnu sadu bez akehokolvek filtra.

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
POST http://localhost:8000/search/autocomplete
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
ANALYTICS_LOG_PATH=/tmp/foodland-ai-agent/question_analytics.jsonl
ERROR_LOG_PATH=/tmp/foodland-ai-agent/backend_errors.jsonl
ANALYTICS_INCLUDE_IP=false
ANALYTICS_SALT=<nahodny tajny retazec>
USER_MEMORY_ENABLED=true
USER_MEMORY_PATH=/tmp/foodland-ai-agent/user_memory.json
USER_MEMORY_MAX_PROFILES=50000
ADMIN_ANALYTICS_TOKEN=<volitelne>
ADMIN_RELOAD_TOKEN=<volitelne>
LOG_LEVEL=INFO
```

Ak `OPENAI_API_KEY` nie je nastaveny, `/chat` vrati fallback odpoved z lokalneho vyhladavania.

## Search autocomplete

Endpoint:

```text
POST /search/autocomplete
```

Body:

```json
{
  "query": "kimchi",
  "limit": 8,
  "client_id": "anonymny-client-id-z-widgetu"
}
```

Vracia miesane navrhy pre okienko pisania:

- `product` - produkt so skladovym badge, obrazkom a URL,
- `brand` - znacka,
- `category` - kategoria,
- `recipe` - recept z knowledge databazy,
- `synonym` - opraveny alebo rozsireny dotaz.

Radenie kombinuje zhodu v nazve, synonymá, preklepy, popularitu, dostupnost produktu, znacku, kategoriu a anonymnu dlhodobu pamat pouzivatela.

## Admin analytika otazok

Endpointy citaju `ANALYTICS_LOG_PATH` a `ERROR_LOG_PATH` a vyzaduju header:

```text
x-admin-token: <ADMIN_ANALYTICS_TOKEN>
```

Ak `ADMIN_ANALYTICS_TOKEN` nie je nastaveny, pouzije sa fallback `ADMIN_RELOAD_TOKEN`.

```text
GET /admin/analytics/summary?days=7&limit=10
GET /admin/analytics/top-questions?days=7&limit=20
GET /admin/analytics/no-results?days=7&limit=20
GET /admin/analytics/intents?days=7
```

Prehlad vracia najcastejsie otazky, otazky bez vysledku, rozdelenie intentov a slabe miesta poradcu.

## Dlhodoba pamat pouzivatela

Widget posiela anonymny `client_id` ulozeny v prehliadaci cez `localStorage`. Backend podla neho uklada zhrnuty profil do `USER_MEMORY_PATH`.

Pamät si neuklada cele konverzacie ani osobne udaje. Uklada iba kulinarske signaly:

- oblubene temy a receptove okruhy,
- kuchyne, napriklad korejska alebo vietnamska,
- dietne preferencie, napriklad pikantne, veganske alebo bezlepkove,
- najcastejsie produkty, recepty a znacky.

Tieto signaly sa potom pouziju na jemne preradenie odporucani. Relevantne produkty ostavaju v odpovedi, ale produkty z oblubenej kuchyne, oblubene znacky alebo preferovane typy jedal mozu ist vyssie.

Pamät sa da vypnut nastavenim:

```text
USER_MEMORY_ENABLED=false
```

Pouzivatelovu anonymnu pamat je mozne vymazat cez:

```text
POST /memory/clear
```

Body:

```json
{
  "client_id": "<client_id z widgetu>"
}
```

### Nastavenie tokenu na Railway

Token vygenerujte lokalne v PowerShelli:

```powershell
.\scripts\generate_admin_analytics_token.ps1
```

V Railway nastavte hodnotu do premennej:

```text
ADMIN_ANALYTICS_TOKEN=<vygenerovana-hodnota-bez-uvodzoviek>
```

Po zmene premennej spustite novy deploy alebo redeploy sluzby.

Token nikdy nevkladajte do Google Tag Managera, widgetu ani verejneho JavaScriptu. Ak bol token omylom zverejneny v chate, logu alebo screenshote, vygenerujte novy a hodnotu v Railway vymenite.

### Test cez PowerShell

Pri rucnom teste musi byt token v PowerShelli v uvodzovkach:

```powershell
$token = '<ADMIN_ANALYTICS_TOKEN>'

Invoke-RestMethod `
  -Uri "https://foodland-ai-agent-production.up.railway.app/admin/analytics/summary?days=7&limit=10" `
  -Headers @{ "x-admin-token" = $token } |
ConvertTo-Json -Depth 6
```

Alebo pouzite pripraveny helper:

```powershell
.\scripts\get_admin_analytics.ps1 -Token '<ADMIN_ANALYTICS_TOKEN>' -Endpoint summary -Days 7 -Limit 10
.\scripts\get_admin_analytics.ps1 -Token '<ADMIN_ANALYTICS_TOKEN>' -Endpoint top-questions -Days 7 -Limit 20
.\scripts\get_admin_analytics.ps1 -Token '<ADMIN_ANALYTICS_TOKEN>' -Endpoint no-results -Days 7 -Limit 20
.\scripts\get_admin_analytics.ps1 -Token '<ADMIN_ANALYTICS_TOKEN>' -Endpoint intents -Days 7
```

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

Produkcia nema nastavovat `demoMode`. Demo data su povolene iba v testovacej stranke, kde je explicitne nastavene aj `allowDemoMode: true`.

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

## CI

`.github/workflows/ci.yml` bezi na kazdy push/PR do `main`: `compileall`, plna testovacia
sada (`pytest tests/`), `consistency_audit.py --collisions`, `trust_audit.py` a
`check_deployment.py`. Bezi bez `-k` filtra - ziadne testy sa v CI nevynechavaju kvoli
lokalnym problemom tohto vyvojarskeho stroja (pozri poznamku vyssie v sekcii Struktura).

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
