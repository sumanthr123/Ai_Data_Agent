import { AlertTriangle, ArrowUp, CircleCheck, FileSearch, Globe, Menu, PanelRight, RotateCcw, ShieldAlert, Square, X } from 'lucide-react'
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { Markdown } from '../components/Markdown'
import { SourceList } from '../components/SourceList'
import { cn } from '../lib/cn'
import { listDatasets } from './api'
import { DatasetPanel } from './DatasetPanel'
import { EvidenceDrawer } from './EvidenceDrawer'
import { humanize, isMeasure, isTimeLike } from './format'
import { ResultTable } from './ResultTable'
import { StatusSteps } from './StatusSteps'
import { CodeAnswer, CouncilView, DocSources, KindBadge } from './AnswerParts'
import type { AskResponse, Dataset, Turn } from './types'

const ResultChart = lazy(() => import('./ResultChart').then((m) => ({ default: m.ResultChart })))  // recharts loads with the first chart
import { useAssistant } from './useAssistant'

/** Starter questions derived from the selected datasets' real columns and profiles, never hard-coded. */
function starters(datasets: Dataset[]): string[] {
  const out: string[] = []
  for (const d of datasets) {
    const cols = d.profile?.columns ?? []
    const measures = cols.filter((c) => isMeasure(c.name, c.type) && !isTimeLike(c.name, c.type)).map((c) => c.name)
    const dims = cols.filter((c) => /string/i.test(c.type) && (c.distinct_approx ?? 0) >= 2 && (c.distinct_approx ?? 0) <= 25).map((c) => c.name)
    const names = cols.filter((c) => /string/i.test(c.type) && /name/i.test(c.name) && (c.distinct_approx ?? 0) > 25).map((c) => c.name)
    const m = measures.find((x) => /sales|revenue|amount|total/i.test(x)) ?? measures[0]
    const year = d.profile?.date_range?.[1]?.slice(0, 4)
    const label = d.kind === 'upload' ? d.description.replace(/^Uploaded /, '') : humanize(d.dataset.split('.').at(-1) ?? '')
    if (m && dims[0]) out.push(`What is total ${humanize(m)} by ${humanize(dims[0])}?`)
    if (m && d.date_column && year) out.push(`How did total ${humanize(m)} change by month in ${year}?`)
    if (m && names[0]) out.push(`Who are the top 5 ${humanize(names[0]).replace(/ name$/, '')}s by ${humanize(m)}?`)
    const second = measures.find((x) => x !== m)
    if (second && dims[1]) out.push(`Which ${humanize(dims[1])} has the highest ${humanize(second)}?`)
    if (!m) out.push(`Summarize ${label}: rows, columns and data quality`)
  }
  return [...new Set(out)].slice(0, 4)
}

function Verdict({ r }: { r: AskResponse }) {
  const v = r.verification
  if (r.status === 'ANSWERED' && r.web_sources?.length) return <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-sky-300"><Globe className="h-4 w-4" /> Live web search · {r.web_sources.length} source{r.web_sources.length === 1 ? '' : 's'}</span>
  if (r.status === 'ANSWERED' && r.kind === 'docs') return <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-emerald-300"><CircleCheck className="h-4 w-4" /> Checked against the cited docs</span>
  if (r.status === 'ANSWERED' && r.kind === 'code') return <span className="text-[12px] font-medium text-zinc-300">Static checks only; not executed</span>
  if (r.status === 'ANSWERED' && r.kind === 'chat') return null
  if (r.status === 'ANSWERED' && v.reviewed) return <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-emerald-300"><CircleCheck className="h-4 w-4" /> Independently reviewed</span>
  if (r.status === 'ANSWERED') return <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-amber-300"><ShieldAlert className="h-4 w-4" /> Not independently reviewed</span>
  if (r.status === 'NEEDS_CLARIFICATION') return <span className="text-[12px] font-medium text-sky-300">Needs one detail</span>
  if (r.status === 'INSUFFICIENT_SCHEMA') return <span className="text-[12px] font-medium text-zinc-300">Not in this data</span>
  if (r.status === 'ERROR') return <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-rose-300"><AlertTriangle className="h-4 w-4" /> Couldn't answer</span>
  return <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-amber-300"><AlertTriangle className="h-4 w-4" /> {r.status === 'UNRESOLVED' ? 'Unverified' : 'Stopped at budget'}</span>
}

