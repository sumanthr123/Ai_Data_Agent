import { Download, LoaderCircle, X } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { CodeBlock } from '../components/CodeBlock'
import { cn } from '../lib/cn'
import { downloadCsv } from './api'
import { layoutSql, relativeTime } from './format'
import { StatusIcon } from './StatusSteps'
import type { Check, Turn, Verification } from './types'

const TABS = ['SQL', 'Sources', 'Assumptions', 'Verification'] as const
type Tab = (typeof TABS)[number]

function Badge({ tone, children }: { tone: 'good' | 'warn' | 'bad' | 'neutral'; children: ReactNode }) {
  const tones = {
    good: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200', warn: 'border-amber-400/30 bg-amber-400/10 text-amber-200',
    bad: 'border-rose-400/30 bg-rose-400/10 text-rose-200', neutral: 'border-zinc-700 bg-zinc-800/60 text-zinc-300',
  }
  return <span className={cn('inline-flex items-center rounded-full border px-2 py-0.5 text-[11.5px] font-medium', tones[tone])}>{children}</span>
}

const roleTone = (status: string): 'good' | 'warn' | 'bad' | 'neutral' =>
  ['OK', 'APPROVED', 'RESOLVED'].includes(status) ? 'good' : ['DEGRADED', 'UNRESOLVED', 'CORRECTIVE_QUERY'].includes(status) ? 'warn'
    : ['FAILED', 'REJECTED'].includes(status) ? 'bad' : 'neutral'

const checkStatus = (c: Check) => (c.status === 'passed' ? 'succeeded' : c.status === 'failed' ? 'failed' : c.status === 'warning' ? 'running' : 'skipped')

