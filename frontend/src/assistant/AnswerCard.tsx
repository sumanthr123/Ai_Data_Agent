import { AlertTriangle, Check, CircleCheck, Copy, Download, FileSearch, Globe, Lock, Pencil, RotateCcw, Scale, ShieldAlert, WifiOff } from 'lucide-react'
import { lazy, memo, Suspense, useEffect, useRef, useState, type ReactNode } from 'react'
import { CodeBlock } from '../components/CodeBlock'
import { Markdown } from '../components/Markdown'
import { SourceList } from '../components/SourceList'
import { cn } from '../lib/cn'
import { CodeAnswer, CouncilView, DocSources, KindBadge, ModelsUsed } from './AnswerParts'
import { downloadCsv } from './api'
import { chartPlan, kpiOf } from './chartPlan'
import { fmtCell, humanize, layoutSql, relativeTime } from './format'
import { followups, type FollowupColumn } from './followups'
import { ResultTable } from './ResultTable'
import { StatusSteps } from './StatusSteps'
import type { AskResponse, Turn } from './types'

const ResultChart = lazy(() => import('./ResultChart').then((m) => ({ default: m.ResultChart })))  // recharts loads with the first chart

export type TurnAction =
  | { type: 'details' } | { type: 'retry' } | { type: 'council' } | { type: 'focus' }
  | { type: 'ask'; text: string } | { type: 'prefill'; text: string }

export interface DatasetShape { columns: FollowupColumn[]; dateColumn: string | null }

type Problem = { kind: 'cancelled' | 'permission' | 'busy' | 'connection' | 'failed'; title: string; body: string; technical: string }

const PERMISSION = /permission|not authori[sz]ed|access denied|insufficient[_ ]privileges|forbidden|\b403\b/i
const BUSY = /rate.?limit|throttl|\b429\b|too many requests|busy|capacity/i
const CONNECTION = /connection (closed|lost|reset)|network|failed to fetch|load failed/i

/** Business language first; the raw message stays one click away. */
export function problemOf(turn: Turn): Problem | null {
  const r = turn.response
  if (turn.cancelled) return { kind: 'cancelled', title: 'Stopped by you', body: 'Nothing further ran on the warehouse. The steps that finished are kept above.', technical: '' }
  const raw = turn.error ?? (r?.status === 'ERROR' ? r.answer : '')
  if (!raw) return null
  if (PERMISSION.test(raw)) return { kind: 'permission', title: "You don't have access to this data", body: 'Access is controlled by Unity Catalog. Copy the details below and send them to the data owner, or try a question about data you can see.', technical: raw }
  if (BUSY.test(raw)) return { kind: 'busy', title: 'The service is busy', body: 'A model or the SQL warehouse is at its limit right now.', technical: raw }
  if (CONNECTION.test(raw)) return { kind: 'connection', title: 'Connection lost', body: 'The answer stopped arriving. Re-run asks the question again.', technical: raw }
  return { kind: 'failed', title: "Couldn't answer this", body: r?.status === 'ERROR' ? 'A step failed. The steps that finished are kept above.' : 'The request failed before an answer arrived.', technical: raw }
}

function TrustBadge({ r }: { r: AskResponse }) {
  const base = 'inline-flex items-center gap-1.5 text-[12.5px] font-medium'
  if (r.status === 'ANSWERED' && r.web_sources?.length) return <span className={cn(base, 'text-fg-2')}><Globe className="h-4 w-4" aria-hidden /> From the web, not your data · {r.web_sources.length} source{r.web_sources.length === 1 ? '' : 's'}</span>
  if (r.status === 'ANSWERED' && r.kind === 'docs') return <span className={cn(base, 'text-ok')}><CircleCheck className="h-4 w-4" aria-hidden /> Checked against the cited docs</span>
  if (r.status === 'ANSWERED' && r.kind === 'code') return <span className={cn(base, 'text-fg-2')}>Static checks only; not executed</span>
  if (r.status === 'ANSWERED' && r.kind === 'chat') return null
  if (r.status === 'ANSWERED' && r.verification.reviewed) return <span className={cn(base, 'text-ok')}><CircleCheck className="h-4 w-4" aria-hidden /> Reviewed by a second model</span>
  if (r.status === 'ANSWERED') return <span className={cn(base, 'text-warn')}><ShieldAlert className="h-4 w-4" aria-hidden /> Not reviewed: check the SQL</span>
  if (r.status === 'UNRESOLVED') return <span className={cn(base, 'text-warn')}><Scale className="h-4 w-4" aria-hidden /> Models disagreed: no answer picked</span>
  if (r.status === 'BUDGET_EXHAUSTED') return <span className={cn(base, 'text-warn')}><AlertTriangle className="h-4 w-4" aria-hidden /> Stopped at the cost limit</span>
  return null
}

