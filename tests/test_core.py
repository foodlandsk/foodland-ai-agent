"""
tests/test_core.py  -  Golden test suite (pytest)

Spustenie:
    pytest tests/test_core.py -v

Pokryva:
- search.py: normalize, tokenize, search_products, ranking
- knowledge.py: search_knowledge, best_faq_answer
- grounding.py: validate_answer, URL stripping, price check
- workflows.py: detect_workflow, get_contract, feature flags
- main.py: intent detekcia, allergen safety, FAQ routing, out-of-domain

Nevyzaduje OPENAI_API_KEY - testuje offline logiku.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import types
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _install_stubs():
    if "pydantic" in sys.modules:
        return
    pydantic = types.ModuleType("pydantic")
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    pydantic.BaseModel = BaseModel
    pydantic.Field = lambda default=None, **kw: default
    sys.modules["pydantic"] = pydantic

    fastapi = types.ModuleType("fastapi")
    class FastAPI:
        def __init__(self, **kw): pass
        def mount(self, *a, **kw): pass
        def add_middleware(self, *a, **kw): pass
        def get(self, *a, **kw): return lambda f: f
        def post(self, *a, **kw): return lambda f: f
        def on_event(self, *a, **kw): return lambda f: f
    fastapi.FastAPI = FastAPI
    fastapi.Header = lambda default=None: default
    fastapi.HTTPException = type("HTTPException", (Exception,), {
        "__init__": lambda s, status_code=None, detail=None: None
    })
    fastapi.Request = object
    cors_mod = types.ModuleType("fastapi.middleware.cors")
    cors_mod.CORSMiddleware = object
    static_mod = types.ModuleType("fastapi.staticfiles")
    static_mod.StaticFiles = type("StaticFiles", (), {
        "__init__": lambda s, **kw: None,
        "file_response": lambda s, *a, **kw: types.SimpleNamespace(headers={}),
    })
    for name, mod in [
        ("fastapi", fastapi),
        ("fastapi.middleware", types.ModuleType("fastapi.middleware")),
        ("fastapi.middleware.cors", cors_mod),
        ("fastapi.staticfiles", static_mod),
        ("openai", types.ModuleType("openai")),
    ]:
        sys.modules[name] = mod
    class _OpenAIError(Exception):
        pass
    sys.modules["openai"].OpenAI = lambda **kw: None
    sys.modules["openai"].RateLimitError = type("RateLimitError", (_OpenAIError,), {})
    sys.modules["openai"].APITimeoutError = type("APITimeoutError", (_OpenAIError,), {})
    sys.modules["openai"].APIConnectionError = type("APIConnectionError", (_OpenAIError,), {})
    os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

_install_stubs()

from app.autocomplete import (
    autocomplete_brands,
    autocomplete_categories,
    autocomplete_products,
    autocomplete_questions,
)
from app.feed import load_products_json
from app.search import (
    autocomplete_suggestions,
    clear_merchandising_cache,
    compute_product_facets,
    filter_products,
    get_merchandising_rules,
    normalize,
    tokenize,
    search_products,
)
from app.knowledge import load_knowledge_json, search_knowledge, best_faq_answer
from app.grounding import validate_answer, collect_allowed_urls, collect_allowed_prices
from app.workflows import detect_workflow, get_contract, products_to_cart_candidates
import app.main as main
import app.merchandising as merchandising
import app.search as search_module


@pytest.fixture(scope="session")
def products():
    path = ROOT / "data" / "products.json"
    if not path.exists():
        pytest.skip("products.json not found")
    return load_products_json(path)


@pytest.fixture(scope="session")
def knowledge():
    path = ROOT / "data" / "knowledge.json"
    if not path.exists():
        pytest.skip("knowledge.json not found")
    return load_knowledge_json(path)


def nrm(v: str) -> str:
    a = unicodedata.normalize("NFKD", str(v)).encode("ascii", "ignore").decode("ascii")
    return " ".join(a.casefold().replace("-", " ").replace("/", " ").split())


def titles_contain(results, *terms) -> bool:
    all_titles = " | ".join(r.get("title", "") for r in results)
    return any(nrm(t) in nrm(all_titles) for t in terms)


def top3_contains(results, term) -> bool:
    top = " | ".join(r.get("title", "") for r in results[:3])
    return nrm(term) in nrm(top)


def compact_product_title(title: str) -> str:
    text = re.sub(r"\b\d+[,.]?\d*\s*(g|kg|ml|l|ks|cm|mm|listov)\b", " ", title, flags=re.I)
    text = re.sub(r"\b\d+\s*[x×]\s*\d+\b", " ", text, flags=re.I)
    text = re.sub(r"[^\w\s-]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split()) or title


class TestNormalize:
    def test_strips_diacritics(self):
        assert normalize("gochujang") == "gochujang"
        assert normalize("Susi ryza") == "susi ryza"
        assert normalize("Bezlepkova sojova omacka") == "bezlepkova sojova omacka"

    def test_lowercases(self):
        assert normalize("KIMCHI") == "kimchi"

    def test_empty(self):
        assert normalize("") == ""


class TestTokenize:
    def test_basic(self):
        tokens = tokenize("gochujang pasta")
        assert "gochujang" in tokens

    def test_sushi_alias(self):
        tokens = tokenize("susi ryza")
        assert "sushi" in tokens
        assert "susi" in tokens

    def test_bezlepk_expansion(self):
        tokens = tokenize("bezlepkova sojova omacka")
        assert "bezlepkova" in tokens
        assert "bezlepkovy" in tokens

    def test_english_fish_sauce(self):
        tokens = tokenize("fish sauce")
        assert "rybacia" in tokens
        assert "omacka" in tokens

    def test_gochujang_typos(self):
        tokens = tokenize("gochuang")
        assert "gochujang" in tokens
        tokens2 = tokenize("gochudang")
        assert "gochujang" in tokens2

    def test_sriracha_typos(self):
        tokens = tokenize("sriraca")
        assert "sriracha" in tokens

    def test_stopwords_removed(self):
        tokens = tokenize("co je na to")
        assert "co" not in tokens
        assert "je" not in tokens
        assert "na" not in tokens


class TestCzechEnglishSynonyms:
    def test_english_oyster_sauce_phrase(self):
        tokens = tokenize("oyster sauce")
        assert "ustricova" in tokens
        assert "omacka" in tokens

    def test_english_sesame_oil_phrase(self):
        tokens = tokenize("sesame oil")
        assert "sezamovy" in tokens
        assert "olej" in tokens

    def test_english_curry_paste_phrase(self):
        tokens = tokenize("curry paste")
        assert "kari" in tokens
        assert "pasta" in tokens

    def test_english_bamboo_shoots_phrase(self):
        tokens = tokenize("bamboo shoots")
        assert "bambusove" in tokens
        assert "vyhonky" in tokens

    def test_english_ingredient_tokens(self):
        assert "zazvor" in tokenize("ginger")
        assert "cesnak" in tokenize("garlic")
        assert "kari" in tokenize("curry powder")
        assert "krevety" in tokenize("shrimp")
        assert "arasidy" in tokenize("peanuts")
        assert "huby" in tokenize("mushroom")

    def test_czech_word_forms(self):
        assert "ryza" in tokenize("ryze")
        assert "cesnak" in tokenize("cesnek")
        assert "huby" in tokenize("houby")
        assert "cukor" in tokenize("cukr")
        assert "sol" in tokenize("sul")
        assert "polievka" in tokenize("polevka")
        assert "korenie" in tokenize("koreni")
        assert "muka" in tokenize("mouka")
        assert "cestoviny" in tokenize("testoviny")
        assert "cibula" in tokenize("cibule")
        assert "kuracie" in tokenize("kureci")
        assert "bravcove" in tokenize("veprove")
        assert "hovadzie" in tokenize("hovezi")

    def test_czech_coconut_milk_phrase(self):
        tokens = tokenize("kokosove mleko")
        assert "kokosove" in tokens
        assert "mlieko" in tokens

    def test_czech_fish_sauce_phrase(self):
        tokens = tokenize("rybi omacka")
        assert "rybacia" in tokens
        assert "omacka" in tokens

    def test_search_products_finds_sesame_oil_via_english(self, products):
        results = search_products(products, "sesame oil", 5)
        assert titles_contain(results, "sezamov")

    def test_search_products_finds_ginger_via_english(self, products):
        results = search_products(products, "ginger", 5)
        assert results

    def test_search_products_finds_rice_via_czech(self, products):
        results = search_products(products, "ryze", 5)
        assert results


class TestMerchandising:
    def test_load_merchandising_rules_missing_file_returns_defaults(self, tmp_path):
        rules = merchandising.load_merchandising_rules(str(tmp_path / "does_not_exist.json"))

        assert rules == {"pins": [], "hidden": set(), "boosts": [], "campaigns": []}

    def test_load_merchandising_rules_from_file(self, tmp_path):
        path = tmp_path / "merchandising.json"
        path.write_text(
            json.dumps({
                "pins": [{"sku": "FL_1", "query": "ramen", "position": 1}],
                "hidden": ["FL_999"],
                "boosts": [{"brand": "Ottogi", "multiplier": 1.5}],
                "campaigns": [{"name": "Summer", "active_from": "2020-01-01", "active_to": "2099-12-31", "category": "Omacky", "boost": 2.0}],
            }),
            encoding="utf-8",
        )

        rules = merchandising.load_merchandising_rules(str(path))

        assert rules["pins"] == [{"sku": "FL_1", "query": "ramen", "position": 1}]
        assert rules["hidden"] == {"FL_999"}
        assert rules["boosts"][0]["brand"] == "Ottogi"

    def test_load_merchandising_rules_malformed_json_returns_defaults(self, tmp_path):
        path = tmp_path / "merchandising.json"
        path.write_text("{not valid json", encoding="utf-8")

        rules = merchandising.load_merchandising_rules(str(path))

        assert rules == {"pins": [], "hidden": set(), "boosts": [], "campaigns": []}

    def test_is_hidden(self):
        rules = {"hidden": {"FL_999"}}
        assert merchandising.is_hidden("FL_999", rules) is True
        assert merchandising.is_hidden("FL_1", rules) is False

    def test_campaign_is_active_within_range(self):
        campaign = {"active_from": "2020-01-01", "active_to": "2099-12-31"}
        assert merchandising.campaign_is_active(campaign, date(2026, 1, 1)) is True

    def test_campaign_is_active_before_start(self):
        campaign = {"active_from": "2099-01-01", "active_to": "2099-12-31"}
        assert merchandising.campaign_is_active(campaign, date(2026, 1, 1)) is False

    def test_campaign_is_active_after_end(self):
        campaign = {"active_from": "2020-01-01", "active_to": "2020-12-31"}
        assert merchandising.campaign_is_active(campaign, date(2026, 1, 1)) is False

    def test_campaign_is_active_no_dates_means_always_active(self):
        assert merchandising.campaign_is_active({}, date(2026, 1, 1)) is True

    def test_merchandising_multiplier_brand_boost(self):
        rules = {"boosts": [{"brand": "Ottogi", "multiplier": 1.5}], "campaigns": []}

        assert merchandising.merchandising_multiplier("Ottogi", "Ramen", rules) == 1.5
        assert merchandising.merchandising_multiplier("Nongshim", "Ramen", rules) == 1.0

    def test_merchandising_multiplier_active_campaign(self):
        rules = {"boosts": [], "campaigns": [{"category": "grilovacie omacky", "boost": 2.0, "active_from": "2020-01-01", "active_to": "2099-12-31"}]}

        multiplier = merchandising.merchandising_multiplier("Any", "Grilovacie omacky > Omacky", rules, today=date(2026, 7, 1))

        assert multiplier == 2.0

    def test_merchandising_multiplier_inactive_campaign_has_no_effect(self):
        rules = {"boosts": [], "campaigns": [{"category": "grilovacie omacky", "boost": 2.0, "active_from": "2020-01-01", "active_to": "2020-12-31"}]}

        multiplier = merchandising.merchandising_multiplier("Any", "Grilovacie omacky > Omacky", rules, today=date(2026, 7, 1))

        assert multiplier == 1.0

    def test_merchandising_multiplier_campaign_matches_despite_diacritics(self):
        # Rule authored in plain ASCII must still match the catalog's actual
        # accented Slovak category text (e.g. "Sojove omacky" -> "Sójové omáčky").
        rules = {"boosts": [], "campaigns": [{"category": "sojove omacky", "boost": 5.0, "active_from": "2020-01-01", "active_to": "2099-12-31"}]}

        multiplier = merchandising.merchandising_multiplier("KIKKOMAN", "Sójové omáčky > Omáčky a marinády", rules, today=date(2026, 7, 1))

        assert multiplier == 5.0

    def test_merchandising_multiplier_brand_boost_matches_despite_diacritics(self):
        rules = {"boosts": [{"brand": "znacka s diakritikou", "multiplier": 3.0}], "campaigns": []}

        multiplier = merchandising.merchandising_multiplier("Značka s diakritikou", "Any", rules)

        assert multiplier == 3.0

    def test_merchandising_multiplier_stacks_boost_and_campaign(self):
        rules = {
            "boosts": [{"brand": "Ottogi", "multiplier": 1.5}],
            "campaigns": [{"category": "ramen", "boost": 2.0, "active_from": "2020-01-01", "active_to": "2099-12-31"}],
        }

        multiplier = merchandising.merchandising_multiplier("Ottogi", "Ramen", rules, today=date(2026, 7, 1))

        assert multiplier == 3.0

    def test_pins_for_query_matches_substring(self):
        rules = {"pins": [{"sku": "FL_1", "query": "ramen", "position": 1}]}

        assert merchandising.pins_for_query("najlepsi ramen", rules) == rules["pins"]
        assert merchandising.pins_for_query("sushi", rules) == []

    def test_pins_for_query_unconditional_pin_matches_everything(self):
        rules = {"pins": [{"sku": "FL_1", "position": 1}]}

        assert merchandising.pins_for_query("anything", rules) == rules["pins"]


class TestMerchandisingIntegration:
    def _set_rules(self, monkeypatch, rules):
        monkeypatch.setattr(search_module, "_merchandising_rules_cache", rules)
        monkeypatch.setattr(search_module, "_merchandising_rules_cache_at", time.time())

    def test_hidden_product_excluded_from_search(self, products, monkeypatch):
        target = next(p for p in products if p.title)
        self._set_rules(monkeypatch, {"pins": [], "hidden": {target.id}, "boosts": [], "campaigns": []})

        results = search_products(products, target.title, 10)

        assert all(r["id"] != target.id for r in results)

    def test_boost_promotes_matching_brand_to_top(self, products, monkeypatch):
        baseline = search_products(products, "omacka", 10)
        assert len(baseline) >= 2
        target_brand = next((r["brand"] for r in baseline[1:] if r.get("brand")), None)
        assert target_brand

        self._set_rules(monkeypatch, {
            "pins": [], "hidden": set(), "boosts": [{"brand": target_brand, "multiplier": 1000.0}], "campaigns": [],
        })

        boosted = search_products(products, "omacka", 10)

        assert boosted[0]["brand"] == target_brand

    def test_pin_forces_product_to_requested_position(self, products, monkeypatch):
        baseline = search_products(products, "omacka", 5)
        assert baseline
        baseline_ids = {r["id"] for r in baseline}
        other = next(p for p in products if p.id not in baseline_ids and p.title)

        self._set_rules(monkeypatch, {
            "pins": [{"sku": other.id, "query": "omacka", "position": 1}],
            "hidden": set(), "boosts": [], "campaigns": [],
        })

        results = search_products(products, "omacka", 5)

        assert results[0]["id"] == other.id

    def test_get_merchandising_rules_reads_from_env_path(self, tmp_path, monkeypatch):
        path = tmp_path / "merchandising.json"
        path.write_text(json.dumps({"pins": [], "hidden": ["FL_1"], "boosts": [], "campaigns": []}), encoding="utf-8")
        monkeypatch.setenv("MERCHANDISING_JSON_PATH", str(path))
        clear_merchandising_cache()

        rules = get_merchandising_rules()

        assert rules["hidden"] == {"FL_1"}
        clear_merchandising_cache()


class TestSearchProducts:
    def test_sushi_rice_not_vinegar(self, products):
        results = search_products(products, "sushi ryza", 6)
        top_titles = " ".join(r.get("title","") for r in results[:3])
        assert "ocot" not in nrm(top_titles) and "vinegar" not in nrm(top_titles)

    def test_sushi_rice_found(self, products):
        results = search_products(products, "sushi ryza", 6)
        assert titles_contain(results, "susi ryza", "sushi ryza", "susi ryz")

    def test_best_sushi_rice_chat_prioritizes_rice(self):
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))
        result = main.chat(main.ChatRequest(message="Najlepsia sushi ryza", limit=5), request)
        titles = [nrm(product.get("title", "")) for product in result.get("products", [])]

        assert result.get("intent") == "product_search"
        assert titles
        assert "ryza" in titles[0] and ("sushi" in titles[0] or "susi" in titles[0])
        assert "nori" not in titles[0]
        assert "ocot" not in titles[0]

    def test_gochujang_found(self, products):
        results = search_products(products, "gochujang", 4)
        assert titles_contain(results, "gochujang", "Gochujang")

    def test_typo_gochujang(self, products):
        results = search_products(products, "gochuang", 4)
        assert titles_contain(results, "gochujang")

    def test_kimchi_found(self, products):
        results = search_products(products, "kimchi", 4)
        assert titles_contain(results, "kimchi", "kimci")

    def test_direct_kimchi_chat_prioritizes_packaged_kimchi(self):
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))
        result = main.chat(main.ChatRequest(message="najlepsie kimchi", limit=5), request)
        titles = [nrm(product.get("title", "")) for product in result.get("products", [])]

        assert result.get("intent") == "product_search"
        assert titles
        assert "kimchi" in titles[0]
        assert "instant" not in titles[0]
        assert "ramen" not in titles[0]
        assert "polievk" not in titles[0]

    def test_bezlepkova_sojova_omacka(self, products):
        results = search_products(products, "bezlepkova sojova omacka", 4)
        found = titles_contain(results, "bezlepkova", "tamari", "Tamari")
        assert found, f"bezlepkova sojova omacka not found: {[r.get('title') for r in results[:3]]}"

    def test_in_stock_products_ranked_first(self, products):
        results = search_products(products, "kokosove mlieko", 6)
        assert any(r.get("availability") == "in_stock" for r in results[:3])

    def test_empty_query_returns_empty(self, products):
        assert search_products(products, "", 6) == []

    def test_limit_respected(self, products):
        results = search_products(products, "omacka", 3)
        assert len(results) <= 3

    def test_out_of_domain_returns_results_anyway(self, products):
        results = search_products(products, "bicykel", 4)
        assert isinstance(results, list)

    def test_english_alias_fish_sauce(self, products):
        results = search_products(products, "fish sauce", 4)
        assert titles_contain(results, "rybacia omacka", "fish sauce", "Fish Sauce")

    def test_pad_thai_found(self, products):
        results = search_products(products, "pad thai", 4)
        assert len(results) > 0

    def test_pad_thai_typos_find_products(self, products):
        for query in ("padthai", "pad tai", "pat thai"):
            results = search_products(products, query, 4)
            titles = " | ".join(product.get("title", "") for product in results)
            assert "pad thai" in nrm(titles), query

    def test_shoyu_does_not_match_soju_or_shoju(self, products):
        results = search_products(products, "shoyu", 6)
        titles = " | ".join(product.get("title", "") for product in results)
        normalized_titles = nrm(titles)
        assert results
        assert "shoyu" in normalized_titles or "sojova omacka" in normalized_titles
        assert "soju" not in normalized_titles
        assert "shoju" not in normalized_titles
        assert "shou" not in normalized_titles

    def test_soju_prioritizes_soju_products(self, products):
        results = search_products(products, "soju drink", 6)
        titles = [nrm(product.get("title", "")) for product in results[:4]]
        assert titles
        assert all("soju" in title for title in titles)

    def test_luigis_style_synonym_soy_sauce(self, products):
        results = search_products(products, "soy sauce", 6)
        assert titles_contain(results, "sojova omacka", "soy sauce", "tamari")

    def test_luigis_style_typo_coconut_milk(self, products):
        results = search_products(products, "coconat milk", 6)
        assert titles_contain(results, "kokosove mlieko", "coconut milk")

    def test_product_catalog_has_required_fields(self, products):
        required = ("id", "title", "link", "image_link", "price", "availability")
        missing = []
        invalid_urls = []
        invalid_prices = []
        duplicates = defaultdict(list)
        seen = defaultdict(dict)

        for index, product in enumerate(products):
            for key in required:
                if getattr(product, key, None) in (None, ""):
                    missing.append((index, key, getattr(product, "title", "")))
            for key in ("id", "link"):
                value = getattr(product, key, "")
                if value in seen[key]:
                    duplicates[key].append((seen[key][value], index, value))
                else:
                    seen[key][value] = index
            title_key = normalize(getattr(product, "title", "")).strip()
            if title_key in seen["title"]:
                duplicates["title"].append((seen["title"][title_key], index, getattr(product, "title", "")))
            else:
                seen["title"][title_key] = index
            for key in ("link", "image_link"):
                value = str(getattr(product, key, "") or "")
                if not value.startswith(("https://", "http://")):
                    invalid_urls.append((index, key, value))
            price = getattr(product, "price", None)
            sale_price = getattr(product, "sale_price", None)
            if not isinstance(price, (int, float)) or price <= 0:
                invalid_prices.append((index, getattr(product, "title", ""), price))
            if sale_price is not None and sale_price <= 0:
                invalid_prices.append((index, getattr(product, "title", ""), sale_price))

        assert not missing
        assert not invalid_urls
        assert not invalid_prices
        assert not {key: rows for key, rows in duplicates.items() if rows}

    def test_all_products_are_findable_by_title_tokens(self, products):
        token_index = defaultdict(set)
        title_tokens = []
        field_tokens = []
        for index, product in enumerate(products):
            product_title_tokens = tokenize(product.title)
            product_field_tokens = set(product_title_tokens) | tokenize(product.brand) | tokenize(product.product_type)
            title_tokens.append(product_title_tokens)
            field_tokens.append(product_field_tokens)
            for token in product_field_tokens:
                token_index[token].add(index)

        weak = []
        for index, product in enumerate(products):
            query = compact_product_title(product.title)
            query_tokens = tokenize(query)
            important_tokens = {token for token in query_tokens if len(token) >= 4} or query_tokens
            candidates = set()
            for token in important_tokens:
                candidates |= token_index.get(token, set())
            if index not in candidates:
                weak.append((index, product.title, query))
                continue

            ranked = []
            normalized_query = normalize(query)
            for candidate in candidates:
                score = 10 * len(query_tokens & title_tokens[candidate]) + 3 * len(query_tokens & field_tokens[candidate])
                if normalized_query in normalize(products[candidate].title):
                    score += 20
                if products[candidate].availability == "in_stock":
                    score += 2
                ranked.append((score, candidate))
            ranked.sort(reverse=True)
            top = {candidate for _, candidate in ranked[:8]}
            if index not in top:
                weak.append((index, product.title, query, [products[candidate].title for candidate in top]))

        assert not weak

    def test_autocomplete_suggestions(self, products):
        suggestions = autocomplete_suggestions(products, "sush", 6)
        labels = " | ".join(item["label"] for item in suggestions)
        assert suggestions
        assert "sushi" in nrm(labels) or "susi" in nrm(labels)

    def test_autocomplete_handles_common_foodland_queries(self, products):
        cases = {
            "kokosove mliko": ("kokos", "mlieko"),
            "sojovka": ("sojova", "omacka"),
            "chin su": ("chin",),
            "padthai": ("pad thai",),
            "pat thai": ("pad thai",),
        }
        for query, expected_terms in cases.items():
            suggestions = autocomplete_suggestions(products, query, 6)
            labels = " | ".join(item["label"] for item in suggestions)
            assert suggestions, f"Missing suggestions for {query}"
            normalized_labels = nrm(labels)
            assert any(term in normalized_labels for term in expected_terms), labels

    def test_autocomplete_keeps_soju_and_shoyu_separate(self, products):
        soju_labels = " | ".join(item["label"] for item in autocomplete_suggestions(products, "soju", 6))
        shoyu_labels = " | ".join(item["label"] for item in autocomplete_suggestions(products, "shoyu", 6))
        assert "soju" in nrm(soju_labels)
        assert "shoyu" in nrm(shoyu_labels) or "sojova omacka" in nrm(shoyu_labels)
        assert "shoju" not in nrm(shoyu_labels)

    def test_search_autocomplete_returns_mixed_results(self, products, knowledge):
        suggestions = main.search_autocomplete(products, knowledge, "kimchi", 8)
        types_found = {item["type"] for item in suggestions}
        labels = nrm(" | ".join(item["label"] for item in suggestions))

        assert suggestions
        assert "buy_intent" in types_found
        assert "cook_intent" in types_found
        assert "explain_intent" in types_found
        assert "product" in types_found
        assert "recipe" in types_found
        assert "kimchi" in labels

    def test_search_autocomplete_highlights_direct_title_matches(self, products, knowledge):
        suggestions = main.search_autocomplete(products, knowledge, "kim", 8)
        first = suggestions[0]

        assert first["type"] in {"product", "recipe"}
        assert "kim" in nrm(first["label"])
        assert first.get("highlight")
        assert first["highlight"][0]["start"] >= 0
        assert first["highlight"][0]["end"] > first["highlight"][0]["start"]

    def test_search_autocomplete_predictive_sentence_has_no_highlight(self, products, knowledge):
        suggestions = main.search_autocomplete(products, knowledge, "ako sa vari ramen", 8)
        first = suggestions[0]

        assert first["type"] == "cook_intent"
        assert "recept na ramen" in nrm(first["label"])
        assert all("highlight" not in item for item in suggestions[:4])

    def test_search_autocomplete_detects_explicit_intents(self, products, knowledge):
        cases = {
            "chcem kupit kimchi": ("buy_intent", "kimchi skladom", "kimchi"),
            "recept kimchi": ("cook_intent", "recept na kimchi", "recept na kimchi"),
            "co je kimchi": ("explain_intent", "co je kimchi", "co je kimchi"),
            "cim nahradit mirin": ("replace_intent", "cim nahradit mirin", "cim nahradit mirin"),
        }
        for query, (expected_type, expected_label, expected_query) in cases.items():
            suggestions = main.search_autocomplete(products, knowledge, query, 8)
            first = suggestions[0]

            assert first["type"] == expected_type, (query, suggestions[:3])
            assert expected_label in nrm(first["label"])
            assert expected_query in nrm(first["query"])

    def test_search_autocomplete_uses_human_subject_labels(self, products, knowledge):
        suggestions = main.search_autocomplete(products, knowledge, "co je sojov", 8)
        first = suggestions[0]

        assert first["type"] == "explain_intent"
        assert "Sójová omáčka" in first["label"]
        assert "sojova omacka" not in first["label"]

    def test_search_autocomplete_replacement_query_avoids_weak_product_noise(self, products, knowledge):
        suggestions = main.search_autocomplete(products, knowledge, "cim nahradit gochu", 8)

        assert suggestions[0]["type"] == "replace_intent"
        assert "Gochujang" in suggestions[0]["label"]
        assert not any(item["type"] == "product" for item in suggestions[:4])

    def test_search_autocomplete_completes_partial_intent_subjects(self, products, knowledge):
        cases = {
            "ako varit kim": "recept na kimchi",
            "recept na pad": "recept na pad thai",
            "cim nahradit gochu": "cim nahradit gochujang",
            "co je sojov": "co je sojova omacka",
        }
        for query, expected_label in cases.items():
            suggestions = main.search_autocomplete(products, knowledge, query, 8)
            first = suggestions[0]

            assert expected_label in nrm(first["label"]), (query, first)
            assert not nrm(first["label"]).endswith(" kim")
            assert not nrm(first["label"]).endswith(" gochu")

    def test_search_autocomplete_completes_multiword_recipe_subjects(self, products, knowledge):
        cases = {
            "ako varit ramen kim": "recept na kimchi ramen",
            "recept kimchi ram": "recept na kimchi ramen",
            "recept pho b": "recept na pho bo",
            "recept pho g": "recept na pho ga",
        }
        for query, expected_label in cases.items():
            suggestions = main.search_autocomplete(products, knowledge, query, 8)
            first = suggestions[0]

            assert expected_label in nrm(first["label"]), (query, first)

    def test_search_autocomplete_personalizes_intent_order(self, products, knowledge):
        cook_profile = {"intent_counts": {"cook": 5}, "last_intent": "recipe"}
        buy_profile = {"intent_counts": {"buy": 5}, "last_intent": "product_search"}

        cook_first = main.search_autocomplete(products, knowledge, "kimchi", 8, cook_profile)[0]
        cook_types = [item["type"] for item in main.search_autocomplete(products, knowledge, "kimchi", 8, cook_profile)]
        buy_types = [item["type"] for item in main.search_autocomplete(products, knowledge, "kimchi", 8, buy_profile)]

        assert cook_first["type"] in {"product", "recipe"}
        assert "cook_intent" in cook_types
        assert "buy_intent" in buy_types

    def test_search_autocomplete_explicit_intent_beats_memory(self, products, knowledge):
        buy_profile = {"intent_counts": {"buy": 10}, "last_intent": "product_search"}
        first = main.search_autocomplete(products, knowledge, "recept kimchi", 8, buy_profile)[0]

        assert first["type"] == "cook_intent"

    def test_search_autocomplete_memory_intent_beats_product_boosts(self, products, knowledge):
        profile = {
            "intent_counts": {"cook": 3},
            "last_intent": "recipe",
            "subjects": {"kimchi": 3},
            "product_titles": {"KIMCHI Ramen OTTOGI - 120g": 4},
            "product_brands": {"NONGSHIM": 3},
            "cuisines": {"korean": 3},
        }
        suggestions = main.search_autocomplete(products, knowledge, "kimchi", 8, profile)

        assert suggestions[0]["type"] in {"product", "recipe"}
        assert any(item["type"] == "cook_intent" for item in suggestions)

    def test_search_autocomplete_handles_padthai_typo(self, products, knowledge):
        suggestions = main.search_autocomplete(products, knowledge, "padthai", 8)
        labels = nrm(" | ".join(item["label"] for item in suggestions))

        assert suggestions
        assert "pad thai" in labels

    def test_search_autocomplete_keeps_soju_and_shoyu_separate(self, products, knowledge):
        soju = nrm(" | ".join(item["label"] for item in main.search_autocomplete(products, knowledge, "soju", 8)))
        shoyu = nrm(" | ".join(item["label"] for item in main.search_autocomplete(products, knowledge, "shoyu", 8)))

        assert "soju" in soju
        assert "shoyu" in shoyu or "sojova omacka" in shoyu
        assert "soju" not in shoyu
        assert "krek" not in shoyu

    def test_search_autocomplete_boosts_favorite_brand(self, products, knowledge):
        profile = {"product_brands": {"JONGGA": 5}, "cuisines": {}, "subjects": {}, "diet_terms": {}, "product_titles": {}}
        suggestions = main.search_autocomplete(products, knowledge, "kimchi", 8, profile)
        first_product = next(item for item in suggestions if item["type"] == "product")

        assert "jongga" in nrm(first_product.get("brand", "") + " " + first_product["label"])


class TestIntentDetection:
    def test_allergen_arasidy(self):
        assert main.detect_allergen_intent("alergia na arasidy, co mozem kupit?") is not None

    def test_allergen_lepok(self):
        term = main.detect_allergen_intent("mam celiakiu, bezlepkove produkty")
        assert term == "lepok"

    def test_allergen_NOT_triggered_for_product_search(self):
        term = main.detect_allergen_intent("mate bezlepkovu sojovu omacku?")
        assert term is None, f"False allergen trigger: {term}"

    def test_allergen_product_query_keeps_requested_product(self):
        assert main.allergen_product_query("je gochujang bez lepku?") == "gochujang"
        assert main.allergen_product_query("je sushi ryza bez lepku?") == "__gluten_free_sushi__"
        assert main.allergen_product_query("je rybacia omacka vegan?") == "rybacia omacka"

    def test_allergen_product_query_avoids_generic_soy_free_guess(self):
        assert main.allergen_product_query("co mate bez soje?") == ""

    def test_allergen_product_matches_include_requested_product(self):
        titles = " | ".join(product["title"] for product in main.allergen_product_matches("je gochujang bez lepku?", 6))
        assert "gochujang" in nrm(titles)

    def test_allergen_product_matches_gluten_free_sushi_bundle(self):
        titles = " | ".join(product["title"] for product in main.allergen_product_matches("som celiak, co k sushi kupit opatrne?", 6))
        normalized_titles = nrm(titles)
        assert "tamari" in normalized_titles or "bezlepkova sojova omacka" in normalized_titles
        assert "nori" in normalized_titles

    def test_allergen_intent_for_product_safety_questions(self):
        assert main.detect_allergen_intent("je sushi ryza bez lepku?") == "lepok"
        assert main.detect_allergen_intent("je rybacia omacka vegan?") == "vhodnost pre veganov"

    def test_vegan_profile_recommendation_is_not_allergen_safety(self):
        assert main.detect_allergen_intent("som vegan a chcem azijske jedla") is None
        assert main.detect_allergen_intent("som vegan. bez vymyslania vlastnosti") is None

    def test_allergen_warning_suffix_does_not_override_product_search(self):
        assert main.detect_allergen_intent("chcem ryzove rezance. pozor na alergeny") is None

    def test_faq_doprava(self):
        assert main.is_faq_intent("kolko stoji doprava?")

    def test_faq_platba(self):
        assert main.is_faq_intent("da sa platit kartou?")

    def test_faq_shipping_carrier_synonyms(self):
        assert main.is_faq_intent("cez koho posielate baliky?")
        assert main.is_faq_intent("ktory prepravca mi privezie objednavku?")
        assert main.is_faq_intent("kto rozvaza foodland objednavky?")

    def test_direct_faq_shipping_carrier_answer(self, knowledge):
        answer = main.best_direct_faq_answer("cez koho posielate baliky?", knowledge)
        assert answer
        assert "Packeta" in answer or "DPD" in answer or "GLS" in answer

    def test_faq_NOT_triggered_for_product(self):
        assert not main.is_faq_intent("gochujang pasta")

    def test_recipe_detected(self):
        assert main.detect_recipe_subject("recept na kimchi") is not None

    def test_recipe_subject_kimchi(self):
        subj = main.detect_recipe_subject("recept na kimchi")
        assert subj == "kimchi"

    def test_recipe_subject_prefers_multiword_recipe_names(self):
        assert main.detect_recipe_subject("recept na kimchi ramen") == "kimchi_ramen"
        assert main.detect_recipe_subject("recept na ramen kimchi") == "kimchi_ramen"
        assert main.recipe_related_product_subject("co potrebujem k receptu kimchi ramen", "kimchi_ramen", []) == "kimchi_ramen"
        assert main.recipe_related_product_subject("co potrebujem k receptu pho bo", "pho", []) == "pho"

    def test_dinner_prompt_returns_three_random_cuisines(self, knowledge):
        assert main.is_random_recipe_intent("Čo variť na večeru?")

        recipes = main.get_random_recipes_by_cuisine(knowledge, 3)
        cuisine_keys = {main.recipe_cuisine_key({}, recipe) for recipe in recipes}

        assert len(recipes) == 3
        assert len(cuisine_keys) == 3

    def test_kimchi_recipe_prioritizes_making_kimchi_and_keeps_related_recipes(self, knowledge):
        query = "recept na kimchi"
        matches = search_knowledge(knowledge, query)
        recipes = main.recipe_results(matches, 4, query, knowledge)
        titles = [nrm(recipe["title"]) for recipe in recipes]

        assert recipes
        assert "tradicny kimchi recept" in titles[0]
        assert any("kimchi ramen" in title or "kimchi jjigae" in title for title in titles[1:])

    def test_recipe_results_match_ingredient_query(self, knowledge):
        query = "recept z kokosového mlieka"
        matches = search_knowledge(knowledge, query)
        recipes = main.recipe_results(matches, 4, query, knowledge)
        titles = " | ".join(recipe["title"] for recipe in recipes)
        assert recipes
        assert "kokos" in nrm(titles) or "tom kha gai" in nrm(titles)

    def test_recipe_results_do_not_overmatch_short_tokens(self, knowledge):
        query = "recept na pho bo"
        matches = search_knowledge(knowledge, query)
        recipes = main.recipe_results(matches, 4, query, knowledge)
        titles = " | ".join(recipe["title"] for recipe in recipes)
        assert "pho bo" in nrm(recipes[0]["title"]) or "hovadzia" in nrm(recipes[0]["title"])
        assert "pho" in nrm(titles)
        assert "pad thai" not in nrm(titles)

    def test_recipe_results_prefer_kimchi_ramen_phrase(self, knowledge):
        for query in ("recept na kimchi ramen", "recept na ramen kimchi"):
            matches = search_knowledge(knowledge, query)
            recipes = main.recipe_results(matches, 4, query, knowledge)

            assert recipes
            assert "kimchi ramen" in nrm(recipes[0]["title"])

    def test_pad_thai_recipe_typos(self, knowledge):
        for query in ("recept na padthai", "recept na pad tai", "recept na pat thai"):
            matches = search_knowledge(knowledge, query)
            recipes = main.recipe_results(matches, 4, query, knowledge)
            titles = " | ".join(recipe["title"] for recipe in recipes)
            assert "pad thai" in nrm(titles), query

    def test_vietnamese_cuisine_recipe_queries_return_recipes(self, knowledge):
        for query in (
            "recepty Vietnamskej kuchyne",
            "vietnamske recepty",
            "ukaz recepty vietnamskej kuchyne",
            "recepty z Vietnamu",
        ):
            matches = search_knowledge(knowledge, query)
            recipes = main.recipe_results(matches, 4, query, knowledge)
            titles = " | ".join(recipe["title"] for recipe in recipes)

            assert recipes, query
            assert "pho" in nrm(titles) or "banh" in nrm(titles) or "vietnamsk" in nrm(titles) or "bun" in nrm(titles)
            assert "pad thai" not in nrm(titles)

    def test_cuisine_recipe_queries_return_matching_country_recipes(self, knowledge):
        cases = (
            ("thajské recepty", ("pad thai", "tom yum", "tom kha", "satay")),
            ("recepty z Thajska", ("pad thai", "tom yum", "tom kha", "satay")),
            ("kórejské recepty", ("kimchi", "japchae", "bulgogi", "bibimbap", "gimbap")),
            ("recepty z Kórey", ("kimchi", "japchae", "bulgogi", "bibimbap", "gimbap")),
            ("japonské recepty", ("udon", "teriyaki", "kuromame", "shoyu", "miso")),
            ("recepty z Japonska", ("udon", "teriyaki", "kuromame", "shoyu", "miso")),
            ("čínske recepty", ("kung pao", "pekingsk", "ma po", "suan la tang")),
            ("recepty z Číny", ("kung pao", "pekingsk", "ma po", "suan la tang")),
            ("indické recepty", ("makhani", "tikka", "tandoori", "biryani")),
            ("recepty z Indie", ("makhani", "tikka", "tandoori", "biryani")),
            ("indonézske recepty", ("nasi goreng", "mie goreng", "rendang")),
            ("recepty z Indonézie", ("nasi goreng", "mie goreng", "rendang")),
            ("malajské recepty", ("rendang", "nasi lemak")),
            ("recepty z Malajzie", ("rendang", "nasi lemak")),
            ("singapurské recepty", ("hainanske", "singapurske")),
            ("recepty zo Singapuru", ("hainanske", "singapurske")),
            ("filipínske recepty", ("sinigang",)),
            ("recepty z Filipín", ("sinigang",)),
        )

        for query, expected_terms in cases:
            matches = search_knowledge(knowledge, query)
            recipes = main.recipe_results(matches, 4, query, knowledge)
            titles = nrm(" | ".join(recipe["title"] for recipe in recipes))

            assert recipes, query
            assert any(term in titles for term in expected_terms), query

    def test_pad_thai_related_subject_typos(self):
        for query in ("ingrediencie na padthai", "ingrediencie na pad tai", "ingrediencie na pat thai"):
            assert main.detect_related_subject(query) == "pad_thai"

    def test_recipe_product_intent_is_explicit(self):
        assert not main.wants_recipe_products("recept na pho bo")
        assert main.wants_recipe_products("recept na pho bo a produkty")
        assert main.wants_recipe_products("co potrebujem k receptu pho bo")

    def test_pho_recipe_products_prioritize_spices_then_noodles(self, products):
        matches = main.related_products_for_subject(products, main.knowledge, "pho", 8)
        main.annotate_recommendations(matches, "recipe_to_products", related_subject="pho")

        groups = [product["recommendation_group"] for product in matches]
        titles = " | ".join(product["title"] for product in matches)
        first_noodle_index = groups.index("Základ")

        assert groups[0] == "Korenie a vývar"
        assert first_noodle_index > 0
        assert all(group == "Korenie a vývar" for group in groups[:first_noodle_index])
        assert "rezance" in nrm(titles) or "banh pho" in nrm(titles)

    def test_recipe_shopping_list_has_foodland_and_missing_items(self, products):
        matches = main.related_products_for_subject(products, main.knowledge, "pho", 8)
        main.annotate_recommendations(matches, "recipe_to_products", related_subject="pho")
        cart_candidates = main.cart_candidates_for_response(matches, "recipe_to_products", "pho")
        missing = main.missing_ingredients_for_subject("pho", [])
        shopping_list = main.shopping_list_for_response(cart_candidates, missing)

        assert cart_candidates
        assert shopping_list["available_on_foodland"]
        assert "limetka" in nrm(" | ".join(missing))
        assert "cerstve" in nrm(" | ".join(missing))

    def test_recipe_to_products_uses_phrase_subject_for_pho_bo_and_kimchi_ramen(self):
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))

        pho_result = main.chat(main.ChatRequest(message="co potrebujem k receptu pho bo", limit=8), request)
        pho_titles = [nrm(product.get("title", "")) for product in pho_result.get("products", [])]

        assert pho_result.get("intent") == "recipe_to_products"
        assert "korenie" in pho_titles[0] and "pho" in pho_titles[0]
        assert any("rezance" in title or "banh pho" in title for title in pho_titles[1:])

        ramen_result = main.chat(main.ChatRequest(message="co potrebujem k receptu ramen kimchi", limit=8), request)
        ramen_titles = nrm(" | ".join(product.get("title", "") for product in ramen_result.get("products", [])))

        assert ramen_result.get("intent") == "recipe_to_products"
        assert "ramen" in ramen_titles or "ramyun" in ramen_titles
        assert "kimchi" in ramen_titles
        assert "ryzova muka" not in ramen_titles

    def test_related_shopping_list_intent_detected(self):
        assert main.wants_shopping_list("nákupný zoznam na sushi")
        assert main.missing_ingredients_for_subject("sushi", [])

    def test_sushi_shopping_list_uses_buyable_core_items_not_water(self, products):
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))
        result = main.chat(main.ChatRequest(message="nakupny zoznam na sushi", limit=8), request)
        shopping_list = result["shopping_list"]

        available_titles = nrm(" | ".join(item.get("title", "") for item in shopping_list["available_on_foodland"]))
        missing_text = nrm(" | ".join(shopping_list["missing_ingredients"]))

        assert "voda" not in missing_text
        assert "ryza" in available_titles
        assert "ocot" in available_titles
        assert "wasabi" in available_titles
        assert "nori" in available_titles

    def test_tom_yum_shopping_list_prioritizes_herbs_and_paste_alternative(self):
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))
        result = main.chat(main.ChatRequest(message="nakupny zoznam na tom yum", limit=8), request)
        titles = [nrm(product.get("title", "")) for product in result.get("products", [])]
        all_titles = " | ".join(titles)

        assert result.get("intent") == "related_products"
        assert "citronova trava" in all_titles
        assert "galangal" in all_titles
        assert "kaffir" in all_titles or "kaffirov" in all_titles
        assert "rybacia omacka" in all_titles
        assert "kokosove mlieko" in all_titles
        assert "sriracha" not in all_titles
        assert "tom yum" in all_titles and "pasta" in all_titles
        assert "sojova omacka" not in " | ".join(titles[:4])
        paste_index = next(index for index, title in enumerate(titles) if "tom yum" in title and "pasta" in title)
        coconut_index = next(index for index, title in enumerate(titles) if "kokosove mlieko" in title)
        assert paste_index > coconut_index

    @pytest.mark.parametrize(
        ("subject", "expected_terms", "forbidden_terms"),
        [
            ("black_rice_salad", ("cierna ryza", "ryzovy ocot"), ("kimchi", "nori")),
            ("mango_sticky_rice", ("lepkava ryza", "kokosove mlieko", "mango"), ("cierna lepkava",)),
            ("jasmine_rice", ("jazminova ryza",), ("nori", "ocot", "kimchi")),
            ("kuromame_gohan", ("susi ryza", "mirin"), ("kimchi",)),
            ("gimbap", ("susi ryza", "nori"), ("ryzovy ocot",)),
            ("tempura", ("tempura",), ("wasabi", "nakladany zazvor")),
            ("ramen", ("ramen", "dashi"), ("nakladany zazvor",)),
            ("japanese_curry", ("golden curry", "japonske kari"), ("cervena kari pasta",)),
            ("kimchi_recipe", ("kimchi zaklad", "cili paprika", "rybacia omacka"), ("arasid", "jazminova ryza")),
            ("bibimbap", ("gochujang", "ryza"), ("kimchi instantna",)),
            ("bulgogi", ("bulgogi", "sojova omacka"), ("kimchi instantna",)),
            ("mapo_tofu", ("ma po", "fazulova omacka"), ("miso polievka",)),
            ("suan_la_tang", ("ostro kysla polievka", "bambus"), ("hoisin",)),
            ("sinigang", ("sinigang", "tamarind"), ("ramen", "rezance")),
        ],
    )
    def test_recipe_shopping_core_uses_recipe_specific_products(self, products, subject, expected_terms, forbidden_terms):
        matches = main.recipe_shopping_core_products(products, subject, [], 8)
        titles = nrm(" | ".join(product.get("title", "") for product in matches))

        assert matches
        for term in expected_terms:
            assert nrm(term) in titles
        for term in forbidden_terms:
            assert nrm(term) not in titles

    def test_all_known_recipes_have_missing_ingredient_mapping(self, knowledge):
        recipes = knowledge.get("sections", {}).get("Recipes", [])
        assert recipes
        missing = []
        for record in recipes:
            recipe = main.recipe_card(record)
            subject = main.recipe_product_subject_from_title(recipe.get("title", ""))
            if not main.missing_ingredients_for_subject(subject, [recipe]):
                missing.append(recipe.get("title", ""))
        assert not missing

    def test_all_known_recipes_have_product_subject(self, knowledge):
        recipes = knowledge.get("sections", {}).get("Recipes", [])
        assert recipes
        missing = []
        for record in recipes:
            title = main.recipe_card(record).get("title", "")
            subject = main.recipe_product_subject_from_title(title)
            if not subject or subject not in main.RELATED_PRODUCT_QUERIES:
                missing.append(title)
        assert not missing

    def test_all_known_recipe_ingredient_queries_have_related_subject(self, knowledge):
        recipes = knowledge.get("sections", {}).get("Recipes", [])
        assert recipes
        missing = []
        for record in recipes:
            title = main.recipe_card(record).get("title", "")
            subject = main.detect_related_subject(f"ingrediencie na {title}")
            if not subject or subject not in main.RELATED_PRODUCT_QUERIES:
                missing.append(title)
        assert not missing

    def test_recipe_product_subject_samples_return_products(self, products):
        subjects = [
            "tom_kha",
            "bun_cha",
            "banh_gio",
            "tikka_masala",
            "biryani",
            "nasi_lemak",
            "sinigang",
            "thit_dong",
        ]
        for subject in subjects:
            matches = main.related_products_for_subject(products, main.knowledge, subject, 6)
            assert matches, subject

    def test_recipe_product_recommendations_exclude_tools_and_false_spices(self, products):
        sushi_titles = " | ".join(product["title"] for product in main.related_products_for_subject(products, main.knowledge, "sushi", 8))
        biryani_titles = " | ".join(product["title"] for product in main.related_products_for_subject(products, main.knowledge, "biryani", 8))
        sinigang_titles = " | ".join(product["title"] for product in main.related_products_for_subject(products, main.knowledge, "sinigang", 8))

        assert "podlozka" not in nrm(sushi_titles)
        assert "cierne korenie" not in nrm(biryani_titles)
        assert "biryani" in nrm(biryani_titles)
        assert "tamarind" in nrm(sinigang_titles)
        assert "soba chili" not in nrm(sinigang_titles)
        for subject in ("banh_gio", "bun_cha", "nuoc_cham", "thit_dong"):
            titles = " | ".join(product["title"] for product in main.related_products_for_subject(products, main.knowledge, subject, 8))
            assert "ananasova cili" not in nrm(titles)

    def test_out_of_domain_bicykel(self):
        assert main.detect_out_of_domain("predate bicykle?")

    def test_out_of_domain_lekar(self):
        assert main.detect_out_of_domain("odporucam ist k lekarovi")

    def test_NOT_out_of_domain_for_food(self):
        assert not main.detect_out_of_domain("gochujang pasta 500g")

    def test_related_subject_sushi(self):
        subj = main.detect_related_subject("co potrebujem na sushi?")
        assert subj == "sushi"

    def test_related_subject_kimchi(self):
        subj = main.detect_related_subject("ingrediencie na kimchi")
        assert subj == "kimchi_recipe"

    def test_special_gluten_free_sushi(self):
        subj = main.detect_special_product_subject("bezlepkove sushi")
        assert subj == "gluten_free_sushi"

    def test_special_rice_vinegar(self):
        subj = main.detect_special_product_subject("ryzovy ocot")
        assert subj == "rice_vinegar"

    def test_special_vegan_fish_sauce(self):
        subj = main.detect_special_product_subject("nahrada za rybaciu omacku vegan")
        assert subj == "vegan_fish_sauce_replacement"

    def test_replacement_subject_detected_before_related_cross_sell(self):
        assert main.detect_replacement_subject("cim vynahradim gochujang") == "gochujang"
        assert main.detect_related_subject("cim vynahradim gochujang") == "gochujang"


class TestRelatedProducts:
    def test_product_specific_cross_sell_from_knowledge(self, products, knowledge):
        results = main.cross_sell_products_for_message(products, knowledge, "co sa hodi k Biela fazula COCK BRAND 400g?", 6)
        titles = nrm(" | ".join(product.get("title", "") for product in results))

        assert results
        assert "rezance" in titles or "ryza" in titles

    def test_product_specific_cross_sell_beats_general_mung_subject(self, products, knowledge):
        results = main.cross_sell_products_for_message(products, knowledge, "co sa hodi k Mung fazula lupana polena COCK BRAND 400 g?", 6)
        titles = nrm(" | ".join(product.get("title", "") for product in results))

        assert "sklenene rezance" in titles or "basmati" in titles

    def test_sushi_related_no_sushi_rice(self, products):
        """related_products_for_subject('sushi') nesmie vratit sushi ryzu."""
        results = main.related_products_for_subject(products, main.knowledge, "sushi", 8)
        for p in results:
            title_nrm = nrm(p.get("title", ""))
            is_sushi_rice = "susi" in title_nrm.split() and "ryza" in title_nrm
            assert not is_sushi_rice, f"sushi ryza in related sushi: {p.get('title')}"

    def test_kimchi_related_no_kimchi_itself(self, products):
        results = main.related_products_for_subject(products, main.knowledge, "kimchi", 8)
        for p in results:
            assert "kimchi" not in nrm(p.get("title", ""))

    def test_kimchi_recipe_shopping_does_not_include_rice_or_ready_kimchi(self):
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))
        result = main.chat(main.ChatRequest(message="co potrebujem na kimchi", limit=8), request)
        titles = nrm(" | ".join(product.get("title", "") for product in result.get("products", [])))

        assert result.get("intent") == "related_products"
        assert "gochujang" in titles or "cili" in titles
        assert "rybacia omacka" in titles
        assert "jazminova ryza" not in titles
        assert "kimchi nakladana" not in titles
        assert "kimchi krajane" not in titles

    def test_kimchi_ramen_shopping_uses_ramen_not_kimchi_making_ingredients(self):
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))
        result = main.chat(main.ChatRequest(message="nakupny zoznam na kimchi ramen", limit=8), request)
        titles = nrm(" | ".join(product.get("title", "") for product in result.get("products", [])))
        missing = nrm(" | ".join(result.get("shopping_list", {}).get("missing_ingredients") or []))

        assert result.get("intent") == "related_products"
        assert "ramen" in titles or "ramyun" in titles
        assert "kimchi" in titles
        assert "gochujang" in titles or "miso" in titles or "sojova omacka" in titles
        assert "kimchi instantna" not in titles
        assert "kimchi ramen ottogi" not in titles
        assert "ryzova muka" not in titles
        assert "cinska kapusta" not in missing
        assert "daikon" not in missing

    def test_replacement_products_are_similar_not_cross_sell(self, products, knowledge):
        results = main.alternative_products_for_subject(products, knowledge, "gochujang", 6)
        titles = nrm(" | ".join(product.get("title", "") for product in results))

        assert results
        assert "gochujang" in titles
        assert "mirin" not in titles
        assert "ryzovy ocot" not in titles
        assert "sezamovy olej" not in titles

    def test_replacement_mirin_prefers_mirin_like_products(self, products, knowledge):
        results = main.alternative_products_for_subject(products, knowledge, "mirin", 6)
        titles = nrm(" | ".join(product.get("title", "") for product in results))

        assert results
        assert "mirin" in titles
        assert "podlozka" not in titles
        assert "palicky" not in titles

    def test_special_kids_snack_no_alcohol(self, products):
        results = main.special_products_for_subject(products, "kids_snack", 6)
        for p in results:
            title = nrm(p.get("title", ""))
            assert "soju" not in title and "sake" not in title

    def test_special_mild_no_spicy(self, products):
        results = main.special_products_for_subject(products, "mild", 6)
        for p in results:
            title = nrm(p.get("title", ""))
            assert "wasabi" not in title and "sriracha" not in title


class TestSessionMemory:
    def test_followup_uses_last_subject(self):
        main.session_memories.clear()
        key = main.session_memory_key("memory-test-1", "127.0.0.1")
        memory = main.get_session_memory(key)
        main.update_session_memory(key, "Chcem varit sushi", "product_search", [], [], {})

        contextual = main.contextualize_message("a co k tomu?", memory)

        assert "sushi" in main.normalize(contextual)
        assert main.detect_related_subject(contextual) == "sushi"

    def test_diet_preference_is_remembered(self):
        main.session_memories.clear()
        key = main.session_memory_key("memory-test-2", "127.0.0.1")
        memory = main.get_session_memory(key)
        main.update_session_memory(key, "Som celiak, hladam bezlepkove veci", "allergen_safety", [], [], {})

        contextual = main.contextualize_message("ake omacky odporucas?", memory)

        assert "bezlepkove" in main.normalize(contextual)

    def test_memory_redacts_contact_details(self):
        redacted = main.redact_memory_text("Moj email je test@example.com a telefon +421 900 123 456")

        assert "test@example.com" not in redacted
        assert "+421" not in redacted
        assert "[email]" in redacted
        assert "[phone]" in redacted


class TestFAQ:
    def test_faq_shipping_cost(self, knowledge):
        answer = main.best_direct_faq_answer("kolko stoji doprava?", knowledge)
        assert answer
        assert any(kw in (answer or "").lower() for kw in ("doprava", "eur", "zadarmo", "dopravy"))

    def test_faq_payment(self, knowledge):
        answer = main.best_direct_faq_answer("ako mozem zaplatit?", knowledge)
        assert answer

    def test_faq_returns_none_for_product_query(self, knowledge):
        answer = main.best_direct_faq_answer("gochujang pasta", knowledge)
        assert answer is None


class TestKnowledgeSearch:
    def test_sriracha_in_products_ai(self, knowledge):
        results = search_knowledge(knowledge, "sriracha")
        assert "Products_AI" in results or "CrossSell" in results

    def test_kimchi_crosssell(self, knowledge):
        results = search_knowledge(knowledge, "kimchi")
        assert results

    def test_empty_query(self, knowledge):
        results = search_knowledge(knowledge, "")
        assert results == {}

    def test_search_knowledge_can_limit_sections(self, knowledge):
        results = search_knowledge(knowledge, "co je kimchi", allowed_sections=("Products_AI",))

        assert set(results).issubset({"Products_AI"})
        assert "Magazine" not in results
        assert "Recipes" not in results

    def test_knowledge_sections_for_chat_intent(self):
        assert main.knowledge_sections_for_intent(
            is_faq_query=True,
            is_random_recipe_query=False,
            recipe_subject=None,
            needs_article_context=True,
            explicit_article_request=True,
        ) == ("FAQ",)
        assert main.knowledge_sections_for_intent(
            is_faq_query=False,
            is_random_recipe_query=False,
            recipe_subject="kimchi",
            needs_article_context=False,
            explicit_article_request=False,
        ) == ("Recipes",)
        assert main.knowledge_sections_for_intent(
            is_faq_query=False,
            is_random_recipe_query=False,
            recipe_subject=None,
            needs_article_context=True,
            explicit_article_request=False,
        ) == ("Products_AI",)
        assert main.knowledge_sections_for_intent(
            is_faq_query=False,
            is_random_recipe_query=False,
            recipe_subject=None,
            needs_article_context=True,
            explicit_article_request=True,
        ) == ("Magazine", "Products_AI")

    def test_magazine_results_return_article_cards(self, knowledge):
        results = search_knowledge(knowledge, "čo je kimchi")
        articles = main.article_results(results, 3)

        assert articles
        assert articles[0]["title"]
        assert articles[0]["link"].startswith("https://")

    def test_recipe_cuisine_articles_match_requested_country(self, knowledge):
        articles = main.article_results(search_knowledge(knowledge, "recepty z Kórey"), 3)
        filtered = main.recipe_article_results(articles, "recepty z Kórey", knowledge)
        titles = nrm(" | ".join(article["title"] for article in filtered))

        assert filtered
        assert "korej" in titles or "kimchi" in titles
        assert "cinsk" not in titles
        assert "azijske recepty" not in titles
        assert "olympij" not in titles

    def test_article_product_filter_keeps_direct_kimchi_products(self, knowledge, products):
        articles = main.article_results(search_knowledge(knowledge, "co je kimchi"), 3)
        subject = main.detect_article_product_subject("co je kimchi", articles)
        matches = main.article_products_for_subject(products, subject, 6)
        titles = " | ".join(product["title"] for product in matches)

        assert subject == "kimchi_article"
        assert matches
        assert "kimchi" in nrm(titles)
        assert "ramen" not in nrm(titles)
        assert "instant" not in nrm(titles)

    def test_article_product_filter_removes_weak_tofu_and_shoyu_matches(self, knowledge, products):
        tofu_articles = main.article_results(search_knowledge(knowledge, "co je tofu"), 3)
        tofu_subject = main.detect_article_product_subject("co je tofu", tofu_articles)
        tofu_matches = main.article_products_for_subject(products, tofu_subject, 6)
        tofu_titles = " | ".join(product["title"] for product in tofu_matches)

        shoyu_articles = main.article_results(search_knowledge(knowledge, "co je shoyu"), 3)
        shoyu_subject = main.detect_article_product_subject("co je shoyu", shoyu_articles)
        shoyu_matches = main.article_products_for_subject(products, shoyu_subject, 6)
        shoyu_titles = " | ".join(product["title"] for product in shoyu_matches)

        assert tofu_subject == "tofu_article"
        assert tofu_matches
        assert "tofu" in nrm(tofu_titles)
        assert "miso polievka" not in nrm(tofu_titles)
        assert shoyu_subject == "shoyu_article"
        assert shoyu_matches
        assert "krek" not in nrm(shoyu_titles)


class TestUserMemory:
    def test_user_memory_persists_culinary_preferences(self, tmp_path, monkeypatch):
        memory_path = tmp_path / "user_memory.json"
        monkeypatch.setenv("USER_MEMORY_PATH", str(memory_path))
        main.user_memories = None

        profile = main.update_user_memory(
            "client-test",
            "mam rad korejske pikantne kimchi",
            "product_search",
            [{"title": "Kimchi JONGGA 300g", "brand": "JONGGA"}],
            [],
        )

        assert "korean" in profile["cuisines"]
        assert "pikantne" in profile["diet_terms"]
        assert profile["product_brands"]["JONGGA"] == 1
        assert profile["intent_counts"]["buy"] == 1

        main.user_memories = None
        loaded = main.get_user_memory("client-test")
        assert "korean" in loaded["cuisines"]
        assert "JONGGA" in loaded["product_brands"]

    def test_user_memory_tracks_recipe_intent_for_autocomplete(self, tmp_path, monkeypatch):
        memory_path = tmp_path / "user_memory.json"
        monkeypatch.setenv("USER_MEMORY_PATH", str(memory_path))
        main.user_memories = None

        main.update_user_memory("client-recipe", "recept na kimchi", "recipe", [], [{"title": "Kimchi Ramen"}])
        main.update_user_memory("client-recipe", "recept na pho", "recipe", [], [{"title": "Pho Bo"}])

        profile = main.get_user_memory("client-recipe")
        assert profile["intent_counts"]["cook"] == 2

    def test_clear_user_memory_removes_profile(self, tmp_path, monkeypatch):
        memory_path = tmp_path / "user_memory.json"
        monkeypatch.setenv("USER_MEMORY_PATH", str(memory_path))
        main.user_memories = None
        main.update_user_memory("client-clear", "kimchi", "product_search", [], [])

        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))
        result = main.clear_user_memory(main.MemoryClearRequest(client_id="client-clear"), request)

        assert result == {"cleared": True}
        assert "client-clear" not in main.load_user_memories()

    def test_personalize_products_boosts_matching_cuisine(self):
        profile = {"cuisines": {"korean": 3}, "subjects": {}, "diet_terms": {}, "product_titles": {}, "product_brands": {}}
        product_rows = [
            {"title": "Jazmínová ryža 1kg", "brand": "AAA"},
            {"title": "Kimchi JONGGA 300g", "brand": "JONGGA"},
        ]

        ranked = main.personalize_products(product_rows, profile)

        assert ranked[0]["title"] == "Kimchi JONGGA 300g"
        assert ranked[0]["personalized"] is True


class TestAdminAnalytics:
    def test_analytics_report_summarizes_questions_and_weak_spots(self):
        events = [
            {"ts": 10, "client_hash": "a", "session_id": "s1", "message": "co je kimchi", "matches_count": 4, "intent": "article_products"},
            {"ts": 11, "client_hash": "a", "session_id": "s1", "message": "co je kimchi?", "matches_count": 4, "intent": "article_products"},
            {"ts": 12, "client_hash": "b", "session_id": "s2", "message": "mate wasabi xxl", "matches_count": 0, "intent": "product_search"},
            {"ts": 13, "client_hash": "c", "session_id": "s3", "message": "predate bicykle", "matches_count": 0, "intent": "unknown"},
            {"ts": 14, "client_hash": "d", "session_id": "s4", "message": "recept na pho", "matches_count": 0, "intent": "recipe"},
        ]
        report = main.analytics_report(events, [{"ts": 15, "event": "openai_transient_error"}], 5)

        assert report["summary"]["questions"] == 5
        assert report["summary"]["unique_clients"] == 4
        assert report["summary"]["no_result_questions"] == 1
        assert report["summary"]["unknown_questions"] == 1
        assert report["summary"]["backend_errors"] == 1
        assert report["top_questions"][0]["count"] == 2
        assert any(row["intent"] == "article_products" for row in report["intents"])
        assert any(row["area"] == "no_results" for row in report["weak_spots"])
        assert report["action_items"]
        assert any(item["type"] == "missing_result" for item in report["action_items"])

    def test_no_result_rows_group_normalized_questions(self):
        events = [
            {"ts": 10, "message": "Nemáte saké 500 ml?", "matches_count": 0, "intent": "product_search"},
            {"ts": 12, "message": "nemate sake?", "matches_count": 0, "intent": "product_search"},
            {"ts": 13, "message": "sake", "matches_count": 2, "intent": "product_search"},
            {"ts": 14, "message": "recept na sushi", "matches_count": 0, "intent": "recipe"},
        ]
        rows = main.no_result_rows(events, 5)

        assert rows
        assert rows[0]["count"] == 2
        assert rows[0]["intent"] == "product_search"

    def test_analytics_action_items_include_low_relevance_and_frequent_questions(self):
        events = [
            {"ts": 10, "message": "co je kimchi", "matches_count": 1, "intent": "article_products"},
            {"ts": 11, "message": "co je kimchi?", "matches_count": 2, "intent": "article_products"},
            {"ts": 12, "message": "mate wasabi xxl", "matches_count": 0, "intent": "product_search"},
            {"ts": 13, "message": "mate wasabi xxl", "matches_count": 0, "intent": "product_search"},
        ]
        items = main.analytics_action_items(events, [], 10)
        item_types = {item["type"] for item in items}

        assert "missing_result" in item_types
        assert "low_relevance" in item_types
        assert "frequent_question" in item_types
        assert any("synonym" in nrm(item.get("suggested_action", "")) for item in items)

    def test_public_suggested_questions_use_repeated_safe_questions(self):
        events = [
            {"ts": 10, "message": "co je kimchi", "matches_count": 4, "intent": "article_products"},
            {"ts": 11, "message": "co je kimchi?", "matches_count": 4, "intent": "article_products"},
            {"ts": 12, "message": "moj email test@example.com", "matches_count": 0, "intent": "unknown"},
            {"ts": 13, "message": "moj email test@example.com", "matches_count": 0, "intent": "unknown"},
            {"ts": 14, "message": "recept na ramen", "matches_count": 0, "intent": "recipe"},
        ]
        rows = main.public_suggested_question_rows(events, limit=5, min_count=2)

        questions = [row["question"] for row in rows]
        assert questions == ["co je kimchi?"]

    def test_clean_public_suggested_question_filters_sensitive_text(self):
        assert main.clean_public_suggested_question("napiste mi na test@example.com") == ""
        assert main.clean_public_suggested_question("pozri https://example.com") == ""
        assert main.clean_public_suggested_question("objednavka 123456789") == ""
        assert main.clean_public_suggested_question("recept na pho") == "recept na pho?"


class TestFastResponses:
    def test_fast_response_enabled_for_product_matches(self, monkeypatch):
        monkeypatch.setenv("FOODLAND_FAST_RESPONSES", "true")
        assert main.should_use_fast_chat_answer("product_search", [{"title": "Kimchi"}], {})

    def test_fast_response_disabled_for_advisory_product_intents(self, monkeypatch):
        monkeypatch.setenv("FOODLAND_FAST_RESPONSES", "true")
        matches = [{"title": "Mirin"}]

        assert not main.should_use_fast_chat_answer("related_products", matches, {})
        assert not main.should_use_fast_chat_answer("article_products", matches, {})
        assert not main.should_use_fast_chat_answer("recipe_to_products", matches, {})

    def test_fast_response_disabled_for_composition_caution(self, monkeypatch):
        monkeypatch.setenv("FOODLAND_FAST_RESPONSES", "true")
        assert not main.should_use_fast_chat_answer("product_search", [{"title": "Tamari"}], {}, True)

    def test_fast_response_can_be_disabled(self, monkeypatch):
        monkeypatch.setenv("FOODLAND_FAST_RESPONSES", "false")
        assert not main.should_use_fast_chat_answer("product_search", [{"title": "Kimchi"}], {})


class TestFallbackAnswerQuality:
    def test_related_fallback_uses_readable_subject_and_product_names(self):
        answer = main.fallback_answer(
            [{"title": "Mirin sladke ryzove vino"}, {"title": "Ryžový ocot"}],
            related_subject="sojova_omacka",
        )

        assert "sojova_omacka" not in answer
        assert "sójovej omáčke" in answer
        assert "Mirin" in answer


class TestProductSearchCache:
    def test_cached_search_products_reuses_scan_and_returns_copies(self, monkeypatch):
        calls = {"count": 0}
        sample_products = [{"title": "Kimchi"}]

        def fake_search_products(products, query, limit):
            calls["count"] += 1
            return [{"title": "Kimchi", "query": query, "limit": limit}]

        monkeypatch.setattr(main, "search_products", fake_search_products)
        main.clear_product_search_cache()

        first = main.cached_search_products(sample_products, "kimchi", 4)
        first[0]["title"] = "Changed"
        second = main.cached_search_products(sample_products, "kimchi", 4)

        assert calls["count"] == 1
        assert second[0]["title"] == "Kimchi"

        main.clear_product_search_cache()


class TestGrounding:
    ALLOWED = {"https://www.foodland.sk/product/kimchi/"}

    def test_allowed_url_unchanged(self):
        url = "https://www.foodland.sk/product/kimchi/"
        answer = f"Najdete ho tu: {url}"
        result = validate_answer(answer, {url})
        assert url in result.sanitized_answer
        assert not result.has_violations

    def test_disallowed_bare_url_removed(self):
        answer = "Pozrite https://example-fake.com/product alebo tu."
        result = validate_answer(answer, self.ALLOWED)
        assert "example-fake.com" not in result.sanitized_answer
        assert result.has_violations

    def test_disallowed_markdown_url_becomes_label(self):
        answer = "Pozrite [Produkt X](https://fake.com/product) tu."
        result = validate_answer(answer, self.ALLOWED)
        assert "https://fake.com" not in result.sanitized_answer
        assert "Produkt X" in result.sanitized_answer

    def test_no_violations_clean_answer(self):
        answer = "Gochujang je korejska chilli pasta. Odporucam 500g balenie."
        result = validate_answer(answer, self.ALLOWED)
        assert not result.has_violations
        assert result.sanitized_answer == answer

    def test_collect_allowed_urls(self):
        products = [{"id": "FL_1", "title": "Kimchi", "link": "https://foodland.sk/kimchi/", "effective_price": 3.99, "currency": "EUR"}]
        urls = collect_allowed_urls(products)
        assert "https://foodland.sk/kimchi/" in urls

    def test_collect_allowed_prices(self):
        products = [{"effective_price": 3.99}, {"effective_price": 1.5}]
        prices = collect_allowed_prices(products)
        assert "3.99" in prices
        assert "1.50" in prices

    def test_price_check_strict_mode(self):
        products = [{"effective_price": 2.99}]
        prices = collect_allowed_prices(products)
        answer = "Tento produkt stoji 99.99 EUR."
        result = validate_answer(answer, set(), prices, strict_prices=True)
        assert result.has_violations

    def test_price_check_allowed_price(self):
        products = [{"effective_price": 2.99}]
        prices = collect_allowed_prices(products)
        answer = "Cena je 2.99 EUR."
        result = validate_answer(answer, set(), prices, strict_prices=True)
        assert not any("suspicious" in v for v in result.violations)


class TestWorkflows:
    def _detect(self, message: str) -> str:
        return detect_workflow(
            message,
            detect_allergen_fn=main.detect_allergen_intent,
            detect_faq_fn=main.is_faq_intent,
            detect_recipe_subject_fn=main.detect_recipe_subject,
            detect_out_of_domain_fn=main.detect_out_of_domain,
            detect_special_fn=main.detect_special_product_subject,
            detect_related_fn=main.detect_related_subject,
        )

    def test_allergen_workflow(self):
        assert self._detect("alergia na arasidy") == "allergen_safety"

    def test_faq_workflow(self):
        assert self._detect("kolko stoji doprava?") == "faq"

    def test_recipe_only_workflow(self):
        assert self._detect("recept na kimchi") == "recipe_only"

    def test_recipe_to_products_workflow(self):
        wf = self._detect("produkty na recept kimchi")
        assert wf == "recipe_to_products"

    def test_out_of_domain_workflow(self):
        assert self._detect("predate bicykle?") == "out_of_domain"

    def test_product_search_workflow(self):
        assert self._detect("gochujang pasta") == "product_search"

    def test_cross_sell_workflow(self):
        wf = self._detect("co potrebujem na kimchi?")
        assert wf == "cross_sell"

    def test_contract_has_allowed_sources(self):
        contract = get_contract("faq")
        assert "FAQ" in contract["allowed_sources"]

    def test_contract_recipe_to_products_has_products(self):
        contract = get_contract("recipe_to_products")
        assert "products" in contract["allowed_sources"]
        assert "one_best_product_per_ingredient" in contract["rules"]

    def test_feature_flag_disables_workflow(self, monkeypatch):
        monkeypatch.setenv("WORKFLOW_DISABLE", "faq")
        wf = self._detect("kolko stoji doprava?")
        assert wf != "faq"

    def test_cart_candidates_schema(self):
        products = [
            {"id": "FL_100", "title": "Kimchi 500g", "effective_price": 4.99, "currency": "EUR", "link": "https://foodland.sk/kimchi/"},
            {"id": "FL_101", "title": "Gochujang 500g", "effective_price": 3.50, "currency": "EUR", "link": "https://foodland.sk/gochujang/"},
        ]
        candidates = products_to_cart_candidates(products, "Ingrediencie na kimchi")
        assert len(candidates) == 2
        assert candidates[0]["product_id"] == "FL_100"
        assert candidates[0]["quantity"] == 1
        assert candidates[0]["reason"] == "Ingrediencie na kimchi"

    def test_recommendation_annotations_feed_cart_candidates(self):
        products = [
            {"id": "FL_100", "title": "Sushi ryza 1kg", "effective_price": 4.99, "currency": "EUR", "link": "https://foodland.sk/sushi-ryza/"},
            {"id": "FL_101", "title": "Ryzovy ocot 500ml", "effective_price": 3.50, "currency": "EUR", "link": "https://foodland.sk/ryzovy-ocot/"},
        ]
        main.annotate_recommendations(products, "related_products", "sushi", None, None, "co k sushi")
        candidates = main.cart_candidates_for_response(products, "related_products", "sushi")

        assert products[0]["recommendation_reason"]
        assert products[0]["recommendation_group"] == "Základ"
        assert "á" in products[0]["recommendation_reason"] or "í" in products[0]["recommendation_reason"]
        assert candidates[0]["recommendation_reason"] == products[0]["recommendation_reason"]
        assert candidates[0]["recommendation_group"] == "Základ"

    def test_article_recommendation_reason_is_human_readable(self):
        product = {"id": "FL_100", "title": "Kimchi krajané JONGGA 1000 g"}
        main.annotate_recommendations([product], "article_products", "kimchi_article")
        reason = product["recommendation_reason"]

        assert "kimchi_article" not in reason
        assert "_" not in reason
        assert "Ak vás zaujal článok o kimchi" in reason

class TestAllergenSafetyAnswer:
    def test_answer_contains_verify_instruction(self):
        answer = main.allergen_safety_answer("lepok")
        assert "overte" in answer.lower() or "detail" in answer.lower()

    def test_answer_mentions_allergen(self):
        answer = main.allergen_safety_answer("arasidy")
        assert "arasidy" in answer or "arasid" in answer

    def test_answer_generic_allergen(self):
        answer = main.allergen_safety_answer("alergeny")
        assert "alergen" in answer.lower() or "overte" in answer.lower()


class TestAutocomplete:
    def test_products_prefix_match(self, products):
        results = autocomplete_products(products, "gochuj", 4)
        assert results
        assert any("gochujang" in nrm(r["title"]) for r in results)
        assert all({"title", "url", "price", "image"} <= set(r.keys()) for r in results)

    def test_products_word_prefix_match(self, products):
        results = autocomplete_products(products, "ryza", 4)
        assert results
        assert any("ryza" in nrm(r["title"]) for r in results)

    def test_products_empty_query_returns_nothing(self, products):
        assert autocomplete_products(products, "", 4) == []
        assert autocomplete_products(products, "   ", 4) == []

    def test_products_respects_limit(self, products):
        results = autocomplete_products(products, "sushi", 2)
        assert len(results) <= 2

    def test_categories_prefix_match(self, products):
        results = autocomplete_categories(products, "sus", 5)
        assert results
        assert any("sus" in nrm(category) for category in results)

    def test_brands_prefix_match(self, products):
        results = autocomplete_brands(products, "otto", 5)
        assert results
        assert any(nrm(brand).startswith("otto") for brand in results)

    def test_questions_prefix_match(self):
        top_questions = [
            {"question": "Co je gochujang?", "normalized": "co je gochujang", "count": 5},
            {"question": "Recept na ramen", "normalized": "recept na ramen", "count": 3},
        ]
        results = autocomplete_questions(top_questions, "co je", 3)
        assert results == ["Co je gochujang?"]

    def test_questions_empty_query_returns_nothing(self):
        top_questions = [{"question": "Co je gochujang?", "normalized": "co je gochujang", "count": 5}]
        assert autocomplete_questions(top_questions, "", 3) == []

    def test_endpoint_returns_all_four_sections(self, products, monkeypatch):
        monkeypatch.setattr(main, "products", products)
        monkeypatch.setattr(main, "cached_top_questions", lambda: [
            {"question": "Co je gochujang?", "normalized": "co je gochujang", "count": 5},
        ])
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))
        result = main.autocomplete(request, q="gochuj", limit=4)

        assert set(result.keys()) == {"products", "categories", "brands", "top_questions"}
        assert result["products"]
        assert result["top_questions"] == ["Co je gochujang?"]

    def test_endpoint_clamps_limit(self, products, monkeypatch):
        monkeypatch.setattr(main, "products", products)
        monkeypatch.setattr(main, "cached_top_questions", lambda: [])
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))
        result = main.autocomplete(request, q="sushi", limit=999)

        assert len(result["products"]) <= 12

    def test_cached_top_questions_reuses_result_within_ttl(self, monkeypatch, tmp_path):
        log_path = tmp_path / "question_analytics.jsonl"
        log_path.write_text('{"ts": 9999999999, "message": "co je kimchi", "matches_count": 1, "intent": "article_products"}\n', encoding="utf-8")
        monkeypatch.setenv("ANALYTICS_LOG_PATH", str(log_path))
        monkeypatch.setattr(main, "_top_questions_cache", [])
        monkeypatch.setattr(main, "_top_questions_cache_at", 0.0)

        first = main.cached_top_questions()
        log_path.write_text("", encoding="utf-8")
        second = main.cached_top_questions()

        assert first == second


class TestRecommend:
    def test_find_product_by_id(self, products):
        sample = products[0].id
        found = main.find_product_by_id(products, sample)
        assert found is not None

    def test_find_product_by_id_missing_returns_none(self, products):
        assert main.find_product_by_id(products, "NOT_A_REAL_SKU") is None

    def test_knowledge_record_by_id_cross_sell(self, knowledge):
        cross_sell_records = knowledge.get("sections", {}).get("CrossSell", [])
        assert cross_sell_records
        sample_id = cross_sell_records[0]["ID"]
        record = main.knowledge_record_by_id(knowledge, "CrossSell", sample_id)
        assert record is not None
        assert record["ID"] == sample_id

    def test_linked_products_from_record_resolves_cross_sell(self, products, knowledge):
        cross_sell_records = knowledge.get("sections", {}).get("CrossSell", [])
        record = next((r for r in cross_sell_records if r.get("Cross-sell 1")), None)
        assert record is not None
        results = main.linked_products_from_record(products, record, "Cross-sell", 5)
        assert isinstance(results, list)
        assert len(results) <= 5

    def test_recommend_similar_returns_product_and_recommendations(self, products, knowledge, monkeypatch):
        monkeypatch.setattr(main, "products", products)
        monkeypatch.setattr(main, "knowledge", knowledge)
        sample_sku = products[0].id

        result = main.recommend_similar(sku=sample_sku, limit=4)

        assert result["sku"] == sample_sku
        assert result["product"] is not None
        assert isinstance(result["recommendations"], list)
        assert len(result["recommendations"]) <= 4
        assert all(r.get("id") != sample_sku for r in result["recommendations"])

    def test_recommend_similar_unknown_sku(self, products, knowledge, monkeypatch):
        monkeypatch.setattr(main, "products", products)
        monkeypatch.setattr(main, "knowledge", knowledge)

        result = main.recommend_similar(sku="NOT_REAL", limit=4)

        assert result["product"] is None
        assert result["recommendations"] == []

    def test_find_recipe_record_fuzzy_match(self, knowledge):
        recipes = knowledge.get("sections", {}).get("Recipes", [])
        assert recipes
        first_title = main.first_record_value(recipes[0], ("Recept", "recipe", "nazov", "názov"))
        assert first_title

        record = main.find_recipe_record(knowledge, first_title)

        assert record is not None

    def test_recommend_recipe_unknown_name(self, products, knowledge, monkeypatch):
        monkeypatch.setattr(main, "products", products)
        monkeypatch.setattr(main, "knowledge", knowledge)

        result = main.recommend_recipe(name="totally made up recipe xyz123", limit=4)

        assert result["recipe"] is None
        assert result["recommendations"] == []

    def test_recommend_recipe_known_name_returns_recipe_card(self, products, knowledge, monkeypatch):
        recipes = knowledge.get("sections", {}).get("Recipes", [])
        first_title = main.first_record_value(recipes[0], ("Recept", "recipe", "nazov", "názov"))
        monkeypatch.setattr(main, "products", products)
        monkeypatch.setattr(main, "knowledge", knowledge)

        result = main.recommend_recipe(name=first_title, limit=4)

        assert result["recipe"] is not None
        assert isinstance(result["recommendations"], list)

    def test_basket_recommendations_excludes_basket_items(self, products, knowledge):
        sample_sku = products[0].id

        results = main.basket_recommendations(products, knowledge, [sample_sku], 5)

        assert all(r.get("id") != sample_sku for r in results)

    def test_trending_product_skus_weights_add_to_cart_over_impression(self, monkeypatch):
        events = [
            {"ts": 9999999999, "event_type": "impression", "product_skus": ["A", "B"]},
            {"ts": 9999999999, "event_type": "add_to_cart", "product_sku": "B"},
        ]
        monkeypatch.setattr(main, "read_engagement_events", lambda days=14: events)

        ranked = main.trending_product_skus(10)

        assert ranked[0] == "B"

    def test_cached_trending_products_falls_back_when_no_events(self, products, monkeypatch):
        monkeypatch.setattr(main, "_trending_products_cache", [])
        monkeypatch.setattr(main, "_trending_products_cache_at", 0.0)
        monkeypatch.setattr(main, "read_engagement_events", lambda days=14: [])

        results = main.cached_trending_products(products, 5)

        assert isinstance(results, list)
        assert results

    def test_recommend_trending_endpoint(self, products, monkeypatch):
        monkeypatch.setattr(main, "products", products)
        monkeypatch.setattr(main, "_trending_products_cache", [])
        monkeypatch.setattr(main, "_trending_products_cache_at", 0.0)
        monkeypatch.setattr(main, "read_engagement_events", lambda days=14: [])

        result = main.recommend_trending(limit=5)

        assert isinstance(result["recommendations"], list)
        assert len(result["recommendations"]) <= 5

    def test_recommend_basket_endpoint(self, products, knowledge, monkeypatch):
        monkeypatch.setattr(main, "products", products)
        monkeypatch.setattr(main, "knowledge", knowledge)
        sample_sku = products[0].id
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))
        basket_request = main.BasketRecommendRequest(skus=[sample_sku], limit=4)

        result = main.recommend_basket(basket_request, request)

        assert isinstance(result["recommendations"], list)
        assert all(r.get("id") != sample_sku for r in result["recommendations"])


def make_filter_request(**overrides):
    defaults = dict(
        query="",
        price_min=None,
        price_max=None,
        brand=None,
        availability="all",
        category=None,
        dietary=None,
        limit=20,
    )
    defaults.update(overrides)
    return main.ProductFilterRequest(**defaults)


class TestProductFilter:
    def test_filter_by_price_range(self, products):
        prices = sorted(p.effective_price for p in products if p.effective_price is not None)
        assert prices
        mid = prices[len(prices) // 2]

        results = filter_products(products, price_min=mid, price_max=mid + 0.01)

        assert results
        for product in results:
            price = product.sale_price if product.sale_price is not None else product.price
            assert mid <= price <= mid + 0.01

    def test_filter_by_price_excludes_out_of_range(self, products):
        prices = sorted(p.effective_price for p in products if p.effective_price is not None)
        low = prices[0]

        results = filter_products(products, price_min=low + 1000)

        assert results == []

    def test_filter_by_brand(self, products):
        sample_brand = next((p.brand for p in products if p.brand), None)
        assert sample_brand

        results = filter_products(products, brand=[sample_brand])

        assert results
        assert all(nrm(r.brand) == nrm(sample_brand) for r in results)

    def test_filter_by_availability_in_stock(self, products):
        results = filter_products(products, availability="in_stock")
        assert results
        assert all(r.availability in {"in_stock", "in stock"} for r in results)

    def test_filter_by_category_substring(self, products):
        results = filter_products(products, category=["susi"])
        assert results
        assert all("susi" in nrm(r.product_type) for r in results)

    def test_filter_by_dietary_gluten_free(self, products):
        results = filter_products(products, dietary=["bezlepkove"])
        assert results
        assert all("bezlepkove" in nrm(r.product_type) for r in results)

    def test_filter_combines_all_criteria(self, products):
        combined = filter_products(products, availability="in_stock", category=["susi"])
        category_only = filter_products(products, category=["susi"])

        assert combined
        assert len(combined) <= len(category_only)

    def test_filter_no_criteria_returns_everything(self, products):
        assert len(filter_products(products)) == len(products)


class TestProductFacets:
    def test_compute_product_facets_returns_brands_categories_and_price_range(self, products):
        facets = compute_product_facets(products)

        assert facets["brands"]
        assert facets["categories"]
        assert facets["price_min"] is not None
        assert facets["price_max"] is not None
        assert facets["price_min"] <= facets["price_max"]

    def test_product_facets_endpoint(self, products, monkeypatch):
        monkeypatch.setattr(main, "products", products)
        monkeypatch.setattr(main, "_facets_cache", None)
        monkeypatch.setattr(main, "_facets_cache_at", 0.0)

        result = main.product_facets()

        assert result["brands"]
        assert result["categories"]

    def test_product_filter_endpoint_with_query(self, products, monkeypatch):
        monkeypatch.setattr(main, "products", products)

        request = make_filter_request(query="gochujang", limit=5)
        result = main.product_filter(request)

        assert result["products"]
        assert result["total_matches"] >= len(result["products"])

    def test_product_filter_endpoint_without_query_uses_filters_only(self, products, monkeypatch):
        monkeypatch.setattr(main, "products", products)
        sample_brand = next((p.brand for p in products if p.brand), None)

        request = make_filter_request(brand=[sample_brand], limit=100)
        result = main.product_filter(request)

        assert result["products"]
        assert all(nrm(p["brand"]) == nrm(sample_brand) for p in result["products"])


REGRESSION_CASES = [
    ("mate bezlepkovu sojovu omacku?", "product_search"),
    ("alergia na arasidy, co mozem kupit?", "allergen_safety"),
    ("mam alergiu na lepok, co by ste odporucili?", "allergen_safety"),
    ("kolko stoji doprava?", "faq"),
    ("da sa platit kartou?", "faq"),
    ("postovne", "faq"),
    ("potrebujem recept na kimchi", "recipe_only"),
    ("predate bicykle?", "out_of_domain"),
    ("co sa hodi ku gochujang?", "cross_sell"),
]


@pytest.mark.parametrize("query,expected_intent", REGRESSION_CASES)
def test_regression_intent(query, expected_intent):
    allergen = main.detect_allergen_intent(query)
    is_faq = main.is_faq_intent(query)
    recipe = main.detect_recipe_subject(query)
    ood = main.detect_out_of_domain(query)
    related = main.detect_related_subject(query)

    if allergen:
        actual = "allergen_safety"
    elif is_faq:
        actual = "faq"
    elif recipe:
        nm = normalize(query)
        actual = "recipe_to_products" if any(m in nm for m in ("produkty","suroviny","nakupny")) else "recipe_only"
    elif ood:
        actual = "out_of_domain"
    elif related:
        actual = "cross_sell"
    else:
        actual = "product_search"

    assert actual == expected_intent, \
        f"Intent mismatch for '{query}': got {actual}, expected {expected_intent}"

