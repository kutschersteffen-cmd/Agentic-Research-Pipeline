import { atom, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Weakening } from '../types'

const TESTS = /(^|\/)(backend|frontend)\/tests\//
// Python tests and asserts, plus vitest/jest cases and expectations.
const MARKERS = /\bdef test_|\bassert\b|\b(it|test)(\.\w+)?\(|\bexpect\(/g

export const count = (text: string) => text.match(MARKERS)?.length ?? 0

const weakenings = atom({ plugin: 'test-guard', key: 'weakenings' } as const, [])

async function warn($: EngineInterface, w: Weakening) {
  const name = w.file.replace(/^.*?((backend|frontend)\/tests\/)/, '$1')
  $.ui.toast(`Tests weakened: ${name} (${w.before} → ${w.after} tests/asserts). List it in the PR.`)
  const all = await update($, weakenings, list => [...list, w])
  $.ui.status(`⚠ ${all.length} test weakening${all.length === 1 ? '' : 's'} this session`)
}

export const register: Register = on => {
  on('tool.call', { tool: 'Edit' }, async ($, e, next) => {
    const ran = await next(e)
    const before = count(e.old_string)
    const after = count(e.new_string)
    if (TESTS.test(e.file_path) && !ran.isError && after < before) await warn($, { file: e.file_path, before, after })
    return ran
  }).catch(($, e, next) => next(e)) // an alarm fails open: never block the edit

  on('tool.call', { tool: 'Write' }, async ($, e, next) => {
    if (!TESTS.test(e.file_path)) return next(e)
    const old = await $.fs.read(e.file_path).catch(() => '')
    const ran = await next(e)
    const before = count(old)
    const after = count(e.content)
    if (!ran.isError && after < before) await warn($, { file: e.file_path, before, after })
    return ran
  }).catch(($, e, next) => next(e))
}
