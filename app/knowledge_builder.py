"""
app/knowledge_builder.py
========================
Auto-generates Foodland knowledge from the live product feed.
Called after every feed refresh (every 3 hours by default).

Sections generated automatically:
  Alternatives   – rule-based per-product (same leaf-category, different brand)
  CrossSell      – rule-based per-product (complementary leaf-categories)
  IntentMapping  – rule-based from top categories and brands
  Products_AI    – OpenAI enrichment, only for new / changed products

Sections preserved from base knowledge (manual curation):
  FAQ, Recipes, Magazine
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openai import OpenAI

from app.feed import Product

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cross-sell category map
# Maps a leaf-category name to complementary leaf-category names.
# Products from a complementary category are surfaced as cross-sell suggestions.
# ---------------------------------------------------------------------------
CROSSSELL_MAP: dict[str, list[str]] = {
    "Instantné polievky": [
        "Kuchynské potreby",
        "Omáčky a marinády",
        "Koreniny a ochucovadlá",
        "Ázijské nápoje",
    ],
    "Rezance, niťovky a cestoviny": [
        "Omáčky a marinády",
        "Koreniny a ochucovadlá",
        "Kuchynské potreby",
        "Konzervované produkty",
    ],
    "Ryža": [
        "Sushi ingrediencie",
        "Omáčky a marinády",
        "Koreniny a ochucovadlá",
        "Konzervované produkty",
    ],
    "Sushi ingrediencie": [
        "Ryža",
        "Omáčky a marinády",
        "Kuchynské potreby",
        "Koreniny a ochucovadlá",
    ],
    "Omáčky a marinády": [
        "Ryža",
        "Rezance, niťovky a cestoviny",
        "Konzervované produkty",
        "Koreniny a ochucovadlá",
    ],
    "Koreniny a ochucovadlá": [
        "Omáčky a marinády",
        "Rezance, niťovky a cestoviny",
        "Ryža",
        "Konzervované produkty",
    ],
    "Konzervované produkty": [
        "Ryža",
        "Omáčky a marinády",
        "Rezance, niťovky a cestoviny",
        "Kuchynské potreby",
    ],
    "Kuchynské potreby": [
        "Instantné polievky",
        "Sushi ingrediencie",
        "Ryža",
        "Rezance, niťovky a cestoviny",
    ],
    "Sladkosti a občerstvenie": [
        "Ázijské nápoje",
        "Kokosové produkty",
        "Mochi koláčiky",
    ],
    "Mochi koláčiky": [
        "Ázijské nápoje",
        "Sladkosti a občerstvenie",
        "Kokosové produkty",
    ],
    "Ázijské nápoje": [
        "Sladkosti a občerstvenie",
        "Kokosové produkty",
        "Kuchynské potreby",
    ],
    "Kokosové produkty": [
        "Koreniny a ochucovadlá",
        "Omáčky a marinády",
        "Sladkosti a občerstvenie",
        "Ryža",
    ],
    "Dekorácie a darčeky": [
        "Kuchynské potreby",
        "Ázijské nápoje",
        "Sladkosti a občerstvenie",
    ],
    "Múka, škrob & ryžový papier": [
        "Omáčky a marinády",
        "Koreniny a ochucovadlá",
        "Konzervované produkty",
    ],
    "Balíčky na prípravu jedál": [
        "Rezance, niťovky a cestoviny",
        "Omáčky a marinády",
        "Kuchynské potreby",
    ],
    "Fazuľa a hrach": [
        "Omáčky a marinády",
        "Ryža",
        "Koreniny a ochucovadlá",
    ],
    "Mrazené potraviny": [
        "Omáčky a marinády",
        "Ryža",
        "Koreniny a ochucovadlá",
    ],
    "Mrazené ryby a morské plody": [
        "Omáčky a marinády",
        "Sushi ingrediencie",
        "Ryža",
    ],
}

# ---------------------------------------------------------------------------
# Products_AI OpenAI prompt
# ---------------------------------------------------------------------------
_PRODUCTS_AI_SYSTEM = (
    "Si expert nákupca pre Foodland.sk – špecializovaný azijský obchod. "
    "Tvorba knowledge card pre konkrétny produkt. "
    "Odpovedaj VÝHRADNE platným JSON, bez komentárov, bez markdown obaľovania."
)

_PRODUCTS_AI_USER_TEMPLATE = """\
Produkt na analýzu:
- ID: {id}
- Kategória: {category}
- Cena: {price} {currency}
- Značka: {brand}
- GTIN: {gtin}

