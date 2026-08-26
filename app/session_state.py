"""
app/session_state.py  -  V2.9 Conversational Memory, Preference & Session
Intelligence

Extends the EXISTING `memory` dict (`app.main.session_memories`, a
process-local `dict[str, dict]`) with new, explicitly-scoped structured
fields instead of introducing a second storage mechanism (Section 32 -
audit first, reuse the simplest storage already in production).

Central invariant (Section 81/82/83/84): this module tracks WHICH task/
concept/recipe a session is currently in - it never decides what a valid
product is (that stays V2.3/V2.4/V2.8), and every field here must have an
explicit reason to still apply to the current turn or it is dropped.
Correct forgetting beats wrong remembering.

All functions are pure over the `memory` dict passed in (the same dict
`app.main.get_session_memory()` already returns and mutates in place) -
no separate session store, no new TTL mechanism (the existing
`SESSION_MEMORY_TTL_SECONDS`/`prune_session_memories()` already covers
every key added here for free).
"""
from __future__ import annotations

import re

from app.search import normalize, tokenize

# ---------------------------------------------------------------------------
# Field access - typed, explicit defaults, never KeyError.
# ---------------------------------------------------------------------------

_RECENT_PRESENTATION_MAX = 8


def get_active_use_case(memory: dict) -> str | None:
    return memory.get("active_use_case") or None


def set_active_use_case(memory: dict, use_case: str | None) -> None:
    memory["active_use_case"] = use_case or ""


def get_active_comparison_pair(memory: dict) -> tuple[str, str] | None:
    """V2.14f - the two product IDs from the last SUCCESSFULLY resolved
    comparison (2 real, distinct targets - never set for a CLARIFY),
    so a bare follow-up criterion ("a lacnejšiu?", "je tá drahšia
    lepšia?") can be re-evaluated against the same pair without the
    customer re-naming both products. Same storage convention as
    active_recipe_id/active_use_case above - a plain memory key, no new
    storage mechanism."""
    pair = memory.get("active_comparison_pair")
    if not pair or len(pair) != 2:
        return None
    return pair[0], pair[1]


def set_active_comparison_pair(memory: dict, product_id_a: str | None, product_id_b: str | None) -> None:
    if product_id_a and product_id_b:
        memory["active_comparison_pair"] = [product_id_a, product_id_b]
    else:
        memory["active_comparison_pair"] = []


def get_last_informational_question(memory: dict) -> str | None:
    """V2.15c - the raw customer message text of the last SUCCESSFULLY
    answered FAQ/informational query this session (store location,
    opening hours, delivery, contact, ...), so a genuinely referential
    follow-up ("Prilož mi Google link na adresu.") that names no new
    subject of its own can re-resolve the SAME FAQ answer instead of
    falling through to an unrelated product search (rt0014). Deliberately
    stores only the RAW QUESTION TEXT, never the answer itself or any
    assistant-generated content (Section 10 of the closure spec - do not
    store entire assistant responses for routing) - re-running it through
    the existing, unmodified best_direct_faq_answer()/best_faq_answer()
    cascade re-derives the identical, already-grounded answer
    deterministically."""
    return memory.get("last_informational_question") or None


def set_last_informational_question(memory: dict, message: str | None) -> None:
    memory["last_informational_question"] = message or ""


def get_active_recipe(memory: dict) -> tuple[str | None, int | None]:
    return memory.get("active_recipe_id") or None, memory.get("recipe_servings") or None


def set_active_recipe(memory: dict, dish_id: str | None, servings: int | None = None) -> None:
    """Starting a DIFFERENT dish than whatever was active drops the prior
    dish's selections/last-asked-ingredient (Section 84 - a role selected
    for Pad Thai must never show as satisfied for Kung Pao); re-confirming
    the SAME active dish (e.g. servings-only update) preserves them."""
    previous_dish_id = memory.get("active_recipe_id") or None
    if dish_id and previous_dish_id and dish_id != previous_dish_id:
        memory["selected_ingredient_products"] = {}
        memory["last_recipe_ingredient_concept"] = ""
    memory["active_recipe_id"] = dish_id or ""
    if servings is not None:
        memory["recipe_servings"] = servings
    elif not dish_id:
        memory["recipe_servings"] = None


