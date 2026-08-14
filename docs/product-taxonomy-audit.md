# Foodland katalógová taxonómia — prvý discovery audit (V2 Taxonomy Phase 1-11)

Tento dokument je vygenerovaný z **aktuálneho** stavu `data/products.json` a
`data/knowledge.json` skriptom `scripts/taxonomy_audit.py`
(`python3 scripts/taxonomy_audit.py --json <out>.json`). Žiadne číslo tu
nie je ručne odhadnuté — všetko je prepočítané zo zdrojových dát pri
každom behu. Re-generuj po každom refreshi feedu.

Dátum tohto behu: 2026-08-14. Zdroj: `data/products.json` (2 140 produktov
v čase tohto behu — **nepovažuj toto číslo za fixné**, vždy over aktuálny
počet).

## Fáza 1 — Profil katalógu (reálne čísla)

```
total_products               = 2140
unique_brands                = 368
unique_categories_top_level  = 127
unique_categories_all_levels = 166
```

Top 10 značiek podľa počtu produktov: EMRO AZIATICA (137), EDO JAPAN (117),
HEM (79), LOBO (51), COCK BRAND (48), LIMPEXT (45), TRS (40), Lee Kum Kee
(37), ASIA EXPRESS (35), Thai Agri Foods (35).

Top-level kategórie sú z veľkej časti **prierezové atribútové značky**, nie
navigačné oddelenia — "Vegánske potraviny" (206), "Zdravé potraviny" (192),
"Vegetariánske potraviny" (85), "Super potraviny" (62), "Sušené produkty"
(84) dominujú počtom, ale nehovoria nič o produktovej identite. Skutočné
navigačné kategórie (Misy a misky 97, Vonné tyčinky 89, Nealkoholické
nápoje 70, Zmes korenia a ochucovadlá 60, Kórejské 57, Sójové omáčky 31,
Potreby na výrobu suši 25...) sú užitočnejšie pre taxonómiu produktovej
rodiny. Toto potvrdzuje rozhodnutie zo Sprintu V2.1.6 (`category_discovery`)
odfiltrovať tieto prierezové značky z odpovede o sortimente.

Balenia v názvoch: g (1151×), ml (434×), cm (298× — hlavne kuchynský riad),
kg (90×), ks (46×), l (20×), mm (17×).

## Fáza 2-4 — Kandidátne produktové rodiny a cross-category kolízie

Skript testoval hypotézy koreňov (`ryz`, `soj`, `kokos`, `caj`, `susi`/
`sushi`, `mlieko`...) proti reálnym title tokenom. Najvýznamnejšia,
opakovane historicky problémová kolízia (Sprint Z.6 v roadmape, viacero
predošlých produkčných chýb) je koreň **`ryz`** (ryža):

| token (normalizovaný) | počet produktov | reálny príklad |
|---|---|---|
| `ryza` | 69 | Basmati ryža – LAILA – 1kg |
| `ryzove` | 63 | Červené ryžové rezance SAVIVA 400g |
| `ryzovy` | 23 | Ryžový ocot CHINKIANG GOLD PLUM 550ml |
| `ryze` | 9 | Múka z lepkavej ryže COCK BRAND 400g |
| `ryzu` | 7 | Elektrický hrniec na ryžu REMO |
| `ryzova` | 3 | Ryžová múka COCK BRAND 400g |
| `ryzovar` | 2 | Komerčný ryžovar CUCKOO |

Manuálnou inšpekciou (`python3 scripts/taxonomy_audit.py --family ryz`)
tento jeden lingvistický koreň reálne pokrýva **najmenej 7 odlišných
produktových podrodín**:

1. samotná ryža (zrno) — basmati, jazmínová, lepkavá/glutinous, čierna...
2. ryžové rezance (rice noodles) — samostatná kategória potravín
3. ryžový ocot (rice vinegar) — koreninová/ocotová kategória
4. ryžová múka (rice flour) — mučná/pekárenská kategória
5. ryžový papier (rice paper) — obaľovacia/wrap kategória
6. ryžovar / hrniec na ryžu (rice cooker) — **má vlastnú reálnu katalógovú
   kategóriu `Ryžovary`**, teda ide o overenú, nie len odvodenú rodinu
