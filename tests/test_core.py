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
import tempfile
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
    clear_behavioral_rankings_cache,
    clear_merchandising_cache,
    compute_product_facets,
    filter_products,
    get_behavioral_rankings,
    get_merchandising_rules,
    normalize,
    tokenize,
    search_products,
)
from app.knowledge import load_knowledge_json, search_knowledge, best_faq_answer, best_product_advice_answer
from app.grounding import validate_answer, collect_allowed_urls, collect_allowed_prices
from app.workflows import detect_workflow, get_contract, products_to_cart_candidates
from app.embeddings import (
    build_product_embeddings,
    cosine_similarity,
    embed_texts,
    load_embeddings,
    product_embedding_text,
    save_embeddings,
    semantic_search,
)
from app.behavioral import (
    baseline_ctr,
    behavioral_multiplier,
    compute_engagement_scores,
    load_behavioral_rankings,
)
from app.fbt import (
    build_baskets,
    compute_pair_counts,
    fbt_recommendations,
    load_fbt_data,
    pairs_by_sku,
)
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


class _FakeEmbeddingItem:
    def __init__(self, embedding):
        self.embedding = embedding


class _FakeEmbeddingResponse:
    def __init__(self, embeddings):
        self.data = [_FakeEmbeddingItem(e) for e in embeddings]


class _FakeEmbeddingsAPI:
    def __init__(self, vector_fn):
        self.vector_fn = vector_fn
        self.calls = []

    def create(self, model, input):
        self.calls.append({"model": model, "input": list(input)})
        return _FakeEmbeddingResponse([self.vector_fn(text) for text in input])


class _FakeOpenAIClient:
    def __init__(self, vector_fn):
        self.embeddings = _FakeEmbeddingsAPI(vector_fn)


class _FakeScopedOpenAIClient(_FakeOpenAIClient):
    """Mirrors the real OpenAI SDK's with_options(timeout=...): records the
    timeout it was scoped to, on the same underlying embeddings API so call
    history is still visible on the original client."""
    def __init__(self, vector_fn):
        super().__init__(vector_fn)
        self.with_options_calls = []

    def with_options(self, timeout=None):
        self.with_options_calls.append({"timeout": timeout})
        scoped = _FakeOpenAIClient.__new__(_FakeOpenAIClient)
        scoped.embeddings = self.embeddings
        return scoped


def _make_vector_fn(mapping, default=(0.0, 0.0, 1.0)):
    def vector_fn(text):
        for key, vector in mapping.items():
            if key in text:
                return list(vector)
        return list(default)
    return vector_fn


class TestEmbeddings:
    def test_cosine_similarity_identical_vectors_is_one(self):
        assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)

    def test_cosine_similarity_orthogonal_vectors_is_zero(self):
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_cosine_similarity_opposite_vectors_is_negative_one(self):
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_cosine_similarity_handles_zero_vector(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_cosine_similarity_handles_empty_or_mismatched(self):
        assert cosine_similarity([], []) == 0.0
        assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0

    def test_product_embedding_text_includes_title_brand_category(self, products):
        sample = products[0]
        text = product_embedding_text(sample)

        assert sample.title in text
        assert sample.brand in text

    def test_embed_texts_empty_list_returns_empty(self):
        client = _FakeOpenAIClient(_make_vector_fn({}))
        assert embed_texts(client, []) == []

    def test_embed_texts_calls_client_with_given_texts(self):
        client = _FakeOpenAIClient(_make_vector_fn({"gochujang": [1.0, 0.0]}))
        result = embed_texts(client, ["gochujang pasta"])

        assert result == [[1.0, 0.0]]
        assert client.embeddings.calls[0]["input"] == ["gochujang pasta"]

    def test_embed_texts_overrides_client_timeout_for_batch_calls(self):
        # Regression test: the shared OpenAI client used elsewhere in the app
        # is tuned for interactive chat (a few seconds), which is too short
        # for an embeddings batch call of many texts at once and caused a
        # real production timeout (openai.APITimeoutError) during D1
        # verification. embed_texts must scope a longer timeout via
        # with_options() rather than reusing the client's default.
        client = _FakeScopedOpenAIClient(_make_vector_fn({"gochujang": [1.0, 0.0]}))

        embed_texts(client, ["gochujang pasta"])

        assert client.with_options_calls
        assert client.with_options_calls[0]["timeout"] > 6

    def test_build_product_embeddings_keys_by_product_id(self, products):
        sample = products[:3]
        client = _FakeOpenAIClient(_make_vector_fn({}, default=(1.0, 0.0, 0.0)))

        embeddings = build_product_embeddings(client, sample, batch_size=2)

        assert set(embeddings.keys()) == {p.id for p in sample}

    def test_save_and_load_embeddings_roundtrip(self, tmp_path):
        path = tmp_path / "embeddings.json"
        original = {"FL_1": [0.1, 0.2], "FL_2": [0.3, 0.4]}

        save_embeddings(original, str(path))
        loaded = load_embeddings(str(path))

        assert loaded == original

    def test_load_embeddings_missing_file_returns_empty(self, tmp_path):
        assert load_embeddings(str(tmp_path / "does_not_exist.json")) == {}

    def test_semantic_search_ranks_by_similarity(self):
        client = _FakeOpenAIClient(_make_vector_fn({"gochujang": [1.0, 0.0]}))
        product_embeddings = {
            "FL_gochujang": [1.0, 0.0],
            "FL_unrelated": [0.0, 1.0],
        }

        results = semantic_search(client, "gochujang pasta", product_embeddings, limit=2)

        assert results[0][0] == "FL_gochujang"
        assert results[0][1] > results[1][1]

    def test_semantic_search_empty_query_returns_empty(self):
        client = _FakeOpenAIClient(_make_vector_fn({}))
        assert semantic_search(client, "   ", {"FL_1": [1.0, 0.0]}) == []

    def test_semantic_search_no_embeddings_returns_empty(self):
        client = _FakeOpenAIClient(_make_vector_fn({}))
        assert semantic_search(client, "gochujang", {}) == []


class TestBehavioralRanking:
    def test_compute_engagement_scores_counts_by_type(self):
        events = [
            {"event_type": "impression", "product_skus": ["FL_1", "FL_2"]},
            {"event_type": "impression", "product_skus": ["FL_1"]},
            {"event_type": "click", "product_sku": "FL_1"},
            {"event_type": "add_to_cart", "product_sku": "FL_1"},
        ]
        scores = compute_engagement_scores(events)

        assert scores["FL_1"]["impressions"] == 2
        assert scores["FL_1"]["clicks"] == 1
        assert scores["FL_1"]["add_to_cart"] == 1
        assert scores["FL_2"]["impressions"] == 1
        assert scores["FL_2"]["clicks"] == 0

    def test_compute_engagement_scores_smoothed_ctr_uses_prior(self):
        # A single impression and no clicks should sit close to the prior
        # baseline, not swing to a literal 0% CTR.
        events = [{"event_type": "impression", "product_skus": ["FL_1"]}]
        scores = compute_engagement_scores(events, prior_clicks=1.0, prior_impressions=40.0)

        expected = 1.0 / 41.0
        assert scores["FL_1"]["ctr"] == pytest.approx(expected)

    def test_baseline_ctr_is_pooled_not_averaged(self):
        # Regression test: a naive average-of-ratios baseline is dominated by
        # low-sample outliers (e.g. 1 click out of 1 impression = 100%
        # "CTR"), which is exactly what caused a real production incident.
        # The pooled sum-of-clicks-over-sum-of-impressions baseline is not.
        scores = {
            "FL_lucky": {"clicks": 1, "impressions": 1},
            "FL_normal_1": {"clicks": 5, "impressions": 500},
            "FL_normal_2": {"clicks": 5, "impressions": 500},
        }
        # naive average of individual ratios would be dragged way up by
        # FL_lucky's 1/1 ratio; pooled should stay close to the bulk rate.
        pooled = baseline_ctr(scores, prior_clicks=1.0, prior_impressions=40.0)
        expected = (1 + 5 + 5 + 1.0) / (1 + 500 + 500 + 40.0)
        assert pooled == pytest.approx(expected)
        assert pooled < 0.05

    def test_baseline_ctr_empty_scores_returns_prior_ratio(self):
        assert baseline_ctr({}, prior_clicks=1.0, prior_impressions=40.0) == pytest.approx(0.025)

    def test_behavioral_multiplier_neutral_for_unknown_product(self):
        assert behavioral_multiplier("FL_missing", {}, baseline=0.1) == 1.0

    def test_behavioral_multiplier_neutral_when_baseline_zero(self):
        scores = {"FL_1": {"ctr": 0.5}}
        assert behavioral_multiplier("FL_1", scores, baseline=0.0) == 1.0

    def test_behavioral_multiplier_boosts_above_average_ctr(self):
        scores = {"FL_1": {"ctr": 0.2}}
        multiplier = behavioral_multiplier("FL_1", scores, baseline=0.1, weight=1.0)

        assert multiplier > 1.0

    def test_behavioral_multiplier_penalizes_below_average_ctr(self):
        scores = {"FL_1": {"ctr": 0.05}}
        multiplier = behavioral_multiplier("FL_1", scores, baseline=0.1, weight=1.0)

        assert multiplier < 1.0

    def test_behavioral_multiplier_clamps_extreme_ratios(self):
        scores = {"FL_huge": {"ctr": 100.0}, "FL_tiny": {"ctr": 0.0001}}

        high = behavioral_multiplier("FL_huge", scores, baseline=0.1, weight=1.0, max_ratio=2.0)
        low = behavioral_multiplier("FL_tiny", scores, baseline=0.1, weight=1.0, min_ratio=0.5)

        assert high == pytest.approx(2.0)
        assert low == pytest.approx(0.5)

    def test_load_behavioral_rankings_reads_from_file(self, tmp_path):
        path = tmp_path / "events.jsonl"
        now = int(time.time())
        lines = [
            json.dumps({"ts": now, "event_type": "impression", "product_skus": ["FL_1"]}),
            json.dumps({"ts": now, "event_type": "click", "product_sku": "FL_1"}),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Override the volume gate to exercise the "active" code path with a
        # small file; the gate itself is tested separately below.
        rankings = load_behavioral_rankings(days=30, path=str(path), min_total_impressions=0)

        assert rankings["active"] is True
        assert "FL_1" in rankings["scores"]
        assert rankings["baseline_ctr"] > 0

    def test_load_behavioral_rankings_missing_file_returns_neutral(self, tmp_path):
        rankings = load_behavioral_rankings(days=30, path=str(tmp_path / "does_not_exist.jsonl"))

        assert rankings["scores"] == {}
        assert rankings["baseline_ctr"] == 0.0
        assert rankings["active"] is False

    def test_load_behavioral_rankings_inactive_below_min_impressions(self, tmp_path):
        # Regression test for the real production incident: a handful of
        # impressions/clicks (this developer's own manual endpoint testing,
        # not organic traffic) must not activate the signal at all.
        path = tmp_path / "events.jsonl"
        now = int(time.time())
        lines = [json.dumps({"ts": now, "event_type": "impression", "product_skus": ["FL_1"]})] * 5
        lines.append(json.dumps({"ts": now, "event_type": "click", "product_sku": "FL_1"}))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        rankings = load_behavioral_rankings(days=30, path=str(path), min_total_impressions=1000)

        assert rankings["active"] is False
        assert rankings["scores"] == {}
        assert rankings["total_impressions"] == 5

    def test_load_behavioral_rankings_active_above_min_impressions(self, tmp_path):
        path = tmp_path / "events.jsonl"
        now = int(time.time())
        lines = [json.dumps({"ts": now, "event_type": "impression", "product_skus": ["FL_1"]})] * 10
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        rankings = load_behavioral_rankings(days=30, path=str(path), min_total_impressions=10)

        assert rankings["active"] is True
        assert rankings["total_impressions"] == 10

    def test_low_event_volume_has_near_neutral_effect_on_search(self, products, monkeypatch, tmp_path):
        # Safety property, reproducing the actual production incident: with
        # only a handful of real events (this developer's own manual testing
        # volume), the behavioral signal must not reorder results at all -
        # the min-impressions gate should keep it fully inactive until
        # genuine traffic accumulates, not just "mostly neutral".
        baseline_results = search_products(products, "omacka", 10)
        assert baseline_results

        path = tmp_path / "events.jsonl"
        now = int(time.time())
        lines = [
            json.dumps({"ts": now, "event_type": "impression", "product_skus": [baseline_results[0]["id"]]}),
            json.dumps({"ts": now, "event_type": "click", "product_sku": baseline_results[0]["id"]}),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rankings = load_behavioral_rankings(days=30, path=str(path))
        assert rankings["active"] is False

        monkeypatch.setattr(search_module, "_behavioral_rankings_cache", rankings)
        monkeypatch.setattr(search_module, "_behavioral_rankings_cache_at", time.time())

        boosted_results = search_products(products, "omacka", 10)

        assert [r["id"] for r in boosted_results] == [r["id"] for r in baseline_results]

    def test_behavioral_boost_promotes_high_ctr_product_with_real_traffic(self, products, monkeypatch):
        baseline_results = search_products(products, "omacka", 10)
        assert len(baseline_results) >= 2
        target_id = baseline_results[1]["id"]

        # Simulate substantial, clearly-differentiated real traffic: the
        # target product gets a much higher click-through rate than everyone
        # else, well past the point where the Bayesian prior would mask it.
        events = [{"event_type": "impression", "product_skus": [r["id"] for r in baseline_results]} for _ in range(200)]
        events += [{"event_type": "click", "product_sku": target_id} for _ in range(150)]
        scores = compute_engagement_scores(events)
        monkeypatch.setattr(search_module, "_behavioral_rankings_cache", {"scores": scores, "baseline_ctr": baseline_ctr(scores)})
        monkeypatch.setattr(search_module, "_behavioral_rankings_cache_at", time.time())

        boosted_results = search_products(products, "omacka", 10)

        assert boosted_results[0]["id"] == target_id

    def test_behavioral_penalty_does_not_suppress_explicit_brand_match(self, products, monkeypatch):
        # Real user report: "chcem sojovu omacku od kikkoman" (I want soy
        # sauce FROM Kikkoman) returned zero Kikkoman products - confirmed
        # via /admin/analytics/behavioral-rankings that a real Kikkoman SKU
        # had a below-baseline CTR (17 impressions, 0 clicks) eligible for
        # the full 0.5x behavioral penalty, enough to drop it below brands
        # the customer never named. A customer explicitly naming a
        # product's own brand is a much stronger and more certain
        # relevance signal than average CTR popularity, so it must not be
        # diluted by the behavioral multiplier.
        query = "chcem sojovu omacku od kikkoman"
        baseline_results = search_products(products, query, 6)
        assert baseline_results
        assert all(main.normalize(r.get("brand", "")) == "kikkoman" for r in baseline_results)

        scores = {r["id"]: {"ctr": 0.0175, "impressions": 17, "clicks": 0} for r in baseline_results}
        monkeypatch.setattr(search_module, "_behavioral_rankings_cache", {"scores": scores, "baseline_ctr": 0.035})
        monkeypatch.setattr(search_module, "_behavioral_rankings_cache_at", time.time())

        penalized_results = search_products(products, query, 6)
        assert all(main.normalize(r.get("brand", "")) == "kikkoman" for r in penalized_results)

        # A generic query naming no brand must still be affected normally.
        generic_baseline = search_products(products, "sojova omacka", 6)
        target_id = generic_baseline[0]["id"]
        boost_scores = {target_id: {"ctr": 0.0175, "impressions": 17, "clicks": 0}}
        monkeypatch.setattr(search_module, "_behavioral_rankings_cache", {"scores": boost_scores, "baseline_ctr": 0.035})
        penalized_generic = search_products(products, "sojova omacka", 6)
        assert [r["id"] for r in penalized_generic] != [r["id"] for r in generic_baseline]

    def test_admin_behavioral_rankings_requires_token(self, monkeypatch):
        monkeypatch.delenv("ADMIN_ANALYTICS_TOKEN", raising=False)
        monkeypatch.delenv("ADMIN_RELOAD_TOKEN", raising=False)

        with pytest.raises(main.HTTPException):
            main.admin_behavioral_rankings(limit=20, x_admin_token=None)

    def test_admin_behavioral_rankings_returns_scored_products(self, monkeypatch):
        monkeypatch.setenv("ADMIN_ANALYTICS_TOKEN", "test-token")
        fake_rankings = {
            "scores": {
                "FL_1": {"impressions": 100, "clicks": 20, "add_to_cart": 5, "ctr": 0.2},
                "FL_2": {"impressions": 100, "clicks": 2, "add_to_cart": 0, "ctr": 0.02},
            },
            "baseline_ctr": 0.1,
        }
        monkeypatch.setattr(main, "get_behavioral_rankings", lambda: fake_rankings)

        result = main.admin_behavioral_rankings(limit=1, x_admin_token="test-token")

        assert result["products_with_scores"] == 2
        assert result["top_products"][0]["product_sku"] == "FL_1"
        assert result["bottom_products"][0]["product_sku"] == "FL_2"


class TestFbt:
    def test_build_baskets_groups_by_session_and_drops_singletons(self):
        events = [
            {"session_id": "s1", "event_type": "add_to_cart", "product_sku": "FL_1"},
            {"session_id": "s1", "event_type": "add_to_cart", "product_sku": "FL_2"},
            {"session_id": "s2", "event_type": "add_to_cart", "product_sku": "FL_3"},
            {"session_id": "s3", "event_type": "click", "product_sku": "FL_4"},
        ]
        baskets = build_baskets(events)

        assert {"FL_1", "FL_2"} in baskets
        assert len(baskets) == 1

    def test_build_baskets_drops_oversized_basket(self):
        events = [
            {"session_id": "bot", "event_type": "add_to_cart", "product_sku": f"FL_{i}"}
            for i in range(30)
        ]
        baskets = build_baskets(events, max_basket_size=25)

        assert baskets == []

    def test_compute_pair_counts_counts_cooccurrence(self):
        baskets = [{"FL_1", "FL_2"}, {"FL_1", "FL_2"}, {"FL_1", "FL_3"}]
        pair_counts = compute_pair_counts(baskets)

        assert pair_counts[("FL_1", "FL_2")] == 2
        assert pair_counts[("FL_1", "FL_3")] == 1

    def test_pairs_by_sku_filters_below_min_count(self):
        pair_counts = {("FL_1", "FL_2"): 3, ("FL_1", "FL_3"): 1}
        pairs = pairs_by_sku(pair_counts, min_pair_count=3)

        assert pairs["FL_1"] == [("FL_2", 3)]
        assert "FL_3" not in pairs.get("FL_1", [])

    def test_pairs_by_sku_sorted_by_count_desc_and_symmetric(self):
        pair_counts = {("FL_1", "FL_2"): 3, ("FL_1", "FL_3"): 5}
        pairs = pairs_by_sku(pair_counts, min_pair_count=1)

        assert pairs["FL_1"] == [("FL_3", 5), ("FL_2", 3)]
        assert pairs["FL_2"] == [("FL_1", 3)]
        assert pairs["FL_3"] == [("FL_1", 5)]

    def test_load_fbt_data_missing_file_returns_inactive(self, tmp_path):
        data = load_fbt_data(days=60, path=str(tmp_path / "does_not_exist.jsonl"))

        assert data["active"] is False
        assert data["pairs"] == {}
        assert data["total_add_to_cart_events"] == 0

    def test_load_fbt_data_inactive_below_min_add_to_cart_events(self, tmp_path):
        # Regression guard mirroring the D2 incident: this developer's own
        # manual testing (a handful of add_to_cart events) must not be
        # enough to activate FBT pairs.
        path = tmp_path / "events.jsonl"
        now = int(time.time())
        lines = [
            json.dumps({"ts": now, "session_id": "s1", "event_type": "add_to_cart", "product_sku": "FL_1"}),
            json.dumps({"ts": now, "session_id": "s1", "event_type": "add_to_cart", "product_sku": "FL_2"}),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        data = load_fbt_data(days=60, path=str(path), min_add_to_cart_events=200)

        assert data["active"] is False
        assert data["pairs"] == {}
        assert data["total_add_to_cart_events"] == 2

    def test_load_fbt_data_active_above_min_events_and_pair_count(self, tmp_path):
        path = tmp_path / "events.jsonl"
        now = int(time.time())
        lines = []
        for i in range(5):
            session_id = f"s{i}"
            lines.append(json.dumps({"ts": now, "session_id": session_id, "event_type": "add_to_cart", "product_sku": "FL_1"}))
            lines.append(json.dumps({"ts": now, "session_id": session_id, "event_type": "add_to_cart", "product_sku": "FL_2"}))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        data = load_fbt_data(days=60, path=str(path), min_add_to_cart_events=10, min_pair_count=3)

        assert data["active"] is True
        assert data["total_add_to_cart_events"] == 10
        assert ("FL_2", 5) in data["pairs"]["FL_1"]

    def test_fbt_recommendations_returns_empty_when_inactive(self):
        data = {"active": False, "pairs": {"FL_1": [("FL_2", 5)]}}

        assert fbt_recommendations("FL_1", data, 5) == []

    def test_fbt_recommendations_returns_top_n_when_active(self):
        data = {
            "active": True,
            "pairs": {"FL_1": [("FL_2", 5), ("FL_3", 3), ("FL_4", 1)]},
        }

        assert fbt_recommendations("FL_1", data, 2) == ["FL_2", "FL_3"]
        assert fbt_recommendations("FL_missing", data, 2) == []


class TestSemanticSearchEndpoint:
    def test_endpoint_returns_error_without_openai_client(self, monkeypatch):
        monkeypatch.setattr(main, "_get_openai_client", lambda: None)
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))

        result = main.semantic_search_endpoint(request, query="gochujang", limit=5)

        assert result["products"] == []
        assert "error" in result

    def test_endpoint_returns_error_without_embeddings(self, monkeypatch):
        monkeypatch.setattr(main, "_get_openai_client", lambda: _FakeOpenAIClient(_make_vector_fn({})))
        monkeypatch.setattr(main, "cached_product_embeddings", lambda: {})
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))

        result = main.semantic_search_endpoint(request, query="gochujang", limit=5)

        assert result["products"] == []
        assert "error" in result

    def test_endpoint_returns_ranked_products(self, products, monkeypatch):
        sample = next(p for p in products if p.id)
        monkeypatch.setattr(main, "products", products)
        monkeypatch.setattr(main, "_get_openai_client", lambda: _FakeOpenAIClient(_make_vector_fn({"query": [1.0, 0.0]})))
        monkeypatch.setattr(main, "cached_product_embeddings", lambda: {sample.id: [1.0, 0.0]})
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))

        result = main.semantic_search_endpoint(request, query="query", limit=5)

        assert result["products"]
        assert result["products"][0]["id"] == sample.id
        assert "similarity" in result["products"][0]

    def test_admin_rebuild_embeddings_requires_token(self, monkeypatch):
        monkeypatch.delenv("ADMIN_ANALYTICS_TOKEN", raising=False)
        monkeypatch.delenv("ADMIN_RELOAD_TOKEN", raising=False)

        with pytest.raises(main.HTTPException):
            main.admin_rebuild_embeddings(x_admin_token=None)

    def test_admin_rebuild_embeddings_saves_and_clears_cache(self, products, monkeypatch, tmp_path):
        path = tmp_path / "embeddings.json"
        # V2.12.1: rebuild is state-changing (OPERATIONS scope) - the
        # legacy ADMIN_ANALYTICS_TOKEN now only grants READ, see
        # app/admin_auth.py.
        monkeypatch.setenv("ADMIN_RELOAD_TOKEN", "test-token")
        monkeypatch.setenv("PRODUCT_EMBEDDINGS_PATH", str(path))
        monkeypatch.setattr(main, "products", products[:2])
        monkeypatch.setattr(main, "_get_openai_client", lambda: _FakeOpenAIClient(_make_vector_fn({}, default=(1.0, 0.0))))

        result = main.admin_rebuild_embeddings(x_admin_token="test-token")

        assert result["products_embedded"] == 2
        assert path.exists()
        reloaded = load_embeddings(str(path))
        assert len(reloaded) == 2

    def test_admin_refresh_feed_requires_token(self, monkeypatch):
        monkeypatch.delenv("ADMIN_ANALYTICS_TOKEN", raising=False)
        monkeypatch.delenv("ADMIN_RELOAD_TOKEN", raising=False)

        with pytest.raises(main.HTTPException):
            main.admin_refresh_feed(x_admin_token=None)

    def test_admin_refresh_feed_runs_v21_pipeline_and_reports_taxonomy(self, products, monkeypatch):
        # V2.1: manual on-demand trigger for refresh_feed() so the feed/
        # normalization/taxonomy pipeline can be verified without waiting
        # for the scheduled feed_refresh_loop() interval. Mocks the network
        # fetch only - refresh_feed() itself, including build_taxonomy_index(),
        # runs for real, so it reassigns several main.* globals (same as
        # test_refresh_feed_keeps_old_catalog_when_new_feed_is_empty below) -
        # save/restore them so this test does not leak state into others.
        original = {
            name: getattr(main, name)
            for name in ("products", "product_snapshot", "translation_index",
                         "product_taxonomy_index", "last_feed_refresh_at", "last_feed_refresh_error")
        }
        try:
            # V2.12.1: feed refresh is state-changing (OPERATIONS scope) -
            # the legacy ADMIN_ANALYTICS_TOKEN now only grants READ, see
            # app/admin_auth.py.
            monkeypatch.setenv("ADMIN_RELOAD_TOKEN", "test-token")
            monkeypatch.setattr(main, "load_multilang_feeds", lambda: {"sk": products})

            result = main.admin_refresh_feed(x_admin_token="test-token")

            assert result["products"] == len(products)
            assert result["taxonomy"]["total_products"] == len(products)
            assert set(result["taxonomy"]["confidence_counts"]) == {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}
            assert result["duration_seconds"] >= 0
            assert result["last_feed_refresh_at"] is not None
        finally:
            for name, value in original.items():
                setattr(main, name, value)

    def test_admin_refresh_feed_raises_on_empty_sk_feed(self, monkeypatch):
        # refresh_feed() keeps the previous catalog and sets
        # last_feed_refresh_error instead of wiping products to [] - the
        # endpoint must surface that as an error, not a fake 200 success.
        # (Not asserting .status_code here: the offline fastapi stub in
        # _install_stubs() above discards constructor args, same as every
        # other pytest.raises(main.HTTPException) test in this file.)
        original_error = main.last_feed_refresh_error
        try:
            # V2.12.1: must grant OPERATIONS scope (ADMIN_RELOAD_TOKEN) so
            # this actually exercises the empty-feed error path below
            # rather than merely failing auth for an unrelated reason.
            monkeypatch.setenv("ADMIN_RELOAD_TOKEN", "test-token")
            monkeypatch.setattr(main, "load_multilang_feeds", lambda: {"sk": []})

            with pytest.raises(main.HTTPException):
                main.admin_refresh_feed(x_admin_token="test-token")
        finally:
            main.last_feed_refresh_error = original_error


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


