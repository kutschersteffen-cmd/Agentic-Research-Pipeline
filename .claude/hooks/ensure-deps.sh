#!/bin/bash
# Install what the checks need, only when it is missing (~1s when everything is there).
# Usage: bash .claude/hooks/ensure-deps.sh backend|frontend|postgres|all
# Called by check.sh before running checks, by Claude before running tests by hand,
# and by the /install-deps skill to warm everything up in the background.
# A per-part lock makes concurrent calls wait for one install instead of racing.

cd "$(git rev-parse --show-toplevel)" || exit 1

backend() {
  python3 -c 'import fastapi, pytest' 2>/dev/null && command -v ruff >/dev/null && return 0
  echo "Installing backend dependencies (~3 min)..." >&2
  # CPU-only torch first: docling would otherwise pull ~4 GB of CUDA libraries.
  pip install -q torch --index-url https://download.pytorch.org/whl/cpu &&
    pip install -q -e "backend[dev]"
}

frontend() {
  [ -d frontend/node_modules ] && return 0
  echo "Installing frontend dependencies (~15 s)..." >&2
  (cd frontend && npm ci --silent)
}

postgres() {  # same DB as CI: postgresql+psycopg://arp:arp@localhost:5432/arp_test
  pg_isready -q -h localhost 2>/dev/null && return 0
  if [ ! -f /usr/share/postgresql/16/extension/vector.control ]; then
    command -v apt-get >/dev/null || { echo "Postgres 16 with pgvector is not installed; install it or set ARP_TEST_POSTGRES_DSN." >&2; return 1; }
    echo "Installing Postgres + pgvector (~1 min)..." >&2
    apt-get update -q >/dev/null && apt-get install -y -q postgresql-16-pgvector >/dev/null || return 1
  fi
  service postgresql start >/dev/null 2>&1
  su postgres -c "psql -qc \"CREATE USER arp WITH PASSWORD 'arp' SUPERUSER;\"" >/dev/null 2>&1
  su postgres -c "createdb -O arp arp_test" >/dev/null 2>&1
  pg_isready -q -h localhost 2>/dev/null || { echo "Postgres is not running on localhost." >&2; return 1; }
}

locked() {  # locked PART: run PART under its lock
  ( flock 9; "$1" ) 9>"${TMPDIR:-/tmp}/ensure-deps-$1.lock"
}

case "$1" in
  backend|frontend|postgres) locked "$1" ;;
  all)
    locked postgres & p=$!
    locked frontend & f=$!
    locked backend; b=$?
    wait $p; pc=$?; wait $f; fc=$?
    exit $(( b || pc || fc )) ;;
  *) echo "Usage: $0 backend|frontend|postgres|all" >&2; exit 2 ;;
esac