7. ryžový nápoj (rice drink) — nápojová kategória

Toto potvrdzuje presne triedu chyby zdokumentovanú v Sprinte Z.6
("workflow s ryžou/ryžovarom") — zdieľaný jazykový koreň nesmie
znamenať rovnakú produktovú rodinu.

Ďalšie kandidátne rodiny s reálnym katalógovým dôkazom (nie vyčerpávajúci
zoznam, len najsilnejšie signály z tohto behu): `rezanc`/`nudl` (rezance,
174 produktov spolu s pluralizovanými tvarmi), `soj` (sójová omáčka, 85
produktov), `kokos` (kokosové produkty, 68 produktov), `caj` (čaj, 100
produktov vrátane príslušenstva), `susi`/`sushi` (78 produktov).

## Fáza 9 — Recepty a IntentMapping ako sémantický dôkaz

`data/knowledge.json["sections"]["IntentMapping"]` (318 záznamov) obsahuje
**overenú kurátorovanú** taxonómiu zákazníckych zámerov, nezávislú od tohto
auditu. Relevantné typy zámerov s reálnym počtom výskytov:

```
6  Omáčky / výber produktu
4  Ryža / výber produktu
4  Rezance / výber produktu
3  Kari / výber produktu
2  Kokosové mlieko / výber produktu
2  Pálivosť / preference
```

Konkrétne overené záznamy pre "Ryža / výber produktu" (priamo použiteľné
ako grounded obsah, nie vymyslené):

```
"Akú ryžu použiť na sushi?"
  → Sushi ryža — "Preferovať sushi ryžu a krátkozrnnú ryžu."
"Akú ryžu použiť ku kari?"
  → Ryža ku kari — "Odporučiť jazmínovú alebo basmati podľa kuchyne."
"Aký je rozdiel medzi jazmínovou a basmati ryžou?"
  → Porovnanie ryže — "Porovnať arómu, zrnitosť, kuchyňu a použitie."
"Potrebujem lepivú ryžu na mango sticky rice."
  → Lepkavá ryža — "Odporučiť glutinous/sticky rice."
```

Toto je priamy, overený zdroj obsahu pre `product_comparison` intent
(porovnanie jazmínová vs. basmati) aj pre `product_advice` (ryža podľa
použitia) — presne tie dva kanonické zámery, ktoré v legacy kóde nemajú
detektor (zdokumentované v `docs/advisor-v2-architecture.md`, V2.4).

Podobne "Rezance / výber produktu" potvrdzuje, že rezance sa delia podľa
**použitia** (pad thai → ploché ryžové rezance, ramen → ramen/instantné,
japchae → sklenené/batátové), nie len podľa suroviny.

## Fáza 5-6 — Kanonická taxonómia (návrh): `rice` (ryža)

Vybraná ako JEDINÁ rodina pre prvú implementáciu (Fáza 26, krok 11) —
najsilnejší kombinovaný dôkaz: vysoký počet produktov (69+ priamo, 173+
naprieč podrodinami), opakovaná história produkčných chýb (Sprint Z.6),
overená IntentMapping podpora, a jasná existujúca čiastočná legacy
implementácia (`SPECIAL_PRODUCT_QUERIES` už má `plain_rice`, `sushi_rice`,
`rice_vinegar`, `rice_side`, `rice_cooker`, `rice_seasoning`) na ktorú sa
dá nadviazať, nie ju nahradiť.

