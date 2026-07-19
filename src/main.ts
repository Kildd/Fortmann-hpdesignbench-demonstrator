import './style.css'
import { createObjectiveChart } from './chart/objectiveChart'
import { preloadBrowserEngine, runOptimize } from './optimizer/runOptimize'
import { drawCrossSection } from './section/drawCrossSection'
import type { OptEvent, OptimizeRequest } from './types'

const UNIT_CO2 = 'kg CO₂-äquivalent/m²'

/** Ordered constraint groups for the layperson UI (Z1–Z3 are hidden). */
const CONSTRAINT_GROUPS: {
  title: string
  items: { key: string | string[]; label: string }[]
}[] = [
  {
    title: '1. Grenzzustand der Tragfähigkeit',
    items: [{ key: 'A_bending_capacity', label: '1.1 Biegetragfähigkeit' }],
  },
  {
    title: '2. Grenzzustand der Gebrauchstauglichkeit',
    items: [
      {
        key: [
          'B1a_deflection_by_wmax_capacity',
          'B1b_deflection_by_mcr_capacity',
        ],
        label: '2.1 Verformungsbegrenzung',
      },
      {
        key: [
          'B2a_failure_announcement_by_wmin_capacity',
          'B2b_failure_announcement_by_mcr_capacity',
        ],
        label: '2.2 Versagensankündigung',
      },
    ],
  },
  {
    title: '3. Konstruktive Durchbildung',
    items: [
      { key: 'C1_concrete_cover_capacity', label: '3.1 Betondeckung' },
      { key: 'C2_clear_spacing_capacity', label: '3.2 Abstand Spannglieder' },
      { key: 'C3_shell_thickness_capacity', label: '3.3 Mindestschalendicke' },
    ],
  },
  {
    title: '4. Bauakustik',
    items: [
      {
        key: 'D1_airborne_sound_insulation_capacity',
        label: '4.1 Luftschalldämmaß',
      },
      {
        key: 'D2_impact_sound_insulation_capacity',
        label: '4.2 Trittschallpegel',
      },
    ],
  },
]

const app = document.querySelector<HTMLDivElement>('#app')!

