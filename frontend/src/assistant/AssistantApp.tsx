import { ArrowLeft, Menu, Monitor, Moon, PanelLeft, PanelRight, SquarePen, Sun, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { cn } from '../lib/cn'
import { useTheme } from '../theme'
import { AnswerCard, type DatasetShape, type TurnAction } from './AnswerCard'
import { getIdentity, listDatasets, listModels } from './api'
import { Composer, datasetLabel, type Mode } from './Composer'
import { DatasetPanel } from './DatasetPanel'
import { EvidenceDrawer } from './EvidenceDrawer'
import { humanize, isMeasure, isTimeLike } from './format'
import { usePins } from './pins'
import type { Dataset, Identity, ModelOption, Turn } from './types'
import { useUpload } from './upload'
import { useAssistant } from './useAssistant'

const MODEL_KEY = 'assistant.model'
const COACH_KEY = 'assistant.coach.v1'
const RAIL_KEY = 'assistant.rail'
const MODE_KEY = 'assistant.mode'

interface Topic { label: string; questions: string[] }

/** Topic pills and their example questions, from the selected datasets' real columns and profiles; nothing is hard-coded. */
function topics(datasets: Dataset[]): Topic[] {
  const out: Topic[] = []
  const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
  for (const d of datasets) {
    const cols = d.profile?.columns ?? []
    const measures = cols.filter((c) => isMeasure(c.name, c.type) && !isTimeLike(c.name, c.type)).map((c) => c.name)
    const dims = cols.filter((c) => /string/i.test(c.type) && (c.distinct_approx ?? 0) >= 2 && (c.distinct_approx ?? 0) <= 25).map((c) => c.name)
    const names = cols.filter((c) => /string/i.test(c.type) && /name/i.test(c.name) && (c.distinct_approx ?? 0) > 25).map((c) => c.name)
    const m = measures.find((x) => /sales|revenue|amount|total/i.test(x)) ?? measures[0]
    const year = d.profile?.date_range?.[1]?.slice(0, 4)
    if (m && dims.length) out.push({ label: cap(humanize(m)), questions: dims.slice(0, 3).map((dim) => `What were total ${humanize(m)} by ${humanize(dim)}${year ? ` in ${year}` : ''}?`) })
    if (m && d.date_column && year) out.push({ label: 'Trends', questions: [`How did total ${humanize(m)} change by month in ${year}?`, `Which month in ${year} had the highest ${humanize(m)}?`] })
    if (m && names[0]) {
      const who = humanize(names[0]).replace(/ name$/, '')
      out.push({ label: cap(`${who}s`), questions: [`Who are the top 5 ${who}s by ${humanize(m)}?`, `How many distinct ${who}s are there${dims[0] ? ` by ${humanize(dims[0])}` : ''}?`] })
    }
    out.push({ label: 'Data quality', questions: [`Summarize ${datasetLabel(d)}: rows, columns, missing values and duplicates`] })
  }
  return out.slice(0, 5)
}

function readLocal(key: string): string | null {
  try { return localStorage.getItem(key) } catch (err) { console.warn(`${key} unavailable`, err); return null }
}
function writeLocal(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch (err) { console.warn(`${key} not saved; it lasts for this session`, err) }
}

const greeting = () => { const h = new Date().getHours(); return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening' }

/** The product mark: an original monogram (three rising bars), not anyone else's logo. */
function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden>
      <rect x="1" y="1" width="22" height="22" rx="6" fill="var(--brand)" />
      <rect x="6" y="12" width="3" height="6" rx="1" fill="var(--on-brand)" /><rect x="10.5" y="9" width="3" height="9" rx="1" fill="var(--on-brand)" />
      <rect x="15" y="6" width="3" height="12" rx="1" fill="var(--on-brand)" />
    </svg>
  )
}

