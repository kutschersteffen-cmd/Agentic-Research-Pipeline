---
name: install-deps
description: Install the backend, frontend and Postgres dependencies in the background so tests are ready before they are needed. Use when the user types /install-deps or asks to pre-install or warm up dependencies.
---

Run `bash .claude/hooks/ensure-deps.sh all` with the Bash tool's `run_in_background: true`, then
tell the user in one line that the install started (about 3–4 minutes on a fresh container,
about 1 second when everything is already installed) and carry on with other work.

When it finishes, report the exit code. On failure, show the last lines of its output.

The checks install on demand anyway (the Stop hook and the `ensure-deps.sh` line in
`CLAUDE.md`), so this only moves the wait earlier. Parts that are already installed are skipped,
and a check that starts during the install waits for it instead of installing twice.