function ActionButton({ onClick, children, label, disabled }: { onClick: () => void; children: ReactNode; label?: string; disabled?: boolean }) {
  return (
    <button type="button" onClick={onClick} aria-label={label} disabled={disabled}
      className="inline-flex min-h-8 items-center gap-1.5 rounded-md px-2.5 text-[12.5px] text-fg-2 hover:bg-surface-2 hover:text-fg disabled:opacity-50">
      {children}
    </button>
  )
}

/** One automatic retry after a visible countdown; Cancel stops it. */
function BusyRetry({ onRetry }: { onRetry: () => void }) {
  const [left, setLeft] = useState(10)
  const [cancelled, setCancelled] = useState(false)
  const retry = useRef(onRetry)
  retry.current = onRetry
  const [fired, setFired] = useState(false)
  useEffect(() => {
    if (cancelled || fired) return
    if (left === 0) { setFired(true); retry.current(); return }
    const t = setTimeout(() => setLeft((s) => s - 1), 1000)
    return () => clearTimeout(t)
  }, [left, cancelled, fired])
  if (fired) return <span className="inline-flex items-center gap-2 text-[12.5px] text-fg-2">Retried automatically <ActionButton onClick={onRetry}><RotateCcw className="h-3.5 w-3.5" aria-hidden /> Retry again</ActionButton></span>
  if (cancelled) return <ActionButton onClick={onRetry}><RotateCcw className="h-3.5 w-3.5" aria-hidden /> Retry now</ActionButton>
  return (
    <span className="inline-flex items-center gap-2 text-[12.5px] text-fg-2">
      Retrying in <span className="font-mono tnum">{left}s</span>…
      <ActionButton onClick={() => setCancelled(true)}>Cancel</ActionButton>
    </span>
  )
}

function ProblemBlock({ p, onAction }: { p: Problem; onAction: (a: TurnAction) => void }) {
  const [copied, setCopied] = useState<string | null>(null)
  const copyDetails = () => navigator.clipboard.writeText(p.technical)
    .then(() => setCopied('Copied'), (err: Error) => setCopied(`Copy failed: ${err.message}`))
  const Icon = p.kind === 'permission' ? Lock : p.kind === 'connection' ? WifiOff : AlertTriangle
  const tone = p.kind === 'cancelled' ? 'border-line bg-surface-2' : p.kind === 'busy' ? 'border-warn/40 bg-warn/5' : 'border-err/40 bg-err/5'
  return (
    <div role={p.kind === 'cancelled' ? undefined : 'alert'} className={cn('rounded-md border p-3', tone)}>
      <p className="flex items-center gap-2 text-[14px] font-medium text-fg"><Icon className="h-4 w-4 shrink-0" aria-hidden /> {p.title}</p>
      <p className="mt-1 text-[13px] text-fg-2">{p.body}</p>
      <div className="mt-2 flex flex-wrap items-center gap-1">
        {p.kind === 'busy' ? <BusyRetry onRetry={() => onAction({ type: 'retry' })} /> : p.kind !== 'permission' && (
          <ActionButton onClick={() => onAction({ type: 'retry' })}><RotateCcw className="h-3.5 w-3.5" aria-hidden /> Re-run</ActionButton>
        )}
        {p.kind === 'permission' && <ActionButton onClick={copyDetails}><Copy className="h-3.5 w-3.5" aria-hidden /> Copy request details</ActionButton>}
        {(p.kind === 'permission' || p.kind === 'cancelled') && <ActionButton onClick={() => onAction({ type: 'focus' })}>Ask something else</ActionButton>}
        {copied && <span className="text-[12px] text-fg-3" role="status">{copied}</span>}
      </div>
      {p.technical && (
        <details className="mt-2 text-[12px]">
          <summary className="cursor-pointer text-fg-3">Technical details</summary>
          <pre className="mt-1 whitespace-pre-wrap break-words font-mono text-fg-2">{p.technical}</pre>
        </details>
      )}
    </div>
  )
}

function Kpi({ label, value, type }: { label: string; value: number; type: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface-2 px-4 py-3">
      <p className="text-[12px] font-medium uppercase tracking-wide text-fg-3">{humanize(label)}</p>
      <p className="mt-1 font-mono text-[40px] font-semibold leading-none tnum text-fg">{fmtCell(value, type)}</p>
    </div>
  )
}

