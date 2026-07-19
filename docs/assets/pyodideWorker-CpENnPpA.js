const c="https://cdn.jsdelivr.net/pyodide/v0.27.5/full/";let n=null,d=!1,r=!1;const s=e=>self.postMessage(e);async function l(){if(n)return n;const{loadPyodide:e}=await import(`${c}pyodide.mjs`);return n=await e({indexURL:c}),n}async function u(e){const t=await fetch(e);if(!t.ok)throw new Error(`Fetch failed: ${e}`);return t.text()}async function y(e,t){const i=await fetch(`${e}engine/manifest.json`);if(!i.ok)throw new Error("engine/manifest.json fehlt – bitte docs neu bauen (npm run build).");const m=await i.json();t.FS.mkdirTree("/home/pyodide/engine");for(const o of m){const p=await u(`${e}engine/${o}`),a=`/home/pyodide/engine/${o}`;t.FS.mkdirTree(a.slice(0,a.lastIndexOf("/"))),t.FS.writeFile(a,p)}}async function g(e){s({type:"status",message:"Pyodide wird geladen (einmalig)…"});const t=await l();s({type:"status",message:"NumPy / SciPy / Shapely…"}),await t.loadPackage(["numpy","scipy","shapely","micropip","sqlite3"]),s({type:"status",message:"HP-Engine wird gemountet…"}),await y(e,t),t.globals.set("js_emit_json",i=>{s(JSON.parse(i))}),s({type:"status",message:"Python-Pakete (structuralcodes, Optuna)…"}),await t.runPythonAsync(`
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
`),d=!0,s({type:"status",message:"Browser-Engine bereit."}),s({type:"ready"})}async function f(e){if(!n||!d)throw new Error("Engine nicht initialisiert.");if(r)throw new Error("Optimierung läuft bereits.");r=!0;try{const t=Number(e.nTrials),i=Number(e.omegaGwp),m=Number(e.omegaCost),o=Number(e.spanMm),p=Number(e.seed),a=JSON.stringify(e.loadCategory);await n.runPythonAsync(`
import json
import demo_optimize
from js import js_emit_json

def _emit(obj):
    js_emit_json(json.dumps(obj))

demo_optimize._emit = _emit
demo_optimize.run_tpe(
    n_trials=${t},
    omega_gwp=${i},
    omega_cost=${m},
    span_mm=${o},
    load_category=${a},
    seed=${p},
)
`)}finally{r=!1}}self.onmessage=async e=>{const t=e.data;try{if(t.cmd==="init"){if(d){s({type:"status",message:"Browser-Engine bereit."}),s({type:"ready"});return}await g(t.base);return}if(t.cmd==="optimize"){await f(t.req);return}}catch(i){r=!1,s({type:"error",message:i instanceof Error?i.message:String(i)})}};
