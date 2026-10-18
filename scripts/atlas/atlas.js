// Atlas page: wires atlas-core (pure logic) to the DOM and a sigma graph. Labels go in via textContent only;
// Markdown goes through marked then DOMPurify. Node ids change between rebuilds, so nothing persists them.
import {
  buildIndex, search, neighbourhood, shortestPath, statusLine, githubUrl, resolveWikiLink, notesFor,
} from './atlas-core.mjs';

const COLLAPSE_OVER = 2000; // whole-repo view shows areas instead of nodes above this many nodes
const LIST_CAP = 50;
const KIND = { file: 'File', entity: 'Symbol', doc: 'Doc' };
const phoneQuery = matchMedia('(max-width: 1023.98px)');

const $ = (id) => document.getElementById(id);
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}

const state = {
  tab: 'explore', view: 'whole', sel: null, area: null, pathFrom: null, pathTo: null,
  filters: { code: true, docs: true, inferred: false },
};
let G = null; let index = null; let wikiPages = []; let notes = [];
let areaInfo = new Map(); // community id -> {label, sub, size, slot}
let renderer = null; let dashed = [];
let askPanel = null;

// ---------- data ----------
async function getJson(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

async function load() {
  const [graph, meta, wiki, notesData, report] = await Promise.all([
    getJson('data/graph.json'), getJson('data/meta.json'), getJson('data/wiki.json'), getJson('data/notes.json'),
    fetch('data/report.md').then((r) => (r.ok ? r.text() : '')),
  ]);
  G = graph;
  index = buildIndex(G);
  wikiPages = wiki.pages || [];
  notes = notesData.notes || [];
  runSearch($('q'), $('results'), pickFromSearch);
  showMeta(meta);
  // Search is live now; the heavier graph work waits a frame so results paint first.
  setTimeout(() => {
    buildAreas();
    renderLeft();
    renderWikiIndex();
    renderMarkdown($('report'), report || '# Graph report\n\nNo report in this data.', null);
    renderGraph();
    setupAsk();
  }, 0);
}

function showMeta(meta) {
  $('meta-commit').textContent = meta.commit ? String(meta.commit).slice(0, 7) : 'unknown';
  $('meta-built').textContent = meta.built_at || 'unknown';
  $('meta-docs').textContent = meta.docs_built_at || 'not yet';
}

// One graph object per filter state: atlas-core caches adjacency by object identity.
const filteredCache = new Map();
function fg() {
  const { code, docs, inferred } = state.filters;
  const key = `${code}|${docs}|${inferred}`;
  let g = filteredCache.get(key);
  if (!g) {
    const ok = new Uint8Array(G.nodes.length);
    const nodes = G.nodes.filter((n) => (n.kind === 'doc' ? docs : code));
    for (const n of nodes) ok[n.id] = 1;
    const links = G.links.filter((l) => ok[l.s] && ok[l.t] && (inferred || !l.inferred));
    const deg = new Uint32Array(G.nodes.length);
    for (const l of links) { deg[l.s]++; deg[l.t]++; }
    g = { nodes, links, ok, deg };
    filteredCache.set(key, g);
  }
  return g;
}

function buildAreas() {
  const top = new Map();
  for (const e of index.entries) {
    const c = e.node.community;
    if (c !== null && c !== undefined && (!top.has(c) || e.deg > top.get(c).deg)) top.set(c, e);
  }
  const bySize = [...G.communities].sort((a, b) => b.size - a.size || a.id - b.id);
  bySize.forEach((c, i) => {
    const generic = /^Community \d+$/.test(c.label);
    const hub = top.get(c.id);
    areaInfo.set(c.id, {
      id: c.id, size: c.size, slot: i < 8 ? i + 1 : 0,
      label: generic && hub ? hub.node.label : c.label,
      sub: generic ? c.label : '',
    });
  });
}

function areaColorVar(c) {
  const a = areaInfo.get(c);
  return a && a.slot ? `var(--c${a.slot})` : 'var(--c-other)';
}

// ---------- search ----------
function runSearch(input, list, onPick) {
  const q = input.value.trim();
  list.replaceChildren();
  if (!q) { list.hidden = true; return; }
  list.hidden = false;
  if (!index) { list.append(el('li', 'r-empty', 'Loading graph…')); return; }
  const hits = search(index, q, 20);
  if (!hits.length) { list.append(el('li', 'r-empty', `No file or symbol matches “${q}”.`)); return; }
  for (const n of hits) {
    const li = el('li');
    li.setAttribute('data-atlas-result', '');
    const b = el('button', 'result');
    b.type = 'button';
    const sw = el('span', 'swatch');
    sw.style.background = areaColorVar(n.community);
    b.append(sw, el('span', 'r-label', n.label), el('span', 'r-kind', KIND[n.kind] || n.kind));
    if (n.path) b.append(el('span', 'r-path', n.path));
    b.addEventListener('click', () => onPick(n));
    li.append(b);
    list.append(li);
  }
}

function wireSearch(input, list, onPick) {
  input.addEventListener('input', () => runSearch(input, list, onPick));
  input.addEventListener('focus', () => { if (input.value.trim()) runSearch(input, list, onPick); });
  input.addEventListener('keydown', (e) => {
    const first = list.querySelector('button');
    if (e.key === 'ArrowDown' && first) { e.preventDefault(); first.focus(); }
    if (e.key === 'Enter' && first) { e.preventDefault(); first.click(); }
    if (e.key === 'Escape') list.hidden = true;
  });
  list.addEventListener('keydown', (e) => {
    const items = [...list.querySelectorAll('button')];
    const i = items.indexOf(document.activeElement);
    if (e.key === 'ArrowDown' && i < items.length - 1) { e.preventDefault(); items[i + 1].focus(); }
    if (e.key === 'ArrowUp') { e.preventDefault(); (i > 0 ? items[i - 1] : input).focus(); }
    if (e.key === 'Escape') { list.hidden = true; input.focus(); }
  });
  document.addEventListener('click', (e) => {
    if (!input.parentElement.contains(e.target)) list.hidden = true;
  });
}

function pickFromSearch(n) {
  $('results').hidden = true;
  setTab('explore');
  select(n.id);
  if (phoneQuery.matches) $('right').scrollIntoView({ block: 'start' });
}

// ---------- selection and detail ----------
function markSelection() {
  $('view-explore').classList.toggle('has-selection', state.sel !== null || state.area !== null);
  $('view-explore').classList.toggle('has-node', state.sel !== null);
}

function select(id) {
  state.sel = id;
  state.area = null;
  markSelection();
  renderDetail();
  renderGraph();
}

function selectArea(cid) {
  state.area = cid;
  state.sel = null;
  markSelection();
  renderDetail();
  renderGraph();
}

function nodeButton(n, extra) {
  const li = el('li');
  const b = el('button');
  b.type = 'button';
  const sw = el('span', 'swatch');
  sw.style.background = areaColorVar(n.community);
  const text = el('span', 'l-text', n.label);
  if (n.path && n.path !== n.label) text.append(el('span', 'l-sub', n.path));
  b.append(sw, text);
  if (extra !== undefined) b.append(el('span', 'l-num', extra));
  b.addEventListener('click', () => select(n.id));
  li.append(b);
  return li;
}

function fillNodeList(list, nodes, countEl) {
  list.replaceChildren();
  if (countEl) countEl.textContent = nodes.length ? String(nodes.length) : '';
  if (!nodes.length) { list.append(el('li', 'more', 'None with the current filters.')); return; }
  for (const n of nodes.slice(0, LIST_CAP)) list.append(nodeButton(n));
  if (nodes.length > LIST_CAP) list.append(el('li', 'more', `and ${nodes.length - LIST_CAP} more`));
}

function neighbours(id) {
  const g = fg();
  const usedBy = new Set(); const uses = new Set();
  for (const l of g.links) {
    if (l.t === id && l.s !== id) usedBy.add(l.s);
    if (l.s === id && l.t !== id) uses.add(l.t);
  }
  const order = (a, b) => (a.kind === 'file' ? 0 : 1) - (b.kind === 'file' ? 0 : 1) || a.label.localeCompare(b.label);
  return {
    usedBy: [...usedBy].map((i) => G.nodes[i]).sort(order),
    uses: [...uses].map((i) => G.nodes[i]).sort(order),
  };
}

function areaName(c) {
  const a = areaInfo.get(c);
  if (!a) return 'No area';
  return a.sub ? `${a.label} (${a.sub})` : a.label;
}

function renderDetail() {
  const empty = state.sel === null && state.area === null;
  $('detail-empty').hidden = !empty;
  $('detail').hidden = state.sel === null;
  $('area-detail').hidden = state.area === null;
  if (state.area !== null) renderAreaDetail();
  if (state.sel === null) return;
  const n = G.nodes[state.sel];
  $('d-kind').textContent = KIND[n.kind] || n.kind;
  $('d-label').textContent = n.label;
  $('d-path').textContent = n.path || 'No source file';
  $('d-swatch').style.background = areaColorVar(n.community);
  $('d-area').textContent = areaName(n.community);
  const gh = githubUrl(n.path);
  $('d-github').hidden = !gh;
  if (gh) $('d-github').href = gh;
  renderExcerpt(n);
  const { usedBy, uses } = neighbours(n.id);
  fillNodeList($('d-usedby'), usedBy, $('d-usedby-count'));
  fillNodeList($('d-uses'), uses, $('d-uses-count'));
  renderNotes(n);
  if (askPanel) askPanel.update();
}

function renderAreaDetail() {
  const a = areaInfo.get(state.area);
  $('a-swatch').style.background = areaColorVar(state.area);
  $('a-label').textContent = areaName(state.area);
  $('a-size').textContent = `${a ? a.size : 0} nodes`;
  const g = fg();
  const members = g.nodes.filter((n) => n.community === state.area).sort((x, y) => g.deg[y.id] - g.deg[x.id]);
  const list = $('a-members');
  list.replaceChildren();
  for (const n of members.slice(0, 20)) list.append(nodeButton(n, String(g.deg[n.id])));
}

function wikiPageFor(n) {
  if (!n.path) return null;
  return wikiPages.find((p) => p.md.includes(n.path)) || null;
}

function renderExcerpt(n) {
  const box = $('d-wiki');
  box.replaceChildren();
  const page = wikiPageFor(n);
  if (!page) {
    box.append(el('p', 'muted', wikiPages.length
      ? 'No wiki page mentions this file.'
      : 'No wiki pages in this data yet. They appear after the first /context-refresh.'));
    return;
  }
  const paras = window.marked.lexer(page.md).filter((t) => t.type === 'paragraph');
  const para = paras.find((t) => t.raw.includes(n.path)) || paras[0];
  const div = el('div');
  if (para) renderMarkdown(div, para.raw, page.slug);
  const more = el('button', 'linkish', `Read “${page.title}” in the wiki`);
  more.type = 'button';
  more.addEventListener('click', () => { setTab('wiki'); showWiki(page.slug); });
  box.append(div, more);
}

function renderNotes(n) {
  const box = $('d-notes');
  box.replaceChildren();
  const names = notesFor(notes, n.path);
  if (!names.length) { box.append(el('p', 'muted', 'No notes link here.')); return; }
  for (const name of names) {
    const note = notes.find((x) => x.name === name);
    const d = el('details', 'note');
    d.append(el('summary', null, name));
    const body = el('div', 'prose');
    renderMarkdown(body, note.md, null);
    d.append(body);
    box.append(d);
  }
}

// ---------- left pane ----------
function renderLeft() {
  const g = fg();
  const hubs = $('hubs');
  hubs.replaceChildren();
  const top = g.nodes.slice().sort((a, b) => g.deg[b.id] - g.deg[a.id]).slice(0, 10);
  for (const n of top) hubs.append(nodeButton(n, String(g.deg[n.id])));

  const areas = $('areas');
  areas.replaceChildren();
  const counts = new Map();
  for (const n of g.nodes) counts.set(n.community, (counts.get(n.community) || 0) + 1);
  const list = [...areaInfo.values()].filter((a) => counts.get(a.id)).sort((a, b) => counts.get(b.id) - counts.get(a.id));
  $('area-count').textContent = String(list.length);
  for (const a of list) {
    const li = el('li');
    const b = el('button');
    b.type = 'button';
    if (state.area === a.id) b.setAttribute('aria-current', 'true');
    const sw = el('span', 'swatch');
    sw.style.background = areaColorVar(a.id);
    const text = el('span', 'l-text', a.label);
    if (a.sub) text.append(el('span', 'l-sub', a.sub));
    b.append(sw, text, el('span', 'l-num', String(counts.get(a.id))));
    b.addEventListener('click', () => selectArea(a.id));
    li.append(b);
    areas.append(li);
  }
}

// ---------- graph ----------
function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
function areaColor(c) {
  const a = areaInfo.get(c);
  return css(a && a.slot ? `--c${a.slot}` : '--c-other');
}

let wholeLayout = null; // positions cached once so filter toggles do not reshuffle the map
function layoutWhole(collapsed) {
  if (wholeLayout && wholeLayout.collapsed === collapsed) return wholeLayout.pos;
  const Graph = window.graphology.Graph || window.graphology;
  const g = new Graph({ type: 'undirected' });
  const keyOf = (id) => (collapsed ? G.nodes[id].community : id);
  const items = collapsed ? [...areaInfo.values()].map((a) => [a.id, a.size]) : G.nodes.map((n) => [n.id, 1]);
  // Phyllotaxis start, biggest first, so the layout is the same on every load.
  items.sort((a, b) => b[1] - a[1]).forEach(([k, size], i) => {
    const r = Math.sqrt(i + 1) * 10; const t = i * 2.39996;
    g.addNode(k, { x: r * Math.cos(t), y: r * Math.sin(t), size: Math.sqrt(size) });
  });
  for (const l of G.links) {
    const a = keyOf(l.s); const b = keyOf(l.t);
    if (a === null || a === undefined || b === null || b === undefined || a === b || !g.hasNode(a) || !g.hasNode(b)) continue;
    if (g.hasEdge(a, b)) g.updateEdgeAttribute(a, b, 'weight', (w) => w + 1);
    else g.addEdge(a, b, { weight: 1 });
  }
  const fa2 = window.graphologyLibrary && window.graphologyLibrary.layoutForceAtlas2;
  if (fa2) {
    const settings = { ...fa2.inferSettings(g), edgeWeightInfluence: 0.5, adjustSizes: false };
    fa2.assign(g, { iterations: collapsed ? 150 : 100, settings });
  }
  const pos = new Map();
  g.forEachNode((k, a) => pos.set(String(k), { x: a.x, y: a.y }));
  wholeLayout = { collapsed, pos };
  return pos;
}

// Ring 1 sorted by area, each given an arc in proportion to its ring-2 children, which sit inside that arc.
function radialTree(center, ring1, kids) {
  const pos = new Map([[center, { x: 0, y: 0 }]]);
  const polar = (r, t) => ({ x: r * Math.cos(t), y: r * Math.sin(t) });
  const weight = (id) => Math.max(1, (kids.get(id) || []).length);
  const total = ring1.reduce((t, id) => t + weight(id), 0);
  let start = 0;
  for (const id of ring1) {
    const span = (2 * Math.PI * weight(id)) / total;
    const ch = kids.get(id) || [];
    pos.set(id, polar(1, start + span / 2));
    ch.forEach((c, i) => pos.set(c, polar(2, start + (span * (i + 0.5)) / ch.length)));
    start += span;
  }
  return pos;
}

function viewMode() {
  if (phoneQuery.matches) return state.sel === null ? null : 'one';
  return state.view;
}

function renderGraph() {
  if (!G || !areaInfo.size) return;
  const g = fg();
  const mode = viewMode();
  const empty = $('graph-empty');
  empty.hidden = true;
  $('path-list').hidden = true;
  let nodes = []; let edges = []; let status = ''; let note = '';
  const pos = new Map();
  const sizes = new Map();

  if (mode === 'whole') {
    const inferredCount = g.links.reduce((k, l) => k + (l.inferred ? 1 : 0), 0);
    status = statusLine({ nodes: g.nodes.length, edges: g.links.length, inferred: inferredCount });
    if (g.nodes.length > COLLAPSE_OVER) {
      ({ nodes, edges } = collapsedView(g, pos, sizes));
      note = `· ${nodes.length} areas shown; pick a node for 2 hops`;
    } else {
      const p = layoutWhole(false);
      nodes = g.nodes.map((n) => `n${n.id}`);
      for (const n of g.nodes) { pos.set(`n${n.id}`, p.get(String(n.id))); sizes.set(`n${n.id}`, 2 + Math.sqrt(g.deg[n.id])); }
      edges = g.links.map((l) => ({ a: `n${l.s}`, b: `n${l.t}`, inferred: l.inferred, w: 1 }));
    }
  } else if (mode === 'hops' || mode === 'one') {
    if (state.sel === null) {
      empty.textContent = 'Pick a node first: search, click a hub, or click a node in the graph.';
      empty.hidden = false;
    } else {
      const hops = mode === 'hops' ? 2 : 1;
      const set = neighbourhood(g, state.sel, hops);
      const ring1 = [...neighbourhood(g, state.sel, 1)].filter((id) => id !== state.sel);
      ring1.sort((a, b) => (G.nodes[a].community ?? -1) - (G.nodes[b].community ?? -1) || a - b);
      const inner = new Set(ring1);
      const parent = new Map(); // ring-2 node -> the first ring-1 node linking to it
      const kids = new Map();
      const sub = g.links.filter((l) => set.has(l.s) && set.has(l.t));
      for (const l of sub) {
        for (const [p, c] of [[l.s, l.t], [l.t, l.s]]) {
          if (inner.has(p) && !inner.has(c) && c !== state.sel && !parent.has(c)) {
            parent.set(c, p);
            if (!kids.has(p)) kids.set(p, []);
            kids.get(p).push(c);
          }
        }
      }
      const p = radialTree(state.sel, ring1, kids);
      for (const id of set) {
        const k = `n${id}`;
        nodes.push(k);
        pos.set(k, p.get(id));
        sizes.set(k, id === state.sel ? 14 : inner.has(id) ? 7 : 3.5);
      }
      // A big neighbourhood drawn in full is a solid disc: draw the tree (centre spokes, one parent link per
      // outer node) and still count every edge in the status line.
      const tree = (l) => l.s === state.sel || l.t === state.sel || parent.get(l.t) === l.s || parent.get(l.s) === l.t;
      const drawn = sub.length > 1500 ? sub.filter(tree) : sub;
      if (drawn.length < sub.length) note = `· drawn as a tree, ${sub.length - drawn.length} cross links hidden`;
      edges = drawn.map((l) => ({ a: `n${l.s}`, b: `n${l.t}`, inferred: l.inferred, w: 1 }));
      status = statusLine({ nodes: set.size, edges: sub.length, inferred: sub.filter((l) => l.inferred).length });
    }
  } else if (mode === 'path') {
    ({ nodes, edges, status } = pathView(g, pos, sizes));
  }

  $('status').textContent = status || ' ';
  $('status-note').textContent = note;
  mountSigma(nodes, edges, pos, sizes);
}

function collapsedView(g, pos, sizes) {
  const p = layoutWhole(true);
  const count = new Map();
  for (const n of g.nodes) if (n.community !== null) count.set(n.community, (count.get(n.community) || 0) + 1);
  const agg = new Map();
  for (const l of g.links) {
    const a = G.nodes[l.s].community; const b = G.nodes[l.t].community;
    if (a === null || b === null || a === b) continue;
    const k = a < b ? `${a}|${b}` : `${b}|${a}`;
    const e = agg.get(k) || { a: `c${Math.min(a, b)}`, b: `c${Math.max(a, b)}`, w: 0, extracted: 0 };
    e.w++;
    if (!l.inferred) e.extracted++;
    agg.set(k, e);
  }
  const nodes = [];
  for (const [c, k] of count) {
    nodes.push(`c${c}`);
    pos.set(`c${c}`, p.get(String(c)));
    sizes.set(`c${c}`, 3 + Math.sqrt(k) * 0.9);
  }
  const edges = [...agg.values()].map((e) => ({ a: e.a, b: e.b, w: e.w, inferred: e.extracted === 0 }));
  return { nodes, edges };
}

function pathView(g, pos, sizes) {
  const empty = $('graph-empty');
  if (state.pathFrom === null || state.pathTo === null) {
    empty.textContent = 'Choose a start and an end node above to see the shortest path between them.';
    empty.hidden = false;
    return { nodes: [], edges: [], status: '' };
  }
  const path = shortestPath(g, state.pathFrom, state.pathTo);
  if (!path) {
    empty.textContent = `No path from ${G.nodes[state.pathFrom].label} to ${G.nodes[state.pathTo].label} with the current filters.`;
    empty.hidden = false;
    return { nodes: [], edges: [], status: statusLine({ nodes: 0, edges: 0, inferred: 0, hops: 0 }) };
  }
  const edges = [];
  let inferred = 0;
  for (let i = 0; i + 1 < path.length; i++) {
    const a = path[i]; const b = path[i + 1];
    // An extracted link wins when both kinds join the pair, matching what the view would draw.
    const between = g.links.filter((l) => (l.s === a && l.t === b) || (l.s === b && l.t === a));
    const inf = between.every((l) => l.inferred);
    if (inf) inferred++;
    edges.push({ a: `n${a}`, b: `n${b}`, inferred: inf, w: 1 });
  }
  path.forEach((id, i) => {
    pos.set(`n${id}`, { x: i, y: i % 2 ? 0.35 : 0 });
    sizes.set(`n${id}`, i === 0 || i === path.length - 1 ? 12 : 8);
  });
  const list = $('path-list');
  list.replaceChildren();
  for (const id of path) {
    const li = el('li');
    const b = el('button', null, G.nodes[id].label);
    b.type = 'button';
    b.title = G.nodes[id].path || '';
    b.addEventListener('click', () => select(id));
    li.append(b);
    list.append(li);
  }
  list.hidden = false;
  return {
    nodes: path.map((id) => `n${id}`), edges,
    status: statusLine({ nodes: path.length, edges: path.length - 1, inferred, hops: path.length - 1 }),
  };
}

function mountSigma(nodes, edges, pos, sizes) {
  if (renderer) { renderer.kill(); renderer = null; }
  dashed = [];
  clearDashes();
  if (!nodes.length || !window.Sigma) return;
  const Graph = window.graphology.Graph || window.graphology;
  const SigmaCtor = window.Sigma.Sigma || window.Sigma.default || window.Sigma;
  const g = new Graph({ type: 'undirected', multi: false });
  const accent = css('--accent');
  const edgeColor = css('--edge');
  const selKey = state.sel === null ? null : `n${state.sel}`;
  const selArea = state.sel !== null ? G.nodes[state.sel].community : state.area;
  for (const k of nodes) {
    const isArea = k[0] === 'c';
    const id = Number(k.slice(1));
    const label = isArea ? areaInfo.get(id)?.label ?? k : G.nodes[id].label;
    const p = pos.get(k) || { x: 0, y: 0 };
    const isSel = k === selKey || (isArea && id === selArea);
    g.addNode(k, {
      x: p.x, y: p.y, label, size: sizes.get(k) || 4,
      color: isSel ? accent : areaColor(isArea ? id : G.nodes[id].community),
      zIndex: isSel ? 2 : 1, forceLabel: isSel,
    });
  }
  const maxW = Math.max(1, ...edges.map((e) => e.w));
  for (const e of edges) {
    if (e.inferred) { dashed.push(e); continue; }
    if (!g.hasEdge(e.a, e.b)) g.addEdge(e.a, e.b, { size: 0.5 + 2 * Math.log1p(e.w) / Math.log1p(maxW), color: edgeColor });
  }
  renderer = new SigmaCtor(g, $('graph'), {
    allowInvalidContainer: true,
    labelFont: '"IBM Plex Sans", sans-serif',
    labelSize: 12,
    labelWeight: '500',
    labelColor: { color: css('--ink') },
    labelRenderedSizeThreshold: 6,
    defaultEdgeColor: edgeColor,
    zIndex: true,
  });
  renderer.on('clickNode', ({ node }) => {
    const id = Number(node.slice(1));
    if (node[0] === 'c') selectArea(id); else select(id);
  });
  renderer.on('afterRender', drawDashes);
  renderer.getCamera().setState({ ratio: 1.15 }); // room for the outermost labels
  drawDashes();
}

function clearDashes() {
  const c = $('dashes');
  c.getContext('2d').clearRect(0, 0, c.width, c.height);
}

// Sigma 2 has no dashed edge program, so INFERRED edges are drawn on a 2D canvas over the WebGL layer.
function drawDashes() {
  const c = $('dashes');
  const dpr = window.devicePixelRatio || 1;
  const w = c.clientWidth; const h = c.clientHeight;
  if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); }
  const ctx = c.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  if (!renderer || !dashed.length) return;
  ctx.strokeStyle = css('--muted');
  ctx.globalAlpha = 0.5;
  ctx.lineWidth = 1.25;
  ctx.setLineDash([4, 3]);
  ctx.beginPath();
  for (const e of dashed) {
    const a = renderer.getNodeDisplayData(e.a); const b = renderer.getNodeDisplayData(e.b);
    if (!a || !b) continue;
    const pa = renderer.framedGraphToViewport(a); const pb = renderer.framedGraphToViewport(b);
    ctx.moveTo(pa.x, pa.y);
    ctx.lineTo(pb.x, pb.y);
  }
  ctx.stroke();
}

