#!/usr/bin/env sh
set -eu
repo="$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)"
cd "$repo/backend"
exec python -m arp.prototypes.openshell_code_mode.verify_host "$@"
