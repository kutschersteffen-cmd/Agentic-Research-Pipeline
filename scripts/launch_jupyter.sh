#!/bin/bash
# ARP on one port for a JupyterLab behind Jupyter Server Proxy (docs/INSTALLATION.md "Bank Jupyter (Vertex)").
# The API serves the built frontend (ARP_FRONTEND_DIST), so the browser needs only port 8000:
#
#   scripts/launch_jupyter.sh up      # init the database, build the frontend if stale, start, print the URL
#   scripts/launch_jupyter.sh down
#   scripts/launch_jupyter.sh check   # readiness: 7 lines, each should start with "ok" (arp preflight)
#
# Settings come from the environment or backend/.env.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
state=${TMPDIR:-/tmp}/arp-jupyter
log=$state/api.log
pidfile=$state/api.pid
port=${ARP_LAUNCH_PORT:-8000}  # 8000 is what the Jupyter proxy URL below assumes; override only for tests
mkdir -p "$state"

setting() {  # setting NAME: its value from the environment, else from backend/.env; empty when unset
  local value=${!1:-}
  if [ -z "$value" ] && [ -f "$root/backend/.env" ]; then
    value=$(grep -E "^$1=" "$root/backend/.env" | tail -1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//' || true)
  fi
  printf '%s' "$value"
}

running() { [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; }

port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; }

stop() {
  if running; then
    kill "$(cat "$pidfile")" 2>/dev/null || true
    for _ in $(seq 1 20); do running || break; sleep 0.5; done
    running && kill -9 "$(cat "$pidfile")" 2>/dev/null || true
  fi
  rm -f "$pidfile"
}

case "${1:-}" in
  up)
    required="ARP_POSTGRES_DSN ARP_LLM_MODEL ARP_LLM_VERIFIER_MODEL"
    [ "$(setting ARP_GEMINI_USE_VERTEX)" = "true" ] && required="$required ARP_GCP_PROJECT"
    missing=0
    for name in $required; do
      [ -n "$(setting "$name")" ] || { echo "$name is not set (environment or backend/.env)" >&2; missing=1; }
    done
    [ "$missing" = 0 ] || exit 1
    if running; then
      echo "already running (pid $(cat "$pidfile"))"
      exit 0
    fi
    if port_busy; then
      echo "port $port is in use by another process" >&2
      exit 1
    fi
    cd "$root/backend"
    python3 -m arp db init-postgres >/dev/null
    cd "$root/frontend"
    if [ ! -f dist/index.html ] || [ -n "$(find src index.html -newer dist/index.html -print -quit)" ]; then
      [ -d node_modules ] || npm ci >"$state/npm.log" 2>&1
      VITE_API_BASE=. npm run build >"$state/build.log" 2>&1 || { echo "frontend build failed, see $state/build.log" >&2; exit 1; }
    fi
    cd "$root/backend"
    ARP_FRONTEND_DIST="$root/frontend/dist" nohup python3 -m uvicorn arp.api.main:app --host 0.0.0.0 --port "$port" >"$log" 2>&1 &
    echo $! >"$pidfile"
    for _ in $(seq 1 120); do
      if curl -sf "http://127.0.0.1:$port/api/health" >/dev/null; then
        if [ -n "${JUPYTERHUB_SERVICE_PREFIX:-}" ]; then
          echo "${JUPYTERHUB_SERVICE_PREFIX%/}/proxy/$port/"
        else
          echo "http://localhost:$port/"
        fi
        exit 0
      fi
      running || break
      sleep 1
    done
    stop
    echo "ARP did not start, see $log" >&2
    tail -5 "$log" >&2 || true
    exit 1
    ;;
  down)
    stop
    ;;
  check)
    cd "$root/backend"
    exec python3 -m arp preflight --base-url "http://127.0.0.1:$port"
    ;;
  *)
    echo "Usage: $0 up|down|check" >&2
    exit 2
    ;;
esac
