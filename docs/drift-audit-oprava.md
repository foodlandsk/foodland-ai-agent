# Drift audit a navrh opravy

## Verdikt

Drift nie je OK v sucasnom stave. Aplikacia pravdepodobne pobezi, pretoze deploy konfiguracia pouziva `app.main:app`, ale repozitar je matuci a rizikovy na dalsie upravy.

Najvacsie problemy:

1. V koreni projektu su duplicitne alebo zle pomenovane subory.
2. Niektore texty su nekonzistentne medzi verziami suborov.
3. Korelove subory mozu pomylit deploy, Vercel autodetekciu alebo dalsieho vyvojara.
4. Widget ma drobny jazykovy drift: cast textov je s diakritikou, cast bez nej.

## Co je OK

- Produkcny start command na Railway pouziva `uvicorn app.main:app`.
- `pyproject.toml` pre Vercel pouziva `app.main:app`.
- Hlavna aplikacia je v priecinku `app/`.
- Staticke subory sa servuju z `app/`, teda `/static/widget.js` berie `app/widget.js`.
- `app/knowledge.py` obsahuje spravne slovenske nazvy klucov ako `Otazka`, `Odpoved`, `Kategoria` s diakritikou.

## Co nie je OK

### 1. Zle pomenovane subory v koreni

V koreni projektu su subory, ktore nazvom nezodpovedaju obsahu:

- `search.py` obsahuje backend aplikaciu, nie vyhladavaci modul.
- `widget.html` obsahuje Python search kod, nie HTML demo.
- `widget.js` obsahuje HTML demo, nie JavaScript widget.

Toto je najnebezpecnejsi drift, lebo vyzera nevinne, ale pri rucnej uprave clovek lahko zmeni nespravny subor.

### 2. Duplicitne entrypointy

V koreni je `main.py`, ktory len importuje:

```python
from app.main import app
```

To samo o sebe nie je zle. Moze to pomoct platformam, ktore hladaju `main.py`. Problem je, ze vedla neho su dalsie root subory s rovnakymi nazvami ako v `app/`, ale s nespravnym obsahom.

### 3. Jazykovy drift vo widgete

V `app/widget.js` su texty miestami s diakritikou a miestami bez:

- `Hladam vo Foodland produktoch`
- `Poslat`
- `Minimalizovat chat`
- `Overit dostupnost`

Pouzivatelsky je lepsie zjednotit vsetko na prirodzenu slovencinu:

- `Hľadám vo Foodland produktoch`
- `Poslať`
- `Minimalizovať chat`
- `Overiť dostupnosť`

### 4. Prompt drift

System prompt v `app/main.py` je bez diakritiky:

```text
Si nakupny asistent...
Odpovedaj po slovensky...
Pouzivaj iba poskytnuty kontext...
```

Funkcne to nie je kriticke, ale pri slovenskom produkte odporucam mat aj interny prompt cisty a citatelny.

## Navrh opravy

### Krok 1 - Vybrat kanonicku strukturu

Kanonicka struktura ma byt:

```text
app/
  main.py
  search.py
  knowledge.py
  feed.py
  import_feed.py
  widget.js
  widget.html
data/
  products.json
  knowledge.json
docs/
  ai-poradca-navrh.md
  drift-audit-oprava.md
```

Vsetko vykonavatelne a pouzivane aplikaciou ostava v `app/`.

### Krok 2 - Upratat root subory

Odporucam ponechat iba root `main.py` ako kompatibilitny shim:

```python
from app.main import app
```

Ostatne zle pomenovane root kopie odstranit:

- `search.py`
- `knowledge.py`
- `widget.js`
- `widget.html`
- `import_feed.py`, ak je duplicitny s `app/import_feed.py`

Ak nechceme mazat hned, alternativa je presunut ich do `archive/legacy-root-files/`, ale pre produkcny repozitar je cistejsie ich odstranit.

### Krok 3 - Zjednotit slovenske texty

V `app/main.py` upravit:

- fallback odpovede,
- rate-limit hlasky,
- warning hlasky,
- system prompt.

V `app/widget.js` upravit:

- titulky,
- placeholder,
- loading text,
- error texty,
- CTA tlacidla,
- demo odpovede.

### Krok 4 - Pridat malu drift kontrolu

Pridat jednoduchy test alebo skript, ktory zlyha, ak:

- root `widget.js` alebo `widget.html` existuju mimo `app/`,
- root `search.py` existuje mimo `app/`,
- v zdrojovych suboroch sa objavia typicke mojibake znaky.

Priklad pravidla:

```text
Zakazane root subory:
- search.py
- widget.js
- widget.html
- knowledge.py
```

### Krok 5 - Overenie po oprave

Po uprave spustit:

```bash
python -m compileall app
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Overit endpointy:

```text
GET  /health
POST /products/search
POST /knowledge/search
POST /chat
GET  /static/widget.html
GET  /static/widget.js
```

## Odporucana minimalna oprava

Ak chceme rychlu a bezpecnu opravu bez zasahu do logiky:

1. Nechat `app/` ako jediny zdroj pravdy.
2. Odstranit zle pomenovane root kopie.
3. Ponechat root `main.py` shim.
4. Precistit slovenske texty v `app/main.py` a `app/widget.js`.
5. Doplnit drift check do dokumentacie alebo testov.

Toto je mala zmena s velkym efektom: znizi riziko chyb pri deployi a dalsom vyvoji bez toho, aby menila spravanie vyhladavania alebo OpenAI odpovedi.
