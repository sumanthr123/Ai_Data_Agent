import {
  flexRender, getCoreRowModel, getFilteredRowModel, getSortedRowModel, useReactTable, type ColumnDef, type SortingState,
} from '@tanstack/react-table'
import { AnimatePresence, motion } from 'framer-motion'
import { ArrowDown, ArrowUp, Braces, Download, GitBranch, LineChart as LineIcon, Search, Table2, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, ComposedChart, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { cn, fmtMoney, fmtNum, spring } from '../lib/cn'
import { SqlBlock } from '../lib/code'
import type { CanvasItem, Kpi, Lineage, ResultSet, Row } from '../types/consensus'
import { Sparkline } from './Sparkline'
import { useToast } from './Toast'

const isPct = (c: string) => /pct|percent|rate/i.test(c)
const isMoney = (c: string) => !isPct(c) && /sales|revenue|profit|loss|cost|amount|arr|mrr|price/i.test(c)
const label = (c: string) => c.replace(/_/g, ' ')
const fmt = (c: string, v: unknown) => typeof v !== 'number' ? String(v ?? '') : isPct(c) ? `${v.toFixed(1)}%` : isMoney(c) ? fmtMoney(v) : fmtNum(v)

function KpiCard({ kpi, i }: { kpi: Kpi; i: number }) {
  const up = kpi.delta >= 0
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ ...spring, delay: i * 0.05 }}
      className="rounded-2xl border border-white/10 bg-slate-900/65 p-3.5 backdrop-blur-xl">
      <div className="truncate font-mono text-[9.5px] tracking-widest text-slate-400">{kpi.label}</div>
      <div className="mt-1 flex items-end justify-between gap-2">
        <div className="text-xl font-semibold text-white">{kpi.value}</div>
        {kpi.delta !== 0 && (
          <span className={cn('flex items-center rounded-md px-1.5 py-0.5 font-mono text-[10.5px]', up ? 'bg-emerald-400/10 text-emerald-300' : 'bg-rose-400/10 text-rose-300')}>
            {up ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}{Math.abs(kpi.delta * 100).toFixed(1)}%
          </span>
        )}
      </div>
      <Sparkline values={kpi.spark} id={`kpi${i}`} />
    </motion.div>
  )
}

