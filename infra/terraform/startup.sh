#!/bin/bash
# Runs on every boot (GCE metadata startup-script). Idempotent.
set -euo pipefail

# Persistent data disk -> /var/lib/docker, so named volumes survive VM rebuilds.
DEV=/dev/disk/by-id/google-arp-data
if ! blkid "$DEV" >/dev/null 2>&1; then
  mkfs.ext4 -m 0 -F "$DEV"
fi
mkdir -p /var/lib/docker
grep -q "$DEV" /etc/fstab || echo "$DEV /var/lib/docker ext4 defaults,nofail 0 2" >> /etc/fstab
mountpoint -q /var/lib/docker || mount /var/lib/docker

if ! command -v docker >/dev/null; then
  apt-get update
  apt-get install -y docker.io docker-compose
  systemctl enable --now docker
fi

# Ops Agent: container stdout + host metrics into Cloud Logging / Monitoring.
if ! systemctl is-active --quiet google-cloud-ops-agent; then
  curl -sSO https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh
  bash add-google-cloud-ops-agent-repo.sh --also-install
fi
