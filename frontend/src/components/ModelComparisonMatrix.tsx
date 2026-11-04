import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, CheckCircle2, ChevronDown, Crown, Info, PanelRightOpen, XCircle } from 'lucide-react'
import { useState } from 'react'
import { cn, spring } from '../lib/cn'
import { SqlBlock } from '../lib/code'
import type { Consensus, LaneState } from '../types/consensus'
import { Markdown } from './Markdown'

const ok = ['border-emerald-400/30 bg-emerald-400/10 text-emerald-100', CheckCircle2] as const
const warn = ['border-amber-400/30 bg-amber-400/10 text-amber-100', AlertTriangle] as const
const bad = ['border-rose-400/30 bg-rose-400/10 text-rose-100', XCircle] as const
const info = ['border-sky-400/30 bg-sky-400/10 text-sky-100', Info] as const
const bannerStyle = { match: ok, partial: warn, incomplete: warn, different: warn, single: warn, conflict: bad, none: bad, text: info } as const

export function ModelComparisonMatrix({ consensus, lanes, defaultOpen, onPromote }: {
  consensus: Consensus | undefined; lanes: LaneState[]; defaultOpen: boolean; onPromote: (lane: LaneState) => void
}) {
  const [open, setOpen] = useState(defaultOpen)
  const winnerSql = lanes.find((l) => l.lane === consensus?.winner_lane)?.result?.sql
  const [style, Icon] = bannerStyle[consensus?.agreement.kind ?? 'text']
  return (
    <div className="rounded-2xl border border-white/10 bg-slate-900/50 backdrop-blur-xl">
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 px-4 py-3 text-left text-[13px] font-semibold text-white">
        Compare each model's answer and SQL
        <span className="text-[11px] font-normal text-slate-400">{lanes.length} models</span>
        <ChevronDown className={cn('ml-auto h-4 w-4 text-slate-400 transition', open && 'rotate-180')} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={spring} className="overflow-hidden">
            <div className="space-y-3 px-4 pb-4">
              {consensus && (
                <div className={cn('flex gap-2 rounded-xl border p-3 text-[12.5px]', style)}>
                  <Icon className="mt-0.5 h-4 w-4 shrink-0" /> {consensus.agreement.message}
                </div>
              )}
              <div className={cn('grid gap-3', lanes.length >= 3 ? 'lg:grid-cols-3' : 'lg:grid-cols-2')}>
                {lanes.map((lane) => {
                  const r = lane.result
                  const isWinner = consensus?.winner_lane === lane.lane
                  const inMajority = consensus?.groups[0]?.includes(lane.lane)
                  return (
                    <motion.div key={lane.lane} layout transition={spring}
                      className={cn('flex min-w-0 flex-col rounded-xl border bg-black/20 p-3', isWinner ? 'border-amber-300/40' : 'border-white/[0.07]')}
                      style={{ boxShadow: `inset 3px 0 0 ${lane.model.color}` }}>
                      <div className="flex items-center gap-2">
                        <span className="text-[13px] font-semibold text-white">{lane.model.name}</span>
                        {isWinner && <Crown className="h-3.5 w-3.5 text-amber-300" />}
                        {consensus && !isWinner && (
                          <span className={cn('rounded-full px-1.5 py-0.5 font-mono text-[9.5px]', inMajority ? 'bg-emerald-400/10 text-emerald-300' : 'bg-rose-400/10 text-rose-300')}>
                            {r?.error ? 'failed' : inMajority ? 'matches' : 'differs'}
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-slate-400">{lane.model.provider}</div>
                      <div className="mt-2 grid grid-cols-3 gap-1 font-mono text-[10.5px]">
                        {[
                          ['latency', r ? `${r.latency_ms}ms` : '—'],
                          ['speed', r ? `${r.tokens_per_second}t/s` : '—'],
                          ['cost', r?.cost_usd != null ? `$${r.cost_usd.toFixed(4)}` : 'n/a'],
                        ].map(([k, v]) => (
                          <div key={k} className="rounded-md bg-white/[0.03] px-1.5 py-1"><div className="text-slate-400">{k}</div><div className="truncate text-slate-200">{v}</div></div>
                        ))}
                      </div>
                      {r?.reasoning && <p className="mt-2 text-[12px] text-slate-400">{r.reasoning}</p>}
                      {r?.error && <p className="mt-2 rounded-md bg-rose-500/10 p-2 text-[11.5px] text-rose-200">{r.error}</p>}
                      {!!r?.issues?.length && (
                        <ul className="mt-2 space-y-1 rounded-md bg-amber-400/10 p-2 text-[11.5px] text-amber-100">{r.issues.map((i) => <li key={i}>• {i}</li>)}</ul>
                      )}
                      {r?.result && <div className="mt-1 text-[11px] text-slate-400">{r.result.row_count.toLocaleString()} rows · warehouse {r.warehouse_ms}ms{r.reused_query ? ' · same query as another model' : ''}</div>}
                      {r?.sql && <SqlBlock sql={r.sql} compareTo={!isWinner && winnerSql ? winnerSql : undefined} className="mt-2 max-h-44" />}
                      {r && !r.needs_data && r.answer && <div className="mt-2 max-h-40 overflow-y-auto rounded-lg bg-white/[0.02] p-2 text-[12px]"><Markdown text={r.answer} /></div>}
                      {r?.result && (
                        <button type="button" onClick={() => onPromote(lane)}
                          className="mt-auto flex items-center justify-center gap-1.5 rounded-lg border border-sky-400/30 bg-sky-500/10 px-2.5 py-1.5 text-[11.5px] text-sky-200 hover:bg-sky-500/20 [margin-top:12px]">
                          <PanelRightOpen className="h-3.5 w-3.5" /> Open this model's result in the data panel
                        </button>
                      )}
                    </motion.div>
                  )
                })}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
