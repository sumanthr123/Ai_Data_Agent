import type { UploadResult } from './types'

export function UploadSummary({ result, onDismiss }: { result: UploadResult; onDismiss: () => void }) {
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
