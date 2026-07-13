# Foodland AI poradca - navrh dalsej verzie

## Ciel

Foodland AI poradca ma byt prakticky nakupny asistent pre zakaznikov Foodland.sk. Jeho hlavna uloha nie je rozpravat vseobecne o jedle, ale rychlo pomoct zakaznikovi najst vhodny produkt, porovnat moznosti, odporucit doplnky k nakupu a zodpovedat bezne otazky z dostupnych Foodland dat.

Poradca ma vzdy posobit ako sucast Foodlandu:

- odpoveda po slovensky alebo cesky podla jazyka zakaznika,
- je kratky, konkretny a nakupne orientovany,
- neprezentuje sa ako univerzalny chatbot,
- nevymysla ceny, sklad, zlozenie ani vlastnosti produktov,
- pri alergiach, dostupnosti a zlozeni odkazuje na detail produktu.

## Aktualny stav MVP

Projekt uz obsahuje:

- FastAPI backend,
- nacitanie produktov z Google Merchant feedu alebo JSON suboru,
- lokalne vyhladavanie nad nazvom, znackou, kategoriou a popisom,
- knowledge vyhladavanie nad FAQ, receptami, magazinom, cross-sellom, alternativami a Products_AI,
- odpoved cez OpenAI, ak je nastavene `OPENAI_API_KEY`,
- fallback odpovede bez OpenAI,
- embeddable chat widget,
- rate limiting na IP adresu,
- JSONL analytiku otazok.

Najblizsie slabiny MVP:

- slovenske texty v niektorych suboroch su poskodene kodovanim,
- vyhladavanie je cisto tokenove a nema semanticke porozumenie,
- prompt este nema jasne intent routing pravidla,
- odpoved nepracuje oddelene s produktmi, FAQ a poradenskym obsahom,
- chyba hodnotenie kvality odpovedi a najcastejsich neuspesnych otazok,
- widget nema navrhy rychlych otazok ani zber spatnej vazby.

## Navrhovane spravanie poradcu

### 1. Produktove hladanie

Priklady:

- "mate sushi ryzu?"
- "hladam gochujang"
- "ukaz mi kokosove mlieko"
- "mate nieco na ramen?"

Odpoved:

- kratka veta, ze nasiel vhodne produkty,
- 3 az 6 produktov s cenou, dostupnostou a odkazom,
- ak existuje Products_AI kontext, doplnit jednu prakticku poznamku k pouzitiu,
- ak je malo presny vysledok, priznat neistotu a ponuknut spresnenie.

### 2. Poradenstvo k pouzitiu

Priklady:

- "aku ryzu potrebujem na sushi?"
- "co sa hodi do pho?"
- "aky je rozdiel medzi svetlou a tmavou sojovou omackou?"

Odpoved:

- najprv kratke vysvetlenie,
- potom odporucane produkty,
- pripadne cross-sell doplnky,
- bez tvrdeni, ktore nie su v produktoch alebo knowledge baze.

### 3. Alternativy

Priklady:

- "nemate tuto omacku, cim ju nahradim?"
- "alternativa ku gochujangu"
- "nieco podobne ako sriracha"

Odpoved:

- pomenovat najblizsie alternativy,
- vysvetlit rozdiel v chuti alebo pouziti, ak je v knowledge baze,
- zobrazit produkty, ktore sa daju kupit.

### 4. Cross-sell

Priklady:

- "co este potrebujem k sushi?"
- "co kupit k ramenu?"
- "co sa hodi k miso polievke?"

Odpoved:

- odporucit doplnky v logickych skupinach,
- nezahlcovat zoznamom,
- preferovat dostupne produkty.

### 5. FAQ a obchodne otazky

Priklady:

- "ako funguju kredity?"
- "ako je to s dorucenim?"
- "da sa platit kartou?"

Odpoved:

- odpoved z FAQ ma prednost pred generickou AI odpovedou,
- ak FAQ nema presnu odpoved, povedat to a odporucit kontakt alebo detail na webe,
- nehadat pravidla dopravy, reklamacie ani platby.

## Navrhovana architektura v2

### Request pipeline

1. Validacia vstupu a rate limit.
2. Detekcia jazyka a intentu.
3. Produktove vyhladavanie.
4. Knowledge vyhladavanie.
5. Zostavenie kontextu podla intentu.
6. Generovanie odpovede.
7. Bezpecnostna kontrola odpovede.
8. Logovanie metrik a anonymizovanej otazky.

### Intent routing

Odporucane intenty:

- `product_search`
- `product_advice`
- `recipe_help`
- `cross_sell`
- `alternative`
- `faq`
- `support`
- `unknown`

