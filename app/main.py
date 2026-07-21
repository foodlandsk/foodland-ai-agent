from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import random
import re
import secrets
import tempfile
import time
from collections import Counter, defaultdict, deque
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openai import OpenAI, APIConnectionError, APITimeoutError, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from pydantic import BaseModel, Field

from app.feed import (
    Product,
    load_multilang_feeds,
    load_products_json,
    multilang_translation_index,
    parse_google_merchant_feed,
)
from app.knowledge import (
    best_faq_answer,
    knowledge_context,
    knowledge_summary,
    load_knowledge_json,
    search_knowledge,
)
from app.knowledge_builder import (
    ProductSnapshot,
    build_knowledge,
    build_product_snapshot,
    save_knowledge,
)
from app.search import autocomplete_suggestions, normalize, products_context, search_products, tokenize
from app.workflows import products_to_cart_candidates


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
    conversation_history: list[dict] = Field(default_factory=list)
    session_id: str = Field(default="", max_length=64)
    client_id: str = Field(default="", max_length=96)


class ProductSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)
    limit: int = Field(default=8, ge=1, le=30)


class ProductSuggestRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=120)
    limit: int = Field(default=8, ge=1, le=12)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)


class MemoryClearRequest(BaseModel):
    client_id: str = Field(default="", max_length=96)


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
# Knowledge-builder state
product_snapshot: ProductSnapshot = build_product_snapshot(products)
translation_index: dict[str, dict[str, "Product"]] = {}
rate_limit_events: dict[str, deque[float]] = defaultdict(deque)
_RATE_LIMIT_MAX_CLIENTS = 50_000  # BUG-02: ochrana pamate – max pocet trackovanych klientov
DEFAULT_RUNTIME_LOG_DIR = Path(tempfile.gettempdir()) / "foodland-ai-agent"
SESSION_MEMORY_TTL_SECONDS = int(os.getenv("SESSION_MEMORY_TTL_SECONDS", "1800"))
SESSION_MEMORY_MAX_SESSIONS = int(os.getenv("SESSION_MEMORY_MAX_SESSIONS", "20000"))
USER_MEMORY_ENABLED = os.getenv("USER_MEMORY_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
USER_MEMORY_MAX_PROFILES = int(os.getenv("USER_MEMORY_MAX_PROFILES", "50000"))
session_memories: dict[str, dict] = {}
user_memories: dict[str, dict] | None = None

RELATED_PRODUCT_QUERIES = {
    "cesnak": [
        "sojova omacka",
        "sezamovy olej",
        "miso pasta",
        "gochujang",
        "chili omacka",
        "hoisin omacka",
    ],
    "nakladany_zazvor": [
        "sushi ryza",
        "nori",
        "wasabi",
        "sojova omacka",
        "ryzovy ocot",
    ],
    "nuoc_cham": [
        "rybacia omacka",
        "ryzovy papier",
        "sweet chili omacka",
        "sriracha",
        "lime",
    ],
    "arasidovy_olej": [
        "sezamovy olej",
        "sojova omacka",
        "sriracha",
        "hoisin omacka",
        "chili omacka",
    ],
    "koriander": [
        "citronova trava",
        "rybacia omacka",
        "kokosove mlieko",
        "sweet chili omacka",
        "gochujang",
    ],
    "ssamjang": [
        "gochujang",
        "doenjang",
        "sezamove semienka",
        "sezamovy olej",
        "hovadzie maso",
    ],
    "mung_fazula": [
        "sojova omacka",
        "sezamovy olej",
        "rybacia omacka",
        "tofu",
        "koriander",
    ],
    "agar_agar": [
        "kokosove mlieko",
        "matcha",
        "tapiokove perly",
        "ryzova muka",
        "kondenzovane mlieko",
    ],
    "bambusove_vyhanky": [
        "sojova omacka",
        "sezamovy olej",
        "ustricova omacka",
        "shiitake",
        "tofu",
    ],
    "vodne_kastany": [
        "sojova omacka",
        "sezamovy olej",
        "ustricova omacka",
        "tofu",
        "bambusove vyhanky",
    ],
    "ryzove_rezance": [
        "rybacia omacka",
        "sojova omacka",
        "sriracha",
        "kokosove mlieko",
        "sweet chili omacka",
    ],
    "sklenene_rezance": [
        "sojova omacka",
        "sezamovy olej",
        "rybacia omacka",
        "gochujang",
        "shiitake",
    ],
    "shichimi_togarashi": [
        "sushi ryza",
        "ramen",
        "udon",
        "sezamovy olej",
        "sojova omacka",
    ],
    "furikake": [
        "jazminova ryza",
        "sushi ryza",
        "nori",
        "sezamove semienka",
        "sojova omacka",
    ],
    "kewpie": [
        "sojova omacka",
        "sriracha",
        "gochujang",
        "sezamovy olej",
        "nori",
    ],
    "mentsuyu": [
        "dashi",
        "sojova omacka",
        "mirin",
        "ramen",
        "udon",
    ],
    "natto": [
        "jazminova ryza",
        "sojova omacka",
        "nori",
        "sezamove semienka",
        "wasabi",
    ],
    "okonomiyaki": [
        "panko strobanka",
        "katsuobushi",
        "nori",
        "kewpie",
        "sojova omacka",
    ],
    "pandan": [
        "kokosove mlieko",
        "ryzova muka",
        "kondenzovane mlieko",
        "matcha",
        "agar agar",
    ],
    "lychee": [
        "kokosove mlieko",
        "matcha",
        "tapiokove perly",
        "kondenzovane mlieko",
        "jasminovy caj",
    ],
    "taro": [
        "kokosove mlieko",
        "ryzova muka",
        "matcha",
        "tapiokove perly",
        "kondenzovane mlieko",
    ],
    "hokkien_rezance": [
        "sojova omacka",
        "sezamovy olej",
        "ustricova omacka",
        "sriracha",
        "miso pasta",
    ],
    "kombu": [
        "dashi",
        "miso pasta",
        "sojova omacka",
        "mirin",
        "sake na varen",
    ],
    "yakiniku": [
        "sojova omacka",
        "mirin",
        "sezamovy olej",
        "cesnak",
        "gochujang",
    ],
    "omurice": [
        "jazminova ryza",
        "sojova omacka",
        "kuraci bujon",
        "mirin",
        "ketchup",
    ],
    "chahan": [
        "jazminova ryza",
        "sojova omacka",
        "sezamovy olej",
        "kuraci bujon",
        "mirin",
    ],
    "kimchi_recipe": [
        "gochugaru",
        "gochujang",
        "rybacia omacka",
        "ryzova muka",
        "cervena cili paprika",
        "sezamovy olej",
        "sojova omacka",
        "nakladana kapusta",
    ],
    "ryzovy_ocot": [
        "sushi ryza",
        "nori",
        "wasabi",
        "sojova omacka",
        "sezamovy olej",
        "nakladany zazvor",
    ],
    "kimchi": [
        "ramen",
        "jazminova ryza",
        "sezamovy olej",
        "gochujang",
        "tofu",
        "kimchi",
    ],
    "sushi": [
        "nori",
        "ryzovy ocot",
        "wasabi",
        "nakladany zazvor",
        "sojova omacka",
        "bezlepkova sojova omacka",
    ],
    "gochujang": [
        "kimchi",
        "sezamovy olej",
        "jazi,nova ryza",
        "sushi ryza",
        "ramen",
        "sojova omacka",
        "gochugaru",
    ],
    "ramen": [
        "ramen rezance",
        "dashi", "bonito",
        "miso pasta",
        "bambusove vyhonky",
        "nori",
        "wakame",
        "sojova omacka", "sezamovy olej",
        "sriracha", "gochujang",
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
        "korenie na pho", "pho korenie",
        "badián", "skorica",
        "bujón",
        "banh pho", "pho rezance", "ryzove rezance",
        "hovadzi bujón", "kuraci bujón",
        "rybacia omacka",
        "koriander", "mung fazulove klicky",
        "hoisin", "sriracha",
        "jazminovy caj", "zeleny caj",
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
        "ssamjang",
        "doenjang",
        "sezamovy olej",
        "sezamove semienka",
        "kimchi",
        "jazminova ryza",
    ],
    "gyoza": [
        "sojova omacka",
        "ryzovy ocot",
        "chilli olej",
    ],
    "poke_bowl": [
        "sushi ryza",
        "nori",
        "sojova omacka",
        "sezamovy olej",
        "wasabi",
        "nakladany zazvor",
    ],
    "korejsky_gril": [
        "gochujang",
        "ssamjang",
        "sezamovy olej",
        "kimchi",
        "sojova omacka",
    ],
    "thajske_kari": [
        "kokosove mlieko",
        "rybacia omacka",
        "kari pasta cervena",
        "jazminova ryza",
        "sriracha",
    ],
    "sojova_omacka": [
        "mirin",
        "ryzovy ocot",
        "hoisin omacka",
        "sezamovy olej",
        "dashi",
    ],
    "wok": [
        "ustricova omacka",
        "sojova omacka",
        "sezamovy olej",
        "sriracha",
        "thajska cili stir-fry omacka",
    ],
    "beginner_kit": [
        "sojova omacka",
        "sezamovy olej",
        "ryzovy ocot",
        "jazminova ryza",
        "ramen rezance",
        "sriracha",
    ],
    "azijske_dezerty": [
        "pocky",
        "mochi",
        "bubble tea",
        "ryzove krekry",
        "kokosove cukriky",
    ],
    "jarne_zavitky": [
        "ryzovy papier",
        "ryzove rezance",
        "sweet chili omacka",
        "rybacia omacka",
        "sriracha",
    ],
    "teriyaki": [
        "sojova omacka",
        "mirin",
        "ryzovy ocot",
        "sezamovy olej",
        "jazminova ryza",
    ],
    "miso_polievka": [
        "miso pasta",
        "dashi",
        "tofu",
        "wakame",
        "nori",
    ],
    "fried_rice": [
        "sojova omacka",
        "sezamovy olej",
        "ustricova omacka",
        "jazminova ryza",
        "sriracha",
    ],
    "bulgogi": [
        "sojova omacka",
        "sezamovy olej",
        "gochugaru",
        "kimchi",
        "jazminova ryza",
    ],
    "tteokbokki": [
        "gochujang",
        "gochugaru",
        "sezamovy olej",
        "sojova omacka",
        "rybacia omacka",
    ],
    "tom_yum": [
        "tom yum pasta",
        "citronova trava",
        "galangal",
        "kaffirove listy",
        "kokosove mlieko",
        "rybacia omacka",
        "sriracha",
    ],
    "japchae": [
        "sklenene rezance",
        "dangmyeon",
        "sojova omacka",
        "sezamovy olej",
        "sezamove semienka",
        "gochujang",
    ],
    "vietnamska_kuchyna": [
        "rybacia omacka",
        "ryzove rezance",
        "sriracha",
        "hoisin omacka",
        "pho rezance",
    ],
    "japonska_kuchyna": [
        "sojova omacka",
        "mirin",
        "dashi",
        "wasabi",
        "sushi ryza",
    ],
    "korejska_kuchyna": [
        "gochujang",
        "sezamovy olej",
        "kimchi",
        "ssamjang",
        "jazminova ryza",
    ],
    "thajska_kuchyna": [
        "kokosove mlieko",
        "rybacia omacka",
        "sriracha",
        "kari pasta cervena",
        "ryzove rezance",
    ],
    "cinska_kuchyna": [
        "sojova omacka",
        "ustricova omacka",
        "sezamovy olej",
        "ramen rezance",
    ],
    "pad_thai": [
        "ryzove rezance",
        "rybacia omacka",
        "tamarind",
        "arasidy",
        "sriracha",
    ],
    "tempura": [
        "tempura muka",
        "sojova omacka",
        "wasabi",
        "nakladany zazvor",
        "ryzovy ocot",
    ],
    "okonomiyaki": [
        "sojova omacka",
        "sezamovy olej",
        "gochujang",
        "miso pasta",
    ],
    "takoyaki": [
        "sojova omacka",
        "ponzu",
        "sezamovy olej",
        "morske riasy",
    ],
    "shabu_shabu": [
        "sojova omacka",
        "sezamovy olej",
        "dashi",
        "miso pasta",
        "gochujang",
    ],
    "onigiri": [
        "sushi ryza",
        "nori",
        "sojova omacka",
        "sezamove semienka",
        "nakladany zazvor",
    ],
    "yakisoba": [
        "yakisoba",
        "yakisoba omacka",
        "sojova omacka",
        "sezamovy olej",
        "ustricova omacka",
        "sriracha",
    ],
    "beginner_kit": [
        "sojova omacka",
        "sezamovy olej",
        "ryzovy ocot",
        "sriracha",
        "mirin",
        "dashi",
        "kokosove mlieko",
        "rybacia omacka",
    ],
    "udon": [
        "dashi",
        "sojova omacka",
        "mirin",
        "nori",
        "tofu",
    ],
    "soba": [
        "sojova omacka",
        "mirin",
        "dashi",
        "nori",
        "wasabi",
    ],
    "mandu": [
        "sojova omacka",
        "sezamovy olej",
        "ryzovy ocot",
        "zazvor",
        "gochujang",
    ],
    "wonton": [
        "sojova omacka",
        "sezamovy olej",
        "ustricova omacka",
        "zazvor",
    ],
    "laksa": [
        "kokosove mlieko",
        "rybacia omacka",
        "ryzove rezance",
        "sojova omacka",
    ],
    "banh_mi": [
        "rybacia omacka",
        "ryzovy ocot",
        "nakladany zazvor",
        "sojova omacka",
        "sriracha",
    ],
    "congee": [
        "sojova omacka",
        "sezamovy olej",
        "dashi",
        "miso pasta",
        "zazvor",
    ],
    "matcha": [
        "matcha prah",
        "smetana",
        "mlieko",
        "sladidlo",
        "zeleny caj",
    ],
    "mochi": [
        "mochiko",
        "ryzova muka",
        "kokosove mlieko",
        "cukrovy praskovy",
        "sezamove semienka",
    ],
    "bubble_tea": [
        "tapiokove perly",
        "caj",
        "kokosove mlieko",
        "kondenzovane mlieko",
        "cierny caj",
    ],
    "edamame": [
        "sojova omacka",
        "morska sol",
        "sezamovy olej",
        "wasabi",
    ],
    "tonkatsu": [
        "panko",
        "tonkatsu omacka",
        "sojova omacka",
        "sezamovy olej",
        "ryzovy ocot",
    ],
    "agedashi_tofu": [
        "tofu",
        "dashi",
        "sojova omacka",
        "mirin",
        "katsuobushi",
    ],
    "nori_rolky": [
        "nori",
        "sushi ryza",
        "ryzovy ocot",
        "wasabi",
        "nakladany zazvor",
        "sojova omacka",
    ],
    "dashi_vyvar": [
        "dashi",
        "katsuobushi",
        "kombu",
        "sojova omacka",
        "mirin",
    ],
    "grilovanie": [
        "sojova omacka",
        "gochujang",
        "teriyaki omacka",
        "sezamovy olej",
        "sriracha",
    ],
    "asian_snack": [
        "ryzove krekry",
        "pocky",
        "mochi",
        "edamame",
        "nori snack",
    ],
    "tom_yum": [
        "kokosove mlieko",
        "rybacia omacka",
        "citronova trava",
        "sriracha",
        "sojova omacka",
    ],
    "tom_kha": [
        "kokosove mlieko",
        "citronova trava",
        "galangal",
        "kaffirove listy",
        "rybacia omacka",
        "sriracha",
    ],
    "jjigae": [
        "gochujang",
        "doenjang pasta",
        "tofu",
        "sojova omacka",
        "sezamovy olej",
        "dashi",
    ],
    "nam_van": [
        "ryzovy papier",
        "rybacia omacka",
        "ryzove rezance",
        "sojova omacka",
        "sezamovy olej",
    ],
    "sukiyaki": [
        "sojova omacka",
        "mirin",
        "sake",
        "sezamovy olej",
        "tofu",
        "dashi",
    ],
    "bao_bun": [
        "sojova omacka",
        "sezamovy olej",
        "ustricova omacka",
        "hoisin omacka",
        "gochujang",
    ],
    "gyudon": [
        "sojova omacka",
        "mirin",
        "dashi",
        "ryzovy ocot",
    ],
    "oyakodon": [
        "sojova omacka",
        "mirin",
        "dashi",
        "sake",
    ],
    "karaage": [
        "sojova omacka", "sake", "zazvor", "cesnak", "sezamovy olej", "mirin",
    ],
    "tonkatsu": [
        "sojova omacka", "tonkatsu omacka", "panko", "sezamovy olej", "cesnak",
    ],
    "gyoza": [
        "sojova omacka", "ryzovy ocot", "sezamovy olej", "zazvor", "cesnak",
    ],
    "yakitori": [
        "sojova omacka", "mirin", "sake", "sezamovy olej", "cesnak",
    ],
    "adobo": [
        "sojova omacka", "ryzovy ocot", "sezamovy olej", "cesnak", "kokosove mlieko",
    ],
    "malatang": [
        "sojova omacka", "sezamovy olej", "tofu", "ryzove rezance", "gochujang",
    ],
    "jajangmyeon": [
        "sojova omacka", "sezamovy olej", "ryzove rezance", "ustricova omacka",
    ],
    "bento": [
        "sojova omacka", "mirin", "nori", "sezamovy olej", "ryzovy ocot",
    ],
    "yangnyeom_chicken": [
        "gochujang", "sojova omacka", "ryzovy ocot", "cesnak", "zazvor", "sezamovy olej",
    ],
    "samgyeopsal": [
        "sojova omacka", "sezamovy olej", "gochujang", "ryzovy ocot", "sesam",
    ],
    "bun_bo_nam_bo": [
        "ryzove rezance", "rybacia omacka", "hoisin", "sezamovy olej", "arasidy", "citronova trava",
    ],
    "bun_cha": [
        "ryzove rezance", "rybacia omacka", "ryzovy ocot", "cesnak", "chili omacka", "arasidy",
    ],
    "thit_dong": [
        "rybacia omacka", "shiitake huby", "susene huby", "sojova omacka", "chili omacka",
    ],
    "bun_bo_hue": [
        "rybacia omacka", "ryzove rezance", "citronova trava", "sojova omacka", "sriracha",
    ],
    "banh_gio": [
        "ryzova muka", "rybacia omacka", "sojova omacka", "shiitake", "chili omacka",
    ],
    "banh_xeo": [
        "ryzova muka", "kokosove mlieko", "rybacia omacka", "sriracha",
    ],
    "mapo_tofu": [
        "tofu", "gochujang", "sojova omacka", "sezamovy olej", "cesnak", "zazvor",
    ],
    "kung_pao": [
        "sojova omacka", "ryzovy ocot", "sezamovy olej", "zazvor", "cesnak", "sriracha",
    ],
    "dim_sum": [
        "siu mai",
        "dim sum krevetove",
        "dim sum kuracie",
        "hoisin omacka",
        "sojova omacka",
        "chili olej",
        "sezamovy olej",
    ],
    "dakgalbi": [
        "gochujang", "sojova omacka", "sezamovy olej", "ryzovy ocot",
    ],
    "char_siu": [
        "sojova omacka", "hoisin omacka", "sezamovy olej", "ryzovy ocot", "cesnak",
    ],
    "som_tam": [
        "rybacia omacka", "ryzovy ocot", "sriracha", "sojova omacka",
    ],
    "nasi_goreng": [
        "sojova omacka", "sezamovy olej", "rybacia omacka", "sriracha",
    ],
    "mee_goreng": [
        "sojova omacka", "sezamovy olej", "rybacia omacka", "sriracha", "ustricova omacka",
    ],
    "rendang": [
        "kokosove mlieko", "citronova trava", "sojova omacka", "kari pasta",
    ],
    "larb": [
        "rybacia omacka", "ryzovy ocot", "sriracha", "sezamovy olej",
    ],
    "chow_mein": [
        "sojova omacka", "sezamovy olej", "ustricova omacka", "ryzove rezance",
    ],
    "satay": [
        "sojova omacka", "kari pasta", "kokosove mlieko", "sriracha", "sezamovy olej",
    ],
    "khao_pad": [
        "sojova omacka", "rybacia omacka", "sezamovy olej", "sriracha",
    ],
    "crying_tiger": [
        "sojova omacka", "rybacia omacka", "sriracha", "ryzovy ocot",
    ],
    "banchan": [
        "gochujang", "sojova omacka", "sezamovy olej", "ryzovy ocot",
    ],
    "dubu_jorim": [
        "tofu", "gochujang", "sojova omacka", "sezamovy olej",
    ],
    "haemul_pajeon": [
        "sojova omacka", "ryzovy ocot", "sezamovy olej", "gochujang",
    ],
    "gimbap": [
        "nori", "sushi ryza", "sojova omacka", "sezamovy olej", "ryzovy ocot",
    ],
    "tangsu_yuk": [
        "sojova omacka", "ryzovy ocot", "sezamovy olej", "gochujang",
    ],
    "hainanese_chicken": [
        "sojova omacka", "sezamovy olej", "zazvor", "cesnak",
    ],
    "mango_sticky_rice": [
        "lepkava ryza", "kokosove mlieko", "mango", "sezamove semienka",
    ],
    "sesame_balls": [
        "ryzova muka", "sezamove semienka", "kokosove mlieko", "matcha",
    ],
    "tikka_masala": [
        "garam masala", "kari pasta", "kokosove mlieko", "jazminova ryza",
    ],
    "tandoori": [
        "tandoori masala", "garam masala", "kari pasta", "jazminova ryza",
    ],
    "biryani": [
        "basmati ryza", "biryani masala", "garam masala", "kardamom", "skorica",
    ],
    "nasi_lemak": [
        "kokosove mlieko", "jazminova ryza", "sambal", "arasidy", "rybacia omacka",
    ],
    "singapore_noodles": [
        "ryzove rezance", "kari korenie", "sojova omacka", "sezamovy olej", "sriracha",
    ],
    "sinigang": [
        "sinigang", "tamarind koncentrat", "tamarind pasta", "rybacia omacka", "ryzove rezance",
    ],
    "yukgaejang": [
        "gochujang", "sojova omacka", "sezamovy olej", "ryzovy ocot",
    ],
    "bossam": [
        "gochujang", "sojova omacka", "sezamovy olej", "kimchi",
    ],
    "wakame": [
        "miso pasta", "tofu", "sojova omacka", "nori", "ryzovy ocot", "sezamovy olej",
    ],
    "dashi": [
        "kombu", "katsuobushi", "bonito vlocky", "shiitake houby",
        "miso pasta", "sojova omacka", "rybacia omacka",
    ],
    "spring_roll": [
        "ryzovy papier", "rice paper", "ryzove vermicelli", "sladkokyselka",
        "sojova omacka", "sezamovy olej", "chili omacka", "koriander",
    ],
    "ryza": [
        "ryzovy ocot", "sojova omacka", "miso pasta", "sezamovy olej",
        "nori", "furikake", "kimchi", "tofu",
    ],
    "kokos": [
        "kari pasta cervena", "kari pasta zelena", "rybacia omacka",
        "jazminova ryza", "sriracha", "lemongrass", "tamarind",
    ],
    "mirin": [
        "sojova omacka", "sake", "ryzovy ocot", "dashi",
        "ginger", "cesnak", "sezamovy olej",
    ],
    "chili": [
        "sriracha", "gochujang", "sambal oelek", "chili olej",
        "thajske chili", "chili pasta",
    ],
    "nori": [
        "sushi ryza", "ryzovy ocot", "wasabi", "sojova omacka",
        "sezamovy olej", "furikake",
    ],
    "rybacia_omacka": [
        "sojova omacka", "tamari", "miso pasta",
        "bezlepkova sojova omacka", "kokosove aminokyseliny",
    ],
    "special_occasion": [
        "sushi ryza", "nori", "wasabi", "ryzovy ocot",
        "sojova omacka", "sezamovy olej", "jazminova ryza",
    ],
    "wasabi": [
        "wasabi", "sojova omacka", "ryzovy ocot", "nori", "sushi ryza",
    ],
    "sezamovy_olej": [
        "sojova omacka", "ryzovy ocot", "mirin", "gochujang", "hoisin",
        "sezamove semienka", "toasted sesame seeds",
    ],
    "ponzu": [
        "ponzu", "sojova omacka", "ryzovy ocot", "mirin", "yuzu",
    ],
    "potsticker": [
        "sojova omacka", "chili olej", "ryzovy ocot",
        "sezamovy olej", "gochujang", "sriracha",
    ],
    "sriracha": [
        "sriracha", "gochujang", "chili omacka", "chili olej",
    ],
    "hoisin": [
        "hoisin omacka", "sezamovy olej", "sojova omacka", "ustricova omacka",
    ],
    "ustricova_omacka": [
        "ustricova omacka", "sojova omacka", "sezamovy olej", "sriracha",
    ],
    "sojova_omacka": [
        "sojova omacka", "tamari", "mirin", "ryzovy ocot",
    ],
    "tamarind": [
        "tamarind pasta", "rybacia omacka", "kokosove mlieko", "hnedy cukor",
    ],
    "tofu": [
        "tofu", "sojova omacka", "sezamovy olej", "miso pasta", "gochujang",
    ],
    "losos": [
        "teriyaki omacka", "wasabi", "sojova omacka", "sezamovy olej", "zazvor",
    ],
    "kuraci": [
        "teriyaki omacka", "sojova omacka", "sezamovy olej", "gochujang", "karaage",
    ],
    "ryba": [
        "rybacia omacka", "sweet chili omacka", "wasabi", "sojova omacka", "citronova trava",
    ],
    "hovadzie": [
        "teriyaki omacka", "sojova omacka", "sezamovy olej", "gochujang", "hoisin omacka",
    ],
    "kreveta": [
        "sweet chili omacka", "sojova omacka", "sriracha", "citronova trava", "wasabi",
    ],
    "panko": [
        "panko strobanka", "teriyaki omacka", "tonkatsu omacka", "sojova omacka", "karaage",
    ],
    "sake": [
        "mirin", "ryzovy ocot", "sojova omacka", "dashi", "sake na varen",
    ],
    "shiitake": [
        "sojova omacka", "sezamovy olej", "miso pasta", "dashi", "oyster sauce",
    ],
    "lotus_root": [
        "sojova omacka", "ryzovy ocot", "sezamovy olej", "dashi", "mirin", "sezamove semienka",
    ],
    "cierne_hriby": [
        "sojova omacka", "sezamovy olej", "ustricova omacka", "cesnak", "zazvor", "wok omacka",
    ],
    "ryzova_muka": [
        "kokosove mlieko", "pandan", "tapiokove perly", "mango", "cukrovy sirup", "sezamove semienka",
    ],
    "tapiokove_perly": [
        "zeleny caj", "matcha", "kokosove mlieko", "med", "ovocny sirup", "bubble tea",
    ],
    "sezamova_pasta": [
        "sezamovy olej", "sojova omacka", "ryzovy ocot", "cesnak", "gochujang", "miso pasta",
    ],
    "zeleny_caj": [
        "matcha", "med", "citron", "sencha", "japonsky caj", "zeleny caj", "sojove mlieko",
    ],
    "cierny_caj": [
        "med", "citron", "chai", "caj", "mliecne mlieko", "cierny caj",
    ],
    "oolong": [
        "med", "matcha", "zeleny caj", "sencha", "caj",
    ],
    "kondenzovane_mlieko": [
        "bubble tea", "tapiokove perly", "kokosove mlieko", "mango", "ovocny sirup", "matcha",
    ],
}

RELATED_SUBJECT_ALIASES = {
    "kimchi_recipe": ("vyrobu kimchi", "kimchi ingrediencie", "kimchi recept", "kimchi navod", "spravit kimchi", "pripravit kimchi", "urobim kimchi", "kimchi suroviny", "ako vyrob kimchi"),
    "kimchi": ("kimchi", "kimci"),
    "sushi": ("sushi", "susi", "sushi ryza", "susi ryza", "maki", "maki rolky", "california roll", "futomaki", "hosomaki", "uramaki", "nigiri", "temaki", "sashimi"),
    "gochujang": ("gochujang", "gochu jang", "gochuang", "gochugaru", "korean chili flakes", "koreanska cili"),
    "ramen": ("ramen", "ramyun", "ramyeon", "tonkotsu", "tantanmen", "noodle soup", "noodle broth", "soup noodles", "nudl", "nudle", "nudlov"),
    "kari": ("kari", "curry"),
    "pho": ("pho",),
    "pad_thai": ("pad thai", "padthai", "pad-thai", "pad tai", "pat thai"),
    "bibimbap": ("bibimbap",),
    "gyoza": ("gyoza", "gyozu", "gyozy", "gyozou"),
    "poke_bowl": ("poke bowl", "poke", "poke boul"),
    "korejsky_gril": ("korejsky gril", "korejsky bbq", "korejsky barbecue", "kbbq", "korean bbq", "korejsku barbecue", "korejskeho grilu", "korejskeho bbq", "korejsky grill"),
    "thajske_kari": ("thajske kari", "thajske curry", "thajsky curry", "thajskeho curry", "thai curry", "thajskemu kari", "thajskeho kari", "thajskou kari", "thajskej kari"),
    "sojova_omacka": ("sojovej omacke", "k sojovej omacke", "doplnky k sojovej", "sojova omacka", "sojov", "soja sos", "soy sauce"),
    "wok": ("woku", "wok", "stir fry", "stir-fry", "na woku", "smaz", "smazit", "smazenie", "vysmaz"),
    "beginner_kit": ("zacinam azijsky", "zacinam varit azijsky", "zacinam s azijskou", "azijska spajza", "co si kupit ako prv", "zacinam varit", "prvy krat azij", "prvy krat varit azij", "krat korejsk", "krat japonsk", "krat thajsk", "krat cinsk", "azijsk", "azijskeho", "azijsku kuchyn", "azijske jedlo", "azijsku vecer", "nieco azij", "nejake azij", "asian", "east asian", "southeast asian", "spicy asian", "vegetarian asian", "vegan asian", "asijsk", "asijsku", "asijskej",
        "azijsk", "azijsku", "azijskej", "azia", "azii", "azijsky"),
    "azijske_dezerty": ("azijske dezerty", "azijsky dezert", "na dezert", "dezert ky"),
    "jarne_zavitky": ("jarne zavitky", "spring rolls", "jarnych zavitkov", "jarne rolky", "nemecke zavitky", "jarnym zavinkom", "jarneho zavitku", "jarnych zavinkov", "jarne zaviny", "jarny zavitok", "jarneho zavitka", "spring roll"),
    "teriyaki": ("teriyaki", "teriyaki kuracie", "teriyaki losos", "teriyaki omacku"),
    "miso_polievka": ("miso", "miso polievku", "miso polievka", "miso soup", "miso sopu", "miso polevku", "miso polievky", "miso polievke"),
    "fried_rice": ("fried rice", "smazena ryza", "vysmazena ryza", "ryza na panvici", "vyprazana ryza", "vyprazanu ryzu", "smazenu ryzu", "smaza ryzu", "smazim ryzu", "rice dish", "rice bowl", "rice meal"),
    "bulgogi": ("bulgogi", "galbi", "galby", "galbi jjim"),
    "tteokbokki": ("tteokbokki", "ddukbokki", "tteok", "dduk"),
    "tom_yum": ("tom yum", "tom yam", "tom kha", "citronova trava", "lemongrass", "galangal", "kaffirove listy", "kaffir lime"),
    "japchae": ("japchae", "jap chae", "korejske sklenene rezance"),
    "vietnamska_kuchyna": ("vietnamsku kuchynu", "vietnamska kuchyna", "vietnamska vecera", "vietnam", "vietnamsk"),
    "japonska_kuchyna": ("japonsku kuchynu", "japonska kuchyna", "japonska vecera", "japonsku veceru", "japonsk", "japansk", "japanese", "j-food", "j food"),
    "korejska_kuchyna": ("korejsku kuchynu", "korejska kuchyna", "korejska vecera", "korejsku veceru", "korejsk", "korean", "k-food", "k food"),
    "thajska_kuchyna": ("thajsku kuchynu", "thajska kuchyna", "thajska vecera", "thajsku veceru", "thajsk", "thai"),
    "cinska_kuchyna": ("cinsku kuchynu", "cinska kuchyna", "cinska vecera", "cinsku veceru", "cinsk", "chinese"),
    "pad_thai": ("pad thai", "padthai", "pad-thai", "pad tai", "pat thai"),
    "tempura": ("tempura", "tempuru", "tempury", "tempurou", "tempur"),
    "okonomiyaki": ("okonomiyaki",),
    "takoyaki": ("takoyaki",),
    "shabu_shabu": ("shabu shabu", "shabu-shabu", "hot pot", "hotpot", "hot-pot", "hot potu", "hotpotu"),
    "onigiri": ("onigiri", "ryżové gulky", "ryzove gulky", "ryzove gulky", "onigiri"),
    "yakisoba": ("yakisoba", "yaki soba", "yakisobu", "yaki sobu", "yakisoby", "yakisobe"),
    "udon": ("udon", "udonom", "udonove nudle", "udonovu polievku"),
    "soba": ("soba", "soba nudle", "soba rezance", "sobove nudle"),
    "mandu": ("mandu",),
    "wonton": ("wonton", "wonton soup", "wontonova polievka"),
    "laksa": ("laksa",),
    "banh_mi": ("banh mi",),
    "congee": ("congee", "ryzova kasa", "ryzovu kasu"),
    "matcha": ("matcha", "matche", "matchu", "matchou", "matchom", "matcha latte", "matcha tea"),
    "mochi": ("mochi",),
    "bubble_tea": ("bubble tea", "boba", "boba tea", "bubble tea", "bubbletea", "boba drink", "bubble drink"),
    "edamame": ("edamame",),
    "tonkatsu": ("tonkatsu",),
    "agedashi_tofu": ("agedashi tofu", "agedashi",),
    "nori_rolky": ("nori rolky", "nori wrap", "nori sheet"),
    "dashi_vyvar": ("dashi vyvar", "dashi vyvaru", "dashi polievka"),
    "japansk": ("japanske ranajky", "japanska snidana"),
    "grilovanie": ("grilovacku", "grilovat", "grilovanie", "na gril", "grilu", "grilovacky"),
    "asian_snack": ("k filmu", "k serialu", "na film", "na serial", "k pivu azij", "snack azij"),
    "tom_yum": ("tom yum", "tom yum polievka", "thajska polievka", "thajskej polievky", "tom yum soup", "citronova trava", "lemongrass", "galangal", "kaffirove listy", "kaffir lime"),
    "tom_kha": ("tom kha", "tom kha gai", "kokosova kuracia polievka", "thajska kokosova polievka"),
    "jjigae": ("jjigae", "sundubu jjigae", "sundubu", "doenjang jjigae", "doenjang", "korejsky stew"),
    "nam_van": ("nam van", "goi cuon", "vietnamske rolky", "cerstve rolky"),
    "sukiyaki": ("sukiyaki",),
    "bao_bun": ("bao bun", "bao", "baozi", "parovany bun", "parovane buchty"),
    "gyudon": ("gyudon", "hovaezi don", "beef bowl"),
    "oyakodon": ("oyakodon", "oyako don"),
    "karaage": ("karaage",),
    "tonkatsu": ("tonkatsu",),
    "gyoza": ("gyoza", "gyozu", "gyozy", "gyozou", "gyoze", "gyozam", "jiaozi"),
    "yakitori": ("yakitori",),
    "adobo": ("adobo", "filipino adobo"),
    "malatang": ("malatang", "mala tang", "mala hotpot"),
    "jajangmyeon": ("jajangmyeon", "jajangmyon", "black bean noodles"),
    "asian_noodles": ("asian noodles", "asian noodle", "stir fry noodles"),
    "medium_spicy": ("spicy food", "hot food", "spicy dinner", "spicy meal", "pikantne jedlo", "horuce jedlo", "hot sauce", "chili sauce", "sriracha dinner", "spicy", "pikantne"),
    "bento": ("bento", "bento box", "bento lunch", "benta", "bente", "do benta", "bent"),
    "yangnyeom_chicken": ("yangnyeom chicken", "yangnyeom", "chimaek", "korean fried chicken", "korean chicken"),
    "samgyeopsal": ("samgyeopsal", "pork belly"),
    "bun_bo_nam_bo": ("bun bo nam bo", "bun bo nam", "vietnamsky hovadzi salat", "hovadzi salat s rezancami", "bun bo juh"),
    "bun_cha": ("bun cha", "bún chả"),
    "bun_bo_hue": ("bun bo hue", "bun bo"),
    "banh_gio": ("banh gio", "bánh giò", "parene pyramídove knedliky", "parene pyramidove knedliky"),
    "banh_xeo": ("banh xeo",),
    "mapo_tofu": ("mapo tofu", "mapo"),
    "kung_pao": ("kung pao", "kung pao chicken"),
    "dim_sum": ("dim sum", "dimsum", "dumpling", "dumplingy", "dumplingom", "plnene testo"),
    "dakgalbi": ("dakgalbi",),
    "char_siu": ("char siu", "char-siu", "cinsky bbq"),
    "som_tam": ("som tam", "som tum", "papajovy salat"),
    "nasi_goreng": ("nasi goreng",),
    "mee_goreng": ("mee goreng", "mi goreng"),
    "rendang": ("rendang",),
    "larb": ("larb",),
    "chow_mein": ("chow mein", "chowmein", "chow-mein"),
    "satay": ("satay", "sate", "satay kura"),
    "mango_sticky_rice": ("mango sticky rice", "lepkava ryza s mangom", "sladka lepkava ryza"),
    "sesame_balls": ("sezamove gulocky", "banh ran", "bánh rán"),
    "tikka_masala": ("tikka masala", "murgh makhani", "maslove kura"),
    "tandoori": ("tandoori", "tandoori masala"),
    "biryani": ("biryani", "kuracie biryani"),
    "nasi_lemak": ("nasi lemak",),
    "singapore_noodles": ("singapurske rezance", "singapore noodles"),
    "sinigang": ("sinigang", "filipinska kysla polievka"),
    "thit_dong": ("thit dong", "thit ong", "vietnamska huspenina", "huspenina"),
    "khao_pad": ("khao pad",),
    "crying_tiger": ("crying tiger",),
    "banchan": ("banchan", "korejske prilohy"),
    "dubu_jorim": ("dubu jorim",),
    "haemul_pajeon": ("haemul pajeon", "pajeon", "korejske palacinky"),
    "gimbap": ("gimbap", "kimbap"),
    "tangsu_yuk": ("tangsu yuk", "tangsu"),
    "hainanese_chicken": ("hainanese chicken", "hainanese rice", "hainan chicken"),
    "yukgaejang": ("yukgaejang",),
    "bossam": ("bossam",),
    "wakame": ("wakame", "wakamy", "wakamu", "wakamom"),
    "dashi": ("dashi", "dashi vyvar", "dashi stock", "dashi buljon", "dashiho", "bonito", "bonito vlocky", "katsuobushi"),
    "spring_roll": ("spring roll", "spring rollu", "spring rollom", "spring rollov", "jarny zavin", "jarneho zavinu", "rice paper", "ryzovy papier"),
    "ryza": ("ryzu", "ryzou", "ryzy", "ryze", "ryzi", "jasminovu ryzu", "jasminovej", "jasminov", "basmati", "sushi ryzu", "bielu ryzu"),
    "kokos": ("kokosov", "kokosove", "kokosoveho", "kokosovym", "kokosove mlieko", "coconut", "kokosova smotana", "kokosova smetan"),
    "mirin": ("mirin", "mirine", "mirinom", "mirinu"),
    "rybacia_omacka": ("rybacia omacka", "rybacou omackou", "rybaci omacku", "rybac", "fish sauce", "nuoc mam", "nuoc nam"),
    "chili": ("chili", "chilli", "chili omacka", "chili paste", "chili paprika", "chili sauce"),
    "nori": ("nori", "nori list", "nori listov", "nori sheets", "nori sheet"),
    "wasabi": ("wasabi", "wasabi pasta", "wasabi prasok", "wasabi omacka"),
    "sezamovy_olej": ("sezamovy olej", "sezamoveho oleja", "sezamovym olejom", "sesame oil", "sezam olej", "dark sesame", "toasted sesame", "sezamove semienka", "sezamovych semienok", "sesame seeds", "sezamovych semen"),
    "ponzu": ("ponzu", "ponzu omacku", "ponzu sauce", "ponzu shoyu", "ponzu yuzu", "yuzu"),
    "potsticker": ("potsticker", "potstickeram", "guo tie", "pot sticker", "pot-sticker"),
    "special_occasion": (
        "svadba", "svadb", "narodeninov", "narozenin", "vianoc", "silvester",
        "novy rok", "sviatok", "romantick", "specialn",
        "priatelk", "anniversary", "wedding", "birthday", "christmas",
        "new year", "date night", "valentin",
        "vikend", "nedel", "sobot", "dnes", "dnesna",
        "host", "hosti", "ludi", "clovek", "osob",
    ),
    "sriracha": ("sriracha", "sriracha omacka", "sriracha sauce", "sriracha hot sauce"),
    "hoisin": ("hoisin", "hoisin omacka", "hoisin sauce"),
    "ustricova_omacka": ("ustricova omacka", "ustricovej omacky", "oyster sauce", "ustricovou omackou"),
    "sojova_omacka": ("sojova omacka", "sojovej omacky", "sojovou omackou", "svetla soja", "tmava soja", "soy sauce", "sojou", "tamari omacka"),
    "tamarind": ("tamarind", "tamarindova pasta", "tamarind paste", "tamarindovy"),
    "tofu": ("tofu", "tofuom", "tofuovi", "firm tofu", "silk tofu", "hedvabne tofu", "silken tofu"),
    "losos": ("losos", "lososa", "lososu", "lososom", "lososovi", "salmon", "lososovy"),
    "kuraci": ("kuraci", "kuracie", "kuraciemu", "kurace", "kuracim", "kuracom", "kuraciom", "chicken", "kure"),
    "ryba": ("ryba", "rybu", "rybe", "rybou", "ryby", "rybaci", "fish", "sea food", "seafood"),
    "hovadzie": ("hovadzie", "hovadziu", "hovadziemu", "hovadze", "beef", "hovadzeho", "hovadzinym", "hovadzimu", "steak"),
    "kreveta": ("kreveta", "krevety", "krevetam", "krevetami", "shrimp", "prawns", "garnele", "krevetove"),
    "panko": ("panko", "panko strobanka", "panko obalenie", "japanese breadcrumbs", "strobanka panko"),
    "sake": ("sake", "sake na varen", "varecke sake", "rice wine", "japanese sake", "varenie sake"),
    "shiitake": ("shiitake", "shiitake houby", "shiitake huby", "shiitake grib", "dried shiitake", "susene shiitake"),
    "ryzovy_ocot": ("ryzovy ocot", "rice vinegar", "ocot sushi", "sushi ocot", "ryzoveho octu", "ryzovym octom"),

    "cesnak": ("cesnak", "cesnakom", "cesnaku", "cesnakovy olej", "garlic", "cesnakoveho", "cesnakova"),
    "nakladany_zazvor": ("nakladany zazvor", "nakladanym zazvorom", "nakladaneho zazvoru", "pickled ginger", "sushi ginger", "gari"),
    "nuoc_cham": ("nuoc cham", "nuoc mam", "vietnamese omacka", "viet dipping", "viet sauce"),

    "arasidovy_olej": ("arasidovy olej", "arasidovym olejom", "arasidoveho oleja", "peanut oil", "groundnut oil", "arasidove maslo", "peanut butter"),
    "koriander": ("koriander", "koriandr", "coriander", "cilantro", "koriandrom", "koriandru", "koriandra"),
    "ssamjang": ("ssamjang", "ssamjangu", "ssam jang", "korean bbq paste", "koreanska omacka"),
    "mung_fazula": ("mung fazula", "mung bean", "mungove klicky", "mung fazule", "mungo fazula", "fazulove klicky"),
    "agar_agar": ("agar agar", "agar-agar", "agar", "vegan gelatin", "veganska zelatina", "agaru"),
    "bambusove_vyhanky": ("bambusove vyhanky", "bambusovych vyhankov", "bamboo shoots", "bambusove klicky", "bamboo klicky"),
    "vodne_kastany": ("vodne kastany", "vodnych kastanov", "water chestnuts", "water chestnut"),
    "ryzove_rezance": ("ryzove rezance", "ryzovych rezancov", "rice noodles", "rice vermicelli", "ryžové rezance", "pho rezance", "bun rezance"),
    "sklenene_rezance": ("sklenene rezance", "sklenych rezancov", "glass noodles", "cellophane noodles", "dangmyeon rezance", "sklenene nudle"),

    "shichimi_togarashi": ("shichimi", "shichimi togarashi", "seven spice", "japanese seven spice", "togarashi"),
    "furikake": ("furikake", "furikake korenie", "japanese rice seasoning", "rice seasoning"),
    "kewpie": ("kewpie", "kewpie majoneza", "japonska majoneza", "japanese mayo", "kewpie mayo", "kewpi"),
    "mentsuyu": ("mentsuyu", "mentsuyu omacka", "japanese dipping sauce", "tsuyu", "men tsuyu"),
    "natto": ("natto", "nattu", "natto soybeans", "fermented soybeans"),
    "okonomiyaki": ("okonomiyaki", "okonomijaki", "japanese pancake", "okonomi"),
    "pandan": ("pandan", "pandanove listy", "pandan listy", "pandan leaves", "pandanu"),
    "lychee": ("lychee", "lichi", "lichin", "litchi", "lychee ovocie"),
    "taro": ("taro", "taro koren", "taro chip", "taro root", "taro boba"),
    "hokkien_rezance": ("hokkien rezance", "hokkien noodles", "hokkien", "wheat noodles lo mein", "lo mein"),
    "kombu": ("kombu", "kombu riasy", "kelp riasy", "kombu dashi", "kombuvych", "kelp seaweed"),
    "yakiniku": ("yakiniku", "yakiniku omacka", "korean bbq", "japanese bbq", "yakiniku sauce"),
    "omurice": ("omurice", "omu rice", "japonska omeleta", "omurajisu"),
    "chahan": ("chahan", "cahan", "japanese fried rice", "yakimeshi", "yaki meshi"),
    "lotus_root": ("lotus root", "lotusovy koren", "renkon", "lotus chips", "lotusoveho korena", "lotusovym korenom"),
    "cierne_hriby": ("cierne hriby", "ciernymi hrybmi", "ciernych hrib", "wood ear", "black fungus", "mu err", "cloud ear", "drevene hriby"),
    "ryzova_muka": ("ryzova muka", "ryzovej muky", "ryzovou mukou", "rice flour", "glutinous rice flour", "lepkava ryzova muka"),
    "tapiokove_perly": ("tapiokove perly", "tapioka", "tapiocove perly", "boba perly", "tapioca pearls", "tapiokovy skrob"),
    "sezamova_pasta": ("sezamova pasta", "tahini", "sezamovej pasty", "sesame paste", "tahini pasta"),
    "zeleny_caj": ("zeleny caj", "zeleneho caju", "zelenym cajom", "green tea", "zelenemu caju"),
    "cierny_caj": ("cierny caj", "cierneho caju", "ciernym cajom", "black tea", "ciernemu caju"),
    "oolong": ("oolong", "oolong caj", "wu long", "wulong", "oolong tea"),
    "kondenzovane_mlieko": ("kondenzovane mlieko", "kondenzovaneho mlieka", "kondenzovanym mliekem", "sweetened condensed milk", "sladzene kondenzovane mlieko"),

}

ARTICLE_PRODUCT_QUERIES = {
    "kimchi_article": ["kimchi"],
    "pho_article": ["pho", "banh pho"],
    "udon_article": ["udon rezance", "udon"],
    "ramen_article": ["ramen rezance", "ramen"],
    "udon_ramen_article": ["udon rezance", "ramen rezance"],
    "tofu_article": ["tofu"],
    "shoyu_article": ["shoyu", "sojova omacka"],
    "tamari_article": ["tamari"],
    "miso_article": ["miso pasta", "miso"],
    "matcha_article": ["matcha"],
    "mochi_article": ["mochi"],
    "bubble_tea_article": ["bubble tea", "tapiokove perly"],
}

RECIPE_TITLE_PRODUCT_SUBJECTS = (
    ("pad thai", "pad_thai"),
    ("sushi a sashimi", "sushi"),
    ("satay", "satay"),
    ("tom kha", "tom_kha"),
    ("tom yum", "tom_yum"),
    ("kokosove kari", "thajske_kari"),
    ("tekvicou", "thajske_kari"),
    ("ciernej ryze", "ryza"),
    ("cierna ryza", "ryza"),
    ("lepkava ryza", "mango_sticky_rice"),
    ("mangom", "mango_sticky_rice"),
    ("pho bo", "pho"),
    ("pho ga", "pho"),
    ("banh mi", "banh_mi"),
    ("nem cuon", "nam_van"),
    ("jarne zavitky", "nam_van"),
    ("bun cha", "bun_cha"),
    ("bun bo nam bo", "bun_bo_nam_bo"),
    ("nuoc cham", "nuoc_cham"),
    ("banh gio", "banh_gio"),
    ("vietnamsky zeleninovy salat", "vietnamska_kuchyna"),
    ("rybacou omackou", "rybacia_omacka"),
    ("thit dong", "thit_dong"),
    ("thit ong", "thit_dong"),
    ("huspenina", "thit_dong"),
    ("jazminova ryza", "ryza"),
    ("banh ran", "sesame_balls"),
    ("sezamove gulocky", "sesame_balls"),
    ("kimchi ramen", "ramen"),
    ("jjigae", "jjigae"),
    ("japchae", "japchae"),
    ("kimchi recept", "kimchi_recipe"),
    ("bulgogi", "bulgogi"),
    ("kimchi prazena ryza", "fried_rice"),
    ("bibimbap", "bibimbap"),
    ("gimbap", "gimbap"),
    ("kuracie kari", "kari"),
    ("udon", "udon"),
    ("teriyaki tofu", "teriyaki"),
    ("kuromame gohan", "ryza"),
    ("yakiudon", "yakisoba"),
    ("miso polievka", "miso_polievka"),
    ("tempura", "tempura"),
    ("shoyu ramen", "ramen"),
    ("kung pao", "kung_pao"),
    ("pekingska kacica", "cinska_kuchyna"),
    ("ma po tofu", "mapo_tofu"),
    ("mapo tofu", "mapo_tofu"),
    ("suan la tang", "cinska_kuchyna"),
    ("murgh makhani", "tikka_masala"),
    ("tikka masala", "tikka_masala"),
    ("tandoori", "tandoori"),
    ("biryani", "biryani"),
    ("nasi goreng", "nasi_goreng"),
    ("mie goreng", "mee_goreng"),
    ("rendang", "rendang"),
    ("nasi lemak", "nasi_lemak"),
    ("hainanske", "hainanese_chicken"),
    ("singapurske rezance", "singapore_noodles"),
    ("sinigang", "sinigang"),
)

RECIPE_URL_OVERRIDES: dict[str, str] = {
    "bun bo nam bo": "https://www.foodland.sk/recepty/vietnamska-specialita-bun-bo-nam-bo/",
    "bun bo nam": "https://www.foodland.sk/recepty/vietnamska-specialita-bun-bo-nam-bo/",
    "vietnamsky hovadzi salat": "https://www.foodland.sk/recepty/vietnamska-specialita-bun-bo-nam-bo/",
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
    "postovn",
    "kurier",
    "packeta",
    "zasielk",
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
    "chyba",
    "chybaju",
    "treba",
    "treba kupit",
    "potrebne",
    "co este",
    "este chybat",
    "este chyba",
    "robim",
    "patri",
    "nakupujem",
    "doplnky k",
    "co k tomu",
    "zacinam",
    "dam do",
    "davam do",
    "do woku",
    "na dezert",
    "na ranajky",
    "na obed",
    "na vecer",
    "pripravujem",
    "chystam",
    "planujem",
    "co este",
    "este nieco",
    "kuchynu",
    "kuchyni",
    "jedlo",
    "veceru",
    "obed",
    "ranajky",
    "snack",
    "grilovanie",
    "grilovacku",
    "varim",
    "chcem",
    "nakupovat",
    "co dame",
    "co dat",
    "co pouzit",
    "na varenie",
    "do polievky",
    "do omacky",
    "do marinady",
    "omacku",
    "polievku",
    "na grilovanie",
    "dam",
    "skusam",
    "vyskusam",
    "chceme",
    "co pridat",
    "k recepty",
    "k receptu",
    "zvyknu",
    "hodiat",
    "co jest", "co si dat", "co dat na stol", "jest so", "jest k", "co hodia",
    "na film", "k filmu", "k serialu", "na serial", "na snack",
    "polievky", "pre vegetarianov", "pre deti", "pre alergikov",
    "vegetariansk", "bezmasov", "vegetarian", "vegan", "spicy", "gluten free",
    "dinner", "lunch", "meal", "cooking", "recipe",
    "vecer", "obedom", "ranom",
    "what do i need", "what to buy", "what goes with",
    "supplies", "party",
    "making", "tonight", "want to make", "need to make", "going to make",
    "want to cook", "going to cook", "how to make", "i make",
    "ideas", "food ideas", "dinner ideas",
    "should i", "night", "grocery", "shopping list", "items", "needed",
    "what to get", "stuff for", "things to buy", "week", "pantry",
    "dokup", "zobrat", "zoznam",
    "at home", "cook", "easy", "learn to",
    "budget", "toppings", "topping", "upgrade", "to buy",
    "sauce", "oil", "seasoning", "spice", "sides", "noodle",
    "korenie", "olej", "rezanc", "polevk", "ocot",
    "skus", "pridat",
    "serve", "pair", "side dish", "goes well",
    "podavat", "dodat", "dobavit",
    "prep", "food prep",
    "kuchyn", "veci", "potrebuj", "koupit",
    "svadba", "sviatok", "vianoc", "silvester", "novy rok",
    "romantick", "specialn", "priatelk", "co si dat", "valentin",
    "robit", "zostalo", "dochut", "poloz", "koreni", "dnes",
    "nahrad", "alternativ", "namiesto", "replacement", "substitute", "instead",
    "jedl", "vecer",
    "darek", "darcek", "gift", "present", "mnozstvo", "kus",
    "jednoduch", "maju rad", "pacia", "miluj",
    "varil", "prvykrat", "zleps", "marin", "namach", "japons",
    # beverage pairing, ingredient-type questions, recommendation, usage/substitution
    "najleps", "pijem", "pije", "pijeme", "pouzit", "mozem",
    "omack", "nieco", "ake", "aky", "akou",
    "ktor", "lepsi", "doplnok",
    "doplni", "kombin", "s cim",
    "nosi", "servir", "spar", "prispiev",
    "ochut", "vyuzi", "zvys",
    # garnish/fill/spread/EN pairing
    "posyp", "napln", "namaz", "ozob", "cim",
    "condiment", "go with", "goes with", "could i", "can i", "ide k",
    # flavour/quality comparative adjectives
    "pikan", "chutnejsi", "zdrav", "sladk", "kysl",
    # EN usage/method queries
    "best way", "how to use", "season", "objedn",
    # ingredient composition queries SK
    "obsah", "sklad", "z coho", "ide do", "obsahuj",
    # diet/health/texture/substitution queries
    "bezgluten", "nizkokalor", "dietn", "verzia",
    "chrumkav", "kremov", "umami", "nahrad",
    # heat/spice balancing, garnish, decoration, storage
    "zniz", "palivost", "zmier", "ostrost", "neutral",
    "garnish", "ozdobi", "uchov",
    # ratio/comparison/sourcing/side-dish queries
    "pomer", "rozdiel", "zohnat", "prikrm",
    # thickening/seasoning/mixing/marinating
    "zahust", "dochuc", "naklad", "zmiesat",
    # flavor enrichment / intensification
    "obohati", "intenz", "zintenz", "povys", "hutnej",
    # upgrade / typical / cuisine-characteristic queries
    "upgrad", "typick", "charakter", "autent",
    # side-dish, beverage-pairing (tea/wine/beer with dish), protein, ingredient-into-dish, recipe-base
    "priloha", "caj", "vino", "pivo", "tofu", "protein", "bielkovin", "baza", "co do",
    # what-is / what-to-put / Czech food spelling / all pouzi* forms
    "co je", "co dat", "jidl", "pouziva",
    # Slovak dative preposition k/ku/ko + space — strongest pairing signal possible
    "k ", "ku ", "ko ",
    # finger food / snack context
    "finger food",
    # meatless / plant-based queries
    "bez mas", "bez mäs",
    "na co",
    "vs",
    "co s",
    "varen",
)

RECIPE_INTENT_MARKERS = (
    "recept",
    "reept",
    "recet",
    "navod",
    "postup",
    "ako spravim",
    "ako pripravim",
    "ako urobim",
)

RANDOM_RECIPE_INTENT_MARKERS = (
    "co dnes varit",
    "co dnes uvarimc",
    "co uvarimc dnes",
    "nahodny recept",
    "nahodne recept",
    "co by som dnes",
    "co si dat dnes",
)


ALREADY_HAVE_MARKERS = (
    "mam ",
    "mam doma ",
    "mam uz ",
    "kupil som ",
    "vlastnim ",
    "mám ",
    "mám doma ",
    "mám uz ",
    "kúpil som ",
    "vlastním ",
)

ALREADY_HAVE_SUBJECT_MAP = {
    "sojova_omacka": ("sojovu omacku", "sojovej omacke", "sojova omacka", "sojovku", "sojovou omackou"),
    "kimchi": ("kimchi",),
    "ramen": ("ramen", "ramyeon", "ramyun"),
    "ryza": ("ryzu", "ryzou", "ryzy", "ryze", "ryzi", "bielu ryzu", "jasminovu ryzu", "jasminovej", "jasminov", "sushi ryzu"),
    "kokos": ("kokosove mlieko", "kokosoveho mlieka", "kokosovym mliekom"),
    "miso": ("miso pastu", "miso pastu", "miso"),
    "nori": ("nori", "morske riasy"),
    "tofu": ("tofu",),
    "gochujang": ("gochujang",),
    "sriracha": ("sriracha", "srirachu", "srirachom"),
    "ryzovy_ocot": ("ryzovy ocot", "ryzovom octe", "sushi ocot", "ocot na sushi", "ryzi ocot"),
    "wasabi": ("wasabi",),
    "udon": ("udon", "udon rezance", "udon rezancov"),
    "hoisin": ("hoisin", "hoisin omacku", "hoisin omacka", "hoisin omacke"),
    "rybacia_omacka": ("rybaciu omacku", "rybacia omacka", "rybacou omackou", "fish sauce"),
    "sezamovy_olej": ("sezamovy olej", "sezamovym olejom"),
    "kari": ("kari pastu", "kari omacku", "kari", "curry"),
    "gyoza": ("gyozu", "gyoza", "gyozove cestoviny", "gyozovych cestoviny"),
    "mochi": ("mochi",),
    "dashi": ("dashi", "dashi bujonu", "dashi stock"),
    "edamame": ("edamame",),
    "rezance": ("udon rezance", "ramen rezance", "ryze rezance", "rezancov", "rezance"),
    "nakladany_zazvor": ("nakladany zazvor", "nakladaneho zazvoru", "zazvor na sushi"),
    "wakame": ("wakame", "morske riasy wakame"),
    "panko": ("panko", "panko struhanka"),
    "ryzovy_papier": ("ryzovy papier", "ryzoveho papiera", "rice paper", "ryzovy papier na zavitky"),
    "gochugaru": ("gochugaru", "kórejske chilli", "korejske cili"),
    "matcha": ("matcha", "matchu", "matchou"),
    "sezamove_semienka": ("sezamove semienka", "sezamovych semienok", "sezam"),
    "pad_thai_omacka": ("pad thai omacku", "pad thai omacka", "pad thai sauce"),
    "sweet_chili": ("sweet chili", "sladku chili", "sladka chili", "sweet chilli"),
    "tamarind": ("tamarind", "tamarindu"),
    "pocky": ("pocky",),
    "bubble_tea": ("bubble tea", "boba tea", "bubble tea prasok"),
    "ustricova_omacka": ("ustricovu omacku", "ustricova omacka", "oyster sauce"),
    "ponzu": ("ponzu", "ponzu omacku"),
    "doenjang": ("doenjang", "korejska sojova pasta"),
    "ssamjang": ("ssamjang",),
    "chilli_olej": ("chilli olej", "cili olej", "chilli olejom", "cili olejom"),
    "mirin": ("mirin", "mirinom", "mirin na varenie"),
    "sake": ("sake", "ryžové víno sake", "ryzove vino sake"),
}

ALREADY_HAVE_COMPLEMENT_QUERIES = {
    "sojova_omacka": ["mirin", "ryzovy ocot", "hoisin omacka", "sezamovy olej", "dashi"],
    "kimchi": ["ramen rezance", "gochujang", "jazminova ryza", "sezamovy olej", "miso pasta"],
    "ramen": ["miso pasta", "wakame", "kimchi", "sezamovy olej", "dashi"],
    "ryza": ["sojova omacka", "rybacia omacka", "mirin", "tofu", "kimchi"],
    "kokos": ["kari pasta cervena", "rybacia omacka", "jazminova ryza", "sriracha"],
    "miso": ["dashi", "tofu", "wakame", "ramen rezance", "nori"],
    "nori": ["sushi ryza", "wasabi", "ryzovy ocot", "nakladany zazvor", "sojova omacka"],
    "tofu": ["sojova omacka", "sezamovy olej", "gochujang", "miso pasta", "rybacia omacka"],
    "gochujang": ["sezamovy olej", "jazminova ryza", "kimchi", "ssamjang", "ramen"],
    "sriracha": ["kokosove mlieko", "rybacia omacka", "jazminova ryza", "ramen"],
    "sezamovy_olej": ["sojova omacka", "ryzovy ocot", "mirin", "gochujang", "kimchi"],
    "kari": ["kokosove mlieko", "jazminova ryza", "rybacia omacka", "koriander", "sriracha"],
    "ryzovy_ocot": ["sushi ryza", "nori", "wasabi", "nakladany zazvor", "sojova omacka"],
    "wasabi": ["sojova omacka", "nakladany zazvor", "nori", "sushi ryza", "ryzovy ocot"],
    "udon": ["sojova omacka", "dashi", "wakame", "miso pasta", "sriracha"],
    "hoisin": ["sojova omacka", "sezamovy olej", "ramen rezance", "udon", "sriracha"],
    "rybacia_omacka": ["ryzove rezance", "sriracha", "hoisin omacka", "nakladany zazvor", "kokosove mlieko"],
    "gyoza": ["sojova omacka", "ryzovy ocot", "chilli olej", "sriracha"],
    "mochi": ["pocky", "bubble tea", "ryzove krekry", "kokosove cukriky"],
    "dashi": ["miso pasta", "tofu", "wakame", "ramen rezance"],
    "edamame": ["sojova omacka", "wasabi", "sezamovy olej", "sriracha"],
    "rezance": ["sojova omacka", "sezamovy olej", "sriracha", "ustricova omacka", "dashi"],
    "nakladany_zazvor": ["sushi ryza", "nori", "wasabi", "sojova omacka", "ryzovy ocot"],
    "wakame": ["miso pasta", "dashi", "tofu", "ramen rezance", "nori"],
    "panko": ["tonkatsu omacka", "sojova omacka", "wasabi", "ryzovy ocot"],
    "ryzovy_papier": ["ryzove rezance", "rybacia omacka", "sweet chili omacka", "sriracha"],
    "gochugaru": ["gochujang", "kimchi", "sezamovy olej", "sojova omacka", "jazminova ryza"],
    "matcha": ["mochi", "bubble tea", "pocky", "ryzove krekry"],
    "sezamove_semienka": ["sezamovy olej", "sojova omacka", "mirin", "ryzovy ocot"],
    "pad_thai_omacka": ["ryzove rezance", "rybacia omacka", "tamarind", "arasidy", "sriracha"],
    "sweet_chili": ["ryzovy papier", "sriracha", "rybacia omacka", "ramen rezance"],
    "tamarind": ["rybacia omacka", "kokosove mlieko", "kari pasta cervena", "sriracha"],
    "pocky": ["mochi", "bubble tea", "ryzove krekry", "matcha"],
    "bubble_tea": ["pocky", "mochi", "matcha", "ryzove krekry"],
    "ustricova_omacka": ["sojova omacka", "sezamovy olej", "sriracha", "ramen rezance"],
    "ponzu": ["sojova omacka", "nakladany zazvor", "wasabi", "nori", "sushi ryza"],
    "doenjang": ["gochujang", "sezamovy olej", "kimchi", "tofu", "jazminova ryza"],
    "ssamjang": ["gochujang", "sezamovy olej", "kimchi", "jazminova ryza"],
    "chilli_olej": ["sojova omacka", "ryzovy ocot", "sezamovy olej", "sriracha"],
    "mirin": ["sojova omacka", "dashi", "ryzovy ocot", "sezamovy olej"],
    "sake": ["mirin", "sojova omacka", "dashi", "sushi ryza"],
}

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
    # BUG-01 fix: zluceny do jedneho dict, akcentovane user-facing labely zachovane
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
    "vegan": "vhodnosť pre veganov",
}

