from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
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
    knowledge_context,
    knowledge_summary,
    load_knowledge_json,
    search_knowledge,
)
from app.search import normalize, products_context, search_products


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    limit: int = Field(default=6, ge=1, le=12)


class ProductSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)
    limit: int = Field(default=8, ge=1, le=30)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)


def load_products() -> list[Product]:
    json_path = os.getenv("PRODUCTS_JSON_PATH", "data/products.json")
    feed_path = os.getenv("PRODUCT_FEED_PATH", "data/googleMerchant_sk_export.xml")

    if json_path and Path(json_path).exists():
        logger.info("Loading products from JSON: %s", json_path)
        return load_products_json(json_path)
    if Path(feed_path).exists() or feed_path.startswith(("http://", "https://")):
        logger.info("Loading products from feed: %s", feed_path)
        return parse_google_merchant_feed(feed_path)
    logger.warning("No products source found at: %s", json_path or feed_path)
    return []


def load_knowledge() -> dict:
    knowledge_path = os.getenv("KNOWLEDGE_JSON_PATH", "data/knowledge.json")
    try:
        loaded_knowledge = load_knowledge_json(knowledge_path)
        logger.info("Knowledge loaded: %s", loaded_knowledge.get("counts", {}))
        return loaded_knowledge
    except Exception as exc:
        logger.error("Failed to load knowledge from %s: %s", knowledge_path, exc, exc_info=True)
        return {"version": "error", "sections": {}, "counts": {}}


products = load_products()
knowledge = load_knowledge()
last_feed_refresh_at = int(time.time()) if products else None
last_feed_refresh_error: str | None = None
feed_refresh_task: asyncio.Task | None = None
rate_limit_events: dict[str, deque[float]] = defaultdict(deque)

RELATED_PRODUCT_QUERIES = {
    "kimchi": [
        "gochujang",
        "gochugaru",
        "cervena cili paprika",
        "rybacia omacka",
        "ryzova muka",
        "sezamovy olej",
        "sojova omacka",
        "ramen",
        "jazminova ryza",
    ],
    "sushi": [
        "nori",
        "ryzovy ocot",
        "wasabi",
        "nakladany zazvor",
        "sojova omacka",
        "bezlepkova sojova omacka",
        "bambusova podlozka sushi",
    ],
    "gochujang": [
        "kimchi",
        "sezamovy olej",
        "jazminova ryza",
        "sushi ryza",
        "ramen",
        "sojova omacka",
        "gochugaru",
    ],
    "ramen": [
        "ramen rezance",
        "miso pasta",
        "wakame",
        "kimchi",
        "sezamovy olej",
        "sojova omacka",
        "sriracha",
    ],
    "kari": [
        "kokosove mlieko",
        "jazminova ryza",
        "rybacia omacka",
        "kari pasta cervena",
        "kari pasta zelena",
        "ryzove rezance",
    ],
}

RELATED_SUBJECT_ALIASES = {
    "kimchi": ("kimchi", "kimci"),
    "sushi": ("sushi", "susi", "sushi ryza", "susi ryza"),
    "gochujang": ("gochujang", "gochu jang", "gochuang"),
    "ramen": ("ramen", "ramyun", "ramyeon"),
    "kari": ("kari", "curry"),
}

SPECIAL_PRODUCT_QUERIES = {
    "mild": [
        "mochi",
        "kokosove mlieko",
        "jazminova ryza",
        "ryzove rezance",
        "miso pasta",
        "mirin",
    ],
    "hot": [
        "sambal oelek extra hot",
        "sriracha",
        "cili pasta",
        "gochujang",
        "cervena cili paprika",
    ],
    "vegan_fish_sauce_replacement": [
        "sojova omacka",
        "tamari",
        "hubova vegetarianska omacka",
        "bezlepkova sojova omacka",
    ],
    "kids_snack": [
        "pocky",
        "mochi",
        "ryzove krekry",
        "bubble tea",
    ],
}

SPECIAL_PRODUCT_EXCLUDE_TERMS = {
    "mild": ("spicy", "hot", "cili", "chilli", "paliv", "angry", "wasabi"),
    "vegan_fish_sauce_replacement": (
        "box",
        "dressing",
        "flastick",
        "flast",
        "miska",
        "misky",
        "nadoba",
        "doza",
        "davkovac",
        "obal",
    ),
    "kids_snack": ("spicy", "hot", "cili", "chilli", "paliv", "angry", "wasabi", "soju", "sake", "alkohol"),
}

