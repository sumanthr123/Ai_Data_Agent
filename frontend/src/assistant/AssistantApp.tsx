import { ArrowUp, Database, Menu, Monitor, Moon, PanelRight, Square, Sun, UserRound, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { cn } from '../lib/cn'
import { useTheme } from '../theme'
import { AnswerCard, type DatasetShape, type TurnAction } from './AnswerCard'
import { getIdentity, listDatasets, listModels } from './api'
import { DatasetPanel } from './DatasetPanel'
import { EvidenceDrawer } from './EvidenceDrawer'
import { humanize, isMeasure, isTimeLike, modelLabel, relativeTime } from './format'
import type { Dataset, Identity, ModelOption, Turn } from './types'
import { usePins } from './pins'
import { useAssistant } from './useAssistant'

const MODEL_KEY = 'assistant.model'
const COACH_KEY = 'assistant.coach.v1'

/** Starter questions from the selected datasets' real columns and profiles, never hard-coded. */
function starters(datasets: Dataset[]): string[] {
  const out: string[] = []
  for (const d of datasets) {
    const cols = d.profile?.columns ?? []
    const measures = cols.filter((c) => isMeasure(c.name, c.type) && !isTimeLike(c.name, c.type)).map((c) => c.name)
    const dims = cols.filter((c) => /string/i.test(c.type) && (c.distinct_approx ?? 0) >= 2 && (c.distinct_approx ?? 0) <= 25).map((c) => c.name)
    const names = cols.filter((c) => /string/i.test(c.type) && /name/i.test(c.name) && (c.distinct_approx ?? 0) > 25).map((c) => c.name)
    const m = measures.find((x) => /sales|revenue|amount|total/i.test(x)) ?? measures[0]
    const year = d.profile?.date_range?.[1]?.slice(0, 4)
    const label = d.kind === 'upload' ? d.description.replace(/^Uploaded /, '') : humanize(d.dataset.split('.').at(-1) ?? '')
    if (m && dims[0] && year) out.push(`What were total ${humanize(m)} by ${humanize(dims[0])} in ${year}?`)
    if (m && d.date_column && year) out.push(`How did total ${humanize(m)} change by month in ${year}?`)
    if (m && names[0]) out.push(`Who are the top 5 ${humanize(names[0]).replace(/ name$/, '')}s by ${humanize(m)}?`)
    const second = measures.find((x) => x !== m)
    if (second && dims[1]) out.push(`Which ${humanize(dims[1])} has the highest ${humanize(second)}?`)
    if (!m) out.push(`Summarize ${label}: rows, columns and data quality`)
  }
  return [...new Set(out)].slice(0, 4)
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
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [scopeOpen, setScopeOpen] = useState(false)
  const [evidenceId, setEvidenceId] = useState<string | null>(null)
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [identityError, setIdentityError] = useState<string | null>(null)
  const [models, setModels] = useState<ModelOption[]>([])
  const [modelsError, setModelsError] = useState<string | null>(null)
  const [model, setModel] = useState<string | null>(() => readLocal(MODEL_KEY))
  const [coach, setCoach] = useState(() => readLocal(COACH_KEY) === null)
  const [status, setStatus] = useState('')
  const feed = useRef<HTMLDivElement>(null)
  const box = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    listModels().then(setModels).catch((err: Error) => { setModels([]); setModelsError(err.message) })
    getIdentity().then(setIdentity).catch((err: Error) => setIdentityError(err.message))
  }, [])
  // A remembered pick that's no longer offered or available falls back to Auto.
  const chosen = model && (!models.length || models.some((m) => m.id === model && m.available)) ? model : null
  const pickModel = (id: string) => { setModel(id || null); writeLocal(MODEL_KEY, id || null) }

  const refresh = useCallback(async (select?: string) => {
    try {
      const list = await listDatasets()
      setDatasets(list)
      setLoadError(null)
      setLoaded(true)
      if (select) a.setDatasets([...new Set([...(a.active?.datasets ?? defaults), select])])
    } catch (err) {
      setLoadError((err as Error).message)
      setLoaded(true)
    }
  }, [a, defaults])
  useEffect(() => { refresh() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const visible = new Set(datasets.map((d) => d.dataset))
  const saved = (a.active?.datasets ?? defaults).filter((d) => visible.has(d))
  const selected = saved.length ? saved : defaults  // a saved chat whose datasets are gone continues on the default
  const usable = selected.length ? selected : undefined  // undefined until the list loads
  const chosenSets = datasets.filter((d) => selected.includes(d.dataset))
  const turns = a.active?.turns ?? []
  const evidenceTurn = turns.find((t) => t.id === evidenceId) ?? [...turns].reverse().find((t) => t.response) ?? null
  const label = (d: Dataset) => (d.kind === 'upload' ? d.description.replace(/^Uploaded /, '') : d.dataset.split('.').at(-1) ?? d.dataset)
  const shape = useMemo<DatasetShape>(() => ({
    columns: chosenSets.flatMap((d) => (d.profile?.columns ?? []).map((c) => ({ name: c.name, type: c.type, distinct: c.distinct_approx }))),
    dateColumn: chosenSets.find((d) => d.date_column)?.date_column ?? null,
  }), [chosenSets.map((d) => d.dataset).join()])  // eslint-disable-line react-hooks/exhaustive-deps

  // Screen readers hear start, ready, stopped and errors only; streamed steps stay silent (the log is aria-live="off").
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
    a.ask(text, false, usable, chosen)
    setDraft('')
    box.current?.focus()
  }
  // Stable across renders so memoized cards don't re-render; reads the latest values through the ref.
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

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (a.busy) { a.cancel(); return }
      setNavOpen(false)
      setScopeOpen(false)
      if (window.innerWidth < 1280) setDrawerOpen(false)  // on wide screens the panel is a pane, not an overlay
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [a])

  const onComposerKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit() }
    if (e.key === 'ArrowUp' && !draft) {
      const last = turns.at(-1)?.question
      if (last) { e.preventDefault(); setDraft(last) }
    }
  }
  const pending = a.active?.state?.pending_clarification
  useEffect(() => { if (pending) box.current?.focus() }, [pending])
  const examples = starters(chosenSets)
  const dismissCoach = () => { setCoach(false); writeLocal(COACH_KEY, 'seen') }
  const ThemeIcon = theme.pref === 'system' ? Monitor : theme.pref === 'light' ? Sun : Moon

  const panel = (
    <DatasetPanel datasets={datasets} selected={selected} onSelect={a.setDatasets} onDatasetsChanged={refresh}
      conversations={a.conversations} activeId={a.activeId} onOpen={(id) => { a.setActiveId(id); setNavOpen(false) }}
      onNew={() => { a.start(selected.length ? selected : defaults); setNavOpen(false); box.current?.focus() }} onDelete={a.remove} onRename={a.rename}
      pins={pins.pins} onRemovePin={pins.remove}
      onRunPin={(p) => { a.ask(p.question, false, p.datasets.filter((d) => visible.has(d)).length ? p.datasets.filter((d) => visible.has(d)) : defaults, chosen, true); setNavOpen(false) }}
      conversationId={a.activeId ?? 'unsorted'} />
  )

  return (
    <div className="flex h-full flex-col bg-bg text-fg">
      <div role="status" aria-live="polite" className="sr-only">{status}</div>
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-surface px-3 py-2">
        <button type="button" className="rounded-md p-1.5 text-fg-2 hover:bg-surface-2 lg:hidden" onClick={() => setNavOpen(true)} aria-label="Open datasets and conversations">
          <Menu className="h-5 w-5" />
        </button>
        <h1 className="text-[15px] font-semibold tracking-tight">AI Data Assistant</h1>
        <div className="relative">
          <button type="button" onClick={() => setScopeOpen((o) => !o)} aria-expanded={scopeOpen} aria-controls="scope"
            className="inline-flex min-h-7 items-center gap-1.5 rounded-md border border-line px-2 text-[12.5px] text-fg-2 hover:border-line-strong hover:text-fg">
            <Database className="h-3.5 w-3.5" aria-hidden />
            {!loaded ? 'Loading datasets…' : chosenSets.length ? `${chosenSets.map(label).join(', ')} · ${chosenSets.length} dataset${chosenSets.length === 1 ? '' : 's'}` : 'No dataset'}
            <span className="hidden sm:inline">· What's in here</span>
          </button>
          {scopeOpen && (
            <div id="scope" className="absolute left-0 top-full z-30 mt-1 w-[min(22rem,90vw)] rounded-lg border border-line bg-surface p-3 shadow-lg">
              {chosenSets.length === 0 && <p className="text-[13px] text-fg-2">Select a dataset in the left panel.</p>}
              {chosenSets.map((d) => (
                <div key={d.dataset} className="space-y-0.5 py-1 text-[13px]">
                  <p className="font-mono text-[12.5px] text-fg">{d.dataset}</p>
                  {d.description && <p className="text-fg-2">{d.description}</p>}
                  <p className="text-fg-3">{d.profile ? `${d.profile.row_count.toLocaleString()} rows · ${d.profile.columns.length} columns` : 'Not profiled yet'} · refreshed {relativeTime(d.refreshed_at)}</p>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="ml-auto flex items-center gap-1">
          <span className="hidden items-center gap-1.5 text-[12.5px] text-fg-2 md:inline-flex" title={identity?.disclosure || undefined}>
            <UserRound className="h-4 w-4" aria-hidden />
            {identityError ? <span className="text-warn">Identity unknown: {identityError}</span>
              : identity ? <>{identity.user ? `${identity.user} · ` : ''}{identity.mode === 'user' ? 'querying as you' : "querying as the app's service principal"}</>
              : 'Checking identity…'}
          </span>
          <button type="button" onClick={theme.cycle} aria-label={`Theme: ${theme.pref}. Change theme`} title={`Theme: ${theme.pref}`}
            className="rounded-md p-1.5 text-fg-2 hover:bg-surface-2"><ThemeIcon className="h-5 w-5" /></button>
          <button type="button" onClick={() => setDrawerOpen((o) => !o)} aria-pressed={drawerOpen} aria-label="Toggle details panel"
            className="rounded-md p-1.5 text-fg-2 hover:bg-surface-2"><PanelRight className="h-5 w-5" /></button>
        </div>
      </header>
      {identity?.mode === 'service_principal' && (
        <p className="border-b border-line bg-surface-2 px-3 py-1 text-[12px] text-fg-2 md:hidden">Queries run as the app's service principal, not as you.</p>
      )}

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-72 shrink-0 border-r border-line bg-surface lg:block" aria-label="Datasets and conversations">{panel}</aside>
        {navOpen && (
          <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Datasets and conversations">
            <div className="absolute inset-0 bg-black/50" onClick={() => setNavOpen(false)} />
            <div className="absolute inset-y-0 left-0 w-[85%] max-w-sm border-r border-line bg-surface">
              <button type="button" onClick={() => setNavOpen(false)} aria-label="Close" className="absolute right-2 top-2 z-10 rounded-md p-1.5 text-fg-2 hover:bg-surface-2"><X className="h-4 w-4" /></button>
              {panel}
            </div>
          </div>
        )}

        <main className="flex min-w-0 flex-1 flex-col">
          <div ref={feed} role="log" aria-live="off" aria-label="Conversation" className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto max-w-3xl space-y-8 px-4 py-6">
              {loadError && <p role="alert" className="rounded-md border border-err/40 bg-err/5 p-3 text-[13px] text-err">Couldn't load datasets: {loadError} <button type="button" className="underline" onClick={() => refresh()}>Retry</button></p>}
              {modelsError && <p role="alert" className="rounded-md border border-warn/40 bg-warn/5 p-3 text-[13px] text-warn">Couldn't load the model list, so answers use Auto: {modelsError}</p>}
              {turns.length === 0 && (
                <section className="pt-6">
                  <h2 className="text-[24px] font-semibold tracking-tight">{chosenSets.length ? `Ask about ${chosenSets.map(label).join(", ")} in plain English.` : "Ask about your data in plain English."}</h2>
                  <p className="mt-2 max-w-xl text-[14px] text-fg-2">Every number comes from a SQL query you can inspect, and a second model reviews it before you see it.</p>
                  {coach && (
                    <div className="mt-4 rounded-lg border border-line bg-surface p-3 text-[13px]">
                      <ol className="grid gap-2 sm:grid-cols-3">
                        <li><span className="font-semibold">1. Ask</span> <span className="text-fg-2">a question, or pick one below.</span></li>
                        <li><span className="font-semibold">2. Inspect</span> <span className="text-fg-2">"How I got this" for the SQL and sources.</span></li>
                        <li><span className="font-semibold">3. Check</span> <span className="text-fg-2">with "Verify with council" when it matters.</span></li>
                      </ol>
                      <button type="button" onClick={dismissCoach} className="mt-2 min-h-6 text-[12.5px] text-brand hover:underline">Got it</button>
                    </div>
                  )}
                  {examples.length > 0 && (
                    <div className="mt-6">
                      <p className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-fg-3">{chosenSets.map(label).join(', ')}</p>
                      <div className="grid gap-2 sm:grid-cols-2">
                        {examples.map((q) => (
                          <button key={q} type="button" onClick={() => submit(q)} className="min-h-11 rounded-lg border border-line bg-surface px-3.5 py-2.5 text-left text-[14px] text-fg hover:border-brand">
                            {q}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  {!examples.length && !loadError && <p className="mt-6 text-[13px] text-fg-3">Loading datasets…</p>}
                </section>
              )}
              {turns.map((t, i) => (
                <AnswerCard key={t.id} turn={t} live={a.busy && i === turns.length - 1} theme={theme.resolved} shape={shape} pinned={pinnedIds.has(t.id)} onAction={onTurnAction} />
              ))}
            </div>
          </div>
          <div className="border-t border-line bg-bg p-3">
            <div className="mx-auto max-w-3xl">
              {pending && <p className="mb-1.5 text-[13px] text-brand">Answering: {pending}</p>}
              <div className="flex items-end gap-2 rounded-lg border border-line-strong bg-surface p-2 focus-within:border-accent">
                <label htmlFor="ask" className="sr-only">Ask a question about your data</label>
                <textarea id="ask" ref={box} rows={1} value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onComposerKey} maxLength={4000}
                  placeholder={pending ? 'Your answer…' : !loaded ? 'Loading datasets…' : selected.length ? 'Ask about your data…' : 'Select a dataset to start'}
                  className="max-h-40 min-h-[40px] flex-1 resize-none bg-transparent px-2 py-2 text-[15px] text-fg placeholder:text-fg-3 focus:outline-none" />
                {a.busy ? (
                  <button type="button" onClick={a.cancel} aria-label="Stop" className="rounded-md bg-fg p-2.5 text-bg hover:opacity-90"><Square className="h-4 w-4" /></button>
                ) : (
                  <button type="button" onClick={() => submit()} disabled={!draft.trim()} aria-label="Send"
                    className="rounded-md bg-brand p-2.5 text-on-brand hover:opacity-90 disabled:bg-surface-2 disabled:text-fg-3"><ArrowUp className="h-4 w-4" /></button>
                )}
              </div>
              <div className="mt-1.5 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[12px] text-fg-3">
                <span>{!loaded ? 'Loading datasets…' : chosenSets.length ? `Answers come from ${chosenSets.map(label).join(', ')}; check the SQL for important decisions.` : 'No dataset selected.'}</span>
                <label className="inline-flex items-center gap-1.5">
                  Model
                  <select value={chosen ?? ''} onChange={(e) => pickModel(e.target.value)} disabled={a.busy}
                    className="min-h-6 rounded border border-line-strong bg-surface px-1.5 text-[12px] text-fg focus:outline-none">
                    <option value="">Auto (recommended)</option>
                    {models.map((m) => (
                      <option key={m.id} value={m.id} disabled={!m.available}>{modelLabel(m.id)}{m.available ? '' : ` (unavailable: ${m.note})`}</option>
                    ))}
                  </select>
                </label>
              </div>
            </div>
          </div>
        </main>

        <div className={cn('hidden w-[400px] shrink-0 border-l border-line bg-surface', drawerOpen && 'xl:block')}>
          <EvidenceDrawer turn={evidenceTurn} onClose={() => setDrawerOpen(false)} />
        </div>
        {drawerOpen && (
          <div className="fixed inset-0 z-40 xl:hidden" role="dialog" aria-modal="true" aria-label="Details">
            <div className="absolute inset-0 bg-black/50" onClick={() => setDrawerOpen(false)} />
            <div className="absolute inset-x-0 bottom-0 max-h-[85%] overflow-auto rounded-t-xl border-t border-line bg-surface md:inset-y-0 md:left-auto md:right-0 md:max-h-none md:w-full md:max-w-md md:rounded-none md:border-l md:border-t-0">
              <EvidenceDrawer turn={evidenceTurn} onClose={() => setDrawerOpen(false)} />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
