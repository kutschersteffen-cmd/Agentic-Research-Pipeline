#!/bin/bash
# Downloads graph.json, GRAPH_REPORT.md and meta.json from origin/context-data into graphify-out/ of the
# current directory's checkout, replacing the old files only once all three arrived.
# Used by context-stack.sh (its fetch-graph step) and scripts/vault.sh. Exits non-zero on failure.
cd "$(git rev-parse --show-toplevel)" || exit
trap 'rm -f graphify-out/.*.tmp' EXIT
git fetch --quiet origin context-data || exit
mkdir -p graphify-out || exit
for f in graph.json GRAPH_REPORT.md meta.json; do
  git show "FETCH_HEAD:$f" >"graphify-out/.$f.tmp" || exit
done
for f in graph.json GRAPH_REPORT.md meta.json; do
  mv "graphify-out/.$f.tmp" "graphify-out/$f" || exit
done
