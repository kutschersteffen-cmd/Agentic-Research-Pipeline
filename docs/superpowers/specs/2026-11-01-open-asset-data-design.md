# Open asset data in the company graph (action plan A5)

Spec slug: `open-asset-data`. Parent: `2026-11-01-model-stack-design.md` (approved).

## Why

Market-leading risk products work on assets (plants, mines, power stations) linked to owners
(`docs/MARKET_EXPOSURE_APPROACHES_RESEARCH.md`, section 3). ARP has no asset data. Two open sources cover the
heavy-emitting sectors that matter most for engagement: Global Energy Monitor trackers (researcher-built, every
fact cited, ownership chains, mostly CC BY 4.0) and Climate TRACE (ML-estimated emissions per source, linked to
owners). Loading them into the existing company graph is the base for "say vs do" (B4) and physical risk (C1).

## Goals

1. Import GEM trackers (steel, cement, coal power, gas power) and Climate TRACE emission sources into the company
   graph as `Asset` nodes with `OWNS` relationships to owner companies.
2. Link owners to ARP companies: by LEI first, then propose name matches for review.
3. Answer, per ARP company: its assets, capacity and estimated emissions by sector, with sources.

## Non-goals

- Hazard data or physical-risk scores (C1).
- Comparing assets with reported emissions (B4).
- Licensed asset data (Asset Impact, vendor feeds), which belongs to the buy-vs-build review (C2).
- Any UI. CLI and graph queries only.

## Anti-goals

- An automatic owner match without either an LEI match or a person's approval.
- Overwriting an imported version: a new release is a new version, as for supply edges.

## Design

### Graph model (Neo4j, `arp/company_graph.py` conventions)

- `(:Asset {asset_id, source, source_id, name, sector, country, lat, lon, capacity, capacity_unit, status,
  emissions_t_co2e, emissions_year, release, published_at, source_url})`
- `(:Owner {owner_key, name, lei})` for each owner entity in the source.
- `(:Owner)-[:OWNS {share, release, published_at}]->(:Asset)`
- `(:Owner)-[:SAME_AS {method: "lei"|"approved", approved_by, approved_at}]->(:Company)`
- `asset_id` = `<source>:<source_id>`. A re-import with the same `release` is a no-op; a new `release` adds new
  versions and leaves old ones readable (queries take `as_of`, as `edges_at` does).

### Import

- `arp assets import-gem --tracker steel|cement|coal|gas --file <xlsx|csv> --release <yyyy-mm>`
  (the GEM download files; column mapping in `arp/assets/data/gem_columns.json`).
- `arp assets import-climate-trace --file <csv> --release <yyyy-mm>` (the per-sector source download).

### Owner matching

- `arp assets match-owners`:
  1. LEI equal to an ARP company's LEI → `SAME_AS {method: "lei"}`.
  2. Otherwise propose candidates by name: `embed` + `rerank` from `arp/models/` against ARP company names,
     written as review items (`kind: asset_owner_match`, top 3 candidates with scores) to the existing review queue.
  3. Approving a review item writes `SAME_AS {method: "approved"}`.

### Query

- `arp assets of --company <company_id> [--as-of <date>] [--json]`: assets reached through
  `SAME_AS`→`OWNS`, with share, capacity, emissions and `source_url`; emissions and capacity totals per sector,
  weighted by ownership share.

## Acceptance

