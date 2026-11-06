import { AlertTriangle, BookOpen, Code2, Database, Globe, MessageCircle, Scale } from 'lucide-react'
import { CodeBlock } from '../components/CodeBlock'
import { cn } from '../lib/cn'
import type { AskResponse, CodeInfo, CouncilInfo, DocSource } from './types'

const KINDS = {
  data: { label: 'Live data', Icon: Database },
  web: { label: 'Web', Icon: Globe },
  docs: { label: 'Project knowledge', Icon: BookOpen },
  code: { label: 'Code', Icon: Code2 },
  chat: { label: 'Conversation', Icon: MessageCircle },
} as const

export function KindBadge({ kind }: { kind: AskResponse['kind'] }) {
  const { label, Icon } = KINDS[kind] ?? KINDS.data
  return <span className="inline-flex items-center gap-1 rounded-full border border-zinc-700 px-2 py-0.5 text-[11.5px] text-zinc-300"><Icon className="h-3 w-3" aria-hidden /> {label}</span>
}

const AGREEMENT = {
  full: ['Agreed', 'text-emerald-300', 'Independent queries returned the same values.'],
  partial: ['Partially agreed', 'text-amber-300', 'Most independent queries returned the same values.'],
  conflict: ['Conflict', 'text-rose-300', 'Independent queries returned different values.'],
  single: ['Single result', 'text-amber-300', 'Only one query ran, so nothing reproduced it: lower confidence.'],
} as const

export function CouncilView({ council }: { council: CouncilInfo }) {
  const [label, color, meaning] = AGREEMENT[council.agreement]
  return (
    <details className="rounded-lg border border-zinc-800 p-3 text-[13px]" open={council.agreement === 'conflict'}>
      <summary className="flex cursor-pointer flex-wrap items-center gap-2 text-zinc-200">
        <Scale className="h-4 w-4 text-zinc-400" aria-hidden />
        <span>Council: <span className={cn('font-medium', color)}>{label}</span></span>
        <span className="text-zinc-400">{council.trigger === 'requested' ? '· requested' : '· the Reviewer disputed the first answer'}</span>
      </summary>
      <p className="mt-2 text-zinc-400">{meaning} Judge: {council.judge.split('/').pop()}{council.chosen ? `, chose ${council.chosen}` : ', chose none'}.</p>
      {council.disagreement && (
        <p className="mt-2 flex gap-2 rounded-md border border-amber-400/30 bg-amber-400/10 p-2 text-amber-100"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />{council.disagreement}</p>
      )}
      <ul className="mt-2 space-y-2">
        {council.candidates.map((c, i) => (
          <li key={i} className={cn('rounded-md border p-2', c.label && c.label === council.chosen ? 'border-emerald-400/40' : 'border-zinc-800')}>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-zinc-300">
              <span className="font-medium text-zinc-100">{c.label || '–'} · {c.endpoint.split('/').pop()}</span>
              <span>{c.status === 'executed' ? `${c.row_count ?? 0} row(s), result group ${(c.group ?? 0) + 1}` : c.status}</span>
              {c.note && <span className="text-zinc-400">{c.note}</span>}
            </div>
            {c.sql && <details className="mt-1"><summary className="cursor-pointer text-zinc-400">SQL</summary><CodeBlock code={c.sql} lang="sql" /></details>}
          </li>
        ))}
      </ul>
    </details>
  )
}

export function DocSources({ sources }: { sources: DocSource[] }) {
  return (
    <ol className="space-y-1.5" aria-label="Project sources">
      {sources.map((s) => (
        <li key={s.n} className="flex gap-2 text-[12.5px]">
          <span className="mt-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-sky-400/15 text-[10.5px] font-semibold text-sky-200">{s.n}</span>
          <span className="min-w-0 text-zinc-300"><span className="text-zinc-100">{s.section}</span> <span className="text-zinc-400">· {s.file}</span></span>
        </li>
      ))}
    </ol>
  )
}

const VALIDATION = {
  validated: ['Validated with EXPLAIN', 'text-emerald-300'],
  syntax_ok: ['Syntax checked, not run', 'text-sky-300'],
  not_run: ['Not validated', 'text-amber-300'],
  failed: ['Failed validation', 'text-rose-300'],
  untested: ['Untested', 'text-amber-300'],
} as const

export function CodeAnswer({ code }: { code: CodeInfo }) {
  const [label, color] = VALIDATION[code.validation]
  return (
    <div className="space-y-2">
      {code.destructive && (
        <p role="alert" className="flex gap-2 rounded-md border border-rose-400/30 bg-rose-400/10 p-2 text-[13px] text-rose-100">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /> This code writes or deletes data or files. Review it before running; the assistant never runs it.
        </p>
      )}
      <CodeBlock code={code.code} lang={code.language === 'other' ? undefined : code.language} />
      <p className="text-[12px]"><span className={cn('font-medium', color)}>{label}</span> <span className="text-zinc-400">{code.detail}</span></p>
    </div>
  )
}
