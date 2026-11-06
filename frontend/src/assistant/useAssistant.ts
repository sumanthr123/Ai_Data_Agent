import { useCallback, useEffect, useRef, useState } from 'react'
import { streamAsk } from './api'
import type { Conversation, StageEvent, Turn } from './types'

const KEY = 'assistant.conversations.v1'

function load(): Conversation[] {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function save(conversations: Conversation[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(conversations.slice(0, 50)))
  } catch { /* storage full or blocked: conversations still work for this session */ }
}

const newId = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36)

export function newConversation(datasets: string[]): Conversation {
  return { id: newId(), title: 'New conversation', updatedAt: Date.now(), turns: [], state: null, datasets }
}

/** Keep one entry per stage: a later event for the same stage replaces the earlier one (running -> succeeded). */
function mergeStage(stages: StageEvent[], event: StageEvent): StageEvent[] {
  const i = stages.findLastIndex((s) => s.stage === event.stage && s.status === 'running')
  if (i >= 0) return stages.map((s, j) => (j === i ? event : s))
  return [...stages, event]
}

export function useAssistant(defaultDatasets: string[]) {
  const [conversations, setConversations] = useState<Conversation[]>(load)
  const [activeId, setActiveId] = useState<string | null>(() => load()[0]?.id ?? null)
  const [busy, setBusy] = useState(false)
  const controller = useRef<AbortController | null>(null)

  useEffect(() => save(conversations), [conversations])

  const active = conversations.find((c) => c.id === activeId) ?? null

  const update = useCallback((id: string, fn: (c: Conversation) => Conversation) => {
    setConversations((all) => all.map((c) => (c.id === id ? fn(c) : c)))
  }, [])

  const updateTurn = useCallback((cid: string, tid: string, fn: (t: Turn) => Turn) => {
    update(cid, (c) => ({ ...c, updatedAt: Date.now(), turns: c.turns.map((t) => (t.id === tid ? fn(t) : t)) }))
  }, [update])

  const start = useCallback((datasets?: string[]) => {
    const conversation = newConversation(datasets ?? defaultDatasets)
    setConversations((all) => [conversation, ...all])
    setActiveId(conversation.id)
    return conversation
  }, [defaultDatasets])

  const setDatasets = useCallback((datasets: string[]) => {
    if (!activeId) {
      start(datasets)
      return
    }
    // Changing datasets starts fresh context: filters from another dataset would not apply.
    update(activeId, (c) => ({ ...c, datasets, state: c.state ? { ...c.state, active_datasets: datasets, applied_filters: [], last_sql: null } : null }))
  }, [activeId, start, update])

  const ask = useCallback(async (question: string, council = false) => {
    if (busy || !question.trim()) return
    const conversation = active ?? start()
    const turn: Turn = { id: newId(), question: question.trim(), stages: [], datasets: conversation.datasets }
    update(conversation.id, (c) => ({
      ...c, updatedAt: Date.now(), turns: [...c.turns, turn],
      title: c.turns.length ? c.title : question.trim().slice(0, 60),
    }))
    const abort = new AbortController()
    controller.current = abort
    setBusy(true)
    try {
      const response = await streamAsk(turn.question, conversation.datasets, conversation.state,
        (event) => updateTurn(conversation.id, turn.id, (t) => ({ ...t, stages: mergeStage(t.stages, event) })), abort.signal, council)
      updateTurn(conversation.id, turn.id, (t) => ({ ...t, response }))
      update(conversation.id, (c) => ({ ...c, state: response.state }))
    } catch (err) {
      const cancelled = abort.signal.aborted
      updateTurn(conversation.id, turn.id, (t) => ({
        ...t, cancelled, error: cancelled ? undefined : (err as Error).message,
        stages: t.stages.map((s) => (s.status === 'running' ? { ...s, status: cancelled ? 'skipped' : 'failed' } : s)),
      }))
    } finally {
      controller.current = null
      setBusy(false)
    }
  }, [active, busy, start, update, updateTurn])

  const cancel = useCallback(() => controller.current?.abort(), [])

  const remove = useCallback((id: string) => {
    setConversations((all) => all.filter((c) => c.id !== id))
    if (id === activeId) setActiveId(null)
  }, [activeId])

  return { conversations, active, activeId, setActiveId, busy, ask, cancel, start, remove, setDatasets }
}
