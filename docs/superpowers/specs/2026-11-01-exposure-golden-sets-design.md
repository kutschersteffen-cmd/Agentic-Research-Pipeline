# Exposure golden sets (action plan A3)

Spec slug: `exposure-golden-sets`. Parent: `2026-11-01-model-stack-design.md` (approved).

Status: approved by the owner, 2026-11-01.

## Why

Every model integration is switched on only after a golden-set comparison (umbrella-spec rule). The
thematic funnel (A2), revenue sizing (B1) and the risk pipelines have no golden set yet. The electrolyser draft
(`docs/golden_drafts/electrolyser_manufacturers.md`, 27 companies, labels checked 2026-11-01) is a start, but
it is too small to set thresholds on and evaluate on the same companies.

## Goals

1. A file format for company-level exposure golden sets: one case per company with a label, the activity or
   risk, the evidence source for the label, and the documents to run on.
2. Three sets:
   - **`electrolyser_makers`**, activity, ~60 companies (the 27 from the draft plus ~33 more: listed makers in
     China, Japan and Korea, more suppliers, buyers and fuel-cell makers).
   - **`ai_datacentre_operators`**, a deliberately fuzzy activity, ~60 companies (operators, REITs, hyperscalers,
     equipment and chip suppliers, utilities that power them).
   - **`water_scarcity_exposed`**, a risk, ~60 companies (cement, mining, semiconductors, beverages, utilities,
     with and without water-stressed sites).
3. A deterministic split into `tune` and `holdout` halves, stratified by label.
4. A CLI that validates a set and reports its balance.

## Non-goals

- Scoring a model or a run against a set: each integration spec (A2, A4, B1, …) defines its own golden command
  and threshold, reading this format.
- Downloading documents automatically. The set lists document URLs and local paths; fetching uses the existing
  discovery and EDGAR tools.
- ~~Private companies.~~ Allowed since 2026-11-02 (owner): private makers may be cases when they publish a report or press releases usable as `documents`; most pure-play electrolyser makers are private.

## Anti-goals

- A label without a source URL and a check date.
- Tuning thresholds on `holdout` cases. This spec only marks the split; each integration spec enforces it by
  tuning with `--split tune` and gating with `--split holdout`.

## Design

### Location and format

`backend/tests/golden/exposure/<set_id>/cases.json`:

```json
{"set_id": "electrolyser_makers", "kind": "activity", "subject": "Manufactures and sells electrolysers…",
 "labels": ["core", "peripheral", "not"], "checked_on": "2026-11-01",
 "cases": [{"case_id": "nel", "company": "Nel ASA", "lei": "…", "isin": "…", "label": "core",
            "role": "make_electrolysers", "rationale": "…", "label_sources": ["https://…"],
            "documents": [{"kind": "annual_report", "fiscal_year": 2025, "url": "https://…", "path": "nel_ar2025.pdf"}],
            "split": "tune"}]}
```

Required set keys: `set_id, kind, subject, labels, checked_on (ISO date), cases`. Required case keys: `case_id,
company, label, role, rationale, label_sources (≥ 1 entry, each an http(s) URL), documents (≥ 1 entry, each with
`url` or `path`; a `path` must exist under `documents/`)`. Optional: `lei, isin, split`.

`kind` is `activity` or `risk`. For risk sets the labels are `exposed_disclosed`, `exposed_undisclosed`,
`not_exposed` (the second marks exposure the company does not write about, from asset or location data, with
that source in `label_sources`). Documents are stored under `backend/tests/golden/exposure/<set_id>/documents/`
only when their licence allows it; otherwise `url` only.

### Split

`split` is assigned once by `arp golden-set exposure split`: cases sorted by `case_id`, then within each label
every second case is `holdout`, starting with the first. An existing `split` value is never changed.

### CLI

- `arp golden-set exposure validate --set <dir>`: checks the schema (every required key present, `label` in
  `labels`, ≥ 1 `label_sources`, unique `case_id`), exits 1 and prints each problem otherwise.
- `arp golden-set exposure split --set <dir>`: assigns missing `split` values as above.
- `arp golden-set exposure stats --set <dir>`: prints one line per label: `<label> tune=<n> holdout=<n>`.

### Labelling procedure (documented in `backend/tests/golden/exposure/README.md`)

1. A research pass proposes label, rationale and sources per company (web, filings).
2. A person checks every label against at least one primary source (filing or company report) and sets
   `checked_on`.
3. Hard cases are kept on purpose: suppliers, buyers and operators, licensors, exited or insolvent makers,
   conglomerates with a small unit.

## Acceptance

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | A cases file where one case has no `label_sources` key | `arp golden-set exposure validate` | Exit code 1; output contains that `case_id` and `label_sources` | unit |
| AC-2  | A cases file where one case has `"label_sources": []` | validate | Exit code 1; output contains that `case_id` and `label_sources` | unit |
| AC-3  | A cases file where one case has `"label_sources": ["see report"]` | validate | Exit code 1; output contains that `case_id` and `label_sources` | unit |
| AC-4  | A cases file where one case lacks `rationale` | validate | Exit code 1; output contains that `case_id` and `rationale` | unit |
| AC-5  | A cases file where one case's `label` is not in `labels` | validate | Exit code 1; output contains that `case_id` and the label | unit |
| AC-6  | A cases file with a duplicate `case_id` | validate | Exit code 1; output contains the duplicate id | unit |
| AC-7  | A set with `"kind": "sector"` | validate | Exit code 1; output contains `kind` | unit |
| AC-8  | A set without `checked_on` | validate | Exit code 1; output contains `checked_on` | unit |
| AC-9  | A set with `"checked_on": "last week"` | validate | Exit code 1; output contains `checked_on` | unit |
| AC-10 | A case with a document that has neither `url` nor `path` | validate | Exit code 1; output contains that `case_id` and `documents` | unit |
| AC-11 | A case with a document `path` that does not exist under `documents/` | validate | Exit code 1; output contains that `case_id` and the path | unit |
| AC-12 | A valid activity set | validate | Exit code 0 | unit |
| AC-13 | A valid risk set using `exposed_disclosed`, `exposed_undisclosed`, `not_exposed` | validate | Exit code 0 | unit |
| AC-14 | Cases a, b labelled `core` and c, d labelled `not`, none with `split` | `split` | `cases.json` afterwards has a and c `holdout`, b and d `tune` | unit |
| AC-15 | A case already marked `tune` that the rule would make `holdout` | `split` | `cases.json` afterwards still has it `tune` | unit |
| AC-16 | Cases from AC-14 after `split` | `stats` | Output contains the lines `core tune=1 holdout=1` and `not tune=1 holdout=1` | unit |
| AC-17 | The repository after this change | validate on `electrolyser_makers`, `ai_datacentre_operators`, `water_scarcity_exposed` (three runs) | Each exits 0 | unit |
| AC-18 | Each of the three sets | `stats` | The sum of all counts is ≥ 55 (the floor for "~60") | unit |
| AC-19 | Each of the three sets | `stats` | Every label line shows `holdout` ≥ 8 | unit |
| AC-20 | The repository after this change | read `backend/tests/golden/exposure/README.md` | It exists and contains the three numbered labelling steps of this spec | unit |
| AC-21 | The existing backend test suite on `main` | `python3 -m pytest backend/tests` on this branch, excluding files added by this change | Same pass/fail result per test as on `main` | unit |

Must not change: existing golden-set commands and files (AC-21).
