import type { ReactNode } from 'react'

const KEYWORDS = new Set(['SELECT', 'FROM', 'WHERE', 'GROUP', 'BY', 'ORDER', 'AS', 'AND', 'OR', 'NOT', 'NULL', 'IS', 'IN', 'BETWEEN', 'SUM', 'AVG',
  'COUNT', 'MIN', 'MAX', 'ROUND', 'COALESCE', 'DESC', 'ASC', 'LIMIT', 'JOIN', 'LEFT', 'INNER', 'OUTER', 'ON', 'USING', 'WITH', 'CASE',
  'WHEN', 'THEN', 'ELSE', 'END', 'DISTINCT', 'HAVING', 'DATE', 'OVER', 'PARTITION'])
const TOKENS = /(--.*$)|('[^']*'|"[^"]*")|(\b[A-Za-z_]+\b)|(\b\d+(?:\.\d+)?\b)/g

/** Syntax-highlight one SQL line as React nodes (no raw HTML). */
export function highlight(line: string): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  for (const m of line.matchAll(TOKENS)) {
    const index = m.index ?? 0
    if (index > last) out.push(line.slice(last, index))
    const [token, comment, str, word, number] = m
    const cls = comment ? 'text-slate-400' : str ? 'text-emerald-300' : number ? 'text-amber-300'
      : word && KEYWORDS.has(word.toUpperCase()) ? 'text-sky-300' : ''
    out.push(cls ? <span key={index} className={cls}>{token}</span> : token)
    last = index + token.length
  }
  if (last < line.length) out.push(line.slice(last))
  return out
}

/** Normalize SQL so a diff ignores formatting: one clause per line, single spaces, upper keywords. */
export function normalizeSql(sql: string): string[] {
  return sql
    .replace(/\s+/g, ' ')
    .replace(/\b(SELECT|FROM|WHERE|GROUP BY|ORDER BY|HAVING|LEFT JOIN|INNER JOIN|JOIN|LIMIT|WITH)\b/gi, '\n$1')
    .split('\n').map((l) => l.trim()).filter(Boolean)
}

export function SqlBlock({ sql, compareTo, className }: { sql: string; compareTo?: string; className?: string }) {
  // Models often return one long line; break it into clauses so it reads without scrolling.
  const lines = compareTo !== undefined || !sql.includes('\n') ? normalizeSql(sql) : sql.split('\n')
  const other = new Set(compareTo !== undefined ? normalizeSql(compareTo).map((l) => l.toLowerCase()) : [])
  return (
    <pre className={`overflow-auto rounded-xl border border-white/[0.06] bg-black/40 p-3 whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed text-slate-300 ${className ?? ''}`}>
      {lines.map((line, i) => {
        const changed = compareTo !== undefined && !other.has(line.toLowerCase())
        return (
          <div key={i} className={changed ? '-mx-3 bg-amber-400/10 px-3' : ''}>
            {changed && <span className="mr-1 text-amber-300">±</span>}{highlight(line)}
          </div>
        )
      })}
    </pre>
  )
}
