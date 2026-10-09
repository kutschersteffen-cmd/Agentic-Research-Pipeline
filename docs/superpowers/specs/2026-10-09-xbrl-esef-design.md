# XBRL pipeline, EU market (ESEF): design

Date: 2026-10-09. Status: implemented. Scope: sub-project 2 of the XBRL pipeline (see `2026-10-09-xbrl-pipeline-design.md`): an ESEF adapter, plus the ESRS tags in the tag dropdown.

## Purpose

Do for EU-listed companies what the SEC adapter does for US ones: download the tagged annual report, extract every tagged fact, resolve revenue and capex, and offer the tags for selection. Companies are keyed by LEI. The ESRS (CSRD sustainability) tags join the tag dropdown, so the user can select them once filers publish tagged sustainability statements.

## Decisions

| Topic | Decision |
|---|---|
| Source | filings.xbrl.org (`settings.esef_index_url`), the XBRL International index of ESEF filings. No other national register in this scope. |
| Facts | Taken from the filing's `json_url`: the filing already parsed to xBRL-JSON. This is the ESEF counterpart of SEC `companyfacts`; our iXBRL parser is not involved. |
| Store key | The company directory is named by the entity key: the 10-digit CIK for SEC, the 20-character LEI for ESEF. The field and API name `cik` stays. A `market` value (`sec` or `esef`) is added next to it. |
| Fetch | Same run type (`xbrl_fetch`), resume, retry and per-company statuses as SEC. One run covers one market. |
| Files the user sees | Two per company, as for SEC: the xBRL-JSON facts file and the filing's report package (`.zip`, containing the inline-XBRL report). |
| Facts kept | Numeric facts with no dimension beyond concept, entity, period and unit. Dimensional facts (segments, equity components) are counted but not stored; they need the per-filing work the first spec already defers. Text facts are not stored. |
| Required items | Revenue and capex, from IFRS concepts (below). |
| ESRS tags | New taxonomy snapshot `esrs`, from EFRAG's published taxonomy `2023-12-22`: the version filers use today. |

## What is reused

- `ingestion/esef.py`: the index lookup by LEI (`/api/entities/{lei}/filings`), the SSRF-guarded capped download, and the on-disk package cache. The XBRL function stays files-only: it does not use `EsefDocumentSource.fetch`, which registers documents in the shared stores. The lookup and download are moved into small public functions that both callers use. Behaviour of the existing class does not change.
- `xbrl_pipeline`: the store, the run model, flatten/catalogue output formats, the registry, selection, verify, views, the API router, the CLI group and the page.

## Fetch, per company

1. The company needs an `lei` (a `lei` column in the universe file). The value is normalised with `strip().upper()` and must be 20 letters or digits. Without a valid one the status is `no_lei` and nothing is written.
2. `GET {index}/api/entities/{lei}/filings`. A 404 gives `not_found`.
3. Pick the latest annual filing: the greatest `period_end` among filings that have a `package_url` and a `json_url`, ignoring implausible dates. The index contains bad values (for example `4172-12-31`); a year outside 2015 to the current year plus one is ignored.
4. Download `json_url` (the original, stored as served, with its sha256) and `package_url` (the report, stored as filed). Both are size-capped and SSRF-guarded as the existing download is.
5. Flatten the JSON to the common fact rows. Write the catalogue and required rows. `meta.json` records `market`, the original's file name, the tag selection, and the count of dimensional facts that were skipped.
6. A package problem never changes the company's status, as for SEC (`report`: stored, unchanged, none, error).

If the stored `meta.json` shows the same original hash and the same tag selection, the status is `unchanged`. `refresh` has no effect for ESEF: the index is always asked, and the hash decides. A package download failure gives report `error` while the company status stays ok (`package_error`); the report package is linked in the Files table only for http(s) URLs.

## Fact mapping

xBRL-JSON gives each fact `concept`, `entity`, `period`, optional `unit`, and `value`. Rows use the existing fields:

