import assert from 'node:assert/strict'
import { test } from 'node:test'
import { followups } from './followups.ts'

const columns = [
  { name: 'region', type: 'string', distinct: 4 },
  { name: 'segment', type: 'string', distinct: 3 },
  { name: 'customer_name', type: 'string', distinct: 793 },
  { name: 'sales', type: 'decimal(18,4)', distinct: null },
]

test('drill-down skips dimensions already used, plus comparison and trend', () => {
  const out = followups({ question: 'What were total sales by region in 2017?', resultColumns: ['region', 'total_sales'], datasetColumns: columns, dateColumn: 'order_date' })
  assert.deepEqual(out, ['Break this down by segment', 'Compare with 2016', 'Show the monthly trend in 2017'])
})

test('no trend for an answer that is already a time series, no comparison without a year', () => {
  const out = followups({ question: 'How did sales change by month?', resultColumns: ['order_month', 'sales'], datasetColumns: columns, dateColumn: 'order_date' })
  assert.deepEqual(out, ['Break this down by region'])
})

test('high-cardinality columns are never suggested', () => {
  const out = followups({ question: 'Sales by region and segment', resultColumns: ['region', 'segment', 'sales'], datasetColumns: columns, dateColumn: null })
  assert.deepEqual(out, [])
})
