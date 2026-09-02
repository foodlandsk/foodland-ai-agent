# Customer QA Analyzer & Evidence Layer (V2.17.2)

Dátum: 2026-09-02. Baseline commit: `76dce8e5ef70fc525aa2b2f29f5c9007576871cd`.

## 1. Účel

Deterministická, evidence-based QA analytická vrstva nad V2.17.1
sanitizovaným customer audit streamom. Pomáha operátorovi zistiť, ktoré
reálne zákaznícke konverzácie vykazujú ŠTRUKTURÁLNY dôkaz možného
problému, na ktorej architektonickej vrstve pravdepodobne patrí, a s
akým presným dôkazom.

## 2. Čo toto NIE JE

`OBSERVATION → ANALYSIS → EVIDENCE → HUMAN INVESTIGATION`, nikdy
`OBSERVATION → AUTOMATIC LABEL → LEARNING → RANKING CHANGE → DEPLOY`.
Žiadne pravidlo nikdy nespúšťa znova intent/search/ranking/cross-sell/
LLM, nikdy nezapisuje do `customer_audit.jsonl` (ten stream je
nemenný vstup), a `automatic_production_change` je vždy `false`.

## 3. Vzťah k V2.17.1

Konzumuje výhradne `app.customer_audit.read_audit_turns()` — žiadny
nový capture systém, žiadne obchádzanie privacy kontrol, žiadny pokus o
reverznutie `conversation_hash`.

## 4. Zvolená architektúra: ON-READ analýza

`GET /admin/qa/findings` číta sanitizované audit ťahy ČERSTVO pri
každom requeste a spúšťa deterministické pravidlá in-memory — žiadny
samostatný `customer_qa_findings.jsonl` (Section 18/22 zadania,
možnosť B) nebol vytvorený. Dôvod: ON-READ triviálne spĺňa KAŽDÚ
guard naraz — nulové riziko duplicitných nálezov (nič sa nikdy
neukladá), nulový dopad na `/chat` latenciu (analýza beží len keď
admin zavolá endpoint), nulové nové runtime úložisko, plná
reprodukovateľnosť.

## 5. Prečo je mimo /chat critical path

`capture_customer_turn()` (V2.17.1) sa volá v `_chat_internal()`; QA
analýza sa NIKDY nevolá odtiaľ — beží výhradne v `/admin/qa/*`
handleroch, teda len keď admin explicitne zavolá GET endpoint.
Overené testom (`test_qa_findings_endpoint_does_not_touch_ranking_module_state`).

## 6. Implementovaná QA taxonómia

