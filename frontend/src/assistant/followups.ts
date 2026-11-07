/** Follow-up questions built from the answer's own shape, not a model call: one drill-down, one comparison, one zoom-out. */

export interface FollowupColumn { name: string; type: string; distinct: number | null }
export interface FollowupInput {
  question: string
  resultColumns: string[]
  datasetColumns: FollowupColumn[]
  dateColumn: string | null
}

const words = (s: string) => s.toLowerCase().replace(/_/g, ' ')
const TIME_WORDS = /\b(month|monthly|week|weekly|day|daily|quarter|quarterly|trend|over time)\b/i

export function followups({ question, resultColumns, datasetColumns, dateColumn }: FollowupInput): string[] {
  const q = words(question)
  const inResult = new Set(resultColumns.map((c) => c.toLowerCase()))
  const out: string[] = []

  // Drill-down: a low-cardinality text column the answer didn't already use.
  const dim = datasetColumns.find((c) => /string/i.test(c.type) && (c.distinct ?? 0) >= 2 && (c.distinct ?? 0) <= 25
    && !inResult.has(c.name.toLowerCase()) && !q.includes(words(c.name)))
  if (dim) out.push(`Break this down by ${words(dim.name)}`)

  // Comparison: the year before the one asked about.
  const year = /\b(19|20)\d{2}\b/.exec(question)?.[0]
  if (year) out.push(`Compare with ${Number(year) - 1}`)

  // Zoom out: the trend over time, when the answer isn't already a time series.
  const hasTime = resultColumns.some((c) => /(date|month|year|quarter|week|day|period)/i.test(c))
  if (dateColumn && !hasTime && !TIME_WORDS.test(question)) out.push(year ? `Show the monthly trend in ${year}` : 'Show the monthly trend')

  return out.slice(0, 3)
}
