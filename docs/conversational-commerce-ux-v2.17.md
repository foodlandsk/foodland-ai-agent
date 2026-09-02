# Conversational Commerce UX & Product Presentation (V2.17)

Dátum: 2026-09-02. Baseline commit: `3b6642c7fda84be9aaf6dca3cc14c6eaace0eaff`
(HEAD, `origin/main`, čistý working tree okrem netrackovaného `.claude/`
— overené `git fetch`/`git status`/`git rev-parse`/`git log`. V2.16c/d/e
plne prítomné, presne na očakávaných SHA).

## 1. Prečo tento dokument existuje

V2.17 nemení, ČO backend odporúča — len ako sa to zobrazuje. Princíp:
backend vlastní význam, frontend zachováva význam. Audit najprv,
implementácia len tam, kde charakterizácia dokázala reálnu, bezpečne
uzavretú medzeru.

## 2. Response contract audit (živo overené)

`/chat` response pre `structured_presentation` (product_search) vetvu
obsahuje minimálne: `answer, products, cross_sell, cross_sell_eligible,
cross_sell_context_type, cross_sell_intro, result_set_id, has_more,
matching_total, displayed_count, answer_strategy, groups, workflow_id,
workflow_confidence, interaction_id, intent, response_mode`. Ostatné
workflow vetvy (comparison/use_case_advice/basket_completion/
recipe_shopping) majú vlastné `*_decision_id` polia, nikdy viac ako
jedno naraz (skorý `return` z presne jednej vetvy).

## 3. Backend / Frontend ownership (potvrdené, nezmenené)

Backend vlastní: intent, workflow, product membership, ranking,
evidence, decision, substitučnú/receptovú/cross-sell sémantiku,
ResultSet identitu, decision ID. Frontend vlastní: rendering, zoskupenie
do vizuálnych sekcií, labely, interakčné kontroly. Táto hranica bola
**rešpektovaná** — žiadna zmena tejto sprinty nepridáva frontend logiku,
ktorá by REKONŠTRUOVALA business sémantiku z textu produktu.

## 4. Widget architektúra (audit)

`app/widget.js` (2123 riadkov, zmiešané CRLF/LF — známy hazard,
rešpektovaný byte-precíznou úpravou). Kľúčové zistenia:

- **DOM safety**: `renderText()`/`escapeHtml()`/`escapeAttr()` už DNES
  bezpečne escapujú VŠETOK dynamický obsah pred vložením — `renderText`
  escapuje CELÝ text PRED vlastnou `<br>`/`<a href>` substitúciou, takže
  URL regex nemôže "vylomiť" z `href="..."` atribútu (úvodzovky sú už
  nahradené na `&quot;` predtým, než regex beží). Karty produktov
  (`renderCard`) používajú `escapeHtml`/`escapeAttr` na KAŽDÚ dynamickú
  hodnotu. **Žiadny nebezpečný `innerHTML` s needôverovaným obsahom
  nebol nájdený.**
- **KĽÚČOVÉ ZISTENIE**: karta produktu UŽ MÁ vstavaný, no
  nevyužitý mechanizmus na "prečo" badge —
  `product.recommendation_reason ? <p class="fl-ai-product-reason">
  <span class="fl-ai-product-group">${group}</span>: ${reason}</p> : ""`.
  Backend (`app.main.annotate_recommendations()`, volané univerzálne
  pre VŠETKY `matches` v commerce kaskáde) toto UŽ napĺňa pre primárne
  produkty (živo overené: "sushi ryza" → `recommendation_group="Základ"`,
  `recommendation_reason="Je to jedna zo základných surovín..."`). Táto
  sprinta objavila, že `cross_sell` produkty MALI vlastné, PARALELNÉ
  polia (`cross_sell_role`/`cross_sell_reason`/`cross_sell_evidence`) —
  reálne evidence-grounded (taxonomy `display_label`), ale nikdy
  namapované na tie isté `recommendation_group`/`recommendation_reason`
  polia, ktoré widget UŽ vie renderovať.
