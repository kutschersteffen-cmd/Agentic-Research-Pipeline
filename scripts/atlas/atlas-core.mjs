// Pure logic for the Atlas page: search, graph walks, links. No DOM; labels stay plain data.
// Graph shape (from build_data.py): {nodes: [{id, label, path, community, kind, inferredDeg}], links: [{s, t, inferred}]}.
// Adjacency is cached by graph object identity: pass a new graph object per filter state.

const REPO = 'https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/main/';
const adjCache = new WeakMap();

function adjacency(graph) {
  let adj = adjCache.get(graph);
  if (!adj) {
    adj = new Map(graph.nodes.map((n) => [n.id, []]));
    for (const { s, t } of graph.links) {
      adj.get(s)?.push(t);
      adj.get(t)?.push(s);
    }
    adjCache.set(graph, adj);
  }
  return adj;
}

// Entries are pre-sorted (file nodes first, then by degree); search ranks exact-name hits above that order.
export function buildIndex(graph) {
  const adj = adjacency(graph);
  const entries = graph.nodes.map((node) => ({
    node,
    name: node.label.toLowerCase(),
    stem: node.label.toLowerCase().replace(/\.[^.]*$/, ''),
    key: `${node.label}\n${node.path ?? ''}`.toLowerCase(),
    file: node.kind === 'file' ? 0 : 1,
    deg: adj.get(node.id).length,
  }));
  entries.sort((a, b) => a.file - b.file || b.deg - a.deg);
  return { entries };
}

export function search(index, query, limit = 20) {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const exact = [];
  const rest = [];
  // Keep scanning past `limit` so an exact hit late in the order is never cut off.
  for (const e of index.entries) {
    if (e.name === q || e.stem === q) exact.push(e.node);
    else if (rest.length < limit && e.key.includes(q)) rest.push(e.node);
  }
  return exact.concat(rest).slice(0, limit);
}

export function neighbourhood(graph, id, hops) {
  const adj = adjacency(graph);
  const seen = new Set([id]);
  let frontier = [id];
  for (let h = 0; h < hops && frontier.length; h++) {
    const next = [];
    for (const v of frontier) for (const w of adj.get(v) ?? []) if (!seen.has(w)) { seen.add(w); next.push(w); }
    frontier = next;
  }
  return seen;
}

export function shortestPath(graph, a, b) {
  const adj = adjacency(graph);
  if (!adj.has(a) || !adj.has(b)) return null;
  const prev = new Map([[a, null]]);
  const queue = [a];
  for (let i = 0; i < queue.length; i++) {
    const v = queue[i];
    if (v === b) {
      const path = [];
      for (let x = b; x !== null; x = prev.get(x)) path.push(x);
      return path.reverse();
    }
    for (const w of adj.get(v)) if (!prev.has(w)) { prev.set(w, v); queue.push(w); }
  }
  return null;
}

export function statusLine({ nodes, edges, inferred, hops }) {
  const line = `${nodes} nodes · ${edges} edges · ${inferred} inferred`;
  return hops === undefined || hops === null ? line : `${line} · ${hops} hops`;
}

export function githubUrl(path) {
  return path ? REPO + encodeURI(path) : null;
}

export function resolveWikiLink(href, slugs) {
  if (/^([a-z][a-z0-9+.-]*:|\/\/)/i.test(href)) return { external: href };
  const slug = href.split('#')[0].replace(/^\.\//, '').replace(/\.md$/, '');
  return slugs.includes(slug) ? { slug } : { missing: href };
}

// Wiki pages link relative to their own folder (slug `a/b` links `../c.md`); returns the link from the wiki root.
export function relativeTo(href, slug) {
  if (!slug || /^([a-z][a-z0-9+.-]*:|\/\/)/i.test(href)) return href;
  try {
    return decodeURIComponent(new URL(href, `https://wiki.invalid/${slug}`).pathname.slice(1));
  } catch {
    return href;
  }
}

export function notesFor(notes, path) {
  return path ? notes.filter((n) => n.links.includes(path)).map((n) => n.name) : [];
}
