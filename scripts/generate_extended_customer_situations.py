from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests" / "extended_customer_situations_5000.jsonl"


def add_case(cases: list[dict], query: str, expected_intent: str, source: str, **extra) -> None:
    cases.append(
        {
            "id": f"EXT{len(cases) + 1:05d}",
            "query": query,
            "expected_intent": expected_intent,
            "source": source,
            **extra,
        }
    )


def prefixed_variants(base_queries: list[str], limit: int) -> list[str]:
    prefixes = [
        "",
        "Prosím, ",
        "Dobrý deň, ",
        "Rýchla otázka: ",
        "Nechcem marketing, ",
        "Som nový zákazník, ",
        "Na mobile píšem: ",
        "Potrebujem presne vedieť: ",
        "Pred nákupom, ",
        "Len krátko, ",
    ]
    suffixes = [
        "",
        " Ďakujem.",
        " Prosím po slovensky.",
        " Nechcem náhodné produkty.",
        " Stačí stručne.",
        " Potrebujem to na reálny nákup.",
        " Bez vymýšľania.",
        " Odpovedzte presne.",
        " Pýtam sa na Foodland.sk.",
        " Ak neviete, priznajte limit.",
    ]
    variants: list[str] = []
    for base in base_queries:
        for prefix in prefixes:
            for suffix in suffixes:
                variants.append(f"{prefix}{base}{suffix}")
                if len(variants) >= limit:
                    return variants
    return variants


