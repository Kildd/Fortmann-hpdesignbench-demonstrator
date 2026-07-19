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

const PYODIDE_INDEX = 'https://cdn.jsdelivr.net/pyodide/v0.27.5/full/'

let pyodidePromise: Promise<PyodideInterface> | null = null

async function getPyodide(): Promise<PyodideInterface> {
  if (!pyodidePromise) {
    pyodidePromise = (async () => {
      // Module workers cannot use importScripts(); load the ESM build instead.
      const { loadPyodide } = await import(
        /* @vite-ignore */ `${PYODIDE_INDEX}pyodide.mjs`
      )
      const pyodide = (await loadPyodide({
        indexURL: PYODIDE_INDEX,
      })) as PyodideInterface
      await pyodide.loadPackage([
        'numpy',
        'scipy',
        'shapely',
        'micropip',
        'sqlite3',
      ])
      return pyodide
    })()
  }
  return pyodidePromise
}

async function fetchText(url: string): Promise<string> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`Fetch failed: ${url}`)
  return res.text()
}

async function listEngineFiles(base: string): Promise<string[]> {
  const res = await fetch(`${base}engine/manifest.json`)
  if (!res.ok) {
    throw new Error(
      'engine/manifest.json fehlt – bitte npm run sync:engine / docs neu bauen.',
    )
  }
  return (await res.json()) as string[]
}

async function mountEngine(
  pyodide: PyodideInterface,
  base: string,
): Promise<void> {
  const files = await listEngineFiles(base)
  pyodide.FS.mkdirTree('/home/pyodide/engine')
  for (const rel of files) {
    const text = await fetchText(`${base}engine/${rel}`)
    const target = `/home/pyodide/engine/${rel}`
    const dir = target.slice(0, target.lastIndexOf('/'))
    pyodide.FS.mkdirTree(dir)
    pyodide.FS.writeFile(target, text)
  }
}

self.onmessage = async (
  ev: MessageEvent<{ req: OptimizeRequest; base: string }>,
) => {
  const { req, base } = ev.data
  const post = (msg: OptEvent) => self.postMessage(msg)

  try {
    post({ type: 'status', message: 'Pyodide wird geladen…' })
    const pyodide = await getPyodide()

    // Bridge: Python emits JSON strings; we forward parsed events to the UI.
    pyodide.globals.set('js_emit_json', (payload: string) => {
      post(JSON.parse(payload) as OptEvent)
    })

    post({ type: 'status', message: 'Engine wird gemountet…' })
    await mountEngine(pyodide, base)

    post({ type: 'status', message: 'Python-Pakete werden installiert…' })
    await pyodide.runPythonAsync(`
import sys, types
# structuralcodes imports triangle for the fiber integrator mesh path.
# We stub it if the wasm wheel is unavailable; HP sections request fiber
# and fall back only if triangulation is actually invoked.
if 'triangle' not in sys.modules:
    tri = types.ModuleType('triangle')
    def _triangulate(*args, **kwargs):
        raise RuntimeError('triangle stub: Fiber-Integrator mesh nicht verfügbar')
    tri.triangulate = _triangulate
    sys.modules['triangle'] = tri

import micropip
await micropip.install(['structuralcodes==0.7.1', 'optuna==4.2.1', 'tabulate==0.9.0'])
`)

    post({ type: 'status', message: 'TPE-Optimierung startet…' })

    const nTrials = Number(req.nTrials)
    const omegaGwp = Number(req.omegaGwp)
    const omegaCost = Number(req.omegaCost)
    const spanMm = Number(req.spanMm)
    const seed = Number(req.seed)
    const loadCategory = JSON.stringify(req.loadCategory)

    await pyodide.runPythonAsync(`
import sys, json
sys.path.insert(0, "/home/pyodide/engine")
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
  } catch (err) {
    post({
      type: 'error',
      message: err instanceof Error ? err.message : String(err),
    })
  }
}
