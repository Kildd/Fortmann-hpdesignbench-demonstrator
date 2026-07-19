import './style.css'
import { createObjectiveChart } from './chart/objectiveChart'
import { preloadBrowserEngine, runOptimize } from './optimizer/runOptimize'
import { drawCrossSection } from './section/drawCrossSection'
import type { BestState, OptEvent, OptimizeRequest } from './types'

const app = document.querySelector<HTMLDivElement>('#app')!

app.innerHTML = `
  <header class="hero">
    <h1 class="brand">HPDesignBench Demonstrator</h1>
    <p class="subtitle">
      Stellen Sie die Ausgangsparameter ein und starten Sie eine TPE-Optimierung.
      Beobachten Sie, wie Variablen, Nebenbedingungen und Ziele sich ändern – inklusive Querschnitt.
    </p>
  </header>

  <div class="layout">
    <aside class="panel">
      <h2>Eingaben</h2>
      <div class="field">
        <label for="spanMm">Spannweite L [mm]</label>
        <input id="spanMm" type="number" min="4000" max="12000" step="100" value="8000" />
      </div>
      <div class="field">
        <label for="loadCategory">Nutzlastkategorie</label>
        <select id="loadCategory">
          <option value="A1">A1</option>
          <option value="A2">A2</option>
          <option value="A3">A3</option>
          <option value="B1">B1</option>
          <option value="B2" selected>B2</option>
          <option value="B3">B3</option>
          <option value="C1">C1</option>
          <option value="C2">C2</option>
          <option value="C3">C3</option>
        </select>
      </div>
      <div class="field">
        <label for="omegaGwp">Gewicht Ω<sub>GWP</sub></label>
        <input id="omegaGwp" type="number" min="0" max="2" step="0.5" value="1" />
      </div>
      <div class="field">
        <label for="omegaCost">Gewicht Ω<sub>Kosten</sub></label>
        <input id="omegaCost" type="number" min="0" max="2" step="0.5" value="0" />
      </div>
      <div class="field">
        <label for="nTrials">Evaluationsbudget</label>
        <input id="nTrials" type="number" min="10" max="200" step="10" value="60" />
      </div>
      <div class="actions">
        <button class="primary" id="startBtn" type="button">Optimierung starten</button>
        <button class="ghost" id="stopBtn" type="button" disabled>Stoppen</button>
      </div>
      <p class="status" id="status">Bereit.</p>
    </aside>

    <main class="stage">
      <section class="sections-row">
        <div class="section-wrap">
          <h2>Querschnitt · aktueller Trial</h2>
          <svg id="sectionCurrent"></svg>
        </div>
        <div class="section-wrap">
          <h2>Querschnitt · best-so-far</h2>
          <svg id="sectionBest"></svg>
        </div>
      </section>

      <section class="card">
        <h2>Ziele</h2>
        <div class="obj-row">
          <div><span>y</span> <strong id="yVal">–</strong></div>
          <div><span>y<sub>p</sub></span> <strong id="ypVal">–</strong></div>
          <div><span>Trial</span> <strong id="trialVal">–</strong></div>
        </div>
        <div id="chart"></div>
      </section>

      <section class="metrics">
        <div class="card">
          <h2>Nebenbedingungen (Ausnutzung)</h2>
          <div id="constraints"></div>
        </div>
        <div class="card">
          <h2>Entwurfsvariablen · best-so-far</h2>
          <div id="vars"></div>
        </div>
      </section>
    </main>
  </div>

  <footer class="footer">
    <p>
      Eigenständige Kopie der Analysemethoden für HP-Schalen (Carbonbeton, TPE-Suche).
      Nicht an das laufende
      <a href="https://github.com/Kildd/hpdesignbench" target="_blank" rel="noreferrer">HPDesignBench</a>-Repository gekoppelt.
      Konzept nach Melcer / TU Berlin.
    </p>
  </footer>
`