def set_recipe_servings(memory: dict, servings: int) -> None:
    memory["recipe_servings"] = servings


def clear_recipe_state(memory: dict) -> None:
    """Hard-switch cleanup (Section 27/84) - drop everything task-scoped to
    the recipe the customer has moved on from."""
    memory["active_recipe_id"] = ""
    memory["recipe_servings"] = None
    memory["last_recipe_ingredient_concept"] = ""
    memory["selected_ingredient_products"] = {}


def clear_use_case_state(memory: dict) -> None:
    memory["active_use_case"] = ""


def get_last_recipe_ingredient_concept(memory: dict) -> str | None:
    return memory.get("last_recipe_ingredient_concept") or None


def set_last_recipe_ingredient_concept(memory: dict, concept_id: str | None) -> None:
    memory["last_recipe_ingredient_concept"] = concept_id or ""


def get_selected_ingredient_products(memory: dict) -> dict[str, str]:
    return dict(memory.get("selected_ingredient_products") or {})


def mark_ingredient_selected(memory: dict, concept_id: str, product_id: str) -> None:
    """Section 18/56/72 - the customer explicitly confirmed/picked a
    product for one recipe role (ordinal reference, explicit product
    mention). Fed into app.recipe_shopping.build_recipe_shopping_plan's
    basket_product_ids so that role shows ALREADY_SATISFIED afterwards -
    Section 19 (do not fabricate basket state): this is only set from an
    explicit customer action resolved this turn, never inferred from a
    product merely being displayed."""
    selected = memory.setdefault("selected_ingredient_products", {})
    selected[concept_id] = product_id


# ---------------------------------------------------------------------------
# Recent presentation + ordinal reference resolution (Section 11-13, 41, 60)
# ---------------------------------------------------------------------------


def track_presentation(memory: dict, product_ids: list[str]) -> None:
    """Bounded (Section 12) - one most-recent presentation, not unlimited
    history. Overwrites the previous one; that is the correct semantics
    for "ten druhy" (refers to what was JUST shown, not some earlier turn)."""
    memory["recent_presentation_ids"] = list(product_ids)[:_RECENT_PRESENTATION_MAX]


def get_recent_presentation(memory: dict) -> list[str]:
    return list(memory.get("recent_presentation_ids") or [])


_ORDINAL_WORDS: dict[str, int] = {
    "prvy": 0, "prva": 0, "prve": 0, "prveho": 0, "prvej": 0, "prvu": 0, "first": 0,
    "druhy": 1, "druha": 1, "druhe": 1, "druheho": 1, "druhej": 1, "druhu": 1, "second": 1,
    "treti": 2, "tretia": 2, "tretie": 2, "tretieho": 2, "tretej": 2, "tretiu": 2, "third": 2,
    "stvrty": 3, "stvrta": 3, "stvrte": 3, "fourth": 3,
}
# Deliberately NO bare digit tokens ("1", "2", "3"...) here (a real bug
# found via live multi-turn testing, spec Section 79): a message like
# "radšej 1 kg" or "chcem 2 ks" contains a bare digit that has nothing to
# do with an ordinal reference - it is a quantity/size. Only an actual
# ordinal WORD (slovenský/anglický) counts as a reference (Section 47 -
# deterministic, but not so loose it collides with ordinary numbers).


def _extract_ordinal_index(message: str) -> int | None:
    normalized = normalize(message)
    tokens = normalized.split()
    for token in tokens:
        if token in _ORDINAL_WORDS:
            return _ORDINAL_WORDS[token]
    return None


def mentions_ordinal_reference(message: str) -> bool:
    """Section 11 - deterministic, no LLM (Section 47). Requires an ordinal
    word; a bare demonstrative ("to", "ten") without one is NOT treated as
    a reference (too weak a signal, would misfire constantly)."""
    return _extract_ordinal_index(message) is not None


