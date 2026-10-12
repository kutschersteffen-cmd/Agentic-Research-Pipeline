import { expect, test } from 'claude-code/testing'

import { format } from './register'

test('formats context, cost and rate limits', () => {
  const limits = [{ kind: 'five_hour', percentUsed: 41.6 }, { kind: 'seven_day', percentUsed: 12 }] as never
  expect(format({ tokens: 45200, window: 200000, percent: 22.6 }, limits, 1.234)).toBe('ctx 45k/200k (23%) · $1.23 · 5h 42% · 7d 12%')
  expect(format({ window: 200000 }, [], undefined)).toBe('ctx –/200k')
})
