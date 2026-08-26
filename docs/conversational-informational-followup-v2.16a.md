# Conversational Context & Informational Follow-up Expansion (V2.16a)

Dátum: 2026-08-26. Baseline commit: `5c1806203e580c002258f900405c9da95efc1027`
(HEAD, `origin/main`, žiadne uncommitted zmeny okrem netrackovaného
`.claude/`).

## 1. Prečo tento dokument existuje

V2.16a rozširuje V2.15c mechanizmus (`NON_COMMERCE_CONTEXTUAL_FOLLOWUP`,
pôvodne len `store_location`) na piatich ďalších informačných témach:
`opening_hours`, `contact`, `delivery`, `pickup`, `payment`. Zadanie
explicitne vyžadovalo audit PRED implementáciou (Sekcia 2/9/10) a
explicitne povolilo heterogénny, nie plne-zelený výsledok (Sekcia 63/67).

## 2. Repository reality check

- `git status`: čisté (len netrackovaný `.claude/`), `git log` potvrdil
  súvislú V2.13→V2.15e.3 históriu, HEAD == `origin/main`.
- V2.15c/d/e séria reprodukovaná ako popísaná v zadaní (store-location
  foundation, informational follow-up primitive, Maps handling,
  `result_set_id` continuation, recommendation/recipe_shopping decision
  observability). `AUTO_PROMOTION=False`, V2.15f nespustené — nezmenené
  touto sprintou.

## 3. V2.15c re-verifikácia (Sekcia 5 zadania)

Skutočný mechanizmus (nezmenený, overený priamym čítaním kódu aj behom):

- `app.session_state.get_last_informational_question()`/
  `set_last_informational_question()` ukladá **iba SUROVÝ TEXT OTÁZKY**
  (nikdy odpoveď) poslednej úspešne zodpovedanej FAQ otázky —
  `app/main.py:4509`, jedno prepisované pole, žiadna per-topic história.
- `app.session_state.looks_like_location_reference_followup()` — úzky,
  lokalizačne špecifický slovník (`app/session_state.py:308-334`).
- `app/main.py:4777-4812` — fallback blok, POZÍCIA AŽ NA KONCI kaskády
  (po safety/FAQ/random_recipe/reset/comparison/use_case_advice/
  basket_completion/recipe/ordinal-reference/orphaned-followup, PRED
  generickou commerce kaskádou). Táto pozícia (nie runtime negociácia)
  je to, čo garantuje "explicitný cieľ vždy vyhráva".
- `app.main._build_maps_link_from_faq_answer()` — kanonický Foodland
  Maps URL (`app/main.py:7443-7444`) sa použije LEN keď regex-extrahovaná
  adresa z recall-ovanej FAQ odpovede normalizuje na presne
  `_FOODLAND_CANONICAL_ADDRESS`.

Žiadna z týchto primitív sa nezmenila. V2.16a ich len obalil (Sekcia 14:
verdikt `WRAP_WITH_SMALL_INFORMATIONAL_RESOLVER`, rovnaký ako V2.15c).

## 4. Current-behavior characterization (pred implementáciou)

Skript spustený proti nezmenenému HEAD (`m.chat()` priamo, rovnaký
harness ako `tests/test_noncommerce_context_followup_v2_15c.py`) na
všetkých prípadoch A–S zo zadania. Kľúčové, empiricky prekvapivé
zistenia (nie predpoklady zo zadania):

| Prípad | BEFORE správanie |
|---|---|
| `store→maps`, `store→"ako sa tam dostanem"` | Funguje (V2.15c, nezmenené) |
| `"Kedy mate otvorene?"` (samotná) | `intent=product_search` (garbage) — FAQ kaskáda sa vôbec nedosiahne |
| `"Ako vas mozem kontaktovat?"` (samotná) | rovnako `product_search` |
| `"Dorucujete do Ceska?"` → `"Kolko stoji doprava?"` | **OBE ťahy nezávisle FAQ** — "doprav"/"doruc" sú už existujúce `FAQ_INTENT_MARKERS`, follow-up funguje BEZ akéhokoľvek session-kontextu |
| `"Ake mate moznosti dopravy?"` → `"A osobny odber?"` | **OBE ťahy nezávisle FAQ** — "odber" je existujúci marker |
| `"Ako mozem zaplatit?"` → `"Da sa kartou?"` | **OBE ťahy nezávisle FAQ** — "kartou" je existujúci marker |
| `"Ako mozem zaplatit?"` → `"A Apple Pay?"` | **REÁLNA CHYBA**: `intent=product_search`, vráti nesúvisiace produkty (fuzzy match "apple" → "Lepkavá ryža APPLE BRAND 2,27kg") |
| hard switches (product/replacement/recipe/comparison/safety/use_case) | všetky správne, nezmenené |
| reset, cross-session izolácia | správne, nezmenené |