def resolve_ordinal_reference(message: str, memory: dict) -> tuple[str | None, bool]:
    """Returns (product_id, needs_clarification). Section 13 - never
    guesses: if an ordinal is mentioned but there is no (or an
    out-of-range) recent presentation, needs_clarification=True and
    product_id=None, rather than picking an arbitrary SKU."""
    index = _extract_ordinal_index(message)
    if index is None:
        return None, False
    presented = get_recent_presentation(memory)
    if index < len(presented):
        return presented[index], False
    return None, True


# ---------------------------------------------------------------------------
# Explicit constraint refinement signals (Section 7-10, 20-21)
# ---------------------------------------------------------------------------

_CHEAPER_MARKERS = ("lacnejsie", "lacnejsia", "lacnejsi", "cheaper", "lacnejsiu", "nieco lacnejsie", "za menej")
_PRICIER_MARKERS = ("drahsie", "drahsia", "drahsi", "kvalitnejsie", "premium", "luxusnejsie")


def detect_price_direction(message: str) -> str | None:
    """Section 20 - "niečo lacnejšie" narrows within the SAME product
    concept (caller's responsibility), never a global cheap-products
    search. Returns "cheaper" | "pricier" | None."""
    normalized = normalize(message)
    if any(marker in normalized for marker in _CHEAPER_MARKERS):
        return "cheaper"
    if any(marker in normalized for marker in _PRICIER_MARKERS):
        return "pricier"
    return None


def rank_by_price_direction(products: list, direction: str, reference_price: float | None = None) -> list:
    """Pure re-rank of an ALREADY-valid candidate list (Section 20 - never
    changes product eligibility, only order). `products` are Product-like
    objects with an `.effective_price` property."""
    priced = [p for p in products if p.effective_price is not None]
    unpriced = [p for p in products if p.effective_price is None]
    reverse = direction == "pricier"
    if reference_price is not None:
        if direction == "cheaper":
            priced = [p for p in priced if p.effective_price < reference_price] or priced
        elif direction == "pricier":
            priced = [p for p in priced if p.effective_price > reference_price] or priced
    priced.sort(key=lambda p: p.effective_price, reverse=reverse)
    return priced + unpriced


_SIZE_REMOVAL_PHRASE_MARKERS = ("akakolvek velkost", "vsetky velkosti", "hocijaka velkost")
_BRAND_REMOVAL_MARKERS = ("nemusi byt", "nezalezi na znacke", "akakolvek znacka", "hocijaka znacka", "nie ")


def detect_size_removal(message: str) -> bool:
    """"na veľkosti nezáleží" (Section 10/64) - token-set match (not exact
    substring) so natural variation ("na veľkosti mi už nezáleží") still
    matches; both "velkost*" and "nezalezi" must appear as tokens."""
    tokens = tokenize(message)
    if any(t.startswith("velkost") for t in tokens) and "nezalezi" in tokens:
        return True
    normalized = normalize(message)
    return any(marker in normalized for marker in _SIZE_REMOVAL_PHRASE_MARKERS)


def detect_brand_removal(message: str) -> bool:
    """Section 10/21/63 - "nemusí byť Kikkoman" / "nie Kikkoman". Detects
    the REMOVAL intent generically; the caller drops whatever brand is
    currently active rather than this function trying to name the exact
    brand (that would duplicate app.query_constraints' own brand
    recognition against `known_brands`)."""
    normalized = normalize(message)
    return any(marker in normalized for marker in _BRAND_REMOVAL_MARKERS)


_RESET_MARKERS = ("zacnime odznova", "zacni odznova", "nove hladanie", "novy hladanie", "zabudni predchadzajuce", "zabudni na predchadzajuce", "od zaciatku", "nova konverzacia")


def detect_reset_request(message: str) -> bool:
    normalized = normalize(message)
    return any(marker in normalized for marker in _RESET_MARKERS)


def apply_reset(memory: dict) -> None:
    """Section 30 - clears shopping/task state only; never touches
    anything account-level (none exists in this system)."""
    memory["active_result_set_id"] = ""
    clear_recipe_state(memory)
    clear_use_case_state(memory)
    memory["recent_presentation_ids"] = []
    memory["subjects"].clear()
    memory["diet_terms"].clear()
    memory["last_top_product_title"] = ""
    memory["active_comparison_pair"] = []
    memory["last_informational_question"] = ""


