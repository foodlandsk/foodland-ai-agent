"""
app/explanation.py  -  V2.16e Recommendation Explanation ("Why this?")

Answers a direct follow-up ("Preco mi odporucas tento?", "Preco prave
tento?", "Preco nie ten druhy?") by re-explaining the customer's LAST
successfully resolved recommendation/comparison/basket decision from
the exact evidence already computed for it - never a fresh, invented
reason (Section 2/17 of the V2.16e spec).

WHY THIS DID NOT EXIST BEFORE (confirmed live during V2.16e
characterization, not hypothetical): a bare "preco"/"why" already
matched app.main.is_article_info_intent()'s broad marker set (that
module answers genuine informational questions like "preco je citronova
trava aromaticka?"), so a why-followup about an actual prior
recommendation was silently swallowed by the FAQ/article-info cascade
instead - reproduced live as two distinct failure modes: (1) "Preco mi
odporucas tento?" after a use_case_advice answer was reinterpreted as a
fresh literal product search for the recommended item's name, returning
"Ano, rvza na sushi v tomto variante mame v ponuke:" - a complete
non-answer; (2) "Preco prave tento?" after a product_search landed on
an unrelated Products_AI knowledge record and surfaced a fragment of
its text verbatim, which (compounding a second, independent, more
severe bug - see app.knowledge._is_broken_curation_placeholder's
docstring) was in that specific case a broken internal AI-authoring
template placeholder, not real content at all.

WHY A NEW (SMALL) MODULE, NOT A NEW EVIDENCE FRAMEWORK (Section 50 Gate
C - "small evidence -> customer-reason adapter"): app.comparison,
app.use_case_advice and app.basket_completion each already compute
real, structured evidence for their own decision (EvidenceItem/
reason_code/confidence, or ComparisonDecision.reason_codes, or
BasketRole.confidence) - this module never recomputes or reinvents that
evidence, it only re-renders the SAME reason_code vocabulary those
three modules already use (product_type_fit/price_fit/unit_price_fit/
size_fit/brand_fit - confirmed by direct audit to be the SAME strings
across all three sources) from a small, uniform snapshot each of them
stores in session memory right after composing their own normal answer
(app.session_state.set_last_explanation()). No new decision_id, no new
confidence scale, no new reason-code namespace (Section 47).

AMBIGUITY (Section 18): a why-followup is answered only when the prior
decision names exactly ONE explainable focal recommendation.
use_case_advice always does (one role/product-family recommendation
per turn, by that module's own design). comparison does only when the
decision resolved a CLEAR_WINNER (any other state has no single winner
to explain - answered honestly instead, never guessed).
basket_completion does only when exactly one role resolved to a real
product (RESOLVED_PRODUCT/ALREADY_COVERED) - more than one is
genuinely ambiguous ("ktory presne?") and CLARIFYs rather than guessing
which of several basket items the customer means.

"WHY NOT THE OTHER ONE?" (Section 19): never fabricates a negative
reason for the non-winner. Only ever states the POSITIVE, grounded
basis the winner actually won on, plus an explicit sentence that no
evidence exists to call the other product worse.
"""
from __future__ import annotations

# Shared with app.comparison._REASON_LABELS_SK / app.use_case_advice's
# RoleEvidence.reason_code / app.basket_completion's EvidenceItem
# reason_code - the SAME vocabulary, not a competing one (Section 38 -
# do not duplicate equivalent evidence under a different name).
_REASON_LABELS_SK = {
    "price_fit": "cena",
    "unit_price_fit": "cena za jednotku množstva",
    "size_fit": "veľkosť balenia",
    "brand_fit": "značka",
    "product_type_fit": "zaradenie v katalógu podľa typu produktu",
    "use_case_fit": "vhodnosť na dané použitie",
}

# Section 41 - natural customer language, never internal term names.
_CONFIDENCE_HEDGE_SK = {
    "HIGH": "",
    "MEDIUM": " Odporúčam si to však overiť v detaile produktu.",
    "LOW": " Táto zhoda je len orientačná, odporúčam overiť detail produktu.",
    "INSUFFICIENT": "",
}

_DEMONSTRATIVE_MARKERS = (
    "tento", "toto", "tuto", "tuto ", "ten produkt", "tu polozku",
    "ten druhy", "tu druhu", "ta druha", "ti dvaja", "tie dva",
)
_RECOMMENDATION_VERB_MARKERS = (
    "odporucas", "odporucam", "odporuca", "odporucal", "odporucala",
    "vybral", "vybrala", "navrhujes", "navrhujem", "navrhuje",
)
_WHY_NOT_MARKERS = ("nie ten", "nie tu", "druh", "iny", "ostatn")


def _normalize(message: str) -> str:
    from app.search import normalize

    return f" {normalize(message)} "


def looks_like_why_followup(message: str) -> bool:
    """Deliberately narrower than app.main.is_article_info_intent()'s
    bare "preco"/"why" marker (Section 41 of this module's docstring) -
    requires a demonstrative ("tento"/"ten druhy") or an explicit
    recommendation verb ("odporucas") co-occurring, so a genuine
    informational question ("preco je citronova trava aromaticka?")
    is left alone for the existing article-info cascade to answer,
    exactly as before."""
    normalized = _normalize(message)
    has_why = any(marker in normalized for marker in (" preco ", " prečo ", " proc "))
    if not has_why:
        return False
    return any(marker in normalized for marker in _DEMONSTRATIVE_MARKERS + _RECOMMENDATION_VERB_MARKERS)


