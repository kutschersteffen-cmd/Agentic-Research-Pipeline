#!/bin/bash
# Self-check for context-stack.sh: runs each scenario in a throwaway clone whose origin is a local bare repo.
# Usage: bash .claude/hooks/context_stack_selftest.sh
repo=$(git rev-parse --show-toplevel)
hook="$repo/.claude/hooks/context-stack.sh"
tmp=$(mktemp -d)
work="$tmp/work"
trap 'stop_job; rm -rf "$tmp"' EXIT
git clone -q --bare "$repo" "$tmp/origin.git"
git -C "$tmp/origin.git" update-ref -d refs/heads/context-data 2>/dev/null  # a local one would be copied
git clone -q "$tmp/origin.git" "$work"
log="$tmp/home/.cache/arp-context/session.log"
# "Tools absent": graphify and openwiki off PATH, pip and npm install into empty temp prefixes.
mkdir -p "$tmp/bin" && ln -s "$(command -v node)" "$(command -v npm)" "$(command -v pip)" "$tmp/bin/" 2>/dev/null
absent=(PATH="$tmp/bin:/usr/bin:/bin" PIP_TARGET="$tmp/pip" npm_config_prefix="$tmp/npm")
p=http://127.0.0.1:9
blocked=(-u NO_PROXY -u no_proxy -u npm_config_noproxy HTTPS_PROXY=$p HTTP_PROXY=$p https_proxy=$p http_proxy=$p
         npm_config_https_proxy=$p npm_config_proxy=$p PIP_RETRIES=0 npm_config_fetch_retries=0)  # no retries: fail in seconds
# Every --foreground run below also uses blocked and absent, so no scenario installs anything for real.
quiet=("${blocked[@]}" "${absent[@]}")
failed=0

# Every process the job starts runs in the clone, so its cwd finds them.
job_pids() {
  local d
  for d in /proc/[0-9]*; do [ "$(readlink "$d/cwd" 2>/dev/null)" = "$work" ] && echo "${d#/proc/}"; done
}
stop_job() { job_pids | xargs -r kill 2>/dev/null; sleep 0.2; job_pids | xargs -r kill -9 2>/dev/null; }

# run [--foreground] [env args...] (env -u options before assignments): runs the hook in the clone with a fresh HOME; sets $out, $rc, $ms
run() {
  local flag=()
  [ "${1:-}" = --foreground ] && { flag=(--foreground); shift; }
  rm -rf "$tmp/home" && mkdir -p "$tmp/home"
  local t0=$(date +%s%N)
  out=$(cd "$work" && env -u ARP_CONTEXT_FAIL -u CLAUDE_PROJECT_DIR "$@" HOME="$tmp/home" bash "$hook" "${flag[@]}")
  rc=$?
  ms=$(( ($(date +%s%N) - t0) / 1000000 ))
}

# check NAME CONDITION...: PASS when the condition (a shell expression) holds
check() {
  local name=$1; shift
  if eval "$*"; then echo "PASS $name"; else echo "FAIL $name ($*; exit $rc, ${ms}ms, stdout '${out}')"; failed=1; fi
}
quick='[ "$rc" = 0 ] && [ "$ms" -le 5000 ] && [ -z "$out" ]'

run "${absent[@]}"
check returns_fast "$quick"
stop_job

run "${blocked[@]}" "${absent[@]}"
check proxy_blocked_returns_fast "$quick"
stop_job
run --foreground "${quiet[@]}"
check proxy_blocked_log '[ "$rc" = 0 ] && [ -z "$out" ] && grep -Eq "^arp-context: install-graphify failed \(.+\)$" "$log" &&
  ! grep -q "command not found" "$log" && grep -qx "arp-context: register-openwiki failed (openwiki not on PATH)" "$log"'
check proxy_blocked_no_children '[ -z "$(job_pids)" ] && [ -z "$out" ]'

run --foreground "${quiet[@]}"
check fetch_missing '[ "$rc" = 0 ] && grep -Eq "^arp-context: fetch-graph failed \(.+\)$" "$log"'

d="$tmp/data"
git init -q "$d"
echo '{"nodes":[{"id":"ctx_probe_node"}],"links":[]}' > "$d/graph.json"
echo '# report' > "$d/GRAPH_REPORT.md"
echo '{"commit":"x","built_at":"2026-10-18T02:17Z","docs_built_at":null}' > "$d/meta.json"
git -C "$d" add -A && git -C "$d" -c user.name=t -c user.email=t@t -c commit.gpgsign=false commit -qm data
git -C "$d" -c push.negotiate=false push -q "$tmp/origin.git" HEAD:refs/heads/context-data

