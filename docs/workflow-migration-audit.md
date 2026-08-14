# Mapa: `app/workflows.py` → skutočný `/chat` v `app/main.py`

Účel tohto dokumentu: presne zistiť, ktoré vetvy dnešnej `/chat` kaskády (v `app/main.py`) zodpovedajú jednotlivým `WORKFLOW_CONTRACTS` v `app/workflows.py`, ktoré sa prekrývajú len čiastočne a ktoré chýbajú úplne. Toto je čisto analytický dokument – **nemení žiadny kód**. `detect_workflow()` ani `get_contract()` nie sú v produkčnom `/chat` zapojené (potvrdené: `grep -n "detect_workflow\|get_contract" app/main.py` nevráti žiadny výsledok mimo `app/workflows.py` samotného) a týmto dokumentom sa to nemení.

## 1. Prečo `workflows.py` existuje oddelene

`app/workflows.py` (Sprint 1, historicky najstaršia časť tejto vrstvy) je čistá, bezstavová deklaratívna vrstva: `WORKFLOW_PRIORITY`, `detect_workflow()`, `WORKFLOW_CONTRACTS`, `get_contract()`, `build_grounded_ids()`. Má vlastnú testovaciu sadu v `tests/test_core.py`, ktorá prechádza – ale beží len oproti `app/workflows.py` samému, nie oproti skutočnému `/chat`. Reálne sa z tohto modulu do `app/main.py` importuje **iba** `products_to_cart_candidates()` (pomocná funkcia bez routovacej logiky).

Namiesto toho `/chat` počíta desiatky nezávislých booleovských/string signálov priamo vo funkcii (`allergen_term`, `is_faq_query`, `recipe_subject`, `already_have_subject`, `special_subject`, `replacement_subject`, `related_subject`, `article_product_subject`, `cross_sell_matches`, `product_advice_context`, `is_category_discovery_query(...)`...) a na konci z nich odvodí jeden legacy `intent` string cez sériu `if`/ternary výrazov. Sprint V2.1 (`app/intent.py`) k tomu pridal `build_customer_intent()` – čisto aditívny adaptér, ktorý tieto už vypočítané legacy signály iba **prekladá** do kanonickej `CustomerIntent` schémy pre analytiku (`question_analytics.jsonl`). Nemení routing.

## 2. Poradie skutočnej `/chat` kaskády (app/main.py, `def chat()`, ~riadok 3631)

V tomto presnom poradí (prvá zhoda vyhráva a vracia sa):

