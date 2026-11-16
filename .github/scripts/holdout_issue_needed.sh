#!/usr/bin/env bash
# Does a failed full Holdout run on main open the `Nightly Holdout failed` issue? (spec holdout-faster-runs)
# usage: holdout_issue_needed.sh <jobs file> <completeness ok>   exit 0 = open the issue, 1 = don't
#        holdout_issue_needed.sh --selftest
# <jobs file> has one "<conclusion><TAB><job name>" line per job of this run attempt; <completeness ok> is the
# completeness check's `ok` output (true, false, or empty when it did not run).
# holdout.yml calls this only when the run itself was not cancelled (`!cancelled()`), so a hand cancel never gets
# here. A job that hits timeout-minutes concludes `cancelled`, so a cancelled job opens the issue too
# (owner decision 16 Nov 2026).
set -euo pipefail

needed() { grep -qE '^(failure|timed_out|cancelled)'$'\t' "$1" || [ "$2" != true ]; }

selftest() {
  local f
  f=$(mktemp)
  # shellcheck disable=SC2064  # expand now: $f is local
  trap "rm -f '$f'" EXIT
  # expect <want: yes|no> <completeness ok> <jobs lines...>
  expect() {
    local want=$1 ok=$2 got=no
    shift 2
    printf '%s\n' "$@" >"$f"
    if needed "$f" "$ok"; then got=yes; fi
    if [ "$got" != "$want" ]; then echo "selftest FAIL: jobs [$*] complete '$ok': got $got, want $want"; exit 1; fi
  }
  local t=$'\t'
  expect yes true "success${t}Holdout setup" "failure${t}Holdout shard 3/6"
  expect yes true "success${t}Holdout setup" "timed_out${t}Holdout shard 3/6"
  expect yes true "success${t}Holdout setup" "cancelled${t}Holdout shard 3/6"    # timeout-minutes, rule alone
  expect yes false "success${t}Holdout setup" "success${t}Holdout shard 3/6"     # completeness failed
  expect yes "" "failure${t}Holdout setup"
  expect no true "success${t}Holdout setup" "skipped${t}Holdout own rows" "success${t}Holdout shard 3/6"
  echo "selftest ok"
}

if [ "${1:-}" = --selftest ]; then selftest; else needed "$1" "${2:-}"; fi
