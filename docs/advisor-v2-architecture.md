# Foodland AI Advisor V2 – stav migrácie architektúry

Tento dokument odráža **skutočný stav kódu**, nie ambície. Aktualizuje sa
pri každom V2 architektonickom kroku (viď `docs/roadmap-features.md`,
sekcia "Sprint V2.x").

Cieľová architektúra:

```
Customer message
  -> CustomerIntent (UNDERSTAND)
  -> Workflow
  -> Retrieval Plan (RETRIEVE)
  -> Candidate Products/Recipes/Knowledge
  -> Ranking (RANK)
  -> Answer Composition (COMPOSE)
  -> Grounding/Safety (GROUND)
  -> Structured Response
  -> Analytics + Evaluation (EVALUATE / LEARN)
```

## Fázy

| Fáza | Stav | Poznámka |
|---|---|---|
| V2.1 Intent foundation | **PARTIAL** | `app/intent.py` existuje: `CustomerIntent`, `PRIMARY_INTENTS` (15 kanonických zámerov), `LEGACY_INTENT_MAP`/`map_legacy_intent()`, `build_customer_intent()`. Zapojené do `/chat` len ako **analytics-only** vrstva (7 volaní `log_question()` teraz logujú `primary_intent`/`subject`). Routovacie rozhodnutia (ktoré produkty/recepty sa vrátia, aký text sa zobrazí) **stále riadi legacy kaskáda**, nie `CustomerIntent`. |
| V2.2 Product routing | **TODO** | `cached_search_products()`/`special_products_for_subject()`/`article_products_for_subject()`/`alternative_products_for_subject()` sa stále volajú priamo z legacy `if/elif` reťazca v `chat()`, nie cez `CustomerIntent`/retrieval plan. `app/search.py: search_products()` berie iba `(products, raw_message, limit)` – žiadne štruktúrované obmedzenia (brand/category/use_case/include/exclude). |
| V2.3 Recipe routing | **TODO** | Recipe-only, recipe-to-products, missing-ingredients a core-product-mapping logika (`recipe_results()`, `recipe_shopping_core_products()`, `missing_ingredients_for_subject()`, `sushi_shopping_core_products()`, `tom_yum_shopping_core_products()`, `kimchi_ramen_shopping_core_products()`) sú samostatné funkcie volané z toho istého legacy `if` bloku v `chat()`, nie zjednotený recipe workflow. `app/workflows.py` (`detect_workflow`, `WorkflowResult`, `get_contract`, `WORKFLOW_CONTRACTS`) existuje od skoršej analýzy, ale **nie je zapojený do `/chat` vôbec** – jediný reálne používaný export je `products_to_cart_candidates()`. |
| V2.4 Replace/cross-sell/comparison | **TODO** | `replacement_subject`/`related_subject`/`special_subject`/`already_have_subject` sú oddelené legacy detektory s ručne poskladanými prioritnými pravidlami priamo v `chat()` (viď napr. override pre "japonske noze" alebo explicitnú značku pri cross-sell, Sprint Z.3/Z.6 v roadmape). Nie sú prvotriedne `CustomerIntent` zámery – `map_legacy_intent()` ich už vie namapovať na `replacement`/`cross_sell`, ale iba spätne, po tom čo legacy kaskáda rozhodla. `product_comparison` a `category_discovery` z kanonického zoznamu nemajú v legacy kóde vôbec zodpovedajúci detektor. |
| V2.5 Answer composer | **TODO** | Odpoveď sa skladá ad-hoc na mieste v `chat()` (`fallback_answer()`, `recipe_products_answer()`, `shopping_list_answer()`, `allergen_safety_answer()`, priamy OpenAI system prompt s pravidlami pre všetky intenty naraz) – nie centralizovaný composer podľa `CustomerIntent.primary_intent`. |
| V2.6 Context/personalizácia | **TODO** | `contextualize_message()`/`is_context_followup()`/`best_memory_subject()` sa aplikujú **pred** akoukoľvek intent detekciou (memory ovplyvňuje `detect_recipe_subject`, `detect_related_subject` atď. už na vstupe), nie až po vyhodnotení explicitného zámeru zákazníka, ako žiada V2 sekcia 12. Sprint V2.1.5 opravil jeden konkrétny prípad kontaminácie (`detect_diet_terms()` nesprávne zachytávalo porovnávacie otázky ako "pikantnejšie" - pozri nižšie), ale samotný mechanizmus – `contextualize_message()` bezpodmienečne vkladá posledné 2 `diet_terms` do KAŽDEJ nasledujúcej správy v session bez ohľadu na relevanciu – zostáva nezmenený a je stále štrukturálnym rizikom pre budúce falošné pozitíva v `detect_diet_terms()`/`detect_memory_subjects()`. |
| V2.7 Synthetic QA optimizer | **PARTIAL** | `scripts/run_customer_situation_tests.py`, `scripts/trust_audit.py`, `scripts/consistency_audit.py` existujú a bežia offline nad reálnym katalógom/kódom (nie mock dáta). Nie je však žiadny centrálny "before/after skóre" runner podľa V2 sekcie 18–19 rubriky (0–100 skóre, kategórie zlyhaní ako `INTENT_ERROR`/`RETRIEVAL_ERROR`/atď.) – aktuálne audity sú binárne (nájdené/nenájdené), nie skórované. |

