#!/usr/bin/env bash
# Smoke checks for one published image on one platform (.github/workflows/images.yml).
#   image_smoke.sh <name> <platform> <image-ref> [<backend-image-ref>]
# <name>: arp-backend | arp-frontend | arp-compute | arp-compute-cuda. arp-frontend also needs the
# arp-backend image of the same tag. Prints one line per check, exactly
#   smoke <name> <platform>: <check> ok
#   smoke <name> <platform>: <check> FAILED <detail>
# and exits non-zero if any check failed. Runs on the platform's native runner, so images run unemulated.
set -uo pipefail

name=$1 platform=$2 image=$3 backend_image=${4:-}
failed=0
net=arp-smoke

ok() { echo "smoke $name $platform: $1 ok"; }
fail() { echo "smoke $name $platform: $1 FAILED ${2:-}"; failed=1; }
# check <name> <command...>: ok when the command exits 0, else FAILED with its output (one line).
check() {
  local c=$1 out
  shift
  if out=$("$@" 2>&1); then ok "$c"; else fail "$c" "$(echo "$out" | tr '\n' ' ' | cut -c1-300)"; fi
}
# status <url> [curl args...]: the HTTP status code only.
status() { local url=$1; shift; curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$@" "$url"; }
expect_status() {
  local want=$1 got
  shift
  got=$(status "$@")
  [ "$got" = "$want" ] || { echo "HTTP $got, want $want"; return 1; }
}
# wait_for <url> <seconds>: until the URL answers at all (any status).
wait_for() {
  local url=$1 tries=$2
  for _ in $(seq "$tries"); do
    [ "$(status "$url")" != "000" ] && return 0
    sleep 1
  done
  return 1
}
dump_logs() { for c in "$@"; do echo "--- docker logs $c"; docker logs --tail 40 "$c" 2>&1; done; }

start_backend() {
  # As compose runs it: dev sign-in, the smoke network trusted, Postgres initialised first
  # (the backend refuses to start on an uninitialised database).
  docker network create "$net" >/dev/null
  local subnet dsn=postgresql+psycopg://arp:arp@postgres:5432/arp
  subnet=$(docker network inspect "$net" -f '{{(index .IPAM.Config 0).Subnet}}')
  docker run -d --name postgres --network "$net" -e POSTGRES_USER=arp -e POSTGRES_PASSWORD=arp \
    -e POSTGRES_DB=arp pgvector/pgvector:pg16 >/dev/null
  for _ in $(seq 60); do docker exec postgres pg_isready -U arp -h 127.0.0.1 >/dev/null 2>&1 && break; sleep 1; done
  docker run --rm --network "$net" -e ARP_POSTGRES_DSN="$dsn" "$1" arp db init-postgres >/dev/null \
    || { dump_logs postgres; fail db-init "arp db init-postgres failed"; return 1; }
  docker run -d --name backend --network "$net" -p 127.0.0.1:8000:8000 \
    -e ARP_POSTGRES_DSN="$dsn" -e ARP_AUTH_MODE=dev -e ARP_DEV_TRUSTED_NETWORKS="[\"$subnet\"]" "$1" >/dev/null
  wait_for http://127.0.0.1:8000/api/health 180 || { dump_logs backend; return 1; }
}

# start_frontend <container> <host port> [docker run args...]: on the smoke network, no ARP_BACKEND_URL.
start_frontend() {
  local c=$1 port=$2
  shift 2
  docker run -d --name "$c" --network "$net" -p "127.0.0.1:$port:80" "$@" "$image" >/dev/null
  wait_for "http://127.0.0.1:$port/" 60 || { dump_logs "$c"; return 1; }
}

api_health_ok() {
  local body
  body=$(curl -s --max-time 20 -w '\n%{http_code}' "$1") || { echo "no answer"; return 1; }
  [ "$(echo "$body" | tail -n1)" = 200 ] || { echo "HTTP $(echo "$body" | tail -n1)"; return 1; }
  echo "$body" | sed '$d' | python3 -c 'import json,sys; s=json.load(sys.stdin).get("status"); sys.exit(0 if s=="ok" else f"status={s!r}")'
}

coop_headers() {
  local h
  h=$(curl -s -D - -o /dev/null --max-time 20 "$1" | tr -d '\r')
  echo "$h" | grep -qi '^cross-origin-opener-policy: same-origin$' || { echo "no COOP same-origin"; return 1; }
  echo "$h" | grep -qi '^cross-origin-embedder-policy: require-corp$' || { echo "no COEP require-corp"; return 1; }
}

start_compute() {
  docker run -d --name compute -p 127.0.0.1:8080:8080 "$image" >/dev/null
  wait_for http://127.0.0.1:8080/healthz 300 || { dump_logs compute; return 1; }
}

healthz_device_cpu() {
  local body
  body=$(curl -s --max-time 20 -w '\n%{http_code}' http://127.0.0.1:8080/healthz) || { echo "no answer"; return 1; }
  [ "$(echo "$body" | tail -n1)" = 200 ] || { echo "HTTP $(echo "$body" | tail -n1)"; return 1; }
  echo "$body" | sed '$d' | python3 -c 'import json,sys; d=json.load(sys.stdin).get("device"); sys.exit(0 if d=="cpu" else f"device={d!r}")'
}

embed_one() {
  local model body
  model=$(docker exec compute python -c 'from arp.retrieval.embeddings import EMBED_MODEL_NAME; print(EMBED_MODEL_NAME)') \
    || { echo "cannot read EMBED_MODEL_NAME"; return 1; }
  body=$(curl -s --max-time 120 -w '\n%{http_code}' -X POST http://127.0.0.1:8080/embed \
    -H 'Content-Type: application/json' -H "X-ARP-Model: $model" -d '{"texts": ["hello"]}') || { echo "no answer"; return 1; }
  [ "$(echo "$body" | tail -n1)" = 200 ] || { echo "HTTP $(echo "$body" | tail -n1): $(echo "$body" | sed '$d' | cut -c1-200)"; return 1; }
  echo "$body" | sed '$d' | python3 -c 'import json,sys; v=json.load(sys.stdin).get("vectors"); sys.exit(0 if isinstance(v, list) and len(v)==1 else f"vectors has {len(v) if isinstance(v, list) else v!r} items")'
}

no_onnxruntime_gpu() {
  if docker exec compute pip show onnxruntime-gpu >/dev/null 2>&1; then echo "onnxruntime-gpu is installed"; return 1; fi
}

torch_cpu() {
  local v
  v=$(docker exec compute python -c 'import torch; print(torch.__version__)') || { echo "cannot import torch"; return 1; }
  case $v in *+cpu) ;; *) echo "torch $v"; return 1 ;; esac
}

