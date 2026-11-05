import { CircleCheck, CircleDashed, CircleMinus, CircleX, LoaderCircle } from 'lucide-react'
import type { Stage, StageEvent, StageStatus } from './types'

const LABELS: Partial<Record<Stage, string>> = {
  context: 'Profiling data', clarify: 'Checking the question', generate_sql: 'Generating SQL', execute: 'Executing query',
  draft: 'Writing answer', review: 'Independent review', correct: 'Correcting', adjudicate: 'Adjudicating', complete: 'Complete',
}
const MAIN: Stage[] = ['context', 'generate_sql', 'execute', 'draft', 'review', 'complete']

export function StatusIcon({ status }: { status: StageStatus | 'pending' }) {
  const cls = 'h-4 w-4 shrink-0'
  if (status === 'running') return <LoaderCircle className={`${cls} animate-spin text-sky-300`} aria-hidden />
  if (status === 'succeeded') return <CircleCheck className={`${cls} text-emerald-400`} aria-hidden />
  if (status === 'failed') return <CircleX className={`${cls} text-rose-400`} aria-hidden />
  if (status === 'skipped') return <CircleMinus className={`${cls} text-zinc-400`} aria-hidden />
  return <CircleDashed className={`${cls} text-zinc-600`} aria-hidden />
}

/** Steps reflect real events only: a step is pending until the server reports it running. */
export function StatusSteps({ stages, live }: { stages: StageEvent[]; live: boolean }) {
  const seen = new Set(stages.map((s) => s.stage))
  const order: Stage[] = MAIN.flatMap((s) => (s === 'complete' ? (['correct', 'adjudicate', 'clarify'] as Stage[]).filter((x) => seen.has(x)).concat(s) : [s]))
  const steps = order.map((stage) => {
    const events = stages.filter((s) => s.stage === stage)
    const last = events.at(-1)
    return { stage, status: (last?.status ?? 'pending') as StageStatus | 'pending', ms: events.reduce((a, e) => a + e.ms, 0), detail: last?.detail ?? '' }
  })
  const visible = live ? steps : steps.filter((s) => s.status !== 'pending')
  return (
    <ol className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12.5px]" aria-live="polite" aria-label="Progress">
      {visible.map((s) => (
        <li key={s.stage} className={s.status === 'pending' ? 'flex items-center gap-1.5 text-zinc-500' : 'flex items-center gap-1.5 text-zinc-200'}
          title={s.detail || undefined}>
          <StatusIcon status={s.status} />
          <span>{LABELS[s.stage]}</span>
          {s.ms > 0 && s.status !== 'running' && <span className="font-mono text-[11px] text-zinc-400">{(s.ms / 1000).toFixed(1)}s</span>}
          <span className="sr-only">{s.status}</span>
        </li>
      ))}
    </ol>
  )
}
