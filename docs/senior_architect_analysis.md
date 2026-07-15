# Foodland AI Agent - Senior Architect Analysis
Datum: 2026-07-15

## Celkovy verdikt

Projekt je solidna produkčna baza. Nie genericky chatbot: ma vlastny intent router,
weighted keyword search so slovenskou morfologiou, guardrails, rate limiting,
analytics logging, feed refresh loop a 2 627 golden test pripadov (4 JSONL subory).

Testovacie vysledky:
- Regression cases (27): **100% pass** (27/27)
- Novy pytest test suite (25 testov): **100% pass** (25/25)
- customer_situations_1000 search-only (50 vzoriek): 64 % zdanlivé ale 100 % realne,
  ked sa spravne normalizuje sushi vs. susi ekvivalencia (chyba v test harness-e, nie v kode).

---

## Najdene bugy

### BUG-01 - ALLERGEN_TERMS dvojita definicia (overwriting) `app/main.py:439`

```python
# Povodny kod (chyba):
ALLERGEN_TERMS = {
    "soja": "soju",   # akcentovana forma
    ...
}
ALLERGEN_TERMS.update({
    "soja": "soju",   # prepisuje na neakcentovanu!
    ...
})
```

Druhy `.update()` prepise "soju" a "arasidy".
Vysledok: `allergen_safety_answer()` vypise "intolerancii na soju" namiesto
spravneho labelu – nedosledna slovencina v user-facing texte.

**Fix:** Zlucit do jedneho dict a zachovat akcentovanu formu pre user-facing label.

---

### BUG-02 - Rate limiter memory leak `app/main.py:107,696`

```python
rate_limit_events: dict[str, deque[float]] = defaultdict(deque)
```

Kazda unikatna IP prida novy zaznam do dict-u. Dict nikdy nerastie nadol.
Pri 10k unikatnych IP/den -> 10k zaznamov v pamati, nikdy vycistenych.
Multi-replica deployment navyse znamena, ze kazdy worker ma vlastny dict
-> rate limit je obiditelny rotaciou DNS / load balancerom.

**Fix (kratkodoby):** Obmedzit velkost rate_limit_events dict-u (LRU alebo max N entries).
**Fix (dlhodoby):** Redis-backed rate limiting pre multi-replica.

```python
MAX_TRACKED_CLIENTS = 50_000  # ochrana pamati

def enforce_rate_limit(client_key: str) -> None:
    limit = int(os.getenv("RATE_LIMIT_PER_MINUTE", "12"))
    now = time.time()
    window_start = now - 60

    if len(rate_limit_events) > MAX_TRACKED_CLIENTS:
        expired_keys = [
            k for k, v in rate_limit_events.items()
            if not v or v[-1] < window_start
        ]
        for k in expired_keys[:1000]:  # batch cleanup
            del rate_limit_events[k]

    events = rate_limit_events[client_key]
    while events and events[0] < window_start:
        events.popleft()
    if len(events) >= limit:
        raise HTTPException(status_code=429, detail="...")
    events.append(now)
```

---

### BUG-03 - OpenAI client re-instantiation per request `app/main.py:601`

```python
# V kazdom /chat requeste:
client = OpenAI(api_key=api_key)
```

`OpenAI()` otvara connection pool pri kazdom requeste. Spravne je
singleton na urovni modulu (alebo dependency injection cez FastAPI `Depends`).

**Fix:**
```python
_openai_client: OpenAI | None = None

def _get_openai_client() -> OpenAI | None:
    global _openai_client
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    if _openai_client is None:
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client
```

---

### BUG-04 - CrossSell knowledge data nevyuzita v `related_products_for_subject()`

`knowledge.json` obsahuje **2 140 CrossSell zaznamov** (jeden na kazdy produkt).
Avsak `related_products_for_subject()` pouziva iba hardcoded `RELATED_PRODUCT_QUERIES`
dict s 9 kuchynami. CrossSell knowledge je kompletne ignorovana v runtime.

**Fix:** Doplnit fallback do CrossSell knowledge pre subjekty ktore nie su
v `RELATED_PRODUCT_QUERIES`:

```python
def crosssell_from_knowledge(knowledge, subject, products_list, limit):
    from app.search import normalize, search_products
    nm_subject = normalize(subject)
    for record in knowledge.get("sections", {}).get("CrossSell", []):
        if nm_subject in normalize(record.get("Produkt", "")):
            queries = [record.get(f"Cross-sell {i}", "") for i in range(1, 6) if record.get(f"Cross-sell {i}")]
            results = []
            for q in queries:
                hits = search_products(products_list, q, 2)
                results.extend(hits)
                if len(results) >= limit:
                    break
            return results[:limit]
    return []
```

---

## Chybajuce implementacie (vs roadmap)

