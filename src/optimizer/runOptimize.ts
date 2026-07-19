import type { OptEvent, OptimizeRequest } from '../types'
import { runNativeOptimize } from './runNative'

function assetBase(): string {
  const base = import.meta.env.BASE_URL || '/'
  return base.endsWith('/') ? base : `${base}/`
}

type ReadyEvent = { type: 'ready' }
type WorkerEvent = OptEvent | ReadyEvent

let sharedWorker: Worker | null = null
let initPromise: Promise<void> | null = null
let preloadStatusHandler: ((ev: OptEvent) => void) | null = null

function getWorker(): Worker {
  if (!sharedWorker) {
    sharedWorker = new Worker(new URL('./pyodideWorker.ts', import.meta.url), {
      type: 'module',
    })
  }
  return sharedWorker
}

/** Start loading Pyodide + packages immediately (page load). */
export function preloadBrowserEngine(
  onStatus?: (ev: OptEvent) => void,
): Promise<void> {
  if (import.meta.env.DEV) {
    // Dev path uses native Python; nothing to preload in the browser.
    return Promise.resolve()
  }
  if (initPromise) {
    if (onStatus) preloadStatusHandler = onStatus
    return initPromise
  }

  preloadStatusHandler = onStatus ?? null
  const worker = getWorker()

  initPromise = new Promise<void>((resolve, reject) => {
    const onMessage = (ev: MessageEvent<WorkerEvent>) => {
      const data = ev.data
      if (data.type === 'status' || data.type === 'error') {
        preloadStatusHandler?.(data)
      }
      if (data.type === 'ready') {
        worker.removeEventListener('message', onMessage)
        resolve()
      }
      if (data.type === 'error') {
        worker.removeEventListener('message', onMessage)
        initPromise = null
        reject(new Error(data.message))
      }
    }
    worker.addEventListener('message', onMessage)
    worker.onerror = (e) => {
      worker.removeEventListener('message', onMessage)
      initPromise = null
      reject(e.error ?? new Error(e.message))
    }
    worker.postMessage({ cmd: 'init', base: assetBase() })
  })

  return initPromise
}

async function runPyodideOptimize(
  req: OptimizeRequest,
  onEvent: (ev: OptEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await preloadBrowserEngine(onEvent)
  const worker = getWorker()

  await new Promise<void>((resolve, reject) => {
    const onAbort = () => {
      // Recreate worker after abort so the next run can re-init cleanly.
      worker.terminate()
      sharedWorker = null
      initPromise = null
      reject(new DOMException('Aborted', 'AbortError'))
    }
    signal?.addEventListener('abort', onAbort)

    const onMessage = (ev: MessageEvent<WorkerEvent>) => {
      const data = ev.data
      if (data.type === 'ready') return
      onEvent(data)
      if (data.type === 'done') {
        cleanup()
        resolve()
      }
      if (data.type === 'error') {
        cleanup()
        reject(new Error(data.message))
      }
    }

    const cleanup = () => {
      signal?.removeEventListener('abort', onAbort)
      worker.removeEventListener('message', onMessage)
    }

    worker.addEventListener('message', onMessage)
    worker.postMessage({ cmd: 'optimize', req })
  })
}

export async function runOptimize(
  req: OptimizeRequest,
  onEvent: (ev: OptEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  if (import.meta.env.DEV) {
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
  }

  await runPyodideOptimize(req, onEvent, signal)
}
