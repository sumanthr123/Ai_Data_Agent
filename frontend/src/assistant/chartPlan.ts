import { isMeasure, isNumericType, isTimeLike } from './format'
import type { ResultPreview } from './types'

export interface ChartPlan { dim: string; measures: string[]; time: boolean; rows: ResultPreview['rows'] }

/** A chart only when the shape suits one: one dimension, at least one measure, 2 to 12 categories (40 points for time). */
export function chartPlan(result: ResultPreview): ChartPlan | null {
  if (result.truncated || result.rows.length < 2) return null
  const cols = result.columns.map((c, i) => ({ name: c, type: result.column_types[i] ?? '' }))
  const dims = cols.filter((c) => !isNumericType(c.type) || isTimeLike(c.name, c.type))
  const measures = cols.filter((c) => isMeasure(c.name, c.type) && !isTimeLike(c.name, c.type)).map((c) => c.name)
  if (dims.length !== 1 || !measures.length) return null
  const dim = dims[0]
  const time = isTimeLike(dim.name, dim.type)
  if (result.rows.length > (time ? 40 : 12)) return null
  const rows = time ? [...result.rows].sort((a, b) => String(a[dim.name]).localeCompare(String(b[dim.name]))) : result.rows
  return { dim: dim.name, measures, time, rows }
}

/** One number: a KPI tile instead of a chart or table. */
export function kpiOf(result: ResultPreview): { label: string; value: number; type: string } | null {
  if (result.rows.length !== 1 || result.columns.length !== 1) return null
  const name = result.columns[0]
  const value = result.rows[0][name]
  return typeof value === 'number' ? { label: name, value, type: result.column_types[0] ?? '' } : null
}