class TestTaxonomyAwareAutocomplete:
    """Sprint V2.2: taxonomy-grounded category/question suggestions wired
    into main.search_autocomplete(), against the real committed catalog
    (data/products.json) via the `products`/`knowledge` fixtures - same
    fixtures TestSearchProducts uses above."""

    def test_broad_rice_query_returns_taxonomy_category_suggestions(self, products, knowledge):
        suggestions = main.search_autocomplete(products, knowledge, "ryza", 8, {})
        category_labels = {s["label"] for s in suggestions if s["type"] == "taxonomy_category"}
        assert category_labels
        assert category_labels <= {"Ryža", "Jazmínová ryža", "Basmati ryža", "Ryža na sushi", "Lepkavá ryža"}

    def test_rice_collision_families_excluded_from_broad_rice_query(self, products, knowledge):
        # Section 13/36 invariant, at the wired search_autocomplete() level:
        # "ryza" must never surface rice noodles/vinegar/paper/cooker as a
        # taxonomy_category suggestion.
        suggestions = main.search_autocomplete(products, knowledge, "ryza", 8, {})
        category_labels = {s["label"] for s in suggestions if s["type"] == "taxonomy_category"}
        assert not category_labels & {"Ryžové rezance", "Ryžový ocot", "Ryžový papier", "Ryžovar"}

    def test_ryzov_prefix_surfaces_collision_concepts_not_plain_rice(self, products, knowledge):
        suggestions = main.search_autocomplete(products, knowledge, "ryzov", 8, {})
        category_labels = {s["label"] for s in suggestions if s["type"] == "taxonomy_category"}
        assert category_labels & {"Ryžové rezance", "Ryžový ocot", "Ryžový papier", "Ryžovar"}
        assert "Ryža" not in category_labels
        assert "Jazmínová ryža" not in category_labels

    def test_comparison_question_for_rozdiel_query(self, products, knowledge):
        suggestions = main.search_autocomplete(products, knowledge, "rozdiel jazminova basmati", 8, {})
        comparisons = [s for s in suggestions if s["type"] == "comparison"]
        assert comparisons
        assert comparisons[0]["label"] == "Aký je rozdiel medzi jazmínovou a basmati ryžou?"
        assert comparisons[0]["action"] == "ASK_QUESTION"

    def test_grounded_question_for_aku_ryzu_query(self, products, knowledge):
        suggestions = main.search_autocomplete(products, knowledge, "aku ryzu", 8, {})
        questions = [s["label"] for s in suggestions if s["type"] == "question"]
        assert "Akú ryžu použiť na sushi?" in questions

    def test_unknown_taxonomy_product_still_discoverable(self, products, knowledge):
        # Mandatory fallback (Section 9/61/77): "Kimchi základ KIKKOMAN" is
        # taxonomy UNKNOWN (no rice/noodles/etc rule matches it) but must
        # still surface as a normal product suggestion via legacy search.
        suggestions = main.search_autocomplete(products, knowledge, "kikko", 8, {})
        product_labels = [s["label"] for s in suggestions if s["type"] == "product"]
        assert any("kikkoman" in nrm(label) for label in product_labels)
        tax = main.product_taxonomy_index.get(
            next(p.id for p in products if "kimchi" in nrm(p.title) and "kikkoman" in nrm(p.brand or ""))
        )
        assert tax is not None
        assert tax.canonical_family is None
        assert tax.confidence == "UNKNOWN"

    def test_structured_suggestions_have_action_and_query(self, products, knowledge):
        suggestions = main.search_autocomplete(products, knowledge, "jazm", 8, {})
        taxonomy_items = [s for s in suggestions if s["type"] == "taxonomy_category"]
        assert taxonomy_items
        for item in taxonomy_items:
            assert item["action"] == "APPLY_CONSTRAINTS"
            assert item["constraints"]["family"]
            assert item["query"]

    def test_personalization_does_not_inject_taxonomy_suggestions(self, products, knowledge):
        # Section 11/26: personalization may reorder valid candidates, but
        # must never inject a category/question suggestion that a neutral
        # profile wouldn't already get for the same query.
        neutral = main.search_autocomplete(products, knowledge, "kikko", 8, {})
        profile = {"product_brands": {"JONGGA": 5}, "cuisines": {}, "subjects": {}, "diet_terms": {}, "product_titles": {}}
        personalized = main.search_autocomplete(products, knowledge, "kikko", 8, profile)
        assert not any(s["type"] in ("taxonomy_category", "question", "comparison") for s in neutral)
        assert not any(s["type"] in ("taxonomy_category", "question", "comparison") for s in personalized)

    def test_personalization_does_not_override_explicit_typed_constraints(self, products, knowledge):
        # A JONGGA-favorite profile must not turn a "basmati" query into a
        # JONGGA (kimchi brand) suggestion - favorite brand cannot create
        # an invalid suggestion (Section 11).
        profile = {"product_brands": {"JONGGA": 5}, "cuisines": {}, "subjects": {}, "diet_terms": {}, "product_titles": {}}
        suggestions = main.search_autocomplete(products, knowledge, "basmati", 8, profile)
        assert not any("jongga" in nrm(s.get("label", "")) for s in suggestions)
        category_labels = {s["label"] for s in suggestions if s["type"] == "taxonomy_category"}
        assert "Basmati ryža" in category_labels

    def test_specific_package_size_query_ranks_matching_size_first(self, products, knowledge):
        # Section 53/64: an existing, already-correct behavior - kept here
        # as a regression guard since V2.2 reorders suggestion sources.
        suggestions = main.search_autocomplete(products, knowledge, "jazminova 5 kg", 6, {})
        first_product = next((s for s in suggestions if s["type"] == "product"), None)
        assert first_product is not None
        assert "5 kg" in first_product["label"].lower() or "5kg" in nrm(first_product["label"])


