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

async function fetchText(url: string): Promise<string> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`Fetch failed: ${url}`)
  return res.text()
}

async function mountEngine(base: string, pd: PyodideInterface): Promise<void> {
  const res = await fetch(`${base}engine/manifest.json`)
  if (!res.ok) {
    throw new Error(
      'engine/manifest.json fehlt – bitte docs neu bauen (npm run build).',
    )
  }
  const files = (await res.json()) as string[]
  pd.FS.mkdirTree('/home/pyodide/engine')
  for (const rel of files) {
    const text = await fetchText(`${base}engine/${rel}`)
    const target = `/home/pyodide/engine/${rel}`
    pd.FS.mkdirTree(target.slice(0, target.lastIndexOf('/')))
    pd.FS.writeFile(target, text)
  }
}

async function initEngine(base: string): Promise<void> {
  post({ type: 'status', message: 'Pyodide wird geladen (einmalig)…' })
  const pd = await getPyodide()

  post({ type: 'status', message: 'NumPy / SciPy / Shapely…' })
  await pd.loadPackage(['numpy', 'scipy', 'shapely', 'micropip', 'sqlite3'])

  post({ type: 'status', message: 'HP-Engine wird gemountet…' })
  await mountEngine(base, pd)

  pd.globals.set('js_emit_json', (payload: string) => {
    post(JSON.parse(payload) as OptEvent)
  })

  post({ type: 'status', message: 'Python-Pakete (structuralcodes, Optuna)…' })
  // triangle has no Pyodide wheel — stub it, then install structuralcodes WITHOUT deps.
  await pd.runPythonAsync(`
import sys, types

if 'triangle' not in sys.modules:
    tri = types.ModuleType('triangle')
    def _triangulate(*args, **kwargs):
        raise RuntimeError('triangle nicht in Pyodide verfügbar')
    tri.triangulate = _triangulate
    sys.modules['triangle'] = tri

import micropip
# structuralcodes declares triangle as dependency; skip deps and use our stub + pyodide shapely/numpy/scipy.
await micropip.install('structuralcodes==0.7.1', deps=False)
await micropip.install(['optuna==4.2.1', 'tabulate==0.9.0'])

import sys
sys.path.insert(0, '/home/pyodide/engine')
import demo_optimize  # noqa: F401 — warm import
`)

  ready = true
  post({ type: 'status', message: 'Browser-Engine bereit.' })
  post({ type: 'ready' } as OptEvent)
}

async function runOptimize(req: OptimizeRequest): Promise<void> {
  if (!pyodide || !ready) throw new Error('Engine nicht initialisiert.')
  if (busy) throw new Error('Optimierung läuft bereits.')
  busy = true
  try {
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