- `data.cross_sell`, `data.basket_roles`, `data.recipe_shopping_plan`,
  `data.why_followup` (V2.16e) **neboli konzumované vôbec** pred touto
  sprintou — customer vidí basket/recipe/why informácie len cez `answer`
  prózu (existujúce, testované composery z V2.16d/e).
- **CTA/cart sémantika už DNES korektná**: `ADD_TO_CART_CONFIRMED` sa
  paľuje LEN po autoritatívnom potvrdení hostiteľského webu
  (`submitRealAddToCartForm()`), nie po kliknutí — V2.15d.2 zachované,
  nezmenené.
- **Stock/availability**: `product.availability === "in_stock" ?
  "Skladom" : ...` — živo overené proti `data/products.json`: **2140/2140
  (100 %)** produktov má `availability="in_stock"` (statické pole z
  Google Merchant feedu, NIE live sklad). "Skladom" bolo teda vždy
  fakticky true bez ohľadu na skutočnú dostupnosť — presne príklad
  Section 79 ("unknown stock shown as 'Available'"). **Opravené.**

## 5. Cross-sell frontend gap — re-audit (Section 15)

V2.15e.3 zistenie ("backend cross-sell existuje, `app/widget.js` ho
nikdy nečíta") bolo **znovu overené na aktuálnom HEAD a potvrdené ako
stále platné** pred touto sprintou. Klasifikácia: bol
`CROSS_SELL_BACKEND_ONLY`.

**5 gate-ov zo Section 16 — všetky živo overené ako splnené:**
1. Backend dodáva explicitné kandidáty (`data.cross_sell`, `cross_sell_eligible=True`).
2. Vzťah je evidence-grounded (`app.cross_sell.generate_candidates()` + taxonomy `display_label`, nie voľná AI úvaha).
3. Produkty NIE sÚ duplikáty primárnych zhôd (`build_cross_sell()` už exkluduje `exclude_ids = set(structured_presentation.ranked_product_ids)` PRED generovaním kandidátov).
4. Rendering nemení ranking (nová funkcia len PRIDÁVA 2 kľúče do UŽ naformátovaných dictov, `rank_candidates()` nedotknutá).
5. Customer vie rozlíšiť cross-sell od požadovaných produktov (vlastný nadpis z `data.cross_sell_intro`, vizuálne oddelená sekcia).

→ **`CROSS_SELL_FRONTEND_CLOSURE_JUSTIFIED`.**

## 6. Implementácia (Gate B — additive backend metadata + widget rendering)

**Backend** (`app/cross_sell.py`, `build_cross_sell()`): 2 nové riadky,
mapujúce `cross_sell_reason` → `recommendation_reason` a statický label
`"Hodí sa k tomu"` → `recommendation_group`. Žiadne nové reason-code
vokabulár, žiadna zmena `rank_candidates()`/kandidátnej generácie.

**Widget** (`app/widget.js`):
- `addSectionHeading(text)` — nová, malá funkcia (6 riadkov logiky),
  znovupoužíva existujúci `.fl-ai-missing-title` heading štýl (0 novej
  CSS), vkladá text cez `textContent` (nie `innerHTML`).
- Cross-sell sa renderuje volaním **tej istej, už testovanej**
  `addProducts(crossSellProducts, text, false)` funkcie — **žiadny
  paralelný card-rendering kód**. `hasServerMore=false` znamená, že
  Show More sa NIKDY nezobrazí pre cross-sell (typicky max 3 položky),
  takže cross-sell a primárne "Zobraziť viac" pokračovanie sa nikdy
  nemiešajú (Section 40).
- Defenzívny frontend dedup (`primaryIds` Set) navrchu existujúcej
  backend záruky (Section 18 — "preferuj backend dedup", toto je len
  jednoriadková poistka, nie náhrada).
- Korelácia (`interaction_id`/`decision_id`/`result_set_id`) sa
  ukladá na cross-sell produkty ROVNAKÝM mechanizmom ako primárne
  produkty — žiadne nové ID, žiadna nová event schéma. Samostatný
  `impression` event pre cross-sell znovupoužíva presne ten istý
  event_type/shape (Section 82: `ADDITIVE_INTERACTION_CORRELATION_JUSTIFIED`).

## 7. Cross-sell observability (Section 82)

**`ADDITIVE_INTERACTION_CORRELATION_JUSTIFIED`** — žiadny nový
decision_id nebol vytvorený, žiadna nová event sémantika. Cross-sell
produkty nesú rovnaké `interaction_id`/`decision_id`/`result_set_id`
ako primárna odpoveď (keďže patria k tej istej `structured_presentation`
odpovedi), a `impression`/`click`/`add_to_cart*` eventy sa už DNES
akceptujú generickу pre ľubovoľnú `product_sku` — žiadna zmena v
`app/main.py`'s `/events` endpointe bola potrebná.

## 8. Recipe/basket a explanation prezentácia — vedomé rozhodnutie NEROZŠIROVAŤ

`compose_basket_answer()`/`compose_recipe_followup_answer()` (V2.16d)
a `compose_why_answer()` (V2.16e) UŽ vkladajú štruktúrované informácie
(už pokryté/chýbajúce role, ambiguity CLARIFY) priamo do `answer` prózy,
overené a testované v predchádzajúcich sprintoch. Budovanie NOVEJ,
samostatnej vizuálnej UI sekcie pre `basket_roles`/`recipe_shopping_plan`
by bola Section 62 Gate D ("large presentation rewrite") — zadanie
vyžaduje dôkaz, že menšia možnosť nestačí. Keďže existujúci textový
mechanizmus je preukázateľne funkčný (V2.16d/e živé overenie), **nebol
nájdený dôkaz pre Gate D** — ponechané ako `LIVE_WITH_LIMITATIONS`
(informácia existuje, len ako próza, nie ako badge/sekcia).

## 9. "Prečo tento?" card action — Gate rozhodnutie

Section 25 vyžaduje explicitné gate-ovanie pred implementáciou tlačidla
"Prečo tento?" na karte. Riziko: per-card action by vyžadovala nový
routing kontext (ktorý produkt presne, keď je viac kariet zobrazených
naraz) — V2.16e's `why_followup` mechanizmus je navrhnutý na
KONVERZAČNÝ (textový) "prečo tento?" dotaz nad POSLEDNÝM rozhodnutím,
nie na per-card kliknutie s explicitnou product identitou. Implementácia
by vyžadovala nový backend request shape (product_id parameter) mimo
minimálneho rozsahu tejto sprinty.

→ **`EXPLAIN_CARD_ACTION_FOUNDATION_ONLY`** (nezavedené, zdokumentované
ako budúca možnosť).

## 10. Mobile/Desktop UX (audit, žiadna zmena potrebná)

Existujúca `@media (max-width: 520px)` sekcia UŽ obsahuje: touch targets
≥36-40px min-height, `safe-area-inset` handling, `-webkit-line-clamp: 3`
na `.fl-ai-product-reason` (rieši overflow dlhého "prečo" textu na
mobile), responzívnu grid štruktúru kariet. Keďže cross-sell karty
znovupoužívajú **100 % rovnakú** `.fl-ai-product` triedu/`renderCard()`
logiku, dedia CELÚ túto existujúcu responzivitu automaticky — žiadna
nová CSS nebola potrebná (Section 56 minimalizmus splnený).

## 11. Accessibility (audit, žiadna zmena potrebná)

Tlačidlá sú už `<button type="button">` (nie klikateľné `<div>`),
klávesnicová navigácia autocomplete (ArrowUp/ArrowDown/Enter/Escape)
už existuje a nebola dotknutá. Nová `addSectionHeading()` používa
sémantický `<p>` element s čistým textovým obsahom.

## 12. DOM/XSS bezpečnosť (Section 51/52 — kritické po V2.16e incidente)

Overené priamo: nová `addSectionHeading()` vkladá `data.cross_sell_intro`
(backend-generovaný, ale v princípe dynamický text) cez `textContent`
(auto-escaping), nikdy `innerHTML`. Existujúci `renderCard()` pattern
(escapeHtml/escapeAttr na každú hodnotu) bol znovupoužitý bezo zmeny
pre cross-sell karty (keďže ide o TEN ISTÝ kód). **Žiadna nová cesta
pre V2.16e-štýl prompt-leak nebola vytvorená** — cross-sell produkty
prechádzajú tou istou `format_product()` normalizáciou ako primárne
produkty, nie cez `Products_AI`/`Chutovy profil` polia vôbec.

## 13. V2.16e prompt-leak ochrana — zachovaná

`app.knowledge._is_broken_curation_placeholder()` guard nebol dotknutý.
Cross-sell mechanizmus nečíta `Products_AI`/`Chutovy profil`/`Kucharsky
tip` polia vôbec (číta priamo `format_product()`-formátované katalógové
dáta + taxonomy `display_label`), takže nevytvára žiadnu novú cestu pre
tento incident. `scripts/trust_audit.py --broken-curation-content`
znovu spustený, 0 nálezov (pozri Sekciu finálneho reportu).

## 14. Testy

- Nový súbor `tests/test_conversational_commerce_ux_v2_17.py`
  (12 testov: cross-sell anotácia, no-overlap, ranking invariance,
  regresné kontroly).
- Rozšírený `tests/js/widget.test.mjs` o 9 nových testov (gated
  rendering, dedup, textContent-only, no internal field leakage, žiadne
  "Skladom" tvrdenie) + 2 existujúce testy AKTUALIZOVANÉ (nie
  odstránené) — zámerne zastarané V2.15e.3 "nikdy nečíta cross_sell"
  invarianty nahradené pozitívnym dôkazom nového, gate-ovaného
  správania. 1 zodpovedajúci Python test
  (`tests/test_decision_observability_expansion_v2_15e_3.py`) rovnako
  aktualizovaný.
- Plná JS sada: **46/46 passed**.

## 15. Ranking invariance (Section 66)

Živo overené: identické product ID/poradie pred a po zmene pre
`"sushi ryza"` (primárne: `FL_1081, FL_1109, FL_11455, FL_11457`) a
rt0013 (`FL_2764, FL_6600, FL_3321, FL_2765`) — **žiadna zmena**.
Zamknuté ako permanentný regresný test.

## 16. AUTO_PROMOTION

**AUTO_PROMOTION = FALSE** (nezmenené). Žiadny learning/ranking kód
nebol dotknutý. `NEXT_PROGRAM_PHASE = WAIT_FOR_EMPIRICAL_DATA`
nezmenené, V2.15f nezačaté.

## 17. Zostávajúci UX/data/architektonický debt

- `basket_roles`/`recipe_shopping_plan` zostávajú len v próze, nie ako
  vizuálne badge/sekcie — budúci malý sprint by mohol rozšíriť rovnaký
  `recommendation_group`/`recommendation_reason` mechanizmus na tieto
  polia (rovnaký vzor ako táto sprinta pre cross-sell).
- "Prečo tento?" per-card tlačidlo zostáva `FOUNDATION_ONLY` — vyžaduje
  nový product_id-parametrizovaný backend request shape.
- Stock/availability zostáva `CATALOG_PRESENCE_ONLY` navždy, kým sa
  neintegruje reálny live-stock feed (business/dátový krok, mimo
  inžinierskeho rozsahu).