/** Chart | Table toggle when a chart suits the result; the table is always one click away (the chart's text alternative). */
function Visual({ r, theme, onError }: { r: AskResponse; theme: string; onError: (m: string) => void }) {
  const result = r.result!
  const plan = r.status === 'ANSWERED' ? chartPlan(result) : null
  const [view, setView] = useState<'chart' | 'table'>(plan ? 'chart' : 'table')
  if (result.row_count === 0) return <p className="text-[13px] text-fg-2">The query returned no rows for this question and data.</p>
  if (r.status === 'ANSWERED' && kpiOf(result)) return null
  return (
    <div className="space-y-2">
      {plan && (
        <div role="group" aria-label="View" className="inline-flex rounded-md border border-line p-0.5">
          {(['chart', 'table'] as const).map((v) => (
            <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)}
              className={cn('min-h-7 rounded px-3 text-[12.5px] capitalize', view === v ? 'bg-surface-2 font-medium text-fg' : 'text-fg-2 hover:text-fg')}>{v}</button>
          ))}
        </div>
      )}
      {plan && view === 'chart'
        ? <Suspense fallback={<div className="skeleton h-[290px] rounded-lg" />}><ResultChart result={result} plan={plan} theme={theme} onError={onError} /></Suspense>
        : <ResultTable result={result} />}
    </div>
  )
}