case $name in
  arp-backend)
    if start_backend "$image"; then
      check api-health expect_status 200 http://127.0.0.1:8000/api/health
    else
      fail api-health "backend did not start"
    fi
    ;;
  arp-frontend)
    [ -n "$backend_image" ] || { echo "arp-frontend needs the backend image" >&2; exit 2; }
    if start_backend "$backend_image" && start_frontend frontend 5173 \
      && start_frontend frontend-hosts 5174 -e ARP_PUBLIC_HOSTS="localhost 127.0.0.1 arp.example.test"; then
      check root expect_status 200 http://127.0.0.1:5173/
      check coop coop_headers http://127.0.0.1:5173/
      check api-proxy api_health_ok http://127.0.0.1:5173/api/health
      check api-proxy-other-host expect_status 200 http://127.0.0.1:5174/api/me \
        -H 'Host: arp.example.test' -H 'Origin: http://arp.example.test'
      check rebind-host expect_status 421 http://127.0.0.1:5173/api/me \
        -H 'Host: rebind.example.test' -H 'Origin: http://rebind.example.test'
      check foreign-origin expect_status 401 http://127.0.0.1:5173/api/me -H 'Origin: http://evil.example.test'
    else
      for c in root coop api-proxy api-proxy-other-host rebind-host foreign-origin; do fail "$c" "stack did not start"; done
    fi
    ;;
  arp-compute)
    if start_compute; then
      check healthz-device-cpu healthz_device_cpu
      check embed embed_one
      check no-onnxruntime-gpu no_onnxruntime_gpu
      [ "$platform" = linux/amd64 ] && check torch-cpu torch_cpu
    else
      for c in healthz-device-cpu embed no-onnxruntime-gpu; do fail "$c" "compute did not start"; done
      [ "$platform" = linux/amd64 ] && fail torch-cpu "compute did not start"
    fi
    ;;
  arp-compute-cuda)
    if start_compute; then
      check healthz-device-cpu healthz_device_cpu
    else
      fail healthz-device-cpu "compute did not start"
    fi
    ;;
  *)
    echo "unknown image name: $name" >&2
    exit 2
    ;;
esac

if [ "$failed" != 0 ]; then
  mapfile -t containers < <(docker ps -a --format '{{.Names}}')
  dump_logs "${containers[@]}"
  exit 1
fi