| Field | ESEF value |
|---|---|
| `taxonomy`, `concept` | Split of the concept QName (`ifrs-full`, `esrs`, or the company's extension prefix). |
| `unit` | The unit with its namespace removed (`iso4217:EUR` gives `EUR`). |
| `period_start`, `period_end` | From `period`. xBRL-JSON writes the end of a period as the start of the next day: one day is subtracted, so `2022-01-01T00:00:00/2023-01-01T00:00:00` gives 2022-01-01 to 2022-12-31 and an instant `2021-01-02T00:00:00` gives 2021-01-01. |
| `fiscal_year` | The year of `period_end` (as for SEC tables, never the filer's own label). |
| `fiscal_period` | `FY` for a duration of about a year and for an instant (a year-end position in an annual report, as SEC marks its annual rows); else empty. |
| `form` | `ESEF`. |
| `filed` | The date part of the index's `date_added`. |
| `accession` | The index's `fxo_id`. |
| `market` | `esef` (new field on fact, required and company rows; the default `sec` keeps existing files readable). |

Not stored: facts with a `language` or other extra dimension keys, non-numeric values, and facts whose `nil`/missing value cannot be read as a number.

## Revenue and capex (IFRS)

Candidate lists, tried in order, from the `ifrs-full` taxonomy:

- Revenue: `Revenue`, `RevenueFromContractsWithCustomers`.
- Capex: `PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities`.

The names were confirmed against the IFRS 2025 snapshot; `PurchaseOfPropertyPlantAndEquipment` is not in the schema and was dropped rather than guessed. For each period-end year, the first candidate that has a full-year, non-dimensional fact wins. If none has, the row is `not_found`, as for SEC. Values keep their reported currency; verify already normalises units with `arp.normalise.units.convert`.

## Tags and the dropdown

- `TAXONOMY_SOURCES["esrs"]`: schema `https://xbrl.efrag.org/taxonomy/esrs/2023-12-22/common/esrs_cor.xsd`; labels `.../common/labels/lab_esrs-en.xml` and `.../common/labels/doc_esrs-en.xml`. Reachable on 2026-10-09. `arp xbrl taxonomy update` fetches it like the others, and `esrs` becomes a standard prefix, so its concepts are not flagged as extensions.
- Filings made with another taxonomy version use concepts that are not in the snapshot (for example IFRS renames). Those concepts still appear in the dropdown through the "seen in fetched reports" rows already built from the catalogues.
- EFRAG also publishes a `2026-08-30` set with a different file layout (`esrs.xsd`, `label-en.xml`). Not adopted: no filing uses it yet. Adding it later is one new source entry.
- The ESRS schema is large (1.5 MB). Parsing it must pass the existing size cap and entity guard. The plan checks that `parse_taxonomy` handles it, and fixes the parser only if it does not.

## Surfaces

- CLI: `arp xbrl fetch --market sec|esef` (default `sec`). `--universe` needs an `lei` column for `esef`.
- API: the fetch request takes `market`. Files, facts, required and verify endpoints take the entity key as before and read `market` from the stored `meta.json`. The company list returns `market`.
- Page: the Fetch area gets a market switch (SEC or EU/ESEF). The Files and Facts tables show a Market column and label the key CIK or LEI by market. The tag combobox gets `esrs` in its taxonomy filter.
- Verify: unchanged. The same guard applies: the `xbrl_facts_enabled` flag also gates ESEF values in the extraction pipeline.

## Errors and limits

- Network and HTTP failures use the existing retry rule (429, 5xx, transport errors).
- Per-company pacing: one company at a time, with a short delay between requests.
- Files over the size cap, a non-JSON body, or a package that is not a zip give an error row for that company; the run continues.
- A company key that fails `safe_id` is refused, as for SEC.
- Latest filing only. It still contains the prior year as comparatives, so the tables normally show two years.

## Out of scope

- Dimensional facts, text blocks, and per-filing iXBRL parsing.
- Older filings (history) per company.
- Other registers (national OAMs, ESAP, UK, Japan).
- Sustainability-specific views. ESRS facts appear in the common tables like any other tag.
- Any change to the extraction pipeline.

## Testing

- Unit tests with a small recorded xBRL-JSON fixture (instant, duration, a dimensional fact, a text fact, an extension concept) for the period mapping and the fact filter.
- Fetch tests with `httpx.MockTransport`: a normal filing, a 404, a bogus `period_end` that must lose to a valid one, a filing without `json_url`, an oversized body, and an unchanged re-run.
- Required-row tests for IFRS revenue and capex, including `not_found`.
- Registry test: the `esrs` source is parsed into entries, using a small excerpt; a test that the real URLs are what the spec says.
- API and CLI tests for `market`; one frontend type check and lint.
- No test calls the network. The first live fetch is run by the user and reported, as for SEC.
