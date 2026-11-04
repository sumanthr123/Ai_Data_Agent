import { AnimatePresence, motion } from 'framer-motion'
import { ChevronRight, Database, Search, Table2 } from 'lucide-react'
import { useState } from 'react'
import { cn, spring } from '../lib/cn'
import type { CatalogTree, Layer, TableNode } from '../types/consensus'

export const layerDot: Record<Layer, string> = {
  gold: 'bg-emerald-400 shadow-[0_0_8px_#10b981]',
  silver: 'bg-amber-400 shadow-[0_0_8px_#f59e0b]',
  bronze: 'bg-orange-600 shadow-[0_0_8px_#ea580c]',
  other: 'bg-slate-500',
}

export function UnityCatalogExplorer({ tree, error, onInsert }: { tree: CatalogTree | null; error: string | null; onInsert: (ref: string) => void }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [hover, setHover] = useState<{ table: TableNode; top: number } | null>(null)
  const q = query.toLowerCase()
  const isOpen = (key: string, fallback = true) => (q ? true : open[key] ?? fallback)
  const toggle = (key: string, fallback = true) => setOpen((o) => ({ ...o, [key]: !(o[key] ?? fallback) }))
  const matches = (t: TableNode) => !q || t.full_name.toLowerCase().includes(q) || t.columns.some((c) => c.name.toLowerCase().includes(q))

  return (
    <div className="flex h-full flex-col gap-3 p-3">
      <label className="flex items-center gap-2 rounded-xl border border-white/10 bg-slate-900/65 px-3 py-2 backdrop-blur-xl">
        <Search className="h-3.5 w-3.5 text-slate-400" />
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search tables & columns"
          className="w-full bg-transparent text-[13px] text-slate-200 placeholder:text-slate-400 focus:outline-none" />
      </label>
      <div className="px-1 font-mono text-[10px] uppercase tracking-widest text-slate-400">Unity Catalog · {tree?.mode ?? '…'}</div>
      {error && <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-2 text-[12px] text-rose-200">{error}</div>}
      {!tree && !error && <div className="px-2 text-[12px] text-slate-400">Loading catalog…</div>}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {tree?.catalogs.map((cat) => (
          <div key={cat.name}>
            <button type="button" onClick={() => toggle(cat.name)} className="flex w-full items-center gap-2 rounded-lg px-1.5 py-1.5 text-[13px] font-medium text-slate-200 hover:bg-white/[0.04]">
              <ChevronRight className={cn('h-3.5 w-3.5 text-slate-400 transition', isOpen(cat.name) && 'rotate-90')} />
              <Database className="h-3.5 w-3.5 text-sky-300" /> {cat.name}
            </button>
            {isOpen(cat.name) && cat.schemas.map((schema) => {
              const tables = schema.tables.filter(matches)
              if (!tables.length) return null
              const key = `${cat.name}.${schema.name}`
              return (
                <div key={key} className="pl-4">
                  <button type="button" onClick={() => toggle(key, schema.layer !== 'bronze')} className="flex w-full items-center gap-2 rounded-lg px-1.5 py-1.5 text-[12.5px] text-slate-300 hover:bg-white/[0.04]">
                    <ChevronRight className={cn('h-3.5 w-3.5 text-slate-400 transition', isOpen(key, schema.layer !== 'bronze') && 'rotate-90')} />
                    <span className={cn('h-2 w-2 rounded-full', layerDot[schema.layer])} /> {schema.name}
                    <span className="ml-auto font-mono text-[10px] text-slate-400">{tables.length}</span>
                  </button>
                  <AnimatePresence initial={false}>
                    {isOpen(key, schema.layer !== 'bronze') && (
                      <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={spring} className="overflow-hidden pl-5">
                        {tables.map((t) => (
                          <div key={t.full_name}>
                            <button type="button" onClick={() => onInsert(`@${t.full_name}`)}
                              onMouseEnter={(e) => setHover({ table: t, top: e.currentTarget.getBoundingClientRect().top })} onMouseLeave={() => setHover(null)}
                              className="group flex w-full items-center gap-2 rounded-lg px-1.5 py-1 font-mono text-[12px] text-slate-400 hover:bg-blue-500/10 hover:text-white">
                              <Table2 className="h-3.5 w-3.5 text-slate-400 group-hover:text-sky-300" /> {t.name}
                            </button>
                            {q && t.columns.filter((c) => c.name.toLowerCase().includes(q)).map((c) => (
                              <div key={c.name} className="flex justify-between pl-7 pr-1 font-mono text-[11px] text-slate-400"><span>{c.name}</span><span className="text-slate-400">{c.type}</span></div>
                            ))}
                          </div>
                        ))}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              )
            })}
          </div>
        ))}
      </div>
      <AnimatePresence>
        {hover && (
          <motion.div initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -6 }} transition={spring}
            style={{ top: Math.min(hover.top - 16, window.innerHeight - 300) }}
            className="pointer-events-none fixed left-[284px] z-50 w-80 rounded-2xl border border-white/10 bg-slate-900/90 p-4 shadow-2xl shadow-black/60 backdrop-blur-xl">
            <div className="flex items-center gap-2"><span className={cn('h-2 w-2 rounded-full', layerDot[hover.table.layer])} /><span className="font-mono text-[12px] text-white">{hover.table.full_name}</span></div>
            {hover.table.comment && <p className="mt-2 text-[12px] text-slate-400">{hover.table.comment}</p>}
            <div className="mt-3 grid grid-cols-2 gap-2 font-mono text-[11px]">
              <div className="rounded-lg bg-white/[0.03] p-2"><div className="text-slate-400">rows</div><div className="text-slate-200">{hover.table.row_count?.toLocaleString() ?? '—'}</div></div>
              <div className="rounded-lg bg-white/[0.03] p-2"><div className="text-slate-400">delta freshness</div><div className="truncate text-slate-200">{hover.table.updated_at ? (/^\d{12,}$/.test(hover.table.updated_at) ? new Date(Number(hover.table.updated_at)).toLocaleString() : hover.table.updated_at) : '—'}</div></div>
            </div>
            <div className="mt-3 space-y-0.5">
              {hover.table.columns.slice(0, 6).map((c) => <div key={c.name} className="flex justify-between font-mono text-[11px]"><span className="text-slate-300">{c.name}</span><span className="text-slate-400">{c.type}</span></div>)}
              {hover.table.columns.length > 6 && <div className="font-mono text-[10.5px] text-slate-400">+{hover.table.columns.length - 6} more columns</div>}
            </div>
            <div className="mt-3 text-[11px] text-sky-300/80">Click to add @{hover.table.full_name}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
