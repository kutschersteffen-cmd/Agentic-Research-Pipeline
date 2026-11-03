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

### G1: keep input fields (`identity_pipeline.py::enriched_universe`)

Read the run's input companies with `run_store.load_companies(run_id)` (both `arp/storage/run_store.py:158` and
`arp/db/runs.py:370` have it). Index them by `company_id`. For each exported result, start from the input
`CompanyRef` and `model_copy(update=...)` only `website`, `cik`, `lei`, `isin`. If the run has no saved companies
(`None`, older runs) or the company is missing from them, fall back to today's behaviour (a new `CompanyRef` from
the result alone).

### G2: LEI-only companies

The exclusion test becomes: not included, or none of website, CIK and LEI. LEI here is the exported LEI
(`identifiers["lei"]`, else `derived_lei`, else `resolved_lei`, else a reviewer's corrected LEI). The inclusion
rules (resolved and not flagged, or approve / edit / correct; reject and open flags excluded) do not change.

### G8: `--previous-run`

`run_identity_resolution` gains `previous_run_id: str | None = None` and passes it to `execute_identity_run`.
`arp identity resolve` gains `--previous-run` (optional) and passes it through. Reuse rules stay in
`match_rules.needs_recheck`. An unknown run id exits 1 with `Run not found: <id>` before any company is resolved.

### G9: duplicate ids

`load_company_universe` raises `UniverseRejected(f"duplicate company_id '{id}'")` on the second occurrence. The
docstring lists: company_id, name, ticker, website, cik, lei, isin, country, sector, isic_code, nace_code,
nace_rev, gics_code, regimes, fiscal_year_end.

### G10: correct an LEI

- `CORRECTED_KEYS["identity"]` (`arp/review/decide.py:43`) adds `resolved_lei`.
- The identity check (`decide.py:132`) accepts `resolved_website`, `resolved_cik` **or** `resolved_lei`. A
  `resolved_lei` that fails `lei_is_valid(normalise_lei(...))` is rejected with 422
  `an identity correction needs a valid LEI`.
- `arp identity review` gains `--lei`. With `--decision correct`, at least one of `--website`, `--cik`, `--lei`
  is required; the existing error message names all three.
- `enriched_universe` applies `edited.get("resolved_lei")` (normalised) before the result's own LEI.

## Left to the builder

Where the input-company index is built; the exact wording of the CLI error for a missing correction field, as
long as it names `--website`, `--cik` and `--lei`.

## Acceptance

Run fixtures: an identity run created with `create_identity_run` over the stated companies, results written with
stand-in lookups and LLM (as in `tests/test_identity_pipeline.py`), decisions recorded with `decide`.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | Input company `C1` with `isic_code="2829"`, `nace_code="28.29"`, `gics_code="201040"`, `country="DE"`, `ticker="C1X"`, `sector="Industrials"`, `regimes=["CSRD"]`, `fiscal_year_end="03-31"`, `website` supplied; result resolved and not flagged | `arp identity enriched-universe <run> --out f.json` | `f.json`'s entry for `C1` has exactly those eight values | holdout |
| AC-2  | Same run, input `C1` saved with `entity_id` `00000000-0000-0000-0000-000000000001` | same | `C1`'s `entity_id` in `f.json` is `00000000-0000-0000-0000-000000000001` | holdout |
| AC-3  | Input company `C2` with no website; reviewer `correct` with `resolved_website="https://c2.example"` | same | `C2`'s `website` is `https://c2.example` and its `isic_code` equals the input's | holdout |
| AC-4  | A run whose saved input companies are absent (`load_companies` returns `None`) | same | Exits 0; each entry has the same keys and values as before this change | holdout |
| AC-5  | Input company `C3` with a valid LEI only, resolved by `exact_lei`, no website and no CIK found, decision `approve` | same | `f.json` contains `C3` with that `lei`, `website: null`, `cik: null` | holdout |
| AC-6  | Input company `C4` resolved by `exact_lei`, flagged, no decision | same | `f.json` has no entry for `C4` | holdout |
| AC-7  | Input company `C5`, decision `reject` | same | `f.json` has no entry for `C5` | holdout |
| AC-8  | Run R1 with company `C6` resolved by rule `supplied`; same universe file | `arp identity resolve --names-file u.csv --previous-run R1` | The new run's result for `C6` has the same `generated_at` as in R1 | holdout |
| AC-9  | Same, but `C6`'s `cik` changed in `u.csv` | same | The new run's result for `C6` has a different `generated_at` than in R1 | holdout |
| AC-10 | No run `R404` | `arp identity resolve --names-file u.csv --previous-run R404` | Exit code 1, stderr contains `Run not found: R404`, no run is created | holdout |
| AC-11 | Universe CSV with two rows `company_id=A` | `load_company_universe` | Raises `UniverseRejected` with message `duplicate company_id 'A'` | holdout |
| AC-12 | Same file | `arp discover run --universe dup.csv` | Exit code ≠ 0 and output contains `duplicate company_id 'A'` | holdout |
| AC-13 | Flagged identity item `C7` | `arp identity review <run> C7 --decision correct --reason wrong_entity --lei 5493001KJTIIGC8Y1R12 --comment "GLEIF record"` | Prints `Recorded (` and exits 0 | holdout |
| AC-14 | AC-13 recorded | `arp identity enriched-universe <run> --out f.json` | `C7`'s `lei` is `5493001KJTIIGC8Y1R12` | holdout |
| AC-15 | Flagged identity item | `POST` decision `correct` with `corrected_value={"resolved_lei": "NOTANLEI"}` and a comment | HTTP 422, detail `an identity correction needs a valid LEI` | holdout |
| AC-16 | Flagged identity item | `arp identity review <run> C7 --decision correct --reason wrong_entity --comment x` (no website, cik or lei) | Exit code 1, stderr names `--website`, `--cik` and `--lei` | holdout |
| AC-17 | Flagged identity item | `POST` decision `correct` with `corrected_value={"value": "https://c8.example"}` and a comment | Recorded; enriched universe gives `C8` `website` `https://c8.example` (unchanged path) | holdout |
| AC-18 | The existing backend test suite on `main` | `python3 -m pytest backend/tests` on this branch, excluding files added by this change | Same pass/fail result per test as on `main` | unit |

Must not change: the inclusion and exclusion rules for resolved, flagged and rejected companies (AC-6, AC-7);
the review page's free-text override (AC-17); older runs without saved companies (AC-4); every existing test
(AC-18).
