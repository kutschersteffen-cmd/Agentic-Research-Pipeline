# Superset 5.x images ship without database drivers. psycopg2 serves both
# the metadata DB and the ARP `bi` data source.
FROM apache/superset:5.0.0
USER root
RUN uv pip install --python /app/.venv/bin/python --no-cache psycopg2-binary==2.9.10
USER superset