# ---------------------------------------------------------------------------
# Recipe follow-up detection (Section 16/17/18/53) - the core V2.9<->V2.8
# integration. Deliberately narrow and deterministic (Section 47).
# ---------------------------------------------------------------------------

_RECIPE_FOLLOWUP_QUESTION_MARKERS = (
    "co este", "co chyba", "co mi chyba", "co dalej", "co potrebujem este",
    "co este potrebujem", "co este treba", "co chyba na",
)
# Deliberately excludes bare "aké"/"aký"/"aká"/"aku"/"ktoré"/"ktorý" - those
# are ordinary Slovak question words that show up in countless unrelated
# questions ("akú kategóriu produktov máte?"). A short "which one" follow-up
# about a SPECIFIC ingredient ("aké rezance?") is instead caught by the
# ingredient-token match in app.recipe_shopping.resolve_recipe_followup,
# which only fires when the message names a real ingredient of the active
# recipe - a much stronger, less collision-prone signal than a bare
# question word (Section 84 - a false positive here wrongly keeps a stale
# recipe active).


_LOCATION_REFERENCE_MARKERS = (
    "mapa", "mapy", "mape", "mapu", "google maps", "google mapa", "google mape",
    "navigacia", "navigaciu", "navigacie",
    "dostanem sa", "dostat sa", "ako sa tam", "kade sa tam",
    "adresu", "adresa", "adrese", "adresy",
    "polohu", "poloha", "polohe",
    "google link", "link na adresu", "link na predajnu", "link na obchod",
    "na nu link", "na neho link",
)


def looks_like_location_reference_followup(message: str) -> bool:
    """V2.15c (rt0014) - a narrow, evidence-backed vocabulary for "give me
    more navigational detail about the physical location we were just
    discussing" (e.g. "Prilož mi Google link na adresu.", "Pošli mi
    Google Maps.", "Ako sa tam dostanem?"). Deliberately scoped to
    location/navigation reference only - NOT a general "any follow-up
    should inherit the last FAQ topic" mechanism, which the closure spec
    explicitly warns against (a broad catch-all would risk hijacking
    unrelated follow-ups, e.g. "Pošli mi link na Kikkoman" names its own
    explicit product target and must never reach this path - it simply
    contains none of these markers). The caller additionally requires a
    stored last_informational_question before treating this as a
    genuine follow-up (Section 12 - explicit current-turn target always
    wins; there is nothing to fall back to if nothing was asked before)."""
    normalized = normalize(message)
    return any(marker in normalized for marker in _LOCATION_REFERENCE_MARKERS)


_PAYMENT_METHOD_TOPIC_MARKERS = ("plat", "kartou", "hotovost")

_PAYMENT_METHOD_FOLLOWUP_MARKERS = (
    "apple pay", "google pay", "paypal", "gopay", "go pay",
    "24-pay", "24 pay", "24pay", "tatrapay", "tatra pay",
    "prevod", "dobierka",
)


def looks_like_payment_method_followup(last_informational_question: str, message: str) -> bool:
    """V2.16a - generalizes the same NON_COMMERCE_CONTEXTUAL_FOLLOWUP
    pattern V2.15c established for store_location
    (looks_like_location_reference_followup) to the payment-methods
    topic. Reproduced gap (V2.16a characterization, Case I): "Ako môžem
    zaplatiť?" -> "A Apple Pay?" fell through the entire routing cascade
    into commerce product search, which fuzzy-matched "apple" against
    unrelated catalog items (e.g. "Lepkavá ryža APPLE BRAND"). Reuses the
    SAME single last_informational_question field - no new topic enum, no
    new session-state field, so reset/TTL/cross-session isolation are
    inherited for free exactly as already proven for rt0014. The previous
    question is classified as payment-topic in-line, at recall time, by
    checking whether it itself contains one of the existing
    FAQ_INTENT_MARKERS payment markers (plat/kartou/hotovost) - not a
    persisted label. Deliberately narrow: bare "apple"/"pay"/"karta" are
    NOT markers here (explicit current-turn target always wins - a
    message about an actual product must never be swallowed by this
    path), only specific named payment-method phrases a customer would
    use to ask "does that one work too?" after a payment question. Data
    evidence (data/knowledge.json): Apple Pay/Google Pay are not present
    anywhere in the FAQ records, so this only ever re-derives the real,
    already-grounded payment-methods answer (which does not list them) -
    it never fabricates a yes/no claim about a specific provider."""
    if not any(marker in normalize(last_informational_question) for marker in _PAYMENT_METHOD_TOPIC_MARKERS):
        return False
    normalized = normalize(message)
    return any(marker in normalized for marker in _PAYMENT_METHOD_FOLLOWUP_MARKERS)


