import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { AppConfig, Attachment, CatalogTree, Health, LaneState, Mode, StreamEvent, Turn, View } from '../types/consensus'


/** Parse a Server-Sent Events body: blocks separated by blank lines, `data:` lines carry JSON. */
async function* readSse(response: Response, signal: AbortSignal): AsyncGenerator<StreamEvent> {
  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (!signal.aborted) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
    let split = buffer.indexOf('\n\n')
    while (split !== -1) {
      const block = buffer.slice(0, split)
      buffer = buffer.slice(split + 2)
      const data = block.split('\n').filter((l) => l.startsWith('data:')).map((l) => l.slice(5).trim()).join('\n')
      if (data && data !== '{}') yield JSON.parse(data) as StreamEvent
      split = buffer.indexOf('\n\n')
    }
  }
}

export function useConsensusStream() {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [mode, setMode] = useState<Mode>('demo')
  const [view, setView] = useState<View>('consensus')
  const [lead, setLead] = useState('auto')
  const [health, setHealth] = useState<Health | null>(null)
  const [catalog, setCatalog] = useState<CatalogTree | null>(null)
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [chats, setChats] = useState<Chat[]>(loadChats)
  // Open on a fresh chat; earlier ones are in the sidebar.
  const [activeId, setActiveId] = useState<string | null>(null)
  const controller = useRef<AbortController | null>(null)
  const turns = useMemo(() => chats.find((c) => c.id === activeId)?.turns ?? [], [chats, activeId])

  useEffect(() => {
    fetch('/api/config').then((r) => r.json()).then((c: AppConfig) => { setConfig(c); setMode(c.default_mode) }).catch(() => undefined)
    // Model availability is probed in the background on first load; pick up the results shortly after.
    const later = setTimeout(() => fetch('/api/config').then((r) => r.json()).then(setConfig).catch(() => undefined), 25_000)
    return () => clearTimeout(later)
  }, [])

  useEffect(() => {
    setHealth(null)
    setCatalog(null)
    setCatalogError(null)
    setLead('auto')
    fetch(`/api/health?mode=${mode}`).then((r) => r.json()).then(setHealth).catch(() => undefined)
    fetch(`/api/catalog/tree?mode=${mode}`)
      .then(async (r) => (r.ok ? setCatalog(await r.json()) : setCatalogError((await r.json()).detail ?? 'Catalog unavailable')))
      .catch((e) => setCatalogError(String(e)))
  }, [mode])

  const busy = chats.some((c) => c.turns.some((t) => !t.done))

  // Save finished chats; skipped mid-stream so a half-written answer isn't stored.
  useEffect(() => { if (!busy) saveChats(chats) }, [busy, chats])

  // A streaming turn may belong to a chat that is no longer open, so find it by turn id.
  const patch = useCallback((id: string, fn: (t: Turn) => Turn) => setChats((all) => all.map((c) =>
    c.turns.some((t) => t.id === id) ? { ...c, updatedAt: Date.now(), turns: c.turns.map((t) => (t.id === id ? fn(t) : t)) } : c)), [])

  const ask = useCallback(async (question: string, attached: Attachment[] = []) => {
    if (!question.trim() || busy) return
    const id = crypto.randomUUID()
    // Earlier answered turns, so follow-ups like "what about 2016?" keep their context.
    const history = turns.filter((t) => t.consensus && t.mode === mode).slice(-6)
      .map((t) => ({ question: t.rewritten ?? t.question, answer: t.consensus!.narrative.slice(0, 1200), sql: t.consensus!.sql }))
    // Files from earlier turns stay available, so "now chart that file" still works later in the chat.
    const earlier = turns.flatMap((t) => t.attachments ?? [])
    const files = [...new Map([...earlier, ...attached].map((f) => [f.id, f])).values()].slice(-10)
      .map(({ name, kind, text, table }) => ({ name, kind, text: text ?? '', table: table ?? '' }))
    const turn: Turn = { id, question, mode, lanes: [], arbiter: 'idle', pipeline: {}, done: false, attachments: attached, lead }
    const chatId = activeId && chats.some((c) => c.id === activeId) ? activeId : crypto.randomUUID()
    setChats((all) => all.some((c) => c.id === chatId)
      ? all.map((c) => (c.id === chatId ? { ...c, updatedAt: Date.now(), turns: [...c.turns, turn] } : c))
      : [{ id: chatId, title: question.slice(0, 60), updatedAt: Date.now(), turns: [turn] }, ...all])
    setActiveId(chatId)
    if (question.length > MAX_QUESTION) {
      patch(id, (t) => ({ ...t, done: true,
        error: `That message is ${question.length.toLocaleString()} characters; the limit is ${MAX_QUESTION.toLocaleString()}. Paste just the part you want help with.` }))
      return
    }
    const abort = new AbortController()
    controller.current = abort
    try {
      const response = await fetch('/api/chat/consensus-stream', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: abort.signal,
        body: JSON.stringify({ question, lead_model: lead, mode, history, attachments: files,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' }),
      })
      if (!response.ok) throw new Error(await friendlyHttpError(response))
      for await (const event of readSse(response, abort.signal)) {
        if (event.type === 'lane') {
          patch(id, (t) => {
            const lanes = [...t.lanes]
            const current = lanes.find((l) => l.lane === event.lane) ?? { lane: event.lane, model: event.model, stages: {} }
            const next: LaneState = { ...current, route: event.route ?? current.route,
              stages: { ...current.stages, [event.stage]: { status: event.status, detail: event.detail } } }
            const index = lanes.findIndex((l) => l.lane === event.lane)
            if (index === -1) lanes.push(next)
            else lanes[index] = next
            return { ...t, lanes: lanes.sort((a, b) => a.lane - b.lane) }
          })
        } else if (event.type === 'lane_result') {
          patch(id, (t) => ({ ...t, lanes: t.lanes.map((l) => (l.lane === event.result.lane ? { ...l, result: event.result } : l)) }))
        } else if (event.type === 'pipeline') {
          patch(id, (t) => ({ ...t, route: event.stage === 'route' ? (event.detail as Turn['route']) : t.route,
            pipeline: { ...t.pipeline, [event.stage]: { status: event.status, detail: event.detail } } }))
        } else if (event.type === 'arbiter') {  // demo mode
          patch(id, (t) => ({ ...t, arbiter: event.status,
            pipeline: { ...t.pipeline, write: { status: event.status === 'done' ? 'succeeded' : 'running', detail: event.detail } } }))
        } else if (event.type === 'consensus') {
          patch(id, (t) => ({ ...t, consensus: event.consensus }))
        } else if (event.type === 'rewrite') {
          patch(id, (t) => ({ ...t, rewritten: event.question }))
        } else if (event.type === 'error') {
          patch(id, (t) => ({ ...t, error: event.message }))
        }
      }
    } catch (error) {
      if (!(error instanceof DOMException && error.name === 'AbortError')) patch(id, (t) => ({ ...t, error: String(error) }))
    } finally {
      patch(id, (t) => ({ ...t, done: true }))
    }
  }, [activeId, busy, chats, lead, mode, patch, turns])

  const stop = useCallback(() => controller.current?.abort(), [])
  /** Open an empty conversation; the chat is created when its first question is asked. */
  const newChat = useCallback(() => setActiveId(null), [])
  const deleteChat = useCallback((id: string) => {
    setChats((all) => all.filter((c) => c.id !== id))
    setActiveId((current) => (current === id ? null : current))
  }, [])
  const clear = useCallback(() => { stop(); newChat() }, [newChat, stop])

  const leadOptions = mode === 'demo'
    ? (config?.demo_models ?? []).map((m) => ({ id: m.id, name: m.name, provider: m.provider }))
    : (config?.live_models ?? [])

  const chatList = [...chats].sort((a, b) => b.updatedAt - a.updatedAt)
  return { config, mode, setMode, view, setView, lead, setLead, leadOptions, health, catalog, catalogError, turns, busy, ask, stop, clear,
    chats: chatList, activeId, selectChat: setActiveId, newChat, deleteChat }
}

export interface Chat { id: string; title: string; updatedAt: number; turns: Turn[] }

/** Mirrors ChatRequest.question's max_length in backend/schemas.py. */
export const MAX_QUESTION = 60_000

/** Turn an HTTP error body (often FastAPI's validation JSON) into one readable sentence. */
async function friendlyHttpError(response: Response): Promise<string> {
  const body = await response.text()
  try {
    const detail = JSON.parse(body).detail
    if (Array.isArray(detail)) return detail.map((d: { msg?: string; loc?: string[] }) => `${d.loc?.at(-1) ?? 'request'}: ${d.msg}`).join('; ')
    if (typeof detail === 'string') return detail
  } catch {
    // Not JSON; fall through to the raw text.
  }
  return `The server returned ${response.status}. ${body.slice(0, 200)}`
}

const STORE = 'consensus.chats.v1'

function loadChats(): Chat[] {
  try {
    const chats = JSON.parse(localStorage.getItem(STORE) ?? '[]') as Chat[]
    // A turn that was streaming when the page closed can't resume; mark it finished.
    return chats.map((c) => ({ ...c, turns: c.turns.map((t) => ({ ...t, pipeline: t.pipeline ?? {}, done: true })) }))
  } catch {
    return []
  }
}

function saveChats(chats: Chat[]) {
  // Keep the newest 50 chats and drop per-model result rows, which are only needed while comparing live.
  const slim = [...chats].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, 50).map((c) => ({
    ...c, turns: c.turns.map((t) => ({ ...t, lanes: t.lanes.map((l) => (l.result ? { ...l, result: { ...l.result, result: null } } : l)) })),
  }))
  try {
    localStorage.setItem(STORE, JSON.stringify(slim))
  } catch {
    // Storage full or blocked (private window): chats still work for this session.
  }
}

export type ConsensusState = ReturnType<typeof useConsensusStream>
