# Repository conventions

## Pull requests

**The base branch for every pull request is `main`.** Always target `main`, regardless of
what GitHub reports as the repository's default branch — that setting currently points at a
`claude/*` feature branch and is wrong. Do not read the base off `git remote show origin`
or `refs/remotes/origin/HEAD`.

Branch off `main` when starting work. If a branch was created from anything else, merge
`origin/main` into it before opening the PR so the diff shows only the intended change.

## Plugins

`.claude/settings.json` registers two marketplaces and enables a plugin from each.
Committed `enabledPlugins` entries do **not** auto-install a plugin from an external source,
so each collaborator has to run both installs once themselves:

```
claude plugin install ponytail@ponytail
claude plugin install ui-ux-pro-max@ui-ux-pro-max-skill
```

- **ponytail** — "lazy senior dev mode". Its hooks run on `SessionStart`, `SubagentStart`
  and `UserPromptSubmit`, and require `node` on `PATH`.
- **ui-ux-pro-max** — UI/UX design intelligence (styles, palettes, typography, charts,
  per-stack guidelines). Skills only, no hooks; its scripts run on demand and need `python3`.

# graphify
- **graphify** (`.claude/skills/graphify/SKILL.md`) - any input to knowledge graph. Trigger: `/graphify`
When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.
