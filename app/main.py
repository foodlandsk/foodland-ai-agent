from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel, Field

from app.feed import Product, load_products_json, parse_google_merchant_feed
from app.knowledge import (
    best_faq_answer,
    best_recipe_answer,
    content_cards,
    is_recipe_query,
    knowledge_context,
    knowledge_summary,
    load_knowledge_json,
    normalize_lang,
    search_knowledge,
)
from app.recipe_ingredients import (
    is_ingredient_query,
    load_recipe_ingredients_json,
    recipe_ingredients_answer,
    search_recipe_ingredient_products,
)
from app.search import normalize, products_context, search_products


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    limit: int = Field(default=6, ge=1, le=12)
    shown_product_ids: list[str] = Field(default_factory=list, max_length=80)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    lang: str = Field(default="SK", min_length=2, max_length=2)
    limit: int = Field(default=6, ge=1, le=12)
    shown_product_ids: list[str] = Field(default_factory=list, max_length=80)


class ProductSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)
    limit: int = Field(default=8, ge=1, le=30)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)


def load_products() -> list[Product]:
    json_path = os.getenv("PRODUCTS_JSON_PATH")
    feed_path = os.getenv("PRODUCT_FEED_PATH", "data/googleMerchant_sk_export.xml")

    if json_path and Path(json_path).exists():
        return load_products_json(json_path)
    if Path(feed_path).exists() or feed_path.startswith(("http://", "https://")):
        return parse_google_merchant_feed(feed_path)
    return []


def load_knowledge() -> dict:
    return load_knowledge_json(os.getenv("KNOWLEDGE_JSON_PATH", "data/knowledge.json"))


def load_recipe_ingredients() -> list[dict]:
    return load_recipe_ingredients_json(os.getenv("RECIPE_INGREDIENTS_PATH", "data/recipe_ingredients.json"))


products = load_products()
knowledge = load_knowledge()
recipe_ingredients = load_recipe_ingredients()
last_feed_refresh_at = int(time.time()) if products else None
last_feed_refresh_error: str | None = None
feed_refresh_task: asyncio.Task | None = None
rate_limit_events: dict[str, deque[float]] = defaultdict(deque)

app = FastAPI(title="Foodland AI Agent", version="0.1.0")
app.mount("/static", StaticFiles(directory=Path(__file__).parent), name="static")

allowed_origins = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "https://www.foodland.sk,https://foodland.sk").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "products": len(products),
        "knowledge": knowledge.get("counts", {}),
        "recipe_ingredients": len(recipe_ingredients),
        "last_feed_refresh_at": last_feed_refresh_at,
        "last_feed_refresh_error": last_feed_refresh_error,
    }


@app.post("/products/search")
def product_search(request: ProductSearchRequest) -> dict:
    return {"products": search_products(products, request.query, request.limit)}


@app.post("/knowledge/search")
def knowledge_search(request: KnowledgeSearchRequest) -> dict:
    results = search_knowledge(knowledge, request.query)
    return {
        "summary": knowledge_summary(results),
        "results": results,
    }


@app.post("/chat")
def chat(chat_request: ChatRequest, request: Request) -> dict:
    return answer_question(
        message=chat_request.message,
        limit=chat_request.limit,
        lang="SK",
        endpoint="chat",
        request=request,
        shown_product_ids=set(chat_request.shown_product_ids),
    )


@app.post("/ask")
def ask(ask_request: AskRequest, request: Request) -> dict:
    return answer_question(
        message=ask_request.question,
        limit=ask_request.limit,
        lang=normalize_lang(ask_request.lang),
        endpoint="ask",
        request=request,
        shown_product_ids=set(ask_request.shown_product_ids),
    )


