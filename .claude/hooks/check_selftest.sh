#!/bin/bash
# Self-check for check.sh: runs each scenario in a throwaway clone and asserts the exit code.
# Usage: bash .claude/hooks/check_selftest.sh
repo=$(git rev-parse --show-toplevel)
hook="$repo/.claude/hooks/check.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git clone -q "$repo" "$tmp"
git -C "$tmp" update-ref refs/remotes/origin/main HEAD  # branch base = clone HEAD
failed=0

# scenario NAME EXPECTED_EXIT GREP_IN_STDERR STDIN
scenario() {
  local name=$1 want=$2 needle=$3 stdin=${4:-'{}'}
  local err got
  err=$(cd "$tmp" && echo "$stdin" | bash "$hook" 2>&1 >/dev/null)
  got=$?
  if [ "$got" = "$want" ] && { [ -z "$needle" ] || grep -q "$needle" <<<"$err"; }; then
    echo "PASS $name"
  else
    echo "FAIL $name (exit $got, want $want${needle:+, stderr should contain $needle})"
    failed=1
  fi
  git -C "$tmp" reset -q --hard && git -C "$tmp" clean -fdq
}

scenario clean_tree 0 ""

echo 'import os' > "$tmp/backend/arp/_bad.py"
scenario stop_hook_active 0 "" '{"stop_hook_active": true}'

echo x > "$tmp/docs/_x.md"
scenario docs_only 0 ""

echo 'import os' > "$tmp/backend/arp/_bad.py"
scenario ruff_failure 2 F401

printf 'def test_x():\n    assert False\n' > "$tmp/backend/tests/test__bad.py"
scenario test_failure 2 test__bad.py

echo 'X = 1' > "$tmp/backend/arp/_ok.py"
scenario no_matching_tests 0 ""

git -C "$tmp" rm -q backend/arp/api/routers/climate.py
scenario deleted_file 0 ""

exit $failed
