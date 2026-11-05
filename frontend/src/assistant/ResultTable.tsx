import { useState } from 'react'
import { fmtCell, isNumericType } from './format'
import type { ResultPreview } from './types'

export function ResultTable({ result }: { result: ResultPreview }) {
  const [limit, setLimit] = useState(20)
  const rows = result.rows.slice(0, limit)
  const types = Object.fromEntries(result.columns.map((c, i) => [c, result.column_types[i] ?? '']))
  return (
    <div className="rounded-xl border border-zinc-800">
      <div className="max-h-[360px] overflow-auto">
        <table className="w-full border-collapse text-[12.5px]">
          <caption className="sr-only">Query result, {result.row_count} rows</caption>
          <thead className="sticky top-0 bg-zinc-900">
            <tr>{result.columns.map((c) => (
              <th key={c} scope="col" className={`whitespace-nowrap border-b border-zinc-800 px-3 py-2 font-mono text-[11px] font-medium text-zinc-300 ${isNumericType(types[c]) ? 'text-right' : 'text-left'}`}>{c}</th>
            ))}</tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-zinc-800/60 last:border-0 hover:bg-zinc-900/60">
                {result.columns.map((c) => (
                  <td key={c} className={`whitespace-nowrap px-3 py-1.5 ${isNumericType(types[c]) ? 'text-right font-mono tabular-nums' : ''} ${row[c] === null ? 'text-zinc-500' : 'text-zinc-100'}`}>
                    {fmtCell(row[c], types[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-zinc-800 px-3 py-2 text-[11.5px] text-zinc-400">
        <span>
          Showing {rows.length.toLocaleString()} of {result.row_count.toLocaleString()} rows
          {result.truncated && <span className="text-amber-300"> · result truncated at the row limit; download for the full result</span>}
          {result.from_cache && ' · cached result'}
        </span>
        {limit < result.rows.length && (
          <button type="button" onClick={() => setLimit((l) => l + 50)} className="rounded-md px-2 py-1 text-sky-300 hover:bg-zinc-800">Show more</button>
        )}
      </div>
    </div>
  )
}
