"""
tests/test_taxonomy_v23.py  -  Sprint V2.3 taxonomy expansion: sauces,
pastes, curry paste, coconut products, oils, expanded noodles, instant
food, tea, seaweed, frozen dumplings.

Every fixture below is grounded in a real title/category pair pulled from
the live Foodland Merchant feed at the time of this sprint (not invented
examples) - see docs/product-taxonomy-audit.md for the full evidence.
Covers the required collision/negative tests: soy sauce vs black bean
sauce/teriyaki/hoisin (all cross-listed under "Sójové omáčky"), coconut
milk vs coconut water vs coconut jelly, miso paste vs miso soup, nori vs
wakame vs kelp, curry paste vs chili paste, yakisoba vs soba, instant
noodles vs instant soup.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.feed import Product
from app.taxonomy import classify_product


def make_product(**overrides) -> Product:
    base = dict(
        id="FL_TEST", title="", description="", product_type="", link="",
        image_link="", price=None, sale_price=None, currency="EUR", brand="",
        availability="in_stock", gtin="", unit_pricing_measure="",
    )
    base.update(overrides)
    return Product(**base)


class TestSauceFamily:
    def test_soy_sauce(self):
        p = make_product(title="Bezlepková sójová omáčka MEGACHEF 200 ml", product_type="Zdravé potraviny > Bezlepkové potraviny > Sójové omáčky > Omáčky a marinády")
        tax = classify_product(p)
        assert tax.canonical_family == "sauce"
        assert tax.canonical_subfamily == "soy_sauce"

    def test_dark_soy_sauce_variety(self):
        p = make_product(title="MARUKIN Tmavá sójová omáčka KOIKUCHI 1000ml", product_type="Sójové omáčky > Omáčky a marinády")
        tax = classify_product(p)
        assert tax.canonical_family == "sauce"
        assert tax.attributes.get("style") == "dark"

    def test_oyster_sauce(self):
        p = make_product(title="Ustricová omáčka LEE KUM KEE PANDA 255ml", product_type="Zdravé potraviny > Bezlepkové potraviny > Ustricové omáčky > Omáčky a marinády")
        tax = classify_product(p)
        assert tax.canonical_family == "sauce"
        assert tax.canonical_subfamily == "oyster_sauce"
        assert tax.confidence == "HIGH"

    def test_fish_sauce(self):
        p = make_product(title="Rybacia omáčka Nam Ngu CHIN-SU 750ml", product_type="Bezlepkové potraviny > Rybacie omáčky > Omáčky a marinády")
        tax = classify_product(p)
        assert tax.canonical_family == "sauce"
        assert tax.canonical_subfamily == "fish_sauce"

    def test_hoisin_sauce(self):
        p = make_product(title="Hoisin omáčka LEE KUM KEE 397g", product_type="Hoisin omáčky > Omáčky a marinády")
        tax = classify_product(p)
        assert tax.canonical_subfamily == "hoisin_sauce"

    def test_teriyaki_sauce(self):
        p = make_product(title="Teriyaki omáčka DEK SOM BOON 250 ml", product_type="Teriyaki omáčky > Sójové omáčky > Omáčky a marinády")
        tax = classify_product(p)
        assert tax.canonical_subfamily == "teriyaki_sauce"

    def test_sriracha(self):
        p = make_product(title="Čili omáčka Sriracha COCK BRAND 490g", product_type="Sriracha čili omáčky > Čili omáčky > Omáčky a marinády")
        tax = classify_product(p)
        assert tax.canonical_family == "sauce"
        assert tax.attributes.get("variety") == "sriracha"


class TestSauceCollisions:
    """Section 45/72: all cross-listed under 'Sójové omáčky' but must
    resolve to distinct subfamilies - the exact class of bug the rice
    pilot's collision guards were designed to prevent, now generalized."""

    def test_soy_black_bean_teriyaki_hoisin_all_distinct(self):
        cases = [
            ("Double Deluxe sójová omáčka LEE KUM KEE 500ml", "soy_sauce"),
            ("Čierna fazuľa omáčka LEE KUM KEE 226 g", "black_bean"),
            ("Teriyaki omáčka bezlepková LEE KUM KEE 368 g", "teriyaki_sauce"),
        ]
        results = []
        for title, expected in cases:
            p = make_product(title=title, product_type="Sójové omáčky > Omáčky a marinády")
            tax = classify_product(p)
            results.append((title, tax.canonical_subfamily, expected))
        for title, actual, expected in results:
            assert actual == expected, title
        assert len({r[1] for r in results}) == 3

    def test_black_bean_sauce_vs_black_bean_paste(self):
        sauce = make_product(title="Čierna fazuľa cesnak omáčka LEE KUM KEE 368 g")
        paste = make_product(title="Čierna fazuľa pasta Jjajang ASSI 500g")
        tax_sauce = classify_product(sauce)
        tax_paste = classify_product(paste)
        assert tax_sauce.canonical_family == "sauce"
        assert tax_paste.canonical_family == "paste"

    def test_generic_soy_sauce_not_confused_with_unrelated_sojove_omacky_products(self):
        # "Poké omáčka"/"Omáčka Unagi"/dumpling sauce all live in the same
        # "Sójové omáčky" category but are not soy sauce by title identity -
        # must not force-classify via category alone (Section 6/58).
        for title in ("Poké omáčka AYUKO 150ml", "Omáčka Unagi YUMMYTO 200 ml", "Omáčka na dumpling LEE KUM KEE 207 ml"):
            p = make_product(title=title, product_type="Sójové omáčky > Omáčky a marinády")
            tax = classify_product(p)
            assert tax.canonical_subfamily != "soy_sauce", title

    def test_chili_paste_not_chili_sauce(self):
        p = make_product(title="Čili pasta so sójovým olejom PANTAI 500g", product_type="Zdravé potraviny > Bezlepkové potraviny > Pasty korenia > Čili omáčky > Koreniny a ochucovadlá > Omáčky a marinády")
        tax = classify_product(p)
        assert tax.canonical_subfamily != "chili_sauce"

    def test_chili_oil_not_chili_sauce(self):
        p = make_product(title="Čili v sójovom oleji LAO GAN MA 210 g", product_type="Zdravé potraviny > Bezlepkové potraviny > Zmes korenia a ochucovadlá > Čili omáčky > Koreniny a ochucovadlá > Omáčky a marinády")
        tax = classify_product(p)
        assert tax.canonical_subfamily != "chili_sauce"


