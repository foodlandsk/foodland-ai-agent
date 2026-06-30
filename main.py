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

from app.cross_sell_rules import recommend_cross_sell_from_rules, recommend_live_related_products
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
    missing_recipe_ingredients,
    recipe_ingredients_answer,
    search_recipe_ingredient_products,
)
from app.search import normalize, products_context, search_products, tokenize
from app.validators import grounding_warnings
from app.workflows import WorkflowResult, detect_workflow


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


class CrossSellRecommendationRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)
    limit: int = Field(default=4, ge=1, le=12)
    shown_product_ids: list[str] = Field(default_factory=list, max_length=80)


def load_products() -> list[Product]:
    json_path = os.getenv("PRODUCTS_JSON_PATH", "data/products.json")
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


@app.post("/recommendations/cross-sell")
def cross_sell_recommendations(request: CrossSellRecommendationRequest) -> dict:
    result = recommend_live_related_products(
        request.query,
        knowledge,
        products,
        limit=request.limit,
        shown_product_ids=set(request.shown_product_ids),
    )
    if not result.cards:
        result = recommend_cross_sell_from_rules(
            request.query,
            knowledge,
            products,
            limit=request.limit,
            shown_product_ids=set(request.shown_product_ids),
        )
    return {
        "cards": result.cards,
        "trace": result.trace,
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
    meal_idea_mode = is_meal_idea_query(message)
    recipe_mode = is_recipe_query(message) and not meal_idea_mode
    ingredient_mode = is_ingredient_query(message) and not meal_idea_mode
    crosssell_mode = is_crosssell_query(message) and not meal_idea_mode
    price_sort_mode = is_price_sort_query(message)
    compare_mode = (is_compare_query(message) and not is_explainer_comparison_query(message)) or price_sort_mode
    alternative_mode = is_alternative_query(message)
    safety_mode = is_safety_query(message)
    if price_sort_mode and matches:
        matches = sort_products_by_price(matches)
    ingredient_recipe = None
    culinary_crosssell_recipe = None
    crosssell_rule_trace: dict | None = None

    if ingredient_mode:
        ingredient_limit = max(limit, 10)
        ingredient_recipe, ingredient_matches = search_recipe_ingredient_products(
            recipe_ingredients,
            products,
            message,
            ingredient_limit,
            shown_product_ids or set(),
        )
        if ingredient_recipe is not None:
            matches = ingredient_matches

    if crosssell_mode and not ingredient_mode:
        crosssell_limit = max(limit, 8)
        candidate_recipe, candidate_matches = search_recipe_ingredient_products(
            recipe_ingredients,
            products,
            message,
            crosssell_limit,
            shown_product_ids or set(),
        )
        if candidate_recipe is not None and is_culinary_recipe_crosssell(message, candidate_recipe):
            culinary_crosssell_recipe = candidate_recipe
            matches = candidate_matches

    if recipe_mode and not ingredient_mode:
        matches = []
        knowledge_matches = {"Recipes": knowledge_matches["Recipes"]} if knowledge_matches.get("Recipes") else {}

    card_matches = knowledge_matches
    if ingredient_mode:
        card_matches = {}
    elif culinary_crosssell_recipe is not None:
        card_matches = {}
    elif crosssell_mode:
        card_matches = {"CrossSell": knowledge_matches["CrossSell"]} if knowledge_matches.get("CrossSell") else {}
    elif alternative_mode or compare_mode:
        if knowledge_matches.get("Alternatives"):
            card_matches = {"Alternatives": knowledge_matches["Alternatives"]}
        elif knowledge_matches.get("CrossSell"):
            card_matches = {"CrossSell": knowledge_matches["CrossSell"]}
        else:
            card_matches = {}
    elif is_content_query(message):
        card_matches = {
            section: hits
            for section, hits in knowledge_matches.items()
            if section in {"Magazine", "IntentMapping"}
        }
    elif not recipe_mode and not ingredient_mode and matches and not is_content_query(message):
        card_matches = {}
    elif not recipe_mode and not ingredient_mode:
        card_matches = {
            section: hits
            for section, hits in knowledge_matches.items()
            if section != "Recipes"
        }

    cards = enrich_content_cards(content_cards(card_matches, lang), products)
    if alternative_mode:
        cards = filter_alternative_cards(cards)
    if crosssell_mode and culinary_crosssell_recipe is None:
        rule_result = recommend_live_related_products(
            message,
            knowledge,
            products,
            limit=4,
            shown_product_ids=shown_product_ids or set(),
        )
        if not rule_result.cards:
            rule_result = recommend_cross_sell_from_rules(
                message,
                knowledge,
                products,
                limit=4,
                shown_product_ids=shown_product_ids or set(),
            )
        if rule_result.cards:
            cards = rule_result.cards
            matches = []
        crosssell_rule_trace = rule_result.trace
    if compare_mode:
        cards = filter_compare_cards(message, cards, matches)
    intent = detect_intent(
        message,
        matches,
        knowledge_matches,
        recipe_mode,
        ingredient_mode,
        crosssell_mode,
        compare_mode,
        meal_idea_mode,
        safety_mode,
    )
    workflow = detect_workflow(
        message,
        recipe_mode=recipe_mode,
        ingredient_mode=ingredient_mode,
        crosssell_mode=crosssell_mode,
        compare_mode=compare_mode,
        alternative_mode=alternative_mode,
        has_faq=bool(knowledge_matches.get("FAQ")),
        has_products=bool(matches or cards),
        has_content=bool(knowledge_matches.get("Magazine") or knowledge_matches.get("Recipes") or knowledge_matches.get("IntentMapping")),
    )
    if workflow and crosssell_rule_trace:
        workflow.trace["cross_sell_rules"] = crosssell_rule_trace

    if meal_idea_mode:
        meal_products = meal_idea_products(message, products, limit=limit)
        log_question(
            message,
            client_key,
            mode="meal_idea",
            intent=intent,
            products_count=len(meal_products),
            knowledge_matches=knowledge_matches,
            content_cards_count=0,
            endpoint=endpoint,
            lang=lang,
        )
        return response_payload(
            meal_idea_answer(message, meal_products),
            intent,
            "meal_idea",
            lang,
            meal_products,
            knowledge_matches,
            [],
            workflow,
        )

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
        return response_payload(fallback_answer([], knowledge_matches), intent, "faq", lang, [], knowledge_matches, cards, workflow)

    if safety_mode:
        safety_products = [] if is_generic_safety_query(message) else matches
        log_question(
            message,
            client_key,
            mode="safety_check",
            intent=intent,
            products_count=len(safety_products),
            knowledge_matches=knowledge_matches,
            content_cards_count=0,
            endpoint=endpoint,
            lang=lang,
        )
        return response_payload(safety_answer(message, safety_products), intent, "safety_check", lang, safety_products, knowledge_matches, [], workflow)

    if intent == "content":
        content_cards_for_response = [] if is_specific_explainer_answer(message) else cards
        log_question(
            message,
            client_key,
            mode="content",
            intent=intent,
            products_count=0,
            knowledge_matches=knowledge_matches,
            content_cards_count=len(content_cards_for_response),
            endpoint=endpoint,
            lang=lang,
        )
        return response_payload(
            content_answer(message, knowledge_matches),
            intent,
            "content",
            lang,
            [],
            knowledge_matches,
            content_cards_for_response,
            workflow,
        )

    if compare_mode and not cards and not matches:
        log_question(
            message,
            client_key,
            mode="compare_needs_product",
            intent=intent,
            products_count=0,
            knowledge_matches={},
            content_cards_count=0,
            endpoint=endpoint,
            lang=lang,
        )
        answer = "Napiste prosim konkretny produkt, ktory chcete porovnat, napriklad 'porovnaj sriracha omacky'."
        return response_payload(answer, intent, "compare_needs_product", lang, [], {}, [], workflow)

    if intent == "compare_products" and matches:
        log_question(
            message,
            client_key,
            mode="product_compare",
            intent=intent,
            products_count=len(matches),
            knowledge_matches=knowledge_matches,
            content_cards_count=0,
            endpoint=endpoint,
            lang=lang,
        )
        return response_payload(compare_answer(matches), intent, "product_compare", lang, matches, knowledge_matches, [], workflow)

    if crosssell_mode and cards and culinary_crosssell_recipe is None:
        crosssell_mode_name = (
            "live_related_products"
            if crosssell_rule_trace and crosssell_rule_trace.get("engine") == "live_related_products_v1"
            else "cross_sell_rules"
        )
        log_question(
            message,
            client_key,
            mode=crosssell_mode_name,
            intent=intent,
            products_count=0,
            knowledge_matches=knowledge_matches,
            content_cards_count=len(cards),
            endpoint=endpoint,
            lang=lang,
        )
        return response_payload(crosssell_answer(cards), intent, crosssell_mode_name, lang, [], knowledge_matches, cards, workflow)

    if culinary_crosssell_recipe is not None:
        missing_ingredients = missing_recipe_ingredients(culinary_crosssell_recipe, matches)
        log_question(
            message,
            client_key,
            mode="culinary_cross_sell",
            intent=intent,
            products_count=len(matches),
            knowledge_matches=knowledge_matches,
            content_cards_count=0,
            endpoint=endpoint,
            lang=lang,
        )
        answer = culinary_crosssell_answer(culinary_crosssell_recipe, matches, missing_ingredients)
        return response_payload(
            answer,
            intent,
            "culinary_cross_sell",
            lang,
            matches,
            knowledge_matches,
            [],
            workflow,
            missing_ingredients=missing_ingredients,
        )

    if ingredient_mode and ingredient_recipe is not None:
        missing_ingredients = missing_recipe_ingredients(ingredient_recipe, matches)
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
        answer = recipe_ingredients_answer(ingredient_recipe, matches, missing_ingredients)
        if not matches and shown_product_ids:
            recipe_name = str(ingredient_recipe.get("name") or "receptu")
            answer = (
                f"Ďalšie spoľahlivé produkty k receptu {recipe_name} už v dátach nemám. "
                "Neopakujem už zobrazené položky ani neponúkam slabé náhrady."
            )
        return response_payload(
            answer,
            intent,
            "recipe_ingredients",
            lang,
            matches,
            knowledge_matches,
            cards,
            workflow,
            missing_ingredients=missing_ingredients,
        )

    if intent == "alternative" and cards:
        log_question(
            message,
            client_key,
            mode="alternatives",
            intent=intent,
            products_count=0,
            knowledge_matches=knowledge_matches,
            content_cards_count=len(cards),
            endpoint=endpoint,
            lang=lang,
        )
        return response_payload(alternative_answer(cards), intent, "alternatives", lang, [], knowledge_matches, cards, workflow)

    if intent == "compare_products" and cards:
        log_question(
            message,
            client_key,
            mode="compare",
            intent=intent,
            products_count=0,
            knowledge_matches=knowledge_matches,
            content_cards_count=len(cards),
            endpoint=endpoint,
            lang=lang,
        )
        return response_payload(compare_cards_answer(cards), intent, "compare", lang, [], knowledge_matches, cards, workflow)

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
        return response_payload(answer, intent, "search_only", lang, [], {}, [], workflow)

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
        return response_payload(answer, intent, "search_only", lang, matches, knowledge_matches, cards, workflow)

    try:
        client = OpenAI(api_key=api_key)
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        ai_answer = generate_openai_answer(
            client=client,
            model=model,
            lang=lang,
            message=message,
            matches=matches,
            knowledge_matches=knowledge_matches,
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
        return response_payload(ai_answer, intent, "ai", lang, matches, knowledge_matches, cards, workflow)
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
        payload = response_payload(answer, intent, "fallback", lang, matches, knowledge_matches, cards, workflow)
        payload["warning"] = "Odpoveď sa nepodarilo vygenerovať cez OpenAI, používam nájdené Foodland dáta."
        return payload


def generate_openai_answer(
    *,
    client: OpenAI,
    model: str,
    lang: str,
    message: str,
    matches: list[dict],
    knowledge_matches: dict,
) -> str:
    system_prompt = (
        "Si nakupny asistent pre Foodland.sk. Odpovedaj po slovensky, kratko a prakticky. "
        "Volas sa Foodland poradca. Neprezentuj sa ako AI. "
        "Pouzivaj iba poskytnuty kontext: produkty, FAQ, recepty, cross-sell, alternativy a Products_AI. "
        "Ak su produkty oznacene ako produkty k receptu, odporuc ich ako nakupne polozky k danemu receptu. "
        "Ak je otazka na recept, odpovedaj iba receptmi z kontextu Recipes a neponukaj produkty. "
        "Nevymyslaj produkty, ceny, sklad, URL, recepty, clanky, FAQ odpovede ani vlastnosti produktu. "
        "Kazdy produkt, cena, recept, clanok a URL v odpovedi musi byt priamo v poskytnutom kontexte. "
        "Ak kontext odpoved nepokryva, povedz to priamo a nenahradzaj chybajuce data odhadom. "
        "Pri alergiach, zlozeni a dostupnosti odporuc overit detail produktu."
    )
    user_prompt = (
        f"Jazyk odpovede: {lang}\n"
        f"Otazka zakaznika: {message}\n\n"
        f"Relevantne produkty:\n{products_context(matches)}\n\n"
        f"Foodland Knowledge:\n{knowledge_context(knowledge_matches)}"
    )

    if hasattr(client, "responses"):
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return str(response.output_text)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return str(response.choices[0].message.content or "").strip()


def response_payload(
    answer: str,
    intent: str,
    mode: str,
    lang: str,
    matches: list[dict],
    knowledge_matches: dict,
    cards: list[dict],
    workflow: WorkflowResult | None = None,
    missing_ingredients: list[dict[str, str]] | None = None,
) -> dict:
    payload = {
        "answer": answer,
        "intent": intent,
        "mode": mode,
        "lang": lang,
        "products": matches,
        "knowledge": knowledge_summary(knowledge_matches),
        "content_cards": cards,
        "suggested_actions": suggested_actions(intent, matches, cards),
    }
    if missing_ingredients is not None:
        payload["missing_ingredients"] = missing_ingredients
    if workflow:
        validator_warnings = grounding_warnings(matches, cards, products)
        if validator_warnings:
            workflow.warnings.extend(validator_warnings)
            workflow.trace["grounding_warnings_count"] = len(validator_warnings)
        else:
            workflow.trace["grounding_warnings_count"] = 0
        payload["workflow"] = workflow.to_dict()
    return payload


def enrich_content_cards(cards: list[dict], product_items: list[Product]) -> list[dict]:
    product_by_link = {normalize_url(product.link): product for product in product_items if product.link}
    enriched: list[dict] = []

    for card in cards:
        item = dict(card)
        if item.get("type") in {"cross_sell", "alternative"}:
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
    meal_idea_mode: bool = False,
    safety_mode: bool = False,
) -> str:
    if safety_mode:
        return "safety_check"
    if meal_idea_mode:
        return "meal_idea"
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
    if is_content_query(message) and (
        knowledge_matches.get("Magazine") or knowledge_matches.get("IntentMapping") or knowledge_matches.get("Products_AI")
    ):
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
        "rozdiel",
        "ako chut",
        "porad",
        "navod",
    ]
    return any(marker in normalized for marker in markers)


