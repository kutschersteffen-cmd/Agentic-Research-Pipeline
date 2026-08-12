# Sample revenue/capex catalogue

`catalogue_sample.csv` is **entirely synthetic test fixture data** -- three
fictional companies (ACME, GLOBALGRID, SUNCELL) with made-up revenue/capex
line items, written purely to exercise `catalogue.py`/`mapping.py`/
`resolver.py`'s code paths in tests and a CLI demo. It is not sourced from,
or intended to resemble, any real company or vendor dataset.

No real "vast structured revenue/capex catalogue" is bundled or fetched by
this system, for the same reason no real ICIO/NACE/NAICS/SIC/GICS data is:
this kind of data is licensed (FactSet RBICS Revenue, Bloomberg product-
line revenue, a company's own internal segment-revenue database, ...) and
this environment has no network access to fetch it besides. Point the
taxonomy-mapping and run commands at your own catalogue export in this
format for real use.

## Format

`data_point_id, company_id, metric (revenue|capex), label, description,
value, unit, period, as_pct_of_total` -- one row per line item.

- `label` is the catalogue's own category/segment/product name --
  `arp revenue-catalogue suggest-mapping` proposes which labels correspond
  to which taxonomy activity; nothing is matched by exact-string convention.
- A `label="Total Revenue"` / `label="Total CapEx"` row per company is the
  denominator used to compute a share for rows that give an absolute
  `value` instead of `as_pct_of_total` directly (see `GLOBALGRID`'s rows for
  a catalogue that expresses share directly, and `ACME`'s for one that
  requires computing it against a total).
- `value` may be omitted if `as_pct_of_total` is supplied directly (some
  vendor feeds, e.g. FactSet RBICS Revenue, report revenue share without
  an absolute dollar figure).
