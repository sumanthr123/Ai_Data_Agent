// Run with: node --test src/lib/markdown.test.ts  (Node strips the TypeScript types itself; no test dependencies.)
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { parseInline, safeHref } from './markdown.ts'

test('only http(s) and mailto links are allowed', () => {
  assert.equal(safeHref('https://www.sos.state.tx.us/elections'), 'https://www.sos.state.tx.us/elections')
  assert.equal(safeHref('javascript:alert(1)'), null)
  assert.equal(safeHref('data:text/html,hi'), null)
  assert.equal(safeHref('/relative'), null)
})

test('markdown links render as links instead of raw text', () => {
  const parts = parseInline('See [Election results](https://results.example.gov/2026) for details.')
  assert.deepEqual(parts[1], { kind: 'link', text: 'Election results', href: 'https://results.example.gov/2026' })
})

test('unsafe links fall back to their text', () => {
  assert.deepEqual(parseInline('[click](javascript:alert(1))')[0], { kind: 'text', text: 'click' })
})

test('citation markers resolve only to known sources', () => {
  const parts = parseInline('Verstappen won.[1][9]', 2)
  assert.deepEqual(parts, [{ kind: 'text', text: 'Verstappen won.' }, { kind: 'cite', n: 1 }])
})

test('bold, code and LaTeX are cleaned up', () => {
  assert.deepEqual(parseInline('**O(n)** via `heapify` is $O(n)$'), [
    { kind: 'bold', text: 'O(n)' }, { kind: 'text', text: ' via ' }, { kind: 'code', text: 'heapify' }, { kind: 'text', text: ' is O(n)' },
  ])
})

test('common LaTeX symbols become plain characters', () => {
  assert.deepEqual(parseInline('projected $\\ge$54 seats'), [{ kind: 'text', text: 'projected ≥54 seats' }])
})

test('LaTeX function names lose their backslash', () => {
  assert.deepEqual(parseInline('**$O(\\log n)$**'), [{ kind: 'bold', text: 'O(log n)' }])
})
