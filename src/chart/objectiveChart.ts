import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

export type ChartPoint = {
  trial: number
  /** Physical objective y (not penalized y_p). */
  y: number | null
  feasible: boolean
  /** Running best physical y among feasible designs so far, or null. */
  bestFeasibleY: number | null
}

const Y_MAX = 1000
const X_MIN_SPAN = 10
const UNIT_CO2 = 'kg CO₂-Äq./m²'

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
  /** x, feasible y, infeasible y, bestFeasible step */
  const data: [
    number[],
    (number | null | undefined)[],
    (number | null | undefined)[],
    (number | null | undefined)[],
  ] = [[], [], [], []]

  const rawY: (number | null)[] = []
  const feasibleFlags: boolean[] = []
  const rawBest: (number | null)[] = []

  const opts: uPlot.Options = {
    width: el.clientWidth || 480,
    height: 260,
    padding: [10, 12, 8, 8],
    scales: {
      x: {
        time: false,
        range: (_u, _min, max) => {
          if (max == null || !Number.isFinite(max)) return [1, X_MIN_SPAN]
          return [1, Math.max(X_MIN_SPAN, max)]
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
        label: 'Zulässiger Entwurf',
        stroke: 'rgba(0,0,0,0)',
        width: 0,
        points: {
          show: true,
          size: 7,
          width: 1,
          stroke: '#1f91cc',
          fill: '#1f91cc',
        },
      },
      {
        label: 'Nicht zulässiger Entwurf',
        stroke: 'rgba(0,0,0,0)',
        width: 0,
        points: {
          show: true,
          size: 7,
          width: 1,
          stroke: '#b8c0c4',
          fill: '#c5c9cd',
        },
      },
      {
        label: 'Bester zulässiger Entwurf',
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
        font: '12px "IBM Plex Sans", "Segoe UI", sans-serif',
        labelFont: '13px "IBM Plex Sans", "Segoe UI", sans-serif',
        values: (_u, splits) => splits.map((v) => String(Math.round(v))),
      },
      {
        label: UNIT_CO2,
        labelSize: 18,
        size: 78,
        stroke: '#434343',
        grid: { stroke: 'rgba(67,67,67,0.12)' },
        ticks: { stroke: 'rgba(67,67,67,0.2)' },
        font: '12px "IBM Plex Sans", "Segoe UI", sans-serif',
        labelFont: '13px "IBM Plex Sans", "Segoe UI", sans-serif',
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
            const yVal = rawY[i]
            if (yVal == null || yVal <= Y_MAX) continue
            const x = u.valToPos(data[0][i], 'x', true)
            const color = feasibleFlags[i] ? '#1f91cc' : '#a8adb2'
            drawUpArrow(ctx, x, top + 1, color)
          }
          for (let i = 0; i < data[0].length; i++) {
            const b = rawBest[i]
            if (b != null && b > Y_MAX) {
              const x = u.valToPos(data[0][i], 'x', true)
              drawUpArrow(ctx, x + 4, top + 1, '#c40d20')
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
      data[3] = []
      rawY.length = 0
      feasibleFlags.length = 0
      rawBest.length = 0
      plot.setData(data)
    },
    push(p: ChartPoint) {
      const clamped = clampY(p.y)
      data[0].push(p.trial + 1)
      data[1].push(p.feasible ? clamped : null)
      data[2].push(p.feasible ? null : clamped)
      data[3].push(clampY(p.bestFeasibleY))
      rawY.push(p.y)
      feasibleFlags.push(p.feasible)
      rawBest.push(p.bestFeasibleY)
      plot.setData(data)
    },
    destroy() {
      window.removeEventListener('resize', resize)
      plot.destroy()
    },
  }
}
