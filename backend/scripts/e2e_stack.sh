#!/bin/bash
# Slim app stack for browser tests and the evaluator agent: the API on :8000 and the built frontend
# on :5173 (the default CORS origin), with demo data seeded, against Postgres (the system of record).
# No OpenSearch, MinIO or Superset. Auth runs in its default dev mode, so local requests are signed in.
# Postgres: the CI service, or `bash .claude/hooks/ensure-deps.sh postgres` in a cloud session.
# Neo4j (company graph, theme exposure layers): the CI service, or `ensure-deps.sh neo4j` (the test graph, :7688). Optional:
# start with ARP_NEO4J_URI= (empty) to see the app without it.
#
#   bash backend/scripts/e2e_stack.sh up     # prints ARP_E2E_URL=... once both answer
#   bash backend/scripts/e2e_stack.sh down
#
# shortcut: writes demo data into the repo's default data dirs (gitignored); give each run its own
# ARP_*_dir settings if parallel runs ever need isolation.
set -euo pipefail
export ARP_POSTGRES_DSN=${ARP_POSTGRES_DSN:-postgresql+psycopg://arp:arp@localhost:5432/arp_test}
export ARP_NEO4J_URI=${ARP_NEO4J_URI-bolt://localhost:7688} ARP_NEO4J_PASSWORD=${ARP_NEO4J_PASSWORD:-arp_neo4j_test}
root=$(cd "$(dirname "$0")/../.." && pwd)
state=${TMPDIR:-/tmp}/arp-e2e
mkdir -p "$state"

wait_for() {  # wait_for URL NAME LOG
  for _ in $(seq 1 60); do curl -sf "$1" >/dev/null && return 0; sleep 1; done
  echo "$2 did not answer at $1; last log lines:" >&2
  tail -20 "$3" >&2
  return 1
}

case "${1:-up}" in
  up)
    cd "$root/backend"
    arp db init-postgres >/dev/null
    arp portfolio seed-demo >/dev/null
    nohup uvicorn arp.api.main:app --host 127.0.0.1 --port 8000 >"$state/api.log" 2>&1 &
    echo $! >"$state/api.pid"
    cd "$root/frontend"
    node_modules/.bin/vite build >"$state/build.log" 2>&1
    nohup node_modules/.bin/vite preview --host localhost --port 5173 --strictPort >"$state/web.log" 2>&1 &
    echo $! >"$state/web.pid"
    wait_for http://127.0.0.1:8000/api/health API "$state/api.log"
    wait_for http://localhost:5173/ Frontend "$state/web.log"
    echo "ARP_E2E_URL=http://localhost:5173"
    ;;
  down)
    for p in api web; do
      [ -f "$state/$p.pid" ] && kill "$(cat "$state/$p.pid")" 2>/dev/null || true
      rm -f "$state/$p.pid"
    done
    ;;
  *) echo "Usage: $0 up|down" >&2; exit 2 ;;
esac
