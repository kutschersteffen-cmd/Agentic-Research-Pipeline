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
- **Bootstrap:** the implementing PR ships tooling only (no generated outputs). The first
  `/context-refresh` run right after merge produces the first `openwiki/`, `graph.json` and Atlas page.
  Rows that need those outputs are checked on that first refresh PR.
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

- **Tools at session start.** A new script wired into the existing SessionStart hook starts a background
  job and returns. The job installs `graphifyy==0.9.92` and `openwiki@0.7.2` when missing, registers
  OpenWiki's Claude Code integration at project scope, then updates the graph. It logs each step to
  `~/.cache/arp-context/session.log` as `arp-context: <step> ok|failed (<reason>)`. Any failure leaves
  the committed outputs usable and never fails the session.
- **Graph reflects the branch.** The job brings the graph up to date with the checked-out code using
  Graphify's local, model-free code extraction. Doc and PDF nodes come from the committed weekly graph and
  must survive the update. If the update fails, the committed graph stays as is. The session update must
  not leave changes that `git add -A` would pick up under `graphify-out/` or `openwiki/`; the builder
  chooses how (e.g. write to a gitignored path and point Graphify at it).
- **Rules block in `.claude/CLAUDE.md`.** One `## Codebase context` section, outside any tool-managed
  block, containing, in this order:
  1. OpenWiki first: the OpenWiki search tool, or read `openwiki/quickstart.md` if the tool is not loaded.
  2. Then `graphify query`, `graphify path` or `graphify explain` before grepping. INFERRED edges are
     guesses: check the source.
  3. Then `notes/`. Notes override the wiki where they conflict.
  4. Then source files, only for detail the above doesn't give.
  Plus: "After a change that alters behaviour, say whether `openwiki/` needs an update." and "Never edit
  `openwiki/` or `graphify-out/` by hand." The same file gains the Atlas URL, the optional setup-script
  snippet, and a short "Open the repo in Obsidian" paragraph. If `graphify claude install` would add its
  own section, ours is the only one kept.
- **Existing `/graphify` skill** in `.claude/skills/graphify/` stays, refreshed from `graphify install`
  for the pinned version.
- **Prompt cache.** `graphify-out/` goes in whatever Claude Code honours to keep it out of context
  (the brief names `.claudeignore`; the builder confirms the current mechanism).

### Weekly refresh (scheduled task)

One scheduled cloud task, Mondays, next to the existing retro task. Its prompt is "run /context-refresh".
The `context-refresh` skill (`.claude/skills/context-refresh/`), also runnable by hand:

1. Branch `context-refresh/<UTC date>` from `main`. Run Graphify's full extraction (code + docs, Claude
   route) and OpenWiki's update ("Update this repository's OpenWiki for changes since its last successful
   run"). `OPENWIKI_TELEMETRY_DISABLED=1` is set.
2. If `openwiki/` (other than `INSTRUCTIONS.md`), `graphify-out/graph.json` or `GRAPH_REPORT.md` changed:
   open (or update, see calls) a PR titled `Context refresh <YYYY-MM-DD>` against `main`, label
   `risk:low`. If nothing changed: no PR, no republish.
3. Republish the Atlas page from the new outputs.

A second scheduled task, daily, republishes the Atlas page when `main` moved since the last publish
(code-only extraction, no model calls). No change on `main` → no republish.

### Atlas page

- One private claude.ai artifact; its URL is recorded in `.claude/CLAUDE.md` once created.
- Content: graph, wiki pages, notes and `GRAPH_REPORT.md` as published data files; the page is static
  HTML/JS loading libraries only from the allowed CDNs.
- **Laptop (≥1024 px):** three panes as mockup A. Left: areas (Graphify communities with node counts),
  filters (code / docs / INFERRED edges), top 10 hubs. Middle: interactive graph, views "Whole repo",
  "2 hops" (selected node plus nodes within two edges), "Path A → B" (shortest path between two chosen
  nodes); click to focus; zoom. Right: the selected node's file path, area, wiki excerpt with a link to
  the full page, "Used by" list, notes that link to it, "Open on GitHub" link to the file on `main`.