class TestIntentDetection:
    def test_allergen_arasidy(self):
        assert main.detect_allergen_intent("alergia na arasidy, co mozem kupit?") is not None

    def test_allergen_lepok(self):
        term = main.detect_allergen_intent("mam celiakiu, bezlepkove produkty")
        assert term == "lepok"

    def test_bare_allergen_question_without_safety_framing_word(self):
        # Real user report: "ma to lepok?" names a real allergen term
        # (already correctly in ALLERGEN_TERMS) but uses "ma" instead of
        # any of the explicit safety-framing words in
        # ALLERGEN_INTENT_MARKERS (alerg/intoler/celiak/obsahuje/vhodn/...)
        # - it fell through the gate entirely and never reached the
        # ALLERGEN_TERMS lookup. Fixed via BARE_ALLERGEN_QUESTION_TERMS.
        assert main.detect_allergen_intent("ma to lepok?") == "lepok"
        assert main.detect_allergen_intent("je v tom lepok?") == "lepok"
        assert main.detect_allergen_intent("ma to arasidy?") == "arašidy"
        assert main.detect_allergen_intent("ma to sezam?") == "sezam"

    def test_bare_allergen_question_control_cases_stay_unaffected(self):
        # Control cases (roadmap section 27): the bare-question fix above
        # is deliberately scoped to BARE_ALLERGEN_QUESTION_TERMS, not all of
        # ALLERGEN_TERMS - "mlieko"/"ryb"/"vajc"/"orech" are also plain
        # grocery nouns, so a generic product question that happens to
        # name one of them must not become an allergen-safety answer.
        assert main.detect_allergen_intent("aku ma chut toto mlieko") is None
        assert main.detect_allergen_intent("kolko ma gramov toto mlieko") is None
        assert main.detect_allergen_intent("mate mlieko?") is None
        assert main.detect_allergen_intent("ma tento produkt orechy?") is None
        assert main.detect_allergen_intent("chcem kupit orechy") is None

    def test_bare_allergen_question_does_not_hijack_soy_sauce_questions(self):
        # Real regression: "soja"/"soj" were originally included in
        # BARE_ALLERGEN_QUESTION_TERMS as supposedly unambiguous allergen
        # vocabulary, but "sojova omacka" (soy sauce) is one of the store's
        # flagship product categories, and the extremely common word "je"
        # ("is") co-occurs with it constantly - so ordinary comparison/price
        # questions about soy sauce were wrongly answered with a soy allergy
        # warning instead of the actual answer. Removed from the bare-verb
        # bypass set entirely (same treatment as mlieko/orech/ryb/vajc).
        assert main.detect_allergen_intent("co je lepsie svetla alebo tmava sojova omacka?") is None
        assert main.detect_allergen_intent("aka je cena kikkoman sojovej omacky?") is None
        assert main.detect_allergen_intent("aka sojova omacka je najlepsia?") is None
        assert main.detect_allergen_intent("preco je sojova omacka tmava") is None
        # Explicit allergen-avoidance phrasing for soy must still work -
        # unaffected, since it goes through the pre-existing
        # ALLERGEN_INTENT_MARKERS "bez soj"/"bez soja" markers, not the
        # bare-question bypass this test is about.
        assert main.detect_allergen_intent("bez soje, co mate?") == "sóju"
        assert main.detect_allergen_intent("alergia na soju, co mozem kupit?") == "sóju"

    def test_allergen_NOT_triggered_for_product_search(self):
        term = main.detect_allergen_intent("mate bezlepkovu sojovu omacku?")
        assert term is None, f"False allergen trigger: {term}"

    def test_allergen_product_query_keeps_requested_product(self):
        assert main.allergen_product_query("je gochujang bez lepku?") == "gochujang"
        assert main.allergen_product_query("je sushi ryza bez lepku?") == "__gluten_free_sushi__"
        assert main.allergen_product_query("je rybacia omacka vegan?") == "rybacia omacka"

    def test_allergen_product_query_avoids_generic_soy_free_guess(self):
        assert main.allergen_product_query("co mate bez soje?") == ""

    def test_allergen_product_query_robust_to_surface_variation(self):
        # V2.18d.3 (C2): a general allergen question with no specific
        # product named must return "" (no product search) even under a
        # typo or word-order change, not just under its exact canonical
        # phrasing. Root cause: the old fallback tried to salvage a
        # "specific product" from whatever text was left after stripping
        # a hand-maintained list of exact phrases - a single doubled
        # character or a two-word swap broke that exact-string matching,
        # and the leftover text (sometimes still containing the allergen
        # term itself, e.g. "arasiidy") became a live catalog search query
        # instead of the safe empty result (reproduced live: 8 concrete
        # peanut products attached to a supposedly product-free allergen
        # disclaimer). See V2.18d.2 cluster C2 / regbug_rt0003, regbug_rt0027.
        for message in (
            "alergia na arašiidy, čo môžem kúpiť?",  # rt0003 + doubled-char typo
            "na alergia arašidy, čo môžem kúpiť?",  # rt0003 + first-two-words swapped
            "mam alergiu na lepok, čo by ste dopuruučili?",  # rt0027 + doubled-char typo
        ):
            assert main.allergen_product_query(message) == "", message
            assert main.allergen_product_matches(message, 8) == [], message

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

    def test_missing_composition_complaint_detected(self):
        # Regression test: a real production complaint cluster where
        # customers said the composition/ingredient list was missing from
        # the product page - these must route to a support-escalation
        # answer, not the generic "check the product page" allergen
        # template (which is exactly what they were complaining about).
        assert main.is_missing_composition_complaint("Ale zlozenie chyba")
        assert main.is_missing_composition_complaint("Chyba zlozenie omacky")
        assert main.is_missing_composition_complaint("Co mam robit ak pri produkte chyba zlozenie?")
        assert main.is_missing_composition_complaint("nemozem najst zlozenie pre tento produkt")

    def test_missing_composition_answer_gives_support_contact(self):
        answer_sk = main.missing_composition_answer("sk")
        assert "eshop@foodland.sk" in answer_sk
        answer_en = main.missing_composition_answer("en")
        assert "eshop@foodland.sk" in answer_en

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

    def test_tom_kha_shopping_list_reaches_recipe_to_products_without_recept_word(self):
        # Real user report: "co potrebujem na tom kha gai" is a shopping-list
        # style question with no "recept"/how-to wording at all (unlike the
        # pho/kimchi ramen cases above, which both contain "k receptu").
        # is_recipe_intent() only fired on RECIPE_INTENT_MARKERS or a bare
        # "recept*" token, so this fell through entirely into the generic
        # cross-sell branch (intent "related_products") instead of the
        # recipe_to_products workflow - even though Tom Kha Gai has a real
        # Foodland recipe card and missing-ingredient mapping. Fixed by
        # adding "tom kha" to RECIPE_INTENT_MARKERS (same pattern as the
        # existing vindaloo/karaage entries).
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))

        for query in ("co potrebujem na tom kha gai", "co kupit na tom kha gai", "tom kha gai"):
            assert main.is_recipe_intent(main.normalize(query)), query
            assert main.detect_recipe_subject(query) == "tom_kha", query

        result = main.chat(main.ChatRequest(message="co potrebujem na tom kha gai", limit=8), request)
        titles = nrm(" | ".join(product.get("title", "") for product in result.get("products", [])))

        assert result.get("intent") == "recipe_to_products"
        assert any(recipe.get("title", "") == "Tom Kha Gai" for recipe in result.get("recipes", []))
        assert "kokosove mlieko" in titles
        assert "galangal" in titles

    def test_tom_kha_fix_does_not_change_neighboring_shopping_list_subjects(self):
        # Control cases (roadmap section 27): the tom_kha fix above must not
        # sweep up lookalike dishes that intentionally keep their existing
        # related_products/cross-sell routing for shopping-list phrasing
        # without "recept" (tom_yum and kimchi_ramen have their own tuned
        # *_shopping_core_products() cross-sell functions and are covered by
        # dedicated tests elsewhere asserting intent == "related_products";
        # sushi/pho/ramen/kimchi have no dedicated recipe-title marker for
        # this bare phrasing at all).
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))
        for query in (
            "co potrebujem na sushi",
            "co potrebujem na pho",
            "co potrebujem na ramen",
            "co potrebujem na kimchi",
            "nakupny zoznam na tom yum",
            "nakupny zoznam na kimchi ramen",
        ):
            assert not main.is_recipe_intent(main.normalize(query)), query
            assert main.detect_recipe_subject(query) is None, query

        tom_yum_result = main.chat(main.ChatRequest(message="nakupny zoznam na tom yum", limit=8), request)
        assert tom_yum_result.get("intent") == "related_products"

        kimchi_ramen_result = main.chat(main.ChatRequest(message="nakupny zoznam na kimchi ramen", limit=8), request)
        assert kimchi_ramen_result.get("intent") == "related_products"

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

    def test_vindaloo_recipe_added_from_real_foodland_page(self, knowledge, products):
        # The bot previously had no Vindaloo recipe at all and truthfully
        # said so, generating a general AI answer (Sprint U/U.1). The user
        # then pointed to the real recipe at foodland.sk/recepty/
        # goanske-bravcove-vindaloo-bez-zemiakov/, so it was added properly:
        # a Recipes entry, a title->subject mapping, and real
        # RELATED_PRODUCT_QUERIES/MISSING_INGREDIENTS_BY_SUBJECT entries
        # (verified against the actual catalog, not guessed) so the three
        # "every recipe must have a mapped subject" guard tests above still
        # pass.
        recipe_subject = main.detect_recipe_subject("recept na vindaloo")
        assert recipe_subject == "vindaloo"

        knowledge_matches = main.search_knowledge(knowledge, "recept na vindaloo", allowed_sections=("Recipes",))
        recipes = main.recipe_results(knowledge_matches, 4, "recept na vindaloo", knowledge)
        assert recipes
        assert any("vindaloo" in main.normalize(r.get("title", "")) for r in recipes)
        assert any("goanske-bravcove-vindaloo" in r.get("link", "") for r in recipes)

        related_matches = main.related_products_for_subject(products, knowledge, "vindaloo", 6)
        assert related_matches

    def test_bare_vindaloo_reaches_recipe_not_ai_fallback(self, knowledge):
        # Real user report, right after the recipe was added: bare
        # "Vindaloo" (no "recept na" prefix) still triggered the general
        # AI fallback and didn't link the real recipe. Root cause:
        # is_recipe_intent() needs a cooking-related word (recept/navod/
        # etc.) - a bare dish name alone never qualified, so it fell
        # through to the same "no matches, no knowledge" catch-all that
        # general_ai_recipe_answer() is wired into, even though the
        # recipe now exists. Added "vindaloo" directly to
        # RECIPE_INTENT_MARKERS.
        for query in ("Vindaloo", "vindaloo"):
            assert main.is_recipe_intent(main.normalize(query)), query
            assert main.detect_recipe_subject(query) == "vindaloo", query

        knowledge_matches = main.search_knowledge(knowledge, "Vindaloo", allowed_sections=("Recipes",))
        recipes = main.recipe_results(knowledge_matches, 4, "Vindaloo", knowledge)
        assert any("goanske-bravcove-vindaloo" in r.get("link", "") for r in recipes)

    def test_karaage_recipe_added_from_real_foodland_page(self, knowledge, products):
        # User provided the real recipe at foodland.sk/recepty/
        # japonske-vyprazane-kura-kuracie-karaage/ to add. Unlike Vindaloo,
        # "karaage" already had a RELATED_PRODUCT_QUERIES entry (used for
        # cross-sell before any recipe existed) but no Recipes entry, no
        # title->subject mapping, and no MISSING_INGREDIENTS_BY_SUBJECT -
        # all added here, plus cornstarch to the cross-sell list (the core
        # coating ingredient, verified against the real recipe and missing
        # from the pre-existing query list entirely).
        for query in ("recept na karaage", "Karaage", "karaage"):
            assert main.is_recipe_intent(main.normalize(query)), query
            assert main.detect_recipe_subject(query) == "karaage", query

        knowledge_matches = main.search_knowledge(knowledge, "recept na karaage", allowed_sections=("Recipes",))
        recipes = main.recipe_results(knowledge_matches, 4, "recept na karaage", knowledge)
        assert recipes
        assert any("japonske-vyprazane-kura-kuracie-karaage" in r.get("link", "") for r in recipes)

        related_matches = main.related_products_for_subject(products, knowledge, "karaage", 6)
        assert related_matches
        assert any("skrob" in main.normalize(r.get("title", "")) for r in related_matches)

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

    def test_out_of_domain_entertainment_trivia_and_school(self):
        # Real user report: "aky je najlepsi film?" (general entertainment
        # trivia, unrelated to Foodland) got answered with a confident but
        # nonsensical product search instead of the refusal message.
        for query in (
            "aky je najlepsi film?",
            "aky je najlepsi serial?",
            "kto je prezident slovenska?",
            "aka je hlavne mesto francuzska",
            "pomozes mi s domacou ulohou z matematiky?",
        ):
            assert main.detect_out_of_domain(query), query

        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))
        result = main.chat(main.ChatRequest(message="aky je najlepsi film?", limit=8), request)
        assert result.get("intent") == "unknown"
        assert not result.get("products")

    def test_out_of_domain_fix_does_not_break_asian_snack_cross_sell(self):
        # Control case (roadmap section 27): the new entertainment markers
        # are deliberately specific multi-word phrases ("najlepsi film",
        # not bare "film"/"serial") because those bare words are substrings
        # of the existing asian_snack cross-sell aliases ("na film",
        # "k filmu", "na serial", "k serialu") - a real snack request for
        # movie/series night must keep working.
        for query in ("co si dat na film", "co si dat k filmu", "nieco na serial"):
            assert not main.detect_out_of_domain(query), query
            assert main.detect_related_subject(query) == "asian_snack", query

    def test_category_discovery_detects_generic_inventory_questions(self):
        # Real user report: "aku kategoriu produktov mate?" (a generic
        # "what do you sell" question, no specific product/subject named)
        # either dead-ended with an unhelpful empty answer or, worse,
        # confidently presented RANDOM irrelevant products as "most
        # relevant" (plain keyword search always finds *something*).
        # category_discovery is a canonical V2 intent that had no detector
        # at all.
        for query in (
            "aku kategoriu produktov mate?",
            "ake kategorie produktov mate?",
            "co vsetko predavate?",
            "aky sortiment mate?",
            "ake znacky predavate?",
            "aky tovar mate?",
        ):
            assert main.is_category_discovery_query(query), query

        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))
        result = main.chat(main.ChatRequest(message="aku kategoriu produktov mate?", limit=8), request)
        assert result.get("intent") == "category_discovery"
        assert not result.get("products")
        answer = result.get("answer", "")
        assert "foodland.sk" in main.normalize(answer)
        # Grounded in real product_type data, not invented category names.
        real_categories = set(main.top_product_categories(main.products, 20))
        assert any(nrm(cat) in nrm(answer) for cat in real_categories)

    def test_category_discovery_does_not_hijack_specific_product_questions(self):
        # Control cases (roadmap section 27): the detector requires an
        # EXACT message match (not substring), specifically so a longer,
        # specific query naming a real product/cuisine is never swept into
        # the generic category-discovery answer.
        for query in (
            "aky tovar mate na sushi?",
            "co mate v ponuke na sushi",
            "co vsetko mate na thajsku kuchynu?",
            "aku ryzu mate",
            "ake znacky sojovej omacky mate?",
            "mate ryzu?",
        ):
            assert not main.is_category_discovery_query(query), query

    def test_top_product_categories_excludes_dietary_marketing_noise(self):
        # Cross-cutting attribute tags like "Vegánske potraviny"/"Zdravé
        # potraviny" are real product_type breadcrumb segments but are not
        # useful as a "what departments do you have" answer - they should
        # not appear in the curated category list.
        categories = main.top_product_categories(main.products, 30)
        normalized_categories = {nrm(c) for c in categories}
        assert "veganske potraviny" not in normalized_categories
        assert "zdrave potraviny" not in normalized_categories
        assert "bio potraviny" not in normalized_categories
        assert categories

    def test_related_subject_sushi(self):
        subj = main.detect_related_subject("co potrebujem na sushi?")
        assert subj == "sushi"

    def test_related_subject_onigiri_not_misdetected_as_sushi(self):
        # Regression test: sushi alias list includes "nigiri", which is a
        # substring of "onigiri" - onigiri questions must resolve to the
        # onigiri subject (and surface the onigiri mold), not sushi.
        subj = main.detect_related_subject("pomocku na balenie onigiri")
        assert subj == "onigiri"
        recs = main.related_products_for_subject(main.products, main.knowledge, "onigiri", 3)
        titles = [r.get("title", "") for r in recs]
        assert any("onigiri" in main.normalize(t) for t in titles)

    def test_related_subject_nigiri_still_resolves_to_sushi(self):
        assert main.detect_related_subject("chcem si kupit nigiri na veceru") == "sushi"

    def test_related_subject_gyudon_not_misdetected_as_udon(self):
        # Regression test found by scripts/consistency_audit.py, not by a
        # customer report: "udon" is a substring of "gyudon" (beef rice
        # bowl, unrelated to udon noodles), so gyudon questions were being
        # misclassified as plain udon-noodle questions and the correct
        # RELATED_PRODUCT_QUERIES["gyudon"] ingredients were unreachable.
        assert main.detect_related_subject("recept na gyudon") == "gyudon"
        recs = main.related_products_for_subject(main.products, main.knowledge, "gyudon", 3)
        assert recs

    def test_related_subject_udon_still_resolves_to_udon(self):
        assert main.detect_related_subject("udon rezance") == "udon"

    def test_related_subject_plain_vinegar_gets_real_pairing_not_more_vinegar(self, products):
        # Real user scenario: "aky ocot mate?" then "co mam kupit k tomu?"
        # (what vinegar do you have / what should I buy to go with it).
        # Plain "ocot" had no RELATED_SUBJECT_ALIASES entry at all, so the
        # follow-up fell through to a plain keyword search on the
        # contextualized message (which embeds the last shown product's
        # title) - it happened to return more vinegar (coincidental
        # title-word overlap with "ocot"), not a genuine complementary
        # pairing. "ocot" must be checked after "ryzovy_ocot" (same class
        # of fix as gyudon/udon): "ocot" is a substring of "ryzovy ocot".
        for query in ("aky ocot mate", "jablcny ocot", "biely ocot"):
            assert main.detect_related_subject(query) == "ocot", query
        assert main.detect_related_subject("ryzovy ocot") == "ryzovy_ocot"

        recs = main.related_products_for_subject(products, main.knowledge, "ocot", 6)
        titles = [main.normalize(r.get("title", "")) for r in recs]
        assert recs
        assert not any("ocot" in t for t in titles), titles

    def test_related_subject_kimchi(self):
        subj = main.detect_related_subject("ingrediencie na kimchi")
        assert subj == "kimchi_recipe"

    def test_special_gluten_free_sushi(self):
        subj = main.detect_special_product_subject("bezlepkove sushi")
        assert subj == "gluten_free_sushi"

    def test_special_rice_vinegar(self):
        subj = main.detect_special_product_subject("ryzovy ocot")
        assert subj == "rice_vinegar"

    def test_special_plain_rice_finds_actual_grain_not_cooker_or_flour(self, products):
        # Real user reports (screenshots): "Mate ryzu?", "aka ryza mate",
        # "obycajna biela ryza" all returned rice FLOUR and/or rice COOKERS
        # instead of actual rice grain - the shared "ryz" root makes these
        # families compete on roughly equal BM25/keyword footing in plain
        # search. Root cause: the old plain_rice trigger required the
        # customer to literally type "nie ocot"/"nie ryzovar" ("not
        # vinegar"/"not rice cooker") as an explicit exclusion clause -
        # something no real customer phrases that way - so it was
        # effectively unreachable.
        for query in ("mate ryzu", "aka ryza mate", "obycajna biela ryza", "chcem ryzu bez octu"):
            assert main.detect_special_product_subject(query) == "plain_rice", query
        matches = main.special_products_for_subject(products, "plain_rice", 6)
        assert matches
        titles = [main.normalize(m.get("title", "")) for m in matches]
        assert all("hrniec" not in t and "muka" not in t and "ryzovar" not in t for t in titles)

    def test_special_rice_cooker_finds_appliance_not_flour(self, products):
        # Real user report (screenshot): "Ryzovar mate?" returned rice
        # flour before the actual rice cooker. Nothing routed rice-cooker
        # questions to a dedicated subject at all.
        for query in ("ryzovar mate", "aky ryzovar odporucate", "hrniec na ryzu"):
            assert main.detect_special_product_subject(query) == "rice_cooker", query
        matches = main.special_products_for_subject(products, "rice_cooker", 6)
        assert matches
        assert all("hrniec" in main.normalize(m.get("title", "")) or "ryzovar" in main.normalize(m.get("title", "")) for m in matches)

    def test_special_rice_seasoning_finds_seasoning_not_cooker(self):
        # Real user message from the same conversation: "Korenie na ryzu"
        # (seasoning for rice) also returned rice cookers instead of a
        # seasoning product.
        assert main.detect_special_product_subject("korenie na ryzu") == "rice_seasoning"

    def test_special_sushi_rice_unaffected_by_rice_family_changes(self):
        assert main.detect_special_product_subject("sushi ryza") == "sushi_rice"

    def test_special_vegan_fish_sauce(self):
        subj = main.detect_special_product_subject("nahrada za rybaciu omacku vegan")
        assert subj == "vegan_fish_sauce_replacement"

    def test_replacement_subject_detected_before_related_cross_sell(self):
        assert main.detect_replacement_subject("cim vynahradim gochujang") == "gochujang"
        assert main.detect_related_subject("cim vynahradim gochujang") == "gochujang"

    def test_product_set_signal_overrides_related_subject_routing(self, products):
        # Real user report: "sake sety" (sake SETS) was forced into the
        # generic "sake" cross-sell branch just because it contains "sake"
        # - even though the actual "Saké Set" products exist and a plain
        # search finds them near the top. A set/kit word signals the
        # customer wants that specific product type, not "what goes with
        # sake" pairings. This mirrors the special_subject override already
        # used for related_subject in the /chat routing.
        assert main.detect_related_subject("sake sety") == "sake"
        for word in ("sety", "sada", "suprava"):
            assert main.PRODUCT_SET_SIGNAL_TOKENS & main.tokenize(f"sake {word}"), word
        assert not (main.PRODUCT_SET_SIGNAL_TOKENS & main.tokenize("co sa hodi k sake"))

        matches = main.cached_search_products(products, "sake sety", 6)
        titles = " ".join(main.normalize(p.get("title", "")) for p in matches)
        assert "sake set" in titles or "saki set" in titles

    def test_explicit_brand_overrides_related_subject_routing(self, products):
        # Real user report (screenshot, confirmed across brands): "Yamasa
        # sojova omacka" got a cross-sell answer ("skvelo pasuje k tomu
        # tamari sojova omacka alebo mirin...") recommending a DIFFERENT
        # brand (Kikkoman) entirely, instead of the actual Yamasa soy sauce
        # the customer named - because "sojova omacka" already matches the
        # "sojova_omacka" RELATED_SUBJECT_ALIASES entry regardless of what
        # brand prefixes it, and related_subject routing never looks at
        # matches at all, just returns cross-sell for the category. A
        # customer naming a specific brand wants that product.
        for message, brand_token in (
            ("Yamasa sojova omacka", "yamasa"),
            ("Squid Brand rybacia omacka", "squid brand"),
        ):
            assert main.detect_related_subject(message), message  # sanity: alias still matches
            mentioned = main.detect_mentioned_replacement_brand(message, products, main.detect_related_subject(message))
            assert mentioned and main.normalize(mentioned) == brand_token, message

            matches = main.cached_search_products(products, message, 6)
            assert matches, message
            # The named brand must lead the results - not necessarily fill
            # every slot, since a brand with few SKUs naturally has other
            # brands fill the remaining ones.
            assert brand_token in main.normalize(matches[0].get("brand", "")), message
            assert any(brand_token in main.normalize(p.get("brand", "")) for p in matches), message

        # No brand named: the existing tradeoff (confirmed with the user)
        # stays unchanged - direct "aky ocot mate" still routes to cross-sell.
        assert main.detect_related_subject("aky ocot mate") == "ocot"

    def test_kitchenware_term_overrides_cuisine_related_subject_routing(self, products):
        # Real user report: "japonske noze" / "noz japonsky" (Japanese
        # knives) got the "japonska_kuchyna" cuisine cross-sell answer
        # (soy sauce, mirin, dashi, wasabi, sushi rice) instead of actual
        # knife products - the "japonska_kuchyna" alias "japonsk" matches
        # ANY word starting with it, including kitchenware (knives,
        # chopsticks, plates, bowls, teapots), not just food questions.
        # Confirmed the same class of bug affects the whole kitchenware
        # category, not just knives, before fixing.
        for message, expected_word in (
            ("japonske noze", "noz"),
            ("noz japonsky", "noz"),
            ("japonske palicky", "palick"),
            ("japonsky tanier", "tanier"),
            ("japonsky cajnik", "cajnik"),
        ):
            assert main.detect_related_subject(message) == "japonska_kuchyna", message  # sanity: alias still matches
            matches = main.cached_search_products(products, message, 4)
            assert matches, message
            # The top result must be the actual item asked for - not
            # necessarily every slot, since a narrow item range naturally
            # has closely related products fill the remaining ones.
            assert expected_word in main.normalize(matches[0].get("title", "")), message

        # A genuine cuisine-level question with no kitchenware term must be
        # unaffected - the override is scoped to kitchenware terms only.
        assert main.detect_related_subject("japonska kuchyna recepty") == "japonska_kuchyna"

    def test_cajove_sety_finds_tea_sets_not_only_matcha(self, products):
        # Real user report: "cajove sety" (tea sets) returned only the 17
        # "Matcha set" bowl/whisk products, none of the 4 actual "Japonska
        # cajova suprava" (teapot + cup) products. Root cause: "cajove"
        # (neuter/plural adjective form used in the query) never matched
        # "cajova" (feminine form used in the product titles) as an exact
        # token - a declension gap, same class of bug as "doprava" vs.
        # "dopravy". Fixing it via a "cajov" prefix synonym (matching the
        # existing bezlepk/sojov pattern in data/synonyms.json) was enough
        # on its own; a first attempt that also cross-mapped "set"/"sety"
        # with "suprava"/"sada" as synonyms was reverted because it caused
        # the opposite problem - all 17 matcha-set titles started matching
        # "suprava" too, drowning out the actual tea sets even worse.
        matches = main.cached_search_products(products, "cajove sety", 6)
        titles = [main.normalize(p.get("title", "")) for p in matches]
        assert any("suprava" in t for t in titles)

    def test_matcha_set_query_unaffected_by_cajov_synonym(self, products):
        matches = main.cached_search_products(products, "matcha set", 6)
        titles = [main.normalize(p.get("title", "")) for p in matches]
        assert all("matcha" in t for t in titles)

    def test_replacement_teapot_finds_teapots_not_only_japanese_products(self, products):
        # Real user report: "nahrada japonskeho cajnika" (replacement for a
        # Japanese teapot) returned noodles, chopsticks and knives - none
        # of the 3 actual "Japonsky cajnik" (teapot) products. Root cause:
        # "cajnika" (genitive) never matched "cajnik" (nominative, as it
        # appears in product titles) as an exact token, so results were
        # driven entirely by the generic "japonske/japonsky" adjective
        # match. Same class of bug as "cajove"/"cajova" - fixed with a
        # "cajnik" prefix synonym.
        subject = main.detect_replacement_subject("nahrada japonskeho cajnika")
        alternatives = main.alternative_products_for_subject(products, main.knowledge, subject, 6)
        titles = [main.normalize(p.get("title", "")) for p in alternatives]
        assert sum("cajnik" in t for t in titles) >= 3
        assert all("cajnik" in t for t in titles[:3])

    def test_replacement_subject_detects_comparative_phrasing(self, products):
        # Real user report: "ina sojova omacka ako Kikkoman" (a different
        # soy sauce than Kikkoman) has none of the explicit markers
        # (nahrad/namiesto/alternativ), so it fell through to the
        # related_products cross-sell branch instead, surfacing unrelated
        # pairings (mirin, rice vinegar) instead of competing soy sauce
        # brands.
        subject = main.detect_replacement_subject("ina sojova omacka ako Kikkoman")
        assert subject == "sojova omacka"

    def test_replacement_brand_query_returns_other_brands_not_more_of_same(self, products):
        # Real user report: "alternativa ku Kikkoman sojovej omacke" (an
        # alternative to Kikkoman soy sauce) - "sojovej omacke" (locative)
        # didn't match either alias in REPLACEMENT_SUBJECT_ALIASES (only
        # "sojova omacka"/"sojovu omacku" were listed), so detect_replacement_
        # subject() fell through to the brand-polluted autocomplete fallback
        # ("kikkoman sojovej omacke"), and the final plain-search fallback
        # then matched "kikkoman" as a keyword and recommended MORE Kikkoman
        # products - the opposite of what "alternative to Kikkoman" means.
        for message, brand_token in (
            ("alternativa ku Kikkoman sojovej omacke", "kikkoman"),
            ("cim nahradim Squid Brand rybaciu omacku", "squid brand"),
        ):
            subject = main.detect_replacement_subject(message)
            assert subject in ("sojova omacka", "rybacia omacka"), message
            mentioned_brand = main.detect_mentioned_replacement_brand(message, products, subject)
            assert mentioned_brand and main.normalize(mentioned_brand) == brand_token, message
            alternatives = main.alternative_products_for_subject(
                products, main.knowledge, subject, 5, exclude_brand=mentioned_brand
            )
            assert alternatives, message
            assert all(brand_token not in main.normalize(p.get("brand", "")) for p in alternatives), message

    def test_replacement_missing_brand_phrasing_reaches_replacement_subject(self, products):
        # Real user report: "Nemam Kikkoman sojovu omacku, co pouzit?" (I
        # don't have Kikkoman soy sauce, what should I use) is a natural
        # substitute request but had no gate marker at all - the function
        # returned None before even checking the alias list.
        subject = main.detect_replacement_subject("nemam Kikkoman sojovu omacku, co pouzit")
        assert subject == "sojova omacka"

        alternatives = main.alternative_products_for_subject(products, main.knowledge, subject, 6)
        assert alternatives
        titles = " ".join(main.normalize(p.get("title", "")) for p in alternatives)
        assert "tamarind" not in titles
        assert "omacka" in titles or "omackov" in titles

    def test_replacement_bare_brand_resolves_to_its_only_sauce_category(self, products):
        # Follow-up requirement: an alternative to a soy sauce brand must
        # always recommend soy sauce (never an unrelated product like chili
        # sauce). "alternativa Kikkoman" (brand name only, no "sojova
        # omacka") used to fall through to a plain brand-name search and
        # surfaced whatever Kikkoman product matched - wok sauce, kimchi
        # base, teriyaki marinade - not soy sauce specifically. Kikkoman and
        # Squid Brand are unambiguous (verified: only sell one of our two
        # sauce categories), so those must resolve directly to it.
        for message, expected_subject, brand_token in (
            ("alternativa Kikkoman", "sojova omacka", "kikkoman"),
            ("alternativa k znacke Kikkoman", "sojova omacka", "kikkoman"),
            ("cim nahradim Squid Brand", "rybacia omacka", "squid brand"),
        ):
            subject = main.detect_replacement_subject(message)
            assert subject == expected_subject, message
            alternatives = main.alternative_products_for_subject(
                products, main.knowledge, subject, 6, exclude_brand=brand_token
            )
            assert alternatives, message
            assert all("omacka" in main.normalize(p.get("title", "")) for p in alternatives), message

    def test_replacement_bare_brand_survives_contextualize_message_pollution(self, products):
        # Live production bug found during deploy verification: /chat calls
        # detect_replacement_subject(contextual_message), and
        # contextualize_message() can append prior-session context (diet
        # terms, last-seen product title) after the brand name. The first
        # version of resolve_unambiguous_sauce_brand() required the cleaned
        # text to EQUAL a brand exactly, so "alternativa Kikkoman
        # bezlepkove" (a returning customer's gluten-free diet term
        # appended) missed the resolution entirely: subject stayed the
        # literal polluted text ("kikkoman bezlepkove") while
        # detect_mentioned_replacement_brand still correctly found
        # "KIKKOMAN" - the two contradicted each other and
        # alternative_products_for_subject's brand-exclusion filter wiped
        # out every result, returning an empty product list with an answer
        # claiming success.
        for message in ("alternativa Kikkoman bezlepkove", "alternativa Kikkoman vegan"):
            subject = main.detect_replacement_subject(message)
            assert subject == "sojova omacka", message
            mentioned_brand = main.detect_mentioned_replacement_brand(message, products, subject)
            alternatives = main.alternative_products_for_subject(
                products, main.knowledge, subject, 6, exclude_brand=mentioned_brand
            )
            assert alternatives, message

    def test_replacement_exclude_brand_safety_net_never_returns_empty(self, products):
        # Defense in depth: if replacement_subject ever ends up as a raw
        # brand-name string (e.g. a resolution fallback failing for reasons
        # outside this function's control) while exclude_brand still
        # correctly identifies that same brand, excluding it from a search
        # FOR that exact literal text is self-defeating and returns nothing
        # - but replacement_products answers are always AI-generated and
        # the system prompt tells it to claim "alternatives are below"
        # regardless of whether matches is empty, so an empty list here
        # means a confident-sounding answer with nothing under it. Must
        # fall back to showing that brand's own products rather than empty.
        recs = main.alternative_products_for_subject(products, main.knowledge, "kikkoman", 6, exclude_brand="KIKKOMAN")
        assert recs
        assert all("kikkoman" in main.normalize(p.get("brand", "")) for p in recs)

    def test_replacement_ambiguous_brand_stays_unresolved(self):
        # MEGACHEF genuinely sells both soy sauce and fish sauce, so a bare
        # brand name must NOT be force-resolved to either - unlike Kikkoman/
        # Squid Brand above, there's no single correct category to guess.
        assert main.detect_replacement_subject("alternativa MEGACHEF") != "sojova omacka"
        assert main.detect_replacement_subject("alternativa MEGACHEF") != "rybacia omacka"

    def test_product_advice_intent_recognizes_usage_and_taste_questions(self):
        # Applied patch (external, reviewed and verified before commit):
        # "co je X" / "na co sa pouziva X" / "ako chuti X" style questions
        # were falling through to cross-sell handling and getting answered
        # with "K X odporucam tieto suvisiace produkty..." phrasing that
        # never actually addressed what was asked.
        for query in ("co je gochujang", "na co sa pouziva gochujang", "ako chuti sriracha", "what is it used for"):
            assert main.is_article_info_intent(query), query

    def test_product_advice_answer_uses_taste_and_usage_fields_only(self, knowledge, products):
        query = "co je gochujang"
        knowledge_matches = main.search_knowledge(knowledge, query, allowed_sections=("Products_AI",))
        matches = main.cached_search_products(products, query, 6)
        links = {m.get("link") for m in matches if m.get("link")}

        answer = best_product_advice_answer(knowledge_matches, matched_links=links)

        assert answer
        # Must be genuine taste/usage prose, not the internal AI-instruction
        # fields ("Kedy odporucit - SK", "Pozor / overit - SK" etc.), which
        # are written as directives to the model ("odporuc pri otazkach
        # na...", "nevymyslaj inu cenu...") rather than customer sentences.
        normalized_answer = main.normalize(answer)
        assert "odporuc" not in normalized_answer
        assert "nevymyslaj" not in normalized_answer
        assert "umami" in normalized_answer or "pikant" in normalized_answer

    def test_product_advice_answer_none_when_no_products_ai_hit(self, knowledge):
        empty_matches = main.search_knowledge(knowledge, "kolobezka bicykel", allowed_sections=("Products_AI",))
        assert best_product_advice_answer(empty_matches) is None

    def test_product_advice_answer_ignores_unmatched_record(self, knowledge, products):
        # The guard: a Products_AI record that scores well on generic
        # keyword overlap but isn't among the products actually shown for
        # this query must not be presented as fact about those products.
        query = "co je gochujang"
        knowledge_matches = main.search_knowledge(knowledge, query, allowed_sections=("Products_AI",))
        answer = best_product_advice_answer(knowledge_matches, matched_links={"https://example.com/not-a-real-product"})
        assert answer is None

    def test_replacement_subject_comparative_marker_requires_word_boundary(self):
        # "vitamina" contains the substring "ina " once padded, but must not
        # be treated as the comparative "ina ... ako" pattern.
        assert main.detect_replacement_subject("potrebujem vitamina ako doplnok stravy") is None

    def test_replacement_queries_dont_confuse_tamari_with_tamarind(self, products):
        # Same bare-"tamari" collision as the Kikkoman fix, found by
        # auditing every REPLACEMENT_PRODUCT_QUERIES entry: "rybacia
        # omacka" (fish sauce) and the "tamari" subject itself both had
        # bare "tamari" as their first fallback query, pulling in unrelated
        # Tamarind fruit products (juice, dried tamarind, soup base).
        for subject in ("rybacia omacka", "tamari"):
            alternatives = main.alternative_products_for_subject(products, main.knowledge, subject, 6)
            titles = " ".join(main.normalize(p.get("title", "")) for p in alternatives)
            assert "tamarind" not in titles, subject

    def test_recipe_intent_not_falsely_triggered_by_english_recommend(self):
        # Regression test: a bare "rec" prefix check used to match any
        # English word starting with those letters ("recommend",
        # "record"), misclassifying plain product questions as recipe
        # intent. Only the actual recept/recipe root should match.
        assert not main.is_recipe_intent(main.normalize("what soy sauce do you recommend for sushi"))
        assert not main.is_recipe_intent(main.normalize("do you have a record of my order"))

    def test_recipe_intent_detects_english_and_czech_phrasing(self):
        assert main.is_recipe_intent(main.normalize("recipe for kimchi soup"))
        assert main.is_recipe_intent(main.normalize("how do i make kimchi"))
        assert main.is_recipe_intent(main.normalize("jak pripravim kimchi"))

    def test_faq_intent_detects_english_and_czech_phrasing(self):
        assert main.is_faq_intent("how long does delivery take?")
        assert main.is_faq_intent("can i pay by card?")
        assert main.is_faq_intent("jak dlouho trva doruceni objednavky?")

    def test_allergen_intent_detects_english_phrasing(self):
        assert main.detect_allergen_intent("is this gluten free? does it contain soy?") is not None
        assert main.detect_allergen_intent("i have a peanut allergy") is not None

    def test_article_info_intent_detects_english_and_czech_phrasing(self):
        assert main.is_article_info_intent("what is gochujang?")
        assert main.is_article_info_intent("why is kimchi fermented?")
        assert main.is_article_info_intent("proc je kimchi fermentovane?")
        assert main.is_article_info_intent("aky je rozdil medzi miso a tamari?")

    def test_explicit_article_request_detects_english_and_czech_phrasing(self):
        assert main.is_explicit_article_request("show me the article about kimchi")
        assert main.is_explicit_article_request("mate clanek o kimchi?")

    def test_random_recipe_intent_detects_english_phrasing(self):
        assert main.is_random_recipe_intent("what should i cook for dinner tonight?")
        assert main.is_random_recipe_intent("give me a random recipe")

    def test_detect_query_language_english(self):
        assert main.detect_query_language("What soy sauce do you recommend for sushi?") == "en"
        assert main.detect_query_language("How long does delivery take?") == "en"

    def test_detect_query_language_defaults_to_sk(self):
        assert main.detect_query_language("Kolko stoji doprava?") == "sk"
        assert main.detect_query_language("Jak dlouho trva doruceni objednavky?") == "sk"

    def test_detect_query_language_ignores_lone_english_product_name(self):
        # A single English word (e.g. a product name) should not flip the
        # language - only >=2 hits count, to avoid false positives.
        assert main.detect_query_language("sriracha") == "sk"

    def test_allergen_safety_answer_english_variant(self):
        answer = main.allergen_safety_answer("lepok", lang="en")
        assert "gluten" in answer
        assert "Foodland.sk" in answer

    def test_recipe_answer_english_variant(self):
        assert main.recipe_answer("kimchi", [{"title": "x"}], lang="en") == (
            "I found a recipe on Foodland.sk. Open it below."
        )
        assert main.recipe_answer("kimchi", [{"title": "x"}, {"title": "y"}], lang="en") == (
            "I found recipes on Foodland.sk. Pick one from the recommendations below."
        )

    def test_random_recipes_answer_english_variant(self):
        answer = main.random_recipes_answer([{"title": "x"}], lang="en")
        assert "dinner" in answer.lower()

    def test_general_ai_recipe_answer_returns_none_without_api_key(self, monkeypatch):
        monkeypatch.setattr(main, "_get_openai_client", lambda: None)
        assert main.general_ai_recipe_answer("vindaloo") is None

    def test_general_ai_recipe_answer_uses_configured_prompt_and_strips_result(self, monkeypatch):
        captured = {}

        def fake_call(client, messages, model, max_tokens=None):
            captured["messages"] = messages
            return "  Vindaloo je pikantné indické kari z Goa.  "

        monkeypatch.setattr(main, "_get_openai_client", lambda: object())
        monkeypatch.setattr(main, "_call_openai_with_retry", fake_call)

        answer = main.general_ai_recipe_answer("vindaloo")

        assert answer == "Vindaloo je pikantné indické kari z Goa."
        system_message = captured["messages"][0]
        assert system_message["role"] == "system"
        # Must forbid inventing Foodland-specific facts - the whole point of
        # this feature is a clearly-general answer, not a fabricated one.
        assert "NIKDY" in system_message["content"]
        assert "vindaloo" in captured["messages"][1]["content"].lower()

    def test_general_ai_recipe_answer_falls_back_to_none_on_api_error(self, monkeypatch):
        def raise_timeout(client, messages, model, max_tokens=None):
            raise main.APITimeoutError(None)

        monkeypatch.setattr(main, "_get_openai_client", lambda: object())
        monkeypatch.setattr(main, "_call_openai_with_retry", raise_timeout)

        assert main.general_ai_recipe_answer("vindaloo") is None

    def test_general_ai_recipe_answer_returns_none_for_non_food_sentinel(self, monkeypatch):
        # Real bug found live: "Vindaloo" typed bare (no "recept na" prefix)
        # doesn't pass is_recipe_intent(), so it never reached the recipe
        # branch at all - it hits the final "no matches, no knowledge" chat
        # fallback instead, which now also tries this function. That means
        # it fires for ANY zero-match query, not just food ones (e.g. a
        # stray brand name), so the model is instructed to reply with a
        # literal NEURCITE sentinel for non-food terms, which must map to
        # None here so the caller falls back to the generic "no exact
        # match" message instead of showing a bogus food explanation.
        monkeypatch.setattr(main, "_get_openai_client", lambda: object())
        monkeypatch.setattr(main, "_call_openai_with_retry", lambda client, messages, model, max_tokens=None: "NEURCITE")

        assert main.general_ai_recipe_answer("babyMonster OREO") is None

    def test_shopping_list_answer_english_variant(self):
        answer = main.shopping_list_answer("kimchi", [{"title": "x"}], [], lang="en")
        assert "shopping list" in answer.lower()
        assert "kimchi" in answer.lower()

    def test_fallback_answer_english_variant(self):
        matches = [{"title": "Soy Sauce KIKKOMAN 150ml"}]
        answer = main.fallback_answer(matches, {}, None, False, lang="en")
        assert "I found" in answer
        assert "Soy Sauce KIKKOMAN 150ml" in answer

    def test_fallback_answer_english_no_matches(self):
        answer = main.fallback_answer([], {}, None, False, lang="en")
        assert answer == "I couldn't find an exact answer. Try rephrasing your question."


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

    def test_followup_falls_back_to_last_product_for_unrecognized_subject(self, products):
        # Regression test: a real production complaint - a customer asked
        # about jujube (not a recognized RELATED_SUBJECT_ALIASES dish), then
        # asked the bare follow-up "Ma kostky?" (does it have pits?). This
        # must resolve using the specific last-shown product, not silently
        # fall through to an unrelated subject incidentally tagged by some
        # other co-result in the same search.
        main.session_memories.clear()
        key = main.session_memory_key("memory-test-kostky", "127.0.0.1")
        memory = main.get_session_memory(key)
        matches = main.cached_search_products(products, "Jujube eaglobe", 3)
        assert matches
        main.update_session_memory(key, "Jujube eaglobe", "product_search", matches, [], {})

        assert main.is_context_followup("Ma kostky?")
        contextual = main.contextualize_message("Ma kostky?", memory)
        assert "jujuba" in main.normalize(contextual)

        followup_matches = main.cached_search_products(products, contextual, 5)
        assert followup_matches
        assert "jujuba" in main.normalize(followup_matches[0].get("title", ""))

    def test_diet_preference_is_remembered(self):
        main.session_memories.clear()
        key = main.session_memory_key("memory-test-2", "127.0.0.1")
        memory = main.get_session_memory(key)
        main.update_session_memory(key, "Som celiak, hladam bezlepkove veci", "allergen_safety", [], [], {})

        contextual = main.contextualize_message("ake omacky odporucas?", memory)

        assert "bezlepkove" in main.normalize(contextual)

    def test_diet_terms_does_not_treat_comparison_questions_as_preference(self):
        assert main.detect_diet_terms("gochujang vs sriracha, co je pikantnejsie?") == []
        assert main.detect_diet_terms("ktora omacka je pikantnejsia?") == []
        assert main.detect_diet_terms("ktory je pikantnejsi, gochujang alebo sriracha?") == []
        # Genuine preference statements are unaffected.
        assert main.detect_diet_terms("mam rad korejske pikantne kimchi") == ["pikantne"]
        assert main.detect_diet_terms("chcem nieco pikantne") == ["pikantne"]
        assert main.detect_diet_terms("je to velmi paliv?") == ["pikantne"]

    def test_comparison_question_does_not_contaminate_later_unrelated_messages(self):
        # Real regression: "gochujang vs sriracha, co je pikantnejsie?" is a
        # comparison QUESTION, not a stated dietary preference, but
        # detect_diet_terms() used to match the bare substring "pikant"
        # inside the comparative "pikantnejsie" and record a "pikantne"
        # diet term. contextualize_message() then silently injected that
        # stale term into every later message in the session regardless of
        # topic, which broke completely unrelated follow-ups: "aku
        # kategoriu produktov mate?" became "...  pikantne" and matched
        # detect_related_subject() as "medium_spicy" (zero real products),
        # and typo/brand lookups like "mate sojovu omacku kikoman" /
        # "gochuujang" / "kikkoman produkty" lost their real product
        # matches the same way further into the same session.
        main.session_memories.clear()
        key = main.session_memory_key("memory-test-spicy-contamination", "127.0.0.1")
        memory = main.get_session_memory(key)
        main.update_session_memory(
            key, "gochujang vs sriracha, co je pikantnejsie?", "product_advice", [], [], {},
        )

        assert list(memory["diet_terms"]) == []
        contextual = main.contextualize_message("mate sojovu omacku kikoman", memory)
        assert "pikantne" not in main.normalize(contextual)

    def test_diet_terms_does_not_invert_negated_statements(self):
        # Real regression, second occurrence of the same root-cause class:
        # "nechcem nic pikantne" ("I don't want anything spicy") was
        # recorded as a POSITIVE "pikantne" preference - the opposite of
        # what the customer said. detect_diet_terms() had no negation
        # awareness at all (not just for the comparative form fixed
        # earlier). Same risk applies to vegan/vegetarian/bezlepkove: "nie
        # som vegan" / "nechcem vegansky produkt" must not be recorded as
        # a vegan preference either.
        assert main.detect_diet_terms("nechcem nic pikantne") == []
        assert main.detect_diet_terms("nemam rad pikantne jedla") == []
        assert main.detect_diet_terms("neznasam pikantne") == []
        assert main.detect_diet_terms("nechcem vegansky produkt") == []
        assert main.detect_diet_terms("nie som vegan") == []
        assert main.detect_diet_terms("nemam rad kokos") == []
        # Genuine preference statements are unaffected.
        assert main.detect_diet_terms("mam rad korejske pikantne kimchi") == ["pikantne"]
        assert main.detect_diet_terms("som vegan") == ["veganske"]
        assert main.detect_diet_terms("hladam bezlepkove produkty") == ["bezlepkove"]

    def test_negated_spice_statement_does_not_corrupt_later_unrelated_answer(self):
        # Real regression found via a multi-turn synthetic QA session:
        # "nechcem nic pikantne" got wrongly recorded as a "pikantne" diet
        # term, which contextualize_message() then silently injected into
        # a much later, completely unrelated comparison question ("aky je
        # rozdiel medzi mirin a rizovym octom?" - what's the difference
        # between mirin and rice vinegar), corrupting its Products_AI
        # knowledge lookup into an unrelated, broken answer fragment about
        # a different product's flavor profile.
        main.session_memories.clear()
        key = main.session_memory_key("memory-test-negation-contamination", "127.0.0.1")
        memory = main.get_session_memory(key)
        main.update_session_memory(key, "nechcem nic pikantne", "related_products", [], [], {})

        assert list(memory["diet_terms"]) == []
        contextual = main.contextualize_message(
            "aky je rozdiel medzi mirin a rizovym octom?", memory,
        )
        assert "pikantne" not in main.normalize(contextual)

    def test_memory_redacts_contact_details(self):
        redacted = main.redact_memory_text("Moj email je test@example.com a telefon +421 900 123 456")

        assert "test@example.com" not in redacted
        assert "+421" not in redacted
        assert "[email]" in redacted
        assert "[phone]" in redacted

    def test_log_question_redacts_contact_details_in_saved_file(self, monkeypatch):
        # log_question() hashes the client identity but used to store the
        # raw question text verbatim - a customer typing an email or phone
        # number into chat landed in question_analytics.jsonl in plain text.
        # Uses tempfile directly (not the tmp_path fixture) to avoid this
        # environment's pytest-tmp-dir PermissionError, unrelated to app code.
        fd, log_path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        try:
            monkeypatch.setenv("ANALYTICS_LOG_PATH", log_path)
            main.log_question("moj email je test@example.com a cislo +421 900 123 456", "client-1", 0)
            saved = Path(log_path).read_text(encoding="utf-8")
        finally:
            os.remove(log_path)

        assert "test@example.com" not in saved
        assert "421 900 123 456" not in saved
        assert "[email]" in saved
        assert "[phone]" in saved

    def test_log_event_redacts_contact_details_in_saved_file(self, monkeypatch):
        fd, log_path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        try:
            monkeypatch.setenv("EVENTS_LOG_PATH", log_path)
            event = main.EventRequest(event_type="search_submit", query="posli mi info na test@example.com")
            main.log_event(event, "client-1")
            saved = Path(log_path).read_text(encoding="utf-8")
        finally:
            os.remove(log_path)

        assert "test@example.com" not in saved
        assert "[email]" in saved

    def test_refresh_feed_keeps_old_catalog_when_new_feed_is_empty(self, monkeypatch):
        # load_multilang_feeds() swallows per-language fetch errors (network
        # blip, HTTP error, malformed XML) and just omits the 'sk' key -
        # refresh_feed() used to overwrite the live catalog with [] in that
        # case, with no exception for the caller's try/except to catch.
        original_products = main.products
        original_snapshot = main.product_snapshot
        try:
            monkeypatch.setattr(main, "load_multilang_feeds", lambda: {})
            main.refresh_feed()

            assert main.products is original_products
            assert main.product_snapshot is original_snapshot
            assert main.last_feed_refresh_error
        finally:
            main.products = original_products
            main.product_snapshot = original_snapshot
            main.last_feed_refresh_error = None

    def test_refresh_feed_rebuilds_taxonomy_concept_index(self, products, monkeypatch):
        # V2.2: autocomplete's taxonomy_concept_index must never go stale
        # after a feed refresh (Section 37) - a product removed from the
        # new feed must disappear from the concept counts too.
        basmati_products = [p for p in products if "basmati" in main.normalize(p.title)]
        assert basmati_products, "fixture must contain at least one basmati rice product"
        reduced_products = [p for p in products if p.id != basmati_products[0].id]

        original = {
            name: getattr(main, name)
            for name in ("products", "product_snapshot", "translation_index",
                         "product_taxonomy_index", "taxonomy_concept_index",
                         "last_feed_refresh_at", "last_feed_refresh_error")
        }
        try:
            monkeypatch.setattr(main, "load_multilang_feeds", lambda: {"sk": reduced_products})
            main.refresh_feed()

            basmati_concept = next(
                (c for c in main.taxonomy_concept_index if c["concept_id"] == "basmati_rice"), None
            )
            original_basmati_concept = next(
                (c for c in original["taxonomy_concept_index"] if c["concept_id"] == "basmati_rice"), None
            )
            assert original_basmati_concept is not None
            if basmati_concept is not None:
                assert basmati_concept["product_count"] < original_basmati_concept["product_count"]
        finally:
            for name, value in original.items():
                setattr(main, name, value)

    def test_refresh_feed_rebuilds_search_performance_indexes(self, products, monkeypatch):
        # V2.2.1: refresh_feed() must warm the new precomputed token/
        # vocabulary/BM25 indexes for the NEW products list, not leave the
        # first post-refresh autocomplete call to build them on the
        # critical path (Section 44 - atomic index swap, no partial state).
        from app.search import get_product_token_index

        basmati_products = [p for p in products if "basmati" in main.normalize(p.title)]
        assert basmati_products
        reduced_products = [p for p in products if p.id != basmati_products[0].id]

        original = {
            name: getattr(main, name)
            for name in ("products", "product_snapshot", "translation_index",
                         "product_taxonomy_index", "taxonomy_concept_index",
                         "last_feed_refresh_at", "last_feed_refresh_error")
        }
        try:
            monkeypatch.setattr(main, "load_multilang_feeds", lambda: {"sk": reduced_products})
            main.refresh_feed()

            # get_product_token_index() must return instantly (already
            # warmed) and reflect the reduced catalog, not the old one.
            index = get_product_token_index(main.products)
            assert basmati_products[0].id not in index
        finally:
            for name, value in original.items():
                setattr(main, name, value)

    def test_static_files_serve_known_binary_assets(self):
        # app/mei-avatar.png, app/foodland-symbol.png and
        # app/foodland-mei-avatar-rigged.glb are served under /static but
        # ALLOWED_SUFFIXES only listed text formats - real static assets
        # would 404. Binary suffixes must not get a forced text charset.
        assert {".png", ".jpg", ".jpeg", ".webp", ".svg", ".glb"} <= main.UTF8StaticFiles.ALLOWED_SUFFIXES
        assert not ({".png", ".glb"} & set(main.UTF8StaticFiles.CHARSET_BY_SUFFIX))


