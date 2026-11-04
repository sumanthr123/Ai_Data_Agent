import { Fragment, type ReactNode } from 'react'
import { parseInline } from '../lib/markdown'
import type { Source } from '../types/consensus'
import { CodeBlock } from './CodeBlock'

/** Renders the Markdown agents produce: headings, lists, tables, paragraphs, links and [n] citations. */
export function Markdown({ text, sources = [] }: { text: string; sources?: Source[] }) {
  const inline = (line: string) => renderInline(line, sources)
  return <div className="space-y-4 text-[15px] leading-[1.75] text-slate-200">{blocks(text, inline)}</div>
}

function blocks(text: string, inline: (line: string) => ReactNode[]): ReactNode[] {
  const lines = text.split('\n')
  const out: ReactNode[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (!line.trim()) { i++; continue }
    const fence = /^\s*```\s*([\w+-]*)/.exec(line)
    if (fence) {
      const code: string[] = []
      i++
      while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++])
      i++
      out.push(<CodeBlock key={out.length} lang={fence[1]} code={code.join('\n')} />)
      continue
    }
    if (line.trim().startsWith('|')) {
      const rows: string[][] = []
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        const cells = lines[i].trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim())
        if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(cells)
        i++
      }
      const [head, ...body] = rows
      out.push(
        <div key={out.length} className="overflow-x-auto rounded-xl border border-white/[0.07]">
          <table className="w-full text-[13px]">
            <thead className="bg-white/[0.04]"><tr>{head.map((c, j) => <th key={j} className="px-3 py-2 text-left font-mono text-[11px] font-medium uppercase tracking-wider text-slate-400">{inline(c)}</th>)}</tr></thead>
            <tbody>{body.map((r, k) => <tr key={k} className="border-t border-white/[0.05]">{r.map((c, j) => <td key={j} className="px-3 py-1.5 font-mono text-slate-200">{inline(c)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      )
      continue
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    if (heading) {
      out.push(<div key={out.length} className={heading[1].length <= 2 ? 'pt-1 text-[16px] font-semibold text-white' : 'pt-1 text-[14.5px] font-semibold text-white'}>{inline(heading[2])}</div>)
      i++
      continue
    }
    if (/^\s*([-*•]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line)
      const items: string[] = []
      while (i < lines.length && /^\s*([-*•]|\d+\.)\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*([-*•]|\d+\.)\s+/, ''))
        i++
      }
      const List = ordered ? 'ol' : 'ul'
      out.push(<List key={out.length} className={`space-y-1 pl-5 ${ordered ? 'list-decimal' : 'list-disc'} marker:text-cyan-400/70`}>{items.map((it, k) => <li key={k}>{inline(it)}</li>)}</List>)
      continue
    }
    const para: string[] = []
    while (i < lines.length && lines[i].trim() && !/^(\s*\||#{1,4}\s|\s*([-*•]|\d+\.)\s+|\s*```)/.test(lines[i])) {
      para.push(lines[i])
      i++
    }
    out.push(<p key={out.length}>{inline(para.join(' '))}</p>)
  }
  return out
}

function renderInline(text: string, sources: Source[]): ReactNode[] {
  return parseInline(text, sources.length).map((part, i) => {
    switch (part.kind) {
      case 'bold': return <strong key={i} className="font-semibold text-white">{part.text}</strong>
      case 'italic': return <em key={i} className="text-slate-300">{part.text}</em>
      case 'code': return <code key={i} className="rounded bg-white/5 px-1.5 py-0.5 font-mono text-[12.5px] text-cyan-300">{part.text}</code>
      case 'link': return <a key={i} href={part.href} target="_blank" rel="noopener noreferrer nofollow" className="text-sky-300 underline decoration-sky-300/40 underline-offset-2 hover:text-sky-200">{part.text}</a>
      case 'cite': {
        const source = sources[part.n - 1]
        return (
          <a key={i} href={source.url} target="_blank" rel="noopener noreferrer nofollow" title={`${source.title} — ${source.publisher}`}
            aria-label={`Source ${part.n}: ${source.title}`}
            className="mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-0.5 items-center justify-center rounded-full bg-sky-400/15 px-1 align-middle text-[10.5px] font-semibold text-sky-200 hover:bg-sky-400/30">
            {part.n}
          </a>
        )
      }
      default: return <Fragment key={i}>{part.text}</Fragment>
    }
  })
}
