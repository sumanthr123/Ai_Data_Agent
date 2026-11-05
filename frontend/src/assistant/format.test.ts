import assert from 'node:assert/strict'
import { test } from 'node:test'
import { fmtCell, isMeasure, layoutSql } from './format.ts'

test('one-line SQL is laid out by clause; multi-line SQL is untouched', () => {
  assert.equal(layoutSql("SELECT region, SUM(sales) AS s FROM t WHERE a >= '2017-01-01' AND b < 3 GROUP BY region ORDER BY s DESC LIMIT 5"),
    "SELECT region, SUM(sales) AS s\nFROM t\nWHERE a >= '2017-01-01'\n  AND b < 3\nGROUP BY region\nORDER BY s DESC\nLIMIT 5")
  assert.equal(layoutSql('SELECT 1\nFROM t'), 'SELECT 1\nFROM t')
})

test('ids, ZIP codes and codes are never charted as measures', () => {
  assert.equal(isMeasure('total_sales', 'DOUBLE'), true)
  for (const name of ['customer_id', 'postal_code', 'row_id', 'zip']) assert.equal(isMeasure(name, 'INT'), false)
})

test('NULL is shown as NULL, not zero', () => {
  assert.equal(fmtCell(null), 'NULL')
  assert.equal(fmtCell(1234.5, 'DOUBLE'), '1,234.50')
  assert.equal(fmtCell('00451', 'STRING'), '00451')
})