Jazykové mutácie názvu a popisu:
{lang_block}

Vygeneruj JSON presne podľa tejto schémy (bez prázdnych hodnôt):
{{
  "Kuchyňa": "<kuchyňa napr. Japonská / Kórejská / Thajská / Vietnamská / Ostatné>",
  "Atribúty": "<čiarkami oddelené atribúty z: Bezlepkové, Vegánske, Vegetariánske, Zdravé, Bio, Pálivé – len tie čo platia>",
  "AI popis – sk": "<1-2 vety praktické SK odporúčanie zákazníkovi>",
  "AI popis – cz": "<1-2 vety CZ preklad/adaptácia>",
  "AI popis – de": "<1-2 vety DE preklad/adaptácia>",
  "AI popis – en": "<1-2 vety EN preklad/adaptácia>",
  "AI popis – hu": "<1-2 vety HU preklad/adaptácia>",
  "AI popis – pl": "<1-2 vety PL preklad/adaptácia>",
  "Cross-sell": "<1 doplnkový produkt s dôvodom, max 15 slov>",
  "Alternatíva": "<1 alternatívny produkt s dôvodom, max 15 slov>",
  "Súvisiaci recept": "<SK názov receptu ak sa hodí, inak prázdny reťazec>",
  "Kucharsky tip - sk": "<praktický tip na prípravu, max 2 vety>",
  "Nakupne odporucanie - sk": "<komu odporučiť a čo pridať do košíka, max 2 vety>",
  "Chutovy profil - sk": "<3-7 slov chuťový profil>",
  "Pouzitie v kuchyni - sk": "<max 5 slov použitie>",
  "Kedy odporucit - sk": "<trigger queries – čo zákazník hľadá, keď tento produkt odporučiť>",
  "Pozor / overit - sk": "<čo zákazník musí overiť pri objednávke, max 2 vety>",
  "Predajny argument - sk": "<1 predajný argument>",
  "Agenticky dalsi krok - sk": "<ďalší krok alebo doplnok do košíka>"
}}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _leaf_category(product_type: str) -> str:
    """Return the last segment of a '>' separated category path."""
    parts = [p.strip() for p in product_type.split(">") if p.strip()]
    return parts[-1] if parts else ""


def _top_category(product_type: str) -> str:
    parts = [p.strip() for p in product_type.split(">") if p.strip()]
    return parts[0] if parts else ""


