import { ArrowDown, ArrowUp } from 'lucide-react'
import { useMemo, useState } from 'react'
import { fmtCell, isNumericType } from './format'
import type { Cell, ResultPreview } from './types'

const compare = (a: Cell, b: Cell) => (a === null ? 1 : b === null ? -1 : typeof a === 'number' && typeof b === 'number' ? a - b : String(a).localeCompare(String(b)))

/** Sticky header, sortable columns, tabular numbers. Scrolls inside its own box so the page never scrolls sideways. */
export function ResultTable({ result, tall = false }: { result: ResultPreview; tall?: boolean }) {
  const [limit, setLimit] = useState(tall ? 500 : 20)
  const [sort, setSort] = useState<{ col: string; dir: 1 | -1 } | null>(null)
  const types = Object.fromEntries(result.columns.map((c, i) => [c, result.column_types[i] ?? '']))
  const sorted = useMemo(() => (sort ? [...result.rows].sort((a, b) => compare(a[sort.col], b[sort.col]) * sort.dir) : result.rows), [result.rows, sort])
  const rows = sorted.slice(0, limit)
  const toggle = (col: string) => setSort((s) => (s?.col !== col ? { col, dir: isNumericType(types[col]) ? -1 : 1 } : s.dir === 1 ? { col, dir: -1 } : { col, dir: 1 }))
  return (
    <div className="rounded-lg border border-line">
      <div className={tall ? 'overflow-auto' : 'max-h-[360px] overflow-auto'}>
        <table className="w-full border-collapse text-[13px]">
          <caption className="sr-only">Query result, {result.row_count.toLocaleString()} rows{sort ? `, sorted by ${sort.col}` : ''}</caption>
          <thead className="sticky top-0 bg-surface-2">
            <tr>{result.columns.map((c) => {
              const numeric = isNumericType(types[c])
              const active = sort?.col === c
              return (
                <th key={c} scope="col" aria-sort={active ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}
                  className={`whitespace-nowrap border-b border-line px-3 py-1.5 font-mono text-[12px] font-medium text-fg-2 ${numeric ? 'text-right' : 'text-left'}`}>
                  <button type="button" onClick={() => toggle(c)} className={`inline-flex min-h-6 items-center gap-1 hover:text-fg ${numeric ? 'flex-row-reverse' : ''}`}>
                    {c}{active && (sort.dir === 1 ? <ArrowUp className="h-3 w-3" aria-hidden /> : <ArrowDown className="h-3 w-3" aria-hidden />)}
                  </button>
                </th>
              )
            })}</tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-line/60 last:border-0 hover:bg-surface-2">
                {result.columns.map((c) => (
                  <td key={c} className={`whitespace-nowrap px-3 py-1.5 ${isNumericType(types[c]) ? 'text-right font-mono tnum' : ''} ${row[c] === null ? 'text-fg-3' : 'text-fg'}`}>
                    {fmtCell(row[c], types[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-3 py-1.5 text-[12px] text-fg-3">
        <span>
          Showing {rows.length.toLocaleString()} of {result.row_count.toLocaleString()} rows
          {result.truncated && <span className="text-warn"> · truncated at the row limit; Export CSV for the full result</span>}
          {result.from_cache && ' · cached result'}
        </span>
        {limit < sorted.length && <button type="button" onClick={() => setLimit((l) => l + 50)} className="min-h-6 rounded px-2 text-brand hover:bg-surface-2">Show more</button>}
      </div>
    </div>
  )
}
