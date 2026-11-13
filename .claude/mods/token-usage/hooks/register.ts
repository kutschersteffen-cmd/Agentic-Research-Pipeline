import type { Register, SessionContextUsage, SessionRateLimit } from 'claude-code'

const LABELS: Record<string, string> = { five_hour: '5h', seven_day: '7d' }
const WINDOW_MS: Record<string, number> = { five_hour: 5 * 3600e3, seven_day: 7 * 86400e3 }
const k = (n: number) => (n >= 1000 ? `${Math.round(n / 1000)}k` : `${n}`)
const label = (r: SessionRateLimit) => LABELS[r.kind] ?? r.kind
const dur = (ms: number) =>
  ms < 3600e3 ? `${Math.max(1, Math.round(ms / 60e3))}m` : ms < 48 * 3600e3 ? `${Math.round(ms / 3600e3)}h` : `${Math.round(ms / 86400e3)}d`

// Time until the limit is used up at the pace so far in this window, if that comes before the reset.
export const runsOutIn = (r: SessionRateLimit, now: number): number | undefined => {
  const window = WINDOW_MS[r.kind]
  if (!window || !r.resetsAt) return undefined
  if (r.percentUsed >= 100) return 0
  const left = Date.parse(r.resetsAt) - now
  const elapsed = window - left
  if (r.percentUsed <= 0 || elapsed < window * 0.05) return undefined // too early in the window to judge pace
  const out = ((100 - r.percentUsed) * elapsed) / r.percentUsed
  return out < left ? out : undefined
}

export const warnings = (rateLimits: SessionRateLimit[], now: number) =>
  rateLimits.flatMap(r => {
    const out = runsOutIn(r, now)
    return out === undefined ? [] : [{ key: `${r.kind}@${r.resetsAt}`, text: `⚠ ${label(r)} out in ~${dur(out)}` }]
  })

export const format = (context: SessionContextUsage, rateLimits: SessionRateLimit[], usd?: number, now = Date.now()) =>
  [
    context.tokens === undefined
      ? `ctx –/${k(context.window)}`
      : `ctx ${k(context.tokens)}/${k(context.window)} (${Math.round(context.percent ?? (100 * context.tokens) / context.window)}%)`,
    usd === undefined ? undefined : `$${usd.toFixed(2)}`,
    ...rateLimits.map(r => `${label(r)} ${Math.round(r.percentUsed)}%`),
    ...warnings(rateLimits, now).map(w => w.text),
  ]
    .filter(Boolean)
    .join(' · ')

export const register: Register = on => {
  const toasted = new Set<string>() // shortcut: resets on reload, so a reload may repeat one toast
  on('session.measure', async ($, e, next) => {
    const { cost } = await $.session.usage()
    const now = Date.now()
    $.ui.status(format(e.context, e.rateLimits, cost?.usd, now))
    for (const w of warnings(e.rateLimits, now)) {
      if (toasted.has(w.key)) continue
      toasted.add(w.key)
      $.ui.toast(`${w.text.slice(2)} at this pace, before the limit resets. Start fewer parallel sessions or jobs.`)
    }
    return next(e)
  })
}
