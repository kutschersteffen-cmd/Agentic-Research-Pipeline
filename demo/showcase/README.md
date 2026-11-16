# Showcase demo pack

Data and a run sheet for the 60-minute ARP showcase on 17 Nov 2026 (Argus, Transition Intelligence,
R&D Lab, StewardIQ). The spec is `docs/superpowers/specs/2026-11-12-showcase-demo-pack-design.md`;
the presenter reads `RUN_SHEET.md`.

Load it the day before. First `scripts/launch_jupyter.sh users` once (it prints two tokens and two lines to
add to `backend/.env`), then `scripts/launch_jupyter.sh up`, then from `backend/`, with the first token:

    ARP_SHOWCASE_TOKEN=<first token> python scripts/load_showcase_pack.py

Safe to run twice. `--only <step>` runs one step; `--again` starts the prepared runs a second time.

What is in here:

- `companies.csv`: the ten companies of the storyline. Identifiers come from GLEIF and SEC EDGAR; the
  lookups behind them are in `identifiers_source.json`.
- `documents.csv`: the 14 reports to download (10 annual reports, 4 US proxy statements). Save each into
  `documents/` under its `file_name`; the PDFs are not committed.
- Three holdings files for the R&D Lab, converted from the public ETF holdings files in `data/holdings/`
  (equity lines only, names, ISINs and weights unchanged):

Source: etf_dax.csv is data/holdings/DAX.xlsx, public ETF holdings (DAX index fund, DWS constituent export) as of 2026-11-02.
Source: etf_euro_stoxx_50.csv is data/holdings/EURO_STOXX_50.xlsx, public ETF holdings (EURO STOXX 50 index fund, DWS constituent export) as of 2026-11-02.
Source: etf_ai_big_data.csv is data/holdings/AI_Big_Data.xlsx, public ETF holdings (AI & Big Data index fund, ISIN IE00BGV5VN51) as of 2026-11-12.
Simulated: ESG values, controversial revenue shares, A-F transition grades and the June to October 2026 holdings history come from data/simulated/esg_simulated.csv, loaded by `arp showcase load`; none of it is real data.

## Rebuild

Before the showcase, rebuild the database rather than cleaning it in place: a database where the older demo seed
ran holds the 15 seeded companies twice (spec `showcase-curated-company-keys`).

1. Start from an empty Postgres database (a new database, or drop and recreate the existing one).
2. `scripts/launch_jupyter.sh up` (keep `config/users.json` and its two lines in `backend/.env`)
3. From `backend/`: `ARP_SHOWCASE_TOKEN=<first token> python scripts/load_showcase_pack.py` (runs `arp showcase load`).
4. Optional, only if the seeded demo portfolios are wanted: `arp portfolio seed-demo`.
