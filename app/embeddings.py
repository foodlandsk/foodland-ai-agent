"""Product embeddings for semantic search.

Deliberately not a hosted vector database: brute-force cosine similarity
over a few thousand product vectors is fast enough in pure Python, so
embeddings are generated once via the OpenAI embeddings API, cached as a
plain JSON file, and compared in memory - no new paid service or
infrastructure dependency.

The OpenAI client is always passed in rather than constructed here, so
these functions stay trivially testable with a fake client.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path

from app.search import product_value

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDINGS_PATH = os.getenv(
    "PRODUCT_EMBEDDINGS_PATH",
    str(Path(tempfile.gettempdir()) / "foodland-ai-agent" / "product_embeddings.json"),
)
_MAX_TEXT_CHARS = 800
_DEFAULT_BATCH_SIZE = 100


def product_embedding_text(product) -> str:
    title = str(product_value(product, "title", ""))
    brand = str(product_value(product, "brand", ""))
    category = str(product_value(product, "product_type", product_value(product, "category", "")))
    description = str(product_value(product, "description", ""))
    text = f"{title}. Znacka: {brand}. Kategoria: {category}. {description}"
    return text[:_MAX_TEXT_CHARS]


def embed_texts(client, texts: list[str], model: str = EMBEDDING_MODEL) -> list[list[float]]:
    if not texts:
        return []
    response = client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in response.data]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def build_product_embeddings(
    client,
    products: list,
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> dict[str, list[float]]:
    embeddings: dict[str, list[float]] = {}
    batch_ids: list[str] = []
    batch_texts: list[str] = []

    def flush() -> None:
        if not batch_texts:
            return
        vectors = embed_texts(client, batch_texts)
        for product_id, vector in zip(batch_ids, vectors):
            embeddings[product_id] = vector
        batch_ids.clear()
        batch_texts.clear()

    for product in products:
        product_id = str(product_value(product, "id", ""))
        if not product_id:
            continue
        batch_ids.append(product_id)
        batch_texts.append(product_embedding_text(product))
        if len(batch_texts) >= batch_size:
            flush()
    flush()
    return embeddings


def save_embeddings(embeddings: dict[str, list[float]], path: str | None = None) -> None:
    resolved_path = Path(path or EMBEDDINGS_PATH)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    with resolved_path.open("w", encoding="utf-8") as f:
        json.dump({"model": EMBEDDING_MODEL, "embeddings": embeddings}, f)


def load_embeddings(path: str | None = None) -> dict[str, list[float]]:
    resolved_path = Path(path or EMBEDDINGS_PATH)
    try:
        with resolved_path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data.get("embeddings", {})


def semantic_search(
    client,
    query: str,
    product_embeddings: dict[str, list[float]],
    limit: int = 8,
    model: str = EMBEDDING_MODEL,
) -> list[tuple[str, float]]:
    if not query.strip() or not product_embeddings:
        return []
    query_vectors = embed_texts(client, [query], model)
    if not query_vectors:
        return []
    query_vector = query_vectors[0]
    scored = [
        (product_id, cosine_similarity(query_vector, vector))
        for product_id, vector in product_embeddings.items()
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:limit]