FAQ_INTENT_MARKERS = (
    "kredit",
    "doprava",
    "doruc",
    "objednav",
    "plat",
    "kartou",
    "hotovost",
    "vyzdvih",
    "reklamac",
    "vraten",
)

RELATED_INTENT_MARKERS = (
    "co k",
    "suvisiace",
    "hodi",
    "hodia",
    "vyrob",
    "priprav",
    "ingredien",
    "surovin",
    "potrebujem",
    "recept",
    "urobit",
    "spravit",
)

ALLERGEN_INTENT_MARKERS = (
    "alerg",
    "alergen",
    "bez soj",
    "bez soja",
    "bezlepk",
    "obsahuje",
    "neobsahuje",
    "neznasam",
    "intoler",
    "celiak",
    "celiaki",
    "zlozen",
)

ALLERGEN_TERMS = {
    "soja": "sóju",
    "soj": "sóju",
    "lepok": "lepok",
    "gluten": "lepok",
    "arasid": "arašidy",
    "orech": "orechy",
    "mlieko": "mlieko",
    "lakto": "laktózu",
    "vajc": "vajcia",
    "sezam": "sezam",
    "ryb": "ryby",
    "makky": "mäkkýše",
    "krev": "krevety",
}

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
    client_key = get_client_key(request)
    enforce_rate_limit(client_key)

    knowledge_matches = search_knowledge(knowledge, chat_request.message)

    allergen_term = detect_allergen_intent(chat_request.message)
    if allergen_term:
        log_question(chat_request.message, client_key, 0)
        return {
            "answer": allergen_safety_answer(allergen_term),
            "products": [],
            "knowledge": knowledge_summary(knowledge_matches),
            "intent": "allergen_safety",
        }

    faq_answer = best_faq_answer(knowledge_matches)
    if faq_answer and is_faq_intent(chat_request.message):
        log_question(chat_request.message, client_key, 0)
        return {
            "answer": faq_answer,
            "products": [],
            "knowledge": knowledge_summary(knowledge_matches),
            "intent": "faq",
        }

    special_subject = detect_special_product_subject(chat_request.message)
    related_subject = detect_related_subject(chat_request.message)
    if special_subject:
        matches = special_products_for_subject(products, special_subject, chat_request.limit)
    elif related_subject:
        matches = related_products_for_subject(products, related_subject, chat_request.limit)
    else:
        matches = search_products(products, chat_request.message, chat_request.limit)
    log_question(chat_request.message, client_key, len(matches))

    if not matches and not knowledge_matches:
        return {
            "answer": "Nenašiel som presný produkt. Skúste napísať názov, značku alebo kategóriu trochu inak.",
            "products": [],
        }

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.debug("No OPENAI_API_KEY set, using fallback answer.")
        return {
            "answer": fallback_answer(matches, knowledge_matches, related_subject),
            "products": matches,
            "knowledge": knowledge_summary(knowledge_matches),
            "intent": "related_products" if related_subject else "product_search",
        }

    try:
        client = OpenAI(api_key=api_key)
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Si nákupný asistent pre Foodland.sk. Odpovedaj po slovensky, krátko a prakticky. "
                        "Voláš sa Foodland poradca. Neprezentuj sa ako AI. "
                        "Používaj iba poskytnutý kontext: produkty, FAQ, recepty, cross-sell, alternatívy a Products_AI. "
                        "Pri produktoch uvádzaj cenu a odkaz, ak sú dostupné. Pri alergiách, zložení a dostupnosti "
                        "odporuč overiť detail produktu. Nevymýšľaj ceny, sklad ani vlastnosti produktu."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Otázka zákazníka: {chat_request.message}\n\n"
                        f"Relevantné produkty:\n{products_context(matches)}\n\n"
                        f"Foodland Knowledge:\n{knowledge_context(knowledge_matches)}"
                    ),
                },
            ],
        )
        answer_text = response.choices[0].message.content or fallback_answer(
            matches,
            knowledge_matches,
            related_subject,
        )
        logger.info("OpenAI response generated.")
        return {
            "answer": answer_text,
            "products": matches,
            "knowledge": knowledge_summary(knowledge_matches),
            "intent": "related_products" if related_subject else "product_search",
        }
    except Exception as exc:
        logger.error("OpenAI API failed: %s", exc, exc_info=True)
        log_backend_error("openai_response_failed", str(exc))
        return {
            "answer": fallback_answer(matches, knowledge_matches),
            "products": matches,
            "knowledge": knowledge_summary(knowledge_matches),
            "warning": "Odpoveď sa nepodarilo vygenerovať, zobrazujem nájdené produkty.",
        }