def answer_question(
    message: str,
    limit: int,
    lang: str,
    endpoint: str,
    request: Request,
    shown_product_ids: set[str] | None = None,
) -> dict:
    client_key = get_client_key(request)
    enforce_rate_limit(client_key)

    matches = search_products(products, message, limit)
    knowledge_matches = search_knowledge(knowledge, message)
    recipe_mode = is_recipe_query(message)
    ingredient_mode = is_ingredient_query(message)
    crosssell_mode = is_crosssell_query(message)
    compare_mode = is_compare_query(message)
    ingredient_recipe = None

    if ingredient_mode:
        ingredient_recipe, ingredient_matches = search_recipe_ingredient_products(
            recipe_ingredients,
            products,
            message,
            limit,
            shown_product_ids or set(),
        )
        if ingredient_recipe is not None:
            matches = ingredient_matches

    if recipe_mode and not ingredient_mode:
        matches = []
        knowledge_matches = {"Recipes": knowledge_matches["Recipes"]} if knowledge_matches.get("Recipes") else {}

    card_matches = knowledge_matches
    if ingredient_mode:
        card_matches = {}
    elif crosssell_mode:
        card_matches = {"CrossSell": knowledge_matches["CrossSell"]} if knowledge_matches.get("CrossSell") else {}
    elif not recipe_mode and not ingredient_mode and matches and not is_content_query(message):
        card_matches = {}
    elif not recipe_mode and not ingredient_mode:
        card_matches = {
            section: hits
            for section, hits in knowledge_matches.items()
            if section != "Recipes"
        }

    cards = enrich_content_cards(content_cards(card_matches, lang), products)
    intent = detect_intent(message, matches, knowledge_matches, recipe_mode, ingredient_mode, crosssell_mode, compare_mode)

    if intent == "faq":
        log_question(
            message,
            client_key,
            mode="faq",
            intent=intent,
            products_count=0,
            knowledge_matches=knowledge_matches,
            content_cards_count=len(cards),
            endpoint=endpoint,
            lang=lang,
        )
        return response_payload(fallback_answer([], knowledge_matches), intent, "faq", lang, [], knowledge_matches, cards)

    if ingredient_mode and ingredient_recipe is not None:
        log_question(
            message,
            client_key,
            mode="recipe_ingredients",
            intent=intent,
            products_count=len(matches),
            knowledge_matches=knowledge_matches,
            content_cards_count=len(cards),
            endpoint=endpoint,
            lang=lang,
        )
        answer = recipe_ingredients_answer(ingredient_recipe, matches)
        if not matches and shown_product_ids:
            recipe_name = str(ingredient_recipe.get("name") or "receptu")
            answer = (
                f"Ďalšie spoľahlivé produkty k receptu {recipe_name} už v dátach nemám. "
                "Neopakujem už zobrazené položky ani neponúkam slabé náhrady."
            )
        return response_payload(answer, intent, "recipe_ingredients", lang, matches, knowledge_matches, cards)

    if not matches and not knowledge_matches:
        log_question(
            message,
            client_key,
            mode="search_only",
            intent=intent,
            products_count=0,
            knowledge_matches={},
            content_cards_count=0,
            endpoint=endpoint,
            lang=lang,
        )
        answer = (
            "Konkrétny recept som zatiaľ nenašiel. Skúste napísať názov jedla alebo surovinu "
            "konkrétnejšie, napríklad 'recept na kimchi' alebo 'ako pripraviť ramen'."
            if recipe_mode or ingredient_mode
            else "Nenašiel som presný produkt ani odpoveď. Skúste napísať názov, značku alebo tému trochu inak."
        )
        return response_payload(answer, intent, "search_only", lang, [], {}, [])

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        log_question(
            message,
            client_key,
            mode="search_only",
            intent=intent,
            products_count=len(matches),
            knowledge_matches=knowledge_matches,
            content_cards_count=len(cards),
            endpoint=endpoint,
            lang=lang,
        )
        if ingredient_mode and ingredient_recipe:
            answer = recipe_ingredients_answer(ingredient_recipe, matches)
        elif compare_mode and matches:
            answer = compare_answer(matches)
        else:
            answer = crosssell_answer(cards) if crosssell_mode and cards else fallback_answer(matches, knowledge_matches)
        return response_payload(answer, intent, "search_only", lang, matches, knowledge_matches, cards)

    try:
        client = OpenAI(api_key=api_key)
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Si nakupny asistent pre Foodland.sk. Odpovedaj po slovensky, kratko a prakticky. "
                        "Volas sa Foodland poradca. Neprezentuj sa ako AI. "
                        "Pouzivaj iba poskytnuty kontext: produkty, FAQ, recepty, cross-sell, alternativy a Products_AI. "
                        "Ak su produkty oznacene ako produkty k receptu, odporuc ich ako nakupne polozky k danemu receptu. "
                        "Ak je otazka na recept, odpovedaj iba receptmi z kontextu Recipes a neponukaj produkty. "
                        "Nevymyslaj produkty, ceny, sklad, URL, recepty, clanky, FAQ odpovede ani vlastnosti produktu. "
                        "Kazdy produkt, cena, recept, clanok a URL v odpovedi musi byt priamo v poskytnutom kontexte. "
                        "Ak kontext odpoved nepokryva, povedz to priamo a nenahradzaj chybajuce data odhadom. "
                        "Pri alergiach, zlozeni a dostupnosti "
                        "odporuc overit detail produktu."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Jazyk odpovede: {lang}\n"
                        f"Otazka zakaznika: {message}\n\n"
                        f"Relevantne produkty:\n{products_context(matches)}\n\n"
                        f"Foodland Knowledge:\n{knowledge_context(knowledge_matches)}"
                    ),
                },
            ],
        )
        log_question(
            message,
            client_key,
            mode="ai",
            intent=intent,
            products_count=len(matches),
            knowledge_matches=knowledge_matches,
            content_cards_count=len(cards),
            endpoint=endpoint,
            lang=lang,
        )
        return response_payload(response.output_text, intent, "ai", lang, matches, knowledge_matches, cards)
    except Exception as exc:
        log_backend_error("openai_response_failed", str(exc))
        log_question(
            message,
            client_key,
            mode="fallback",
            intent=intent,
            products_count=len(matches),
            knowledge_matches=knowledge_matches,
            content_cards_count=len(cards),
            endpoint=endpoint,
            lang=lang,
        )
        if ingredient_mode and ingredient_recipe:
            answer = recipe_ingredients_answer(ingredient_recipe, matches)
        else:
            answer = crosssell_answer(cards) if crosssell_mode and cards else fallback_answer(matches, knowledge_matches)
        payload = response_payload(answer, intent, "fallback", lang, matches, knowledge_matches, cards)
        payload["warning"] = "Odpoveď sa nepodarilo vygenerovať cez OpenAI, používam nájdené Foodland dáta."
        return payload


