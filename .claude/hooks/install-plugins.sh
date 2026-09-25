#!/usr/bin/env bash
# Installs the plugins that .claude/settings.json enables.
#
# extraKnownMarketplaces only *declares* a marketplace and enabledPlugins only
# flips a plugin on once it is installed -- neither fetches anything. Cloud
# sessions (claude.ai/code, the mobile Code tab) get a fresh container each time
# and cannot run /plugin, so without this hook those plugins are never present.
#
# Never fails the session: every path exits 0.

set -u

# Turn on i-have-adhd's always-on mode. The flag lives outside the repo, so a
# fresh cloud container loses it; recreate it every session. Delete this line to opt out.
mkdir -p "${CLAUDE_CONFIG_DIR:-$HOME/.claude}" && touch "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/.i-have-adhd-always"

command -v claude >/dev/null 2>&1 || exit 0

add_marketplace() {
  claude plugin marketplace add "$1" >/dev/null 2>&1 \
    || claude plugin marketplace update "${1##*/}" >/dev/null 2>&1 \
    || true
}

install_plugin() {
  local spec=$1 name=${1%%@*}
  if claude plugin list 2>/dev/null | grep -q "$name"; then
    return 0
  fi
  if claude plugin install "$spec" >/dev/null 2>&1; then
    echo "$name"
  fi
}

add_marketplace DietrichGebert/ponytail
add_marketplace nextlevelbuilder/ui-ux-pro-max-skill
add_marketplace pbakaus/impeccable
add_marketplace ayghri/i-have-adhd
add_marketplace forrestchang/andrej-karpathy-skills
add_marketplace blader/humanizer

installed=()
for spec in ponytail@ponytail ui-ux-pro-max@ui-ux-pro-max-skill impeccable@impeccable \
            i-have-adhd@i-have-adhd andrej-karpathy-skills@karpathy-skills humanizer@humanizer; do
  name=$(install_plugin "$spec") && [ -n "$name" ] && installed+=("$name")
done

if [ ${#installed[@]} -gt 0 ]; then
  echo "Installed plugins: ${installed[*]}. Plugin skills load at session start, so they are namespaced as /<plugin>:<skill> from the next session onward."
fi

exit 0
