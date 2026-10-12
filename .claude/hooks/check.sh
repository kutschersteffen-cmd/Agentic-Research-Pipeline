#!/bin/bash
# Stop hook: lint and test the code changed on this branch before Claude may finish.
# Exit 0 = pass or nothing to check; exit 2 = failure, details on stderr (fed back to Claude).
# Self-check: bash .claude/hooks/check_selftest.sh

active=$(python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("stop_hook_active", False))
except Exception: print(False)')
[ "$active" = "True" ] && exit 0

cd "$(git rev-parse --show-toplevel)" || exit 0
base=$(git merge-base HEAD origin/main 2>/dev/null || echo HEAD)

py=() tests=() frontend=0
while IFS= read -r f; do
  [ -f "$f" ] || continue  # deleted
  case "$f" in
    backend/tests/*.py) py+=("${f#backend/}"); tests+=("${f#backend/}") ;;
    backend/*.py) py+=("${f#backend/}") ;;
    frontend/node_modules/*) ;;
    frontend/*) frontend=1 ;;
  esac
done < <({ git diff --name-only "$base"; git ls-files --others --exclude-standard; } | sort -u)

[ ${#py[@]} -eq 0 ] && [ $frontend -eq 0 ] && exit 0

failures=""
run() {  # run DIR CMD... ; record output on failure
  local dir=$1 out code; shift
  out=$(cd "$dir" && "$@" 2>&1); code=$?
  [ "$3" = pytest ] && [ $code -eq 5 ] && return  # no tests collected
  [ $code -ne 0 ] && failures+=$'\n'"\$ (cd $dir && $*)"$'\n'"$(tail -n 50 <<<"$out")"$'\n'
}
need() {  # need TOOL INSTALL_HINT
  if [ "$1" = pytest ]; then python3 -c 'import pytest' 2>/dev/null && return 0
  else command -v "$1" >/dev/null && return 0; fi
  failures+=$'\n'"$1 not found. Install with: $2"$'\n'; return 1
}

if [ ${#py[@]} -gt 0 ]; then
  if need ruff 'pip install -e "backend[dev]"'; then run backend ruff check "${py[@]}"; fi
  for p in "${py[@]}"; do
    case "$p" in tests/*) continue ;; esac
    mod=${p%.py}; mod=${mod//\//.}
    while IFS= read -r t; do tests+=("$t"); done < <(cd backend && grep -rlF "$mod" tests --include='*.py')
  done
  if [ ${#tests[@]} -gt 0 ] && need pytest 'pip install -e "backend[dev]"'; then
    mapfile -t tests < <(printf '%s\n' "${tests[@]}" | sort -u)
    run backend python3 -m pytest -q "${tests[@]}"  # not bare pytest: it may be a uv tool without backend deps
  fi
fi

if [ $frontend -eq 1 ]; then
  if [ -d frontend/node_modules ]; then
    run frontend npm run lint
    run frontend npx tsc -b
    run frontend npm test
  else
    failures+=$'\n'"frontend/node_modules missing. Install with: (cd frontend && npm ci)"$'\n'
  fi
fi

[ -z "$failures" ] && exit 0
echo "Checks failed on the code you changed. Fix them before finishing:$failures" >&2
exit 2