// ---------- views, tabs, filters ----------
function setView(v) {
  state.view = v;
  for (const b of document.querySelectorAll('[data-view]')) b.setAttribute('aria-pressed', String(b.dataset.view === v));
  $('pathbar').hidden = v !== 'path';
  if (v === 'path') {
    if (state.pathFrom === null && state.sel !== null) {
      state.pathFrom = state.sel;
      $('path-from').value = G.nodes[state.sel].path || G.nodes[state.sel].label;
    }
    (state.pathFrom === null ? $('path-from') : $('path-to')).focus();
  }
  renderGraph();
}

function setTab(t) {
  state.tab = t;
  for (const b of document.querySelectorAll('[data-tab]')) b.setAttribute('aria-pressed', String(b.dataset.tab === t));
  $('view-explore').hidden = t !== 'explore';
  $('view-wiki').hidden = t !== 'wiki';
  $('view-report').hidden = t !== 'report';
  $('view-ask').hidden = t !== 'ask';
  if (askPanel) askPanel.place();
  if (t === 'explore') renderGraph();
  if (t === 'wiki' && !$('wiki-page').childElementCount) showWiki(wikiPages[0]?.slug ?? null);
}

function onFilters() {
  state.filters = { code: $('f-code').checked, docs: $('f-docs').checked, inferred: $('f-inferred').checked };
  renderLeft();
  renderDetail();
  renderGraph();
}

