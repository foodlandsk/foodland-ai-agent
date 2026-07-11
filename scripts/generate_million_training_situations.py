from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]


def text(value: Any) -> str:
    return str(value or "").strip()


def first_value(record: dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = text(record.get(key))
        if value:
            return value
    return ""


def compact_category(product_type: str) -> str:
    parts = [part.strip() for part in product_type.split(">") if part.strip()]
    return parts[-1] if parts else product_type


def product_price(product: dict[str, Any]) -> float | None:
    sale_price = product.get("sale_price")
    price = product.get("price")
    return sale_price if sale_price is not None else price


def product_terms(product: dict[str, Any]) -> list[str]:
    terms = [
        text(product.get("title")),
        text(product.get("brand")),
        compact_category(text(product.get("product_type"))),
    ]
    return [term for term in terms if term]


def load_data() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    products = json.loads((ROOT / "data" / "products.json").read_text(encoding="utf-8"))
    knowledge = json.loads((ROOT / "data" / "knowledge.json").read_text(encoding="utf-8"))
    return products, knowledge


def case(case_id: int, query: str, expected_intent: str, source: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": f"MIL{case_id:07d}",
        "source": source,
        "query": query,
        "expected_intent": expected_intent,
        **extra,
    }


def product_search_cases(products: list[dict[str, Any]]) -> Iterable[tuple[str, dict[str, Any]]]:
    templates = [
        "máte {title}?",
        "hľadám {title}",
        "chcem kúpiť {title}",
        "ukážte mi {title}",
        "predávate {title}?",
        "je skladom {title}?",
        "koľko stojí {title}?",
        "potrebujem {title}, nie náhodnú alternatívu",
        "máte produkt od značky {brand}?",
        "čo máte v kategórii {category}?",
        "hľadám {category} od {brand}",
        "nájdite mi {title} za dobrú cenu",
    ]
    prefixes = ["", "prosím ", "dobrý deň, ", "som náročný zákazník, ", "nechcem omyl, "]
    for product in products:
        title = text(product.get("title"))
        brand = text(product.get("brand")) or "Foodland"
        category = compact_category(text(product.get("product_type")))
        expected = [title]
        for template in templates:
            for prefix in prefixes:
                query = prefix + template.format(title=title, brand=brand, category=category)
                yield query, {
                    "expected_intent": "product_search",
                    "expected_products_include": expected,
                    "product_id": product.get("id"),
                    "risk": "product_lookup_precision",
                }


def related_cases(knowledge: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any]]]:
    cross_sell = knowledge.get("sections", {}).get("CrossSell", [])
    alternatives = knowledge.get("sections", {}).get("Alternatives", [])

    related_templates = [
        "čo sa hodí k {product}?",
        "čo kúpiť k {product}?",
        "súvisiace produkty k {product}",
        "doplnky k {product}",
        "čo odporúčate k {product}, ale presne?",
        "ak kupujem {product}, čo ešte potrebujem?",
    ]
    for record in cross_sell:
        product = first_value(record, ["Produkt"])
        expected = [text(record.get(f"Cross-sell {index}")) for index in range(1, 6)]
        expected = [item for item in expected if item]
        if not product or not expected:
            continue
        for template in related_templates:
            yield template.format(product=product), {
                "expected_intent": "related_products",
                "expected_products_include": expected[:5],
                "source_section": "CrossSell",
                "risk": "bad_related_recommendation",
            }

    alternative_templates = [
        "nemáte {product}, čo je dobrá alternatíva?",
        "náhrada za {product}",
        "podobný produkt ako {product}",
        "čo namiesto {product}?",
    ]
    for record in alternatives:
        product = first_value(record, ["Produkt"])
        expected = [text(record.get(f"Alternativa {index}")) for index in range(1, 6)]
        expected = [item for item in expected if item]
        if not product or not expected:
            continue
        for template in alternative_templates:
            yield template.format(product=product), {
                "expected_intent": "alternative_products",
                "expected_products_include": expected[:5],
                "source_section": "Alternatives",
                "risk": "bad_alternative",
            }


def faq_cases(knowledge: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any]]]:
    templates = [
        "{question}",
        "prosím, {question}",
        "odpovedzte presne: {question}",
        "neukazujte produkty, len FAQ: {question}",
        "som prísny zákazník, {question}",
    ]
    for record in knowledge.get("sections", {}).get("FAQ", []):
        question = first_value(record, ["Otázka", "Otazka", "question"])
        answer = first_value(record, ["Odpoveď", "Odpoved", "answer"])
        category = first_value(record, ["Kategória", "Kategoria", "category"])
        if not question:
            continue
        answer_terms = [part for part in answer.replace(".", " ").split() if len(part) >= 4][:4]
        for template in templates:
            yield template.format(question=question), {
                "expected_intent": "faq",
                "expected_products_count": 0,
                "expected_answer_include": answer_terms,
                "source_section": "FAQ",
                "faq_category": category,
                "risk": "faq_product_leakage",
            }


