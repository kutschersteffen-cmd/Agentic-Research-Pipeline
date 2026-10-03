# Phase 1b spike: Superset dashboard export/import

Run on 2026-10-03 against live Superset 5.0.0 (local image `arp-superset:dev`, host network),
dashboard `arp-risk-exposure` (8 charts, 2 datasets, unpublished).
Test: `backend/tests/test_bi_live_export.py` (`ARP_TEST_SUPERSET_URL`, plus `ARP_TEST_SUPERSET_URL2` for scenario b).

## Decision for Task 8: **auto-import**

Both scenarios pass, so hand-built dashboards are exported, stored, and re-imported when a project is opened.

## Results

| Scenario | Result |
|---|---|
| (a) Export, delete only the dashboard (charts and datasets stay), import with `overwrite=true` | PASS. Dashboard back under the same slug (new numeric id), 8 charts attached, `published=false`. A second import of the same bundle also succeeds (overwrite, no duplicates). |
| (b) Import onto a fresh metadata DB (`superset_live2`, second Superset container) after `arp bi bootstrap` there | PASS. Dashboard restored with 8 charts, `published=false`. No duplicate database or datasets: the bundle's `arp_bi` database and its two datasets (`holdings`, `holdings_history`) were matched to the bootstrapped ones (same ids), and adopted the source UUIDs. A bootstrap run afterwards reports the template `unchanged`. |

## What worked

- Export: `GET /api/v1/dashboard/export/?q=!(<dashboard id>)`, same auth headers as every other call (bearer token, `X-CSRFToken`, `Referer`). Returns `application/zip` (about 30 KB here) with `dashboard_export_<ts>/{metadata.yaml, dashboards/, charts/, datasets/arp_bi/, databases/arp_bi.yaml}`.
- The exported database file masks the password: `sqlalchemy_uri: postgresql://bi_reader:XXXXXXXXXX@host:port/db`.
- Import: `POST /api/v1/dashboard/import/`, multipart: file field `formData` (the zip, `application/zip`), form fields `overwrite=true` and `passwords={"databases/arp_bi.yaml": "<bi_reader password>"}` (JSON string, key is the path inside the bundle without the root folder). Same auth headers; httpx sets the multipart content type itself. Response 200 `{"message": "OK"}`.
- The bundle can be imported without the password map only if the target already has the database (not tested; always send the map).

## Caveats for Task 8

- Import creates a new dashboard id; look it up by slug (`find_dashboard`) afterwards.
- Import overwrites the dashboard's layout and `json_metadata`, so manual edits made in Superset since the export are lost (expected for `overwrite=true`).
- Fresh-DB order matters: bootstrap first (creates the database, datasets, metrics, and the standard template), then import. Importing before bootstrap was not tested.
- The password map must name the bundle's database file; if a stored bundle uses another database name the key differs. Task 8 should take the key from the bundle's `databases/*.yaml` entries.
- Superset response bodies stay out of exception messages (`SupersetError` already omits the body from `str`).

## Second Superset recipe (scenario b)

Same image, env and entrypoint as the main container, only the port and metadata DB change:

```
createdb -p 5433 -O arp superset_live2
sed 's#superset_live$#superset_live2#; s#SUPERSET_PORT=8090#SUPERSET_PORT=8091#' <env of arp-superset-live> > live.envfile
docker run -d --name arp-superset-live2 --network host --env-file live.envfile \
  -v <repo>/superset:/app/pythonpath:ro arp-superset:dev /app/pythonpath/entrypoint.sh
```

The container command must be `/app/pythonpath/entrypoint.sh` (it migrates the new DB and creates the
`arp_designer` user); without it Superset starts on an empty DB and every login returns 401. Both
instances share the same credentials (`ARP_SUPERSET_USER` / `ARP_SUPERSET_PASSWORD`, `ARP_BI_READER_PASSWORD`)
and the same ARP database, so one env file serves both. Run the tests with
`ARP_TEST_SUPERSET_DESTRUCTIVE=1 ARP_TEST_SUPERSET_URL=http://127.0.0.1:8090 ARP_TEST_SUPERSET_URL2=http://127.0.0.1:8091 pytest -m live_superset tests/test_bi_live_export.py`.
The tests delete `arp-risk-exposure` on both instances afterwards.

## Client

`SupersetClient.export_dashboard(dashboard_id: int) -> bytes` and
`SupersetClient.import_dashboard(bundle: bytes, db_passwords: dict[str, str]) -> None`, with unit tests
against a fake httpx transport in `backend/tests/test_bi_superset_client.py`.
