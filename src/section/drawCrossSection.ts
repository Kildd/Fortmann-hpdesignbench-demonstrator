import type { GeometryState } from '../types'

function num(v: number | undefined, fallback: number): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : fallback
}

type Pt = { y: number; z: number }

/** Mid-span HP shell section (x = 0): z = 4 Hy y² / B², thickness along surface normal. */
function shellPolygon(B: number, Hy: number, t: number, n = 64): Pt[] {
  const ys: number[] = []
  for (let i = 0; i < n; i++) ys.push(-B / 2 + (B * i) / (n - 1))

  const zsMid = ys.map((y) => (4 * Hy * y * y) / (B * B))
  const normals = ys.map((y) => {
    const dzdy = (8 * Hy * y) / (B * B)
    const len = Math.hypot(dzdy, 1)
    return { ny: -dzdy / len, nz: 1 / len }
  })

  const t2 = t / 2
  const bottom = ys.map((y, i) => ({
    y: y - normals[i].ny * t2,
    z: zsMid[i] - normals[i].nz * t2,
  }))
  const top = ys.map((y, i) => ({
    y: y + normals[i].ny * t2,
    z: zsMid[i] + normals[i].nz * t2,
  }))
  return [...bottom, ...top.reverse()]
}

/** Tendon (y,z) at mid-span — same layout idea as HPGeometry (2 · n_t bars). */
function tendonPoints(B: number, L: number, Hx: number, Hy: number, dy: number, nt: number): Pt[] {
  const n = Math.max(1, Math.round(nt))
  const xp = (L / 2) * (1 + Math.sqrt(Hy) / Math.sqrt(Hx))
  const yp = (B / 2) * (1 + Math.sqrt(Hx) / Math.sqrt(Hy))
  const zp = (Math.sqrt(Hx) + Math.sqrt(Hy)) ** 2

  let alphaEdge = 0.5 * ((-B / 2 + dy) / yp + L / 2 / xp + 1)
  let alphaEdgeBar = 1 - alphaEdge
  if (alphaEdge > 0.5) alphaEdgeBar = 0.5

  const alphas: number[] = []
  if (n === 1) {
    alphas.push(0.5)
  } else {
    const dAlpha = (alphaEdgeBar - alphaEdge) / (n - 1)
    for (let i = 0; i < n; i++) alphas.push(alphaEdge + dAlpha * i)
  }

  // At mid-span x = 0: interpolate between tendon ends at ±L/2
  const pts: Pt[] = []
  for (const alpha of alphas) {
    const y0 = (-L / 2 / xp + 2 * alpha - 1) * yp
    const y1 = (L / 2 / xp + 2 * alpha - 1) * yp
    const z0 =
      (4 * alpha * (-L / 2) / xp -
        2 * (-L / 2) / xp +
        4 * alpha ** 2 -
        4 * alpha +
        1) *
      zp
    const z1 =
      (4 * alpha * (L / 2) / xp - 2 * (L / 2) / xp + 4 * alpha ** 2 - 4 * alpha + 1) * zp
    const y = 0.5 * (y0 + y1)
    const z = 0.5 * (z0 + z1)
    pts.push({ y, z })
    pts.push({ y: -y, z }) // mirrored group
  }
  return pts
}

export type DrawSectionOptions = {
  ariaLabel?: string
  idPrefix?: string
}

