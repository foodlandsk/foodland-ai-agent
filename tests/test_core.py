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
import sys
import types
import unicodedata
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

from app.feed import load_products_json
from app.search import autocomplete_suggestions, normalize, tokenize, search_products
from app.knowledge import load_knowledge_json, search_knowledge, best_faq_answer
from app.grounding import validate_answer, collect_allowed_urls, collect_allowed_prices
from app.workflows import detect_workflow, get_contract, products_to_cart_candidates
import app.main as main


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


class TestSearchProducts:
    def test_sushi_rice_not_vinegar(self, products):
        results = search_products(products, "sushi ryza", 6)
        top_titles = " ".join(r.get("title","") for r in results[:3])
        assert "ocot" not in nrm(top_titles) and "vinegar" not in nrm(top_titles)

    def test_sushi_rice_found(self, products):
        results = search_products(products, "sushi ryza", 6)
        assert titles_contain(results, "susi ryza", "sushi ryza", "susi ryz")

    def test_gochujang_found(self, products):
        results = search_products(products, "gochujang", 4)
        assert titles_contain(results, "gochujang", "Gochujang")

    def test_typo_gochujang(self, products):
        results = search_products(products, "gochuang", 4)
        assert titles_contain(results, "gochujang")

    def test_kimchi_found(self, products):
        results = search_products(products, "kimchi", 4)
        assert titles_contain(results, "kimchi", "kimci")

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

    def test_luigis_style_synonym_soy_sauce(self, products):
        results = search_products(products, "soy sauce", 6)
        assert titles_contain(results, "sojova omacka", "soy sauce", "tamari")

    def test_luigis_style_typo_coconut_milk(self, products):
        results = search_products(products, "coconat milk", 6)
        assert titles_contain(results, "kokosove mlieko", "coconut milk")

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
        }
        for query, expected_terms in cases.items():
            suggestions = autocomplete_suggestions(products, query, 6)
            labels = " | ".join(item["label"] for item in suggestions)
            assert suggestions, f"Missing suggestions for {query}"
            normalized_labels = nrm(labels)
            assert any(term in normalized_labels for term in expected_terms), labels


class TestIntentDetection:
    def test_allergen_arasidy(self):
        assert main.detect_allergen_intent("alergia na arasidy, co mozem kupit?") is not None

    def test_allergen_lepok(self):
        term = main.detect_allergen_intent("mam celiakiu, bezlepkove produkty")
        assert term == "lepok"

    def test_allergen_NOT_triggered_for_product_search(self):
        term = main.detect_allergen_intent("mate bezlepkovu sojovu omacku?")
        assert term is None, f"False allergen trigger: {term}"

    def test_faq_doprava(self):
        assert main.is_faq_intent("kolko stoji doprava?")

    def test_faq_platba(self):
        assert main.is_faq_intent("da sa platit kartou?")

    def test_faq_NOT_triggered_for_product(self):
        assert not main.is_faq_intent("gochujang pasta")

    def test_recipe_detected(self):
        assert main.detect_recipe_subject("recept na kimchi") is not None

    def test_recipe_subject_kimchi(self):
        subj = main.detect_recipe_subject("recept na kimchi")
        assert subj == "kimchi"

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
        assert "pho" in nrm(titles)
        assert "pad thai" not in nrm(titles)

    def test_recipe_product_intent_is_explicit(self):
        assert not main.wants_recipe_products("recept na pho bo")
        assert main.wants_recipe_products("recept na pho bo a produkty")
        assert main.wants_recipe_products("co potrebujem k receptu pho bo")

    def test_pho_recipe_products_prioritize_spices_then_noodles(self, products):
        matches = main.related_products_for_subject(products, "pho", 8)
        main.annotate_recommendations(matches, "recipe_to_products", related_subject="pho")

        groups = [product["recommendation_group"] for product in matches]
        titles = " | ".join(product["title"] for product in matches)
        first_noodle_index = groups.index("Zaklad")

        assert groups[0] == "Korenie a vyvar"
        assert first_noodle_index > 0
        assert all(group == "Korenie a vyvar" for group in groups[:first_noodle_index])
        assert "rezance" in nrm(titles) or "banh pho" in nrm(titles)

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
        assert subj == "kimchi"

    def test_special_gluten_free_sushi(self):
        subj = main.detect_special_product_subject("bezlepkove sushi")
        assert subj == "gluten_free_sushi"

    def test_special_rice_vinegar(self):
        subj = main.detect_special_product_subject("ryzovy ocot")
        assert subj == "rice_vinegar"

    def test_special_vegan_fish_sauce(self):
        subj = main.detect_special_product_subject("nahrada za rybaciu omacku vegan")
        assert subj == "vegan_fish_sauce_replacement"


class TestRelatedProducts:
    def test_sushi_related_no_sushi_rice(self, products):
        """related_products_for_subject('sushi') nesmie vratit sushi ryzu."""
        results = main.related_products_for_subject(products, "sushi", 8)
        for p in results:
            title_nrm = nrm(p.get("title", ""))
            is_sushi_rice = "susi" in title_nrm.split() and "ryza" in title_nrm
            assert not is_sushi_rice, f"sushi ryza in related sushi: {p.get('title')}"

    def test_kimchi_related_no_kimchi_itself(self, products):
        results = main.related_products_for_subject(products, "kimchi", 8)
        for p in results:
            assert "kimchi" not in nrm(p.get("title", ""))

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
        assert products[0]["recommendation_group"] == "Zaklad"
        assert candidates[0]["recommendation_reason"] == products[0]["recommendation_reason"]
        assert candidates[0]["recommendation_group"] == "Zaklad"

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

