import { ArrowUp, Check, ChevronDown, Database, FileSpreadsheet, LoaderCircle, Paperclip, Plus, Square, X } from 'lucide-react'
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from 'react'
import { cn } from '../lib/cn'
import { modelLabel, relativeTime } from './format'
import type { Dataset, ModelOption } from './types'
import { ACCEPT, type UploadState } from './upload'
import { UploadSummary } from './UploadSummary'

export type Mode = 'quick' | 'deep'

/** Closes a popover on Escape or a click outside it; Escape doesn't reach the page (which would stop a running answer). */
function usePopover() {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])
  const onKeyDown = (e: KeyboardEvent) => { if (e.key === 'Escape' && open) { e.stopPropagation(); setOpen(false) } }
  return { open, setOpen, box, onKeyDown }
}

function Chip({ children, onRemove, label }: { children: ReactNode; onRemove?: () => void; label: string }) {
  return (
    <span className="inline-flex min-h-7 items-center gap-1.5 rounded-xl border border-line bg-surface-2 pl-2 pr-1 text-[12.5px] text-fg-2">
      {children}
      {onRemove && <button type="button" onClick={onRemove} aria-label={`Remove ${label}`} className="rounded p-0.5 hover:bg-bubble hover:text-fg"><X className="h-3.5 w-3.5" /></button>}
    </span>
  )
}

export const datasetLabel = (d: Dataset) => (d.kind === 'upload' ? d.description.replace(/^Uploaded /, '') : d.dataset.split('.').at(-1) ?? d.dataset)

