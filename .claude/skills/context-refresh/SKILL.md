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

The last refresh is the newest commit on `main` that is a refresh merge: a line starting
`Context refresh` (squash merge) or a `Merge pull request #<n> from <owner>/context-refresh/...` subject.

```bash
last=$(git log origin/main -1 --format=%H -E \
  --grep='^Context refresh' --grep='^Merge pull request #[0-9]+ from [^ ]+/context-refresh/')
[ -n "$last" ] && git log "$last"..origin/main --name-only --format= | grep -v -e '^openwiki/' -e '^$'
```

If `$last` is set and the second command prints nothing, every commit since the last refresh touches
only `openwiki/`: say "Quiet week, no refresh" and stop. No PR, no Atlas step (the daily run covers it).
No earlier refresh (first run) is never quiet.

## 2. Branch (weekly)

With the GitHub tools (or `gh` if they are not available), look for an open PR in this repo whose title
starts with `Context refresh` and whose head branch starts with `context-refresh/`. Ignore any other PR.

- **One is open:** reuse it. Fetch its head branch (the clone may be shallow and single-branch), check it
  out and bring it up to date:

  ```bash
  git fetch --quiet origin "+refs/heads/<head>:refs/remotes/origin/<head>"
  git checkout -B <head> origin/<head> && git merge --no-edit origin/main
  ```

- **None:** `git checkout -B "context-refresh/$(date -u +%F)" origin/main`.

## 3. Update the wiki (weekly)

Ask OpenWiki: "Update this repository's OpenWiki for changes since its last successful run". Follow
the `openwiki` skill's required sequence with mode `update` (mode `init` when `openwiki/quickstart.md`
does not exist yet). If `openwiki_begin` returns `noop`, there is nothing new to commit: go on to step 4.

The `openwiki_*` tools come from the `openwiki` MCP server in `.mcp.json`; if they are listed only as
deferred names, load them with ToolSearch. If they are missing (OpenWiki was installed after this
session started), say so, go on to step 4 (a reused PR still gets `main` and today's title), and tell
the owner the setup-script snippet in `.claude/CLAUDE.md` fixes it. Never run the `openwiki` CLI's own agent: it calls a non-Claude model.

## 4. Commit and PR (weekly)

OpenWiki also writes files outside `openwiki/`: it creates or edits root `AGENTS.md` (and `CLAUDE.md` if
one exists), and on `init` adds `.github/workflows/openwiki-update.yml`. Restore the tracked ones and
delete the ones it created (never an untracked `CLAUDE.md`, which OpenWiki only edits), then commit only
`openwiki/`, never `openwiki/INSTRUCTIONS.md`:

```bash
for f in AGENTS.md CLAUDE.md .github/workflows/openwiki-update.yml; do
  if git ls-files --error-unmatch "$f" >/dev/null 2>&1; then git checkout -q HEAD -- "$f"
  elif [ "$f" != CLAUDE.md ]; then rm -f "$f"; fi
done
git add -A openwiki/ && git reset -q -- openwiki/INSTRUCTIONS.md
git diff --cached --quiet || git commit -m "Context refresh $(date -u +%F)"
```

Then, with the GitHub tools (or `gh` if they are not available):

- **Reused PR:** always push the branch (`git push origin HEAD`), even if OpenWiki committed nothing new,
  so it carries the merge of `main`. Retitle it `Context refresh <YYYY-MM-DD>` (today, UTC).
- **New branch, nothing committed:** open no PR; go to step 5.
- **New branch with a commit:** `git push -u origin HEAD`, then open a PR with base `main`, title
  `Context refresh <YYYY-MM-DD>` (today, UTC), body: what changed in one or two lines, then
  `risk:low: only generated openwiki/ pages.`

Either way the PR carries the label `risk:low`. One open refresh PR at most.

## 5. Atlas page (both modes)

Fetch last night's graph, then read the page with the `Artifact` tool (a publish to a page this session
has not read is refused):

```bash
bash .claude/hooks/fetch-graph.sh   # context-data -> graphify-out/{graph.json,GRAPH_REPORT.md,meta.json}
```

1. **Read** the page: `action: "read"`, `url: $atlas`.
2. **`--atlas-only` only:** read the published data with `action: "read"`, `url: $atlas`,
   `path: "data/meta.json"`. If its `commit` equals the `commit` in `graphify-out/meta.json`, the page is
   current: say so and stop. Build and publish nothing.

Build the data from `context-data` and `main`'s `openwiki/`, `notes/` and page files, in
`graphify-out/atlas` (gitignored):

```bash
d=graphify-out/atlas && rm -rf "$d" && mkdir -p "$d/src/openwiki" "$d/src/notes"
git archive origin/main scripts/atlas $(git ls-tree --name-only origin/main openwiki notes) | tar -x -C "$d/src"
python3 "$d/src/scripts/atlas/build_data.py" --graph graphify-out/graph.json --meta graphify-out/meta.json \
  --report graphify-out/GRAPH_REPORT.md --wiki "$d/src/openwiki" --notes "$d/src/notes" --out "$d/out"
cp "$d"/src/scripts/atlas/{index.html,atlas.js,atlas.css,atlas-core.mjs} "$d/out/"
```

Then publish with the `Artifact` tool:

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

If `PushNotification` cannot be loaded, say so in your final message, with that same text.

Never publish without `url`: that would create a second page instead of updating the Atlas.

## Done

Report in one or two lines: quiet week or the PR link (or "no wiki changes"), and the Atlas page's
data commit (first 7 characters of `meta.json` `commit`) or why it was not republished.