function TurnView({ turn, live, onEvidence, onRetry, onCouncil }: { turn: Turn; live: boolean; onEvidence: () => void; onRetry: () => void; onCouncil: () => void }) {
  const r = turn.response
  return (
    <article className="space-y-3">
      <div className="flex justify-end">
        <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-zinc-800 px-4 py-2.5 text-[14.5px] text-zinc-50">{turn.question}</p>
      </div>
      <div className="space-y-3 rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
        <StatusSteps stages={turn.stages} live={live} />
        {turn.cancelled && <p className="text-[13px] text-zinc-400">Stopped. Nothing further ran on the warehouse.</p>}
        {turn.error && (
          <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg border border-rose-400/30 bg-rose-400/10 p-3 text-[13px] text-rose-100">
            <span className="flex-1">{turn.error}</span>
            <button type="button" onClick={onRetry} className="inline-flex items-center gap-1.5 rounded-md border border-rose-300/40 px-2.5 py-1 hover:bg-rose-400/10"><RotateCcw className="h-3.5 w-3.5" /> Retry</button>
          </div>
        )}
        {r && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-zinc-800 pt-3">
              <span className="flex flex-wrap items-center gap-2"><KindBadge kind={r.kind ?? 'data'} /><Verdict r={r} /></span>
              <div className="flex items-center gap-2">
                {(r.status === 'ERROR' || r.status === 'BUDGET_EXHAUSTED') && (
                  <button type="button" onClick={onRetry} className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[12px] text-zinc-300 hover:bg-zinc-800"><RotateCcw className="h-3.5 w-3.5" /> Retry</button>
                )}
                {(r.kind ?? 'data') === 'data' && r.sql && !r.council && !live && (
                  <button type="button" onClick={onCouncil} className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[12px] text-zinc-300 hover:bg-zinc-800">Verify with council</button>
                )}
                <button type="button" onClick={onEvidence} className="inline-flex items-center gap-1.5 rounded-md border border-zinc-700 px-2.5 py-1 text-[12px] text-zinc-100 hover:bg-zinc-800">
                  <FileSearch className="h-3.5 w-3.5" /> Evidence
                </button>
              </div>
            </div>
            {r.status === 'NEEDS_CLARIFICATION' && r.clarifying_question ? (
              <div className="space-y-2">
                <p className="text-[14.5px] text-zinc-100">{r.clarifying_question}</p>
                <p className="text-[12.5px] text-zinc-400">Reply in the box below; your answer is applied to this question.</p>
              </div>
            ) : r.answer && <Markdown text={r.answer} sources={r.web_sources} />}
            {!!r.web_sources?.length && <SourceList sources={r.web_sources} />}
            {r.code && <CodeAnswer code={r.code} />}
            {!!r.doc_sources?.length && <DocSources sources={r.doc_sources} />}
            {r.council && <CouncilView council={r.council} />}
            {r.answer_truncated && <p className="text-[12px] text-zinc-400">Shortened to the answer length limit; ask for a full breakdown to see more.</p>}
            {r.hypotheses.length > 0 && (
              <details className="rounded-lg border border-zinc-800 p-3 text-[13px]">
                <summary className="cursor-pointer text-zinc-300">Possible explanations (hypotheses, not verified by the data)</summary>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-zinc-300">{r.hypotheses.map((h) => <li key={h}>{h}</li>)}</ul>
              </details>
            )}
            {r.result && r.result.row_count > 0 && r.status === 'ANSWERED' && <Suspense fallback={null}><ResultChart result={r.result} /></Suspense>}
            {r.result && r.result.row_count > 0 && <ResultTable result={r.result} />}
            {r.result && r.result.row_count === 0 && <p className="text-[13px] text-zinc-400">The query returned no rows.</p>}
          </>
        )}
      </div>
    </article>
  )
}

