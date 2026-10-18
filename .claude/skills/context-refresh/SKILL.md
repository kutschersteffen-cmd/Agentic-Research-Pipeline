---
name: context-refresh
description: Refresh the codebase context. `/context-refresh` (weekly) updates the OpenWiki in `openwiki/` through a `Context refresh <date>` PR and republishes the Atlas page; `/context-refresh --atlas-only` (daily) republishes the Atlas page only when last night's graph is newer than the page. Use when a scheduled task says `run /context-refresh` or `run /context-refresh --atlas-only`, or when the owner asks for either.
---

You keep the wiki and the Atlas page current. You never merge, and you change only `openwiki/` (by PR)
and the Atlas page.

## 0. Setup (both modes)

Run from the repo root on a checkout of `main`:

```bash
export OPENWIKI_TELEMETRY_DISABLED=1
git fetch --quiet origin +refs/heads/main:refs/remotes/origin/main
[ "$(git rev-parse --is-shallow-repository)" = true ] && git fetch --quiet --unshallow origin main
atlas=$(sed -n 's/^Atlas: //p' .claude/CLAUDE.md)
```

`$atlas` is the Atlas page URL. Read it from that line every run; never hard-code it.

With `--atlas-only`, go to step 5. Otherwise continue with step 1.

## 1. Quiet week (weekly)

The last refresh is the newest commit on `main` that is a refresh merge: its subject contains
`Context refresh` (squash merge) or names a `context-refresh/` branch (merge commit).

```bash
last=$(git log origin/main -1 --format=%H -E --grep='^Context refresh|/context-refresh/')
[ -n "$last" ] && git log "$last"..origin/main --name-only --format= | grep -v -e '^openwiki/' -e '^$'
```

If `$last` is set and the second command prints nothing, every commit since the last refresh touches
only `openwiki/`: say "Quiet week, no refresh" and stop. No PR, no Atlas step (the daily run covers it).
No earlier refresh (first run) is never quiet.

## 2. Branch (weekly)

With the GitHub tools, look for an open PR in this repo whose title starts with `Context refresh`.

- **One is open:** reuse it. Check out its head branch and bring it up to date:
  `git checkout -B <head> origin/<head> && git merge --no-edit origin/main`.
- **None:** `git checkout -B "context-refresh/$(date -u +%F)" origin/main`.

## 3. Update the wiki (weekly)

Ask OpenWiki: "Update this repository's OpenWiki for changes since its last successful run". Follow
the `openwiki` skill's required sequence with mode `update` (mode `init` when `openwiki/quickstart.md`
does not exist yet). If `openwiki_begin` returns `noop`, there is nothing to commit: go to step 5.

The `openwiki_*` tools come from the `openwiki` MCP server in `.mcp.json`; if they are listed only as
deferred names, load them with ToolSearch. If they are missing (OpenWiki was installed after this
session started), say so, skip to step 5, and tell the owner the setup-script snippet in
`.claude/CLAUDE.md` fixes it. Never run the `openwiki` CLI's own agent: it calls a non-Claude model.

## 4. Commit and PR (weekly)

OpenWiki also writes files outside `openwiki/` (`AGENTS.md`, a workflow on `init`). Commit only
`openwiki/`, and never `openwiki/INSTRUCTIONS.md`:

```bash
git add -A openwiki/ && git reset -q -- openwiki/INSTRUCTIONS.md
git diff --cached --quiet || git commit -m "Context refresh $(date -u +%F)"
```

If nothing was staged, open no PR and go to step 5. Otherwise push the branch
(`git push -u origin HEAD`), then with the GitHub tools:

- **Reused PR:** retitle it `Context refresh <YYYY-MM-DD>` (today, UTC).
- **New PR:** base `main`, title `Context refresh <YYYY-MM-DD>` (today, UTC), body: what changed in
  one or two lines, then `risk:low: only generated openwiki/ pages.`

Either way the PR carries the label `risk:low`. One open refresh PR at most.

## 5. Atlas page (both modes)

Build the data from `context-data` and `main`'s `openwiki/`, `notes/` and page files, in
`graphify-out/atlas` (gitignored):

```bash
bash .claude/hooks/fetch-graph.sh   # context-data -> graphify-out/{graph.json,GRAPH_REPORT.md,meta.json}
d=graphify-out/atlas && rm -rf "$d" && mkdir -p "$d/src/openwiki" "$d/src/notes"
git archive origin/main scripts/atlas $(git ls-tree --name-only origin/main openwiki notes) | tar -x -C "$d/src"
python3 "$d/src/scripts/atlas/build_data.py" --graph graphify-out/graph.json --meta graphify-out/meta.json \
  --report graphify-out/GRAPH_REPORT.md --wiki "$d/src/openwiki" --notes "$d/src/notes" --out "$d/out"
cp "$d"/src/scripts/atlas/{index.html,atlas.js,atlas.css,atlas-core.mjs} "$d/out/"
```

Then, with the `Artifact` tool:

1. **Read** the page: `action: "read"`, `url: $atlas`. A publish to a page this session has not read
   is refused.
2. **`--atlas-only` only:** read the published data with `action: "read"`, `url: $atlas`,
   `path: "data/meta.json"`. If its `commit` equals the `commit` in `graphify-out/meta.json`, the page is
   current: say so and stop without publishing.
3. **Publish** with `url: $atlas`, `file_path: graphify-out/atlas/out/index.html`,
   `root: graphify-out/atlas/out`, and

   ```json
   "files": {
     "atlas.js": "atlas.js",
     "atlas.css": "atlas.css",
     "atlas-core.mjs": {"from": "atlas-core.mjs", "contentType": "text/javascript"},
     "data/graph.json": "data/graph.json",
     "data/meta.json": "data/meta.json",
     "data/wiki.json": "data/wiki.json",
     "data/notes.json": "data/notes.json",
     "data/report.md": {"from": "data/report.md", "contentType": "text/markdown"}
   }
   ```

   Leave out `capabilities` and `icon`, so the page keeps the ones it has.

If the publish is refused because a newer version exists, read the page again and publish once more.
On any other failure (no `Atlas:` line, a read or build that fails, a publish refused or not approved,
a second refusal), load `PushNotification` with ToolSearch (`select:PushNotification`) and send
exactly:

```
Atlas not republished: run /context-refresh
```

Never publish without `url`: that would create a second page instead of updating the Atlas.

## Done

Report in one or two lines: quiet week or the PR link (or "no wiki changes"), and the Atlas page's
data commit (first 7 characters of `meta.json` `commit`) or why it was not republished.
