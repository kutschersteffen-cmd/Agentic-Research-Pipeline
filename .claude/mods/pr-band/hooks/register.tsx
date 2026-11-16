import { atom, read, update } from 'claude-code'
import type { EngineInterface, McpToolResult, Register } from 'claude-code'

import type { Ci } from '../types'

const REFRESH_MS = 60_000
const FAILED = ['failure', 'timed_out', 'cancelled', 'action_required', 'startup_failure']
const state = atom({ plugin: 'pr-band', key: 'band' } as const, {})

type CheckRun = { status: string; conclusion: string | null }

export const ci = (runs: CheckRun[]): Ci =>
  runs.length === 0
    ? 'none'
    : runs.some(r => FAILED.includes(r.conclusion ?? ''))
      ? 'red'
      : runs.some(r => r.status !== 'completed')
        ? 'pending'
        : 'green'

// "https://github.com/o/r(.git)" or "git@github.com:o/r.git" → { owner, repo }
export const ownerRepo = (url: string) => {
  const m = url.trim().match(/github\.com[/:]([^/]+)\/(.+?)(\.git)?$/)
  return m ? { owner: m[1]!, repo: m[2]! } : undefined
}

const json = (r: McpToolResult) => {
  const text = r.content.map(b => (b.type === 'text' ? b.text : '')).join('')
  if (r.isError) throw new Error(text.slice(0, 120))
  return JSON.parse(text)
}

const git = async ($: EngineInterface, ...args: string[]) => (await $.process.run(['git', ...args])).stdout.trim()

async function refresh($: EngineInterface) {
  try {
    const where = ownerRepo(await git($, 'remote', 'get-url', 'origin'))
    const branch = await git($, 'branch', '--show-current')
    if (!where || !branch) return update($, state, () => ({}))
    const prs = json(
      await $.mcp.call('github', 'list_pull_requests', { ...where, head: `${where.owner}:${branch}`, state: 'open', fields: ['number', 'title', 'labels'] }),
    ) as { number: number; title: string; labels?: (string | { name: string })[] }[]
    const pr = prs[0]
    if (!pr) return update($, state, () => ({}))
    // shortcut: first 100 check runs only, page further if a PR ever has more
    const { check_runs } = json(await $.mcp.call('github', 'pull_request_read', { ...where, method: 'get_check_runs', pullNumber: pr.number, perPage: 100 }))
    const risk = (pr.labels ?? []).map(l => (typeof l === 'string' ? l : l.name)).find(l => l.startsWith('risk:'))
    await update($, state, () => ({ pr: { number: pr.number, title: pr.title, risk, ci: ci(check_runs ?? []) } }))
  } catch (err) {
    await update($, state, old => ({ ...old, error: (err as Error).message }))
  }
}

const CI_LOOK: Record<Ci, { text: string; color?: string }> = {
  green: { text: '✓ CI green', color: 'green' },
  red: { text: '✗ CI red', color: 'red' },
  pending: { text: '… CI running', color: 'yellow' },
  none: { text: 'no checks' },
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    void refresh($)
    $.clock.every(REFRESH_MS, () => void refresh($))
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    void refresh($) // a turn may have pushed or opened the PR
    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const { pr, error } = await read($, state)
    if (e.props.hasSurvey || (!pr && !error)) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    if (!pr) return <Box><Text dimColor>PR band: {error}</Text></Box>
    const look = CI_LOOK[pr.ci]
    return (
      <Box>
        <Text>
          <Text bold>PR #{pr.number}</Text>
          {pr.risk && <Text color={pr.risk === 'risk:high' ? 'red' : undefined}> · {pr.risk}</Text>}
          {' · '}
          <Text color={look.color}>{look.text}</Text>
          <Text dimColor> · {pr.title.length > 60 ? `${pr.title.slice(0, 59)}…` : pr.title}</Text>
        </Text>
      </Box>
    )
  })
}