## Legacy routovacie mechanizmy, ktoré ešte existujú (V2 sekcia 6, zámerne nezmazané)

Všetky nižšie žijú v `app/main.py` ako samostatné, priamo v `chat()` volané funkcie/slovníky. `app/intent.py` ich zatiaľ len **pozoruje** (cez `build_customer_intent()` po tom, čo už rozhodli), nemigruje ich:

- `RELATED_PRODUCT_QUERIES`, `RELATED_SUBJECT_ALIASES` – cross-sell podľa témy
- `SPECIAL_PRODUCT_QUERIES`, `SPECIAL_PRODUCT_EXCLUDE_TERMS` – špeciálne produktové témy (napr. ryžové rodiny)
- `REPLACEMENT_SUBJECT_ALIASES`, `REPLACEMENT_PRODUCT_QUERIES`, `detect_replacement_subject()`, `detect_mentioned_replacement_brand()`, `resolve_unambiguous_sauce_brand()` – náhrady
- `RECIPE_SHOPPING_CORE_QUERIES`, `MISSING_INGREDIENTS_BY_SUBJECT` – recipe-to-products mapovanie
- `ARTICLE_PRODUCT_QUERIES`, `detect_article_product_subject()`, `is_article_info_intent()` – "čo je X" produktové info
- `ALREADY_HAVE_SUBJECT_MAP`, `ALREADY_HAVE_COMPLEMENT_QUERIES` – "mám X, čo ešte" cross-sell
- `ALLERGEN_TERMS`, `detect_allergen_intent()` – alergénová bezpečnosť
- `FAQ_CATEGORY_MARKERS`, `is_faq_intent()`, `best_direct_faq_answer()` – FAQ routing
- `AUTOCOMPLETE_INTENTS` (`app/main.py`) – samostatný intent systém len pre autocomplete, úplne mimo `/chat` a mimo `app/intent.py`
- `app/workflows.py` (`detect_workflow`, `WORKFLOW_CONTRACTS`) – navrhnutá, ale nikdy nezapojená alternatívna routovacia vrstva

Toto je presne ten zoznam, ktorý V2.2–V2.4 majú postupne presunúť za `CustomerIntent`, nie zmazať naraz.

## Zistené systematické medzery (zo synthetic QA V2.1, real production dôkaz čaká na prístup k Railway)