export function Composer({ boxRef, draft, setDraft, onSubmit, onKeyDown, busy, onStop, pending, loaded, home, datasets, selected, defaults, onSelect,
  mode, setMode, models, chosen, pickModel, upload, onUpload, onResetUpload }: {
  boxRef: RefObject<HTMLTextAreaElement | null>; draft: string; setDraft: (s: string) => void; onSubmit: () => void
  onKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>) => void; busy: boolean; onStop: () => void; pending: string | null | undefined
  loaded: boolean; home: boolean; datasets: Dataset[]; selected: string[]; defaults: string[]; onSelect: (names: string[]) => void
  mode: Mode; setMode: (m: Mode) => void; models: ModelOption[]; chosen: string | null; pickModel: (id: string) => void
  upload: UploadState; onUpload: (file: File, sheet?: string) => void; onResetUpload: () => void
}) {
  const plus = usePopover()
  const picker = usePopover()
  const [about, setAbout] = useState(false)
  const file = useRef<HTMLInputElement>(null)
  const chosenSets = datasets.filter((d) => selected.includes(d.dataset))
  const extra = chosenSets.filter((d) => !defaults.includes(d.dataset))  // the default needs no chip; the picker shows it
  const toggle = (name: string) => {
    const next = selected.includes(name) ? selected.filter((d) => d !== name) : [...selected, name]
    if (next.length) onSelect(next)
  }
  const pickerLabel = !loaded ? 'Loading…' : chosenSets.length ? `${datasetLabel(chosenSets[0])}${chosenSets.length > 1 ? ` +${chosenSets.length - 1}` : ''}` : 'No source'
  const hasChips = extra.length > 0 || mode === 'deep' || upload.phase !== 'idle'
  const canSend = !!draft.trim()

  return (
    <div>
      <div className={cn('rounded-[20px] border border-line bg-surface px-3.5 pb-2.5 pt-3 transition-colors focus-within:border-line-strong', home && 'shadow-[0_1px_2px_rgba(46,38,30,0.04)]')}>
        {pending && <p className="mb-1.5 px-1 text-[13px] text-brand">Answering: {pending}</p>}
        {hasChips && (
          <div className="mb-2 flex flex-wrap items-center gap-1.5" aria-label="Active context">
            {extra.map((d) => (
              <Chip key={d.dataset} label={datasetLabel(d)} onRemove={() => toggle(d.dataset)}>
                {d.kind === 'upload' ? <FileSpreadsheet className="h-3.5 w-3.5" aria-hidden /> : <Database className="h-3.5 w-3.5" aria-hidden />}{datasetLabel(d)}
              </Chip>
            ))}
            {mode === 'deep' && <Chip label="Deep analysis" onRemove={() => setMode('quick')}>Deep analysis · council</Chip>}
            {upload.phase === 'uploading' && <Chip label="upload"><LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden /> Uploading and profiling {upload.name}…</Chip>}
            {upload.phase === 'error' && <span role="alert"><Chip label="upload error" onRemove={onResetUpload}><span className="text-err">{upload.message}</span></Chip></span>}
          </div>
        )}
        {upload.phase === 'sheet' && (
          <fieldset className="mb-2 rounded-xl border border-line p-2">
            <legend className="px-1 text-[12.5px] text-fg-2">Which sheet in {upload.result.file_name}?</legend>
            {upload.result.sheets.map((s) => (
              <button key={s.name} type="button" onClick={() => onUpload(upload.file, s.name)}
                className="flex min-h-8 w-full items-center justify-between rounded-md px-2 text-left text-[13px] text-fg hover:bg-surface-2">
                <span>{s.name}</span><span className="text-fg-3">{s.rows.toLocaleString()} rows · {s.columns} cols</span>
              </button>
            ))}
          </fieldset>
        )}
        {upload.phase === 'done' && <div className="mb-2"><UploadSummary result={upload.result} onDismiss={onResetUpload} /></div>}

        <label htmlFor="ask" className="sr-only">Ask a question about your data</label>
        <textarea id="ask" ref={boxRef} rows={home ? 2 : 1} value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKeyDown} maxLength={4000}
          placeholder={pending ? 'Your answer…' : !loaded ? 'Loading data sources…' : selected.length ? 'Ask a question about your data…' : 'Choose a data source to start'}
          className="block max-h-[40vh] min-h-[44px] w-full resize-none bg-transparent px-1 text-[16px] leading-relaxed text-fg [field-sizing:content] placeholder:text-fg-3 focus:outline-none" />

        <div className="mt-1.5 flex items-center gap-1.5">
          <div ref={plus.box} className="relative" onKeyDown={plus.onKeyDown}>
            <button type="button" onClick={() => plus.setOpen((o) => !o)} aria-label="Add context" aria-expanded={plus.open} aria-haspopup="menu"
              className="flex h-8 w-8 items-center justify-center rounded-full border border-line text-fg-2 hover:border-line-strong hover:text-fg"><Plus className="h-4 w-4" /></button>
            {plus.open && (
              <div role="menu" className="absolute bottom-full left-0 z-30 mb-2 w-72 rounded-xl border border-line bg-surface p-1.5 shadow-lg">
                <button type="button" role="menuitem" onClick={() => { file.current?.click(); plus.setOpen(false) }}
                  className="flex min-h-9 w-full items-center gap-2 rounded-lg px-2 text-left text-[13.5px] text-fg hover:bg-surface-2">
                  <Paperclip className="h-4 w-4 text-fg-3" aria-hidden /> Attach a file <span className="ml-auto text-[12px] text-fg-3">CSV, TSV, XLSX</span>
                </button>
                <p className="px-2 pb-1 pt-2 text-[12px] font-medium text-fg-3">Add a data source</p>
                {datasets.map((d) => (
                  <button key={d.dataset} type="button" role="menuitemcheckbox" aria-checked={selected.includes(d.dataset)} onClick={() => toggle(d.dataset)}
                    className="flex min-h-9 w-full items-center gap-2 rounded-lg px-2 text-left text-[13.5px] text-fg hover:bg-surface-2">
                    {d.kind === 'upload' ? <FileSpreadsheet className="h-4 w-4 text-fg-3" aria-hidden /> : <Database className="h-4 w-4 text-fg-3" aria-hidden />}
                    <span className="truncate">{datasetLabel(d)}</span>
                    {selected.includes(d.dataset) && <Check className="ml-auto h-4 w-4 text-brand" aria-hidden />}
                  </button>
                ))}
                <p className="px-2 pb-1 pt-1.5 text-[11.5px] text-fg-3">Files are private to you and deleted after 24 h.</p>
              </div>
            )}
            <input ref={file} type="file" accept={ACCEPT} className="sr-only" tabIndex={-1} aria-hidden
              onChange={(e) => { const f = e.target.files?.[0]; if (f) onUpload(f); e.target.value = '' }} />
          </div>

          <div ref={picker.box} className="relative ml-auto" onKeyDown={picker.onKeyDown}>
            <button type="button" onClick={() => picker.setOpen((o) => !o)} aria-expanded={picker.open} aria-haspopup="dialog"
              className="inline-flex min-h-8 items-center gap-1 rounded-lg px-2 text-[13px] text-fg-2 hover:bg-surface-2 hover:text-fg">
              {pickerLabel} · {mode === 'deep' ? 'Deep' : 'Quick'} <ChevronDown className="h-3.5 w-3.5" aria-hidden />
            </button>
            {picker.open && (
              <div role="dialog" aria-label="Data source and mode" className="absolute bottom-full right-0 z-30 mb-2 w-80 rounded-xl border border-line bg-surface p-2 shadow-lg">
                <p className="px-1.5 pb-1 text-[12px] font-medium text-fg-3">Data sources</p>
                {datasets.length === 0 && <p className="px-1.5 py-1 text-[13px] text-fg-2">No data sources are available to you.</p>}
                {datasets.map((d) => (
                  <label key={d.dataset} className="flex cursor-pointer items-start gap-2 rounded-lg px-1.5 py-1.5 hover:bg-surface-2">
                    <input type="checkbox" checked={selected.includes(d.dataset)} onChange={() => toggle(d.dataset)} className="mt-1 h-4 w-4 accent-[var(--brand)]" />
                    <span className="min-w-0">
                      <span className="block text-[13.5px] text-fg">{datasetLabel(d)}</span>
                      <span className="block text-[12px] text-fg-3">{d.description || d.dataset} · {d.profile ? `${d.profile.row_count.toLocaleString()} rows` : 'not profiled yet'}</span>
                    </span>
                  </label>
                ))}
                <div className="my-2 border-t border-line" />
                <div role="radiogroup" aria-label="Mode" className="grid grid-cols-2 gap-1 rounded-lg bg-surface-2 p-1">
                  {([['quick', 'Quick answer', 'Checked by a second model'], ['deep', 'Deep analysis', 'Independent models must agree; slower']] as const).map(([value, title, note]) => (
                    <button key={value} type="button" role="radio" aria-checked={mode === value} onClick={() => setMode(value)}
                      className={cn('rounded-md px-2 py-1.5 text-left', mode === value ? 'bg-surface text-fg shadow-sm' : 'text-fg-2 hover:text-fg')}>
                      <span className="block text-[13px] font-medium">{title}</span><span className="block text-[11.5px] text-fg-3">{note}</span>
                    </button>
                  ))}
                </div>
                <label className="mt-2 flex items-center justify-between gap-2 px-1.5 text-[12.5px] text-fg-2">
                  Model that writes the SQL
                  <select value={chosen ?? ''} onChange={(e) => pickModel(e.target.value)} disabled={busy}
                    className="min-h-7 max-w-[55%] rounded-md border border-line-strong bg-surface px-1.5 text-[12.5px] text-fg">
                    <option value="">Auto (recommended)</option>
                    {models.map((m) => <option key={m.id} value={m.id} disabled={!m.available}>{modelLabel(m.id)}{m.available ? '' : ` (unavailable: ${m.note})`}</option>)}
                  </select>
                </label>
                <button type="button" onClick={() => setAbout((a) => !a)} aria-expanded={about} className="mt-2 min-h-6 px-1.5 text-[12.5px] text-brand hover:underline">
                  What's in {chosenSets.length === 1 ? datasetLabel(chosenSets[0]) : 'these sources'}?
                </button>
                {about && chosenSets.map((d) => (
                  <div key={d.dataset} className="px-1.5 pt-1 text-[12.5px]">
                    <p className="font-mono text-fg">{d.dataset}</p>
                    <p className="text-fg-3">{d.profile ? `${d.profile.columns.length} columns: ${d.profile.columns.slice(0, 8).map((c) => c.name).join(', ')}${d.profile.columns.length > 8 ? '…' : ''}` : 'Not profiled yet'} · refreshed {relativeTime(d.refreshed_at)}</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {busy ? (
            <button type="button" onClick={onStop} aria-label="Stop" className="flex h-8 w-8 items-center justify-center rounded-full bg-fg text-bg hover:opacity-90"><Square className="h-3.5 w-3.5" /></button>
          ) : (
            <button type="button" onClick={onSubmit} aria-label="Send" disabled={!canSend}
              className={cn('flex h-8 w-8 items-center justify-center rounded-full bg-brand text-on-brand transition-[opacity,transform] duration-150 hover:opacity-90',
                canSend ? 'scale-100 opacity-100' : 'pointer-events-none scale-90 opacity-0')}>
              <ArrowUp className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
      <p className="mt-2 text-center text-[12px] text-fg-3">Answers can be wrong. Check the SQL for important decisions.</p>
    </div>
  )
}
