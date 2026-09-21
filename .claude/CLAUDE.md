# Repository conventions

## Pull requests

**The base branch for every pull request is `main`.** Always target `main`, regardless of
what GitHub reports as the repository's default branch — that setting currently points at a
`claude/*` feature branch and is wrong. Do not read the base off `git remote show origin`
or `refs/remotes/origin/HEAD`.

Branch off `main` when starting work. If a branch was created from anything else, merge
`origin/main` into it before opening the PR so the diff shows only the intended change.

## Plugins

`.claude/settings.json` declares two marketplaces and enables a plugin from each. Neither
entry does any fetching: `extraKnownMarketplaces` only *declares* a marketplace, and
`enabledPlugins` only flips a plugin on once it is installed. So each collaborator has to
register both marketplaces and run both installs once themselves:

```
claude plugin marketplace add DietrichGebert/ponytail
claude plugin marketplace add nextlevelbuilder/ui-ux-pro-max-skill
claude plugin install ponytail@ponytail
claude plugin install ui-ux-pro-max@ui-ux-pro-max-skill
```

The `marketplace add` lines are the step that is easy to miss. Skip them and the install
fails with `Plugin "ponytail" not found in marketplace "ponytail"` — which reads as if the
plugin were missing, when really the marketplace was never cloned. `claude plugin marketplace
list` printing `No marketplaces configured` confirms that case.

Hooks load at session start, so start a new session after installing before expecting
ponytail to take effect.

- **ponytail** — "lazy senior dev mode". Its hooks run on `SessionStart`, `SubagentStart`
  and `UserPromptSubmit`, and require `node` on `PATH`.
- **ui-ux-pro-max** — UI/UX design intelligence (styles, palettes, typography, charts,
  per-stack guidelines). Skills only, no hooks; its scripts run on demand and need `python3`.

# graphify
- **graphify** (`.claude/skills/graphify/SKILL.md`) - any input to knowledge graph. Trigger: `/graphify`
When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.
