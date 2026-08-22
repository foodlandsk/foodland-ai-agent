# V2.14f — Evidence-Grounded Recommendation Decision, Choice Explanation & Conversion Intelligence

Dátum: 2026-08-22. Baseline: `2a2801f` (V2.14e), pytest 1517/1517, V2.10
fast-mode 34/39, canary 10/10.

## 1. Repository reality check

HEAD == `origin/main` == `2a2801f` pred zmenami (presná zhoda s SHA
očakávanou v zadaní), žiadny drift, čistý working tree.

## 2. Audit existujúcich primitívov (PRED implementáciou)

**Kľúčový nález**: `app/comparison.py` (V2.14b) už implementuje takmer
CELÝ požadovaný recommendation-decision model pre PRESNE VYRIEŠENÝ pár
produktov:
- Rozhodovacie stavy: `CLEAR_WINNER`/`CONDITIONAL_WINNER`/`TRADE_OFF`/
  `NO_MEANINGFUL_DIFFERENCE`/`CLARIFY`/`ABSTAIN`.
- Ciele: `CHEAPEST`/`BEST_VALUE`/`LARGEST_PACK`/`SMALLEST_PACK`/
  `GENERAL_BEST`/`UNSUPPORTED_QUALITATIVE` (posledný explicitne routuje
  na ABSTAIN pri chuti/autenticite/prémiovosti/zdravosti/obľúbenosti).
- `reason_codes` (price_fit, unit_price_fit, size_fit, brand_fit,
  product_type_fit) explicitne exponované, "why this"/"why not other"
  už zabudované v `compose_comparison_answer()`.
- **Nulové LLM volanie** kdekoľvek v rozhodovacej/kompozičnej ceste
  (bezpečnosť "by construction", nie runtime detekciou).

`app/use_case_advice.py` (V2.14c) implementuje analogický model pre
PRESNE JEDNU rolu jedného use case. `app/basket_completion.py` (V2.14e)
pre VIACERO rolí naraz. `app/grounding.py` je VŠEOBECNÝ LLM-výstupný
sanitizér (URL/cena) — **nerobí komparatívnu claim-validáciu vôbec** —
irelevantné pre V2.14b/c/d/e/f, pretože žiadny z ich modulov nikdy
nevolá LLM v rozhodovacej ceste.

**Záver**: V2.14f nepotrebuje novú "recommendation decision" vrstvu —
existujúce primitíva už POKRÝVAJÚ takmer celý požadovaný model. Sprinta
je preto primárne AUDIT + oprava 2 reálnych, charakterizáciou
objavených defektov + 1 nová, úzko ohraničená funkcia (comparison
follow-up continuity).

## 3. Current-behavior characterization (Section 7, pred zmenou)

| Prípad | Dopyt | Pred V2.14f |
|---|---|---|
| A | "ktorú rybaciu omáčku mám kúpiť?" | `related_products` (plochý zoznam, žiadne rozhodnutie) |
| B | "ktorá rybacia omáčka je najlepšia na pho?" | `product_search` — **BUG**: trailing "?" blokoval `resolve_use_case()` |
| C | "Kikkoman alebo Yamasa?" | `product_comparison`/CLARIFY (bez kontextu) |
| H | "je tá drahšia lepšia?" (po komparácii) | fallback bez kontextu — **BUG**: "drahšia" mapovalo na GOAL_CHEAPEST |
| J | "potrebujem ryžu na sushi, ktorú odporúčaš?" | `related_products` — **BUG**: trailing "," blokoval `resolve_use_case()` |
| M | "najlepšia omáčka na Tom Kha" | `use_case_advice` (funguje) |
| N | "najlepšie rezance na ramen" | `product_search` (korektne DATA_REQUIRED) |

## 4. Recommendation goal model

