/// <reference lib="webworker" />

import type { OptimizeRequest, OptEvent } from '../types'

declare const self: DedicatedWorkerGlobalScope

type PyodideInterface = {
  loadPackage: (pkgs: string | string[]) => Promise<void>
  runPythonAsync: (code: string) => Promise<unknown>
  FS: {
    mkdirTree: (path: string) => void
    writeFile: (path: string, data: string | Uint8Array) => void
  }
  unpackArchive?: (data: ArrayBuffer, format: string) => void
}

let pyodidePromise: Promise<PyodideInterface> | null = null

async function getPyodide(): Promise<PyodideInterface> {
  if (!pyodidePromise) {
    pyodidePromise = (async () => {
      importScripts('https://cdn.jsdelivr.net/pyodide/v0.27.5/full/pyodide.js')
      // @ts-expect-error loadPyodide from importScripts
      const pyodide = (await loadPyodide({
        indexURL: 'https://cdn.jsdelivr.net/pyodide/v0.27.5/full/',
      })) as PyodideInterface
      await pyodide.loadPackage(['numpy', 'scipy', 'shapely', 'micropip', 'sqlite3'])
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
  // We sync a manifest at build time; fall back to known roots via recursive fetch of index is not available on GH pages.
  const res = await fetch(`${base}engine/manifest.json`)
  if (!res.ok) throw new Error('engine/manifest.json fehlt – bitte npm run sync:engine ausführen.')
  return (await res.json()) as string[]
}

async function mountEngine(pyodide: PyodideInterface, base: string): Promise<void> {
  const files = await listEngineFiles(base)
  pyodide.FS.mkdirTree('/home/pyodide/engine')
  for (const rel of files) {
    const url = `${base}engine/${rel}`
    const text = await fetchText(url)
    const target = `/home/pyodide/engine/${rel}`
    const dir = target.slice(0, target.lastIndexOf('/'))
    pyodide.FS.mkdirTree(dir)
    pyodide.FS.writeFile(target, text)
  }
}

self.onmessage = async (ev: MessageEvent<{ req: OptimizeRequest; base: string }>) => {
  const { req, base } = ev.data
  const post = (msg: OptEvent) => self.postMessage(msg)

  try {
    post({ type: 'status', message: 'Pyodide wird geladen…' })
    const pyodide = await getPyodide()

    post({ type: 'status', message: 'Engine wird gemountet…' })
    await mountEngine(pyodide, base)

    post({ type: 'status', message: 'Python-Pakete werden installiert…' })
    await pyodide.runPythonAsync(`
import sys, types
# structuralcodes importiert triangle nur für den Fiber-Integrator;
# die HP-Analyse nutzt den Marin-Integrator.
if 'triangle' not in sys.modules:
    tri = types.ModuleType('triangle')
    def _triangulate(*args, **kwargs):
        raise RuntimeError('triangle stub: Fiber-Integrator nicht verfügbar')
    tri.triangulate = _triangulate
    sys.modules['triangle'] = tri

import micropip
await micropip.install(['structuralcodes==0.7.1', 'optuna==4.2.1', 'tabulate==0.9.0'])
`)

    post({ type: 'status', message: 'TPE-Optimierung startet…' })

    const code = `
import sys, json
sys.path.insert(0, "/home/pyodide/engine")
from demo_optimize import run_tpe

class Emitter:
    def write(self, s):
        s = s.strip()
        if not s:
            return
        for line in s.splitlines():
            line = line.strip()
            if line:
                from js import self as js_self
                js_self.postMessage(json.loads(line))
    def flush(self):
        pass

import demo_optimize
_orig = demo_optimize._emit

def _emit(obj):
    from js import self as js_self
    js_self.postMessage(obj)

demo_optimize._emit = _emit

run_tpe(
    n_trials=${Number(req.nTrials)},
    omega_gwp=${Number(req.omegaGwp)},
    omega_cost=${Number(req.omegaCost)},
    span_mm=${Number(req.spanMm)},
    load_category=${JSON.stringify(req.loadCategory)},
    seed=${Number(req.seed)},
)
`
    await pyodide.runPythonAsync(code)
  } catch (err) {
    post({
      type: 'error',
      message: err instanceof Error ? err.message : String(err),
    })
  }
}
