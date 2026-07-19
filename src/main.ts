import './style.css'
import { createObjectiveChart } from './chart/objectiveChart'
import { preloadBrowserEngine, runOptimize } from './optimizer/runOptimize'
import { drawCrossSection } from './section/drawCrossSection'
import type { BestState, OptEvent, OptimizeRequest } from './types'

const UNIT_CO2 = 'kg CO₂-Äq./m²'
const FEAS_TOL = 1e-9

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
      {
        key: 'C2_clear_spacing_capacity',
        label: '3.2 Abstand der Spannglieder',
      },
      { key: 'C3_shell_thickness_capacity', label: '3.3 Mindestschalendicke' },
    ],
  },
  {
    title: '4. Bauakustik',
    items: [
      {
        key: 'D1_airborne_sound_insulation_capacity',
        label: '4.1 Luftschalldämmmaß',
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
    <h1 class="brand">SlabDesignBench – Demonstrator</h1>
    <p class="tagline">Vorstudienmodell einer HP-Schale</p>
    <p class="subtitle">
      Dieser Demonstrator zum Förderantrag „SlabDesignBench“ bei der Fritz und
      Trude Fortmann-Stiftung zeigt anhand eines vorhandenen
      Optimierungswerkzeugs für HP-Schalen die grundsätzliche Machbarkeit des
      Vorhabens. Das Vorstudienmodell verbindet die parametrische Definition von
      Entwurfsproblemen mit der automatisierten Bemessung durch einen Optimierungsalgorithmus.
    </p>
    <p class="subtitle">
      Im beantragten Projekt wird diese Methodik zunächst auf Stahlbeton-Geschossdecken
      übertragen. Die Browser-Version ist auf die CO<sub>2</sub>-Optimierung, ausgewählte Nachweise
      und wegen ihrer erhöhten Laufzeit auf eine begrenzte Anzahl von Iterationen beschränkt.
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
            <label for="loadCategory">Nutzlastkategorie</label>
            <select id="loadCategory">
              <option value="A2">A2: 1,5 kN/m²</option>
              <option value="B2" selected>B2: 3,0 kN/m²</option>
            </select>
          </div>
          <div class="field">
            <label for="nTrials">Anzahl erlaubter Iterationen</label>
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
          <h3>Auswahl des Entwurfsproblems</h3>
          <p>
            Hier wird ein vorhandenes HP-Schalen-Testproblem ausgewählt.
            SlabDesignBench überträgt dieselbe Prozesslogik auf 116.640
            Bemessungsaufgaben je Deckentyp.
          </p>
        </aside>
      </div>
    </aside>

    <main class="stage">
      <div class="panel-unit">
        <section class="card">
          <h2>Optimierungsverlauf</h2>
          <div class="obj-explain">
            <p>
              Aktueller Entwurf:
              <strong id="objCurrent">–</strong> ${UNIT_CO2}
              <span id="objFeasibleBadge" class="feas-badge" hidden></span>
            </p>
            <p>
              Bester zulässiger Entwurf:
              <strong id="objBest">–</strong> ${UNIT_CO2}
            </p>
            <p class="obj-trial">
              Iteration: <strong id="trialVal">–</strong> von
              <strong id="trialTotal">–</strong>
            </p>
          </div>
          <div id="chart"></div>
        </section>
        <aside class="info-box">
          <h3>Darstellung des Optimierungsverlaufs</h3>
          <p>
            Die Punkte zeigen die bewerteten Entwürfe. Grau kennzeichnet unzulässige
            Entwürfe mit nicht erfüllten Nachweisen, blaue Punkte kennzeichnen
            zulässige Entwürfe, die alle Nachweise erfüllen. Die rote Linie zeigt das
            niedrigste Treibhausgaspotenzial der bis zur jeweiligen Iteration
            gefundenen zulässigen Entwürfe.
          </p>
        </aside>
      </div>

      <div class="panel-unit">
        <section class="sections-row">
          <div class="section-wrap">
            <h2>Aktueller Entwurf</h2>
            <svg id="sectionCurrent"></svg>
            <h3 class="section-subhead">Zielgröße</h3>
            <p class="objective-value">
              <strong id="gwpCurrent">–</strong> ${UNIT_CO2}
            </p>
            <h3 class="section-subhead">Optimierungsvariablen</h3>
            <div id="statsCurrent" class="section-stats-host"></div>
            <h3 class="section-subhead">Nachweise (Ausnutzung in %)</h3>
            <p class="checks-hint">Ausnutzungen bis einschliesslich 100&nbsp;% gelten als erfüllt.</p>
            <div id="constraintsCurrent" class="constraints-host"></div>
          </div>
          <div class="section-wrap" id="bestPanel">
            <h2>Bester zulässiger Entwurf</h2>
            <p id="bestPlaceholder" class="best-placeholder">
              Noch kein zulässiger Entwurf gefunden.
            </p>
            <div id="bestContent" class="best-content" hidden>
              <svg id="sectionBest"></svg>
              <h3 class="section-subhead">Zielgröße</h3>
              <p class="objective-value">
                <strong id="gwpBest">–</strong> ${UNIT_CO2}
              </p>
              <h3 class="section-subhead">Optimierungsvariablen</h3>
              <div id="statsBest" class="section-stats-host"></div>
              <h3 class="section-subhead">Nachweise (Ausnutzung in %)</h3>
              <p class="checks-hint">Ausnutzungen bis einschliesslich 100&nbsp;% gelten als erfüllt.</p>
              <div id="constraintsBest" class="constraints-host"></div>
            </div>
          </div>
        </section>
        <aside class="info-box">
          <h3>Vergleich der Entwürfe</h3>
          <p>
            Links ist der aktuelle Entwurf, rechts der beste bisher gefundene zulässige
            Entwurf dargestellt. Zulässige Entwürfe müssen alle Nachweise erfüllen.
          </p>
        </aside>
      </div>
    </main>
  </div>

  <footer class="footer">
    <p>
      Vorstudie: Fachgebiet Entwerfen und Konstruieren – Massivbau, Technische
      Universität Berlin. Kontakt:
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
const gwpCurrentEl = document.querySelector<HTMLElement>('#gwpCurrent')!
const gwpBestEl = document.querySelector<HTMLElement>('#gwpBest')!
const objFeasibleBadge = document.querySelector<HTMLElement>('#objFeasibleBadge')!
const trialVal = document.querySelector<HTMLElement>('#trialVal')!
const trialTotal = document.querySelector<HTMLElement>('#trialTotal')!
const constraintsCurrentEl = document.querySelector<HTMLElement>('#constraintsCurrent')!
const constraintsBestEl = document.querySelector<HTMLElement>('#constraintsBest')!
const bestPlaceholder = document.querySelector<HTMLElement>('#bestPlaceholder')!
const bestContent = document.querySelector<HTMLElement>('#bestContent')!
const chart = createObjectiveChart(document.querySelector<HTMLElement>('#chart')!)

let abort: AbortController | null = null
let lastCurrentUtil: Record<string, number> | undefined
let nTrialsTotal = 0
let stoppedByUser = false

drawCrossSection(sectionCurrentEl, null, {
  idPrefix: 'cur',
  ariaLabel: 'Querschnitt aktueller Entwurf',
  statsEl: statsCurrentEl,
})
constraintsCurrentEl.innerHTML = '<p class="empty">Noch keine Auswertung.</p>'
showBestEmpty()

/** Objective / GWP values shown to users: one decimal place. */
function fmtY(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '–'
  return n.toLocaleString('de-DE', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })
}

function fmtPct(u: number): string {
  return (u * 100).toLocaleString('de-DE', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })
}

function isOk(u: number): boolean {
  return u <= 1 + FEAS_TOL
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

function showBestEmpty() {
  bestPlaceholder.hidden = false
  bestContent.hidden = true
  constraintsBestEl.innerHTML = ''
  statsBestEl.innerHTML = ''
  gwpBestEl.textContent = '–'
}

function showBestDesign(best: BestState) {
  bestPlaceholder.hidden = true
  bestContent.hidden = false
  gwpBestEl.textContent = fmtY(best.y)
  drawCrossSection(sectionBestEl, best.geometry, {
    idPrefix: 'best',
    ariaLabel: 'Querschnitt bester zulässiger Entwurf',
    statsEl: statsBestEl,
  })
  renderConstraintsInto(constraintsBestEl, best.utilizations)
}

function setFeasibleBadge(feasible: boolean | null) {
  if (feasible == null) {
    objFeasibleBadge.hidden = true
    objFeasibleBadge.textContent = ''
    objFeasibleBadge.className = 'feas-badge'
    return
  }
  objFeasibleBadge.hidden = false
  objFeasibleBadge.textContent = feasible ? 'zulässig' : 'nicht zulässig'
  objFeasibleBadge.className = `feas-badge ${feasible ? 'ok' : 'bad'}`
}

function renderConstraintsInto(
  el: HTMLElement,
  util: Record<string, number> | undefined,
) {
  if (!util || !Object.keys(util).length) {
    el.innerHTML = '<p class="empty">Noch keine Auswertung.</p>'
    return
  }

  const shown: { label: string; u: number; ok: boolean }[] = []
  for (const group of CONSTRAINT_GROUPS) {
    for (const item of group.items) {
      const u = maxUtil(util, item.key)
      if (u == null) continue
      shown.push({ label: item.label, u, ok: isOk(u) })
    }
  }

  const failed = shown.filter((r) => !r.ok).length
  const total = shown.length
  const summary =
    total === 0
      ? ''
      : failed === 0
        ? '<p class="checks-summary ok">Alle Nachweise erfüllt</p>'
        : `<p class="checks-summary bad">${failed} von ${total} Nachweisen nicht erfüllt</p>`

  const groups = CONSTRAINT_GROUPS.map((group) => {
    const rows = group.items
      .map((item) => {
        const u = maxUtil(util, item.key)
        if (u == null) return ''
        const ok = isOk(u)
        const title = ok
          ? 'Nachweis erfüllt: Ausnutzung ≤ 100 %'
          : 'Nachweis nicht erfüllt: Ausnutzung > 100 %'
        const text = ok
          ? `${fmtPct(u)} % – erfüllt`
          : `${fmtPct(u)} % – nicht erfüllt`
        return `<div class="check-row">
          <span class="check-label">${item.label}</span>
          <span class="pill ${ok ? 'ok' : 'bad'}" title="${title}">${text}</span>
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
    summary +
    (groups || '<p class="empty">Keine Nachweise in dieser Auswertung.</p>')
}

function renderConstraints(
  current: Record<string, number> | undefined,
  best: Record<string, number> | undefined,
) {
  renderConstraintsInto(constraintsCurrentEl, current)
  if (best) renderConstraintsInto(constraintsBestEl, best)
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
    nTrialsTotal = ev.n_trials
    trialTotal.textContent = String(ev.n_trials)
    trialVal.textContent = '0'
    statusEl.textContent = `Optimierung läuft · 0 von ${ev.n_trials} Iterationen`
    return
  }
  if (ev.type === 'trial') {
    const i = ev.trial + 1
    trialVal.textContent = String(i)
    trialTotal.textContent = String(nTrialsTotal || '–')
    objCurrentEl.textContent = fmtY(ev.y)
    gwpCurrentEl.textContent = fmtY(ev.y)
    setFeasibleBadge(ev.is_feasible)

    const bf = ev.bestFeasible
    if (bf) {
      objBestEl.textContent = fmtY(bf.y)
      showBestDesign(bf)
    } else {
      objBestEl.textContent = '–'
      showBestEmpty()
    }

    drawCrossSection(sectionCurrentEl, ev.geometry, {
      idPrefix: 'cur',
      ariaLabel: 'Querschnitt aktueller Entwurf',
      statsEl: statsCurrentEl,
    })

    chart.push({
      trial: ev.trial,
      y: ev.y,
      feasible: ev.is_feasible,
      bestFeasibleY: bf?.y ?? null,
    })

    renderConstraints(ev.utilizations, bf?.utilizations)
    lastCurrentUtil = ev.utilizations

    if (ev.is_best_feasible) {
      statusEl.textContent = `Iteration ${i} von ${nTrialsTotal} · neuer bester zulässiger Entwurf`
    } else if (!bf) {
      statusEl.textContent = `Iteration ${i} von ${nTrialsTotal} · noch keine zulässige Lösung`
    } else {
      statusEl.textContent = `Iteration ${i} von ${nTrialsTotal}`
    }
    return
  }
  if (ev.type === 'done') {
    if (stoppedByUser) {
      statusEl.textContent = 'Optimierung gestoppt · Ergebnis vorläufig.'
    } else if (ev.bestFeasible) {
      statusEl.textContent = `Fertig · bester zulässiger Entwurf: ${fmtY(ev.bestFeasible.y)} ${UNIT_CO2}`
      objBestEl.textContent = fmtY(ev.bestFeasible.y)
      showBestDesign(ev.bestFeasible)
      renderConstraints(lastCurrentUtil, ev.bestFeasible.utilizations)
    } else {
      statusEl.textContent = 'Fertig · keine zulässige Lösung gefunden.'
      objBestEl.textContent = '–'
      showBestEmpty()
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
  stoppedByUser = false
  startBtn.disabled = true
  stopBtn.disabled = false
  chart.reset()
  objCurrentEl.textContent = '–'
  objBestEl.textContent = '–'
  gwpCurrentEl.textContent = '–'
  gwpBestEl.textContent = '–'
  setFeasibleBadge(null)
  trialVal.textContent = '–'
  trialTotal.textContent = '–'
  lastCurrentUtil = undefined
  statusEl.textContent = 'Starte Optimierung…'
  drawCrossSection(sectionCurrentEl, null, {
    idPrefix: 'cur',
    statsEl: statsCurrentEl,
  })
  showBestEmpty()
  constraintsCurrentEl.innerHTML = '<p class="empty">Noch keine Auswertung.</p>'

  try {
    await runOptimize(readRequest(), onEvent, abort.signal)
    if (stoppedByUser && !statusEl.textContent?.startsWith('Optimierung gestoppt')) {
      statusEl.textContent = 'Optimierung gestoppt · Ergebnis vorläufig.'
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      statusEl.textContent = 'Optimierung gestoppt · Ergebnis vorläufig.'
    } else {
      statusEl.textContent = `Fehler: ${err instanceof Error ? err.message : String(err)}`
    }
  } finally {
    startBtn.disabled = false
    stopBtn.disabled = true
  }
})

stopBtn.addEventListener('click', () => {
  stoppedByUser = true
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
