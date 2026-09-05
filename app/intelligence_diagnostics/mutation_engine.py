"""
app/intelligence_diagnostics/mutation_engine.py  -  V2.18b safe mutation
engine.

A mutation tests robustness to SURFACE variation while preserving the
SAME declared ground truth (Section 19). It inherits the parent
scenario's `expected_invariants`/`ground_truth_status`/
`ground_truth_authority` ONLY when the transformation is provably
semantics-preserving (Section 20) - never when it could alter intent or
constraint meaning.

SAFE (semantics-preserving) mutation types implemented: TYPO,
DIACRITICS_STRIP, WORD_ORDER, POLITENESS_TOGGLE. Each is a pure,
deterministic string transform - no LLM, no randomness (Section 16/22 -
Date.now()/random-style nondeterminism would break reproducibility).

UNSAFE mutation types are deliberately NOT auto-applied here (Section
20's examples - negation, constraint change, quantity change). Section
22 forbids self-generated adversarial ground truth entirely for this
sprint, so this module does not attempt to invent "harder" unsafe
variants at all; `classify_mutation_safety()` exists so a FUTURE
human-authored transform can be checked before being trusted, and
`UNSAFE_MUTATION_MARKERS` documents the class of transform this module
refuses to auto-generate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

from app.intelligence_diagnostics.scenario_schema import (
    Scenario,
    ScenarioTurn,
    SOURCE_SAFE_MUTATION,
)

MUTATION_VERSION = "1"

TYPO = "TYPO"
DIACRITICS_STRIP = "DIACRITICS_STRIP"
WORD_ORDER = "WORD_ORDER"
POLITENESS_TOGGLE = "POLITENESS_TOGGLE"

SAFE_MUTATION_TYPES = (TYPO, DIACRITICS_STRIP, WORD_ORDER, POLITENESS_TOGGLE)

# Section 20 - transformations that CAN change meaning and must never be
# auto-applied as if they preserved ground truth. Not executed by this
# module; documented so classify_mutation_safety() has a real basis and
# so a future manually-authored case can be checked against it.
UNSAFE_MUTATION_MARKERS = (
    "NEGATION_FLIP",
    "DIETARY_CONSTRAINT_CHANGE",
    "QUANTITY_CHANGE",
    "REPLACEMENT_TO_SIMILAR",
    "SEVERITY_REWORD",
    "ALLERGY_TO_PREFERENCE",
)

# Explicit, small, correct Slovak diacritic-strip table (safer than a
# generic unicodedata NFKD pass, which can mis-strip characters this
# project's own normalize() deliberately treats specially elsewhere).
_SK_DIACRITICS = {
    "á": "a", "ä": "a", "č": "c", "ď": "d", "é": "e", "í": "i", "ľ": "l", "ĺ": "l",
    "ň": "n", "ó": "o", "ô": "o", "ŕ": "r", "š": "s", "ť": "t", "ú": "u", "ý": "y", "ž": "z",
}

_TYPO_SWAPS = {
    "ryza": "ryzha",
    "omacka": "omackaa",
    "sojova": "sojva",
    "kikkoman": "kikoman",
}

_POLITE_PREFIXES = ("prosim vas, ", "prosim, ", "dobry den, ")


def strip_diacritics(text: str) -> str:
    result = []
    for ch in text:
        lower = ch.lower()
        if lower in _SK_DIACRITICS:
            replacement = _SK_DIACRITICS[lower]
            result.append(replacement.upper() if ch.isupper() else replacement)
        else:
            result.append(ch)
    return "".join(result)


_TRAILING_PUNCT = "?!.,;:"


def apply_typo(text: str) -> str:
    lowered = text.lower()
    for original, typo in _TYPO_SWAPS.items():
        if original in lowered:
            idx = lowered.index(original)
            return text[:idx] + typo + text[idx + len(original):]
    # Deterministic fallback typo: double the LAST letter of the
    # longest word, never random (Section 16/22). Word length and the
    # mutation target are both measured on the word's letters only
    # (trailing "?"/"." stripped first) - otherwise a short word with
    # attached punctuation (e.g. "doprava?") can out-rank a longer
    # punctuation-free word, and the mutation itself can land on the
    # punctuation mark instead of a letter.
    #
    # V2.18d.5 (C1_TYPO_MUTATOR_KEYWORD_CORRUPTION): the previous
    # policy doubled the MIDDLE character instead of the last one. For
    # short Slovak keywords (7-9 letters) that middle point falls
    # inside, or immediately after, the short leading stem this
    # project's own intent/FAQ classifiers key off via substring checks
    # (e.g. "kredit", "doprav", "nahrad", "obsahuj" - see app/main.py) -
    # turning a robustness-testing typo into a meaning-destroying one.
    # Doubling the final letter instead is an equally realistic,
    # equally deterministic typo (a common fat-finger repeat at the end
    # of a word) that leaves the leading stem untouched for any word,
    # regardless of length or vocabulary - it is not tuned to any
    # specific keyword or scenario.
    words = text.split()
    if not words:
        return text

    def _core_len(word: str) -> int:
        return len(word.rstrip(_TRAILING_PUNCT))

    longest_idx = max(range(len(words)), key=lambda i: _core_len(words[i]))
    word = words[longest_idx]
    core = word.rstrip(_TRAILING_PUNCT)
    suffix = word[len(core):]
    if len(core) < 3:
        return text
    words[longest_idx] = core + core[-1] + suffix
    return " ".join(words)


def apply_word_order(text: str) -> str:
    words = text.split()
    if len(words) < 2:
        return text
    words[0], words[1] = words[1], words[0]
    return " ".join(words)


def apply_politeness_toggle(text: str) -> str:
    lowered = text.lower()
    for prefix in _POLITE_PREFIXES:
        if lowered.startswith(prefix):
            return text[len(prefix):].strip().capitalize()
    return "Prosim vas, " + text[0].lower() + text[1:] if text else text


_MUTATORS = {
    TYPO: apply_typo,
    DIACRITICS_STRIP: strip_diacritics,
    WORD_ORDER: apply_word_order,
    POLITENESS_TOGGLE: apply_politeness_toggle,
}


def classify_mutation_safety(mutation_type: str) -> bool:
    """True only for a registered, provably semantics-preserving
    mutation type. Anything else (including every UNSAFE_MUTATION_MARKERS
    entry) is unsafe by default - fail-closed, not fail-open."""
    return mutation_type in SAFE_MUTATION_TYPES


def mutate_scenario(scenario: Scenario, mutation_type: str) -> Scenario:
    """Applies a safe mutation to every turn's message, INHERITING the
    parent's ground truth unchanged (Section 20) - only valid because
    classify_mutation_safety() gates entry. Raises if mutation_type is
    not registered as safe, rather than silently producing an unscored/
    inherited-truth scenario for an unvetted transform."""
    if not classify_mutation_safety(mutation_type):
        raise ValueError(
            f"{mutation_type!r} is not a registered safe mutation type - "
            "cannot auto-inherit ground truth (Section 20)."
        )
    mutator = _MUTATORS[mutation_type]
    mutated_turns = tuple(replace(t, message=mutator(t.message)) for t in scenario.turns)
    mutation_id = f"{scenario.scenario_id}__mut_{mutation_type.lower()}_v{MUTATION_VERSION}"
    return replace(
        scenario,
        scenario_id=mutation_id,
        source=SOURCE_SAFE_MUTATION,
        turns=mutated_turns,
        provenance=f"mutation of {scenario.scenario_id} (type={mutation_type}, version={MUTATION_VERSION})",
        underlying_case_id=scenario.scenario_id,
    )


@dataclass(frozen=True)
class MutationRecord:
    mutation_id: str
    parent_scenario_id: str
    mutation_type: str
    mutation_version: str
    semantics_preserving: bool


def mutation_record_for(scenario: Scenario, parent_scenario_id: str, mutation_type: str) -> MutationRecord:
    return MutationRecord(
        mutation_id=scenario.scenario_id,
        parent_scenario_id=parent_scenario_id,
        mutation_type=mutation_type,
        mutation_version=MUTATION_VERSION,
        semantics_preserving=classify_mutation_safety(mutation_type),
    )


def generate_safe_mutations(scenario: Scenario, mutation_types: tuple[str, ...] = SAFE_MUTATION_TYPES) -> list[Scenario]:
    """Only ever called for scenarios that are themselves SCORED
    (Section 20 - a mutation inherits ground truth, so the parent must
    have real ground truth to inherit). GROUND_TRUTH_PENDING scenarios
    are never mutated (there is nothing valid to inherit)."""
    if scenario.ground_truth_status != "SCORED":
        return []
    return [mutate_scenario(scenario, mt) for mt in mutation_types]