class TestCurryPaste:
    def test_curry_paste_classified_via_category_when_no_variety_keyword(self):
        # No red/green/massaman/panang keyword in the title - falls through
        # to the generic category-backed rule, HIGH confidence, no variety.
        p = make_product(title="GOLDEN CURRY Extra Hot – Japonské kari S&B 220g", product_type="Vegetariánske potraviny > Zdravé potraviny > Kari pasty > Koreniny a ochucovadlá")
        tax = classify_product(p)
        assert tax.canonical_family == "curry_paste"
        assert tax.confidence == "HIGH"
        assert "variety" not in tax.attributes

    def test_curry_paste_variety_match_is_medium_confidence(self):
        # Variety rules are title-only by design (Section 44/58 - a shared
        # category can't distinguish red/green/massaman/panang), so a
        # variety match is honestly MEDIUM even though family=curry_paste
        # is correct either way.
        p = make_product(title="Červená kari pasta COCK BRAND 400g", product_type="Vegánske potraviny > Vegetariánske potraviny > Zdravé potraviny > Bezlepkové potraviny > Kari pasty > Koreniny a ochucovadlá")
        tax = classify_product(p)
        assert tax.canonical_family == "curry_paste"
        assert tax.confidence == "MEDIUM"
        assert tax.attributes.get("variety") == "red"

    def test_variety_extraction(self):
        cases = [
            ("Červená kari pasta COCK BRAND 400g", "red"),
            ("Kari pasta Massaman COCK BRAND 400g", "massaman"),
            ("Kari pasta Panang COCK BRAND 1000g", "panang"),
        ]
        for title, expected_variety in cases:
            p = make_product(title=title, product_type="Kari pasty > Koreniny a ochucovadlá")
            tax = classify_product(p)
            assert tax.attributes.get("variety") == expected_variety, title