1. `is_missing_composition_complaint()` → `intent="missing_composition"`
2. `allergen_term` (a `allergen_product_query()` alebo nie je `related_subject`) → `intent="allergen_safety"`
3. `is_faq_query` a nájdená `best_direct_faq_answer()`/`best_faq_answer()` → `intent="faq"`
4. `is_random_recipe_query` → `intent="recipe"` (náhodné recepty podľa kuchyne)
5. `recipe_subject` → `intent="recipe_to_products"` ak sa našli produkty k receptu, inak `"recipe"`
6. `detect_out_of_domain()` → `intent="unknown"`
7. `is_category_discovery_query()` → `intent="category_discovery"` **(nové, Sprint V2.1.6/PR #8 – vôbec nepredchádza `workflows.py`)**
8. Sekundárna kaskáda počíta `matches` z presne jedného zdroja, v tomto poradí: `already_have_subject` → `special_subject` → `replacement_subject` → `article_product_subject` → `cross_sell_matches` → `related_subject` → inak `cached_search_products()` (plné vyhľadávanie)
9. Finálny `intent` ternary (nezávislý od kroku 8, číta iné premenné):
   `"article_products"` ak `article_product_subject`, inak `"replacement_products"` ak `replacement_subject`, inak `"product_advice"` ak `product_advice_context`, inak `"related_products"` ak `not special_subject and (related_subject or cross_sell_matches)`, inak `"product_search"`

**Dôležitý detail, ktorý nie je na prvý pohľad vidieť**: krok 8 (aké dáta sa reálne vrátia) a krok 9 (aký `intent` string sa zaloguje/vráti v odpovedi) sú **dve nezávislé vetvy s inou logikou**. Konkrétne:
- Keď je nastavený iba `already_have_subject` (žiadny z ostatných), `matches` pochádzajú z `complement_products_for_subject()`, ale zalogovaný/vrátený `intent` je `"product_search"` – `already_have_subject` nemá vlastný label.
- Keď je nastavený `special_subject`, `matches` pochádzajú z `special_products_for_subject()`, ale `intent` je opäť vždy `"product_search"` (podmienka `not special_subject` v ternary to explicitne vynucuje).

## 3. Priama mapa: `WORKFLOW_CONTRACTS` kľúč → skutočná vetva

| `WORKFLOW_CONTRACTS` kľúč | Legacy `intent` string | Kód v `main.py` | Zhoda |
|---|---|---|---|
| `allergen_safety` | `allergen_safety` | riadky 3680–3698, `allergen_product_matches()` | **Priama zhoda** rutingu. `allowed_sources` kontrakt = `FAQ, Products_AI, products`; reálne `allergen_product_matches()` číta iba `products` (cez `cached_search_products`/`special_products_for_subject`) – `FAQ`/`Products_AI` sa v kontrakte spomínajú zrejme kvôli textu upozornenia (`allergen_safety_answer()`), nie kvôli zoznamu produktov. Rule `no_invented_composition` zodpovedá zámeru celej vetvy (žiadny support-escalation text sa nevymýšľa, len upozornenie + odkaz na detail produktu). |
| `faq` | `faq` | riadky 3700–3715, `best_direct_faq_answer()`/`best_faq_answer()` | **Priama zhoda.** `allowed_sources=[FAQ]` sedí presne. Rule `no_product_upsell_after_faq` je presne to, čo Sprint Z.4 tento cyklus opravoval (FAQ cross-sell leak) – kontrakt formalizuje pravidlo, ktoré už bolo opravené ad-hoc v kóde, nie cez tento kontrakt. |
| `recipe_only` | `recipe` | riadky 3717–3733 (náhodný recept) **a** 3734–3797 keď `recipe_products` je prázdne | **Zhoda, ale z 2 rôznych kódových miest.** Kontrakt nerozlišuje "náhodný recept podľa kuchyne" od "recept k explicitnému predmetu bez nájdených produktov" – oba dnes zdieľajú label `recipe`, ani jeden nevolá `get_contract("recipe_only")`. |
| `recipe_to_products` | `recipe_to_products` | riadky 3734–3797 keď `recipe_products` neprázdne | **Zhoda.** Rovnaký kódový blok ako vyššie, len iná vetva `if recipe_products`. `allowed_sources` kontrakt = `Recipes, Products_AI, CrossSell, Alternatives, products` – reálne `related_products_for_subject()` + `sushi_shopping_core_products()`/`tom_yum_...`/`kimchi_ramen_...`/`recipe_shopping_core_products()` skutočne kombinujú viacero z týchto zdrojov, takže zoznam je vecne presný. |
| `cross_sell` | `related_products` | riadky 3905–3908 (`cross_sell_matches`/`related_subject` vetva v kroku 8) + ternary krok 9 | **Čiastočná zhoda.** Legacy `related_products` label sa nastaví len keď `not special_subject`, takže presne zodpovedá kontraktu iba pokiaľ sa žiadny `special_subject` súčasne nespustil. Rule `no_repeat_of_original_product` a `each_product_has_reason` nie sú v kóde explicitne pomenované/testované ako samostatné pravidlá – reálne ich čiastočne zabezpečuje `annotate_recommendations()` (dôvod/reason pole) a `seen`-style dedup v `related_products_for_subject()`/`cross_sell_products_for_message()` (nekontrolované priamo oproti tomuto zoznamu pravidiel). |
| `special_products` | **žiadny vlastný label** | riadky 3896–3897, 8266–8287 (`special_products_for_subject()`) | **Chýbajúce prepojenie.** Kód existuje a reálne implementuje presne to, čo kontrakt opisuje (`apply_exclude_terms` cez `SPECIAL_PRODUCT_EXCLUDE_TERMS`, `no_duplicate_products` cez `seen` set) – ale výsledný `intent` sa vždy zaloguje ako `"product_search"`, takže v analytike (`question_analytics.jsonl`) sa táto vetva nedá odlíšiť od plného vyhľadávania. `allowed_sources` kontrakt = `Products_AI, Alternatives, products`; reálne sa číta iba `products`. |
| `product_search` | `product_search` | riadok 3910 (`cached_search_products()`) a fallback vo vetvách `already_have_subject`/`special_subject` | **Zhoda, ale preťažená.** Jeden legacy label pokrýva najmenej 3 vecne odlišné dátové cesty: (a) skutočné plné vyhľadávanie bez rozpoznaného predmetu, (b) `already_have_subject` (dopĺňajúce produkty k tomu, čo zákazník už má), (c) `special_subject` (špeciálne podtémy ako `plain_rice`/`rice_cooker`/`gluten_free_sushi`). Kontrakt `no_invented_prices_or_availability`/`no_invented_urls`/`show_effective_price` sa reálne vynucuje až následne cez `app/grounding.py::validate_answer()` (voláno s `strict_prices=True`), nie priamo v tejto vetve. |
| `out_of_domain` | `unknown` | riadky 3799–3815, `detect_out_of_domain()` | **Priama zhoda** (len iný string – `LEGACY_INTENT_MAP` v `app/intent.py` už mapuje `unknown → out_of_domain`). `allowed_sources=[]` a rule `return_fixed_refusal_message` sedí presne – vetva vracia fixný text bez produktov. |

## 4. Legacy vetvy, ktoré `WORKFLOW_CONTRACTS` vôbec nepokrýva

Tieto existujú a reálne bežia v `/chat`, ale `app/workflows.py` pre ne nemá žiadny kontrakt:

- **`missing_composition`** (riadky 3666–3678) – support-escalation odpoveď pre "chýba zloženie" (Sprint M). Vlastný fixný text, žiadne produkty.
- **`article_products`** (`detect_article_product_subject()`, riadky 7645+) – informačné "čo je X" otázky smerované na konkrétny magazínový článok. Predbieha `replacement_products` aj `product_advice` v poradí kroku 9.
- **`replacement_products`** (`detect_replacement_subject()`, riadok 6969+, `alternative_products_for_subject()`) – **najväčšia medzera**: náhrady/alternatívy k značke boli témou veľkej časti tejto session (Sprint S, T, X.2, Z.2, Z.3) a majú vlastný trust-audit skript (`scripts/trust_audit.py::check_empty_alternatives()`), no v `WORKFLOW_CONTRACTS` neexistujú vôbec – žiadne `allowed_sources`, žiadne `rules`.
- **`product_advice`** (Sprint Z.5, `best_product_advice_answer()` v `app/knowledge.py`) – vznikol po `workflows.py`, logicky nemá ako byť pokrytý.
- **`category_discovery`** (Sprint V2.1.6, `is_category_discovery_query()`) – rovnako vznikol dávno po `workflows.py`.

## 5. Zhrnutie

| | Počet |
|---|---|
| `WORKFLOW_CONTRACTS` kľúčov | 8 |
| – s priamym 1:1 legacy ekvivalentom | 4 (`allergen_safety`, `faq`, `recipe_to_products`, `out_of_domain`) |
| – so zdieľaným/preťaženým legacy labelom | 3 (`recipe_only` zdieľa `recipe`, `cross_sell` len keď `not special_subject`, `product_search` pokrýva 3 rôzne cesty) |
| – bez akéhokoľvek legacy labelu v analytike | 1 (`special_products`) |
| Legacy `intent` hodnoty bez zodpovedajúceho kontraktu | 5 (`missing_composition`, `article_products`, `replacement_products`, `product_advice`, `category_discovery`) |

**Záver**: `workflows.py` pokrýva menej ako polovicu reálneho priestoru intentov a jeho `allowed_sources` zoznamy sú v 2 z 8 prípadov (`allergen_safety`, `special_products`) širšie než to, čo zodpovedajúci kód skutočne číta. Zapojenie `detect_workflow()`/`get_contract()` do produkčného `/chat` by si vyžiadalo najprv doplniť kontrakty pre `replacement_products` (najvyššia priorita – má vlastný trust audit, ale žiadny formálny kontrakt) a `product_advice`/`category_discovery`/`article_products`/`missing_composition`, a rozhodnúť, či `already_have_subject` a `special_subject` majú dostať vlastné `intent` labely namiesto zdieľania `product_search`. To je zámerne mimo rozsahu tejto zmeny – iba táto mapa, žiadny kód sa nemenil.
