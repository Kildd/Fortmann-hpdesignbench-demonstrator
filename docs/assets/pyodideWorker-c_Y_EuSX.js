const p="https://cdn.jsdelivr.net/pyodide/v0.27.5/full/",l="2026-07-19c";let a=null,y=!1,m=!1;const i=e=>self.postMessage(e);async function u(){if(a)return a;const{loadPyodide:e}=await import(`${p}pyodide.mjs`);return a=await e({indexURL:p}),a}function f(e,t){const s=t.includes("?")?"&":"?";return`${e}engine/${t}${s}v=${l}`}async function w(e,t=3){let s;for(let o=1;o<=t;o++)try{const n=await fetch(e,{cache:"no-store"});if(!n.ok)throw new Error(`HTTP ${n.status}`);return await n.json()}catch(n){s=n,o<t&&await new Promise(r=>setTimeout(r,250*o))}throw new Error(`Fetch failed: ${e}${s instanceof Error?` (${s.message})`:""}`)}async function h(e,t){i({type:"status",message:"HP-Engine-Bundle wird geladen…"});const s=await w(f(e,"bundle.json")),o=Object.entries(s);t.FS.mkdirTree("/home/pyodide/engine");let n=0;for(const[r,d]of o){const c=`/home/pyodide/engine/${r}`,g=c.lastIndexOf("/");g>0&&t.FS.mkdirTree(c.slice(0,g)),t.FS.writeFile(c,d),n+=1,(n%40===0||n===o.length)&&i({type:"status",message:`HP-Engine wird gemountet… (${n}/${o.length})`})}}async function _(e){i({type:"status",message:"Pyodide wird geladen (einmalig)…"});const t=await u();i({type:"status",message:"NumPy / SciPy / Shapely…"}),await t.loadPackage(["numpy","scipy","shapely"]),i({type:"status",message:"HP-Engine wird gemountet…"}),await h(e,t),t.globals.set("js_emit_json",s=>{i(JSON.parse(s))}),i({type:"status",message:"Python-Module werden vorgewärmt…"}),await t.runPythonAsync(`
import sys
sys.path.insert(0, '/home/pyodide/engine/vendor')
sys.path.insert(0, '/home/pyodide/engine')
import demo_optimize  # noqa: F401
`),y=!0,i({type:"status",message:"Browser-Engine bereit."}),i({type:"ready"})}async function E(e){if(!a||!y)throw new Error("Engine nicht initialisiert.");if(m)throw new Error("Optimierung läuft bereits.");m=!0;try{const t=Number(e.nTrials),s=Number(e.omegaGwp),o=Number(e.omegaCost),n=Number(e.spanMm),r=Number(e.seed),d=JSON.stringify(e.loadCategory);await a.runPythonAsync(`
import json
import demo_optimize
from js import js_emit_json

def _emit(obj):
    js_emit_json(json.dumps(obj))

demo_optimize._emit = _emit
demo_optimize.run_tpe(
    n_trials=${t},
    omega_gwp=${s},
    omega_cost=${o},
    span_mm=${n},
    load_category=${d},
    seed=${r},
)
`)}finally{m=!1}}self.onmessage=async e=>{const t=e.data;try{if(t.cmd==="init"){if(y){i({type:"status",message:"Browser-Engine bereit."}),i({type:"ready"});return}await _(t.base);return}if(t.cmd==="optimize"){await E(t.req);return}}catch(s){m=!1,i({type:"error",message:s instanceof Error?s.message:String(s)})}};