/** Parametric HP mid-span cross-section: shell + reinforcement only. */
export function drawCrossSection(
  svg: SVGSVGElement,
  g: GeometryState | null,
  options: DrawSectionOptions = {},
): void {
  const NS = 'http://www.w3.org/2000/svg'
  while (svg.firstChild) svg.removeChild(svg.firstChild)

  const W = 640
  const H = 360
  const id = options.idPrefix ?? 'sec'
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`)
  svg.setAttribute('role', 'img')
  svg.setAttribute('aria-label', options.ariaLabel ?? 'HP-Schalen-Querschnitt')

  const defs = document.createElementNS(NS, 'defs')
  defs.innerHTML = `
    <linearGradient id="${id}-bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#d9e2e8"/>
      <stop offset="100%" stop-color="#eef2f4"/>
    </linearGradient>
    <linearGradient id="${id}-shell" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#8a939a"/>
      <stop offset="100%" stop-color="#5c656c"/>
    </linearGradient>
  `
  svg.appendChild(defs)

  const bg = document.createElementNS(NS, 'rect')
  bg.setAttribute('width', String(W))
  bg.setAttribute('height', String(H))
  bg.setAttribute('fill', `url(#${id}-bg)`)
  svg.appendChild(bg)

  const span = num(g?.span_mm, 8000)
  const B = num(g?.b_mm, 1350)
  const hGes = num(g?.h_ges_mm, 300)
  const hxRatio = num(g?.hx_hges_ratio, 0.2)
  const Hx = num(g?.hx_mm, hxRatio * hGes)
  const Hy = num(g?.hy_mm, (1 - hxRatio) * hGes)
  const t = num(g?.t_mm, 40)
  const nt = Math.max(1, Math.round(num(g?.nt, 10)))
  const dy = num(g?.dy_mm, 10)
  const aTex = num(g?.a_tex_mm2, 1.81)
  const dBar = Math.sqrt((4 * aTex) / Math.PI)

  const poly = shellPolygon(B, Hy, t)
  const tendons = tendonPoints(B, span, Math.max(Hx, 1e-6), Math.max(Hy, 1e-6), dy, nt)

  let minY = Infinity
  let maxY = -Infinity
  let minZ = Infinity
  let maxZ = -Infinity
  for (const p of [...poly, ...tendons]) {
    minY = Math.min(minY, p.y)
    maxY = Math.max(maxY, p.y)
    minZ = Math.min(minZ, p.z)
    maxZ = Math.max(maxZ, p.z)
  }
  // Include bar radius in bounds
  minZ -= dBar
  maxZ += dBar

  const padX = 36
  const padTop = 28
  const padBot = 36
  const drawW = W - padX * 2
  const drawH = H - padTop - padBot
  const spanY = Math.max(maxY - minY, 1)
  const spanZ = Math.max(maxZ - minZ, 1)
  // Uniform mm scale so height vs width proportions stay correct
  const scale = Math.min(drawW / spanY, drawH / spanZ)

  const midY = (minY + maxY) / 2
  const midZ = (minZ + maxZ) / 2
  const toX = (y: number) => W / 2 + (y - midY) * scale
  // SVG y grows downward; structural z grows upward
  const toY = (z: number) => padTop + drawH / 2 - (z - midZ) * scale

  const d = [
    `M ${toX(poly[0].y)} ${toY(poly[0].z)}`,
    ...poly.slice(1).map((p) => `L ${toX(p.y)} ${toY(p.z)}`),
    'Z',
  ].join(' ')

  const shell = document.createElementNS(NS, 'path')
  shell.setAttribute('d', d)
  shell.setAttribute('fill', `url(#${id}-shell)`)
  shell.setAttribute('stroke', '#2f363b')
  shell.setAttribute('stroke-width', '1.25')
  svg.appendChild(shell)

  const rPx = Math.max(2.2, (dBar / 2) * scale)
  for (const p of tendons) {
    const c = document.createElementNS(NS, 'circle')
    c.setAttribute('cx', String(toX(p.y)))
    c.setAttribute('cy', String(toY(p.z)))
    c.setAttribute('r', String(rPx))
    c.setAttribute('fill', '#c40d20')
    c.setAttribute('stroke', '#7a0814')
    c.setAttribute('stroke-width', '0.8')
    svg.appendChild(c)
  }

  const label = document.createElementNS(NS, 'text')
  label.setAttribute('x', String(padX))
  label.setAttribute('y', String(H - 12))
  label.setAttribute('fill', '#2f363b')
  label.setAttribute('font-family', '"IBM Plex Mono", ui-monospace, monospace')
  label.setAttribute('font-size', '11')
  const kap = num(g?.kap_t_percent, 0)
  const fck = num(g?.fck, 30)
  label.textContent = `H_y=${Hy.toFixed(0)} · t=${t.toFixed(0)} · n_t=${nt} (Σ ${2 * nt}) · d=${dBar.toFixed(1)} · f_ck=${fck} · κ_t=${kap}%`
  svg.appendChild(label)
}