Dôsledok: zadanie predpokladalo, že `delivery`/`pickup`/`payment` (karta)
follow-upy potrebujú nový mechanizmus — **empiricky nepotrebujú**, už
fungujú vďaka existujúcim `FAQ_INTENT_MARKERS`. Jediná reálna, reprodukovaná
medzera v tejto skupine je pomenovaný platobný spôsob mimo markerov
(Apple Pay/Google Pay/PayPal/...).

## 5. Source-of-truth audit (`data/knowledge.json`, `sections.FAQ`)

- `opening_hours`: **len ako vedľajšia veta v store-location zázname**
  ("Otváracie hodiny: Po–Pi 8:00–18:00, So 9:00–20:00, Ne 9:00–15:00").
  Žiadny samostatný FAQ záznam.
- `contact`: **DATA_ABSENT pre telefón** (0 výskytov `+421`/"telefón" v
  celom `knowledge.json`). Len scoped e-maily (`eshop@foodland.sk`,
  `reklamacie@foodland.sk`) viazané na konkrétne pod-témy, žiadny
  všeobecný "ako nás kontaktovať" záznam.
- `delivery`: reálne dáta — krajiny (DPD/GLS/Nagel do Európy, Packeta len
  SK/CZ/HU), doprava zadarmo nad 49 € pre súkromných zákazníkov.
- `pickup`: reálne dáta — osobný odber v Bratislave bez poplatku.
- `payment`: reálne dáta — hotovosť/karta pri odbere, 24-Pay/TatraPay/
  GoPay/PayPal/bankový prevod/dobierka online. **Apple Pay aj Google Pay
  sú DATA_ABSENT** — 0 výskytov v `knowledge.json`.

## 6. Blast-radius audit (pred akoukoľvek zmenou FAQ_INTENT_MARKERS)

Pred zvážením pridania markera pre `opening_hours` (napr. `"otvoren"`)
bol spustený test proti `data/products.json` (2140 produktov):

```
otvoren -> 5 hits (napr. "Teriyaki BBQ omáčka s medom KIKKOMAN" — "po otvorení" skladovacia inštrukcia)
hodin   -> 0 hits
kontakt -> 4 hits ("kontakt s potravinami" — obalové fólie)
```

**Rozhodnutie: marker `"otvoren"` sa NEPRIDÁVA.** Reálne riziko, že
legitímna otázka o skladovaní po otvorení ("Ako skladovať po otvorení?")
by bola nesprávne prevzatá FAQ vetvou namiesto product/usage odpovede.
`"hodin"` samotné by nezachytilo cieľovú frázu "Kedy máte otvorené?"
(neobsahuje "hodin"). `opening_hours` a `contact` preto zostávajú
`NOT_REACHED_PRE_EXISTING_GAP` — vedomé rozhodnutie, nie prehliadnutie
(Sekcia 26 zadania to explicitne povoľuje).

## 7. Architektonické rozhodnutie

Zvolená cesta: **REUSE_WITH_SMALL_WRAPPER** (Sekcia 14) — žiadne nové
session-state pole. `app.session_state.looks_like_payment_method_followup()`
klasifikuje tému AŽ PRI RECALL-e, testovaním, či samotná uložená
`last_informational_question` obsahuje existujúci payment marker
(`plat`/`kartou`/`hotovost`), a či aktuálny ťah obsahuje jeden z nových,
úzkych `_PAYMENT_METHOD_FOLLOWUP_MARKERS` (`apple pay`, `google pay`,
`paypal`, `gopay`, `24-pay`, `tatrapay`, `prevod`, `dobierka`). Reset/TTL/
cross-session izolácia sa dedia zadarmo (rovnaké pole ako V2.15c).

`app/main.py:4777-4812` fallback blok rozšírený o `elif` vetvu na
**identickej pozícii** — žiadny hard-switch invariant sa nemenil.

## 8. Gate rozhodnutia per capabilita

