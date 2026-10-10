"""
tests/test_servings_parser_v2_28c.py  -  V2.28c servings parser bounded extension

Parser-only tests for the bounded grammar extension to
app.ingredients._SERVINGS_PATTERN: "asi"/"cca" as additional approximate-
count prefixes alongside "pre"/"na", and "hosti" added to the trailing
servings-noun alternation. No routing, no package-size, no price, no
recipe-scaling, no session state - see app/ingredients.py's own V2.28c
docstring note for the exact corpus evidence behind each addition.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingredients import extract_requested_servings, extract_requested_servings_lenient


class TestExistingFormsPreserved:
    """Forms supported before V2.28c must remain byte-identical in behavior."""

    def test_pre_ludi_ascii(self):
        assert extract_requested_servings("pre 6 ludi") == 6

    def test_pre_ludi_diacritics(self):
        assert extract_requested_servings("pre 6 ľudí") == 6

    def test_na_porcii_ascii(self):
        assert extract_requested_servings("na 6 porcii") == 6

    def test_na_porcii_diacritics(self):
        assert extract_requested_servings("na 6 porcií") == 6

    def test_natural_sentence_unchanged(self):
        assert extract_requested_servings("Chcem robit Pad Thai pre 8 ludi. Co mam kupit?") == 8
        assert extract_requested_servings("recept na kung pao pre 4 osoby") == 4

    def test_no_servings_phrase_still_none(self):
        assert extract_requested_servings("Co potrebujem na Pad Thai?") is None

    def test_out_of_range_still_ignored(self):
        assert extract_requested_servings("pre 999 osob") is None


class TestNewApproximatePrefixPositives:
    """V2.28c Target A - 'asi'/'cca' approximate prefixes.

    'asi 6 porcii' is the exact golden-corpus text of
    eval/golden/v2_20_scenarios.json::v220_basket_completeness_0002
    (DEV split). 'cca' carries zero corpus occurrences either way
    (included per the same approximate-register class, not independently
    corpus-attested - see app/ingredients.py docstring)."""

    def test_asi_porcii_ascii(self):
        assert extract_requested_servings("asi 6 porcii") == 6

    def test_asi_porcii_diacritics(self):
        assert extract_requested_servings("asi 6 porcií") == 6

    def test_cca_porcii_ascii(self):
        assert extract_requested_servings("cca 6 porcii") == 6

    def test_cca_porcii_diacritics(self):
        assert extract_requested_servings("cca 6 porcií") == 6

    def test_exact_golden_corpus_text(self):
        # eval/golden/v2_20_scenarios.json, scenario_id=v220_basket_completeness_0002
        assert extract_requested_servings("Robím pho pre celú rodinu, asi 6 porcií.") == 6

    def test_approximate_prefix_distinct_from_na_prefix_in_same_sentence(self):
        # "na 6 porcii" already matches without any V2.28c change - confirms
        # this sentence is not accidentally relying on the new "asi" branch.
        assert extract_requested_servings("Potrebujem to asi na 6 porcii.") == 6

    def test_asi_immediately_before_number(self):
        # The genuine new-grammar case: "asi" directly governs the number,
        # no "pre"/"na" anywhere in the sentence.
        assert extract_requested_servings("Je to asi 6 porcii.") == 6


class TestNewHostTokenPositive:
    """V2.28c Target B - 'hosti' added to the noun alternation. Zero
    corpus occurrences of 'host-' exist in either direction (verified via
    corpus grep across eval/golden/*.json and tests/*.jsonl) - included
    because the collision check came back clean, not because of positive
    corpus frequency."""

    def test_pre_hosti_ascii(self):
        assert extract_requested_servings("pre 6 hosti") == 6

    def test_pre_hosti_diacritics(self):
        assert extract_requested_servings("pre 6 hostí") == 6


class TestCaseAndPunctuationResilience:
    def test_uppercase(self):
        assert extract_requested_servings("ASI 6 PORCII") == 6

    def test_mixed_case_with_period(self):
        assert extract_requested_servings("Cca 6 porcii.") == 6

    def test_mixed_case_with_question_mark(self):
        assert extract_requested_servings("Pre 6 HOSTÍ?") == 6


class TestStandaloneNumericStillRejected:
    """Locked V2.28b decision: bare '<N> porcií' with no prefix at all
    stays strict-rejected - this sprint adds prefix/noun TOKENS, not a new
    no-prefix grammar."""

    def test_bare_porcii_ascii(self):
        assert extract_requested_servings("6 porcii") is None

    def test_bare_porcii_diacritics(self):
        assert extract_requested_servings("6 porcií") is None

    def test_bare_porcii_lenient_also_none(self):
        # extract_requested_servings_lenient's own bare-number fallback
        # (_SERVINGS_PATTERN_BARE) still requires a "pre"/"na" prefix - a
        # fully bare number was never, and is still not, accepted by
        # either function.
        assert extract_requested_servings_lenient("6 porcii") is None


class TestIntentionallyNotBroadened:
    """Locked V2.28b decision: no 'skip an arbitrary word between prefix
    and number' grammar."""

    def test_pre_rodinu_n_ludi_ascii(self):
        assert extract_requested_servings("pre rodinu 6 ludi") is None

    def test_pre_rodinu_n_ludi_diacritics(self):
        assert extract_requested_servings("pre rodinu 6 ľudí") is None


class TestPriceCollisionProtection:
    """Must never produce a servings count from a EUR amount."""

    def test_asi_eur(self):
        assert extract_requested_servings("asi 6 eur") is None

    def test_cca_eur(self):
        assert extract_requested_servings("cca 10 eur") is None

    def test_pre_eur(self):
        assert extract_requested_servings("pre 6 eur") is None


class TestPackageSizeCollisionProtection:
    """Must never produce a servings count from a mass/volume unit."""

    def test_asi_kg(self):
        assert extract_requested_servings("asi 6 kg") is None

    def test_cca_l(self):
        assert extract_requested_servings("cca 5 l") is None

    def test_pre_kg(self):
        assert extract_requested_servings("pre 6 kg") is None


class TestResultCountStockOwnershipCollisionProtection:
    def test_result_count_phrase(self):
        assert extract_requested_servings("ukáž mi 6 produktov") is None
        assert extract_requested_servings("daj mi 5 omáčok") is None

    def test_stock_count_phrase(self):
        assert extract_requested_servings("máte 6 kusov skladom?") is None
        assert extract_requested_servings("máte 6 balení?") is None

    def test_ownership_phrase(self):
        assert extract_requested_servings("mám doma 6 balení nori") is None
        assert extract_requested_servings("mám 6 omáčok") is None

    def test_product_information_phrase(self):
        assert extract_requested_servings("produkt má 6 kg") is None


class TestNumericNegatives:
    """Zero/negative/decimal servings stay rejected - existing policy,
    unchanged and unredesigned by this sprint."""

    def test_zero(self):
        assert extract_requested_servings("asi 0 porcii") is None

    def test_negative(self):
        assert extract_requested_servings("asi -6 porcii") is None

    def test_decimal_dot(self):
        assert extract_requested_servings("asi 6.5 porcii") is None

    def test_decimal_comma(self):
        assert extract_requested_servings("asi 6,5 porcii") is None


class TestDeterminism:
    def test_repeated_calls_identical(self):
        text = "Robím pho pre celú rodinu, asi 6 porcií."
        results = {extract_requested_servings(text) for _ in range(5)}
        assert results == {6}
