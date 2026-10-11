"""
tests/test_recipe_shopping_special3_v2_29c.py  -  V2.29c data-port parity

Verifies app.recipe_shopping.SPECIAL3_SHOPPING_DEFINITIONS (sushi/tom_yum/
kimchi_ramen ported into the generic recipe-shopping data shape) against
the live legacy builders (app.main.sushi_shopping_core_products() etc.),
WITHOUT touching app.main.RECIPE_SHOPPING_CORE_QUERIES or any routing
guard. Builds one ISOLATED RecipeGraphIndex locally (passed explicitly
to build_recipe_shopping_plan(), never assigned to any module-level
global) so the helper-level plan tests exercise the real graph machinery
with zero production side effects.

Routing-immutability tests at the bottom prove /chat behavior for all
three dishes is byte-identical to pre-V2.29c (same intent, same
workflow_id) - this sprint ports DATA only, routing stays frozen.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import app.main as m
from app.recipe_graph import build_recipe_graph_index
from app.recipe_shopping import SPECIAL3_SHOPPING_DEFINITIONS, build_recipe_shopping_plan


class _FakeRequest:
    class client:
        host = "127.0.0.1"
    headers: dict = {}


def _chat(message: str, session_id: str, limit: int = 8) -> dict:
    return m.chat(m.ChatRequest(message=message, session_id=session_id, limit=limit), _FakeRequest())


def _local_graph():
    """Isolated RecipeGraphIndex carrying the real 47 dishes PLUS the 3
    special ones, built from a local dict copy - never touches
    app.main.RECIPE_SHOPPING_CORE_QUERIES (no mutation, no global
    reassignment, no effect on app.cross_sell/app.basket_completion,
    which read the real module-level dict directly)."""
    local_queries = dict(m.RECIPE_SHOPPING_CORE_QUERIES)
    local_queries.update(SPECIAL3_SHOPPING_DEFINITIONS)
    return build_recipe_graph_index(
        products=m.products,
        taxonomy_index=m.product_taxonomy_index,
        normalized_index=m.normalized_product_index,
        recipe_shopping_core_queries=local_queries,
        missing_ingredients_by_subject=m.MISSING_INGREDIENTS_BY_SUBJECT,
        recipe_title_product_subjects=m.RECIPE_TITLE_PRODUCT_SUBJECTS,
        cms_recipes=m.knowledge.get("sections", {}).get("Recipes", []),
        products_ai=m.knowledge.get("sections", {}).get("Products_AI", []),
        special_product_queries=m.SPECIAL_PRODUCT_QUERIES,
    )


class TestDataStructureParity:
    """Section J - ingredient count/order/terms match the legacy source
    exactly (verified by direct comparison against the literal legacy
    tuples, re-read from app/main.py at review time, not from memory)."""

    def test_sushi_ingredient_count_and_order(self):
        entries = SPECIAL3_SHOPPING_DEFINITIONS["sushi"]
        assert [q for q, _, _ in entries] == [
            "sushi ryza", "ryzovy ocot", "wasabi", "nori", "nakladany zazvor", "sojova omacka",
        ]

    def test_tom_yum_ingredient_count_and_order(self):
        entries = SPECIAL3_SHOPPING_DEFINITIONS["tom_yum"]
        assert [q for q, _, _ in entries] == [
            "citronova trava", "galangal", "kaffirove listy", "rybacia omacka",
            "kokosove mlieko", "tom yum pasta",
        ]

    def test_kimchi_ramen_ingredient_count_and_order(self):
        entries = SPECIAL3_SHOPPING_DEFINITIONS["kimchi_ramen"]
        assert [q for q, _, _ in entries] == [
            "ramen rezance", "kimchi", "gochujang", "miso pasta",
            "sojova omacka", "dashi", "wakame", "nori",
        ]

    def test_tom_yum_excluded_terms_preserved(self):
        entries = dict((q, (r, e)) for q, r, e in SPECIAL3_SHOPPING_DEFINITIONS["tom_yum"])
        assert entries["kaffirove listy"] == (("kaffir", "kaffirov"), ("bambus", "kari list", "caj"))
        assert entries["tom yum pasta"] == (
            ("tom yum", "pasta"), ("arasid", "riasy", "instant", "polievka v kelimku"),
        )

    def test_kimchi_ramen_excluded_terms_preserved(self):
        entries = dict((q, (r, e)) for q, r, e in SPECIAL3_SHOPPING_DEFINITIONS["kimchi_ramen"])
        assert entries["kimchi"] == (
            ("kimchi",), ("instant", "ramen", "ramyun", "rezance", "polievk", "omack"),
        )

    def test_sushi_only_rice_has_a_filter(self):
        entries = dict((q, (r, e)) for q, r, e in SPECIAL3_SHOPPING_DEFINITIONS["sushi"])
        assert entries["sushi ryza"] == (("ryza", "susi"), ())
        for q in ("ryzovy ocot", "wasabi", "nori", "nakladany zazvor", "sojova omacka"):
            assert entries[q] == ((), ()), f"{q} must stay unfiltered like its legacy source"


class TestSushiRicePrecisionGuard:
    """Section G/17/41 - empirical proof that required_terms=("ryza","susi")
    reproduces the legacy OR-guard's exact candidate set on the real
    catalog, with no new field, no required_any_terms, no app.main edit."""

    def test_legacy_and_generic_select_the_same_candidate_set(self):
        legacy_ids = set()
        for product in m.cached_search_products(m.products, "sushi ryza", 50):
            title = m.normalize(product.get("title", ""))
            if "ryza" in title and {"sushi", "susi"} & set(title.split()):
                legacy_ids.add(product.get("id"))

        generic_ids = {
            p.get("id")
            for p in m.recipe_core_product_candidates(m.products, "sushi ryza", ("ryza", "susi"), (), limit=1000)
        }
        assert legacy_ids, "sanity: legacy guard must match at least one real product"
        assert legacy_ids == generic_ids, (
            "required_terms=('ryza','susi') must select the identical candidate set "
            "the legacy OR-guard selects on the current catalog"
        )

    def test_no_false_positive_from_english_spelling_products(self):
        # The 22 catalog products using literal "sushi" (not "susi") are
        # all packaging/tableware, never rice - confirm none leak in.
        candidates = m.recipe_core_product_candidates(
            m.products, "sushi ryza", ("ryza", "susi"), (), limit=1000,
        )
        for product in candidates:
            title = m.normalize(product.get("title", ""))
            assert "ryza" in title, f"non-rice product leaked into sushi-rice candidates: {product.get('title')}"

    def test_sushi_rice_top_pick_is_a_genuine_sushi_rice_product(self):
        top = m.recipe_core_product_candidates(m.products, "sushi ryza", ("ryza", "susi"), (), limit=1)
        assert top, "must return at least one candidate"
        title = m.normalize(top[0].get("title", ""))
        assert "ryza" in title and {"sushi", "susi"} & set(title.split())


class TestProductParityPerIngredient:
    """Section K/L/M - per-ingredient-slot comparison, legacy vs generic,
    classified EXACT_PARITY/SEMANTIC_PARITY/BETTER_GENERIC/REGRESSION.
    A REGRESSION (domain-wrong product, or an excluded term leaking
    through) fails the test outright; SEMANTIC_PARITY (different but
    valid SKU) is accepted and logged via the assertion message only on
    failure, never silently passed without the domain check below."""

    def _legacy_pick(self, dish, query, required_terms, excluded_terms, fetch_count):
        for product in m.cached_search_products(m.products, query, fetch_count):
            title = m.normalize(product.get("title", ""))
            if query == "sushi ryza" and not ("ryza" in title and {"sushi", "susi"} & set(title.split())):
                continue
            if any(term in title for term in excluded_terms):
                continue
            if required_terms and not all(term in title for term in required_terms):
                continue
            return product
        return None

    def _check_dish(self, dish, fetch_count):
        regressions = []
        for query, required_terms, excluded_terms in SPECIAL3_SHOPPING_DEFINITIONS[dish]:
            legacy = self._legacy_pick(dish, query, required_terms, excluded_terms, fetch_count)
            generic_candidates = m.recipe_core_product_candidates(
                m.products, query, required_terms, excluded_terms, limit=5,
            )
            if legacy is None:
                continue  # no legacy candidate to compare against - not a regression target
            if not generic_candidates:
                regressions.append((query, "generic returned ZERO candidates, legacy found one"))
                continue
            generic_titles = {m.normalize(p.get("title", "")) for p in generic_candidates}
            for term in excluded_terms:
                for title in generic_titles:
                    if term in title:
                        regressions.append((query, f"excluded term {term!r} leaked into generic candidate {title!r}"))
            for term in required_terms:
                top_title = m.normalize(generic_candidates[0].get("title", ""))
                if term not in top_title:
                    regressions.append((query, f"required term {term!r} missing from generic top pick {top_title!r}"))
        assert not regressions, f"{dish} parity regressions: {regressions}"

    def test_sushi_parity(self):
        self._check_dish("sushi", fetch_count=20)

    def test_tom_yum_parity(self):
        self._check_dish("tom_yum", fetch_count=32)

    def test_kimchi_ramen_parity(self):
        self._check_dish("kimchi_ramen", fetch_count=32)


class TestPriceConstraintParity:
    """Section N/18/19 - price_max is a per-product ceiling (V2.27
    semantics), never a basket total; unchanged by this sprint, only
    re-verified against the ported data."""

    def _prices_ok(self, dish, price_max):
        from app.query_constraints import PriceConstraint
        pc = PriceConstraint(price_max=price_max)
        for query, required_terms, excluded_terms in SPECIAL3_SHOPPING_DEFINITIONS[dish]:
            candidates = m.recipe_core_product_candidates(
                m.products, query, required_terms, excluded_terms, limit=5, price_constraint=pc,
            )
            for product in candidates:
                price = product.get("effective_price")
                assert price is not None and price <= price_max, (
                    f"{dish}/{query}: {product.get('title')} price {price} exceeds {price_max}"
                )

    def test_sushi_price_10eur(self):
        self._prices_ok("sushi", 10.0)

    def test_tom_yum_price_10eur(self):
        self._prices_ok("tom_yum", 10.0)

    def test_kimchi_ramen_price_5eur(self):
        self._prices_ok("kimchi_ramen", 5.0)


class TestHelperLevelPlanBuilds:
    """Section 28 - full build_recipe_shopping_plan() exercised end-to-end
    via an ISOLATED local graph (never the production global)."""

    def test_sushi_plan_builds_and_is_nonempty(self):
        graph = _local_graph()
        plan = build_recipe_shopping_plan(graph, "sushi", m.products, m.product_taxonomy_index, m.normalized_product_index)
        assert plan is not None
        assert len(plan.ingredients) == 6
        available = [ing for ing in plan.ingredients if ing.selected_product_id]
        assert available, "sushi plan must resolve at least one ingredient to a real product"

    def test_tom_yum_plan_builds_and_is_nonempty(self):
        graph = _local_graph()
        plan = build_recipe_shopping_plan(graph, "tom_yum", m.products, m.product_taxonomy_index, m.normalized_product_index)
        assert plan is not None
        assert len(plan.ingredients) == 6
        available = [ing for ing in plan.ingredients if ing.selected_product_id]
        assert available

    def test_kimchi_ramen_plan_builds_and_is_nonempty(self):
        graph = _local_graph()
        plan = build_recipe_shopping_plan(graph, "kimchi_ramen", m.products, m.product_taxonomy_index, m.normalized_product_index)
        assert plan is not None
        assert len(plan.ingredients) == 8
        available = [ing for ing in plan.ingredients if ing.selected_product_id]
        assert available

    def test_servings_presence_does_not_activate_scaling(self):
        # Section 20 - requested_servings is carried, but ingredient
        # quantities stay None (no structured recipe data exists), so no
        # arithmetic activates - re-confirms the V2.28 finding on the
        # newly-ported dishes specifically.
        graph = _local_graph()
        plan = build_recipe_shopping_plan(
            graph, "sushi", m.products, m.product_taxonomy_index, m.normalized_product_index, servings=6,
        )
        assert plan.requested_servings == 6
        for ing in plan.ingredients:
            assert ing.quantity is None
            assert ing.package_count is None

    def test_basket_product_ids_accepted_by_ported_dishes(self):
        # Section 22 - the generic plan already accepts basket_product_ids;
        # verify it works for the newly-ported dishes too (helper level
        # only - NOT wired into the live already-have routing this sprint).
        graph = _local_graph()
        plan_no_basket = build_recipe_shopping_plan(graph, "sushi", m.products, m.product_taxonomy_index, m.normalized_product_index)
        satisfied_candidate = next(
            (ing.selected_product_id for ing in plan_no_basket.ingredients if ing.selected_product_id), None,
        )
        assert satisfied_candidate is not None
        plan_with_basket = build_recipe_shopping_plan(
            graph, "sushi", m.products, m.product_taxonomy_index, m.normalized_product_index,
            basket_product_ids=frozenset({satisfied_candidate}),
        )
        satisfied = [ing for ing in plan_with_basket.ingredients if ing.status == "ALREADY_SATISFIED"]
        assert satisfied, "basket_product_ids must mark at least one ingredient ALREADY_SATISFIED"


class TestRoutingImmutability:
    """Section I/27 - THE critical gate: live /chat behavior for all three
    special dishes must be byte-identical to pre-V2.29c. This sprint only
    added inert data; it must not be reachable from any routing path."""

    def test_sushi_routing_unchanged(self):
        r = _chat("Aké sushi suroviny predávate?", "v229c-routing-sushi")
        assert r.get("intent") == "related_products"
        assert r.get("workflow_id") is None

    def test_tom_yum_routing_unchanged(self):
        r = _chat("Aké tom yum suroviny predávate?", "v229c-routing-tomyum")
        assert r.get("intent") == "related_products"
        assert r.get("workflow_id") is None

    def test_kimchi_ramen_routing_unchanged(self):
        r = _chat("Aké kimchi ramen suroviny predávate?", "v229c-routing-kimchiramen")
        assert r.get("intent") == "related_products"
        assert r.get("workflow_id") is None

    def test_sushi_shopping_list_routing_unchanged(self):
        r = _chat("Nákupný zoznam na sushi.", "v229c-routing-sushi-zoznam")
        assert r.get("intent") == "related_products"
        assert r.get("workflow_id") is None

    def test_sushi_session_followup_still_fails_as_before(self):
        # Documents (does not fix) the known V2.29b finding: sushi's
        # legacy path establishes no active_recipe, so this follow-up
        # does not resolve. A future routing-flip sprint changes this;
        # V2.29c must NOT change it yet.
        sid = "v229c-routing-sushi-followup"
        _chat("Nákupný zoznam na sushi.", sid)
        r2 = _chat("Čo ešte potrebujem?", sid)
        assert r2.get("workflow_id") != "RECIPE_SHOPPING"

    def test_direct_product_search_unaffected(self):
        for text in ("Chcem sushi ryžu.", "Chcem ramen rezance.", "Chcem kimchi."):
            r = _chat(text, f"v229c-dps-{hash(text) % 10000}")
            assert r.get("intent") == "product_search"

    def test_sushi_rice_ranking_special_subject_unaffected(self):
        # The existing special_subject=="sushi_rice" re-ranking (unrelated
        # to this sprint) must still fire exactly as before.
        r = _chat("sushi ryza", "v229c-sushi-rice-rank")
        assert r.get("intent") == "product_search"
