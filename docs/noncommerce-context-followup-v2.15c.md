# Non-Commerce Contextual Follow-up Resolution (V2.15c, rt0014 closure)

Dátum: 2026-08-23.

## 1. Prečo tento dokument existuje

rt0014 (interné označenie tejto sprinty, **nezamieňať** s `regbug_rt0014`
v `eval/golden/regression_bugs.json` — to je nesúvisiaci, existujúci
golden case "chcem snack pre deti"; zhoda v číslovaní je náhodná
kolízia dvoch nezávislých číselných radov, viď Sekcia 9):

```
TURN 1: "Kde sa nachádza kamenná predajňa?"
        -> Mei správne vráti adresu predajne.
TURN 2 (rovnaká session): "Prilož mi Google link na adresu."
        -> nesprávne stráca kontext, spadne do product-search správania.
```

## 2. Diagnostikovaná príčina

Nie je to len chýbajúci FAQ marker. Skutočná príčina je architektonická:
FAQ odpoveďová kaskáda (`is_faq_intent()` + `best_direct_faq_answer()`/
`best_faq_answer()`) nemá ŽIADNU session pamäť predtým zodpovedanej
témy. Aj keby fráza obsahovala FAQ marker, akčne formulovaný follow-up
("prilož mi", nie otázka) nezodpovedá otázkovo tvarovanému vzoru
kaskády, vráti `None`, a ťah prepadne do všeobecného, irelevantného
product-search fallbacku.

## 3. Zhodnotenie `app.turn_resolver.resolve_action_target_signal()`

**NOT_SUITABLE** pre priame znovupoužitie. Jeho parametre
(`special_subject`, `related_subject`, `has_recipe_shopping_language`,
`resolves_confident_product_family`) sú výhradne commerce/product-family
detekčné koncepty. Jeho jediná úloha (podľa vlastného docstringu) je
arbitráž special_subject-vs-related_subject konfliktu, ktorý spôsobil
rt0004 — nie všeobecné action/reference rozlíšenie. Znovupoužitie by
vyžadovalo fabrikovanie falošných product-family signálov pre FAQ témy.

**Zvolená cesta**: `WRAP_WITH_SMALL_INFORMATIONAL_RESOLVER` — malý,
samostatný, session-state-driven mechanizmus s vlastnou, úzkou
slovníkovou detekciou.

## 4. Implementovaný mechanizmus

- `app.session_state.get_last_informational_question()` /
  `set_last_informational_question()`: ukladá SUROVÝ TEXT OTÁZKY (nikdy
  odpoveď, nikdy AI-generovaný obsah) posledne úspešne zodpovedanej
  FAQ/informačnej otázky v danej session.
