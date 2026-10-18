#!/bin/bash
# Prepares the repo for Obsidian: downloads last night's graph from origin/context-data into graphify-out/
# and exports it as notes into graphify-out/obsidian. Then open the repo root as a vault.
# Usage: bash scripts/vault.sh   (runs on the checkout of the current directory)
# Writes only under graphify-out/ (gitignored); never touches notes/ or .obsidian/, starts no server.
fetch="$(cd "$(dirname "$0")/.." && pwd)/.claude/hooks/fetch-graph.sh"
cd "$(git rev-parse --show-toplevel)" || exit 1
command -v graphify >/dev/null ||
  { echo "vault.sh: graphify not found; install it with: pip install graphifyy==0.9.92" >&2; exit 1; }
bash "$fetch" || { echo "vault.sh: could not download the graph from origin/context-data" >&2; exit 1; }
graphify export obsidian --graph graphify-out/graph.json --dir graphify-out/obsidian
