# V2.18d.1 — Fix: regbug_rt0010 "diacritics-strip fragility"

Dátum: 2026-09-03. Baseline commit: `872092ad129ab9de1e7d31e77fcc730cbbba9185`.
Human mandát: "V2.18d.1 — fix regbug_rt0010 diacritics-strip fragility"
(vybraný z Kandidáta A v `docs/intelligence-diagnostic-loop-v2.18.md`).

## 1. Diagnóza — TOTO NIE JE chyba Advisora

Priame porovnanie cez `app.evaluation.adapter.make_chat_fn()`
(EVALUATION context) ukázalo, že dotaz s diakritikou ("sójová omáčka
bez sóje") a diakritikou zbavený dotaz ("sojova omacka bez soje")
produkujú **bajtovo identickú** odpoveď: `intent=allergen_safety`,
`products=[]`, rovnaký text ("Prosím overte zloženie a alergény...").
Advisor sa správa **správne a bezpečne** v oboch prípadoch — čestne
odmieta odporučiť konkrétny produkt pri alergénovej otázke.

## 2. Skutočná príčina — chyba vo V2.18a-c diagnostickom nástroji

`app.intelligence_diagnostics.scenario_registry.adapt_golden_case()`
mal chybný fallback: pre každý prípad bez `must_include_title_substrings`
automaticky priradil invariant `"products_nonempty"` — bez ohľadu na
to, či prípad má explicitný kontrakt `max_products=0` (t.j. PRÁZDNY
zoznam produktov JE správne, bezpečné správanie — napr. pri
alergénových/FAQ/receptových odpovediach).

Tento chybný fallback sa uplatňoval LEN pri `SAFE_MUTATION` potomkoch
scenára (`mutate_scenario()` dedí `expected_invariants` nezmenené) —
pôvodný (nemutovaný) scenár bol vždy skórovaný cez skutočný
`app.evaluation.runner.run_golden_case()`, ktorý `max_products`
rešpektuje správne a nikdy nebol touto chybou dotknutý.

## 3. Rozsah dopadu

**36 z 43 FAIL výsledkov** v prvej generácii Intelligence Reportu
(`2a3bf04d36e1ec298d1470eb`) zdieľalo presne túto príčinu, naprieč
**10 regresnými prípadmi**: rt0003, rt0007, rt0010, rt0015, rt0016,
rt0022, rt0023, rt0024, rt0025, rt0027.

## 4. Oprava (minimálny patch)

- `app/intelligence_diagnostics/invariant_evaluator.py`: pridaný nový
  invariant `"products_empty"` (opak `"products_nonempty"`).
- `app/intelligence_diagnostics/scenario_registry.py`: `adapt_golden_case()`
  teraz najprv kontroluje `case.max_products == 0` → `"products_empty"`;
  inak (a len ak chýbajú `must_include_title_substrings`) →
  `"products_nonempty"` ako predtým.

**Nulová zmena v `app/main.py`, `app/widget.js`, alebo akomkoľvek
zákaznícky-relevantnom súbore.** Toto je čisto oprava diagnostického
nástroja, nie zmena Advisor správania.

## 5. Overenie

- Priamo: všetky 4 mutácie `regbug_rt0010` (typo, diacritics_strip,
  word_order, politeness_toggle) teraz **PASS** živo.
- 7 nových permanentných regresných testov
  (`tests/test_intelligence_diagnostics_v2_18.py::TestMaxProductsZeroInvariantFix`).
- **Nová generácia benchmarku** (`88a4499e90e395dfd3cb8cde`):
  overall_score **0.861 → 0.945**, mutation_score **0.840 → 0.947**
  (teraz VYŠŠIE než stable_core_score 0.939), FAIL **43 → 17**.
- Plná Python sada: **2245 passed** (2238 baseline + 7 nových).
- V2.10 evaluácia: identická ako baseline (35/39, `GROUNDING_ERROR: 2,
  RETRIEVAL_MISS: 2` — presne rovnaký, nezmenený stav, potvrdzuje že
  Advisor správanie sa NEZMENILO).
- Canary: 10/10 PASS. Consistency/trust audit: čisté.

## 6. Zostávajúcich 17 FAIL

Nie sú predmetom tohto mandátu (úzko vymedzený na `regbug_rt0010`).
Zostávajú ako legitímne kandidáty pre budúci, samostatný V2.18d.2+
mandát — vyžadujú individuálnu diagnózu (mohli by byť reálne slabiny
Advisora, alebo ďalšie artefakty diagnostického nástroja).

## 7. Nasadenie

**ŽIADNE Railway nasadenie v tomto mandáte** — zmena zostáva lokálne
commitnutá, NEPUSHNUTÁ na `origin/main` (push by v tomto projekte
automaticky spustil Railway deploy). Nasadenie vyžaduje samostatné,
explicitné ľudské schválenie ("V2.18d.1-release").