def response_payload(
    answer: str,
    intent: str,
    mode: str,
    lang: str,
    matches: list[dict],
    knowledge_matches: dict,
    cards: list[dict],
) -> dict:
    return {
        "answer": answer,
        "intent": intent,
        "mode": mode,
        "lang": lang,
        "products": matches,
        "knowledge": knowledge_summary(knowledge_matches),
        "content_cards": cards,
        "suggested_actions": suggested_actions(intent, matches, cards),
    }


def enrich_content_cards(cards: list[dict], product_items: list[Product]) -> list[dict]:
    product_by_link = {normalize_url(product.link): product for product in product_items if product.link}
    enriched: list[dict] = []

    for card in cards:
        item = dict(card)
        if item.get("type") == "cross_sell":
            product = product_by_link.get(normalize_url(str(item.get("url") or "")))
            if product:
                item["image_link"] = product.image_link
                item["effective_price"] = product.effective_price
                item["currency"] = product.currency
                item["availability"] = product.availability
                item["brand"] = product.brand
        enriched.append(item)

    return enriched


def normalize_url(value: str) -> str:
    return value.strip().split("?", 1)[0].rstrip("/")


def get_client_key(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(client_key: str) -> None:
    limit = int(os.getenv("RATE_LIMIT_PER_MINUTE", "12"))
    now = time.time()
    window_start = now - 60
    events = rate_limit_events[client_key]

    while events and events[0] < window_start:
        events.popleft()

    if len(events) >= limit:
        raise HTTPException(
            status_code=429,
            detail="Príliš veľa otázok za krátky čas. Skúste to prosím o chvíľu.",
        )

    events.append(now)


def detect_intent(
    message: str,
    matches: list[dict],
    knowledge_matches: dict,
    recipe_mode: bool,
    ingredient_mode: bool,
    crosssell_mode: bool,
    compare_mode: bool,
) -> str:
    if ingredient_mode:
        return "recipe_ingredients"
    if recipe_mode:
        return "recipe"
    if compare_mode:
        return "compare_products"
    if crosssell_mode:
        return "cross_sell"
    if is_alternative_query(message):
        return "alternative"
    if knowledge_matches.get("FAQ") and not matches:
        return "faq"
    if is_content_query(message) and (knowledge_matches.get("Magazine") or knowledge_matches.get("IntentMapping")):
        return "content"
    if matches:
        return "product"
    if knowledge_matches.get("Products_AI"):
        return "product_advice"
    if knowledge_matches:
        return next(iter(knowledge_matches)).lower()
    return "unknown"


def is_content_query(message: str) -> bool:
    normalized = normalize(message)
    markers = [
        "clan",
        "blog",
        "magaz",
        "co je",
        "ako chut",
        "porad",
        "navod",
    ]
    return any(marker in normalized for marker in markers)


def is_crosssell_query(message: str) -> bool:
    normalized = normalize(message)
    markers = [
        "suvisiace",
        "suvisiaci",
        "co kupit",
        "co sa hodi",
        "k tomu",
        "hodi sa",
        "doplnky",
        "odporuc",
        "cross",
    ]
    return any(marker in normalized for marker in markers)


def is_compare_query(message: str) -> bool:
    normalized = normalize(message)
    markers = [
        "porovnaj",
        "porovnanie",
        "rozdiel",
        "rozdiely",
        "ktory je lepsi",
        "ktora je lepsia",
        "co je lepsie",
        "vyber",
        "vybrat",
    ]
    return any(marker in normalized for marker in markers)


def is_alternative_query(message: str) -> bool:
    normalized = normalize(message)
    markers = [
        "alternativa",
        "alternativy",
        "nahrada",
        "namiesto",
        "miesto toho",
        "podobne",
        "podobny",
    ]
    return any(marker in normalized for marker in markers)


def suggested_actions(intent: str, matches: list[dict], cards: list[dict]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    topic = primary_topic(matches, cards)

    if intent == "recipe_ingredients":
        actions.extend(
            [
                {"label": "Súvisiace produkty", "message": f"Súvisiace produkty k {topic}"},
                {"label": "Nájdi alternatívy", "message": f"Alternatívy k {topic}"},
            ]
        )
    elif intent == "recipe":
        actions.extend(
            [
                {"label": "Produkty na recept", "message": f"Produkty na recept {topic}"},
                {"label": "Čo sa k tomu hodí", "message": f"Čo sa hodí k {topic}?"},
            ]
        )
    elif intent == "product":
        actions.extend(
            [
                {"label": "Porovnať možnosti", "message": f"Porovnaj {topic}"},
                {"label": "Čo sa k tomu hodí", "message": f"Čo sa hodí k {topic}?"},
                {"label": "Nájdi alternatívy", "message": f"Alternatívy k {topic}"},
            ]
        )
    elif intent == "compare_products":
        actions.extend(
            [
                {"label": "Lacnejšia alternatíva", "message": f"Lacnejšia alternatíva k {topic}"},
                {"label": "Produkty na recept", "message": f"Produkty na recept {topic}"},
            ]
        )
    elif intent == "content":
        actions.append({"label": "Odporuč produkty", "message": f"Odporuč produkty k téme {topic}"})

    return actions[:3]


def primary_topic(matches: list[dict], cards: list[dict]) -> str:
    if cards:
        title = str(cards[0].get("title") or "").strip()
        if title:
            return title
    if matches:
        title = str(matches[0].get("recipe_name") or matches[0].get("title") or "").strip()
        if title:
            return title
    return "tomuto výberu"


def log_question(
    message: str,
    client_key: str,
    *,
    mode: str,
    intent: str,
    products_count: int,
    knowledge_matches: dict,
    content_cards_count: int,
    endpoint: str,
    lang: str,
) -> None:
    path = Path(os.getenv("ANALYTICS_LOG_PATH", "data/question_analytics.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    salt = os.getenv("ANALYTICS_SALT", "")
    record = {
        "ts": int(time.time()),
        "client_hash": hashlib.sha256(f"{salt}:{client_key}".encode("utf-8")).hexdigest()[:24],
        "endpoint": endpoint,
        "lang": lang,
        "mode": mode,
        "intent": intent,
        "message": message[:1000],
        "products_count": products_count,
        "knowledge_summary": knowledge_summary(knowledge_matches),
        "content_cards_count": content_cards_count,
    }
    if os.getenv("ANALYTICS_INCLUDE_IP", "false").lower() == "true":
        record["ip"] = client_key
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def log_backend_error(event: str, detail: str) -> None:
    path = Path(os.getenv("ERROR_LOG_PATH", "data/backend_errors.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": int(time.time()),
        "event": event,
        "detail": detail[:1000],
    }
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def fallback_answer(matches: list[dict], knowledge_matches: dict | None = None) -> str:
    knowledge_matches = knowledge_matches or {}
    faq_answer = best_faq_answer(knowledge_matches)
    if faq_answer and not matches:
        return faq_answer
    recipe_answer = best_recipe_answer(knowledge_matches)
    if recipe_answer and not matches:
        return recipe_answer

    if matches:
        count = min(len(matches), 5)
        if knowledge_matches:
            return f"Našiel som {count} vhodných produktov a doplnil som odporúčania z Foodland poradcu."
        return f"Našiel som {count} vhodných produktov. Pozrite si odporúčania nižšie."

    if knowledge_matches:
        return "Našiel som súvisiace informácie vo Foodland poradcovi."

    return "Nenašiel som presnú odpoveď. Skúste otázku napísať trochu inak."


def crosssell_answer(cards: list[dict]) -> str:
    count = min(len(cards), 4)
    if count == 1:
        return "Našiel som jeden súvisiaci produkt. Pozrieť si ho môžete nižšie."
    return f"Našiel som {count} súvisiace produkty, ktoré sa k tomu hodia. Pozrieť si ich môžete nižšie."


def compare_answer(matches: list[dict]) -> str:
    count = min(len(matches), 4)
    if count <= 1:
        return "Našiel som jednu vhodnú možnosť. Pri porovnaní odporúčam pozrieť cenu, balenie a dostupnosť."
    return f"Vybral som {count} možnosti na porovnanie. Pozrite si hlavne cenu, balenie, značku a dostupnosť pri kartičkách nižšie."


@app.on_event("startup")
async def start_feed_refresh_loop() -> None:
    global feed_refresh_task
    refresh_minutes = int(os.getenv("FEED_REFRESH_MINUTES", "0"))
    if refresh_minutes > 0:
        feed_refresh_task = asyncio.create_task(feed_refresh_loop(refresh_minutes))


@app.on_event("shutdown")
async def stop_feed_refresh_loop() -> None:
    if feed_refresh_task:
        feed_refresh_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await feed_refresh_task


async def feed_refresh_loop(refresh_minutes: int) -> None:
    while True:
        await asyncio.sleep(refresh_minutes * 60)
        await asyncio.to_thread(refresh_feed)


def refresh_feed() -> None:
    global products, last_feed_refresh_at, last_feed_refresh_error
    try:
        refreshed_products = load_products()
        if refreshed_products:
            products = refreshed_products
            last_feed_refresh_at = int(time.time())
            last_feed_refresh_error = None
    except Exception as exc:
        last_feed_refresh_error = str(exc)


@app.post("/admin/reload-feed")
def reload_feed(x_admin_token: str | None = Header(default=None)) -> dict:
    token = os.getenv("ADMIN_RELOAD_TOKEN")
    if not token:
        raise HTTPException(status_code=403, detail="Admin reload is disabled.")
    if x_admin_token != token:
        raise HTTPException(status_code=401, detail="Invalid admin token.")

    refresh_feed()
    return {"status": "reloaded", "products": len(products)}
