# Session Intelligence — Sprint V2.9 technical documentation

Dátum: 2026-08-16. Zdroj kódu: `app/session_state.py` (nový),
`app/recipe_shopping.py` (rozšírený o `resolve_recipe_followup()`/
`compose_recipe_followup_answer()`), `app/query_constraints.py`
(`merge_constraints()` rozšírené o `remove_size`/`remove_brand`),
`app/structured_search.py` (`build_structured_result_set()` prijíma
removal flagy), `app/main.py` (zapojenie, byte-safe patche).

## Session state model

Žiadne nové úložisko (Section 32, `docs/session-intelligence-audit.md`).
Nové polia priamo v existujúcom `memory` dict (`session_memories`,
process-local, rovnaké TTL ako doteraz):

```
active_use_case: str            # "" alebo napr. "sushi"
active_recipe_id: str           # "" alebo V2.8 dish_id, napr. "pad_thai"
recipe_servings: int | None
last_recipe_ingredient_concept: str   # posledná ingrediencia, o ktorej sa hovorilo
selected_ingredient_products: dict[str, str]   # concept_id -> zvolené product_id
recent_presentation_ids: list[str]    # posledné zobrazené produkty, max 8
```

Prístup výhradne cez typované funkcie v `app/session_state.py`
(`get_active_recipe`, `set_active_recipe`, `clear_recipe_state`,
`get_active_use_case`, `mark_ingredient_selected`, `track_presentation`,
`resolve_ordinal_reference`, ...) — main.py nikdy nečíta/nepíše kľúče
dictu priamo mimo týchto funkcií.

## Scopy (Section 6)

| Príklad | Scope | Pole |
|---|---|---|
| "5 kg" pri jazmínovej ryži | PRODUCT_NEED | `StructuredProductQuery.package_size` (V2.5, existujúce) |
| "Pad Thai pre 8" | RECIPE/TASK | `recipe_servings` |
| "chcem robiť sushi" | TASK | `active_use_case` |
| vybraný produkt pre rolu receptu | RECIPE | `selected_ingredient_products` |

Nič nie je "session-global" defaultne — `active_use_case`/
`active_recipe_id` sa explicitne čistia pri hard switch (nižšie).

## Constraint inheritance/override/removal (Section 7-10)

`app.query_constraints.merge_constraints(base, addition, *, remove_size,
remove_brand)`:

- **inherit**: `family`/`subfamily`/`attributes`/`concept_id` vždy z `base`
  (V2.5, nezmenené).
- **override**: `addition.package_size or base.package_size` — `or`
  prirodzene uprednostní `addition`, keď je pravdivá ("radšej 1 kg"
  nahradí "5 kg").
- **removal** (V2.9, nové): `remove_size=True` → `None` bez ohľadu na
  `addition`/`base`. Signál prichádza z `app.session_state.
  detect_size_removal()`/`detect_brand_removal()` (deterministické
  frázové/token markery), nie z parsovania `addition` (odstraňovacia
  fráza sama osebe nenesie pozitívnu hodnotu).

Overené priamym testom (3 ťahy): `family=rice` prežije celý reťazec,
`package_size` sa najprv nastaví na 5kg, potom prepíše na 1kg, potom
úplne odstráni.

## Reference resolution (Section 11-13)

`resolve_ordinal_reference(message, memory)` — hľadá slovenské/anglické
ordinálne slová (`prvý/druhý/tretí/štvrtý` + pádové tvary, `first/second/
third/fourth`) v normalizovanom texte, mapuje na index do
`recent_presentation_ids`. Mimo rozsahu (out-of-range) alebo prázdna
história → `needs_clarification=True`, **nikdy** náhodný produkt.

Testované:
```
"jazmínová ryža"  -> 4 produkty zobrazené
"ten druhý"        -> presne produkt #2 z PRÁVE ZOBRAZENÉHO zoznamu
"ten druhý" (fresh session, žiadna história) -> clarification, 0 produktov
```

## ResultSet / Show More / Show All (Section 14)

Nezmenené — V2.5 mechanizmus (`active_result_set_id`, `app.result_sets`)
zostáva jediná autorita pre pagináciu. V2.9 iba PRIDÁVA
`recent_presentation_ids` tracking vedľa neho (pre ordinal referencie),
nikdy ho nenahrádza ani neduplikuje.

## Recipe/servings kontinuita (Section 16-18, 39) — hlavná časť sprintu

`app.recipe_shopping.resolve_recipe_followup(message, memory, graph,
products, taxonomy_index, normalized_index)`:

1. Vyžaduje `active_recipe_id` nastavené (Section 39 — V2.9 nerobí
   vlastnú recipe detekciu, iba používa V2.8 gráf).
2. Rozpozná servings zmenu (`extract_requested_servings_lenient` -
   akceptuje aj holé "pre 8" v potvrdenom recipe kontexte).
3. Ordinal referencia oproti POSLEDNEJ zobrazenej ingrediencii
   (`last_recipe_ingredient_concept`) → označí produkt ako vybraný
   (`mark_ingredient_selected`).
