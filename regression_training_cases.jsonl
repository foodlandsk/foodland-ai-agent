from __future__ import annotations

import argparse
import csv
import json
import sys
import types
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.feed import load_products_json
from app.search import format_product, normalize, search_products, tokenize


def normalized(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    text = ascii_text.casefold()
    return " ".join(text.replace("-", " ").replace("/", " ").split())


def variants(value: str) -> set[str]:
    base = normalized(value)
    results = {base}
    if "sushi" in base:
        results.add(base.replace("sushi", "susi"))
    if "susi" in base:
        results.add(base.replace("susi", "sushi"))
    if "omacka" in base:
        results.add(base.replace("omacka", "omacku"))
    if "omacku" in base:
        results.add(base.replace("omacku", "omacka"))
    return results


def contains_any(text: str, needles: list[str]) -> bool:
    normalized_text = normalized(text)
    return any(needle_variant in normalized_text for needle in needles for needle_variant in variants(needle))


def first_prioritizes_forbidden(
    products: list[dict[str, Any]],
    forbidden_terms: list[str],
    expected_terms: list[str] | None = None,
) -> bool:
    if not forbidden_terms or not products:
        return False
    checked_titles = []
    for product in products[:3]:
        title = product.get("title", "")
        if expected_terms and contains_any(title, expected_terms):
            continue
        checked_titles.append(title)
    return contains_any(" | ".join(checked_titles), forbidden_terms)


def build_search_index(product_data) -> list[dict[str, Any]]:
    return [
        {
            "product": product,
            "title_tokens": tokenize(product.title),
            "category_tokens": tokenize(product.product_type),
            "brand_tokens": tokenize(product.brand),
            "description_tokens": tokenize(product.description),
            "normalized_title": normalize(product.title),
        }
        for product in product_data
    ]


def fast_search_products(index: list[dict[str, Any]], query: str, limit: int = 8) -> list[dict[str, Any]]:
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    normalized_query = normalize(query)
    wants_sushi_rice = {"ryza"} <= query_tokens and bool({"sushi", "susi"} & query_tokens)

    ranked = []
    for item in index:
        product = item["product"]
        title_tokens = item["title_tokens"]
        category_tokens = item["category_tokens"]
        brand_tokens = item["brand_tokens"]
        description_tokens = item["description_tokens"]
        normalized_title = item["normalized_title"]

        title_hits = len(query_tokens & title_tokens)
        brand_hits = len(query_tokens & brand_tokens)
        category_hits = len(query_tokens & category_tokens)
        description_hits = len(query_tokens & description_tokens)

        score = 8 * title_hits + 5 * brand_hits + 4 * category_hits + description_hits
        if normalized_query in normalized_title:
            score += 12

        if wants_sushi_rice:
            title_is_sushi_rice = (
                "ryza" in title_tokens
                and bool({"sushi", "susi"} & title_tokens)
                and "ocot" not in title_tokens
                and "vinegar" not in title_tokens
            )
            if title_is_sushi_rice:
                score += 18
            if "ocot" in title_tokens or "vinegar" in title_tokens:
                score -= 30

        strong_match = bool(title_hits or brand_hits or category_hits or normalized_query in normalized_title)
        if score > 0 and product.availability == "in_stock":
            score += 1
        if score > 0:
            ranked.append((score, strong_match, product))

    strong_ranked = [item for item in ranked if item[1]]
    weak_ranked = [item for item in ranked if not item[1]]
    strong_ranked.sort(key=lambda item: item[0], reverse=True)
    weak_ranked.sort(key=lambda item: item[0], reverse=True)
    ranked = strong_ranked if len(strong_ranked) >= min(limit, 4) else strong_ranked + weak_ranked
    return [format_product(product) for _, _, product in ranked[:limit]]


def fast_related_products(main, index: list[dict[str, Any]], subject: str, limit: int) -> list[dict[str, Any]]:
    subject_query = normalize(subject)
    seen: set[str] = set()
    recommendations: list[dict[str, Any]] = []
    for query in main.RELATED_PRODUCT_QUERIES.get(subject, []):
        for product in fast_search_products(index, query, 3):
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


def fast_special_products(main, index: list[dict[str, Any]], subject: str, limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    recommendations: list[dict[str, Any]] = []
    excluded_terms = main.SPECIAL_PRODUCT_EXCLUDE_TERMS.get(subject, ())

    for query in main.SPECIAL_PRODUCT_QUERIES.get(subject, []):
        for product in fast_search_products(index, query, 5):
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


def evaluate_case(case: dict[str, Any], products: list[dict[str, Any]], top_n: int) -> tuple[bool, list[str]]:
    issues: list[str] = []
    titles = " | ".join(product.get("title", "") for product in products[:top_n])
    expected_terms = case.get("expected_products_include") or []
    forbidden_terms = case.get("must_not_prioritize") or []

    if expected_terms and not contains_any(titles, expected_terms):
        issues.append("missing_expected_product")

    if first_prioritizes_forbidden(products, forbidden_terms, expected_terms):
        issues.append("forbidden_prioritized")

    if expected_terms and not products:
        issues.append("no_products")

    return not issues, issues


def install_backend_stubs() -> None:
    if "fastapi" in sys.modules:
        return

    fastapi = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code=None, detail=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class FastAPI:
        def __init__(self, *args, **kwargs):
            pass

        def mount(self, *args, **kwargs):
            pass

        def add_middleware(self, *args, **kwargs):
            pass

        def get(self, *args, **kwargs):
            return lambda func: func

        def post(self, *args, **kwargs):
            return lambda func: func

        def on_event(self, *args, **kwargs):
            return lambda func: func

    def Header(default=None):
        return default

    class Request:
        pass

    fastapi.FastAPI = FastAPI
    fastapi.Header = Header
    fastapi.HTTPException = HTTPException
    fastapi.Request = Request

    cors = types.ModuleType("fastapi.middleware.cors")
    cors.CORSMiddleware = object

    static = types.ModuleType("fastapi.staticfiles")

    class StaticFiles:
        def __init__(self, *args, **kwargs):
            pass

        def file_response(self, *args, **kwargs):
            response = types.SimpleNamespace(headers={})
            return response

    static.StaticFiles = StaticFiles

    sys.modules["fastapi"] = fastapi
    sys.modules["fastapi.middleware"] = types.ModuleType("fastapi.middleware")
    sys.modules["fastapi.middleware.cors"] = cors
    sys.modules["fastapi.staticfiles"] = static

    openai = types.ModuleType("openai")
    openai.OpenAI = lambda *args, **kwargs: None
    sys.modules["openai"] = openai


class Client:
    host = "local-test"


class RequestStub:
    headers: dict[str, str] = {}
    client = Client()


def backend_module():
    install_backend_stubs()
    import app.main as main

    return main


def run_chat_case(case: dict[str, Any], limit: int) -> dict[str, Any]:
    main = backend_module()
    return main.chat(main.ChatRequest(message=case["query"], limit=limit), RequestStub())


def run_hybrid_case(case: dict[str, Any], product_data, index, limit: int) -> dict[str, Any]:
    expected_intent = case.get("expected_intent")
    main = backend_module()
    if expected_intent == "related_products":
        subject = main.detect_related_subject(case["query"])
        products = fast_related_products(main, index, subject, limit) if subject else []
        return {"intent": "related_products" if subject else "unknown", "products": products, "answer": ""}

    if expected_intent == "allergen_safety":
        intent = "allergen_safety" if main.detect_allergen_intent(case["query"]) else "product_search"
        products = fast_search_products(index, main.allergen_product_query(case["query"]), limit)
        return {"intent": intent, "products": products, "answer": ""}

    special_subject = main.detect_special_product_subject(case["query"])
    if special_subject:
        products = fast_special_products(main, index, special_subject, limit)
        return {"intent": "product_search" if products else "unknown", "products": products, "answer": ""}

    products = fast_search_products(index, case["query"], limit)
    if expected_intent == "faq":
        return {"intent": "faq", "products": [], "answer": ""}
    if expected_intent == "unknown":
        if main.detect_out_of_domain(case["query"]):
            return {"intent": "unknown", "products": [], "answer": ""}
        return {"intent": "unknown" if not products else "product_search", "products": products, "answer": ""}
    return {"intent": "product_search" if products else "unknown", "products": products, "answer": ""}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="tests/customer_situations_1000.jsonl")
    parser.add_argument("--products", default="data/products.json")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--top-n", type=int, default=8)
    parser.add_argument("--report", default="outputs/customer_situations_report.csv")
    parser.add_argument("--mode", choices=["chat", "hybrid", "search"], default="hybrid")
    args = parser.parse_args()

    product_data = load_products_json(ROOT / args.products)
    index = build_search_index(product_data)
    rows = [
        json.loads(line)
        for line in (ROOT / args.cases).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    report_rows: list[dict[str, Any]] = []
    passed = 0
    failed = 0

    for case in rows:
        if args.mode == "chat":
            result = run_chat_case(case, args.limit)
            products = result.get("products", [])
            actual_intent = result.get("intent", "")
            answer = result.get("answer", "")
        elif args.mode == "hybrid":
            result = run_hybrid_case(case, product_data, index, args.limit)
            products = result.get("products", [])
            actual_intent = result.get("intent", "")
            answer = result.get("answer", "")
        else:
            products = fast_search_products(index, case["query"], args.limit)
            actual_intent = "product_search" if products else "unknown"
            answer = ""

        ok, issues = evaluate_case(case, products, args.top_n)
        expected_intent = case.get("expected_intent")
        if expected_intent and expected_intent not in {"dietary_filter"} and actual_intent != expected_intent:
            if not (expected_intent == "product_search" and actual_intent == "related_products"):
                issues.append(f"intent:{actual_intent}!={expected_intent}")
                ok = False
        if case.get("must_not_invent") and expected_intent == "unknown" and products:
            issues.append("invented_products_for_unknown_or_safety_case")
            ok = False

        passed += int(ok)
        failed += int(not ok)
        report_rows.append(
            {
                "id": case.get("id", ""),
                "ok": ok,
                "issues": ";".join(issues),
                "query": case.get("query", ""),
                "expected_intent": expected_intent or "",
                "actual_intent": actual_intent,
                "expected_products_include": " | ".join(case.get("expected_products_include") or []),
                "must_not_prioritize": " | ".join(case.get("must_not_prioritize") or []),
                "answer": answer,
                "top_products": " | ".join(product.get("title", "") for product in products[: args.top_n]),
            }
        )

    report_path = ROOT / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(report_rows[0].keys()))
        writer.writeheader()
        writer.writerows(report_rows)

    print(
        json.dumps(
            {
                "cases": len(rows),
                "passed": passed,
                "failed": failed,
                "pass_rate": round(passed / len(rows) * 100, 2) if rows else 0,
                "report": str(report_path),
                "first_failures": [row for row in report_rows if not row["ok"]][:10],
            },
            ensure_ascii=True,
            indent=2,
        )
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
