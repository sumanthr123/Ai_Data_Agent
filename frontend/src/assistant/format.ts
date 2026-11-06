import type { Cell } from './types'

const NUMERIC = /^(byte|short|int|integer|long|bigint|smallint|tinyint|float|double|decimal)/i
const ID_LIKE = /(^id$|_id$|^row_id$|postal|zip|_code$)/i
const TIME_LIKE = /(date|month|year|quarter|week|day|period|time)/i

export const isNumericType = (type: string) => NUMERIC.test(type)
export const isMeasure = (name: string, type: string) => isNumericType(type) && !ID_LIKE.test(name)
export const isTimeLike = (name: string, type: string) => /^(date|timestamp)/i.test(type) || TIME_LIKE.test(name)
export const humanize = (name: string) => name.replace(/_/g, ' ')

const MODEL_LABELS: Record<string, string> = {
  'databricks-gpt-oss-120b': 'GPT-OSS 120B', 'databricks-llama-4-maverick': 'Llama 4 Maverick',
  'databricks-qwen35-122b-a10b': 'Qwen 3.5 122B', 'gemini-3-5-flash': 'Gemini 3.5 Flash', 'claude-sonnet-5-5': 'Claude Sonnet 5.5',
}
/** "endpoint" or "endpoint/served_model" -> a readable model name. */
export const modelLabel = (endpoint: string) => {
  const name = endpoint.split('/').pop() ?? endpoint
  return MODEL_LABELS[name] ?? name.replace(/^databricks-/, '')
}

export function fmtCell(value: Cell, type = ''): string {
  if (value === null || value === undefined) return 'NULL'
  if (typeof value === 'number') {
    return /^(double|float|decimal)/i.test(type) || !Number.isInteger(value)
      ? value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      : value.toLocaleString('en-US')
  }
  return String(value)
}

export function fmtCompact(n: number): string {
  return Math.abs(n) >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : Math.abs(n) >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : n.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

export function relativeTime(iso: string | null): string {
  if (!iso) return 'unknown'
  const diff = Date.now() - new Date(iso).getTime()
  const future = diff < 0
  const mins = Math.round(Math.abs(diff) / 60000)
  const text = mins < 60 ? `${mins} min` : mins < 2880 ? `${Math.round(mins / 60)} h` : `${Math.round(mins / 1440)} days`
  return future ? `in ${text}` : `${text} ago`
}

/** One-line SQL from a model, broken before its main clauses so it reads top to bottom (multi-line SQL is left as is). */
export function layoutSql(sql: string): string {
  if (sql.includes('\n')) return sql
  return sql.replace(/\s+(FROM|WHERE|GROUP BY|HAVING|ORDER BY|LIMIT|(?:LEFT |RIGHT |FULL |INNER |CROSS )?(?:OUTER )?JOIN|UNION(?: ALL)?)\s+/gi, '\n$1 ')
    .replace(/\s+(AND|OR)\s+(?=[^()]*(?:\(|$))/gi, '\n  $1 ')
}