const sectionCurrentEl = document.querySelector<SVGSVGElement>('#sectionCurrent')!
const sectionBestEl = document.querySelector<SVGSVGElement>('#sectionBest')!
const statusEl = document.querySelector<HTMLElement>('#status')!
const startBtn = document.querySelector<HTMLButtonElement>('#startBtn')!
const stopBtn = document.querySelector<HTMLButtonElement>('#stopBtn')!
const yVal = document.querySelector<HTMLElement>('#yVal')!
const ypVal = document.querySelector<HTMLElement>('#ypVal')!
const trialVal = document.querySelector<HTMLElement>('#trialVal')!
const varsEl = document.querySelector<HTMLElement>('#vars')!
const constraintsEl = document.querySelector<HTMLElement>('#constraints')!
const chart = createObjectiveChart(document.querySelector<HTMLElement>('#chart')!)

let labels = {
  vars: {} as Record<string, string>,
  constraints: {} as Record<string, string>,
}
let abort: AbortController | null = null

drawCrossSection(sectionCurrentEl, null, {
  idPrefix: 'cur',
  ariaLabel: 'Querschnitt aktueller Trial',
})
drawCrossSection(sectionBestEl, null, {
  idPrefix: 'best',
  ariaLabel: 'Querschnitt best-so-far',
})
constraintsEl.innerHTML = '<p class="empty">Noch keine Auswertung.</p>'
varsEl.innerHTML = '<p class="empty">Noch keine Auswertung.</p>'

function fmt(n: number | null | undefined, digits = 3): string {
  if (n == null || !Number.isFinite(n)) return '–'
  if (Math.abs(n) >= 1000) return n.toExponential(3)
  return n.toFixed(digits)
}

function renderVars(best: BestState | null, varLabels: Record<string, string>) {
  if (!best) {
    varsEl.innerHTML = '<p class="empty">Noch keine Auswertung.</p>'
    return
  }
  const rows = Object.entries(best.vars)
    .map(
      ([k, v]) =>
        `<tr><td>${varLabels[k] ?? k}</td><td class="mono">${typeof v === 'number' ? fmt(v, 2) : v}</td></tr>`,
    )
    .join('')
  varsEl.innerHTML = `<table><thead><tr><th>Variable</th><th>Wert</th></tr></thead><tbody>${rows}</tbody></table>`
}

function renderConstraints(
  util: Record<string, number> | undefined,
  constraintLabels: Record<string, string>,
) {
  if (!util || !Object.keys(util).length) {
    constraintsEl.innerHTML = '<p class="empty">Noch keine Auswertung.</p>'
    return
  }
  const rows = Object.entries(util)
    .map(([k, v]) => {
      const ok = v <= 1
      return `<tr>
        <td>${constraintLabels[k] ?? k}</td>
        <td><span class="pill ${ok ? 'ok' : 'bad'}">${fmt(v, 3)}</span></td>
      </tr>`
    })
    .join('')
  constraintsEl.innerHTML = `<table><thead><tr><th>Check</th><th>u</th></tr></thead><tbody>${rows}</tbody></table>`
}

