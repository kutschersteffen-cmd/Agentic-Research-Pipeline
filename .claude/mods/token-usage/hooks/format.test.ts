import { expect, test } from 'claude-code/testing'

import { format, runsOutIn } from './register'

test('formats context, cost and rate limits', () => {
  const limits = [{ kind: 'five_hour', percentUsed: 41.6 }, { kind: 'seven_day', percentUsed: 12 }] as never
  expect(format({ tokens: 45200, window: 200000, percent: 22.6 }, limits, 1.234)).toBe('ctx 45k/200k (23%) · $1.23 · 5h 42% · 7d 12%')
  expect(format({ window: 200000 }, [], undefined)).toBe('ctx –/200k')
})

test('warns when the pace uses up a limit before it resets', () => {
  const now = Date.parse('2026-11-13T12:00:00Z')
  const resetsAt = '2026-11-13T15:00:00Z' // 2 h of the 5 h window gone, 3 h left
  // 80% in 2 h: the last 20% goes in 30 min, well before the reset
  expect(runsOutIn({ kind: 'five_hour', percentUsed: 80, resetsAt }, now)).toBe(30 * 60e3)
  expect(format({ window: 200000 }, [{ kind: 'five_hour', percentUsed: 80, resetsAt }], undefined, now)).toBe(
    'ctx –/200k · 5h 80% · ⚠ 5h out in ~30m',
  )
  // 30% in 2 h: 100% would take 6.7 h, after the reset
  expect(runsOutIn({ kind: 'five_hour', percentUsed: 30, resetsAt }, now)).toBeUndefined()
  // already at the limit
  expect(runsOutIn({ kind: 'seven_day', percentUsed: 100, resetsAt }, now)).toBe(0)
  // too early in the window, or no reset time: no guess
  expect(runsOutIn({ kind: 'five_hour', percentUsed: 5, resetsAt: '2026-11-13T16:59:00Z' }, now)).toBeUndefined()
  expect(runsOutIn({ kind: 'five_hour', percentUsed: 90 }, now)).toBeUndefined()
})
