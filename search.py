from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
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


class UTF8StaticFiles(StaticFiles):
    ALLOWED_SUFFIXES = {".css", ".html", ".ico", ".js", ".json", ".map", ".txt"}
    CHARSET_BY_SUFFIX = {
        ".css": "text/css; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".map": "application/json; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
    }

    def file_response(self, full_path, stat_result, scope, status_code=200):
        suffix = Path(full_path).suffix.lower()
        if suffix not in self.ALLOWED_SUFFIXES:
            raise HTTPException(status_code=404, detail="Static file not found.")

        response = super().file_response(full_path, stat_result, scope, status_code)
        content_type = self.CHARSET_BY_SUFFIX.get(suffix)
        if content_type:
            response.headers["content-type"] = content_type
        return response


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
    "pho": [
        "ryzove rezance",
        "rybacia omacka",
        "sriracha",
        "hoisin",
        "mung fazulove klicky",
    ],
    "pad_thai": [
        "ryzove rezance",
        "tamarind",
        "rybacia omacka",
        "arasidy",
        "pad thai omacka",
    ],
    "bibimbap": [
        "gochujang",
        "sezamovy olej",
        "kimchi",
        "jazminova ryza",
    ],
    "gyoza": [
        "sojova omacka",
        "ryzovy ocot",
        "chilli olej",
    ],
}

RELATED_SUBJECT_ALIASES = {
    "kimchi": ("kimchi", "kimci"),
    "sushi": ("sushi", "susi", "sushi ryza", "susi ryza"),
    "gochujang": ("gochujang", "gochu jang", "gochuang"),
    "ramen": ("ramen", "ramyun", "ramyeon"),
    "kari": ("kari", "curry"),
    "pho": ("pho",),
    "pad_thai": ("pad thai", "padthai"),
    "bibimbap": ("bibimbap",),
    "gyoza": ("gyoza",),
}

SPECIAL_PRODUCT_QUERIES = {
    "gluten_free_sushi": [
        "bezlepkova sojova omacka",
        "tamari",
        "nori",
        "sushi ryza",
        "wasabi",
        "nakladany zazvor",
    ],
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
    "asian_sweets": [
        "mochi",
        "ryzove krekry",
        "pocky",
        "kokosove cukriky",
    ],
    "dairy_replacement": [
        "sezamovy olej",
        "kokosove mlieko",
        "miso pasta",
    ],
    "fermented_sour": [
        "kimchi",
        "nakladany zazvor",
        "tamarind",
    ],
    "rice_vinegar": [
        "ryzovy ocot",
        "rice vinegar",
        "ocot sushi",
    ],
    "asian_noodles": [
        "ryzove rezance",
        "udon",
        "ramen rezance",
    ],
    "rice_side": [
        "jazminova ryza",
        "sushi ryza",
        "basmati ryza",
    ],
    "vegan_asian": [
        "tofu",
        "nori",
        "ryzove rezance",
        "kokosove mlieko",
    ],
    "no_pork_asian": [
        "tofu",
        "nori",
        "wakame",
        "ryzove rezance",
    ],
    "medium_spicy": [
        "sriracha",
        "gochujang",
        "chilli olej",
    ],
    "korean_paste": [
        "gochujang",
        "ssamjang",
    ],
    "tamari": [
        "tamari",
        "bezlepkova sojova omacka",
    ],
    "safe_snack": [
        "mochi",
        "pocky",
        "ryzove krekry",
    ],
    "safe_sauce": [
        "sojova omacka",
        "tamari",
        "hoisin",
    ],
    "plain_rice": [
        "jazminova ryza",
        "sushi ryza",
    ],
    "sushi_condiments": [
        "nori",
        "wasabi",
        "nakladany zazvor",
    ],
    "tofu_seaweed": [
        "tofu",
        "nori",
        "wakame",
    ],
}

