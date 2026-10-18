# Codebase Context Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give coding agents a daily code graph and a weekly wiki in every session, and give the owner one Atlas page (laptop, phone, Claude app) plus an Obsidian vault.

**Architecture:** A GitHub Actions workflow builds the Graphify graph from `main` nightly and force-pushes it to the orphan branch `context-data`. A SessionStart hook installs the pinned tools in the background and downloads that graph. OpenWiki runs weekly inside a scheduled Claude session and opens a wiki-only PR. A `context-refresh` skill turns the graph + wiki + notes into data files and publishes a static Atlas page as a claude.ai artifact.

**Tech Stack:** bash, Python 3 stdlib, GitHub Actions, `graphifyy==0.9.92` (PyPI), `openwiki@0.7.2` (npm, Node ≥22.22), browser JS (ES modules, `graphology@0.25.4` + `sigma@2.4.0` + `marked@12.0.2` + `dompurify@3.1.6` from cdn.jsdelivr.net), `node --test` for page logic.

**Spec:** `docs/superpowers/specs/2026-10-18-codebase-context-stack-design.md` (approved). Row IDs `AC-n` below refer to its Acceptance table.

## Global Constraints

- Pins: `graphifyy==0.9.92`, `openwiki@0.7.2`. Never `latest`.
- Graph data never committed to `main`; `graphify-out/` is gitignored entirely.
- `context-data` = orphan branch, single commit, files `graph.json`, `GRAPH_REPORT.md`, `meta.json` (`commit`, `built_at`, `docs_built_at`; times ISO 8601 UTC `YYYY-MM-DDTHH:MMZ`).
- Refresh branches: `context-refresh/YYYY-MM-DD`. Guard message: `generated file changed outside context-refresh/*: <path>`.
- Hook log: `~/.cache/arp-context/session.log`, lines `arp-context: <step> ok` / `arp-context: <step> failed (<reason>)`. Steps: `install-graphify`, `install-openwiki`, `register-openwiki`, `fetch-graph`. `ARP_CONTEXT_FAIL=<step>` forces a failure; `build_graph.sh` honours `ARP_CONTEXT_FAIL=build`.
- Hooks write nothing to stdout and always exit 0; the session hook returns within 5 s.
- `OPENWIKI_TELEMETRY_DISABLED=1` everywhere OpenWiki runs.
- Model calls only to Claude. Nothing listens on a port.
- Atlas: `Atlas: <url>` line in `.claude/CLAUDE.md`; push text on failed publish: `Atlas not republished: run /context-refresh`.
- Repo conventions: `.github/scripts/*.py` carry a `--selftest`; hook scripts get a `*_selftest.sh` twin (see `.claude/hooks/check_selftest.sh`). Never weaken existing tests.

## Review Focus

1. `context-data` does not exist yet (first day, fresh fork): the session job, `vault.sh` and the Atlas build must fail soft with a clear log line, not crash or leave partial files. → Task 3 (`fetch-graph` failure scenario), Task 5 (`build_data.py` with missing input exits 2 and writes nothing).
2. Hostile or odd text in node labels and wiki pages (`<script>`, `[[` without `]]`, very long names): the page must show it as text and sanitize rendered Markdown. → Task 5 test `escapes_labels`; Task 6 renders all labels via `textContent` and wiki HTML via DOMPurify.
3. A large graph (≥10 000 nodes): search must stay fast on a phone. → Task 5 test `search_10k_under_50ms`.
4. Nodes without a source file (concept or rationale nodes) or entity nodes inside a file: no broken "Open on GitHub" link; file node preferred in search. → Task 5 tests `github_url_none_for_concept`, `search_prefers_file_node`.
5. Weekly and daily Atlas runs on the same Monday collide on one artifact: the second publish is refused as a conflict and must re-read and republish, not create a new artifact. → Task 7 skill text, verified by firing both tasks back to back in Task 8.

---

### Task 1: Graph build script and ignore files

**Files:**
- Create: `scripts/build_graph.sh`, `scripts/build_graph_selftest.sh`, `.graphifyignore`, `.openwikiignore`
- Modify: `.gitignore` (append `graphify-out/`, `.obsidian/`)

