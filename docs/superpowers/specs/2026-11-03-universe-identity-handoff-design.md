# Universe and identity hand-off

Spec slug: `universe-identity-handoff`. Gaps G1, G2, G8, G9 and G10 of the universe-to-documents review
(https://claude.ai/artifact/FH7Q7fWJVUpxTRbjyKLx5a).

Status: draft.

## Why

`arp identity enriched-universe` is the file that feeds `arp discover run`, `arp documents warm` and the theme
run. Today it writes only `company_id`, `name`, `website`, `cik`, `lei` and `isin`
(`arp/discovery/identity_pipeline.py:160-163`). Ticker, country, sector, the ISIC / NACE / GICS codes, regimes,
fiscal year end and `entity_id` from the input universe are lost. The theme run reads ISIC, NACE, country and
ticker (`arp/research/match_graph.py:70-73, 145`), and the A2 theme funnel's sector-code narrowing needs the codes.

The same export drops a company that was resolved by LEI but has no website or CIK (`identity_pipeline.py:158`),
although discovery can work from an LEI alone (ESEF, Wikidata homepage). A reviewer cannot correct an LEI
(`arp/cli/identity.py:106`, `arp/review/decide.py:43`). Every `arp identity resolve` run pays all lookups and LLM
calls again, because the CLI has no way to pass the previous run (`identity_pipeline.py:106-120`). The universe
loader accepts the same `company_id` twice (`arp/universe.py:55-63`).

## Goals

1. G1: `enriched_universe` keeps every field of the input company and only overwrites `website`, `cik`, `lei`
   and `isin`.
2. G2: a company that ends up with an LEI but no website and no CIK is exported.
3. G8: `arp identity resolve --previous-run <run_id>` reuses that run's results for companies that do not need a
   re-check.
4. G9: `load_company_universe` rejects a file with a duplicate `company_id`, and its docstring lists every column
   it reads.
5. G10: a reviewer can correct the LEI of an identity item, from the CLI and the API.

## Non-goals

- Filtering the universe by sector code. That is the A2 theme funnel's (sector-code narrowing). This spec only
  keeps the codes.
- Keeping holdings weights in the universe. `CompanyRef` would need a new field; not worth it now.
- Turning the holdings `sector` text into a code.
- Changes to discovery, warm or the theme run.
- Any frontend change. The review page keeps sending `{"value": ...}`; that path stays as it is.

## Anti-goals

- An exported company whose `isic_code`, `nace_code`, `gics_code`, `country`, `ticker`, `sector`, `regimes`,
  `fiscal_year_end` or `entity_id` differ from the input universe.
- An LEI in the export that failed `lei_is_valid`.
- A company excluded today for `reject` or for an open flag (no decision) that becomes exported.

## Design

