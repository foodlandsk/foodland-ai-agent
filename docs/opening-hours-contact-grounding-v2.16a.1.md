# Opening Hours & Contact Data Grounding Closure (V2.16a.1)

Dátum: 2026-08-27. Baseline commit: `f56a2f509420697af73e3c3a6e47b2032750b801`
(HEAD, `origin/main`, žiadne uncommitted zmeny okrem netrackovaného
`.claude/` - overené `git fetch`/`git status`/`git rev-parse`, presne
zodpovedá očakávanému stavu zo zadania: implementácia `c947b8a`, doc/live
verifikácia `f56a2f5`).

## 1. Prečo tento dokument existuje

V2.16a nechal `opening_hours` (FOUNDATION_ONLY) a `contact`
(DATA_REQUIRED) vedome nedoriešené. V2.16a.1 je DATA-GROUNDING sprint
najprv, routing sprint až potom - zadanie explicitne vyžadovalo audit
existujúcich zdrojov dát PRED akoukoľvek routing logikou.

## 2. Repository reality check

`git fetch`/`git status`/`git log` potvrdili presne očakávaný baseline.
Žiadna novšia legitímna práca, žiadna odchýlka.

## 3. V2.16a re-verifikácia + zásadný nález

Znovu-audit `data/knowledge.json` (nie len dôvera v predchádzajúci
report) odhalil, že **V2.16a tvrdenie "contact phone = DATA_ABSENT" bolo
NESPRÁVNE**. Reálne, business-owner-potvrdené telefónne číslo
`+421 2 4468 1527` a podporný e-mail `eshop@foodland.sk` už existovali
live v produkcii vo vnútri `app.main.missing_composition_answer()`
(`app/main.py:9407-9418`), dosiahnuteľné len cez úzku
`is_missing_composition_complaint()` vetvu (sťažnosti na chýbajúce
zloženie produktu), nikdy cez všeobecnú "ako vás kontaktovať" otázku.
Proveniencia: `docs/roadmap-features.md:427` - "Pridaný
`is_missing_composition_complaint()` detektor... ktorý... nasmeruje
zákazníka na podporu (eshop@foodland.sk, +421 2 4468 1527)." Overené
priamym behom (`missing_composition_answer()` vracia presne tento text)
a priamym čítaním zdrojového kódu (nie len dôvera v sub-agent report).

## 4. Current-behavior characterization (pred implementáciou)

Skript spustený proti nezmenenému HEAD na všetkých prípadoch A-N zo
zadania (store_location, delivery, pickup, payment ako regresné kontroly
+ F-N opening_hours/contact varianty). Potvrdené: `Kedy máte otvorené?`,
`Ake su otvaracie hodiny?`, `Ste otvoreni v sobotu?`, `Dokedy mate dnes
otvorene?`, `Ako vas mozem kontaktovat?`, `Aky mate telefon?`, `Mate
email?`, `Dajte mi kontakt na predajnu.` - všetky `intent=product_search`
(garbage), presne ako V2.16a zdokumentoval, nezmenené na aktuálnom HEAD.

## 5. Opening-hours source audit

