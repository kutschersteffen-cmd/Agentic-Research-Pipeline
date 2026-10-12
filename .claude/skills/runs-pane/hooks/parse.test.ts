import { expect, test } from 'claude-code/testing'

import { parse } from './register'

test('parses arp runs list lines', () => {
  const out = 'abc\tcalibration\trunning\t3/10 done\t$1.25\n\nnot a run line\n'
  expect(parse(out)).toEqual([{ id: 'abc', type: 'calibration', status: 'running', progress: '3/10', cost: '$1.25' }])
})