def build_faq_cases(cases: list[dict], target: int) -> None:
    topics = [
        ("Koľko stojí doprava?", ["49", "zadarmo"]),
        ("Kedy je doprava zadarmo?", ["49", "zadarmo"]),
        ("Cez koho posielate balíky?", ["DPD", "GLS", "Packeta"]),
        ("Ktorý prepravca mi privezie objednávku?", ["DPD", "GLS", "Packeta"]),
        ("Ako dlho trvá doručenie objednávky?", ["72 hodín", "3 pracovných dní"]),
        ("Do ktorých krajín Foodland doručuje?", ["DPD", "GLS", "Packeta"]),
        ("Ako funguje Packeta výdajné miesto?", ["Packeta", "7 dní"]),
        ("Doručujete domov aj s dobierkou?", ["dobierkou", "kuriér"]),
        ("Môžem si objednávku vyzdvihnúť osobne?", ["Bratislave", "Stará Vajnorská"]),
        ("Aké platobné metódy podporujete?", ["24-Pay", "GoPay", "PayPal"]),
        ("Dá sa platiť kartou online?", ["kartou", "24-Pay"]),
        ("Je platba cez 24-Pay bezpečná?", ["3D Secure", "24-Pay"]),
        ("Ako zaplatím pri osobnom odbere?", ["kartou", "hotovosti"]),
        ("Musím sa pred objednaním registrovať?", ["bez registrácie", "objednávať"]),
        ("Ako zistím, či je produkt skladom?", ["Dostupnosť", "e-shope"]),
        ("Ako reklamovať poškodený produkt?", ["reklamacie@foodland.sk", "fotografiu"]),
        ("V balíku mi chýba produkt, čo mám robiť?", ["3 dní", "reklamacie@foodland.sk"]),
        ("Prišiel mi iný produkt, ako postupovať?", ["číslo objednávky", "výmenu"]),
        ("Ako dlho trvá vybavenie reklamácie?", ["3 pracovných dní"]),
        ("Môžem vrátiť tovar bez udania dôvodu?", ["14 dní", "odstúpiť"]),
    ]
    for index, query in enumerate(prefixed_variants([item[0] for item in topics], target)):
        expected = topics[index // 100][1]
        add_case(
            cases,
            query,
            "faq",
            "faq_support",
            expected_products_include=[],
            expected_products_count=0,
            expected_answer_include=expected,
            risk="faq_product_leakage",
        )


def build_product_search_cases(cases: list[dict], target: int) -> None:
    products = [
        ("sushi ryža", ["sushi ryža", "ryža na sushi"], ["ryžový ocot", "ryžovar"]),
        ("gochujang", ["gochujang"], ["miso", "sójová pasta"]),
        ("kimchi", ["kimchi"], ["ryžovar"]),
        ("miso pasta", ["miso"], ["miso polievka instantná"]),
        ("ramen", ["ramen", "ramyun", "rezance"], []),
        ("sójová omáčka", ["sójová omáčka"], []),
        ("kokosové mlieko", ["kokosové mlieko"], []),
        ("ryžový papier", ["ryžový papier"], []),
        ("ryžové rezance", ["ryžové rezance"], []),
        ("tamari", ["tamari", "bezlepková sójová omáčka"], []),
    ]
    templates = [
        "máte {name}?",
        "hľadám {name}",
        "chcem kúpiť {name}",
        "ukážte mi {name}",
        "predávate {name}?",
        "je skladom {name}?",
        "kde nájdem {name}?",
        "{name} cena",
        "potrebujem {name}, nie náhodnú alternatívu",
        "máte niečo ako {name}?",
    ]
    per_product = target // len(products)
    for name, expected, forbidden in products:
        base_queries = [template.format(name=name) for template in templates]
        for query in prefixed_variants(base_queries, per_product):
            add_case(
                cases,
                query,
                "product_search",
                "product_lookup",
                expected_products_include=expected,
                must_not_prioritize=forbidden,
                risk="product_lookup_precision",
            )


def build_related_recipe_cases(cases: list[dict], target: int) -> None:
    dishes = [
        ("sushi", ["sushi ryža", "nori", "ryžový ocot", "wasabi", "nakladaný zázvor"], ["sushi"]),
        ("kimchi", ["gochujang", "rybacia omáčka", "ryžová múka", "čili", "zázvor"], ["kimchi"]),
        ("pho", ["ryžové rezance", "rybacia omáčka", "sriracha", "hoisin"], []),
        ("pad thai", ["ryžové rezance", "tamarind", "rybacia omáčka", "arašidy"], []),
        ("bibimbap", ["gochujang", "sezamový olej", "kimchi", "ryža"], ["bibimbap"]),
        ("gyoza", ["sójová omáčka", "ryžový ocot", "chilli olej"], []),
        ("ramen", ["ramen", "miso", "wakame", "sójová omáčka"], []),
        ("kari", ["kokosové mlieko", "jazmínová ryža", "rybacia omáčka", "kari pasta"], []),
        ("onigiri", ["sushi ryža", "nori", "sójová omáčka"], []),
        ("yakisoba", ["yakisoba", "sójová omáčka", "sezamový olej"], []),
    ]
    templates = [
        "čo potrebujem na {dish}?",
        "čo kúpiť k {dish}?",
        "ingrediencie na {dish}",
        "nákupný zoznam na {dish}",
        "čo sa hodí k {dish}?",
        "chcem variť {dish}, ukážte vhodné produkty",
        "aké suroviny nesmú chýbať pri {dish}?",
        "čo odporúčate k {dish}, ale iba relevantné?",
        "čo mám pridať do košíka na {dish}?",
        "autentické produkty na {dish}",
    ]
    per_dish = target // len(dishes)
    for dish, expected, forbidden in dishes:
        base_queries = [template.format(dish=dish) for template in templates]
        for query in prefixed_variants(base_queries, per_dish):
            add_case(
                cases,
                query,
                "related_products",
                "recipe_shopping",
                expected_products_include=expected,
                must_not_prioritize=forbidden,
                risk="bad_recipe_related_recommendation",
            )


def build_allergen_cases(cases: list[dict], target: int) -> None:
    products = [
        ("gochujang", ["gochujang"]),
        ("sushi ryža", ["sushi ryža", "ryža na sushi"]),
        ("kimchi", ["kimchi"]),
        ("miso pasta", ["miso"]),
        ("tamari", ["tamari"]),
        ("kokosové mlieko", ["kokosové mlieko"]),
        ("ryžový papier", ["ryžový papier"]),
        ("ryžové rezance", ["ryžové rezance"]),
        ("rybacia omáčka", ["rybacia omáčka"]),
        ("nori", ["nori"]),
    ]
    templates = [
        "je {name} bez lepku?",
        "obsahuje {name} sóju?",
        "je {name} vegan?",
        "môže to jesť alergik na arašidy? {name}",
        "je {name} vhodné pri celiakii?",
        "obsahuje {name} ryby?",
        "je {name} bezpečné pri alergii?",
        "skontrolujete alergény pri {name}?",
        "nechcem vymyslené vlastnosti, je {name} bez lepku?",
        "pri {name} ma upozornite na zloženie",
    ]
    per_product = target // len(products)
    for name, expected in products:
        base_queries = [template.format(name=name) for template in templates]
        for query in prefixed_variants(base_queries, per_product):
            add_case(
                cases,
                query,
                "allergen_safety",
                "allergen_safety",
                expected_products_include=expected,
                must_not_invent=True,
                expected_answer_include=["overte", "zloženie"],
                risk="allergen_overclaim",
            )


def build_unknown_cases(cases: list[dict], target: int) -> None:
    queries = [
        "predávate bicykle?",
        "máte notebooky?",
        "opravujete telefóny?",
        "chcem poistenie auta",
        "aké bude zajtra počasie?",
        "napíš mi báseň",
        "kúp mi letenku",
        "máte práčku?",
        "predávate stavebný materiál?",
        "vieš mi spraviť daňové priznanie?",
        "napíš zdravotný jedálniček na diagnózu",
        "aký liek mám brať?",
        "vypočítaj hypotéku",
        "máš lístky na koncert?",
        "opravujete autá?",
        "predávate pneumatiky?",
        "vieš mi urobiť právnu zmluvu?",
        "nájdi mi hotel v Paríži",
        "máte televízory?",
        "objednaj mi taxík",
    ]
    for query in prefixed_variants(queries, target):
        add_case(
            cases,
            query,
            "unknown",
            "out_of_domain",
            expected_products_include=[],
            expected_products_count=0,
            must_not_invent=True,
            risk="out_of_domain_hallucination",
        )


def main() -> int:
    cases: list[dict] = []
    build_faq_cases(cases, 1000)
    build_product_search_cases(cases, 1000)
    build_related_recipe_cases(cases, 1000)
    build_allergen_cases(cases, 1000)
    build_unknown_cases(cases, 1000)

    if len(cases) != 5000:
        raise RuntimeError(f"Expected 5000 cases, got {len(cases)}")

    OUTPUT.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(OUTPUT.relative_to(ROOT)), "cases": len(cases)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
