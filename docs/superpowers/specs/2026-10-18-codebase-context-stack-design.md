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

1. Agents read in a fixed order (wiki → graph → notes → source) and do so in every cloud session without
   manual setup.
2. The graph in a session matches the code on that session's branch.
3. The wiki is refreshed weekly through a PR the owner reviews; quiet weeks produce no PR.
4. The owner can explore the codebase on laptop, phone and Claude app from one link (Atlas page).
5. The owner can open the repo as an Obsidian vault on a laptop and see wiki, graph export and notes linked.

## Non-goals (v1)

- OpenWiki personal mode (Gmail, Notion, X), linked wiki workspaces across repos, a shared graph server.
- Obsidian on the phone. The Atlas page covers the phone.
- Editing notes from the Atlas page. Notes are edited in Obsidian or by PR; the page only shows them.
- Graphify "strict" mode (blocking the agent's first raw file read). Default nudge only.

## Anti-goals (a failure even if it technically works)

- Session start gets noticeably slower or can fail: every new hook step must exit 0 on error and stay
  within the existing hook's timeout budget.
- Generated files churn in ordinary PRs: a feature PR must not contain `graphify-out/` or `openwiki/`
  changes unless the PR is the weekly refresh.
- The graph or wiki contains anything from ignored paths (data extracts, credentials, client files).
- The Claude prompt cache resets on every graph rebuild.

## Decisions made with the owner

- **Viewing:** both. Atlas page everywhere (laptop full three-pane layout, phone search-first layout,
  same page in the Claude app) plus Obsidian on the laptop. Layout per mockups A and B.
- **Data route:** sending this repo's code and docs to Claude for the wiki and the graph's doc pass is
  approved, same route as existing Claude Code sessions. No other model provider.
- **Wiki cadence:** weekly refresh, delivered as a PR against `main`.

## Shape of the solution

### Repository layout

```
openwiki/                 committed. INSTRUCTIONS.md is ours and never overwritten
graphify-out/graph.json   committed (weekly refresh only)
graphify-out/GRAPH_REPORT.md  committed (weekly refresh only)
graphify-out/cache/, other machine-local graphify files   gitignored
graphify-out/obsidian/    gitignored, generated on the laptop
notes/                    committed, human-written; starts with a README saying what goes here
.obsidian/                gitignored
.graphifyignore, .openwikiignore   committed
```

### Agents (cloud and local sessions)

- **Tools available at session start.** The SessionStart path (today `install-plugins.sh`, or a sibling
  script wired into the same hook) installs `graphifyy` (pinned version) and `openwiki` (pinned version)
  when missing, registers OpenWiki's Claude Code integration at project scope, and exits 0 on any failure.
  Pin versions; never `latest`.
- **Graph matches the branch.** At session start, after install, the graph is brought up to date with the
  checked-out code using Graphify's local, model-free code extraction. Doc and PDF nodes come from the
  committed weekly graph and may be up to a week old. The builder decides the exact mechanism (incremental
  update on top of the committed graph, or a code-only rebuild merged with the committed doc nodes) and
  must verify that doc nodes survive it. If the update fails, the committed graph is used as is.
- **Rules block in `.claude/CLAUDE.md`.** A "Codebase context" section with the reading order from the
  owner's brief: OpenWiki search first (`openwiki_search`, fallback `openwiki/quickstart.md`), then
  `graphify query|path|explain` before grepping (INFERRED edges are guesses: check source), then `notes/`
  (overrides the wiki), then source files. After a behaviour change, say whether `openwiki/` needs an
  update. Never hand-edit `openwiki/` or `graphify-out/`. Tool-managed blocks (e.g.
  `<!-- OPENWIKI:START -->`) stay separate from this section. If `graphify claude install` would add its
  own CLAUDE.md section, keep only one of the two, ours.
- **Existing `/graphify` skill** in `.claude/skills/graphify/` stays; the builder checks it matches the
  pinned version and updates it with `graphify install` output if not.
- **Generated files stay out of feature PRs.** The Stop hook or CI rejects `graphify-out/` / `openwiki/`
  changes on any branch that is not the weekly refresh branch. Session-start rebuilds must therefore not
  leave committed files dirty in a way that ends up in a feature PR (the builder chooses how: write the
  session graph to an ignored path the tools read, `git update-index --skip-worktree`, or similar).
- **Prompt cache.** Add `graphify-out/` to whatever Claude Code honours for this (the brief names
  `.claudeignore`; the builder confirms the current mechanism).

### Weekly refresh (scheduled task)

One scheduled cloud task, Mondays, next to the existing retro task:

1. Fresh session on `main`. Run Graphify's full extraction (code + docs, Claude backend) and OpenWiki's
   update ("Update this repository's OpenWiki for changes since its last successful run").
2. If `openwiki/`, `graphify-out/graph.json` or `GRAPH_REPORT.md` changed: open a PR titled
   `Context refresh <date>` against `main`, labelled `risk:low`. If nothing changed: no PR.
3. Republish the Atlas page from the new outputs.

A skill (`.claude/skills/context-refresh/`) holds these steps so the owner can also run it by hand.

### Atlas page

- One private claude.ai artifact, URL fixed once created and recorded in `.claude/CLAUDE.md`.
- Content: the graph, wiki pages and notes as published data files; the page itself is static HTML/JS.
- **Laptop (≥1024 px):** three panes as mockup A: left = areas (Graphify communities with counts), filters
  (code / docs / INFERRED edges), top hubs; middle = interactive graph with "whole repo", "2 hops" and
  "path A → B" views, click to focus, zoom; right = selected node's file path, area, wiki excerpt with a
  link to the full page, "used by" list, matching notes, "Open on GitHub" link.
- **Phone (<1024 px):** search first; selected node shows one-hop mini graph, wiki excerpt, tappable list
  of connected nodes. Bottom tabs: Explore, Wiki, Report, Ask.
- **Wiki tab** renders `openwiki/` pages with working links between them. **Report tab** renders
  `GRAPH_REPORT.md`.
- **Ask / "Ask Claude about this"**: uses the artifact runtime's ask-Claude capability if the owner's
  account offers it, grounded on the selected node and its wiki page. If not offered, the button is hidden.
- Header shows the commit and build time of the data.
- Republished by the weekly refresh, and by a daily scheduled task when `main` moved since the last publish
  (graph only, code-only extraction, no model cost). The skill also republishes on demand.
- Must render the full repo graph without freezing a phone: the builder may thin the default view
  (e.g. communities collapsed until expanded) but search must reach every node.

### Obsidian (laptop)

- `scripts/vault.sh` (or similar, one command): builds the graph locally and exports it with
  `graphify export obsidian --dir graphify-out/obsidian`. Does not touch `notes/` or `.obsidian/`.
- `notes/README.md` explains: one note per decision, link to wiki pages or files with `[[...]]`.
- `.claude/CLAUDE.md` gains a short "Open the repo in Obsidian" paragraph.

### Ignore files

`.graphifyignore` and `.openwikiignore` both exclude at least: `.env*`, anything matching `*secret*`,
`*credential*`, `*.key`, `*.pem`; data extracts and client files (builder lists the repo's actual data
directories, e.g. sample datasets, `backend/tests/fixtures` binaries, `docs/screenshots`, `docs/decks`);
`node_modules`, build output, `frontend/src/api` generated client, lockfiles; `graphify-out/`, `openwiki/`
themselves where relevant.

### Controls

- `OPENWIKI_TELEMETRY_DISABLED=1` set in the session environment (hook) and in the scheduled tasks.
- Model calls only through the session's Claude route (OpenWiki host-driven mode; Graphify `--backend
  claude`). No other provider keys configured.
- Graph served nowhere over HTTP.

## Left to the builder

Exact hook structure, the session graph update mechanism (within the constraints above), Atlas page
libraries (must load from the allowed CDNs), how data files are split for the page, the scheduled task
prompts, and the ignore lists' concrete entries.

## Acceptance

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | A fresh cloud session on `main` with this change merged | The session starts | `graphify --version` and `openwiki --version` print the pinned versions; the hook exits 0 | evaluator |
| AC-2  | Session-start install fails (e.g. network blocked for npm) | The session starts | The hook exits 0 and the session starts; `.claude/hooks` log line names the failed step | unit |
| AC-3  | A branch that adds a new function `foo_ctx_probe` in `backend/arp/` | A session starts on that branch | `graphify query "foo_ctx_probe"` exits 0 and names the new function's file | evaluator |
| AC-4  | Same session as AC-3 | `graphify query` for a node that exists only in a doc under `docs/` (from the committed weekly graph) | Exits 0 and returns the doc node (doc nodes survived the session update) | evaluator |
| AC-5  | A feature branch whose diff includes a change under `graphify-out/` or `openwiki/` | Checks run (Stop hook and CI) | The check fails with a message naming the path; the same check passes on a branch named for the weekly refresh | unit |
| AC-6  | A session started and its graph updated | `git status --porcelain` | No entries under `graphify-out/` or `openwiki/` | unit |
| AC-7  | `.claude/CLAUDE.md` after the change | Read | Contains a "Codebase context" section with the four-step order (wiki, graph, notes, source) and the "never hand-edit" rule, and exactly one such section | unit |
| AC-8  | A new session | Asked "how does grounding work?" | The agent's first context tool call is `openwiki_search` (or a read under `openwiki/`), before any grep or source read | evaluator |
| AC-9  | A new session | Asked "what calls `select_evidence`?" | The agent runs `graphify query`, `path` or `explain` before grepping | evaluator |
| AC-10 | A file `notes/x.md` that contradicts a wiki statement | The agent is asked about that topic | The answer follows the note and says it overrides the wiki | evaluator |
| AC-11 | The weekly task runs on `main` with code changes since last refresh | It finishes | Exactly one open PR titled `Context refresh <YYYY-MM-DD>` against `main`, label `risk:low`, diff touching only `openwiki/`, `graphify-out/graph.json`, `graphify-out/GRAPH_REPORT.md` | evaluator |
| AC-12 | The weekly task runs with no changes since last refresh | It finishes | No PR is opened | evaluator |
| AC-13 | `openwiki/` after the first generation | Each page is inspected | Every page has at least one claim in `openwiki/.claims/` pointing to a file and line range that exists on `main` | unit |
| AC-14 | A file under an ignored path containing the string `CTX_IGNORE_CANARY` | Graph and wiki are generated | `grep -r CTX_IGNORE_CANARY graphify-out/graph.json openwiki/` finds nothing | unit |
| AC-15 | The Atlas page URL from `.claude/CLAUDE.md` | Opened on a laptop browser at 1440 px | Three panes visible; searching `grounding` and selecting `arp/grounding.py` shows its wiki excerpt, a "used by" list with ≥1 entry, and an "Open on GitHub" link to that file on `main` | evaluator |
| AC-16 | Same URL | Opened at 390 px width (phone) | No horizontal page scroll; search, one-hop mini graph, connected list and the Explore/Wiki/Report/Ask tabs are present; tapping a connected node selects it | evaluator |
| AC-17 | Same URL | Opened in the Claude app | The page loads and search works | evaluator |
| AC-18 | Atlas page header | Read | Shows a commit SHA equal to the `main` commit the data was built from, and a build time | evaluator |
| AC-19 | Atlas Wiki tab | A wiki page with a link to another wiki page is opened and the link tapped | The linked page renders in the tab | evaluator |
| AC-20 | `main` moved since the last Atlas publish | The daily task runs | The page header SHA changes to the new `main` SHA within that run | evaluator |
| AC-21 | A laptop clone | `scripts/vault.sh` is run | `graphify-out/obsidian/` exists with one note per graph node group; `notes/` and `.obsidian/` are unchanged (same file hashes before and after) | unit |
| AC-22 | Session environment and scheduled-task prompts | Inspected | `OPENWIKI_TELEMETRY_DISABLED=1` is set in both | unit |
| AC-23 | `.gitignore` | Read | Ignores `.obsidian/`, `graphify-out/obsidian/` and Graphify's machine-local files; does not ignore `graphify-out/graph.json`, `graphify-out/GRAPH_REPORT.md`, `openwiki/`, `notes/` | unit |

Must not change:

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-24 | The existing SessionStart behaviour | A session starts | The seven plugins and three mods still install as today (`claude plugin list` shows them) | evaluator |
| AC-25 | The Stop hook (`check.sh`) on a branch with no changes under the new paths | It runs | Same pass/fail result and same checks as before this change | unit |
