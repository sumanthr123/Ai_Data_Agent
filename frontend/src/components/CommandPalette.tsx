import { AnimatePresence, motion } from 'framer-motion'
import { Bot, CornerDownLeft, Database, PanelLeft, PanelRight, Search, Swords, Telescope, Trash2, Zap } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { cn, spring } from '../lib/cn'

export interface PaletteCommand {
  id: string
  group: 'Models' | 'Modes' | 'Tables' | 'Actions'
  label: string
  hint?: string
  icon: typeof Bot
  run: () => void
}

export const paletteIcons = { Bot, Database, PanelLeft, PanelRight, Swords, Telescope, Trash2, Zap }

export function CommandPalette({ open, onClose, commands }: { open: boolean; onClose: () => void; commands: PaletteCommand[] }) {
  const [query, setQuery] = useState('')
  const [index, setIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const results = useMemo(() => {
    const q = query.toLowerCase().trim()
    return commands.filter((c) => !q || `${c.group} ${c.label} ${c.hint ?? ''}`.toLowerCase().includes(q)).slice(0, 14)
  }, [commands, query])

  useEffect(() => {
    if (open) {
      setQuery('')
      setIndex(0)
      setTimeout(() => inputRef.current?.focus(), 30)
    }
  }, [open])

  const run = (c: PaletteCommand | undefined) => {
    if (!c) return
    c.run()
    onClose()
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-[70] flex items-start justify-center bg-black/50 pt-[14vh] backdrop-blur-sm"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={onClose}>
          <motion.div role="dialog" aria-label="Command palette" onMouseDown={(e) => e.stopPropagation()}
            initial={{ opacity: 0, y: -12, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -12, scale: 0.97 }} transition={spring}
            className="glass w-full max-w-xl overflow-hidden rounded-2xl shadow-2xl shadow-black/70">
            <div className="flex items-center gap-3 border-b border-white/[0.06] px-4 py-3">
              <Search className="h-4 w-4 text-slate-400" />
              <input
                ref={inputRef}
                value={query}
                onChange={(e) => { setQuery(e.target.value); setIndex(0) }}
                onKeyDown={(e) => {
                  if (e.key === 'ArrowDown') { e.preventDefault(); setIndex((i) => Math.min(i + 1, results.length - 1)) }
                  if (e.key === 'ArrowUp') { e.preventDefault(); setIndex((i) => Math.max(i - 1, 0)) }
                  if (e.key === 'Enter') run(results[index])
                  if (e.key === 'Escape') onClose()
                }}
                placeholder="Switch models, search tables, toggle Arena…"
                className="w-full bg-transparent text-[14px] text-white placeholder:text-slate-400 focus:outline-none"
              />
              <kbd className="rounded border border-white/10 px-1.5 font-mono text-[10px] text-slate-400">esc</kbd>
            </div>
            <ul className="max-h-[50vh] overflow-y-auto p-1.5">
              {results.length === 0 && <li className="px-3 py-6 text-center text-[13px] text-slate-400">No matching commands</li>}
              {results.map((c, i) => {
                const Icon = c.icon
                const showGroup = i === 0 || results[i - 1].group !== c.group
                return (
                  <li key={c.id}>
                    {showGroup && <div className="px-3 pb-1 pt-2 font-mono text-[10px] uppercase tracking-widest text-slate-400">{c.group}</div>}
                    <button type="button" onMouseEnter={() => setIndex(i)} onClick={() => run(c)}
                      className={cn('flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-[13px]', i === index ? 'bg-blue-500/15 text-white' : 'text-slate-300')}>
                      <Icon className="h-4 w-4 text-cyan-300" />
                      <span className="flex-1">{c.label}</span>
                      {c.hint && <span className="font-mono text-[11px] text-slate-400">{c.hint}</span>}
                      {i === index && <CornerDownLeft className="h-3.5 w-3.5 text-slate-400" />}
                    </button>
                  </li>
                )
              })}
            </ul>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
