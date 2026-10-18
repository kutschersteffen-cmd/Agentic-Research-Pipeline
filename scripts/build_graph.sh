#!/bin/bash
# Build the Graphify knowledge graph of the repo (run from the repo root) into graphify-out/.
# Usage: bash scripts/build_graph.sh [--with-docs]
#   default      code only (no API key); doc nodes are carried over from $ARP_PREV_GRAPH if it exists
#   --with-docs  also extract docs with Claude (needs ANTHROPIC_API_KEY)
# Output is built in a temp dir and moved at the end, so a failed build leaves graphify-out/ as it was.
set -euo pipefail

graphify --version 2>/dev/null | grep -q 0.9.92 || pip install --quiet graphifyy==0.9.92

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
out="$tmp/graphify-out"
prev_meta=""
[ -n "${ARP_PREV_GRAPH:-}" ] && prev_meta="$(dirname "$ARP_PREV_GRAPH")/meta.json"

[ "${ARP_CONTEXT_FAIL:-}" = build ] && { echo "build_graph: forced failure (ARP_CONTEXT_FAIL=build)" >&2; exit 1; }

if [ "${1:-}" = --with-docs ]; then
  graphify extract . --backend claude --out "$tmp"
else
  graphify extract . --code-only --out "$tmp"
  # `graphify update` drops non-code nodes, so re-add the previous ones (and links touching them) by hand.
  if [ -f "${ARP_PREV_GRAPH:-}" ]; then
    OUT="$out/graph.json" python3 - <<'PY'
import json, os
g = json.load(open(os.environ["OUT"]))
p = json.load(open(os.environ["ARP_PREV_GRAPH"]))
# Code files also yield rationale nodes, which the fresh extract owns: skip nodes from those extensions or with a fresh id.
# shortcut: a language that vanished from the repo keeps its stale rationale nodes, rebuild with --with-docs to clear.
ext = lambda n: os.path.splitext(n.get("source_file") or "")[1]
code_ext = {ext(n) for n in g["nodes"]}
fresh = {n["id"] for n in g["nodes"]}
kept = [n for n in p["nodes"] if n.get("file_type") != "code" and n["id"] not in fresh and ext(n) not in code_ext]
g["nodes"] += kept
ids = {n["id"] for n in g["nodes"]}
kept_ids = {n["id"] for n in kept}
g["links"] += [l for l in p["links"]
               if l["source"] in ids and l["target"] in ids and (l["source"] in kept_ids or l["target"] in kept_ids)]
json.dump(g, open(os.environ["OUT"], "w"))
PY
  fi
fi

# Backend none: keep "Community N" names instead of labelling them with a model call.
GRAPHIFY_BACKEND=none graphify cluster-only "$tmp"

OUT="$out/meta.json" PREV_META="$prev_meta" WITH_DOCS="${1:-}" python3 - <<'PY'
import datetime, json, os, subprocess
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
docs = None
if os.environ["WITH_DOCS"] == "--with-docs":
    docs = now
elif os.path.isfile(os.environ["PREV_META"]):
    docs = json.load(open(os.environ["PREV_META"])).get("docs_built_at")
commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
json.dump({"commit": commit, "built_at": now, "docs_built_at": docs}, open(os.environ["OUT"], "w"))
PY

mkdir -p graphify-out
mv "$out/graph.json" "$out/GRAPH_REPORT.md" "$out/meta.json" graphify-out/
