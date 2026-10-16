# Acceptance section template

Every spec in `docs/superpowers/specs/` ends with this section. The owner approves it together with the
spec, before any code is written. It is the only definition of "done" that counts: anything the spec leaves
open is decided here, not by the implementing agent.

Why: an agent that writes the code and its own tests can rewrite a test until it matches the code. The
criteria below are checked by tests and agents the implementer cannot see or edit. See
[SOFTWARE_FACTORY_RESEARCH.md](../SOFTWARE_FACTORY_RESEARCH.md) for the sources.

## Copy this into the spec

```markdown
## Acceptance

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 |       |      |                          | holdout    |
| AC-2 |       |      |                          | evaluator  |

Must not change: <behaviours that stay as they are, each also an AC row>
```

## Rules for writing rows

- **One observable behaviour per row**, visible from outside the code: CLI output, an API response, a
  database row, what the UI shows. "Function X is called" is not a criterion.
- **"Then" is exact**: values, counts, messages, status codes. "Works correctly" is not a criterion.
- **IDs are stable.** Never renumber. Retire a row with ~~strikethrough~~ and the reason.
- **Regressions are rows too.** Behaviour that must stay the same gets its own ID.
- **"Checked by"** is one of:
  - `holdout`: a deterministic test in the private holdout repo. The default.
  - `evaluator`: a separate agent checks it by using the running app (UI flows, wording, layout).
  - `unit`: the implementer's own tests are enough. Only for low-stakes rows.

## Who does what

| Role | Sees | Does |
|------|------|------|
| Owner | Everything | Approves the table with the spec. Reads the AC matrix at merge. |
| Test-writer agent | This table and `main`. Never the implementation branch | Writes one test per `holdout` row into the private holdout repo, named `test_ac_<n>_<short_name>` |
| Implementer agent | The spec and this repo. Never the holdout repo: it is not attached to the session | Builds the change. Gets back only "AC-n failed: <symptom>", never test code |
| CI | Both repos, read-only token for the holdout repo | Runs the holdout tests against the PR build as a required check, reports pass or fail per AC ID |
| Evaluator agent | The running PR build and this table | Checks the `evaluator` rows the way a user would and posts the AC matrix on the PR |

## AC matrix (posted on the PR)

| ID   | Result | Evidence |
|------|--------|----------|
| AC-1 | pass   | holdout `test_ac_1_<short_name>` |
| AC-2 | fail   | evaluator: what it did, what it saw, what the row expected |

The PR merges only when every row passes or the owner signs off a row as an accepted exception in the PR.
