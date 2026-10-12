import { expect, test } from 'claude-code/testing'

import { count } from './register'

test('counts python and js test markers', () => {
  expect(count('def test_a():\n    assert x == 1\n')).toBe(2)
  expect(count("it('works', () => { expect(a).toBe(1) })")).toBe(2)
  expect(count('test.each([1])("x", () => {})')).toBe(1)
  expect(count('# nothing here')).toBe(0)
})