function VerificationTab({ v }: { v: Verification }) {
  return (
    <div className="space-y-5">
      <section>
        <h3 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-zinc-400">Models</h3>
        <dl className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-2 text-[13px]">
          <dt className="text-zinc-300">Analyst</dt><dd><Badge tone={roleTone(v.analyst)}>{v.analyst}</Badge></dd>
          <dt className="text-zinc-300">Reviewer</dt><dd><Badge tone={roleTone(v.reviewer)}>{v.reviewer}</Badge>{v.correction_cycles > 0 && <span className="ml-2 text-[12px] text-zinc-400">after {v.correction_cycles} correction</span>}</dd>
          <dt className="text-zinc-300">Adjudicator</dt><dd><Badge tone={roleTone(v.adjudicator)}>{v.adjudicator.replace('_', ' ')}</Badge></dd>
        </dl>
        <p className="mt-3 text-[12.5px] text-zinc-400">
          {v.reviewed ? 'Reviewed: an independent model approved it and every automated check passed.'
            : 'Not marked reviewed: the independent review did not complete and pass, or an automated check failed.'}
        </p>
      </section>
      {v.degraded_reasons.length > 0 && (
        <section className="rounded-lg border border-amber-400/30 bg-amber-400/5 p-3 text-[12.5px] text-amber-100">
          <div className="mb-1 font-medium">Reduced verification</div>
          <ul className="list-disc space-y-1 pl-4">{v.degraded_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        </section>
      )}
      <section>
        <h3 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-zinc-400">Automated checks</h3>
        <ul className="space-y-2 text-[12.5px]">
          {v.checks.map((c, i) => (
            <li key={i} className="flex gap-2"><StatusIcon status={checkStatus(c)} />
              <span><span className="font-mono text-zinc-200">{c.name}</span> <span className="text-zinc-400">{c.detail}</span></span></li>
          ))}
          {v.checks.length === 0 && <li className="text-zinc-400">No checks ran (no query was executed).</li>}
        </ul>
      </section>
      {v.open_issues.length > 0 && (
        <section>
          <h3 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-zinc-400">Review notes</h3>
          <ul className="space-y-1.5 text-[12.5px]">{v.open_issues.map((i, k) => (
            <li key={k} className="flex gap-2"><Badge tone={i.severity === 'high' ? 'bad' : i.severity === 'medium' ? 'warn' : 'neutral'}>{i.severity}</Badge><span className="text-zinc-300">{i.description}</span></li>
          ))}</ul>
        </section>
      )}
      <section>
        <h3 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-zinc-400">Cost and latency</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead><tr className="text-left text-zinc-400"><th className="py-1 pr-2 font-medium">Call</th><th className="pr-2 font-medium">Status</th><th className="pr-2 text-right font-medium">In</th><th className="pr-2 text-right font-medium">Out</th><th className="pr-2 text-right font-medium">Think</th><th className="text-right font-medium">Time</th></tr></thead>
            <tbody className="font-mono tabular-nums">
              {v.calls.map((c, i) => (
                <tr key={i} className="border-t border-zinc-800" title={c.endpoint + (c.error ? ` · ${c.error}` : '')}>
                  <td className="py-1 pr-2 font-sans text-zinc-200">{c.role} · {c.purpose}</td>
                  <td className={cn('pr-2 font-sans', c.status === 'ok' ? 'text-zinc-300' : 'text-amber-300')}>{c.status.replace('_', ' ')}</td>
                  <td className="pr-2 text-right text-zinc-300">{c.prompt_tokens.toLocaleString()}</td>
                  <td className="pr-2 text-right text-zinc-300">{c.completion_tokens.toLocaleString()}</td>
                  <td className="pr-2 text-right text-zinc-300">{c.reasoning_tokens.toLocaleString()}</td>
                  <td className="text-right text-zinc-300">{(c.latency_ms / 1000).toFixed(1)}s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[12px] text-zinc-400">
          {v.total_model_calls} model calls · {v.total_tokens.toLocaleString()} tokens · {v.sql_attempts} SQL attempt{v.sql_attempts === 1 ? '' : 's'}
          {v.cost_estimate_usd !== null ? ` · est. $${v.cost_estimate_usd.toFixed(4)}` : ' · cost estimate not configured'}
        </p>
      </section>
    </div>
  )
}

export function EvidenceDrawer({ turn, onClose }: { turn: Turn | null; onClose: () => void }) {
  const [tab, setTab] = useState<Tab>('SQL')
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const r = turn?.response
  const download = async () => {
    if (!r?.sql) return
    setDownloading(true)
    setDownloadError(null)
    try {
      await downloadCsv(r.sql, turn!.datasets)
    } catch (err) {
      setDownloadError((err as Error).message)
    } finally {
      setDownloading(false)
    }
  }
  return (
    <aside aria-label="Evidence" className="flex h-full flex-col bg-zinc-950">
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
        <h2 className="text-[14px] font-semibold text-zinc-100">Evidence</h2>
        <div className="flex items-center gap-1">
          {r?.sql && (
            <button type="button" onClick={download} disabled={downloading}
              className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 px-2.5 py-1.5 text-[12.5px] text-zinc-100 hover:bg-zinc-800 disabled:opacity-60">
              {downloading ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />} CSV
            </button>
          )}
          <button type="button" onClick={onClose} aria-label="Close evidence" className="rounded-lg p-1.5 text-zinc-300 hover:bg-zinc-800"><X className="h-4 w-4" /></button>
        </div>
      </div>
      {downloadError && <p role="alert" className="border-b border-zinc-800 bg-rose-500/10 px-4 py-2 text-[12px] text-rose-200">Download failed: {downloadError}</p>}
      {!r ? (
        <p className="p-4 text-[13px] text-zinc-400">Ask a question to see the executed SQL, sources, assumptions and how the answer was checked.</p>
      ) : (
        <>
          <div role="tablist" aria-label="Evidence sections" className="flex gap-1 border-b border-zinc-800 px-2">
            {TABS.map((t) => (
              <button key={t} role="tab" type="button" aria-selected={tab === t} onClick={() => setTab(t)}
                className={cn('border-b-2 px-2.5 py-2 text-[12.5px]', tab === t ? 'border-sky-400 text-white' : 'border-transparent text-zinc-400 hover:text-zinc-200')}>
                {t}
              </button>
            ))}
          </div>
          <div role="tabpanel" className="min-h-0 flex-1 overflow-y-auto p-4">
            {tab === 'SQL' && (r.sql ? (
              <div className="space-y-3">
                <CodeBlock code={layoutSql(r.sql)} lang="sql" />
                {r.filters.length > 0 && (
                  <div>
                    <h3 className="mb-1.5 text-[12px] font-semibold uppercase tracking-wide text-zinc-400">Filters applied</h3>
                    <ul className="space-y-1">{r.filters.map((f) => <li key={f} className="font-mono text-[12px] text-zinc-200">{f}</li>)}</ul>
                  </div>
                )}
                {r.result && <p className="text-[12px] text-zinc-400">Statement {r.result.statement_id ?? '—'} · {r.result.row_count.toLocaleString()} rows · {(r.result.runtime_ms / 1000).toFixed(1)}s{r.result.from_cache ? ' · cached' : ''}</p>}
              </div>
            ) : <p className="text-[13px] text-zinc-400">No SQL ran for this answer.</p>)}
            {tab === 'Sources' && (
              <div className="space-y-4">
                {r.sources.map((s) => (
                  <div key={s.table} className="rounded-lg border border-zinc-800 p-3">
                    <div className="break-all font-mono text-[12.5px] text-zinc-100">{s.table}</div>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      <Badge tone="neutral">{s.kind === 'upload' ? 'Your upload' : 'Shared dataset'}</Badge>
                      {s.row_count !== null && <Badge tone="neutral">{s.row_count.toLocaleString()} rows</Badge>}
                      {s.date_range && <Badge tone="neutral">{s.date_range[0]} → {s.date_range[1]}</Badge>}
                    </div>
                    <p className="mt-2 text-[12px] text-zinc-400">Updated {relativeTime(s.updated_at)}{s.expires_at ? ` · deleted ${relativeTime(s.expires_at)}` : ''}</p>
                    {s.warnings.length > 0 && <ul className="mt-2 list-disc space-y-1 pl-4 text-[12px] text-amber-200">{s.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
                  </div>
                ))}
                <p className="rounded-lg border border-zinc-800 p-3 text-[12px] text-zinc-400">
                  {r.auth.mode === 'user' ? 'Queries ran with your own Unity Catalog permissions.' : r.auth.disclosure}
                </p>
              </div>
            )}
            {tab === 'Assumptions' && (
              <div className="space-y-4 text-[13px]">
                <section>
                  <h3 className="mb-1.5 text-[12px] font-semibold uppercase tracking-wide text-zinc-400">Assumptions</h3>
                  {r.assumptions.length ? <ul className="list-disc space-y-1 pl-4 text-zinc-200">{r.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
                    : <p className="text-zinc-400">None stated.</p>}
                </section>
                <section>
                  <h3 className="mb-1.5 text-[12px] font-semibold uppercase tracking-wide text-zinc-400">Possible explanations (not verified)</h3>
                  {r.hypotheses.length ? <ul className="list-disc space-y-1 pl-4 text-zinc-300">{r.hypotheses.map((h) => <li key={h}>{h}</li>)}</ul>
                    : <p className="text-zinc-400">None.</p>}
                </section>
                {Object.keys(r.state.resolved_definitions).length > 0 && (
                  <section>
                    <h3 className="mb-1.5 text-[12px] font-semibold uppercase tracking-wide text-zinc-400">Your clarifications</h3>
                    <dl className="space-y-1">{Object.entries(r.state.resolved_definitions).map(([q, a]) => (
                      <div key={q}><dt className="text-zinc-400">{q}</dt><dd className="text-zinc-200">{a}</dd></div>
                    ))}</dl>
                  </section>
                )}
              </div>
            )}
            {tab === 'Verification' && <VerificationTab v={r.verification} />}
          </div>
        </>
      )}
    </aside>
  )
}
