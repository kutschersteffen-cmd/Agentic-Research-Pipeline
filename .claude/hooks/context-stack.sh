#!/bin/bash
# SessionStart hook: installs graphify and OpenWiki and fetches last night's graph from origin/context-data.
# Usage: bash .claude/hooks/context-stack.sh [--foreground]
#   default       starts the job in the background and returns at once
#   --foreground  runs the job inline (for tests)
# Runs in the git checkout of the current directory. Logs each step to ~/.cache/arp-context/session.log;
# ARP_CONTEXT_FAIL=<step> forces that step to fail. Writes nothing to stdout and always exits 0.
export OPENWIKI_TELEMETRY_DISABLED=1

if [ "${1:-}" != --foreground ]; then
  nohup bash "$0" --foreground </dev/null >/dev/null 2>&1 &
  exit 0
fi

exec </dev/null >/dev/null
log="$HOME/.cache/arp-context/session.log"
mkdir -p "${log%/*}" && : >"$log" || exit 0
cd "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null

# step NAME COMMAND...: runs the command, logs "ok" or "failed (<its error line>)"
step() {
  local name=$1 out rc
  shift
  if [ "${ARP_CONTEXT_FAIL:-}" = "$name" ]; then
    out=forced
  else
    out=$("$@" 2>&1) && { echo "arp-context: $name ok" >>"$log"; return; }
    rc=$?
    out=$(tr -d '\r' <<<"$out" | grep -v '^[[:space:]]*$')
    # pip and npm print their error first and then advice or a log path, so prefer the first error line.
    out=$(grep -m1 -E '^(npm )?(error|ERROR)' <<<"$out" || tail -n 1 <<<"$out")
    out=${out:-exit $rc}
  fi
  echo "arp-context: $name failed (${out:0:300})" >>"$log"
}

install_graphify() { graphify --version 2>/dev/null | grep -qF 0.9.92 || pip install --quiet graphifyy==0.9.92; }
# openwiki has no --version flag; npm knows what is installed.
install_openwiki() { npm ls -g --depth=0 openwiki 2>/dev/null | grep -qF openwiki@0.7.2 || npm install -g --loglevel=error openwiki@0.7.2; }
# "installed" means both the committed .mcp.json entry and .claude/skills/openwiki are intact.
register_openwiki() {
  openwiki integrations list --project . | grep -q '^claude[[:space:]]installed' ||
    { echo "openwiki claude integration not installed (.mcp.json, .claude/skills/openwiki)"; return 1; }
}
fetch_graph() {
  local f
  git fetch --quiet origin context-data || return
  mkdir -p graphify-out || return
  for f in graph.json GRAPH_REPORT.md meta.json; do
    git show "FETCH_HEAD:$f" >"graphify-out/.$f.tmp" || return
  done
  for f in graph.json GRAPH_REPORT.md meta.json; do
    mv "graphify-out/.$f.tmp" "graphify-out/$f" || return
  done
}

step install-graphify install_graphify
step install-openwiki install_openwiki
step register-openwiki register_openwiki
step fetch-graph fetch_graph
rm -f graphify-out/.*.tmp
exit 0