4. Explicitná zmienka inej ingrediencie ("a rybaciu omáčku?") →
   token-overlap match OBMEDZENÝ na ingrediencie AKTÍVNEHO receptu
   (nikdy na celý katalóg konceptov — Section 18).
5. Cenová preferencia na poslednej diskutovanej ingrediencii.
6. Generická otázka ("čo ešte potrebujem?") → prestavaný plán,
   vynechá už `ALREADY_SATISFIED` roly (Section 18).

**Kritický nález pri implementácii**: token-match používajúci presné
slová zlyhával na slovenských pádoch ("rybaciu omáčku" vs. "rybacia
omáčka") — opravené na zdieľaný-prefix (≥4 znaky) namiesto presnej
zhody. **Druhý kritický nález**: generické slová ako "omáčka" (spoločné
naprieč desiatkami produktov) spôsobovali falošné zhody — "kikkoman
sójová omáčka 1000 ml" (úplne nesúvisiaci, konkrétny produktový dopyt)
sa nesprávne priradil k Pad Thai fish_sauce role len cez zdieľané slovo
"omáčka". Zachytené existujúcim V2.8 regresným testom
(`test_context_switch_away_from_recipe_does_not_leak_plan`), opravené
vylúčením zoznamu generických kategóriových slov z scoringu.

Plný overený reťazec (Section 53, 7 ťahov) — viď README nižšie.

## Soft/hard context switch (Section 26-29, 84)

**Recipe**: keď `active_recipe_id` je nastavené a `resolve_recipe_followup()`
vráti `None` (správa sa nečíta ako pokračovanie), `app.session_state.
clear_recipe_state()` sa zavolá OKAMŽITE, pred akýmkoľvek ďalším
spracovaním. Overené: "Pad Thai" → ... → "chcem kúpiť mlieko" → žiadny
`recipe_shopping_plan`, žiadny `RECIPE_SHOPPING` workflow.

**Use case (sushi)**: `active_use_case` sa nastaví pri `related_subject
== "sushi"`, vyčistí sa keď sa v aktuálnom ťahu rozpozná iný konkrétny,
pomenovaný subjekt (nesúvisiaci `special_subject`/`replacement_subject`/
`related_subject`).

**Soft switch** (Section 15/26): v rámci `active_use_case="sushi"`,
bare "ryža"/"ocot" sa NARROWUJE na `sushi_rice`/`rice_vinegar`
(`special_subject` override) namiesto vyčistenia `active_use_case` —
zámerne úzko naškálované na presne overený scenár (Section 5).

## V2.6 integrácia (basket/satisfied role)

`selected_ingredient_products` (concept_id -> product_id) sa odovzdáva
ako `basket_product_ids` do `app.recipe_shopping.build_recipe_shopping_plan()`
(existujúci V2.8 parameter) — rola sa zobrazí `ALREADY_SATISFIED`, ďalšie
volanie plánu ju nenavrhne znova. **Čestné obmedzenie** (nezmenené od
V2.8): `ChatRequest` nemá skutočné cart pole, takže toto funguje iba pre
explicitne v konverzácii potvrdené výbery (ordinal referencia po
zobrazení kandidátov), nie pre reálny stav košíka v e-shope.

## Multilingválne pokrytie

Ordinálne slová: SK (`prvý/druhý/tretí/štvrtý` + pádové tvary) + EN
(`first/second/third/fourth`). Reset frázy, cenové markery: SK only
(zámerne — EN zákazníci existujú, ale mandátne testy sú SK; rozšírenie
je lacné, keď bude potrebné). Interný `memory` model je jazykovo
neutrálny (Section 50) — žiadny per-jazyk state model.

## Privacy (Section 33)

Nič nové oproti existujúcemu `memory` dictu — žiadne osobné/platobné
údaje, žiadny permanentný profil. `selected_ingredient_products`/
`active_recipe_id`/atď. sú TTL-viazané presne ako existujúce
`session_memories` polia (žiadne nové retenčné pravidlo).

## Performance

Merané lokálne (2140 produktov):
- `resolve_ordinal_reference`: O(1) dict lookup, zanedbateľné.
- `resolve_recipe_followup` (plný ťah vrátane `build_recipe_shopping_plan`):
  rovnaký rád ako V2.8 (~15-20 ms), žiadny extra katalógový sken.
- `_match_recipe_ingredient_by_tokens`: O(5 konceptov × pár desiatok
  aliasov) — mikrosekundy.

## Fallback (Section 68/70)

Každá nová vetva je obalená v `try/except` s pádom na presne ten istý
legacy/V2.8 kód, ktorý bežal pred V2.9 (`logger.warning(...)` + `= None`).
Vypnutie V2.9 by znamenalo vrátiť tieto patche — V2.4-V2.8 fungujú úplne
nezávisle a nekontrolujú `active_recipe_id`/`active_use_case` vôbec, keď
V2.9 vetvy tieto polia nevyplnia.

## Ako znovu overiť

```bash
python -m pytest tests/test_session_intelligence.py -q
```
