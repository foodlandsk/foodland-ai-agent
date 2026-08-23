# V2.15d.1 — Frontend Widget Test Tooling & Instrumentation Safety Foundation

Dátum: 2026-08-23.

## 1. Mandát a hranica

Cieľom V2.15d.1 je vytvoriť MINIMÁLNU spoľahlivú JavaScript validačnú
infraštruktúru potrebnú na bezpečnú budúcu úpravu `app/widget.js`
(V2.15d.2). **Táto sprinta SAMA neimplementuje žiadnu novú produkčnú
telemetriu** — `app/widget.js` zostáva byte-identický. Žiadna zmena
zákazníckeho správania, žiadny nový sieťový volanie, žiadny nový
telemetrický event.

## 2. Baseline

HEAD pred touto sprintou: `f667717` (V2.15d). pytest 1664/1664, V2.10
35/39, canary 10/10, `AUTO_PROMOTION_ENABLED=False`.

## 3. Tooling audit

**Node.js/npm/npx**: nezávisle overené — **nedostupné nikde lokálne**
(`node --version`, `npm --version`, `npx --version` zlyhávajú; žiadny
`node.exe` v `Program Files`/`Program Files (x86)`, `where.exe node`
nič nenašiel). **Žiadny `package.json`/lockfile v repozitári.**

Kľúčový rozdiel oproti V2.15d: **GitHub Actions runner (ubuntu-latest)
je nezávislé prostredie** od tohto lokálneho vývojového stroja —
`actions/setup-node@v4` môže nainštalovať Node.js v CI bez ohľadu na
lokálnu absenciu. Toto som si v V2.15d nedostatočne odlíšil (moje
vtedajšie zistenie "no Node.js available" bolo pravdivé len pre lokálne
prostredie, nie pre CI) — táto sprinta to naprávuje.

## 4. Architektúra `app/widget.js`

2041 riadkov, jeden top-level IIFE (`(function () { ... })()`), CommonJS-
kompatibilný (žiadny `import`/`export`), plain script pre `<script src>`
injektáž do hostiteľskej stránky. Súbor začína UTF-8 BOM (`\xef\xbb\xbf`)
— `node --check` a Node-ov module loader ho automaticky odstraňujú,
`fs.readFileSync(...,'utf8')` NEODSTRAŇUJE, čo som musel explicitne
ošetriť v `vm.Script` teste.

Sieťové volania: `fetch()` na `${apiBaseUrl}/events`,
`/suggested-questions`, `/search/autocomplete`, `/products/suggest`,
`/chat` (5 endpointov), plus jeden literálny fetch na
`https://www.foodland.sk/nakupny-kosik/` (cart-state readback po
add-to-cart). Súbor obsahuje AJ desiatky ďalších `https://www.foodland.sk/...`
reťazcov, ktoré NIE SÚ sieťové volania — statický demo/fallback katalóg
produktov (aktívny len keď `demoMode`/`isDemoPage`) a default fallback
linky pre recepty/články/produkty bez vlastného odkazu.

## 5. Product click / add-to-cart charakteristika (znovu-overené)

- **Product click**: `article.fl-ai-product` klik deleguje na cart
  tlačidlo; `a.fl-ai-product-link` fireuje `click` telemetriu a
  navigáciu cez natívny `href`.
- **Add-to-cart**: `submitRealAddToCartForm()` vytvorí skrytý iframe na
  reálnej produktovej stránke, počká na `load`, nájde a klikne skutočné
  `#addtocart button[type=submit]` v iframe DOM-e — simuluje reálneho
  návštevníka, nie priame API volanie.
- **Potvrdenie**: interceptuje `XMLHttpRequest.prototype.open` v iframe
  a čaká na `trigger=addToCart` AJAX odpoveď s `data.success===true`.
  Ak interceptovanie zlyhá, degraduje na pevný 2.5s timer (odhad, nie
  skutočné potvrdenie) — táto nuance zostáva zdokumentovaná, nezmenená.
- **Backend ID dostupnosť**: `interaction_id` a `*_decision_id` (V2.15b/d)
  SÚ vo `/chat` odpovedi, ale `app/widget.js` ich dnes vôbec nečíta ani
  nepoužíva — **`BACKEND_EXISTS_NOT_EXPOSED`** (V2.15d.1 to
  nezavádza, iba dokumentuje).

## 6. GATE rozhodnutie: TOOLING_GATE_B

- Node.js (v CI cez `actions/setup-node@v4`, pinovaná verzia 20 LTS)
- `node --check app/widget.js` — deterministický syntax gate
- `node --test tests/js/` — vstavaný Node test runner, **0 externých
  npm závislostí, žiadny `package.json`**