class TestFermentedPastes:
    def test_miso_paste(self):
        p = make_product(title="Miso Pasta Červená HIKARI 400g", product_type="Pasty korenia > Koreniny a ochucovadlá")
        tax = classify_product(p)
        assert tax.canonical_family == "paste"
        assert tax.canonical_subfamily == "miso"

    def test_miso_soup_not_miso_paste(self):
        p = make_product(title="AKA MISO polievka prášok s tofu LOBO 30g", product_type="Japonské > Hotové jedlá > Balíčky na prípravu jedál > Instantné polievky")
        tax = classify_product(p)
        assert tax.canonical_subfamily != "miso"

    def test_gochujang(self):
        p = make_product(title="Čili pasta GOCHUJANG SEMPIO 500g", product_type="Super potraviny > Vegetariánske potraviny > Zdravé potraviny > Pasty korenia > Koreniny a ochucovadlá")
        tax = classify_product(p)
        assert tax.canonical_family == "paste"
        assert tax.canonical_subfamily == "gochujang"

    def test_kimchi_is_not_a_paste(self):
        # Section 24: kimchi must never be swept into the paste family.
        p = make_product(title="Kimchi základ KIKKOMAN 1180g", product_type="Marinády > Omáčky a marinády")
        tax = classify_product(p)
        assert tax.canonical_family != "paste"


class TestCoconutProducts:
    def test_coconut_milk(self):
        p = make_product(title="Kokosové mlieko AROY-D 400 ml", product_type="Kokosové mlieko > Mlieko a mliečné výrobky > Kokosové mlieko a krémy > Kokosové produkty")
        tax = classify_product(p)
        assert tax.canonical_family == "coconut_product"
        assert tax.canonical_subfamily == "coconut_milk"
        assert tax.confidence == "HIGH"

    def test_coconut_water(self):
        p = make_product(title="Kokosová voda 100% naturálna FOCO 1000 ml", product_type="Kokosový nápoj > Ovocné džúsy > Ázijské nápoje > Kokosové produkty")
        tax = classify_product(p)
        assert tax.canonical_subfamily == "coconut_water"

    def test_coconut_milk_vs_coconut_water_distinct(self):
        milk = make_product(title="Kokosové mlieko AROY-D 400 ml", product_type="Kokosové mlieko a krémy > Kokosové produkty")
        water = make_product(title="Kokosová voda BAMBOO TREE 1000 ml", product_type="Kokosový nápoj > Kokosové produkty")
        assert classify_product(milk).canonical_subfamily != classify_product(water).canonical_subfamily

    def test_coconut_jelly_dessert_not_coconut_milk_or_water(self):
        # Real product genuinely ambiguous (milk-and-jelly dessert drink) -
        # must stay UNKNOWN rather than force one identity (Section 40/99).
        p = make_product(
            title="Kokosové mlieko s kokosovým želé - Ananásová príchuť COCO ROYAL 290ml",
            product_type="Kokosové mlieko > Super potraviny > Zdravé potraviny > Nealkoholické nápoje > Kokosový nápoj > Ázijské nápoje > Kokosové produkty",
        )
        tax = classify_product(p)
        assert tax.canonical_subfamily not in ("coconut_milk", "coconut_water")


class TestOils:
    def test_sesame_oil(self):
        p = make_product(title="Sezamový olej 100% LEE KUM KEE 207 ml", product_type="Sezamový olej > Vegetariánske potraviny > Zdravé potraviny > Olej a maslo > Olej na dochucovanie > Koreniny a ochucovadlá")
        tax = classify_product(p)
        assert tax.canonical_family == "oil"
        assert tax.canonical_subfamily == "sesame_oil"
        assert tax.confidence == "HIGH"


