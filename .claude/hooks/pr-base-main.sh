#!/usr/bin/env bash
# PreToolUse hook for mcp__github__create_pull_request.
# Every PR in this repo targets main (see .claude/CLAUDE.md). The GitHub default branch is wrong,
# so a PR that takes the default is the usual mistake. Exit 2 blocks the call and the message
# on stderr goes back to Claude.
command -v jq >/dev/null 2>&1 || exit 0  # no jq: fail open rather than block every PR
base=$(jq -r '.tool_input.base // empty' 2>/dev/null)
if [ "$base" != "main" ]; then
  echo "Blocked: PRs must target main (got base='${base:-<missing>}'). Set base to main and retry." >&2
  exit 2
fi
exit 0
