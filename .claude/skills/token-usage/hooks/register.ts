import type { Register, SessionContextUsage, SessionRateLimit } from 'claude-code'

const LABELS: Record<string, string> = { five_hour: '5h', seven_day: '7d' }
const k = (n: number) => (n >= 1000 ? `${Math.round(n / 1000)}k` : `${n}`)

export const format = (context: SessionContextUsage, rateLimits: SessionRateLimit[], usd?: number) =>
  [
    context.tokens === undefined
      ? `ctx –/${k(context.window)}`
      : `ctx ${k(context.tokens)}/${k(context.window)} (${Math.round(context.percent ?? (100 * context.tokens) / context.window)}%)`,
    usd === undefined ? undefined : `$${usd.toFixed(2)}`,
    ...rateLimits.map(r => `${LABELS[r.kind] ?? r.kind} ${Math.round(r.percentUsed)}%`),
  ]
    .filter(Boolean)
    .join(' · ')

export const register: Register = on => {
  on('session.measure', async ($, e, next) => {
    const { cost } = await $.session.usage()
    $.ui.status(format(e.context, e.rateLimits, cost?.usd))
    return next(e)
  })
}
