from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests" / "mobile_ux_out_of_domain_3000.jsonl"


def add_case(cases: list[dict], query: str, expected_intent: str, source: str, **extra) -> None:
    cases.append(
        {
            "id": f"MOOD{len(cases) + 1:05d}",
            "query": query,
            "expected_intent": expected_intent,
            "source": source,
            **extra,
        }
    )


def variants(base_queries: list[str], limit: int) -> list[str]:
    prefixes = [
        "",
        "mobil: ",
        "rychlo ",
        "klikol som na tlacidlo: ",
        "po znovuotvoreni widgetu ",
        "po zatvoreni a otvoreni ",
        "opakujem otazku: ",
        "este raz ",
        "pisem v mobile ",
        "kratko ",
    ]
    suffixes = [
        "",
        "?",
        " prosim",
        " dakujem",
        " len strucne",
        " nechcem nahodne produkty",
        " bez omacky okolo",
        " zobrazit viac",
        " po slovensky",
        " do kosika",
    ]
    results: list[str] = []
    for base in base_queries:
        for prefix in prefixes:
            for suffix in suffixes:
                results.append(f"{prefix}{base}{suffix}".strip())
                if len(results) >= limit:
                    return results
    return results


def build_mobile_short_questions(cases: list[dict], target: int) -> None:
    topics = [
        ("kimchi", "product_search", ["kimchi"], []),
        ("gochujang", "product_search", ["gochujang"], []),
        ("sushi ryza", "product_search", ["sushi ryza", "ryza na sushi"], ["ryzovy ocot"]),
        ("ramen", "product_search", ["ramen", "ramyun", "rezance"], []),
        ("miso", "product_search", ["miso"], []),
        ("tamari", "product_search", ["tamari"], []),
        ("kokosove mlieko", "product_search", ["kokosove mlieko"], []),
        ("ryzovy papier", "product_search", ["ryzovy papier"], []),
        ("ryzove rezance", "product_search", ["ryzove rezance"], []),
        ("sojova omacka", "product_search", ["sojova omacka"], []),
    ]
    templates = [
        "{term}",
        "{term} skladom",
        "{term} cena",
        "mate {term}",
        "hladam {term}",
        "chcem {term}",
        "kupit {term}",
        "ukaz {term}",
        "najdi {term}",
        "{term} prosim",
    ]
    per_topic = target // len(topics)
    for term, intent, expected, forbidden in topics:
        base = [template.format(term=term) for template in templates]
        for query in variants(base, per_topic):
            add_case(
                cases,
                query,
                intent,
                "mobile_short_question",
                expected_products_include=expected,
                must_not_prioritize=forbidden,
                risk="mobile_short_input_precision",
            )


def build_mobile_interrupted_sentences(cases: list[dict], target: int) -> None:
    topics = [
        ("ako varit ramen", "related_products", ["ramen", "miso", "wakame", "sojova omacka"], []),
        ("co na pad thai", "related_products", ["ryzove rezance", "tamarind", "rybacia omacka", "arasidy"], []),
        ("co kupit na pho", "related_products", ["ryzove rezance", "rybacia omacka", "sriracha", "hoisin"], []),
        ("ingrediencie kimchi", "related_products", ["gochujang", "rybacia omacka", "ryzova muka", "cili"], ["kimchi"]),
        ("cim nahradit mirin", "product_search", ["mirin", "ryzovy ocot"], []),
        ("bezlepkova sojova", "product_search", ["tamari", "bezlepkova sojova omacka"], []),
        ("recept sushi", "related_products", ["sushi ryza", "nori", "ryzovy ocot", "wasabi"], ["sushi set"]),
        ("co dnes varit", "recipe", [], []),
        ("vecera rychlo", "recipe", [], []),
        ("nieco korejske", "recipe", [], []),
    ]
    fragments = [
        "{term}",
        "{term}...",
        "{term} pros",
        "{term} pls",
        "{term} a produkty",
        "{term} iba suroviny",
        "{term} nie nahodne",
        "{term} zobraz viac",
        "{term} do kosika",
        "{term} znova",
    ]
    per_topic = target // len(topics)
    for term, intent, expected, forbidden in topics:
        base = [fragment.format(term=term) for fragment in fragments]
        for query in variants(base, per_topic):
            add_case(
                cases,
                query,
                intent,
                "mobile_interrupted_sentence",
                expected_products_include=expected,
                must_not_prioritize=forbidden,
                risk="mobile_interrupted_intent_detection",
            )


