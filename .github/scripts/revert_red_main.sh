#!/bin/bash
# Prepare a revert of a commit that turned main's CI red, on a branch `revert-<short sha>`.
# A merge commit is reverted against its first parent (main as it was before the merge).
# Refuses to revert a commit that is itself a revert, so a red revert never starts a loop.
#
#   bash revert_red_main.sh <sha>     prints the branch name; the caller pushes it and opens the PR
#   bash revert_red_main.sh --selftest
set -euo pipefail

revert() {  # revert SHA -> creates branch revert-<short>, prints its name
  local sha=$1 short subject parents
  short=$(git rev-parse --short "$sha")
  subject=$(git log -1 --format=%s "$sha")
  case "$subject" in Revert*) echo "refusing: $short is itself a revert ($subject)" >&2; return 3 ;; esac
  parents=$(git rev-list --parents -n 1 "$sha" | wc -w)
  git checkout -q -b "revert-$short" "$sha"
  if [ "$parents" -gt 2 ]; then git revert --no-edit -m 1 "$sha" >/dev/null; else git revert --no-edit "$sha" >/dev/null; fi
  echo "revert-$short"
}

selftest() {
  local d; d=$(mktemp -d); trap 'rm -rf "$d"' RETURN
  cd "$d" && git init -q -b main && git config user.email t@t && git config user.name t
  echo good >f && git add f && git commit -qm base
  git checkout -qb feature && echo bad >f && git commit -qam "break it" && git checkout -q main
  git merge -q --no-ff feature -m "Merge pull request #1"
  local b; b=$(revert HEAD)
  [ "$(cat f)" = good ] || { echo "selftest: merge revert left f=$(cat f)" >&2; return 1; }
  [ "$b" = "$(git branch --show-current)" ] || { echo "selftest: wrong branch" >&2; return 1; }
  git checkout -q main && echo worse >f && git commit -qam "plain change"
  revert HEAD >/dev/null && [ "$(cat f)" = bad ] || { echo "selftest: plain revert failed" >&2; return 1; }
  if revert HEAD 2>/dev/null; then echo "selftest: reverted a revert" >&2; return 1; fi
  echo "selftest ok"
}

case "${1:-}" in
  --selftest) selftest ;;
  "") echo "Usage: $0 <sha> | --selftest" >&2; exit 2 ;;
  *) revert "$1" ;;
esac