class TestNoodlesExpansion:
    def test_wheat_noodles(self):
        p = make_product(title="Čínske rezance THAI DANCER 400g", product_type="Pšeničné rezance > Rezance, niťovky a cestoviny")
        tax = classify_product(p)
        assert tax.canonical_family == "noodles"
        assert tax.canonical_subfamily == "wheat_noodles"

    def test_soba_noodles(self):
        p = make_product(title="Soba pohánkové cestoviny japonské EAGLOBE 300g", product_type="Pohánkové rezance > Pšeničné rezance > Rezance, niťovky a cestoviny")
        tax = classify_product(p)
        assert tax.canonical_subfamily == "soba"
        assert tax.confidence == "HIGH"

    def test_yakisoba_not_soba(self):
        # "Yakisoba" contains "soba" as a bare substring but is a distinct
        # wheat-noodle dish/sauce, not buckwheat soba (Section 44/45).
        sauce = make_product(title="Yakisoba omáčka na rezance OTAFUKU 300g")
        noodles = make_product(title="Yakisoba Japonské stir-fry rezance s omáčkou OTAFUKU 370g")
        assert classify_product(sauce).canonical_subfamily != "soba"
        assert classify_product(noodles).canonical_subfamily != "soba"

    def test_rice_noodles_still_distinct_from_wheat_noodles(self):
        # V2.1 collision invariant must survive V2.3 expansion.
        rice_noodles = make_product(title="Ryžové rezance BAMBOO TREE 400g", product_type="Ryžové rezance > Rezance, niťovky a cestoviny")
        wheat_noodles = make_product(title="Čínske rezance THAI DANCER 400g", product_type="Pšeničné rezance > Rezance, niťovky a cestoviny")
        assert classify_product(rice_noodles).canonical_subfamily == "rice_noodles"
        assert classify_product(wheat_noodles).canonical_subfamily == "wheat_noodles"


class TestInstantFood:
    def test_instant_noodles(self):
        p = make_product(title="INDOMIE Instantné vypražené rezance Mi Goreng 80g", product_type="Instantné polievky")
        tax = classify_product(p)
        assert tax.canonical_family == "instant_food"
        assert tax.canonical_subfamily == "instant_noodles"

    def test_instant_soup(self):
        p = make_product(title="BUN BO HUE Instantná hovädzia polievka VIFON 65g", product_type="Vietnamské > Balíčky na prípravu jedál > Instantné polievky")
        tax = classify_product(p)
        assert tax.canonical_subfamily == "instant_soup"

    def test_instant_noodles_vs_instant_soup_distinct(self):
        noodles = make_product(title="CHOI'S Kórejské ramyeon rezance Spicy 112,5g", product_type="Kórejské > Instantné polievky")
        soup = make_product(title="Cung Dinh instantná polievka kuracia 79 g", product_type="Vietnamské > Instantné polievky")
        assert classify_product(noodles).canonical_subfamily == "instant_noodles"
        assert classify_product(soup).canonical_subfamily == "instant_soup"

    def test_soup_labeled_noodle_product_stays_soup(self):
        # Explicitly labeled "polievka" wins over the presence of "rezance"
        # in the same title - it is a ready-to-eat soup, not raw noodles.
        p = make_product(title="CHAM PONG RAMYUN instantná rezancová polievka 124g", product_type="Kórejské > Balíčky na prípravu jedál > Instantné polievky")
        tax = classify_product(p)
        assert tax.canonical_subfamily == "instant_soup"


class TestTea:
    def test_tea_classified(self):
        p = make_product(title="Čierny čaj Ceylon 100 % čistý čaj Cozy 1000g", product_type="Sušené produkty > Vegánske potraviny > Vegetariánske potraviny > BIO potraviny > Zdravé potraviny > Čaj")
        tax = classify_product(p)
        assert tax.canonical_family == "tea"
        assert tax.confidence == "HIGH"


