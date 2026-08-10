"""Proactive audit for the two bug classes found repeatedly by hand this
project: (1) a short marker/alias used to route a query (FAQ intent, recipe
intent, related/replacement subject, product-set signal) turns out to be a
substring of a *different* marker used for an unrelated purpose - e.g.
"kari" (curry) is a prefix of "kariet" (cards, genitive plural), so a
payment-card question got routed to curry cross-sell before that was fixed
by adding "kariet" as its own FAQ marker; and (2) a FAQ/recipe/product's
distinguishing word has no synonym/prefix entry covering its common Slovak
case endings, so a customer typing a different case ("dopravy" instead of
"doprava", "cajnika" instead of "cajnik") gets no match or the wrong one.

This does not require any external wordlist or LLM call - it runs entirely
against the routing tables and knowledge data already in the repo, so it is
free and fast to run as often as needed (e.g. from the weekly production
check, or by hand after adding a new FAQ/recipe/marker).

The two checks have very different confidence levels:

  - Check 1 (marker/alias substring collisions) is close to zero-noise: a
    finding means two markers really can collide, and it's worth a quick
    look at which one wins and whether that's the right one. Known,
    already-handled collisions are in KNOWN_SAFE_COLLISIONS below so they
    stop being reported once fixed/verified.

  - Check 2 (declension robustness) is a *candidate generator*, not a
    verdict - Slovak morphology is not modeled precisely here, so a
    reported line means "a short customer-style query gave a different
    FAQ's answer", which is sometimes a real bug (the "cajnik"/"doprava"
    class) and sometimes just a reasonable answer to a genuinely ambiguous
    bare-word query. Triage each finding the way Sprint P did: test the
    query live, decide if it's actually misleading, only then fix it.

Usage:
    python scripts/consistency_audit.py                 # both checks
    python scripts/consistency_audit.py --collisions     # only check 1
    python scripts/consistency_audit.py --declensions    # only check 2
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import main as bot  # noqa: E402
from app import search as search_module  # noqa: E402


def normalize(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower()


# ---------------------------------------------------------------------------
# Check 1: cross-dictionary marker/alias substring collisions.
# ---------------------------------------------------------------------------
#
# Every dict below maps a "bucket name" (just for reporting) to a function
# that returns {marker_string: short description of what it's for}. Add a
# new bucket here whenever a new marker/alias table is introduced.

def _collect_markers() -> dict[str, dict[str, str]]:
    buckets: dict[str, dict[str, str]] = {}

    buckets["FAQ_INTENT_MARKERS"] = {m: "FAQ intent gate" for m in bot.FAQ_INTENT_MARKERS}
    buckets["RECIPE_INTENT_MARKERS"] = {m: "recipe intent gate" for m in bot.RECIPE_INTENT_MARKERS}
    buckets["PRODUCT_SET_SIGNAL_TOKENS"] = {m: "product-set override signal" for m in bot.PRODUCT_SET_SIGNAL_TOKENS}

    related = {}
    for subject, aliases in bot.RELATED_SUBJECT_ALIASES.items():
        for alias in aliases:
            related[alias] = f'related_subject="{subject}"'
    buckets["RELATED_SUBJECT_ALIASES"] = related

    replacement = {}
    for subject, aliases in bot.REPLACEMENT_SUBJECT_ALIASES.items():
        for alias in aliases:
            replacement[alias] = f'replacement_subject="{subject}"'
    buckets["REPLACEMENT_SUBJECT_ALIASES"] = replacement

    recipe_title = {}
    for marker, subject in bot.RECIPE_TITLE_PRODUCT_SUBJECTS:
        recipe_title[marker] = f'recipe_subject="{subject}"'
    buckets["RECIPE_TITLE_PRODUCT_SUBJECTS"] = recipe_title

    prefix_syn = {p: f"PREFIX_SYNONYMS -> {sorted(v)}" for p, v in search_module.PREFIX_SYNONYMS.items()}
    buckets["PREFIX_SYNONYMS"] = prefix_syn

    return buckets


def _concept_key(bucket: str, marker: str, meaning: str) -> str | None:
    """Best-effort identifier for "what real-world thing does this marker
    point at", so two markers that both ultimately mean the same dish/
    ingredient (just declined differently, or reached via different dicts)
    aren't flagged as a collision - only markers whose *subjects* actually
    differ are a real routing risk. Returns None when the bucket has no
    natural single-concept grouping (FAQ/recipe intent markers are each
    their own standalone concept) or PRODUCT_SET_SIGNAL_TOKENS/
    PREFIX_SYNONYMS same-bucket pairs, which are handled separately.
    """
    if bucket == "PRODUCT_SET_SIGNAL_TOKENS":
        return "product_set"  # every entry in this bucket is the same signal
    match = re.search(r'"([^"]+)"', meaning)
    if match:
        return match.group(1)
    return None


def _prefix_synonym_targets(meaning: str) -> set[str]:
    """Extract the variant word list out of a PREFIX_SYNONYMS meaning
    string like "PREFIX_SYNONYMS -> ['sriracha']"."""
    match = re.search(r"\[(.*)\]", meaning)
    if not match:
        return set()
    return {w.strip(" '\"") for w in match.group(1).split(",") if w.strip(" '\"")}


# Real collisions that were investigated and are already safe in practice
# because the code checks the more specific marker first (a dedicated
# shortcut, or dict iteration order) - kept here so re-running the audit
# after a genuine fix doesn't keep reporting the same resolved case. Remove
# an entry once the underlying alias itself is changed so it can no longer
# collide (i.e. this is a "known and handled", not a "safe to ignore
# forever" list - re-verify if the routing code around it changes).
KNOWN_SAFE_COLLISIONS = {
    frozenset({"kari", "kariet"}),  # Sprint V.3: "kariet" got its own FAQ marker, checked before related_subject
    frozenset({"nigiri", "onigiri"}),  # onigiri checked before sushi in RELATED_SUBJECT_ALIASES iteration order
    frozenset({"thai", "padthai"}),  # "pad thai" resolves via the RECIPE_TITLE_PRODUCT_SUBJECTS title-match shortcut, which runs before the RELATED_SUBJECT_ALIASES loop reaches "thai"
    frozenset({"udon", "gyudon"}),  # fixed: gyudon reordered before udon in both RELATED_SUBJECT_ALIASES and RECIPE_TITLE_PRODUCT_SUBJECTS
    frozenset({"ryba", "rybac"}),  # verified live: "rybacia omacka" already resolves to rybacia_omacka, not the shorter "ryba"
    frozenset({"rybac", "rybaci"}),  # same
}


def check_collisions(min_len: int = 3, max_len: int = 7) -> list[str]:
    buckets = _collect_markers()

    # Flat list of (marker, bucket, meaning) for every marker short enough
    # to realistically be an accidental substring of something else.
    flat: list[tuple[str, str, str]] = []
    for bucket_name, entries in buckets.items():
        for marker, meaning in entries.items():
            norm = normalize(marker)
            if min_len <= len(norm) <= max_len and " " not in norm:
                flat.append((norm, bucket_name, meaning))

    findings = []
    seen_pairs: set[tuple[str, str]] = set()
    for marker, bucket, meaning in flat:
        for other_marker, other_bucket, other_meaning in flat:
            if marker == other_marker:
                continue
            if marker not in other_marker:
                continue
            # marker is a substring of other_marker (different string).
            # Skip pairs that resolve to the same real-world subject even
            # across different dicts (e.g. a RELATED_SUBJECT_ALIASES entry
            # and a REPLACEMENT_SUBJECT_ALIASES entry both for "mirin") -
            # those are intentional declension overlaps, not a routing risk.
            concept = _concept_key(bucket, marker, meaning)
            other_concept = _concept_key(other_bucket, other_marker, other_meaning)
            if concept and concept == other_concept:
                continue
            # A PREFIX_SYNONYMS entry's target word list counts as "same
            # concept" as a subject with a matching name (e.g. "srirac" ->
            # ['sriracha'] vs replacement_subject="sriracha").
            if bucket == "PREFIX_SYNONYMS" and other_concept in _prefix_synonym_targets(meaning):
                continue
            if other_bucket == "PREFIX_SYNONYMS" and concept in _prefix_synonym_targets(other_meaning):
                continue
            if bucket == "PREFIX_SYNONYMS" == other_bucket and (
                _prefix_synonym_targets(meaning) & _prefix_synonym_targets(other_meaning)
            ):
                continue
            if frozenset({marker, other_marker}) in KNOWN_SAFE_COLLISIONS:
                continue
            pair_key = tuple(sorted((f"{bucket}:{marker}", f"{other_bucket}:{other_marker}")))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            findings.append(
                f'"{marker}" ({bucket}, {meaning}) is a substring of '
                f'"{other_marker}" ({other_bucket}, {other_meaning})'
            )
    return sorted(findings)


# ---------------------------------------------------------------------------
# Check 2: declension robustness for FAQ entries, recipes, and the subject/
# marker dictionaries themselves.
# ---------------------------------------------------------------------------
#
# Not a full morphological analyzer - just the common Slovak case-ending
# swaps that actually caused bugs this project (genitive/dative/locative/
# instrumental singular, a few plural forms). Good enough to catch regular
# declension gaps; irregular plurals (karta -> kariet) still need a human.

# Deliberately small and conservative: every real declension bug found in
# this project so far (cajnik/cajnika, doprava/dopravy, cajova/cajove) was
# a single-letter swap at the very end of the word (genitive/accusative
# singular for masculine/feminine nouns, or the neuter adjective ending).
# A fuller Slovak case paradigm (dative -u, instrumental -om, plural -ami/
# -ov, adjective -eho/-emu/-ej/-ym/-ych, ...) produces mostly nonsense words
# when naively suffix-swapped onto an arbitrary stem (especially already-
# inflected nouns like "objednavke", or gerunds like "vyzdvihnutie"), which
# drowns real findings in noise. Widen this list only after checking real
# false-positive/negative rates on a run, not preemptively.
_CASE_SUFFIXES = ("a", "u", "y", "e")


def declined_variants(word: str) -> set[str]:
    normalized_word = normalize(word)
    if len(normalized_word) < 5:
        return set()
    variants: set[str] = set()
    stem = normalized_word[:-1]
    for suffix in _CASE_SUFFIXES:
        variants.add(stem + suffix)
    variants.discard(normalized_word)
    return variants


_VERB_INFINITIVE_ENDINGS = ("ovat", "avat", "ivat", "iet", "iet", "nut")


def _looks_like_verb(token: str) -> bool:
    """Our case-suffix table models noun/adjective declension, not verb
    conjugation - Slovak infinitives (registrovat, vyzdvihnut, zaplatit)
    need a completely different transformation, and naively swapping their
    last 1-2 letters produces garbage no customer would type. Skip them
    rather than report nonsense as a false "collision"."""
    return token.endswith("t") and (
        token.endswith(_VERB_INFINITIVE_ENDINGS) or token.endswith(("atit", "asit", "adit", "ucit", "utit"))
    )


def check_faq_declensions() -> list[str]:
    findings = []
    faq = bot.knowledge.get("sections", {}).get("FAQ", [])

    # Words shared across many FAQ entries in the same topic cluster
    # ("objednavka" in a dozen order-related questions, "kredity" in every
    # loyalty-program question) are *inherently* ambiguous in isolation -
    # any of several answers could legitimately be "right" for a bare
    # one-word query, so testing them alone isn't a fair signal. Only test
    # words that are this FAQ's own distinguishing term: they appear as a
    # token in this record's text and in at most one other record's.
    doc_freq: dict[str, int] = {}
    for record in faq:
        q = bot.first_record_value(record, ("Otázka", "Otazka", "question"))
        a = bot.first_record_value(record, ("Odpoveď", "Odpoved", "answer"))
        for token in bot.tokenize(f"{q} {a}"):
            doc_freq[token] = doc_freq.get(token, 0) + 1

    for record in faq:
        question = bot.first_record_value(record, ("Otázka", "Otazka", "question"))
        expected_answer = bot.first_record_value(record, ("Odpoveď", "Odpoved", "answer"))
        if not question or not expected_answer:
            continue
        # Test the single longest NOUN/ADJECTIVE-looking, distinguishing
        # content word from the question - the one most likely to be the
        # customer's search term, and the word class our declension
        # heuristic actually models.
        content_tokens = [
            t
            for t in bot.tokenize(question)
            if len(t) >= 6 and not _looks_like_verb(t) and doc_freq.get(t, 0) <= 2
        ]
        if not content_tokens:
            continue
        head_token = max(content_tokens, key=len)
        for variant in sorted(declined_variants(head_token))[:6]:  # cap for speed
            got = bot.best_direct_faq_answer(variant, bot.knowledge)
            if got is None:
                continue  # a clean "no match" is not a false-answer bug
            if got.strip() != expected_answer.strip():
                findings.append(
                    f'FAQ "{question[:60]}...": declined query "{variant}" '
                    f"(from \"{head_token}\") returned a DIFFERENT FAQ's answer"
                )
    return findings


def check_recipe_declensions() -> list[str]:
    findings = []
    recipes = bot.knowledge.get("sections", {}).get("Recipes", [])
    for record in recipes:
        card = bot.recipe_card(record)
        title = card.get("title", "")
        if not title:
            continue
        subject = bot.recipe_product_subject_from_title(title)
        if not subject:
            findings.append(f'Recipe "{title}": no RECIPE_TITLE_PRODUCT_SUBJECTS marker matches its own title')
            continue
        content_tokens = [t for t in bot.tokenize(title) if len(t) >= 6]
        for token in content_tokens[:2]:
            for variant in sorted(declined_variants(token))[:6]:
                resolved = bot.recipe_product_subject_from_title(variant)
                # Only flag when the base title's own subject is reachable
                # via the exact word but a same-family declined form of that
                # same word resolves to nothing or a different subject -
                # not every declined fragment needs to resolve on its own.
                if token in variant and resolved not in (None, subject):
                    findings.append(
                        f'Recipe "{title}": declined form "{variant}" of "{token}" '
                        f'resolves to a DIFFERENT subject ("{resolved}" instead of "{subject}")'
                    )
    return findings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collisions", action="store_true", help="only run the marker-collision check")
    parser.add_argument("--declensions", action="store_true", help="only run the declension-robustness check")
    args = parser.parse_args()

    run_collisions = args.collisions or not (args.collisions or args.declensions)
    run_declensions = args.declensions or not (args.collisions or args.declensions)

    exit_code = 0

    if run_collisions:
        print("=== Marker/alias substring collisions ===")
        findings = check_collisions()
        if findings:
            exit_code = 1
            for line in findings:
                print(" -", line)
        else:
            print(" (none found)")
        print()

    if run_declensions:
        print("=== FAQ declension robustness ===")
        faq_findings = check_faq_declensions()
        if faq_findings:
            exit_code = 1
            for line in faq_findings:
                print(" -", line)
        else:
            print(" (none found)")
        print()

        print("=== Recipe declension robustness ===")
        recipe_findings = check_recipe_declensions()
        if recipe_findings:
            exit_code = 1
            for line in recipe_findings:
                print(" -", line)
        else:
            print(" (none found)")
        print()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
