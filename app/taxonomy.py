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
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


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