class TestFAQ:
    def test_faq_shipping_cost(self, knowledge):
        answer = main.best_direct_faq_answer("kolko stoji doprava?", knowledge)
        assert answer
        assert any(kw in (answer or "").lower() for kw in ("doprava", "eur", "zadarmo", "dopravy"))

    def test_faq_shipping_cost_explains_it_depends_on_weight_and_payment_method(self, knowledge):
        # User feedback: the old answer ("Doprava je zadarmo nad 49 EUR...")
        # was too simplistic below that threshold - it didn't explain WHY
        # the price varies (weight category, only known after adding to
        # cart; payment method - COD/bank transfer/gateway) or that the
        # real total is shown at checkout before the order is confirmed.
        answer = main.best_direct_faq_answer("kedy je doprava zadarmo?", knowledge)
        assert answer
        normalized = main.normalize(answer)
        assert "49" in answer  # free-shipping threshold still stated
        assert "hmotnost" in normalized or "vahov" in normalized  # weight-based factor explained
        assert "platby" in normalized or "dobierka" in normalized  # payment-method factor explained
        assert "kosik" in normalized  # points customer to checkout for the real total

    def test_faq_payment(self, knowledge):
        answer = main.best_direct_faq_answer("ako mozem zaplatit?", knowledge)
        assert answer

    def test_faq_generic_payment_question_gets_full_methods_list(self, knowledge):
        # V2.18d.4 (C3 FAQ retrieval topic mismatch, regbug_rt0024): a bare
        # "how can I pay?" with no store/card qualifier must return the
        # complete payment-methods answer (COD + card + bank transfer +
        # ...), not the narrow "yes you can pay by card in our physical
        # store" record. Root cause: the general scoring loop's "ako"+
        # "zapl" bonus applied equally to every payment-related FAQ
        # question (all of them contain "plat" as a substring), so the
        # in-store record won on raw token overlap alone - its own
        # question text literally contains "zaplatit".
        answer = main.best_direct_faq_answer("ako mozem zaplatit?", knowledge)
        normalized = main.normalize(answer)
        assert "dobierka" in normalized
        assert "kartou" in normalized
        assert "predajni" not in normalized

    def test_faq_instore_card_question_still_gets_narrow_answer(self, knowledge):
        # Companion regression for the fix above: an explicit in-store
        # qualifier must still win the specific record, even when phrased
        # with "ako" (which the generic-question shortcut above also
        # matches on).
        for query in (
            "ako mozem zaplatit kartou v predajni?",
            "Da sa v predajni platit kartou?",
            "Mozem zaplatit kartou priamo v predajni?",
        ):
            answer = main.best_direct_faq_answer(query, knowledge)
            assert answer
            assert "predajni" in main.normalize(answer), query

    def test_faq_intent_detects_slovak_loyalty_program_wording(self):
        # Regression: FAQ_INTENT_MARKERS only had the English "loyalty",
        # so a Slovak question about "vernostny program" never even reached
        # the FAQ lookup and fell through to plain product search instead.
        assert main.is_faq_intent("Ma Foodland vernostny program so zlavami alebo bodmi?")

    def test_faq_returns_none_for_product_query(self, knowledge):
        answer = main.best_direct_faq_answer("gochujang pasta", knowledge)
        assert answer is None

    def test_faq_tracking_question_beats_generic_delivery_methods(self, knowledge):
        # Regression from a real dashboard no-result: "sledovanie zasielok"
        # (order tracking) scored zero token overlap with any FAQ entry, so
        # it needed a direct-marker shortcut like the shipping/delivery ones
        # above it. "zasiel" also matches the delivery-methods shortcut, so
        # the tracking check must run first or a tracking question gets the
        # generic "which delivery methods do you offer" answer instead.
        answer = main.best_direct_faq_answer("sledovanie zasielok", knowledge)
        assert answer
        assert "objednavky" in main.normalize(answer) or "ucte" in main.normalize(answer)

    # Regression suite from a systematic audit: all 51 FAQ entries were
    # tested against realistic short/terse customer phrasings (not just the
    # FAQ's own question wording). ~12 scored a confident but wrong answer
    # instead of a clean "no match" - each fixed below with a direct-marker
    # shortcut, verified not to regress any of the other 50 entries.

    def test_faq_parking_reaches_intent_gate_and_scores(self, knowledge):
        # Real user report: "Parkovanie, kde sa da zaparkovat?" answered
        # with random unrelated products. FAQ_INTENT_MARKERS had no marker
        # for parking at all, so the question never reached the FAQ branch;
        # and even a bare "Parkovanie" alone shares only the noun root with
        # the FAQ's own question wording ("parkovanie" vs "zaparkovat"),
        # topping out at score 1 - short of the >= 3 threshold.
        assert main.is_faq_intent("Parkovanie, kde sa da zaparkovat?")
        answer = main.best_direct_faq_answer("Parkovanie, kde sa da zaparkovat?", knowledge)
        assert answer
        assert "parkovanie" in main.normalize(answer)
        assert main.best_direct_faq_answer("Parkovanie", knowledge) == answer

    def test_faq_delivery_methods_reaches_gate_with_doprava_declensions(self, knowledge):
        # Real user report: "sposoby dopravy foodlandu" answered with
        # random products. FAQ_INTENT_MARKERS had "doprava" (nominative),
        # which does not match the genitive "dopravy" as a substring -
        # shortened the marker to the root "doprav" so it covers every
        # case. Also needed "doprav" added as a trigger for the
        # delivery-methods shortcut itself (separate from the intent gate).
        for query in ("sposoby dopravy foodlandu", "sposoby dopravy", "ake su sposoby dopravy"):
            assert main.is_faq_intent(query), query
            answer = main.best_direct_faq_answer(query, knowledge)
            assert answer, query
            assert "osobny odber" in main.normalize(answer) or "kurierom" in main.normalize(answer)

    def test_faq_free_shipping_still_wins_over_delivery_methods(self, knowledge):
        # Regression: broadening the delivery-methods shortcut trigger to
        # "doprav" made it also catch "kedy je doprava zadarmo?" (when is
        # shipping free), which shares that root - it must still resolve to
        # the free-shipping-threshold answer, not the generic delivery
        # methods list, regardless of word order between "doprava" and
        # "zadarmo".
        for query in ("kolko stoji doprava?", "kedy je doprava zadarmo?", "doprava je zadarmo od kolko?"):
            answer = main.best_direct_faq_answer(query, knowledge)
            assert answer, query
            assert "49" in answer, query

    def test_faq_delivery_time_beats_generic_delivery_methods(self, knowledge):
        # Real user report: "Ako dlho trva dorucenie zasielok?" (how long
        # does shipping take) got the generic "which delivery methods do
        # you offer" answer instead of the specific delivery-time answer -
        # both contain "doruc", and the generic shortcut ran first.
        for query in ("Ako dlho trva dorucenie zasielok?", "ako dlho trva dorucenie objednavky"):
            answer = main.best_direct_faq_answer(query, knowledge)
            assert answer, query
            assert "72" in answer or "3 pracovne" in main.normalize(answer), query

    def test_faq_shipping_cost_wording_with_kolko_and_zaplatit(self, knowledge):
        # Real user report (screenshot): "Kolko treba zaplatit za dopravu?"
        # got the delivery-METHODS answer instead of the shipping-cost
        # answer - the shortcut required the exact phrase "kolko stoji
        # doprava" and didn't recognize "kolko treba zaplatit za dopravu"
        # as the same question. Broadened to a flexible "kolko" + cost verb
        # (stoji/zaplatit/platit) + doprav/postovn/doruc combination -
        # verified this doesn't also swallow "kolko trva dorucenie" (a
        # duration question, not cost), which must still reach the
        # delivery-time answer instead.
        for query in ("kolko treba zaplatit za dopravu", "kolko stoji dorucenie"):
            answer = main.best_direct_faq_answer(query, knowledge)
            assert answer, query
            assert "zadarmo" in main.normalize(answer), query

        duration_answer = main.best_direct_faq_answer("kolko trva dorucenie", knowledge)
        assert duration_answer
        assert "72" in duration_answer or "3 pracovne" in main.normalize(duration_answer)

    def test_faq_delivery_deadline_wording_reaches_delivery_time_answer(self, knowledge):
        # Real dashboard no-result: "Termindodania" (delivery deadline) never
        # matched any FAQ_INTENT_MARKERS root at all - "dodan" doesn't appear
        # anywhere else in the FAQ corpus (verified), so it's a pure
        # vocabulary gap, not a routing collision like the "dlho" cases above.
        for query in ("termin dodania", "aky je termin dodania"):
            assert main.is_faq_intent(query), query
            answer = main.best_direct_faq_answer(query, knowledge)
            assert answer, query
            assert "72" in answer or "3 pracovne" in main.normalize(answer), query

    def test_faq_pickup_ready_while_you_wait_no_longer_leaks_to_ai_cross_sell(self, knowledge):
        # Real user report (screenshot): a question about whether in-store
        # pickup is ready "na pockanie" (while you wait) got an AI-generated
        # answer with an unsolicited product recommendation attached (a
        # Wasabi sauce card) - the user's complaint: "pri takych otazkach
        # nema byt doporucenie produktov" (such questions must not get
        # product recommendations). Root cause: neither "pockanie" nor
        # "odber" was in FAQ_INTENT_MARKERS at all, so is_faq_intent()
        # rejected the message before it ever reached the FAQ system,
        # falling all the way through to the general AI answer path -
        # whose system prompt always appends a cross-sell nudge when any
        # (even coincidentally matched) products are attached.
        for query in (
            "je osobny odber na pockanie",
            "da sa vyzdvihnut tovar na pockanie",
            "mozem si tovar vyzdvihnut hned na pockanie",
        ):
            assert main.is_faq_intent(query), query
            answer = main.best_direct_faq_answer(query, knowledge)
            assert answer, query
            assert "e-mail" in main.normalize(answer) or "email" in main.normalize(answer), query

    def test_faq_delivery_speed_wording_beats_generic_delivery_methods(self, knowledge):
        # Real dashboard no-result: "rychlost dorucenia" (delivery speed)
        # reached the FAQ system fine via "doruc" but the generic "which
        # delivery methods" shortcut won because it only checked for "dlho",
        # not "rychlost".
        answer = main.best_direct_faq_answer("rychlost dorucenia", knowledge)
        assert answer
        assert "72" in answer or "3 pracovne" in main.normalize(answer)

    def test_faq_bare_store_word_gets_store_info_not_none(self, knowledge):
        # Real dashboard no-result: the bare word "Predajnu" (store,
        # accusative) only overlaps one token with the store-info FAQ, which
        # scores below the >=3 confidence threshold in the general scoring
        # loop and returned None - falling through to a product search with
        # zero results instead of the obvious store-info answer.
        answer = main.best_direct_faq_answer("predajnu", knowledge)
        assert answer
        assert "vajnorska" in main.normalize(answer)

    def test_faq_card_type_question_not_hijacked_by_curry_subject(self, knowledge):
        # Real user report: "typy kariet" / "aky typ kariet prijimate"
        # (which card types do you accept) returned kari-pasta / curry
        # cross-sell products instead of the payment-methods FAQ. Root
        # cause: "kariet" (cards, genitive plural) contains "kari" (curry)
        # as a substring, which detect_related_subject() matches via plain
        # substring check - same class of bug as "sake" hijacking "sake
        # sety" before Sprint V.
        for query in ("typy kariet", "aky typ kariet prijimate"):
            assert main.is_faq_intent(query), query
            answer = main.best_direct_faq_answer(query, knowledge)
            assert answer, query
            assert "kartou" in main.normalize(answer) or "platob" in main.normalize(answer), query
        # Legitimate curry questions must still work normally.
        assert main.detect_related_subject("recept na kari") == "kari"

    def test_faq_company_address_beats_generic_product_search(self, knowledge):
        # Real dashboard no-result: "Adresa firmy" got an unrelated dashi
        # soup-base product instead of the store address FAQ. "adresa" had
        # no FAQ_INTENT_MARKERS entry at all.
        for query in ("Adresa firmy", "Adresa", "aka je adresa predajne"):
            assert main.is_faq_intent(query), query
            answer = main.best_direct_faq_answer(query, knowledge)
            assert answer, query
            assert "vajnorska" in main.normalize(answer), query

    def test_faq_cash_on_delivery_home_beats_card_in_store(self, knowledge):
        # "da sa platit dobierkou" used to match the unrelated "can I pay by
        # card in store" FAQ (both mention "plat"/"kart" adjacent words).
        answer = main.best_direct_faq_answer("da sa platit dobierkou", knowledge)
        assert answer
        assert "dobierkou" in main.normalize(answer)

    def test_faq_cash_on_delivery_with_courier_beats_generic_delivery_methods(self, knowledge):
        # "dobierka kurier" used to match the generic "which delivery
        # methods do you offer" shortcut instead of the specific COD answer,
        # since "kurier" triggers both.
        answer = main.best_direct_faq_answer("dobierka kurier", knowledge)
        assert answer
        assert "dobierk" in main.normalize(answer)

    def test_faq_which_countries_beats_generic_delivery_methods(self, knowledge):
        # "dorucujete do cr?" used to match the generic delivery-methods
        # shortcut (triggered by "doruc") instead of the countries-list FAQ.
        answer = main.best_direct_faq_answer("dorucujete do cr?", knowledge)
        assert answer
        assert "krajin" in main.normalize(answer)

    def test_faq_no_show_beats_generic_how_to_order(self, knowledge):
        # "nevyzdvihol som si objednavku" (I never picked up my order) used
        # to score highest against the unrelated "how do I place an order"
        # FAQ - actively unhelpful for a customer worried about a no-show.
        answer = main.best_direct_faq_answer("nevyzdvihol som si objednavku", knowledge)
        assert answer
        assert "neprevzati" in main.normalize(answer) or "zmluvnu pokutu" in main.normalize(answer)

    def test_faq_refund_timing_beats_generic_complaint_contact(self, knowledge):
        # "vratenie penazi" used to match the generic wrong-item complaint
        # FAQ instead of the specific refund-timing answer.
        answer = main.best_direct_faq_answer("vratenie penazi", knowledge)
        assert answer
        assert "lehotach" in main.normalize(answer) or "obchodnymi podmienkami" in main.normalize(answer)

    def test_faq_credit_note_mechanism_beats_generic_complaint_contact(self, knowledge):
        answer = main.best_direct_faq_answer("vratenie penazi dobropisom", knowledge)
        assert answer
        assert "dobropis" in main.normalize(answer)

    def test_faq_exchange_in_store_beats_complaint_in_store(self, knowledge):
        # "vymena v predajni" used to tie-break against the unrelated
        # "can I resolve a complaint in store" FAQ (both share the
        # "vymen"/"predajni" category-marker bonus).
        answer = main.best_direct_faq_answer("vymena v predajni", knowledge)
        assert answer
        assert "vymen" in main.normalize(answer) or "vraten" in main.normalize(answer)

    def test_faq_credit_validity_beats_generic_credits_intro(self, knowledge):
        # "platnost kreditov" used to match the top-level "yes we have a
        # credits program" intro instead of the specific 365-day answer.
        answer = main.best_direct_faq_answer("platnost kreditov", knowledge)
        assert answer
        assert "365" in answer

    def test_faq_credit_expiry_notice_beats_generic_credits_intro(self, knowledge):
        answer = main.best_direct_faq_answer("upozornenie na vyprsanie kreditov", knowledge)
        assert answer
        assert "notifik" in main.normalize(answer) or "30 dni" in main.normalize(answer) or "upozornime" in main.normalize(answer)

    def test_faq_sub_question_beats_generic_same_category_answer(self, knowledge):
        # Regression: sub-questions in knowledge.json leave Kategória blank
        # and inherit the preceding row's category. Without forward-filling
        # that category for scoring, a specific sub-question like "can I pay
        # by card in store" lost to the generic "which payment methods do
        # you support" answer, because only the generic row carried a
        # Kategória value and got the FAQ_CATEGORY_MARKERS bonus.
        answer = main.best_direct_faq_answer("Da sa v predajni platit kartou?", knowledge)
        assert answer
        assert "predajni" in main.normalize(answer)


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

    def test_public_suggested_questions_exclude_frequent_no_results(self):
        # Regression: "Ma kostky?" only makes sense as a follow-up right
        # after a specific product was discussed (Sprint N), so asked cold
        # it reliably returns zero matches - yet it was frequent enough to
        # show up as a standalone "suggested question" chip, actively
        # inviting visitors into a guaranteed no-result experience. Rather
        # than hardcoding that one phrase, exclude any question that is
        # itself tracked as a no-result in the same window, so this stays
        # correct automatically as new context-dependent questions emerge.
        events = [
            {"ts": 10, "message": "Ma kostky?", "matches_count": 0, "intent": "product_search"},
            {"ts": 11, "message": "Ma kostky?", "matches_count": 0, "intent": "product_search"},
            {"ts": 12, "message": "Korenie na ryzu", "matches_count": 3, "intent": "product_search"},
            {"ts": 13, "message": "Korenie na ryzu", "matches_count": 5, "intent": "product_search"},
        ]
        rows = main.public_suggested_question_rows(events, limit=5, min_count=2)

        questions = [row["question"] for row in rows]
        assert "Korenie na ryzu?" in questions or "Korenie na ryzu" in questions
        assert not any("kostky" in main.normalize(q) for q in questions)

    def test_clean_public_suggested_question_filters_sensitive_text(self):
        assert main.clean_public_suggested_question("napiste mi na test@example.com") == ""
        assert main.clean_public_suggested_question("pozri https://example.com") == ""
        assert main.clean_public_suggested_question("objednavka 123456789") == ""
        assert main.clean_public_suggested_question("recept na pho") == "recept na pho?"

    def test_events_summary_counts_by_type_and_product(self):
        events = [
            {"ts": 10, "session_id": "s1", "event_type": "impression", "product_skus": ["FL_1", "FL_2"]},
            {"ts": 11, "session_id": "s1", "event_type": "click", "product_sku": "FL_1"},
            {"ts": 12, "session_id": "s1", "event_type": "add_to_cart", "product_sku": "FL_1"},
            {"ts": 13, "session_id": "s2", "event_type": "click", "product_sku": "FL_2"},
            {"ts": 14, "session_id": "s2", "event_type": "no_result"},
        ]

        summary = main.events_summary(events)

        assert summary["total_events"] == 5
        assert summary["events_by_type"] == {"impression": 1, "click": 2, "add_to_cart": 1, "no_result": 1}
        assert summary["unique_sessions"] == 2
        assert summary["unique_products_touched"] == 2
        assert summary["top_products_by_touches"][0] == {"product_sku": "FL_1", "touches": 3}
        assert summary["earliest_ts"] == 10
        assert summary["latest_ts"] == 14

    def test_events_summary_handles_empty_events(self):
        summary = main.events_summary([])

        assert summary["total_events"] == 0
        assert summary["events_by_type"] == {}
        assert summary["unique_sessions"] == 0
        assert summary["earliest_ts"] is None
        assert summary["latest_ts"] is None

    def test_admin_analytics_events_summary_endpoint_requires_token(self, monkeypatch):
        monkeypatch.delenv("ADMIN_ANALYTICS_TOKEN", raising=False)
        monkeypatch.delenv("ADMIN_RELOAD_TOKEN", raising=False)

        with pytest.raises(main.HTTPException):
            main.admin_analytics_events_summary(days=30, x_admin_token=None)

    def test_admin_analytics_events_summary_endpoint_with_valid_token(self, monkeypatch, tmp_path):
        log_path = tmp_path / "events.jsonl"
        log_path.write_text(
            '{"ts": 9999999999, "session_id": "s1", "event_type": "click", "product_sku": "FL_1"}\n',
            encoding="utf-8",
        )
        monkeypatch.setenv("EVENTS_LOG_PATH", str(log_path))
        monkeypatch.setenv("ADMIN_ANALYTICS_TOKEN", "test-token")

        result = main.admin_analytics_events_summary(days=30, x_admin_token="test-token")

        assert result["total_events"] == 1
        assert result["events_by_type"] == {"click": 1}


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

    def test_generic_recommendation_request_returns_no_random_products(self):
        # Real user report: "Co ma kupit ked ma alergiu na lepok" (colloquial
        # "ma" instead of grammatically correct "mam") returned random
        # unrelated products (lychee nectar, fenugreek seeds, instant pho
        # soup...) instead of the safe "check the label" answer with no
        # products. Root cause: the cleanup_patterns step in
        # allergen_product_query() strips the standalone word "ma" (meant
        # for "produkt MA lepok" phrasing) before the generic-request check
        # ever saw it, so "co ma kupit" could never match there - only the
        # grammatically correct "co mam kupit" worked.
        for message in (
            "Co ma kupit ked ma alergiu na lepok",
            "co mam kupit ked mam alergiu na lepok",
            "co si ma kupit ked mam intoleranciu na lepok",
        ):
            assert main.detect_allergen_intent(message) == "lepok", message
            assert main.allergen_product_query(message) == "", message
            assert main.allergen_product_matches(message, 6) == [], message


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

    def test_products_include_brand_for_personalization(self, products):
        results = autocomplete_products(products, "gochuj", 4)
        assert results
        assert all("brand" in r for r in results)

    def test_endpoint_reorders_by_profile_affinity(self, products, monkeypatch):
        monkeypatch.setattr(main, "products", products)
        monkeypatch.setattr(main, "cached_top_questions", lambda: [])
        fixed_suggestions = [
            {"title": "Produkt A", "url": "https://x/a", "price": 1.0, "image": "", "brand": "OTHER"},
            {"title": "Produkt B", "url": "https://x/b", "price": 2.0, "image": "", "brand": "TARGET_BRAND"},
        ]
        monkeypatch.setattr(main, "autocomplete_products", lambda *a, **k: [dict(s) for s in fixed_suggestions])
        fake_profile = {"product_brands": {"TARGET_BRAND": 6}}
        monkeypatch.setattr(main, "get_user_memory", lambda profile_key: fake_profile)
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))

        result = main.autocomplete(request, q="produkt", limit=4, client_id="client-abc")

        assert result["products"][0]["title"] == "Produkt B"
        assert result["products"][0]["personalized"] is True

    def test_endpoint_unaffected_without_profile(self, products, monkeypatch):
        monkeypatch.setattr(main, "products", products)
        monkeypatch.setattr(main, "cached_top_questions", lambda: [])
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))

        without_client_id = main.autocomplete(request, q="sushi", limit=4)
        with_unknown_client_id = main.autocomplete(request, q="sushi", limit=4, client_id="brand-new-client")

        assert without_client_id["products"] == with_unknown_client_id["products"]

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
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))

        result = main.recommend_similar(request, sku=sample_sku, limit=4)

        assert result["sku"] == sample_sku
        assert result["product"] is not None
        assert isinstance(result["recommendations"], list)
        assert len(result["recommendations"]) <= 4
        assert all(r.get("id") != sample_sku for r in result["recommendations"])

    def test_recommend_similar_unknown_sku(self, products, knowledge, monkeypatch):
        monkeypatch.setattr(main, "products", products)
        monkeypatch.setattr(main, "knowledge", knowledge)
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))

        result = main.recommend_similar(request, sku="NOT_REAL", limit=4)

        assert result["product"] is None
        assert result["recommendations"] == []

    def test_recommend_similar_reorders_by_profile_affinity(self, products, knowledge, monkeypatch):
        monkeypatch.setattr(main, "products", products)
        monkeypatch.setattr(main, "knowledge", knowledge)
        monkeypatch.setattr(main, "knowledge_record_by_id", lambda *a, **k: None)
        sample_sku = products[0].id
        fixed_candidates = [
            {"id": "FL_A", "title": "Produkt A", "brand": "OTHER"},
            {"id": "FL_B", "title": "Produkt B", "brand": "TARGET_BRAND"},
        ]
        monkeypatch.setattr(main, "cached_search_products", lambda *a, **k: [dict(p) for p in fixed_candidates])
        fake_profile = {"product_brands": {"TARGET_BRAND": 6}}
        monkeypatch.setattr(main, "get_user_memory", lambda profile_key: fake_profile)
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))

        result = main.recommend_similar(request, sku=sample_sku, limit=5, client_id="client-abc")

        assert result["recommendations"][0]["id"] == "FL_B"
        assert result["recommendations"][0]["personalized"] is True

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

    def test_basket_recommendations_falls_back_to_knowledge_when_fbt_inactive(self, products, knowledge, monkeypatch):
        # Regression guard: at the current tiny production add_to_cart
        # volume the FBT gate stays inactive, so basket recommendations
        # must be byte-for-byte identical to before FBT was wired in.
        sample_sku = products[0].id
        monkeypatch.setattr(main, "get_fbt_data", lambda: {"pairs": {}, "total_add_to_cart_events": 2, "active": False})

        baseline = main.basket_recommendations(products, knowledge, [sample_sku], 5)
        monkeypatch.setattr(main, "FBT_RECOMMENDATIONS_ENABLED", False)
        without_fbt = main.basket_recommendations(products, knowledge, [sample_sku], 5)

        assert baseline == without_fbt

    def test_basket_recommendations_prefers_fbt_pair_when_active(self, products, knowledge, monkeypatch):
        sample_sku = products[0].id
        other_sku = products[1].id
        fake_fbt = {
            "pairs": {sample_sku: [(other_sku, 10)]},
            "total_add_to_cart_events": 500,
            "active": True,
        }
        monkeypatch.setattr(main, "get_fbt_data", lambda: fake_fbt)

        results = main.basket_recommendations(products, knowledge, [sample_sku], 5)

        assert results
        assert results[0]["id"] == other_sku

    def test_admin_fbt_pairs_requires_token(self, monkeypatch):
        monkeypatch.delenv("ADMIN_ANALYTICS_TOKEN", raising=False)
        monkeypatch.delenv("ADMIN_RELOAD_TOKEN", raising=False)

        with pytest.raises(main.HTTPException):
            main.admin_fbt_pairs(sku="FL_1", limit=20, x_admin_token=None)

    def test_admin_fbt_pairs_returns_data_for_sku(self, monkeypatch):
        monkeypatch.setenv("ADMIN_ANALYTICS_TOKEN", "test-token")
        fake_fbt = {
            "pairs": {"FL_1": [("FL_2", 5)]},
            "total_add_to_cart_events": 500,
            "active": True,
        }
        monkeypatch.setattr(main, "get_fbt_data", lambda: fake_fbt)

        result = main.admin_fbt_pairs(sku="FL_1", limit=20, x_admin_token="test-token")

        assert result["active"] is True
        assert result["co_purchased_skus"] == ["FL_2"]

    def test_admin_fbt_pairs_returns_sample_without_sku(self, monkeypatch):
        monkeypatch.setenv("ADMIN_ANALYTICS_TOKEN", "test-token")
        fake_fbt = {
            "pairs": {"FL_1": [("FL_2", 5)], "FL_3": [("FL_4", 2)]},
            "total_add_to_cart_events": 500,
            "active": True,
        }
        monkeypatch.setattr(main, "get_fbt_data", lambda: fake_fbt)

        result = main.admin_fbt_pairs(sku="", limit=20, x_admin_token="test-token")

        assert result["skus_with_pairs"] == 2
        assert len(result["sample"]) == 2

    def test_basket_recommendations_reorders_by_profile_affinity(self, products, knowledge, monkeypatch):
        # Force the plain title-search fallback tier with fixed candidates
        # so the test does not depend on which CrossSell/Alternatives/FBT
        # record happens to exist for this product in the real catalog.
        monkeypatch.setattr(main, "FBT_RECOMMENDATIONS_ENABLED", False)
        monkeypatch.setattr(main, "knowledge_record_by_id", lambda *a, **k: None)
        fixed_candidates = [
            {"id": "FL_A", "title": "Produkt A", "brand": "OTHER"},
            {"id": "FL_B", "title": "Produkt B", "brand": "TARGET_BRAND"},
        ]
        monkeypatch.setattr(main, "cached_search_products", lambda *a, **k: [dict(p) for p in fixed_candidates])
        sample_sku = products[0].id
        profile = {
            "cuisines": {},
            "subjects": {},
            "diet_terms": {},
            "product_titles": {},
            "product_brands": {"TARGET_BRAND": 6},
        }

        personalized = main.basket_recommendations(products, knowledge, [sample_sku], 5, profile)

        assert personalized[0]["id"] == "FL_B"
        assert personalized[0]["personalized"] is True

    def test_basket_recommendations_unaffected_without_profile(self, products, knowledge, monkeypatch):
        sample_sku = products[0].id

        without_profile_arg = main.basket_recommendations(products, knowledge, [sample_sku], 5)
        with_empty_profile = main.basket_recommendations(products, knowledge, [sample_sku], 5, {})

        assert without_profile_arg == with_empty_profile

    def test_recommend_basket_endpoint_applies_client_profile(self, products, knowledge, monkeypatch):
        monkeypatch.setattr(main, "products", products)
        monkeypatch.setattr(main, "knowledge", knowledge)
        sample_sku = products[0].id
        captured = {}
        def fake_basket_recommendations(products_list, all_knowledge, skus, limit, profile=None):
            captured["profile"] = profile
            return []
        monkeypatch.setattr(main, "basket_recommendations", fake_basket_recommendations)
        fake_profile = {"product_brands": {"ACME": 5}}
        monkeypatch.setattr(main, "get_user_memory", lambda profile_key: fake_profile)
        request = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))
        basket_request = main.BasketRecommendRequest(skus=[sample_sku], limit=4, client_id="client-xyz")

        main.recommend_basket(basket_request, request)

        assert captured["profile"] == fake_profile

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

        request = make_filter_request(brand=[sample_brand], limit=50)
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


