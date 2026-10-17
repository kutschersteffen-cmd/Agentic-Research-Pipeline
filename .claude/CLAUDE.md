# Repository conventions

## Pull requests

**The base branch for every pull request is `main`.** Always target `main`, regardless of
what GitHub reports as the repository's default branch — that setting currently points at a
`claude/*` feature branch and is wrong. Do not read the base off `git remote show origin`
or `refs/remotes/origin/HEAD`.

Agents driving a PR follow `.claude/skills/steward/SKILL.md`: a `risk:` label, a stop after three
failed fix rounds, `factory:blocked` for spec questions, at most three agent PRs in flight. Once CI is
green, the `evaluator` skill checks the spec's `evaluator` rows in the running app.
If CI goes red on `main` after a merge, the Main guard workflow opens a `Revert <sha>` PR (or an issue);
merge it, or close it when a fix is already on the way.

Branch off `main` when starting work. If a branch was created from anything else, merge
`origin/main` into it before opening the PR so the diff shows only the intended change.

## Plugins

`.claude/settings.json` declares seven marketplaces and enables a plugin from each. Neither
entry does any fetching: `extraKnownMarketplaces` only *declares* a marketplace, and
`enabledPlugins` only flips a plugin on once it is installed. So each collaborator has to
register every marketplace and run every install once themselves:

```
claude plugin marketplace add DietrichGebert/ponytail
claude plugin marketplace add nextlevelbuilder/ui-ux-pro-max-skill
claude plugin marketplace add pbakaus/impeccable
claude plugin install ponytail@ponytail
claude plugin install ui-ux-pro-max@ui-ux-pro-max-skill
claude plugin install impeccable@impeccable
```

The `marketplace add` lines are the step that is easy to miss. Skip them and the install
fails with `Plugin "ponytail" not found in marketplace "ponytail"` — which reads as if the
plugin were missing, when really the marketplace was never cloned. `claude plugin marketplace
list` printing `No marketplaces configured` confirms that case.

A `SessionStart` hook (`.claude/hooks/install-plugins.sh`, wired up in `settings.json`) now
runs those commands for you. It is idempotent — it skips anything already installed and
prints nothing — and it always exits 0, so a failure never blocks session start. It exists
mainly for cloud sessions (claude.ai/code and the mobile **Code** tab), which get a fresh
container every time and cannot run `/plugin` at all. Running the commands by hand is still
fine, and still the faster path on a local machine.

Hooks load at session start, so start a new session after installing before expecting
ponytail to take effect. That applies to the hook too: it installs the plugins during startup,
after the plugin registry has already been read, so the skills it fetches become selectable in
the *following* session. For cloud sessions each new session is a fresh container, which means
the first one after a container boot pays the install and the skills are live from then on. To
have them ready in the very first session instead, run the same commands from the cloud
environment's setup script, which runs before the session starts.

- **ponytail** — "lazy senior dev mode". Its hooks run on `SessionStart`, `SubagentStart`
  and `UserPromptSubmit`, and require `node` on `PATH`.
- **ui-ux-pro-max** — UI/UX design intelligence (styles, palettes, typography, charts,
  per-stack guidelines). Skills only, no hooks; its scripts run on demand and need `python3`.
- **impeccable** — frontend design fluency: one skill with sub-commands (`/impeccable:impeccable
  polish`, `audit`, `critique`, …) plus anti-pattern detection. Its hooks run on `SessionStart`,
  `PostToolUse` (Edit/Write) and `Stop`.

`settings.json` also enables three more plugins, which the same hook installs. By hand:

```
claude plugin marketplace add ayghri/i-have-adhd
claude plugin marketplace add forrestchang/andrej-karpathy-skills
claude plugin marketplace add blader/humanizer
claude plugin install i-have-adhd@i-have-adhd
claude plugin install andrej-karpathy-skills@karpathy-skills
claude plugin install humanizer@humanizer
```

- **i-have-adhd** — ADHD-friendly output: next action first, numbered steps, no tangents.
  `/i-have-adhd`. Always-on here: `install-plugins.sh` creates `~/.claude/.i-have-adhd-always`
  every session, so the plugin's own `SessionStart` hook loads the full ruleset. Say "stop adhd
  mode" to turn it off for one session; delete the `touch` line in the hook to opt out for good.
- **andrej-karpathy-skills** — the `karpathy-guidelines` skill: think before coding, simplicity
  first, surgical changes, goal-driven execution. Skill only.
- **humanizer** — rewrites AI-sounding text so it reads naturally. `/humanizer:humanizer`.
  Skill only.

And one more, the same way:

```
claude plugin marketplace add obra/superpowers-marketplace
claude plugin install superpowers@superpowers-marketplace
```

- **superpowers** — development workflow skills: brainstorming, writing plans, TDD,
  systematic debugging, worktrees. Its `SessionStart` hook loads `using-superpowers`.

## Which plugin does what

superpowers and ponytail pull in opposite directions (process vs. minimalism), so each owns a
phase:

- **Planning → superpowers.** For non-trivial work use `superpowers:brainstorming`, then
  `superpowers:writing-plans`. Apply ponytail's ladder to the plan itself: cut tasks that
  don't need to exist before writing them down. Trivial changes skip planning.
  Every spec ends with an `## Acceptance` table in the format of
  `docs/superpowers/ACCEPTANCE_TEMPLATE.md`; run the `spec-critic` skill on it, then the owner
  approves it before implementation starts.
