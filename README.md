# SlabDesignBench – Machbarkeitsdemonstrator

Eigenständiger Web-Demonstrator für die parametrische Bemessung und
Optimierung einer vorgespannten HP-Schale. Das vorhandene
Modell dient als technisches Vorstudienmodell für das umfangreichere
Optimierungswerkzeug „SlabDesignBench“ für die Optimierung von Geschossdecken.

## Unabhängigkeit von HPDesignBench

Dieses Repository enthält eine **eingefrorene Kopie** der benötigten Analysemodule unter `engine/`.  
Es gibt **kein** Submodul und keinen Laufzeit-Import aus [Kildd/hpdesignbench](https://github.com/Kildd/hpdesignbench).  
Änderungen am Originalprojekt beeinflussen diese Website nicht, bis die Engine bewusst aktualisiert wird.

## Voraussetzungen

- Node.js 20+
- Python 3.12+

## Setup

```bash
npm install
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r engine\requirements-engine.txt
```

## Lokal starten

```bash
npm run dev
```

Öffnen: `http://localhost:5173/`

Der Dev-Server startet die Optimierung über die **native Python-Engine** (`/api/optimize` → `engine/demo_optimize.py`).

## Build / GitHub Pages

```bash
npm run build
# publish folder for Pages:
# copy dist → docs  (or: Remove-Item -Recurse docs; Copy-Item -Recurse dist docs)
```

Die Website wird aus dem Ordner [`docs/`](docs/) auf `main` ausgeliefert:

**GitHub → Settings → Pages → Deploy from a branch → `main` / `/docs`**

Live: https://kildd.github.io/Fortmann-hpdesignbench-demonstrator/

Hinweis: Auf GitHub Pages steht kein lokales Python zur Verfügung. Die Seite versucht dann den **Pyodide**-Pfad (langsamer, erster Start lädt Pakete). Für die beste Erfahrung Optimierungen lokal mit `npm run dev` ausführen.

## Engine-Smoke-Test

```bash
npm run optimize:smoke
```

## Credits

Analyselogik adaptiert aus dem HPDesignBench-/SlabDesignBench-Ökosystem (Loutfi, Melcer, Dombrowski @ TU Berlin Fachgebiet Entwerfen und Konstruieren – Massivbau).
