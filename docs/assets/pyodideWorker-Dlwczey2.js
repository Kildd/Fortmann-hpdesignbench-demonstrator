const m="https://cdn.jsdelivr.net/pyodide/v0.27.5/full/";let r=null;async function u(){return r||(r=(async()=>{const{loadPyodide:t}=await import(`${m}pyodide.mjs`),e=await t({indexURL:m});return await e.loadPackage(["numpy","scipy","shapely","micropip","sqlite3"]),e})()),r}async function y(t){const e=await fetch(t);if(!e.ok)throw new Error(`Fetch failed: ${t}`);return e.text()}async function f(t){const e=await fetch(`${t}engine/manifest.json`);if(!e.ok)throw new Error("engine/manifest.json fehlt – bitte npm run sync:engine / docs neu bauen.");return await e.json()}async function w(t,e){const a=await f(e);t.FS.mkdirTree("/home/pyodide/engine");for(const n of a){const s=await y(`${e}engine/${n}`),i=`/home/pyodide/engine/${n}`,o=i.slice(0,i.lastIndexOf("/"));t.FS.mkdirTree(o),t.FS.writeFile(i,s)}}self.onmessage=async t=>{const{req:e,base:a}=t.data,n=s=>self.postMessage(s);try{n({type:"status",message:"Pyodide wird geladen…"});const s=await u();s.globals.set("js_emit_json",p=>{n(JSON.parse(p))}),n({type:"status",message:"Engine wird gemountet…"}),await w(s,a),n({type:"status",message:"Python-Pakete werden installiert…"}),await s.runPythonAsync(`
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
`),n({type:"status",message:"TPE-Optimierung startet…"});const i=Number(e.nTrials),o=Number(e.omegaGwp),c=Number(e.omegaCost),l=Number(e.spanMm),d=Number(e.seed),g=JSON.stringify(e.loadCategory);await s.runPythonAsync(`
import sys, json
sys.path.insert(0, "/home/pyodide/engine")
import demo_optimize
from js import js_emit_json

def _emit(obj):
    js_emit_json(json.dumps(obj))

demo_optimize._emit = _emit

demo_optimize.run_tpe(
    n_trials=${i},
    omega_gwp=${o},
    omega_cost=${c},
    span_mm=${l},
    load_category=${g},
    seed=${d},
)
`)}catch(s){n({type:"error",message:s instanceof Error?s.message:String(s)})}};