# ---------------------------------------------------------------------------
# Audit scripts wired into the normal pytest run.
#
# scripts/consistency_audit.py and scripts/trust_audit.py were built earlier
# this project as standalone tools you had to remember to run by hand before
# a commit. Only the zero-noise checks are wired in here as hard gates
# (marker/alias collisions, empty-alternatives, PII leaks) - both scripts'
# own docstrings explain that the declension checks are candidate
# generators, not verdicts, and would make `pytest` fail on findings that
# need a human "is this actually a bug?" triage step, so those stay
# standalone (`python scripts/consistency_audit.py --declensions`).
# ---------------------------------------------------------------------------

def test_audit_no_marker_alias_collisions():
    from scripts.consistency_audit import check_collisions

    findings = check_collisions()
    assert not findings, "New marker/alias substring collision(s), see scripts/consistency_audit.py:\n" + "\n".join(findings)


def test_audit_no_empty_replacement_alternatives():
    from scripts.trust_audit import check_empty_alternatives

    findings = check_empty_alternatives()
    assert not findings, "replacement_products reply would show zero alternatives, see scripts/trust_audit.py:\n" + "\n".join(findings)


def test_audit_no_pii_leak_in_redaction():
    from scripts.trust_audit import check_pii_leak

    findings = check_pii_leak()
    assert not findings, "redact_pii() left PII in the output, see scripts/trust_audit.py:\n" + "\n".join(findings)