def is_safety_query(message: str) -> bool:
    normalized = normalize(message)
    markers = [
        "bez lepku",
        "lepok",
        "gluten",
        "alergen",
        "alerg",
        "zlozenie",
        "obsahuje",
        "vegan",
        "vegetarian",
        "tehoten",
    ]
    return any(marker in normalized for marker in markers)


def is_generic_safety_query(message: str) -> bool:
    tokens = tokenize(message)
    generic_tokens = {
        "obsahuje",
        "soju",
        "soja",
        "soj",
        "alergiu",
        "alergia",
        "alergie",
        "vhodne",
        "veganov",
        "vegan",
        "vegetarianov",
        "vegetarian",
        "bez",
        "lepku",
        "lepok",
        "gluten",
        "alergen",
        "alergeny",
        "zlozenie",
        "kupit",
    }
    return bool(tokens) and not (tokens - generic_tokens)


def is_meal_idea_query(message: str) -> bool:
    normalized = normalize(message)
    has_cooking_need = any(
        marker in normalized
        for marker in [
            "chcem uvarit",
            "co uvarit",
            "nieco k",
            "nieco pikantne",
            "co odporucate",
            "tip na jedlo",
            "inspiracia",
            "rychla vecera",
            "rychlu veceru",
            "rychly obed",
            "rychly obed",
        ]
    )
    has_broad_topic = any(marker in normalized for marker in ["ryzi", "ryza", "rezancom", "veceru", "obed", "jedlo"])
    return has_cooking_need and has_broad_topic


