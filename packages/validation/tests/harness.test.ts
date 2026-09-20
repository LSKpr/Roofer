import assert from 'node:assert/strict'
import { test } from 'node:test'

test('runner wykonuje TypeScript i widzi typy', () => {
  const doubled: number[] = [1, 2, 3].map((n) => n * 2)
  assert.deepEqual(doubled, [2, 4, 6])
})