class TestV2_18d8_RecipeShoppingLanguageWordBoundary:
    """V2.18d.8 - C6 word-order fragility root cause (docs/routing-debt.md
    rt0002 entry). "co potrebujem"/"co treba"/"co k tomu"/"co pridat" are
    meant to detect the standalone word "co" ("čo" = "what"), but a bare
    substring check also matched INSIDE a preceding word: Slovak "nieco"
    (something) ends in "co", so "nieco potrebujem" (something I need - a
    perfectly natural word order) silently satisfied "co potrebujem"
    (what do I need), forcing ACTION-language detection where none was
    intended. _has_recipe_shopping_language() now requires a word
    boundary before markers starting with "co ", while every other marker
    keeps its original, deliberately loose stem-substring match.
    """

    def test_word_glued_before_co_marker_no_longer_matches(self):
        assert main._has_recipe_shopping_language("nieco potrebujem bez lepku k sushi") is False

    def test_other_co_ending_words_also_protected(self):
        # Not a one-word special case - any word ending in "co" is affected.
        assert main._has_recipe_shopping_language("vselico potrebujem") is False
        assert main._has_recipe_shopping_language("to nieco treba kupit") is False

    def test_standalone_co_marker_still_matches(self):
        assert main._has_recipe_shopping_language("co potrebujem na wok?") is True
        assert main._has_recipe_shopping_language("co treba na kimchi?") is True
        assert main._has_recipe_shopping_language("co k tomu pasuje?") is True
        assert main._has_recipe_shopping_language("co pridat do kosika?") is True

    def test_co_marker_at_start_of_message_still_matches(self):
        assert main._has_recipe_shopping_language("Co potrebujem na wok?") is True

    def test_non_co_markers_keep_loose_stem_matching(self):
        # "ingredien" must still match inflected forms like "ingredienciu" -
        # the boundary fix must not spread to markers that never had this bug.
        assert main._has_recipe_shopping_language("aku mate ingredienciu na sushi") is True
        assert main._has_recipe_shopping_language("recept na kimchi") is True

    def test_canonical_and_word_order_variant_now_agree(self):
        # The actual regbug_rt0002 pair (docs/routing-debt.md) - both must
        # resolve to the same has_recipe_shopping_language() verdict now.
        canonical = main._has_recipe_shopping_language("potrebujem niečo bez lepku k sushi")
        word_order_variant = main._has_recipe_shopping_language("niečo potrebujem bez lepku k sushi")
        assert canonical == word_order_variant == False

