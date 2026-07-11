from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_ROOT_FILES = {
    "search.py",
    "knowledge.py",
    "widget.js",
    "widget.html",
    "import_feed.py",
    "main (2).py",
    "download",
    "download (1)",
    "env.example",
    "knowledge.json",
    "__init__.py",
    "cross_sell_rules.py",
    "download (2)",
    "feed.py",
    "golden_tests.py",
    "import_knowledge.py",
    "main (1).py",
    "product_graph.py",
    "products.json",
    "question_analytics.jsonl",
    "recipe_ingredients.json",
    "recipe_ingredients.py",
    "UPLOAD_STRUCTURE.txt",
    "validators.py",
    "workflows.py",
}

FORBIDDEN_PACKAGE_FILES = {
    "data/question_analytics.jsonl",
    "data/backend_errors.jsonl",
}

MOJIBAKE_MARKERS = (
    "\u0102",
    "\u0139",
    "\u00c4",
    "\u00c2",
    "\ufffd",
)
TEXT_SUFFIXES = {".py", ".js", ".html", ".md", ".toml", ".json", ".txt", ".example"}
SKIP_DIRS = {"outputs", ".runtime-check-deps", ".runtime-check-venv"}


def main() -> int:
    errors: list[str] = []

    for name in sorted(FORBIDDEN_ROOT_FILES):
        if (ROOT / name).exists():
            errors.append(f"Forbidden root drift file exists: {name}")

    for name in sorted(FORBIDDEN_PACKAGE_FILES):
        if (ROOT / name).exists():
            errors.append(f"Generated runtime file should not be packaged: {name}")

    for required in [
        "app/main.py",
        "app/search.py",
        "app/knowledge.py",
        "app/feed.py",
        "app/widget.js",
        "app/widget.html",
        "data/products.json",
        "data/knowledge.json",
        "requirements.txt",
        "Procfile",
        "railway.json",
        "pyproject.toml",
        ".env.example",
    ]:
        if not (ROOT / required).exists():
            errors.append(f"Missing deployment file: {required}")

    for path in ROOT.rglob("*"):
        if "__pycache__" in path.parts or any(part in SKIP_DIRS for part in path.parts) or not path.is_file():
            continue
        if path.suffix not in TEXT_SUFFIXES and path.name != "Procfile":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append(f"Text file is not valid UTF-8: {path.relative_to(ROOT)}")
            continue
        if any(marker in text for marker in MOJIBAKE_MARKERS):
            errors.append(f"Possible mojibake in: {path.relative_to(ROOT)}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print("Deployment check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