**Interfaces:**
- Produces: `scripts/build_graph.sh [--with-docs]`. Run from the repo root. Writes `graphify-out/graph.json`, `graphify-out/GRAPH_REPORT.md`, `graphify-out/meta.json`. Reads an optional previous graph from `$ARP_PREV_GRAPH` (path) for daily mode. Exit 0 on success, non-zero on failure (CI must see the failure); never deletes a previous good output on failure (writes to a temp dir, moves at the end).

- [ ] **Step 1: Write `scripts/build_graph_selftest.sh`** (clone-to-tmp pattern from `check_selftest.sh`). Scenarios, each asserting exit code and file content:
  - `canary`: AC-18 setup (`CTX_IGNORE_CANARY` in `x_secret.py`, `x_credential.py`, `data/x.py`, `runs/x.py`, `engagements/x.py`, `ballots/x.py`; `CTX_IGNORE_CANARY_OK` in `x_ok.py`), no `ARP_PREV_GRAPH` → exit 0; `grep -q CTX_IGNORE_CANARY_OK graphify-out/graph.json`; `! grep -rqw CTX_IGNORE_CANARY graphify-out/`.
  - `keeps_doc_nodes`: `ARP_PREV_GRAPH` = a fixture graph with one node `{"id":"doc_probe","file_type":"document","source_file":"docs/x.md"}` → output graph.json contains `doc_probe`.
  - `forced_failure`: `ARP_CONTEXT_FAIL=build` → exit ≠ 0 and a pre-existing `graphify-out/graph.json` is byte-identical afterwards.
  - `meta`: `meta.json` has `commit` = `git rev-parse HEAD` and `built_at` matching `^\d{4}-\d\d-\d\dT\d\d:\d\dZ$`.
- [ ] **Step 2: Run it, expect FAIL** — `bash scripts/build_graph_selftest.sh` → `FAIL canary` (script missing).
- [ ] **Step 3: Write `.graphifyignore` and `.openwikiignore`** with exactly the 18 lines of the spec's Ignore files block; append `graphify-out/` and `.obsidian/` to `.gitignore`.
- [ ] **Step 4: Implement `scripts/build_graph.sh`.** Install `graphifyy==0.9.92` with `pip install --quiet` if `graphify --version` doesn't print `0.9.92`. Daily mode: if `$ARP_PREV_GRAPH` exists copy it to the temp `graphify-out/graph.json` and run `graphify update .`; otherwise `graphify extract . --code-only`. `--with-docs`: `graphify extract . --backend claude` (needs `ANTHROPIC_API_KEY`). Then `graphify cluster-only .` if the update path left communities stale. Write `meta.json` (`docs_built_at` = now in `--with-docs` mode, else copied from the previous meta or `null`). First confirm by running against this repo that `graphify update .` keeps non-`code` nodes; if it does not, merge them in a small inline `python3 -c` step (previous nodes with `file_type != "code"` plus links whose both ends exist).
- [ ] **Step 5: Run selftest, expect all PASS.** Also time a real run on this repo: `time bash scripts/build_graph.sh` and note the duration in the PR description.
- [ ] **Step 6: Commit** — `git add scripts/build_graph*.sh .graphifyignore .openwikiignore .gitignore && git commit -m "Add graph build script and ignore files"`.

### Task 2: `Context graph` workflow

**Files:**
- Create: `.github/workflows/context-graph.yml`

**Interfaces:**
- Consumes: `scripts/build_graph.sh [--with-docs]`, `$ARP_PREV_GRAPH` (Task 1).
- Produces: branch `context-data` with the three files.

