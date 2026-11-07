import { useMemo, useRef, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { token } from '../theme'
import type { ChartPlan } from './chartPlan'
import { fmtCell, fmtCompact, humanize } from './format'
import type { ResultPreview } from './types'

/** Saves the drawn SVG as a PNG on the surface color, so it pastes cleanly into a deck. */
async function savePng(svg: SVGSVGElement, name: string): Promise<void> {
  const { width, height } = svg.getBoundingClientRect()
  const clone = svg.cloneNode(true) as SVGSVGElement
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  clone.setAttribute('width', String(width))
  clone.setAttribute('height', String(height))
  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)], { type: 'image/svg+xml' }))
  try {
    const img = new Image()
    await new Promise<void>((resolve, reject) => { img.onload = () => resolve(); img.onerror = () => reject(new Error('The chart image could not be drawn.')); img.src = url })
    const scale = 2
    const canvas = Object.assign(document.createElement('canvas'), { width: width * scale, height: height * scale })
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('This browser cannot draw the chart image.')
    ctx.fillStyle = token('--surface')
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
    const a = Object.assign(document.createElement('a'), { href: canvas.toDataURL('image/png'), download: `${name}.png` })
    a.click()
  } finally {
    URL.revokeObjectURL(url)
  }
}

/** One measure per chart (one axis); a selector switches measures. `theme` re-reads colors when it changes. */
export function ResultChart({ result, plan, theme, onError }: { result: ResultPreview; plan: ChartPlan; theme: string; onError: (message: string) => void }) {
  const [measure, setMeasure] = useState<string | null>(null)
  const box = useRef<HTMLDivElement>(null)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const c = useMemo(() => ({ series: token('--chart-1'), grid: token('--border'), axis: token('--text-3'), text: token('--text') }), [theme])
  const m = measure && plan.measures.includes(measure) ? measure : plan.measures[0]
  const types = Object.fromEntries(result.columns.map((col, i) => [col, result.column_types[i] ?? '']))
  const data = plan.rows.map((r) => ({ label: String(r[plan.dim] ?? 'NULL'), value: typeof r[m] === 'number' ? r[m] : null }))
  const title = `${humanize(m)} by ${humanize(plan.dim)}`
  const exportPng = () => {
    const svg = box.current?.querySelector('svg')
    if (!svg) return onError('The chart is not drawn yet.')
    savePng(svg, title.replace(/\s+/g, '-')).catch((err: Error) => onError(err.message))
  }
  const tooltip = (
    <Tooltip cursor={{ fill: c.grid, fillOpacity: 0.35 }}
      content={({ active, payload, label }) => active && payload?.length ? (
        <div className="rounded-md border border-line bg-surface px-3 py-2 text-[12px] shadow-md">
          <div className="text-fg-2">{label}</div>
          <div className="font-mono tnum text-fg">{fmtCell(payload[0].value as number, types[m])} <span className="text-fg-3">{humanize(m)}</span></div>
        </div>
      ) : null} />
  )
  const axes = (
    <>
      <CartesianGrid stroke={c.grid} vertical={false} />
      <XAxis dataKey="label" tick={{ fill: c.axis, fontSize: 12 }} tickLine={false} axisLine={{ stroke: c.grid }} interval="preserveStartEnd" />
      <YAxis tick={{ fill: c.axis, fontSize: 12 }} tickLine={false} axisLine={false} tickFormatter={fmtCompact} width={56} />
    </>
  )
  return (
    <figure className="rounded-lg border border-line p-3">
      <figcaption className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="text-[13px] font-medium text-fg">{title}</span>
        <span className="flex flex-wrap items-center gap-1">
          {plan.measures.length > 1 && plan.measures.map((x) => (
            <button key={x} type="button" aria-pressed={x === m} onClick={() => setMeasure(x)}
              className={x === m ? 'min-h-6 rounded bg-surface-2 px-2 text-[12px] text-fg ring-1 ring-line-strong' : 'min-h-6 rounded px-2 text-[12px] text-fg-2 hover:bg-surface-2'}>
              {humanize(x)}
            </button>
          ))}
          <button type="button" onClick={exportPng} className="min-h-6 rounded px-2 text-[12px] text-fg-2 hover:bg-surface-2">Save PNG</button>
        </span>
      </figcaption>
      <div ref={box} className="h-60" role="img" aria-label={`${plan.time ? 'Line' : 'Bar'} chart of ${title}. Switch to Table for exact values.`}>
        <ResponsiveContainer width="100%" height="100%">
          {plan.time ? (
            <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              {axes}{tooltip}
              <Line type="linear" dataKey="value" stroke={c.series} strokeWidth={2} dot={{ r: 3, fill: c.series, strokeWidth: 0 }} activeDot={{ r: 5 }} isAnimationActive={false} />
            </LineChart>
          ) : (
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barCategoryGap="22%">
              {axes}{tooltip}
              <Bar dataKey="value" fill={c.series} radius={[3, 3, 0, 0]} maxBarSize={48} isAnimationActive={false} />
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </figure>
  )
}