// ---------- markdown, wiki, report ----------
function renderMarkdown(target, md, slug) {
  target.innerHTML = window.DOMPurify.sanitize(window.marked.parse(md));
  for (const a of target.querySelectorAll('a[href]')) {
    const href = a.getAttribute('href');
    if (href.startsWith('#')) { a.addEventListener('click', (e) => e.preventDefault()); continue; }
    const link = resolveWikiLink(relativeTo(href, slug), wikiPages.map((p) => p.slug));
    if (link.external) { a.target = '_blank'; a.rel = 'noopener noreferrer'; continue; }
    a.addEventListener('click', (e) => {
      e.preventDefault();
      setTab('wiki');
      if (link.slug !== undefined) showWiki(link.slug); else showNotFound(link.missing);
    });
  }
}

// Wiki pages link relative to their own folder; resolve before matching slugs.
function relativeTo(href, slug) {
  if (!slug || /^([a-z][a-z0-9+.-]*:|\/\/)/i.test(href)) return href;
  try { return decodeURI(new URL(href, `https://wiki.invalid/${slug}`).pathname.slice(1)); } catch { return href; }
}

function renderWikiIndex() {
  const list = $('wiki-index');
  list.replaceChildren();
  for (const p of wikiPages) {
    const li = el('li');
    const b = el('button', null, p.title);
    b.type = 'button';
    b.dataset.slug = p.slug;
    b.addEventListener('click', () => showWiki(p.slug));
    li.append(b);
    list.append(li);
  }
}

