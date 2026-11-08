import { useCallback, useEffect, useState } from 'react'
import type { Pin, Turn } from './types'

// Kept in this browser, like conversations, until the server-side tables exist (they wait on the GDPR job's access).
const KEY = 'assistant.pins.v1'

function load(): Pin[] {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? JSON.parse(raw) : []
  } catch (err) {
    console.warn('Pinned answers unreadable; starting empty', err)
    return []
  }
}

export function usePins() {
  const [pins, setPins] = useState<Pin[]>(load)
  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(pins.slice(0, 50)))
    } catch (err) {
      console.warn('Pinned answers not saved; they last for this session', err)
    }
  }, [pins])
  const toggle = useCallback((turn: Turn) => setPins((all) => all.some((p) => p.id === turn.id) ? all.filter((p) => p.id !== turn.id)
    : [{ id: turn.id, question: turn.question, datasets: turn.datasets, summary: (turn.response?.answer ?? '').replace(/\*\*/g, '').slice(0, 160), pinnedAt: Date.now() }, ...all]), [])
  const remove = useCallback((id: string) => setPins((all) => all.filter((p) => p.id !== id)), [])
  return { pins, toggle, remove }
}