```
canonical_family_id: rice
display_name: Ryža
aliases: ryza, ryze, ryzu, ryzou, rice, gao, com (VI základ)

subfamilies:
  plain_rice        confidence=HIGH   evidence=69 products, IntentMapping "Ryža/výber produktu"
  sushi_rice         confidence=HIGH   evidence=existing SPECIAL_PRODUCT_QUERIES + IntentMapping "sushi ryža"
  rice_noodles        confidence=HIGH   evidence=63 products distinct category (rezance), IntentMapping "Rezance/výber produktu"
  rice_vinegar         confidence=HIGH   evidence=23 products, distinct category "Ocot"
  rice_flour             confidence=HIGH   evidence=distinct category "Múka, škrob & ryžový papier"
  rice_paper               confidence=HIGH   evidence=distinct category "Obaľovacia zmes, tempura & panko"
  rice_cooker                confidence=HIGH   evidence=distinct real catalog category "Ryžovary"
  rice_drink                   confidence=MEDIUM evidence=2 products only ("ryžový nápoj")

P1 (identity) attributes: subfamily (which of the above), variety (basmati/
  jazmínová/lepkavá-glutinous/hnedá-brown/čierna-black/riceberry)
P2 (selection/use-case) attributes: cuisine (thajska/japonska/vietnamska/
  korejska), use_case (sushi/kari/dezert-sticky-rice/bežné varenie)
P3 (preference/commercial) attributes: brand, package_size

collision_risks: rice_noodles, rice_vinegar, rice_flour, rice_paper,
  rice_cooker, rice_drink all share the "ryz*" linguistic root with
  plain_rice and with each other - MUST be disambiguated by compound
  phrase, not root stem alone (already handled for the 4 subjects that
  exist in SPECIAL_PRODUCT_QUERIES; rice_flour, rice_paper, rice_drink
  are NOT yet in legacy special-product routing).

related_recipe_roles: base ingredient (sushi, kari, plov), seasoning
  (rice_vinegar in sushi), wrapping (rice_paper in spring rolls)
```

## Fáza 11 — Confidence pravidlo pre tento audit

Iba `plain_rice`, `sushi_rice`, `rice_noodles`, `rice_vinegar`,
`rice_flour`, `rice_paper`, `rice_cooker` majú HIGH confidence (jasný
katalógový/kategóriový dôkaz). `rice_drink` má MEDIUM (len 2 produkty) —
podľa Fázy 11 pravidla MEDIUM smie ovplyvniť ranking, nesmie tvoriť tvrdé
retrieval obmedzenie. V tejto prvej iterácii sa `rice_drink` nezapája do
klasifikátora vôbec (žiadne customer-facing správanie sa nemení pre
žiadnu podrodinu v tomto behu — pozri Fáza 16 nižšie).

## Fáza 12 — Bez ručného mapovania 2000+ SKU

`app/taxonomy.py` (pridané touto iteráciou) neobsahuje žiadny zoznam
`product_id`. Klasifikácia beží nad `title`/`product_type` poľami
existujúcich produktov pomocou malej, opakovane použiteľnej sady
frázových pravidiel na rodinu. Nové produkty pribudnuté do feedu sa
klasifikujú automaticky bez zmeny kódu, pokiaľ zodpovedajú existujúcim
frázovým vzorom; produkty mimo tejto rodiny jednoducho nedostanú
klasifikáciu (žiadny hard-coded SKU zoznam).

## Fáza 16 — Rollout stage tohto behu

**Stage A (shadow/observation mode) — implementované touto iteráciou.**
`app/taxonomy.py` poskytuje `classify_rice_query()`, ktorá sa v `/chat`
volá **len na účely analytics logovania** (rovnaký, už zavedený a
bezpečný vzor ako `app/intent.py` `CustomerIntent` v Sprinte V2.1) —
NEMENÍ žiadne existujúce routovacie rozhodnutie, produkty, ani text
odpovede. Skutočné nahradenie legacy `SPECIAL_PRODUCT_QUERIES` rice
logiky (Stage B) je zámerne mimo rozsahu tohto behu — vyžaduje najprv
overenie zhody cez produkčné dáta (blokované `LIVE_VERIFICATION_BLOCKED_BY_EXECUTION_ENVIRONMENT`
v tomto vykonávacom prostredí).

## Ako znovu spustiť tento audit

```bash
python3 scripts/taxonomy_audit.py                        # plný výpis
python3 scripts/taxonomy_audit.py --family ryz            # detail jednej rodiny
python3 scripts/taxonomy_audit.py --json audit_raw.json   # surové dáta na ďalšie spracovanie
```

Skript nemá žiadne hardcoded počty produktov ani kategórií — všetko
prepočíta nanovo z `data/products.json` a `data/knowledge.json` pri
každom behu.
