# Repository conventions

## Pull requests

**The base branch for every pull request is `main`.** Always target `main`, regardless of
what GitHub reports as the repository's default branch — that setting currently points at a
`claude/*` feature branch and is wrong. Do not read the base off `git remote show origin`
or `refs/remotes/origin/HEAD`.

Branch off `main` when starting work. If a branch was created from anything else, merge
`origin/main` into it before opening the PR so the diff shows only the intended change.

## Plugins

`.claude/settings.json` declares six marketplaces and enables a plugin from each. Neither
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
  `/i-have-adhd`. Ships an opt-in `SessionStart` hook for always-on mode
  (`touch ~/.claude/.i-have-adhd-always`).
- **andrej-karpathy-skills** — the `karpathy-guidelines` skill: think before coding, simplicity
  first, surgical changes, goal-driven execution. Skill only.
- **humanizer** — rewrites AI-sounding text so it reads naturally. `/humanizer:humanizer`.
  Skill only.

## Invoking skills

The `/` autocomplete menu is a terminal-only feature. In cloud sessions — claude.ai/code and
the mobile **Code** tab — the composer is a plain chat box with no picker, so type the skill
name (`/graphify`) and send it, or just describe what you want and let the description trigger
it. Plugin skills are namespaced: `/ponytail:ponytail-review`, `/ui-ux-pro-max:design`.

# graphify
- **graphify** (`.claude/skills/graphify/SKILL.md`) - any input to knowledge graph. Trigger: `/graphify`
When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.