- [ ] **Step 1: Write the workflow.** `name: Context graph`; `on: schedule: - cron: '17 2 * * *'` and `workflow_dispatch` with boolean input `with_docs`; job condition `github.ref == 'refs/heads/main'`; `permissions: contents: write`. Steps: checkout (`fetch-depth: 1`); `git fetch origin context-data` and `git show origin/context-data:graph.json > /tmp/prev.json` (ignore failure); docs mode when `github.event.schedule` and `date -u +%u` = `1`, or `inputs.with_docs`; run `ARP_PREV_GRAPH=/tmp/prev.json bash scripts/build_graph.sh [--with-docs]` with `ANTHROPIC_API_KEY: ${{ secrets.ARP_ANTHROPIC_API_KEY }}`; then in a temp dir `git init`, copy the three files, commit as `github-actions[bot]`, `git push --force origin HEAD:context-data`. The push step runs only if the build succeeded.
- [ ] **Step 2: Validate syntax** — `python3 -c "import yaml,sys; d=yaml.safe_load(open('.github/workflows/context-graph.yml')); assert d['name']=='Context graph'; print(d[True]['schedule'])"` → prints `[{'cron': '17 2 * * *'}]`.
- [ ] **Step 3: Commit** — `git commit -m "Add nightly Context graph workflow"`. (Live run is part of Task 8; AC-12/13/14/15/16/17.)

### Task 3: Session hook, OpenWiki integration and settings

**Files:**
- Create: `.claude/hooks/context-stack.sh`, `.claude/hooks/context_stack_selftest.sh`, `.mcp.json`, `.claude/skills/openwiki/` (generated)
- Modify: `.claude/settings.json`, `.claude/skills/graphify/SKILL.md` (regenerated)

**Interfaces:**
- Consumes: branch `context-data` (Task 2) via `git fetch origin context-data`.
- Produces: `graphify-out/graph.json`, `GRAPH_REPORT.md`, `meta.json` in the working tree; `graphify` and `openwiki` on PATH.

- [ ] **Step 1: Write `context_stack_selftest.sh`** (throwaway clone; a local bare repo as `origin`). Scenarios:
  - `returns_fast`: no flag, tools absent → exit 0 in ≤5 s, stdout empty (AC-3, AC-33).
  - `proxy_blocked`: `HTTPS_PROXY=HTTP_PROXY=http://127.0.0.1:9` → no-flag exit 0 ≤5 s; `--foreground` log matches `^arp-context: install-graphify failed \(.+\)$`; afterwards no child `pip install`/`npm install` process (AC-4/5/6).
  - `fetch_ok`: bare origin has `context-data` with a graph containing `ctx_probe_node` → `--foreground` writes `graphify-out/graph.json` containing it; log has `arp-context: fetch-graph ok` (AC-7).
  - `fetch_missing`: no `context-data` → exit 0; log matches `^arp-context: fetch-graph failed \(.+\)$` (AC-8).
  - `clean_tree`: after `fetch_ok`, `git status --porcelain` empty (AC-9).
  - `forced`: `ARP_CONTEXT_FAIL=register-openwiki` → log has `arp-context: register-openwiki failed (forced)`, later steps still run.
- [ ] **Step 2: Run, expect FAIL** (`returns_fast` — script missing).
- [ ] **Step 3: Implement `context-stack.sh`.** Without `--foreground`: `nohup bash "$0" --foreground >/dev/null 2>&1 &` then `exit 0`. With it: four steps in spec order, each wrapped `step <name> <command…>` that logs ok/failed and honours `ARP_CONTEXT_FAIL`. Installs: `pip install --quiet graphifyy==0.9.92` (skip if version matches), `npm install -g --silent openwiki@0.7.2` (skip if matches). `register-openwiki`: `openwiki --version` succeeds and `.mcp.json` has the `openwiki` server. `fetch-graph`: `git fetch --quiet origin context-data` then `git show origin/context-data:<f> > graphify-out/<f>` for the three files (write to temp, move on success). `export OPENWIKI_TELEMETRY_DISABLED=1` at top.
- [ ] **Step 4: Generate the OpenWiki integration** — `npm i -g openwiki@0.7.2 && OPENWIKI_TELEMETRY_DISABLED=1 openwiki integrations install claude --project .`. Expect `.mcp.json` = `{"mcpServers":{"openwiki":{"command":"openwiki","args":["mcp","--host","claude"]}}}` (or equivalent) and `.claude/skills/openwiki/SKILL.md`. Refresh `.claude/skills/graphify/SKILL.md` with `graphify install` for 0.9.92 (AC-79: file names `0.9.92`); keep the repo's existing `# graphify` CLAUDE.md section untouched.
- [ ] **Step 5: Edit `.claude/settings.json`:** add `"env": {"OPENWIKI_TELEMETRY_DISABLED": "1"}`, `"permissions": {"deny": ["Read(./graphify-out/graph.json)"]}`, `"enabledMcpjsonServers": ["openwiki"]`; add a second SessionStart hook entry `bash "${CLAUDE_PROJECT_DIR}/.claude/hooks/context-stack.sh"`, `timeout: 10`. Keep every existing key and hook.
- [ ] **Step 6: Run selftest, expect all PASS;** run `bash .claude/hooks/check_selftest.sh` too (AC-78 unchanged).
- [ ] **Step 7: Commit** — `git commit -m "Add context-stack session hook and OpenWiki integration"`.

