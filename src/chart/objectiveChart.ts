import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

export type ChartPoint = {
  trial: number
  /** Objective value of the current iteration (optimizer metric). */
  current: number | null
  /** Best-so-far objective value. */
  best: number | null
}

const Y_MAX = 1000

function clampY(v: number | null): number | null {
  if (v == null || !Number.isFinite(v)) return null
  return Math.min(v, Y_MAX)
}

function drawUpArrow(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  color: string,
): void {
  const h = 7
  const half = 4.5
  ctx.beginPath()
  ctx.moveTo(x, y)
  ctx.lineTo(x - half, y + h)
  ctx.lineTo(x + half, y + h)
  ctx.closePath()
  ctx.fillStyle = color
  ctx.fill()
}

export function createObjectiveChart(el: HTMLElement) {
  const data: [
    number[],
    (number | null | undefined)[],
    (number | null | undefined)[],
  ] = [[], [], []]

  /** Raw values (unclamped) for overflow markers. */
  const rawCurrent: (number | null)[] = []
  const rawBest: (number | null)[] = []
  let bestValue: number | null = null

  const opts: uPlot.Options = {
    width: el.clientWidth || 480,
    height: 260,
    padding: [10, 12, 8, 8],
    scales: {
      x: {
        time: false,
        auto: false,
        // Keep 1…10 until enough iterations exist; avoids odd zoom with few points.
        range: (_u, _dataMin, dataMax) => {
          if (!Number.isFinite(dataMax) || (dataMax as number) < 10) {
            return [1, 10]
          }
          return [1, dataMax as number]
        },
      },
      y: {
        auto: false,
        range: [0, Y_MAX],
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
        font: '11px "IBM Plex Sans", "Segoe UI", sans-serif',
        labelFont: '12px "IBM Plex Sans", "Segoe UI", sans-serif',
        values: (_u, splits) => splits.map((v) => String(Math.round(v))),
      },
      {
        label: 'kg CO₂-äquivalent/m²',
        labelSize: 18,
        size: 72,
        stroke: '#434343',
        grid: { stroke: 'rgba(67,67,67,0.12)' },
        ticks: { stroke: 'rgba(67,67,67,0.2)' },
        font: '11px "IBM Plex Sans", "Segoe UI", sans-serif',
        labelFont: '12px "IBM Plex Sans", "Segoe UI", sans-serif',
        values: (_u, splits) =>
          splits.map((v) =>
            Number.isFinite(v)
              ? v.toLocaleString('de-DE', { maximumFractionDigits: 0 })
              : '',
          ),
      },
    ],
    legend: { show: true },
    hooks: {
      draw: [
        (u) => {
          const { ctx, bbox } = u
          const top = bbox.top
          ctx.save()
          for (let i = 0; i < data[0].length; i++) {
            const xVal = data[0][i]
            const x = u.valToPos(xVal, 'x', true)
            const cur = rawCurrent[i]
            const best = rawBest[i]
            if (cur != null && cur > Y_MAX) {
              drawUpArrow(ctx, x - 3, top + 1, '#1f91cc')
            }
            if (best != null && best > Y_MAX) {
              drawUpArrow(ctx, x + 3, top + 1, '#c40d20')
            }
          }
          ctx.restore()
        },
      ],
    },
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
      rawCurrent.length = 0
      rawBest.length = 0
      bestValue = null
      plot.setData(data)
    },
    push(p: ChartPoint) {
      if (p.best != null && Number.isFinite(p.best)) bestValue = p.best
      data[0].push(p.trial + 1)
      data[1].push(clampY(p.current))
      data[2].push(clampY(bestValue))
      rawCurrent.push(p.current)
      rawBest.push(bestValue)
      plot.setData(data)
    },
    destroy() {
      window.removeEventListener('resize', resize)
      plot.destroy()
    },
  }
}