run --foreground "${quiet[@]}"
check fetch_ok '[ "$rc" = 0 ] && [ -z "$out" ] && grep -q ctx_probe_node "$work/graphify-out/graph.json" &&
  [ -f "$work/graphify-out/GRAPH_REPORT.md" ] && [ -f "$work/graphify-out/meta.json" ] &&
  grep -qx "arp-context: fetch-graph ok" "$log"'
check clean_tree '[ -z "$(git -C "$work" status --porcelain)" ]'

run --foreground "${quiet[@]}" ARP_CONTEXT_FAIL=register-openwiki
check forced 'grep -qx "arp-context: register-openwiki failed (forced)" "$log" && grep -qx "arp-context: fetch-graph ok" "$log"'

# A stub openwiki that reports a modified integration: the reason carries its status line.
mkdir -p "$tmp/stub" && printf '#!/bin/sh\nprintf "claude\\tmodified\\tClaude Code\\n"\n' > "$tmp/stub/openwiki" && chmod +x "$tmp/stub/openwiki"
run --foreground "${quiet[@]}" PATH="$tmp/stub:$tmp/bin:/usr/bin:/bin"
check register_status 'grep -qx "arp-context: register-openwiki failed (openwiki reports: claude modified Claude Code)" "$log"'

# Two jobs at once (startup then resume): the second sees the lock and leaves, so the graph is fetched once.
rm -rf "$tmp/home" "$work/graphify-out" && mkdir -p "$tmp/home"
both() { (cd "$work" && env -u ARP_CONTEXT_FAIL -u CLAUDE_PROJECT_DIR "${quiet[@]}" HOME="$tmp/home" bash "$hook" --foreground); }
both & a=$!; both & b=$!
wait $a; ra=$?; wait $b; rb=$?
check concurrent '[ "$ra$rb" = 00 ] && [ "$(grep -c "^arp-context: fetch-graph" "$log")" = 1 ] &&
  grep -qx "arp-context: fetch-graph ok" "$log" &&
  python3 -c "import json, sys; json.load(open(sys.argv[1]))" "$work/graphify-out/graph.json" &&
  grep -q ctx_probe_node "$work/graphify-out/graph.json"'

# fetch-graph.sh runs without the hook's lock (vault.sh, the skill): four at once must all succeed.
fetch1() { (cd "$work" && env "${quiet[@]}" HOME="$tmp/home" bash "$repo/.claude/hooks/fetch-graph.sh"); }
rm -rf "$work/graphify-out"
pids=() rcs=
for i in 1 2 3 4; do fetch1 & pids+=($!); done
for p in "${pids[@]}"; do wait "$p"; rcs+=$?; done
check fetch_parallel '[ "$rcs" = 0000 ] && grep -q ctx_probe_node "$work/graphify-out/graph.json" &&
  python3 -c "import json, sys; json.load(open(sys.argv[1]))" "$work/graphify-out/graph.json" &&
  [ -z "$(ls -A "$work/graphify-out" | grep tmp)" ]'

# vault.sh in the clone: writes only under graphify-out/, so the tree stays clean and notes/ and .obsidian/
# keep their exact contents. Without graphify it must say so and still change nothing.
vault="$repo/scripts/vault.sh"
mkdir -p "$work/.obsidian" && echo '{"probe":1}' > "$work/.obsidian/app.json"
snap() { (cd "$work" && find notes .obsidian -type f -print0 2>/dev/null | sort -z | xargs -0 -r sha256sum); }
before=$(snap)
rm -rf "$work/graphify-out"
out=$(cd "$work" && env "${quiet[@]}" HOME="$tmp/home" bash "$vault" 2>&1); rc=$?
check vault_no_graphify '[ "$rc" != 0 ] && grep -q "graphify not found" <<<"$out" && [ ! -e "$work/graphify-out" ] &&
  [ -z "$(git -C "$work" status --porcelain)" ] && [ "$(snap)" = "$before" ]'
if g=$(command -v graphify); then
  out=$(cd "$work" && env "${blocked[@]}" PATH="${g%/*}:/usr/bin:/bin" HOME="$tmp/home" bash "$vault" 2>&1); rc=$?
  check vault_clean '[ "$rc" = 0 ] && [ -f "$work/graphify-out/obsidian/ctx_probe_node.md" ] &&
    [ -z "$(git -C "$work" status --porcelain)" ] && [ "$(snap)" = "$before" ] && [ -n "$before" ]'
else
  echo "SKIP vault_clean (graphify not installed)"
fi

exit $failed
