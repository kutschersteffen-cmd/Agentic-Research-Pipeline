# Universe and identity hand-off

Spec slug: `universe-identity-handoff`. Gaps G1, G2, G8, G9 and G10 of the universe-to-documents review
(https://claude.ai/artifact/FH7Q7fWJVUpxTRbjyKLx5a).

Status: approved by the owner, 2026-11-03.

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
4. G9: `load_company_universe` rejects a file with a duplicate `company_id`.
5. G10: a reviewer can correct the LEI of an identity item, from the CLI and the API.

## Non-goals

- Filtering the universe by sector code. That is the A2 theme funnel's (sector-code narrowing). This spec only
  keeps the codes.
- Keeping holdings weights in the universe. `CompanyRef` would need a new field; not worth it now.
- Turning the holdings `sector` text into a code.
- Changes to discovery, warm or the theme run.
- Any frontend change. Existing website and CIK corrections keep working as today.

## Anti-goals

- An exported company whose `isic_code`, `nace_code`, `gics_code`, `country`, `ticker`, `sector`, `regimes`,
  `fiscal_year_end` or `entity_id` differ from the input universe.
- An LEI in the export that failed `lei_is_valid`.
- A company excluded today for `reject` or for an open flag (no decision) that becomes exported.

## Design


### G1: keep input fields (`identity_pipeline.py::enriched_universe`)

Read the run's input companies with `run_store.load_companies(run_id)` (both `arp/storage/run_store.py:158` and
`arp/db/runs.py:370` have it). Index them by `company_id`. For each exported result, start from the input
`CompanyRef` and `model_copy(update=...)` only `website`, `cik`, `lei` and `isin`.

Null rule: an update value that is `None` is left out of the update, so the input value stays. Example: the input
has `isin="DE0007236101"` and the result's `identifiers` has no `isin`; the export keeps `DE0007236101`.

If the run has no saved companies (`load_companies` returns `None`, older runs) or the company is missing from
them, the entry is built from the result alone: `company_id`, `name` (= `input_name`), `website`, `cik`, `lei`,
`isin` from the result, and every other `CompanyRef` field at its default (`null`, `regimes: []`,
`nace_rev: "2"`). That is today's output.

### LEI precedence (G2 and G10)

The exported LEI is the first one present of: the reviewer's corrected LEI (`edited_value["resolved_lei"]`),
`identifiers["lei"]`, `derived_lei`, `resolved_lei`, the input's `lei`. Any candidate that fails
`lei_is_valid(normalise_lei(...))` is skipped; if none passes, the exported `lei` is `null`. The same LEI is used
for the G2 inclusion test and for the exported value.

### G2: LEI-only companies

The exclusion test becomes: not included, or none of website, CIK and the exported LEI. The inclusion rules
(resolved and not flagged, or a final approve or correct decision; reject and open flags excluded) do not change.

### G8: `--previous-run`

`run_identity_resolution` gains `previous_run_id: str | None = None` and passes it to `execute_identity_run`.
`arp identity resolve` gains `--previous-run` (optional) and passes it through. Reuse rules stay in
`match_rules.needs_recheck` (a changed LEI, CIK or ISIN forces a re-check, `match_rules.py:71-72`). An unknown run
id exits 1 with `Run not found: <id>` on stderr before the LLM client is built and before any run is created.

### G9: duplicate ids

`load_company_universe` raises `UniverseRejected(f"duplicate company_id '{id}'")` on the second occurrence of an
id. Every caller already handles `UniverseRejected` (the upload route returns it as HTTP 422,
`arp/api/routers/universe.py:40-41`).

### G10: correct an LEI

- `CORRECTED_KEYS["identity"]` (`arp/review/decide.py:43`) adds `resolved_lei`.
- The identity check (`decide.py:132`) accepts `resolved_website`, `resolved_cik` **or** `resolved_lei`.
- A `resolved_lei` is normalised with `normalise_lei` (trimmed, upper case) before it is validated and stored,
  as `decide.py:232-233` already does for `security` items. One that fails `lei_is_valid` is rejected with 422
  `an identity correction needs a valid LEI`.
- `arp identity review` gains `--lei`. With `--decision correct`, at least one of `--website`, `--cik`, `--lei`
  is required; the error message names all three. `corrected_value` holds only the flags given: today
  `cli/identity.py:106` always sends `resolved_website` and `resolved_cik`, even as `None`, which would null a
  website on an LEI-only correction. `enriched_universe` also treats a `None` corrected field as absent (null rule). A `DecisionError` is printed as today (`cli/identity.py:113-115`).
