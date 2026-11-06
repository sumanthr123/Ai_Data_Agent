import type { AskResponse, ConversationState, Dataset, ModelOption, StageEvent, UploadResult } from './types'

async function fail(res: Response): Promise<never> {
  let message = `${res.status} ${res.statusText}`
  try {
    const body = await res.json()
    if (typeof body.detail === 'string') message = body.detail
  } catch { /* not JSON */ }
  throw new Error(message)
}

export async function listDatasets(): Promise<Dataset[]> {
  const res = await fetch('/api/ask/datasets')
  if (!res.ok) await fail(res)
  return res.json()
}

export async function listModels(): Promise<ModelOption[]> {
  const res = await fetch('/api/ask/models')
  if (!res.ok) await fail(res)
  return res.json()
}

export async function uploadFile(file: File, conversationId: string, sheet?: string, signal?: AbortSignal): Promise<UploadResult> {
  const form = new FormData()
  form.append('file', file)
  form.append('conversation_id', conversationId)
  if (sheet) form.append('sheet', sheet)
  const res = await fetch('/api/ask/uploads', { method: 'POST', body: form, signal })
  if (!res.ok) await fail(res)
  return res.json()
}

export async function deleteUpload(dataset: string): Promise<void> {
  const res = await fetch(`/api/ask/uploads/${encodeURIComponent(dataset)}`, { method: 'DELETE' })
  if (!res.ok) await fail(res)
}

/** Streams stage events, resolves with the final answer. Aborting the signal cancels the run server-side too. */
export async function streamAsk(question: string, datasets: string[], state: ConversationState | null,
  onStage: (e: StageEvent) => void, signal: AbortSignal, council = false, model: string | null = null): Promise<AskResponse> {
  const res = await fetch('/api/ask/stream', {
    method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ question, datasets, state: state ?? {}, council, model }), signal,
  })
  if (!res.ok || !res.body) await fail(res)
  const reader = res.body!.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value.replace(/\r\n/g, '\n')
    let cut: number
    while ((cut = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, cut)
      buffer = buffer.slice(cut + 2)
      const event = /^event: ?(.*)$/m.exec(block)?.[1]?.trim()
      const data = block.split('\n').filter((l) => l.startsWith('data:')).map((l) => l.slice(5).replace(/^ /, '')).join('\n')
      if (!data) continue
      if (event === 'stage') onStage(JSON.parse(data))
      else if (event === 'result') return JSON.parse(data)
      else if (event === 'error') throw new Error(JSON.parse(data).message)
    }
  }
  throw new Error('The connection closed before an answer arrived.')
}

export async function downloadCsv(sql: string, datasets: string[]): Promise<void> {
  const res = await fetch('/api/ask/export', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sql, datasets }) })
  if (!res.ok) await fail(res)
  const url = URL.createObjectURL(await res.blob())
  const a = Object.assign(document.createElement('a'), { href: url, download: 'query-result.csv' })
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
