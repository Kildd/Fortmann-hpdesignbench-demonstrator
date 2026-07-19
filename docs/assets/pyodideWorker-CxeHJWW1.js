const g="https://cdn.jsdelivr.net/pyodide/v0.27.5/full/",u="2026-07-19b";let o=null,y=!1,m=!1;const s=e=>self.postMessage(e);async function l(){if(o)return o;const{loadPyodide:e}=await import(`${g}pyodide.mjs`);return o=await e({indexURL:g}),o}async function f(e){const t=await fetch(e,{cache:"no-store"});if(!t.ok)throw new Error(`Fetch failed: ${e}`);return t.text()}function p(e,t){const n=t.includes("?")?"&":"?";return`${e}engine/${t}${n}v=${u}`}async function w(e,t){const n=await fetch(p(e,"manifest.json"),{cache:"no-store"});if(!n.ok)throw new Error("engine/manifest.json fehlt – bitte docs neu bauen (npm run build).");const a=await n.json();t.FS.mkdirTree("/home/pyodide/engine");let i=0;for(const r of a){const d=await f(p(e,r)),c=`/home/pyodide/engine/${r}`;t.FS.mkdirTree(c.slice(0,c.lastIndexOf("/"))),t.FS.writeFile(c,d),i+=1,(i%25===0||i===a.length)&&s({type:"status",message:`HP-Engine wird gemountet… (${i}/${a.length})`})}}async function h(e){s({type:"status",message:"Pyodide wird geladen (einmalig)…"});const t=await l();s({type:"status",message:"NumPy / SciPy / Shapely…"}),await t.loadPackage(["numpy","scipy","shapely"]),s({type:"status",message:"HP-Engine wird gemountet…"}),await w(e,t),t.globals.set("js_emit_json",n=>{s(JSON.parse(n))}),s({type:"status",message:"Python-Module werden vorgewärmt…"}),await t.runPythonAsync(`
import sys
sys.path.insert(0, '/home/pyodide/engine/vendor')
sys.path.insert(0, '/home/pyodide/engine')
import demo_optimize  # noqa: F401
`),y=!0,s({type:"status",message:"Browser-Engine bereit."}),s({type:"ready"})}async function _(e){if(!o||!y)throw new Error("Engine nicht initialisiert.");if(m)throw new Error("Optimierung läuft bereits.");m=!0;try{const t=Number(e.nTrials),n=Number(e.omegaGwp),a=Number(e.omegaCost),i=Number(e.spanMm),r=Number(e.seed),d=JSON.stringify(e.loadCategory);await o.runPythonAsync(`
import json
import demo_optimize
from js import js_emit_json

def _emit(obj):
    js_emit_json(json.dumps(obj))

demo_optimize._emit = _emit
demo_optimize.run_tpe(
    n_trials=${t},
    omega_gwp=${n},
    omega_cost=${a},
    span_mm=${i},
    load_category=${d},
    seed=${r},
)
`)}finally{m=!1}}self.onmessage=async e=>{const t=e.data;try{if(t.cmd==="init"){if(y){s({type:"status",message:"Browser-Engine bereit."}),s({type:"ready"});return}await h(t.base);return}if(t.cmd==="optimize"){await _(t.req);return}}catch(n){m=!1,s({type:"error",message:n instanceof Error?n.message:String(n)})}};
