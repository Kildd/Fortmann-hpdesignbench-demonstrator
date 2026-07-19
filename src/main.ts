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
      Dieser Demonstrator steht im Zusammenhang mit dem Förderantrag
      „SlabDesignBench – Eine offene Forschungsplattform zur datenbasierten
      Optimierung von Stahlbeton-Geschossdecken hinsichtlich Kosten und
      CO<sub>2</sub>-Emissionen“ bei der Fritz und Trude Fortmann-Stiftung.
      Er soll anhand eines vereinfachten Optimierungs-Skripts für HP-Schalen
      als Deckenelemente die grundsätzliche Machbarkeit eines solchen Werkzeugs
      demonstrieren. Weil die Laufzeit des Tools im Browser deutlich länger ist,
      kann es sein, dass im festgelegten Evaluationsbudget kein Entwurf gefunden
      wird, der alle Nebenbedingungen erfüllt.
    </p>
  </header>

  <div class="layout">
    <aside class="panel-stack">
      <div class="panel-unit">
        <aside class="panel">
          <h2>Eingaben</h2>
          <div class="field">
            <label for="spanMm">Spannweite</label>
            <select id="spanMm">
              <option value="5100">5,10 m</option>
              <option value="6450" selected>6,45 m</option>
            </select>
          </div>
          <div class="field">
            <label for="loadCategory">Nutzlastkategorie nach Eurocode 1</label>
            <select id="loadCategory">
              <option value="A2">A2: 1,5 kN/m²</option>
              <option value="B2" selected>B2: 3,0 kN/m²</option>
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
        <aside class="info-box">
          <h3>Infobox „Eingaben“</h3>
          <p>
            Hier wird das zu lösende Optimierungsproblem ausgewählt. In SlabDesignBench
            wird hier eines der 116.640 zu lösenden Probleme eingestellt. Darüber hinaus
            kann z.&nbsp;B. eingestellt werden, wie viele Iterationen der
            Optimierungsalgorithmus ausführen darf.
          </p>
        </aside>
      </div>
    </aside>

    <main class="stage">
      <div class="panel-unit">
        <section class="card">
          <h2>Zielfunktion</h2>
          <div class="obj-explain">
            <p>Aktuelle Iteration: <strong id="objCurrent">–</strong> ${UNIT_CO2}</p>
            <p>Bestes Ergebnis aller Iterationen: <strong id="objBest">–</strong> ${UNIT_CO2}</p>
            <p class="obj-trial">Iteration: <strong id="trialVal">–</strong></p>
          </div>
          <div id="chart"></div>
        </section>
        <aside class="info-box">
          <h3>Infobox „Zielfunktion“</h3>
          <p>
            Dieser Konvergenzplot stellt den Wert der zu minimierenden Zielfunktion
            (hier Treibhausgaspotenzial, GWP) über die Iterationen dar. Werte, die über
            den abgebildeten Wertebereich hinausgehen, sind mit einem kleinen Pfeil nach
            oben dargestellt. Es ist zu sehen, wie qualitativ hochwertige
            Zwischenergebnisse in <span class="swatch-blue">blau</span> den insgesamt
            gefundenen Wert in <span class="swatch-red">rot</span> schrittweise
            minimieren.
          </p>
        </aside>
      </div>

      <div class="panel-unit">
        <section class="sections-row">
          <div class="section-wrap">
            <h2>Ergebnisse aktuelle Iteration</h2>
            <svg id="sectionCurrent"></svg>
            <h3 class="section-subhead">Variablen</h3>
            <div id="statsCurrent" class="section-stats-host"></div>
            <h3 class="section-subhead">Nebenbedingungen (Nachweise)</h3>
            <div id="constraintsCurrent" class="constraints-host"></div>
          </div>
          <div class="section-wrap">
            <h2>Bestes Ergebnis aller Iterationen</h2>
            <svg id="sectionBest"></svg>
            <h3 class="section-subhead">Variablen</h3>
            <div id="statsBest" class="section-stats-host"></div>
            <h3 class="section-subhead">Nebenbedingungen (Nachweise)</h3>
            <div id="constraintsBest" class="constraints-host"></div>
          </div>
        </section>
        <aside class="info-box">
          <h3>Infobox „Ergebnisse“</h3>
          <p>
            Hier werden die wichtigsten Informationen zur aktuellen Iteration und der
            insgesamt besten Iteration dargestellt. In der linken Spalte ist zu sehen,
            wie sich mit jeder neuen Iteration die Werte der Variablen ändern und somit
            auch die Ausnutzungen der Nachweise darunter variieren. Der bisher beste Entwurf wird
            auf der rechten Seite dargestellt. Der Gesamtwert der Zielfunktion eines
            Entwurfs wird durch die eingesetzten Materialvolumina und die zugehörigen
            GWP-Werte berechnet. Sind einzelne Nachweise nicht eingehalten
            (Ausnutzung&nbsp;&gt;&nbsp;100&nbsp;%), wird der Wert der Zielfunktion
            künstlich erhöht (Penalty-Konzept).
          </p>
        </aside>
      </div>
    </main>
  </div>

  <footer class="footer">
    <p>
      Dieses Web-Tool basiert auf mehreren Masterarbeiten und Forschungsaktivitäten
      am Fachgebiet Entwerfen und Konstruieren - Massivbau an der Technischen Universität Berlin.
      Kontakt:
      <a href="mailto:m.dombrowski@tu-berlin.de">m.dombrowski@tu-berlin.de</a>
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
const objCurrentEl = document.querySelector<HTMLElement>('#objCurrent')!
const objBestEl = document.querySelector<HTMLElement>('#objBest')!
const trialVal = document.querySelector<HTMLElement>('#trialVal')!
const constraintsCurrentEl = document.querySelector<HTMLElement>('#constraintsCurrent')!
const constraintsBestEl = document.querySelector<HTMLElement>('#constraintsBest')!
const chart = createObjectiveChart(document.querySelector<HTMLElement>('#chart')!)

