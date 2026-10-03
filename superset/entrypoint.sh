#!/bin/sh
# Container boot: create the metadata database if missing, migrate it,
# create the arp_designer account (Admin; the single account ARP's bootstrap
# and runtime log in as), then start the web server. Every step is
# idempotent, so a restart is safe.
set -e
: "${ARP_SUPERSET_PASSWORD:?ARP_SUPERSET_PASSWORD is not set -- add it to backend/.env}"

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
PY

superset db upgrade
# No-op (with a log line) if the user exists; does not change its password.
superset fab create-admin --username "${ARP_SUPERSET_USER:-arp_designer}" --password "$ARP_SUPERSET_PASSWORD" \
    --firstname ARP --lastname Designer --email "${ARP_SUPERSET_USER:-arp_designer}@localhost"
superset init
exec /usr/bin/run-server.sh
