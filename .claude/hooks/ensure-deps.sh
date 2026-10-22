#!/bin/bash
# Install what the checks need, only when it is missing (~1s when everything is there).
# Usage: bash .claude/hooks/ensure-deps.sh backend|frontend|postgres|neo4j|all
# Called by check.sh before running checks, by Claude before running tests by hand,
# and by the /install-deps skill to warm everything up in the background.
# A per-part lock makes concurrent calls wait for one install instead of racing.

cd "$(git rev-parse --show-toplevel)" || exit 1
# The backend venv when there is one (a local checkout, e.g. Windows), else python3 (cloud).
PY=python3
for v in "$PWD/backend/.venv/bin/python" "$PWD/backend/.venv/Scripts/python.exe"; do [ -x "$v" ] && { PY=$v; break; }; done

backend() {
  "$PY" -c 'import fastapi, pytest, ruff' 2>/dev/null && return 0
  echo "Installing backend dependencies (~3 min)..." >&2
  # Cloud sessions: the proxy CA bundle lacks download.pytorch.org's root, so add certifi's roots.
  # Runs in locked()'s subshell, so the exports reach only the pip commands below.
  if [ -f /root/.ccr/ca-bundle.crt ] && certifi=$(python3 -c 'import certifi; print(certifi.where())' 2>/dev/null); then
    ca=$(mktemp) && trap 'rm -f "$ca"' EXIT && cat /root/.ccr/ca-bundle.crt "$certifi" >"$ca" &&
      export REQUESTS_CA_BUNDLE=$ca SSL_CERT_FILE=$ca PIP_CERT=$ca
  fi
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
  # No pg_isready (Windows, Postgres in Docker): an open port counts.
  "$PY" -c "import socket; socket.create_connection(('127.0.0.1', 5432), 2)" 2>/dev/null && return 0
  if [ ! -f /usr/share/postgresql/16/extension/vector.control ]; then
    command -v apt-get >/dev/null || { echo "Postgres 16 with pgvector is not installed; install it or set ARP_TEST_POSTGRES_DSN." >&2; return 1; }
    echo "Installing Postgres + pgvector (~1 min)..." >&2
    apt-get update -q >/dev/null && apt-get install -y -q postgresql-16-pgvector >/dev/null || return 1
  fi
  service postgresql start >/dev/null 2>&1 9>&-  # 9>&-: the server must not inherit (and hold) the lock
  su postgres -c "psql -qc \"CREATE USER arp WITH PASSWORD 'arp' SUPERUSER;\"" >/dev/null 2>&1
  su postgres -c "createdb -O arp arp_test" >/dev/null 2>&1
  pg_isready -q -h localhost 2>/dev/null || { echo "Postgres is not running on localhost." >&2; return 1; }
}

neo4j() {  # test graph, same as CI: bolt://localhost:7688, user neo4j, password arp_neo4j_test
  # 7688, not 7687: tests wipe this graph, and the dev graph (docker-compose, .env.example) uses 7687.
  "$PY" -c "import socket; socket.create_connection(('127.0.0.1', 7688), 2)" 2>/dev/null && return 0
  local v=5.26.0 dir="${XDG_CACHE_HOME:-$HOME/.cache}/neo4j"
  command -v java >/dev/null || { echo "Neo4j needs Java 17+; install it, or run Neo4j in Docker and set ARP_TEST_NEO4J_URI." >&2; return 1; }
  if [ ! -x "$dir/neo4j-community-$v/bin/neo4j" ]; then
    echo "Installing Neo4j $v Community (~1 min)..." >&2
    mkdir -p "$dir" && curl -fsSL "https://dist.neo4j.org/neo4j-community-$v-unix.tar.gz" | tar -xz -C "$dir" || return 1
    "$dir/neo4j-community-$v/bin/neo4j-admin" dbms set-initial-password arp_neo4j_test >/dev/null || return 1
  fi
  local conf="$dir/neo4j-community-$v/conf/neo4j.conf"
  sed -i 's/^#\{0,1\}server\.bolt\.listen_address=.*/server.bolt.listen_address=:7688/; s/^server\.http\.enabled=true/server.http.enabled=false/' "$conf"
  "$dir/neo4j-community-$v/bin/neo4j" start >/dev/null 2>&1 9>&-
  for _ in $(seq 1 60); do
    "$PY" -c "import socket; socket.create_connection(('127.0.0.1', 7688), 2)" 2>/dev/null && return 0
    sleep 1
  done
  echo "Neo4j did not start on localhost:7688; see $dir/neo4j-community-$v/logs/neo4j.log" >&2; return 1
}

locked() {  # locked PART: run PART under its lock (unlocked without flock, e.g. Git Bash)
  command -v flock >/dev/null || { "$1"; return; }
  ( flock 9; "$1" ) 9>"${TMPDIR:-/tmp}/ensure-deps-$1.lock"
}

case "$1" in
  backend|frontend|postgres|neo4j) locked "$1" ;;
  all)
    locked postgres & p=$!
    locked neo4j & n=$!
    locked frontend & f=$!
    locked backend; b=$?
    wait $p; pc=$?; wait $n; nc=$?; wait $f; fc=$?
    exit $(( b || pc || nc || fc )) ;;
  *) echo "Usage: $0 backend|frontend|postgres|neo4j|all" >&2; exit 2 ;;
esac
