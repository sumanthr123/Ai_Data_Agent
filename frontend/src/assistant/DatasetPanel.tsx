import { ChevronDown, Database, FileSpreadsheet, MessageSquare, Pencil, RotateCcw, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { cn } from '../lib/cn'
import { deleteUpload } from './api'
import { relativeTime } from './format'
import type { Conversation, Dataset, Pin } from './types'


/** Today, the last 7 days, and older, by last update. */
function groupByAge(list: Conversation[]): [string, Conversation[]][] {
  const start = new Date().setHours(0, 0, 0, 0)
  const week = start - 6 * 86400000
  return [['Today', list.filter((c) => c.updatedAt >= start)], ['Previous 7 days', list.filter((c) => c.updatedAt < start && c.updatedAt >= week)],
    ['Older', list.filter((c) => c.updatedAt < week)]]
}

export function DatasetPanel({ datasets, selected, onSelect, onDatasetsChanged, conversations, activeId, onOpen, onDelete, onRename, pins, onRunPin, onRemovePin }: {
  datasets: Dataset[]; selected: string[]; onSelect: (names: string[]) => void; onDatasetsChanged: (select?: string) => void
  conversations: Conversation[]; activeId: string | null; onOpen: (id: string) => void; onDelete: (id: string) => void
  onRename: (id: string, title: string) => void
  pins: Pin[]; onRunPin: (pin: Pin) => void; onRemovePin: (id: string) => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [inspect, setInspect] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const [title2, setTitle2] = useState('')
  const [confirming, setConfirming] = useState<string | null>(null)
  const groups = groupByAge(conversations.filter((c) => c.title.toLowerCase().includes(query.trim().toLowerCase())))

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
      setError((err as Error).message)
    }
  }

  const shortName = (d: Dataset) => (d.kind === 'upload' ? d.description.replace(/^Uploaded /, '') : d.dataset.split('.').at(-1) ?? d.dataset)

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-3">
      <section aria-labelledby="ds-heading">
        <h2 id="ds-heading" className="mb-2 px-1 text-[11.5px] font-semibold uppercase tracking-wide text-zinc-400">Data sources</h2>
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

      {error && (
        <p role="alert" className="rounded-md border border-err/40 bg-err/5 p-2 text-[12.5px] text-err">
          {error} <button type="button" onClick={() => setError(null)} className="ml-1 underline">Dismiss</button>
        </p>
      )}

      {pins.length > 0 && (
        <section aria-labelledby="pin-heading">
          <h2 id="pin-heading" className="mb-2 px-1 text-[12px] font-semibold uppercase tracking-wide text-fg-3">Pinned answers</h2>
          <ul className="space-y-1.5">
            {pins.map((p) => (
              <li key={p.id} className="rounded-md border border-line p-2 text-[12.5px]">
                <p className="font-medium text-fg">{p.question}</p>
                {p.summary && <p className="mt-0.5 line-clamp-2 text-fg-2">{p.summary}</p>}
                <div className="mt-1 flex items-center gap-1 text-fg-3">
                  <span className="flex-1">Pinned {relativeTime(new Date(p.pinnedAt).toISOString())}</span>
                  <button type="button" onClick={() => onRunPin(p)} className="inline-flex min-h-6 items-center gap-1 rounded px-1.5 text-brand hover:bg-surface-2">
                    <RotateCcw className="h-3 w-3" aria-hidden /> Re-run on fresh data
                  </button>
                  <button type="button" onClick={() => onRemovePin(p.id)} aria-label={`Unpin ${p.question}`} className="rounded p-1 hover:bg-surface-2 hover:text-err"><X className="h-3.5 w-3.5" /></button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="conv-heading" className="min-h-0">
        <div className="mb-2 flex items-center justify-between px-1">
          <h2 id="conv-heading" className="text-[12px] font-semibold uppercase tracking-wide text-fg-3">Recents</h2>
        </div>
        {conversations.length === 0 ? (
          <p className="px-1 text-[13px] text-fg-3">No conversations yet. Ask a question to start one.</p>
        ) : (
          <>
            <label htmlFor="conv-search" className="sr-only">Search conversations</label>
            <input id="conv-search" type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search conversations"
              className="mb-2 min-h-8 w-full rounded-md border border-line-strong bg-surface px-2 text-[13px] text-fg placeholder:text-fg-3" />
            {groups.every(([, list]) => list.length === 0) && <p className="px-1 text-[13px] text-fg-3">No conversation matches "{query}".</p>}
            {groups.filter(([, list]) => list.length).map(([title, list]) => (
              <div key={title} className="mb-2">
                <h3 className="px-1 pb-1 text-[12px] text-fg-3">{title}</h3>
                <ul className="space-y-0.5">
                  {list.map((c) => (
                    <li key={c.id} className="group flex items-center">
                      {editing === c.id ? (
                        <form className="flex-1" onSubmit={(e) => { e.preventDefault(); onRename(c.id, title2); setEditing(null) }}>
                          <label htmlFor={`rename-${c.id}`} className="sr-only">Rename conversation</label>
                          <input id={`rename-${c.id}`} autoFocus value={title2} onChange={(e) => setTitle2(e.target.value)} onBlur={() => setEditing(null)}
                            onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); setEditing(null) } }}
                            className="min-h-7 w-full rounded-md border border-accent bg-surface px-2 text-[13px] text-fg" />
                        </form>
                      ) : (
                        <button type="button" onClick={() => onOpen(c.id)} aria-current={c.id === activeId ? 'true' : undefined}
                          className={cn('flex min-h-8 min-w-0 flex-1 items-center gap-2 rounded-md px-2 text-left text-[13px]', c.id === activeId ? 'bg-surface-2 font-medium text-fg' : 'text-fg-2 hover:bg-surface-2')}>
                          <MessageSquare className="h-3.5 w-3.5 shrink-0 text-fg-3" aria-hidden /><span className="truncate">{c.title}</span>
                        </button>
                      )}
                      <button type="button" onClick={() => { setEditing(c.id); setTitle2(c.title) }} aria-label={`Rename conversation ${c.title}`}
                        className="rounded p-1.5 text-fg-3 opacity-0 hover:text-fg focus:opacity-100 group-hover:opacity-100">
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button type="button" onClick={() => { if (confirming === c.id) { onDelete(c.id); setConfirming(null) } else setConfirming(c.id) }}
                        aria-label={confirming === c.id ? `Confirm delete of ${c.title}` : `Delete conversation ${c.title}`}
                        className={cn('rounded p-1.5 focus:opacity-100 group-hover:opacity-100', confirming === c.id ? 'text-err opacity-100' : 'text-fg-3 opacity-0 hover:text-err')}>
                        {confirming === c.id ? <span className="text-[12px] font-medium">Delete?</span> : <Trash2 className="h-3.5 w-3.5" />}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </>
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

