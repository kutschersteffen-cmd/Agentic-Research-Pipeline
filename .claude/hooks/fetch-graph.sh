#!/bin/bash
# Downloads graph.json, GRAPH_REPORT.md and meta.json from origin/context-data into graphify-out/ of the
# current directory's checkout, replacing the old files only once all three arrived.
# Used by context-stack.sh (its fetch-graph step), scripts/vault.sh and the context-refresh skill, which may
# run at the same time: the fetched ref and the tmp files carry this process's id, so runs never clobber
# each other's (a shared FETCH_HEAD can be read half-written).
# Exits non-zero on failure.
cd "$(git rev-parse --show-toplevel)" || exit
ref=refs/arp-context/fetch-$$
trap 'rm -f graphify-out/.*.$$.tmp; git update-ref -d "$ref" 2>/dev/null' EXIT
git fetch --quiet --no-write-fetch-head --refmap= origin "+refs/heads/context-data:$ref" || exit
mkdir -p graphify-out || exit
for f in graph.json GRAPH_REPORT.md meta.json; do
  git show "$ref:$f" >"graphify-out/.$f.$$.tmp" || exit
done
for f in graph.json GRAPH_REPORT.md meta.json; do
  mv "graphify-out/.$f.$$.tmp" "graphify-out/$f" || exit
done
