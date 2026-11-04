import { cn } from '../lib/cn'
import type { LaneState, PipelineStage, Turn } from '../types/consensus'
import { StatusIcon } from './ParallelRaceTrace'

// Steps per route. Only the chosen route's steps are shown, and each step's state comes from real events.
const STEPS: Record<string, [PipelineStage | 'execute' | 'answer', string][]> = {
  data: [['execute', 'Running queries'], ['compare', 'Comparing results'], ['validate', 'Checking against your question'], ['write', 'Writing answer']],
  web: [['search', 'Searching the web'], ['answer', 'Answering from sources'], ['write', 'Writing cited answer']],
  general: [['compare', 'Comparing answers'], ['write', 'Writing answer']],
  arithmetic: [['write', 'Calculating']],
}

function laneStatus(lanes: LaneState[], stage: 'execute' | 'answer') {
  const states = lanes.map((l) => l.stages[stage]?.status).filter(Boolean)
  if (!states.length) return 'pending'
  if (states.includes('running')) return 'running'
  return states.every((s) => s === 'failed') ? 'failed' : 'succeeded'
}

export function ThinkingStatus({ turn }: { turn: Turn }) {
  const planning = turn.lanes.filter((l) => l.stages.plan?.status === 'running').length
  // Until the route is confirmed, show the steps of the route most models are taking.
  const votes = turn.lanes.map((l) => l.route).filter((r): r is NonNullable<typeof r> => Boolean(r))
  const likely = turn.route ?? votes.sort((a, b) => votes.filter((v) => v === b).length - votes.filter((v) => v === a).length)[0]
  const steps = likely ? STEPS[likely] : []
  return (
    <div role="status" aria-live="polite" className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-2xl border border-white/10 bg-slate-900/50 px-4 py-3 text-[13px]">
      <span className="flex items-center gap-1.5 text-slate-200">
        <StatusIcon status={turn.route ? 'succeeded' : 'running'} />
        {turn.route ? `Route: ${{ data: 'your data', web: 'live web', general: 'general knowledge', arithmetic: 'calculation' }[turn.route]}`
          : planning ? `${planning} model(s) planning…` : turn.lanes.length ? 'Models working…' : 'Starting…'}
      </span>
      <ol className="flex flex-wrap items-center gap-3 text-[12.5px]">
        {steps.map(([id, label]) => {
          const status = id === 'execute' || id === 'answer' ? laneStatus(turn.lanes, id) : turn.pipeline[id]?.status ?? 'pending'
          return (
            <li key={id} className={cn('flex items-center gap-1.5', status === 'pending' ? 'text-slate-400' : status === 'failed' ? 'text-rose-200' : 'text-slate-200')}>
              <StatusIcon status={status} /> {label}
            </li>
          )
        })}
      </ol>
    </div>
  )
}