def meal_idea_products(message: str, product_items: list[Product], limit: int = 6) -> list[dict]:
    normalized = normalize(message)
    if "ryz" in normalized:
        queries = ["kimchi", "gochujang", "kari pasta", "kokosove mlieko", "sojova omacka", "sriracha"]
    elif "rezanc" in normalized:
        queries = ["ryzove rezance", "sojova omacka", "sriracha", "gochujang", "kimchi"]
    else:
        queries = ["kimchi", "gochujang", "kari pasta", "ryzove rezance", "kokosove mlieko"]

    results: list[dict] = []
    seen: set[str] = set()
    for query in queries:
        for product in search_products(product_items, query, 3):
            key = str(product.get("id") or product.get("link") or product.get("title") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            product["meal_idea_reason"] = query
            results.append(product)
            break
        if len(results) >= limit:
            break
    return results


def meal_idea_answer(message: str, products: list[dict]) -> str:
    if products:
        return (
            "Navrhol by som 3 rychle smery: kimchi ryza, kokosove kari alebo pikantny stir-fry. "
            "Nizsie davam produkty, z ktorych si viete rychlo vyskladat nakup."
        )
    return (
        "Viem odporucit smer, ale potrebujem trochu spresnit chut: chcete nieco pikantne, kokosove kari, "
        "rezance alebo rychlu ryzu na panvici?"
    )


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


def is_explainer_comparison_query(message: str) -> bool:
    normalized = normalize(message)
    if not any(marker in normalized for marker in ["rozdiel", "aky je rozdiel", "co je rozdiel"]):
        return False
    return any(marker in normalized for marker in ["gochujang", "gochugaru", "sriracha", "miso", "doenjang"])


def is_specific_explainer_answer(message: str) -> bool:
    normalized = normalize(message)
    return any(marker in normalized for marker in ["gochujang", "gochugaru", "sriracha"])


def is_price_sort_query(message: str) -> bool:
    normalized = normalize(message)
    markers = [
        "najlacnejs",
        "najlacn",
        "lacna",
        "lacne",
        "lacny",
        "najvyhodnejs",
        "najvyhodn",
    ]
    return any(marker in normalized for marker in markers)


def sort_products_by_price(items: list[dict]) -> list[dict]:
    return sorted(
        items,
        key=lambda item: (
            item.get("effective_price") is None,
            float(item.get("effective_price") or 0),
            str(item.get("title") or ""),
        ),
    )


def is_alternative_query(message: str) -> bool:
    normalized = normalize(message)
    markers = [
        "alternativa",
        "alternativy",
        "nahrada",
        "nahrad",
        "namiesto",
        "miesto toho",
        "podobne",
        "podobny",
    ]
    return any(marker in normalized for marker in markers)


CULINARY_CROSSSELL_NOISE_TOKENS = {
    "hodi",
    "hodia",
    "suvisiace",
    "suvisiaci",
    "odporuc",
    "odporucit",
    "doplnky",
    "kupit",
    "recept",
    "jedlo",
    "varenie",
    "priprava",
    "produkty",
    "produkt",
}


def is_culinary_recipe_crosssell(message: str, recipe: dict) -> bool:
    query_tokens = tokenize(message) - CULINARY_CROSSSELL_NOISE_TOKENS
    if not query_tokens:
        return False

    normalized_message = normalize(message)
    if "kimchi" in query_tokens and not any(
        marker in normalized_message
        for marker in ["vyrobu", "pripravu", "recept", "urobit", "spravit", "potrebujem"]
    ):
        return False

    recipe_name = str(recipe.get("name") or "")
    cuisine = str(recipe.get("cuisine") or "")
    recipe_tokens = tokenize(f"{recipe_name} {cuisine}") - CULINARY_CROSSSELL_NOISE_TOKENS
    overlap = query_tokens & recipe_tokens
    if len(overlap) >= 2:
        return True

    normalized_name = normalize(recipe_name)
    if normalized_name and normalized_name in normalized_message:
        return True

    strong_single_dish_tokens = {"kimchi", "pho", "ramen", "jjigae", "sushi", "susi", "pad", "thai", "kari", "curry"}
    return bool(overlap & strong_single_dish_tokens)


COMPARE_NOISE_TOKENS = {
    "porovnaj",
    "porovnanie",
    "porovnat",
    "porovnajme",
    "rozdiel",
    "rozdiely",
    "ktory",
    "ktora",
    "lepsi",
    "lepsia",
    "lepsie",
    "vyber",
    "vybrat",
    "cena",
    "ceny",
    "cenovo",
    "lacnejsi",
    "lacnejsia",
    "produkt",
    "produkty",
    "produktov",
    "podobny",
    "podobne",
    "podobnych",
    "moznosti",
    "moznost",
}


def filter_compare_cards(message: str, cards: list[dict], matches: list[dict]) -> list[dict]:
    if not cards:
        return []

    reference_tokens = tokenize(message) - COMPARE_NOISE_TOKENS
    match_tokens: set[str] = set()
    if matches:
        primary_match = matches[0]
        match_tokens = tokenize(
            " ".join(
                [
                    str(primary_match.get("title") or ""),
                    str(primary_match.get("brand") or ""),
                    str(primary_match.get("product_type") or ""),
                ]
            )
        )

    if not reference_tokens and not match_tokens:
        return []

    filtered: list[dict] = []
    for card in cards:
        source_tokens = tokenize(str(card.get("source_product") or ""))
        title_tokens = tokenize(str(card.get("title") or ""))
        subtitle_tokens = tokenize(str(card.get("subtitle") or ""))
        card_tokens = source_tokens | title_tokens | subtitle_tokens

        source_matches_query = bool(source_tokens and reference_tokens and (reference_tokens & source_tokens))
        card_matches_query = bool(reference_tokens and (reference_tokens & card_tokens))
        source_matches_product = bool(source_tokens and match_tokens and (source_tokens & match_tokens))
        title_matches_product = bool(title_tokens and match_tokens and (title_tokens & match_tokens))

        if source_matches_query or source_matches_product or (card_matches_query and title_matches_product):
            filtered.append(card)

    return filtered[:4]


def filter_alternative_cards(cards: list[dict]) -> list[dict]:
    filtered: list[dict] = []
    for card in cards:
        if card.get("type") != "alternative":
            filtered.append(card)
            continue

        source_tokens = tokenize(str(card.get("source_product") or ""))
        title_tokens = tokenize(str(card.get("title") or ""))
        if not source_tokens or not title_tokens:
            continue

        # Alternative must remain in the same product family. A single flavor token
        # like "kokos" is too broad and can pull in snacks for coconut milk.
        if len(source_tokens & title_tokens) >= 2:
            filtered.append(card)

    return filtered[:4]


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
    elif intent == "meal_idea":
        actions.extend(
            [
                {"label": "Kimchi ryza", "message": "Produkty na kimchi prazenu ryzu"},
                {"label": "Kokosove kari", "message": "Co kupit na rychle kokosove kari?"},
                {"label": "Stir-fry", "message": "Co kupit na pikantny stir-fry?"},
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


def content_answer(message: str, knowledge_matches: dict | None = None) -> str:
    normalized = normalize(message)
    if "gochujang" in normalized and "gochugaru" in normalized:
        return (
            "Gochujang je korejska fermentovana cili pasta: je husty, slano-pikantny a umami. "
            "Pouziva sa do marinad, bibimbapu, omacok a polievok. Gochugaru je korejske cervene cili vo forme vlociek alebo prasku. "
            "Pouziva sa najma na kimchi a pikantne korejske jedla. Nie su to rovnake suroviny: pasta sa neda vzdy nahradit praskom a naopak."
        )
    if "gochujang" in normalized or "gocudzang" in normalized or "gocujang" in normalized:
        return (
            "Gochujang je korejska fermentovana cili pasta. Pouziva sa do kimchi, bibimbapu, marinad, "
            "polievok, ryzovych misiek a omacok. Je pikantna, slana a ma vyrazne umami. "
            "Pri alergiach a zlozeni si prosim overte detail konkretneho produktu."
        )
    if "gochugaru" in normalized:
        return (
            "Gochugaru je korejske cervene cili, vacsinou vo forme vlociek alebo prasku. "
            "Pouziva sa najma na kimchi, jjigae a pikantne korejske jedla. Nie je to to iste ako gochujang pasta."
        )
    if "sriracha" in normalized:
        return (
            "Sriracha je pikantna cili omacka vhodna k rezancom, ryzi, masu, zelenine, marinadam a dipom. "
            "Rozdiely medzi produktmi su hlavne v palivosti, baleni, znacke a chuti."
        )
    if knowledge_matches and knowledge_matches.get("Products_AI"):
        return "Nasiel som vysvetlenie vo Foodland poradci. Pri zlozeni, alergenoch a dostupnosti si prosim overte detail produktu."
    return "Nasiel som suvisiace informacie vo Foodland poradci."


def safety_answer(message: str, matches: list[dict]) -> str:
    if matches:
        return (
            "Toto neviem spolahlivo potvrdit iba z vyhladavania. Pri lepku, alergenoch, zlozeni a dietnych obmedzeniach "
            "si prosim otvorte detail konkretneho produktu a skontrolujte zlozenie na obale. Nizsie davam relevantne produkty na overenie."
        )
    return (
        "Toto neviem spolahlivo potvrdit z dostupnych dat. Pri lepku, alergenoch, zlozeni a dietnych obmedzeniach "
        "si prosim overte detail konkretneho produktu alebo etiketu."
    )


def crosssell_answer(cards: list[dict]) -> str:
    count = min(len(cards), 4)
    if count == 1:
        return "Našiel som jeden súvisiaci produkt. Pozrieť si ho môžete nižšie."
    return f"Našiel som {count} súvisiace produkty, ktoré sa k tomu hodia. Pozrieť si ich môžete nižšie."


def culinary_crosssell_answer(
    recipe: dict,
    products: list[dict],
    missing_ingredients: list[dict[str, str]] | None = None,
) -> str:
    recipe_name = str(recipe.get("name") or "tomuto jedlu")
    count = len(products)
    missing_count = len(missing_ingredients or [])
    if count and missing_count:
        return (
            f"K jedlu {recipe_name} som vybral {count} Foodland produktov podla receptu a kucharskej kombinacie. "
            "Suroviny, ktore nie su spolahlivo sparovane s e-shopom, uvadzam zvlast na dokupenie."
        )
    if count:
        return f"K jedlu {recipe_name} som vybral {count} Foodland produktov, ktore spolu kucharsky davaju zmysel."
    if missing_count:
        return f"K jedlu {recipe_name} nemam spolahlive Foodland produktove karty, ale suroviny na dokupenie uvadzam nizsie."
    return f"K jedlu {recipe_name} zatial nemam spolahlive cross-sell odporucania."


def alternative_answer(cards: list[dict]) -> str:
    count = min(len(cards), 4)
    if count == 1:
        return "Našiel som jednu vhodnú alternatívu vo Foodland poradci. Pozrite si ju nižšie."
    return f"Našiel som {count} vhodné alternatívy vo Foodland poradci. Porovnajte cenu, balenie a dostupnosť nižšie."


def compare_cards_answer(cards: list[dict]) -> str:
    count = min(len(cards), 4)
    if count == 1:
        return "Našiel som jednu možnosť na porovnanie vo Foodland poradci."
    return f"Vybral som {count} možnosti na porovnanie z Foodland dát. Pozrite si cenu, balenie, značku a dostupnosť pri kartách nižšie."


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
