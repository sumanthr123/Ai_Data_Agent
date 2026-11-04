import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, CloudSun, Globe2, Lightbulb, TrendingUp, UploadCloud, Users } from 'lucide-react'
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { FileChip, uploadFile } from './components/Attachments'
import { ChatSidebar } from './components/ChatSidebar'
import { CommandPalette, paletteIcons, type PaletteCommand } from './components/CommandPalette'
import { HeaderBar } from './components/HeaderBar'
import { ModelComparisonMatrix } from './components/ModelComparisonMatrix'
import { OmniPromptBar } from './components/OmniPromptBar'
import { ParallelRaceTrace } from './components/ParallelRaceTrace'
import { ThinkingStatus } from './components/ThinkingStatus'
import { ToastProvider } from './components/Toast'
import { UnityCatalogExplorer } from './components/UnityCatalogExplorer'
import { VerifiedWinnerCard } from './components/VerifiedWinnerCard'
import { useConsensusStream } from './hooks/useConsensusStream'
import { cn, spring } from './lib/cn'
import type { Attachment, CanvasItem, Mode, Turn } from './types/consensus'

// Charts and the data grid load only when the canvas first opens.
const DataLineageCanvas = lazy(() => import('./components/DataLineageCanvas').then((m) => ({ default: m.DataLineageCanvas })))

const STARTERS: Record<Mode, { icon: typeof Globe2; title: string; prompt: string }[]> = {
  demo: [
    { icon: TrendingUp, title: 'ARR trajectory', prompt: 'Show monthly ARR growth for 2025' },
    { icon: Globe2, title: 'Regional revenue', prompt: 'Revenue by region' },
    { icon: AlertTriangle, title: 'Anomaly root-cause', prompt: 'Why did orders spike in late November?' },
    { icon: Lightbulb, title: 'Ask anything', prompt: 'What is a data lakehouse?' },
  ],
  live: [
    { icon: Globe2, title: 'Regional performance', prompt: 'What are total sales and profit by region?' },
    { icon: AlertTriangle, title: 'Loss makers', prompt: 'Which 5 sub-categories lost the most money?' },
    { icon: Users, title: 'Top customers', prompt: 'Who are the top 5 customers by sales?' },
    { icon: CloudSun, title: 'Live information', prompt: 'What is the weather in Austin, TX today?' },
  ],
}

function Hero({ onPick, mode }: { onPick: (p: string) => void; mode: Mode }) {
  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={spring} className="mx-auto flex max-w-2xl flex-col items-center px-6 pb-48 pt-16 text-center">
      <div className="h-12 w-12 rounded-2xl bg-gradient-to-br from-sky-400 via-blue-500 to-indigo-600 shadow-[0_0_40px_-6px_rgba(59,130,246,0.8)]" />
      <h1 className="mt-6 text-3xl font-semibold tracking-tight text-white">What would you like to know?</h1>
      <p className="mt-3 text-[15px] text-slate-400">
        {mode === 'live'
          ? 'Ask about your Superstore sales data, today\'s news or weather, or any general question. Several AI models answer and check each other.'
          : 'Demo mode shows pre-recorded sample answers. Switch to Live at the top right for real answers.'}
      </p>
      <div className="mt-8 grid w-full grid-cols-1 gap-2.5 sm:grid-cols-2">
        {STARTERS[mode].map(({ icon: Icon, title, prompt }) => (
          <button key={title} type="button" onClick={() => onPick(prompt)}
            className="flex items-start gap-3 rounded-xl border border-white/10 bg-slate-900/60 p-4 text-left transition hover:border-blue-400/40 hover:bg-slate-900">
            <Icon className="mt-0.5 h-4 w-4 shrink-0 text-sky-300" />
            <span><span className="block text-[13.5px] font-medium text-white">{title}</span><span className="text-[13px] text-slate-400">{prompt}</span></span>
          </button>
        ))}
      </div>
    </motion.div>
  )
}

