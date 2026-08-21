"""
app/taxonomy.py  -  V2 catalog-first product taxonomy (Phase 5-6): rice family

Rice is the first canonical family selected for implementation, per
docs/product-taxonomy-audit.md (mandatory first taxonomy run). Selected on
real catalog evidence, not example text from a prompt: at least 7 distinct
sub-families share the "ryz*" linguistic root (plain rice, sushi rice,
rice noodles, rice vinegar, rice flour, rice paper, rice cookers - the
last of which has its own real catalog category, "Ryžovary"), this exact
collision class caused repeated production bugs (roadmap Sprint Z.6), and
app/main.py's SPECIAL_PRODUCT_QUERIES already has partial coverage
(plain_rice, sushi_rice, rice_vinegar, rice_cooker, rice_seasoning,
rice_side) to build on rather than replace.

Rollout stage (Phase 16): Stage A, shadow/observation mode only.
classify_rice_query() is wired into /chat purely for analytics logging
(see log_taxonomy_shadow() in app/main.py) - it does not change any
routing decision, product selection, or answer text. Nothing here is a
manually maintained per-SKU mapping (Phase 12): classification runs over
message/title text via a small, reusable phrase table, not a list of
product IDs.

Sprint V2.1 (Feed Foundation / Product Normalization / Taxonomy Engine)
extends this module with a second, distinct classifier: classify_product()
and build_taxonomy_index() operate on catalog PRODUCTS (category
memberships + title + URL), not on customer message text, and produce a
real canonical_family per product (family != word root - a rice cooker's
family is "kitchenware", not "rice"). See the "PRODUCT-LEVEL TAXONOMY
ENGINE" section below. classify_rice_query() above is unchanged and keeps
its original message-classification meaning.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Iterable

from app.feed import Product
from app.product_normalizer import extract_url_category
from app.search import normalize as search_normalize

logger = logging.getLogger(__name__)


@dataclass
class TaxonomyMatch:
    family: str = "rice"
    subfamily: str | None = None
    confidence: str = "NONE"  # HIGH / MEDIUM / LOW / NONE
    matched_phrase: str | None = None


# Subfamily detection phrases, most specific first - the same
# collision-ordering discipline already used for RELATED_SUBJECT_ALIASES
# in app/main.py (e.g. "gyudon" checked before "udon"). Compound phrases
# for the six non-generic subfamilies are checked before the bare grain
# itself ("plain_rice"), since every one of them shares the "ryz*" root
# with it.
RICE_SUBFAMILY_PHRASES: dict[str, tuple[str, ...]] = {
    "rice_cooker": ("ryzovar", "hrniec na ryzu", "rice cooker"),
    "rice_vinegar": ("ryzovy ocot", "ryzoveho octu", "ryzovym octom", "rice vinegar"),
    "rice_flour": ("ryzova muka", "ryzovu muku", "ryzovej muky", "muka z ryze", "muka z lepkavej ryze", "rice flour"),
    "rice_paper": ("ryzovy papier", "rice paper"),
    "rice_noodles": ("ryzove rezance", "ryzovych rezancov", "ryzovymi rezancami", "rice noodles"),
    "sushi_rice": ("sushi ryza", "susi ryza", "ryza na sushi", "ryzu na sushi", "sushi rice"),
    "rice_drink": ("ryzovy napoj", "rice drink"),
    "plain_rice": ("ryza", "ryzu", "ryze", "ryzou", "ryzova", "ryzi"),
}

RICE_SUBFAMILY_CONFIDENCE: dict[str, str] = {
    "rice_cooker": "HIGH",
    "rice_vinegar": "HIGH",
    "rice_flour": "HIGH",
    "rice_paper": "HIGH",
    "rice_noodles": "HIGH",
    "sushi_rice": "HIGH",
    "rice_drink": "MEDIUM",
    "plain_rice": "HIGH",
}


def classify_rice_query(message: str, normalize: Callable[[str], str]) -> TaxonomyMatch:
    """Shadow-mode rice-family classifier.

    `normalize` is injected (pass app.search.normalize) to avoid a
    circular import between this module and app.main/app.search.
    """
    normalized = f" {normalize(message)} "
    for subfamily, phrases in RICE_SUBFAMILY_PHRASES.items():
        for phrase in phrases:
            if phrase in normalized:
                # "aku ryzu odporucas na sushi?" names plain rice and the
                # sushi use-case as separate words, not the compound
                # "sushi ryza" phrase - IntentMapping's verified "Ryža /
                # výber produktu" entry for this exact question says to
                # prefer sushi rice, so treat rice+sushi co-occurrence the
                # same as the compound phrase.
                if subfamily == "plain_rice" and any(t in normalized for t in (" sushi ", " susi ")):
                    return TaxonomyMatch(
                        family="rice",
                        subfamily="sushi_rice",
                        confidence="HIGH",
                        matched_phrase=f"{phrase.strip()}+sushi",
                    )
                return TaxonomyMatch(
                    family="rice",
                    subfamily=subfamily,
                    confidence=RICE_SUBFAMILY_CONFIDENCE[subfamily],
                    matched_phrase=phrase.strip(),
                )
    return TaxonomyMatch(family="rice", subfamily=None, confidence="NONE", matched_phrase=None)


# ===========================================================================
# V2.1 PRODUCT-LEVEL TAXONOMY ENGINE
# ===========================================================================
#
# `classify_rice_query()` above answers "does this MESSAGE mention the rice
# linguistic cluster?" for shadow analytics - it always reports family="rice"
# even for a rice cooker or rice vinegar query, because it is grouping
# *query text* by shared root, not classifying a *product's identity*.
#
# The engine below answers a different question: "what IS this catalog
# PRODUCT?" Family ≠ word root is a mandatory invariant here
# (docs/product-taxonomy-audit.md): a rice cooker's canonical_family is
# "kitchenware", not "rice", even though both classifiers key off the same
# "ryz*" vocabulary. Do not conflate the two - they serve different
# consumers (message-level shadow logging vs. per-product structured data).
#
# Deterministic, data-driven, no LLM calls. Rules are ordered most-specific
# first (rice_cooker/rice_paper/rice_noodles/... before generic plain rice)
# so a compound concept is never swallowed by the bare grain rule it shares
# a root with - the same collision-ordering discipline already used above
# for RICE_SUBFAMILY_PHRASES.

TAXONOMY_VERSION = 1

CONFIDENCE_LEVELS = ("HIGH", "MEDIUM", "LOW", "UNKNOWN")

_CONFIDENCE_DOWNGRADE = {"HIGH": "MEDIUM", "MEDIUM": "LOW", "LOW": "LOW"}


class CategoryRole:
    """Reusable role vocabulary for a single category_memberships[] entry.

    Not every membership resolves to a known role - UNKNOWN is legitimate
    and expected (recurring UNKNOWN memberships become input for a future
    V2 taxonomy iteration, docs/product-taxonomy-audit.md).
    """

    PRODUCT_FAMILY = "PRODUCT_FAMILY"
    PRODUCT_SUBFAMILY = "PRODUCT_SUBFAMILY"
    VARIETY = "VARIETY"
    DIETARY_FACET = "DIETARY_FACET"
    CUISINE_FACET = "CUISINE_FACET"
    USE_CASE = "USE_CASE"
    COMMERCIAL_FACET = "COMMERCIAL_FACET"
    MERCHANDISING_FACET = "MERCHANDISING_FACET"
    UNKNOWN = "UNKNOWN"


# Cross-referential dietary/merchandising labels that show up as *category
# memberships* across many unrelated families (Fáza 1 of the catalog audit:
# "Vegánske potraviny", "Zdravé potraviny" etc. dominate by count but say
# nothing about product identity). Roled as facets, never as canonical_family.
_DIETARY_CATEGORY_TERMS = {
    "veganske potraviny": "vegan",
    "vegetarianske potraviny": "vegetarian",
    "bezlepkove potraviny": "gluten_free",
    "bio potraviny": "organic",
}
_MERCHANDISING_CATEGORY_TERMS = {
    "zdrave potraviny": "healthy_food",
    "super potraviny": "superfood",
    "vypredaj": "clearance",
}

# Two catalog category labels observed for the same sushi-rice product set
# (docs/product-taxonomy-audit.md, canonical aliases). Deterministic,
# testable, no LLM - both normalize (app.search.normalize) to distinct
# strings but must resolve to the same taxonomy signal.
CATEGORY_ALIASES: dict[str, str] = {
    "ryza na susi (sushi)": "sushi_rice_category",
    "susi ryza": "sushi_rice_category",
}


@dataclass(frozen=True, slots=True)
class FamilyRule:
    """One data-driven classification rule. Evaluated in list order - the
    engine stops at the first rule that matches (most specific first)."""

    rule_id: str
    family: str
    subfamily: str | None
    confidence: str  # applied when matched via category evidence
    category_terms: tuple[str, ...] = ()  # normalized; matched against category_memberships (+ aliases)
    title_phrases: tuple[str, ...] = ()  # normalized; matched as substrings of the normalized title
    exclude_title_phrases: tuple[str, ...] = ()  # V2.3 collision guard: any hit here disqualifies this rule
    attributes: tuple[tuple[str, str], ...] = ()
    display_label: str = ""  # Slovak concept name (V2.2 autocomplete), e.g. "Jazmínová ryža"


# Rice pilot family (Sprint V2.1) - every rule grounded in real
# data/products.json / live-feed category paths and titles, not invented
# examples (see docs/product-taxonomy-audit.md for the evidence). Ordered
# so every rice-root collision (rezance/ocot/muka/papier/ryzovar/napoj/vino)
# is resolved BEFORE the generic bare-grain rule at the bottom.
FAMILY_DEFINITIONS: list[FamilyRule] = [
    FamilyRule(
        rule_id="rice_cooker",
        family="kitchenware",
        subfamily="rice_cooker",
        confidence="HIGH",
        category_terms=("ryzovary",),
        title_phrases=("ryzovar", "hrniec na ryzu"),
        attributes=(("object_type", "rice_cooker"),),
        display_label="Ryžovar",
    ),
    FamilyRule(
        rule_id="rice_paper",
        family="rice_paper",
        subfamily=None,
        confidence="HIGH",
        category_terms=("ryzovy papier",),
        title_phrases=("ryzovy papier",),
        display_label="Ryžový papier",
    ),
    FamilyRule(
        rule_id="rice_noodles",
        family="noodles",
        subfamily="rice_noodles",
        confidence="HIGH",
        category_terms=("ryzove rezance",),
        # "banh pho" (V2.14d) - the Vietnamese name for this exact noodle,
        # already present on real catalog products in this category (e.g.
        # "Ryzove rezance siroke Banh Pho BAMBOO TREE") so classify_product()
        # already resolves those products HIGH via category - this phrase
        # only closes the QUERY-side gap (recipe_graph's pho ingredient
        # list uses this name and had no title_phrase to match against).
        title_phrases=("ryzove rezance", "ryzovymi rezancami", "ryzovych rezancov", "rice noodles", "banh pho"),
        attributes=(("ingredient_base", "rice"),),
        display_label="Ryžové rezance",
    ),
    FamilyRule(
        rule_id="rice_vinegar",
        family="vinegar",
        subfamily="rice_vinegar",
        confidence="HIGH",
        title_phrases=("ryzovy ocot",),
        attributes=(("source", "rice"),),
        display_label="Ryžový ocot",
    ),
    FamilyRule(
        rule_id="rice_flour",
        family="flour",
        subfamily="rice_flour",
        confidence="HIGH",
        title_phrases=("ryzova muka", "muka z ryze", "muka z lepkavej ryze"),
        attributes=(("ingredient_base", "rice"),),
        display_label="Ryžová múka",
    ),
    FamilyRule(
        rule_id="rice_wine",
        family="beverages",
        subfamily="rice_wine",
        confidence="MEDIUM",
        title_phrases=("ryzove vino", "makgeolli"),
        attributes=(("source", "rice"),),
        display_label="Ryžové víno",
    ),
    FamilyRule(
        rule_id="rice_drink",
        family="beverages",
        subfamily="rice_drink",
        confidence="MEDIUM",
        title_phrases=("ryzovy napoj",),
        attributes=(("source", "rice"),),
        display_label="Ryžový nápoj",
    ),
    FamilyRule(
        rule_id="sushi_rice",
        family="rice",
        subfamily="sushi_rice",
        confidence="HIGH",
        category_terms=("sushi_rice_category",),
        title_phrases=("susi ryza", "ryza na susi", "sushi ryza"),
        attributes=(("use_case", "sushi"),),
        display_label="Ryža na sushi",
    ),
    FamilyRule(
        rule_id="jasmine_rice",
        family="rice",
        subfamily="plain_rice",
        confidence="HIGH",
        category_terms=("jazminova ryza",),
        title_phrases=("jazminova ryza",),
        attributes=(("variety", "jasmine"),),
        display_label="Jazmínová ryža",
    ),
    FamilyRule(
        rule_id="basmati_rice",
        family="rice",
        subfamily="plain_rice",
        confidence="HIGH",
        category_terms=("basmati ryza",),
        title_phrases=("basmati ryza",),
        attributes=(("variety", "basmati"),),
        display_label="Basmati ryža",
    ),
    FamilyRule(
        rule_id="glutinous_rice",
        family="rice",
        subfamily="plain_rice",
        confidence="HIGH",
        title_phrases=("lepkava ryza", "lepkavej ryze", "lepkavu ryzu"),
        attributes=(("variety", "glutinous"),),
        display_label="Lepkavá ryža",
    ),
    FamilyRule(
        rule_id="plain_rice",
        family="rice",
        subfamily="plain_rice",
        confidence="HIGH",
        category_terms=("ryza",),
        title_phrases=("ryza", "ryzu", "ryze", "ryzou", "ryzi"),
        display_label="Ryža",
    ),
]

# Sprint V2.3 taxonomy expansion - every rule grounded in real live-feed
# category paths and titles (see docs/product-taxonomy-audit.md for the
# evidence), same collision discipline as the rice pilot above: most
# specific first, generic fallback last, exclude_title_phrases where a
# shared category cross-lists genuinely different product identities
# (e.g. "Čili omáčky" also contains chili PASTE and chili-oil products).
FAMILY_DEFINITIONS += [
    # --- sauces ---------------------------------------------------------
    FamilyRule(
        rule_id="dark_soy_sauce",
        family="sauce",
        subfamily="soy_sauce",
        confidence="HIGH",
        # No category_terms: "Sójové omáčky" also cross-lists black bean
        # sauce, poke sauce, unagi sauce, dumpling sauce, teriyaki - not
        # pure soy-sauce identity on its own (Section 53/58 purity gate).
        title_phrases=("tmava sojova omacka", "dark soy sauce"),
        # "sójová omáčka" as a bare flavour descriptor also appears in
        # instant ramen/noodle titles (e.g. "Instantné rezance NISSIN Demae
        # Ramen Sójová omáčka") - found live during V2.4 structured
        # retrieval verification (Section 96), same collision class already
        # guarded for teriyaki_sauce below.
        exclude_title_phrases=("instantna", "instantne"),
        attributes=(("style", "dark"),),
        display_label="Tmavá sójová omáčka",
    ),
    FamilyRule(
        rule_id="light_soy_sauce",
        family="sauce",
        subfamily="soy_sauce",
        confidence="HIGH",
        title_phrases=("svetla sojova omacka", "light soy sauce"),
        exclude_title_phrases=("instantna", "instantne"),
        attributes=(("style", "light"),),
        display_label="Svetlá sójová omáčka",
    ),
    FamilyRule(
        rule_id="soy_sauce",
        family="sauce",
        subfamily="soy_sauce",
        confidence="HIGH",
        title_phrases=("sojova omacka", "soy sauce"),
        exclude_title_phrases=("instantna", "instantne"),
        display_label="Sójová omáčka",
    ),
    FamilyRule(
        rule_id="oyster_sauce",
        family="sauce",
        subfamily="oyster_sauce",
        confidence="HIGH",
        category_terms=("ustricove omacky",),
        title_phrases=("ustricova omacka",),
        display_label="Ustricová omáčka",
    ),
    FamilyRule(
        rule_id="fish_sauce",
        family="sauce",
        subfamily="fish_sauce",
        confidence="HIGH",
        category_terms=("rybacie omacky",),
        title_phrases=("rybacia omacka", "fish sauce"),
        display_label="Rybacia omáčka",
    ),
    FamilyRule(
        rule_id="hoisin_sauce",
        family="sauce",
        subfamily="hoisin_sauce",
        confidence="HIGH",
        category_terms=("hoisin omacky",),
        title_phrases=("hoisin",),
        display_label="Hoisin omáčka",
    ),
    FamilyRule(
        rule_id="teriyaki_sauce",
        family="sauce",
        subfamily="teriyaki_sauce",
        confidence="HIGH",
        category_terms=("teriyaki omacky",),
        title_phrases=("teriyaki",),
        exclude_title_phrases=("instantna", "instantne"),
        display_label="Teriyaki omáčka",
    ),
    FamilyRule(
        rule_id="black_bean_sauce",
        family="sauce",
        subfamily="black_bean",
        confidence="HIGH",
        title_phrases=("cierna fazula omacka", "cierna fazula cesnak omacka"),
        display_label="Čierna fazuľa omáčka",
    ),
    FamilyRule(
        rule_id="black_bean_paste",
        family="paste",
        subfamily="black_bean",
        confidence="HIGH",
        title_phrases=("cierna fazula pasta",),
        display_label="Čierna fazuľa pasta",
    ),
    # V2.12.3 - "čili pasta"/"chilli paste" had no FamilyRule at all: the
    # chili_sauce rule below already explicitly excludes "cili pasta" title
    # matches (a pre-existing collision guard), which meant these products
    # resolved to no family whatsoever and fell to the unguarded legacy
    # scorer, surfacing a chili SNACK and a chili PICKLE for a paste query
    # (docs/query-semantics.md). Grounded in 19 real "Čili pasta ..." catalog
    # products (Gochujang, Sambal Oelek, Thai-basil varieties).
    FamilyRule(
        rule_id="chili_paste",
        family="paste",
        subfamily="chili_paste",
        confidence="HIGH",
        title_phrases=("cili pasta", "chili paste", "chilli paste"),
        # Korean gochujang products are literally titled "Čili pasta
        # Gochujang ..." on this catalog - the gochujang rule below is
        # more specific and must win (test_taxonomy_v23.py::test_gochujang).
        exclude_title_phrases=("gochujang", "gochu jang", "gochudzang", "gochudang"),
        display_label="Čili pasta",
    ),
    # V2.12.3 - "tamarindová pasta"/"tamarind paste" had no FamilyRule at
    # all (family=None/UNKNOWN for both languages), so the query fell to
    # detect_related_subject()'s "tamarind" bundle
    # (RELATED_PRODUCT_QUERIES["tamarind"]) which mixes in fish sauce,
    # coconut milk and brown sugar alongside the one real tamarind product
    # (docs/query-semantics.md, SPECIAL_PRODUCT_QUERIES/bundle audit).
    # Grounded in real catalog products: "Tamarind pasta na varenie THAI
    # DANCER" (250/435/1000ml).
    FamilyRule(
        rule_id="tamarind_pasta",
        family="paste",
        subfamily="tamarind_pasta",
        confidence="HIGH",
        title_phrases=("tamarindova pasta", "tamarind pasta", "tamarind paste"),
        display_label="Tamarindová pasta",
    ),
    FamilyRule(
        rule_id="sriracha_sauce",
        family="sauce",
        subfamily="chili_sauce",
        confidence="HIGH",
        category_terms=("sriracha cili omacky",),
        title_phrases=("sriracha",),
        attributes=(("variety", "sriracha"),),
        display_label="Sriracha omáčka",
    ),
    FamilyRule(
        rule_id="sweet_chili_sauce",
        family="sauce",
        subfamily="chili_sauce",
        confidence="HIGH",
        category_terms=("sladke cili omacky",),
        title_phrases=("sladka cili omacka", "cili omacka sladka", "cili limetkova omacka"),
        attributes=(("variety", "sweet"),),
        display_label="Sladká čili omáčka",
    ),
    FamilyRule(
        rule_id="chili_garlic_sauce",
        family="sauce",
        subfamily="chili_sauce",
        confidence="HIGH",
        category_terms=("cili cesnak omacky",),
        title_phrases=("cili cesnak omacka", "cili omacka cesnakova"),
        attributes=(("variety", "garlic"),),
        display_label="Čili cesnaková omáčka",
    ),
    FamilyRule(
        rule_id="chili_sauce",
        family="sauce",
        subfamily="chili_sauce",
        confidence="HIGH",
        category_terms=("cili omacky",),
        title_phrases=("cili omacka",),
        exclude_title_phrases=("cili pasta", "oleji"),
        display_label="Čili omáčka",
    ),
    # --- curry pastes -----------------------------------------------------
    FamilyRule(
        rule_id="massaman_curry_paste",
        family="curry_paste",
        subfamily=None,
        confidence="HIGH",
        # No category_terms here: every curry_paste variety rule below
        # shares the exact same "Kari pasty" category, so a category-only
        # match on the FIRST rule in this group would silently swallow
        # every other variety regardless of title (Section 44/58 - caught
        # by test_variety_extraction misclassifying a red curry paste as
        # massaman). Variety identity comes from the title only; the
        # shared category still backs the generic curry_paste fallback.
        title_phrases=("massaman", "matsaman"),
        attributes=(("variety", "massaman"),),
        display_label="Massaman kari pasta",
    ),
    FamilyRule(
        rule_id="panang_curry_paste",
        family="curry_paste",
        subfamily=None,
        confidence="HIGH",
        title_phrases=("panang",),
        attributes=(("variety", "panang"),),
        display_label="Panang kari pasta",
    ),
    FamilyRule(
        rule_id="red_curry_paste",
        family="curry_paste",
        subfamily=None,
        confidence="HIGH",
        title_phrases=("cervena kari pasta", "cervena kari"),
        attributes=(("variety", "red"),),
        display_label="Červená kari pasta",
    ),
    FamilyRule(
        rule_id="green_curry_paste",
        family="curry_paste",
        subfamily=None,
        confidence="HIGH",
        title_phrases=("zelena kari pasta", "zelena kari"),
        attributes=(("variety", "green"),),
        display_label="Zelená kari pasta",
    ),
    FamilyRule(
        rule_id="curry_paste",
        family="curry_paste",
        subfamily=None,
        confidence="HIGH",
        category_terms=("kari pasty",),
        # Bare "kari pasta"/"curry pasta" (V2.14d) - real products with no
        # named variety already resolve here via category (e.g. "Kari
        # pasta ASIAN HOME GOURMET"); this phrase only closes the
        # QUERY-side gap for a colour-less recipe ingredient line (a
        # recipe asking for "curry paste" with no variety is satisfied by
        # any curry paste). Positioned after every variety-specific rule
        # above, so "cervena kari pasta" etc. still match their own,
        # more specific rule first (first-match-wins) - unaffected.
        title_phrases=("kari pasta", "curry pasta"),
        display_label="Kari pasta",
    ),
    # --- fermented pastes -------------------------------------------------
    FamilyRule(
        rule_id="miso",
        family="paste",
        subfamily="miso",
        confidence="HIGH",
        title_phrases=("miso pasta", "biela miso", "cervena miso"),
        exclude_title_phrases=("polievka", "miso soup", "miso tofu"),
        display_label="Miso pasta",
    ),
    FamilyRule(
        rule_id="gochujang",
        family="paste",
        subfamily="gochujang",
        confidence="HIGH",
        title_phrases=("gochujang",),
        display_label="Gochujang",
    ),
    # --- coconut products ---------------------------------------------------
    FamilyRule(
        rule_id="coconut_milk",
        family="coconut_product",
        subfamily="coconut_milk",
        confidence="HIGH",
        category_terms=("kokosove mlieko a kremy",),
        title_phrases=("kokosove mlieko",),
        exclude_title_phrases=("zele", "dzus", "kokosovy napoj"),
        display_label="Kokosové mlieko",
    ),
    FamilyRule(
        rule_id="coconut_water",
        family="coconut_product",
        subfamily="coconut_water",
        confidence="HIGH",
        # No category_terms: "Kokosový nápoj" also cross-lists coconut
        # jelly desserts and coconut-milk-with-jelly drinks (Section 58).
        title_phrases=("kokosova voda",),
        display_label="Kokosová voda",
    ),
    # V2.12.2 - "kokosovy olej" (coconut OIL) was leaking coconut cream/
    # juice/vinegar/milk into its results because none of these had a
    # FamilyRule at all: with no rule, parse_structured_query() never
    # resolves a family, retrieve_products() unconditionally returns
    # LEGACY_FALLBACK, and the query never reaches the taxonomy-aware
    # exclusion retrieval already does for every OTHER rice/coconut
    # variant - it fell straight to the un-filtered legacy lexical
    # scorer (docs/query-semantics.md). Ordered before coconut_oil below
    # (own family) and coconut_milk above (own subfamily) so first-match-
    # wins never confuses these adjacent-but-distinct coconut products.
    FamilyRule(
        rule_id="coconut_cream",
        family="coconut_product",
        subfamily="coconut_cream",
        confidence="HIGH",
        category_terms=("kokosove mlieko a kremy",),
        title_phrases=("kokosovy krem", "kokosovy krem v prasku"),
        display_label="Kokosový krém",
    ),
    FamilyRule(
        rule_id="coconut_juice",
        family="coconut_product",
        subfamily="coconut_juice",
        confidence="HIGH",
        title_phrases=("kokosovy dzus",),
        display_label="Kokosový džús",
    ),
    FamilyRule(
        rule_id="coconut_vinegar",
        family="vinegar",
        subfamily="coconut_vinegar",
        confidence="HIGH",
        title_phrases=("kokosovy ocot",),
        attributes=(("source", "coconut"),),
        display_label="Kokosový ocot",
    ),
    # --- oils ---------------------------------------------------------------
    FamilyRule(
        rule_id="sesame_oil",
        family="oil",
        subfamily="sesame_oil",
        confidence="HIGH",
        category_terms=("sezamovy olej",),
        title_phrases=("sezamovy olej",),
        display_label="Sezamový olej",
    ),
    FamilyRule(
        rule_id="coconut_oil",
        family="oil",
        subfamily="coconut_oil",
        confidence="HIGH",
        category_terms=("kokosovy olej",),
        title_phrases=("kokosovy olej", "coconut oil"),
        display_label="Kokosový olej",
    ),
    # --- noodles expansion ----------------------------------------------
    FamilyRule(
        rule_id="soba_noodles",
        family="noodles",
        subfamily="soba",
        confidence="HIGH",
        category_terms=("pohankove rezance",),
        title_phrases=("soba",),
        # "soba" alone also false-matches "yakisoba" (a different, wheat-
        # based fried-noodle dish - and its own sauce product), instant
        # soba-flavoured SOUP, and a china bowl product line named "Soba"
        # (Section 53/58 purity gate).
        exclude_title_phrases=("yakisoba", "instantna", "instantne", "polievka", "miska"),
        attributes=(("ingredient_base", "buckwheat"),),
        display_label="Soba rezance",
    ),
    FamilyRule(
        rule_id="wheat_noodles",
        family="noodles",
        subfamily="wheat_noodles",
        confidence="HIGH",
        category_terms=("psenicne rezance",),
        # "udon" title-matches so the bare *query* "udon"/"udon rezance"
        # resolves here too (queries have no category to match against -
        # V2.12.3, docs/query-semantics.md). Real udon products already
        # classified correctly via category_terms above; this only fixes
        # query-side resolution, which previously fell through to
        # instant_noodles' bare "rezance" phrase. Excludes a literal
        # Japanese ceramic bowl SET also titled "Udon Misky" - same
        # collision-guard pattern as soba's "miska" exclude below.
        title_phrases=("udon",),
        exclude_title_phrases=("instantna", "instantne", "polievka", "miska", "misky"),
        attributes=(("ingredient_base", "wheat"),),
        display_label="Pšeničné rezance",
    ),
    # V2.12.3 - "sklenené rezance"/"glass noodles" had no FamilyRule: both
    # the products (14 real catalog items) and the bare query fell through
    # to instant_noodles via its generic "rezance" title phrase, so a glass-
    # noodle query returned Korean instant ramyun cups instead
    # (docs/query-semantics.md). Positioned before instant_noodles so
    # first-match-wins routes both products and queries here correctly.
    FamilyRule(
        rule_id="glass_noodles",
        family="noodles",
        subfamily="glass_noodles",
        confidence="HIGH",
        category_terms=("sklenene rezance",),
        title_phrases=("sklenene rezance", "glass noodles"),
        display_label="Sklenené rezance",
    ),
    # V2.14d - "Stolovy riad" (tableware) is a narrow, exclusive leaf
    # category (268 catalog products, none previously classified by any
    # earlier rule here) used for bowls, chopsticks and spoons - including
    # 9 "ramen"-branded serving bowl/spoon products (e.g. "Japonske Ramen
    # misky sada 2 ks", "Ramen lyzica bambusova") that were being swept
    # into instant_noodles below via its bare title-only "ramen" match
    # (MEDIUM confidence, no category corroboration) - a real production
    # collision found during V2.14c/V2.14d (docs/use-case-recipe-data-
    # quality-v2.14d.md). Positioned before instant_noodles so any
    # product carrying this category is classified as tableware first,
    # regardless of what food-sounding word appears in its title -
    # a category-based fix generalizes to any future non-food product in
    # this category, not just today's known ramen-branded SKUs.
    FamilyRule(
        rule_id="tableware",
        family="kitchenware",
        subfamily="tableware",
        confidence="HIGH",
        category_terms=("stolovy riad",),
        display_label="Stolový riad",
    ),
    # --- instant food -----------------------------------------------------
    FamilyRule(
        rule_id="instant_noodles",
        family="instant_food",
        subfamily="instant_noodles",
        confidence="HIGH",
        category_terms=("instantne polievky",),
        title_phrases=("rezance", "ramyeon", "ramyun", "ramen"),
        # V2.12.3 - the bare "rezance" phrase (kept because ~half of real
        # instant-noodle titles, e.g. "Instantné rezance KING COOK", carry
        # no other distinguishing word) was also matching a noodle
        # STRAINER, konjac/shirataki noodles, and noodle-flavoured SAUCES
        # that are not instant noodles at all - found while tracing why
        # glass noodles fell into this rule (docs/query-semantics.md).
        exclude_title_phrases=("polievka", "koreniaca pasta", "omacka", "sitko", "shirataki", "konjac"),
        display_label="Instantné rezance",
    ),
    FamilyRule(
        rule_id="instant_soup",
        family="instant_food",
        subfamily="instant_soup",
        confidence="HIGH",
        category_terms=("instantne polievky",),
        title_phrases=("polievka",),
        display_label="Instantná polievka",
    ),
    # --- tea ------------------------------------------------------------
    FamilyRule(
        rule_id="tea",
        family="tea",
        subfamily=None,
        confidence="HIGH",
        category_terms=("caj",),
        display_label="Čaj",
    ),
    # --- seaweed ----------------------------------------------------------
    FamilyRule(
        rule_id="nori",
        family="seaweed",
        subfamily="nori",
        confidence="HIGH",
        # No category_terms: "Morské riasy" covers nori, wakame AND kelp/
        # kombu together - only the title distinguishes them (Section 58).
        title_phrases=("nori",),
        display_label="Nori riasy",
    ),
    FamilyRule(
        rule_id="wakame",
        family="seaweed",
        subfamily="wakame",
        confidence="HIGH",
        title_phrases=("wakame",),
        display_label="Wakame riasy",
    ),
    # --- frozen food --------------------------------------------------------
    FamilyRule(
        rule_id="gyoza",
        family="frozen_food",
        subfamily="dumplings",
        confidence="HIGH",
        # No category_terms: "Mrazené potraviny"/"Mrazené hotové jedlá" cover
        # everything frozen (squid, mochi ice cream, edamame, lemongrass) -
        # category alone is not identity evidence here, only the "gyoza"
        # loanword in the title is (Section 53/58 family purity gate; a
        # category+title version of this rule wrongly caught 70 unrelated
        # frozen products during V2.3 development, caught by manual review).
        title_phrases=("gyoza",),
        display_label="Gyoza knedličky",
    ),
]

FAMILY_DEFINITIONS_BY_ID: dict[str, FamilyRule] = {rule.rule_id: rule for rule in FAMILY_DEFINITIONS}


@dataclass(slots=True)
class ProductTaxonomy:
    product_id: str
    canonical_family: str | None = None
    canonical_subfamily: str | None = None
    concept_id: str = ""  # FamilyRule.rule_id that matched (V2.2 autocomplete grouping); "" if UNKNOWN
    attributes: dict[str, str] = field(default_factory=dict)
    dietary_facets: list[str] = field(default_factory=list)
    cuisine_facets: list[str] = field(default_factory=list)
    use_case_facets: list[str] = field(default_factory=list)
    commercial_facets: list[str] = field(default_factory=list)
    merchandising_facets: list[str] = field(default_factory=list)
    confidence: str = "UNKNOWN"
    evidence: list[str] = field(default_factory=list)
    taxonomy_version: int = TAXONOMY_VERSION


def _facets_from_category_memberships(category_memberships: Iterable[str]) -> tuple[list[str], list[str]]:
    """Split cross-cutting category labels into (dietary_facets, merchandising_facets).

    These labels dominate the catalog by raw count but are attribute
    facets, not product identity (docs/product-taxonomy-audit.md, Fáza 1).
    """
    dietary: list[str] = []
    merchandising: list[str] = []
    for raw in category_memberships:
        normalized = search_normalize(raw)
        if normalized in _DIETARY_CATEGORY_TERMS:
            dietary.append(_DIETARY_CATEGORY_TERMS[normalized])
        elif normalized in _MERCHANDISING_CATEGORY_TERMS:
            merchandising.append(_MERCHANDISING_CATEGORY_TERMS[normalized])
    return dietary, merchandising


def classify_product(product: Product) -> ProductTaxonomy:
    """Deterministic per-product classification. Pure function, no I/O.

    Evaluates FAMILY_DEFINITIONS in order and returns on the first match.
    A product matching no rule gets canonical_family=None,
    confidence="UNKNOWN" - it stays fully available to legacy search
    (failure/absence of classification never removes a product).
    """
    category_memberships = product.category_memberships
    normalized_categories = {search_normalize(c) for c in category_memberships}
    aliased_categories = {
        CATEGORY_ALIASES[c] for c in normalized_categories if c in CATEGORY_ALIASES
    }
    category_set = normalized_categories | aliased_categories

    normalized_title = search_normalize(product.title)
    url_category = extract_url_category(product.link)

    dietary_facets, merchandising_facets = _facets_from_category_memberships(category_memberships)

    for rule in FAMILY_DEFINITIONS:
        if rule.exclude_title_phrases and any(p in normalized_title for p in rule.exclude_title_phrases):
            continue

        category_hit = next((t for t in rule.category_terms if t in category_set), None)
        title_hit = next((p for p in rule.title_phrases if p in normalized_title), None)

        if category_hit is None and title_hit is None:
            continue

        confidence = rule.confidence if category_hit is not None else _CONFIDENCE_DOWNGRADE[rule.confidence]
        evidence = []
        if category_hit:
            evidence.append(f"category:{category_hit}")
        if title_hit:
            evidence.append(f"title:{title_hit}")
        if url_category:
            evidence.append(f"url_category:{url_category}")

        return ProductTaxonomy(
            product_id=product.id,
            canonical_family=rule.family,
            canonical_subfamily=rule.subfamily,
            concept_id=rule.rule_id,
            attributes=dict(rule.attributes),
            dietary_facets=dietary_facets,
            cuisine_facets=[],
            use_case_facets=[],
            commercial_facets=[],
            merchandising_facets=merchandising_facets,
            confidence=confidence,
            evidence=evidence,
        )

    return ProductTaxonomy(
        product_id=product.id,
        confidence="UNKNOWN",
        dietary_facets=dietary_facets,
        merchandising_facets=merchandising_facets,
    )


def build_taxonomy_index(products: Iterable[Product]) -> dict[str, ProductTaxonomy]:
    """Batch-classify a catalog with per-product failure isolation.

    A single bad product's classification failure must not break the
    refresh (docs/product-taxonomy-audit.md, failure isolation / global
    failure safety) - it just falls back to UNKNOWN and the raw product
    stays available to legacy search.
    """
    index: dict[str, ProductTaxonomy] = {}
    failures = 0
    for product in products:
        try:
            index[product.id] = classify_product(product)
        except Exception:
            logger.warning("Product taxonomy classification failed for id=%s", getattr(product, "id", "?"), exc_info=True)
            failures += 1
            index[product.id] = ProductTaxonomy(product_id=getattr(product, "id", ""), confidence="UNKNOWN")

    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    for entry in index.values():
        counts[entry.confidence] = counts.get(entry.confidence, 0) + 1
    logger.info(
        "Taxonomy index built: %d products, HIGH=%d MEDIUM=%d LOW=%d UNKNOWN=%d, failures=%d",
        len(index), counts["HIGH"], counts["MEDIUM"], counts["LOW"], counts["UNKNOWN"], failures,
    )
    return index


def get_taxonomy(index: dict[str, ProductTaxonomy], product_id: str) -> ProductTaxonomy | None:
    return index.get(product_id)


def find_by_family(index: dict[str, ProductTaxonomy], family: str) -> list[str]:
    """Product ids whose canonical_family matches - the structural query
    future retrieval code needs instead of re-tokenizing product_type."""
    return [pid for pid, tax in index.items() if tax.canonical_family == family]


def find_by_attributes(index: dict[str, ProductTaxonomy], **constraints: str) -> list[str]:
    """Product ids matching every given attribute constraint (AND)."""
    return [
        pid for pid, tax in index.items()
        if all(tax.attributes.get(key) == value for key, value in constraints.items())
    ]


def taxonomy_coverage(index: dict[str, ProductTaxonomy]) -> dict:
    """Aggregate stats for docs/product-taxonomy-audit.md (Fáza: coverage)."""
    total = len(index)
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    families: dict[str, int] = {}
    subfamilies: dict[str, int] = {}
    for tax in index.values():
        counts[tax.confidence] = counts.get(tax.confidence, 0) + 1
        if tax.canonical_family:
            families[tax.canonical_family] = families.get(tax.canonical_family, 0) + 1
        if tax.canonical_subfamily:
            subfamilies[tax.canonical_subfamily] = subfamilies.get(tax.canonical_subfamily, 0) + 1
    classified = total - counts["UNKNOWN"]
    return {
        "total_products": total,
        "classified_products": classified,
        "taxonomy_coverage": (classified / total) if total else 0.0,
        "confidence_counts": counts,
        "canonical_family_count": len(families),
        "canonical_subfamily_count": len(subfamilies),
        "families": families,
        "subfamilies": subfamilies,
    }


# Confidence levels grounded enough to proactively suggest to a customer
# (Sprint V2.2 autocomplete). LOW is excluded - too weak a signal to show
# as a semantic concept, even though it still counts toward taxonomy_coverage.
_SUGGESTABLE_CONFIDENCE = {"HIGH", "MEDIUM"}


def build_concept_index(index: dict[str, ProductTaxonomy]) -> list[dict]:
    """Precomputed, compact list of semantic concepts for autocomplete
    (Sprint V2.2) - one entry per FamilyRule that actually has current
    catalog evidence, with a real product count. Rebuilt alongside
    build_taxonomy_index() on every feed refresh (docs/advisor-v2-architecture.md).

    Deliberately grouped by `concept_id` (the FamilyRule that matched),
    not by (family, subfamily) alone - two rules can share a subfamily
    (e.g. jasmine_rice / basmati_rice both -> rice/plain_rice) but are
    still distinct customer-facing concepts.
    """
    counts: dict[str, int] = {}
    for tax in index.values():
        if tax.concept_id and tax.confidence in _SUGGESTABLE_CONFIDENCE:
            counts[tax.concept_id] = counts.get(tax.concept_id, 0) + 1

    concepts: list[dict] = []
    for concept_id, count in counts.items():
        rule = FAMILY_DEFINITIONS_BY_ID.get(concept_id)
        if rule is None or not rule.display_label:
            continue
        concepts.append({
            "concept_id": concept_id,
            "label": rule.display_label,
            "family": rule.family,
            "subfamily": rule.subfamily,
            "attributes": dict(rule.attributes),
            "product_count": count,
        })
    return concepts
