# V2.15d.3 — Event Execution-Context Isolation, Synthetic Signal Hygiene & Analytics Contamination Closure

Dátum: 2026-08-24.

## 1. Mandát

Uzavrieť medzeru objavenú počas V2.15d.2 produkčnej verifikácie: 2
syntetické `/events` záznamy pristáli v produkčnom `events.jsonl`,
nerozlíšiteľné od reálnej zákazníckej telemetrie. **Nie learning
sprint** — `AUTO_PROMOTION` zostáva `False`.

## 2. Baseline

HEAD pred touto sprintou: `9563f45` (V2.15d.2). **BASELINE_CONFIRMED**.

## 3. Root cause (nezávisle overené, nie prevzaté)

`/events` (`app/main.py`, `track_event()`) nemal **ŽIADNY** execution-
context mechanizmus — žiadny `X-Execution-Context`/`X-Admin-Token`
header, žiadnu integráciu s `app.execution_context`/`app.admin_auth`.
Jediný guard bol IP-kľúčovaný rate limiter (`enforce_event_rate_limit`),
ktorý neautentizuje nič. Všetci 3 downstream čitatelia
(`app.behavioral` — CTR ranking boost, `app.fbt` — frequently-bought-
together, `app.learning_events`→`app.learning_cycle` — riadené
auto-learning) dôverovali obsahu `events.jsonl` bez akéhokoľvek
overenia pôvodu.

## 4. Historické 2 syntetické eventy — klasifikácia

**`HISTORICAL_SYNTHETIC_EVENTS_LEFT_AS_DOCUMENTED_ARTIFACT`** — žiadny
deštruktívny prepis JSONL (mimo rozsahu). Dôkazmi podložené zistenie:
tieto 2 záznamy (`event_type="add_to_cart_attempt"/"add_to_cart_confirmed"`,
`product_sku="SMOKE-TEST-SKU"`) sú UŽ TERAZ štrukturálne neviditeľné pre
všetkých 3 čitateľov — `app.behavioral`/`app.fbt`/`app.learning_events`
rozpoznávajú výhradne literál `"add_to_cart"` (legacy), nie tieto 2
nové V2.15d.2 event_type reťazce. Overené testom
(`TestHistoricalSyntheticArtifact`).

## 5. Execution-context trust model (reused, not reinvented)

`/events` teraz prijíma rovnaké `X-Execution-Context`/`X-Admin-Token`
headery ako `/chat`, resolvované **server-side** cez
`app.admin_auth.resolve_token_scope()` — presne tá istá funkcia, ten
istý OPERATIONS/PROMOTION scope-check. Klient NEMÔŽE tvrdiť ADMIN_TEST
len odoslaním hlavičky — bez platného, dostatočne-scope-ovaného tokenu
sa vždy vráti CUSTOMER (fail-closed). Overené testom aj priamo
(garbage token, READ-scope token — obe zlyhajú closed na CUSTOMER).

## 6. Per-context matica

| Context | accepted? | durably_logged? | learning_eligible | auth_required? | production_safe_for_smoke? |
|---|---|---|---|---|---|
| CUSTOMER | áno (default) | áno | `True` | nie | — (je to reálna prevádzka) |
| ADMIN_TEST | áno | áno | `False` | áno (OPERATIONS/PROMOTION) | **áno** |
| EVALUATION | interný len | **nie** | n/a | n/a | n/a |
| SHADOW | interný len | **nie** | n/a | n/a | n/a |
| LEARNING | interný len | **nie** | n/a | n/a | n/a |
| UNKNOWN/malformed | áno | áno (ako CUSTOMER) | `True` | nie | nie |

## 7. Per-event matica (nezmenené touto sprintou, pre úplnosť)

| Event | correlation | authoritative? | learning-relevantné | execution-context chránené |
|---|---|---|---|---|
| click | interaction_id/decision_id | n/a | nie (observed only) | áno (nová) |
| add_to_cart_attempt | áno | nie | nie | áno (nová) |
| add_to_cart (legacy) | áno | nie (believed-success) | nie | áno (nová) |
| add_to_cart_confirmed | áno | **áno** (V2.15d.2 fix) | nie (observability only) | áno (nová) |
| impression | čiastočné | n/a | nie | áno (nová) |
| purchase | **NOT_AVAILABLE** | — | — | — |

## 8. Downstream reader fix

`app.behavioral._read_events()`, `app.fbt._read_events()`,
`app.learning_events._read_raw_events()` teraz preskakujú akýkoľvek
záznam s `execution_context not in (None, "CUSTOMER")`. `None`/chýbajúce
pole (každý pred-V2.15d.3 záznam) sa traktuje ako CUSTOMER — `/events`
predtým nemal žiadnu non-customer cestu, takže historické dáta sú
dôveryhodné.

## 9. STORE_LOCATION canonical data closure (bounded subtask)

Autoritatívne dáta od product ownera:
- Adresa: `Stará Vajnorská 3308/19, 831 04 Bratislava`
- Maps: `https://maps.app.goo.gl/3tFJ4P6w2pj88xAP8`

**Jediný zdroj pravdy zostáva** `data/knowledge.json` (FAQ `Odpoveď`
text) — žiadny nový business-config modul (overené auditom, žiadny
neexistuje). Maps link NIE JE zapečený do Odpoveď textu — bola by
duplicita pri V2.15c follow-up recall. Namiesto toho jediná funkcia
(`_build_maps_link_from_faq_answer()`) rozhoduje o linku na OBOCH
miestach (prvá odpoveď aj follow-up), volaná identicky. `_ADDRESS_PATTERN`
rozšírený o `(?:/\d+)?` pre formát "3308/19". Kanonický Foodland URL má
prednosť pred generovaným search URL len keď extrahovaná adresa presne
zodpovedá kanonickej adrese — generovaný fallback zostáva pre INÉ
adresy.

Testy: 21 existujúcich V2.15c testov (aktualizované na nové dáta) + 11
nových SL-A..SL-H testov, všetky PASSED.

## 10. Testy (táto sprinta)

`tests/test_event_execution_context_v2_15d_3.py` — 25 testov (customer
default, trusted admin, spoofing protection x2, malformed/missing
context, EVALUATION/SHADOW/LEARNING suppression, backward compat,
downstream reader exclusion x4, historical artifact klasifikácia x3,
telemetry failure isolation, AUTO_PROMOTION, rt0004/10/11/13).
`tests/test_store_location_canonical_v2_15d_3.py` — 11 testov.

## 11. Regresia

Pozri finálny report.

## 12. Contamination closure kritériá (Section 47)

Všetkých 10 kritérií splnené: CUSTOMER nezmenené, spoofing zablokovaný,
non-customer nikdy learning-eligible, execution context nepresahuje
cez requesty (žiadny ContextVar použitý — parameter je explicitne
predaný, žiadny globálny stav), telemetry failure izolovaná,
correlation IDs nedotknuté, V2.15d.2 sémantiky nedotknuté,
AUTO_PROMOTION nezmenené, live verifikácia nekontaminuje dataset (viď
finálny report — použitý ADMIN_TEST kanál).

## 13. V2.15e

Rozhodnutie vo finálnom reporte.
