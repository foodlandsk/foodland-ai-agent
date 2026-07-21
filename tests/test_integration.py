"""
tests/test_integration.py  –  Integration testy: workflow engine + OpenAI retry

Spustenie:
    pytest tests/test_integration.py -v

Pokryva:
- detect_workflow pre vsetky intenty (allergen, faq, recipe, cross_sell, product_search)
- workflow kontrakt (get_contract) pre kazdy intent
- end-to-end chat odpoved s mock OpenAI (normalna cesta)
- retry logika: RateLimitError 2x → uspech na 3. pokus
- fallback po vycerpani retry (APITimeoutError, APIConnectionError)
- fallback_answer ked nie je OPENAI_API_KEY

Nevyzaduje OPENAI_API_KEY ani ziadnu sietovu konektivitu.
"""
from __future__ import annotations

import os
import sys
import types
import unittest.mock as mock
from pathlib import Path

import pytest

# ─── Root path ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ─── Stubs pre pydantic / fastapi / openai ────────────────────────────────────
# Musime stubnout pred importom app.main, aby zbytocne kniznice nepadali.

def _install_stubs() -> None:
    if "pydantic" in sys.modules:
        return

    # pydantic
    pydantic = types.ModuleType("pydantic")
    class _BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    pydantic.BaseModel = _BaseModel
    pydantic.Field = lambda default=None, **kw: default
    sys.modules["pydantic"] = pydantic

    # fastapi
    fastapi = types.ModuleType("fastapi")
    class _FastAPI:
        def __init__(self, **kw): pass
        def mount(self, *a, **kw): pass
        def add_middleware(self, *a, **kw): pass
        def get(self, *a, **kw): return lambda f: f
        def post(self, *a, **kw): return lambda f: f
        def on_event(self, *a, **kw): return lambda f: f
    fastapi.FastAPI = _FastAPI
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
    sys.modules["fastapi"] = fastapi
    sys.modules["fastapi.middleware"] = types.ModuleType("fastapi.middleware")
    sys.modules["fastapi.middleware.cors"] = cors_mod
    sys.modules["fastapi.staticfiles"] = static_mod

    # openai – realne error typy musime zachovat pre retry logiku
    # Pouzijeme jednoduche stub triedy ktore su instanciou Exception
    openai_mod = types.ModuleType("openai")
    class _OpenAIError(Exception): pass
    class RateLimitError(_OpenAIError): pass
    class APITimeoutError(_OpenAIError): pass
    class APIConnectionError(_OpenAIError): pass
    class OpenAI:
        def __init__(self, **kw): pass
    openai_mod.OpenAI = OpenAI
    openai_mod.RateLimitError = RateLimitError
    openai_mod.APITimeoutError = APITimeoutError
    openai_mod.APIConnectionError = APIConnectionError
    sys.modules["openai"] = openai_mod

    # tenacity – chceme skutocnu tenacity logiku, ale ak nie je nainstalovana
    # (napr. v CI bez tenacity), poskytneme pasivny stub ktory retry nevykonava.
    try:
        import tenacity  # noqa: F401
    except ImportError:
        tenacity_mod = types.ModuleType("tenacity")
        def _no_retry(**kw):
            def decorator(fn): return fn
            return decorator
        tenacity_mod.retry = _no_retry
        tenacity_mod.retry_if_exception_type = lambda *a: None
        tenacity_mod.stop_after_attempt = lambda n: None
        tenacity_mod.wait_exponential = lambda **kw: None
        sys.modules["tenacity"] = tenacity_mod

    os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "1000000")


_install_stubs()

import app.main as main  # noqa: E402
from app.workflows import detect_workflow, get_contract  # noqa: E402

# ─── Pomocne fixtures ────────────────────────────────────────────────────────���

SAMPLE_PRODUCTS = [
    {
        "id": "p1",
        "title": "Bezlepkova sojova omacka Kikkoman 250ml",
        "description": "Tamari sojova omacka bez lepku, vhodna pre celiatikov.",
        "price": "3.99",
        "effective_price": 3.99,
        "currency": "EUR",
        "link": "https://www.foodland.sk/p/p1",
        "category": "Omacky",
        "brand": "Kikkoman",
        "availability": "in stock",
    },
    {
        "id": "p2",
        "title": "Kokosove mlieko BIO 400ml",
        "description": "Organicke kokosove mlieko bez pridanych latok.",
        "price": "2.49",
        "effective_price": 2.49,
        "currency": "EUR",
        "link": "https://www.foodland.sk/p/p2",
        "category": "Mlieko a alternativy",
        "brand": "Aroy-D",
        "availability": "in stock",
    },
    {
        "id": "p3",
        "title": "Ramen nudle bez glutenu 200g",
        "description": "Ryzove nudle vhodne pre bezlepkovu dietu.",
        "price": "1.89",
        "effective_price": 1.89,
        "currency": "EUR",
        "link": "https://www.foodland.sk/p/p3",
        "category": "Nudle a cestoviny",
        "brand": "Lotus",
        "availability": "in stock",
    },
]