def build_quick_button_repeats(cases: list[dict], target: int) -> None:
    buttons = [
        ("co dnes varit", "recipe", []),
        ("recept na ramen", "related_products", ["ramen", "miso", "wakame", "sojova omacka"]),
        ("cim nahradit mirin", "product_search", ["mirin", "ryzovy ocot"]),
        ("najlepsia sushi ryza", "product_search", ["sushi ryza", "ryza na sushi"]),
        ("kokosove mlieko", "product_search", ["kokosove mlieko"]),
        ("je kimchi vhodne", "product_search", ["kimchi"]),
        ("co sa hodi k ramen", "related_products", ["ramen", "miso", "wakame", "sojova omacka"]),
        ("ukaz viac ramen", "related_products", ["ramen", "miso", "wakame", "sojova omacka"]),
        ("opat kimchi", "product_search", ["kimchi"]),
        ("zopakuj odporucanie sushi ryza", "product_search", ["sushi ryza", "ryza na sushi"]),
    ]
    templates = [
        "{button}",
        "{button} {button}",
        "klik {button}",
        "rychle tlacidlo {button}",
        "po zavreti widgetu {button}",
        "po otvoreni widgetu {button}",
        "tlacidlo nereagovalo {button}",
        "este raz {button}",
        "omylom som zavrel {button}",
        "zobrazit viac {button}",
    ]
    per_button = target // len(buttons)
    for button, intent, expected in buttons:
        base = [template.format(button=button) for template in templates]
        for query in variants(base, per_button):
            add_case(
                cases,
                query,
                intent,
                "mobile_quick_button_repeat",
                expected_products_include=expected,
                risk="quick_button_repeat_or_reopen",
            )


def build_out_of_domain_cases(cases: list[dict], target: int) -> None:
    topics = [
        "predavate bicykle",
        "aky bicykel kupit",
        "opravujete elektrobicykle",
        "ake lieky na bolest brucha",
        "mozem brat antibiotika",
        "diagnoza bolest hlavy",
        "urob mi pravnu zmluvu",
        "mozem zalovat predajcu",
        "vypocitaj hypoteku",
        "ktora banka da najlepsiu hypoteku",
        "kryptomeny dnes",
        "ake akcie kupit na burze",
        "kupim notebook",
        "aky telefon odporucas",
        "opravujete auta",
        "predavate pneumatiky",
        "rezervuj hotel",
        "kup mi letenku",
        "objednaj taxi",
        "ake bude pocasie",
        "napis mi basen",
        "urob danove priznanie",
        "predavate televizory",
        "chcem poistenie auta",
        "najdi pravnika",
        "potrebujem lekara",
        "nahradne diely do auta",
        "predavate matrace",
        "mate krmivo pre psa",
        "porad investiciu",
    ]
    templates = [
        "{topic}",
        "{topic} prosim",
        "{topic} na foodlande",
        "mate {topic}",
        "viete poradit {topic}",
        "rychla otazka {topic}",
        "nechcem produkty, {topic}",
        "odpovedz presne {topic}",
        "som v mobile {topic}",
        "{topic} dakujem",
    ]
    start_count = len(cases)
    per_topic = (target + len(topics) - 1) // len(topics)
    for topic in topics:
        base = [template.format(topic=topic) for template in templates]
        for query in variants(base, per_topic):
            if len(cases) - start_count >= target:
                return
            add_case(
                cases,
                query,
                "unknown",
                "out_of_domain_guard",
                expected_products_include=[],
                expected_products_count=0,
                must_not_invent=True,
                risk="out_of_domain_product_hallucination",
            )


def main() -> int:
    cases: list[dict] = []
    build_mobile_short_questions(cases, 750)
    build_mobile_interrupted_sentences(cases, 750)
    build_quick_button_repeats(cases, 500)
    build_out_of_domain_cases(cases, 1000)

    if len(cases) != 3000:
        raise RuntimeError(f"Expected 3000 cases, got {len(cases)}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as file:
        for case in cases:
            file.write(json.dumps(case, ensure_ascii=False) + "\n")

    print(json.dumps({"output": str(OUTPUT.relative_to(ROOT)), "cases": len(cases)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