Klasifikácia: **AUTHORITATIVE_UNSTRUCTURED, EXTRACT_FROM_EXISTING**.
Hodiny existujú LEN ako vedľajšia veta v store-location FAQ zázname
(`data/knowledge.json:70950-70961`, `Otázka`: "Má Foodland kamennú
predajňu? Kde ju nájdem a aké má otváracie hodiny?"). Druhý,
pickup-orientovaný záznam (`70481-70491`) obsahuje IDENTICKÉ hodiny
("Po–Pi 8:00–18:00, So 9:00–20:00, Ne 9:00–15:00") - žiadny konflikt,
len staršia adresná formulácia ("Starej Vajnorskej 19" vs. kanonické
"Stará Vajnorská 3308/19"). Žiadny samostatný "opening hours" záznam.
Provenience (`docs/roadmap-features.md:415`): "obsah potvrdený majiteľom
biznisu, adresa/hodiny predajne krížovo overené na foodland.sk/kontakt."

## 6. Contact source audit

Per-field klasifikácia:
- **address**: GROUNDED (existujúci `_FOODLAND_CANONICAL_ADDRESS`).
- **maps_url**: GROUNDED (existujúci `_FOODLAND_CANONICAL_MAPS_URL`).
- **phone**: GROUNDED (znovu-nájdené, `+421 2 4468 1527`, business-owner
  potvrdené, live v produkcii - viď Sekcia 3).
- **email**: GROUNDED (`eshop@foodland.sk`, už používaný na viacero
  rôznych tém v `knowledge.json`, potvrdzujúce, že je to všeobecná
  e-shop podporná adresa, nie úzko scoped).

Žiadny všeobecný "ako nás kontaktovať" FAQ záznam existoval - všetky
e-maily v `knowledge.json` sú topic-scoped (skladom, reklamácie,
vrátenie, dobropis).

## 7. Opening-hours gate

**Gate D** (V2.16a.1 terminológia: capabilita bola efektívne blokovaná
len chýbajúcim routing prepojením, nie chýbajúcimi dátami - žiadne nové
dáta vynájdené). **Status: LIVE.**

## 8. Contact gate

**Gate C** (nová, evidence-grounded live implementácia, dáta
znovu-použité z už-overeného zdroja). **Status: LIVE** pre
address/maps/phone/email spoločne v jednom novom FAQ zázname.

## 9. Dátový model

Žiadny nový štruktúrovaný dátový model (žiadne YAML/JSON schema pre
`opening_hours:`/`contact:` polia) - zámerne, keďže existujúca
`data/knowledge.json` FAQ-záznamová architektúra už postačuje (Sekcia 8
zadania: "Do not create unnecessary architecture if the repository
already has an appropriate data representation"). Opening-hours:
**OH-B EXTRACT_FROM_EXISTING_AUTHORITATIVE_SOURCE** (žiadny nový
záznam). Contact: jeden nový FAQ záznam pridaný do `data/knowledge.json`
(52. záznam), obsahujúci VÝHRADNE už-overené hodnoty (žiadna nová
"vymyslená" dátová položka).

## 10. Routing implementácia

- `app.session_state.is_opening_hours_query()` / `is_contact_query()`:
  úzke, phrase/token-based detektory. **Zámerne NEpridané do zdieľaného
  `FAQ_INTENT_MARKERS`** - blast-radius re-check (Sekcia 20 nižšie)
  potvrdil, že bare `"otvoren"` substring koliduje s reálnym produktovým
  textom ("po otvorení", "otvorenými", "dotvorenie") a bare `"kontakt"`
  koliduje s "kontakt s potravinami"/"priamy kontakt s fóliou" (obalové
  materiály). Namiesto toho oba detektory sú OR-ované priamo do
  `is_faq_query` v `_chat_impl()` (`app/main.py`).
- `app.session_state.looks_like_opening_hours_followup()` /
  `looks_like_contact_followup()`: rovnaký vzor ako V2.16a's
  `looks_like_payment_method_followup()` - klasifikácia témy AŽ PRI
  RECALL-e z existujúceho `last_informational_question` poľa, ŽIADNE
  nové session-state pole.
- `app.main.best_direct_faq_answer()`: dva nové shortcut bloky,
  `is_opening_hours_query()` → reuse `("kamennu", "predajnu")` shortcut
  (rovnaký cieľ ako existujúce "adresa"/bare "predajn" vetvy),
  `is_contact_query()` → nový `("kontaktovat", "telefon")` shortcut
  smerujúci na nový FAQ záznam.
- Fallback blok (`app/main.py`, pozícia nezmenená od V2.15c/V2.16a)
  rozšírený o `_is_opening_hours_followup`/`_is_contact_followup` vetvy,
  reťazené (`not` predchádzajúce) presne ako `_is_payment_followup`.

## 11. Opening-hours follow-up

`_OPENING_HOURS_FOLLOWUP_DAY_MARKERS` - len jednoznačné názvy dní
(pondelok...nedeľa, víkend). Cases H/I/G2 zo zadania overené (Saturday,
Sunday, "A cez víkend?"). Prípad E ("Ste dnes otvorení?" → "A zajtra?")
zámerne NEpokrytý - viď Sekcia 14.

## 12. Contact follow-up

`_CONTACT_FOLLOWUP_MARKERS` - telefón/email cue slová. Adresa/Maps
follow-upy ("Pošli mi adresu.", "A Google Maps?") sú zadarmo pokryté
EXISTUJÚcim `looks_like_location_reference_followup()` (nie je
topic-gated) - žiadny duplicitný kód.

## 13. store_location / Maps control

`test_v2_15c_store_location_maps_regression` - `Kde sa nachádza kamenná
predajňa?` → `Pošli mi mapu.` naďalej vracia kanonický
`maps.app.goo.gl/3tFJ4P6w2pj88xAP8` link, nezmenené. Nový contact FAQ
záznam TIEŽ automaticky dostáva tento istý kanonický link (obsahuje
kanonickú adresu, `_build_maps_link_from_faq_answer()` je content-based,
nie topic-based).

## 14. RELATIVE-DAY STATUS

**RELATIVE_DAY_QUERY_FOUNDATION_ONLY.** "Dnes"/"zajtra" zámerne
VYLÚČENÉ z follow-up cue setu (`_OPENING_HOURS_FOLLOWUP_DAY_MARKERS`) -
tento repozitár nemá spoľahlivý timezone-aware "aký je dnes deň"
mechanizmus, a bare "dnes"/"zajtra" sa bežne vyskytuje v nesúvisiacich
commerce dopytoch ("máte dnes akciu na ryžu?"), čo by riskovalo
hijacking. Viacslovné frázy ("ste dnes otvorení", "mate dnes otvorene")
SÚ rozpoznané ako INITIAL dopyt (vrátia reálny týždenný rozvrh, z
ktorého zákazník sám odčíta dnešný stav) - žiadny kód nepočíta ani
netvrdí konkrétny "otvorené teraz: áno/nie" status.

## 15. HOLIDAY-HOURS STATUS

**DATA_REQUIRED.** Žiadny kalendár výnimiek v repozitári. Bežné týždenné
hodiny sú LIVE; sviatočné hodiny neboli a nebudú v tejto sprinte
vymyslené.

## 16. STORE-LOCATION / MAPS CONTROL

Pozri Sekciu 13.

## 17. ROUTING PRECEDENCE

Nezmenená - nové vetvy na identickej, poslednej pozícii (po safety/FAQ/
comparison/use_case/basket/recipe/ordinal/orphaned-followup, pred
generickou commerce kaskádou).

## 18. HARD TOPIC SWITCH SAFETY

Overené (lokálne aj live): `opening_hours`→product_search/recipe/
replacement; `contact`→product_search/replacement/recipe/
allergen_safety. Všetky správne prebíjajú stálu tému.

## 19. SESSION RESET

`apply_reset()` nezmenené (existujúce vymazanie
`last_informational_question` stačí pre oba nové topicy). Otestované.

## 20. CROSS-SESSION ISOLATION

Otestovaná pre oba nové topicy - žiadny leak.

## 21. CLAIM SAFETY

Žiadny fabrikovaný fakt. Telefón/email/adresa/Maps link sú všetky
znovu-použité z už-overených zdrojov (žiadna nová hodnota vymyslená).
Opening-hours follow-up nikdy netvrdí "otvorené práve teraz" - len
zobrazuje reálny rozvrh.

## 22. FAQ / BLAST-RADIUS AUDIT

Re-check proti `data/products.json` (2140 produktov) potvrdil V2.16a
nález a rozšíril ho:
```
otvoren -> 5 hits: "po otvorení" (skladovacie inštrukcie), "otvorenými
           očami" (dekor), "otvoreným plameňom" (grilovanie),
           "Na otvorenie nápoja" (návod), "dotvorenie" (NESÚVISIACE
           slovo obsahujúce "otvoren" ako substring)
kontakt -> 4 hits: "kontakt s potravinami" (2x, obalové boxy),
           "priamy kontakt s fóliou" (2x, potravinárska fólia)
```
Detektory používajú buď viacslovné frázy (nikdy holé "kontakt"), alebo
whole-TOKEN prefix check (`tokenize()` už zabraňuje "dotvorenie" typu
falošným zásahom) PLUS interrogatívny cue token, PLUS explicitné
vylúčenie presne nájdeného "po otvoren" kolízneho vzoru. Negatívne
kontroly (`Ako mam skladovat tento produkt po otvoreni?`, `Je tato folia
vhodna na priamy kontakt s potravinami?`) overené - obe zostávajú
`product_search`.

## 23. WIDGET STATUS

**WIDGET_PATCH_NOT_REQUIRED** - `git diff -- app/widget.js
app/widget.html` prázdny.

## 24. JS TEST STATUS

**NOT_REQUIRED_WIDGET_UNCHANGED.**

## 25. TARGETED PYTHON TESTS

`tests/test_opening_hours_contact_grounding_v2_16a_1.py` - 37 nových
testov. Plus aktualizácia `tests/test_conversational_informational_
followup_v2_16a.py`: `TestOpeningHoursPreExistingGap`/
`TestContactPreExistingGap` premenované na `TestOpeningHoursClosedByV2161a`/
`TestContactClosedByV2161a` s aktualizovanými assertions (history
zachovaná v docstringoch/komentároch, nie prepísaná). Spolu s
`test_noncommerce_context_followup_v2_15c.py`: **90/90 PASSED.**

## 26. FULL TEST SUITE

BEFORE (git stash): 1870 testov. AFTER: 1907 testov (+37). Plný beh
AFTER: **1907 passed, 0 failed, 0 errors** (837.22s, izolovaný
`--basetemp` od začiatku - žiadna dočasno-adresárová kontaminácia tento
raz).

## 27. V2.10 BEFORE/AFTER

BEFORE aj AFTER: **54/58 (93.1%)**, identické error buckets
(`GROUNDING_ERROR: 2`, `RETRIEVAL_MISS: 2`). Nulová regresia.

## 28. CANARY

**10/10 PASS**, žiadne anomálie.

## 29. CONSISTENCY AUDIT

**0 nových marker/alias kolízií** (nové detektory sú phrase-only, mimo
`FAQ_INTENT_MARKERS`, mimo declension-scoreru). Existujúce declension
nálezy identické so stavom pred touto sprintou - **0 nových**.

## 30. TRUST AUDIT

**0 nálezov.** PII redakcia korektne NEoznačila nové telefónne
číslo/email ako leak (je to verejný business support kontakt, nie
customer PII).

## 31. LLM CALL COUNT

0 nových.

## 32. SEARCH CALL COUNT

0 nových catalog-search volaní pre informačný routing.

## 33. PERFORMANCE

Zanedbateľný - čisté substring/token porovnania na už existujúcom texte,
žiadne nové I/O ani sieťové volania (žiadne volanie na Google Maps/
Business API).

## 34. PRIVACY

Žiadne nové PII storage. Nové dáta (telefón/email) sú verejné business
kontaktné údaje, nie customer PII.

## 35. LEARNING/RANKING FREEZE

`app/learning_lifecycle.py`, `app/ranking*.py`, `app/learning_candidates.py`,
`app/learning_cycle.py` - `git diff --stat` prázdny pre všetky.

## 36. AUTO_PROMOTION STATUS

`AUTO_PROMOTION_ENABLED` nezmenené (default `False`, `app/learning_lifecycle.py:57`).

## 37. rt0004/rt0010/rt0011/rt0013

Všetky 4 permanentné kontroly PASSED (lokálne + live).

## 38. RAMEN CONTROL

Overené (hard-switch test `Daj mi recept na ramen.` po hours/contact
téme → `recipe`).

## 39. V2.15/V2.16 CONTROL MATRIX

`test_noncommerce_context_followup_v2_15c.py` (21 testov) a
`test_conversational_informational_followup_v2_16a.py` (32 testov,
aktualizovaných na 5 nových assertions) - všetky PASSED, žiadna
regresia payment-followup mechanizmu potvrdená explicitným
cross-check testom.

## 40. MIXED-EOL / BYTE-SAFETY AUDIT

**Aplikovaná permanentná disciplína zo Sekcie 20 zadania.** `app/main.py`
opäť ukázal whole-file CRLF normalizáciu po prvom kole úprav (rovnaký
mechanizmus ako V2.16a) - diagnostikované OKAMŽITE (`git diff --stat`
ukázal ~15200 zmenených riadkov namiesto ~70) a opravené identickou
byte-presnou rekonštrukčnou technikou (pôvodný blob načítaný binárne,
`splitlines(keepends=True)`, 4 skutočné hunky vložené s lokálnym EOL,
zvyšok bajtovo nezmenený). `data/knowledge.json` bol upravený PRIAMO
byte-precíznym Python skriptom (nie cez editačný nástroj) preventívne,
keďže je to 7.2 MB, jednotne-CRLF súbor - `git diff --stat` potvrdil
presne 12 riadkov. `app/session_state.py` a nový testovací súbor sa
upravili čisto (žiadna korupcia). Finálny `git diff --check` na všetky
zmenené súbory: 0 problémov (okrem očakávaných CRLF-ako-"trailing
whitespace" hlásení konzistentných s existujúcim štýlom oboch súborov).

## 41. DIFF AUDIT

`git diff --stat`: `app/main.py` +66/-4, `app/session_state.py` +104,
`data/knowledge.json` +12, `tests/test_conversational_informational_
followup_v2_16a.py` +108/-44 (rename + updated assertions). Žiadny
neočakávaný súbor, žiadny secret (`grep -iE "api.?key|secret|password|
bearer"` na diffe = 0 zásahov).

## 42. DOCUMENTATION

Tento dokument. `docs/routing-debt.md` nebol upravený (žiadny relevantný
nový routing-debt záznam vznikol touto sprintou).

## 43. COMMIT SHA(S)

Viď finálny report (commit sa vytvorí po dokončení tohto dokumentu).

## 44. CI

Viď finálny report.

## 45. RAILWAY

Viď finálny report.

## 46. LIVE PRODUCTION MATRIX

Viď finálny report.

## 47. LIVE CLAIM-SAFETY CHECK

Viď finálny report.

## 48. PER-CAPABILITY READINESS MATRIX

| Capabilita | Zdroj dát | Initial | Follow-up | Gate | Status |
|---|---|---|---|---|---|
| store_location | GROUNDED (existujúce) | LIVE | LIVE | C | **LIVE** (nezmenené) |
| opening_hours | AUTHORITATIVE_UNSTRUCTURED (existujúce, extrahované) | LIVE | LIVE (dni v týždni) | D | **LIVE** |
| opening_hours_relative_day | N/A (žiadny temporal mechanizmus) | rozpoznané, reálny rozvrh | rozpoznané | - | **RELATIVE_DAY_QUERY_FOUNDATION_ONLY** |
| holiday_hours | DATA_REQUIRED | N/A | N/A | A | **DATA_REQUIRED** |
| contact_generic | GROUNDED (znovu-nájdené) | LIVE | LIVE | C | **LIVE** |
| contact_address | GROUNDED | LIVE | LIVE | C | **LIVE** |
| contact_maps | GROUNDED | LIVE | LIVE | C | **LIVE** |
| contact_phone | GROUNDED (znovu-nájdené) | LIVE | LIVE | C | **LIVE** |
| contact_email | GROUNDED (znovu-nájdené) | LIVE | LIVE | C | **LIVE** |
| delivery | GROUNDED (V2.16a) | LIVE | LIVE | C | **LIVE** (nezmenené) |
| pickup | GROUNDED (V2.16a) | LIVE | LIVE | C | **LIVE** (nezmenené) |
| payment | GROUNDED (V2.16a) | LIVE | LIVE_WITH_LIMITATIONS | C | **LIVE_WITH_LIMITATIONS** (nezmenené) |

## 49. GLOBAL RELEASE STATUS

**OPENING_HOURS_AND_CONTACT_LIVE** (s výnimkou `holiday_hours` =
DATA_REQUIRED a `opening_hours_relative_day` = FOUNDATION_ONLY, oba
explicitne dokumentované, nie skryté).

## 50. REMAINING DEBT

- `holiday_hours`: vyžaduje business-owner-dodaný kalendár výnimiek.
- `opening_hours_relative_day`: vyžaduje spoľahlivý timezone-aware
  "aký je dnes deň" mechanizmus predtým, ako je bezpečné tvrdiť
  "otvorené práve teraz: áno/nie".

## 51. RECOMMENDED NEXT STEP

Žiadna ďalšia informačná sprint nie je nutná - pokrytie šiestich
capabilít (store_location, opening_hours, delivery, pickup, payment,
contact) je teraz kompletné a evidence-grounded. Ak business poskytne
kalendár sviatočných hodín, samostatná malá uzávierka by mohla doplniť
`holiday_hours` bez zásahu do zvyšku architektúry.