### Task 4: Generated-files guard and CI wiring

**Files:**
- Create: `.github/scripts/context_guard.py`
- Modify: `.github/workflows/pr-guards.yml`

**Interfaces:**
- Produces: `python .github/scripts/context_guard.py --head-ref <ref> --changed <path>...` → exit 1 + `generated file changed outside context-refresh/*: <path>` per offending path; exit 0 otherwise. `--selftest` runs the four AC-21..24 cases. Without `--changed`, reads `git diff --name-only origin/main...HEAD`.

- [ ] **Step 1: Write the selftest cases inside the script** (`--selftest` asserts): `feat/x` + `openwiki/a.md` → 1 with the message; `feat/x` + `openwiki/INSTRUCTIONS.md` → 0; `context-refresh/2026-10-19` + `openwiki/a.md` → 0; `feat/x` + `backend/arp/config.py` → 0. Also `context-refresh/x` (not a date) + `openwiki/a.md` → 1.
- [ ] **Step 2: Run `--selftest`, expect FAIL** (function missing).
- [ ] **Step 3: Implement `check(head_ref: str, changed: list[str]) -> list[str]`** (returns offending paths) and `main()`; branch must match `^context-refresh/\d{4}-\d{2}-\d{2}$`.
- [ ] **Step 4: Run `--selftest`, expect PASS.**
- [ ] **Step 5: Add two jobs to `pr-guards.yml`:** `context-guard` named `Generated context guard` (checkout `fetch-depth: 0`, `python3 .github/scripts/context_guard.py --selftest`, then `--head-ref ${{ github.head_ref }}`); `context-selftests` named `Context stack self-tests` running `bash scripts/build_graph_selftest.sh`, `bash .claude/hooks/context_stack_selftest.sh`, `node --test scripts/atlas/`, `python3 scripts/atlas/build_data.py --selftest` (Node 22 via `actions/setup-node@v4`).
- [ ] **Step 6: Commit** — `git commit -m "Guard generated wiki files and run context self-tests in CI"`.

### Task 5: Atlas data builder and page logic

**Files:**
- Create: `scripts/atlas/build_data.py`, `scripts/atlas/atlas-core.mjs`, `scripts/atlas/atlas-core.test.mjs`

**Interfaces:**
- Produces:
  - `build_data.py --graph <graph.json> --meta <meta.json> --report <GRAPH_REPORT.md> --wiki openwiki --notes notes --out <dir>` → writes `<dir>/data/graph.json` (`{"nodes":[{id,label,path,community,kind,inferredDeg}],"links":[{s,t,inferred}],"communities":[{id,label,size}]}`), `<dir>/data/wiki.json` (`{"pages":[{slug,title,md}]}`), `<dir>/data/notes.json` (`{"notes":[{name,md,links:[path]}]}`), `<dir>/data/report.md`, `<dir>/data/meta.json`. Exit 2 and write nothing when `--graph` is missing. `--selftest`.
  - `atlas-core.mjs` exports: `search(index, query, limit=20) -> Node[]` (file nodes first, then by degree), `buildIndex(graph) -> Index`, `neighbourhood(graph, id, hops) -> Set<id>` (undirected), `shortestPath(graph, a, b) -> id[] | null` (undirected BFS), `statusLine({nodes, edges, inferred, hops}) -> string` (`"N nodes · M edges · K inferred"` + `" · H hops"` when hops given), `githubUrl(path) -> string | null` (`https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/main/<path>`, `null` when no path), `resolveWikiLink(href, slugs) -> {slug} | {external: href} | {missing: href}`, `notesFor(notes, path) -> string[]`.

