# Routing Debt Register

Dátum: 2026-08-20. Vytvorené počas V2.13a (AdvisorEngine Application
Boundary sprint) zo 7 zlyhaní V2.10 golden suite pri commite `5f7303d`
(V2.12.4 HEAD). Toto NIE JE zoznam vecí opravených v V2.13a — V2.13a je
čisto architektonická extrakcia (aplikačná hranica), nulová zmena
routing/intent/retrieval sémantiky (Invariant #2). Tento register je
vstupný dôkazový základ pre V2.13b (TurnResolver + WorkflowResolver).

## Prečo tento dokument existuje

51/58 na V2.10 nie je len jedno číslo — každé zo 7 zlyhaní má inú
príčinu a inú relevanciu pre budúcu prácu. Zmiešanie "toto je routing
bug" s "toto je pravopisný nesúlad v testovacom datasete" by viedlo
V2.13b k riešeniu nesprávnych vecí. Tento register drží presnú,
overenú klasifikáciu.

## Register

| case_id | query | current_intent | current_workflow | expected_semantic_behavior | failure_class | root_cause | confidence | target_sprint | status |
|---|---|---|---|---|---|---|---|---|---|
| `regbug_rt0004` | "súvisiace produkty k sushi ryži" | `product_search` | `LEGACY_FALLBACK` | related/complementary products (nori, ryžový ocot, wasabi, nakladaný zázvor) | RETRIEVAL_MISS + RANKING_ERROR + INTENT_ERROR | `"sushi ryža"` sebavedomo rezolvuje `family=rice/subfamily=sushi_rice`; V2.12.2 Bug A guard (`_query_resolves_to_confident_product_family`) potom potláča `related_subject`, keďže dopyt neobsahuje frázu z `RECIPE_SHOPPING_LANGUAGE_MARKERS` presne v tomto tvare | HIGH | V2.13b | **OPEN — ROUTING/WORKFLOW PRECEDENCE DEFECT** |
| `regbug_rt0010` | "sójová omáčka bez sóje" | `product_search` | `PRODUCT_LOOKUP` | `allergen_safety` — 0 produktov + bezpečnostné upozornenie | PRESENTATION_ERROR + GROUNDING_ERROR + INTENT_ERROR | allergen/safety detektor nerozpoznáva vzor "X bez [alergénu, ktorý je definičnou súčasťou X]" — dopyt nikdy nezíska prednosť pred plochým product_search | HIGH | V2.13b | **OPEN — ROUTING/INTENT PRECEDENCE GAP** (predtým nepresne označené `INTENTIONAL_SAFETY_BEHAVIOR` vo V2.12.3 — opravené v V2.12.4 finálnom reporte) |
| `regbug_rt0013` | "náhrada za rybiu omáčku vegan" | `replacement_products` | — | golden case očakáva `product_search`; systémové správanie (`replacement_products`) je architektonicky plausibilné pre doslovné "náhrada za X" | INTENT_ERROR | nejasné, či je chybný systém alebo golden case | — | — | **PENDING_SEMANTIC_PRODUCT_DECISION — HUMAN_REVIEW_REQUIRED** |
| `regbug_rt0002` | "potrebujem niečo bez lepku k sushi" | `product_search` | — | (zhoda s očakávaním) | RETRIEVAL_MISS | golden case očakáva anglický prepis `'sushi ryža'`, katalóg/produkty používajú slovenský `'Suši ryža'` | — | — | **CLOSED — evaluation/text normalization artifact, nie routing** |
| `regbug_rt0006` | "čo k červenej kari paste?" | `related_products` | — | (zhoda s očakávaním) | RETRIEVAL_MISS | golden case očakáva `'rybia omáčka'`, katalóg má `'Rybacia omáčka'` (iný gramatický tvar) — produkt je fakticky prítomný | — | — | **CLOSED — lexical/evaluation wording mismatch, nie routing** |
| `regbug_rt0022` | "potrebujem recept na kimchi" | `recipe` | `RECIPE_SHOPPING` | (zhoda s očakávaním, intent aj workflow správne) | GROUNDING_ERROR | AI-generovaný text neobsahuje presne očakávané slová `'kapustu'`/`'fermentovat'` | — | — | **CLOSED — generated-answer textual variance, nie routing** |
| `regbug_rt0024` | "ako môžem zaplatiť?" | `faq` | — | (zhoda s očakávaním, intent správny) | GROUNDING_ERROR | FAQ odpoveď neobsahuje presne slovo `'Dobierka'` | — | — | **CLOSED — generated-answer textual variance, nie routing** |

## Mandátne V2.13b prípady (Invariant #4/#5 zo zadania V2.13a)

### A) `regbug_rt0004`

```
"súvisiace produkty k sushi ryži"
Expected workflow: RELATED / COMPLEMENTARY PRODUCTS
```

Fráza vyjadrujúca požadovanú akciu ("súvisiace produkty k X") musí
prebiť rozpoznanú produktovú entitu (rodinu) v rámci nej. TurnResolver
musí vedieť rozlíšiť "chcem X" od "chcem NIEČO SÚVISIACE S X", aj keď X
samo osebe sebavedomo rezolvuje vlastnú rodinu.

### B) `regbug_rt0010`

```
"sójová omáčka bez sóje"
Expected workflow: ALLERGEN / SAFETY
```

Bezpečnostný zámer musí získať prednosť pred bežným product retrieval,
KEĎ dopyt pomenúva alergén, ktorý je definičnou súčasťou pýtaného
produktu — nie len keď je alergén doplnkovou vlastnosťou.

## Čo tento dokument NIE JE

- Nie je zoznam vecí opravených v V2.13a (V2.13a routing nemení vôbec).
- Nie je dôkaz, že systém je "rozbitý" — 51/58 s presne diagnostikovanými
  2 skutočnými routing medzerami (z 25 celkových critical golden
  prípadov) je solídny stav pre produkčný systém tejto veľkosti.
- Nie je konečný zoznam všetkých routing medzier — len tých, ktoré V2.10
  golden suite momentálne meria. Produkčný monitoring (V2.12.4
  `search_quality.jsonl`) môže časom odhaliť ďalšie, akonáhle sa
  nahromadí dostatočný objem.

## Ako pridávať nové záznamy

Pri objavení novej routing medzery (manuálnym testovaním, produkčným
monitoringom, alebo novým golden case zlyhaním): pridaj riadok do
tabuľky vyššie s rovnakou disciplínou — `root_cause` musí byť overený
priamym testom (`parse_structured_query`, `select_workflow`, atď.), nie
odhad. Nemiešaj `evaluation wording mismatch` s `workflow architecture
defect` — sú to odlišné triedy problémov vyžadujúce odlišnú akciu.