OUT_OF_DOMAIN_MARKERS = (
    # --- potravinovy obchod: existujuce markery ---
    "bicyk",
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
    " liek",
    " predpis",
    "akcie",
    "burz",
    "hypotek",
    "nahradne diely",
    "diely do auta",
    "krmivo",
    "psov",
    "psa",
    " lekar",
    " lekara",
    "zdravotn",
    "diagnoz",
    "jedalnick",
    # --- elektronika ---
    "televizor",
    "televiz",
    "smartphon",
    "laptop",
    "pocitac",
    "sluchadl",
    "reproduktor",
    "fotoaparat",
    "tlaciare",
    "hernu konzol",
    "mobil telefon",
    "kupim telefon",
    "aky telefon",
    # --- oblecenie a obuv ---
    "oblecen",
    "topank",
    "sandal",
    "nohavic",
    "sukn",
    "saty",
    "sveter",
    "ponozk",
    "spodna bielizen",
    "tenisk",
    # --- nabytok a domacnost ---
    "nabytok",
    "nabytku",
    "matrac",
    "kreslo",
    "skrink",
    "komoda",
    # --- vozidla ---
    "auto servis",
    "pneumatik",
    "motorka",
    "elektricke auto",
    "ojazdene auto",
    # --- nehnutelnosti ---
    "nehnutelnost",
    "prenajom bytu",
    "kupim byt",
    "predaj domu",
    "realitna",
    # --- kozmetika ---
    "parfum",
    "kozmetika",
    "lak na nechty",
    # --- financie ---
    "kryptomien",
    "bitcoin",
    "investici",
    # --- praca a zamestnanie ---
    "zivotopis",
    "pracovnu ponuku",
    "pracovne miesto",
    # --- sport a volny cas ---
    "lyze",
    "lyzovania",
    "futbalov",
    "basketbal",
    # --- cestovanie ---
    "hotelovu rezervaci",
    "dovolenk",
)

