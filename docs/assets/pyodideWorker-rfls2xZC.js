const l="https://cdn.jsdelivr.net/pyodide/v0.27.5/full/",u="2026-07-19g";let a=null,g=!1,m=!1;const i=t=>self.postMessage(t);async function f(){if(a)return a;const{loadPyodide:t}=await import(`${l}pyodide.mjs`);return a=await t({indexURL:l}),a}function w(t,e){const s=e.includes("?")?"&":"?";return`${t}engine/${e}${s}v=${u}`}async function h(t,e=3){let s;for(let o=1;o<=e;o++)try{const n=await fetch(t,{cache:"no-store"});if(!n.ok)throw new Error(`HTTP ${n.status}`);return await n.json()}catch(n){s=n,o<e&&await new Promise(r=>setTimeout(r,250*o))}throw new Error(`Fetch failed: ${t}${s instanceof Error?` (${s.message})`:""}`)}async function _(t,e){i({type:"status",message:"HP-Engine-Bundle wird geladen…"});const s=await h(w(t,"bundle.json")),o=Object.entries(s);e.FS.mkdirTree("/home/pyodide/engine");let n=0;for(const[r,d]of o){const c=`/home/pyodide/engine/${r}`,y=c.lastIndexOf("/");y>0&&e.FS.mkdirTree(c.slice(0,y)),e.FS.writeFile(c,d),n+=1,(n%40===0||n===o.length)&&i({type:"status",message:`HP-Engine wird gemountet… (${n}/${o.length})`})}}async function E(t){i({type:"status",message:"Pyodide wird geladen (einmalig)…"});const e=await f();i({type:"status",message:"NumPy / SciPy / Shapely…"}),await e.loadPackage(["numpy","scipy","shapely"]),i({type:"status",message:"HP-Engine wird gemountet…"}),await _(t,e),p(e),i({type:"status",message:"Python-Module werden vorgewärmt…"}),await e.runPythonAsync(`
import sys
sys.path.insert(0, '/home/pyodide/engine/vendor')
sys.path.insert(0, '/home/pyodide/engine')
import demo_optimize  # noqa: F401
`),g=!0,i({type:"status",message:"Browser-Engine bereit."}),i({type:"ready"})}function p(t){const e=s=>{i(JSON.parse(s))};globalThis.js_emit_json=e,t.globals.set("js_emit_json",e)}async function j(t){if(!a||!g)throw new Error("Engine nicht initialisiert.");if(m)throw new Error("Optimierung läuft bereits.");m=!0;try{p(a);const e=Number(t.nTrials),s=Number(t.omegaGwp),o=Number(t.omegaCost),n=Number(t.spanMm),r=Number(t.seed),d=JSON.stringify(t.loadCategory);await a.runPythonAsync(`
import json
import demo_optimize
from js import js_emit_json

def _emit(obj):
    js_emit_json(json.dumps(obj))

demo_optimize._emit = _emit
demo_optimize.run_tpe(
    n_trials=${e},
    omega_gwp=${s},
    omega_cost=${o},
    span_mm=${n},
    load_category=${d},
    seed=${r},
)
`)}finally{m=!1}}self.onmessage=async t=>{const e=t.data;try{if(e.cmd==="init"){if(g){i({type:"status",message:"Browser-Engine bereit."}),i({type:"ready"});return}await E(e.base);return}if(e.cmd==="optimize"){await j(e.req);return}}catch(s){m=!1,i({type:"error",message:s instanceof Error?s.message:String(s)})}};
