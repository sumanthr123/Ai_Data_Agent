import { Download, FileCode2, Pin, PinOff, RotateCcw, X } from 'lucide-react'
import { lazy, Suspense, useEffect, useState } from 'react'
import { CodeBlock } from '../components/CodeBlock'
import { cn } from '../lib/cn'
import { downloadResult } from './api'
import { chartPlan } from './chartPlan'
import { layoutSql, relativeTime } from './format'
import { ResultTable } from './ResultTable'
import type { Turn } from './types'

const ResultChart = lazy(() => import('./ResultChart').then((m) => ({ default: m.ResultChart })))

type View = 'chart' | 'table' | 'sql'

/** Large results, charts and SQL beside the conversation. Versions are this conversation's data answers, newest last. */
export function CanvasPanel({ versions, activeId, onPick, onClose, theme, pinned, onPin, onRerun }: {
  versions: Turn[]; activeId: string; onPick: (id: string) => void; onClose: () => void; theme: string
  pinned: boolean; onPin: (t: Turn) => void; onRerun: (t: Turn) => void
}) {
  const turn = versions.find((t) => t.id === activeId) ?? versions.at(-1)
  const r = turn?.response
  const plan = r?.result && r.status === 'ANSWERED' ? chartPlan(r.result) : null
  const [view, setView] = useState<View>(plan ? 'chart' : 'table')
  const [note, setNote] = useState<string | null>(null)
  useEffect(() => { setView(plan ? 'chart' : r?.result ? 'table' : 'sql'); setNote(null) }, [turn?.id])  // eslint-disable-line react-hooks/exhaustive-deps
  if (!turn || !r) return null
  const n = versions.findIndex((t) => t.id === turn.id) + 1
  const asOf = r.sources.find((s) => s.kind === 'shared')?.updated_at ?? null
  const save = (format: 'csv' | 'xlsx') => r.sql && downloadResult(r.sql, turn.datasets, format)
    .then(() => setNote(`${format.toUpperCase()} downloaded`), (err: Error) => setNote(`Download failed: ${err.message}`))
  const saveSql = () => {
    if (!r.sql) return
    const url = URL.createObjectURL(new Blob([layoutSql(r.sql) + '\n'], { type: 'text/plain' }))
    Object.assign(document.createElement('a'), { href: url, download: 'query.sql' }).click()
    URL.revokeObjectURL(url)
    setNote('SQL downloaded')
  }
  const tabs: View[] = [...(plan ? ['chart' as const] : []), ...(r.result ? ['table' as const] : []), ...(r.sql ? ['sql' as const] : [])]
  const btn = 'inline-flex min-h-8 items-center gap-1.5 rounded-lg px-2.5 text-[13px] text-fg-2 hover:bg-surface-2 hover:text-fg'
  return (
    <section aria-label="Canvas" className="flex h-full min-w-0 flex-col bg-surface"
      onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }}>
      <header className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2.5">
        <div className="min-w-0 flex-1">
          <h2 className="truncate font-display text-[17px] text-fg">{turn.question}</h2>
          <p className="text-[12px] text-fg-3">{view === 'sql' ? 'SQL' : view === 'chart' ? 'Chart' : 'Table'} · {r.result ? `${r.result.row_count.toLocaleString()} rows` : 'no rows'}{asOf ? ` · data as of ${relativeTime(asOf)}` : ''}</p>
        </div>
        {versions.length > 1 && (
          <label className="text-[12.5px] text-fg-2">
            <span className="sr-only">Version</span>
            <select value={turn.id} onChange={(e) => onPick(e.target.value)} className="min-h-8 max-w-[14rem] rounded-lg border border-line-strong bg-surface px-2 text-[12.5px] text-fg">
              {versions.map((v, i) => <option key={v.id} value={v.id}>v{i + 1} · {v.question.slice(0, 40)}</option>)}
            </select>
          </label>
        )}
        {versions.length === 1 && <span className="text-[12.5px] text-fg-3">v{n}</span>}
        <button type="button" onClick={onClose} aria-label="Close canvas" title="Close (Esc)" className="rounded-lg p-1.5 text-fg-2 hover:bg-surface-2 hover:text-fg"><X className="h-4 w-4" /></button>
      </header>

      <div className="flex flex-wrap items-center gap-1 border-b border-line px-3 py-1.5">
        <div role="tablist" aria-label="View" className="mr-2 inline-flex rounded-lg bg-surface-2 p-0.5">
          {tabs.map((v) => (
            <button key={v} type="button" role="tab" aria-selected={view === v} onClick={() => setView(v)}
              className={cn('min-h-7 rounded-md px-3 text-[13px] capitalize', view === v ? 'bg-surface font-medium text-fg shadow-sm' : 'text-fg-2 hover:text-fg')}>{v === 'sql' ? 'SQL' : v}</button>
          ))}
        </div>
        {r.sql && <><button type="button" onClick={() => save('csv')} className={btn}><Download className="h-3.5 w-3.5" aria-hidden /> CSV</button>
          <button type="button" onClick={() => save('xlsx')} className={btn}><Download className="h-3.5 w-3.5" aria-hidden /> XLSX</button>
          <button type="button" onClick={saveSql} className={btn}><FileCode2 className="h-3.5 w-3.5" aria-hidden /> .sql</button></>}
        <button type="button" onClick={() => onPin(turn)} className={btn}>{pinned ? <PinOff className="h-3.5 w-3.5" aria-hidden /> : <Pin className="h-3.5 w-3.5" aria-hidden />} {pinned ? 'Unsave' : 'Save'}</button>
        <button type="button" onClick={() => onRerun(turn)} className={btn}><RotateCcw className="h-3.5 w-3.5" aria-hidden /> Re-run</button>
        {note && <span role="status" className="ml-1 text-[12px] text-fg-3">{note}</span>}
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-4" role="tabpanel">
        {view === 'chart' && plan && r.result && (
          <Suspense fallback={<div className="skeleton h-[420px] rounded-lg" />}>
            <ResultChart result={r.result} plan={plan} theme={theme} onError={setNote} height="h-[420px]" />
          </Suspense>
        )}
        {view === 'table' && r.result && <ResultTable result={r.result} tall />}
        {view === 'sql' && r.sql && <CodeBlock code={layoutSql(r.sql)} lang="sql" />}
        {r.result?.truncated && <p className="mt-2 text-[12.5px] text-warn">This preview is truncated at the row limit; CSV and XLSX run the full query.</p>}
      </div>
    </section>
  )
}
