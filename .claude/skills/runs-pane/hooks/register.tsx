import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Run } from '../types'

const PANE = 'pipeline-runs'
const REFRESH_MS = 15_000
const state = atom({ plugin: 'runs-pane', key: 'runs' } as const, { runs: [] })

// One line of `arp runs list`: id, type, status, "n/m done", "$cost", tab-separated.
export const parse = (stdout: string): Run[] =>
  stdout
    .split('\n')
    .map(line => line.split('\t'))
    .filter(cols => cols.length === 5)
    .map(([id = '', type = '', status = '', progress = '', cost = '']) => ({ id, type, status, progress: progress.replace(' done', ''), cost }))

async function refresh($: EngineInterface) {
  const r = await $.process
    .run(['python3', '-m', 'arp.cli', 'runs', 'list'], { cwd: 'backend', timeoutMs: 20_000 })
    .catch((err: Error) => ({ exitCode: 1, stdout: '', stderr: err.message }))
  const error = r.exitCode === 0 ? undefined : r.stderr.trim().split('\n').pop() || `exit ${r.exitCode}`
  const now = await $.clock.now()
  await update($, state, old => ({ runs: error ? old.runs : parse(r.stdout), error, at: now }))
}

const open = ($: EngineInterface) => $.ui.open({ id: PANE, title: 'Pipeline runs' })

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'runs', description: 'Show pipeline runs in a live pane' })
    void refresh($)
    $.clock.every(REFRESH_MS, () => void refresh($))
    void open($)
    return next(e)
  })

  on('command.run', { command: 'runs' }, async $ => {
    await refresh($)
    await open($)
    return { text: 'Pipeline runs pane opened.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const { runs, error, at } = await read($, state)
    const room = Math.max(1, (e.viewport?.rows ?? 24) - 5)
    const color = (s: string) => (s === 'failed' ? 'red' : s === 'completed' ? 'green' : s === 'running' ? 'yellow' : undefined)

    return (
      <Box flexDirection="column">
        {error && <Text color="red">Can't list runs: {error}</Text>}
        {!error && runs.length === 0 && <Text dimColor>{at ? 'No runs yet.' : 'Loading…'}</Text>}
        {runs.slice(0, room).map(run => (
          <Text>
            <Text color={color(run.status)}>{run.status.padEnd(10)}</Text> {run.type.padEnd(18)} {run.progress.padEnd(9)} {run.cost.padStart(7)}{' '}
            <Text dimColor>{run.id}</Text>
          </Text>
        ))}
        {at && <Text dimColor>updated {new Date(at).toLocaleTimeString()} · every {REFRESH_MS / 1000}s · /runs to refresh</Text>}
      </Box>
    )
  })
}