`UNDERSTAND, RETRIEVE, RANK, COMPOSE, GROUND, PRESENT, CROSS_SELL,
DATA, SAFETY_TRUST` — všetkých 9 je deklarovaných ako platné hodnoty.
**Reálne pravidlá v V2.17.1 existujú len pre `CROSS_SELL`, `PRESENT`,
`COMPOSE` a `SAFETY_TRUST`** — `UNDERSTAND`/`RETRIEVE`/`RANK`/`GROUND`/
`DATA` zámerne NEMAJÚ pravidlo (pozri Section 20 "false-negative
philosophy" nižšie).

## 7. PASS sémantika

"Žiadne nakonfigurované pravidlo nenašlo problém" — NIE "odpoveď je
objektívne dokonalá". Overené testom.

## 8. FINDING sémantika

Aspoň jeden nález s dôkazom existuje. Každý nález má `rule_id`,
`evidence`, `classification`, `severity`, `confidence`,
`recommended_action`, `automatic_production_change=false`.

## 9. UNCERTAIN sémantika

Prvotriedny, platný výsledok — nie núdzový prípad. Nastáva, keď ťah
chýba kľúčové polia (napr. staršia schéma, Section 31 — historické
záznamy sa spracúvajú defenzívne, nikdy sa neopravujú deštruktívne)
alebo nemá dostatok kontextu na zmysluplné vyhodnotenie.

## 10. Severity model

`LOW/MEDIUM/HIGH/CRITICAL`. Príklad: `QA_STOCK_001` (Skladom wording) =
MEDIUM (zavádzajúce, nie bezpečnostný únik); `QA_TRUST_001` (prompt-
leak marker) = CRITICAL; `QA_TRUST_002` (PII prežilo redakciu) = HIGH.

## 11. Confidence model

**HIGH/MEDIUM/LOW**, nikdy fingovaná pravdepodobnosť (Section 9
zadania to explicitne povoľuje ako čestnejšiu alternatívu). Čisto
štrukturálne/boolean kontroly (napr. `QA_STRUCT_001` id-prekrytie) =
HIGH (jednoznačný fakt). Textovo-vzorové kontroly (napr. "Skladom"
wording, "nenašla som" fráza) = MEDIUM (možnosť gramatického
kontextu, ktorý regex nezachytí presne).

## 12. Implementované deterministické pravidlá

| rule_id | classification | severity | popis |
|---|---|---|---|
| QA_STRUCT_001 | CROSS_SELL | MEDIUM | produkt id v `products` aj `cross_sell` súčasne |
| QA_STRUCT_002 | CROSS_SELL | LOW | `cross_sell_eligible=True`, ale prázdna skupina |
| QA_STRUCT_003 | PRESENT | LOW | `has_more=True` odporuje `displayed_count`/`matching_total` |
| QA_TRUST_001 | SAFETY_TRUST | CRITICAL | V2.16e prompt-leak signatúra v odpovedi |
| QA_TRUST_002 | SAFETY_TRUST | HIGH | email vzor prežil V2.17.1 redakciu |
| QA_STOCK_001 | SAFETY_TRUST | MEDIUM | "Skladom" wording v odpovedi |
| QA_COMPOSE_001 | COMPOSE | MEDIUM | "nenašla som" fráza, ale `products` neprázdne |
| QA_COMPOSE_002/003 | COMPOSE | LOW | zmienka o alternatívach/cross-sell, ale skupina prázdna |

## 13. Evidence model

`{question, answer_excerpt (≤300 znakov), intent, workflow_id, groups:
{products, cross_sell}}`. Nikdy surový identifikátor, nikdy secrets,
nikdy systémový prompt.

## 14. Cross-sell guard: VÝSLEDOK SPLNENÝ

`QA_STRUCT_001` deteguje presne to porušenie, ktorému V2.6/V2.17
zabraňujú (`exclude_ids` dedup). Žiadne pravidlo neklasifikuje
cross-sell produkt ako zlú primárnu zhodu (overené testom).

## 15. Stock guard: VÝSLEDOK SPLNENÝ

"Skladom" deteguje, "Dostupné na Foodland.sk" NIKDY nedeteguje
(overené testom `test_dostupne_na_foodland_sk_is_not_flagged`). Surové
`availability="in_stock"` samo osebe nikdy nestačí na pozitívny nález.

## 16. Ranking/order guard: VÝSLEDOK SPLNENÝ

Žiadne pravidlo nezávisí od poradia produktov — `test_qa_does_not_
require_arbitrary_exact_product_order` overuje PASS pre obe permutácie
tej istej množiny. `RANK` klasifikácia sa v tejto sprinte NIKDY
nepoužíva.

## 17. Privacy výsledok: VÝSLEDOK SPLNENÝ

QA nikdy nevyžaduje surový `session_id`/`client_id`/IP, nikdy sa
nepokúša reverznúť `conversation_hash`.

## 18. Customer-stream integrity výsledok: VÝSLEDOK SPLNENÝ

Overené živo aj testom: `ADMIN_TEST` volania cez
`advisor_engine.run(..., admin_test_context())` NEVYTVÁRAJÚ
`customer_audit.jsonl` záznam.

## 19. ADMIN_TEST overenie

Produkčná verifikácia tejto sprinty NEPOUŽÍVA priame `/chat` volania —
len `GET /admin/qa/*` (read-only, nedotýka sa `/chat` vôbec) plus
`/health`. Nebola potrebná žiadna syntetická `/chat` konverzácia.

## 20. False-positive/false-negative filozofia

**False-negative philosophy**: V2.17.2 zámerne NEIMPLEMENTUJE
`UNDERSTAND`/`RETRIEVE`/`RANK`/`GROUND`/`DATA` pravidlá — sanitizovaný
audit záznam sám osebe nedokazuje, čo MALO byť vrátené (chýba ground
truth). Vymyslieť takéto pravidlo z nedostatočného dôkazu by porušilo
vlastný princíp projektu "chýbajúci dôkaz = NEZNÁME, nikdy NIE".
Radšej menej pravidiel s pevným dôkazom než veľa špekulatívnych.

**False-positive philosophy**: každé pravidlo je striktne štruktúrne
alebo known-pattern based — nikdy subjektívny úsudok o kvalite
odporúčania. `confidence=MEDIUM` na textovo-vzorových pravidlách
priznáva reálne riziko falošného poplachu namiesto predstierania
istoty.

## 21. Prečo click != kvalita, prečo nález != tréningový label

Tento modul VÔBEC nečíta behaviorálne dáta (click/cart/feedback) —
žiadne pravidlo ich používa ako vstup. Nález je vždy o ŠTRUKTÚRE
alebo TEXTE už-dokončenej odpovede, nikdy o tom, či zákazník klikol.
Nálezy sa nikde nezapisujú do learning/ranking pipeline — sú to len
JSON objekty vrátené z READ endpointu pre ľudské preskúmanie.

## 22. Storage model

Žiadny. ON-READ, nič sa nepersistuje (Section 4).

## 23. Deduplication stratégia

`qa_id = sha256(f"{identity}:{rule_id}:{rule_version}")[:24]` —
deterministický, stabilný naprieč opakovanými GET requestmi (keďže sa
nič neukladá, duplicity fyzicky nemôžu vzniknúť).

## 24. Endpointy

- `GET /admin/qa/status` — agregované počty PASS/FINDING/UNCERTAIN.
- `GET /admin/qa/findings` — plochý zoznam nálezov (`days`, `limit`,
  `classification`, `severity`, `conversation_hash`, `q`).
- `GET /admin/qa/conversations/{conversation_hash}` — plný QA výsledok
  pre každý ťah jednej konverzácie.

## 25. Autentifikácia

`SCOPE_READ` cez existujúci `app.admin_auth.require_admin_scope()`.

## 26. Testy

`tests/test_customer_qa_v2_17_2.py` — 57 testov pokrývajúcich všetkých
52 požadovaných prípadov.

## 27. Výkon

Nulový dopad na `/chat` latenciu (mimo critical path). Bounded
(`days`≤90, `limit`≤500).

## 28. Známe obmedzenia

- `UNDERSTAND`/`RETRIEVE`/`RANK`/`GROUND`/`DATA` nemajú zatiaľ žiadne
  pravidlo (zámerne, pozri Section 20).
- Žiadna historická trend analýza (ON-READ, nič sa neukladá).
- Admin Dashboard UI integrácia mimo rozsahu.

## 29. Budúca V2.17.3 hranica

Budúca reprodukčná vrstva (`finding → reproduction case → regression
candidate`) vyžaduje samostatný explicitný mandát — V2.17.2 NEVYTVÁRA
žiadny automatický commit regresných testov z reálnych konverzácií.