- `app.session_state.looks_like_location_reference_followup()`: úzky,
  lokalizačne/navigačne špecifický slovník (mapa, adresa, "ako sa tam
  dostanem", google link, ...) — NIE všeobecný "akýkoľvek krátky
  follow-up dedí kontext" catch-all.
- `app/main.py` `_chat_impl()`: nový fallback blok, umiestnený AŽ NA
  KONCI kaskády — po safety, FAQ, comparison, use_case_advice,
  basket_completion, recipe, ordinal-reference clarification a
  recipe/result-set orphaned-followup kontrole, a PRED všeobecnou
  special_subject/related_subject commerce kaskádou. Táto POZÍCIA
  (nie runtime negociácia) je to, čo garantuje "explicitný cieľ
  aktuálneho ťahu vždy vyhráva" (Sekcia 12 zadania) — akákoľvek reálna
  zmienka produktu/značky/náhrady/receptu/alergénu je vybavená vlastnou,
  skoršou vetvou s vyššou precedenciou a štrukturálne sem nemôže dôjsť.
- `app.main._build_maps_link_from_faq_answer()`: Google Maps SEARCH url
  (nikdy fabrikované súradnice/place ID/trasa) zostrojený regex
  extrakciou reálnej, už zaznamenanej adresy priamo z recall-ovanej FAQ
  odpovede (`data/knowledge.json`) — link vznikne LEN keď téma naozaj
  obsahuje adresu, a vždy odráža aktuálny obsah knowledge base.

## 5. Charakterizačná matica (empiricky overené)

| Prípad | Vstup | Výsledok |
|---|---|---|
| Primárna reprodukcia | store→"Prilož mi Google link na adresu." | `faq`, adresa + maps link, 0 produktov |
| Generalizácia (mapa) | store→"Mas na to mapu?" | `faq`, 0 produktov |
| Generalizácia (dostanem) | store→"Ako sa tam dostanem?" | `faq`, 0 produktov |
| Hard switch → produkt | store→"Poslite mi Kikkoman sojovu omacku" | `product_search` (nezmenené) |
| Hard switch → náhrada (rt0013) | store→"vegan nahrada za rybaciu omacku" | `replacement_products` (nezmenené) |
| Hard switch → alergén | store→"Mam alergiu na arasidy..." | `allergen_safety` (nezmenené) |
| Hard switch → recept | store→"Das mi recept na ramen?" | `recipe` (nezmenené) |
| Explicitný cieľ preváži generické "link" | store→"Pošli mi link na Kikkoman" | `product_search` (nie location followup) |
| Reset | store→"Zacnime odznova"→followup | followup NEobnoví store tému |
| Cross-session izolácia | session A store, session B followup bez predchádzajúcej otázky | session B nededí session A tému |
| Viac tém za sebou | store→delivery→followup | followup rieši NAJNOVŠIU tému (delivery), bez fabrikovaného linku (delivery odpoveď neobsahuje adresu) |
| opening_hours (E) | "Ake mate otvaracie hodiny?" | **NEDOSIAHNE FAQ kaskádu vôbec** — potvrdené ako PRE-EXISTING gap (reprodukované aj na nezmenenom HEAD), mimo rozsahu tejto uzávierky |
| contact (F) | "Aky mate telefonny kontakt?" | **NEDOSIAHNE FAQ kaskádu vôbec** — rovnaký, PRE-EXISTING gap |
| delivery (G) | "Akym sposobom dorucujete tovar?" | Počiatočná otázka FUNGUJE (`faq`), ale nemá vlastný follow-up slovník (mimo rozsahu — slovník je location-specific) |

## 6. Per-capability status

- `store_location`: **LIVE** — plná follow-up podpora (otázka + generalizovaný
  location-reference follow-up + maps link + hard-switch bezpečnosť).
- `delivery`: **FOUNDATION_ONLY** — počiatočná otázka funguje cez existujúcu
  FAQ kaskádu, žiadny dedikovaný follow-up mechanizmus (mimo rozsahu tejto
  uzávierky, spec to explicitne povoľuje).
- `opening_hours`, `contact`: **NOT_REACHED_PRE_EXISTING_GAP** — samotná
  počiatočná otázka nedosiahne FAQ kaskádu s testovanými frázami; potvrdené
  ako existujúce pred touto sprintou (reprodukované na nezmenenom HEAD),
  nie regresia V2.15c. Mimo rozsahu tejto uzávierky.

## 7. Bezpečnostné invarianty

- 0 nových LLM volaní (fallback blok volá len `best_direct_faq_answer`,
  `best_faq_answer`, `search_knowledge(allowed_sections=("FAQ",))`,
  `update_user_memory`, `log_question` — žiadne z nich nevolajú OpenAI).
- 0 nových product-search volaní (`search_products`/
  `cached_search_products`/`hybrid_cached_search_products` sa v novom
  bloku nikde nevolajú).
- `app/learning_lifecycle.py` a všetky ranking/promotion súbory zostávajú
  byte-identické (potvrdené `git diff --stat` = prázdny výstup).
- Žiadny fabrikovaný geo-údaj — maps link je vždy odvodený zo skutočného
  textu v `data/knowledge.json`, nikdy z hardcoded súradníc/place ID.
- rt0004/rt0010/rt0011/rt0013 permanentné kontroly nezmenené a overené.

## 8. Testy

`tests/test_noncommerce_context_followup_v2_15c.py` — 21 testov, skupiny
A–R zo zadania (primárny prípad, generalizácia, maps grounding,
multi-topic recency, hard-switch bezpečnosť, explicitný cieľ, reset,
cross-session izolácia, negatívne kontroly proti over-triggeringu,
rt0004/rt0010/rt0011/rt0013 regresné kontroly).

## 9. Kolízia číslovania s `regbug_rt0014`

`eval/golden/regression_bugs.json` už obsahuje nesúvisiaci
`regbug_rt0014` ("chcem snack pre deti", product_search/Pocky/Mochi/
ryžové krekry). Toto je NÁHODNÁ kolízia dvoch nezávislých číselných
radov (routing-debt "rt00XX" vs. golden-suite "regbug_rt00XX") —
overené, že tento existujúci golden case zostáva plne funkčný a
nezmenený touto sprintou. Budúca práca by mala explicitne rozlišovať
oba rady, aby sa predišlo zámene.

## 10. Nevyriešené / mimo rozsahu

- opening_hours/contact FAQ marker gap (Sekcia 6) — reálny, ale
  pred-existujúci defekt, kandidát na budúcu samostatnú sprintu.
- delivery/iné FAQ témy nemajú vlastný follow-up slovník — zámerne mimo
  rozsahu (spec povoľuje heterogénny výsledok).
- V2.15d nie je touto sprintou autorizovaná na spustenie.