function HowIGotThis({ turn, r, onDetails }: { turn: Turn; r: AskResponse; onDetails: () => void }) {
  return (
    <details className="group rounded-md border border-line">
      <summary className="flex min-h-9 cursor-pointer items-center gap-2 px-3 text-[13px] font-medium text-fg-2 hover:text-fg">
        <FileSearch className="h-4 w-4" aria-hidden /> How I got this
      </summary>
      <div className="space-y-4 border-t border-line p-3 text-[13px]">
        <StatusSteps stages={turn.stages} live={false} compact />
        {r.sql && <CodeBlock code={layoutSql(r.sql)} lang="sql" />}
        {r.sources.length > 0 && (
          <div>
            <p className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-fg-3">Sources</p>
            <ul className="space-y-0.5">
              {r.sources.map((s) => (
                <li key={s.table} className="text-fg-2">
                  <span className="font-mono text-fg">{s.table}</span> · data as of {s.updated_at ? `${s.updated_at.slice(0, 16).replace('T', ' ')} UTC (${relativeTime(s.updated_at)})` : 'unknown'}
                </li>
              ))}
            </ul>
          </div>
        )}
        {r.assumptions.length > 0 && (
          <div>
            <p className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-fg-3">Assumptions</p>
            <ul className="list-disc space-y-0.5 pl-5 text-fg-2">{r.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
          </div>
        )}
        <ModelsUsed r={r} />
        <button type="button" onClick={onDetails} className="min-h-6 text-[12.5px] text-brand underline-offset-2 hover:underline">All details: checks, models, cost</button>
      </div>
    </details>
  )
}

/** Memoized: typing in the composer or a stage event on the live turn doesn't re-render earlier answers. */
export const AnswerCard = memo(function AnswerCard({ turn, live, theme, shape, onAction }: {
  turn: Turn; live: boolean; theme: string; shape: DatasetShape; onAction: (turn: Turn, action: TurnAction) => void
}) {
  const act = (a: TurnAction) => onAction(turn, a)
  const r = turn.response
  const problem = problemOf(turn)
  const [note, setNote] = useState<string | null>(null)
  const kpi = r?.status === 'ANSWERED' && r.result ? kpiOf(r.result) : null
  const answered = r?.status === 'ANSWERED' && (r.kind ?? 'data') === 'data'
  const next = answered && r.result ? followups({ question: turn.question, resultColumns: r.result.columns, datasetColumns: shape.columns, dateColumn: shape.dateColumn }) : []
  const asOf = r?.sources.find((s) => s.kind === 'shared')?.updated_at ?? null

  const copySummary = () => r && navigator.clipboard.writeText(r.answer).then(() => setNote('Summary copied'), (err: Error) => setNote(`Copy failed: ${err.message}`))
  const exportCsv = () => r?.sql && downloadCsv(r.sql, turn.datasets).then(() => setNote('CSV downloaded'), (err: Error) => setNote(`Export failed: ${err.message}`))

  return (
    <article className="space-y-2">
      <h3 className="sr-only">You asked</h3>
      <p className="whitespace-pre-wrap text-[15px] font-medium text-fg">{turn.question}</p>
      <section className="space-y-4 rounded-lg border border-line bg-surface p-4">
        <h3 className="sr-only">AI Data Assistant answered</h3>
        {(live || !r) && <StatusSteps stages={turn.stages} live={live} startedAt={turn.startedAt} />}
        {live && <div className="skeleton h-[290px] rounded-lg" aria-hidden />}
        {problem && <ProblemBlock p={problem} onAction={act} />}

        {r && r.status !== 'ERROR' && (
          <div className="reveal space-y-4">
            {r.status === 'NEEDS_CLARIFICATION' && r.clarifying_question ? (
              <div className="space-y-2">
                <p className="text-[15px] text-fg">{r.clarifying_question}</p>
                <p className="text-[13px] text-fg-2">Nothing is computed until you choose.</p>
                <button type="button" onClick={() => act({ type: 'focus' })} className="min-h-8 rounded-md border border-line-strong px-3 text-[13px] text-fg hover:bg-surface-2">Answer in the box below</button>
              </div>
            ) : (
              <>
                {kpi && <Kpi {...kpi} />}
                {r.answer && <div className="text-[15px] leading-relaxed"><Markdown text={r.answer} sources={r.web_sources} /></div>}
              </>
            )}

            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <TrustBadge r={r} />
              <KindBadge kind={r.kind ?? 'data'} />
              {asOf && <span className="text-[12.5px] text-fg-3">Data as of {relativeTime(asOf)}</span>}
              {r.from_cache && <span className="text-[12.5px] text-fg-3" title="Same question on the same data version, answered in the last few minutes">· cached</span>}
              {r.freshness_unmet && <span className="text-[12.5px] text-warn">· the data may be older than this question needs</span>}
            </div>

            {r.filters.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5" aria-label="How the question was read">
                {r.filters.map((f) => (
                  <button key={f} type="button" onClick={() => act({ type: 'prefill', text: `${turn.question} Change the filter ${f} to ` })}
                    className="inline-flex min-h-7 items-center gap-1.5 rounded-md border border-line bg-surface-2 px-2 font-mono text-[12px] text-fg-2 hover:border-line-strong hover:text-fg"
                    aria-label={`Change filter ${f}`}>
                    {f}<Pencil className="h-3 w-3" aria-hidden />
                  </button>
                ))}
              </div>
            )}

            {r.result && <Visual r={r} theme={theme} onError={setNote} />}
            {!!r.web_sources?.length && <SourceList sources={r.web_sources} />}
            {r.code && <CodeAnswer code={r.code} />}
            {!!r.doc_sources?.length && <DocSources sources={r.doc_sources} />}
            {r.council && <CouncilView council={r.council} />}
            {r.answer_truncated && <p className="text-[12.5px] text-fg-3">Shortened to the answer length limit; ask for a full breakdown to see more.</p>}
            {r.hypotheses.length > 0 && (
              <details className="rounded-md border border-line p-3 text-[13px]">
                <summary className="cursor-pointer text-fg-2">Possible explanations (hypotheses the data doesn't prove)</summary>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-fg-2">{r.hypotheses.map((h) => <li key={h}>{h}</li>)}</ul>
              </details>
            )}

            {(r.kind ?? 'data') === 'data' && <HowIGotThis turn={turn} r={r} onDetails={() => act({ type: 'details' })} />}

            <div className="flex flex-wrap items-center gap-1 border-t border-line pt-2">
              {r.answer && <ActionButton onClick={copySummary}><Copy className="h-3.5 w-3.5" aria-hidden /> Copy summary</ActionButton>}
              {r.sql && (r.kind ?? 'data') === 'data' && <ActionButton onClick={exportCsv}><Download className="h-3.5 w-3.5" aria-hidden /> Export CSV</ActionButton>}
              <ActionButton onClick={() => act({ type: 'retry' })}><RotateCcw className="h-3.5 w-3.5" aria-hidden /> Re-run</ActionButton>
              {(r.kind ?? 'data') === 'data' && r.sql && !r.council && <ActionButton onClick={() => act({ type: 'council' })}><Scale className="h-3.5 w-3.5" aria-hidden /> Verify with council</ActionButton>}
              {note && <span className="ml-1 inline-flex items-center gap-1 text-[12px] text-fg-3" role="status"><Check className="h-3.5 w-3.5" aria-hidden />{note}</span>}
            </div>
          </div>
        )}
      </section>

      {next.length > 0 && !live && (
        <nav aria-label="Follow-up questions" className="flex flex-wrap items-center gap-1.5 pt-1">
          <span className="text-[12.5px] text-fg-3">Follow up:</span>
          {next.map((q) => (
            <button key={q} type="button" onClick={() => act({ type: 'ask', text: q })}
              className="min-h-7 rounded-full border border-line px-3 text-[12.5px] text-fg-2 hover:border-brand hover:text-fg">{q}</button>
          ))}
        </nav>
      )}
    </article>
  )
})