def products_ai_cases(knowledge: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any]]]:
    templates = [
        "čo je {name}?",
        "na čo sa používa {name}?",
        "ako chutí {name}?",
        "poradíte mi s produktom {name}?",
        "je {name} vhodné pre ázijské varenie?",
        "som začiatočník, vysvetlite {name}",
        "nechcem marketing, prakticky: {name}",
    ]
    for record in knowledge.get("sections", {}).get("Products_AI", []):
        name = first_value(record, ["product_name"])
        if not name:
            continue
        expected = [name] + [part.strip() for part in text(record.get("synonyms")).split(",") if part.strip()][:3]
        answer_terms = [
            value
            for value in [record.get("usage"), record.get("taste"), record.get("advisor_note")]
            if text(value)
        ][:2]
        for template in templates:
            yield template.format(name=name), {
                "expected_intent": "product_advice",
                "expected_products_include": expected,
                "expected_answer_include": answer_terms,
                "source_section": "Products_AI",
                "risk": "knowledge_grounding",
            }


def recipe_and_magazine_cases(knowledge: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any]]]:
    recipe_templates = [
        "máte recept na {name}?",
        "ako pripraviť {name}?",
        "čo potrebujem na recept {name}?",
        "vysvetlite postup pre {name}",
    ]
    for record in knowledge.get("sections", {}).get("Recipes", []):
        name = first_value(record, ["Recept (SK názov)", "Recept (SK nazov)"])
        cuisine = first_value(record, ["Kuchyňa", "Kuchyna"])
        if not name:
            continue
        for template in recipe_templates:
            yield template.format(name=name), {
                "expected_intent": "recipe",
                "expected_answer_include": [name],
                "source_section": "Recipes",
                "cuisine": cuisine,
                "risk": "recipe_grounding",
            }

    magazine_templates = [
        "čo viete o téme {topic}?",
        "máte článok k téme {topic}?",
        "poradca k téme {topic}",
    ]
    for record in knowledge.get("sections", {}).get("Magazine", []):
        topic = first_value(record, ["Téma", "Tema"])
        article = first_value(record, ["Článok (SK názov)", "Clanok (SK nazov)"])
        subject = topic or article
        if not subject:
            continue
        for template in magazine_templates:
            yield template.format(topic=subject), {
                "expected_intent": "knowledge_answer",
                "expected_answer_include": [subject],
                "source_section": "Magazine",
                "risk": "knowledge_grounding",
            }


def allergen_and_diet_cases(products: list[dict[str, Any]]) -> Iterable[tuple[str, dict[str, Any]]]:
    templates = [
        "je {title} bez lepku?",
        "obsahuje {title} sóju?",
        "môže {title} jesť alergik na arašidy?",
        "je {title} vegan?",
        "má {title} alergény?",
        "mám intoleranciu, čo skontrolovať pri {title}?",
        "je {title} vhodné pri celiakii?",
        "nechcem vymyslenú odpoveď, overte zloženie pri {title}",
    ]
    for product in products:
        title = text(product.get("title"))
        if not title:
            continue
        for template in templates:
            intent = "dietary_filter" if "vegan" in template else "allergen_safety"
            yield template.format(title=title), {
                "expected_intent": intent,
                "expected_products_include": [title],
                "expected_answer_include": ["overte", "zloženie", "detail"],
                "product_id": product.get("id"),
                "must_not_invent": True,
                "risk": "allergen_hallucination",
            }


def strict_customer_cases() -> Iterable[tuple[str, dict[str, Any]]]:
    base = [
        ("Nejem európsky chlieb, chcem ryžovú alternatívu.", "product_search", ["ryžový papier", "ryžové rezance"]),
        ("Nechcem smotanu, chcem kokosové mlieko.", "product_search", ["kokosové mlieko"]),
        ("Chcem k sushi všetko potrebné, nie náhodné produkty.", "related_products", ["sushi ryža", "nori", "wasabi"]),
        ("Som celiak, čo bezpečné k sushi?", "dietary_filter", ["tamari", "bezlepková sójová omáčka"]),
        ("Nechcem kyslú kapustu, chcem kimchi.", "product_search", ["kimchi"]),
        ("Nechcem horčicu, chcem wasabi.", "product_search", ["wasabi"]),
        ("Chcem fish sauce po slovensky.", "product_search", ["rybacia omáčka"]),
        ("Chcem sesame oil, nie olivový olej.", "product_search", ["sezamový olej"]),
        ("Chcem rice paper na rolky.", "product_search", ["ryžový papier"]),
        ("Chcem gochudžang, opravte preklep.", "product_search", ["gochujang"]),
    ]
    suffixes = [
        "",
        " Som prísny zákazník.",
        " Nechcem marketing.",
        " Nevracajte náhodné výsledky.",
        " Mám problém s európskou stravou.",
    ]
    for query, intent, expected in base:
        for suffix in suffixes:
            yield query + suffix, {
                "expected_intent": intent,
                "expected_products_include": expected,
                "must_not_invent": True,
                "risk": "strict_european_diet_conflict",
            }