| Capabilita | Initial routing | Follow-up | Gate | Status |
|---|---|---|---|---|
| `store_location` | LIVE (nezmenené) | LIVE (nezmenené) | C | **LIVE** |
| `delivery` | LIVE (existujúce markery) | LIVE (existujúce markery, bez novej implementácie) | C | **LIVE** |
| `pickup` | LIVE (existujúce markery) | LIVE (existujúce markery, bez novej implementácie) | C | **LIVE** |
| `payment` | LIVE (existujúce markery) | LIVE pre kartu/hotovosť/prevod/dobierku (existujúce); **NOVÉ**: pomenovaný spôsob mimo markerov (Apple/Google Pay/PayPal) teraz recall-uje reálnu odpoveď namiesto product-search garbage | C | **LIVE_WITH_LIMITATIONS** (Apple Pay/Google Pay nie sú v dátach — odpoveď to nepotvrdzuje ani nevymýšľa, len ukáže reálne podporované spôsoby) |
| `opening_hours` | NOT_REACHED (marker gap, blast-radius riziko) | N/A (nemožné bez initial routingu) | A | **FOUNDATION_ONLY / NOT_REACHED_PRE_EXISTING_GAP** |
| `contact` | NOT_REACHED (žiadny marker, žiadny dátový zdroj) | N/A | A | **DATA_REQUIRED** |

## 9. Implementácia

- `app/session_state.py`: pridané `_PAYMENT_METHOD_TOPIC_MARKERS`,
  `_PAYMENT_METHOD_FOLLOWUP_MARKERS`, `looks_like_payment_method_followup()`.
  Žiadne nové session-state pole, žiadna zmena `apply_reset()` (existujúce
  vymazanie `last_informational_question` stačí).
- `app/main.py`: nový import + rozšírenie existujúceho V2.15c fallback
  bloku o `_is_payment_followup` vetvu, na identickej pozícii.
- **`app/widget.js` NEZMENENÝ** — audit potvrdil, že je to čistý UI shell
  bez FAQ/informačnej logiky (`WIDGET_PATCH_NOT_REQUIRED`).
- 0 nových LLM volaní, 0 nových catalog-search volaní (rovnaký kontrakt
  ako V2.15c — fallback blok volá len `best_direct_faq_answer`/
  `best_faq_answer`/`search_knowledge(allowed_sections=("FAQ",))`).

## 10. Testy

`tests/test_conversational_informational_followup_v2_16a.py` — 32
testov: store_location regresný zámok, opening_hours/contact
PRE_EXISTING_GAP charakterizácia, delivery/pickup/payment-karta
already-live regresný zámok, nová payment-method-followup kapabilita
(Apple Pay/Google Pay/PayPal + negatívna kontrola explicitného
"Apple Brand" produktu + bare-no-context negatívna kontrola), 6 hard-switch
kontrol, explicit-topic-override, anti-over-triggering, reset/cross-session
izolácia pre payment tému, rt0004/rt0010/rt0011/rt0013 permanentné
kontroly. Všetkých 32 PASSED. Pôvodných 21 testov
`test_noncommerce_context_followup_v2_15c.py` — všetkých 21 PASSED
(nezmenené).

## 11. Plný regresný test suite

BEFORE (git stash, nezmenený HEAD): 1838 testov collected.
AFTER (V2.16a): 1870 testov collected (+32, presne nový súbor).
Plný beh AFTER (solo, izolovaný `--basetemp`): **1870 passed, 0 failed,
0 errors** (788.79s).

