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

py=() mods=() tests=() frontend=0  # py: existing files to lint; mods: modules whose tests to run
while IFS= read -r f; do
  case "$f" in
    backend/tests/*.py) [ -f "$f" ] && { py+=("${f#backend/}"); tests+=("${f#backend/}"); } ;;
    backend/*.py) mods+=("${f#backend/}"); [ -f "$f" ] && py+=("${f#backend/}") ;;
    frontend/node_modules/*) ;;
    frontend/*) frontend=1 ;;  # deletions count too: they can break imports
  esac
done < <({ git diff --name-only "$base"; git ls-files --others --exclude-standard; } | sort -u)

[ ${#py[@]} -eq 0 ] && [ ${#mods[@]} -eq 0 ] && [ $frontend -eq 0 ] && exit 0

# Skip when nothing changed since the last passing run: a long branch would otherwise
# re-run the same tests at the end of every turn.
stamp="$(git rev-parse --git-dir)/claude-check-passed"
hash=$({ git diff "$base"; git ls-files --others --exclude-standard -z | xargs -0 -r cat; } 2>/dev/null | git hash-object --stdin)
[ "$(cat "$stamp" 2>/dev/null)" = "$hash" ] && exit 0

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

# Same values as CI (.github/workflows/ci.yml) and the cloud setup script.
export ARP_TEST_POSTGRES_DSN=${ARP_TEST_POSTGRES_DSN:-postgresql+psycopg://arp:arp@localhost:5432/arp_test}
[ -z "$ARP_CHROMIUM_PATH" ] && [ -x /opt/pw-browsers/chromium ] && export ARP_CHROMIUM_PATH=/opt/pw-browsers/chromium
postgres_up() {  # conftest fails, not skips, without Postgres; only checkable for the default DSN
  [[ "$ARP_TEST_POSTGRES_DSN" != *@localhost:5432/* ]] && return 0
  pg_isready -q -h localhost 2>/dev/null && return 0
  failures+=$'\n'"Postgres is not running on localhost. Start it (see the setup script in docs/superpowers/specs/2026-10-11-engineering-process-design.md) or set ARP_TEST_POSTGRES_DSN."$'\n'
  return 1
}

if [ ${#py[@]} -gt 0 ] || [ ${#mods[@]} -gt 0 ]; then
  if [ ${#py[@]} -gt 0 ] && need ruff 'pip install -e "backend[dev]"'; then run backend ruff check "${py[@]}"; fi
  for p in "${mods[@]}"; do
    mod=${p%.py}; mod=${mod//\//.}
    while IFS= read -r t; do tests+=("$t"); done < <(cd backend && grep -rlF "$mod" tests --include='*.py')
  done
  if [ ${#tests[@]} -gt 0 ] && need pytest 'pip install -e "backend[dev]"' && postgres_up; then
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

[ -z "$failures" ] && { echo "$hash" > "$stamp"; exit 0; }
echo "Checks failed on the code you changed. Fix them before finishing:$failures" >&2
exit 2