- [ ] **Step 1: Write `atlas-core.test.mjs`** (`node:test` + `assert`): `statusLine({nodes:5,edges:7,inferred:0})` = `"5 nodes · 7 edges · 0 inferred"`; with `hops:3` ends `" · 3 hops"`; `neighbourhood` on a 5-node chain from the middle with `hops:2` has size 5, from an end has size 3; `shortestPath` on a chain returns the chain, on disconnected nodes `null`; `search_prefers_file_node` (file node `grounding.py` ranks above entity `ground()`); `github_url_none_for_concept` (`githubUrl(undefined) === null`); `escapes_labels` (search result label `<script>` comes back unchanged as data, never as HTML: assert type string and that `buildIndex` doesn't alter it); `search_10k_under_50ms` (10 000 synthetic nodes, `search` < 50 ms); `resolveWikiLink('other.md', ['other'])` → `{slug:'other'}`, `'https://x'` → external, `'nope.md'` → missing; `notesFor` finds a note whose links contain `backend/arp/grounding.py`.
- [ ] **Step 2: Run `node --test scripts/atlas/`, expect FAIL** (module missing).
- [ ] **Step 3: Implement `atlas-core.mjs`.** Pure functions, no DOM.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: `build_data.py --selftest`** asserts on a tiny fixture: INFERRED links marked `inferred: true` (Graphify `confidence == "INFERRED"`); notes' `[[...]]` targets extracted (strip `|alias`, `#heading`); `openwiki/INSTRUCTIONS.md` and `openwiki/.claims/` not in `wiki.json`; missing `--graph` → exit 2 and `--out` dir untouched. Run, expect FAIL; implement; run, expect PASS.
- [ ] **Step 6: Commit** — `git commit -m "Add Atlas data builder and page logic"`.

### Task 6: Atlas page UI and bootstrap publish

**Files:**
- Create: `scripts/atlas/index.html`, `scripts/atlas/atlas.js`, `scripts/atlas/atlas.css`

**Interfaces:**
- Consumes: `atlas-core.mjs` (Task 5); data files under `data/` at the page's relative path.

- [ ] **Step 1: Load skills first:** `artifact-design` (page contract, theming), `artifact-capabilities` (the exact ask-Claude call and how to detect it), `dataviz` (graph colours). Use the ask call only if present; `location.hash === '#noask'` forces it off.
- [ ] **Step 2: Build the page** per spec "Atlas page": header (search box, 7-char SHA, `built_at`, `docs_built_at`), laptop three panes ≥1024 px, phone layout <1024 px with tabs Explore/Wiki/Report(/Ask). Graph via sigma + graphology; INFERRED edges hidden by default and dashed when shown; status line under the graph from `statusLine`. Search results carry `data-atlas-result`. All labels via `textContent`; wiki/report Markdown via `marked` → `DOMPurify.sanitize`; wiki links resolved with `resolveWikiLink` (in-tab for slugs, new tab for external, "Page not found" for missing). Default view collapses communities when nodes > 2 000.
- [ ] **Step 3: Build bootstrap data** — `bash scripts/build_graph.sh` then `python3 scripts/atlas/build_data.py --graph graphify-out/graph.json --meta graphify-out/meta.json --report graphify-out/GRAPH_REPORT.md --wiki openwiki --notes notes --out /tmp/atlas` and copy the page files into `/tmp/atlas`.
- [ ] **Step 4: Check it in Chromium (Playwright, `/opt/pw-browsers`)** at 1440 and 390 px over a local static server: AC-44/45/47/48/49/50/53/54/55/57; measure AC-56 with 4× CPU throttle. Screenshot both widths, then run `/impeccable:impeccable audit` (CLAUDE.md rule for UI changes) and fix what it flags.
- [ ] **Step 5: Publish:** `Artifact` quickstart (`intent: "other"`), then publish `index.html` with `files` for `atlas.js`, `atlas.css`, `atlas-core.mjs`, `data/*`, icon `map`, title `Codebase Atlas`. Record the URL and the PR head SHA for the PR description (data commit, AC-59).
- [ ] **Step 6: Commit** — `git commit -m "Add Atlas page"`.

### Task 7: context-refresh skill, vault script, notes and agent rules

**Files:**
- Create: `.claude/skills/context-refresh/SKILL.md`, `scripts/vault.sh`, `notes/README.md`, `openwiki/INSTRUCTIONS.md`
- Modify: `.claude/CLAUDE.md`

**Interfaces:**
- Consumes: `build_data.py` CLI (Task 5), page files (Task 6), `context-data` (Task 2), the `Atlas:` line.

- [ ] **Step 1: `.claude/skills/context-refresh/SKILL.md`.** Frontmatter `name: context-refresh`, description naming both modes. Body: export `OPENWIKI_TELEMETRY_DISABLED=1`; **weekly** (no args): quiet-week check (`git log <last refresh merge>..origin/main --name-only` touches only `openwiki/` → stop), branch `context-refresh/$(date -u +%F)`, ask OpenWiki to "Update this repository's OpenWiki for changes since its last successful run", PR `Context refresh <date>` with label `risk:low` (reuse and retitle an open one), then Atlas step; **`--atlas-only`**: fetch `context-data`, compare `meta.json` `commit` with the page's SHA (read via `Artifact` read), stop if equal; **Atlas step**: run `build_data.py` into a scratch dir and publish to the `Atlas:` URL with `files`; on refusal because of a newer version, re-read and republish once; on any other failure send `PushNotification` with exactly `Atlas not republished: run /context-refresh` and never publish without `url`.
- [ ] **Step 2: `scripts/vault.sh`** — fetch `context-data` files into `graphify-out/` (same as the hook's `fetch-graph`), then `graphify export obsidian --dir graphify-out/obsidian`. Add to `context_stack_selftest.sh`: `vault_clean` (AC-10 `git status --porcelain` empty; AC-69 hashes of `notes/` and `.obsidian/` unchanged). Run selftest, expect PASS.
- [ ] **Step 3: `notes/README.md`** (one note per decision, `[[backend/arp/grounding.py]]`-style example link) and `openwiki/INSTRUCTIONS.md` (scope: `backend/arp`, `frontend/src`, docs; skip generated files and the ignore list; priorities: architecture, data flow, extraction/grounding/publish).
- [ ] **Step 4: `.claude/CLAUDE.md`.** Add `## Codebase context` after `## Checks` with the four ordered steps and the phrases `INFERRED`, `override`, `as of last night`, `needs an update`, `Never edit` (AC-26..28); the line `Atlas: <url from Task 6>`; the optional setup-script snippet (`pip install graphifyy==0.9.92 && npm i -g openwiki@0.7.2`); an "Open the repo in Obsidian" paragraph (`bash scripts/vault.sh`, then open the repo root as a vault). No `@`-imports. Leave `# graphify` as is.
- [ ] **Step 5: Verify** — `grep -c '^## Codebase context' .claude/CLAUDE.md` → `1`; `grep -c '^# graphify' .claude/CLAUDE.md` → `1`; `grep -E '^@(graphify-out|openwiki)/' .claude/CLAUDE.md` → exit 1.
- [ ] **Step 6: Commit** — `git commit -m "Add context-refresh skill, vault script, notes and agent rules"`.

### Task 8: PR, then post-merge bootstrap

- [ ] **Step 1: Open the PR** against `main` with `Spec: codebase-context-stack`, label `risk:medium`, the bootstrap data commit SHA, the measured build time, and every test change listed. Drive CI green per the steward skill.
- [ ] **Step 2 (after merge): Dispatch `Context graph`** with `with_docs: true`; confirm `context-data` (AC-12, AC-13).
- [ ] **Step 3: Run `/context-refresh`** once by hand on `main` → first wiki PR (AC-39/40/43); merge it after owner review; Atlas republished with wiki and doc nodes.
- [ ] **Step 4: Create the two scheduled tasks** with `create_trigger` (`create_new_session_on_fire: true`, this environment): weekly `run /context-refresh` on Mondays after 02:17 UTC (pick a minute not used by the retro task, e.g. `CRON_TZ=UTC 41 5 * * 1`), daily `run /context-refresh --atlas-only` (`CRON_TZ=UTC 37 3 * * *`). Check `list_triggers` shows the retro task unchanged (AC-38, AC-80). Fire both back to back once to check Review Focus 5.
