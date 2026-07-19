let a=null;async function m(){return a||(a=(async()=>{importScripts("https://cdn.jsdelivr.net/pyodide/v0.27.5/full/pyodide.js");const t=await loadPyodide({indexURL:"https://cdn.jsdelivr.net/pyodide/v0.27.5/full/"});return await t.loadPackage(["numpy","scipy","shapely","micropip","sqlite3"]),t})()),a}async function d(t){const e=await fetch(t);if(!e.ok)throw new Error(`Fetch failed: ${t}`);return e.text()}async function p(t){const e=await fetch(`${t}engine/manifest.json`);if(!e.ok)throw new Error("engine/manifest.json fehlt – bitte npm run sync:engine ausführen.");return await e.json()}async function c(t,e){const n=await p(e);t.FS.mkdirTree("/home/pyodide/engine");for(const i of n){const s=`${e}engine/${i}`,r=await d(s),o=`/home/pyodide/engine/${i}`,l=o.slice(0,o.lastIndexOf("/"));t.FS.mkdirTree(l),t.FS.writeFile(o,r)}}self.onmessage=async t=>{const{req:e,base:n}=t.data,i=s=>self.postMessage(s);try{i({type:"status",message:"Pyodide wird geladen…"});const s=await m();i({type:"status",message:"Engine wird gemountet…"}),await c(s,n),i({type:"status",message:"Python-Pakete werden installiert…"}),await s.runPythonAsync(`
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
`),i({type:"status",message:"TPE-Optimierung startet…"});const r=`
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
    n_trials=${Number(e.nTrials)},
    omega_gwp=${Number(e.omegaGwp)},
    omega_cost=${Number(e.omegaCost)},
    span_mm=${Number(e.spanMm)},
    load_category=${JSON.stringify(e.loadCategory)},
    seed=${Number(e.seed)},
)
`;await s.runPythonAsync(r)}catch(s){i({type:"error",message:s instanceof Error?s.message:String(s)})}};
