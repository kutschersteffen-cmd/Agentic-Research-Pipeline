#!/usr/bin/env bash
# Is this branch behind origin/main only by planning docs? (spec holdout-faster-runs, owner decision 1)
# Run in the PR branch after `git fetch origin main`. Prints one line:
#   code: <path>  exit 1  first file changed on origin/main since the merge base that is not allowlisted
#   conflict      exit 1  merging origin/main into HEAD would conflict
#   docs-only     exit 0  otherwise, including when nothing is ahead
# A rename counts as its old and its new path (--no-renames).
# --selftest checks the cases of the spec's AC-37 in a throwaway repo and prints `selftest ok`.
set -euo pipefail

# Not allowlisted on purpose: the app reads docs/decision-studio/example-framework/*.csv and
# docs/transition_barrier/RULE_BOOK.md at run time.
allowed() {
  case "$1" in
    docs/superpowers/* | docs/adr/* | docs/handoffs/* | docs/FACTORY_RETRO_LOG.md) return 0 ;;
    *) return 1 ;;
  esac
}

check() {
  local base path rc=0
  base=$(git merge-base HEAD origin/main)
  while IFS= read -r -d '' path; do
    if ! allowed "$path"; then echo "code: $path"; return 1; fi
  done < <(git diff -z --name-only --no-renames "$base" origin/main)
  git merge-tree --write-tree HEAD origin/main >/dev/null 2>&1 || rc=$?
  if [ "$rc" -eq 1 ]; then echo conflict; return 1; fi
  if [ "$rc" -ne 0 ]; then echo "error: git merge-tree failed ($rc)" >&2; return 2; fi
  echo docs-only
}

selftest() {
  local dir base
  dir=$(mktemp -d)
  # shellcheck disable=SC2064  # expand now: $dir is local and gone when the trap runs
  trap "rm -rf '$dir'" EXIT
  cd "$dir"
  export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
  git init -q -b base
  mkdir -p docs/superpowers backend
  echo a >docs/superpowers/a.md
  echo z >backend/z.py
  git add -A && git commit -qm base
  base=$(git rev-parse HEAD)

  # expect <name> <output> <exit code> <shell run on main> <shell run on the branch>
  expect() {
    local got rc=0
    git checkout -q -B branch "$base"
    eval "$5"; git add -A; git commit -qm branch --allow-empty
    git checkout -q -B main "$base"
    eval "$4"; git add -A; git commit -qm main --allow-empty
    git update-ref refs/remotes/origin/main main
    git checkout -q branch
    got=$(check) || rc=$?
    if [ "$got" != "$2" ] || [ "$rc" != "$3" ]; then
      echo "selftest FAIL: $1: got '$got' (exit $rc), want '$2' (exit $3)"
      exit 1
    fi
  }
  local mk='mkdir -p docs/adr docs/handoffs docs/decision-studio/example-framework docs/transition_barrier'
  expect "nothing ahead" docs-only 0 : "echo b >backend/b.py"
  expect "only allowlisted" docs-only 0 \
    "$mk; echo 1 >docs/adr/1.md; echo h >docs/handoffs/h.md; echo r >docs/FACTORY_RETRO_LOG.md; echo m >docs/superpowers/a.md" \
    "echo b >backend/b.py"
  expect "code" "code: backend/x.py" 1 "echo x >backend/x.py" :
  expect "framework csv" "code: docs/decision-studio/example-framework/x.csv" 1 \
    "$mk; echo x >docs/decision-studio/example-framework/x.csv" :
  expect "rule book" "code: docs/transition_barrier/RULE_BOOK.md" 1 "$mk; echo x >docs/transition_barrier/RULE_BOOK.md" :
  expect "conflict" conflict 1 "echo m >docs/superpowers/a.md" "echo b >docs/superpowers/a.md"
  expect "code and conflict" "code: backend/y.py" 1 \
    "echo m >docs/superpowers/a.md; echo y >backend/y.py" "echo b >docs/superpowers/a.md"
  expect "rename into docs" "code: backend/z.py" 1 "git mv backend/z.py docs/superpowers/z.md" :
  echo "selftest ok"
}

if [ "${1:-}" = --selftest ]; then selftest; else check; fi
