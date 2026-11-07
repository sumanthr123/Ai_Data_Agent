import { useCallback, useEffect, useRef, useState } from 'react'
import { useTheme } from '../theme'
import { AnswerCard, type TurnAction } from './AnswerCard'
import { DATA_STAGES, GALLERY, REPLAY } from './fixtures'
import type { StageEvent, Turn } from './types'

const SHAPE = {
  columns: [{ name: 'region', type: 'string', distinct: 4 }, { name: 'segment', type: 'string', distinct: 3 }, { name: 'category', type: 'string', distinct: 3 }],
  dateColumn: 'order_date',
}

function merge(stages: StageEvent[], e: StageEvent): StageEvent[] {
  const i = stages.findLastIndex((s) => s.stage === e.stage && s.status === 'running')
  return i >= 0 ? stages.map((s, j) => (j === i ? e : s)) : [...stages, e]
}

/** The streaming state, driven by mock events with realistic delays, including a slow warehouse start. */
function Replay({ theme, onAction }: { theme: string; onAction: (t: Turn, a: TurnAction) => void }) {
  const [run, setRun] = useState(0)
  const [turn, setTurn] = useState<Turn>({ id: 'live', question: 'What were total sales by region in 2017?', stages: [], datasets: [], startedAt: Date.now() })
  const done = turn.stages.some((s) => s.stage === 'review' && s.status === 'succeeded')
  const timers = useRef<number[]>([])
  useEffect(() => {
    setTurn((t) => ({ ...t, stages: [], startedAt: Date.now(), response: undefined }))
    timers.current = REPLAY.map(([at, e]) => window.setTimeout(() => setTurn((t) => ({ ...t, stages: merge(t.stages, e) })), at))
    timers.current.push(window.setTimeout(() => setTurn((t) => ({ ...t, stages: DATA_STAGES, response: GALLERY[0].turn.response })), 14100))
    return () => timers.current.forEach(clearTimeout)
  }, [run])
  return (
    <div className="space-y-2">
      <AnswerCard turn={turn} live={!turn.response} theme={theme} shape={SHAPE} onAction={onAction} />
      {(done || turn.response) && <button type="button" onClick={() => setRun((r) => r + 1)} className="min-h-7 rounded-md border border-line px-3 text-[12.5px] text-fg-2 hover:text-fg">Replay</button>}
    </div>
  )
}

export default function StatesGallery() {
  const theme = useTheme()
  const [last, setLast] = useState('')
  const onAction = useCallback((t: Turn, a: TurnAction) => setLast(`${t.id}: ${a.type}${'text' in a ? ` "${a.text}"` : ''}`), [])
  return (
    <div className="min-h-full bg-bg text-fg">
      <header className="flex flex-wrap items-center gap-3 border-b border-line bg-surface px-4 py-3">
        <h1 className="text-[16px] font-semibold">AI Data Assistant: every state</h1>
        <a href="/" className="text-[13px] text-brand hover:underline">Open the app (empty and onboarding states)</a>
        <button type="button" onClick={theme.cycle} className="ml-auto min-h-7 rounded-md border border-line px-3 text-[12.5px]">Theme: {theme.pref}</button>
      </header>
      <p role="status" className="px-4 pt-2 text-[12.5px] text-fg-3">{last ? `Action fired: ${last}` : 'Mock data. Actions are captured here, not sent, except Export CSV, which runs the shown SQL.'}</p>
      <main className="grid gap-8 p-4 xl:grid-cols-2">
        <section aria-labelledby="g-stream" className="space-y-2">
          <h2 id="g-stream" className="text-[13px] font-semibold uppercase tracking-wide text-fg-3">Streaming <span className="font-normal normal-case">· vertical steps, elapsed time, fixed-size skeleton</span></h2>
          <Replay theme={theme.resolved} onAction={onAction} />
        </section>
        {GALLERY.map((g) => (
          <section key={g.turn.id} aria-labelledby={`g-${g.turn.id}`} className="space-y-2">
            <h2 id={`g-${g.turn.id}`} className="text-[13px] font-semibold uppercase tracking-wide text-fg-3">{g.title} <span className="font-normal normal-case">· {g.note}</span></h2>
            <AnswerCard turn={g.turn} live={false} theme={theme.resolved} shape={SHAPE} onAction={onAction} />
          </section>
        ))}
      </main>
    </div>
  )
}
