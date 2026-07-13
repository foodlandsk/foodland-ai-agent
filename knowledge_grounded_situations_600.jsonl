from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests" / "strict_customer_european_diet_1000.jsonl"


def add_case(cases: list[dict], query: str, expected_intent: str, **extra) -> None:
    case = {
        "id": f"SC{len(cases) + 1:04d}",
        "persona": "prisny_zakaznik_problemy_s_europskou_stravou",
        "query": query,
        "expected_intent": expected_intent,
        **extra,
    }
    cases.append(case)


def main() -> int:
    cases: list[dict] = []

    product_search_scenarios = [
        ("Nejem klasický európsky chlieb, chcem niečo ryžové a ľahké.", ["ryžový papier", "ryžové rezance", "ryžové krekry"]),
        ("Zemiaky mi nesedia, ukážte mi radšej ryžu na prílohu.", ["jazmínová ryža", "sushi ryža", "basmati ryža"]),
        ("Hľadám náhradu za pšeničné cestoviny, ale nechcem talianske cestoviny.", ["ryžové rezance", "udon", "ramen"]),
        ("Nemôžem mlieko, chcem kokosové mlieko do varenia.", ["kokosové mlieko"]),
        ("Európske sladkosti mi nesedia, chcem mochi alebo niečo ryžové.", ["mochi", "ryžové krekry"]),
        ("Klasické omáčky mi vadia, chcem sójovú alebo tamari.", ["sójová omáčka", "tamari"]),
        ("Potrebujem niečo na dochutenie namiesto masla a smotany.", ["sezamový olej", "kokosové mlieko", "miso"]),
        ("Nechcem európsku polievku, chcem ramen alebo miso.", ["ramen", "miso"]),
        ("Hľadám niečo kyslé a fermentované, ale nie kyslú kapustu.", ["kimchi"]),
        ("Chcem snack bez európskej čokolády, radšej ázijský snack.", ["Pocky", "mochi", "ryžové krekry"]),
        ("Nechcem bravčové ani salámu, chcem tofu alebo morské riasy.", ["tofu", "nori", "wakame"]),
        ("Potrebujem omáčku k ryži, nie kečup.", ["sójová omáčka", "sriracha", "gochujang"]),
        ("Chcem bezlepkovú sójovú omáčku, nie obyčajnú omáčku na mäso.", ["bezlepková sójová omáčka", "tamari"]),
        ("Hľadám ryžový papier na rolky, nie papierové obrúsky.", ["ryžový papier"]),
        ("Chcem fish sauce, ale po slovensky mi nájdi rybaciu omáčku.", ["rybacia omáčka"]),
        ("Chcem sesame oil, nie olivový olej.", ["sezamový olej"]),
        ("Chcem rice vinegar do sushi, nie vínny ocot.", ["ryžový ocot"]),
        ("Chcem wasabi a nakladaný zázvor, nie horčicu.", ["wasabi", "nakladaný zázvor"]),
        ("Hľadám hoisin na ázijské jedlo, nie európsku BBQ omáčku.", ["hoisin"]),
        ("Chcem panko, ale nie klasickú strúhanku.", ["panko"]),
    ]
    prefixes = [
        "",
        "Som náročný zákazník: ",
        "Prosím presne: ",
        "Neodporúčajte mi náhodné veci, ",
        "Mám citlivé trávenie, ",
    ]
    for query, expected in product_search_scenarios:
        for prefix in prefixes:
            add_case(
                cases,
                prefix + query,
                "product_search",
                expected_products_include=expected,
                must_not_invent=True,
                risk="wrong_european_substitute",
            )

    dishes = [
        ("sushi", ["sushi ryža", "nori", "ryžový ocot", "wasabi", "nakladaný zázvor"]),
        ("kimchi", ["gochujang", "rybacia omáčka", "ryžová múka", "čili", "zázvor"]),
        ("pho", ["ryžové rezance", "rybacia omáčka", "sriracha", "hoisin"]),
        ("pad thai", ["ryžové rezance", "tamarind", "rybacia omáčka", "arašidy"]),
        ("bibimbap", ["gochujang", "sezamový olej", "kimchi", "ryža"]),
        ("gyoza", ["sójová omáčka", "ryžový ocot", "chilli olej"]),
        ("ramen", ["ramen", "miso", "wakame", "sójová omáčka"]),
        ("kari", ["kokosové mlieko", "jazmínová ryža", "rybacia omáčka", "kari pasta"]),
    ]
    related_templates = [
        "Čo presne potrebujem na {dish}, nechcem európsku improvizáciu.",
        "Dajte mi nákupný zoznam na {dish}, nie všeobecné rady.",
        "Čo kúpiť k {dish}, aby to chutilo autenticky?",
        "Som prísny, odporučte suroviny k {dish} a nepleťte tam nezmysly.",
        "Ak robím {dish}, čo mi nesmie chýbať?",
        "Chcem variť {dish}, ukážte mi vhodné produkty.",
        "Čo sa hodí k {dish}, ak mi vadí bežná európska strava?",
        "Potrebujem doplnky k {dish}, ale iba relevantné.",
        "Ingrediencie na {dish}, prosím bez náhodných snackov.",
        "Čo odporúčate k {dish} pre zákazníka, ktorý nechce európsku kuchyňu?",
    ]
    for dish, expected in dishes:
        for template in related_templates:
            add_case(
                cases,
                template.format(dish=dish),
                "related_products",
                expected_products_include=expected,
                must_not_prioritize=[dish] if dish not in {"pho", "pad thai"} else [],
                risk="bad_related_recommendation",
            )

    allergen_products = [
        ("sushi ryža", ["sushi ryža", "ryža na sushi"]),
        ("gochujang", ["gochujang"]),
        ("kimchi", ["kimchi"]),
        ("miso pasta", ["miso"]),
        ("ramen", ["ramen", "ramyun", "rezance"]),
        ("sójová omáčka", ["sójová omáčka"]),
        ("rybacia omáčka", ["rybacia omáčka"]),
        ("sezamový olej", ["sezamový olej"]),
        ("kokosové mlieko", ["kokosové mlieko"]),
        ("panko strúhanka", ["panko"]),
        ("ryžový papier", ["ryžový papier", "rice paper"]),
        ("wakame", ["wakame"]),
        ("nori", ["nori"]),
        ("sriracha", ["sriracha"]),
        ("udon", ["udon"]),
        ("mochi", ["mochi"]),
    ]
    allergen_templates = [
        "Je {product} bez lepku? Nehádajte, upozornite ma na zloženie.",
        "Obsahuje {product} sóju? Chcem opatrnú odpoveď.",
        "Môže to jesť alergik na arašidy? {product}",
        "Je {product} vhodné pri celiakii?",
        "Je {product} vegan? Nechcem vymyslené vlastnosti.",
        "Má {product} alergény? Ukážte produkt, ale povedzte nech overím etiketu.",
        "Potrebujem {product}, ale mám intoleranciu. Čo mám skontrolovať?",
        "Dobrý deň, je {product} bez lepku a skladom?",
        "Ahoj, obsahuje {product} sóju alebo lepok?",
        "Prosím môže {product} jesť človek s alergiou na arašidy?",
    ]
    for product, expected in allergen_products:
        for template in allergen_templates:
            add_case(
                cases,
                template.format(product=product),
                "allergen_safety",
                expected_products_include=expected,
                expected_answer_include=["overte", "zloženie", "detail"],
                must_not_invent=True,
                risk="allergen_hallucination",
            )

    dietary_templates = [
        "Som vegan a európske jedlá mi nesedia, čo ázijské odporúčate?",
        "Chcem niečo nepálivé, ale nie európsku prílohu bez chuti.",
        "Chcem bezlepkové veci k sushi, ale nechcem rizikovú odpoveď.",
        "Nejem mlieko ani maslo, čo mám použiť do kari?",
        "Potrebujem snack pre dieťa, ale nič pálivé ani alkoholické.",
        "Chcem niečo fermentované, ale nie príliš pálivé.",
        "Hľadám ázijské jedlo bez bravčového.",
        "Chcem pikantné, ale nie extrémne pálivé.",
        "Chcem extra pálivé omáčky, nie sladké snacky.",
        "Hľadám jemné jedlo pre citlivý žalúdok.",
    ]
    dietary_expected = [
        ["tofu", "nori", "ryžové rezance", "kokosové mlieko"],
        ["mochi", "kokosové mlieko", "jazmínová ryža", "miso"],
        ["bezlepková sójová omáčka", "tamari", "nori", "sushi ryža"],
        ["kokosové mlieko", "sezamový olej", "kari pasta"],
        ["Pocky", "mochi", "ryžové krekry"],
        ["kimchi", "miso", "nakladaný zázvor"],
        ["tofu", "nori", "wakame", "ryžové rezance"],
        ["sriracha", "gochujang", "chilli olej"],
        ["Sambal Oelek", "Sriracha", "gochujang", "čili pasta"],
        ["jazmínová ryža", "miso", "kokosové mlieko", "mochi"],
    ]
    for idx, query in enumerate(dietary_templates):
        for suffix in ["", " Prosím buďte presní.", " Nechcem generickú odpoveď.", " Ukážte produkty.", " Bez európskych náhrad."]:
            add_case(
                cases,
                query + suffix,
                "dietary_filter",
                expected_products_include=dietary_expected[idx],
                expected_answer_include=["overte"] if "bezlepk" in query else [],
                risk="dietary_misclassification",
            )

    faq_queries = [
        ("Som prísny zákazník, ako fungujú kredity?", ["1 kredit", "0,01"]),
        ("Koľko stojí doprava a od akej sumy je zdarma?", ["doprava", "zdarma"]),
        ("Dá sa platiť kartou alebo iba hotovosťou?", ["kartou", "hotovosť"]),
        ("Kedy mi príde objednávka, ak objednám ázijské potraviny?", ["doručenie", "objednávka"]),
        ("Môžem vrátiť produkt, ak mi nesedí chuť?", ["vrátenie", "reklamácia"]),
        ("Máte osobný odber, nechcem čakať na kuriéra?", ["osobný odber"]),
        ("Posielate aj mimo Slovenska?", ["doručenie"]),
        ("Ako použijem vernostné kredity pri ďalšom nákupe?", ["kredit"]),
        ("Čo ak príde poškodený produkt?", ["reklamácia"]),
        ("Ako zistím stav objednávky?", ["objednávka"]),
    ]
    for query, expected_answer in faq_queries:
        for suffix in ["", " Nezobrazujte mi pri tom produkty.", " Odpovedzte stručne.", " Chcem presné pravidlá.", " Bez marketingu."]:
            add_case(
                cases,
                query + suffix,
                "faq",
                expected_products_count=0,
                expected_answer_include=expected_answer,
                risk="faq_product_leakage",
            )

    unknown_queries = [
        "Predávate práčky a sušičky?",
        "Viete mi vybaviť letenku do Japonska?",
        "Napíšte mi báseň o sushi.",
        "Aké bude zajtra počasie v Bratislave?",
        "Vieš mi spraviť daňové priznanie?",
        "Predávate stavebný materiál?",
        "Opravujete telefóny?",
        "Chcem poistenie auta.",
        "Máte notebooky alebo monitory?",
        "Objednáte mi taxík?",
        "Viete mi zohnať lieky na predpis?",
        "Kúpite mi akcie na burze?",
        "Vypočítajte mi hypotéku.",
        "Máte náhradné diely do auta?",
        "Predávate krmivo pre psov?",
    ]
    for query in unknown_queries:
        for suffix in ["", " Nehľadajte náhodné potraviny.", " Ak to nie je Foodland, povedzte nie.", " Bez vymýšľania.", " Som prísny, priznajte limit."]:
            add_case(
                cases,
                query + suffix,
                "unknown",
                expected_products_count=0,
                must_not_invent=True,
                risk="out_of_domain_hallucination",
            )

    typo_queries = [
        ("Mate gochudžang bez lepku?", "allergen_safety", ["gochujang"]),
        ("Hladam kimchee, nie europsku kyslu kapustu.", "product_search", ["kimchi"]),
        ("Chcem sushy ryza, opravte si preklep.", "product_search", ["sushi ryža", "ryža na sushi"]),
        ("Mate rice paper na rolky?", "product_search", ["ryžový papier", "rice paper"]),
        ("Kde najdem fish sauce?", "product_search", ["rybacia omáčka"]),
        ("Potrebujem sesame oil.", "product_search", ["sezamový olej"]),
        ("Mate coconat milk do kari?", "product_search", ["kokosové mlieko"]),
        ("Chcem tamary namiesto sojovej omacky.", "product_search", ["tamari"]),
        ("Mate siracha alebo sriraca?", "product_search", ["sriracha"]),
        ("Chcem gochu jang pastu.", "product_search", ["gochujang"]),
    ]
    for query, intent, expected in typo_queries:
        for suffix in ["", " Som náročný zákazník.", " Nevracajte nesúvisiace produkty.", " Prosím presne.", " S diakritikou aj bez nej."]:
            add_case(
                cases,
                query + suffix,
                intent,
                expected_products_include=expected,
                must_not_invent=True,
                risk="typo_and_transliteration",
            )

    strict_negative_constraints = [
        ("Chcem snack, ale nič pálivé, nič alkoholické a nič s wasabi.", ["mochi", "Pocky", "ryžové krekry"], ["wasabi", "soju", "sake", "hot", "spicy"]),
        ("Chcem omáčku, ale nie rybaciu a nie s arašidmi.", ["sójová omáčka", "tamari", "hoisin"], ["rybacia omáčka", "arašidy"]),
        ("Chcem ryžu, ale nie ocot a nie ryžovar.", ["sushi ryža", "jazmínová ryža"], ["ryžový ocot", "ryžovar"]),
        ("Chcem k sushi doplnky, ale nie ďalšie balenia ryže.", ["nori", "wasabi", "nakladaný zázvor"], ["sushi ryža"]),
        ("Chcem niečo jemné, nie extra hot omáčky.", ["mochi", "kokosové mlieko", "miso"], ["extra hot", "sambal"]),
        ("Chcem pálivé, ale nie sladké cukríky.", ["sriracha", "gochujang", "chilli olej"], ["cukríky", "mochi"]),
        ("Chcem tofu alebo riasy, nie mäso.", ["tofu", "nori", "wakame"], ["bravčové", "kuracie"]),
        ("Chcem bezlepkovú sójovú omáčku, nie soju alkohol.", ["bezlepková sójová omáčka", "tamari"], ["Soju"]),
        ("Chcem ryžové rezance, nie instantné snacky.", ["ryžové rezance"], ["snack"]),
        ("Chcem kokosové mlieko do kari, nie kokosové sladkosti.", ["kokosové mlieko"], ["cukríky", "dezert"]),
    ]
    for query, expected, forbidden in strict_negative_constraints:
        for suffix in ["", " Skontrolujte poradie výsledkov.", " Som veľmi prísny.", " Nechcem kompromis.", " Ukážte relevantné produkty."]:
            add_case(
                cases,
                query + suffix,
                "product_search",
                expected_products_include=expected,
                must_not_prioritize=forbidden,
                risk="negative_constraint_ignored",
            )

    european_diet_conflict = [
        ("Po európskej pšenici mi býva ťažko, chcem ryžové rezance.", "product_search", ["ryžové rezance"], []),
        ("Neznášam smotanové omáčky, dajte mi kokosové mlieko do kari.", "product_search", ["kokosové mlieko"], []),
        ("Chcem náhradu za maslo do ázijského jedla.", "product_search", ["sezamový olej", "kokosové mlieko"], []),
        ("Nechcem obyčajný chlieb, hľadám ryžový papier.", "product_search", ["ryžový papier"], []),
        ("Nechcem európsku prílohu, chcem jazmínovú ryžu.", "product_search", ["jazmínová ryža"], []),
        ("Mám problém s kravským mliekom, čo ázijské do varenia?", "product_search", ["kokosové mlieko"], []),
        ("Chcem niečo k jedlu namiesto majonézy.", "product_search", ["sriracha", "sójová omáčka", "hoisin"], []),
        ("Nechcem horčicu, chcem wasabi.", "product_search", ["wasabi"], []),
        ("Nechcem kyslú kapustu, chcem kimchi.", "product_search", ["kimchi"], []),
        ("Nechcem talianske cestoviny, chcem udon.", "product_search", ["udon"], []),
        ("Chcem ľahké rezance do vývaru, nie pšeničné špagety.", "product_search", ["ryžové rezance", "ramen", "udon"], []),
        ("Chcem snack po ázijsky, nie európske sušienky.", "product_search", ["mochi", "Pocky", "ryžové krekry"], []),
        ("Chcem autentickú pastu do kórejského jedla.", "product_search", ["gochujang", "ssamjang"], []),
        ("Nechcem paradajkovú omáčku, chcem sójovú omáčku.", "product_search", ["sójová omáčka"], []),
        ("Chcem bezlepkovú omáčku k ryži.", "product_search", ["bezlepková sójová omáčka", "tamari"], []),
        ("Čo potrebujem na ľahké sushi bez európskych náhrad?", "related_products", ["sushi ryža", "nori", "ryžový ocot", "wasabi"], []),
        ("Čo potrebujem na pho, ak nechcem európsku polievku?", "related_products", ["ryžové rezance", "rybacia omáčka", "sriracha", "hoisin"], []),
        ("Čo potrebujem na jemné kari bez smotany?", "related_products", ["kokosové mlieko", "jazmínová ryža", "kari pasta"], []),
        ("Čo potrebujem na pad thai, nie európske cestoviny?", "related_products", ["ryžové rezance", "tamarind", "rybacia omáčka"], []),
        ("Čo potrebujem na bibimbap bez improvizácie?", "related_products", ["gochujang", "sezamový olej", "kimchi", "ryža"], []),
        ("Je tamari bezpečnejšia voľba pri lepku?", "allergen_safety", ["tamari"], ["overte", "zloženie"]),
        ("Je ryžový papier bez lepku?", "allergen_safety", ["ryžový papier"], ["overte", "zloženie"]),
        ("Je kokosové mlieko bez laktózy?", "allergen_safety", ["kokosové mlieko"], ["overte", "zloženie"]),
        ("Je miso pasta vhodná pri alergii na sóju?", "allergen_safety", ["miso"], ["overte", "zloženie"]),
        ("Je kimchi bezpečné pri alergii na ryby?", "allergen_safety", ["kimchi"], ["overte", "zloženie"]),
        ("Som celiak, čo k sushi kúpiť opatrne?", "dietary_filter", ["bezlepková sójová omáčka", "tamari", "nori", "sushi ryža"], ["overte"]),
        ("Som vegan a nechcem európske nátierky.", "dietary_filter", ["tofu", "nori", "wakame", "ryžové rezance"], []),
        ("Chcem nepálivé ázijské jedlo, európske mi nechutí.", "dietary_filter", ["mochi", "kokosové mlieko", "jazmínová ryža", "miso"], []),
        ("Chcem extra pálivé, ale nie sladké európske snacky.", "dietary_filter", ["sriracha", "gochujang", "sambal"], []),
        ("Hľadám snack pre dieťa, nie pálivé ázijské čipsy.", "dietary_filter", ["Pocky", "mochi", "ryžové krekry"], []),
        ("Ako mi doručíte ázijské potraviny, keď som mimo Bratislavy?", "faq", [], ["doručenie"]),
        ("Ako zaplatím, ak nechcem hotovosť?", "faq", [], ["kartou", "platba"]),
        ("Ako vrátim produkt, keď mi nesadne chuť?", "faq", [], ["vrátenie", "reklamácia"]),
        ("Viete mi poradiť európsku diétu od lekára?", "unknown", [], []),
        ("Napíšte mi zdravotný jedálniček na diagnózu.", "unknown", [], []),
    ]
    strict_suffixes = [
        "",
        " Odpovedzte veľmi presne.",
        " Nechcem náhodné produkty.",
        " Som prísny zákazník.",
        " Mám zlú skúsenosť s európskou stravou.",
        " Nechcem marketingové reči.",
        " Ukážte iba relevantné produkty.",
        " Ak neviete, priznajte limit.",
        " Pozor na alergény.",
        " Bez vymýšľania vlastností.",
        " Potrebujem to na reálny nákup.",
    ]
    for query, intent, expected_products, expected_answer in european_diet_conflict:
        for suffix in strict_suffixes:
            extra = {
                "expected_products_include": expected_products,
                "risk": "strict_european_diet_conflict",
                "must_not_invent": True,
            }
            if expected_answer:
                extra["expected_answer_include"] = expected_answer
            if intent in {"faq", "unknown"}:
                extra["expected_products_count"] = 0
            add_case(cases, query + suffix, intent, **extra)

    if len(cases) != 1000:
        raise RuntimeError(f"Expected 1000 cases, got {len(cases)}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as file:
        for case in cases:
            file.write(json.dumps(case, ensure_ascii=False) + "\n")

    print(json.dumps({"output": str(OUTPUT), "cases": len(cases)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
