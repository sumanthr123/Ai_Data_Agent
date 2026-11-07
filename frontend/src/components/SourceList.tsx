import { ExternalLink } from 'lucide-react'
import type { Source } from '../types/consensus'

export function SourceList({ sources }: { sources: Source[] }) {
  return (
    <ol className="mt-4 space-y-1.5" aria-label="Sources">
      {sources.map((s) => (
        <li key={s.n} className="flex gap-2 text-[12.5px]">
          <span className="mt-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-sky-400/15 text-[10.5px] font-semibold text-sky-200">{s.n}</span>
          <span className="min-w-0">
            <a href={s.url} target="_blank" rel="noopener noreferrer nofollow" className="inline-flex items-center gap-1 text-zinc-100 hover:text-sky-200 hover:underline">
              {s.title} <ExternalLink className="h-3 w-3 shrink-0 text-zinc-400" />
            </a>
            <span className="block text-zinc-400">
              {[s.publisher, s.published && `published ${s.published}`, s.retrieved_at && `retrieved ${s.retrieved_at}`].filter(Boolean).join(' · ')}
            </span>
          </span>
        </li>
      ))}
    </ol>
  )
}