- ~~Recipe detekcia nerozpozná niektoré recipe-shopping formulácie skôr, než ich zachytí cross-sell vetva (`"co potrebujem na tom kha gai"` → `related_products`, nie `recipe_to_products`).~~ **Opravené (Sprint V2.1.1)** – `"tom kha"` pridané do `RECIPE_INTENT_MARKERS`. Pozor: toto NIE je štrukturálna oprava celej triedy – je to úmyselne úzky, jednorazový marker presne ako `"vindaloo"`/`"karaage"`. Rovnaká medzera existuje ďalej pre iné jedlá s vlastnou receptovou kartou, ktoré nemajú vlastnú cross-sell `*_shopping_core_products()` funkciu (napr. `pad_thai`, `karaage` má už markera, `bibimbap`, `bulgogi`...) – kandidát na skutočnú V2.3 recipe-routing štrukturálnu opravu, keď bude jasné pravidlo na odlíšenie "má vlastnú doladenú cross-sell funkciu, zámerne zostáva na related_products" od "nemá nič, mala by ísť na recipe_to_products".
- ~~`detect_allergen_intent()` nezachytí holé "ma to lepok?" bez pomenovaného produktu.~~ **Opravené (Sprint V2.1.2, upravené Sprint V2.1.4)** – `BARE_ALLERGEN_QUESTION_TERMS` (podmnožina `ALLERGEN_TERMS` obmedzená na jednoznačné alergénové slová: lepok, gluten, arašidy, sezam, mäkkýše, krevety) + kontrola na sloveso "má/je/sú" obchádza `ALLERGEN_INTENT_MARKERS` bránu. Zámerne VYNECHÁVA generické potravinové podstatné mená z `ALLERGEN_TERMS` (mlieko, ryby, vajcia, orechy, **a od V2.1.4 aj sója/soj**), ktoré sú aj bežné produktové slová – "aku ma chut toto mlieko" nesmie skončiť ako alergénová odpoveď. Toto je vedomý kompromis, nie úplné pokrytie. **"soja"/"soj" boli pôvodne v tejto množine, no spôsobili reálnu regresiu** – pozri Sprint V2.1.4 nižšie.
- ~~`detect_out_of_domain()` nezachytí všeobecné mimo-doménové otázky (napr. "aky je najlepsi film?").~~ **Čiastočne opravené (Sprint V2.1.3)** – doplnené kategórie zábava/média (filmy, seriály), všeobecné znalosti/politika a domáce úlohy do `OUT_OF_DOMAIN_MARKERS`. Reálny nález pred nasadením: bare slová `"film"`/`"serial"` by kolidovali s existujúcimi `RELATED_SUBJECT_ALIASES["asian_snack"]` frázami (`"na film"`, `"k filmu"`, `"na serial"`, `"k serialu"` – legitímna žiadosť o snack na filmový večer), takže použité len viacslovné, kolízne overené frázy. **Toto NIE JE štrukturálna oprava** – `OUT_OF_DOMAIN_MARKERS` zostáva čisto negatívny/enumeratívny zoznam, ktorý principiálne nemôže pokryť všetky mimo-doménové témy (napr. "čo si myslíš o politike?", "odporúčaš mi dobrú knihu?", "spievaš rád?" zostávajú nepokryté). Skutočná štrukturálna oprava by vyžadovala pozitívny signál "je toto o Foodland doméne" (napr. confidence-based fallback pri nízkej relevancii vyhľadávania) namiesto donekonečna rastúceho negatívneho zoznamu – kandidát na budúcu V2 architektonickú iteráciu, nie na jednorazovú opravu.
- ~~`detect_diet_terms()` nesprávne zachytávalo porovnávaciu otázku "co je pikantnejsie?" (ktoré je pikantnejšie) ako trvalú stravovaciu preferenciu "pikantne".~~ **Opravené (Sprint V2.1.5)** – vylúčený porovnávací tvar (spoločný kmeň "pikantnej" pre pikantnejší/pikantnejšia/pikantnejšie). **Toto bola reálna regresia s vysokým dosahom**: falošne zachytený `diet_terms` sa cez `contextualize_message()` bezpodmienečne vkladal do KAŽDEJ nasledujúcej správy v session (nie len pri follow-up otázkach), čím kontaminoval úplne nesúvisiace neskoršie dopyty v tej istej konverzácii (preklepy značiek, "aku kategoriu produktov mate?", holé značky ako "kikkoman produkty") – tie strácali reálne produktové zhody a padali do prázdnej "Našla som súvisiace informácie" odpovede. Objavené širším synthetic QA behom (25 scenárov v jednej session), nie cieleným hľadaním.
- **Novo zistené, zatiaľ NEOPRAVENÉ:** `"aku kategoriu produktov mate?"` (a podobné všeobecné "aké kategórie máte" otázky) vracajú prázdnu odpoveď `"Našla som súvisiace informácie vo Foodland poradkyni."` bez produktov, aj úplne izolovane bez akéhokoľvek predošlého kontextu. Očakávané – `category_discovery` (kanonický V2 zámer) nemá v legacy kóde vôbec zodpovedajúci detektor (rovnaká medzera ako `product_comparison`, zdokumentovaná vyššie vo fáze V2.4). Kandidát na ďalšiu V2 iteráciu.

## Ako aktualizovať tento dokument

Pri každom ďalšom V2 sprinte: zmeň stav fázy (TODO → PARTIAL → DONE) **len ak sa reálne zmenil kód**, nie plán. Pridaj/odober položky zo zoznamu legacy mechanizmov podľa toho, čo sa skutočne presunulo za `CustomerIntent`.