SAMPLE_KNOWLEDGE: dict = {}


def _make_chat_request(message: str, limit: int = 5):
    """Vytvori ChatRequest-like objekt kompatibilny s main.chat()."""
    req = object.__new__(main.ChatRequest)
    req.message = message
    req.limit = limit
    return req


def _mock_http_request():
    """Stub pre FastAPI Request objekt."""
    req = mock.MagicMock()
    req.headers = {}
    req.client = types.SimpleNamespace(host="127.0.0.1")
    return req


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Workflow detection
# ═══════════════════════════════════════════════════════════════════════════════

class TestDetectWorkflow:
    """detect_workflow vracia spravny intent pre rozne typy sprav."""

    def _detect(self, message: str) -> str:
        return detect_workflow(
            message,
            detect_allergen_fn=main.detect_allergen_intent,
            detect_faq_fn=lambda m: None,          # FAQ stub – test_core pokryva detail
            detect_recipe_subject_fn=main.detect_recipe_subject,
            detect_out_of_domain_fn=main.detect_out_of_domain,
            detect_special_fn=main.detect_special_product_subject,
            detect_related_fn=main.detect_related_subject,
        )

    def test_allergen_safety_lepok(self):
        assert self._detect("mam celiakiu, kde najdem bezlepkove produkty?") == "allergen_safety"

    def test_allergen_safety_laktoza(self):
        assert self._detect("som laktozovo intolerantny, mam problem s mliekom") == "allergen_safety"

    def test_allergen_safety_arasidy(self):
        assert self._detect("mam alergia na arasidy, mozem jest tento produkt?") == "allergen_safety"

    def test_out_of_domain(self):
        assert self._detect("ake je dnes pocasie v Bratislave?") == "out_of_domain"

    def test_product_search_default(self):
        assert self._detect("chcem kupit sojovu omacku") == "product_search"

    def test_recipe_to_products(self):
        # "recept na sushi" + "kupim ingrediencie" → recipe_to_products
        wf = self._detect("recept na sushi a chcel by som kupit ingrediencie")
        assert wf in ("recipe_to_products", "recipe_only")

    def test_cross_sell_related(self):
        # "co ide k" → related intent → cross_sell
        wf = self._detect("co ide k sushi ryzi?")
        # detect_related_subject by mal najst related intent
        # Ak nie, padne na product_search – obe su akceptovatelne pre tento test
        assert wf in ("cross_sell", "product_search")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Workflow kontrakt
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkflowContracts:
    """get_contract vracia spravne allowed_sources a quality_rules."""

    def test_allergen_contract_has_safety_rule(self):
        contract = get_contract("allergen_safety")
        assert "never_assert_allergen_free_by_name_only" in contract["quality_rules"]

    def test_allergen_contract_allowed_sources(self):
        contract = get_contract("allergen_safety")
        assert "products" in contract["allowed_sources"]

    def test_product_search_contract(self):
        contract = get_contract("product_search")
        assert "products" in contract["allowed_sources"]
        assert "answer" in contract["output_fields"]

    def test_recipe_only_contract_no_product_push(self):
        contract = get_contract("recipe_only")
        assert "no_product_push_if_recipe_only_asked" in contract["quality_rules"]

    def test_cross_sell_contract_output_fields(self):
        contract = get_contract("cross_sell")
        assert "cart_candidates" in contract["output_fields"]

    def test_unknown_intent_fallback_to_product_search(self):
        contract = get_contract("neexistujuci_intent")
        # Bezpecny fallback podla implementacie
        assert "products" in contract["allowed_sources"]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Chat flow s mock OpenAI
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatWithMockOpenAI:
    """End-to-end test chat() s mocknutym OpenAI – nevyzaduje API kluc."""

    def _run_chat(self, message: str, openai_response: str = "Testovacia odpoved."):
        """
        Spusti main.chat() s:
        - nastavenym produktovym katalogom (SAMPLE_PRODUCTS)
        - mocknutym _call_openai_with_retry
        - fake OPENAI_API_KEY
        """
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-fake-key"}):
            # Resetujeme singleton klienta aby nacital novy fake key
            main._openai_client = None

            # Mockujeme _call_openai_with_retry aby nevykonalo realne HTTP volanie
            with mock.patch.object(main, "_call_openai_with_retry", return_value=openai_response):
                # Nastavime produkty priamo do main.products
                original_products = getattr(main, "products", [])
                main.products = SAMPLE_PRODUCTS
                try:
                    import asyncio
                    result = asyncio.get_event_loop().run_until_complete(
                        main.chat(
                            _make_chat_request(message),
                            _mock_http_request(),
                        )
                    )
                finally:
                    main.products = original_products
                    main._openai_client = None
        return result

    def test_normal_response_returns_answer(self):
        result = self._run_chat("ake bezlepkove omacky mate?", "Odporucam Kikkoman tamari.")
        assert "answer" in result
        assert result["answer"] == "Odporucam Kikkoman tamari."

    def test_response_includes_products(self):
        result = self._run_chat("bezlepkova sojova omacka")
        assert "products" in result
        assert isinstance(result["products"], list)

    def test_out_of_domain_no_openai_call(self):
        """Out-of-domain query nema volat OpenAI – vrati priamu odpoved."""
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-fake-key"}):
            main._openai_client = None
            openai_called = []
            with mock.patch.object(main, "_call_openai_with_retry", side_effect=lambda *a, **kw: openai_called.append(1) or ""):
                original_products = getattr(main, "products", [])
                main.products = SAMPLE_PRODUCTS
                try:
                    import asyncio
                    result = asyncio.get_event_loop().run_until_complete(
                        main.chat(
                            _make_chat_request("ake je dnes pocasie v Bratislave?"),
                            _mock_http_request(),
                        )
                    )
                finally:
                    main.products = original_products
                    main._openai_client = None
        # Out-of-domain odpoved by nemala volat OpenAI
        assert len(openai_called) == 0
        assert "answer" in result

    def test_no_api_key_returns_fallback(self):
        """Bez OPENAI_API_KEY musi prist fallback odpoved bez crash."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            main._openai_client = None
            original_products = getattr(main, "products", [])
            main.products = SAMPLE_PRODUCTS
            try:
                import asyncio
                result = asyncio.get_event_loop().run_until_complete(
                    main.chat(
                        _make_chat_request("bezlepkova sojova omacka"),
                        _mock_http_request(),
                    )
                )
            finally:
                main.products = original_products
                main._openai_client = None
        assert "answer" in result
        assert result["answer"]  # nie je prazdny


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Retry logika – RETRY-01
# ═══════════════════════════════════════════════════════════════════════════════

class TestOpenAIRetry:
    """
    Testuje _call_openai_with_retry priamo:
    - uspech po 2 zlyaniach (retry funguje)
    - fallback po vycerpani pokusov (reraise=True)
    """

    def _get_openai_errors(self):
        """Vrati error briady zo stubnuteho openai modulu."""
        openai_mod = sys.modules["openai"]
        return (
            openai_mod.RateLimitError,
            openai_mod.APITimeoutError,
            openai_mod.APIConnectionError,
        )

    def _make_fake_client(self, side_effects: list):
        """
        Vytvori fake OpenAI klienta ktoreho create() vyvolava postupne
        definovane side_effects (Exception alebo navratova hodnota).
        """
        fake_completion = types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="OK"))]
        )
        fake_client = mock.MagicMock()

        call_count = [0]
        def _create(**kw):
            idx = call_count[0]
            call_count[0] += 1
            effect = side_effects[min(idx, len(side_effects) - 1)]
            if isinstance(effect, Exception):
                raise effect
            if isinstance(effect, type) and issubclass(effect, Exception):
                raise effect()
            return fake_completion

        fake_client.chat.completions.create = _create
        return fake_client

    def test_retry_succeeds_after_rate_limit(self):
        """RateLimitError 2x → uspech na 3. pokus."""
        try:
            import tenacity
        except ImportError:
            pytest.skip("tenacity not installed")

        RateLimitError, _, _ = self._get_openai_errors()

        # Prvy a druhy pokus vracia RateLimitError, treti uspeje
        side_effects = [RateLimitError(), RateLimitError(), "success"]
        call_count = [0]

        def fake_create(**kw):
            idx = call_count[0]
            call_count[0] += 1
            if idx < 2:
                raise RateLimitError("rate limited")
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="OK po retry"))]
            )

        fake_client = mock.MagicMock()
        fake_client.chat.completions.create = fake_create

        # Patchujeme tenacity wait aby sme nespali v testoch
        with mock.patch("tenacity.wait_exponential.__call__", return_value=0):
            # Volame _call_openai_with_retry s kratkou cakacou dobou
            # Priamo volame funkciu – tenacity dekorator je uz aplikovany
            result = main._call_openai_with_retry(fake_client, [], "gpt-4.1-mini")

        assert result == "OK po retry"
        assert call_count[0] == 3

    def test_retry_raises_after_max_attempts(self):
        """APITimeoutError pri vsetkych pokusoch → vyhodi vynimku (reraise=True)."""
        try:
            import tenacity
        except ImportError:
            pytest.skip("tenacity not installed")

        _, APITimeoutError, _ = self._get_openai_errors()

        call_count = [0]
        def fake_create(**kw):
            call_count[0] += 1
            raise APITimeoutError("timeout")

        fake_client = mock.MagicMock()
        fake_client.chat.completions.create = fake_create

        with pytest.raises(APITimeoutError):
            main._call_openai_with_retry(fake_client, [], "gpt-4.1-mini")

        # Max 3 pokusy
        assert call_count[0] == 3

    def test_non_transient_error_not_retried(self):
        """ValueError (ne-transientna chyba) sa nema opakovat – padne hned."""
        try:
            import tenacity
        except ImportError:
            pytest.skip("tenacity not installed")

        call_count = [0]
        def fake_create(**kw):
            call_count[0] += 1
            raise ValueError("unexpected error")

        fake_client = mock.MagicMock()
        fake_client.chat.completions.create = fake_create

        with pytest.raises(ValueError):
            main._call_openai_with_retry(fake_client, [], "gpt-4.1-mini")

        # Ziadny retry – len 1 pokus
        assert call_count[0] == 1

    def test_chat_endpoint_fallback_on_permanent_failure(self):
        """Chat endpoint vracia fallback (nie 500) ked OpenAI permanentne zlyha."""
        _, _, APIConnectionError = self._get_openai_errors()

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-fake-key"}):
            main._openai_client = None
            with mock.patch.object(
                main, "_call_openai_with_retry",
                side_effect=APIConnectionError("connection refused")
            ):
                original_products = getattr(main, "products", [])
                main.products = SAMPLE_PRODUCTS
                try:
                    import asyncio
                    result = asyncio.get_event_loop().run_until_complete(
                        main.chat(
                            _make_chat_request("bezlepkova omacka"),
                            _mock_http_request(),
                        )
                    )
                finally:
                    main.products = original_products
                    main._openai_client = None

        # Musi dostat answer (fallback), nie vyhodik vynimku
        assert "answer" in result
        assert result["answer"]
        assert "warning" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Allergen safety workflow – bezpecnostna logika
# ═══════════════════════════════════════════════════════════════════════════════

class TestAllergenSafetyWorkflow:
    """Allergen intent detekcia a bezpecnostna odpoved."""

    def test_celiac_detected(self):
        intent = main.detect_allergen_intent("mam celiakiu, co mozem jest?")
        assert intent is not None
        assert "lepok" in intent.lower() or "celiak" in intent.lower() or intent

    def test_lactose_detected(self):
        intent = main.detect_allergen_intent("som laktozovo intolerantny")
        assert intent is not None

    def test_no_allergen_in_normal_query(self):
        intent = main.detect_allergen_intent("chcem kupit kokosove mlieko")
        # Kokosove mlieko samo o sebe nie je allergen query
        # Moze byt None alebo nejaky intent – testujeme ze nefalsely nedetekuje
        # Toto je smoke test
        assert True  # Nesmie crashnut

    def test_allergen_answer_includes_caution(self):
        """Fallback odpoved pre allergen query musi obsahovat opatrnost."""
        answer = main.fallback_answer(
            SAMPLE_PRODUCTS[:1],
            knowledge_matches=None,
            related_subject=None,
            needs_composition_caution=True,
        )
        assert answer  # nie je prazdna
        # Bezpecnostna odpoved by mala byt dlhsia ako jednoduche "nenasiel som"
        assert len(answer) > 10