/** The user's message; long pastes (code, logs) collapse to a few lines with a toggle. */
function UserMessage({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  const lines = text.split('\n')
  const long = lines.length > 8 || text.length > 600
  return (
    <div className="max-w-[80%] rounded-2xl rounded-br-md border border-white/10 bg-gradient-to-br from-blue-600/25 to-indigo-700/20 px-4 py-2.5 text-[14.5px] text-white">
      <div className={cn('whitespace-pre-wrap break-words', long && 'font-mono text-[12.5px]', long && !open && 'max-h-40 overflow-hidden [mask-image:linear-gradient(to_bottom,black_60%,transparent)]')}>
        {text}
      </div>
      {long && (
        <button type="button" onClick={() => setOpen((o) => !o)} className="mt-1.5 text-[12px] text-sky-300 hover:text-sky-200">
          {open ? 'Show less' : `Show all (${lines.length.toLocaleString()} lines)`}
        </button>
      )}
    </div>
  )
}

function canvasFor(turn: Turn): CanvasItem | null {
  const c = turn.consensus
  if (!c) return null
  const winner = turn.lanes.find((l) => l.lane === c.winner_lane)
  return { title: turn.question, source: `Consensus · ${winner?.model.name ?? ''} · ${c.reliability.toFixed(1)}%`, result: c.result, sql: c.sql, kpis: c.kpis,
    lineage: c.lineage, compare: turn.lanes.map((l) => l.result).filter((r): r is NonNullable<typeof r> => Boolean(r)) }
}

export default function App() {
  const s = useConsensusStream()
  const [text, setText] = useState('')
  const [pills, setPills] = useState<string[]>([])
  const [canvas, setCanvas] = useState<CanvasItem | null>(null)
  const [palette, setPalette] = useState(false)
  const [tablesOpen, setTablesOpen] = useState(false)
  const [files, setFiles] = useState<Attachment[]>([])
  const end = useRef<HTMLDivElement>(null)
  const last = s.turns.at(-1)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette((p) => !p) } }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [s.turns.length, last?.lanes.length, last?.consensus, last?.arbiter])
  useEffect(() => { setCanvas(null) }, [s.mode])

  const ready = files.filter((f) => f.status === 'ready')
  const uploading = files.some((f) => f.status === 'uploading')

  const send = (prompt?: string) => {
    if (uploading) return
    const typed = prompt ?? [...pills, text].filter(Boolean).join(' ')
    const question = typed.trim() || (ready.length ? `Analyze the attached file${ready.length > 1 ? 's' : ''} and summarize the key points.` : '')
    if (!question) return
    void s.ask(question, ready)
    setText('')
    setPills([])
    setFiles([])
  }

  const addFiles = (list: FileList | File[]) => {
    const picked = [...list].slice(0, 10)
    const pending: Attachment[] = picked.map((f) => ({ id: crypto.randomUUID(), name: f.name, size: f.size, status: 'uploading' }))
    setFiles((all) => [...all, ...pending])
    picked.forEach((file, i) => {
      const placeholder = pending[i].id
      uploadFile(file)
        .then((done) => setFiles((all) => all.map((f) => (f.id === placeholder ? done : f))))
        .catch((e: Error) => setFiles((all) => all.map((f) => (f.id === placeholder ? { ...f, status: 'error', error: e.message } : f))))
    })
  }

  // Drag files anywhere over the chat; the counter ignores enter/leave events from child elements.
  const dragDepth = useRef(0)
  const [dragging, setDragging] = useState(false)
  const hasFiles = (e: React.DragEvent) => e.dataTransfer.types.includes('Files')
  const dropProps = {
    onDragEnter: (e: React.DragEvent) => { if (hasFiles(e)) { e.preventDefault(); dragDepth.current++; setDragging(true) } },
    onDragOver: (e: React.DragEvent) => { if (hasFiles(e)) e.preventDefault() },
    onDragLeave: () => { dragDepth.current = Math.max(0, dragDepth.current - 1); if (!dragDepth.current) setDragging(false) },
    onDrop: (e: React.DragEvent) => {
      e.preventDefault()
      dragDepth.current = 0
      setDragging(false)
      if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files)
    },
  }

  const commands = useMemo<PaletteCommand[]>(() => [
    { id: 'lead-auto', group: 'Models', label: 'Lead: Auto-Router', icon: paletteIcons.Bot, run: () => s.setLead('auto') },
    ...s.leadOptions.map((m) => ({ id: `lead-${m.id}`, group: 'Models' as const, label: `Lead: ${m.name}`, hint: m.provider, icon: paletteIcons.Bot, run: () => s.setLead(m.id) })),
    { id: 'view-consensus', group: 'Modes', label: 'Consensus mode (crown best)', icon: paletteIcons.Zap, run: () => s.setView('consensus') },
    { id: 'view-arena', group: 'Modes', label: 'Arena split-screen', icon: paletteIcons.Swords, run: () => s.setView('arena') },
    { id: 'mode', group: 'Modes', label: s.mode === 'live' ? 'Switch to Simulated Demo Mode' : 'Switch to Live Databricks SDK', icon: paletteIcons.Telescope, run: () => s.setMode(s.mode === 'live' ? 'demo' : 'live') },
    ...(s.catalog?.catalogs ?? []).flatMap((c) => c.schemas.flatMap((sc) => sc.tables.map((t) => ({
      id: `t-${t.full_name}`, group: 'Tables' as const, label: `@${t.full_name}`, hint: t.row_count != null ? `${t.row_count.toLocaleString()} rows` : sc.layer,
      icon: paletteIcons.Database, run: () => setPills((p) => (p.includes(`@${t.full_name}`) ? p : [...p, `@${t.full_name}`])) })))),
    { id: 'clear', group: 'Actions', label: 'New chat', icon: paletteIcons.Trash2, run: () => { s.clear(); setCanvas(null) } },
    { id: 'canvas', group: 'Actions', label: 'Close canvas', icon: paletteIcons.PanelRight, run: () => setCanvas(null) },
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [s.leadOptions, s.mode, s.catalog])

  return (
    <ToastProvider>
      <div className="nebula-bg flex h-full flex-col">
        <HeaderBar health={s.health} mode={s.mode} setMode={s.setMode} onPalette={() => setPalette(true)} onToggleData={() => setTablesOpen((o) => !o)} dataOpen={tablesOpen} />
        <div className="relative z-10 flex min-h-0 flex-1">
          <aside className="hidden w-[248px] shrink-0 border-r border-white/[0.07] bg-[#070a10]/70 backdrop-blur-xl md:block">
            <ChatSidebar chats={s.chats} activeId={s.activeId} onSelect={(id) => { s.selectChat(id); setCanvas(null) }}
              onNew={() => { s.newChat(); setCanvas(null) }} onDelete={s.deleteChat} />
          </aside>
          {tablesOpen && (
            <aside className="w-[276px] shrink-0 border-r border-white/[0.07] bg-[#070a10]/60 backdrop-blur-xl">
              <UnityCatalogExplorer tree={s.catalog} error={s.catalogError} onInsert={(ref) => setPills((p) => (p.includes(ref) ? p : [...p, ref]))} />
            </aside>
          )}
          <main className="relative min-w-0 flex-1" {...dropProps}>
            <AnimatePresence>
              {dragging && (
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                  className="pointer-events-none absolute inset-3 z-40 flex flex-col items-center justify-center rounded-3xl border-2 border-dashed border-sky-400/60 bg-[#05070B]/85 backdrop-blur-sm">
                  <UploadCloud className="h-12 w-12 text-sky-300" />
                  <div className="mt-3 text-[18px] font-semibold text-white">Drop files to attach</div>
                  <div className="mt-1 text-[13px] text-slate-400">CSV, Excel, JSON, Parquet, PDF, Word, PowerPoint, images, code or text · up to 25 MB each</div>
                </motion.div>
              )}
            </AnimatePresence>
            <div className="h-full overflow-y-auto">
              {s.turns.length === 0 ? <Hero onPick={send} mode={s.mode} /> : (
                <div className="mx-auto max-w-5xl space-y-8 px-6 pb-56 pt-8">
                  {s.turns.map((turn, index) => {
                    const previous = s.turns[index - 1]
                    const modelName = (id?: string) => (!id || id === 'auto' ? 'Auto' : s.leadOptions.find((m) => m.id === id)?.name ?? id)
                    const switched = previous && (previous.lead ?? 'auto') !== (turn.lead ?? 'auto')
                    const matrix = <ModelComparisonMatrix key={`m-${turn.id}-${s.view}`} consensus={turn.consensus} lanes={turn.lanes} defaultOpen={s.view === 'arena'}
                      onPromote={(lane) => lane.result && setCanvas({ title: turn.question, source: `Promoted · ${lane.model.name}`, result: lane.result.result,
                        // Headline numbers belong to the consensus result; an outlier's rows differ, so it gets none.
                        sql: lane.result.sql, kpis: turn.consensus?.groups[0]?.includes(lane.lane) ? turn.consensus.kpis : [], lineage: turn.consensus?.lineage ?? null,
                        compare: turn.lanes.map((l) => l.result).filter((r): r is NonNullable<typeof r> => Boolean(r)) })} />
                    return (
                      <motion.section key={turn.id} layout initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={spring} className="space-y-4">
                        {switched && (
                          <div className="flex items-center gap-3 text-[12px] text-slate-300" role="note">
                            <span className="h-px flex-1 bg-white/10" />
                            Switched to {modelName(turn.lead)} · the conversation continues with full context
                            <span className="h-px flex-1 bg-white/10" />
                          </div>
                        )}
                        {!!turn.attachments?.length && (
                          <div className="flex flex-wrap justify-end gap-2">{turn.attachments.map((f) => <FileChip key={f.id} file={f} />)}</div>
                        )}
                        <div className="flex justify-end">
                          <UserMessage text={turn.question} />
                        </div>
                        {turn.rewritten && (
                          <div className="-mt-2 text-right text-[12px] text-slate-400">Understood as: <span className="text-slate-300">{turn.rewritten}</span></div>
                        )}
                        {!turn.consensus && !turn.error && !turn.done && <ThinkingStatus turn={turn} />}
                        {turn.error && (
                          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-[13px] text-rose-100">
                            <span className="min-w-0 flex-1">Something went wrong: {turn.error}</span>
                            {!s.busy && <button type="button" onClick={() => void s.ask(turn.question, turn.attachments ?? [])}
                              className="rounded-lg border border-rose-300/30 px-2.5 py-1 text-[12.5px] hover:bg-rose-400/10">Retry</button>}
                          </div>
                        )}
                        <AnimatePresence>
                          {turn.consensus && <VerifiedWinnerCard key={`w-${turn.id}`} question={turn.question} consensus={turn.consensus} lanes={turn.lanes} mode={turn.mode}
                            onOpenData={turn.consensus.result ? () => setCanvas(canvasFor(turn)) : undefined}
                            onRetry={s.busy ? undefined : () => void s.ask(turn.question, turn.attachments ?? [])}
                            details={<>{turn.lanes.length > 0 && <ParallelRaceTrace lanes={turn.lanes} />}{turn.lanes.length > 0 && matrix}</>} />}
                        </AnimatePresence>
                      </motion.section>
                    )
                  })}
                  <div ref={end} />
                </div>
              )}
            </div>
            <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center bg-gradient-to-t from-[#05070B] via-[#05070B]/85 to-transparent px-4 pb-5 pt-16">
              <div className="pointer-events-auto flex w-full justify-center">
                <OmniPromptBar text={text} setText={setText} pills={pills} setPills={setPills} leadOptions={s.leadOptions} lead={s.lead} setLead={s.setLead}
                  busy={s.busy} onSend={() => send()} onStop={s.stop}
                  files={files} onAddFiles={addFiles} onRemoveFile={(id) => setFiles((all) => all.filter((f) => f.id !== id))} />
              </div>
            </div>
          </main>
          <AnimatePresence initial={false}>
            {canvas && (
              <motion.aside initial={{ width: 0, opacity: 0 }} animate={{ width: 580, opacity: 1 }} exit={{ width: 0, opacity: 0 }} transition={spring}
                className="shrink-0 overflow-hidden border-l border-white/[0.07] bg-[#070a10]/70 backdrop-blur-xl">
                <div className="h-full w-[580px]"><Suspense fallback={<div className="p-6 font-mono text-[12px] text-slate-400">Loading canvas…</div>}><DataLineageCanvas item={canvas} onClose={() => setCanvas(null)} /></Suspense></div>
              </motion.aside>
            )}
          </AnimatePresence>
        </div>
        <CommandPalette open={palette} onClose={() => setPalette(false)} commands={commands} />
      </div>
    </ToastProvider>
  )
}