def unknown_cases() -> Iterable[tuple[str, dict[str, Any]]]:
    queries = [
        "predávate notebooky?",
        "viete mi vybaviť letenku?",
        "aké bude zajtra počasie?",
        "napíšte mi báseň",
        "spravíte mi daňové priznanie?",
        "opravujete telefóny?",
        "predávate stavebný materiál?",
        "chcem poistenie auta",
        "máte lieky na predpis?",
        "vypočítajte mi hypotéku",
    ]
    suffixes = ["", " Nehľadajte náhodné potraviny.", " Ak neviete, povedzte limit.", " Bez vymýšľania."]
    for query in queries:
        for suffix in suffixes:
            yield query + suffix, {
                "expected_intent": "unknown",
                "expected_products_count": 0,
                "must_not_invent": True,
                "risk": "out_of_domain_hallucination",
            }


def all_generators(products: list[dict[str, Any]], knowledge: dict[str, Any]) -> list[tuple[str, Iterable[tuple[str, dict[str, Any]]]]]:
    return [
        ("knowledge_faq", faq_cases(knowledge)),
        ("knowledge_products_ai", products_ai_cases(knowledge)),
        ("knowledge_recipes_magazine", recipe_and_magazine_cases(knowledge)),
        ("knowledge_cross_sell_alternatives", related_cases(knowledge)),
        ("product_search_all_products", product_search_cases(products)),
        ("allergen_and_diet_all_products", allergen_and_diet_cases(products)),
        ("strict_customer", strict_customer_cases()),
        ("unknown", unknown_cases()),
    ]


def write_sharded_cases(args: argparse.Namespace) -> dict[str, Any]:
    products, knowledge = load_data()
    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    streams = []
    for source, generator in all_generators(products, knowledge):
        generated = list(generator)
        if args.shuffle_source:
            rng.shuffle(generated)
        streams.append((source, generated))

    source_counts = {source: len(items) for source, items in streams}
    total_available_cycle = sum(source_counts.values())
    if total_available_cycle == 0:
        raise RuntimeError("No cases available.")

    shard_index = 1
    written = 0
    case_id = 1
    current_file = None
    current_path = None
    shard_paths: list[str] = []

    def open_shard(index: int):
        path = out_dir / f"situations_{index:04d}.jsonl"
        shard_paths.append(str(path.relative_to(ROOT)))
        return path, path.open("w", encoding="utf-8", newline="\n")

    current_path, current_file = open_shard(shard_index)
    try:
        positions = {source: 0 for source, _ in streams}
        while written < args.count:
            for source, items in streams:
                if written >= args.count:
                    break
                pos = positions[source] % len(items)
                positions[source] += 1
                query, payload = items[pos]
                payload_copy = dict(payload)
                record = case(case_id, query, payload_copy.pop("expected_intent"), source, **payload_copy)
                record["cycle"] = positions[source] // len(items)
                current_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1
                case_id += 1

                if written < args.count and written % args.shard_size == 0:
                    current_file.close()
                    shard_index += 1
                    current_path, current_file = open_shard(shard_index)
    finally:
        if current_file and not current_file.closed:
            current_file.close()

    manifest = {
        "count": written,
        "seed": args.seed,
        "shard_size": args.shard_size,
        "shards": shard_paths,
        "source_available_counts": source_counts,
        "notes": [
            "Synthetic training/evaluation data grounded in data/products.json and data/knowledge.json.",
            "Do not package full million-row outputs into Railway deployment ZIP.",
            "Regenerate with scripts/generate_million_training_situations.py for deterministic output.",
        ],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=1_000_000)
    parser.add_argument("--shard-size", type=int, default=50_000)
    parser.add_argument("--out", default="outputs/synthetic_training_1m")
    parser.add_argument("--seed", type=int, default=20260711)
    parser.add_argument("--shuffle-source", action="store_true")
    args = parser.parse_args()

    manifest = write_sharded_cases(args)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