`node --test` objaví `tests/js/*.test.mjs` priamo bez akejkoľvek
konfigurácie (Node 18+). Voľba `package.json` bola vyhodnotená ako
zbytočná — nepridáva žiadnu determinizmus navyše pre tento rozsah.

## 7. Implementované testy (`tests/js/widget.test.mjs`)

1. `app/widget.js` existuje, nie je orezaný (>10kB).
2. `node --check` prechádza na reálnom súbore.
3. `node --check` naozaj ODMIETNE zámerne rozbitý fixture (dôkaz, že
   gate funguje, nie len že príkaz existuje).
4. Nezávislý parse cez `node:vm` (`vm.Script`) — druhý, nezávislý
   parser dosahuje rovnaký záver ako `--check`.
5. Statická kontrola: presná, zamrazená množina `${apiBaseUrl}/...`
   endpointov (Section 47 "no behavior change" dôkaz).
6. Statická kontrola: presne jeden literálny `fetch()` na externý host
   (`nakupny-kosik` cart-state readback).
7. `interaction_id`/`decision_id` sa v súbore vôbec nevyskytujú — čestný
   dôkaz, že V2.15d.1 nezaviedla žiadnu frontend koreláciu.

Všetky regexové vzory boli krížovo overené cez Python `re` proti
reálnemu obsahu súboru pred pushom (keďže lokálne nie je možné spustiť
Node) — CI beh je finálny, autoritatívny overovací mechanizmus.

## 8. Runtime-load validácia

**`LOAD_VALIDATION_NOT_YET_AVAILABLE`** — syntaktická validácia
(`--check`/`vm.Script`) NEspúšťa top-level IIFE (ten okamžite odkazuje
na `window`/`document`), takže neodhalí runtime chyby pri inicializácii.
Pridanie minimálneho DOM stubu bolo zvážené a zámerne odložené (Section
16 zadania to explicitne povoľuje) — vyžadovalo by mockovanie
`window`/`document`/`fetch` bez jasného bezpečnostného kontraktu, ktorý
by to odôvodňoval v tejto úzko-rozsahovej sprinte.

## 9. Byte-safety / diff audit

`app/widget.js`: **0 zmien** (`git diff --stat` prázdny). Zmenené:
`.github/workflows/ci.yml` (pridaný Node setup + JS validačný krok),
nový `tests/js/widget.test.mjs`. Žiadny `node_modules`, žiadny
lockfile, žiadny `package.json`.

## 10. CI integrácia

Nový krok `JS syntax + widget test foundation (V2.15d.1)` umiestnený
hneď po Python "Compile check", PRED drahou plnou pytest sadou —
rozbitý `widget.js` teraz zlyhá CI rýchlo, nie až po ~15 minútach
testov.

## 11. Regresia (backend, nezmenený)

Plná sada: **pozri finálny report** (očakávané 1664/1664, nezmenené).
V2.10: 35/39 (nezmenené). Canary: 10/10 (nezmenené).

## 12. Zostávajúce obmedzenia

- Runtime-load validácia (DOM/browser globals) nie je implementovaná.
- Pure-helper extrakcia (payload construction, ID extraction) nebola
  vykonaná — žiadna funkcia nebola extrahovaná z IIFE, keďže by to
  vyžadovalo úpravu `widget.js`, mimo rozsahu tejto sprinty.
- Testy sú spustiteľné len v CI (Node 20) alebo na stroji s Node
  nainštalovaným — nie na tomto lokálnom vývojovom stroji.

## 13. Finálny stav pripravenosti

**`FRONTEND_SYNTAX_VALIDATION_ONLY`** (TOOLING_GATE_B dosiahnutý, ale
bez runtime-load/pure-helper vrstvy — čestne neoznačené ako plné
"READY", keďže load-time validácia chýba).

## 14. V2.15d.2 GO/STOP

**`V2_15D_2_GO_WITH_LIMITATIONS`** — syntax/parse/no-new-endpoint gate
je teraz v CI vynútený, čo robí BUDÚCU úpravu `widget.js` bezpečne
recenzovateľnú. Limitácia: runtime-load validácia chýba, takže
V2.15d.2 by mal minimalizovať zmeny v top-level inicializačnom kóde a
sústrediť sa na pridávanie polí do už-existujúcich, už-testovaných
volaní (`fireEvent()` payloady).

## 15. V2.15e

Zostáva **`V2_15E_STOP_CORRELATION_INSUFFICIENT`** (nezmenené touto
sprintou — frontend korelácia stále neimplementovaná, len jej
bezpečnostná základňa).