- `enriched_universe` applies the corrected LEI by the precedence above.

A correction needs a second reviewer before it is final (`second_review_reasons`, rule `correction`), and only
final decisions reach the export (`effective_decisions`). The rows below say "final correction" for: corrected
by user `u1`, then the same correction by user `u2`. Every row that asserts a review state or a final decision runs
with `second_review_sample_rate=0`.

## Left to the builder

- Where the input-company index is built.
- The loader docstring (`arp/universe.py:35-41`) lists every column it reads: company_id, entity_id, name,
  ticker, website, cik, lei, isin, country, sector, isic_code, nace_code, nace_rev, gics_code, regimes,
  fiscal_year_end.
- `identity_pipeline.py:156` still accepts a decision `edit`, which `decide` no longer produces. Leave it; not part
  of this spec.
- `second_review_reasons` reads `corrected_value["value"]` when a prior value exists (`decide.py:75`). An identity
  correction holds `resolved_*` keys, not `value`. Check whether identity items can have a prior value; if they
  can, a correction would raise `KeyError`. Report it, do not widen this spec.

## Acceptance

Fixtures: an identity run created with `create_identity_run` over the stated companies and executed with stand-in
lookups and a stand-in LLM, as in `tests/test_identity_pipeline.py`. Decisions are recorded with `decide`,
the CLI or the API as each row says. "Final correction" is defined in the Design. API calls go to
`POST /api/review/runs/{run_id}/items/{item_key}/decision` with body
`{"decision": "correct", "reason_code": "wrong_entity", "corrected_value": {...}, "comment": "GLEIF record", "context_etag": <etag from GET /api/review/runs/{run_id}/items/{item_key}/context>}`.
Rows that need an identity run with stored results are `unit`: the e2e app cannot create one without real
lookups and an LLM. The `holdout` rows (AC-10, AC-10b, AC-12) need no identity run results.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | Input company `C1`: `name="C1 AG"`, `ticker="C1X"`, `website="https://c1.example"`, `isin="DE0007236101"`, `country="DE"`, `sector="Industrials"`, `isic_code="2829"`, `nace_code="28.29"`, `nace_rev="2"`, `gics_code="201040"`, `regimes=["CSRD"]`, `fiscal_year_end="03-31"`; result resolved by `supplied`, not flagged | `arp identity enriched-universe <run> --out f.json` | `f.json`'s entry for `C1` has exactly those twelve values | unit |
| AC-2  | Same as AC-1, with column `entity_id=00000000-0000-0000-0000-000000000001` for `C1` in the `u.csv` passed to `arp identity resolve --names-file` | same | `C1`'s `entity_id` is `00000000-0000-0000-0000-000000000001` | unit |
| AC-3  | Input company `C2` with `isic_code="2711"` and no website; flagged; final correction `{"resolved_website": "https://c2.example"}` | same | `C2`'s `website` is `https://c2.example` | unit |
| AC-3b | Same as AC-3 | same | `C2`'s `isic_code` is `2711` | unit |
| AC-3c | Input company `C9` with `isin="DE0007236101"`; result's `identifiers` has no `isin`; resolved by `supplied` | same | `C9`'s `isin` is `DE0007236101` | unit |
| AC-4  | A run where `load_companies` returns `None`; result `C10`: `input_name="C10 SA"`, `resolved_website="https://c10.example"`, resolved, not flagged, no identifiers | same | `C10`'s entry is `company_id="C10"`, `name="C10 SA"`, `website="https://c10.example"`, `cik`/`lei`/`isin`/`ticker`/`country`/`sector`/`isic_code`/`nace_code`/`gics_code`/`fiscal_year_end`/`entity_id` all `null`, `regimes=[]`, `nace_rev="2"` | unit |
| AC-5  | Input company `C3` with `lei="5493001KJTIIGC8Y1R12"` only; result `exact_lei`, no website, no CIK, flagged; decision `approve` (final) | same | `f.json` contains `C3` with `lei="5493001KJTIIGC8Y1R12"`, `website=null`, `cik=null` | unit |
| AC-6  | Input company `C4` resolved by `exact_lei`, flagged, no decision | same | `f.json` has no entry for `C4` | unit |
| AC-7  | Input company `C5`, flagged, decision `reject` (final) | same | `f.json` has no entry for `C5` | unit |
| AC-8  | Run R1 over `u.csv` with company `C6` (`website` and `cik="0000320193"` supplied, rule `supplied`), stand-in lookups and LLM via `run_identity_resolution` | `run_identity_resolution` over the same `u.csv` with `previous_run_id=R1` | The new run's result for `C6` has the same `generated_at` as in R1 | unit |
| AC-9  | Same, but `C6`'s `cik` is `0000789019` in the second `u.csv` | same | The new run's result for `C6` has a `generated_at` different from R1's | unit |
| AC-9b | Same as AC-8 | `arp identity resolve --names-file u.csv --previous-run R1` with the stand-ins patched in | stdout ends with `Run complete: <new run id> (0/1 flagged for review)` | unit |
| AC-10 | No run `R404` | `arp identity resolve --names-file u.csv --previous-run R404` | Exit code 1 and stderr is `Run not found: R404` | holdout |
| AC-10b| Same | `arp runs list --run-type identity` before and after AC-10's command | Same number of lines both times | holdout |
| AC-11 | Universe CSV with two rows `company_id=A` | `load_company_universe` | Raises `UniverseRejected` with message `duplicate company_id 'A'` | unit |
| AC-12 | Same CSV as `dup.csv` | `POST /api/universe/upload` with `dup.csv` | HTTP 422, `detail` is `duplicate company_id 'A'` | holdout |
| AC-13 | Flagged identity item `C7` (result `resolved_lei="529900T8BM49AURSDO55"`, `resolved_website="https://c7.example"`) | `arp identity review <run> C7 --decision correct --reason wrong_entity --lei 5493001KJTIIGC8Y1R12 --comment "GLEIF record"` as user `u1` | stdout is `Recorded (first_done).`, exit code 0 | unit |
| AC-14 | AC-13 plus the same correction by user `u2` | `arp identity enriched-universe <run> --out f.json` | `C7`'s `lei` is `5493001KJTIIGC8Y1R12` | unit |
| AC-14b| Same as AC-14 | `arp identity enriched-universe <run> --out f.json` | `C7`'s `website` is `https://c7.example` | unit |
| AC-15 | Flagged identity item `C11` | API correction with `corrected_value={"resolved_lei": "NOTANLEI"}` | HTTP 422, `detail` is `an identity correction needs a valid LEI` | unit |
| AC-15b| Flagged identity item `C11` | `arp identity review <run> C11 --decision correct --reason wrong_entity --lei NOTANLEI --comment x` | Exit code 1, stderr is `an identity correction needs a valid LEI` | unit |
| AC-16 | Flagged identity item `C7` | `arp identity review <run> C7 --decision correct --reason wrong_entity --comment x` (no website, cik or lei) | Exit code 1, stderr contains `--website`, `--cik` and `--lei` | unit |
| AC-17 | Flagged identity item `C12` | API correction with `corrected_value={"resolved_lei": "5493001KJTIIGC8Y1R12"}` | HTTP 200, body `state` is `first_done` | unit |
| AC-17b| AC-17 plus the same correction by user `u2` | `arp identity enriched-universe <run> --out f.json` | `C12`'s `lei` is `5493001KJTIIGC8Y1R12` | unit |
| AC-18 | Flagged identity item `C13` | API correction with `corrected_value={"resolved_lei": " 5493001kjtiigc8y1r12 "}`, then the same by user `u2`, then `enriched-universe` | `C13`'s `lei` is `5493001KJTIIGC8Y1R12` | unit |
| AC-19 | Flagged identity item `C8` | API correction with `corrected_value={"resolved_website": "https://c8.example"}` | HTTP 200, body `state` is `first_done` | unit |
| AC-19b| AC-19 plus the same correction by user `u2` | `arp identity enriched-universe <run> --out f.json` | `C8`'s `website` is `https://c8.example` | unit |
| AC-19c| Flagged identity item `C15`, final correction `{"resolved_cik": "0000320193"}` | `arp identity enriched-universe <run> --out f.json` | `C15`'s `cik` is `0000320193` | unit |
| AC-19d| Input company `C14` with `lei="BADLEI"` and a supplied website; resolved by `supplied`, not flagged | `arp identity enriched-universe <run> --out f.json` | `C14`'s `lei` is `null` | unit |
| AC-20 | The existing backend test suite on `main` | `python3 -m pytest backend/tests` on this branch, excluding files added by this change | Same pass/fail result per test as on `main` | unit |

Must not change: the inclusion and exclusion rules for resolved, flagged and rejected companies (AC-6, AC-7);
website and CIK corrections (AC-19, AC-19b, AC-19c); older runs without saved companies (AC-4); every existing
test (AC-20).