def _normalize(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower()


def _price_label(product: Product) -> str:
    p = product.effective_price
    if p is None:
        return ""
    return f"{p:.2f} {product.currency}"


def _alt_label(candidate: Product, source: Product) -> str:
    """Human-readable label for an alternative product."""
    parts = [candidate.title]
    leaf = _leaf_category(source.product_type)
    if leaf:
        parts.append(f"– alternativa v kategorii {leaf}")
        if candidate.brand == source.brand:
            parts.append("rovnaka znacka")
        cp = candidate.effective_price
        sp = source.effective_price
        if cp and sp and abs(cp - sp) / max(sp, 0.01) < 0.1:
            parts.append("podobna cena")
    return ", ".join(parts[1:]).replace(", –", " –") if len(parts) > 1 else candidate.title


def _crosssell_label(candidate: Product, reason: str) -> str:
    """Human-readable label for a cross-sell product."""
    return f"{candidate.title} – {reason}"


def _build_category_index(products: list[Product]) -> dict[str, list[Product]]:
    """Index products by leaf category."""
    index: dict[str, list[Product]] = {}
    for p in products:
        leaf = _leaf_category(p.product_type)
        index.setdefault(leaf, []).append(p)
    return index


# ---------------------------------------------------------------------------
# Public: detect changed products (for targeted OpenAI enrichment)
# ---------------------------------------------------------------------------

ProductSnapshot = dict[str, tuple[str, str]]  # {id: (title, price_str)}


def build_product_snapshot(products: list[Product]) -> ProductSnapshot:
    """Create a lightweight snapshot for change detection."""
    return {p.id: (p.title, _price_label(p)) for p in products}


def diff_products(
    old_snapshot: ProductSnapshot,
    new_products: list[Product],
) -> tuple[list[Product], list[str]]:
    """Return (changed_or_new products, removed product IDs)."""
    changed: list[Product] = []
    new_ids = {p.id for p in new_products}

    for p in new_products:
        old = old_snapshot.get(p.id)
        if old is None or old != (p.title, _price_label(p)):
            changed.append(p)

    removed = [pid for pid in old_snapshot if pid not in new_ids]
    return changed, removed
------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def build_alternatives(products: list[Product], max_alts: int = 2) -> list[dict]:
    """Build Alternatives section (rule-based).

    For each product: find *max_alts* products with the same leaf category,
    different brand, closest price.  Falls back to same category regardless
    of brand when fewer alternatives exist.
    """
    cat_index = _build_category_index(products)
    result: list[dict] = []

    for p in products:
        leaf = _leaf_category(p.product_type)
        pool = [c for c in cat_index.get(leaf, []) if c.id != p.id]

        # Prefer different brand first
        diff_brand = [c for c in pool if _normalize(c.brand) != _normalize(p.brand)]
        same_brand = [c for c in pool if _normalize(c.brand) == _normalize(p.brand)]
        ordered = diff_brand + same_brand

        # Sort by price proximity
        ep = p.effective_price or 0.0
        ordered.sort(key=lambda c: abs((c.effective_price or 0.0) - ep))

        alts = ordered[:max_alts]

        entry: dict[str, Any] = {
            "ID": p.id,
            "Produkt": p.title,
            "Cena": _price_label(p),
            "Kategoria": leaf,
            "Produkt_url": p.link,
        }
        for i, alt in enumerate(alts, start=1):
            entry[f"Alternativa {i}"] = _alt_label(alt, p)
            entry[f"Alternativa {i}_url"] = alt.link

        result.append(entry)

    return result


def build_crosssell(products: list[Product], max_cs: int = 5) -> list[dict]:
    """Build CrossSell section (rule-based).

    For each product: find *max_cs* products from complementary categories
    defined in CROSSSELL_MAP.  Falls back to same top-category if the leaf
    category isn't mapped.
    """
    cat_index = _build_category_index(products)
    top_index: dict[str, list[Product]] = {}
    for p in products:
        top_index.setdefault(_top_category(p.product_type), []).append(p)

    result: list[dict] = []

    for p in products:
        leaf = _leaf_category(p.product_type)
        comp_cats = CROSSSELL_MAP.get(leaf, [])

        cs_products: list[tuple[Product, str]] = []
        for comp in comp_cats:
        for c in cat_index.get(comp, []):
                if c.id != p.id and c.availability == "in_stock":
                    cs_products.append((c, comp))
                if len(cs_products) >= max_cs * 3:
                    break
            if len(cs_products) >= max_cs * 3:
                break

        # Fallback: same top-category, different leaf
        if not cs_products:
            top = _top_category(p.product_type)
            for c in top_index.get(top, []):
                if c.id != p.id and _leaf_category(c.product_type) != leaf:
                    cs_products.append((c, _leaf_category(c.product_type)))
                if len(cs_products) >= max_cs * 3:
                    break

        # Deduplicate by product ID, prefer in-stock
        seen: set[str] = set()
        deduped: list[tuple[Product, str]] = []
        for c, reason in cs_products:
            if c.id not in seen:
                seen.add(c.id)
                deduped.append((c, reason))
        deduped = deduped[:max_cs]

        entry: dict[str, Any] = {
            "ID": p.id,
            "Produkt": p.title,
            "Cena": _price_label(p),
            "Kategoria": leaf,
            "Produkt_url": p.link,
        }
        for i, (c, reason) in enumerate(deduped, start=1):
            entry[f"Cross-sell {i}"] = _crosssell_label(c, reason)
            entry[f"Cross-sell {i}_url"] = c.link

        result.append(entry)

    return result


def build_intent_mapping(products: list[Product], faq_entries: list[dict]) -> list[dict]:
    """Build IntentMapping section.

    Generates intent entries for:
    - FAQ questions (preserved)
    - Top leaf categories  (→ category search intent)
    - Unique brands with ≥3 products (→ brand preference intent)
    """
    result: list[dict] = []

    # 1. Preserve FAQ intents
    for faq in faq_entries:
        result.append({
            "Typ zámeru": "FAQ / zákaznícka podpora",
            "Zámer (príklad otázky/vyhľadávania)": faq.get("Otázka", ""),
            "Názov prepojeného obsahu": faq.get("Otázka", ""),
            "Poznámka": "Prevzaté z FAQ.",
        })

    # 2. Category intents (leaf categories with ≥5 products)
    from collections import Counter
    leaf_counts: Counter[str] = Counter()
    for p in products:
        leaf = _leaf_category(p.product_type)
        if leaf:
            leaf_counts[leaf] += 1

    for leaf, count in leaf_counts.most_common():
        if count < 5:
            break
        result.append({
            "Typ zámeru": "Kategóriové vyhľadávanie",
            "Zámer (príklad otázky/vyhľadávania)": f"Hľadám {leaf.lower()}",
            "Názov prepojeného obsahu": leaf,
            "Poznámka": f"Auto-generované z feedu ({count} produktov).",
        })

    # 3. Brand intents (brands with ≥3 products)
    brand_counts: Counter[str] = Counter()
    for p in products:
        if p.brand:
            brand_counts[p.brand] += 1

    for brand, count in brand_counts.most_common():
        if count < 3:
            break
        result.append({
            "Typ zámeru": "Značková preferencia",
            "Zámer (príklad otázky/vyhľadávania)": f"produkty značky {brand}",
            "Názov prepojeného obsahu": brand,
            "Poznámka": f"Auto-generované z feedu ({count} produktov).",
        })

    return result


# ---------------------------------------------------------------------------
# OpenAI Products_AI enrichment (async)
# ---------------------------------------------------------------------------

def _build_lang_block(
    product: Product,
    translation_index: dict[str, dict[str, Product]],
) -> str:
    """Build the multilang name/description block for the OpenAI prompt."""
    lines: list[str] = []
    translations = translation_index.get(product.id, {})

    # Always include the primary (SK) entry
    all_langs = {"sk": product, **translations}

    for lang, p in all_langs.items():
        lines.append(f"  [{lang.upper()}] {p.title}")
        if p.description:
            lines.append(f"       {p.description[:200]}")

    return "\n".join(lines)


def _enrich_one_product(
    product: Product,
    translation_index: dict[str, dict[str, Product]],
    openai_client: "OpenAI",
    model: str = "gpt-4.1-mini",
) -> dict | None:
    """Call OpenAI to generate Products_AI entry for a single product.
    Returns None on failure (logged but not re-raised).
    """
    lang_block = _build_lang_block(product, translation_index)
    price_str = _price_label(product) or "N/A"

    user_msg = _PRODUCTS_AI_USER_TEMPLATE.format(
        id=product.id,
        category=product.product_type,
        price=product.effective_price or "",
        currency=product.currency,
        brand=product.brand,
        gtin=product.gtin,
        lang_block=lang_block,
    )

    try:
        response = openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _PRODUCTS_AI_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
    except Exception as exc:
        logger.warning("Products_AI enrichment failed for %s: %s", product.id, exc)
        return None

    # Normalise keys to match existing knowledge.json format (e.g. "AI popis – sk")
    entry: dict[str, Any] = {
        "ID": product.id,
        "Produkt (URL)": product.link,
        "Kategória": product.product_type,
        "Kuchyňa": data.get("Kuchyňa", ""),
        "Cena": price_str,
        "Balenie": product.unit_pricing_measure,
        "GTIN": product.gtin,
        "Atribúty": data.get("Atribúty", ""),
    }
    for lang in ("sk", "cz", "de", "en", "hu", "pl"):
        key = f"AI popis – {lang}"
        entry[key] = data.get(key, data.get(f"AI popis – {lang.upper()}", ""))

    for field in (
        "Cross-sell",
        "Alternatíva",
        "Súvisiaci recept",
        "Kucharsky tip - sk",
        "Nakupne odporucanie - sk",
        "Chutovy profil - sk",
        "Pouzitie v kuchyni - sk",
        "Kedy odporucit - sk",
        "Pozor / overit - sk",
        "Predajny argument - sk",
        "Agenticky dalsi krok - sk",
    ):
        entry[field] = data.get(field, "")

    return entry

def enrich_products_ai(
    changed_products: list[Product],
    existing_ai: list[dict],
    translation_index: dict[str, dict[str, Product]],
    openai_client: "OpenAI",
    model: str = "gpt-4.1-mini",
    max_per_run: int = 50,
) -> list[dict]:
    """Enrich changed/new products with OpenAI and merge into existing_ai.

    Processes at most *max_per_run** products per call to limit API cost.
    Existing entries for unchanged products are preserved.
    Entries for products removed from the feed are dropped.
    """
    existing_by_id = {e["ID"]: e for e in existing_ai}
    enriched = 0

    for product in changed_products[:max_per_run]:
        logger.info("Enriching Products_AI for %s (%s)…", product.id, product.title[:40])
        entry = _enrich_one_product(product, translation_index, openai_client, model)
        if entry:
            existing_by_id[product.id] = entry
            enriched += 1

    if enriched:
        logger.info("Products_AI enriched: %d products updated.", enriched)
    return list(existing_by_id.values())


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_knowledge(
    products: list[Product],
    base_knowledge: dict,
    *,
    old_snapshot: ProductSnapshot | None = None,
    translation_index: dict[str, dict[str, Product]] | None = None,
    openai_client: "OpenAI | None" = None,
    openai_model: str = "gpt-4.1-mini",
    max_ai_enrichment_per_run: int = 50,
) -> tuple[dict, ProductSnapshot]:
    """Build a fresh knowledge dict from the live product feed.

    Args:
        products:                SK (primary) products from the feed.
        base_knowledge:          Existing knowledge.json content.
        old_snapshot:            Previous product snapshot for change detection.
        translation_index:       {product_id: {lang: Product}} from all feed mutations.
        openai_client:           OpenAI client; skipped if None.
        openai_model:            Model to use for Products_AI enrichment.
        max_ai_enrichment_per_run: Max products to enrich per invocation.

    Returns:
        (new_knowledge_dict, new_snapshot)
    """
    logger.info("Building knowledge from %d products…", len(products))

    sections = base_knowledge.get("sections", {})

    # ---- rule-based sections (fast, always regenerated) ----
    logger.info("Building Alternatives…")
    alternatives = build_alternatives(products)

    logger.info("Building CrossSell…")
    crosssell = build_crosssell(products)

    logger.info("Building IntentMapping…")
    faq = sections.get("FAQ", [])
    intent_mapping = build_intent_mapping(products, faq)

    # ---- OpenAI Products_AI enrichment (async, only changed products) ----
    existing_ai: list[dict] = sections.get("Products_AI", [])

    if openai_client is not None and old_snapshot is not None:
        changed, removed = diff_products(old_snapshot, products)
        logger.info(
            "Feed diff: %d changed/new, %d removed products.",
            len(changed),
            len(removed),
        )
        # Drop removed products from Products_AI
        removed_set = set(removed)
        existing_ai = [e for e in existing_ai if e["ID"] not in removed_set]

        if changed:
            existing_ai = enrich_products_ai(
                changed,
                existing_ai,
                translation_index or {},
                openai_client,
                model=openai_model,
                max_per_run=max_ai_enrichment_per_run,
            )
    elif openai_client is None:
        logger.debug("No OpenAI client — Products_AI enrichment skipped.")

    # ---- Assemble output ----
    new_knowledge = {
        "version": "auto_v1",
        "source": "product_feed_autogenerated",
        "sections": {
            "Alternatives": alternatives,
            "CrossSell": crosssell,
            # Manual sections preserved verbatim
            "Recipes": sections.get("Recipes", []),
            "Magazine": sections.get("Magazine", []),
            "FAQ": faq,
            "Products_AI": existing_ai,
            "IntentMapping": intent_mapping,
        },
        "counts": {
            "Alternatives": len(alternatives),
            "CrossSell": len(crosssell),
            "Recipes": len(sections.get("Recipes", [])),
            "Magazine": len(sections.get("Magazine", [])),
            "FAQ": len(faq),
            "Products_AI": len(existing_ai),
            "IntentMapping": len(intent_mapping),
        },
    }

    new_snapshot = build_product_snapshot(products)
    logger.info(
        "Knowledge rebuilt: %s",
        {k: v for k, v in new_knowledge["counts"].items()},
    )
    return new_knowledge, new_snapshot

def save_knowledge(knowledge: dict, path: str | Path) -> None:
    """Write knowledge dict to JSON file (atomic write via temp file)."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(knowledge, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(dest)
    logger.info("Knowledge saved to %s.", dest)
