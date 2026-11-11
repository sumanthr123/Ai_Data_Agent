import { ChevronRight, CircleCheck, CircleDashed, CircleMinus, CircleX, LoaderCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { Stage, StageEvent, StageStatus } from './types'

/** Action labels, not anthropomorphic ones. */
const LABELS: Partial<Record<Stage, string>> = {
  context: 'Reading table metadata', clarify: 'Checking the question', generate_sql: 'Planning the answer', web_search: 'Searching the web',
  retrieve: 'Searching project docs', council: 'Independent models drafting', execute: 'Running query', draft: 'Writing answer',
  review: 'Independent review', correct: 'Correcting', adjudicate: 'Judging the drafts', complete: 'Complete',
}
const MAIN: Stage[] = ['context', 'generate_sql', 'execute', 'draft', 'review', 'complete']
const STATUS_TEXT = { running: 'in progress', succeeded: 'done', failed: 'failed', skipped: 'skipped', pending: 'not started' } as const

export function StatusIcon({ status }: { status: StageStatus | 'pending' }) {
  const cls = 'h-4 w-4 shrink-0'
  if (status === 'running') return <LoaderCircle className={`${cls} animate-spin text-brand`} aria-hidden />
  if (status === 'succeeded') return <CircleCheck className={`${cls} text-ok`} aria-hidden />
  if (status === 'failed') return <CircleX className={`${cls} text-err`} aria-hidden />
  if (status === 'skipped') return <CircleMinus className={`${cls} text-fg-3`} aria-hidden />
  return <CircleDashed className={`${cls} text-line-strong`} aria-hidden />
}

export interface Step { stage: Stage; status: StageStatus | 'pending'; ms: number; detail: string }

/** Steps reflect real events only: a step stays pending until the server reports it running. */
function stepsFor(stages: StageEvent[], live: boolean): Step[] {
  const seen = new Set(stages.map((s) => s.stage))
  // A live question can go straight to the web: then no table or planning step ran, and none is shown.
  const main: Stage[] = seen.has('web_search') && !seen.has('context') ? ['web_search', 'complete']
    : seen.has('web_search') ? ['context', 'generate_sql', 'web_search', 'complete']
    : seen.has('retrieve') ? ['context', 'generate_sql', 'retrieve', 'draft', 'complete']
    : seen.has('generate_sql') && !seen.has('execute') && seen.has('complete') ? ['context', 'generate_sql', 'draft', 'complete'] : MAIN
  const order: Stage[] = main.flatMap((s) => (s === 'complete' ? (['correct', 'council', 'adjudicate', 'clarify'] as Stage[]).filter((x) => seen.has(x)).concat(s) : [s]))
  const steps = order.map((stage) => {
    const events = stages.filter((s) => s.stage === stage)
    const last = events.at(-1)
    return { stage, status: (last?.status ?? 'pending') as Step['status'], ms: events.reduce((a, e) => a + e.ms, 0), detail: last?.detail ?? '' }
  })
  return live ? steps : steps.filter((s) => s.status !== 'pending')
}

const clock = (ms: number) => `${Math.floor(ms / 60000)}:${String(Math.floor((ms % 60000) / 1000)).padStart(2, '0')}`

function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  return <span className="font-mono text-[12px] tnum text-fg-3" aria-label={`Elapsed ${clock(now - since)}`}>{clock(now - since)}</span>
}

/** Vertical step list. Not a live region: the page announces only start, ready, stopped and errors. */
function StatusSteps({ stages, live, startedAt, compact = false }: { stages: StageEvent[]; live: boolean; startedAt?: number; compact?: boolean }) {
  const steps = stepsFor(stages, live)
  if (!steps.length) return null
  return (
    <div>
      {live && startedAt && (
        <div className="mb-2 flex items-center justify-between text-[12px] text-fg-3"><span>Working on it</span><Elapsed since={startedAt} /></div>
      )}
      <ol className={compact ? 'space-y-1' : 'space-y-1.5'} aria-label="Steps">
        {steps.map((s) => (
          <li key={s.stage} className="flex items-start gap-2 text-[13px]">
            <StatusIcon status={s.status} />
            <span className={s.status === 'pending' ? 'text-fg-3' : 'text-fg'}>
              {LABELS[s.stage]}<span className="sr-only">: {STATUS_TEXT[s.status]}</span>
              {s.detail && (s.status === 'running' || s.status === 'failed' || s.status === 'skipped') && <span className="text-fg-3"> · {s.detail}</span>}
            </span>
            {s.ms > 0 && s.status !== 'running' && <span className="ml-auto pl-3 font-mono text-[12px] tnum text-fg-3">{(s.ms / 1000).toFixed(1)}s</span>}
          </li>
        ))}
      </ol>
    </div>
  )
}

/** One line while working ("Running query · 0:06"), then "Worked for 14s · 5 steps"; the full list expands either way. */
export function StepsBlock({ stages, live, startedAt, totalMs }: { stages: StageEvent[]; live: boolean; startedAt?: number; totalMs?: number }) {
  const steps = stepsFor(stages, live)
  if (!steps.length && !live) return null
  const current = [...steps].reverse().find((s) => s.status === 'running') ?? steps.find((s) => s.status === 'pending')
  const done = steps.filter((s) => s.status === 'succeeded' && s.stage !== 'complete').length
  const failed = steps.some((s) => s.status === 'failed')
  return (
    <details className="group" open={live || failed || undefined}>
      <summary className="inline-flex min-h-7 cursor-pointer list-none items-center gap-2 rounded-md text-[13.5px] text-fg-2 hover:text-fg">
        {live ? (
          <>
            <LoaderCircle className="h-4 w-4 animate-spin text-brand" aria-hidden />
            <span className="shimmer-text">{current ? LABELS[current.stage] : 'Starting'}</span>
            {startedAt && <Elapsed since={startedAt} />}
          </>
        ) : (
          <span>{failed ? 'Stopped at a failed step' : `Worked for ${((totalMs ?? steps.reduce((a, s) => a + s.ms, 0)) / 1000).toFixed(0)}s`} · {done} step{done === 1 ? '' : 's'}</span>
        )}
        <ChevronRight aria-hidden className="h-3.5 w-3.5 text-fg-3 transition group-open:rotate-90" />
      </summary>
      <div className="mt-2 border-l border-line pl-3"><StatusSteps stages={stages} live={live} compact /></div>
    </details>
  )
}
