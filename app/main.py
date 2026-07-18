from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import tempfile
import time
from collections import defaultdict, deque
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
from app.search import normalize, products_context, search_products, tokenize


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
# Knowledge-builder state
product_snapshot: ProductSnapshot = build_product_snapshot(products)
translation_index: dict[str, dict[str, "Product"]] = {}
rate_limit_events: dict[str, deque[float]] = defaultdict(deque)
_RATE_LIMIT_MAX_CLIENTS = 50_000  # BUG-02: ochrana pamate – max pocet trackovanych klientov
DEFAULT_RUNTIME_LOG_DIR = Path(tempfile.gettempdir()) / "foodland-ai-agent"

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
        "jazi,nova ryza",
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
        "sezamovy olej",
        "sojova omacka",
        "kimchi",
    ],
    "tom_yum": [
        "rybacia omacka",
        "kokosove mlieko",
        "sriracha",
        "ryzove rezance",
    ],
    "japchae": [
        "sojova omacka",
        "sezamovy olej",
        "ryzove rezance",
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
    "bun_bo_hue": [
        "rybacia omacka", "ryzove rezance", "citronova trava", "sojova omacka", "sriracha",
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
        "sojova omacka", "sezamovy olej", "ustricova omacka", "zazvor", "hoisin omacka",
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
    "yukgaejang": [
        "gochujang", "sojova omacka", "sezamovy olej", "ryzovy ocot",
    ],
    "bossam": [
        "gochujang", "sojova omacka", "sezamovy olej", "kimchi",
    ],
    "special_occasion": [
        "sushi ryza", "nori", "wasabi", "ryzovy ocot",
        "sojova omacka", "sezamovy olej", "jazminova ryza",
    ],
}

RELATED_SUBJECT_ALIASES = {
    "kimchi": ("kimchi", "kimci"),
    "sushi": ("sushi", "susi", "sushi ryza", "susi ryza", "maki", "maki rolky", "california roll", "futomaki", "hosomaki", "uramaki", "nigiri", "temaki", "sashimi"),
    "gochujang": ("gochujang", "gochu jang", "gochuang"),
    "ramen": ("ramen", "ramyun", "ramyeon", "tonkotsu", "tantanmen", "noodle soup", "noodle broth", "soup noodles"),
    "kari": ("kari", "curry"),
    "pho": ("pho",),
    "pad_thai": ("pad thai", "padthai"),
    "bibimbap": ("bibimbap",),
    "gyoza": ("gyoza", "gyozu", "gyozy", "gyozou"),
    "poke_bowl": ("poke bowl", "poke", "poke boul"),
    "korejsky_gril": ("korejsky gril", "korejsky bbq", "korejsky barbecue", "kbbq", "korean bbq"),
    "thajske_kari": ("thajske kari", "thajske curry", "thajsky curry", "thajskeho curry", "thai curry"),
    "sojova_omacka": ("sojovej omacke", "k sojovej omacke", "doplnky k sojovej", "sojova omacka"),
    "wok": ("woku", "wok", "stir fry", "stir-fry", "na woku", "smaz", "smazit", "smazenie", "vysmaz"),
    "beginner_kit": ("zacinam azijsky", "zacinam varit azijsky", "zacinam s azijskou", "azijska spajza", "co si kupit ako prv", "zacinam varit", "prvy krat azij", "prvy krat varit azij", "krat korejsk", "krat japonsk", "krat thajsk", "krat cinsk", "azijsk", "azijskeho", "azijsku kuchyn", "azijske jedlo", "azijsku vecer", "nieco azij", "nejake azij", "asian", "east asian", "southeast asian", "spicy asian", "vegetarian asian", "vegan asian", "asijsk", "asijsku", "asijskej",
        "azijsk", "azijsku", "azijskej", "azia", "azii", "azijsky"),
    "azijske_dezerty": ("azijske dezerty", "azijsky dezert", "na dezert", "dezert ky"),
    "jarne_zavitky": ("jarne zavitky", "spring rolls", "jarnych zavitkov", "jarne rolky", "nemecke zavitky"),
    "teriyaki": ("teriyaki", "teriyaki kuracie", "teriyaki losos", "teriyaki omacku"),
    "miso_polievka": ("miso", "miso polievku", "miso polievka", "miso soup", "miso sopu", "miso polevku", "miso polievky", "miso polievke"),
    "fried_rice": ("fried rice", "smazena ryza", "vysmazena ryza", "ryza na panvici", "vyprazana ryza", "vyprazanu ryzu", "smazenu ryzu", "smaza ryzu", "smazim ryzu", "rice dish", "rice bowl", "rice meal"),
    "bulgogi": ("bulgogi", "galbi", "galby", "galbi jjim"),
    "tteokbokki": ("tteokbokki", "ddukbokki", "tteok", "dduk"),
    "tom_yum": ("tom yum", "tom yam", "tom kha"),
    "japchae": ("japchae", "jap chae", "korejske sklenene rezance"),
    "vietnamska_kuchyna": ("vietnamsku kuchynu", "vietnamska kuchyna", "vietnamska vecera", "vietnam", "vietnamsk"),
    "japonska_kuchyna": ("japonsku kuchynu", "japonska kuchyna", "japonska vecera", "japonsku veceru", "japonsk", "japansk", "japanese", "j-food", "j food"),
    "korejska_kuchyna": ("korejsku kuchynu", "korejska kuchyna", "korejska vecera", "korejsku veceru", "korejsk", "korean", "k-food", "k food"),
    "thajska_kuchyna": ("thajsku kuchynu", "thajska kuchyna", "thajska vecera", "thajsku veceru", "thajsk", "thai"),
    "cinska_kuchyna": ("cinsku kuchynu", "cinska kuchyna", "cinska vecera", "cinsku veceru", "cinsk", "chinese"),
    "pad_thai": ("pad thai", "padthai", "pad-thai"),
    "tempura": ("tempura", "tempuru", "tempury", "tempurou", "tempur"),
    "okonomiyaki": ("okonomiyaki",),
    "takoyaki": ("takoyaki",),
    "shabu_shabu": ("shabu shabu", "shabu-shabu", "hot pot", "hotpot", "hot-pot", "hot potu", "hotpotu"),
    "onigiri": ("onigiri", "ryżové gulky", "ryzove gulky", "ryzove gulky", "onigiri"),
    "yakisoba": ("yakisoba", "yaki soba", "yakisobu", "yaki sobu", "yakisoby"),
    "udon": ("udon", "udonom", "udonove nudle", "udonovu polievku"),
    "soba": ("soba", "soba nudle", "soba rezance", "sobove nudle"),
    "mandu": ("mandu",),
    "wonton": ("wonton", "wonton soup", "wontonova polievka"),
    "laksa": ("laksa",),
    "banh_mi": ("banh mi",),
    "congee": ("congee", "ryzova kasa", "ryzovu kasu"),
    "matcha": ("matcha",),
    "mochi": ("mochi",),
    "bubble_tea": ("bubble tea", "boba", "boba tea", "bubble tea"),
    "edamame": ("edamame",),
    "tonkatsu": ("tonkatsu",),
    "agedashi_tofu": ("agedashi tofu", "agedashi",),
    "nori_rolky": ("nori rolky", "nori wrap", "nori sheet"),
    "dashi_vyvar": ("dashi vyvar", "dashi vyvaru", "dashi polievka"),
    "japansk": ("japanske ranajky", "japanska snidana"),
    "grilovanie": ("grilovacku", "grilovat", "grilovanie", "na gril", "grilu", "grilovacky"),
    "asian_snack": ("k filmu", "k serialu", "na film", "na serial", "k pivu azij", "snack azij"),
    "tom_yum": ("tom yum", "tom yum polievka", "thajska polievka", "thajskej polievky", "tom yum soup"),
    "jjigae": ("jjigae", "sundubu jjigae", "sundubu", "doenjang jjigae", "doenjang", "korejsky stew"),
    "nam_van": ("nam van", "goi cuon", "vietnamske rolky", "cerstve rolky"),
    "sukiyaki": ("sukiyaki",),
    "bao_bun": ("bao bun", "bao", "baozi", "parovany bun", "parovane buchty"),
    "gyudon": ("gyudon", "hovaezi don", "beef bowl"),
    "oyakodon": ("oyakodon", "oyako don"),
    "karaage": ("karaage",),
    "tonkatsu": ("tonkatsu",),
    "gyoza": ("gyoza", "jiaozi"),
    "yakitori": ("yakitori",),
    "adobo": ("adobo", "filipino adobo"),
    "malatang": ("malatang", "mala tang", "mala hotpot"),
    "jajangmyeon": ("jajangmyeon", "jajangmyon", "black bean noodles"),
    "asian_noodles": ("asian noodles", "asian noodle", "stir fry noodles"),
    "medium_spicy": ("spicy food", "hot food", "spicy dinner", "spicy meal", "pikantne jedlo", "horuce jedlo", "hot sauce", "chili sauce", "sriracha dinner"),
    "bento": ("bento", "bento box", "bento lunch"),
    "yangnyeom_chicken": ("yangnyeom chicken", "yangnyeom", "chimaek", "korean fried chicken", "korean chicken"),
    "samgyeopsal": ("samgyeopsal", "pork belly"),
    "bun_bo_hue": ("bun bo hue", "bun bo"),
    "banh_xeo": ("banh xeo",),
    "mapo_tofu": ("mapo tofu", "mapo"),
    "kung_pao": ("kung pao", "kung pao chicken"),
    "dim_sum": ("dim sum", "dimsum", "dumpling", "dumplingy"),
    "dakgalbi": ("dakgalbi",),
    "char_siu": ("char siu", "char-siu", "cinsky bbq"),
    "som_tam": ("som tam", "som tum", "papajovy salat"),
    "nasi_goreng": ("nasi goreng",),
    "mee_goreng": ("mee goreng", "mi goreng"),
    "rendang": ("rendang",),
    "larb": ("larb",),
    "chow_mein": ("chow mein", "chowmein", "chow-mein"),
    "satay": ("satay", "sate", "satay kura"),
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
    "special_occasion": (
        "svadba", "svadb", "narodeninov", "narozenin", "vianoc", "silvester",
        "novy rok", "sviatok", "romantick", "specialn",
        "priatelk", "anniversary", "wedding", "birthday", "christmas",
        "new year", "date night", "valentin",
        "vikend", "nedel", "sobot", "dnes", "dnesna",
        "host", "hosti", "ludi", "clovek", "osob",
    ),
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
    "ryza": ("ryzu", "ryzou", "ryzy", "bielu ryzu", "jasminovu ryzu", "sushi ryzu"),
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
    if allergen_term and not detect_related_subject(chat_request.message):
        allergen_matches = allergen_product_matches(chat_request.message, chat_request.limit)
        log_question(chat_request.message, client_key, len(allergen_matches))
        return {
            "answer": allergen_safety_answer(allergen_term),
            "products": allergen_matches,
            "knowledge": knowledge_summary(knowledge_matches),
            "intent": "allergen_safety",
        }

    faq_answer = None
    if is_faq_intent(chat_request.message):
        faq_answer = best_direct_faq_answer(chat_request.message, knowledge) or best_faq_answer(knowledge_matches)
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
        recipes = recipe_results(knowledge_matches, chat_request.limit, chat_request.message, knowledge)
        log_question(chat_request.message, client_key, 0)
        return {
            "answer": recipe_answer(recipe_subject, recipes),
            "recipes": recipes,
            "products": [],
            "knowledge": knowledge_summary(knowledge_matches),
            "intent": "recipe",
        }

    if detect_out_of_domain(chat_request.message) and not detect_related_subject(chat_request.message):
        log_question(chat_request.message, client_key, 0)
        return {
            "answer": "Na toto neviem spoľahlivo odpovedať ako Foodland poradca. Skúste sa opýtať na produkty, objednávku, dopravu alebo platbu na Foodland.sk.",
            "products": [],
            "knowledge": knowledge_summary(knowledge_matches),
            "intent": "unknown",
        }

    already_have_subject = detect_already_have_subject(chat_request.message)
    special_subject = detect_special_product_subject(chat_request.message)
    related_subject = detect_related_subject(chat_request.message)
    needs_composition_caution = is_composition_caution_search(chat_request.message)
    if already_have_subject:
        matches = complement_products_for_subject(products, already_have_subject, chat_request.limit)
    elif special_subject:
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

    client = _get_openai_client()
    if not client:
        logger.debug("No OPENAI_API_KEY set, using fallback answer.")
        return {
            "answer": fallback_answer(matches, knowledge_matches, related_subject, needs_composition_caution),
            "products": matches,
            "knowledge": knowledge_summary(knowledge_matches),
            "intent": "related_products" if (related_subject or already_have_subject) else "product_search",
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
                ),
            },
        ]
        # Pridaj historiu konverzacie (max 10 sprav)
        for msg in chat_request.conversation_history[-10:]:
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
            "knowledge": knowledge_summary(knowledge_matches),
            "intent": "related_products" if (related_subject or already_have_subject) else "product_search",
        }
    except (RateLimitError, APITimeoutError, APIConnectionError) as exc:
        logger.warning("OpenAI transient error after retries: %s", exc)
        log_backend_error("openai_transient_error", str(exc))
        return {
            "answer": fallback_answer(matches, knowledge_matches, related_subject, needs_composition_caution),
            "products": matches,
            "knowledge": knowledge_summary(knowledge_matches),
            "warning": "Služba je momentálne preťažená, zobrazujem nájdené produkty.",
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


def log_question(message: str, client_key: str, matches_count: int) -> None:
    path = Path(os.getenv("ANALYTICS_LOG_PATH", str(DEFAULT_RUNTIME_LOG_DIR / "question_analytics.jsonl")))
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


def is_recipe_intent(normalized_message: str) -> bool:
    if any(marker in normalized_message for marker in RECIPE_INTENT_MARKERS):
        return True
    return any(token.startswith(("rec", "recep")) for token in tokenize(normalized_message))


def recipe_results(
    knowledge_matches: dict | None,
    limit: int = 4,
    message: str = "",
    all_knowledge: dict | None = None,
) -> list[dict]:
    recipes = (knowledge_matches or {}).get("Recipes", [])
    results: list[dict] = []
    seen_titles: set[str] = set()
    wanted_tokens = recipe_query_tokens(message)

    if not recipes and not wanted_tokens and all_knowledge:
        recipes = [
            {"record": record}
            for record in all_knowledge.get("sections", {}).get("Recipes", [])
        ]

    for item in recipes:
        record = item.get("record", {})
        recipe = recipe_card(record)
        title_key = normalize(recipe.get("title", ""))
        recipe_tokens = tokenize(" ".join([recipe.get("title", ""), recipe.get("cuisine", "")]))
        if wanted_tokens and not (wanted_tokens & recipe_tokens):
            continue
        if recipe["title"] and title_key not in seen_titles:
            seen_titles.add(title_key)
            results.append(recipe)
        if len(results) >= max(1, min(limit, 4)):
            break

    return results


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
    }
    return {token for token in tokenize(message) if token not in stop_words and len(token) > 1}


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


def first_record_value(record: dict, markers: tuple[str, ...]) -> str:
    normalized_markers = tuple(normalize(marker) for marker in markers)
    for key, value in record.items():
        normalized_key = normalize(str(key))
        if any(marker in normalized_key for marker in normalized_markers) and value:
            return str(value).strip()
    return ""


def first_recipe_link(record: dict, title: str) -> str:
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


def recipe_answer(subject: str, recipes: list[dict] | None = None) -> str:
    if recipes:
        if len(recipes) == 1:
            return "Našiel som recept z Foodland.sk. Otvorte si ho nižšie."
        return "Našiel som recepty z Foodland.sk. Vyberte si z odporúčaní nižšie."

    return "Receptovú otázku som zachytil, ale nemám dosť detailov na presný recept. Skúste napísať napríklad: recept na kimchi alebo recept na pad thai."


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
    if not any(marker in normalized_message for marker in RELATED_INTENT_MARKERS):
        return None

    if "pho" in normalized_message:
        return "pho"

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
    if "rybi" in normalized_message and "omack" in normalized_message and any(
        marker in normalized_message for marker in ("vegan", "vegans", "nahrad", "alternativ")
    ):
        return None
    if "bezlepk" in normalized_message:
        return "lepok"
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