Znovupoužitý bezo zmeny z V2.14b (`app.comparison`'s goal vokabulár) a
V2.14c (`app.use_case_advice`'s rola-per-use-case). Žiadny nový goal
detektor — Section 9 explicitne zakazuje vymýšľať detektory len na
splnenie zoznamu.

## 5. RECOMMEND / COMPARE / CLARIFY / ABSTAIN

Nezmenené, znovupoužité z V2.14b/c.

## 6. Evidence model

Znovupoužitý z V2.14a bezo zmeny (`EvidenceItem`/`compute_confidence()`).
Žiadny nový confidence systém.

## 7. Confidence contract

LLM_JUDGMENT nikdy negeneruje HIGH — nezmenené, overené statickou
inšpekciou (`TestNoNewLlmCall`).

## 8. Comparative grounding — 2 reálne opravené defekty

### Defekt 1: trailing punctuation (`app/use_case_advice.py`)

`resolve_use_case()` vyžadoval doslovnú medzeru hneď za use-case
aliasom — akákoľvek otázka končiaca "?" alebo s čiarkou hneď za
aliasom ("na pho?", "na sushi, ktorú...") sa **vôbec nevyriešila**.
Opravené novou `_padded_for_boundary_match()` (nahrádza `?!.,;:`
medzerami pred kontrolou hranice) — aplikované LEN na
`resolve_use_case()`.

**Druhý reálny nález pri oprave**: rovnaká oprava aplikovaná aj na
`resolve_role()` spôsobila NOVÚ regresiu — čiarka medzi dvoma
sémantickými vetami ("mám ryžové rezance, čo ešte potrebujem na pho?")
sa zmenila na medzeru, čím rolový marker "rezance" nesprávne "preskočil"
cez hranicu viet a uniesol `app.basket_completion`'s self-deklaračný
ťah do jednorolovej `use_case_advice` odpovede
(`tests/test_basket_completion_v2_14e.py::TestCaseG_AlreadyCoveredRole`).
Opravené vrátením `resolve_role()` na pôvodné, konzervatívnejšie
správanie — obe mandátne charakterizačné prípady (B, J) nepotrebovali
túto funkciu zmenenú vôbec.

### Defekt 2: "drahšia" → GOAL_CHEAPEST (`app/comparison.py`)

`_CHEAPEST_MARKERS` obsahovalo `"drahsi"`/`"drahsia"` — "je tá drahšia
lepšia?" (Section 12 vlajkový príklad) sa tak vyriešilo ako GOAL_CHEAPEST
a odpovedalo odporúčaním LACNEJŠIEHO produktu — nezmyselná odpoveď na
inak položenú otázku. Opravené odstránením z `_CHEAPEST_MARKERS` +
novou explicitnou kombinovanou kontrolou (`_PRICE_DIRECTION_MARKERS` +
`_BARE_QUALITY_MARKERS`) → `GOAL_UNSUPPORTED_QUALITATIVE` → čestný
ABSTAIN ("Viem porovnať... podľa ceny a veľkosti balenia, ale nemám
spoľahlivé údaje na to, aby som povedala, ktorá chutí lepšie alebo je
autentickejšia."). Bare "ktorá je lepšia?" (bez cenovej zmienky) zostáva
zámerne nezmenené (GOAL_GENERAL_BEST) — nestráca užitočnosť pre
najbežnejšiu formuláciu.

## 9. Best-choice policy

Nezmenené — `GOAL_GENERAL_BEST` už len skladá dominanciu cez
overiteľné dimenzie (cena/veľkosť), nikdy chuť/kvalitu.

## 10. Choice explanation / Why-not-other

Znovupoužité z V2.14b `compose_comparison_answer()` — `reason_codes`
explicitne v odpovedi, symetrické pomenovanie oboch produktov.

## 11. Price / Size / Value logic

Nezmenené (`_price_evidence`/`_unit_price_evidence`/`_size_evidence`,
V2.14b) — jednotková cena porovnáva LEN zhodné jednotky, nikdy g proti ml.

## 12. Use-case integrácia

Nezmenené (5 eligible use cases z V2.14e), ramen vylúčený.

## 13. Ramen exclusion

Overené naživo a testom: `resolve_use_case("najlepsie rezance na
ramen?")` vracia `None` — dve nezávislé štrukturálne brány (nie je v
`LIVE_USE_CASES` ani v `BASKET_V1_ELIGIBLE_USE_CASES`), nedotknuté.

## 14. Basket Completion integrácia

Nedotknuté — `app/basket_completion.py` sa nemenil. Odlišné sémantiky
zachované (recommendation = "ktorý vybrať", basket = "čo všetko
potrebujem").

## 15. Cross-sell integrácia

Nedotknuté.

## 16. Recipe shopping integrácia

Nedotknuté.

## 17. Session follow-up — nová funkcia

**Nová schopnosť**: `app.session_state.get_active_comparison_pair()`/
`set_active_comparison_pair()` (rovnaký konvenčný vzor ako
`active_recipe_id`/`active_use_case`) + `app.comparison.is_bare_comparison_followup()`/
`resolve_comparison_targets_from_pair()`. Keď `looks_like_comparison_request()`
je False, ale správa obsahuje rozpoznaný cieľový marker (cena/veľkosť/
kvalita) A existuje aktívny pár z posledného úspešne vyriešeného
porovnania, `execute_comparison()` prepočíta ROVNAKÉ `decide_comparison()`/
`compose_comparison_answer()` nad ULOŽENÝM párom s NOVÝM cieľom — žiadna
nová rozhodovacia logika, len druhá cesta k `ComparisonTargets`.

Živo overené: "porovnaj prvý a druhý" → CLEAR_WINNER, potom "Chcem
lacnejšiu." → CHEAPEST na TOM ISTOM páre, "Máte väčšie balenie?" →
LARGEST_PACK, "Je tá drahšia lepšia?" → ABSTAIN/UNSUPPORTED_QUALITATIVE.

## 18. Session contamination safety

Aktívny pár sa čistí pri explicitnom resete (`apply_reset()`) a
prirodzene nepreukazuje sa pri téme, ktorá nemá porovnávací marker
(hard topic switch funguje bez špeciálneho kódu — "Shin Ramyun"
neobsahuje žiadny cieľový marker, takže `is_bare_comparison_followup()`
vráti False). Cross-session izolácia overená testom (samostatný
`memory` dict per session_id, existujúci mechanizmus).

## 19. Allergen safety

Nedotknuté — beží PRED comparison/use_case_advice/basket_completion v
kaskáde, overené testom.

## 20. rt0004 / rt0010 / rt0011 / rt0013

Všetky tri live-overené nezmenené. rt0013 nedotknuté.

## 21. Observability / Learning signal contract

**Nezaviedené v tejto sprinte** — žiadne nové telemetria polia neboli
pridané (Section 28/29 zadania sú voliteľné, "only if safe and
consistent"; existujúci `log_question()`/`build_customer_intent()`
mechanizmus už zaznamenáva `intent`/`subject` pre každý nový branch
rovnako ako pre všetky V2.14 sprinty predtým — dostatočné pre V2.14g
audit bez nových polí tejto sprinty).

## 22. AUTO_PROMOTION / Learning safety

**Nedotknuté.** `app/learning_lifecycle.py` sa v tejto sprinte
nemenil (potvrdené `git diff --name-only`). Žiadny nový kód nečíta ani
nezapisuje `AUTO_PROMOTION_ENABLED`.

## 23. Response contract

Nové polia (`comparison_decision`/`comparison_goal`/`comparison_confidence`
už existovali z V2.14b) — follow-up cesta vracia PRESNE ROVNAKÝ tvar,
žiadne nové povinné polia.

## 24. Frontend compatibility

`app/widget.js` sa nemenil — žiadna zmena tvaru odpovede, ktorá by
vyžadovala frontend úpravu.

## 25. Privacy

Žiadne nové PII — `active_comparison_pair` ukladá len 2 product ID
(rovnaká citlivosť ako existujúce `active_recipe_id`).

## 26. LLM call count

**0 nových LLM volaní** (statický dôkaz, `TestNoNewLlmCall`).

## 27. Search call count / Performance

Žiadne nové vyhľadávanie — follow-up cesta znovupoužíva 2 už predtým
vyriešené produkty z pamäte. Nameraná latencia: **~5.4ms priemer**
(10 opakovaní s aktívnym párom), ~4.5ms bez (okamžitý defer).

## 28. Per-capability readiness matrix

| Capability | Ready? | Data coverage | Confidence support | Runtime status | Limitation |
|---|---|---|---|---|---|
| cheapest choice | Áno | Vysoké (effective_price univerzálne) | HIGH (DATA_DERIVED) | **LIVE** (V2.14b + follow-up) | — |
| larger/smaller choice | Áno | Stredné (unit_pricing_measure nie univerzálne) | HIGH keď dostupné | **LIVE** | ABSTAIN pri chýbajúcej veľkosti |
| use-case choice | Áno | 5 eligible use cases | HIGH/MEDIUM | **LIVE** | ramen vylúčený |
| price-per-unit choice | Áno | Len zhodné jednotky | HIGH/MEDIUM | **LIVE** | nikdy g proti ml |
| qualitative "best" | Nie | — | — | **ABSTAIN (zámerne)** | žiadny dôkaz kvality v katalógu |
| flavor-profile | Nie | — | — | **DATA_REQUIRED** | žiadne štruktúrované dáta |
| authenticity | Nie | — | — | **DATA_REQUIRED** | žiadne štruktúrované dáta |
| bare "ktorý si mám kúpiť?" (bez páru/use-case) | Nie | — | — | **GATE A (audit only)** | viď Sekcia 29 |
| basket continuation | Áno (nedotknuté) | — | — | **LIVE** (V2.14e) | — |

## 29. Vedome NEIMPLEMENTOVANÉ — Case A

"Ktorú rybaciu omáčku mám kúpiť?" (bare kategória, žiadny explicitný
pár, žiadny use-case rámec) zostáva `related_products` — **zámerne
neriešené v tejto sprinte**. Dôvod: bezpečné vyriešenie by vyžadovalo
novú "vyber TOP 1 z bežného vyhľadávacieho výsledku" mechaniku, ktorá
riskuje zámenu RANKING relevantnosti za RECOMMENDATION nadradenosť
(Section 14 explicitne zakazuje). Toto si vyžaduje samostatný,
premyslenejší dizajn (napr. explicitné rozlíšenie "najlacnejší z
zobrazených" vs. "objektívne najlepší"), nie rýchlu prístavbu v už
rozsiahlej sprinte. Klasifikované GATE A (audit only), odporúčané pre
budúcu sprintu s vlastným charakterizačným kolom.

## 30. Testy

`tests/test_recommendation_decision_v2_14f.py` (36 testov) — 2
permanentné regresné zámky (trailing punctuation, drahšia→CHEAPEST), 1
zámok pre clause-boundary regresiu objavenú počas opravy, 8 testov pre
comparison follow-up continuity, 15 z mandátnej Section 43 matice
(A/C/D/E/F/G/H/K/L/M/N/O), no-LLM statický dôkaz, rt0004/10/11.

## 31. Full test suite

**1553/1553** (1517 baseline + 36 nových), 0 regresií po oprave 2
nálezov.

## 32. V2.10 evaluation

Fast-mode **34/39 nezmenené** (identické error buckety).

## 33. Search quality canary

**10/10**, no anomalies.

## 34. Audits

Consistency 0, trust 0, deployment check passed.

## 35. Final release status

**Global**: `RECOMMENDATION_INTELLIGENCE_LIVE_PARTIAL`

## 36. Remaining debt

1. Case A (bare "ktorý si mám kúpiť?") — GATE A, audit-only.
2. Rovnaký dátový dlh ako V2.14d/e (ramen, 7 NO_TAXONOMY_MATCH koncepty,
   `structured_search`'s tableware-signal limit).
3. Comparison follow-up funguje LEN pre uz existujúce ciele
   (cena/veľkosť/kvalita) — nerozširuje sa na use-case rámec v tomto
   type follow-upu.
4. rt0013 nedotknuté.

## 37. V2.14g readiness

Recommendation rozhodnutia sú stabilné, deterministické, evidence-grounded.
Existujúci `log_question()`/`build_customer_intent()` mechanizmus už
zaznamenáva dostatočné signály pre budúci V2.14g audit BEZ potreby
nových telemetria polí v tejto sprinte. **AUTO_PROMOTION zostáva false**
a MUSÍ tak zostať aj v akejkoľvek budúcej V2.14g sprinte bez
samostatného, explicitného schválenia.
