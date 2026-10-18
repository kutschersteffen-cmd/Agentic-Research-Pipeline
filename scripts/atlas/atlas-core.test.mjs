import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  search, buildIndex, neighbourhood, shortestPath, statusLine, githubUrl, resolveWikiLink, notesFor,
} from './atlas-core.mjs';

const node = (id, extra = {}) => ({ id, label: `n${id}`, path: null, community: 0, kind: 'entity', inferredDeg: 0, ...extra });
const chain = (n) => ({
  nodes: Array.from({ length: n }, (_, i) => node(i)),
  links: Array.from({ length: n - 1 }, (_, i) => ({ s: i, t: i + 1, inferred: false })),
});

test('statusLine', () => {
  assert.equal(statusLine({ nodes: 5, edges: 7, inferred: 0 }), '5 nodes · 7 edges · 0 inferred');
  assert.ok(statusLine({ nodes: 5, edges: 7, inferred: 0, hops: 3 }).endsWith(' · 3 hops'));
});

test('neighbourhood is undirected and bounded by hops', () => {
  const g = chain(5);
  assert.equal(neighbourhood(g, 2, 2).size, 5);
  assert.equal(neighbourhood(g, 0, 2).size, 3);
  assert.equal(neighbourhood(g, 4, 2).size, 3);
});

test('shortestPath', () => {
  assert.deepEqual(shortestPath(chain(5), 0, 4), [0, 1, 2, 3, 4]);
  assert.deepEqual(shortestPath(chain(5), 4, 0), [4, 3, 2, 1, 0]);
  const g = { nodes: [node(0), node(1), node(2)], links: [{ s: 0, t: 1, inferred: false }] };
  assert.equal(shortestPath(g, 0, 2), null);
});

test('search_prefers_file_node', () => {
  const g = {
    nodes: [
      node(0, { label: 'ground()', path: 'backend/arp/grounding.py' }),
      node(1, { label: 'grounding.py', path: 'backend/arp/grounding.py', kind: 'file' }),
      node(2), node(3), node(4),
    ],
    links: [{ s: 0, t: 2 }, { s: 0, t: 3 }, { s: 0, t: 4 }],
  };
  const res = search(buildIndex(g), 'ground');
  assert.deepEqual(res.map((n) => n.id), [1, 0]);
});

test('search matches path and is case-insensitive, respects limit', () => {
  const g = { nodes: [node(0, { label: 'x', path: 'backend/arp/Grounding.py' }), node(1)], links: [] };
  assert.deepEqual(search(buildIndex(g), 'GROUNDING').map((n) => n.id), [0]);
  assert.equal(search(buildIndex(chain(50)), 'n', 7).length, 7);
  assert.deepEqual(search(buildIndex(chain(5)), '   '), []);
});

test('github_url_none_for_concept', () => {
  assert.equal(githubUrl(undefined), null);
  assert.equal(githubUrl(null), null);
  assert.equal(githubUrl('backend/arp/grounding.py'),
    'https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/main/backend/arp/grounding.py');
});

test('escapes_labels', () => {
  const g = { nodes: [node(0, { label: '<script>' })], links: [] };
  const idx = buildIndex(g);
  assert.equal(g.nodes[0].label, '<script>');
  const [hit] = search(idx, '<script');
  assert.equal(typeof hit.label, 'string');
  assert.equal(hit.label, '<script>');
});

test('search_10k_under_50ms', () => {
  const nodes = Array.from({ length: 10000 }, (_, i) => node(i, { label: `sym_${i}`, path: `pkg/mod_${i % 300}.py`, kind: i % 10 ? 'entity' : 'file' }));
  const links = Array.from({ length: 30000 }, (_, i) => ({ s: i % 10000, t: (i * 7919) % 10000, inferred: i % 5 === 0 }));
  const idx = buildIndex({ nodes, links });
  search(idx, 'warm');
  const t0 = performance.now();
  for (const q of ['sym_1', 'mod_2', 'zzz', 'y']) search(idx, q);
  assert.ok((performance.now() - t0) / 4 < 50);
});

test('resolveWikiLink', () => {
  assert.deepEqual(resolveWikiLink('other.md', ['other']), { slug: 'other' });
  assert.deepEqual(resolveWikiLink('./other.md#intro', ['other']), { slug: 'other' });
  assert.deepEqual(resolveWikiLink('https://x', ['other']), { external: 'https://x' });
  assert.deepEqual(resolveWikiLink('nope.md', ['other']), { missing: 'nope.md' });
});

test('notesFor', () => {
  const notes = [
    { name: 'ctx-probe', md: '', links: ['backend/arp/grounding.py'] },
    { name: 'other', md: '', links: ['backend/arp/config.py'] },
  ];
  assert.deepEqual(notesFor(notes, 'backend/arp/grounding.py'), ['ctx-probe']);
  assert.deepEqual(notesFor(notes, null), []);
});