function onEvent(ev: OptEvent) {
  if (ev.type === 'status') {
    statusEl.textContent = ev.message
    return
  }
  if (ev.type === 'error') {
    statusEl.textContent = `Fehler: ${ev.message}`
    return
  }
  if (ev.type === 'start') {
    labels = { vars: ev.var_labels, constraints: ev.constraint_labels }
    chart.reset()
    const integ = ev.integrator ?? 'fiber'
    statusEl.textContent = `TPE läuft · ${ev.n_trials} Trials · Integrator: ${integ}`
    return
  }
  if (ev.type === 'trial') {
    trialVal.textContent = String(ev.trial + 1)
    if (ev.y != null) yVal.textContent = fmt(ev.y)
    if (ev.y_p != null) ypVal.textContent = fmt(ev.y_p)

    drawCrossSection(sectionCurrentEl, ev.geometry, {
      idPrefix: 'cur',
      ariaLabel: 'Querschnitt aktueller Trial',
    })

    chart.push({
      trial: ev.trial,
      y: ev.y,
      y_p: ev.y_p,
      bestY: ev.best?.y ?? null,
      bestYp: ev.best?.y_p ?? null,
    })

    if (ev.best) {
      drawCrossSection(sectionBestEl, ev.best.geometry, {
        idPrefix: 'best',
        ariaLabel: 'Querschnitt best-so-far',
      })
      renderVars(ev.best, labels.vars)
      renderConstraints(ev.best.utilizations, labels.constraints)
    }
    statusEl.textContent = ev.is_best
      ? `Trial ${ev.trial + 1} · neues Best-so-far · Integrator: fiber`
      : `Trial ${ev.trial + 1} · Integrator: fiber`
    return
  }
  if (ev.type === 'done') {
    statusEl.textContent = ev.best
      ? `Fertig · bestes y_p = ${fmt(ev.best.y_p)} (Trial ${ev.best.trial + 1})`
      : 'Fertig · keine gültige Lösung'
    if (ev.best) {
      drawCrossSection(sectionBestEl, ev.best.geometry, {
        idPrefix: 'best',
        ariaLabel: 'Querschnitt best-so-far',
      })
      renderVars(ev.best, labels.vars)
      renderConstraints(ev.best.utilizations, labels.constraints)
    }
  }
}

function readRequest(): OptimizeRequest {
  return {
    spanMm: Number(document.querySelector<HTMLInputElement>('#spanMm')!.value),
    loadCategory: document.querySelector<HTMLSelectElement>('#loadCategory')!.value,
    omegaGwp: Number(document.querySelector<HTMLInputElement>('#omegaGwp')!.value),
    omegaCost: Number(document.querySelector<HTMLInputElement>('#omegaCost')!.value),
    nTrials: Number(document.querySelector<HTMLInputElement>('#nTrials')!.value),
    seed: 42,
  }
}

startBtn.addEventListener('click', async () => {
  abort?.abort()
  abort = new AbortController()
  startBtn.disabled = true
  stopBtn.disabled = false
  chart.reset()
  yVal.textContent = '–'
  ypVal.textContent = '–'
  trialVal.textContent = '–'
  statusEl.textContent = 'Starte Optimierung…'
  drawCrossSection(sectionCurrentEl, null, { idPrefix: 'cur' })
  drawCrossSection(sectionBestEl, null, { idPrefix: 'best' })

  try {
    await runOptimize(readRequest(), onEvent, abort.signal)
  } catch (err) {
    if (!(err instanceof DOMException && err.name === 'AbortError')) {
      statusEl.textContent = `Fehler: ${err instanceof Error ? err.message : String(err)}`
    } else {
      statusEl.textContent = 'Abgebrochen.'
    }
  } finally {
    startBtn.disabled = false
    stopBtn.disabled = true
  }
})

stopBtn.addEventListener('click', () => {
  abort?.abort()
  stopBtn.disabled = true
})

// Warm Pyodide + packages as soon as the page opens (GitHub Pages path).
if (!import.meta.env.DEV) {
  startBtn.disabled = true
  statusEl.textContent = 'Browser-Engine wird vorbereitet…'
  preloadBrowserEngine((ev) => {
    if (ev.type === 'status') statusEl.textContent = ev.message
    if (ev.type === 'error') statusEl.textContent = `Fehler: ${ev.message}`
  })
    .then(() => {
      startBtn.disabled = false
      statusEl.textContent = 'Bereit.'
    })
    .catch((err) => {
      startBtn.disabled = false
      statusEl.textContent = `Engine-Vorbereitung fehlgeschlagen: ${
        err instanceof Error ? err.message : String(err)
      }`
    })
}
