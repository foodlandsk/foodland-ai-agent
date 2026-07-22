from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests" / "faq_delivery_payment_1000.jsonl"


def add_case(cases: list[dict], query: str, topic: str, expected_answer: list[str]) -> None:
    cases.append(
        {
            "id": f"FAQDP{len(cases) + 1:04d}",
            "query": query,
            "expected_intent": "faq",
            "expected_products_include": [],
            "expected_products_count": 0,
            "expected_answer_include": expected_answer,
            "source_section": "FAQ",
            "faq_topic": topic,
            "risk": "delivery_payment_faq_product_leakage",
        }
    )


def main() -> int:
    scenarios = [
        (
            "dopravcovia",
            [
                "Ktorá spoločnosť mi doručí objednávku?",
                "Aký kuriér vozí objednávky z Foodlandu?",
                "Cez koho posielate balíky?",
                "Kto mi prinesie zásielku domov?",
                "Robí doručenie DPD alebo GLS?",
                "Používate Packetu na doručenie?",
                "Ktorý prepravca doručuje mimo Bratislavy?",
                "Kto rozváža Foodland objednávky po Slovensku?",
                "Aká doručovacia firma privezie ázijské potraviny?",
                "Je možné doručenie cez kuriéra?",
            ],
            ["DPD", "GLS", "Packeta"],
        ),
        (
            "cas_dorucenia",
            [
                "Ako dlho trvá doručenie objednávky?",
                "Kedy mi príde balík, keď objednám dnes?",
                "Za koľko dní doručujete?",
                "Ako rýchlo posielate ázijské potraviny?",
                "Ak objednám doobeda, kedy to dorazí?",
                "Koľko trvá doprava na Slovensku?",
                "Koľko trvá doručenie cez Packetu?",
                "Ako dlho čakám na objednávku do Česka?",
                "Doručíte do 72 hodín?",
                "Kedy môžem očakávať zásielku?",
            ],
            ["72 hodín", "3 pracovných dní"],
        ),
        (
            "cena_dopravy",
            [
                "Koľko stojí doprava?",
                "Aká je cena poštovného?",
                "Kedy je doprava zadarmo?",
                "Od akej sumy mám dopravu zdarma?",
                "Platím poštovné pri objednávke nad 49 eur?",
                "Je doprava zdarma pre súkromného zákazníka?",
                "Koľko zaplatím za doručenie?",
                "Máte bezplatnú dopravu?",
                "Kedy neplatím za kuriéra?",
                "Je poštovné zadarmo nad 49 €?",
            ],
            ["49", "zadarmo"],
        ),
        (
            "krajiny",
            [
                "Do ktorých krajín doručujete?",
                "Posielate aj mimo Slovenska?",
                "Doručujete do Česka?",
                "Dá sa objednať do Maďarska?",
                "Vie Foodland poslať balík do Rakúska?",
                "Ako je to s doručením v rámci Európy?",
                "Doručuje Packeta aj mimo Slovenska?",
                "Kam všade posielate objednávky?",
                "Pošlete mi ázijské potraviny do zahraničia?",
                "Ktoré krajiny podporuje doručenie?",
            ],
            ["DPD", "GLS", "Packeta"],
        ),
        (
            "packeta",
            [
                "Ako funguje vyzdvihnutie na výdajnom mieste Packeta?",
                "Koľko dní mám na vyzdvihnutie Packety?",
                "Dostanem SMS pri doručení na Packetu?",
                "Máte výdajné miesta Packeta?",
                "Ako zistím, že je balík na výdajnom mieste?",
                "Koľko výdajných miest má Packeta?",
                "Dá sa poslať objednávka na Packetu?",
                "Aký je limit dobierky na Packetu?",
                "Môžem si balík vyzdvihnúť vo výdajnom mieste?",
                "Ako dlho drží Packeta zásielku?",
            ],
            ["Packeta", "7 dní", "700"],
        ),
        (
            "dobierka_doprava",
            [
                "Doručujete tovar domov aj s dobierkou?",
                "Dá sa platiť dobierkou kuriérovi?",
                "Môžem zaplatiť pri prevzatí balíka?",
                "Kuriér berie hotovosť?",
                "Dá sa pri kuriérovi platiť kartou?",
                "Ako funguje dobierka pri doručení?",
                "Môžem zaplatiť až keď príde balík?",
                "Je dobierka dostupná na Slovensku?",
                "Ktorý kuriér umožňuje dobierku?",
                "Platím dobierku priamo kuriérovi?",
            ],
            ["dobierkou", "kuriér"],
        ),
        (
            "osobny_odber",
            [
                "Môžem si objednávku vyzdvihnúť osobne?",
                "Máte osobný odber?",
                "Je osobný odber bez poštovného?",
                "Kde si môžem vyzdvihnúť tovar?",
                "Dá sa prísť do predajne v Bratislave?",
                "Na akej adrese je osobný odber?",
                "Musím platiť dopravu pri osobnom odbere?",
                "Vyzdvihnem si objednávku na Starej Vajnorskej?",
                "Kde je predajňa Foodland na odber?",
                "Môžem si balík prevziať v REMPO areáli?",
            ],
            ["Stará Vajnorská", "Bratislave"],
        ),
        (
            "platobne_metody",
            [
                "Aké spôsoby platby podporujete?",
                "Ako môžem zaplatiť objednávku?",
                "Dá sa platiť kartou online?",
                "Podporujete bankový prevod?",
                "Môžem zaplatiť cez PayPal?",
                "Máte GoPay alebo TatraPay?",
                "Čo je 24-Pay pri platbe?",
                "Aké platobné metódy má Foodland?",
                "Dá sa platiť v hotovosti?",
                "Môžem zaplatiť kartou pri osobnom odbere?",
            ],
            ["24-Pay", "GoPay", "PayPal"],
        ),
        (
            "bezpecnost_platby",
            [
                "Je platba cez 24-Pay bezpečná?",
                "Je online platba kartou bezpečná?",
                "Používate 3D Secure?",
                "Je bezpečné platiť kartou na Foodlande?",
                "Ako chránite platbu cez internet?",
                "Podporuje 24-Pay overenie bankou?",
                "Mám sa báť online platby?",
                "Je platobná brána dôveryhodná?",
                "Ako funguje bezpečnosť pri platbe kartou?",
                "Má 24-Pay podporu slovenských bánk?",
            ],
            ["3D Secure", "24-Pay"],
        ),
        (
            "platba_predajna",
            [
                "Môžem zaplatiť kartou priamo v predajni?",
                "Berie predajňa hotovosť?",
                "Ako zaplatím pri osobnom odbere?",
                "Dá sa v Bratislave platiť kartou?",
                "Pri vyzdvihnutí môžem platiť hotovosťou?",
                "Ak idem osobne, môžem použiť kartu?",
                "Platí sa pri osobnom odbere vopred?",
                "V predajni sa dá zaplatiť kartou?",
                "Aké platby sú možné na predajni?",
                "Môžem si vybrať platbu až na mieste?",
            ],
            ["kartou", "hotovosti"],
        ),
        (
            "objednavka",
            [
                "Ako môžem na Foodlande objednať tovar?",
                "Ako prebieha objednávka v e-shope?",
                "Musím vložiť produkty do košíka?",
                "Čo mám spraviť po výbere produktov?",
                "Ako dokončím nákup?",
                "Príde mi potvrdenie objednávky e-mailom?",
                "Potrebujem pri objednávke doručovaciu adresu?",
                "Ako zadám dopravu a platbu?",
                "Môžem objednať bez telefonátu?",
                "Aký je postup objednania?",
            ],
            ["košíka", "dopravy", "platby"],
        ),
        (
            "registracia",
            [
                "Musím sa pred objednaním registrovať?",
                "Dá sa nakúpiť bez registrácie?",
                "Potrebujem účet na objednávku?",
                "Je registrácia povinná?",
                "Aké výhody má registrácia?",
                "Môžem objednať ako hosť?",
                "Musím sa prihlásiť pred nákupom?",
                "Prečo sa oplatí registrovať?",
                "Ukladá registrácia doručovacie údaje?",
                "Dá sa spraviť opakovaná objednávka cez účet?",
            ],
            ["bez registrácie", "objednávať"],
        ),
        (
            "skladom",
            [
                "Ako zistím, či je konkrétny produkt skladom?",
                "Kde vidím dostupnosť produktu?",
                "Ukáže e-shop, či je to skladom?",
                "Ako overím väčšiu objednávku?",
                "Komu napísať pri firemnej objednávke?",
                "Kde zistím skladovosť?",
                "Je dostupnosť priamo pri produkte?",
                "Môžem sa opýtať na sklad pri väčšom odbere?",
                "Ako zistím, či máte veľké balenie skladom?",
                "Vidím skladom stav na Foodlande?",
            ],
            ["Dostupnosť", "e-shope"],
        ),
        (
            "poskodeny_tovar",
            [
                "Ako postupovať, ak mi prišiel poškodený produkt?",
                "Prišiel mi rozbitý balík, čo mám robiť?",
                "Kam poslať fotku poškodeného tovaru?",
                "Na aký e-mail riešim reklamáciu poškodenia?",
                "Čo ak je produkt po doručení poškodený?",
                "Mám poškodený tovar z objednávky.",
                "Komu napísať pri rozliatej omáčke v balíku?",
                "Potrebujete číslo objednávky pri reklamácii?",
                "Ako reklamovať poškodenú zásielku?",
                "Čo priložiť k reklamácii poškodenia?",
            ],
            ["reklamacie@foodland.sk", "fotografiu"],
        ),
        (
            "chybajuci_tovar",
            [
                "V balíku mi chýba produkt, čo mám robiť?",
                "Nedorazila mi jedna položka z objednávky.",
                "Kam nahlásim chýbajúci produkt?",
                "Do koľkých dní mám riešiť chýbajúci tovar?",
                "Čo ak v zásielke niečo chýba?",
                "Objednávka nebola kompletná.",
                "Mám nahlásiť chýbajúci produkt do 3 dní?",
                "Na koho sa obrátiť pri nekompletnej objednávke?",
                "Chýba mi ryža v balíku, kam písať?",
                "Ako reklamovať neúplný balík?",
            ],
            ["3 dní", "reklamacie@foodland.sk"],
        ),
        (
            "iny_tovar",
            [
                "Dostal som iný produkt, než som si objednal. Ako postupovať?",
                "Prišiel mi nesprávny produkt.",
                "Čo ak Foodland poslal inú položku?",
                "Objednal som ryžu, prišlo niečo iné.",
                "Ako riešiť zámenu tovaru?",
                "Komu napísať pri nesprávnom produkte?",
                "Potrebujete číslo objednávky pri zámene?",
                "Dá sa vymeniť omylom doručený produkt?",
                "Prišiel iný tovar v balíku.",
                "Ako nahlásim rozdiel v objednávke?",
            ],
            ["číslo objednávky", "výmenu"],
        ),
        (
            "reklamacia_cas",
            [
                "Ako dlho trvá vybavenie reklamácie?",
                "Kedy odpoviete na reklamáciu?",
                "Do koľkých dní riešite reklamáciu?",
                "Ako rýchlo reagujete na poškodený tovar?",
                "Koľko trvá reklamácia objednávky?",
                "Kedy dostanem odpoveď na reklamáciu?",
                "Má Foodland lehotu na reklamáciu?",
                "Reklamoval som balík, ako dlho čakám?",
                "Do 3 pracovných dní sa ozvete?",
                "Ako dlho trvá preverenie reklamácie?",
            ],
            ["3 pracovných dní"],
        ),
        (
            "vratenie",
            [
                "Môžem vrátiť tovar bez udania dôvodu?",
                "Do koľkých dní môžem odstúpiť od zmluvy?",
                "Dá sa vrátiť objednávka?",
                "Mám 14 dní na vrátenie?",
                "Ako funguje vrátenie tovaru?",
                "Môžem vrátiť nechcený produkt?",
                "Platí odstúpenie pre spotrebiteľa?",
                "Ako riešim vrátenie bez dôvodu?",
                "Koľko dní mám na odstúpenie?",
                "Môžem poslať tovar späť?",
            ],
            ["14 dní", "odstúpiť"],
        ),
        (
            "co_nevratit",
            [
                "Aký tovar nie je možné vrátiť?",
                "Dá sa vrátiť otvorený produkt?",
                "Môžem vrátiť potravinu s porušeným obalom?",
                "Čo sa nedá vrátiť z hygienických dôvodov?",
                "Môžem vrátiť rozbalenú omáčku?",
                "Sú potraviny s otvoreným obalom vratné?",
                "Aké výnimky má vrátenie tovaru?",
                "Môžem vrátiť poškodený obal?",
                "Kedy Foodland neakceptuje vrátenie?",
                "Čo ak som produkt už otvoril?",
            ],
            ["hygienických", "porušeným obalom"],
        ),
        (
            "firemna_doprava",
            [
                "Platí doprava zadarmo aj pre firemných zákazníkov?",
                "Mám firmu, mám dopravu zdarma nad 49 eur?",
                "Ako je to s IČO a dopravou zdarma?",
                "Firemná objednávka má poštovné zadarmo?",
                "Prečo firma nemá dopravu zdarma nad 49 €?",
                "Čo treba pri firemnej registrácii?",
                "Ak objednávam na firmu, platí iná doprava?",
                "Doprava zdarma je len pre súkromné osoby?",
                "Ako funguje doprava pri firemnom účte?",
                "Potrebujem názov spoločnosti a IČO?",
            ],
            ["firemn", "49"],
        ),
    ]

    prefixes = [
        "",
        "Prosím, ",
        "Dobrý deň, ",
        "Odpovedzte stručne: ",
        "Neukazujte produkty, iba info: ",
        "Som nový zákazník, ",
        "Potrebujem rýchlu odpoveď, ",
        "Len prakticky, ",
        "Pred objednávkou: ",
        "Na mobile sa pýtam: ",
    ]

    suffixes = [
        "",
        " Ďakujem.",
        " Bez produktových odporúčaní.",
        " Potrebujem presnú informáciu.",
        " Nechcem marketing.",
        " Ide mi o objednávku na Foodland.sk.",
        " Pýtam sa pred nákupom.",
        " Stačí krátka odpoveď.",
        " Nechcem náhodné produkty.",
        " Prosím po slovensky.",
    ]

    cases: list[dict] = []
    for topic, questions, expected_answer in scenarios:
        for question in questions:
            for prefix in prefixes:
                for suffix in suffixes:
                    if len(cases) >= 1000:
                        break
                    add_case(cases, f"{prefix}{question}{suffix}", topic, expected_answer)
                if len(cases) >= 1000:
                    break
            if len(cases) >= 1000:
                break
        if len(cases) >= 1000:
            break

    if len(cases) != 1000:
        raise RuntimeError(f"Expected 1000 cases, got {len(cases)}")

    OUTPUT.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(OUTPUT.relative_to(ROOT)), "cases": len(cases)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