function DeltaGrid({ result }: { result: ResultSet }) {
  const toast = useToast()
  const [sorting, setSorting] = useState<SortingState>([])
  const [filter, setFilter] = useState('')
  const ranges = useMemo(() => Object.fromEntries(result.columns.filter((c) => result.rows.every((r) => typeof r[c] === 'number')).map((c) => {
    const v = result.rows.map((r) => Number(r[c]))
    return [c, [Math.min(...v), Math.max(...v)]]
  })), [result])
  const columns = useMemo<ColumnDef<Row>[]>(() => result.columns.map((c) => ({ id: c, accessorKey: c, header: label(c), cell: (i) => fmt(c, i.getValue()) })), [result.columns])
  const table = useReactTable({
    data: result.rows, columns, state: { sorting, globalFilter: filter }, onSortingChange: setSorting, onGlobalFilterChange: setFilter,
    getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel(), getFilteredRowModel: getFilteredRowModel(),
  })
  const save = (content: string, type: string, name: string) => {
    const url = URL.createObjectURL(new Blob([content], { type }))
    Object.assign(document.createElement('a'), { href: url, download: name }).click()
    URL.revokeObjectURL(url)
    toast(`Exported ${name}`)
  }
  const rows = table.getRowModel().rows.map((r) => r.original)
  return (
    <div className="overflow-hidden rounded-2xl border border-white/10 bg-slate-900/65 backdrop-blur-xl">
      <div className="flex flex-wrap items-center gap-2 border-b border-white/[0.06] p-2.5">
        <label className="flex flex-1 items-center gap-2 rounded-lg bg-black/30 px-2.5 py-1.5">
          <Search className="h-3.5 w-3.5 text-slate-400" />
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter rows" className="w-full bg-transparent font-mono text-[12px] text-slate-200 placeholder:text-slate-400 focus:outline-none" />
          {filter && <button type="button" onClick={() => setFilter('')} aria-label="Clear filter"><X className="h-3.5 w-3.5 text-slate-400" /></button>}
        </label>
        <span className="font-mono text-[11px] text-slate-400">{rows.length}{result.truncated ? '+' : ''} rows</span>
        <button type="button" onClick={() => save([result.columns.join(','), ...rows.map((r) => result.columns.map((c) => JSON.stringify(r[c] ?? '')).join(','))].join('\n'), 'text/csv', 'consensus_result.csv')}
          className="flex items-center gap-1 rounded-lg border border-white/10 px-2 py-1.5 text-[11.5px] text-slate-300 hover:bg-white/[0.06]"><Download className="h-3.5 w-3.5" /> CSV</button>
        <button type="button" onClick={() => save(JSON.stringify(rows, null, 2), 'application/json', 'consensus_result.json')}
          className="flex items-center gap-1 rounded-lg border border-white/10 px-2 py-1.5 text-[11.5px] text-slate-300 hover:bg-white/[0.06]"><Braces className="h-3.5 w-3.5" /> JSON</button>
      </div>
      <div className="max-h-[420px] overflow-auto">
        <table className="w-full border-collapse text-[12.5px]">
          <thead className="sticky top-0 z-10 bg-[#0b1018]">
            <tr>{table.getHeaderGroups()[0].headers.map((h, i) => (
              <th key={h.id} className="whitespace-nowrap border-b border-white/[0.06] px-3 py-2 text-left">
                <button type="button" onClick={h.column.getToggleSortingHandler()} className="flex items-center gap-1 font-mono text-[10.5px] uppercase tracking-wider text-slate-400 hover:text-white">
                  {flexRender(h.column.columnDef.header, h.getContext())}
                  {h.column.getIsSorted() === 'asc' ? <ArrowUp className="h-3 w-3" /> : h.column.getIsSorted() === 'desc' ? <ArrowDown className="h-3 w-3" /> : null}
                </button>
                <span className="mt-0.5 inline-block rounded bg-white/[0.05] px-1 font-mono text-[9px] text-slate-400">{(result.column_types[i] ?? '').toLowerCase()}</span>
              </th>
            ))}</tr>
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="hover:bg-white/[0.03]">
                {row.getVisibleCells().map((cell) => {
                  const range = ranges[cell.column.id]
                  const v = cell.getValue()
                  const share = range && typeof v === 'number' && range[1] !== range[0] ? (v - range[0]) / (range[1] - range[0]) : null
                  return (
                    <td key={cell.id} className="relative whitespace-nowrap border-b border-white/[0.04] px-3 py-1.5 font-mono text-slate-200">
                      {share !== null && <span className="absolute inset-y-1 left-0 rounded-r bg-sky-400/15" style={{ width: `${8 + share * 88}%` }} />}
                      <span className="relative">{flexRender(cell.column.columnDef.cell, cell.getContext())}</span>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

type Kind = 'area' | 'bar' | 'line' | 'composed'

function ChartStudio({ result }: { result: ResultSet }) {
  const dims = result.columns.filter((c) => !result.measures.includes(c))
  const [kind, setKind] = useState<Kind>(result.dimension && /date|month|year|day|week|quarter/i.test(result.dimension) ? 'area' : 'bar')
  const [x, setX] = useState(result.dimension ?? result.columns[0])
  const [y, setY] = useState(result.measures[0])
  if (!y) return <div className="rounded-2xl border border-white/10 bg-slate-900/65 p-6 text-center text-[13px] text-slate-400">This result has no numeric column to chart.</div>
  const data = result.rows.map((r, i, all) => {
    const window = all.slice(Math.max(0, i - 2), i + 1).map((w) => Number(w[y]))
    return { ...r, __trend: window.reduce((a, b) => a + b, 0) / window.length }
  })
  const axis = { stroke: '#475569', fontSize: 11, tickLine: false, axisLine: false }
  const yTick = (v: number) => (isPct(y) ? `${v}%` : isMoney(y) ? fmtMoney(v) : fmtNum(v))
  const tip = (
    <Tooltip cursor={{ fill: 'rgba(255,255,255,0.04)', stroke: 'rgba(255,255,255,0.15)' }}
      content={(p) => p.active && p.payload?.length ? (
        <div className="rounded-xl border border-white/10 bg-slate-900/90 px-3 py-2 shadow-xl backdrop-blur-xl">
          <div className="mb-1 font-mono text-[11px] text-slate-400">{String(p.label)}</div>
          {p.payload.map((e, i) => <div key={i} className="flex gap-3 text-[12px]"><span className="text-slate-400">{String(e.name) === '__trend' ? '3-pt avg' : label(String(e.name))}</span><span className="ml-auto font-mono text-white">{fmt(y, e.value)}</span></div>)}
        </div>) : null} />
  )
  const grid = <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
  const defs = (
    <defs>
      <linearGradient id="g-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#38BDF8" stopOpacity={0.45} /><stop offset="100%" stopColor="#4f46e5" stopOpacity={0} /></linearGradient>
      <linearGradient id="g-bar" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#38BDF8" /><stop offset="100%" stopColor="#4f46e5" stopOpacity={0.7} /></linearGradient>
    </defs>
  )
  const common = { data, margin: { left: 4, right: 8, top: 8 } }
  const xAxis = <XAxis dataKey={x} {...axis} />
  const yAxis = <YAxis tickFormatter={yTick} width={66} {...axis} />
  return (
    <div className="rounded-2xl border border-white/10 bg-slate-900/65 p-4 backdrop-blur-xl">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex rounded-full border border-white/10 bg-black/30 p-0.5">
          {(['area', 'bar', 'line', 'composed'] as Kind[]).map((k) => (
            <button key={k} type="button" onClick={() => setKind(k)} className={cn('relative rounded-full px-2.5 py-1 text-[11px] capitalize', kind === k ? 'text-white' : 'text-slate-400 hover:text-slate-300')}>
              {kind === k && <motion.span layoutId="chart-kind" transition={spring} className="absolute inset-0 rounded-full bg-sky-500/25 ring-1 ring-sky-400/40" />}
              <span className="relative">{k}</span>
            </button>
          ))}
        </div>
        <label className="ml-auto flex items-center gap-1 font-mono text-[10.5px] text-slate-400">X
          <select value={x} onChange={(e) => setX(e.target.value)} className="rounded-md border border-white/10 bg-black/40 px-1.5 py-0.5 text-slate-200">{(dims.length ? dims : result.columns).map((c) => <option key={c}>{c}</option>)}</select>
        </label>
        <label className="flex items-center gap-1 font-mono text-[10.5px] text-slate-400">Y
          <select value={y} onChange={(e) => setY(e.target.value)} className="rounded-md border border-white/10 bg-black/40 px-1.5 py-0.5 text-slate-200">{result.measures.map((c) => <option key={c}>{c}</option>)}</select>
        </label>
      </div>
      <AnimatePresence mode="wait">
        <motion.div key={`${kind}${x}${y}`} initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }} transition={spring} className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            {kind === 'area' ? <AreaChart {...common}>{defs}{grid}{xAxis}{yAxis}{tip}<Area type="monotone" dataKey={y} stroke="#38BDF8" strokeWidth={2} fill="url(#g-area)" /></AreaChart>
              : kind === 'bar' ? <BarChart {...common}>{defs}{grid}{xAxis}{yAxis}{tip}<Bar dataKey={y} fill="url(#g-bar)" radius={[4, 4, 0, 0]} maxBarSize={36} /></BarChart>
              : kind === 'line' ? <LineChart {...common}>{grid}{xAxis}{yAxis}{tip}<Line type="monotone" dataKey={y} stroke="#38BDF8" strokeWidth={2} dot={{ r: 3 }} /></LineChart>
              : <ComposedChart {...common}>{defs}{grid}{xAxis}{yAxis}{tip}<Bar dataKey={y} fill="url(#g-bar)" fillOpacity={0.6} radius={[4, 4, 0, 0]} maxBarSize={28} /><Line type="monotone" dataKey="__trend" stroke="#F59E0B" strokeWidth={2} dot={false} /></ComposedChart>}
          </ResponsiveContainer>
        </motion.div>
      </AnimatePresence>
      {kind === 'composed' && <div className="mt-1 font-mono text-[10.5px] text-slate-400">Bars: {label(y)} · Amber line: 3-point moving average (same axis)</div>}
    </div>
  )
}

const nodeColor: Record<string, string> = { bronze: '#ea580c', silver: '#F59E0B', gold: '#10B981', other: '#64748b', warehouse: '#38BDF8', output: '#A78BFA' }

function LineageGraph({ lineage }: { lineage: Lineage }) {
  // Layered layout: each node's column is its longest path from a source.
  const depth: Record<string, number> = {}
  const visit = (id: string, d: number) => { if ((depth[id] ?? -1) < d) { depth[id] = d; lineage.edges.filter(([a]) => a === id).forEach(([, b]) => visit(b, d + 1)) } }
  lineage.nodes.filter((n) => !lineage.edges.some(([, b]) => b === n.id)).forEach((n) => visit(n.id, 0))
  const columns = Math.max(...Object.values(depth), 0) + 1
  const byCol: string[][] = Array.from({ length: columns }, () => [])
  lineage.nodes.forEach((n) => byCol[depth[n.id] ?? 0].push(n.id))
  const W = 500, colW = W / columns, rowH = 64
  const H = Math.max(...byCol.map((c) => c.length)) * rowH + 20
  const pos = Object.fromEntries(byCol.flatMap((ids, c) => ids.map((id, r) => [id, { x: c * colW + colW / 2, y: 30 + r * rowH + (H - 20 - ids.length * rowH) / 2 }])))
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Data lineage graph">
      {lineage.edges.map(([a, b]) => pos[a] && pos[b] && (
        <path key={`${a}-${b}`} d={`M${pos[a].x + 46},${pos[a].y} C${(pos[a].x + pos[b].x) / 2},${pos[a].y} ${(pos[a].x + pos[b].x) / 2},${pos[b].y} ${pos[b].x - 46},${pos[b].y}`}
          fill="none" stroke="rgba(148,163,184,0.35)" strokeWidth={1.5} />
      ))}
      {lineage.nodes.map((n) => {
        const p = pos[n.id]
        const text = n.label.split('.').pop() ?? n.label
        return (
          <g key={n.id} transform={`translate(${p.x - 46},${p.y - 16})`}>
            <rect width={92} height={32} rx={9} fill="rgba(15,23,42,0.9)" stroke={nodeColor[n.kind]} strokeWidth={1.5} />
            <circle cx={11} cy={16} r={3.5} fill={nodeColor[n.kind]} />
            <text x={20} y={13} fill="#e2e8f0" fontSize={9} fontFamily="JetBrains Mono, monospace">{text.length > 12 ? `${text.slice(0, 11)}…` : text}</text>
            <text x={20} y={24} fill="#64748b" fontSize={7.5} fontFamily="JetBrains Mono, monospace">{n.kind}</text>
            <title>{n.label}</title>
          </g>
        )
      })}
    </svg>
  )
}

type Tab = 'grid' | 'chart' | 'lineage'

export function DataLineageCanvas({ item, onClose }: { item: CanvasItem; onClose: () => void }) {
  const [tab, setTab] = useState<Tab>('grid')
  const lead = item.compare[0]
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start gap-3 border-b border-white/[0.07] p-4">
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[10px] uppercase tracking-widest text-slate-400">Data & lineage canvas</div>
          <div className="mt-1 truncate text-[14px] font-medium text-white">{item.title}</div>
          <div className="mt-1 font-mono text-[10.5px] text-sky-300/80">{item.source}</div>
        </div>
        <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-white/[0.06] hover:text-white" aria-label="Close canvas"><X className="h-4 w-4" /></button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {item.kpis.length > 0 && <div className="grid grid-cols-3 gap-2.5">{item.kpis.map((k, i) => <KpiCard key={k.label} kpi={k} i={i} />)}</div>}
        <div className="flex rounded-full border border-white/10 bg-black/30 p-0.5">
          {([['grid', 'Delta Grid', Table2], ['chart', 'Chart Studio', LineIcon], ['lineage', 'SQL Diff & Lineage', GitBranch]] as const).map(([id, text, Icon]) => (
            <button key={id} type="button" onClick={() => setTab(id)} className={cn('relative flex flex-1 items-center justify-center gap-1.5 rounded-full px-3 py-1.5 text-[12px]', tab === id ? 'text-white' : 'text-slate-400 hover:text-slate-300')}>
              {tab === id && <motion.span layoutId="canvas-tab" transition={spring} className="absolute inset-0 rounded-full bg-blue-500/25 ring-1 ring-blue-400/40" />}
              <Icon className="relative h-3.5 w-3.5" /><span className="relative">{text}</span>
            </button>
          ))}
        </div>
        {!item.result && tab !== 'lineage' && <div className="rounded-2xl border border-white/10 p-6 text-center text-[13px] text-slate-400">No tabular result for this answer.</div>}
        {item.result && tab === 'grid' && <DeltaGrid key={item.title + item.source} result={item.result} />}
        {item.result && tab === 'chart' && <ChartStudio key={item.title + item.source} result={item.result} />}
        {tab === 'lineage' && (
          <div className="space-y-3">
            {item.lineage ? (
              <div className="rounded-2xl border border-white/10 bg-slate-900/65 p-4 backdrop-blur-xl">
                <LineageGraph lineage={item.lineage} />
                <div className="mt-3 grid grid-cols-3 gap-2 font-mono text-[10.5px]">
                  <div className="rounded-lg bg-white/[0.03] p-2"><div className="text-slate-400">statement_id</div><div className="truncate text-slate-200" title={item.lineage.statement_id ?? ''}>{item.lineage.statement_id ?? '—'}</div></div>
                  <div className="rounded-lg bg-white/[0.03] p-2"><div className="text-slate-400">runtime</div><div className="text-slate-200">{item.lineage.runtime_ms} ms</div></div>
                  <div className="rounded-lg bg-white/[0.03] p-2"><div className="text-slate-400">bytes scanned</div><div className="text-slate-200">{item.lineage.bytes_scanned?.toLocaleString() ?? 'n/a'}</div></div>
                </div>
              </div>
            ) : <div className="rounded-2xl border border-white/10 p-4 text-[12.5px] text-slate-400">No lineage for this answer.</div>}
            {item.sql && <div><div className="mb-1 font-mono text-[10.5px] text-slate-400">Canvas SQL ({item.source})</div><SqlBlock sql={item.sql} /></div>}
            {item.compare.filter((c) => c.sql && c.sql !== item.sql).map((c) => (
              <div key={c.lane}>
                <div className="mb-1 font-mono text-[10.5px]" style={{ color: c.model.color }}>{c.model.name} vs canvas SQL (± = differs)</div>
                <SqlBlock sql={c.sql} compareTo={item.sql} />
              </div>
            ))}
            {!lead && <div className="text-[12px] text-slate-400">Ask a data question to compare SQL across models.</div>}
          </div>
        )}
      </div>
    </div>
  )
}