Intent sa da najprv riesit jednoducho pravidlami nad tokenmi a neskor modelom. Pre MVP v2 staci hybrid:

- pravidla pre jasne FAQ, alternativy a cross-sell,
- produktove vyhladavanie pre vsetky otazky,
- OpenAI pouzit na formulaciu odpovede, nie ako zdroj faktov.

### Vyhladavanie

Kratkodobo:

- opravit diakritiku a synonymicka pravidla,
- rozsirit stopwords pre slovencinu a cestinu,
- pridat boosty pre presnu zhodu produktu, znacky a kategorie,
- pouzit Products_AI ako synonymicky slovnik.

Strednodobo:

- vytvorit embeddings index nad produktmi a knowledge zaznamami,
- kombinovat token score + vector score,
- pre kazdy vysledok vratit dovod zhody: nazov, synonymum, kategoria, poradenska poznamka.

### Odpovedovy kontrakt

Endpoint `/chat` by mal vracat stabilnu strukturu:

```json
{
  "answer": "Kratka odpoved pre zakaznika.",
  "intent": "product_search",
  "products": [],
  "recommendations": [],
  "knowledge": {},
  "confidence": "high",
  "warnings": []
}
```

Tym sa widget moze rozhodovat, ci zobrazi produktove karty, FAQ odpoved, odporucane doplnky alebo vyzvu na spresnenie.

## Guardrails

Poradca musi dodrziavat tieto pravidla:

- Pouzivaj iba poskytnute produkty a knowledge kontext.
- Ceny uvadzaj iba z produktoveho feedu.
- Dostupnost uvadzaj iba z produktoveho feedu.
- Pri alergiach, zlozeni a nutricnych tvrdeniach odporuc overit detail produktu.
- Pri zdravotnych otazkach neposkytuj medicinske rady.
- Ak odpoved nie je v datach, povedz to priamo.
- Neporovnavaj Foodland s konkurenciou, ak na to nie su data.
- Nepouzivaj dlhe marketingove odpovede.

## Widget v2

Odporucane zlepsenia:

- rychle otazky po otvoreni:
  - "Co potrebujem na sushi?"
  - "Mate gochujang?"
  - "Odporucte mi nieco na ramen"
  - "Ako funguju kredity?"
- palec hore/dole pri odpovedi,
- tlacidlo "Zobrazit viac produktov",
- jemne oznacenie, ked je vysledok neisty,
- automaticke otvorenie produktu v novom tabe,
- moznost predvyplnit otazku z produktovej stranky, napr. "K comu sa hodi tento produkt?"

## Analytika kvality

Logovat anonymizovane:

- text otazky,
- intent,
- pocet najdenych produktov,
- pocet knowledge vysledkov,
- confidence,
- ci odpoved pouzila OpenAI alebo fallback,
- kliky na produkt z widgetu,
- feedback palec hore/dole.

Pravidelny report:

- top neuspesne otazky,
- top hladane produkty bez vysledku,
- najcastejsie intenty,
- produkty s vysokym poctom klikov,
- FAQ temy, ktore chybaju.

## Implementacny roadmap

### Faza 1 - stabilizacia MVP

- Opravit poskodene UTF-8 texty v `app/main.py`, `app/knowledge.py` a `app/widget.js`.
- Doplnit testy pre vyhladavanie a fallback odpovede.
- Zjednotit duplicate subory v koreni a v `app/`.
- Overit, ze `/health`, `/products/search`, `/knowledge/search` a `/chat` funguju lokalne.
- Nasadit backend na Railway alebo Render.

### Faza 2 - lepsi poradca

- Pridat intent routing.
- Upravit `/chat` odpoved na stabilny JSON kontrakt.
- Rozsirit synonymicka pravidla z Products_AI.
- Vylepsit prompt podla intentu.
- Doplnit widget quick prompts a feedback.

### Faza 3 - semanticke vyhladavanie

- Vytvorit embeddings index produktov a knowledge zaznamov.
- Kombinovat tokenove a semanticke skore.
- Pridat admin endpoint na rebuild indexu.
- Merat precision na realnych otazkach.

### Faza 4 - obchodne napojenia

- Ak e-shop poskytne API, doplnit real-time sklad.
- Pridat odporucania na urovni kosika.
- Pridat produktove otazky priamo na detail produktu.
- Napojit support handoff pre otazky mimo znalostnej bazy.

## Najblizsi odporucany krok

Najprv opravit kodovanie a zaviest intent routing. Bez toho bude poradca tazsie posobit profesionalne, aj keby samotne vyhladavanie fungovalo. Po tejto uprave sa da lepsie testovat kvalita odpovedi a widget moze zobrazovat spravne typy vysledkov.
