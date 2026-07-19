import type { OptEvent, OptimizeRequest } from '../types'
import { runNativeOptimize } from './runNative'

function assetBase(): string {
  const base = import.meta.env.BASE_URL || '/'
  return base.endsWith('/') ? base : `${base}/`
}

async function runPyodideOptimize(
  req: OptimizeRequest,
  onEvent: (ev: OptEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const worker = new Worker(new URL('./pyodideWorker.ts', import.meta.url), {
    type: 'module',
  })

  await new Promise<void>((resolve, reject) => {
    const onAbort = () => {
      worker.terminate()
      reject(new DOMException('Aborted', 'AbortError'))
    }
    signal?.addEventListener('abort', onAbort)

    worker.onmessage = (ev: MessageEvent<OptEvent>) => {
      onEvent(ev.data)
      if (ev.data.type === 'done' || ev.data.type === 'error') {
        signal?.removeEventListener('abort', onAbort)
        worker.terminate()
        if (ev.data.type === 'error') reject(new Error(ev.data.message))
        else resolve()
      }
    }
    worker.onerror = (e) => {
      signal?.removeEventListener('abort', onAbort)
      worker.terminate()
      reject(e.error ?? new Error(e.message))
    }

    worker.postMessage({ req, base: assetBase() })
  })
}

export async function runOptimize(
  req: OptimizeRequest,
  onEvent: (ev: OptEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  // Prefer native Python via Vite middleware (fast, identical stack).
  try {
    const ok = await runNativeOptimize(req, onEvent, signal)
    if (ok) return
  } catch (err) {
    if (signal?.aborted) throw err
    onEvent({
      type: 'status',
      message: 'Native Engine nicht erreichbar – wechsle zu Pyodide…',
    })
  }

  await runPyodideOptimize(req, onEvent, signal)
}
