import { Check, CircleDashed, Loader2, MinusCircle, XCircle } from 'lucide-react'
import { cn } from '../lib/cn'
import type { LaneState, StageStatus } from '../types/consensus'

const LABELS: Record<string, string> = { plan: 'Plan', execute: 'Run query on warehouse', answer: 'Answer from web evidence' }
const ROUTE: Record<string, string> = { data: 'Database query', web: 'Web search', general: 'Direct answer' }

export function StatusIcon({ status }: { status: StageStatus | 'passed' | 'warning' | 'not_run' }) {
  if (status === 'running') return <Loader2 className="h-3.5 w-3.5 animate-spin text-sky-300" aria-label="Running" />
  if (status === 'succeeded' || status === 'passed') return <Check className="h-3.5 w-3.5 text-emerald-300" aria-label="Succeeded" />
  if (status === 'failed') return <XCircle className="h-3.5 w-3.5 text-rose-300" aria-label="Failed" />
  if (status === 'warning') return <MinusCircle className="h-3.5 w-3.5 text-amber-300" aria-label="Warning" />
  if (status === 'skipped' || status === 'not_run') return <MinusCircle className="h-3.5 w-3.5 text-slate-400" aria-label="Skipped" />
  return <CircleDashed className="h-3.5 w-3.5 text-slate-400" aria-label="Pending" />
}

/** Each model's stages exactly as they happened: only stages that ran are listed, with their real outcome. */
export function ParallelRaceTrace({ lanes }: { lanes: LaneState[] }) {
  return (
    <div className="space-y-3 rounded-2xl border border-white/10 bg-slate-900/65 p-4">
      <div className="text-[12px] font-medium text-slate-300">What each model did</div>
      {lanes.map((lane) => {
        const stages = Object.entries(lane.stages).filter(([name]) => name in LABELS)
        const failed = stages.some(([, s]) => s?.status === 'failed')
        return (
          <div key={lane.lane} className="rounded-xl border border-white/[0.06] bg-black/20 p-3">
            <div className="mb-1.5 flex flex-wrap items-center gap-2 text-[13px]">
              <span className="h-2 w-2 rounded-full" style={{ background: lane.model.color }} />
              <span className="font-medium text-white">{lane.model.name}</span>
              {lane.route && <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-[11px] text-slate-300">{ROUTE[lane.route] ?? lane.route}</span>}
              {failed && <span className="rounded-full bg-rose-400/15 px-2 py-0.5 text-[11px] text-rose-200">failed</span>}
            </div>
            <ol className="space-y-1">
              {stages.map(([name, s]) => (
                <li key={name} className="flex items-start gap-2 text-[12.5px]">
                  <span className="mt-0.5"><StatusIcon status={s!.status} /></span>
                  <span className={cn('shrink-0', s!.status === 'failed' ? 'text-rose-200' : 'text-slate-200')}>{LABELS[name]}</span>
                  {s!.detail && <span className={cn('min-w-0 break-words', s!.status === 'failed' ? 'text-rose-200/90' : 'text-slate-400')}>— {s!.detail}</span>}
                </li>
              ))}
              {!stages.length && <li className="text-[12.5px] text-slate-400">Not started</li>}
            </ol>
          </div>
        )
      })}
    </div>
  )
}