SPECIAL_PRODUCT_EXCLUDE_TERMS = {
    "gluten_free_sushi": (
        "flastick",
        "flast",
        "miska",
        "misky",
        "nadoba",
        "doza",
        "davkovac",
        "obal",
        "box",
    ),
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
    "asian_sweets": ("spicy", "hot", "cili", "chilli", "paliv", "angry", "wasabi", "soju", "sake", "alkohol"),
    "dairy_replacement": ("dezert", "cukrik", "snack", "cokolad"),
    "fermented_sour": ("polievk", "lemonade", "cukrik", "krekry", "forma", "noznice", "miska"),
    "vegan_asian": ("caj", "kava", "napoj", "dzus", "cukrik", "snack", "box", "filter"),
    "no_pork_asian": ("caj", "kava", "napoj", "dzus", "cukrik", "snack", "box", "filter"),
    "medium_spicy": ("rezance", "chips", "cipsy", "curry", "kari pasta", "sladk"),
    "korean_paste": ("rezance", "snack", "rolky", "omacka na morske", "caj", "dzus"),
    "safe_snack": ("spicy", "hot", "cili", "chilli", "paliv", "angry", "wasabi", "soju", "sake", "alkohol"),
    "safe_sauce": ("rybacia", "arasid"),
    "plain_rice": ("ocot", "ryzovar", "vinegar"),
    "sushi_condiments": ("ryza", "rice"),
    "tofu_seaweed": ("bravc", "kurac", "maso"),
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
    "kupit",
    "varit",
    "odporuc",
    "doplnky",
    "recept",
    "urobit",
    "spravit",
    "nakupny zoznam",
    "nesmie",
    "chybat",
    "robim",
)