app.innerHTML = `
  <header class="hero">
    <h1 class="brand">HPDesignBench Demonstrator</h1>
    <p class="subtitle">
      Stellen Sie Spannweite, Nutzlast und Evaluationsbudget ein und starten Sie
      eine TPE-Optimierung der vorgespannte Carbonbeton-HP-Schale.
    </p>
  </header>

  <div class="layout">
    <aside class="panel">
      <h2>Eingaben</h2>
      <div class="field">
        <label for="spanMm">Spannweite</label>
        <select id="spanMm">
          <option value="5100">5,10 m</option>
          <option value="6450" selected>6,45 m</option>
          <option value="7900">7,90 m</option>
        </select>
      </div>
      <div class="field">
        <label for="loadCategory">Nutzlastkategorie nach Eurocode 1</label>
        <select id="loadCategory">
          <option value="A2">A2: 1,5 kN/m²</option>
          <option value="B2" selected>B2: 3,0 kN/m²</option>
          <option value="T2">T2: 5,0 kN/m²</option>
        </select>
      </div>
      <div class="field">
        <label for="nTrials">Evaluationsbudget</label>
        <input id="nTrials" type="number" min="20" max="1000" step="10" value="60" />
        <p class="hint">Ganzzahl zwischen 20 und 1000</p>
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
          <h2>Querschnitt – aktuelle Iteration</h2>
          <svg id="sectionCurrent"></svg>
          <div id="statsCurrent" class="section-stats-host"></div>
        </div>
        <div class="section-wrap">
          <h2>Querschnitt – bestes Ergebnis aller Iterationen</h2>
          <svg id="sectionBest"></svg>
          <div id="statsBest" class="section-stats-host"></div>
        </div>
      </section>

      <section class="card">
        <h2>Zielfunktion</h2>
        <div class="obj-explain" id="objExplain">
          <p>Unbestrafte Zielfunktion: y = <strong id="yVal">–</strong> ${UNIT_CO2}</p>
          <p>Bestrafte Zielfunktion: y<sub>p</sub> = <strong id="ypVal">–</strong> ${UNIT_CO2}</p>
          <p class="obj-trial">Iteration: <strong id="trialVal">–</strong></p>
        </div>
        <div id="chart"></div>
      </section>

      <section class="card">
        <h2>Nebenbedingungen (Nachweise)</h2>
        <div id="constraints"></div>
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
const statsCurrentEl = document.querySelector<HTMLElement>('#statsCurrent')!
const statsBestEl = document.querySelector<HTMLElement>('#statsBest')!
const statusEl = document.querySelector<HTMLElement>('#status')!
const startBtn = document.querySelector<HTMLButtonElement>('#startBtn')!
const stopBtn = document.querySelector<HTMLButtonElement>('#stopBtn')!
const yVal = document.querySelector<HTMLElement>('#yVal')!
const ypVal = document.querySelector<HTMLElement>('#ypVal')!
const trialVal = document.querySelector<HTMLElement>('#trialVal')!
const constraintsEl = document.querySelector<HTMLElement>('#constraints')!
const chart = createObjectiveChart(document.querySelector<HTMLElement>('#chart')!)

let abort: AbortController | null = null

drawCrossSection(sectionCurrentEl, null, {
  idPrefix: 'cur',
  ariaLabel: 'Querschnitt aktuelle Iteration',
  statsEl: statsCurrentEl,
})
drawCrossSection(sectionBestEl, null, {
  idPrefix: 'best',
  ariaLabel: 'Querschnitt bestes Ergebnis',
  statsEl: statsBestEl,
})
constraintsEl.innerHTML = '<p class="empty">Noch keine Auswertung.</p>'

function fmt(n: number | null | undefined, digits = 2): string {
  if (n == null || !Number.isFinite(n)) return '–'
  if (Math.abs(n) >= 1000) return n.toExponential(2)
  return n.toFixed(digits)
}

function maxUtil(
  util: Record<string, number>,
  keys: string | string[],
): number | null {
  const list = Array.isArray(keys) ? keys : [keys]
  const vals = list
    .map((k) => util[k])
    .filter((v): v is number => typeof v === 'number' && Number.isFinite(v))
  if (!vals.length) return null
  return Math.max(...vals)
}

function renderConstraints(util: Record<string, number> | undefined) {
  if (!util || !Object.keys(util).length) {
    constraintsEl.innerHTML = '<p class="empty">Noch keine Auswertung.</p>'
    return
  }

  const html = CONSTRAINT_GROUPS.map((group) => {
    const rows = group.items
      .map((item) => {
        const u = maxUtil(util, item.key)
        if (u == null) return ''
        const ok = u <= 1
        return `<div class="check-row">
          <span class="check-label">${item.label}</span>
          <span class="pill ${ok ? 'ok' : 'bad'}" title="Ausnutzung u ≤ 1 ist erfüllt">${fmt(u, 3)}</span>
        </div>`
      })
      .filter(Boolean)
      .join('')
    if (!rows) return ''
    return `<div class="check-group">
      <h3>${group.title}</h3>
      ${rows}
    </div>`
  }).join('')

  constraintsEl.innerHTML =
    html || '<p class="empty">Keine Nachweise in dieser Auswertung.</p>'
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
    chart.reset()
    statusEl.textContent = `Optimierung läuft · ${ev.n_trials} Iterationen`
    return
  }
  if (ev.type === 'trial') {
    trialVal.textContent = String(ev.trial + 1)
    if (ev.y != null) yVal.textContent = fmt(ev.y)
    if (ev.y_p != null) ypVal.textContent = fmt(ev.y_p)

    drawCrossSection(sectionCurrentEl, ev.geometry, {
      idPrefix: 'cur',
      ariaLabel: 'Querschnitt aktuelle Iteration',
      statsEl: statsCurrentEl,
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
        ariaLabel: 'Querschnitt bestes Ergebnis',
        statsEl: statsBestEl,
      })
      renderConstraints(ev.best.utilizations)
    }
    statusEl.textContent = ev.is_best
      ? `Iteration ${ev.trial + 1} · neues bestes Ergebnis`
      : `Iteration ${ev.trial + 1}`
    return
  }
  if (ev.type === 'done') {
    statusEl.textContent = ev.best
      ? `Fertig · bestes y_p = ${fmt(ev.best.y_p)} ${UNIT_CO2} (Iteration ${ev.best.trial + 1})`
      : 'Fertig · keine gültige Lösung'
    if (ev.best) {
      drawCrossSection(sectionBestEl, ev.best.geometry, {
        idPrefix: 'best',
        ariaLabel: 'Querschnitt bestes Ergebnis',
        statsEl: statsBestEl,
      })
      renderConstraints(ev.best.utilizations)
      if (ev.best.y != null) yVal.textContent = fmt(ev.best.y)
      if (ev.best.y_p != null) ypVal.textContent = fmt(ev.best.y_p)
      trialVal.textContent = String(ev.best.trial + 1)
    }
  }
}

function readRequest(): OptimizeRequest {
  const nTrials = Math.min(
    1000,
    Math.max(20, Math.round(Number(document.querySelector<HTMLInputElement>('#nTrials')!.value))),
  )
  document.querySelector<HTMLInputElement>('#nTrials')!.value = String(nTrials)
  return {
    spanMm: Number(document.querySelector<HTMLSelectElement>('#spanMm')!.value),
    loadCategory: document.querySelector<HTMLSelectElement>('#loadCategory')!.value,
    omegaGwp: 1,
    omegaCost: 0,
    nTrials,
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
  drawCrossSection(sectionCurrentEl, null, {
    idPrefix: 'cur',
    statsEl: statsCurrentEl,
  })
  drawCrossSection(sectionBestEl, null, {
    idPrefix: 'best',
    statsEl: statsBestEl,
  })
  constraintsEl.innerHTML = '<p class="empty">Noch keine Auswertung.</p>'

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
