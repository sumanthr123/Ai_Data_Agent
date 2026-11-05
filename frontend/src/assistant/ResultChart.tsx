import { useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fmtCell, fmtCompact, humanize, isMeasure, isNumericType, isTimeLike } from './format'
import type { ResultPreview } from './types'

const SERIES = '#38bdf8'
const GRID = '#27272a'
const AXIS = '#a1a1aa'

/** One measure per chart (one axis); a selector switches measures. Only drawn when the shape suits a chart. */
export function ResultChart({ result }: { result: ResultPreview }) {
  const plan = useMemo(() => {
    if (result.truncated || result.rows.length < 2 || result.rows.length > 40) return null
    const cols = result.columns.map((c, i) => ({ name: c, type: result.column_types[i] ?? '' }))
    const dims = cols.filter((c) => !isNumericType(c.type) || isTimeLike(c.name, c.type))
    const measures = cols.filter((c) => isMeasure(c.name, c.type) && !isTimeLike(c.name, c.type)).map((c) => c.name)
    if (dims.length !== 1 || !measures.length) return null
    const dim = dims[0]
    const time = isTimeLike(dim.name, dim.type)
    const rows = time ? [...result.rows].sort((a, b) => String(a[dim.name]).localeCompare(String(b[dim.name]))) : result.rows
    return { dim: dim.name, measures, time, rows }
  }, [result])
  const [measure, setMeasure] = useState<string | null>(null)
  if (!plan) return null
  const m = measure && plan.measures.includes(measure) ? measure : plan.measures[0]
  const types = Object.fromEntries(result.columns.map((c, i) => [c, result.column_types[i] ?? '']))
  const data = plan.rows.map((r) => ({ label: String(r[plan.dim] ?? 'NULL'), value: typeof r[m] === 'number' ? r[m] : null }))
  const title = `${humanize(m)} by ${humanize(plan.dim)}`
  const tooltip = (
    <Tooltip cursor={{ fill: 'rgba(255,255,255,0.04)' }}
      content={({ active, payload, label }) => active && payload?.length ? (
        <div className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-[12px] shadow-lg">
          <div className="text-zinc-300">{label}</div>
          <div className="font-mono text-zinc-100">{fmtCell(payload[0].value as number, types[m])}</div>
        </div>
      ) : null} />
  )
  const axes = (
    <>
      <CartesianGrid stroke={GRID} vertical={false} />
      <XAxis dataKey="label" tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={{ stroke: GRID }} interval="preserveStartEnd" />
      <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} tickFormatter={fmtCompact} width={56} />
    </>
  )
  return (
    <figure className="rounded-xl border border-zinc-800 p-3">
      <figcaption className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="text-[13px] font-medium text-zinc-200">{title}</span>
        {plan.measures.length > 1 && (
          <div role="group" aria-label="Measure" className="flex flex-wrap gap-1">
            {plan.measures.map((x) => (
              <button key={x} type="button" aria-pressed={x === m} onClick={() => setMeasure(x)}
                className={x === m ? 'rounded-md bg-zinc-700 px-2 py-0.5 text-[11.5px] text-white' : 'rounded-md px-2 py-0.5 text-[11.5px] text-zinc-300 hover:bg-zinc-800'}>
                {humanize(x)}
              </button>
            ))}
          </div>
        )}
      </figcaption>
      <div className="h-56" role="img" aria-label={`${plan.time ? 'Line' : 'Bar'} chart of ${title}. The table below has the exact values.`}>
        <ResponsiveContainer width="100%" height="100%">
          {plan.time ? (
            <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              {axes}{tooltip}
              <Line type="linear" dataKey="value" stroke={SERIES} strokeWidth={2} dot={{ r: 3, fill: SERIES, strokeWidth: 0 }} activeDot={{ r: 5 }} />
            </LineChart>
          ) : (
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barCategoryGap="20%">
              {axes}{tooltip}
              <Bar dataKey="value" fill={SERIES} radius={[4, 4, 0, 0]} maxBarSize={48} />
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </figure>
  )
}
