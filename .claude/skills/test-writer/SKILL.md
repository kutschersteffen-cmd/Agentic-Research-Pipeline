---
name: test-writer
description: Turn a spec's `holdout` acceptance rows into hidden tests in the private holdout repo. Use in a session that has kutschersteffen-cmd/holdout attached and has NOT worked on the implementation, after the owner approved the spec.
---

You write the hidden acceptance tests for one spec. The implementing agent never sees them, so they
check what the spec says, not what the implementation happens to do.

## Rules

- **Inputs:** the spec file in `docs/superpowers/specs/` (its `## Acceptance` table) and the app's
  `main` branch. Never read or check out the implementation branch or its PR.
- **One test per `holdout` row**, in `specs/<slug>/test_ac_<n>_<short_name>.py` in the holdout repo.
  `<slug>` is the spec file name without the date prefix and `.md`.
- **Mark every test** `@pytest.mark.ac("AC-<n>", kind="new")` for behaviour the change adds, or
  `kind="keep"` for a "must not change" row.
- **Drive the running app only** (`api` and `page` fixtures in the holdout repo's `conftest.py`);
  never import the app's code. Assert exactly what the row's "Then" says: values, counts, messages.
- **Prove each test means something** before opening the PR. Start `main` with
  `backend/scripts/e2e_stack.sh up`, then run `python run.py --check-new --spec <slug>` in the
  holdout repo: every `new` test must fail and every `keep` test must pass. The holdout repo's CI
  runs the same check and fails the PR otherwise.
- Open the PR in the holdout repo, not in the app repo, and tell the owner the spec slug. The
  implementing PR names the same slug in its description as `Spec: <slug>`.
- Never paste test code, assertions or expected values into the app repo, its PRs or comments.

## After the implementing PR merges

Move `specs/<slug>/` into `regression/` (or copy it) so the behaviour stays checked on every PR.