def is_why_not_other_variant(message: str) -> bool:
    normalized = _normalize(message)
    return any(marker in normalized for marker in _WHY_NOT_MARKERS)


def _reason_phrase_sk(reason_codes: list[str]) -> str:
    labels = [_REASON_LABELS_SK.get(code, code) for code in reason_codes if code]
    labels = list(dict.fromkeys(labels))  # dedupe, preserve order (Section 38)
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " a " + labels[-1]


def compose_why_answer(explanation: dict | None, message: str, query_language: str = "sk") -> tuple[str, list[str]]:
    """Returns (answer_text, explained_product_ids). Never invents a
    reason not already present in `explanation` (Section 2/11) - every
    branch below only re-renders fields that were already computed and
    stored by the source workflow's own executor."""
    is_en = query_language == "en"

    if not explanation:
        if is_en:
            return (
                "I don't have a saved reason for a specific recommendation right now - "
                "which product are you asking about?"
            ), []
        return (
            "Momentálne nemám uložený dôvod k žiadnemu konkrétnemu odporúčaniu - "
            "ktorý produkt presne máte na mysli?"
        ), []

    workflow = explanation.get("workflow")

    if workflow == "use_case_advice":
        label = explanation.get("display_label_sk") or ""
        reason_phrase = _reason_phrase_sk([explanation.get("reason_code")])
        hedge = _CONFIDENCE_HEDGE_SK.get(explanation.get("confidence"), "")
        use_case_label = explanation.get("use_case_label_sk") or explanation.get("use_case") or ""
        if is_en:
            text = f"For {use_case_label}, I recommend {label} - based on {reason_phrase}.{hedge}"
        else:
            text = f"Na {use_case_label} odporúčam {label} - na základe: {reason_phrase}.{hedge}"
        return text, list(explanation.get("product_ids") or [])

    if workflow == "basket_completion":
        roles = explanation.get("roles") or []
        resolved = [r for r in roles if r.get("status") in ("RESOLVED_PRODUCT", "ALREADY_COVERED") and r.get("product_id")]
        if len(resolved) != 1:
            if is_en:
                return (
                    "Which item exactly - I have several in that shopping list: "
                    + ", ".join(r.get("display_label_sk", "") for r in resolved) + "?"
                ), []
            return (
                "Ktorú položku presne máte na mysli? V tomto zozname mám viac produktov: "
                + ", ".join(r.get("display_label_sk", "") for r in resolved) + "."
            ), []
        role = resolved[0]
        if role.get("status") == "ALREADY_COVERED":
            if is_en:
                return f"{role.get('display_label_sk')} is already marked as something you have.", [role.get("product_id")]
            return f"{role.get('display_label_sk')} je označené ako niečo, čo už máte.", [role.get("product_id")]
        reason_phrase = _reason_phrase_sk([role.get("reason_code") or "product_type_fit"])
        hedge = _CONFIDENCE_HEDGE_SK.get(role.get("confidence"), "")
        if is_en:
            text = f"It fills the {role.get('display_label_sk')} role in your shopping list - based on {reason_phrase}.{hedge}"
        else:
            text = f"Dopĺňa rolu \"{role.get('display_label_sk')}\" vo vašom nákupnom zozname - na základe: {reason_phrase}.{hedge}"
        return text, [role.get("product_id")]

    if workflow == "comparison":
        state = explanation.get("state")
        product_ids = list(explanation.get("product_ids") or [])
        if state != "CLEAR_WINNER":
            if is_en:
                return (
                    "I didn't pick a single winner for that comparison - "
                    + (explanation.get("no_winner_reason_en") or "the data didn't show one product dominating.")
                ), product_ids
            return (
                "Pri tomto porovnaní som nevybrala jednoznačného víťaza - "
                + (explanation.get("no_winner_reason_sk") or "z dostupných údajov jeden produkt jednoznačne nevynikal.")
            ), product_ids
        reason_phrase = _reason_phrase_sk(explanation.get("reason_codes") or [])
        winner_id = explanation.get("winner_product_id")
        if is_why_not_other_variant(message):
            if is_en:
                text = (
                    f"I picked it based on {reason_phrase} - I don't have grounded evidence "
                    "to say the other product is worse, only that this one won on that dimension."
                )
            else:
                text = (
                    f"Vybrala som ho na základe: {reason_phrase} - nemám doklad na to, že ten druhý produkt "
                    "je horší, len že tento vyhráva v tomto porovnaní."
                )
        else:
            if is_en:
                text = f"I picked it based on {reason_phrase}."
            else:
                text = f"Vybrala som ho na základe: {reason_phrase}."
        return text, ([winner_id] if winner_id else product_ids)

    if not explanation:
        pass
    if is_en:
        return "I don't have a saved reason for that recommendation - which product do you mean?", []
    return "Nemám uložený dôvod k tomuto odporúčaniu - ktorý produkt máte na mysli?", []
