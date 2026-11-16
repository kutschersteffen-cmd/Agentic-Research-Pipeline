import { expect, test } from 'claude-code/testing'

import { ci, ownerRepo } from './register'

test('CI state: red beats running, running beats green', () => {
  expect(ci([])).toBe('none')
  expect(ci([{ status: 'completed', conclusion: 'success' }, { status: 'completed', conclusion: 'skipped' }])).toBe('green')
  expect(ci([{ status: 'completed', conclusion: 'success' }, { status: 'in_progress', conclusion: null }])).toBe('pending')
  expect(ci([{ status: 'in_progress', conclusion: null }, { status: 'completed', conclusion: 'failure' }])).toBe('red')
})

test('owner and repo from https and ssh remotes', () => {
  expect(ownerRepo('https://github.com/o/r')).toEqual({ owner: 'o', repo: 'r' })
  expect(ownerRepo('git@github.com:o/r.git\n')).toEqual({ owner: 'o', repo: 'r' })
  expect(ownerRepo('https://gitlab.com/o/r')).toBe(undefined)
})