# BUG-03 fix: OpenAI client singleton – nevytvara novy connection pool pri kazdom requeste
_openai_client: OpenAI | None = None


def _get_openai_client() -> OpenAI | None:
    """Vrati singleton OpenAI klienta. None ak OPENAI_API_KEY nie je nastaveny."""
    global _openai_client
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    if _openai_client is None:
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


# RETRY-01: Retry pre transientne OpenAI chyby (rate limit, timeout, connection)
# Max 3 pokusy, exponencialne backoff 1s → 2s → 4s, ostatne vynimky padaju okamzite.
@retry(
    retry=retry_if_exception_type((RateLimitError, APITimeoutError, APIConnectionError)),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _call_openai_with_retry(client: OpenAI, messages: list[dict], model: str) -> str:
    """
    Zavola OpenAI chat completion s retry pri transientnych chybach.
    Vracia text odpovede alebo prazdny retazec ak choices[0].message.content je None.
    """
    response = client.chat.completions.create(model=model, messages=messages)
    return response.choices[0].message.content or ""


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


@app.post("/products/suggest")
def product_suggest(request: ProductSuggestRequest) -> dict:
    return {"suggestions": autocomplete_suggestions(products, request.query, request.limit)}


@app.post("/knowledge/search")
def knowledge_search(request: KnowledgeSearchRequest) -> dict:
    results = search_knowledge(knowledge, request.query)
    return {
        "summary": knowledge_summary(results),
        "results": results,
    }


@app.post("/memory/clear")
def clear_user_memory(clear_request: MemoryClearRequest, request: Request) -> dict:
    client_key = get_client_key(request)
    profile_key = user_memory_key(clear_request.client_id, client_key)
    memories = load_user_memories()
    removed = profile_key in memories
    memories.pop(profile_key, None)
    save_user_memories()
    return {"cleared": removed}


@app.get("/admin/analytics/summary")
def admin_analytics_summary(
    days: int = 7,
    limit: int = 10,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    require_admin_token(x_admin_token)
    events = read_analytics_events(days)
    errors = read_error_events(days)
    return analytics_report(events, errors, limit)


@app.get("/admin/analytics/top-questions")
def admin_analytics_top_questions(
    days: int = 7,
    limit: int = 20,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    require_admin_token(x_admin_token)
    events = read_analytics_events(days)
    return {"top_questions": top_question_rows(events, limit)}


@app.get("/admin/analytics/no-results")
def admin_analytics_no_results(
    days: int = 7,
    limit: int = 20,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    require_admin_token(x_admin_token)
    events = read_analytics_events(days)
    return {"no_results": no_result_rows(events, limit)}


@app.get("/admin/analytics/intents")
def admin_analytics_intents(
    days: int = 7,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    require_admin_token(x_admin_token)
    events = read_analytics_events(days)
    return {"intents": intent_rows(events)}


def session_memory_key(session_id: str, client_key: str) -> str:
    raw_session = re.sub(r"[^a-zA-Z0-9_-]", "", str(session_id or ""))[:64]
    if raw_session:
        return raw_session
    digest = hashlib.sha256(str(client_key or "unknown").encode("utf-8")).hexdigest()[:24]
    return f"anon-{digest}"


def user_memory_key(client_id: str, client_key: str) -> str:
    raw_client = re.sub(r"[^a-zA-Z0-9_-]", "", str(client_id or ""))[:96]
    if raw_client:
        return raw_client
    digest = hashlib.sha256(str(client_key or "unknown").encode("utf-8")).hexdigest()[:24]
    return f"anon-{digest}"


def user_memory_path() -> Path:
    return Path(os.getenv("USER_MEMORY_PATH", str(DEFAULT_RUNTIME_LOG_DIR / "user_memory.json")))


def load_user_memories() -> dict[str, dict]:
    global user_memories
    if user_memories is not None:
        return user_memories
    user_memories = {}
    if not USER_MEMORY_ENABLED:
        return user_memories

    path = user_memory_path()
    if not path.exists():
        return user_memories
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            user_memories = {
                str(key): value
                for key, value in data.items()
                if isinstance(value, dict)
            }
    except Exception as exc:
        logger.error("Failed to read user memory %s: %s", path, exc, exc_info=True)
        user_memories = {}
    return user_memories


def save_user_memories() -> None:
    if not USER_MEMORY_ENABLED or user_memories is None:
        return
    path = user_memory_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(pruned_user_memories(user_memories), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.error("Failed to write user memory %s: %s", path, exc, exc_info=True)


def pruned_user_memories(memories: dict[str, dict]) -> dict[str, dict]:
    if len(memories) <= USER_MEMORY_MAX_PROFILES:
        return memories
    sorted_items = sorted(memories.items(), key=lambda item: float(item[1].get("updated_at", 0)), reverse=True)
    return dict(sorted_items[:USER_MEMORY_MAX_PROFILES])


def get_user_memory(profile_key: str) -> dict:
    memories = load_user_memories()
    profile = memories.get(profile_key)
    if not profile:
        profile = {
            "subjects": {},
            "diet_terms": {},
            "cuisines": {},
            "product_titles": {},
            "product_brands": {},
            "recipe_titles": {},
            "last_intent": "",
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        memories[profile_key] = profile
    return profile


def bump_profile_counter(profile: dict, key: str, value: str, weight: int = 1, limit: int = 40) -> None:
    normalized_value = redact_memory_text(str(value or "")).strip()
    if not normalized_value:
        return
    bucket = profile.setdefault(key, {})
    bucket[normalized_value] = int(bucket.get(normalized_value, 0)) + weight
    if len(bucket) > limit:
        keep = sorted(bucket.items(), key=lambda item: item[1], reverse=True)[:limit]
        profile[key] = dict(keep)


def update_user_memory(
    profile_key: str,
    message: str,
    intent: str,
    matches: list[dict] | None = None,
    recipes: list[dict] | None = None,
) -> dict:
    if not USER_MEMORY_ENABLED:
        return {}
    profile = get_user_memory(profile_key)
    profile["last_intent"] = intent
    profile["updated_at"] = time.time()

    for subject in detect_memory_subjects(message):
        bump_profile_counter(profile, "subjects", subject)
    for term in detect_diet_terms(message):
        bump_profile_counter(profile, "diet_terms", term)
    for cuisine in detect_cuisines_from_text(message):
        bump_profile_counter(profile, "cuisines", cuisine)

    for product in (matches or [])[:6]:
        if not should_remember_product_match(message, product):
            continue
        title = str(product.get("title") or "").strip()
        brand = str(product.get("brand") or "").strip()
        if title:
            bump_profile_counter(profile, "product_titles", title)
            for subject in detect_memory_subjects(title):
                bump_profile_counter(profile, "subjects", subject)
            for cuisine in detect_cuisines_from_text(title):
                bump_profile_counter(profile, "cuisines", cuisine)
        if brand:
            bump_profile_counter(profile, "product_brands", brand)

    for recipe in (recipes or [])[:4]:
        title = str(recipe.get("title") or "").strip()
        cuisine = str(recipe.get("cuisine") or "").strip()
        if title:
            bump_profile_counter(profile, "recipe_titles", title)
            for subject in detect_memory_subjects(title):
                bump_profile_counter(profile, "subjects", subject)
            for detected_cuisine in detect_cuisines_from_text(title):
                bump_profile_counter(profile, "cuisines", detected_cuisine)
        for detected_cuisine in detect_cuisines_from_text(cuisine):
            bump_profile_counter(profile, "cuisines", detected_cuisine)

    save_user_memories()
    return profile


def should_remember_product_match(message: str, product: dict) -> bool:
    message_tokens = {token for token in tokenize(message) if len(token) > 3}
    if not message_tokens:
        return False
    product_tokens = set(tokenize(str(product.get("title", ""))))
    direct_hits = message_tokens & product_tokens
    if direct_hits:
        return True
    product_text = product_profile_text(product)
    detected_subjects = set(detect_memory_subjects(message))
    return any(
        subject in detected_subjects and any(alias in product_text for alias in aliases)
        for subject, aliases in RELATED_SUBJECT_ALIASES.items()
    )


def public_user_memory_summary(profile: dict | None) -> dict:
    profile = profile or {}
    return {
        "top_subjects": top_profile_values(profile, "subjects", 5),
        "top_cuisines": top_profile_values(profile, "cuisines", 5),
        "diet_terms": top_profile_values(profile, "diet_terms", 5),
        "favorite_brands": top_profile_values(profile, "product_brands", 5),
    }


def top_profile_values(profile: dict, key: str, limit: int = 5) -> list[str]:
    bucket = profile.get(key, {})
    if not isinstance(bucket, dict):
        return []
    return [
        str(value)
        for value, _ in sorted(bucket.items(), key=lambda item: int(item[1]), reverse=True)[:limit]
    ]


def get_session_memory(memory_key: str) -> dict:
    now = time.time()
    prune_session_memories(now)
    memory = session_memories.get(memory_key)
    if not memory:
        memory = {
            "queries": deque(maxlen=6),
            "subjects": deque(maxlen=5),
            "diet_terms": deque(maxlen=4),
            "product_titles": deque(maxlen=8),
            "recipe_titles": deque(maxlen=5),
            "last_intent": "",
            "updated_at": now,
        }
        session_memories[memory_key] = memory
    memory["updated_at"] = now
    return memory


def prune_session_memories(now: float | None = None) -> None:
    now = now or time.time()
    if len(session_memories) <= SESSION_MEMORY_MAX_SESSIONS:
        expired = [
            key
            for key, memory in session_memories.items()
            if now - float(memory.get("updated_at", 0)) > SESSION_MEMORY_TTL_SECONDS
        ]
    else:
        sorted_items = sorted(session_memories.items(), key=lambda item: float(item[1].get("updated_at", 0)))
        expired = [key for key, _ in sorted_items[: max(1, len(session_memories) - SESSION_MEMORY_MAX_SESSIONS)]]

    for key in expired:
        session_memories.pop(key, None)


def contextualize_message(message: str, memory: dict | None) -> str:
    if not memory:
        return message

    parts = [message]
    if is_context_followup(message):
        subject = best_memory_subject(memory)
        if subject:
            parts.append(subject.replace("_", " "))
    for term in list(memory.get("diet_terms", []))[-2:]:
        if term and term not in normalize(" ".join(parts)):
            parts.append(term)
    return " ".join(parts).strip()


def is_context_followup(message: str) -> bool:
    normalized_message = normalize(message).strip()
    if len(tokenize(normalized_message)) <= 3 and any(
        marker in normalized_message
        for marker in ("k tomu", "co este", "este nieco", "dopln", "hodia", "odporuc", "a co", "a este")
    ):
        return True
    return normalized_message in {
        "co k tomu",
        "a co k tomu",
        "co este",
        "a este nieco",
        "co odporucas",
        "doplnky",
        "ake doplnky",
        "co chyba",
        "co mi chyba",
    }


def best_memory_subject(memory: dict | None) -> str | None:
    if not memory:
        return None
    subjects = list(memory.get("subjects", []))
    return subjects[-1] if subjects else None


def update_session_memory(
    memory_key: str,
    message: str,
    intent: str,
    matches: list[dict] | None = None,
    recipes: list[dict] | None = None,
    knowledge_matches: dict | None = None,
) -> dict:
    memory = get_session_memory(memory_key)
    memory["last_intent"] = intent
    memory["queries"].append(redact_memory_text(message))

    for subject in detect_memory_subjects(message):
        append_unique(memory["subjects"], subject)
    for term in detect_diet_terms(message):
        append_unique(memory["diet_terms"], term)

    for product in (matches or [])[:4]:
        title = product.get("title")
        if title:
            append_unique(memory["product_titles"], redact_memory_text(str(title))[:120])
            for subject in detect_memory_subjects(str(title)):
                append_unique(memory["subjects"], subject)

    for recipe in (recipes or [])[:3]:
        title = recipe.get("title")
        if title:
            append_unique(memory["recipe_titles"], redact_memory_text(str(title))[:120])
            for subject in detect_memory_subjects(str(title)):
                append_unique(memory["subjects"], subject)

    for hit in (knowledge_matches or {}).get("Recipes", [])[:2]:
        record = hit.get("record", {})
        title = first_record_value(record, ("Recept", "recipe", "nazov", "názov"))
        if title:
            append_unique(memory["recipe_titles"], redact_memory_text(title)[:120])

    memory["updated_at"] = time.time()
    return memory


def detect_memory_subjects(text: str) -> list[str]:
    normalized_text = normalize(text)
    subjects: list[str] = []
    for subject, aliases in RELATED_SUBJECT_ALIASES.items():
        if any(alias in normalized_text for alias in aliases):
            subjects.append(subject)
    return subjects[:4]


def detect_cuisines_from_text(text: str) -> list[str]:
    normalized_text = normalize(text)
    cuisines: list[str] = []
    for cuisine, markers in RECIPE_CUISINE_MARKERS.items():
        if any(marker in normalized_text for marker in markers):
            cuisines.append(cuisine)
    return cuisines[:4]


def detect_diet_terms(text: str) -> list[str]:
    normalized_text = normalize(text)
    terms: list[str] = []
    if any(marker in normalized_text for marker in ("bezlepk", "celiak", "bez lepku")):
        terms.append("bezlepkove")
    if any(marker in normalized_text for marker in ("vegan", "vegans")):
        terms.append("veganske")
    if any(marker in normalized_text for marker in ("vegetarian", "vegetariansk")):
        terms.append("vegetarianske")
    if any(marker in normalized_text for marker in ("nepaliv", "jemne", "menej paliv", "nie paliv")):
        terms.append("jemne")
    if any(marker in normalized_text for marker in ("paliv", "pikant", "chilli", "chili")):
        terms.append("pikantne")
    return terms


def append_unique(values: deque, value: str) -> None:
    if value in values:
        try:
            values.remove(value)
        except ValueError:
            pass
    values.append(value)


def redact_memory_text(text: str) -> str:
    cleaned = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[email]", str(text))
    cleaned = re.sub(r"\+?\d[\d\s().-]{6,}\d", "[phone]", cleaned)
    return cleaned[:200]


def session_memory_context(memory: dict | None) -> str:
    if not memory:
        return "bez ulozeneho kontextu"
    parts = []
    if memory.get("subjects"):
        parts.append("temy: " + ", ".join(list(memory["subjects"])[-3:]))
    if memory.get("diet_terms"):
        parts.append("preferencie: " + ", ".join(list(memory["diet_terms"])[-3:]))
    if memory.get("product_titles"):
        parts.append("posledne produkty: " + "; ".join(list(memory["product_titles"])[-3:]))
    if memory.get("recipe_titles"):
        parts.append("posledne recepty: " + "; ".join(list(memory["recipe_titles"])[-2:]))
    return " | ".join(parts) if parts else "bez ulozeneho kontextu"


@app.post("/chat")
def chat(chat_request: ChatRequest, request: Request) -> dict:
    client_key = get_client_key(request)
    enforce_rate_limit(client_key)

    session_id = getattr(chat_request, "session_id", "") or ""
    memory_key = session_memory_key(session_id, client_key)
    memory = get_session_memory(memory_key)
    profile_key = user_memory_key(getattr(chat_request, "client_id", ""), client_key)
    user_profile = get_user_memory(profile_key) if USER_MEMORY_ENABLED else {}
    contextual_message = contextualize_message(chat_request.message, memory)
    memory_subject = best_memory_subject(memory)

    knowledge_matches = search_knowledge(knowledge, contextual_message)
    articles = article_results(knowledge_matches, chat_request.limit)

    allergen_term = detect_allergen_intent(chat_request.message)
    if allergen_term and not detect_related_subject(chat_request.message):
        allergen_matches = allergen_product_matches(chat_request.message, chat_request.limit)
        allergen_matches = personalize_products(allergen_matches, user_profile)
        update_session_memory(memory_key, chat_request.message, "allergen_safety", allergen_matches, [], knowledge_matches)
        updated_profile = update_user_memory(profile_key, chat_request.message, "allergen_safety", allergen_matches, [])
        log_question(chat_request.message, client_key, len(allergen_matches), intent="allergen_safety", session_id=session_id)
        return {
            "answer": allergen_safety_answer(allergen_term),
            "products": allergen_matches,
            "articles": articles,
            "knowledge": knowledge_summary(knowledge_matches),
            "memory": public_user_memory_summary(updated_profile),
            "intent": "allergen_safety",
        }

    faq_answer = None
    if is_faq_intent(chat_request.message):
        faq_answer = best_direct_faq_answer(chat_request.message, knowledge) or best_faq_answer(knowledge_matches)
    if faq_answer and is_faq_intent(chat_request.message):
        update_session_memory(memory_key, chat_request.message, "faq", [], [], knowledge_matches)
        updated_profile = update_user_memory(profile_key, chat_request.message, "faq", [], [])
        log_question(chat_request.message, client_key, 0, intent="faq", session_id=session_id)
        return {
            "answer": faq_answer,
            "products": [],
            "articles": articles,
            "knowledge": knowledge_summary(knowledge_matches),
            "memory": public_user_memory_summary(updated_profile),
            "intent": "faq",
        }

    if is_random_recipe_intent(chat_request.message):
        random_rec = get_random_recipe(knowledge)
        random_recipes = [random_rec] if random_rec else []
        random_recipes = personalize_recipes(random_recipes, user_profile)
        update_session_memory(memory_key, chat_request.message, "recipe", [], random_recipes, knowledge_matches)
        updated_profile = update_user_memory(profile_key, chat_request.message, "recipe", [], random_recipes)
        log_question(chat_request.message, client_key, 0, intent="recipe", session_id=session_id)
        return {
            "answer": recipe_answer("general", random_recipes),
            "recipes": random_recipes,
            "products": [],
            "articles": articles,
            "knowledge": knowledge_summary(knowledge_matches),
            "memory": public_user_memory_summary(updated_profile),
            "intent": "recipe",
        }

    recipe_subject = detect_recipe_subject(contextual_message)
    if recipe_subject:
        recipes = recipe_results(knowledge_matches, chat_request.limit, contextual_message, knowledge)
        recipes = personalize_recipes(recipes, user_profile)
        recipe_articles = recipe_article_results(articles, contextual_message, knowledge, chat_request.limit)
        recipe_product_subject = recipe_related_product_subject(contextual_message, recipe_subject, recipes)
        recipe_products = (
            related_products_for_subject(products, recipe_product_subject, max(chat_request.limit, 8))
            if wants_recipe_products(contextual_message) and recipe_product_subject
            else []
        )
        recipe_products = personalize_products(recipe_products, user_profile)
        intent = "recipe_to_products" if recipe_products else "recipe"
        if recipe_products:
            annotate_recommendations(
                recipe_products,
                intent,
                related_subject=recipe_product_subject,
                query=contextual_message,
            )
        update_session_memory(memory_key, chat_request.message, intent, recipe_products, recipes, knowledge_matches)
        updated_profile = update_user_memory(profile_key, chat_request.message, intent, recipe_products, recipes)
        log_question(chat_request.message, client_key, 0, intent=intent, session_id=session_id)
        return {
            "answer": recipe_products_answer(recipe_product_subject, recipes) if recipe_products else recipe_answer(recipe_subject, recipes),
            "recipes": recipes,
            "products": recipe_products,
            "articles": recipe_articles,
            "cart_candidates": cart_candidates_for_response(recipe_products, intent, recipe_product_subject),
            "knowledge": knowledge_summary(knowledge_matches),
            "memory": public_user_memory_summary(updated_profile),
            "intent": intent,
        }

    if detect_out_of_domain(chat_request.message) and not detect_related_subject(chat_request.message):
        update_session_memory(memory_key, chat_request.message, "unknown", [], [], knowledge_matches)
        updated_profile = update_user_memory(profile_key, chat_request.message, "unknown", [], [])
        log_question(chat_request.message, client_key, 0, intent="unknown", session_id=session_id)
        return {
            "answer": "Na toto neviem spoľahlivo odpovedať ako Foodland poradca. Skúste sa opýtať na produkty, objednávku, dopravu alebo platbu na Foodland.sk.",
            "products": [],
            "knowledge": knowledge_summary(knowledge_matches),
            "memory": public_user_memory_summary(updated_profile),
            "intent": "unknown",
        }

    already_have_subject = detect_already_have_subject(contextual_message)
    special_subject = detect_special_product_subject(contextual_message)
    related_subject = detect_related_subject(contextual_message)
    article_product_subject = (
        detect_article_product_subject(contextual_message, articles)
        if articles and is_article_info_intent(chat_request.message)
        else None
    )
    if not related_subject and is_context_followup(chat_request.message):
        related_subject = memory_subject
    needs_composition_caution = is_composition_caution_search(contextual_message)
    if already_have_subject:
        matches = complement_products_for_subject(products, already_have_subject, chat_request.limit)
    elif special_subject:
        matches = special_products_for_subject(products, special_subject, chat_request.limit)
    elif article_product_subject:
        matches = article_products_for_subject(products, article_product_subject, chat_request.limit)
    elif related_subject:
        matches = related_products_for_subject(products, related_subject, chat_request.limit)
    else:
        matches = search_products(products, contextual_message, chat_request.limit)
    matches = personalize_products(matches, user_profile)
    intent = "article_products" if article_product_subject else ("related_products" if related_subject else "product_search")
    annotate_recommendations(
        matches,
        intent,
        related_subject or article_product_subject,
        already_have_subject,
        special_subject,
        contextual_message,
    )
    cart_candidates = cart_candidates_for_response(
        matches,
        intent,
        article_product_subject or related_subject or already_have_subject or special_subject or contextual_message,
    )
    update_session_memory(memory_key, chat_request.message, intent, matches, [], knowledge_matches)
    updated_profile = update_user_memory(profile_key, chat_request.message, intent, matches, [])
    log_question(chat_request.message, client_key, len(matches), intent=intent, session_id=session_id)

    if not matches and not knowledge_matches:
        return {
            "answer": "Nenašiel som presný produkt. Skúste napísať názov, značku alebo kategóriu trochu inak.",
            "products": [],
        }

    client = _get_openai_client()
    if not client:
        logger.debug("No OPENAI_API_KEY set, using fallback answer.")
        return {
            "answer": fallback_answer(matches, knowledge_matches, related_subject, needs_composition_caution),
            "products": matches,
            "articles": articles,
            "cart_candidates": cart_candidates,
            "knowledge": knowledge_summary(knowledge_matches),
            "memory": public_user_memory_summary(updated_profile),
            "intent": intent,
        }

    try:
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        messages = [
            {
                "role": "system",
                "content": (
                    "Si Foodland poradca – odborný nákupný asistent pre Foodland.sk, špeciálne azijské a svetové potraviny. "
                    "Odpovedaj po slovensky, priateľsky a s predajným tónom. Neprezentuj sa ako AI. "
                    "Vždy navrhuj doplnkové produkty (cross-sell) – napr. k sójovej omáčke navrhni mirin alebo ryžový ocot, "
                    "k ramen navrhni dashi alebo kimchi. Používaj formulácie: 'Odporúčam tiež...', "
                    "'Skvelo sa hodí k...', 'Zákazníci si k tomu zvyčajne berú aj...'. "
                    "Používaj iba poskytnutý kontext: produkty, FAQ, recepty, cross-sell, alternatívy a Products_AI. "
                    "Pri produktoch uvádzaj cenu a odkaz, ak sú dostupné. Pri alergiách, zložení a dostupnosti "
                    "odporuč overiť detail produktu. Nevymýšľaj ceny, sklad ani vlastnosti produktu. "
                    "Nevkladaj žiadne URL ani markdown odkazy, ktoré nie sú doslovne v poskytnutom kontexte. "
                    "Konverzácia je viackolová – pri otázkach ako 'a čo k tomu?' alebo 'a ešte niečo?' "
                    "odkazuj na predchádzajúce správy v konverzácii."
                    "Ak zákazník hovorí, že produkt UŽ MÁ ('mám X', 'kúpil som X', 'vlastním X'), "
                    "odporúčaj výhradne iné, komplementárne produkty – nie ďalšie varianty toho istého. "
                    "Tvoja textová odpoveď má byť iba 1–2 vety: vysvetli, prečo odporúčané produkty patria k danej téme alebo receptu. "
                    "Nepíš zoznam produktov, ich názvy ani ceny – zákazník ich vidí v kartách pod odpoveďou."
                ),
            },
        ]
        # Pridaj historiu konverzacie (max 10 sprav)
        conversation_history = getattr(chat_request, "conversation_history", None) or []
        for msg in conversation_history[-10:]:
            if isinstance(msg, dict) and msg.get("role") in ("user", "assistant") and isinstance(msg.get("content"), str):
                messages.append({"role": msg["role"], "content": msg["content"][:2000]})
        # Pridaj aktualnu otazku so vsetkym kontextom
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Otázka zákazníka: {chat_request.message}\n\n"
                    f"Relevantné produkty:\n{products_context(matches)}\n\n"
                    f"Foodland Knowledge:\n{knowledge_context(knowledge_matches)}\n\n"
                    f"Bezpečnostná poznámka: {composition_caution_context(needs_composition_caution)}"
                ),
            }
        )
        # RETRY-01: _call_openai_with_retry pokusi sa max 3x pri RateLimit/Timeout/Connection
        answer_text = _call_openai_with_retry(client, messages, model)
        if not answer_text:
            answer_text = fallback_answer(matches, knowledge_matches, related_subject, needs_composition_caution)
        answer_text = sanitize_answer_links(answer_text, allowed_answer_urls(matches, knowledge_matches))
        logger.info("OpenAI response generated.")
        return {
            "answer": answer_text,
            "products": matches,
            "articles": articles,
            "cart_candidates": cart_candidates,
            "knowledge": knowledge_summary(knowledge_matches),
            "memory": public_user_memory_summary(updated_profile),
            "intent": intent,
        }
    except (RateLimitError, APITimeoutError, APIConnectionError) as exc:
        logger.warning("OpenAI transient error after retries: %s", exc)
        log_backend_error("openai_transient_error", str(exc))
        return {
            "answer": fallback_answer(matches, knowledge_matches, related_subject, needs_composition_caution),
            "products": matches,
            "articles": articles,
            "cart_candidates": cart_candidates,
            "knowledge": knowledge_summary(knowledge_matches),
            "warning": "Služba je momentálne preťažená, zobrazujem nájdené produkty.",
        }
    except Exception as exc:
        logger.error("OpenAI API failed: %s", exc, exc_info=True)
        log_backend_error("openai_response_failed", str(exc))
        return {
            "answer": fallback_answer(matches, knowledge_matches, related_subject, needs_composition_caution),
            "products": matches,
            "articles": articles,
            "cart_candidates": cart_candidates,
            "knowledge": knowledge_summary(knowledge_matches),
            "warning": "Odpoveď sa nepodarilo vygenerovať, zobrazujem nájdené produkty.",
        }


def get_client_key(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def allowed_answer_urls(matches: list[dict], knowledge_matches: dict | None) -> set[str]:
    urls: set[str] = set()
    for product in matches or []:
        for key in ("link", "url"):
            value = str(product.get(key) or "").strip()
            if value.startswith(("http://", "https://")):
                urls.add(value)

    for hits in (knowledge_matches or {}).values():
        for hit in hits:
            record = hit.get("record", {})
            for value in record.values():
                text = str(value or "").strip()
                if text.startswith(("http://", "https://")):
                    urls.add(text)

    return urls


def annotate_recommendations(
    matches: list[dict],
    intent: str,
    related_subject: str | None = None,
    already_have_subject: str | None = None,
    special_subject: str | None = None,
    query: str = "",
) -> None:
    context = related_subject or already_have_subject or special_subject or query
    for index, product in enumerate(matches or [], start=1):
        group = recommendation_group(product)
        product["recommendation_group"] = group
        product["recommendation_priority"] = index
        product["recommendation_reason"] = recommendation_reason(product, group, intent, context)


def personalize_products(matches: list[dict], profile: dict | None) -> list[dict]:
    if not matches or not profile:
        return matches
    ranked: list[tuple[int, int, dict]] = []
    for index, product in enumerate(matches):
        score = personalization_score(product_profile_text(product), product, profile)
        if score > 0:
            product["personalized"] = True
            product["personalization_score"] = score
        ranked.append((score, -index, product))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [product for _, _, product in ranked]


def personalize_recipes(recipes: list[dict], profile: dict | None) -> list[dict]:
    if not recipes or not profile:
        return recipes
    ranked: list[tuple[int, int, dict]] = []
    for index, recipe in enumerate(recipes):
        text = normalize(" ".join(str(recipe.get(key, "")) for key in ("title", "cuisine", "note", "link")))
        score = personalization_score(text, {}, profile)
        if score > 0:
            recipe["personalized"] = True
            recipe["personalization_score"] = score
        ranked.append((score, -index, recipe))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [recipe for _, _, recipe in ranked]


def product_profile_text(product: dict) -> str:
    return normalize(
        " ".join(
            str(product.get(key, ""))
            for key in ("title", "brand", "product_type", "category", "description")
        )
    )


def personalization_score(text: str, item: dict, profile: dict) -> int:
    score = 0
    score += profile_marker_score(text, profile.get("cuisines", {}), RECIPE_CUISINE_MARKERS, 4)
    score += profile_marker_score(text, profile.get("subjects", {}), RELATED_SUBJECT_ALIASES, 3)
    score += profile_marker_score(text, profile.get("diet_terms", {}), DIET_TERM_MARKERS, 3)
    score += profile_text_score(text, profile.get("product_titles", {}), 1, max_weight=2)
    brand = normalize(str(item.get("brand", "")))
    if brand:
        score += profile_text_score(brand, profile.get("product_brands", {}), 2, max_weight=6)
    return score


def profile_marker_score(text: str, bucket: dict, marker_map: dict, weight: int) -> int:
    if not isinstance(bucket, dict):
        return 0
    score = 0
    for key, count in bucket.items():
        markers = marker_map.get(key, (key,))
        if any(marker in text for marker in markers):
            score += min(int(count), 5) * weight
    return score


def profile_text_score(text: str, bucket: dict, weight: int, max_weight: int = 5) -> int:
    if not isinstance(bucket, dict):
        return 0
    score = 0
    for key, count in bucket.items():
        normalized_key = normalize(str(key))
        if normalized_key and normalized_key in text:
            score += min(int(count), max_weight) * weight
    return score


def recommendation_group(product: dict) -> str:
    text = normalize(" ".join(str(product.get(key, "")) for key in ("title", "product_type", "category", "description")))
    if any(marker in text for marker in ("korenie", "badian", "skorica", "bujon", "vyvar", "dashi", "bonito")):
        return "Korenie a vývar"
    if any(marker in text for marker in ("ryza", "rezance", "nudle", "papier", "nori")):
        return "Základ"
    if any(marker in text for marker in ("omack", "sauce", "ocot", "mirin", "olej", "miso", "pasta")):
        return "Dochutenie"
    if any(marker in text for marker in ("chili", "cili", "sriracha", "gochujang", "wasabi", "kimchi")):
        return "Pikantné"
    if any(marker in text for marker in ("kokos", "mlieko", "tofu", "hub", "shiitake", "zazvor", "cesnak")):
        return "Doplnok"
    return "Odporúčané"


def recommendation_reason(product: dict, group: str, intent: str, context: str | None) -> str:
    title = normalize(str(product.get("title", "")))
    context_text = recommendation_context_label(context)
    if intent == "article_products" and context_text:
        return f"Ak vás zaujal článok o {context_text}, toto je priamo súvisiaci produkt."
    if intent == "related_products" and context_text:
        return f"K {context_text} sa hodí, keď chcete nákup doplniť o ďalšiu surovinu alebo dochutenie."
    if "bezlepk" in title or "tamari" in title:
        return "Vhodný kandidát pri bezlepkovom výbere; zloženie si overte v detaile produktu."
    if group == "Základ":
        return "Je to jedna zo základných surovín, bez ktorej sa dané jedlo pripravuje ťažšie."
    if group == "Korenie a vývar":
        return "Pomáha postaviť chuť vývaru a dodá jedlu typickú vôňu."
    if group == "Dochutenie":
        return "Doladí slanosť, kyslosť alebo umami, takže jedlo nebude chutiť plocho."
    if group == "Pikantné":
        return "Pridá pikantnosť alebo fermentovanú chuť, ak chcete výraznejší výsledok."
    return "Je to praktický doplnok, ktorý sa pri tejto kuchyni často zíde."


def recommendation_context_label(context: str | None) -> str:
    raw_context = str(context or "").strip()
    if not raw_context:
        return ""
    labels = {
        "kimchi_article": "kimchi",
        "pho_article": "pho",
        "udon_article": "udon rezancoch",
        "ramen_article": "ramene",
        "udon_ramen_article": "udon a ramen rezancoch",
        "tofu_article": "tofu",
        "shoyu_article": "shoyu",
        "tamari_article": "tamari",
        "miso_article": "miso paste",
        "matcha_article": "matcha",
        "mochi_article": "mochi",
        "bubble_tea_article": "bubble tea",
    }
    return labels.get(raw_context, raw_context.replace("_", " "))


def cart_candidates_for_response(matches: list[dict], intent: str, context: str | None = None) -> list[dict]:
    if intent not in {"related_products", "product_search", "recipe_to_products", "article_products"}:
        return []
    reason = f"Odporúčanie Foodland Mei: {str(context or intent).replace('_', ' ')[:80]}"
    candidates = products_to_cart_candidates(matches or [], reason)
    for candidate, product in zip(candidates, matches or []):
        candidate["recommendation_group"] = product.get("recommendation_group", "Odporúčané")
        candidate["recommendation_reason"] = product.get("recommendation_reason", reason)
        candidate["priority"] = product.get("recommendation_priority", 0)
    return candidates


def sanitize_answer_links(answer: str, allowed_urls: set[str]) -> str:
    def markdown_replacement(match: re.Match) -> str:
        label = match.group(1)
        url = match.group(2).rstrip(".,);")
        return match.group(0) if url in allowed_urls else label

    sanitized = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", markdown_replacement, answer)

    def bare_replacement(match: re.Match) -> str:
        url = match.group(0).rstrip(".,);")
        suffix = match.group(0)[len(url):]
        return match.group(0) if url in allowed_urls else suffix

    return re.sub(r"https?://[^\s)]+", bare_replacement, sanitized)


def enforce_rate_limit(client_key: str) -> None:
    limit = int(os.getenv("RATE_LIMIT_PER_MINUTE", "12"))
    now = time.time()
    window_start = now - 60

    # BUG-02 fix: batch cleanup expired klientov ak dict presiahne limit
    if len(rate_limit_events) > _RATE_LIMIT_MAX_CLIENTS:
        expired = [k for k, v in rate_limit_events.items() if not v or v[-1] < window_start]
        for k in expired[:1000]:
            del rate_limit_events[k]
        if expired:
            logger.info("Rate limit cleanup: removed %d expired client entries.", len(expired[:1000]))

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


def log_question(message: str, client_key: str, matches_count: int, intent: str = "", session_id: str = "") -> None:
    path = Path(os.getenv("ANALYTICS_LOG_PATH", str(DEFAULT_RUNTIME_LOG_DIR / "question_analytics.jsonl")))
    salt = os.getenv("ANALYTICS_SALT", "")
    record = {
        "ts": int(time.time()),
        "client_hash": hashlib.sha256(f"{salt}:{client_key}".encode("utf-8")).hexdigest()[:24],
        "message": message[:1000],
        "matches_count": matches_count,
        "intent": intent,
        "session_id": session_id,
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
    path = Path(os.getenv("ERROR_LOG_PATH", str(DEFAULT_RUNTIME_LOG_DIR / "backend_errors.jsonl")))
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


def require_admin_token(x_admin_token: str | None) -> None:
    expected = os.getenv("ADMIN_ANALYTICS_TOKEN") or os.getenv("ADMIN_RELOAD_TOKEN")
    if not expected:
        raise HTTPException(status_code=404, detail="Admin analytika nie je zapnutá.")
    if not x_admin_token or not hmac_compare(str(x_admin_token), str(expected)):
        raise HTTPException(status_code=401, detail="Neplatný admin token.")


def hmac_compare(left: str, right: str) -> bool:
    return secrets.compare_digest(left, right)


def read_analytics_events(days: int = 7) -> list[dict]:
    path = Path(os.getenv("ANALYTICS_LOG_PATH", str(DEFAULT_RUNTIME_LOG_DIR / "question_analytics.jsonl")))
    return read_jsonl_events(path, days)


def read_error_events(days: int = 7) -> list[dict]:
    path = Path(os.getenv("ERROR_LOG_PATH", str(DEFAULT_RUNTIME_LOG_DIR / "backend_errors.jsonl")))
    return read_jsonl_events(path, days)


def read_jsonl_events(path: Path, days: int = 7) -> list[dict]:
    if not path.exists():
        return []
    now = int(time.time())
    safe_days = max(1, min(int(days or 7), 90))
    since = now - safe_days * 86400
    events: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = int(record.get("ts", 0) or 0)
                if ts >= since:
                    events.append(record)
    except Exception as exc:
        logger.error("Failed to read analytics log %s: %s", path, exc, exc_info=True)
    return events


def analytics_report(events: list[dict], errors: list[dict] | None = None, limit: int = 10) -> dict:
    errors = errors or []
    safe_limit = max(1, min(int(limit or 10), 100))
    no_results = [event for event in events if is_no_result_event(event)]
    unknowns = [event for event in events if event.get("intent") == "unknown"]
    return {
        "summary": {
            "questions": len(events),
            "unique_clients": len({event.get("client_hash") for event in events if event.get("client_hash")}),
            "sessions": len({event.get("session_id") for event in events if event.get("session_id")}),
            "no_result_questions": len(no_results),
            "unknown_questions": len(unknowns),
            "backend_errors": len(errors),
        },
        "top_questions": top_question_rows(events, safe_limit),
        "no_results": no_result_rows(events, safe_limit),
        "intents": intent_rows(events),
        "weak_spots": weak_spot_rows(events, errors, safe_limit),
    }


def normalized_question_key(message: str) -> str:
    cleaned = normalize(message)
    cleaned = re.sub(r"\b\d+[,.]?\d*\s*(g|kg|ml|l|ks)\b", " ", cleaned)
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", cleaned)
    return " ".join(cleaned.split())[:160]


def top_question_rows(events: list[dict], limit: int = 20) -> list[dict]:
    counter: Counter[str] = Counter()
    examples: dict[str, str] = {}
    for event in events:
        message = str(event.get("message", "")).strip()
        key = normalized_question_key(message)
        if not key:
            continue
        counter[key] += 1
        examples.setdefault(key, message[:240])
    return [
        {"question": examples[key], "normalized": key, "count": count}
        for key, count in counter.most_common(max(1, min(limit, 100)))
    ]


def no_result_rows(events: list[dict], limit: int = 20) -> list[dict]:
    no_result_events = [event for event in events if is_no_result_event(event)]
    counter: Counter[str] = Counter()
    examples: dict[str, dict] = {}
    for event in no_result_events:
        message = str(event.get("message", "")).strip()
        key = normalized_question_key(message)
        if not key:
            continue
        counter[key] += 1
        examples.setdefault(
            key,
            {
                "question": message[:240],
                "intent": event.get("intent", ""),
                "last_seen": event.get("ts", 0),
            },
        )
        examples[key]["last_seen"] = max(int(examples[key].get("last_seen", 0) or 0), int(event.get("ts", 0) or 0))
    return [
        {"normalized": key, "count": count, **examples[key]}
        for key, count in counter.most_common(max(1, min(limit, 100)))
    ]


def intent_rows(events: list[dict]) -> list[dict]:
    counts = Counter(str(event.get("intent") or "unknown") for event in events)
    total = sum(counts.values()) or 1
    return [
        {"intent": intent, "count": count, "share": round(count / total, 4)}
        for intent, count in counts.most_common()
    ]


def weak_spot_rows(events: list[dict], errors: list[dict] | None = None, limit: int = 10) -> list[dict]:
    errors = errors or []
    rows: list[dict] = []
    no_result_count = sum(1 for event in events if is_no_result_event(event))
    unknown_count = sum(1 for event in events if event.get("intent") == "unknown")
    if no_result_count:
        rows.append({"area": "no_results", "count": no_result_count, "note": "Otázky bez nájdených produktov alebo obsahu."})
    if unknown_count:
        rows.append({"area": "unknown_intent", "count": unknown_count, "note": "Otázky mimo rozpoznaných Foodland tém."})
    for intent, count in Counter(str(event.get("intent") or "unknown") for event in events if is_no_result_event(event)).most_common():
        rows.append({"area": f"no_results:{intent}", "count": count, "note": "Intent často končí bez produktovej zhody."})
    for event_name, count in Counter(str(error.get("event") or "backend_error") for error in errors).most_common():
        rows.append({"area": f"backend:{event_name}", "count": count, "note": "Backend chyba v sledovanom období."})
    rows.sort(key=lambda row: row["count"], reverse=True)
    return rows[: max(1, min(limit, 100))]


def is_no_result_event(event: dict) -> bool:
    intent = str(event.get("intent") or "")
    product_intents = {"product_search", "related_products", "article_products", "recipe_to_products", "allergen_safety"}
    return intent in product_intents and int(event.get("matches_count", 0) or 0) == 0


def is_faq_intent(message: str) -> bool:
    normalized_message = normalize(message)
    return any(marker in normalized_message for marker in FAQ_INTENT_MARKERS)


FAQ_CATEGORY_MARKERS = {
    "doprava": ("doprava", "doruc", "kurier", "packeta", "dpd", "gls", "postovn", "vyzdvih"),
    "platby": ("plat", "zapl", "kart", "hotov", "dobier", "paypal", "gopay", "prevod"),
    "reklamacie": ("reklamac", "poskoden", "chyb", "vymen", "vratenie penaz"),
    "vratenie tovaru": ("vrat", "odstup", "vymen"),
    "registracia": ("registr", "prihlas", "heslo", "ucet"),
    "vernostny program": ("kredit", "vernost", "zlava", "body", "bod"),
    "nakup": ("objednav", "kosik", "nakup", "skladom"),
}


def best_direct_faq_answer(message: str, loaded_knowledge: dict) -> str | None:
    normalized_message = normalize(message)
    query_tokens = tokenize(message)
    best_score = 0
    best_answer = ""

    if any(marker in normalized_message for marker in ("postovn", "cena dopravy", "stoji doprava", "kolko stoji doprava")):
        shipping_answer = direct_faq_answer_by_question_markers(
            loaded_knowledge,
            required_markers=("doprava", "zadarmo"),
        )
        if shipping_answer:
            return shipping_answer
    if any(marker in normalized_message for marker in ("kurier", "doruc", "zasielk")):
        delivery_answer = direct_faq_answer_by_question_markers(
            loaded_knowledge,
            required_markers=("sposoby", "dorucenia"),
        )
        if delivery_answer:
            return delivery_answer

    for record in loaded_knowledge.get("sections", {}).get("FAQ", []):
        question = first_record_value(record, ("Otázka", "Otazka", "question"))
        answer = first_record_value(record, ("Odpoveď", "Odpoved", "answer"))
        category = first_record_value(record, ("Kategória", "Kategoria", "category"))
        if not answer:
            continue

        normalized_question = normalize(question)
        normalized_category = normalize(category)
        record_tokens = tokenize(" ".join([category, question, answer]))
        score = len(query_tokens & record_tokens)

        if normalized_question and normalized_question in normalized_message:
            score += 20
        if normalized_category and normalized_category in normalized_message:
            score += 12
        for category_name, markers in FAQ_CATEGORY_MARKERS.items():
            if normalized_category == category_name and any(marker in normalized_message for marker in markers):
                score += 10
        if (
            any(marker in normalized_message for marker in ("kolko", "cena", "stoji", "postovn"))
            and "zadarmo" in normalized_question
            and "doprava" in normalized_question
        ):
            score += 10
        if "ako" in normalized_message and "zapl" in normalized_message and "plat" in normalized_question:
            score += 10

        if score > best_score:
            best_score = score
            best_answer = answer

    return best_answer if best_score >= 3 else None


def direct_faq_answer_by_question_markers(loaded_knowledge: dict, required_markers: tuple[str, ...]) -> str | None:
    for record in loaded_knowledge.get("sections", {}).get("FAQ", []):
        question = first_record_value(record, ("Otázka", "Otazka", "question"))
        normalized_question = normalize(question)
        if all(marker in normalized_question for marker in required_markers):
            answer = first_record_value(record, ("Odpoveď", "Odpoved", "answer"))
            if answer:
                return answer
    return None


def detect_recipe_subject(message: str) -> str | None:
    normalized_message = normalize(message)
    if not is_recipe_intent(normalized_message):
        return None

    for subject, aliases in RELATED_SUBJECT_ALIASES.items():
        if any(alias in normalized_message for alias in aliases):
            return subject

    return "general"


def wants_recipe_products(message: str) -> bool:
    normalized_message = normalize(message)
    return any(
        marker in normalized_message
        for marker in (
            "ingredien",
            "surovin",
            "produkt",
            "kupit",
            "nakup",
            "nakupny zoznam",
            "co potrebujem",
            "co treba",
            "co mi chyba",
            "co chyba",
            "do kosika",
            "k receptu",
            "k recept",
        )
    )


def recipe_related_product_subject(
    message: str,
    recipe_subject: str | None,
    recipes: list[dict] | None = None,
) -> str | None:
    message_subject = recipe_product_subject_from_title(message)
    if message_subject:
        return message_subject
    related_subject = detect_related_subject(message)
    if related_subject:
        return related_subject
    if recipe_subject in RELATED_PRODUCT_QUERIES:
        return recipe_subject
    for recipe in recipes or []:
        subject = recipe_product_subject_from_title(recipe.get("title", ""))
        if subject:
            return subject
    return None


def recipe_product_subject_from_title(title: str) -> str | None:
    normalized_title = normalize(title)
    for marker, subject in RECIPE_TITLE_PRODUCT_SUBJECTS:
        if marker in normalized_title:
            return subject
    return None


def is_recipe_intent(normalized_message: str) -> bool:
    if any(marker in normalized_message for marker in RECIPE_INTENT_MARKERS):
        return True
    return any(token.startswith(("rec", "recep")) for token in tokenize(normalized_message))


def is_random_recipe_intent(message: str) -> bool:
    normalized_message = normalize(message)
    return any(marker in normalized_message for marker in RANDOM_RECIPE_INTENT_MARKERS)


def get_random_recipe(all_knowledge: dict) -> dict | None:
    all_recipes = all_knowledge.get("sections", {}).get("Recipes", [])
    if not all_recipes:
        return None
    return recipe_card(random.choice(all_recipes))


def recipe_results(
    knowledge_matches: dict | None,
    limit: int = 4,
    message: str = "",
    all_knowledge: dict | None = None,
) -> list[dict]:
    recipes = (knowledge_matches or {}).get("Recipes", [])
    results: list[tuple[int, dict]] = []
    seen_titles: set[str] = set()
    wanted_tokens = recipe_query_tokens(message)
    cuisine_subject = detect_recipe_cuisine(message)

    if cuisine_subject and all_knowledge:
        recipes = [
            {"record": record, "score": 0}
            for record in all_knowledge.get("sections", {}).get("Recipes", [])
            if recipe_matches_cuisine(record, cuisine_subject)
        ]
        wanted_tokens = {token for token in wanted_tokens if not is_recipe_cuisine_query_token(token)}

    if not recipes and not wanted_tokens and all_knowledge:
        recipes = [
            {"record": record}
            for record in all_knowledge.get("sections", {}).get("Recipes", [])
        ]

    candidate_records = list(recipes)
    if wanted_tokens and all_knowledge:
        known_titles = {
            normalize(recipe_card(item.get("record", {})).get("title", ""))
            for item in candidate_records
        }
        for record in all_knowledge.get("sections", {}).get("Recipes", []):
            title_key = normalize(recipe_card(record).get("title", ""))
            if title_key and title_key not in known_titles:
                candidate_records.append({"record": record, "score": 0})
                known_titles.add(title_key)

    for item in candidate_records:
        record = item.get("record", {})
        recipe = recipe_card(record)
        title_key = normalize(recipe.get("title", ""))
        recipe_tokens = tokenize(recipe_search_text(record, recipe))
        token_hits = len(wanted_tokens & recipe_tokens)
        if wanted_tokens and token_hits == 0:
            continue
        if recipe["title"] and title_key not in seen_titles:
            seen_titles.add(title_key)
            title_tokens = tokenize(recipe.get("title", ""))
            score = int(item.get("score", 0)) + (10 * len(wanted_tokens & title_tokens)) + (3 * token_hits)
            results.append((score, recipe))
        if len(results) >= max(1, min(limit, 4)) and not wanted_tokens:
            break

    results.sort(key=lambda item: item[0], reverse=True)
    return [recipe for _, recipe in results[: max(1, min(limit, 4))]]


def recipe_search_text(record: dict, recipe: dict) -> str:
    values = [
        recipe.get("title", ""),
        recipe.get("cuisine", ""),
        recipe.get("note", ""),
    ]
    for key, value in record.items():
        normalized_key = normalize(str(key))
        if normalized_key in {"sk_url", "sk"} or "poznamka" in normalized_key:
            values.append(str(value))
    return " ".join(values)


RECIPE_CUISINE_MARKERS = {
    "vietnam": (
        "vietnam",
        "vietnamsk",
        "vietnamska",
        "vietnamske",
        "vietnamskej",
        "vietnamsku",
        "pho",
        "banh",
        "bun cha",
        "bun bo",
        "nem cuon",
        "nuoc cham",
        "thit dong",
    ),
    "thai": (
        "thai",
        "thajsk",
        "thajska",
        "thajske",
        "thajskej",
        "thajsku",
        "thajsko",
        "thajska",
        "pad thai",
        "tom yum",
        "tom kha",
        "satay",
        "khaoneeomamuang",
    ),
    "korean": (
        "korejsk",
        "korejska",
        "korejske",
        "korejskej",
        "korejsku",
        "korea",
        "korey",
        "korei",
        "korean",
        "kimchi",
        "jjigae",
        "japchae",
        "bulgogi",
        "bibimbap",
        "gimbap",
    ),
    "japanese": (
        "japonsk",
        "japonska",
        "japonske",
        "japonskej",
        "japonsku",
        "japansk",
        "japanese",
        "udon",
        "yakiudon",
        "teriyaki",
        "kuromame",
        "miso",
        "tempura",
        "shoyu",
    ),
    "chinese": (
        "cinsk",
        "cinska",
        "cinske",
        "cinskej",
        "cinsku",
        "cina",
        "ciny",
        "cinu",
        "chinese",
        "kung pao",
        "pekingsk",
        "peking",
        "ma po",
        "mapo",
        "sichuan",
        "suan la tang",
    ),
    "indian": (
        "indick",
        "indicka",
        "indicke",
        "indickej",
        "india",
        "indie",
        "indiu",
        "indian",
        "murgh makhani",
        "tikka masala",
        "tandoori",
        "biryani",
    ),
    "indonesian": (
        "indonez",
        "indonezska",
        "indonezske",
        "indonezskej",
        "indonezia",
        "indonezie",
        "indoneziu",
        "indonesia",
        "nasi goreng",
        "mie goreng",
    ),
    "malaysian": (
        "malajsk",
        "malajska",
        "malajske",
        "malajskej",
        "malajzia",
        "malajzie",
        "malajziu",
        "malaysia",
        "nasi lemak",
    ),
    "singapore": (
        "singapur",
        "singapursk",
        "singapurska",
        "singapurske",
        "singapurskej",
        "hainanske",
    ),
    "filipino": (
        "filipin",
        "filipinska",
        "filipinske",
        "filipinskej",
        "philippines",
        "sinigang",
    ),
}

RECIPE_CUISINE_QUERY_TOKENS = {
    "vietnam",
    "vietnamsk",
    "vietnamska",
    "vietnamske",
    "vietnamskej",
    "vietnamsku",
    "thai",
    "thajsk",
    "thajska",
    "thajske",
    "thajskej",
    "thajsku",
    "korejsk",
    "korejska",
    "korejske",
    "korejskej",
    "korejsku",
    "korea",
    "korey",
    "korei",
    "japonsk",
    "japonska",
    "japonske",
    "japonskej",
    "japonsku",
    "cinsk",
    "cinska",
    "cinske",
    "cinskej",
    "cinsku",
    "cina",
    "ciny",
    "cinu",
    "indick",
    "indicka",
    "indicke",
    "indickej",
    "india",
    "indie",
    "indiu",
    "indonez",
    "indonezia",
    "indonezie",
    "indoneziu",
    "malajsk",
    "malajzia",
    "malajzie",
    "malajziu",
    "singapur",
    "filipin",
    "kuchyna",
    "kuchyne",
    "kuchyni",
    "kuchynu",
}


ARTICLE_CULINARY_MARKERS = (
    "kuchyn",
    "recept",
    "jedal",
    "jedlo",
    "chut",
    "potrav",
    "ingredien",
    "omac",
    "rezanc",
    "poliev",
    "ryz",
    "snack",
    "pochut",
    "kimchi",
    "miso",
    "udon",
    "ramen",
    "shoyu",
    "mochi",
    "pho",
    "pad thai",
    "tom yum",
    "kung pao",
    "tofu",
    "biryani",
    "rendang",
    "nasi",
    "sinigang",
)


DIET_TERM_MARKERS = {
    "bezlepkove": ("bezlepk", "gluten free", "tamari"),
    "veganske": ("vegan", "vegansk", "tofu", "rastlinn"),
    "vegetarianske": ("vegetarian", "vegetariansk", "tofu", "rastlinn"),
    "jemne": ("jemne", "mild", "nepaliv"),
    "pikantne": ("pikant", "chili", "cili", "sriracha", "gochujang", "wasabi", "kimchi"),
}


def detect_recipe_cuisine(message: str) -> str | None:
    normalized_message = normalize(message)
    for cuisine, markers in RECIPE_CUISINE_MARKERS.items():
        if any(marker in normalized_message for marker in markers):
            return cuisine
    return None


def is_recipe_cuisine_query_token(token: str) -> bool:
    if token in RECIPE_CUISINE_QUERY_TOKENS:
        return True
    return token.startswith(
        (
            "vietnam",
            "vietnamsk",
            "thajsk",
            "korejsk",
            "japonsk",
            "japansk",
            "cinsk",
            "indick",
            "indonez",
            "malajsk",
            "singapur",
            "filipin",
            "kuchyn",
        )
    )


def recipe_matches_cuisine(record: dict, cuisine: str) -> bool:
    recipe = recipe_card(record)
    text = normalize(recipe_search_text(record, recipe))
    return any(marker in text for marker in RECIPE_CUISINE_MARKERS.get(cuisine, ()))


def recipe_query_tokens(message: str) -> set[str]:
    stop_words = {
        "recept",
        "recepty",
        "reept",
        "recet",
        "receppt",
        "recep",
        "navod",
        "postup",
        "ako",
        "spravim",
        "pripravim",
        "urobim",
        "na",
        "pre",
        "zo",
        "z",
        "stranky",
        "foodland",
        "foodlandu",
        "sk",
        "prosim",
        "ake",
        "aky",
        "aku",
        "mate",
        "mas",
        "mame",
        "ponukate",
        "ukaz",
        "daj",
        "thai",
    }
    return {token for token in tokenize(message) if token not in stop_words and len(token) > 2}


def recipe_card(record: dict) -> dict:
    title = first_record_value(record, ("Recept", "recipe", "nazov", "názov"))
    cuisine = first_record_value(record, ("Kuchyňa", "Kuchyna", "cuisine"))
    note = first_record_value(record, ("Poznámka", "Poznamka", "note"))
    return {
        "title": title,
        "cuisine": cuisine,
        "note": note,
        "link": first_recipe_link(record, title),
    }


def article_results(knowledge_matches: dict | None, limit: int = 3) -> list[dict]:
    results: list[dict] = []
    seen_titles: set[str] = set()
    for hit in (knowledge_matches or {}).get("Magazine", []):
        article = article_card(hit.get("record", {}))
        title_key = normalize(article.get("title", ""))
        if article["title"] and title_key not in seen_titles:
            seen_titles.add(title_key)
            results.append(article)
        if len(results) >= max(1, min(limit, 3)):
            break
    return results


def recipe_article_results(
    articles: list[dict],
    message: str,
    all_knowledge: dict | None = None,
    limit: int = 3,
) -> list[dict]:
    cuisine = detect_recipe_cuisine(message)
    if not cuisine:
        return articles
    filtered = [article for article in articles if article_matches_cuisine(article, cuisine)]
    if filtered or not all_knowledge:
        return filtered[: max(1, min(limit, 3))]

    results: list[dict] = []
    seen_titles: set[str] = set()
    for record in all_knowledge.get("sections", {}).get("Magazine", []):
        article = article_card(record)
        title_key = normalize(article.get("title", ""))
        if article.get("title") and title_key not in seen_titles and article_matches_cuisine(article, cuisine):
            seen_titles.add(title_key)
            results.append(article)
        if len(results) >= max(1, min(limit, 3)):
            break
    return results


def article_matches_cuisine(article: dict, cuisine: str) -> bool:
    text = normalize(
        " ".join(str(article.get(key, "")) for key in ("title", "topic", "note", "link"))
    )
    has_cuisine = any(marker in text for marker in RECIPE_CUISINE_MARKERS.get(cuisine, ()))
    has_culinary_context = any(marker in text for marker in ARTICLE_CULINARY_MARKERS)
    return has_cuisine and has_culinary_context


def article_card(record: dict) -> dict:
    title = first_record_value(record, ("Clanok", "článok", "article", "nazov", "nĂˇzov"))
    topic = first_record_value(record, ("Tema", "téma", "topic"))
    note = first_record_value(record, ("PoznĂˇmka", "Poznamka", "note"))
    return {
        "title": title,
        "topic": topic,
        "note": note,
        "link": first_article_link(record, title),
    }


def first_record_value(record: dict, markers: tuple[str, ...]) -> str:
    normalized_markers = tuple(normalize(marker) for marker in markers)
    for key, value in record.items():
        normalized_key = normalize(str(key))
        if any(marker in normalized_key for marker in normalized_markers) and value:
            return str(value).strip()
    return ""


def first_recipe_link(record: dict, title: str) -> str:
    # Check hardcoded URL overrides by title
    normalized_title = normalize(title)
    for recipe_key, recipe_url in RECIPE_URL_OVERRIDES.items():
        if recipe_key in normalized_title:
            return recipe_url

    for key, value in record.items():
        text = str(value or "").strip()
        normalized_key = normalize(str(key))
        if text.startswith(("http://", "https://")) and any(
            marker in normalized_key for marker in ("url", "link", "odkaz", "sk", "cz", "en")
        ):
            return text

    if title:
        return f"https://www.foodland.sk/?s={quote_plus(title)}"
    return "https://www.foodland.sk/recepty/"


def first_article_link(record: dict, title: str) -> str:
    for key, value in record.items():
        text = str(value or "").strip()
        normalized_key = normalize(str(key))
        if text.startswith(("http://", "https://")) and any(
            marker in normalized_key for marker in ("sk_url", "url", "link", "odkaz")
        ):
            return text

    if title:
        return f"https://www.foodland.sk/blog/?s={quote_plus(title)}"
    return "https://www.foodland.sk/blog/"


def recipe_answer(subject: str, recipes: list[dict] | None = None) -> str:
    if recipes:
        if len(recipes) == 1:
            return "Našiel som recept z Foodland.sk. Otvorte si ho nižšie."
        return "Našiel som recepty z Foodland.sk. Vyberte si z odporúčaní nižšie."

    return "Receptovú otázku som zachytil, ale nemám dosť detailov na presný recept. Skúste napísať napríklad: recept na kimchi alebo recept na pad thai."


def recipe_products_answer(subject: str | None, recipes: list[dict] | None = None) -> str:
    subject_text = str(subject or "recept").replace("_", " ")
    if recipes:
        return (
            f"Našiel som recept a k nemu relevantné produkty pre {subject_text}. "
            "Najprv dávam kľúčové korenie alebo vývar, potom základ ako rezance či ryžu a nakoniec dochutenie."
        )
    return (
        f"K receptu pre {subject_text} som našiel relevantné produkty. "
        "Sú zoradené od kľúčových surovín po doplnky."
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
    if any(term in normalized_message for term in ("rybi", "rybac")) and "omack" in normalized_message and any(
        marker in normalized_message for marker in ("vegan", "vegans", "nahrad", "alternativ")
    ):
        return "vegan_fish_sauce_replacement"
    if "nepaliv" in normalized_message or "jemne" in normalized_message:
        return "mild"
    return None


def detect_related_subject(message: str) -> str | None:
    normalized_message = normalize(message)
    if not any(marker in normalized_message for marker in RELATED_INTENT_MARKERS):
        return None

    if "pho" in normalized_message:
        return "pho"

    title_subject = recipe_product_subject_from_title(normalized_message)
    if title_subject and title_subject in RELATED_PRODUCT_QUERIES:
        return title_subject

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


def is_article_info_intent(message: str) -> bool:
    normalized_message = normalize(message)
    return any(
        marker in normalized_message
        for marker in (
            "co je",
            "co znamena",
            "ako chuti",
            "ako sa je",
            "ako sa vyraba",
            "aky je rozdiel",
            "rozdiel",
            "preco",
            "benefity",
            "ucinky",
        )
    )


def detect_article_product_subject(message: str, articles: list[dict] | None = None) -> str | None:
    text = normalize(" ".join([message, *[article.get("title", "") for article in articles or []]]))
    if "kimchi" in text or "kimci" in text:
        return "kimchi_article"
    if "pho" in text:
        return "pho_article"
    if "udon" in text and "ramen" in text:
        return "udon_ramen_article"
    if "udon" in text:
        return "udon_article"
    if "ramen" in text or "ramyun" in text:
        return "ramen_article"
    if "tofu" in text:
        return "tofu_article"
    if "shoyu" in text:
        return "shoyu_article"
    if "tamari" in text:
        return "tamari_article"
    if "miso" in text:
        return "miso_article"
    if "matcha" in text:
        return "matcha_article"
    if "mochi" in text:
        return "mochi_article"
    if "bubble tea" in text or "boba" in text:
        return "bubble_tea_article"
    return None


def article_products_for_subject(products_list: list[Product], subject: str, limit: int) -> list[dict]:
    seen: set[str] = set()
    recommendations: list[dict] = []

    for query in ARTICLE_PRODUCT_QUERIES.get(subject, []):
        for product in search_products(products_list, query, max(6, limit)):
            if not is_article_relevant_product(product, subject):
                continue
            key = product.get("id") or product.get("link") or product.get("title")
            if not key or key in seen:
                continue
            seen.add(key)
            recommendations.append(product)
            if len(recommendations) >= limit:
                return recommendations
    return recommendations


def is_article_relevant_product(product: dict, subject: str) -> bool:
    title = normalize(str(product.get("title", "")))
    text = normalize(" ".join(str(product.get(key, "")) for key in ("title", "product_type", "category", "description")))
    title_tokens = set(title.split())

    blocked_markers = (
        "miska",
        "misky",
        "set ",
        "suprava",
        "palicky",
        "podlozka",
        "sushi mat",
        "krek",
        "snack",
        "chips",
        "cukrik",
        "bonbon",
    )
    if any(marker in text for marker in blocked_markers):
        return False

    if subject == "kimchi_article":
        return "kimchi" in title and not any(marker in title for marker in ("ramen", "ramyun", "instant", "polievka"))
    if subject == "pho_article":
        return "pho" in title or "banh pho" in title
    if subject == "udon_article":
        return "udon" in title
    if subject == "ramen_article":
        return "ramen" in title or "ramyun" in title
    if subject == "udon_ramen_article":
        return "udon" in title or "ramen" in title or "ramyun" in title
    if subject == "tofu_article":
        return "tofu" in title and "miso" not in title_tokens and "polievka" not in title_tokens
    if subject == "shoyu_article":
        return "shoyu" in title or ("sojova" in title_tokens and "omacka" in title_tokens)
    if subject == "tamari_article":
        return "tamari" in title_tokens
    if subject == "miso_article":
        return "miso" in title and "polievka" not in title_tokens
    if subject == "matcha_article":
        return "matcha" in title
    if subject == "mochi_article":
        return "mochi" in title
    if subject == "bubble_tea_article":
        return "bubble" in title or "boba" in title or "tapiok" in title
    return True


def detect_already_have_subject(message: str) -> str | None:
    """Detekuje vzor 'mám X / kúpil som X / vlastním X' a vracia kanonický kľúč subjektu."""
    normalized_message = normalize(message)
    # Musí obsahovať marker 'mám' / 'kúpil som' / 'vlastním'
    if not any(marker in normalized_message for marker in ALREADY_HAVE_MARKERS):
        return None
    for subject_key, aliases in ALREADY_HAVE_SUBJECT_MAP.items():
        if any(alias in normalized_message for alias in aliases):
            return subject_key
    return None


def complement_products_for_subject(products_list: list, subject_key: str, limit: int) -> list[dict]:
    """Vráti komplementárne produkty k tomu, čo zákazník už má."""
    seen: set[str] = set()
    recommendations: list[dict] = []
    for query in ALREADY_HAVE_COMPLEMENT_QUERIES.get(subject_key, []):
        for product in search_products(products_list, query, 3):
            key = product.get("id") or product.get("link") or product.get("title")
            if not key or key in seen:
                continue
            seen.add(key)
            recommendations.append(product)
            if len(recommendations) >= limit:
                return recommendations
            break
    return recommendations


def detect_allergen_intent(message: str) -> str | None:
    normalized_message = normalize(message)
    # Recept query bez explicitnej alergenicke otazky -> nie je allergen intent
    _allergen_explicit = ("alerg", "intoler", "bezlepk", "bez soj", "bez lakt", "celiak")
    if "recept" in normalized_message and not any(e in normalized_message for e in _allergen_explicit):
        return None
    if any(term in normalized_message for term in ("rybi", "rybac")) and "omack" in normalized_message and any(
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

    if "bezlepk" in normalized_message:
        return "lepok"

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
        normalized_after_question = normalize(after_question)
        if is_generic_allergen_recommendation_tail(normalized_after_question):
            return ""
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
    cleaned = " ".join(cleaned.split())
    if is_generic_allergen_recommendation_tail(cleaned):
        return ""
    return cleaned


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
    if "bez" in normalized_message:
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
        normalized_after_question = normalize(after_question)
        if is_generic_allergen_recommendation_tail(normalized_after_question):
            return ""
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
    cleaned = " ".join(cleaned.split())
    if is_generic_allergen_recommendation_tail(cleaned):
        return ""
    return cleaned


def is_generic_allergen_recommendation_tail(normalized_text: str) -> bool:
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", normalized_text)
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return True
    generic_markers = (
        "co by ste odporucili",
        "co odporucate",
        "co odporucas",
        "co by ste doporucili",
        "co by ste dopurucili",
        "co doporucujete",
        "co dopurucujete",
        "poradite",
        "poradis",
        "ake produkty",
        "co mam kupit",
        "co si mam kupit",
    )
    if any(marker in cleaned for marker in generic_markers):
        return True
    generic_words = {
        "co",
        "by",
        "ste",
        "mi",
        "prosim",
        "odporucili",
        "odporucate",
        "odporucas",
        "doporucili",
        "doporucujete",
        "dopurucili",
        "dopurucujete",
        "poradite",
        "poradis",
        "kupit",
        "produkty",
    }
    tokens = set(cleaned.split())
    return bool(tokens) and tokens <= generic_words


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
    if allergen_term in ("alergeny", "alerginy"):
        return (
            "Pri alergènoch vám nechcem odporučiť nesprávny produkt. "
            "Prosím overte zloženie v detaile konkrétneho produktu alebo nám napíšte názov produktu, "
            "ktorý chcete skontrolovať."
        )

    if allergen_term in ("vhodnost pre veganov", "vhodnosť pre veganov"):
        return (
            "Rozumiem, že ste vegán. V Foodland.sk máme viaceré produkty vhodné pre vegánov "
            "— rastlinné omáčky, kokosové mlieko, tofu, tempeh a iné. "
            "Odporúčam použiť filter alebo nám napísať čo konkrétne hľadáte."
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
            if not is_recipe_relevant_product(product, subject):
                continue
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


def is_recipe_relevant_product(product: dict, subject: str | None = None) -> bool:
    text = normalize(" ".join(str(product.get(key, "")) for key in ("title", "product_type", "category", "description")))
    blocked_markers = (
        "podlozka",
        "sushi mat",
        "miska",
        "misky",
        "set ",
        "suprava",
        "palicky",
        "dekor",
        "ozdoby",
        "solarna",
        "macka stastia",
        "vonna tycinka",
        "ananasova cili",
    )
    if any(marker in text for marker in blocked_markers):
        return False

    snack_markers = ("krek", "snack", "pocky", "cukrik", "bonbon", "chips")
    subject_allows_snacks = subject in {"asian_snack", "azijske_dezerty", "mochi", "matcha", "bubble_tea", "mango_sticky_rice"}
    if not subject_allows_snacks and any(marker in text for marker in snack_markers):
        return False

    return True


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


async def feed_refresh_loop(refresh_minutes: int) -> None:
    """Periodicky obnovi produktovy feed a prebuduje knowledge databazu."""
    global last_feed_refresh_error
    while True:
        await asyncio.sleep(refresh_minutes * 60)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(refresh_feed),
                timeout=90.0,
            )
        except asyncio.TimeoutError:
            last_feed_refresh_error = "feed_refresh_timeout"
            logger.error("Feed refresh timed out after 90s.")
        except Exception as exc:
            last_feed_refresh_error = str(exc)
            logger.error("Feed refresh failed: %s", exc, exc_info=True)
        else:
            try:
                await asyncio.wait_for(rebuild_knowledge_from_feed(), timeout=300.0)
            except asyncio.TimeoutError:
                logger.error("Knowledge rebuild timed out after 300s.")
            except Exception as exc:
                logger.error("Knowledge rebuild failed: %s", exc, exc_info=True)


def refresh_feed() -> None:
    """Nacita produkty zo vsetkych jazykovych mutacii feedu (SK/CZ/DE/EN/HU/PL)."""
    global products, product_snapshot, translation_index
    global last_feed_refresh_at, last_feed_refresh_error

    lang_feeds = load_multilang_feeds()
    new_products = lang_feeds.get('sk', [])
    new_translation_index = multilang_translation_index(lang_feeds)
    products = new_products
    product_snapshot = build_product_snapshot(new_products)
    translation_index = new_translation_index
    last_feed_refresh_at = int(time.time())
    last_feed_refresh_error = None
    logger.info(
        "Feed refreshed: %d products, langs=%s",
        len(products),
        list(new_translation_index.keys()),
    )


async def rebuild_knowledge_from_feed() -> None:
    """Prebuduje knowledge.json z aktualnych produktov a ulozi na disk."""
    global knowledge, product_snapshot
    knowledge_path = os.getenv("KNOWLEDGE_JSON_PATH", "data/knowledge.json")
    openai_client = _get_openai_client()

    logger.info("Starting knowledge rebuild from feed (%d products)...", len(products))
    new_knowledge, new_snapshot = await asyncio.to_thread(
        build_knowledge,
        products,
        knowledge,
        old_snapshot=product_snapshot,
        translation_index=translation_index,
        openai_client=openai_client,
    )
    await asyncio.to_thread(save_knowledge, new_knowledge, knowledge_path)
    knowledge = new_knowledge
    product_snapshot = new_snapshot
    logger.info("Knowledge rebuilt successfully: %s", new_knowledge.get("counts", {}))
