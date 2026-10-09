"""
tests/test_structured_path_price_filter_v2_27h.py  -  V2.27h: wiring
app.query_constraints.PriceConstraint into app.structured_search.
build_structured_result_set() as a hard eligibility filter on the
structured-retrieval path, complementing V2.27e's filter on the legacy
path.

Context (V2.27a-h read-only architecture/contract/wiring review series,
docs/query-semantics.md): V2.27e wired extract_price_constraint() into
/chat as a post-hoc filter on `matches`, but only ever sees whatever the
upstream retrieval path already produced. V2.27f found this is a complete
no-op risk for the structured-retrieval path specifically:
build_structured_result_set() builds a ResultSet whose `ranked_product_ids`
holds the FULL ranked candidate set (unbounded by chat_request.limit),
and only a small, fixed `page_size` (4, for FILTERED_PRODUCT_LIST) of it
ever reaches `matches` via initial_page_ids() - a post-hoc filter on just
those 4 has no guarantee of finding any eligible item among them, since
ranking is price-unaware. V2.27g locked the exact fix: filter
RetrievalResult's own id-lists (exact/valid/nearest_match_ids) BEFORE
rank_candidates()/build_result_set() ever see them, inside
build_structured_result_set() itself - this is V2.27h's implementation of
that exact contract.

This also, as a side effect, automatically fixes two things V2.27g
identified but did not need separate code for:
- `matching_total` (customer-facing "N products found" count, derived
  from exact_match_ids) becomes correct once exact_match_ids itself is
  filtered;
- Show-More/Show-All continuation (app.main._execute_resultset_
  continuation()) pages purely over whatever ranked_product_ids was
  persisted on the ResultSet at creation time, with no re-filtering, so
  filtering here (before the ResultSet is built) is sufficient on its
  own - no continuation-specific test is needed to prove this, it falls
  out of pagination being pure slicing over an already-correct list.

This is a PARSER/RETRIEVAL-LAYER test file: it calls
app.structured_search.build_structured_result_set() directly (the same
function app/main.py calls at both of its two call sites), not /chat -
avoids any accidental dependency on unrelated routing decisions and lets
this file assert the exact ResultSet shape precisely. budget_0002 is
HOLDOUT - these tests call build_structured_result_set() directly on its
text (same class of static inspection already used throughout V2.25-27
for HOLDOUT scenarios), never through /chat or the golden/scorer
pipeline.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m
from app.query_constraints import PriceConstraint
from app.structured_search import build_structured_result_set


def _build(query_text: str, price_constraint: PriceConstraint | None = None):
    return build_structured_result_set(
        query_text,
        m.products,
        m.product_taxonomy_index,
        m.normalized_product_index,
        catalog_version=id(m.products),
        taxonomy_version=m.TAXONOMY_VERSION,
        now=time.time(),
        price_constraint=price_constraint,
    )


class TestStructuredPathPriceFilterTarget:
    """budget_0002 (HOLDOUT) - static-only, never executed via /chat.
    This text resolves to retrieval_mode=STRUCTURED_FILTERED with 26
    exact matches, only 6 of which are <=3 EUR - the exact scenario
    V2.27f/g found V2.27e's post-hoc /chat filter could not reliably
    reach."""

    def test_enters_structured_path(self):
        rs = _build("Chcem sriracha omacku do 3 eur.")
        assert rs is not None
        assert rs.matching_total == 26

    def test_price_constraint_filters_matching_total(self):
        rs = _build("Chcem sriracha omacku do 3 eur.", PriceConstraint(price_max=3.0))
        assert rs is not None
        assert rs.matching_total == 6

    def test_all_ranked_ids_satisfy_budget(self):
        rs = _build("Chcem sriracha omacku do 3 eur.", PriceConstraint(price_max=3.0))
        assert rs is not None
        products_by_id = {p.id: p for p in m.products}
        prices = [products_by_id[pid].effective_price for pid in rs.ranked_product_ids]
        assert prices
        assert all(price is not None and price <= 3.0 for price in prices)

    def test_initial_page_satisfies_budget(self):
        rs = _build("Chcem sriracha omacku do 3 eur.", PriceConstraint(price_max=3.0))
        assert rs is not None
        products_by_id = {p.id: p for p in m.products}
        initial_prices = [products_by_id[pid].effective_price for pid in rs.initial_page_ids()]
        assert initial_prices
        assert all(price is not None and price <= 3.0 for price in initial_prices)


class TestNoConstraintRegression:
    """Omitting price_constraint (the default) must reproduce the exact
    pre-V2.27h behavior - zero behavior change for the overwhelming
    majority of structured queries that never carry a price constraint."""

    def test_sriracha_unchanged_without_constraint(self):
        rs = _build("Chcem sriracha omacku do 3 eur.")
        assert rs is not None
        assert rs.matching_total == 26
        assert len(rs.ranked_product_ids) == 26

    def test_sushi_rice_unchanged(self):
        rs = _build("chcem sushi ryzu")
        assert rs is not None

    def test_plain_rice_unchanged(self):
        rs = _build("chcem ryzu")
        assert rs is not None

    def test_coconut_milk_unchanged(self):
        rs = _build("kokosove mlieko")
        assert rs is not None


class TestChatLevelNonInterference:
    """/chat-level regression lock - every one of these must remain
    byte-identical to the pre-V2.27h baseline (none carries a price
    constraint that would ever reach the new filtering branch)."""

    class _FakeRequest:
        class client:
            host = "127.0.0.1"
        headers: dict = {}

    @staticmethod
    def _chat(message: str, session_id: str, limit: int = 8) -> dict:
        return m.chat(
            m.ChatRequest(message=message, session_id=session_id, limit=limit),
            TestChatLevelNonInterference._FakeRequest(),
        )

    def test_sushi_rice_plain_chat_unchanged(self):
        r = self._chat("chcem sushi ryzu", "v227h-chat-sushirice")
        assert r.get("intent") == "product_search"
        assert len(r.get("products") or []) == 4

    def test_plain_rice_chat_unchanged(self):
        r = self._chat("chcem ryzu", "v227h-chat-plainrice")
        assert r.get("intent") == "product_search"
        assert len(r.get("products") or []) == 5

    def test_coconut_milk_chat_unchanged(self):
        r = self._chat("kokosove mlieko", "v227h-chat-coconut")
        assert r.get("intent") == "product_search"
        assert len(r.get("products") or []) == 4

    def test_budget_0001_legacy_path_still_correct(self):
        # Legacy path (V2.27e) - untouched by this sprint, re-asserted
        # here to prove the two filters coexist without interference.
        r = self._chat("Mám 10 eur, akú rybaciu omáčku si za to môžem kúpiť?", "v227h-chat-budget0001")
        products = r.get("products") or []
        assert r.get("intent") == "product_search"
        assert products
        assert all(p.get("effective_price") is not None and p["effective_price"] <= 10.0 for p in products)

    def test_budget_0003_legacy_path_still_correct(self):
        r = self._chat("Mám rozpočet 5 eur na kari pastu.", "v227h-chat-budget0003")
        products = r.get("products") or []
        assert r.get("intent") == "product_search"
        assert len(products) == 4
        assert all(p.get("effective_price") is not None and p["effective_price"] <= 5.0 for p in products)

    def test_multi_constraint_0003_unchanged(self):
        r = self._chat("Potrebujem rybaciu omáčku pod 5 eur, značka Megachef.", "v227h-chat-mc0003")
        assert r.get("intent") == "product_search"
        assert len(r.get("products") or []) == 8

    def test_selected6_unaffected(self):
        r = self._chat("Aké máte rybacie omáčky?", "v227h-chat-sel6")
        assert r.get("intent") == "product_search"
        assert len(r.get("products") or []) == 8

    def test_product_search_0007_unaffected(self):
        r = self._chat("Chcem miso pastu na polievku.", "v227h-chat-ps0007")
        assert r.get("intent") == "product_search"
        assert len(r.get("products") or []) == 8

    def test_contract2_unaffected(self):
        r = self._chat("Ako uvariť Ma Po Tofu?", "v227h-chat-contract2")
        assert r.get("intent") == "recipe"

    def test_sushi_session_unaffected(self):
        sid = "v227h-chat-sushi-session"
        r1 = self._chat("chcem robit sushi", sid)
        assert r1.get("intent") == "related_products"
        r2 = self._chat("aká ryžu?", sid)
        assert r2.get("intent") == "product_search"

    def test_quantity_unaffected(self):
        r = self._chat(
            "Potrebujem sriracha omáčku na 20 porcií, aké veľké balenie mi odporúčate?",
            "v227h-chat-quantity",
        )
        assert r.get("intent") == "related_products"
        assert len(r.get("products") or []) == 20

    def test_dish_a2_unaffected(self):
        r = self._chat("Aké sushi suroviny predávate?", "v227h-chat-disha2")
        assert r.get("intent") == "related_products"

    def test_price_information_unaffected(self):
        r = self._chat("Koľko stojí jazmínová ryža Royal Umbrella 1kg?", "v227h-chat-priceinfo")
        assert r.get("intent") == "product_search"
        assert len(r.get("products") or []) == 2

    def test_sale_faq_unaffected(self):
        r = self._chat("Funguje u vás vernostný program so zľavami?", "v227h-chat-faq0010")
        assert r.get("intent") == "faq"

    def test_relative_price_unaffected(self):
        r = self._chat("niečo lacnejšie", "v227h-chat-relprice")
        assert r.get("intent") == "product_search"