function showWiki(slug) {
  const page = wikiPages.find((p) => p.slug === slug);
  const box = $('wiki-page');
  for (const b of $('wiki-index').querySelectorAll('button')) b.setAttribute('aria-current', String(b.dataset.slug === slug));
  if (!page) {
    box.replaceChildren(el('h1', null, 'Wiki'), el('p', 'muted', wikiPages.length
      ? 'Pick a page on the left.'
      : 'No wiki pages in this data yet. They appear after the first /context-refresh.'));
    return;
  }
  renderMarkdown(box, page.md, page.slug);
  box.scrollTop = 0;
}

function showNotFound(href) {
  const box = $('wiki-page');
  const p = el('div', 'not-found');
  p.append(el('h1', null, 'Page not found'), el('p', null, `No wiki page matches “${href}”. Pick one from the list.`));
  box.replaceChildren(p);
}

// ---------- ask Claude ----------
async function setupAsk() {
  if (location.hash.includes('noask')) return;
  const claude = window.claude;
  if (!claude || typeof claude.use !== 'function') return;
  let sample = null;
  try { sample = await claude.use('sample'); } catch { sample = null; }
  if (!sample || location.hash.includes('noask')) return;
  askPanel = makeAskPanel(sample);
}

function makeAskPanel(sample) {
  const panel = el('div', 'ask');
  panel.id = 'ask-panel';
  const ctxLine = el('p', 'ask-context');
  const label = el('label', 'sr-only', 'Question for Claude');
  label.htmlFor = 'ask-q';
  const box = el('textarea');
  box.id = 'ask-q';
  box.placeholder = 'What does this do?';
  const row = el('div', 'ask-row');
  const go = el('button', 'primary', 'Ask');
  go.type = 'button';
  const stop = el('button', null, 'Stop');
  stop.type = 'button';
  stop.hidden = true;
  const answer = el('div', 'ask-answer');
  answer.setAttribute('aria-live', 'polite');
  row.append(go, stop);
  panel.append(ctxLine, label, box, row, answer);
  panel.hidden = true;

  const btn = el('button', 'ask-btn', 'Ask Claude about this');
  btn.type = 'button';
  btn.addEventListener('click', () => { panel.hidden = !panel.hidden; if (!panel.hidden) box.focus(); });
  $('d-github').parentElement.append(btn);

  const tab = el('button', 'tab', 'Ask');
  tab.type = 'button';
  tab.dataset.tab = 'ask';
  tab.setAttribute('aria-pressed', 'false');
  tab.addEventListener('click', () => setTab('ask'));
  document.querySelector('.tabs').append(tab);

  let ctl = null;
  stop.addEventListener('click', () => ctl?.abort());
  go.addEventListener('click', async () => {
    if (state.sel === null || !box.value.trim()) return;
    ctl = new AbortController();
    go.disabled = true;
    stop.hidden = false;
    answer.textContent = 'Thinking…';
    try {
      await sample(askPrompt(G.nodes[state.sel], box.value.trim()), {
        signal: ctl.signal, onText: ({ text }) => { answer.textContent = text; },
      });
    } catch (e) {
      answer.textContent = e.text || ASK_ERRORS[e.code] || `Claude could not answer (${e.code || 'error'}). Ask again in a moment.`;
    } finally {
      go.disabled = false;
      stop.hidden = true;
    }
  });

  const api = {
    update() {
      const n = state.sel === null ? null : G.nodes[state.sel];
      ctxLine.textContent = n ? `About ${n.path || n.label}` : 'Select a file or symbol first.';
      go.disabled = !n;
    },
    place() {
      const onPhoneTab = state.tab === 'ask';
      const home = onPhoneTab ? $('view-ask') : $('detail');
      if (panel.parentElement !== home) {
        if (onPhoneTab) home.append(panel); else $('d-github').parentElement.after(panel);
      }
      if (onPhoneTab) panel.hidden = false;
    },
  };
  api.update();
  api.place();
  return api;
}

