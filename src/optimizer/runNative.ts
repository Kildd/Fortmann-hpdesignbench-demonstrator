import type { OptEvent, OptimizeRequest } from '../types'

export async function runNativeOptimize(
  req: OptimizeRequest,
  onEvent: (ev: OptEvent) => void,
  signal?: AbortSignal,
): Promise<boolean> {
  const res = await fetch('/api/optimize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
    signal,
  })

  if (!res.ok || !res.body) {
    return false
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed) continue
      try {
        onEvent(JSON.parse(trimmed) as OptEvent)
      } catch {
        // ignore partial/non-json noise
      }
    }
  }

  if (buffer.trim()) {
    try {
      onEvent(JSON.parse(buffer.trim()) as OptEvent)
    } catch {
      /* ignore */
    }
  }

  return true
}
