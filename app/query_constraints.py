"""
app/query_constraints.py  -  V2.4 Structured Product Query

Turns a free-text customer query into a StructuredProductQuery: canonical
V2.3 taxonomy family/subfamily/attributes, brand, package size and dietary
facets, each tagged with WHERE it came from (EXPLICIT vs an inferred tier).
Reuses app.taxonomy.FAMILY_DEFINITIONS instead of building a second,
independent taxonomy (Section 7 of the V2.4 spec) - the same
most-specific-first, collision-guarded rule list that already classifies
catalog products classifies query text, so "ryžový ocot" resolving to
vinegar/rice_vinegar (not rice) and "ryžové rezance" resolving to
noodles/rice_noodles (not rice) fall out of the existing rule ordering for
free (Section 8/9).

Deterministic, no LLM calls, no network access.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from app.product_normalizer import PackageSize
from app.search import normalize as search_normalize
from app.search import raw_tokens
from app.taxonomy import FAMILY_DEFINITIONS, FAMILY_DEFINITIONS_BY_ID, FamilyRule, _CONFIDENCE_DOWNGRADE

# Rules whose title_phrases are just grammatical case-forms of the bare
# family noun itself (e.g. plain_rice: "ryza"/"ryzu"/"ryze"/...) - matching
# one of these means the customer named the FAMILY, not a specific
# sub-concept, so subfamily/attributes must stay inferred rather than a
# hard filter (a broad "ryža" query must still return sushi/jasmine/basmati
# rice, not just plain_rice - Section 25/26 specificity monotonicity).
# Every other rule in FAMILY_DEFINITIONS already requires a compound/
# qualified phrase (e.g. "sojova omacka", "cervena kari pasta", "gochujang")
# and IS a genuine sub-concept request, even when it carries no attributes
# tuple of its own - the match itself is the constraint.
_GENERIC_FAMILY_ONLY_RULE_IDS = frozenset({"plain_rice"})

# classify_rice_query() (message-level shadow classifier) already treats
# bare "ryza"+"sushi"/"susi" co-occurrence as equivalent to the compound
# "ryza na sushi" phrase for the same reason: customers write "sushi" and
# "suši"/"susi" interchangeably and in either word order, unlike a product
# title which is catalog-controlled. Reused here so query parsing doesn't
# miss the sushi_rice concept just because the exact compound phrase in
# FAMILY_DEFINITIONS (product-title-oriented) wasn't typed verbatim.
_RICE_ROOT_TOKENS = frozenset({"ryza", "ryzu", "ryze", "ryzou", "ryzi"})
_SUSHI_TOKENS = frozenset({"sushi", "susi"})

# Source tiers for a single constraint (Section 5). Do not treat a weak
# inference like an explicit customer requirement.
EXPLICIT = "EXPLICIT"
INFERRED_HIGH = "INFERRED_HIGH"
INFERRED_MEDIUM = "INFERRED_MEDIUM"

# V2.20d - explicit product/brand EXCLUSION markers (distinct from
# app.session_state._BRAND_REMOVAL_MARKERS, which only means "stop
# requiring the currently active brand", never enforces a hard block).
# Deliberately narrow, longest/most-specific-first so "ale nie od" is tried
# before its own substring "nie od" - covers only the forms confirmed by
# V2.20b evidence (regbug-style negation_0003/product_search_0004) plus the
# closely analogous forms the fix's own mandate named ("iny/ina/ine nez").
# Fails OPEN by design (Section 33): a marker with no recognizable known
# brand/subfamily after it does nothing, never guesses.
_EXCLUSION_MARKERS = ("ale nie od ", "nie od ", "ale nie ", "nechcem ", "iny nez ", "ina nez ", "ine nez ")
_EXCLUSION_CLAUSE_END_RE = re.compile(r"[,.;!?]")
# A single compact word/hyphenated-word (e.g. "aroy-d", "kikkoman") - used
# as a fallback brand-shaped exclusion candidate when `known_brands` (built
# from the catalog's own `brand` FIELD) does not recognize it. This catalog
# stores the manufacturer/importer name in `brand` ("Thai Agri Foods Public
# Company Limited"), not the marketing name printed on the title
# ("AROY-D") - confirmed by direct catalog inspection - so a known-brands-
# only check would silently miss real marketing-brand exclusions entirely
# (Section 34/35 of the originating mandate: fall back to title-matching
# convention when structured brand metadata is absent/unreliable). A
# multi-word vague phrase ("nieco prilis slane") never matches this shape,
# so it never becomes an exclusion (Section 33 fail-open).
_NAMED_ENTITY_RE = re.compile(r"^[a-z][a-z0-9-]{2,}$")


def _looks_like_named_entity(clause_text: str) -> bool:
    return bool(_NAMED_ENTITY_RE.match(clause_text.strip()))


def _find_exclusion_span(normalized_message: str) -> tuple[int, int, str] | None:
    """First EXPLICIT exclusion marker's (span_start, span_end, clause_text) -
    span_start/span_end cover marker+clause so the caller can cut it out of
    the text used for POSITIVE detection; clause_text is only the words
    between the marker and the next clause boundary (comma/period/
    semicolon/?/! or end of string), which is what gets checked against
    known brands/taxonomy. Returns None if no marker is present."""
    for marker in _EXCLUSION_MARKERS:
        idx = normalized_message.find(marker)
        if idx == -1:
            continue
        clause_start = idx + len(marker)
        end_match = _EXCLUSION_CLAUSE_END_RE.search(normalized_message, clause_start)
        clause_end = end_match.start() if end_match else len(normalized_message)
        clause_text = normalized_message[clause_start:clause_end].strip()
        if clause_text:
            return idx, clause_end, clause_text
    return None


# V2.20f - comparative-continuation words ("iné"/"iný"/"iná" - "show me
# OTHER X") immediately after an exclusion clause. Bounded, explicit set
# only (Section 44 of the originating mandate) - not a general grammar.
_RELATED_SUBJECT_CONTINUATION_MARKERS = ("ine ", "iny ", "ina ", "inu ", "ineho ", "inej ")


def related_subject_suppression_span(message: str) -> tuple[int, int] | None:
    """A WIDER span than _find_exclusion_span() above - that clause and
    its brand/subfamily resolution feeding parse_structured_query()/
    retrieval are completely UNCHANGED (Section 84 of the V2.20f mandate).
    This span exists only for app.main.detect_related_subject() to decide
    whether a RELATED_SUBJECT_ALIASES occurrence is positive current-turn
    evidence (Section 39 - reuses the SAME marker detection rather than a
    second, independent negation parser).

    When the exclusion clause is immediately followed by one of the
    bounded continuation markers, the exclusion semantically governs the
    REST of the sentence, not just the clause up to the first punctuation
    mark - "Nechcem sriracha omácku, ukáž mi iné pikantné omáčky" means
    "[show me] other [sauces] than what I excluded", not an unrelated
    second request, so "pikantné" occurring after "iné" must not count as
    positive related-subject evidence either. Without a continuation
    marker, the span is exactly the same narrow clause as V2.20d's own
    exclusion (e.g. "chcem omácku, ale nie sriracha" - no continuation
    word, so only "sriracha" itself is suppressed)."""
    normalized = search_normalize(message)
    span = _find_exclusion_span(normalized)
    if span is None:
        return None
    marker_start, clause_end, _clause_text = span
    tail = f" {normalized[clause_end:].lstrip(' ,.;!?')} "
    if any(f" {marker}" in tail for marker in _RELATED_SUBJECT_CONTINUATION_MARKERS):
        return marker_start, len(normalized)
    return marker_start, clause_end

# Dietary phrase stems -> the same facet vocabulary app.taxonomy already
# derives from real category memberships (_DIETARY_CATEGORY_TERMS) - never
# an invented health claim (Section 19). Matched as a normalized substring,
# so both "bezlepkova"/"bezlepkove"/"bezlepkovej" hit "bezlepkov".
#
# V2.16b: "vegansk"/"vegetariansk" REMOVED - app.taxonomy._DIETARY_CATEGORY_
# TERMS no longer produces "vegan"/"vegetarian" facets at all (proven
# unreliable breadcrumb signal, see that module's docstring), so detecting
# these stems here would only ever hard-filter against a permanently-empty
# index, silently returning zero matches instead of falling through to
# ordinary relevance search. Removed at the source instead.
_DIETARY_QUERY_STEMS: dict[str, str] = {
    "bezlepkov": "gluten_free",
    "gluten free": "gluten_free",
    "bio ": "organic",
}

_QUERY_MULTIPACK_RE = re.compile(
    r"(?P<count>\d+)\s*[x×]\s*(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>kg|g|ml|l)\b"
)
_QUERY_SIZE_RE = re.compile(r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>kg|g|ml|l)\b")


@dataclass
class StructuredProductQuery:
    """What the customer asked for, structurally - see V2.4 spec Section 4.

    `explicit_constraints` names which of the fields below were stated by
    the customer (directly or via a recognized compound taxonomy phrase);
    `constraint_sources` records the tier for every populated field, not
    only the explicit ones. Fields nobody could infer keep their empty
    default and are simply absent from both.
    """

    raw_query: str = ""
    family: str | None = None
    subfamily: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    brand: str | None = None
    package_size: PackageSize | None = None
    dietary_facets: list[str] = field(default_factory=list)
    concept_id: str = ""
    excluded_brand: str | None = None
    excluded_subfamily: str | None = None
    explicit_constraints: set[str] = field(default_factory=set)
    constraint_sources: dict[str, str] = field(default_factory=dict)
    confidence: str = "UNKNOWN"  # HIGH / MEDIUM / LOW / UNKNOWN, taxonomy-style

    @property
    def has_structured_family(self) -> bool:
        return bool(self.family)


def _match_taxonomy_rule(normalized_query: str) -> FamilyRule | None:
    """Same most-specific-first, collision-guarded scan classify_product()
    runs against a product title - here against query text. A query never
    has a "category", so every match is inherently the title-only path."""
    query_tokens = raw_tokens(normalized_query)
    if (query_tokens & _RICE_ROOT_TOKENS) and (query_tokens & _SUSHI_TOKENS):
        sushi_rule = FAMILY_DEFINITIONS_BY_ID.get("sushi_rice")
        if sushi_rule is not None:
            return sushi_rule

    for rule in FAMILY_DEFINITIONS:
        if rule.exclude_title_phrases and any(p in normalized_query for p in rule.exclude_title_phrases):
            continue
        hit = next((p for p in rule.title_phrases if p in normalized_query), None)
        if hit is not None:
            return rule
    return None


def _detect_brand(normalized_query: str, known_brands: Iterable[str]) -> str | None:
    """Longest matching known catalog brand (normalized), so a short brand
    name cannot shadow a longer, more specific one mentioned in the same
    query. Padded with spaces the same way classify_rice_query() already
    guards word-boundary phrase matches in this codebase."""
    padded = f" {normalized_query} "
    best: str | None = None
    for brand in known_brands:
        if not brand:
            continue
        if f" {brand} " in padded and (best is None or len(brand) > len(best)):
            best = brand
    return best


def _detect_package_size(normalized_query: str) -> PackageSize | None:
    multipack = _QUERY_MULTIPACK_RE.search(normalized_query.replace(",", "."))
    if multipack:
        return PackageSize(
            raw=multipack.group(0),
            value=float(multipack.group("value")),
            unit=multipack.group("unit"),
            multipack_count=int(multipack.group("count")),
        )
    simple = _QUERY_SIZE_RE.search(normalized_query.replace(",", "."))
    if simple:
        return PackageSize(raw=simple.group(0), value=float(simple.group("value")), unit=simple.group("unit"))
    return None


def _detect_dietary_facets(normalized_query: str) -> list[str]:
    facets: list[str] = []
    for stem, facet in _DIETARY_QUERY_STEMS.items():
        if stem in normalized_query and facet not in facets:
            facets.append(facet)
    return facets


def parse_structured_query(
    message: str,
    known_brands: Iterable[str] = (),
) -> StructuredProductQuery:
    """Pure, deterministic parse of a free-text customer query.

    `known_brands` should be normalized (app.search.normalize) brand
    strings actually present in the current catalog - passing the live
    catalog's brand set (not a hardcoded list) is what keeps this grounded
    in real data rather than invented brand names.
    """
    normalized = search_normalize(message)
    query = StructuredProductQuery(raw_query=message)

    # V2.20d - resolve an explicit exclusion clause BEFORE any positive
    # detection runs, so a named entity the customer excluded ("nechcem
    # sriracha", "ale nie od AROY-D") can never also register as a
    # positive family/subfamily/brand requirement further down. Only
    # cut the clause out of `positive_text` once it resolves to a REAL
    # known brand or taxonomy subfamily (fail open on anything else -
    # Section 33: ambiguous phrasing must never turn into a hard filter).
    positive_text = normalized
    exclusion_span = _find_exclusion_span(normalized)
    if exclusion_span is not None:
        span_start, span_end, clause_text = exclusion_span
        excluded_rule = _match_taxonomy_rule(clause_text)
        if excluded_rule is not None and excluded_rule.subfamily:
            query.excluded_subfamily = excluded_rule.subfamily
        excluded_brand_hit = _detect_brand(clause_text, known_brands)
        if not excluded_brand_hit and not excluded_rule and _looks_like_named_entity(clause_text):
            excluded_brand_hit = clause_text.strip()
        if excluded_brand_hit:
            query.excluded_brand = excluded_brand_hit
        if query.excluded_subfamily or query.excluded_brand:
            positive_text = normalized[:span_start] + " " + normalized[span_end:]

    rule = _match_taxonomy_rule(positive_text)
    if rule is not None:
        query.family = rule.family
        query.subfamily = rule.subfamily
        query.concept_id = rule.rule_id
        query.explicit_constraints.add("family")
        query.constraint_sources["family"] = EXPLICIT
        # A match on the family's own generic/bare-noun rule (e.g. "ryza")
        # names the family only - subfamily/attributes stay inferred, or a
        # broad "ryža" query would wrongly exclude sushi/jasmine/basmati
        # rice from its own family (breaks specificity monotonicity,
        # Section 26). Every OTHER rule already requires a qualified/
        # compound phrase to match at all (e.g. "sojova omacka",
        # "cervena kari pasta") - the match itself is the hard constraint,
        # whether or not the rule also carries an attributes tuple
        # (most sauce/paste/seaweed/instant_food subfamily rules do not).
        if rule.rule_id in _GENERIC_FAMILY_ONLY_RULE_IDS:
            query.constraint_sources["subfamily"] = INFERRED_HIGH
        else:
            if rule.subfamily:
                query.subfamily = rule.subfamily
                query.explicit_constraints.add("subfamily")
                query.constraint_sources["subfamily"] = EXPLICIT
            if rule.attributes:
                query.attributes = dict(rule.attributes)
                query.explicit_constraints.add("attributes")
                query.constraint_sources["attributes"] = EXPLICIT
        # Same title-only downgrade classify_product() applies: a query never
        # supplies "category" evidence, so a HIGH-confidence rule's match
        # here is only ever as reliable as a title-only catalog match.
        query.confidence = _CONFIDENCE_DOWNGRADE.get(rule.confidence, rule.confidence)
    else:
        query.confidence = "UNKNOWN"

    brand = _detect_brand(positive_text, known_brands)
    if brand:
        query.brand = brand
        query.explicit_constraints.add("brand")
        query.constraint_sources["brand"] = EXPLICIT

    size = _detect_package_size(normalized)
    if size is not None:
        query.package_size = size
        query.explicit_constraints.add("package_size")
        query.constraint_sources["package_size"] = EXPLICIT

    dietary = _detect_dietary_facets(normalized)
    if dietary:
        query.dietary_facets = dietary
        query.explicit_constraints.add("dietary_facets")
        query.constraint_sources["dietary_facets"] = EXPLICIT

    return query


def query_from_constraints(
    raw_query: str,
    *,
    family: str,
    subfamily: str | None = None,
    attributes: dict[str, str] | None = None,
    concept_id: str = "",
) -> StructuredProductQuery:
    """Build a StructuredProductQuery directly from already-known
    constraints - the V2.2 autocomplete APPLY_CONSTRAINTS handoff path
    (Section 50). Never re-derives from raw_query text: a customer who
    clicked a concrete taxonomy_category_suggestions() suggestion already
    supplied server-verified family/subfamily/attributes, so re-parsing the
    label text would be redundant and could disagree with what they clicked
    (Section 51 - only ever trust taxonomy fields the server itself knows,
    never take arbitrary client-provided constraints on faith beyond that)."""
    query = StructuredProductQuery(raw_query=raw_query, family=family, subfamily=subfamily, concept_id=concept_id)
    query.explicit_constraints.add("family")
    query.constraint_sources["family"] = EXPLICIT
    if attributes:
        query.attributes = dict(attributes)
        query.explicit_constraints.add("attributes")
        query.constraint_sources["attributes"] = EXPLICIT
    if subfamily:
        query.explicit_constraints.add("subfamily")
        query.constraint_sources["subfamily"] = EXPLICIT
    query.confidence = "HIGH"
    return query


def merge_constraints(
    base: StructuredProductQuery,
    addition: StructuredProductQuery,
    *,
    remove_size: bool = False,
    remove_brand: bool = False,
) -> StructuredProductQuery:
    """V2.5 follow-up narrowing (Section 13): "jazmínová ryža" then "len 5
    kg" must keep family=rice/variety=jasmine and only ADD package_size,
    never restart interpretation from the short follow-up message alone.
    `addition.package_size`/`addition.brand` OVERRIDE the base value when
    present (Section 9 of V2.9 - "radšej 1 kg" replaces 5kg, never keeps
    both) because `or` already prefers the truthy `addition` side.

    Caller is responsible for only merging when `addition` genuinely has
    no family of its own (a follow-up that DOES name a new family/concept
    is a fresh query, not a narrowing - see app.structured_search).

    `remove_size`/`remove_brand` (V2.9 Section 10/21/63/64) - explicit
    customer removal ("na veľkosti nezáleží", "nemusí byť Kikkoman"),
    detected by app.session_state's deterministic text markers (not
    something `addition`'s own parse would produce, since there is no
    positive value to parse out of a removal phrase). Removal wins over
    whatever `addition`/`base` would otherwise have supplied."""
    merged_size = None if remove_size else (addition.package_size or base.package_size)
    merged_brand = None if remove_brand else (addition.brand or base.brand)
    merged = StructuredProductQuery(
        raw_query=f"{base.raw_query} {addition.raw_query}".strip(),
        family=base.family,
        subfamily=base.subfamily,
        attributes=dict(base.attributes),
        concept_id=base.concept_id,
        brand=merged_brand,
        package_size=merged_size,
        dietary_facets=list(dict.fromkeys([*base.dietary_facets, *addition.dietary_facets])),
        excluded_brand=addition.excluded_brand or base.excluded_brand,
        excluded_subfamily=addition.excluded_subfamily or base.excluded_subfamily,
        confidence=base.confidence,
    )
    merged.explicit_constraints = (set(base.explicit_constraints) | set(addition.explicit_constraints))
    if remove_size:
        merged.explicit_constraints.discard("package_size")
    if remove_brand:
        merged.explicit_constraints.discard("brand")
    merged.constraint_sources = {**base.constraint_sources, **addition.constraint_sources}
    return merged
