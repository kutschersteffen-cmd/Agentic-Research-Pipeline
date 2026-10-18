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
- **Graphify** (`graphify-out/`): what calls, imports or references what.
- **`notes/`**: decisions written by people. They win over the wiki where they conflict.
- **Atlas page**: one private claude.ai page that shows graph + wiki + notes, usable on a laptop, a phone
  and inside the Claude app.
- **Obsidian**: the repo root opened as a vault on the owner's laptop, for reading and editing notes.

## Goals

1. Agents read in a fixed order (wiki → graph → notes → source) and get the tools in every cloud session
   with no manual step.
2. The graph in a session reflects the code on that session's branch, as of session start.
3. The wiki is refreshed weekly through a PR the owner reviews; quiet weeks produce no PR.
4. The owner can explore the codebase on laptop, phone and Claude app from one link (Atlas page).
5. The owner can open the repo as an Obsidian vault on a laptop and see wiki, graph export and notes linked.

## Non-goals (v1)

- OpenWiki personal mode (Gmail, Notion, X), linked wiki workspaces across repos, a shared graph server.
- Obsidian on the phone. The Atlas page covers the phone.
- Editing notes from the Atlas page. Notes are edited in Obsidian or by PR; the page only shows them.
- Graphify "strict" mode (blocking the agent's first raw file read). Default nudge only.
- Keeping the graph current after commits *during* a session (no git hooks in cloud sessions). Session
  start only; on a laptop, `scripts/vault.sh` rebuilds on demand.

## Anti-goals (a failure even if it technically works)

- Session start gets slower or can fail: the new hook step returns within 5 s and always exits 0.
- Generated files churn in ordinary PRs: a feature PR must not contain `graphify-out/` or `openwiki/`
  changes.
- The graph, wiki or Atlas data contain anything from excluded paths (secrets, local data folders).
- The Claude prompt cache resets on every graph rebuild.

## Decisions made with the owner

- **Viewing:** both. Atlas page everywhere (laptop three-pane layout, phone search-first layout, same page
  in the Claude app) plus Obsidian on the laptop. Layout per mockups A and B.
- **Data route:** sending this repo's code and docs to Claude for the wiki and the graph's doc pass is
  approved, same route as existing Claude Code sessions. No other model provider.
- **Wiki cadence:** weekly refresh, delivered as a PR against `main`.
- **Exclusions:** all committed docs, sample data and fixtures may be read. Excluded: secrets and the
  local data folders (see Ignore files).

## Calls made by the spec author (owner: check these)

- **Pinned versions:** `graphifyy==0.9.92`, `openwiki@0.7.2`.
- **Install path:** the SessionStart hook starts a background job and returns; tools arrive a few minutes
  into the first session of a new container. An optional 3-line cloud setup-script snippet in
  `.claude/CLAUDE.md` makes them ready before the session starts. The owner pasting it is optional.
- **Refresh branch:** `context-refresh/YYYY-MM-DD` (UTC date). Only these branches may change generated
  files. The guard is a CI job named `Generated context guard`, not the Stop hook.
- **Bootstrap:** the implementing PR ships tooling plus the Atlas page itself: the implementer creates
  the artifact, publishes it from a code-only graph built in the session (not committed), and records its
  URL in `.claude/CLAUDE.md`. The first `/context-refresh` run right after merge produces the first
  committed `openwiki/` and `graph.json` and republishes the page with wiki and doc nodes. Rows that need
  the wiki or doc nodes are marked *first refresh* and checked on that first refresh PR.
- **Quiet week:** the weekly run skips extraction when every commit on `main` since the last refresh
  merge touches only generated paths (`openwiki/`, `graphify-out/`); it then opens no PR and does not
  republish.
- **Data commit:** the commit the outputs were built from: the PR head for the bootstrap publish
  (recorded in the implementing PR description), the `main` commit for refresh and daily publishes
  (recorded in the refresh PR body, or the task's final message for the daily task). The Atlas header
  shows it.
- **Atlas URL location:** one line `Atlas: <url>` in `.claude/CLAUDE.md`; the skill reads it from there.
- **Existing `# graphify` section** in `.claude/CLAUDE.md` (the skill pointer) stays unchanged;
  `graphify claude install` is not run.
- **Context exclusion:** `.claude/settings.json` `permissions.deny` gains `Read(./graphify-out/graph.json)`,
  so agents query the graph through the CLI instead of loading the whole file into context.
- **`openwiki/INSTRUCTIONS.md`** is hand-written and exempt from the guard.
- **Unattended publish:** if a scheduled session cannot publish the Atlas page without approval, the task
  sends the owner a push notification ("Atlas not republished: run /context-refresh") instead.
- **Open earlier refresh PR:** the weekly run pushes to and retitles that PR rather than opening a second.

## Shape of the solution

### Repository layout

```
openwiki/                       committed (refresh branches only). INSTRUCTIONS.md is ours
graphify-out/graph.json         committed (refresh branches only)
graphify-out/GRAPH_REPORT.md    committed (refresh branches only)
graphify-out/cache/, manifest and other Graphify machine-local files   gitignored
graphify-out/obsidian/          gitignored, generated on the laptop
notes/                          committed, human-written; starts with README.md
.obsidian/                      gitignored
.graphifyignore, .openwikiignore   committed
```

### Agents (cloud and local sessions)

- **Tools at session start.** New script `.claude/hooks/context-stack.sh`, wired into the existing
  SessionStart hook, starts a background job and returns. `--foreground` runs the job inline (for tests).
  The job runs four steps in order: `install-graphify` (`graphifyy==0.9.92` when missing),
  `install-openwiki` (`openwiki@0.7.2` when missing), `register-openwiki` (checks the committed
  project-scope `.mcp.json` entry works), `update-graph`. It logs each step to
  `~/.cache/arp-context/session.log` as `arp-context: <step> ok` or `arp-context: <step> failed (<reason>)`.
  `ARP_CONTEXT_FAIL=<step>` forces that step to fail (for tests). Every install honours the standard
  `HTTPS_PROXY`/`HTTP_PROXY` variables. The script writes nothing to stdout (it would land in the cached
  prompt). Any failure leaves the committed outputs
  untouched and never fails the session. The project-scope `.mcp.json` for OpenWiki is committed by the
  implementing PR, so the job writes nothing tracked.
- **Graph reflects the branch.** The job brings the graph up to date with the checked-out code using
  Graphify's local, model-free code extraction. Doc and PDF nodes come from the committed weekly graph and
  must survive the update. If the update fails, the committed graph stays as is. After the job (and after
  `scripts/vault.sh`) `git status --porcelain` is empty; the builder chooses how (e.g. write the session
  graph to a gitignored path and point Graphify at it).
- **Rules block in `.claude/CLAUDE.md`.** One `## Codebase context` section, outside any tool-managed
  block, containing, in this order:
  1. OpenWiki first: the OpenWiki search tool, or read `openwiki/quickstart.md` if the tool is not loaded.
  2. Then `graphify query`, `graphify path` or `graphify explain` before grepping. INFERRED edges are
     guesses: check the source.
  3. Then `notes/`. Notes override the wiki where they conflict.
  4. Then source files, only for detail the above doesn't give.
  Plus: "After a change that alters behaviour, say whether `openwiki/` needs an update." and "Never edit
  `openwiki/` or `graphify-out/` by hand." The same file gains the Atlas URL, the optional setup-script
  snippet, and a short "Open the repo in Obsidian" paragraph. No `@`-import of anything under
  `openwiki/` or `graphify-out/` (it would change the cached prompt on every refresh).
- **Existing `/graphify` skill** in `.claude/skills/graphify/` stays, refreshed from `graphify install`
  for the pinned version.
- **Prompt cache / context size.** See the context-exclusion call above.

### Weekly refresh (scheduled task)

One scheduled cloud task, Mondays, next to the existing retro task. Its prompt is `run /context-refresh`.
The `context-refresh` skill (`.claude/skills/context-refresh/`), also runnable by hand:

1. Branch `context-refresh/<UTC date>` from `main`. Run Graphify's full extraction (code + docs, Claude
   route) and OpenWiki's update ("Update this repository's OpenWiki for changes since its last successful
   run"). The skill sets `OPENWIKI_TELEMETRY_DISABLED=1` before any OpenWiki call. Quiet-week rule
   applies (see calls).
2. If `openwiki/` (other than `INSTRUCTIONS.md`), `graphify-out/graph.json` or `GRAPH_REPORT.md` changed:
   open (or update, see calls) a PR titled `Context refresh <YYYY-MM-DD>` against `main`, label
   `risk:low`. If nothing changed: no PR, no republish.
3. Republish the Atlas page from the new outputs.

A second scheduled task, daily, with prompt `run /context-refresh --atlas-only`: republishes the Atlas
page from a code-only graph (no model calls) merged with the committed doc nodes and wiki, when `main`
moved since the last publish. No change on `main` → no republish. If a scheduled session cannot publish,
it sends the push notification `Atlas not republished: run /context-refresh`.

### Atlas page

- One private claude.ai artifact; its URL is recorded in `.claude/CLAUDE.md` once created.
- Content: graph, wiki pages, notes and `GRAPH_REPORT.md` as published data files; the page is static
  HTML/JS loading libraries only from the allowed CDNs.
- **Laptop (≥1024 px):** search box in the header; three panes as mockup A. Left: areas (Graphify communities with node counts),
  filters (code / docs / INFERRED edges; INFERRED off by default, drawn dashed when on), top 10 hubs.
  Middle: interactive graph, views "Whole repo", "2 hops" (selected node plus nodes within two edges,
  edges treated as undirected), "Path A → B" (shortest undirected path between two chosen nodes); click to
  focus; zoom. Right: the selected node's file path, area, wiki excerpt with a link to
  the full page, "Used by" list, notes that link to it, "Open on GitHub" link to the file on `main`.
- **Phone (<1024 px):** search first; selected node shows a one-hop mini graph, wiki excerpt and a
  tappable list of connected nodes. Bottom tabs: Explore, Wiki, Report, and Ask when available.
- **Nodes:** Graphify emits file nodes and entity nodes (functions, classes). Search results and path
  endpoints include file nodes (label = basename, path = repo-relative file); selecting a result shows
  that node. Each search result element carries the attribute `data-atlas-result`.
- **Status line** under the graph, for the current view: `N nodes · M edges · K inferred`, plus
  `· H hops` in the path view.
- **Wiki tab** renders `openwiki/` pages; links between pages open inside the tab. **Report tab**
  renders `GRAPH_REPORT.md`.
- **Ask** (tab on phone, "Ask Claude about this" button on laptop): uses the artifact runtime's
  ask-Claude capability, grounded on the selected node and its wiki page. Absent capability, or the URL
  hash `#noask`, → neither tab nor button is rendered.
- Header: data commit (see calls) as a 7-character SHA and build time in ISO 8601 UTC.
- The default view may be thinned (e.g. communities collapsed) so phones stay responsive; search reaches
  every node.

### Obsidian (laptop)

- `scripts/vault.sh`: one command; builds the graph locally (code-only) and runs
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

- `OPENWIKI_TELEMETRY_DISABLED=1` in the session environment (`.claude/settings.json` `env`) and in both
  scheduled-task prompts.
- Model calls only through the Claude route (OpenWiki host-driven mode in the session; Graphify's Claude
  backend). No other provider key is configured by this change.
- Nothing listens on a network port: no `openwiki visualize` server, no Graphify HTTP server.

## Left to the builder

Exact hook structure, the session graph update mechanism (within the constraints above), Atlas page
libraries, how data files are split for the page, scheduled task wording beyond "run /context-refresh",
and the ignore lists beyond the entries named.

## Acceptance

Rows marked *first refresh* are checked on the first `Context refresh` PR after the implementing PR
merges; all others on the implementing PR. "≥4/5" rows run five fresh sessions with the same prompt.
"Session job" = `.claude/hooks/context-stack.sh --foreground`.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | A fresh cloud session on the PR branch, 5 minutes after start | `graphify --version` | Exits 0; stdout contains `0.9.92` | evaluator |
| AC-2  | Same session | `openwiki --version` | Exits 0; stdout contains `0.7.2` | evaluator |
| AC-3  | Tools not installed | `.claude/hooks/context-stack.sh` (no flag) | Exits 0 within 5 s | holdout |
| AC-4  | `HTTPS_PROXY=HTTP_PROXY=http://127.0.0.1:9`, `NO_PROXY` unset | `.claude/hooks/context-stack.sh` (no flag) | Exits 0 within 5 s | holdout |
| AC-5  | `HTTPS_PROXY=HTTP_PROXY=http://127.0.0.1:9`, `NO_PROXY` unset, tools not installed | Session job | `~/.cache/arp-context/session.log` has a line matching `^arp-context: install-graphify failed \(.+\)$` | holdout |
| AC-6  | Same as AC-5, job finished | List processes (psutil, or `pgrep -f` run directly, not through a shell) | No process other than the checker and its ancestors has a command line matching the ERE `graphify`, `openwiki`, `pip install` or `npm install` | holdout |
| AC-7  | Tools installed; the test builds a code-only `graphify-out/graph.json` and commits it; `ARP_CONTEXT_FAIL=update-graph` | Session job, then `git diff --quiet graphify-out/graph.json` | Exits 0 | holdout |
| AC-8  | Same as AC-7 | `graphify query "grounding"` | Exits 0; output contains `backend/arp/grounding.py` | holdout |
| AC-9  | *First refresh* merged; branch adds function `foo_ctx_probe` in new file `backend/arp/ctx_probe.py` | Session job, then `graphify query "foo_ctx_probe"` | Exits 0; output contains `backend/arp/ctx_probe.py` | evaluator |
| AC-10 | Same as AC-9 | `graphify query "ACCEPTANCE_TEMPLATE"` | Exits 0; output contains `docs/superpowers/ACCEPTANCE_TEMPLATE.md` | evaluator |
| AC-11 | Clean checkout, tools installed | Session job, then `git status --porcelain` | Prints nothing | holdout |
| AC-12 | Clean checkout | `scripts/vault.sh`, then `git status --porcelain` | Prints nothing | holdout |
| AC-13 | — | `python .github/scripts/context_guard.py --head-ref feat/x --changed graphify-out/graph.json` | Exits 1; stdout contains `generated file changed outside context-refresh/*: graphify-out/graph.json` | holdout |
| AC-14 | — | Same with `--changed openwiki/INSTRUCTIONS.md` | Exits 0 | holdout |
| AC-15 | — | Same with `--head-ref context-refresh/2026-10-19 --changed graphify-out/graph.json openwiki/a.md` | Exits 0 | holdout |
| AC-16 | — | Same with `--head-ref feat/x --changed backend/arp/config.py` | Exits 0 | holdout |
| AC-17 | `.github/workflows/` after the change | Read | A job named `Generated context guard` runs `.github/scripts/context_guard.py` on pull requests | holdout |
| AC-18 | `.claude/CLAUDE.md` | `grep -c '^## Codebase context' .claude/CLAUDE.md` | Prints `1` | holdout |
| AC-19 | That section | Line numbers of the first mention of `openwiki`, `graphify query`, `notes/`, `source files` | Strictly increasing in that order | holdout |
| AC-20 | That section | Searched for each phrase | Contains `INFERRED`, `override`, `needs an update`, `Never edit` | holdout |
| AC-21 | `.claude/CLAUDE.md` | Searched | Contains `Obsidian` | holdout |
| AC-22 | `.claude/CLAUDE.md` | Searched | Contains a `https://claude.ai/` artifact URL labelled Atlas, and that URL opens the Atlas page | evaluator |
| AC-23 | `.claude/CLAUDE.md` | `grep -c '^# graphify' .claude/CLAUDE.md` | Prints `1` | holdout |
| AC-24 | New session, session job finished | `claude mcp get openwiki` | Shows scope project and status connected | evaluator |
| AC-25 | *First refresh*; 5 fresh sessions | Asked "how does grounding work?" | In ≥4/5, the first Read, Grep, Bash or MCP call is the OpenWiki search tool or a Read of a path under `openwiki/`, before any Grep tool call, `grep`/`rg` command or Read outside `openwiki/` | evaluator |
| AC-26 | 5 fresh sessions | Asked "what calls `select_evidence`?" | In ≥4/5, a Bash call starting `graphify query`, `graphify path` or `graphify explain` comes before any Grep tool call or `grep`/`rg` command | evaluator |
| AC-27 | *First refresh*; `notes/ctx-probe.md` says grounding tolerance is `0.5%`; the wiki says `1%` | 5 fresh sessions asked "what is the grounding tolerance?" | In ≥4/5 the answer contains `0.5%` and `notes/ctx-probe.md` | evaluator |
| AC-28 | `list_triggers` | Read | A Monday task with prompt `run /context-refresh` and a daily task with prompt `run /context-refresh --atlas-only` exist and are enabled | evaluator |
| AC-29 | *First refresh*: weekly task fired by hand on `main` with non-generated commits since the last refresh | It finishes | Exactly one open PR titled `Context refresh <YYYY-MM-DD>` (UTC date of the run), base `main`, label `risk:low` | evaluator |
| AC-30 | Same PR | Its changed paths | Every path is under `openwiki/` (not `openwiki/INSTRUCTIONS.md`) or is `graphify-out/graph.json` or `graphify-out/GRAPH_REPORT.md` | evaluator |
| AC-31 | An earlier `Context refresh` PR still open | Weekly task fired by hand | Exactly one open PR whose title starts `Context refresh`, titled with today's UTC date | evaluator |
| AC-32 | AC-29's PR merged, no other commits on `main`, daily task disabled | Weekly task fired by hand | No open PR whose title starts `Context refresh` | evaluator |
| AC-33 | Same as AC-32 | Atlas header read before and after | SHA and build time unchanged | evaluator |
| AC-34 | *First refresh* PR | Each `openwiki/` page except `INSTRUCTIONS.md` | Has ≥1 claim under `openwiki/.claims/`; every claim's `repo://<path>#L<a>-L<b>` evidence names a file that exists at the PR's base commit with ≥`b` lines | evaluator |
| AC-35 | Tools installed; `def CTX_IGNORE_CANARY(): pass` in each of `x_secret.py`, `x_credential.py`, `data/x.py`, `runs/x.py`, `engagements/x.py`, `ballots/x.py`; `def CTX_IGNORE_CANARY_OK(): pass` in `x_ok.py` | `scripts/vault.sh` | Exits 0; `grep -r CTX_IGNORE_CANARY_OK graphify-out/obsidian/` exits 0; `grep -rw CTX_IGNORE_CANARY graphify-out/` exits 1 | holdout |
| AC-36 | `.graphifyignore` and `.openwikiignore` | Read | Each contains every line of the Ignore files block as an exact line | holdout |
| AC-36b | — | `.claude/hooks/context-stack.sh`, with and without `--foreground` | stdout is empty in both cases | holdout |
| AC-36c | `.claude/CLAUDE.md` | `grep -E '^@(graphify-out\|openwiki)/' .claude/CLAUDE.md` (unescaped ERE) | Exits 1 | holdout |
| AC-37 | In a session on `main` after the first refresh, the AC-35 files plus `CTX_IGNORE_CANARY` in `.env.ctx` and `x.pem`, all untracked | `/context-refresh` run by hand | `graphify-out/` contains a node from `x_ok.py`; `grep -rw CTX_IGNORE_CANARY graphify-out/ openwiki/` exits 1; no published Atlas data file contains `CTX_IGNORE_CANARY` as a whole word | evaluator |
| AC-38 | Atlas URL, laptop at 1440 px | Page loads | Header search box plus left, middle and right panes visible side by side | evaluator |
| AC-39 | Same | Type `grounding`, select the file node `backend/arp/grounding.py` | Right pane shows path `backend/arp/grounding.py` and a "Used by" list with ≥1 entry | evaluator |
| AC-40 | *First refresh*; same selection | Read right pane | Shows a wiki excerpt of ≥1 sentence that appears word for word in an `openwiki/` page | evaluator |
| AC-41 | Same selection | Inspect "Open on GitHub" | href is `https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/main/backend/arp/grounding.py` | evaluator |
| AC-42 | Same selection | Click "2 hops" | Status line `N` equals the undirected 2-hop neighbourhood size of that node in the published graph data (node included) | evaluator |
| AC-43 | Laptop | "Path A → B" from file node `backend/arp/api/app.py` to file node `backend/arp/grounding.py` | Path shows `app.py` first and `grounding.py` last; status line `H` equals the undirected shortest-path length in the published graph data | evaluator |
| AC-44 | Laptop, default filters | Read status line | `K` is `0` | evaluator |
| AC-45 | Laptop, INFERRED filter on, graph data has ≥1 INFERRED edge in view | Read status line; look at the graph | `K` ≥ 1; at least one dashed edge visible | evaluator |
| AC-46 | `notes/ctx-probe.md` links `[[backend/arp/grounding.py]]`; Atlas republished | Select `grounding.py` | Right pane lists `ctx-probe` under notes | evaluator |
| AC-47 | Atlas URL at 390 px width (Chromium emulation) | Page loads | `document.documentElement.scrollWidth` ≤ 390 | evaluator |
| AC-48 | Same | Inspect | Search box, Explore, Wiki and Report tabs are present | evaluator |
| AC-49 | Same, `grounding.py` selected | Tap the first connected node whose path differs from `backend/arp/grounding.py` | Shown file path changes to that node's path | evaluator |
| AC-50 | Same, cache disabled, no network throttling, 4× CPU throttling | Type `grounding` as soon as the box accepts input | In the artifact content frame, `performance.now()` at the first insertion of an element matching `[data-atlas-result]` is ≤3000 | evaluator |
| AC-51 | Same | Search 3 node names taken from the published graph data, one from its smallest community | Each appears in results | evaluator |
| AC-52 | Atlas in the Claude app | Type `grounding` | Results list `backend/arp/grounding.py` | evaluator |
| AC-53 | Atlas header | Read | 7-char SHA equal to `git rev-parse --short` of the data commit recorded as the spec says (PR description, refresh PR body or daily task message) | evaluator |
| AC-54 | Atlas header | Read | Build time in ISO 8601 UTC (`YYYY-MM-DDTHH:MMZ`) | evaluator |
| AC-55 | *First refresh*; Wiki tab, a page linking another wiki page | Tap the link | Target page's H1 shows in the Wiki tab; browser URL host and path unchanged | evaluator |
| AC-56 | Report tab | Open | Shows the first H1 of the published `GRAPH_REPORT.md` | evaluator |
| AC-57 | Atlas URL opened with hash `#noask` | Inspect DOM | No Ask tab and no "Ask Claude about this" button | evaluator |
| AC-58 | Account with the capability | Ask "what does this do?" with `grounding.py` selected | In ≥4/5 runs the answer contains `grounding` | evaluator |
| AC-59 | `main` moved since last Atlas publish | Daily task fired by hand | Atlas header SHA equals the new `main` short SHA | evaluator |
| AC-60 | `main` unchanged since last Atlas publish | Daily task fired by hand | Atlas header SHA and build time unchanged | evaluator |
| AC-61 | The `Atlas:` line in `.claude/CLAUDE.md` set to `https://claude.ai/artifact/invalid` in the session | `/context-refresh --atlas-only` run | Transcript shows a push notification with exactly `Atlas not republished: run /context-refresh`, and no Artifact publish without a `url` | evaluator |
| AC-62 | *First refresh*; a laptop clone | `scripts/vault.sh` | Exits 0; `graphify-out/obsidian/` has ≥N `.md` files, N = distinct community ids in `graph.json` | evaluator |
| AC-63 | Clean checkout | Hash `notes/` and `.obsidian/` before and after `scripts/vault.sh` | Identical | holdout |
| AC-64 | *First refresh*; same as AC-62 | Every `[[...]]` link in `notes/README.md` and in 3 export files (the first 3 by name) | After stripping `\|alias` and `#heading`, each target resolves to an existing file either as an exact vault-root-relative path or as a basename (`.md` added when there is no extension) unique in the vault | evaluator |
| AC-65 | New session | `echo $OPENWIKI_TELEMETRY_DISABLED` | Prints `1` | evaluator |
| AC-66 | `.claude/skills/context-refresh/SKILL.md` | Read | Contains `OPENWIKI_TELEMETRY_DISABLED=1` | holdout |
| AC-67 | Repo after the change | `git check-ignore -q` on `.obsidian/x`, `graphify-out/obsidian/x`, `graphify-out/cache/x` | Exits 0 for each | holdout |
| AC-68 | Same | `git check-ignore -q` on `graphify-out/graph.json`, `graphify-out/GRAPH_REPORT.md`, `openwiki/x.md`, `notes/README.md` | Exits 1 for each | holdout |
| AC-69 | `.claude/settings.json` | Read `permissions.deny` | Contains `Read(./graphify-out/graph.json)` | holdout |
| AC-70 | After session job and `scripts/vault.sh` ran | `ss -ltnp` | No listening socket owned by a `graphify` or `openwiki` process | evaluator |

Must not change:

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-71 | Second session after a container boot | `claude plugin list` | Shows enabled: ponytail, ui-ux-pro-max, impeccable, i-have-adhd, andrej-karpathy-skills, humanizer, superpowers, runs-pane, test-guard, token-usage | evaluator |
| AC-72 | Fixture branches: one clean, one with a ruff error in `backend/` | Stop hook runs | Same exit code and same check names in its output as on `main` before this change | holdout |
| AC-73 | `.claude/skills/graphify/SKILL.md` | Read | Exists and names version `0.9.92` | holdout |
| AC-74 | The existing Monday retro scheduled task | `list_triggers` | Same cron and prompt as before this change | evaluator |
