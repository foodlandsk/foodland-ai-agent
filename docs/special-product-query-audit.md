# SPECIAL_PRODUCT_QUERIES / RELATED_PRODUCT_QUERIES Bundle Audit — Sprint V2.12.3

Dátum: 2026-08-20.

## Rozsah

V2.12.2 (Bug D) migrovalo 4 z 25 `SPECIAL_PRODUCT_QUERIES` kľúčov
(`plain_rice`, `sushi_rice`, `rice_vinegar`, `rice_cooker`) na štruktúrované
vyhľadávanie, pretože boli zneužívané ako PRIMÁRNE vyhľadávanie napriek
tomu, že taxonomy engine ich už vedel spoľahlivo rozpoznať ako vlastnú
rodinu. V2.12.3 mandátovalo doaudítovať zvyšných 21 kľúčov + samostatný
`RELATED_PRODUCT_QUERIES` mechanizmus (iný dict, iná funkcia,
`related_products_for_subject()`) rovnakou optikou.

## SPECIAL_PRODUCT_QUERIES — zvyšných 21 kľúčov

Pre každý kľúč bol spustený `parse_structured_query()` na reprezentatívnom
holom texte zodpovedajúcom `detect_special_product_subject()`'s vlastnému
trigger reťazcu (nie na umelo skonštruovanom texte):

| Kľúč | family/subfamily | Klasifikácia |
|---|---|---|
| `kimchi_product` | None/UNKNOWN | Bez taxonomy pravidla — CONSTRAINT_BASED_LEGACY |
| `gluten_free_sushi` | sauce/soy_sauce (len s dietary kvalifikátorom) | CONSTRAINT_BASED_LEGACY (dietary constraint) |
| `mild` / `hot` / `medium_spicy` | None/UNKNOWN | CONSTRAINT_BASED_LEGACY (spice-level) |
| `vegan_fish_sauce_replacement` | sauce/fish_sauce (len s "vegan" kvalifikátorom) | CONSTRAINT_BASED_LEGACY (dietary) |
| `kids_snack` / `asian_sweets` / `safe_snack` | None/UNKNOWN | CONSTRAINT_BASED_LEGACY |
| `dairy_replacement` / `vegan_asian` / `no_pork_asian` | None/UNKNOWN | CONSTRAINT_BASED_LEGACY (dietary) |
| `fermented_sour` | None/UNKNOWN | CONSTRAINT_BASED_LEGACY |
| `asian_noodles` | instant_food/instant_noodles (zavádzajúco generické) | CONSTRAINT_BASED_LEGACY — nie skutočný zámer dopytu |
| `rice_side` | None/UNKNOWN | CONSTRAINT_BASED_LEGACY |
| `korean_paste` | trigger texty ("gochu jang" medzera, preklepy) → None/UNKNOWN; správne "gochujang" už obchádza tento mechanizmus úplne | NOT_A_MIGRATION_CANDIDATE — trigger existuje presne PRE preklepy, správny pravopis sem nikdy nedorazí |
| `tamari` | None/UNKNOWN (žiadne taxonomy pravidlo pre tamari existuje) | CONSTRAINT_BASED_LEGACY / TAXONOMY_GAP (mimo rozsahu — nízky objem) |
| `safe_sauce` | None/UNKNOWN | CONSTRAINT_BASED_LEGACY |
| `rice_seasoning` | rice/plain_rice (stráca "koreniaca zmes" kvalifikátor) | **Zámerne nemigrované** (V2.12.2 near-miss, potvrdené znova) |
| `sushi_condiments` / `tofu_seaweed` | None/UNKNOWN | CONSTRAINT_BASED_LEGACY |

**Záver**: žiadny zo zvyšných 21 kľúčov nemá rovnaký tvar ako pôvodné 4
migrované ("holý produktový názov s vlastnou sebavedomou taxonomy rodinou
priamo z trigger textu"). Všetky sú buď skutočne constraint-based (diétne
obmedzenie, úroveň pikantnosti — jazyk, ktorému taxonomy engine prirodzene
nerozumie), alebo nemajú vôbec taxonomy pokrytie. **Žiadna ďalšia migrácia
nebola vykonaná** — presne podľa dôkazov, nie podľa predpokladu.

## RELATED_PRODUCT_QUERIES — nový mechanizmus, rovnaká otázka

`RELATED_PRODUCT_QUERIES` (`app/main.py`) napája `related_products_for_subject()`
volanú z `detect_related_subject()`. Na rozdiel od `SPECIAL_PRODUCT_QUERIES`
(ktoré malo byť primárne vyhľadávanie), tento mechanizmus je **navrhnutý**
ako "čo súvisí s X" — zámerne bundluje viacero odlišných rodín
(komplementárne produkty), čo je jeho správna funkcia, nie chyba.

