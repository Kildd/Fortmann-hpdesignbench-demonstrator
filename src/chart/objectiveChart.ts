import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

export type ChartPoint = {
  trial: number
  /** Objective value of the current iteration (optimizer metric). */
  current: number | null
  /** Best-so-far objective value. */
  best: number | null
}

export function createObjectiveChart(el: HTMLElement) {
  const data: [
    number[],
    (number | null | undefined)[],
    (number | null | undefined)[],
  ] = [[], [], []]

  let bestValue: number | null = null

  const yRange = (): { min: number; max: number } => {
    const candidates = [1000]
    for (const v of data[1]) {
      if (typeof v === 'number' && Number.isFinite(v)) candidates.push(v * 1.25)
    }
    if (bestValue != null && Number.isFinite(bestValue)) {
      candidates.push(bestValue * 1.25)
    }
    return { min: 0, max: Math.max(...candidates) }
  }

  const opts: uPlot.Options = {
    width: el.clientWidth || 480,
    height: 260,
    padding: [8, 12, 8, 8],
    scales: {
      x: { time: false },
      y: {
        auto: false,
        range: () => {
          const r = yRange()
          return [r.min, r.max]
        },
      },
    },
    series: [
      {},
      {
        label: 'Aktuelle Iteration',
        stroke: '#1f91cc',
        width: 2,
        points: { show: false },
      },
      {
        label: 'Bestes Ergebnis',
        stroke: '#c40d20',
        width: 2,
        points: { show: false },
      },
    ],
    axes: [
      {
        label: 'Iteration',
        labelSize: 18,
        stroke: '#434343',
        grid: { stroke: 'rgba(67,67,67,0.12)' },
        ticks: { stroke: 'rgba(67,67,67,0.2)' },
        font: '11px "IBM Plex Mono", monospace',
        values: (_u, splits) => splits.map((v) => String(Math.round(v))),
      },
      {
        label: 'kg CO₂-äquivalent/m²',
        labelSize: 18,
        size: 72,
        stroke: '#434343',
        grid: { stroke: 'rgba(67,67,67,0.12)' },
        ticks: { stroke: 'rgba(67,67,67,0.2)' },
        font: '11px "IBM Plex Mono", monospace',
        values: (_u, splits) =>
          splits.map((v) =>
            Number.isFinite(v)
              ? v.toLocaleString('de-DE', { maximumFractionDigits: 0 })
              : '',
          ),
      },
    ],
    legend: { show: true },
  }

  const plot = new uPlot(opts, data, el)

  const resize = () => {
    plot.setSize({ width: el.clientWidth || 480, height: 260 })
  }
  window.addEventListener('resize', resize)

  return {
    reset() {
      data[0] = []
      data[1] = []
      data[2] = []
      bestValue = null
      plot.setData(data)
    },
    push(p: ChartPoint) {
      if (p.best != null && Number.isFinite(p.best)) bestValue = p.best
      data[0].push(p.trial + 1)
      data[1].push(p.current)
      data[2].push(bestValue)
      plot.setData(data)
    },
    destroy() {
      window.removeEventListener('resize', resize)
      plot.destroy()
    },
  }
}