- **Implementation → ponytail.** Smallest working diff; follow the plan's tasks, not more.
- **Frontend design → impeccable and ui-ux-pro-max**, as before. After a UI change, screenshot
  the affected page with Playwright and run `/impeccable:impeccable audit`.
- **Review → ponytail.** Review with `/ponytail:ponytail-review` (over-engineering) plus
  `/code-review` (correctness). Do not use `superpowers:requesting-code-review` or
  `superpowers:receiving-code-review`.
- **Finishing → no auto-merge.** `superpowers:finishing-a-development-branch` must open a PR
  against `main` (see above); never merge locally.

## Coding rules (on top of ponytail)

The gaps ponytail leaves from `karpathy-guidelines`. Where they clash, these win.

- Ambiguity that would change the result → ask one question first. Otherwise default and say so.
- Don't touch adjacent code, comments or formatting. Mention unrelated dead code, don't delete it.
- Remove imports/variables your own change made unused.
- Never delete or weaken an existing test to make it pass. List every test change in the PR
  description.

## Checks

- Backend: `cd backend && ruff check . && python3 -m pytest tests/<file>`
- Frontend: `cd frontend && npm run lint && npx tsc -b && npm test`
- API contract: after changing a request or response model, run `cd backend && python scripts/export_openapi.py`
  then `cd frontend && npm run gen:api`, fix the type errors `tsc -b` reports, and commit both generated files.
  A new `request<T>()` against an endpoint with a response model gets a line in `frontend/src/api/contract.ts`.
- Browser flow (cloud session): `bash .claude/hooks/ensure-deps.sh postgres && bash backend/scripts/e2e_stack.sh up`,
  then `cd backend && ARP_E2E_URL=http://localhost:5173 ARP_CHROMIUM_PATH=$(ls -d /opt/pw-browsers/chromium-*/chrome-linux/chrome | head -1) pytest -m e2e tests/e2e`;
  `e2e_stack.sh down` when done. CI runs it as the "E2E (browser)" job.
- Mutation check (do the tests catch bugs?): `cd backend && pip install mutmut==3.8.0 && python scripts/mutation_check.py --base origin/main`
  (some tests need `ARP_TEST_POSTGRES_DSN`). CI runs it nightly and on `risk:high` PRs; surviving mutants are weak tests.
  Frontend: `python3 .github/scripts/mutation_frontend.py --base=origin/main` (Stryker via npx, `frontend/stryker.config.json`).
- Dependencies install on demand: run `bash .claude/hooks/ensure-deps.sh backend` (or `frontend`,
  `postgres`) before running tests by hand. It takes about 1 s when already installed. `/install-deps`
  installs everything in the background.

The Stop hook (`.claude/hooks/check.sh`) runs these on the code you changed and blocks finishing
on failure; CI runs the full suites.

## Invoking skills

The `/` autocomplete menu is a terminal-only feature. In cloud sessions — claude.ai/code and
the mobile **Code** tab — the composer is a plain chat box with no picker, so type the skill
name (`/graphify`) and send it, or just describe what you want and let the description trigger
it. Plugin skills are namespaced: `/ponytail:ponytail-review`, `/ui-ux-pro-max:design`.

## Matt Pocock skills

Six skills from [mattpocock/skills](https://github.com/mattpocock/skills) (MIT, upstream
`49dd158`) are copied into `.claude/skills/`, not installed as a plugin, so they can be edited
and don't duplicate superpowers. Local edit: `handoff` and `improve-codebase-architecture` save to
`docs/handoffs/` and `docs/architecture-reviews/` instead of `/tmp`, so cloud sessions keep them.
Keep that edit when re-copying from upstream.

- `domain-modeling` — maintain `GLOSSARY.md` and ADRs in `docs/adr/`.
- `research` — answer a question from primary sources, saved as a cited Markdown file.
- `codebase-design` — deep-module vocabulary; `/improve-codebase-architecture` builds on it.
- `handoff` — `/handoff` writes a handoff doc for the next session.
- `grilling` — only as the interview step of `/improve-codebase-architecture`. For planning,
  `superpowers:brainstorming` still owns the phase.

## Mods

Three mods live in `.claude/mods/`. The repo root is a plugin marketplace
(`.claude-plugin/marketplace.json`, name `arp-mods`), and `install-plugins.sh` installs the mods
from it like the plugins above, so they are live from the session after the one that installed
them. They are read straight from `.claude/mods/`: after editing one, run `/reload-plugins`. By hand:

```
claude plugin marketplace add .
claude plugin install runs-pane@arp-mods
claude plugin install test-guard@arp-mods
claude plugin install token-usage@arp-mods
```

Keep them out of `.claude/skills/`: a trusted workspace would load them from there a second time.

- `test-guard` — toast + status line when an edit under `backend/tests/` or `frontend/tests/`
  removes tests or asserts (counted by regex). Never blocks the edit.
- `runs-pane` — live pane of `arp runs list`, refreshed every 15 s; `/runs` refreshes now.
  Needs `ARP_POSTGRES_DSN` and the backend installed, else it shows the error.
- `token-usage` — status line after each turn: context fill, session cost, rate-limit use
  (`ctx 45k/200k (23%) · $1.23 · 5h 42%`).

Check one with `claude plugin validate .claude/mods/<mod>` and `claude plugin test .claude/mods/<mod>`.

# graphify
- **graphify** (`.claude/skills/graphify/SKILL.md`) - any input to knowledge graph. Trigger: `/graphify`
When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.