RECIPE_INTENT_MARKERS = (
    "recept",
    "navod",
    "postup",
    "ako spravim",
    "ako pripravim",
    "ako urobim",
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
    "vegan",
    "celiak",
    "celiaki",
    "lakto",
    "vhodn",
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

ALLERGEN_TERMS.update(
    {
        "soja": "soju",
        "soj": "soju",
        "arasid": "arasidy",
        "lakto": "laktozu",
        "makky": "makkyse",
        "vegan": "vhodnost pre veganov",
    }
)

OUT_OF_DOMAIN_MARKERS = (
    "bicykl",
    "notebook",
    "opravujete telefon",
    "poistenie auta",
    "pocasie",
    "basen",
    "letenk",
    "prack",
    "stavebn",
    "danov",
    "taxik",
    "taxi",
    "liek",
    "predpis",
    "akcie",
    "burz",
    "hypotek",
    "nahradne diely",
    "diely do auta",
    "krmivo",
    "psov",
    "psa",
    "lekar",
    "lekara",
    "zdravotn",
    "diagnoz",
    "jedalnick",
)

app = FastAPI(title="Foodland AI Agent", version="0.1.0")
app.mount("/static", UTF8StaticFiles(directory=Path(__file__).parent), name="static")

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
        allergen_matches = allergen_product_matches(chat_request.message, chat_request.limit)
        log_question(chat_request.message, client_key, len(allergen_matches))
        return {
            "answer": allergen_safety_answer(allergen_term),
            "products": allergen_matches,
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

    recipe_subject = detect_recipe_subject(chat_request.message)
    if recipe_subject:
        log_question(chat_request.message, client_key, 0)
        return {
            "answer": recipe_answer(recipe_subject, knowledge_matches),
            "products": [],
            "knowledge": knowledge_summary(knowledge_matches),
            "intent": "recipe",
        }

    if detect_out_of_domain(chat_request.message):
        log_question(chat_request.message, client_key, 0)
        return {
            "answer": "Na toto neviem spoľahlivo odpovedať ako Foodland poradca. Skúste sa opýtať na produkty, objednávku, dopravu alebo platbu na Foodland.sk.",
            "products": [],
            "knowledge": knowledge_summary(knowledge_matches),
            "intent": "unknown",
        }

    special_subject = detect_special_product_subject(chat_request.message)
    related_subject = detect_related_subject(chat_request.message)
    needs_composition_caution = is_composition_caution_search(chat_request.message)
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
            "answer": fallback_answer(matches, knowledge_matches, related_subject, needs_composition_caution),
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
                        f"Foodland Knowledge:\n{knowledge_context(knowledge_matches)}\n\n"
                        f"Bezpečnostná poznámka: {composition_caution_context(needs_composition_caution)}"
                    ),
                },
            ],
        )
        answer_text = response.choices[0].message.content or fallback_answer(
            matches,
            knowledge_matches,
            related_subject,
            needs_composition_caution,
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
            "answer": fallback_answer(matches, knowledge_matches, related_subject, needs_composition_caution),
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


def detect_recipe_subject(message: str) -> str | None:
    normalized_message = normalize(message)
    if not any(marker in normalized_message for marker in RECIPE_INTENT_MARKERS):
        return None

    for subject, aliases in RELATED_SUBJECT_ALIASES.items():
        if any(alias in normalized_message for alias in aliases):
            return subject

    return "general"


def recipe_answer(subject: str, knowledge_matches: dict | None = None) -> str:
    if subject == "kimchi":
        return (
            "Recept na zakladne kimchi: nakrajajte cinsku kapustu, poriadne ju nasolte a nechajte 1-2 hodiny zmaknut. "
            "Potom ju oplachnite a zmiesajte s pastou z gochugaru alebo cili, cesnaku, zazvoru, rybacej omacky, "
            "trochy cukru a ryzovej kase z ryzovej muky. Pridat mozete jarne cibulky alebo mrkvu. "
            "Natlačte do pohara, nechajte 1-2 dni fermentovat pri izbovej teplote a potom skladujte v chladnicke. "
            "Ak chcete nakupny zoznam, napiste: suroviny na kimchi."
        )

    recipes = (knowledge_matches or {}).get("Recipes", [])
    if recipes:
        record = recipes[0].get("record", {})
        recipe_name = next((str(value) for key, value in record.items() if "Recept" in key and value), "")
        if recipe_name:
            return (
                f"Nasiel som recept: {recipe_name}. "
                "Ak chcete, mozem k nemu doplnit aj nakupny zoznam produktov z Foodlandu."
            )

    return (
        "Receptovu otazku som zachytil, ale nemam dost detailov na presny recept. "
        "Skuste napisat nazov jedla, napriklad: recept na kimchi alebo recept na pad thai."
    )


def detect_special_product_subject(message: str) -> str | None:
    normalized_message = normalize(message)
    if (is_gluten_free_search(normalized_message) or "celiak" in normalized_message) and bool(
        {"sushi", "susi"} & set(normalized_message.split())
    ):
        return "gluten_free_sushi"
    if "ryz" in normalized_message and "ocot" in normalized_message and any(
        marker in normalized_message for marker in ("nie ocot", "nie ryzovar")
    ):
        return "plain_rice"
    if "sushi" in normalized_message and "dopln" in normalized_message and any(
        marker in normalized_message for marker in ("nie dalsie balenia ryze", "nie ryz")
    ):
        return "sushi_condiments"
    if ("paliv" in normalized_message or "pikant" in normalized_message) and any(
        marker in normalized_message for marker in ("nie sladke", "cukrik")
    ):
        return "medium_spicy"
    if ("tofu" in normalized_message or "rias" in normalized_message) and "nie maso" in normalized_message:
        return "tofu_seaweed"
    if "gochu jang" in normalized_message or "gochudzang" in normalized_message or "gochudang" in normalized_message:
        return "korean_paste"
    if "coconat milk" in normalized_message or "coconut milk" in normalized_message:
        return "dairy_replacement"
    if "kokos" in normalized_message and "mlieko" in normalized_message and "kari" in normalized_message:
        return "dairy_replacement"
    if any(marker in normalized_message for marker in ("extra paliv", "velmi paliv", "najpaliv")):
        return "hot"
    if "pikant" in normalized_message and any(marker in normalized_message for marker in ("nie extrem", "nie velmi", "mierne")):
        return "medium_spicy"
    if "rice vinegar" in normalized_message or ("ryzov" in normalized_message and "ocot" in normalized_message):
        return "rice_vinegar"
    if ("tamari" in normalized_message or "tamary" in normalized_message) and (
        "sojov" in normalized_message or "bezlepk" in normalized_message or "namiesto" in normalized_message
    ):
        return "tamari"
    if "bezlepk" in normalized_message and "sojov" in normalized_message and "omack" in normalized_message:
        return "tamari"
    if "korejsk" in normalized_message and "past" in normalized_message:
        return "korean_paste"
    if "vegan" in normalized_message and any(marker in normalized_message for marker in ("azij", "europsk", "jedl")):
        return "vegan_asian"
    if "bravcov" in normalized_message and any(marker in normalized_message for marker in ("azij", "jedl", "bez")):
        return "no_pork_asian"
    if "sladkost" in normalized_message or (
        "snack" in normalized_message
        and any(marker in normalized_message for marker in ("azij", "cokolad", "europsk"))
        and "omack" not in normalized_message
    ):
        return "asian_sweets"
    if "mochi" in normalized_message and "ryz" in normalized_message:
        return "asian_sweets"
    if "snack" in normalized_message and any(marker in normalized_message for marker in ("nic paliv", "alkohol", "wasabi")):
        return "safe_snack"
    if "omack" in normalized_message and "nie rybac" in normalized_message:
        return "safe_sauce"
    if any(marker in normalized_message for marker in ("masla", "maslo", "smotany", "smotana")) and any(
        marker in normalized_message for marker in ("namiesto", "nahrad", "dochuten")
    ):
        return "dairy_replacement"
    if any(marker in normalized_message for marker in ("smotanov", "kravskym mliekom", "kravske mlieko")) and any(
        marker in normalized_message for marker in ("kokos", "azij", "varenia", "kari")
    ):
        return "dairy_replacement"
    if "ferment" in normalized_message or ("kysl" in normalized_message and "kapust" in normalized_message):
        return "fermented_sour"
    if any(marker in normalized_message for marker in ("psenic", "talianske cestoviny", "cestoviny")) and any(
        marker in normalized_message for marker in ("nahrad", "nechcem", "nesedia")
    ):
        return "asian_noodles"
    if "zemiak" in normalized_message and "ryz" in normalized_message:
        return "rice_side"
    if "snack" in normalized_message and any(marker in normalized_message for marker in ("det", "dieta", "deti")):
        return "kids_snack"
    if "rybi" in normalized_message and "omack" in normalized_message and any(
        marker in normalized_message for marker in ("vegan", "vegans", "nahrad", "alternativ")
    ):
        return "vegan_fish_sauce_replacement"
    if "nepaliv" in normalized_message or "jemne" in normalized_message:
        return "mild"
    return None


def detect_related_subject(message: str) -> str | None:
    normalized_message = normalize(message)
    if is_gluten_free_search(normalized_message):
        return None

    if not any(marker in normalized_message for marker in RELATED_INTENT_MARKERS):
        return None

    for subject, aliases in RELATED_SUBJECT_ALIASES.items():
        if any(alias in normalized_message for alias in aliases):
            return subject

    if normalized_message.strip() in {
        "na vyrobu",
        "na pripravu",
        "ingrediencie",
        "suroviny",
        "co na vyrobu",
        "co treba na vyrobu",
        "co potrebujem na vyrobu",
    }:
        return "kimchi"

    return None


def detect_allergen_intent(message: str) -> str | None:
    normalized_message = normalize(message)
    if "rybi" in normalized_message and "omack" in normalized_message and any(
        marker in normalized_message for marker in ("vegan", "vegans", "nahrad", "alternativ")
    ):
        return None
    if ("celiak" in normalized_message or "vhodn" in normalized_message) and any(
        term in normalized_message for term in ("bez lepku", "bezlepk", "celiak")
    ):
        return "lepok"
    if "vegan" in normalized_message and any(
        marker in normalized_message for marker in ("je ", " su ", "vhodn", "vlastnost", "zlozen")
    ):
        return "vhodnost pre veganov"
    if "lepk" in normalized_message and any(marker in normalized_message for marker in ("tamari", "bezpec", "pri lepk")):
        return "lepok"
    gluten_free_product_search = is_gluten_free_search(normalized_message)
    asks_if_gluten_free = gluten_free_product_search and (
        re.search(r"\b(je|su|mate|obsahuje)\b.*\bbez lepku\b", normalized_message) is not None
    )
    if asks_if_gluten_free:
        return "lepok"

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

    if "intoler" in normalized_message or "zlozen" in normalized_message:
        return "alergeny"

    if "alerg" in normalized_message or "alergen" in normalized_message:
        return "alergény"

    return None


def detect_out_of_domain(message: str) -> bool:
    normalized_message = normalize(message)
    return any(marker in normalized_message for marker in OUT_OF_DOMAIN_MARKERS)


def allergen_product_matches(message: str, limit: int) -> list[dict]:
    query = allergen_product_query(message)
    if not query:
        return []
    return search_products(products, query, limit)


def allergen_product_query(message: str) -> str:
    normalized_message = normalize(message)
    if "bez soj" in normalized_message or "bez soja" in normalized_message:
        return ""
    if "gochu jang" in normalized_message or "gochudzang" in normalized_message or "gochudang" in normalized_message:
        return "gochujang"

    known_product_queries = (
        "bezlepkova sojova omacka",
        "sushi ryza",
        "gochujang",
        "kimchi",
        "tamari",
        "miso pasta",
        "miso",
        "kokosove mlieko",
        "sezamovy olej",
        "ryzovy ocot",
        "nori",
        "wakame",
        "tofu",
        "sriracha",
        "ramen",
        "ramyun",
        "udon",
        "panko",
        "ssamjang",
        "sambal",
        "hoisin",
        "sojova omacka",
        "rybacia omacka",
        "ryzove rezance",
        "ryzovy papier",
        "mochi",
        "wasabi",
    )
    for product_query in known_product_queries:
        if product_query in normalized_message:
            return product_query

    after_question = message.rsplit("?", 1)[-1].strip()
    if after_question and after_question != message.strip():
        return after_question

    cleanup_patterns = [
        r"\bviete mi najst\b",
        r"\bdobry den\b",
        r"\bahoj\b",
        r"\bprosim\b",
        r"\bmoze to jest\b",
        r"\balergik na arasidy\b",
        r"\balergia na arasidy\b",
        r"\bs alergiou na arasidy\b",
        r"\bje\b",
        r"\bsu\b",
        r"\bma\b",
        r"\bbez lepku\b",
        r"\bbezlepk\w*\b",
        r"\bobsahuje\b",
        r"\bneobsahuje\b",
        r"\balergeny\b",
        r"\bvegan\b",
        r"\bvhodn\w*\b",
        r"\bpri celiakii\b",
        r"\bceliak\w*\b",
        r"\bintoleranc\w*\b",
        r"\bco mam skontrolovat\b",
        r"\bskontrolovat\b",
        r"\bukazte produkt\b",
        r"\boverte etiketu\b",
        r"\betiketu\b",
        r"\bnechcem vymyslene vlastnosti\b",
        r"\bnehadajte\b",
        r"\bupozornite ma na zlozenie\b",
        r"\bchcem opatrnu odpoved\b",
        r"\bopatrnu odpoved\b",
        r"\bsoju\b",
        r"\bsoja\b",
        r"\blepok\b",
        r"\bskladom\b",
        r"\bza dobru cenu\b",
    ]
    cleaned = normalized_message
    for pattern in cleanup_patterns:
        cleaned = re.sub(pattern, " ", cleaned)
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", cleaned)
    return " ".join(cleaned.split())


def is_gluten_free_search(message_or_normalized: str) -> bool:
    normalized_message = normalize(message_or_normalized)
    return (
        "bezlepk" in normalized_message
        or "bez lepku" in normalized_message
        or "bezlepkova" in normalized_message
    )


def is_composition_caution_search(message: str) -> bool:
    normalized_message = normalize(message)
    return is_gluten_free_search(normalized_message) or any(
        marker in normalized_message for marker in ("zlozen", "obsahuje", "neobsahuje")
    )


def composition_caution_context(needs_composition_caution: bool) -> str:
    if not needs_composition_caution:
        return "Nie je potrebná."
    return "Pri bezlepkových otázkach alebo otázkach na zloženie odporuč overiť zloženie v detaile produktu."


def allergen_safety_answer(allergen_term: str) -> str:
    if allergen_term == "alergény":
        return (
            "Pri alergénoch vám nechcem odporučiť nesprávny produkt. "
            "Prosím overte zloženie v detaile konkrétneho produktu alebo nám napíšte názov produktu, "
            "ktorý chcete skontrolovať."
        )

    return (
        f"Pri alergii alebo intolerancii na {allergen_term} vám nechcem odporučiť produkt len podľa názvu. "
        "Prosím overte zloženie a alergény v detaile konkrétneho produktu. Ak riešite konkrétny produkt, rozhodujúca je etiketa. "
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
            break

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
            break

    return recommendations


def fallback_answer(
    matches: list[dict],
    knowledge_matches: dict | None = None,
    related_subject: str | None = None,
    needs_composition_caution: bool = False,
) -> str:
    knowledge_matches = knowledge_matches or {}
    faq_answer = best_faq_answer(knowledge_matches)
    if faq_answer and not matches:
        return faq_answer

    if matches:
        count = min(len(matches), 5)
        caution = (
            " Pri bezlepkových produktoch alebo otázkach na zloženie si prosím overte zloženie v detaile produktu."
            if needs_composition_caution
            else ""
        )
        if related_subject:
            return f"Našiel som {count} súvisiacich produktov a surovín, ktoré sa hodia k téme {related_subject}.{caution}"
        if knowledge_matches:
            return f"Našiel som {count} vhodných produktov a doplnil som odporúčania z Foodland poradcu.{caution}"
        return f"Našiel som {count} vhodných produktov. Pozrite si odporúčania nižšie.{caution}"

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