Problém nastáva len vtedy, keď **holý, nejednoznačný produktový názov**
(nie skutočná recept/companion otázka) omylom skončí v tomto mechanizme
namiesto priameho vyhľadávania — presne trieda chyby, akú V2.12.2's Bug A
guard (`_query_resolves_to_confident_product_family()`) rieši, KEĎ dopyt
má vlastnú sebavedomú taxonomy rodinu.

Dva konkrétne nálezy tento cyklus:

- `RELATED_PRODUCT_QUERIES["sklenene_rezance"]` = `["sklenene rezance",
  "sojova omacka", "sezamovy olej", "rybacia omacka", "gochujang",
  "shiitake"]` — `"glass noodles"` (anglický holý názov) sa smerovalo sem,
  pretože nemalo vlastnú taxonomy rodinu (`family=None`), takže Bug A guard
  nemal čo zachytiť.
- `RELATED_PRODUCT_QUERIES["tamarind"]` = podobný bundle (rybacia omáčka,
  kokosové mlieko, trstinový cukor + tamarindová pasta).

**Oprava nebola v `RELATED_PRODUCT_QUERIES` samotnom** — namiesto toho
V2.12.3's nové taxonomy pravidlá (`glass_noodles`, `tamarind_pasta`, +
anglické aliasy) dali `"glass noodles"`/`"sklenene rezance"`/`"udon
rezance"`/`"chilli paste"`/`"coconut oil"`/`"fish sauce"` **vlastnú
sebavedomú rodinu**, čím V2.12.2's existujúci Bug A guard **automaticky**
tieto dopyty presmeroval na priame vyhľadávanie (`intent=product_search`)
namiesto `related_products` bundlu — overené priamo cez `chat()` end-to-end
(pozri `docs/query-semantics.md`, sekcia "Interakcia s V2.12.2 Bug A
guardom"). Žiadna zmena kódu v `RELATED_PRODUCT_QUERIES` nebola potrebná
ani vykonaná.

Holý `"tamarind"` (bez "pasta"/"paste") **zámerne zostáva** na
`related_products` ceste — katalóg má reálne odlišné tamarindové produkty
(pasta, koncentrát, sušené ovocie, nápoj) a jedno nejednoznačné slovo sa
nedá bezpečne priradiť k jednej rodine. Toto je správne správanie, nie
zvyšková chyba.

## ARTICLE_PRODUCT_QUERIES / ALREADY_HAVE_COMPLEMENT_QUERIES / REPLACEMENT_PRODUCT_QUERIES

Rovnaká štruktúra (query-bundle dicts), rovnaká funkcia ako
`RELATED_PRODUCT_QUERIES` — zámerne bundlujú súvisiace, nie identické
produkty (magazine-článok kontext, "čo mi chýba k X", "namiesto Y"). Žiaden
z týchto troch nebol v tomto cykle hlásený s konkrétnym dôkazom kontaminácie
(na rozdiel od `sklenene_rezance`/`tamarind`) — audit ostáva otvorený pre
budúci cyklus, ak sa objaví konkrétny dôkaz, rovnakým protokolom ako tu.

## Zhrnutie klasifikácie (V2.12.3 Section 13/14 požiadavka)

- **EQUIVALENT_ALIAS / SAFE_PREFIX_NORMALIZATION**: väčšina `PHRASE_SYNONYMS`
  (52/52), gramatické pádové varianty (`bezlepk*`, `cajov*`).
- **SUBTYPE_EXPANSION** (rovnaká top-level rodina, rôzny subtype): `rybac`/
  `rybi`, `mliek`/`mliec`, `oil`, `curry`, `seaweed`, `wine`.
- **UNSAFE_RELATED_EXPANSION** (naprieč rôznymi rodinami, potvrdené naživo):
  `kokos`/`coconut`, `ryz`/`rice`, `sojov`/`soy`, `omack`/`sauce` (nízke
  praktické riziko — doslovné generické slovo), `noodles`/`rezance`.
  **Adresované cez Bug C guard** (`app/main.py::_exclude_taxonomy_family_mismatches`),
  nie zmenou `data/synonyms.json` — synonymá samotné zostávajú nezmenené,
  pretože sú lexikálne správne (naozaj rovnaký koreň), problém je v
  legacy scoreri, ktorý ich nevie odlíšiť sémanticky.
- **DEAD_OR_UNUSED**: `kredit`, `sirach`, `kimci`/`kimchee`, `gochuang`/
  `gochud`/`gocud`/`gocuj` — nulové reálne catalog hity, bez rizika aj bez
  efektu.
- **SPECIAL_PRODUCT_QUERIES / RELATED_PRODUCT_QUERIES**: klasifikácia podľa
  tabuľky vyššie — 4/25 migrované (V2.12.2), zvyšných 21 potvrdené ako
  CONSTRAINT_BASED_LEGACY alebo TAXONOMY_GAP mimo rozsahu.