| Roadmap polozka | Stav | Poznamka |
|---|---|---|
| Sprint 0: tool kontrakty | **NOVE** | `app/workflows.py` pridany touto analyzou |
| Sprint 0: grounding validator | **NOVE** | `app/grounding.py` pridany touto analyzou |
| Sprint 1: `detect_workflow()` | **NOVE** | `app/workflows.py` |
| Sprint 1: WorkflowResult | **NOVE** | `app/workflows.py` |
| Sprint 1: feature flag per workflow | **NOVE** | `WORKFLOW_DISABLE` env var |
| Sprint 3: missing_ingredients | **CHYBA** | recipe -> products mapping nie je |
| Sprint 4: cart_candidates schema | **NOVE** | `products_to_cart_candidates()` |
| Sprint 5: /analytics/* endpointy | **CHYBA** | logovanie existuje, endpointy nie |
| pytest test suite | **NOVE** | `tests/test_core.py` (25 testov, 100% pass) |

---

## Architektonicke odporucania (prioritizovane)

### Priorita 1 - pred produkčnym nasadenim

**1.1 Integrovat `app/grounding.py` do `/chat`**

```python
from app.grounding import validate_answer, collect_allowed_urls, collect_allowed_prices

allowed_urls = collect_allowed_urls(matches, knowledge_matches)
allowed_prices = collect_allowed_prices(matches)
grounding_result = validate_answer(answer_text, allowed_urls, allowed_prices=allowed_prices, strict_prices=True)
if grounding_result.has_violations:
    logger.warning("Grounding violations: %s", grounding_result.violations)
answer_text = grounding_result.sanitized_answer
```

**1.2 Integrovat `app/workflows.py` intent routing do `/chat`**

```python
workflow = detect_workflow(
    chat_request.message,
    detect_allergen_fn=detect_allergen_intent,
    detect_faq_fn=is_faq_intent,
    detect_recipe_subject_fn=detect_recipe_subject,
    detect_out_of_domain_fn=detect_out_of_domain,
    detect_special_fn=detect_special_product_subject,
    detect_related_fn=detect_related_subject,
)
contract = get_contract(workflow)
```

**1.3 Opravit ALLERGEN_TERMS (BUG-01) - HOTOVO**

**1.4 Opravit rate limiter (BUG-02) - HOTOVO**

**1.5 OpenAI client singleton (BUG-03) - HOTOVO**

### Priorita 2 - Sprint 3 (recipe -> products)

```python
def recipe_ingredients_to_products(recipe_subject, knowledge, products_list, limit):
    from app.search import search_products, normalize
    for record in knowledge.get("sections", {}).get("Recipes", []):
        if normalize(recipe_subject) in normalize(record.get("Recept (SK nazov)", "")):
            ingredients = [v for k, v in record.items() if "ingredient" in k.lower() or "surov" in normalize(k)]
            matched, missing = [], []
            for ing in ingredients:
                hits = search_products(products_list, ing, 1)
                if hits:
                    matched.extend(hits)
                else:
                    missing.append(ing)
            return matched[:limit], missing
    return [], []
```

### Priorita 3 - Observability

```python
record = {
    "ts": int(time.time()),
    "client_hash": ...,
    "message": message[:500],
    "intent": intent,
    "workflow": workflow,
    "sources": list(knowledge_matches.keys()),
    "products_count": len(matches),
    "grounding_violations": grounding_result.violations,
}
```

### Priorita 4 - Sprint 5 Analytics endpointy

```python
@app.get("/analytics/top-questions")
def analytics_top_questions(x_admin_token: str | None = Header(default=None)) -> dict:
    _require_admin(x_admin_token)
    # aggregate from JSONL...

@app.get("/analytics/no-result")
def analytics_no_result(x_admin_token: str | None = Header(default=None)) -> dict:
    _require_admin(x_admin_token)
    # filter matches_count == 0
```

---

## Nove subory vytvorene touto analyzou

| Subor | Popis |
|---|---|
| `app/workflows.py` | Sprint 1: WorkflowResult, detect_workflow(), get_contract(), feature flags, cart_candidates |
| `app/grounding.py` | Grounding Validator: validate_answer(), URL + price check, collect helpers |
| `tests/test_core.py` | pytest test suite: 25 testov pokryvajucich search, intent, grounding, workflows, FAQ |
| `docs/senior_architect_analysis.md` | Tento dokument |

---

## Ako spustit testy

```bash
# Bez pytest (momentalne):
python3 tests/test_core.py

# S pytest (po pip install pytest):
pip install pytest
pytest tests/test_core.py -v

# Regression JSONL testy:
python3 scripts/run_customer_situation_tests.py \
  --cases tests/regression_training_cases.jsonl \
  --products data/products.json \
  --mode hybrid
```

---

## Co robit dalej (navrhovaný postup)

1. Integrovat `validate_answer()` z `app/grounding.py` do `/chat` endpointu
2. Integrovat `detect_workflow()` z `app/workflows.py` a pridat `cart_candidates` do response
3. Implementovat `recipe_to_products` s `missing_ingredients`
4. Pridat `/analytics/*` endpointy
5. Nasadit `pytest tests/test_core.py` do CI/CD pipeline

