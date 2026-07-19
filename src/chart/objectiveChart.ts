import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

export type ChartPoint = {
  trial: number
  y: number | null
  y_p: number | null
  bestY: number | null
  bestYp: number | null
}

export function createObjectiveChart(el: HTMLElement) {
  const data: [
    number[],
    (number | null | undefined)[],
    (number | null | undefined)[],
  ] = [[], [], []]

  let bestY: number | null = null
  let bestYp: number | null = null

  const yRange = (): { min: number; max: number } => {
    const candidates = [1000]
    if (bestY != null && Number.isFinite(bestY)) candidates.push(bestY * 1.25)
    if (bestYp != null && Number.isFinite(bestYp)) candidates.push(bestYp * 1.25)
    return { min: 0, max: Math.max(...candidates) }
  }

  const opts: uPlot.Options = {
    width: el.clientWidth || 480,
    height: 220,
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
        label: 'y (unbestraft)',
        stroke: '#1f91cc',
        width: 2,
        points: { show: false },
      },
      {
        label: 'y_p (bestraft, best)',
        stroke: '#c40d20',
        width: 2,
        points: { show: false },
      },
    ],
    axes: [
      {
        stroke: '#434343',
        grid: { stroke: 'rgba(67,67,67,0.12)' },
        ticks: { stroke: 'rgba(67,67,67,0.2)' },
        font: '11px "IBM Plex Mono", monospace',
      },
      {
        stroke: '#434343',
        grid: { stroke: 'rgba(67,67,67,0.12)' },
        ticks: { stroke: 'rgba(67,67,67,0.2)' },
        font: '11px "IBM Plex Mono", monospace',
        size: 56,
      },
    ],
    legend: { show: true },
  }

  let plot = new uPlot(opts, data, el)

  const resize = () => {
    plot.setSize({ width: el.clientWidth || 480, height: 220 })
  }
  window.addEventListener('resize', resize)

  return {
    reset() {
      data[0] = []
      data[1] = []
      data[2] = []
      bestY = null
      bestYp = null
      plot.setData(data)
    },
    push(p: ChartPoint) {
      if (p.bestY != null && Number.isFinite(p.bestY)) bestY = p.bestY
      if (p.bestYp != null && Number.isFinite(p.bestYp)) bestYp = p.bestYp
      data[0].push(p.trial)
      data[1].push(p.y)
      // Step series: current best y_p (readable scale follows improvements)
      data[2].push(bestYp)
      plot.setData(data)
    },
    destroy() {
      window.removeEventListener('resize', resize)
      plot.destroy()
    },
  }
}
