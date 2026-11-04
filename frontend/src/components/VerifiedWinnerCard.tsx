import { motion } from 'framer-motion'
import { BarChart3, BookOpen, Calculator, ChevronDown, Database, ExternalLink, Globe, Lightbulb, RotateCcw, ThumbsDown, ThumbsUp } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { cn, spring } from '../lib/cn'
import { normalizeSql, SqlBlock } from '../lib/code'
import type { Check, Consensus, LaneState, Mode } from '../types/consensus'
import { CodeBlock } from './CodeBlock'
import { Markdown } from './Markdown'
import { StatusIcon } from './ParallelRaceTrace'
import { useToast } from './Toast'

const ROUTE = {
  data: { icon: Database, label: 'From your data' },
  web: { icon: Globe, label: 'From the web' },
  general: { icon: BookOpen, label: 'General knowledge' },
  arithmetic: { icon: Calculator, label: 'Exact calculation' },
} as const

const TONE: Record<Check['status'], string> = {
  passed: 'bg-emerald-400/10 text-emerald-200', warning: 'bg-amber-400/10 text-amber-200',
  failed: 'bg-rose-400/10 text-rose-200', not_run: 'bg-white/[0.06] text-slate-300',
}

export function VerifiedWinnerCard({ question, consensus, lanes, mode, details, onOpenData, onRetry }: {
  question: string; consensus: Consensus; lanes: LaneState[]; mode: Mode; details: ReactNode; onOpenData?: () => void; onRetry?: () => void
}) {
  const toast = useToast()
  const [rated, setRated] = useState<'up' | 'down' | null>(null)
  const [open, setOpen] = useState(false)
  const winner = consensus.route === 'arithmetic' ? undefined : lanes.find((l) => l.lane === consensus.winner_lane)
  const route = ROUTE[consensus.route] ?? ROUTE.general
  const checks = consensus.checks ?? []
  // The headline check: agreement for model answers, the search for web answers, the calculation for arithmetic.
  const headline = checks.find((c) => c.id === (consensus.route === 'web' ? 'search' : consensus.route === 'arithmetic' ? 'calculation' : 'agreement'))
  const problems = checks.some((c) => c.status === 'failed') || checks.some((c) => c.id === 'models')
  // Show the query up front when the user asked for it; otherwise it stays under "How this was checked".
  const showSql = Boolean(consensus.sql) && /\b(sql|query|queries|code)\b/i.test(question) && !consensus.strict_format
  const ctx = consensus.data_context
  const metrics = consensus.metrics

  const rate = async (rating: 'up' | 'down') => {
    setRated(rating)
    const response = await fetch('/api/feedback', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, rating, winner_model: winner?.model.id ?? '', reliability: consensus.reliability, sql: consensus.sql, mode }),
    }).then((r) => r.json()).catch(() => ({ logged: false }))
    toast(response.logged ? 'Thanks for the feedback' : `Feedback not saved: ${response.error ?? 'unavailable'}`)
  }

  const detailsToggle = (
    <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-slate-300 hover:text-white">
      How this was checked <ChevronDown className={cn('h-4 w-4 transition', open && 'rotate-180')} />
    </button>
  )

  return (
    <motion.div layout initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={spring} className="px-1">
      {!consensus.strict_format && (
        <div className="mb-3 flex flex-wrap items-center gap-2 text-[12px]">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-white/15 px-2.5 py-1 font-medium text-slate-100">
            <route.icon className="h-3.5 w-3.5" /> {route.label}{consensus.route === 'web' ? ` · ${consensus.sources.length} sources` : ''}
          </span>
          {headline && (
            <span className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1', TONE[headline.status])} title={headline.detail}>
              <StatusIcon status={headline.status} /> {headline.label}
            </span>
          )}
          {winner && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 px-2.5 py-1 text-slate-300">
              <span className="h-2 w-2 rounded-full" style={{ background: winner.model.color }} />
              Written by <span className="font-medium text-white">{winner.model.name}</span>
            </span>
          )}
        </div>
      )}
      <Markdown text={consensus.narrative} sources={consensus.sources} />
      {showSql && <div className="mt-4"><CodeBlock lang="sql" code={normalizeSql(consensus.sql).join('\n')} /></div>}
      {!consensus.strict_format && ctx && (
        <dl className="mt-3 grid gap-x-4 gap-y-1 rounded-xl border border-white/[0.07] bg-white/[0.02] px-3 py-2 text-[12px] text-slate-300 sm:grid-cols-[auto_1fr]">
          <dt className="text-slate-400">Source</dt><dd className="font-mono text-[11.5px]">{ctx.tables.join(', ')}</dd>
          {ctx.coverage && <><dt className="text-slate-400">Data coverage</dt><dd>{ctx.coverage}</dd></>}
          <dt className="text-slate-400">Filters applied</dt><dd className="font-mono text-[11.5px]">{ctx.filters}</dd>
          {ctx.freshness && <><dt className="text-slate-400">Freshness</dt><dd>{ctx.freshness}</dd></>}
          {ctx.currency && <><dt className="text-slate-400">Currency</dt><dd>{ctx.currency}</dd></>}
        </dl>
      )}
      {!consensus.strict_format && consensus.insights.length > 0 && (
        <ul className="mt-4 space-y-1.5">
          {consensus.insights.map((insight) => (
            <li key={insight} className="flex gap-2 text-[13.5px] text-slate-200">
              <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-sky-300" /> <Markdown text={insight} sources={consensus.sources} />
            </li>
          ))}
        </ul>
      )}
      {!consensus.strict_format && consensus.sources?.length > 0 && (
        <ol className="mt-4 space-y-1.5" aria-label="Sources">
          {consensus.sources.map((s) => (
            <li key={s.n} className="flex gap-2 text-[12.5px]">
              <span className="mt-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-sky-400/15 text-[10.5px] font-semibold text-sky-200">{s.n}</span>
              <span className="min-w-0">
                <a href={s.url} target="_blank" rel="noopener noreferrer nofollow" className="inline-flex items-center gap-1 text-slate-100 hover:text-sky-200 hover:underline">
                  {s.title} <ExternalLink className="h-3 w-3 shrink-0 text-slate-400" />
                </a>
                <span className="block text-slate-400">
                  {[s.publisher, s.published && `published ${s.published}`, s.retrieved_at && `retrieved ${s.retrieved_at}`].filter(Boolean).join(' · ')}
                </span>
              </span>
            </li>
          ))}
        </ol>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-2 text-[12.5px]">
        {onOpenData && !consensus.strict_format && (
          <button type="button" onClick={onOpenData} className="flex items-center gap-1.5 rounded-lg bg-sky-500/15 px-3 py-1.5 text-sky-100 hover:bg-sky-500/25">
            <BarChart3 className="h-4 w-4" /> View chart &amp; data
          </button>
        )}
        {detailsToggle}
        {onRetry && problems && (
          <button type="button" onClick={onRetry} className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-slate-200 hover:bg-white/5">
            <RotateCcw className="h-3.5 w-3.5" /> Retry
          </button>
        )}
        <div className="ml-auto flex items-center gap-1 text-slate-300">
          Helpful?
          {(['up', 'down'] as const).map((r) => (
            <button key={r} type="button" onClick={() => rate(r)} disabled={rated !== null} aria-label={r === 'up' ? 'Helpful' : 'Not helpful'}
              className={cn('rounded-lg p-1.5 transition disabled:cursor-default', rated === r ? 'bg-sky-400/15 text-sky-100' : 'hover:text-white disabled:opacity-40')}>
              {r === 'up' ? <ThumbsUp className="h-4 w-4" /> : <ThumbsDown className="h-4 w-4" />}
            </button>
          ))}
        </div>
      </div>
      {open && (
        <div className="mt-3 space-y-3">
          <ul className="space-y-1.5 rounded-xl border border-white/[0.07] bg-white/[0.02] p-3" aria-label="Checks">
            {checks.map((c) => (
              <li key={c.id} className="flex gap-2 text-[12.5px]">
                <span className="mt-0.5"><StatusIcon status={c.status} /></span>
                <span><span className="text-slate-100">{c.label}</span>{c.detail && <span className="block text-slate-400">{c.detail}</span>}</span>
              </li>
            ))}
            {consensus.agreement.message && consensus.route !== 'arithmetic' && (
              <li className="pl-6 text-[12px] text-slate-400">{consensus.agreement.message}</li>
            )}
          </ul>
          {consensus.limitations?.length > 0 && (
            <div className="text-[12px] text-slate-300">
              <span className="font-medium text-slate-200">Limitations: </span>{consensus.limitations.join(' ')}
            </div>
          )}
          {metrics && (
            <div className="text-[12px] text-slate-400">
              {(metrics.total_ms / 1000).toFixed(1)}s total · {metrics.calls.filter((c) => c.purpose !== 'probe').length} model calls ·{' '}
              {metrics.calls.reduce((n, c) => n + c.prompt_tokens + c.completion_tokens, 0).toLocaleString()} tokens
              {metrics.queries_executed > 0 && ` · ${metrics.queries_executed} quer${metrics.queries_executed === 1 ? 'y' : 'ies'} run${metrics.queries_reused ? `, ${metrics.queries_reused} reused` : ''}`}
            </div>
          )}
          {consensus.sql && !showSql && <SqlBlock sql={consensus.sql} className="max-h-44" />}
          {details}
        </div>
      )}
    </motion.div>
  )
}