_OPENING_HOURS_TOPIC_PHRASE_MARKERS = (
    "otvaracie hodiny", "otvorene hodiny", "prevadzkove hodiny",
    "kedy mate otvorene", "kedy je otvorene", "kedy je predajna otvorena",
    "kedy otvarate", "kedy zatvarate",
    "dokedy mate otvorene", "dokedy je otvorene", "dokedy je predajna otvorena",
    "ste otvoreni", "ste dnes otvoreni", "mate dnes otvorene",
    "otvoreni v sobotu", "otvoreni v nedelu", "otvorene v sobotu", "otvorene v nedelu",
    "opening hours", "business hours",
)
_OPENING_HOURS_CUE_TOKENS = frozenset({"kedy", "dokedy", "hodiny", "hodin"})


def is_opening_hours_query(message: str) -> bool:
    """V2.16a.1 - narrow, evidence-backed opening-hours intent detector.
    Deliberately does NOT add a bare "otvoren" substring to the shared
    FAQ_INTENT_MARKERS list: a blast-radius check against
    data/products.json (V2.16a Section 6, re-verified here) found real
    product description text containing "po otvorení" (storage/usage
    instructions, e.g. Kikkoman Teriyaki BBQ sauce), "otvorenými" (a
    decor item description), and "dotvorenie" (an unrelated word that
    happens to contain the "otvoren" substring) - a bare substring
    marker would misroute a legitimate storage-instruction question
    into the hours FAQ. This detector instead requires either a full,
    evidence-backed phrase match, OR a whole-TOKEN "otvoren*" root
    (tokenize() already prevents mid-word false hits like "dotvorenie")
    PLUS an interrogative/temporal cue token, with an explicit exclusion
    for the exact "po otvoren" collision pattern found in the audit."""
    normalized = normalize(message)
    if "po otvoren" in normalized:
        return False
    if any(marker in normalized for marker in _OPENING_HOURS_TOPIC_PHRASE_MARKERS):
        return True
    tokens = tokenize(message)
    has_otvoren_root = any(t.startswith("otvoren") for t in tokens)
    return has_otvoren_root and bool(tokens & _OPENING_HOURS_CUE_TOKENS)


_OPENING_HOURS_FOLLOWUP_DAY_MARKERS = (
    "pondelok", "utorok", "streda", "stvrtok", "piatok", "sobota", "sobotu", "sobote",
    "nedela", "nedelu", "nedeli", "vikend",
)


def looks_like_opening_hours_followup(last_informational_question: str, message: str) -> bool:
    """V2.16a.1 - generalizes the V2.15c/V2.16a NON_COMMERCE_CONTEXTUAL_
    FOLLOWUP pattern to opening_hours. Reuses the single
    last_informational_question field (no new session state); the
    previous question is classified as opening-hours-topic at recall
    time via is_opening_hours_query(). Deliberately excludes "dnes"/
    "zajtra" (today/tomorrow) from the cue set - resolving those would
    require reliable timezone-aware "what day is it" reasoning this
    codebase does not have; only unambiguous day-name words are used as
    cues, since a bare "dnes"/"zajtra" is common inside unrelated
    commerce queries (e.g. "mate dnes akciu na ryzu?") and would risk
    hijacking them (explicit current-turn target must always win)."""
    if not is_opening_hours_query(last_informational_question):
        return False
    normalized = normalize(message)
    return any(marker in normalized for marker in _OPENING_HOURS_FOLLOWUP_DAY_MARKERS)