let abort: AbortController | null = null
let lastCurrentUtil: Record<string, number> | undefined

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
constraintsCurrentEl.innerHTML = '<p class="empty">Noch keine Auswertung.</p>'
constraintsBestEl.innerHTML = '<p class="empty">Noch keine Auswertung.</p>'

function fmt(n: number | null | undefined, digits = 2): string {
  if (n == null || !Number.isFinite(n)) return '–'
  return n.toLocaleString('de-DE', {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  })
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

function renderConstraintsInto(
  el: HTMLElement,
  util: Record<string, number> | undefined,
) {
  if (!util || !Object.keys(util).length) {
    el.innerHTML = '<p class="empty">Noch keine Auswertung.</p>'
    return
  }

  const groups = CONSTRAINT_GROUPS.map((group) => {
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
      <h4>${group.title}</h4>
      ${rows}
    </div>`
  }).join('')

  el.innerHTML =
    groups || '<p class="empty">Keine Nachweise in dieser Auswertung.</p>'
}

function renderConstraints(
  current: Record<string, number> | undefined,
  best: Record<string, number> | undefined,
) {
  renderConstraintsInto(constraintsCurrentEl, current)
  renderConstraintsInto(constraintsBestEl, best)
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
    // Show the optimizer objective without naming y / y_p.
    objCurrentEl.textContent = fmt(ev.y_p)
    if (ev.best) {
      objBestEl.textContent = `${fmt(ev.best.y_p)} (Iteration ${ev.best.trial + 1})`
    }

    drawCrossSection(sectionCurrentEl, ev.geometry, {
      idPrefix: 'cur',
      ariaLabel: 'Querschnitt aktuelle Iteration',
      statsEl: statsCurrentEl,
    })

    chart.push({
      trial: ev.trial,
      current: ev.y_p,
      best: ev.best?.y_p ?? null,
    })

    if (ev.best) {
      drawCrossSection(sectionBestEl, ev.best.geometry, {
        idPrefix: 'best',
        ariaLabel: 'Querschnitt bestes Ergebnis',
        statsEl: statsBestEl,
      })
    }
    renderConstraints(ev.utilizations, ev.best?.utilizations)
    lastCurrentUtil = ev.utilizations

    statusEl.textContent = ev.is_best
      ? `Iteration ${ev.trial + 1} · neues bestes Ergebnis`
      : `Iteration ${ev.trial + 1}`
    return
  }
  if (ev.type === 'done') {
    statusEl.textContent = ev.best
      ? `Fertig · bestes Ergebnis = ${fmt(ev.best.y_p)} ${UNIT_CO2} (Iteration ${ev.best.trial + 1})`
      : 'Fertig · keine gültige Lösung'
    if (ev.best) {
      drawCrossSection(sectionBestEl, ev.best.geometry, {
        idPrefix: 'best',
        ariaLabel: 'Querschnitt bestes Ergebnis',
        statsEl: statsBestEl,
      })
      objBestEl.textContent = `${fmt(ev.best.y_p)} (Iteration ${ev.best.trial + 1})`
      trialVal.textContent = String(ev.best.trial + 1)
      renderConstraints(lastCurrentUtil, ev.best.utilizations)
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
  objCurrentEl.textContent = '–'
  objBestEl.textContent = '–'
  trialVal.textContent = '–'
  lastCurrentUtil = undefined
  statusEl.textContent = 'Starte Optimierung…'
  drawCrossSection(sectionCurrentEl, null, {
    idPrefix: 'cur',
    statsEl: statsCurrentEl,
  })
  drawCrossSection(sectionBestEl, null, {
    idPrefix: 'best',
    statsEl: statsBestEl,
  })
  constraintsCurrentEl.innerHTML = '<p class="empty">Noch keine Auswertung.</p>'
  constraintsBestEl.innerHTML = '<p class="empty">Noch keine Auswertung.</p>'

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