class TestSeaweed:
    def test_nori(self):
        p = make_product(title="Morské riasy Yaki nori na Kimbap GIMBAPGIM NBH 10 listov", product_type="Super potraviny > Zdravé potraviny > Morské riasy > Sushi ingrediencie")
        tax = classify_product(p)
        assert tax.canonical_family == "seaweed"
        assert tax.canonical_subfamily == "nori"

    def test_wakame(self):
        p = make_product(title="Wakame sušené morské riasy INAKA 300g", product_type="Sušené produkty > Super potraviny > Zdravé potraviny > Morské riasy > Sušená zelenina")
        tax = classify_product(p)
        assert tax.canonical_subfamily == "wakame"

    def test_kelp_is_neither_nori_nor_wakame(self):
        # Real product: kelp/kombu lives in the same "Morské riasy" category
        # as nori and wakame but is a distinct seaweed identity - must not
        # be swept into either (Section 31/58).
        p = make_product(title="Dashima Konbu sušený kelp WANG KOREA 56g", product_type="Morské riasy > Sushi ingrediencie")
        tax = classify_product(p)
        assert tax.canonical_subfamily not in ("nori", "wakame")

    def test_nori_and_wakame_distinct(self):
        nori = make_product(title="Morské riasy SUSHINORI GOLD HUTAKU 50 listov, 140g", product_type="Morské riasy")
        wakame = make_product(title="Morské riasy Wakame rezané a sušené HUTAKU 300g", product_type="Morské riasy")
        assert classify_product(nori).canonical_subfamily == "nori"
        assert classify_product(wakame).canonical_subfamily == "wakame"


class TestFrozenFood:
    def test_gyoza(self):
        p = make_product(title="Gyoza knedlíky Bravčové a zelenina CJ BIBIGO 600g", product_type="Mrazené hotové jedlá > Mrazené potraviny > Hotové jedlá > Balíčky na prípravu jedál")
        tax = classify_product(p)
        assert tax.canonical_family == "frozen_food"
        assert tax.canonical_subfamily == "dumplings"

    def test_unrelated_frozen_products_not_classified_as_dumplings(self):
        # Section 53/58 purity gate: "Mrazené potraviny" is a broad frozen-
        # food category covering squid, mochi ice cream, edamame etc - none
        # of these are dumplings and must not be swept in via category alone.
        for title in ("Celé kalamáre EMERALD 1000g", "BUONO Mochi Ice Mango 156 g", "Edamame - Sójové struky zmrazené ASIAN CHOICE 500g"):
            p = make_product(title=title, product_type="Mrazené potraviny")
            tax = classify_product(p)
            assert tax.canonical_family != "frozen_food", title


class TestUnknownStillDiscoverable:
    """Section 46/70/99: taxonomy expansion must never regress UNKNOWN
    fallback for products with no matching family."""

    def test_tofu_remains_unknown(self):
        # Deliberately NOT implemented this sprint (weak/inconsistent
        # catalog evidence, see docs/product-taxonomy-audit.md) - must
        # honestly report UNKNOWN, not a forced guess.
        p = make_product(title="Nakladané tofu Thuan Phat 510g", product_type="Zdravé potraviny > Bezlepkové potraviny > Konzervované produkty")
        tax = classify_product(p)
        assert tax.canonical_family is None
        assert tax.confidence == "UNKNOWN"

    def test_wasabi_remains_unknown(self):
        # Deliberately NOT implemented - "wasabi" title matches were mostly
        # wasabi-FLAVOURED snacks and a tableware product line name, not the
        # actual condiment (Section 40 - title/category didn't agree).
        p = make_product(title="Krekry wasabi mix GOLDEN TURTLE 150g", product_type="Krekry a snacky > Sladkosti a občerstvenie")
        tax = classify_product(p)
        assert tax.canonical_family is None