const ASK_ERRORS = {
  not_granted: 'Asking Claude was declined for this page view.',
  rate_limited: 'Too many questions at once. Wait a minute, then ask again.',
  cancelled: 'Stopped.',
};

function askPrompt(n, question) {
  const { usedBy, uses } = neighbours(n.id);
  const page = wikiPageFor(n);
  const name = (x) => (x.path && x.path !== x.label ? `${x.label} (${x.path})` : x.label);
  return [
    'Answer a question about one part of the Agentic-Research-Pipeline codebase. Use only the context below;',
    'say so when it does not cover the question. Answer in plain text, under 200 words, and name the file.',
    '',
    `Selected: ${n.label} (${KIND[n.kind] || n.kind})`,
    `File: ${n.path || 'none'}`,
    `Area: ${areaName(n.community)}`,
    `Used by: ${usedBy.slice(0, 30).map(name).join(', ') || 'nothing'}`,
    `Uses: ${uses.slice(0, 30).map(name).join(', ') || 'nothing'}`,
    '',
    page ? `Wiki page "${page.title}":\n${page.md.slice(0, 40000)}` : 'No wiki page covers this file.',
    '',
    `Question: ${question}`,
  ].join('\n');
}

// ---------- boot ----------
wireSearch($('q'), $('results'), pickFromSearch);
wireSearch($('path-from'), $('path-from-results'), (n) => {
  state.pathFrom = n.id; $('path-from').value = n.path || n.label; $('path-from-results').hidden = true; renderGraph();
});
wireSearch($('path-to'), $('path-to-results'), (n) => {
  state.pathTo = n.id; $('path-to').value = n.path || n.label; $('path-to-results').hidden = true; renderGraph();
});
for (const b of document.querySelectorAll('[data-view]')) b.addEventListener('click', () => setView(b.dataset.view));
for (const b of document.querySelectorAll('.tabs [data-tab]')) b.addEventListener('click', () => setTab(b.dataset.tab));
for (const id of ['f-code', 'f-docs', 'f-inferred']) $(id).addEventListener('change', onFilters);
$('zoom-in').addEventListener('click', () => renderer?.getCamera().animatedZoom({ duration: 200 }));
$('zoom-out').addEventListener('click', () => renderer?.getCamera().animatedUnzoom({ duration: 200 }));
$('zoom-reset').addEventListener('click', () => renderer?.getCamera().animatedReset({ duration: 200 }));
phoneQuery.addEventListener('change', () => { if (askPanel) askPanel.place(); renderGraph(); });
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', renderGraph);
new MutationObserver(renderGraph).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

load().catch((err) => {
  const box = $('load-error');
  box.textContent = `The Atlas data did not load (${err.message}). Reload the page; if it keeps failing, republish with /context-refresh.`;
  box.hidden = false;
  $('status').textContent = 'No graph data.';
});