- **Phone (<1024 px):** search first; selected node shows a one-hop mini graph, wiki excerpt and a
  tappable list of connected nodes. Bottom tabs: Explore, Wiki, Report, and Ask when available.
- **Wiki tab** renders `openwiki/` pages; links between pages open inside the tab. **Report tab**
  renders `GRAPH_REPORT.md`.
- **Ask** (tab on phone, "Ask Claude about this" button on laptop): uses the artifact runtime's
  ask-Claude capability, grounded on the selected node and its wiki page. Absent capability → neither
  tab nor button is rendered.
- Header: data commit as a 7-character SHA and build time in ISO 8601 UTC.
- The default view may be thinned (e.g. communities collapsed) so phones stay responsive; search reaches
  every node.

### Obsidian (laptop)

- `scripts/vault.sh`: one command; builds the graph locally (code-only) and runs
  `graphify export obsidian --dir graphify-out/obsidian`. Does not touch `notes/` or `.obsidian/`. Starts
  no server.
- `notes/README.md`: one note per decision; link wiki pages or files with `[[...]]`.

### Ignore files

`.graphifyignore` and `.openwikiignore` both exclude at least: `.env*`, `*secret*`, `*credential*`,
`*.key`, `*.pem`; local data folders `data/`, `runs/`, `engagements/`, `ballots/`; `node_modules/`,
build output (`dist/`, `build/`), lockfiles, the generated API client under `frontend/src/api/`;
`graphify-out/` and `.obsidian/`.

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
merges. "≥4/5" rows run five fresh sessions with the same prompt.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | A fresh cloud session on `main` with this change merged, 5 minutes after start | `graphify --version` | Prints `0.9.92` | evaluator |
| AC-2  | Same session | `openwiki --version` | Prints `0.7.2` | evaluator |
| AC-3  | The new session-start script, tools not installed | It runs | It exits 0 within 5 s | holdout |
| AC-4  | The background job with npm and pip registry access blocked | It finishes | `~/.cache/arp-context/session.log` contains a line starting `arp-context: ` and ending `failed (` + reason + `)` for the install step; no process left running | holdout |
| AC-5  | The background job with graph extraction forced to fail, committed `graph.json` present | Then `graphify query "grounding"` | Exits 0 and its output contains `backend/arp/grounding.py` | holdout |
| AC-6  | A branch that adds function `foo_ctx_probe` in new file `backend/arp/ctx_probe.py`; first refresh merged | Session started on it, background job finished, then `graphify query "foo_ctx_probe"` | Exits 0; output contains `backend/arp/ctx_probe.py` | evaluator |
| AC-7  | Same session as AC-6 | `graphify query` for the doc node of `docs/superpowers/ACCEPTANCE_TEMPLATE.md` | Exits 0; output contains `docs/superpowers/ACCEPTANCE_TEMPLATE.md` | evaluator |
| AC-8  | Same session as AC-6 | `git add -A && git commit -m t && git show --stat HEAD` | No listed path starts with `graphify-out/` or `openwiki/` | evaluator |
| AC-9  | A PR from branch `feat/x` changing `graphify-out/graph.json` | CI runs | Job `Generated context guard` fails; its log contains `generated file changed outside context-refresh/*: graphify-out/graph.json` | holdout |
| AC-10 | A PR from `feat/x` changing only `openwiki/INSTRUCTIONS.md` | CI runs | `Generated context guard` passes | holdout |
| AC-11 | A PR from `context-refresh/2026-10-19` changing `graphify-out/graph.json` and `openwiki/a.md` | CI runs | `Generated context guard` passes | holdout |
| AC-12 | A PR from `feat/x` changing only `backend/arp/config.py` | CI runs | `Generated context guard` passes | holdout |
| AC-13 | `.claude/CLAUDE.md` | `grep -c '^## Codebase context' .claude/CLAUDE.md` | Prints `1` | holdout |
| AC-14 | That section | Line numbers of the first mention of `openwiki`, `graphify query`, `notes/`, `source files` | Strictly increasing in that order | holdout |
| AC-15 | That section | Searched for each phrase | Contains `INFERRED`, `override`, `needs an update`, `Never edit` | holdout |
| AC-16 | `.claude/CLAUDE.md` | Searched | Contains a `https://claude.ai/` artifact URL for the Atlas page and the word `Obsidian` | holdout |
| AC-17 | A new session, background job finished | `claude mcp list` | Lists an `openwiki` server at project scope, status connected | evaluator |
| AC-18 | 5 fresh sessions, first refresh merged | Asked "how does grounding work?" | In ≥4/5, the first Read, Grep, Bash or MCP call is the OpenWiki search tool or a Read of a path under `openwiki/`, before any Grep tool call, `grep`/`rg` command or Read outside `openwiki/` | evaluator |
| AC-19 | 5 fresh sessions | Asked "what calls `select_evidence`?" | In ≥4/5, a Bash call starting `graphify query`, `graphify path` or `graphify explain` comes before any Grep tool call or `grep`/`rg` command | evaluator |
| AC-20 | `notes/ctx-probe.md` says grounding tolerance is `0.5%`; the wiki says `1%` | 5 fresh sessions asked "what is the grounding tolerance?" | In ≥4/5 the answer contains `0.5%` and `notes/ctx-probe.md` | evaluator |
| AC-21 | *First refresh*: weekly task fired by hand on `main` with commits since the last refresh | It finishes | Exactly one open PR titled `Context refresh <YYYY-MM-DD>` (UTC), base `main`, label `risk:low` | evaluator |
| AC-22 | Same PR | Its changed paths | Every path is under `openwiki/` (not `openwiki/INSTRUCTIONS.md`) or is `graphify-out/graph.json` or `graphify-out/GRAPH_REPORT.md` | evaluator |
| AC-23 | Task fired again right after AC-21's PR merged, no new commits | It finishes | No new PR opened; Atlas header SHA and build time unchanged | evaluator |
| AC-24 | *First refresh* PR | Each `openwiki/` page except `INSTRUCTIONS.md` | Has ≥1 claim in the pinned OpenWiki's claims store; every claim's file exists at the PR's base commit and its line range ends at or before that file's last line | evaluator |
| AC-25 | Canary string `CTX_IGNORE_CANARY` in each of `.env.ctx`, `x_secret.txt`, `x.pem`, `data/x.md`, `runs/x.md` | Code-only graph is built | `grep -r CTX_IGNORE_CANARY graphify-out/` exits 1 | holdout |
| AC-26 | *First refresh* run with the AC-25 canaries present | It finishes | `grep -r CTX_IGNORE_CANARY graphify-out/ openwiki/` and the published Atlas data files exit 1 / contain no match | evaluator |
| AC-27 | Atlas URL, laptop at 1440 px | Page loads | Left, middle and right panes are visible side by side | evaluator |
| AC-28 | Same | Type `grounding`, select `backend/arp/grounding.py` | Right pane shows path `backend/arp/grounding.py`, a wiki excerpt, and a "Used by" list with ≥1 entry | evaluator |
| AC-29 | Same selection | Inspect "Open on GitHub" | href is `https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/main/backend/arp/grounding.py` | evaluator |
| AC-30 | Same selection | Click "2 hops" | Graph shows only the selected node and nodes ≤2 edges away (spot-check 3 shown nodes against `graph.json`) | evaluator |
| AC-31 | Laptop | "Path A → B" from `backend/arp/api/app.py` to `backend/arp/grounding.py` | Shows a path whose first node is `app.py` and last is `grounding.py`, every hop an edge in `graph.json` | evaluator |
| AC-32 | Laptop, INFERRED filter off | Count dashed/INFERRED edges drawn | 0 | evaluator |
| AC-33 | `notes/ctx-probe.md` links `[[backend/arp/grounding.py]]`; Atlas republished | Select `grounding.py` | Right pane lists `ctx-probe` under notes | evaluator |
| AC-34 | Atlas URL at 390 px width (Chromium emulation) | Page loads | `document.documentElement.scrollWidth` ≤ 390 | evaluator |
| AC-35 | Same | Inspect | Search box, Explore, Wiki and Report tabs are present | evaluator |
| AC-36 | Same, select `grounding.py` | Tap the first connected node | Shown file path changes to that node's path | evaluator |
| AC-37 | Same, 4× CPU throttling | Type `grounding` right after load | First result appears ≤3 s after load starts | evaluator |
| AC-38 | Same | Search a node whose community is collapsed by default | It appears in results | evaluator |
| AC-39 | Atlas in the Claude app | Type `grounding` | Results list `backend/arp/grounding.py` | evaluator |
| AC-40 | Atlas header | Read | Shows the 7-char SHA equal to `git rev-parse --short` of the data commit | evaluator |
| AC-41 | Atlas header | Read | Shows a build time in ISO 8601 UTC (`YYYY-MM-DDTHH:MMZ`) | evaluator |
| AC-42 | Wiki tab, a page linking another wiki page | Tap the link | The target page's H1 shows in the Wiki tab; the browser URL host and path are unchanged | evaluator |
| AC-43 | Report tab | Open | Shows the first H1 of the published `GRAPH_REPORT.md` | evaluator |
| AC-44 | Account without the ask-Claude capability | Page loads | No Ask tab and no "Ask Claude about this" button in the DOM | evaluator |
| AC-45 | Account with the capability | Ask "what does this do?" with `grounding.py` selected | In ≥4/5 runs the answer contains `grounding` | evaluator |
| AC-46 | `main` moved since last Atlas publish | Daily task fired by hand | Atlas header SHA equals the new `main` short SHA | evaluator |
| AC-47 | A laptop clone after first refresh | `scripts/vault.sh` | Exits 0; `graphify-out/obsidian/` contains ≥1 `.md` file per community in `graph.json` | holdout |
| AC-48 | Same | Hash `notes/` and `.obsidian/` before and after | Identical | holdout |
| AC-49 | Same | `notes/README.md`'s `[[...]]` example link and one link in `graphify-out/obsidian/` | Each resolves to an existing file in the vault | evaluator |
| AC-50 | New session | `echo $OPENWIKI_TELEMETRY_DISABLED` | Prints `1` | evaluator |
| AC-51 | Both scheduled task prompts or the skill they run | Read | Each sets `OPENWIKI_TELEMETRY_DISABLED=1` | holdout |
| AC-52 | Repo after the change | `git check-ignore -q` on `.obsidian/x`, `graphify-out/obsidian/x`, `graphify-out/cache/x` | Exits 0 for each | holdout |
| AC-53 | Same | `git check-ignore -q` on `graphify-out/graph.json`, `graphify-out/GRAPH_REPORT.md`, `openwiki/x.md`, `notes/README.md` | Exits 1 for each | holdout |
| AC-54 | Claude Code's context-exclusion file (as confirmed by the builder) | Read | Lists `graphify-out/` | holdout |
| AC-55 | After the session job and `scripts/vault.sh` ran | `ss -ltnp` | No listening socket owned by a `graphify` or `openwiki` process | evaluator |

Must not change:

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-56 | Second session after a container boot | `claude plugin list` | Shows enabled: ponytail, ui-ux-pro-max, impeccable, i-have-adhd, andrej-karpathy-skills, humanizer, superpowers, runs-pane, test-guard, token-usage | evaluator |
| AC-57 | Fixture branches: one clean, one with a ruff error in `backend/` | Stop hook runs | Same exit code and same check names in its output as on `main` before this change | holdout |
| AC-58 | `.claude/skills/graphify/SKILL.md` | Read | Exists and names version `0.9.92` | holdout |
| AC-59 | The existing Monday retro scheduled task | `list_triggers` | Same cron and prompt as before this change | evaluator |
