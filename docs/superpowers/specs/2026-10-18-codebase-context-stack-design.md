# Codebase context stack: Graphify + OpenWiki + Obsidian + Atlas page

Status: draft for owner approval · 2026-10-18
Source brief: the owner's doc "Codebase Context Stack: Graphify + OpenWiki + Obsidian"
(claude.ai artifact 2ZXu36Gky3UcZck7STkBPJ). Mockups: claude.ai artifact LpT9iVAaTGbn7kkCVRiXJY.

## Why

Coding agents in this repo start every cloud session in a fresh container and rediscover the codebase by
grepping and opening files. That costs tokens and gives inconsistent context from session to session. The
owner also has no way to *see* the codebase's shape from a laptop or a phone.

The stack gives each kind of question one source:

- **OpenWiki** (`openwiki/`): how and why things work, with evidence back to source lines.
- **Graphify** graph: what calls, imports or references what. Built once a day from `main`.
- **`notes/`**: decisions written by people. They win over the wiki where they conflict.
- **Atlas page**: one private claude.ai page that shows graph + wiki + notes, usable on a laptop, a phone
  and inside the Claude app.
- **Obsidian**: the repo root opened as a vault on the owner's laptop, for reading and editing notes.

## Goals

1. Agents read in a fixed order (wiki → graph → notes → source) and get the tools and the graph in every
   cloud session with no manual step.
2. The graph is rebuilt automatically once a day from `main` (code), with doc nodes refreshed weekly.
3. The wiki is refreshed weekly through a PR the owner reviews; quiet weeks produce no PR.
4. The owner can explore the codebase on laptop, phone and Claude app from one link (Atlas page).
5. The owner can open the repo as an Obsidian vault on a laptop and see wiki, graph export and notes linked.

## Non-goals (v1)

