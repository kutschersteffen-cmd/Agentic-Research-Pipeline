#!/bin/sh
# Container boot: create the metadata database if missing, migrate it,
# create the arp_designer account (Admin; the single account ARP's bootstrap
# and runtime log in as) and set its password from backend/.env, then start
# the web server. Every step is idempotent, so a restart is safe.
set -e
# Imports superset_config, which also rejects unset/placeholder/short secrets.
python -c 'import superset_config as c; c.required("ARP_SUPERSET_PASSWORD")'

python - <<'PY'
import os

import psycopg2
from sqlalchemy.engine.url import make_url

url = make_url(os.environ["SUPERSET_DATABASE_URI"])
conn = psycopg2.connect(host=url.host, port=url.port or 5432, user=url.username, password=url.password, dbname="postgres")
conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (url.database,))
if cur.fetchone() is None:
    cur.execute(f'CREATE DATABASE "{url.database}"')
# Only the owner (and superusers) may connect to Superset's metadata.
cur.execute(f'REVOKE CONNECT ON DATABASE "{url.database}" FROM PUBLIC')
PY

superset db upgrade
superset fab create-admin --username "${ARP_SUPERSET_USER:-arp_designer}" --password "$ARP_SUPERSET_PASSWORD" \
    --firstname ARP --lastname Designer --email "${ARP_SUPERSET_USER:-arp_designer}@localhost"
# create-admin skips an existing user, so apply the password on every boot:
# backend/.env stays the single source of truth.
superset fab reset-password --username "${ARP_SUPERSET_USER:-arp_designer}" --password "$ARP_SUPERSET_PASSWORD"
superset init
exec /usr/bin/run-server.sh
