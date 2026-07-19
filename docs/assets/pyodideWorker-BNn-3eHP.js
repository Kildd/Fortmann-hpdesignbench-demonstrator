const c="https://cdn.jsdelivr.net/pyodide/v0.27.5/full/";let o=null,g=!1,m=!1;const n=e=>self.postMessage(e);async function p(){if(o)return o;const{loadPyodide:e}=await import(`${c}pyodide.mjs`);return o=await e({indexURL:c}),o}async function u(e){const t=await fetch(e);if(!t.ok)throw new Error(`Fetch failed: ${e}`);return t.text()}async function l(e,t){const s=await fetch(`${e}engine/manifest.json`);if(!s.ok)throw new Error("engine/manifest.json fehlt – bitte docs neu bauen (npm run build).");const a=await s.json();t.FS.mkdirTree("/home/pyodide/engine");let i=0;for(const r of a){const d=await u(`${e}engine/${r}`),y=`/home/pyodide/engine/${r}`;t.FS.mkdirTree(y.slice(0,y.lastIndexOf("/"))),t.FS.writeFile(y,d),i+=1,(i%25===0||i===a.length)&&n({type:"status",message:`HP-Engine wird gemountet… (${i}/${a.length})`})}}async function f(e){n({type:"status",message:"Pyodide wird geladen (einmalig)…"});const t=await p();n({type:"status",message:"NumPy / SciPy / Shapely…"}),await t.loadPackage(["numpy","scipy","shapely"]),n({type:"status",message:"HP-Engine wird gemountet…"}),await l(e,t),t.globals.set("js_emit_json",s=>{n(JSON.parse(s))}),n({type:"status",message:"Python-Module werden vorgewärmt…"}),await t.runPythonAsync(`
import sys
sys.path.insert(0, '/home/pyodide/engine/vendor')
sys.path.insert(0, '/home/pyodide/engine')
import demo_optimize  # noqa: F401
`),g=!0,n({type:"status",message:"Browser-Engine bereit."}),n({type:"ready"})}async function w(e){if(!o||!g)throw new Error("Engine nicht initialisiert.");if(m)throw new Error("Optimierung läuft bereits.");m=!0;try{const t=Number(e.nTrials),s=Number(e.omegaGwp),a=Number(e.omegaCost),i=Number(e.spanMm),r=Number(e.seed),d=JSON.stringify(e.loadCategory);await o.runPythonAsync(`
import json
import demo_optimize
from js import js_emit_json

def _emit(obj):
    js_emit_json(json.dumps(obj))

demo_optimize._emit = _emit
demo_optimize.run_tpe(
    n_trials=${t},
    omega_gwp=${s},
    omega_cost=${a},
    span_mm=${i},
    load_category=${d},
    seed=${r},
)
`)}finally{m=!1}}self.onmessage=async e=>{const t=e.data;try{if(t.cmd==="init"){if(g){n({type:"status",message:"Browser-Engine bereit."}),n({type:"ready"});return}await f(t.base);return}if(t.cmd==="optimize"){await w(t.req);return}}catch(s){m=!1,n({type:"error",message:s instanceof Error?s.message:String(s)})}};