def get_client_key(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(client_key: str) -> None:
    limit = int(os.getenv("RATE_LIMIT_PER_MINUTE", "1000"))
    now = time.time()
    window_start = now - 60
    events = rate_limit_events[client_key]

    while events and events[0] < window_start:
        events.popleft()

    if len(events) >= limit:
        logger.warning("Rate limit exceeded.")
        raise HTTPException(
            status_code=429,
            detail="Príliš veľa otázok za krátky čas. Skúste to prosím o chvíľu.",
        )

    events.append(now)


def log_question(message: str, client_key: str, matches_count: int) -> None:
    path = Path(os.getenv("ANALYTICS_LOG_PATH", "data/question_analytics.jsonl"))
    salt = os.getenv("ANALYTICS_SALT", "")
    record = {
        "ts": int(time.time()),
        "client_hash": hashlib.sha256(f"{salt}:{client_key}".encode("utf-8")).hexdigest()[:24],
        "message": message[:1000],
        "matches_count": matches_count,
    }
    if os.getenv("ANALYTICS_INCLUDE_IP", "false").lower() == "true":
        record["ip"] = client_key
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error("Failed to log question: %s", exc, exc_info=True)


def log_backend_error(event: str, detail: str) -> None:
    path = Path(os.getenv("ERROR_LOG_PATH", "data/backend_errors.jsonl"))
    record = {
        "ts": int(time.time()),
        "event": event,
        "detail": detail[:1000],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error("Failed to log backend error: %s", exc, exc_info=True)


def is_faq_intent(message: str) -> bool:
    normalized_message = normalize(message)
    return any(marker in normalized_message for marker in FAQ_INTENT_MARKERS)


def detect_special_product_subject(message: str) -> str | None:
    normalized_message = normalize(message)
    if "snack" in normalized_message and any(marker in normalized_message for marker in ("det", "dieta", "deti")):
        return "kids_snack"
    if "rybi" in normalized_message and "omack" in normalized_message and any(
        marker in normalized_message for marker in ("vegan", "vegans", "nahrad", "alternativ")
    ):
        return "vegan_fish_sauce_replacement"
    if "nepaliv" in normalized_message or "jemne" in normalized_message:
        return "mild"
    if any(marker in normalized_message for marker in ("extra paliv", "velmi paliv", "najpaliv")):
        return "hot"
    return None


def detect_related_subject(message: str) -> str | None:
    normalized_message = normalize(message)
    if not any(marker in normalized_message for marker in RELATED_INTENT_MARKERS):
        return None

    for subject, aliases in RELATED_SUBJECT_ALIASES.items():
        if any(alias in normalized_message for alias in aliases):
            return subject

    return None


def detect_allergen_intent(message: str) -> str | None:
    normalized_message = normalize(message)
    gluten_free_product_search = (
        "bezlepk" in normalized_message
        or "bez lepku" in normalized_message
        or "bezlepkova" in normalized_message
    )
    if gluten_free_product_search and not any(
        marker in normalized_message
        for marker in ("alerg", "alergen", "intoler", "celiak", "obsahuje", "neobsahuje", "zlozen")
    ):
        return None

    if gluten_free_product_search and any(
        phrase in normalized_message
        for phrase in ("sojova omacka", "sojovu omacku", "sojovka", "tamari")
    ):
        return None

    if not any(marker in normalized_message for marker in ALLERGEN_INTENT_MARKERS):
        return None

    for term, label in ALLERGEN_TERMS.items():
        if term in normalized_message:
            return label

    if "alerg" in normalized_message or "alergen" in normalized_message:
        return "alergény"

    return None


def allergen_safety_answer(allergen_term: str) -> str:
    if allergen_term == "alergény":
        return (
            "Pri alergénoch vám nechcem odporučiť nesprávny produkt. "
            "Prosím overte zloženie v detaile konkrétneho produktu alebo nám napíšte názov produktu, "
            "ktorý chcete skontrolovať."
        )

    return (
        f"Pri alergii alebo intolerancii na {allergen_term} vám nechcem odporučiť produkt len podľa názvu. "
        "Prosím overte zloženie a alergény v detaile konkrétneho produktu. "
        "Ak mi pošlete názov produktu, pomôžem vám nájsť jeho detail na Foodland.sk."
    )


def related_products_for_subject(products: list[Product], subject: str, limit: int) -> list[dict]:
    subject_query = normalize(subject)
    seen: set[str] = set()
    recommendations: list[dict] = []

    for query in RELATED_PRODUCT_QUERIES.get(subject, []):
        for product in search_products(products, query, 3):
            title = normalize(product.get("title", ""))
            title_tokens = set(title.split())
            if subject == "sushi" and "ryza" in title_tokens and {"sushi", "susi"} & title_tokens:
                continue
            if subject in {"kimchi", "gochujang"} and subject_query and subject_query in title:
                continue

            key = product.get("id") or product.get("link") or product.get("title")
            if not key or key in seen:
                continue

            seen.add(key)
            recommendations.append(product)
            if len(recommendations) >= limit:
                return recommendations

    return recommendations


def special_products_for_subject(products: list[Product], subject: str, limit: int) -> list[dict]:
    seen: set[str] = set()
    recommendations: list[dict] = []
    excluded_terms = SPECIAL_PRODUCT_EXCLUDE_TERMS.get(subject, ())

    for query in SPECIAL_PRODUCT_QUERIES.get(subject, []):
        for product in search_products(products, query, 5):
            title = normalize(product.get("title", ""))
            if excluded_terms and any(term in title for term in excluded_terms):
                continue

            key = product.get("id") or product.get("link") or product.get("title")
            if not key or key in seen:
                continue

            seen.add(key)
            recommendations.append(product)
            if len(recommendations) >= limit:
                return recommendations

    return recommendations


def fallback_answer(
    matches: list[dict],
    knowledge_matches: dict | None = None,
    related_subject: str | None = None,
) -> str:
    knowledge_matches = knowledge_matches or {}
    faq_answer = best_faq_answer(knowledge_matches)
    if faq_answer and not matches:
        return faq_answer

    if matches:
        count = min(len(matches), 5)
        if related_subject:
            return f"Našiel som {count} súvisiacich produktov a surovín, ktoré sa hodia k téme {related_subject}."
        if knowledge_matches:
            return f"Našiel som {count} vhodných produktov a doplnil som odporúčania z Foodland poradcu."
        return f"Našiel som {count} vhodných produktov. Pozrite si odporúčania nižšie."

    if knowledge_matches:
        return "Našiel som súvisiace informácie vo Foodland poradcovi."

    return "Nenašiel som presnú odpoveď. Skúste otázku napísať trochu inak."


@app.on_event("startup")
async def start_feed_refresh_loop() -> None:
    global feed_refresh_task
    refresh_minutes = int(os.getenv("FEED_REFRESH_MINUTES", "0"))
    if refresh_minutes > 0:
        logger.info("Starting feed refresh loop every %s minutes.", refresh_minutes)
        feed_refresh_task = asyncio.create_task(feed_refresh_loop(refresh_minutes))


@app.on_event("shutdown")
async def stop_feed_refresh_loop() -> None:
    if feed_refresh_task:
        logger.info("Stopping feed refresh loop.")
        feed_refresh_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await feed_refresh_task


async def feed_refresh_loop(refresh_minutes: int) -> None:
    while True:
        await asyncio.sleep(refresh_minutes * 60)
        try:
            await asyncio.wait_for(asyncio.to_thread(refresh_feed), timeout=60)
        except asyncio.TimeoutError:
            logger.error("Feed refresh timeout.")


def refresh_feed() -> None:
    global products, last_feed_refresh_at, last_feed_refresh_error
    try:
        logger.info("Refreshing feed.")
        refreshed_products = load_products()
        if refreshed_products:
            products = refreshed_products
            last_feed_refresh_at = int(time.time())
            last_feed_refresh_error = None
            logger.info("Feed refreshed successfully: %s products.", len(products))
        else:
            logger.warning("Feed refresh returned no products.")
    except Exception as exc:
        last_feed_refresh_error = str(exc)
        logger.error("Feed refresh failed: %s", exc, exc_info=True)


@app.post("/admin/reload-feed")
def reload_feed(x_admin_token: str | None = Header(default=None)) -> dict:
    token = os.getenv("ADMIN_RELOAD_TOKEN")
    if not token:
        raise HTTPException(status_code=403, detail="Admin reload is disabled.")
    if x_admin_token != token:
        logger.warning("Invalid admin reload token attempt.")
        raise HTTPException(status_code=401, detail="Invalid admin token.")

    logger.info("Manual feed reload requested.")
    refresh_feed()
    return {"status": "reloaded", "products": len(products)}