export default function AssistantApp() {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const defaults = useMemo(() => datasets.filter((d) => d.kind === 'shared').slice(0, 1).map((d) => d.dataset), [datasets])
  const a = useAssistant(defaults)
  const [draft, setDraft] = useState('')
  const [navOpen, setNavOpen] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [evidenceId, setEvidenceId] = useState<string | null>(null)
  const feed = useRef<HTMLDivElement>(null)
  const box = useRef<HTMLTextAreaElement>(null)

  const refresh = useCallback(async (select?: string) => {
    try {
      const list = await listDatasets()
      setDatasets(list)
      setLoadError(null)
      if (select) a.setDatasets([...new Set([...(a.active?.datasets ?? defaults), select])])
    } catch (err) {
      setLoadError((err as Error).message)
    }
  }, [a, defaults])

  useEffect(() => { refresh() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') {
        setNavOpen(false)
        if (window.innerWidth < 1280) setDrawerOpen(false)  // on wide screens the drawer is a pane, not an overlay
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const visible = new Set(datasets.map((d) => d.dataset))
  const selected = (a.active?.datasets ?? defaults).filter((d) => visible.has(d))
  const turns = a.active?.turns ?? []
  const evidenceTurn = turns.find((t) => t.id === evidenceId) ?? [...turns].reverse().find((t) => t.response) ?? null

  useEffect(() => { feed.current?.scrollTo({ top: feed.current.scrollHeight, behavior: 'smooth' }) }, [turns.length, turns.at(-1)?.stages.length, turns.at(-1)?.response])

  const submit = (text = draft) => {
    if (!text.trim() || a.busy) return
    if (!selected.length && defaults.length) a.setDatasets(defaults)
    a.ask(text)
    setDraft('')
  }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    }
  }
  const pending = a.active?.state?.pending_clarification
  const label = (name: string) => {
    const d = datasets.find((x) => x.dataset === name)
    return d?.kind === 'upload' ? d.description.replace(/^Uploaded /, '') : name.split('.').at(-1)
  }
  useEffect(() => { if (pending) box.current?.focus() }, [pending])
  const examples = starters(datasets.filter((d) => selected.includes(d.dataset)))

  const panel = (
    <DatasetPanel datasets={datasets} selected={selected} onSelect={a.setDatasets} onDatasetsChanged={refresh}
      conversations={a.conversations} activeId={a.activeId} onOpen={(id) => { a.setActiveId(id); setNavOpen(false) }}
      onNew={() => { a.start(selected.length ? selected : defaults); setNavOpen(false) }} onDelete={a.remove}
      conversationId={a.activeId ?? 'unsorted'} />
  )

  return (
    <div className="flex h-full flex-col bg-zinc-950 text-zinc-100">
      <header className="flex items-center gap-2 border-b border-zinc-800 px-3 py-2.5">
        <button type="button" className="rounded-lg p-1.5 text-zinc-300 hover:bg-zinc-800 lg:hidden" onClick={() => setNavOpen(true)} aria-label="Open datasets and conversations">
          <Menu className="h-5 w-5" />
        </button>
        <h1 className="text-[15px] font-semibold tracking-tight">AI Data Assistant</h1>
        <span className="hidden text-[12.5px] text-zinc-400 sm:inline">Answers from your Unity Catalog data, checked by an independent model</span>
        <div className="ml-auto flex items-center gap-1">
          <a href="/council" className="rounded-lg px-2.5 py-1.5 text-[12.5px] text-zinc-300 hover:bg-zinc-800">Classic chat</a>
          <button type="button" onClick={() => setDrawerOpen((o) => !o)} aria-pressed={drawerOpen} aria-label="Toggle evidence panel"
            className="rounded-lg p-1.5 text-zinc-300 hover:bg-zinc-800"><PanelRight className="h-5 w-5" /></button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-72 shrink-0 border-r border-zinc-800 lg:block" aria-label="Datasets and conversations">{panel}</aside>
        {navOpen && (
          <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Datasets and conversations">
            <div className="absolute inset-0 bg-black/60" onClick={() => setNavOpen(false)} />
            <div className="absolute inset-y-0 left-0 w-[85%] max-w-sm border-r border-zinc-800 bg-zinc-950">
              <button type="button" onClick={() => setNavOpen(false)} aria-label="Close" className="absolute right-2 top-2 z-10 rounded-lg p-1.5 text-zinc-300 hover:bg-zinc-800"><X className="h-4 w-4" /></button>
              {panel}
            </div>
          </div>
        )}

        <main className="flex min-w-0 flex-1 flex-col">
          <div ref={feed} className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto max-w-3xl space-y-8 px-4 py-6">
              {loadError && <p role="alert" className="rounded-lg border border-rose-400/30 bg-rose-400/10 p-3 text-[13px] text-rose-100">Couldn't load datasets: {loadError} <button type="button" className="underline" onClick={() => refresh()}>Retry</button></p>}
              {turns.length === 0 && (
                <section className="pt-8 text-center">
                  <h2 className="text-[22px] font-semibold tracking-tight">What do you want to know?</h2>
                  <p className="mx-auto mt-2 max-w-md text-[13.5px] text-zinc-400">
                    Every number comes from a query you can inspect. Add your own CSV or Excel file on the left to combine it with shared data.
                  </p>
                  {examples.length > 0 && (
                    <div className="mx-auto mt-6 grid max-w-2xl gap-2 sm:grid-cols-2">
                      {examples.map((q) => (
                        <button key={q} type="button" onClick={() => submit(q)} className="rounded-xl border border-zinc-800 px-3.5 py-3 text-left text-[13.5px] text-zinc-200 hover:border-zinc-600 hover:bg-zinc-900">
                          {q}
                        </button>
                      ))}
                    </div>
                  )}
                  {!examples.length && !loadError && <p className="mt-6 text-[12.5px] text-zinc-500">Loading datasets…</p>}
                </section>
              )}
              {turns.map((t, i) => (
                <TurnView key={t.id} turn={t} live={a.busy && i === turns.length - 1}
                  onEvidence={() => { setEvidenceId(t.id); setDrawerOpen(true) }}
                  onRetry={() => submit(t.question)} onCouncil={() => a.ask(t.question, true)} />
              ))}
            </div>
          </div>
          <div className="border-t border-zinc-800 p-3">
            <div className="mx-auto max-w-3xl">
              {pending && <p className="mb-1.5 text-[12.5px] text-sky-300">Answering: {pending}</p>}
              <div className="flex items-end gap-2 rounded-2xl border border-zinc-700 bg-zinc-900 p-2 focus-within:border-zinc-500">
                <label htmlFor="ask" className="sr-only">Ask a question about your data</label>
                <textarea id="ask" ref={box} rows={1} value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} maxLength={4000}
                  placeholder={pending ? 'Your answer…' : selected.length ? 'Ask about your data…' : 'Select a dataset to start'}
                  className="max-h-40 min-h-[40px] flex-1 resize-none bg-transparent px-2 py-2 text-[14.5px] text-zinc-100 placeholder:text-zinc-500 focus:outline-none" />
                {a.busy ? (
                  <button type="button" onClick={a.cancel} aria-label="Stop" className="rounded-xl bg-zinc-200 p-2.5 text-zinc-900 hover:bg-white"><Square className="h-4 w-4" /></button>
                ) : (
                  <button type="button" onClick={() => submit()} disabled={!draft.trim()} aria-label="Send" className="rounded-xl bg-sky-400 p-2.5 text-zinc-950 hover:bg-sky-300 disabled:bg-zinc-700 disabled:text-zinc-400"><ArrowUp className="h-4 w-4" /></button>
                )}
              </div>
              <p className="mt-1.5 text-center text-[11px] text-zinc-500">
                {selected.length ? `Using ${selected.map(label).join(', ')}` : 'No dataset selected'} · Enter to send, Shift+Enter for a new line
              </p>
            </div>
          </div>
        </main>

        <div className={cn('hidden w-[400px] shrink-0 border-l border-zinc-800', drawerOpen && 'xl:block')}>
          <EvidenceDrawer turn={evidenceTurn} onClose={() => setDrawerOpen(false)} />
        </div>
        {drawerOpen && (
          <div className="fixed inset-0 z-40 xl:hidden" role="dialog" aria-modal="true" aria-label="Evidence">
            <div className="absolute inset-0 bg-black/60" onClick={() => setDrawerOpen(false)} />
            <div className="absolute inset-y-0 right-0 w-full max-w-md border-l border-zinc-800">
              <EvidenceDrawer turn={evidenceTurn} onClose={() => setDrawerOpen(false)} />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
