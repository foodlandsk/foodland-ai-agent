from __future__ import annotations

import argparse
import csv
import json
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def normalized(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.casefold().replace("-", " ").replace("/", " ").split())


def contains_any(text: str, terms: list[str]) -> bool:
    haystack = normalized(text)
    return any(normalized(term) in haystack for term in terms)


def post_chat(base_url: str, message: str, limit: int, timeout: int) -> tuple[int, dict[str, Any]]:
    payload = json.dumps({"message": message, "limit": limit}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat",
        data=payload,
        method="POST",
        headers={"content-type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {"error": body}
        return exc.code, data


def evaluate(case: dict[str, Any], status: int, result: dict[str, Any]) -> tuple[bool, list[str]]:
    issues: list[str] = []
    products = result.get("products") or []
    titles = " | ".join(str(product.get("title", "")) for product in products)
    answer = str(result.get("answer", ""))
    intent = str(result.get("intent", ""))

    if status != 200:
        issues.append(f"status:{status}")
        return False, issues

    expected_intent = case.get("expected_intent")
    if expected_intent and intent != expected_intent:
        if not (expected_intent == "product_search" and intent in {"product_search", "related_products"}):
            issues.append(f"intent:{intent}!={expected_intent}")

    expected_count = case.get("expected_products_count")
    if expected_count is not None and len(products) != int(expected_count):
        issues.append(f"products_count:{len(products)}!={expected_count}")

    expected_products = case.get("expected_products_include") or []
    if expected_products and not contains_any(titles, expected_products):
        issues.append("missing_expected_product")

    must_not_include = case.get("must_not_include_products") or []
    if must_not_include and contains_any(titles, must_not_include):
        issues.append("must_not_include_product")

    must_not_start = case.get("must_not_start_with") or case.get("must_not_prioritize") or []
    first_titles = " | ".join(str(product.get("title", "")) for product in products[:3])
    if must_not_start and contains_any(first_titles, must_not_start):
        issues.append("forbidden_prioritized")

    expected_answer = case.get("expected_answer_include") or []
    if expected_answer and not contains_any(answer, expected_answer):
        issues.append("missing_expected_answer")

    return not issues, issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://foodland-ai-agent-production.up.railway.app")
    parser.add_argument("--cases", default="tests/regression_training_cases.jsonl")
    parser.add_argument("--report", default="outputs/live_regression_report.csv")
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.25)
    args = parser.parse_args()

    cases = [
        json.loads(line)
        for line in (ROOT / args.cases).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows: list[dict[str, Any]] = []
    passed = 0

    for index, case in enumerate(cases, 1):
        status, result = post_chat(args.base_url, case["query"], args.limit, args.timeout)
        ok, issues = evaluate(case, status, result)
        passed += int(ok)
        products = result.get("products") or []
        rows.append(
            {
                "id": case.get("id", ""),
                "ok": ok,
                "issues": ";".join(issues),
                "status": status,
                "query": case.get("query", ""),
                "expected_intent": case.get("expected_intent", ""),
                "actual_intent": result.get("intent", ""),
                "answer": str(result.get("answer", "")).replace("\r", " ").replace("\n", " "),
                "top_products": " | ".join(str(product.get("title", "")) for product in products[:6]),
            }
        )
        if index < len(cases) and args.delay:
            time.sleep(args.delay)

    report_path = ROOT / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "cases": len(cases),
        "passed": passed,
        "failed": len(cases) - passed,
        "pass_rate": round(passed / len(cases) * 100, 2) if cases else 0,
        "report": str(report_path),
        "first_failures": [row for row in rows if not row["ok"]][:10],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
