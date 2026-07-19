/// <reference lib="webworker" />

import type { OptimizeRequest, OptEvent } from '../types'

declare const self: DedicatedWorkerGlobalScope

type PyodideInterface = {
  loadPackage: (pkgs: string | string[]) => Promise<void>
  runPythonAsync: (code: string) => Promise<unknown>
  globals: {
    set: (name: string, value: unknown) => void
  }
  FS: {
    mkdirTree: (path: string) => void
    writeFile: (path: string, data: string | Uint8Array) => void
  }
}

type WorkerIn =
  | { cmd: 'init'; base: string }
  | { cmd: 'optimize'; req: OptimizeRequest }

const PYODIDE_INDEX = 'https://cdn.jsdelivr.net/pyodide/v0.27.5/full/'
/** Bump when engine files change so GitHub Pages / browser caches cannot serve stale Python. */
const ENGINE_REV = '2026-07-19i'

let pyodide: PyodideInterface | null = null
let ready = false
let busy = false

const post = (msg: OptEvent) => self.postMessage(msg)

async function getPyodide(): Promise<PyodideInterface> {
  if (pyodide) return pyodide
  const { loadPyodide } = await import(
    /* @vite-ignore */ `${PYODIDE_INDEX}pyodide.mjs`
  )
  pyodide = (await loadPyodide({
    indexURL: PYODIDE_INDEX,
  })) as PyodideInterface
  return pyodide
}

function engineUrl(base: string, rel: string): string {
  const sep = rel.includes('?') ? '&' : '?'
  return `${base}engine/${rel}${sep}v=${ENGINE_REV}`
}

async function fetchJson<T>(url: string, retries = 3): Promise<T> {
  let lastErr: unknown
  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      const res = await fetch(url, { cache: 'no-store' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return (await res.json()) as T
    } catch (err) {
      lastErr = err
      if (attempt < retries) {
        await new Promise((r) => setTimeout(r, 250 * attempt))
      }
    }
  }
  throw new Error(
    `Fetch failed: ${url}${lastErr instanceof Error ? ` (${lastErr.message})` : ''}`,
  )
}

async function mountEngine(base: string, pd: PyodideInterface): Promise<void> {
  post({ type: 'status', message: 'HP-Engine-Bundle wird geladen…' })
  const files = await fetchJson<Record<string, string>>(
    engineUrl(base, 'bundle.json'),
  )
  const entries = Object.entries(files)
  pd.FS.mkdirTree('/home/pyodide/engine')
  let done = 0
  for (const [rel, text] of entries) {
    const target = `/home/pyodide/engine/${rel}`
    const slash = target.lastIndexOf('/')
    if (slash > 0) pd.FS.mkdirTree(target.slice(0, slash))
    pd.FS.writeFile(target, text)
    done += 1
    if (done % 40 === 0 || done === entries.length) {
      post({
        type: 'status',
        message: `HP-Engine wird gemountet… (${done}/${entries.length})`,
      })
    }
  }
}

async function initEngine(base: string): Promise<void> {
  post({ type: 'status', message: 'Pyodide wird geladen (einmalig)…' })
  const pd = await getPyodide()

  post({ type: 'status', message: 'NumPy / SciPy / Shapely…' })
  await pd.loadPackage(['numpy', 'scipy', 'shapely'])

  post({ type: 'status', message: 'HP-Engine wird gemountet…' })
  await mountEngine(base, pd)

  bindEmitBridge(pd)

  // No micropip: structuralcodes is vendored under engine/vendor,
  // TPE is engine/tpe_simple.py (no Optuna).
  post({ type: 'status', message: 'Python-Module werden vorgewärmt…' })
  await pd.runPythonAsync(`
import sys
sys.path.insert(0, '/home/pyodide/engine/vendor')
sys.path.insert(0, '/home/pyodide/engine')
import demo_optimize  # noqa: F401
`)

  ready = true
  post({ type: 'status', message: 'Browser-Engine bereit.' })
  post({ type: 'ready' } as OptEvent)
}

/** Expose emit callback on JS globalThis so Python can call it via `from js import …`. */
function bindEmitBridge(pd: PyodideInterface): void {
  const emit = (payload: string) => {
    post(JSON.parse(payload) as OptEvent)
  }
  ;(globalThis as unknown as { js_emit_json: (payload: string) => void }).js_emit_json =
    emit
  pd.globals.set('js_emit_json', emit)
}

async function runOptimize(req: OptimizeRequest): Promise<void> {
  if (!pyodide || !ready) throw new Error('Engine nicht initialisiert.')
  if (busy) throw new Error('Optimierung läuft bereits.')
  busy = true
  try {
    bindEmitBridge(pyodide)
    const nTrials = Number(req.nTrials)
    const omegaGwp = Number(req.omegaGwp)
    const omegaCost = Number(req.omegaCost)
    const spanMm = Number(req.spanMm)
    const seed = Number(req.seed)
    const loadCategory = JSON.stringify(req.loadCategory)

    await pyodide.runPythonAsync(`
import json
import demo_optimize
from js import js_emit_json

def _emit(obj):
    js_emit_json(json.dumps(obj))

demo_optimize._emit = _emit
demo_optimize.run_tpe(
    n_trials=${nTrials},
    omega_gwp=${omegaGwp},
    omega_cost=${omegaCost},
    span_mm=${spanMm},
    load_category=${loadCategory},
    seed=${seed},
)
`)
  } finally {
    busy = false
  }
}

self.onmessage = async (ev: MessageEvent<WorkerIn>) => {
  const data = ev.data
  try {
    if (data.cmd === 'init') {
      if (ready) {
        post({ type: 'status', message: 'Browser-Engine bereit.' })
        post({ type: 'ready' } as OptEvent)
        return
      }
      await initEngine(data.base)
      return
    }
    if (data.cmd === 'optimize') {
      await runOptimize(data.req)
      return
    }
  } catch (err) {
    busy = false
    post({
      type: 'error',
      message: err instanceof Error ? err.message : String(err),
    })
  }
}
