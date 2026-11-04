import { motion } from 'framer-motion'
import { AlertCircle, FileCode2, FileImage, FileSpreadsheet, FileText, Loader2, X } from 'lucide-react'
import { cn } from '../lib/cn'
import type { Attachment } from '../types/consensus'

const ICONS = { data: FileSpreadsheet, image: FileImage, code: FileCode2, document: FileText, text: FileText }
const KIND_LABEL = { data: 'Data · queryable', image: 'Image', code: 'Code', document: 'Document', text: 'Text' }

export function formatSize(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : bytes < 1024 ** 2 ? `${(bytes / 1024).toFixed(0)} KB` : `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

/** Upload one file; the server returns its extracted text or, for data files, a queryable read_files() source. */
export async function uploadFile(file: File): Promise<Attachment> {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch('/api/files', { method: 'POST', body: form })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.detail ?? `Upload failed (${response.status})`)
  return { ...body, status: 'ready' }
}

export function FileChip({ file, onRemove }: { file: Attachment; onRemove?: () => void }) {
  const Icon = file.status === 'error' ? AlertCircle : ICONS[file.kind ?? 'text']
  return (
    <motion.div layout initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.9 }}
      title={file.error ?? file.name}
      className={cn('flex max-w-[240px] items-center gap-2 rounded-xl border px-2.5 py-1.5 text-left',
        file.status === 'error' ? 'border-rose-400/40 bg-rose-500/10' : 'border-white/10 bg-white/[0.05]')}>
      <span className={cn('flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
        file.status === 'error' ? 'bg-rose-500/20 text-rose-200' : file.kind === 'data' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-sky-500/15 text-sky-300')}>
        {file.status === 'uploading' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Icon className="h-4 w-4" />}
      </span>
      <span className="min-w-0">
        <span className="block truncate text-[12.5px] text-white">{file.name}</span>
        <span className={cn('block truncate text-[11px]', file.status === 'error' ? 'text-rose-300' : 'text-slate-400')}>
          {file.status === 'uploading' ? 'Reading…' : file.status === 'error' ? file.error : `${KIND_LABEL[file.kind ?? 'text']} · ${formatSize(file.size)}`}
        </span>
      </span>
      {onRemove && (
        <button type="button" onClick={onRemove} aria-label={`Remove ${file.name}`} className="ml-auto rounded-full p-1 text-slate-400 hover:bg-white/10 hover:text-white">
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </motion.div>
  )
}
