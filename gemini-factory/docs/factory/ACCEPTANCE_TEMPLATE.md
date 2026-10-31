# Acceptance section template

Every spec in `docs/factory/specs/` ends with this section. The owner approves it with the spec, before
any code is written. It is the only definition of "done": anything the spec leaves open is decided here,
not by the implementing agent. The checks come from tests and agents the implementer cannot see or edit,
so the implementer can't rewrite a test until it matches the code.

## Copy this into the spec

```markdown
## Acceptance

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 |       |      |                          | holdout    |
| AC-2 |       |      |                          | evaluator  |

Must not change: <behaviours that stay as they are, each also an AC row>
```

## Rules for rows

- One observable behaviour per row: CLI output, an API response, a database row, what the UI shows.
- "Then" is exact: values, counts, messages, status codes. "Works correctly" is not a criterion.
- IDs are stable. Never renumber. Retire a row with ~~strikethrough~~ and the reason.
- Behaviour that must stay the same gets its own row.
- "Checked by" is one of:
  - `holdout`: a deterministic test in the private holdout repo (`/factory:tests`).
  - `evaluator`: an agent checks it by using the running app (`/factory:evaluate`).
  - `unit`: the implementer's own tests. Only for low-stakes rows.
