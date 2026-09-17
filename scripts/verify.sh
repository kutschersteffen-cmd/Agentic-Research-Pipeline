#!/usr/bin/env bash
# ARP deterministic verification -- the single command that answers
# "would CI accept this?".
#
#   bash scripts/verify.sh              # backend + frontend
#   bash scripts/verify.sh --backend    # backend only
#   bash scripts/verify.sh --frontend   # frontend only
#
# .github/workflows/ci.yml invokes this same script, so a green run here
# and a green `backend`/`frontend` CI job are the same claim. Steps run in
# a fixed order and the first failure stops the run, cheapest check first,
# so a formatting-level mistake fails in seconds instead of after the full
# suite.
#
# What this does NOT cover, by design:
#   * The Postgres/OpenSearch integration suites. They are gated on
#     ARP_TEST_POSTGRES_DSN / ARP_TEST_OPENSEARCH_URL and skip when unset
#     (63 skips locally). CI sets both against service containers. To run
#     them here: `docker compose up -d postgres opensearch`, export the
#     two variables, then re-run -- the gating is per-test, so nothing
#     about this script changes.
#   * gitleaks secret scanning. That is a pre-commit hook plus its own CI
#     job; run `pre-commit install` once and it fires on every commit.
#   * pip-audit / npm audit / Trivy. Non-blocking CI jobs (see
#     docs/CORPORATE_READINESS_PLAN.md Phase 0).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$REPO_ROOT/backend"
FRONTEND="$REPO_ROOT/frontend"

run_backend=true
run_frontend=true

while [ $# -gt 0 ]; do
    case "$1" in
        --backend) run_frontend=false ;;
        --frontend) run_backend=false ;;
        -h|--help) sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "verify.sh: unknown argument '$1' (try --help)" >&2; exit 2 ;;
    esac
    shift
done

# Prefer the project venv over whatever is on PATH, so pre-commit/pre-push
# hooks and fresh shells -- which never activate it -- run the same ruff and
# pytest a developer runs interactively. CI provisions its own environment
# and simply has these on PATH already.
if [ -d "$BACKEND/.venv/bin" ]; then
    PATH="$BACKEND/.venv/bin:$PATH"
    export PATH
fi

step=0
total=0
$run_backend && total=$((total + 2))
$run_frontend && total=$((total + 2))

announce() {
    step=$((step + 1))
    echo
    echo "==> [$step/$total] $1"
}

require() {
    command -v "$1" >/dev/null 2>&1 && return 0
    echo "verify.sh: '$1' not found. $2" >&2
    exit 1
}

if $run_backend; then
    require ruff 'Install the backend dev extras: cd backend && pip install -e ".[dev]"'
    require pytest 'Install the backend dev extras: cd backend && pip install -e ".[dev]"'

    announce "ruff check (backend)"
    (cd "$BACKEND" && ruff check .)

    announce "pytest (backend)"
    (cd "$BACKEND" && pytest -q)
fi

if $run_frontend; then
    require npm 'Install Node 22+ -- see docs/INSTALLATION.md'
    if [ ! -d "$FRONTEND/node_modules" ]; then
        echo "verify.sh: frontend/node_modules is missing. Run: cd frontend && npm install" >&2
        exit 1
    fi

    announce "oxlint (frontend)"
    (cd "$FRONTEND" && npm run --silent lint)

    announce "tsc + vite build (frontend)"
    (cd "$FRONTEND" && npm run --silent build)
fi

echo
echo "[OK] verify passed"
