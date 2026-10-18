#!/bin/bash
# Self-check for build_graph.sh: runs each scenario in a tiny throwaway git repo and asserts exit code and output.
# Usage: bash scripts/build_graph_selftest.sh
repo=$(git rev-parse --show-toplevel)
build="$repo/scripts/build_graph.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp" || exit 1
git init -q && git config user.email t@t && git config user.name t
cp "$repo/.graphifyignore" .
mkdir data runs engagements ballots
echo 'def CTX_IGNORE_CANARY_OK(): return 1' > x_ok.py
for f in x_secret.py x_credential.py data/x.py runs/x.py engagements/x.py ballots/x.py; do
  echo 'def CTX_IGNORE_CANARY(): return 1' > "$f"
done
git add -A && git commit -qm fixture
failed=0

# scenario NAME WANT_EXIT CHECK [ENV=VALUE...]   (CHECK is shell run in the repo after the build)
scenario() {
  local name=$1 want=$2 check=$3 got
  shift 3
  env "$@" bash "$build" >/dev/null 2>&1
  got=$?
  if [ "$got" = "$want" ] && bash -c "$check"; then
    echo "PASS $name"
  else
    echo "FAIL $name (exit $got, want $want)"
    failed=1
  fi
  rm -rf graphify-out
}

scenario canary 0 '
  grep -q CTX_IGNORE_CANARY_OK graphify-out/graph.json && ! grep -rqw CTX_IGNORE_CANARY graphify-out/'

echo '{"nodes":[{"id":"doc_probe","file_type":"document","source_file":"docs/x.md"}],"links":[]}' > "$tmp/prev.json"
scenario keeps_doc_nodes 0 'grep -q doc_probe graphify-out/graph.json' ARP_PREV_GRAPH="$tmp/prev.json"

mkdir graphify-out && echo previous > graphify-out/graph.json
scenario forced_failure 1 '[ "$(cat graphify-out/graph.json)" = previous ]' ARP_CONTEXT_FAIL=build
rm -rf graphify-out

scenario meta 0 '
  python3 -c "
import json, re, subprocess, sys
m = json.load(open(\"graphify-out/meta.json\"))
sys.exit(not (m[\"commit\"] == subprocess.check_output([\"git\", \"rev-parse\", \"HEAD\"], text=True).strip()
              and re.fullmatch(r\"\d{4}-\d\d-\d\dT\d\d:\d\dZ\", m[\"built_at\"])))"'

exit $failed
