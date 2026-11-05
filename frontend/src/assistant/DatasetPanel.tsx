import { ChevronDown, Database, FileSpreadsheet, LoaderCircle, MessageSquare, SquarePen, Trash2, Upload } from 'lucide-react'
import { useRef, useState, type DragEvent } from 'react'
import { cn } from '../lib/cn'
import { deleteUpload, uploadFile } from './api'
import { relativeTime } from './format'
import type { Conversation, Dataset, UploadResult } from './types'

type UploadState =
  | { phase: 'idle' }
  | { phase: 'uploading'; name: string }
  | { phase: 'sheet'; file: File; result: UploadResult }
  | { phase: 'done'; result: UploadResult }
  | { phase: 'error'; message: string }

const ACCEPT = '.csv,.tsv,.xlsx'

export function DatasetPanel({ datasets, selected, onSelect, onDatasetsChanged, conversations, activeId, onOpen, onNew, onDelete, conversationId }: {
  datasets: Dataset[]; selected: string[]; onSelect: (names: string[]) => void; onDatasetsChanged: (select?: string) => void
  conversations: Conversation[]; activeId: string | null; onOpen: (id: string) => void; onNew: () => void; onDelete: (id: string) => void
  conversationId: string
}) {
  const [upload, setUpload] = useState<UploadState>({ phase: 'idle' })
  const [dragging, setDragging] = useState(false)
  const [inspect, setInspect] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)

  const send = async (file: File, sheet?: string) => {
    setUpload({ phase: 'uploading', name: file.name })
    try {
      const result = await uploadFile(file, conversationId, sheet)
      if (result.status === 'NEEDS_SHEET') {
        setUpload({ phase: 'sheet', file, result })
        return
      }
      setUpload({ phase: 'done', result })
      onDatasetsChanged(result.dataset ?? undefined)
    } catch (err) {
      setUpload({ phase: 'error', message: (err as Error).message })
    }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) send(file)
  }

  const toggle = (name: string) => {
    const next = selected.includes(name) ? selected.filter((d) => d !== name) : [...selected, name]
    if (next.length) onSelect(next)
  }

  const remove = async (name: string) => {
    if (!window.confirm('Delete this upload and its table? This can\'t be undone.')) return
    try {
      await deleteUpload(name)
      if (selected.includes(name)) onSelect(selected.filter((d) => d !== name).length ? selected.filter((d) => d !== name) : [datasets[0]?.dataset].filter(Boolean) as string[])
      onDatasetsChanged()
    } catch (err) {
      setUpload({ phase: 'error', message: (err as Error).message })
    }
  }

  const shortName = (d: Dataset) => (d.kind === 'upload' ? d.description.replace(/^Uploaded /, '') : d.dataset.split('.').at(-1) ?? d.dataset)

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-3">
      <section aria-labelledby="ds-heading">
        <h2 id="ds-heading" className="mb-2 px-1 text-[11.5px] font-semibold uppercase tracking-wide text-zinc-400">Datasets</h2>
        <ul className="space-y-1">
          {datasets.map((d) => {
            const on = selected.includes(d.dataset)
            const p = d.profile
            return (
              <li key={d.dataset} className={cn('rounded-lg border', on ? 'border-sky-400/40 bg-sky-400/5' : 'border-zinc-800')}>
                <div className="flex items-start gap-2 p-2">
                  <input id={`ds-${d.dataset}`} type="checkbox" checked={on} onChange={() => toggle(d.dataset)}
                    className="mt-0.5 h-4 w-4 accent-sky-400" aria-describedby={`ds-meta-${d.dataset}`} />
                  <label htmlFor={`ds-${d.dataset}`} className="min-w-0 flex-1 cursor-pointer">
                    <span className="flex items-center gap-1.5 text-[13px] text-zinc-100">
                      {d.kind === 'upload' ? <FileSpreadsheet className="h-3.5 w-3.5 shrink-0 text-zinc-400" /> : <Database className="h-3.5 w-3.5 shrink-0 text-zinc-400" />}
                      <span className="truncate">{shortName(d)}</span>
                    </span>
                    <span id={`ds-meta-${d.dataset}`} className="mt-0.5 block text-[11.5px] text-zinc-400">
                      {p ? `${p.row_count.toLocaleString()} rows` : 'not profiled yet'}
                      {d.kind === 'upload' ? ` · deleted ${relativeTime(d.expires_at)}` : ` · updated ${relativeTime(d.refreshed_at)}`}
                    </span>
                  </label>
                  {d.kind === 'upload' && (
                    <button type="button" onClick={() => remove(d.dataset)} aria-label={`Delete ${shortName(d)}`} className="rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-rose-300">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
                <button type="button" onClick={() => setInspect(inspect === d.dataset ? null : d.dataset)} aria-expanded={inspect === d.dataset}
                  className="flex w-full items-center gap-1 border-t border-zinc-800/80 px-2 py-1 text-[11.5px] text-zinc-400 hover:text-zinc-200">
                  <ChevronDown className={cn('h-3 w-3 transition', inspect === d.dataset && 'rotate-180')} /> Schema and profile
                </button>
                {inspect === d.dataset && <Inspector dataset={d} />}
              </li>
            )
          })}
        </ul>
      </section>

      <section aria-labelledby="up-heading">
        <h2 id="up-heading" className="mb-2 px-1 text-[11.5px] font-semibold uppercase tracking-wide text-zinc-400">Add data</h2>
        <div onDragOver={(e) => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={onDrop}
          className={cn('rounded-lg border border-dashed p-3 text-center transition', dragging ? 'border-sky-400 bg-sky-400/10' : 'border-zinc-700')}>
          <Upload className="mx-auto h-5 w-5 text-zinc-400" aria-hidden />
          <p className="mt-1 text-[12.5px] text-zinc-300">Drop a CSV or Excel file</p>
          <button type="button" onClick={() => input.current?.click()} className="mt-2 rounded-md border border-zinc-700 px-2.5 py-1 text-[12px] text-zinc-100 hover:bg-zinc-800">
            Choose file
          </button>
          <input ref={input} type="file" accept={ACCEPT} className="sr-only" aria-label="Upload a CSV or Excel file"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) send(f); e.target.value = '' }} />
          <p className="mt-2 text-[11px] text-zinc-500">CSV, TSV or XLSX · up to 25 MB · private to you · deleted after 24 h</p>
        </div>
        <div aria-live="polite">
          {upload.phase === 'uploading' && (
            <p className="mt-2 flex items-center gap-2 text-[12.5px] text-zinc-300"><LoaderCircle className="h-3.5 w-3.5 animate-spin" /> Uploading and profiling {upload.name}…</p>
          )}
          {upload.phase === 'sheet' && (
            <fieldset className="mt-2 rounded-lg border border-zinc-800 p-2">
              <legend className="px-1 text-[12px] text-zinc-300">Which sheet in {upload.result.file_name}?</legend>
              {upload.result.sheets.map((s) => (
                <button key={s.name} type="button" onClick={() => send(upload.file, s.name)}
                  className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-[12.5px] text-zinc-100 hover:bg-zinc-800">
                  <span>{s.name}</span><span className="text-zinc-400">{s.rows.toLocaleString()} rows · {s.columns} cols</span>
                </button>
              ))}
            </fieldset>
          )}
          {upload.phase === 'done' && <UploadSummary result={upload.result} onDismiss={() => setUpload({ phase: 'idle' })} />}
          {upload.phase === 'error' && (
            <div role="alert" className="mt-2 rounded-lg border border-rose-400/30 bg-rose-400/10 p-2 text-[12.5px] text-rose-100">
              {upload.message}
              <button type="button" onClick={() => setUpload({ phase: 'idle' })} className="ml-2 underline">Dismiss</button>
            </div>
          )}
        </div>
      </section>

      <section aria-labelledby="conv-heading" className="min-h-0">
        <div className="mb-2 flex items-center justify-between px-1">
          <h2 id="conv-heading" className="text-[11.5px] font-semibold uppercase tracking-wide text-zinc-400">Conversations</h2>
          <button type="button" onClick={onNew} className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[12px] text-zinc-200 hover:bg-zinc-800">
            <SquarePen className="h-3.5 w-3.5" /> New
          </button>
        </div>
        {conversations.length === 0 ? <p className="px-1 text-[12.5px] text-zinc-400">Your conversations appear here.</p> : (
          <ul className="space-y-0.5">
            {conversations.map((c) => (
              <li key={c.id} className="group flex items-center">
                <button type="button" onClick={() => onOpen(c.id)} aria-current={c.id === activeId ? 'true' : undefined}
                  className={cn('flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left text-[12.5px]', c.id === activeId ? 'bg-zinc-800 text-white' : 'text-zinc-300 hover:bg-zinc-900')}>
                  <MessageSquare className="h-3.5 w-3.5 shrink-0 text-zinc-500" /><span className="truncate">{c.title}</span>
                </button>
                <button type="button" onClick={() => onDelete(c.id)} aria-label={`Delete conversation ${c.title}`}
                  className="rounded p-1 text-zinc-500 opacity-0 hover:text-rose-300 focus:opacity-100 group-hover:opacity-100">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

function Inspector({ dataset }: { dataset: Dataset }) {
  const p = dataset.profile
  if (!p) return <p className="px-2 pb-2 text-[12px] text-zinc-400">Profile not available yet.</p>
  const dups = Object.entries(p.duplicates).filter(([, n]) => n > 0)
  return (
    <div className="space-y-2 px-2 pb-2 text-[11.5px]">
      {dataset.grain && <p className="text-zinc-400">Grain: {dataset.grain}</p>}
      {p.date_range && <p className="text-zinc-400">Dates: {p.date_range[0]} → {p.date_range[1]}</p>}
      {dups.map(([k, n]) => <p key={k} className="text-amber-200">{n.toLocaleString()} duplicate ({k}) rows</p>)}
      <ul className="max-h-64 space-y-1 overflow-y-auto">
        {p.columns.map((c) => (
          <li key={c.name} title={dataset.column_descriptions[c.name] || dataset.original_names[c.name] || undefined}>
            <div className="flex justify-between gap-2">
              <span className="truncate font-mono text-zinc-200">{c.name}</span>
              <span className="shrink-0 font-mono text-zinc-500">{c.type}{c.nulls ? ` · ${(c.null_rate * 100).toFixed(1)}% null` : ''}</span>
            </div>
            {c.anomalies.map((a) => <div key={a} className="text-amber-200/90">{a}</div>)}
          </li>
        ))}
      </ul>
      {[...p.warnings, ...dataset.warnings].length > 0 && (
        <ul className="list-disc space-y-0.5 pl-4 text-amber-200/90">{[...new Set([...p.warnings, ...dataset.warnings])].map((w) => <li key={w}>{w}</li>)}</ul>
      )}
    </div>
  )
}

function UploadSummary({ result, onDismiss }: { result: UploadResult; onDismiss: () => void }) {
  const notes = result.columns.flatMap((c) => c.notes.map((n) => `${c.name}: ${n}`))
  return (
    <div className="mt-2 rounded-lg border border-emerald-400/30 bg-emerald-400/5 p-2 text-[12px]">
      <p className="text-emerald-100">{result.file_name}{result.sheet ? ` (${result.sheet})` : ''}: {result.row_count.toLocaleString()} rows, {result.columns.length} columns loaded and selected.</p>
      {result.rejected_row_count > 0 && <p className="mt-1 text-amber-200">{result.rejected_row_count} malformed rows not loaded (lines {result.rejected_rows.slice(0, 8).join(', ')}).</p>}
      {notes.length > 0 && <ul className="mt-1 list-disc space-y-0.5 pl-4 text-zinc-300">{notes.slice(0, 6).map((n) => <li key={n}>{n}</li>)}</ul>}
      <button type="button" onClick={onDismiss} className="mt-1 text-zinc-400 underline">Dismiss</button>
    </div>
  )
}