`unit` rows use a Neo4j test instance (as the existing company-graph tests do) and small fixture files. Fixture
`gem_steel.csv`: plants P1, P2, P3; owner O1 owns P1 and P2, owner O2 owns P3 (share 1.0 each), P1 capacity 2.0 Mt.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | `gem_steel.csv` | `arp assets import-gem --tracker steel --release 2026-06 --file gem_steel.csv` | The graph has 3 `Asset` nodes with `source` = `gem` and `asset_id` = `gem:<source_id>` | unit |
| AC-2  | Same | same | The graph has 2 `Owner` nodes | unit |
| AC-3  | Same | same | `OWNS` relationships are exactly O1→P1, O1→P2, O2→P3 | unit |
| AC-4  | A 1-plant fixture for each of `cement`, `coal`, `gas` | `import-gem --tracker <t>` (three runs) | Each gives 1 `Asset` with `sector` = `<t>` | unit |
| AC-5  | `gem_steel.csv` imported twice with release `2026-06` | second import | Node and relationship counts are unchanged | unit |
| AC-6  | `gem_steel.csv` imported with release `2026-06` (`published_at` 2026-06-15), then with release `2026-09` (`published_at` 2026-09-15) and P1 capacity 3.0 | `arp assets of --company <X> --as-of 2026-07-01` (X linked to O1) | P1's capacity is 2.0 (`as_of` compares with `published_at`) | unit |
| AC-7  | Same | `arp assets of --company X` | P1's capacity is 3.0 | unit |
| AC-8  | Same | query the graph for P1 | 2 versions of P1 exist; the `2026-06` version has capacity 2.0 | unit |
| AC-9  | A Climate TRACE fixture with sources S1 (1,000 t) and S2 (2,500 t), both owned by owner O3 | `import-climate-trace --release 2026-06` | 2 `Asset` nodes with `source` = `climate_trace` and `emissions_t_co2e` 1000 and 2500 | unit |
| AC-10 | Same | same | 2 `OWNS` relationships from O3 | unit |
| AC-11 | An owner whose LEI equals ARP company X's LEI | `arp assets match-owners` | A `SAME_AS {method: "lei"}` from that owner to X exists | unit |
| AC-12 | An owner without LEI; `embed`/`rerank` stand-ins rank companies Y, Z, W first to third | `match-owners` | One review item of kind `asset_owner_match` with exactly 3 candidates, Y first, each with a score | unit |
| AC-13 | Same | `match-owners` | No `SAME_AS` from that owner exists | unit |
| AC-14 | An owner with an LEI that matches no ARP company; stand-ins rank Y first | `match-owners` | One review item, Y first; no `SAME_AS` from that owner | unit |
| AC-15 | The AC-12 review item | approve it as user `u1` through the existing review decision endpoint (`POST /review/runs/{run_id}/items/{item_key}/decision` with an approve decision) | `SAME_AS {method: "approved", approved_by: "u1"}` to Y exists with `approved_at` set | unit |
| AC-16 | X linked to O1; O1 owns P1 with `share` 0.5; P1 capacity 2.0 Mt, emissions 4.0 Mt CO2e | `arp assets of --company X --json` | `sectors.steel.capacity` is 1.0 and `sectors.steel.capacity_unit` is `Mt` | unit |
| AC-17 | Same | same | `sectors.steel.emissions_t_co2e` is 2,000,000 | unit |
| AC-18 | Same | same | P1's row has `source_url` equal to the fixture's URL | unit |
| AC-19 | A GEM fixture whose row 3 has no `source_id` | `import-gem` | Exit code 1; stderr is `row 3: missing source_id` | unit |
| AC-20 | Same | same | No `Asset` or `Owner` node from that file exists | unit |
| AC-21 | A Climate TRACE fixture whose row 2 has no `source_id` | `import-climate-trace` | Exit code 1; stderr is `row 2: missing source_id`; no node from that file exists | unit |
| AC-22 | `ARP_NEO4J_URI` unset | each of `import-gem`, `import-climate-trace`, `match-owners`, `of` | Each exits 1 with `company graph not configured: set ARP_NEO4J_URI` | unit |
| AC-23 | GEM steel and cement trackers (pinned release), `backend/tests/golden/asset_owners.jsonl` (listed owners with their correct ARP company id) | `arp golden-set asset-owners --cases backend/tests/golden/asset_owners.jsonl --min-recall 0.80` | Exit code 0 (a case counts as matched when it has an LEI match or the correct company is the top-1 candidate) | golden |
| AC-24 | The supply-edge fixture used by the existing company-graph tests | `arp theme edges import` then `edges_at(2026-01-01)` | Returns the same edges as on `main` | unit |
| AC-25 | The existing backend test suite on `main` | `python3 -m pytest backend/tests` on this branch, excluding files added by this change | Same pass/fail result per test as on `main` | unit |

Must not change: supply-edge import and `edges_at` (AC-24, AC-25).
