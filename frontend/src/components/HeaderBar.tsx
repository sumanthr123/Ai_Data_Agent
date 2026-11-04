import { PanelLeft, Search } from 'lucide-react'
import { cn } from '../lib/cn'
import type { Health, Mode } from '../types/consensus'

export function HeaderBar({ health, mode, setMode, onPalette, onToggleData, dataOpen }: {
  health: Health | null; mode: Mode; setMode: (m: Mode) => void; onPalette: () => void; onToggleData: () => void; dataOpen: boolean
}) {
  const ok = Boolean(health?.unity_catalog?.startsWith('Connected'))
  const detail = health ? `Data: ${health.unity_catalog} · Warehouse: ${health.warehouse} · Models: ${health.council.join(', ')}` : 'Checking connection…'
  return (
    <header className="relative z-30 flex h-14 shrink-0 items-center gap-3 border-b border-white/[0.07] bg-[#05070B]/80 px-4 backdrop-blur-xl">
      <button type="button" onClick={onToggleData} aria-pressed={dataOpen} title="Show or hide your tables"
        className={cn('flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[12.5px] transition',
          dataOpen ? 'border-sky-400/40 bg-sky-400/10 text-sky-100' : 'border-white/10 text-slate-400 hover:text-white')}>
        <PanelLeft className="h-4 w-4" /> Tables
      </button>
      <div className="flex items-center gap-2.5">
        <div className="h-7 w-7 rounded-lg bg-gradient-to-br from-sky-400 via-blue-500 to-indigo-600" />
        <div className="text-[15px] font-semibold tracking-tight text-white">AI Data Agent</div>
      </div>
      <span title={detail} className="ml-2 hidden items-center gap-1.5 text-[12px] text-slate-400 sm:flex">
        <span className={cn('h-2 w-2 rounded-full', health ? (ok ? 'bg-emerald-400' : 'bg-amber-400') : 'bg-slate-600')} />
        {health ? (ok ? 'Connected to your data' : 'Data connection issue') : 'Connecting…'}
      </span>
      <div className="ml-auto flex items-center gap-2">
        <div className="flex rounded-lg border border-white/10 bg-black/30 p-0.5 text-[12px]" role="radiogroup" aria-label="Data source">
          {(['live', 'demo'] as const).map((m) => (
            <button key={m} type="button" role="radio" aria-checked={mode === m} onClick={() => setMode(m)}
              title={m === 'live' ? 'Real answers from your Databricks data' : 'Pre-recorded sample answers, no real data'}
              className={cn('rounded-md px-3 py-1', mode === m ? 'bg-white/10 text-white' : 'text-slate-400 hover:text-slate-300')}>
              {m === 'live' ? 'Live' : 'Demo'}
            </button>
          ))}
        </div>
        <button type="button" onClick={onPalette} title="Commands (⌘K)" className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-[12px] text-slate-400 hover:text-white">
          <Search className="h-3.5 w-3.5" /> ⌘K
        </button>
      </div>
    </header>
  )
}