_CONTACT_TOPIC_PHRASE_MARKERS = (
    "ako vas mozem kontaktovat", "ako sa da kontaktovat", "ako vas kontaktovat",
    "kontakt na foodland", "kontakt na predajnu", "kontakt na vas",
    "kontaktne udaje", "kontaktny udaj",
    "aky mate telefon", "vas telefon", "telefonne cislo", "telefonny kontakt",
    "vas email", "mate email", "vasa emailova adresa", "vas e-mail",
    "dajte mi kontakt", "posli mi kontakt", "chcem kontakt", "davate kontakt",
)


def is_contact_query(message: str) -> bool:
    """V2.16a.1 - narrow, phrase-only contact-intent detector.
    Deliberately does NOT match on the bare word "kontakt": a
    blast-radius check against data/products.json found real product
    description text using "kontakt s potravinami" (food-contact-safe
    packaging material) and "priamy kontakt s foliou" (plastic wrap) -
    a bare "kontakt" marker would misroute a legitimate
    packaging-safety question into the contact FAQ. Only curated,
    multi-word phrases a customer would actually use to ask "how do I
    reach you" are matched, never the generic word alone."""
    normalized = normalize(message)
    return any(marker in normalized for marker in _CONTACT_TOPIC_PHRASE_MARKERS)


_CONTACT_FOLLOWUP_MARKERS = (
    "telefon", "telefonne cislo", "email", "e-mail", "emailova adresa",
)


def looks_like_contact_followup(last_informational_question: str, message: str) -> bool:
    """V2.16a.1 - generalizes the same pattern to contact. Address/Maps
    follow-ups ("Pošli mi adresu.", "A Google Maps?") after a contact
    topic are already handled for free by the existing
    looks_like_location_reference_followup() path (it is not gated on
    which topic was previously discussed, only on a stored
    last_informational_question existing at all) - this function only
    adds the phone/email cues that path does not cover."""
    if not is_contact_query(last_informational_question):
        return False
    normalized = normalize(message)
    return any(marker in normalized for marker in _CONTACT_FOLLOWUP_MARKERS)


def looks_like_recipe_followup(message: str) -> bool:
    """True when the message reads as a continuation question about an
    already-active recipe (Section 53: "aké rezance?", "čo ešte
    potrebujem?") rather than a fresh, unrelated request. Kept intentionally
    narrow - a false positive here would wrongly keep a stale recipe
    active (Section 84: correct forgetting beats wrong remembering), so
    this is only ONE signal; the caller additionally requires the message
    to either match a known ingredient concept of the active recipe OR one
    of these generic markers, not markers alone (see
    resolve_active_recipe_followup in app/main.py)."""
    normalized = normalize(message)
    if len(tokenize(normalized)) > 8:
        return False
    return any(marker in normalized for marker in _RECIPE_FOLLOWUP_QUESTION_MARKERS)


# ---------------------------------------------------------------------------
# Constraint removal signals bundled into one lightweight resolution object
# for callers that want everything from one call (Section 36).
# ---------------------------------------------------------------------------


class TurnSignals:
    """Section 36 - deterministic, structured turn-level signals a single
    call site can consume. Not a full "TurnResolver" abstraction over the
    whole cascade (Section 1/75 - incremental, not a rewrite) - just the
    concrete signals V2.9's new call sites in app/main.py actually need."""

    __slots__ = (
        "ordinal_product_id", "ordinal_needs_clarification", "price_direction",
        "size_removed", "brand_removed", "reset_requested", "is_recipe_followup",
    )

    def __init__(self, message: str, memory: dict) -> None:
        self.ordinal_product_id, self.ordinal_needs_clarification = resolve_ordinal_reference(message, memory)
        self.price_direction = detect_price_direction(message)
        self.size_removed = detect_size_removal(message)
        self.brand_removed = detect_brand_removal(message)
        self.reset_requested = detect_reset_request(message)
        self.is_recipe_followup = looks_like_recipe_followup(message)
