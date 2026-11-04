import { AnimatePresence, motion } from 'framer-motion'
import { ArrowUp, Paperclip, SlidersHorizontal, Square, X } from 'lucide-react'
import { useRef, useState, type ClipboardEvent, type KeyboardEvent } from 'react'
import { cn, spring } from '../lib/cn'
import type { Attachment, ModelOption } from '../types/consensus'
import { FileChip } from './Attachments'

export function OmniPromptBar({ text, setText, pills, setPills, leadOptions, lead, setLead, busy, onSend, onStop, files, onAddFiles, onRemoveFile }: {
  text: string; setText: (t: string) => void; pills: string[]; setPills: (p: string[]) => void
  leadOptions: ModelOption[]; lead: string; setLead: (id: string) => void
  busy: boolean; onSend: () => void; onStop: () => void
  files: Attachment[]; onAddFiles: (files: File[]) => void; onRemoveFile: (id: string) => void
}) {
  const [focused, setFocused] = useState(false)
  const [advanced, setAdvanced] = useState(false)
  const unavailable = leadOptions.filter((m) => m.available === false).length
  const picker = useRef<HTMLInputElement>(null)
  const uploading = files.some((f) => f.status === 'uploading')
  const canSend = !uploading && (Boolean(text.trim()) || pills.length > 0 || files.some((f) => f.status === 'ready'))

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (canSend) onSend() }
    if (e.key === 'Backspace' && !text && pills.length) setPills(pills.slice(0, -1))
  }
  // Pasting a screenshot or a copied file attaches it instead of inserting text.
  const onPaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    const pasted = [...e.clipboardData.files]
    if (pasted.length) { e.preventDefault(); onAddFiles(pasted) }
  }

  return (
    <motion.div layout transition={spring}
      className={cn('w-full max-w-3xl rounded-3xl border border-white/10 bg-slate-900/80 p-3 shadow-2xl shadow-black/60 backdrop-blur-xl transition',
        focused && 'border-blue-400/40')}>
      {files.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-2 px-1">
          <AnimatePresence>{files.map((f) => <FileChip key={f.id} file={f} onRemove={() => onRemoveFile(f.id)} />)}</AnimatePresence>
        </div>
      )}
      {pills.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5 px-1">
          <AnimatePresence>
            {pills.map((p) => (
              <motion.span key={p} layout initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.8 }} transition={spring}
                className="flex items-center gap-1 rounded-full border border-sky-400/30 bg-sky-500/10 py-0.5 pl-2.5 pr-1 font-mono text-[11.5px] text-sky-200">
                {p}<button type="button" onClick={() => setPills(pills.filter((x) => x !== p))} aria-label={`Remove ${p}`} className="rounded-full p-0.5 text-slate-400 hover:text-white"><X className="h-3 w-3" /></button>
              </motion.span>
            ))}
          </AnimatePresence>
        </div>
      )}
      <textarea value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} onPaste={onPaste} onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
        rows={2} placeholder={files.length ? 'Ask about the attached files…' : 'Ask about your sales data, or anything else… (drop files to attach)'}
        className="w-full resize-none bg-transparent px-2 text-[15px] text-white placeholder:text-slate-400 focus:outline-none" />
      <div className="mt-1 flex flex-wrap items-center gap-2 px-1">
        <input ref={picker} type="file" multiple hidden onChange={(e) => { if (e.target.files?.length) onAddFiles([...e.target.files]); e.target.value = '' }} />
        <button type="button" onClick={() => picker.current?.click()} title="Attach files (or drag and drop)" aria-label="Attach files"
          className="flex h-8 w-8 items-center justify-center rounded-full text-slate-300 hover:bg-white/10 hover:text-white">
          <Paperclip className="h-4 w-4" />
        </button>
        <div className="relative">
          <button type="button" onClick={() => setAdvanced((a) => !a)} aria-expanded={advanced} aria-controls="model-settings"
            className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1 text-[12.5px] text-slate-200 hover:bg-white/5">
            <SlidersHorizontal className="h-3.5 w-3.5" /> Model: {lead === 'auto' ? 'Auto' : leadOptions.find((m) => m.id === lead)?.name ?? lead}
          </button>
          {advanced && (
            <div id="model-settings" role="dialog" aria-label="Model settings" onKeyDown={(e) => { if (e.key === 'Escape') setAdvanced(false) }}
              className="absolute bottom-full left-0 z-50 mb-2 w-[320px] rounded-2xl border border-white/10 bg-slate-950 p-3 shadow-2xl">
              <label htmlFor="lead-model" className="block text-[12.5px] font-medium text-slate-100">Lead model</label>
              <p className="mt-0.5 text-[12px] text-slate-300">Auto picks available models and is recommended. The lead model answers first; others cross-check.</p>
              <select id="lead-model" value={lead} autoFocus onChange={(e) => { setLead(e.target.value); setAdvanced(false) }}
                className="mt-2 w-full rounded-lg border border-white/15 bg-slate-900 px-2 py-1.5 text-[13px] text-slate-100">
                <option value="auto">Auto (recommended)</option>
                {[...new Set(leadOptions.map((m) => m.provider ?? 'Other'))].map((provider) => (
                  <optgroup key={provider} label={provider}>
                    {leadOptions.filter((m) => (m.provider ?? 'Other') === provider).map((m) => (
                      <option key={m.id} value={m.id} disabled={m.available === false}>
                        {m.name}{m.available === false ? ` — unavailable: ${m.reason}` : ''}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
              {unavailable > 0 && (
                <p className="mt-2 text-[12px] text-slate-300">{unavailable} model(s) are unavailable right now (checked with the provider); they're greyed out with the reason.</p>
              )}
            </div>
          )}
        </div>
        <span className="hidden text-[12px] text-slate-300 sm:inline">{uploading ? 'Reading files…' : 'Other models double-check every answer'}</span>
        <motion.button type="button" whileTap={{ scale: 0.92 }} onClick={busy ? onStop : onSend} disabled={!busy && !canSend}
          aria-label={busy ? 'Stop' : 'Send'}
          className="ml-auto flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-sky-400 via-blue-500 to-indigo-600 text-white disabled:opacity-30">
          {busy ? <Square className="h-3.5 w-3.5 fill-white" /> : <ArrowUp className="h-4 w-4" />}
        </motion.button>
      </div>
    </motion.div>
  )
}