- OpenWiki personal mode (Gmail, Notion, X), linked wiki workspaces across repos, a shared graph server.
- Obsidian on the phone. The Atlas page covers the phone.
- Editing notes from the Atlas page. Notes are edited in Obsidian or by PR; the page only shows them.
- Graphify "strict" mode (blocking the agent's first raw file read). Default nudge only.
- A graph of a session's own unmerged branch. Sessions use the daily `main` graph; the agent knows its own
  changes.

## Anti-goals (a failure even if it technically works)

- Session start gets slower or can fail: the new hook step returns within 5 s and always exits 0.
- Generated files churn in ordinary PRs or on `main`: the graph never lives on `main`; a feature PR must
  not contain `openwiki/` changes.
- The graph, wiki or Atlas data contain anything from excluded paths (secrets, local data folders).
- The Claude prompt cache resets when the graph or wiki changes.

## Decisions made with the owner

- **Viewing:** both. Atlas page everywhere (laptop three-pane layout, phone search-first layout, same page
  in the Claude app) plus Obsidian on the laptop. Layout per mockups A and B.
- **Data route:** sending this repo's code and docs to Claude for the wiki and the graph's doc pass is
  approved. No other model provider.
- **Wiki cadence:** weekly refresh, delivered as a PR against `main`.
- **Graph cadence:** built once a day, not per session.
- **Exclusions:** all committed docs, sample data and fixtures may be read. Excluded: secrets and the
  local data folders (see Ignore files).

## Calls made by the spec author (owner: check these)

- **Pinned versions:** `graphifyy==0.9.92`, `openwiki@0.7.2`.
- **Graph storage:** branch `context-data`, an orphan branch force-pushed as a single commit each build
  (no history, so the repo doesn't grow by a graph per day). It holds `graph.json`, `GRAPH_REPORT.md` and
  `meta.json` (`{"commit": "<40-char main SHA>", "built_at": "<ISO 8601 UTC>", "docs_built_at": "<ISO 8601 UTC>"}`).
  Nothing graph-related is committed to `main`.
- **Graph build:** a GitHub Actions workflow `Context graph`, on `main` only. Daily at 02:17 UTC: code-only
  extraction (no model calls), keeping the doc nodes from the last weekly build. Mondays: full extraction
  including docs through Graphify's Claude backend, using the existing `ARP_ANTHROPIC_API_KEY` secret.
  Also runnable by hand (`workflow_dispatch`). The build logic lives in `scripts/build_graph.sh` so it can
  run outside CI.
- **Install path:** the SessionStart hook starts a background job and returns; tools arrive a few minutes
  into the first session of a new container. An optional 3-line cloud setup-script snippet in
  `.claude/CLAUDE.md` makes them ready before the session starts. The owner pasting it is optional.
- **Refresh branch:** `context-refresh/YYYY-MM-DD` (UTC date). Only these branches may change `openwiki/`
  (except `openwiki/INSTRUCTIONS.md`, which is hand-written). The guard is a CI job named
  `Generated context guard`.
- **Bootstrap:** the implementing PR ships tooling plus the Atlas page itself: the implementer creates the
  artifact, publishes it from a code-only graph built in the session, and records its URL. After merge,
  the owner (or the implementer) dispatches `Context graph` in Monday mode once and runs `/context-refresh`
  once. Rows that need those outputs are marked *first refresh*.
- **Quiet week:** the weekly wiki run skips work when every commit on `main` since the last refresh merge
  touches only `openwiki/`; it then opens no PR.
- **Data commit:** `meta.json` `commit` for refresh and daily publishes; the PR head SHA for the bootstrap
  publish (recorded in the implementing PR description). The Atlas header shows it.
- **Atlas URL location:** one line `Atlas: <url>` in `.claude/CLAUDE.md`; the skill reads it from there.
- **Existing `# graphify` section** in `.claude/CLAUDE.md` (the skill pointer) stays unchanged;
  `graphify claude install` is not run.
- **Context exclusion:** `.claude/settings.json` `permissions.deny` gains `Read(./graphify-out/graph.json)`,
  so agents query the graph through the CLI instead of loading the whole file into context.
- **Unattended publish:** if a scheduled session cannot publish the Atlas page without approval, the task
  sends the owner a push notification `Atlas not republished: run /context-refresh` instead.
- **Open earlier refresh PR:** the weekly run pushes to and retitles that PR rather than opening a second.

## Shape of the solution

### Repository layout

```
main:
  openwiki/                       committed (refresh branches only). INSTRUCTIONS.md is ours
  notes/                          committed, human-written; starts with README.md
  graphify-out/                   gitignored entirely (downloaded or built locally)
  .obsidian/                      gitignored
  .graphifyignore, .openwikiignore   committed
  scripts/build_graph.sh, scripts/vault.sh
  .github/workflows/context-graph.yml
context-data (orphan, single commit):
  graph.json, GRAPH_REPORT.md, meta.json
```

### Daily graph (GitHub Actions)

`scripts/build_graph.sh [--with-docs]`: installs `graphifyy==0.9.92`, runs Graphify on the repo honouring
`.graphifyignore`, writes `graphify-out/graph.json`, `GRAPH_REPORT.md` and `meta.json`. Without
`--with-docs` it extracts code only and carries over the doc nodes from the current `context-data`
`graph.json` (the builder chooses the merge mechanism; doc nodes must survive). The workflow then
force-pushes those three files to `context-data`. A failed build leaves `context-data` unchanged.
`ARP_CONTEXT_FAIL=build` forces the build to fail (for tests).

### Agents (cloud and local sessions)

- **Tools and graph at session start.** New script `.claude/hooks/context-stack.sh`, wired into the
  existing SessionStart hook, starts a background job and returns. `--foreground` runs the job inline
  (for tests). The job runs four steps in order: `install-graphify` (`graphifyy==0.9.92` when missing),
  `install-openwiki` (`openwiki@0.7.2` when missing), `register-openwiki` (checks the committed
  project-scope `.mcp.json` entry works), `fetch-graph` (downloads `graph.json`, `GRAPH_REPORT.md` and
  `meta.json` from `origin/context-data` into `graphify-out/`). It logs each step to
  `~/.cache/arp-context/session.log` as `arp-context: <step> ok` or `arp-context: <step> failed (<reason>)`.
  `ARP_CONTEXT_FAIL=<step>` forces that step to fail (for tests). Every network call honours
  `HTTPS_PROXY`/`HTTP_PROXY`. The script writes nothing to stdout. A failure never fails the session.
- **Rules block in `.claude/CLAUDE.md`.** One `## Codebase context` section, outside any tool-managed
  block, containing, in this order:
  1. OpenWiki first: the OpenWiki search tool, or read `openwiki/quickstart.md` if the tool is not loaded.
  2. Then `graphify query`, `graphify path` or `graphify explain` before grepping. INFERRED edges are
     guesses: check the source. The graph is `main` as of last night; your own changes are not in it.
  3. Then `notes/`. Notes override the wiki where they conflict.
  4. Then source files, only for detail the above doesn't give.
  Plus: "After a change that alters behaviour, say whether `openwiki/` needs an update." and "Never edit
  `openwiki/` by hand." The same file gains the `Atlas:` line, the optional setup-script snippet, and a
  short "Open the repo in Obsidian" paragraph. No `@`-import of anything under `openwiki/` or
  `graphify-out/`.
- **Existing `/graphify` skill** in `.claude/skills/graphify/` stays, refreshed from `graphify install`
  for the pinned version.

### Weekly wiki refresh (scheduled task)

One scheduled cloud task, Mondays after the Monday graph build, next to the existing retro task. Prompt:
`run /context-refresh`. The `context-refresh` skill (`.claude/skills/context-refresh/`), also runnable by
hand:

1. Branch `context-refresh/<UTC date>` from `main`. Set `OPENWIKI_TELEMETRY_DISABLED=1`. Run OpenWiki's
   update ("Update this repository's OpenWiki for changes since its last successful run"). Quiet-week
   rule applies.
2. If `openwiki/` (other than `INSTRUCTIONS.md`) changed: open (or update) a PR titled
   `Context refresh <YYYY-MM-DD>` against `main`, label `risk:low`. Otherwise no PR.
3. Republish the Atlas page.

### Daily Atlas republish (scheduled task)

Daily, after the graph build. Prompt: `run /context-refresh --atlas-only`. Fetches `context-data` and
`main`'s `openwiki/` and `notes/`, and republishes the Atlas page when `meta.json` `commit` differs from
the commit the page shows. Otherwise does nothing.

### Atlas page

- One private claude.ai artifact; URL in the `Atlas:` line.
- Content: graph, wiki pages, notes and `GRAPH_REPORT.md` as published data files; the page is static
  HTML/JS loading libraries only from the allowed CDNs.
- **Laptop (≥1024 px):** search box in the header; three panes as mockup A. Left: areas (Graphify
  communities with node counts), filters (code / docs / INFERRED edges; INFERRED off by default, drawn
  dashed when on), top 10 hubs. Middle: interactive graph, views "Whole repo", "2 hops" (selected node plus
  nodes within two edges, undirected), "Path A → B" (shortest undirected path); click to focus; zoom.
  Right: the selected node's file path, area, wiki excerpt with a link to the full page, "Used by" list,
  notes that link to it, "Open on GitHub" link to the file on `main`.
- **Phone (<1024 px):** search first; selected node shows a one-hop mini graph, wiki excerpt and a
  tappable list of connected nodes. Bottom tabs: Explore, Wiki, Report, and Ask when available.
- **Nodes:** search results and path endpoints include file nodes (label = basename, path =
  repo-relative file). Each search result element carries the attribute `data-atlas-result`.
- **Status line** under the graph, for the current view: `N nodes · M edges · K inferred`, plus
  `· H hops` in the path view.
- **Wiki tab** renders `openwiki/` pages; links between pages open inside the tab. **Report tab** renders
  `GRAPH_REPORT.md`.
- **Ask** (tab on phone, "Ask Claude about this" button on laptop): uses the artifact runtime's ask-Claude
  capability, grounded on the selected node and its wiki page. Absent capability, or the URL hash
  `#noask`, → neither tab nor button is rendered.
- Header: data commit as a 7-character SHA, graph build time and doc-pass time, both ISO 8601 UTC.
- The default view may be thinned (e.g. communities collapsed) so phones stay responsive; search reaches
  every node.

### Obsidian (laptop)

- `scripts/vault.sh`: one command; downloads the graph from `context-data` into `graphify-out/` and runs
  `graphify export obsidian --dir graphify-out/obsidian`. Does not touch `notes/` or `.obsidian/`. Starts
  no server.
- `notes/README.md`: one note per decision; link wiki pages or files with `[[...]]`.

### Ignore files

`.graphifyignore` and `.openwikiignore` both contain at least these exact lines:

```
.env*
*secret*
*credential*
*.key
*.pem
data/
runs/
engagements/
ballots/
node_modules/
dist/
build/
package-lock.json
*.lock
frontend/src/api/schema.gen.ts
frontend/src/api/openapi.json
graphify-out/
.obsidian/
```

### Controls

- `OPENWIKI_TELEMETRY_DISABLED=1` in the session environment (`.claude/settings.json` `env`) and in the
  `context-refresh` skill.
- Model calls only to Claude: OpenWiki host-driven in the session; Graphify's Claude backend in the
  Monday build. No other provider key is configured by this change.
- Nothing listens on a network port: no `openwiki visualize` server, no Graphify HTTP server.

## Left to the builder

Exact hook and workflow structure, the doc-node merge mechanism, Atlas page libraries, how data files are
split for the page, and the ignore lists beyond the entries named.

## Acceptance

Rows marked *first refresh* are checked after the bootstrap steps (one Monday-mode graph build and one
`/context-refresh`) have run; all others on the implementing PR. "≥4/5" rows run five fresh sessions with
the same prompt. "Session job" = `.claude/hooks/context-stack.sh --foreground`.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | A fresh cloud session on the PR branch, 5 minutes after start | `graphify --version` | Exits 0; stdout contains `0.9.92` | evaluator |
| AC-2  | Same session | `openwiki --version` | Exits 0; stdout contains `0.7.2` | evaluator |
| AC-3  | Tools not installed | `.claude/hooks/context-stack.sh` (no flag) | Exits 0 within 5 s | holdout |
| AC-4  | `HTTPS_PROXY=HTTP_PROXY=http://127.0.0.1:9`, `NO_PROXY` unset | `.claude/hooks/context-stack.sh` (no flag) | Exits 0 within 5 s | holdout |
| AC-5  | Same proxy, tools not installed | Session job | `~/.cache/arp-context/session.log` has a line matching `^arp-context: install-graphify failed \(.+\)$` | holdout |
| AC-6  | Same as AC-5, job finished | List processes (psutil, or `pgrep -f` run directly, not through a shell) | No process other than the checker and its ancestors has a command line matching the ERE `graphify`, `openwiki`, `pip install` or `npm install` | holdout |
| AC-7  | A local bare remote whose `context-data` branch holds a `graph.json` with node `ctx_probe_node` | Session job against that remote | `graphify-out/graph.json` exists and contains `ctx_probe_node`; log has `arp-context: fetch-graph ok` | holdout |
| AC-8  | Remote without a `context-data` branch | Session job | Exits 0; log has a line matching `^arp-context: fetch-graph failed \(.+\)$` | holdout |
| AC-9  | Clean checkout, tools installed | Session job, then `git status --porcelain` | Prints nothing | holdout |
| AC-10 | Clean checkout | `scripts/vault.sh`, then `git status --porcelain` | Prints nothing | holdout |
| AC-11 | `.github/workflows/context-graph.yml` | Read | Named `Context graph`; triggers `schedule` with cron `17 2 * * *` and `workflow_dispatch`; runs only on `main` | holdout |
| AC-12 | *First refresh*; `context-data` | `git show origin/context-data --stat` and `git rev-list --count origin/context-data` | Holds exactly `graph.json`, `GRAPH_REPORT.md`, `meta.json`; count is `1` | evaluator |
| AC-13 | *First refresh*; `meta.json` | Read | `commit` is a commit on `main`; `built_at` and `docs_built_at` are ISO 8601 UTC | evaluator |
| AC-14 | *First refresh*; a new commit on `main` adds function `foo_ctx_probe` in `backend/arp/ctx_probe.py` | `Context graph` dispatched (daily mode), then in a new session `graphify query "foo_ctx_probe"` | Exits 0; output contains `backend/arp/ctx_probe.py` | evaluator |
| AC-15 | Same as AC-14 | `graphify query "ACCEPTANCE_TEMPLATE"` | Exits 0; output contains `docs/superpowers/ACCEPTANCE_TEMPLATE.md` (doc nodes survived the daily build) | evaluator |
| AC-16 | Same daily-mode run | Its log | Contains no request to a model API (Graphify reports code-only mode) | evaluator |
| AC-17 | `scripts/build_graph.sh` forced to fail (e.g. `ARP_CONTEXT_FAIL=build`) in a dispatched run | Run finishes | `origin/context-data` head SHA unchanged | evaluator |
| AC-18 | Tools installed; `def CTX_IGNORE_CANARY(): pass` in each of `x_secret.py`, `x_credential.py`, `data/x.py`, `runs/x.py`, `engagements/x.py`, `ballots/x.py`; `def CTX_IGNORE_CANARY_OK(): pass` in `x_ok.py`; no `context-data` available | `scripts/build_graph.sh` | Exits 0; `grep -r CTX_IGNORE_CANARY_OK graphify-out/graph.json` exits 0; `grep -rw CTX_IGNORE_CANARY graphify-out/` exits 1 | holdout |
| AC-19 | `.graphifyignore` and `.openwikiignore` | Read | Each contains every line of the Ignore files block as an exact line | holdout |
| AC-20 | *First refresh*; in a session on `main`, the AC-18 files plus `CTX_IGNORE_CANARY` in `.env.ctx` and `x.pem`, all untracked | `/context-refresh` and `scripts/build_graph.sh --with-docs` run by hand | `grep -rw CTX_IGNORE_CANARY graphify-out/ openwiki/` exits 1; no Atlas data file published in that run contains `CTX_IGNORE_CANARY` as a whole word | evaluator |
| AC-21 | — | `python .github/scripts/context_guard.py --head-ref feat/x --changed openwiki/a.md` | Exits 1; stdout contains `generated file changed outside context-refresh/*: openwiki/a.md` | holdout |
| AC-22 | — | Same with `--changed openwiki/INSTRUCTIONS.md` | Exits 0 | holdout |
| AC-23 | — | Same with `--head-ref context-refresh/2026-10-19 --changed openwiki/a.md` | Exits 0 | holdout |
| AC-24 | — | Same with `--head-ref feat/x --changed backend/arp/config.py` | Exits 0 | holdout |
| AC-25 | `.github/workflows/` | Read | A job named `Generated context guard` runs `.github/scripts/context_guard.py` on pull requests | holdout |
| AC-26 | `.claude/CLAUDE.md` | `grep -c '^## Codebase context' .claude/CLAUDE.md` | Prints `1` | holdout |
| AC-27 | That section | Line numbers of the first mention of `openwiki`, `graphify query`, `notes/`, `source files` | Strictly increasing in that order | holdout |
| AC-28 | That section | Searched for each phrase | Contains `INFERRED`, `override`, `as of last night`, `needs an update`, `Never edit` | holdout |
| AC-29 | `.claude/CLAUDE.md` | Searched | Contains `Obsidian` | holdout |
| AC-30 | `.claude/CLAUDE.md` | Searched | Has a line `Atlas: https://claude.ai/...` whose URL opens the Atlas page | evaluator |
| AC-31 | `.claude/CLAUDE.md` | `grep -c '^# graphify' .claude/CLAUDE.md` | Prints `1` | holdout |
| AC-32 | `.claude/CLAUDE.md` | `grep -E '^@graphify-out/' .claude/CLAUDE.md` and `grep -E '^@openwiki/' .claude/CLAUDE.md` | Both exit 1 | holdout |
| AC-33 | — | `.claude/hooks/context-stack.sh`, with and without `--foreground` | stdout is empty in both cases | holdout |
| AC-34 | New session, session job finished | `claude mcp get openwiki` | Shows scope project and status connected | evaluator |
| AC-35 | *First refresh*; 5 fresh sessions | Asked "how does grounding work?" | In ≥4/5, the first Read, Grep, Bash or MCP call is the OpenWiki search tool or a Read of a path under `openwiki/`, before any Grep tool call, `grep`/`rg` command or Read outside `openwiki/` | evaluator |
| AC-36 | *First refresh*; 5 fresh sessions | Asked "what calls `select_evidence`?" | In ≥4/5, a Bash call starting `graphify query`, `graphify path` or `graphify explain` comes before any Grep tool call or `grep`/`rg` command | evaluator |
| AC-37 | *First refresh*; `notes/ctx-probe.md` says grounding tolerance is `0.5%`; the wiki says `1%` | 5 fresh sessions asked "what is the grounding tolerance?" | In ≥4/5 the answer contains `0.5%` and `notes/ctx-probe.md` | evaluator |
| AC-38 | `list_triggers` | Read | A Monday task with prompt `run /context-refresh` and a daily task with prompt `run /context-refresh --atlas-only` exist and are enabled | evaluator |
| AC-39 | *First refresh*: weekly task fired by hand on `main` with non-`openwiki/` commits since the last refresh | It finishes | Exactly one open PR titled `Context refresh <YYYY-MM-DD>` (UTC date of the run), base `main`, label `risk:low` | evaluator |
| AC-40 | Same PR | Its changed paths | Every path is under `openwiki/` and none is `openwiki/INSTRUCTIONS.md` | evaluator |
| AC-41 | An earlier `Context refresh` PR still open | Weekly task fired by hand | Exactly one open PR whose title starts `Context refresh`, titled with today's UTC date | evaluator |
| AC-42 | AC-39's PR merged, no other commits on `main` | Weekly task fired by hand | No open PR whose title starts `Context refresh` | evaluator |
| AC-43 | *First refresh* PR | Each `openwiki/` page except `INSTRUCTIONS.md` | Has ≥1 claim under `openwiki/.claims/`; every claim's `repo://<path>#L<a>-L<b>` evidence names a file that exists at the PR's base commit with ≥`b` lines | evaluator |
| AC-44 | Atlas URL, laptop at 1440 px | Page loads | Header search box plus left, middle and right panes visible side by side | evaluator |
| AC-45 | Same | Type `grounding`, select the file node `backend/arp/grounding.py` | Right pane shows path `backend/arp/grounding.py` and a "Used by" list with ≥1 entry | evaluator |
| AC-46 | *First refresh*; same selection | Read right pane | Shows a wiki excerpt of ≥1 sentence that appears word for word in an `openwiki/` page | evaluator |
| AC-47 | Same selection | Inspect "Open on GitHub" | href is `https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/main/backend/arp/grounding.py` | evaluator |
| AC-48 | Same selection | Click "2 hops" | Status line `N` equals the undirected 2-hop neighbourhood size of that node in the published graph data (node included) | evaluator |
| AC-49 | Laptop | "Path A → B" from file node `backend/arp/api/app.py` to file node `backend/arp/grounding.py` | Path shows `app.py` first and `grounding.py` last; status line `H` equals the undirected shortest-path length in the published graph data | evaluator |
| AC-50 | Laptop, default filters | Read status line | `K` is `0` | evaluator |
| AC-51 | Laptop, INFERRED filter on, graph data has ≥1 INFERRED edge in view | Read status line; look at the graph | `K` ≥ 1; at least one dashed edge visible | evaluator |
| AC-52 | `notes/ctx-probe.md` links `[[backend/arp/grounding.py]]`; Atlas republished | Select `grounding.py` | Right pane lists `ctx-probe` under notes | evaluator |
| AC-53 | Atlas URL at 390 px width (Chromium emulation) | Page loads | `document.documentElement.scrollWidth` ≤ 390 | evaluator |
| AC-54 | Same | Inspect | Search box, Explore, Wiki and Report tabs are present | evaluator |
| AC-55 | Same, `grounding.py` selected | Tap the first connected node whose path differs from `backend/arp/grounding.py` | Shown file path changes to that node's path | evaluator |
| AC-56 | Same, cache disabled, no network throttling, 4× CPU throttling | Type `grounding` as soon as the box accepts input | In the artifact content frame, `performance.now()` at the first insertion of an element matching `[data-atlas-result]` is ≤3000 | evaluator |
| AC-57 | Same | Search 3 node names taken from the published graph data, one from its smallest community | Each appears in results | evaluator |
| AC-58 | Atlas in the Claude app | Type `grounding` | Results list `backend/arp/grounding.py` | evaluator |
| AC-59 | Atlas header | Read | 7-char SHA equal to `git rev-parse --short` of the data commit (`meta.json` `commit`, or the PR head SHA recorded in the PR description for the bootstrap) | evaluator |
| AC-60 | *First refresh*; Atlas header | Read | Shows graph build time and doc-pass time equal to `meta.json` `built_at` and `docs_built_at` | evaluator |
| AC-61 | *First refresh*; Wiki tab, a page linking another wiki page | Tap the link | Target page's H1 shows in the Wiki tab; browser URL host and path unchanged | evaluator |
| AC-62 | Report tab | Open | Shows the first H1 of the published `GRAPH_REPORT.md` | evaluator |
| AC-63 | Atlas URL opened with hash `#noask` | Inspect DOM | No Ask tab and no "Ask Claude about this" button | evaluator |
| AC-64 | Account with the ask-Claude capability | Ask "what does this do?" with `grounding.py` selected | In ≥4/5 runs the answer contains `grounding` | evaluator |
| AC-65 | *First refresh*; `meta.json` `commit` differs from the Atlas header SHA | Daily Atlas task fired by hand | Atlas header SHA equals the short form of `meta.json` `commit` | evaluator |
| AC-66 | `meta.json` `commit` equals the Atlas header SHA | Daily Atlas task fired by hand | Atlas header SHA and build time unchanged | evaluator |
| AC-67 | The `Atlas:` line in `.claude/CLAUDE.md` set to `https://claude.ai/artifact/invalid` in the session | `/context-refresh --atlas-only` run | Transcript shows a push notification with exactly `Atlas not republished: run /context-refresh`, and no Artifact publish without a `url` | evaluator |
| AC-68 | *First refresh*; a laptop clone | `scripts/vault.sh` | Exits 0; `graphify-out/obsidian/` has ≥N `.md` files, N = distinct community ids in `graph.json` | evaluator |
| AC-69 | Clean checkout, a `context-data` branch reachable | Hash `notes/` and `.obsidian/` before and after `scripts/vault.sh` | Identical | holdout |
| AC-70 | *First refresh*; same as AC-68 | Every `[[...]]` link in `notes/README.md` and in the first 3 export files by name | After stripping `\|alias` and `#heading`, each target resolves to an existing file either as an exact vault-root-relative path or as a basename (`.md` added when there is no extension) unique in the vault | evaluator |
| AC-71 | New session | `echo $OPENWIKI_TELEMETRY_DISABLED` | Prints `1` | evaluator |
| AC-72 | `.claude/skills/context-refresh/SKILL.md` | Read | Contains `OPENWIKI_TELEMETRY_DISABLED=1` | holdout |
| AC-73 | Repo after the change | `git check-ignore -q` on `.obsidian/x`, `graphify-out/x`, `graphify-out/obsidian/x` | Exits 0 for each | holdout |
| AC-74 | Same | `git check-ignore -q` on `openwiki/x.md`, `notes/README.md` | Exits 1 for each | holdout |
| AC-75 | `.claude/settings.json` | Read `permissions.deny` | Contains `Read(./graphify-out/graph.json)` | holdout |
| AC-76 | After session job and `scripts/vault.sh` ran | `ss -ltnp` | No listening socket owned by a `graphify` or `openwiki` process | evaluator |

Must not change:

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-77 | Second session after a container boot | `claude plugin list` | Shows enabled: ponytail, ui-ux-pro-max, impeccable, i-have-adhd, andrej-karpathy-skills, humanizer, superpowers, runs-pane, test-guard, token-usage | evaluator |
| AC-78 | Fixture branches: one clean, one with a ruff error in `backend/` | Stop hook runs | Same exit code and same check names in its output as on `main` before this change | holdout |
| AC-79 | `.claude/skills/graphify/SKILL.md` | Read | Exists and names version `0.9.92` | holdout |
| AC-80 | The existing Monday retro scheduled task | `list_triggers` | Same cron and prompt as before this change | evaluator |
| AC-81 | `main` after the bootstrap steps | `git ls-tree -r --name-only origin/main` | No path starts with `graphify-out/` | evaluator |