Poznámka k metodike: prvý pokus o plný beh zaznamenal roztrúsené
`PermissionError` na zdieľanom `pytest-of-UNIRIA` temp adresári —
diagnostikované ako Windows file-lock kontaminácia zo súbežne bežiacich
pozadia procesov (nie regresia kódu), overené jej vymiznutím po
`taskkill` + izolovaný `--basetemp` (presne tak, ako to zadanie
predpokladalo v Sekcii "explicitne autorizovaný ... use --basetemp
where required").

## 11a. Diff/byte-safety audit — reálny nález

`git diff --stat` po prvej sade úprav ukázal **15165 zmenených riadkov v
`app/main.py`** (7627 insertions/7576 deletions) namiesto očakávaných
~20 — presne ten scenár, pred ktorým zadanie varuje ("Do not commit
accidental whole-file line-ending rewrites"). Diagnostika: pôvodný commitnutý
blob `app/main.py` má **zmiešané riadkové ukončenia** (2956× CRLF, 7201×
LF-only na 10157 riadkoch — historický artefakt, nie tejto sprinty), a
editačný nástroj pri zápise zmien normalizoval CELÝ súbor na jednotné
CRLF. `git add`/`core.autocrlf=true` toto nenormalizovalo späť (potvrdené
`git diff --cached --stat` = rovnako 15165 riadkov).

**Náprava**: byte-presná rekonštrukcia — pôvodný blob (`git show
HEAD:app/main.py`) načítaný binárne, rozdelený `splitlines(keepends=True)`
(zachová pôvodné `\r\n`/`\n` per-line), a LEN dva skutočné hunky (nový
import riadok, nahradenie fallback bloku) vložené s riadkovým ukončením
zodpovedajúcim lokálnemu kontextu — všetky ostatné riadky bajtovo
nezmenené. Overené: `diff --strip-trailing-cr` medzi rekonštrukciou a
predchádzajúcou (obsahovo správnou, ale EOL-poškodenou) verziou = žiadny
rozdiel (čisto obsahová zhoda). Výsledný `git diff --cached --stat`:
presne `app/main.py | 19 ++++++++++++++++---` a
`app/session_state.py | 38 ++++++++++++++++++++++++++++++++++++++`
(`session_state.py` bol od začiatku čistý — pôvodný blob je jednotne LF,
takže autocrlf normalizácia fungovala bez zásahu). `git diff --cached
--check` = 0 nálezov. Testy re-spustené proti rekonštruovanému súboru —
53/53 passed (V2.15c + V2.16a súbory).

## 12. V2.10 evaluation

BEFORE (git stash) aj AFTER (V2.16a): **54/58 golden cases (93.1%)**,
identické error buckets (`GROUNDING_ERROR: 2`, `RETRIEVAL_MISS: 2`),
`Gate: WARN` (rovnaké, nie nové). Nulová regresia — očakávané, keďže
golden set (`eval/golden/*.json`) je produktovo orientovaný (rice/sauces/
noodles/...), nie FAQ orientovaný. Historicky citované "35/39" v zadaní
zodpovedá staršiemu, menšiemu `--fast` datasetu z commitu `2bb1ea5`
(pred V2.15c) — nie priamo porovnateľné s aktuálnym `--full` 58-case setom.

## 13. Canary a audity

- `scripts/run_search_quality_canary.py`: **10/10 PASS, žiadne anomálie**
  (jazmínová ryža, basmati ryža, ryžové rezance, ryžový ocot, sushi ryža,
  rybacia omáčka, tmavá sójová omáčka, kokosové mlieko, Shin Ramyun,
  Kikkoman).
- `scripts/consistency_audit.py`: **0 marker/alias substring kolízií**
  (vrátane nových payment-followup markerov — sú gate-ované na topic
  match, nie súčasťou `FAQ_INTENT_MARKERS`, takže sa vôbec nezúčastňujú
  tejto kontroly). Existujúce declension-robustness nálezy (doruc*/
  vyzdvihnut*/dobierk*/registrac*/...) sú **PRE_EXISTING** — nesúvisia s
  novým kódom, ktorý nepoužíva všeobecný token-declension scorer vôbec.
- `scripts/trust_audit.py`: **0 nálezov** — 0 replacement-queries s
  potenciálne nulovými produktmi, 0 PII redaction leaks.

## 14. Bezpečnostné invarianty (nezmenené oproti V2.15c)

- Explicitný cieľ aktuálneho ťahu vždy vyhráva — overené priamo
  (`Poslite mi Apple Brand ryzu` po payment téme zostáva `product_search`).
- Žiadny fabrikovaný fakt — Apple Pay/Google Pay follow-up recall-uje
  reálnu, existujúcu odpoveď (ktorá tieto metódy nespomína), nikdy
  negeneruje nové tvrdenie o nich.
- `app/learning_lifecycle.py` a všetky ranking/promotion súbory
  nezmenené. `AUTO_PROMOTION=False`. V2.15f nespustené.

## 15. Známe limity / mimo rozsahu

- `opening_hours`/`contact` zostávajú `NOT_REACHED`/`DATA_REQUIRED` —
  vyžadujú buď nový, bezpečný FAQ marker (opening_hours) alebo nové
  prevádzkové dáta (telefónne číslo pre contact), obe mimo rozsahu tejto
  minimálnej sprinty.
- `delivery`/`pickup` follow-up podpora je "zadarmo" cez existujúce
  markery — nemajú vlastný dedikovaný slovník ako `payment`/
  `store_location`; ak by sa objavila fráza mimo existujúcich markerov
  (napr. "A je to zadarmo?"), zostáva NOT_REACHED. Nebolo pridané
  špekulatívne, bez konkrétneho reprodukovaného zlyhania (Sekcia 45/46
  zadania — žiadne hádanie desiatok fráz bez blast-radius dôkazu).