export default function AssistantApp() {
  const theme = useTheme()
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)
  const defaults = useMemo(() => datasets.filter((d) => d.kind === 'shared').slice(0, 1).map((d) => d.dataset), [datasets])
  const a = useAssistant(defaults)
  const pins = usePins()
  const pinnedIds = useMemo(() => new Set(pins.pins.map((p) => p.id)), [pins.pins])
  const [draft, setDraft] = useState('')
  const [navOpen, setNavOpen] = useState(false)
  const [rail, setRail] = useState(() => readLocal(RAIL_KEY) === 'collapsed')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [evidenceId, setEvidenceId] = useState<string | null>(null)
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [identityError, setIdentityError] = useState<string | null>(null)
  const [models, setModels] = useState<ModelOption[]>([])
  const [modelsError, setModelsError] = useState<string | null>(null)
  const [model, setModel] = useState<string | null>(() => readLocal(MODEL_KEY))
  const [mode, setModeState] = useState<Mode>(() => (readLocal(MODE_KEY) === 'deep' ? 'deep' : 'quick'))
  const [coach, setCoach] = useState(() => readLocal(COACH_KEY) === null)
  const [topic, setTopic] = useState<Topic | null>(null)
  const [status, setStatus] = useState('')
  const feed = useRef<HTMLDivElement>(null)
  const box = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    listModels().then(setModels).catch((err: Error) => { setModels([]); setModelsError(err.message) })
    getIdentity().then(setIdentity).catch((err: Error) => setIdentityError(err.message))
  }, [])
  const chosen = model && (!models.length || models.some((m) => m.id === model && m.available)) ? model : null
  const pickModel = (id: string) => { setModel(id || null); writeLocal(MODEL_KEY, id || null) }
  const setMode = (m: Mode) => { setModeState(m); writeLocal(MODE_KEY, m) }
  const toggleRail = useCallback(() => setRail((r) => { writeLocal(RAIL_KEY, r ? null : 'collapsed'); return !r }), [])

  const refresh = useCallback(async (select?: string) => {
    try {
      const list = await listDatasets()
      setDatasets(list)
      setLoadError(null)
      if (select) a.setDatasets([...new Set([...(a.active?.datasets ?? defaults), select])])
    } catch (err) {
      setLoadError((err as Error).message)
    } finally {
      setLoaded(true)
    }
  }, [a, defaults])
  useEffect(() => { refresh() }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const upload = useUpload(a.activeId ?? 'unsorted', refresh)

  const visible = new Set(datasets.map((d) => d.dataset))
  const saved = (a.active?.datasets ?? defaults).filter((d) => visible.has(d))
  const selected = saved.length ? saved : defaults
  const usable = selected.length ? selected : undefined
  const chosenSets = datasets.filter((d) => selected.includes(d.dataset))
  const turns = a.active?.turns ?? []
  const home = turns.length === 0
  const evidenceTurn = turns.find((t) => t.id === evidenceId) ?? [...turns].reverse().find((t) => t.response) ?? null
  const shape = useMemo<DatasetShape>(() => ({
    columns: chosenSets.flatMap((d) => (d.profile?.columns ?? []).map((c) => ({ name: c.name, type: c.type, distinct: c.distinct_approx }))),
    dateColumn: chosenSets.find((d) => d.date_column)?.date_column ?? null,
  }), [chosenSets.map((d) => d.dataset).join()])  // eslint-disable-line react-hooks/exhaustive-deps

  const announce = useCallback((text: string) => { setStatus(''); requestAnimationFrame(() => setStatus(text)) }, [])
  const wasBusy = useRef(false)
  useEffect(() => {
    if (a.busy && !wasBusy.current) announce('Answer started')
    if (!a.busy && wasBusy.current) {
      const last = a.active?.turns.at(-1)
      announce(last?.cancelled ? 'Stopped' : last?.error ? `Error: ${last.error}` : last?.response?.status === 'ERROR' ? `Error: ${last.response.answer}` : 'Answer ready')
      box.current?.focus()
    }
    wasBusy.current = a.busy
  }, [a.busy, a.active, announce])
  useEffect(() => { feed.current?.scrollTo({ top: feed.current.scrollHeight, behavior: 'smooth' }) }, [turns.length, turns.at(-1)?.response])

  const submit = (text = draft) => {
    if (!text.trim() || a.busy) return
    a.ask(text, mode === 'deep', usable, chosen)
    setDraft('')
    setTopic(null)
    box.current?.focus()
  }
  const latest = useRef({ submit, ask: a.ask, usable, chosen, pin: pins.toggle })
  latest.current = { submit, ask: a.ask, usable, chosen, pin: pins.toggle }
  const onTurnAction = useCallback((turn: Turn, action: TurnAction) => {
    const l = latest.current
    if (action.type === 'details') { setEvidenceId(turn.id); setDrawerOpen(true) }
    else if (action.type === 'retry') l.submit(turn.question)
    else if (action.type === 'council') l.ask(turn.question, true, l.usable, l.chosen)
    else if (action.type === 'ask') l.submit(action.text)
    else if (action.type === 'pin') l.pin(turn)
    else if (action.type === 'prefill') { setDraft(action.text); requestAnimationFrame(() => box.current?.focus()) }
    else box.current?.focus()
  }, [])
  const newChat = useCallback(() => { a.start(selected.length ? selected : defaults); setNavOpen(false); setTopic(null); box.current?.focus() }, [a, selected, defaults])

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey
      if (mod && e.shiftKey && e.key.toLowerCase() === 's') { e.preventDefault(); toggleRail(); return }
      if (mod && e.key.toLowerCase() === 'k') { e.preventDefault(); newChat(); return }
      if (e.key !== 'Escape') return
      if (a.busy) { a.cancel(); return }
      setNavOpen(false)
      if (window.innerWidth < 1280) setDrawerOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [a, newChat, toggleRail])

  const onComposerKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit() }
    if (e.key === 'ArrowUp' && !draft) {
      const last = turns.at(-1)?.question
      if (last) { e.preventDefault(); setDraft(last) }
    }
  }
  const pending = a.active?.state?.pending_clarification
  useEffect(() => { if (pending) box.current?.focus() }, [pending])
  const pills = topics(chosenSets)
  const dismissCoach = () => { setCoach(false); writeLocal(COACH_KEY, 'seen') }
  const ThemeIcon = theme.pref === 'system' ? Monitor : theme.pref === 'light' ? Sun : Moon
  const lastChat = a.conversations.find((c) => c.id !== a.activeId && c.turns.length)
  const noAccess = loaded && !loadError && datasets.length === 0

  const composer = (
    <Composer boxRef={box} draft={draft} setDraft={setDraft} onSubmit={() => submit()} onKeyDown={onComposerKey} busy={a.busy} onStop={a.cancel}
      pending={pending} loaded={loaded} home={home} datasets={datasets} selected={selected} defaults={defaults} onSelect={a.setDatasets}
      mode={mode} setMode={setMode} models={models} chosen={chosen} pickModel={pickModel}
      upload={upload.state} onUpload={upload.send} onResetUpload={upload.reset} />
  )

  const sidebar = (collapsed: boolean) => (
    <div className="flex h-full flex-col">
      <div className={cn('flex items-center gap-2 px-3 pb-2 pt-3', collapsed && 'flex-col px-2')}>
        <Mark className="h-7 w-7 shrink-0" />
        {!collapsed && <span className="font-display text-[17px] text-fg">AI Data Assistant</span>}
        <button type="button" onClick={toggleRail} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} title="Ctrl/Cmd+Shift+S"
          className={cn('hidden rounded-md p-1.5 text-fg-3 hover:bg-bubble hover:text-fg lg:block', !collapsed && 'ml-auto')}><PanelLeft className="h-4 w-4" /></button>
      </div>
      <div className={cn('px-3', collapsed && 'px-2')}>
        <button type="button" onClick={newChat} title="New chat (Ctrl/Cmd+K)" aria-label="New chat"
          className={cn('flex min-h-9 w-full items-center gap-2 rounded-lg text-[14px] font-medium text-fg hover:bg-bubble', collapsed ? 'justify-center' : 'px-2.5')}>
          <SquarePen className="h-4 w-4 text-brand" aria-hidden />{!collapsed && 'New chat'}
        </button>
      </div>
      {!collapsed && (
        <div className="min-h-0 flex-1">
          <DatasetPanel datasets={datasets} selected={selected} onSelect={a.setDatasets} onDatasetsChanged={refresh}
            conversations={a.conversations} activeId={a.activeId} onOpen={(id) => { a.setActiveId(id); setNavOpen(false) }}
            onDelete={a.remove} onRename={a.rename} pins={pins.pins} onRemovePin={pins.remove}
            onRunPin={(p) => { const keep = p.datasets.filter((d) => visible.has(d)); a.ask(p.question, false, keep.length ? keep : defaults, chosen, true); setNavOpen(false) }} />
        </div>
      )}
      <div className={cn('mt-auto border-t border-line p-3 text-[12.5px]', collapsed && 'p-2')}>
        {!collapsed && (
          <p className="mb-1.5 text-fg-2" title={identity?.disclosure || undefined}>
            {identityError ? <span className="text-warn">Identity unknown: {identityError}</span>
              : identity ? <><span className="block truncate text-fg">{identity.user ?? 'Signed in'}</span>
                <span className="text-fg-3">{identity.mode === 'user' ? 'Querying as you' : "Querying as the app's service principal"}</span></>
              : 'Checking identity…'}
          </p>
        )}
        <button type="button" onClick={theme.cycle} aria-label={`Theme: ${theme.pref}. Change theme`}
          className={cn('inline-flex min-h-7 items-center gap-1.5 rounded-md px-1.5 text-fg-2 hover:bg-bubble hover:text-fg', collapsed && 'w-full justify-center')}>
          <ThemeIcon className="h-4 w-4" aria-hidden />{!collapsed && <span className="capitalize">Theme: {theme.pref}</span>}
        </button>
      </div>
    </div>
  )

  return (
    <div className="flex h-full bg-bg text-fg">
      <div role="status" aria-live="polite" className="sr-only">{status}</div>
      <aside className={cn('hidden shrink-0 bg-surface-2 lg:block', rail ? 'w-14' : 'w-[260px]')} aria-label="Sidebar">{sidebar(rail)}</aside>
      {navOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Sidebar">
          <div className="absolute inset-0 bg-black/40" onClick={() => setNavOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-[85%] max-w-[300px] bg-surface-2">
            <button type="button" onClick={() => setNavOpen(false)} aria-label="Close sidebar" className="absolute right-2 top-2 z-10 rounded-md p-1.5 text-fg-2 hover:bg-bubble"><X className="h-4 w-4" /></button>
            {sidebar(false)}
          </div>
        </div>
      )}

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 px-3 py-2">
          <button type="button" className="rounded-md p-1.5 text-fg-2 hover:bg-surface-2 lg:hidden" onClick={() => setNavOpen(true)} aria-label="Open sidebar"><Menu className="h-5 w-5" /></button>
          {!home && <h1 className="truncate text-[14px] font-medium text-fg-2">{a.active?.title}</h1>}
          {home && <h1 className="sr-only">AI Data Assistant</h1>}
          <div className="ml-auto flex items-center gap-1">
            <button type="button" className="rounded-md p-1.5 text-fg-2 hover:bg-surface-2 lg:hidden" onClick={newChat} aria-label="New chat"><SquarePen className="h-5 w-5" /></button>
            {!home && <button type="button" onClick={() => setDrawerOpen((o) => !o)} aria-pressed={drawerOpen} aria-label="Toggle details panel"
              className="rounded-md p-1.5 text-fg-2 hover:bg-surface-2"><PanelRight className="h-5 w-5" /></button>}
          </div>
        </header>

        {home ? (
          <div className="flex min-h-0 flex-1 flex-col items-center overflow-y-auto px-4 pb-8 pt-[12vh] sm:pt-[18vh]">
            <div className="reveal w-full max-w-[720px]">
              {!loaded ? (
                <div className="mb-6 space-y-2" aria-hidden><div className="skeleton mx-auto h-10 w-72 rounded-md" /><div className="skeleton mx-auto h-4 w-56 rounded" /></div>
              ) : (
                <div className="mb-6 text-center">
                  <h2 className="flex items-center justify-center gap-3 font-display text-[28px] font-normal tracking-tight text-fg sm:text-[40px]">
                    <Mark className="h-7 w-7 sm:h-9 sm:w-9" />{greeting()}
                  </h2>
                  {chosenSets.length > 0 && <p className="mt-1.5 text-[15px] text-fg-2">Ask anything about {chosenSets.map(datasetLabel).join(', ')}.</p>}
                </div>
              )}
              {loadError && (
                <p role="alert" className="mb-3 rounded-xl border border-err/40 bg-err/5 px-3 py-2 text-[13px] text-err">
                  Can't reach the data service: {loadError} <button type="button" className="ml-1 underline" onClick={() => refresh()}>Retry</button>
                </p>
              )}
              {modelsError && <p role="alert" className="mb-3 rounded-xl border border-warn/40 bg-warn/5 px-3 py-2 text-[13px] text-warn">The model list didn't load, so answers use Auto: {modelsError}</p>}
              {noAccess ? (
                <div className="rounded-[20px] border border-line bg-surface p-5 text-center">
                  <p className="text-[15px] text-fg">You don't have access to any data sources yet.</p>
                  <p className="mt-1 text-[13px] text-fg-2">Access is managed in Unity Catalog. Ask the data owner to grant you a dataset, or attach your own file with +.</p>
                  {identity?.user && <button type="button" onClick={() => navigator.clipboard.writeText(identity.user ?? '').then(() => announce('User ID copied'), (err: Error) => announce(`Copy failed: ${err.message}`))}
                    className="mt-3 min-h-8 rounded-lg border border-line-strong px-3 text-[13px] text-fg hover:bg-surface-2">Copy my user ID</button>}
                  <div className="mt-4 text-left">{composer}</div>
                </div>
              ) : composer}
              {lastChat && loaded && (
                <p className="mt-4 text-center text-[13px]"><button type="button" onClick={() => a.setActiveId(lastChat.id)} className="text-fg-2 underline-offset-2 hover:text-fg hover:underline">Continue: {lastChat.title}</button></p>
              )}
              {!noAccess && loaded && pills.length > 0 && (
                <div className="mt-5">
                  {topic ? (
                    <div className="mx-auto max-w-[600px]">
                      <button type="button" onClick={() => setTopic(null)} className="mb-1 inline-flex min-h-7 items-center gap-1 rounded-md px-1.5 text-[13px] text-fg-2 hover:text-fg"><ArrowLeft className="h-3.5 w-3.5" aria-hidden /> {topic.label}</button>
                      <ul className="divide-y divide-[var(--border)] rounded-xl border border-line bg-surface">
                        {topic.questions.map((q) => (
                          <li key={q}><button type="button" onClick={() => { setDraft(q); requestAnimationFrame(() => box.current?.focus()) }}
                            className="block min-h-10 w-full px-3.5 py-2 text-left text-[14px] text-fg hover:bg-surface-2">{q}</button></li>
                        ))}
                      </ul>
                    </div>
                  ) : (
                    <div className="flex gap-2 overflow-x-auto pb-1 sm:flex-wrap sm:justify-center" role="list" aria-label="Topics">
                      {pills.map((p) => (
                        <button key={p.label} type="button" role="listitem" onClick={() => setTopic(p)}
                          className="min-h-9 shrink-0 rounded-full border border-line px-4 text-[14px] text-fg-2 hover:border-line-strong hover:text-fg">{p.label}</button>
                      ))}
                    </div>
                  )}
                </div>
              )}
              {coach && loaded && !noAccess && (
                <div className="mx-auto mt-6 max-w-[600px] rounded-xl border border-line bg-surface p-3.5 text-[13px]">
                  <p className="font-medium text-fg">Three things to know</p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-5 text-fg-2">
                    <li>Answers come from {chosenSets.length ? chosenSets.map(datasetLabel).join(', ') : 'your data sources'}, and a second model checks each one.</li>
                    <li>Open "How I got this" to see the SQL and sources.</li>
                    <li>Rate answers with the thumbs; Deep analysis asks independent models to agree.</li>
                  </ul>
                  <button type="button" onClick={dismissCoach} className="mt-2 min-h-6 text-[12.5px] text-brand hover:underline">Got it</button>
                </div>
              )}
            </div>
          </div>
        ) : (
          <>
            <div ref={feed} role="log" aria-live="off" aria-label="Conversation" className="min-h-0 flex-1 overflow-y-auto">
              <div className="mx-auto max-w-[760px] space-y-10 px-4 pb-6 pt-2">
                {loadError && <p role="alert" className="rounded-xl border border-err/40 bg-err/5 p-3 text-[13px] text-err">Can't reach the data service: {loadError} <button type="button" className="underline" onClick={() => refresh()}>Retry</button></p>}
                {turns.map((t, i) => (
                  <AnswerCard key={t.id} turn={t} live={a.busy && i === turns.length - 1} theme={theme.resolved} shape={shape} pinned={pinnedIds.has(t.id)} onAction={onTurnAction} />
                ))}
              </div>
            </div>
            <div className="relative px-4 pb-3">
              <div className="pointer-events-none absolute inset-x-0 -top-8 h-8 bg-gradient-to-t from-[var(--bg)] to-transparent" aria-hidden />
              <div className="mx-auto max-w-[760px]">{composer}</div>
            </div>
          </>
        )}
      </main>

      <div className={cn('hidden w-[400px] shrink-0 border-l border-line bg-surface', drawerOpen && !home && 'xl:block')}>
        <EvidenceDrawer turn={evidenceTurn} onClose={() => setDrawerOpen(false)} />
      </div>
      {drawerOpen && !home && (
        <div className="fixed inset-0 z-40 xl:hidden" role="dialog" aria-modal="true" aria-label="Details">
          <div className="absolute inset-0 bg-black/40" onClick={() => setDrawerOpen(false)} />
          <div className="absolute inset-x-0 bottom-0 max-h-[85%] overflow-auto rounded-t-2xl bg-surface md:inset-y-0 md:left-auto md:right-0 md:max-h-none md:w-full md:max-w-md md:rounded-none md:border-l md:border-line">
            <EvidenceDrawer turn={evidenceTurn} onClose={() => setDrawerOpen(false)} />
          </div>
        </div>
      )}
    </div>
  )
}
