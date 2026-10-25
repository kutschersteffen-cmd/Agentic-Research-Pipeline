# Theme dossier: one record and one page per theme

Status: draft, 2026-10-25.

## The process this serves (owner decisions, 2026-10-25)

The owner defined one research process for any theme, in five steps:

1. **Spot + context.** An emerging theme with a context brief: why now, early evidence, affected sectors.
2. **Define.** A ratified thematic taxonomy. Every extraction about the theme (revenue, CapEx, OpEx, R&D,
   innovation) uses a schema generated from the ratified taxonomy version.
3. **Research.** A theme-level note on risks and opportunities, financial relevance, growth potential and the
   economic and financial transmission channels. It is written only from authoritative sources (IEA, academic
   research, official statistics; no think tanks, no non-profit or industry initiatives) that the model proposes
   with why and how to use each, and that the user approves before anything is written.
4. **Find companies.** The exposed universe, measured with the taxonomy's schema and reviewed.
5. **Position + standards.** The house position and narrative on the theme, derived from the research's risks
   and opportunities; standards are checkable stewardship expectations for exposed companies, derived from the
   position and flagged in StewardIQ.

Every approval point needs one person only. The owner chose approach A: one **theme dossier** that ties the
steps together, built first. Steps 3 and 5, the taxonomy-generated schema and the step 1 brief each get their
own spec later and attach to the dossier.

## Intent

Today the pieces of a theme live on separate screens and are joined only by ids passed between them. Nobody
can see in one place where a theme stands, what waits for them, or which taxonomy version the company list was
measured against. The dossier is that place: one record per theme that links its pieces, and one page that
shows the five steps with their live state.

## Goals

- Every theme has one dossier, reachable from the R&D Lab.
- The dossier page shows the five steps, each with a state and the next action, read from the records that
  already exist (candidates, taxonomies, theme runs, review items).
- A promoted Emerging Themes candidate opens a dossier automatically; a user can also start one from a topic.
- The dossier makes version mismatches visible: a company run measured against an older taxonomy version than
  the latest ratified one is flagged.

## Non-goals

- Building steps 3 and 5, the taxonomy-generated schema, or the step 1 brief (their own specs).
- Changing how matching, taxonomy drafting or ratification work.
- Replacing the existing R&D Lab process "Launch a thematic product".

## Anti-goals

- Copying data into the dossier that already lives elsewhere. The dossier stores links and decisions; every
  state on the page is derived on read, so it can never disagree with the screens it links to.
- A step shown as done when the record behind it is not.

## Approaches

| | Approach | Trade-off | |
|---|---|---|---|
| A | **Theme dossier record + guided page.** | Traceable chain from brief to standards; one new record type and page. | **Chosen by the owner** |
| B | Extend the process bar only, passing ids between screens. | Least code; nothing guarantees the pieces belong to the same taxonomy version. | Rejected |
| C | One orchestrating agent run that pauses at each approval. | Most automated; long-lived runs fit poorly with approvals spread over weeks. | Rejected |

## The record

A dossier holds:

- `dossier_id` (`dos_` + 12 hex), `name`, `created_by`, `created_at`;
- `origin`: `candidate` (with `run_id`, `theme_id` of the Emerging Themes candidate) or `topic`;
- `taxonomy_id` (nullable until a taxonomy exists);
- `status`: `active` or `shelved`, with `shelved_by`, `shelved_at`, `shelve_reason` when shelved.

Nothing else. Taxonomy versions, runs and review items are found from `taxonomy_id`.

## Step states (derived on read)

Each step has a `state` and a `detail` line. States: `done`, `waiting` (on a person), `running`, `failed`,
`not_started`, `skipped`, `not_built`.

1. **Spot.** Origin `candidate`: the candidate's status (`promoted` → `done`, with its decision reason; the
   candidate missing → `failed`, detail `candidate not found`). Origin `topic` → `skipped`, detail `started from
   a topic`.
2. **Define.** No `taxonomy_id` → `not_started`. A taxonomy with no ratified version → `waiting`, detail
   `ratify a version`. Otherwise `done`, detail `v<n> ratified by <name>` for the latest ratified version.
3. **Research.** Always `not_built`, detail `coming next`.
4. **Find companies.** The theme runs whose parameters name this `taxonomy_id`, newest first. None →
   `not_started`. The newest one: active → `running`; failed → `failed`; completed with open review items →
   `waiting`, detail `<n> to review`; completed with none open → `done`, detail `<n> companies, taxonomy v<m>`.
   When `m` is lower than the latest ratified version, detail gains ` · older than v<latest>` and the state is
   `waiting`.
5. **Position + standards.** Always `not_built`, detail `coming later`.

A shelved dossier shows its steps the same way, plus a banner `Shelved by <name> on <date>: <reason>`.

## Scope

1. **Store.** `backend/arp/themes/dossiers.py`: one JSON file per dossier under `runs_dir/_dossiers/`, written
   atomically, like `arp/argus/flows.py`.
2. **API**, `/api/dossiers`, behind `authorize` (viewer reads, analyst writes):
   - `GET /api/dossiers` → `{items: [{dossier_id, name, status, origin, current_step, created_at}]}`, newest
     first; `current_step` is the first step (1–5) whose state is not `done` or `skipped`, or `null` when all
     built steps are done.
   - `POST /api/dossiers` `{name, taxonomy_id?}` → the dossier (origin `topic`); 404 when `taxonomy_id` is
     unknown; 422 when `name` is blank.
   - `GET /api/dossiers/{id}` → the dossier with `steps: [{number, title, state, detail, href}]`; 404
     `unknown dossier '<id>'`.
   - `PATCH /api/dossiers/{id}` `{taxonomy_id}` to attach a taxonomy, or `{status: "shelved", reason}` to shelve
     (reason required; shelving never deletes); 409 when the dossier already has a different `taxonomy_id`.
3. **Promote.** `POST /api/emerging-themes/runs/{run_id}/candidates/{theme_id}/promote` also creates a dossier
   (origin `candidate`, the new or extended `taxonomy_id`) and returns its `dossier_id`. Promoting the same
   candidate again returns the existing dossier, never a second one.
4. **Screens.**
   - `#/themes`: the list, a **New theme** form (name, optional taxonomy), and a **Show shelved** toggle.
   - `#/themes/<id>`: the dossier page: name, origin, and the five steps as a vertical stepper. Each step
     shows its title, state, detail and one action link: step 1 → the candidate in Emerging Themes; step 2 →
     the taxonomy in the Taxonomy Library (or **Choose a taxonomy** when none); step 4 → the newest run in the
     Thematic Universe, or **Find companies** opening `#/theme` with the taxonomy preselected; steps 3 and 5 no
     link. A **Shelve** action with a required reason.
   - The R&D Lab lists **Theme dossiers** (`#/themes`) among its screens, and gains the process **Research a
     theme** with the five steps, each pointing at the dossier list.
   - Emerging Themes shows **Open dossier** on a promoted candidate.

## Step titles (verbatim)

`Spot`, `Define`, `Research`, `Find companies`, `Position and standards`.

## My calls (owner to confirm with the acceptance table)

1. **Files, not Postgres**, following the Argus draft-flow precedent: a dossier is small and only links.
2. **One taxonomy per dossier.** Later versions of that taxonomy belong to the same dossier; a second taxonomy
   means a second dossier.
3. **The latest ratified version is the dossier's reference version.** No separate pin; the mismatch rule in
   step 4 makes drift visible.
4. **Steps 3 and 5 show as `not_built`** so the process is visible now and each later spec only changes its
   step's derivation.
5. **No approvals are stored in the dossier yet.** The two existing gates keep their own records (the candidate
   decision, the taxonomy ratification); the later specs add theirs.

## Constraints

- Repo checks: `ruff`, `pytest`, `npm run lint`, `npx tsc -b`, `npm test`; API contract regenerated and committed.
- No LLM call in this feature.

## Left to the builder

File layout inside `runs_dir/_dossiers/`, component structure, how the run list for a taxonomy is queried
(the run store already filters by run type), and the stepper's visual design within DESIGN.md.

## Acceptance

Fixture: an empty `runs_dir` and taxonomy store; a taxonomy `tax_a` with versions 1 (ratified by `ana`) and 2
(draft); helper functions in the test suite that add a theme run for a given taxonomy id, version, status and
number of open review items, and an Emerging Themes candidate with a given status.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | empty store | `POST /api/dossiers {"name": "Grid electrification"}` | 200; `dossier_id` matches `^dos_[0-9a-f]{12}$`; `origin` `topic`; `taxonomy_id` null; `status` `active` | holdout |
| AC-2 | AC-1's dossier | `GET /api/dossiers/{id}` | `steps` titles in order `Spot`, `Define`, `Research`, `Find companies`, `Position and standards`; states `skipped`, `not_started`, `not_built`, `not_started`, `not_built` | holdout |
| AC-3 | empty store | `POST /api/dossiers {"name": "  "}` | 422 | holdout |
| AC-4 | empty store | `POST /api/dossiers {"name": "X", "taxonomy_id": "tax_none"}` | 404 | holdout |
| AC-5 | dossier with `tax_a` | `GET /api/dossiers/{id}` | step 2 `done`, detail `v1 ratified by ana` | holdout |
| AC-6 | taxonomy `tax_b` with only a draft version, attached | `GET` | step 2 `waiting`, detail `ratify a version` | holdout |
| AC-7 | dossier with `tax_a`, no runs | `GET` | step 4 `not_started` | holdout |
| AC-8 | a running theme run for `tax_a` v1 | `GET` | step 4 `running` | holdout |
| AC-9 | newest run for `tax_a` v1 completed, 3 open review items | `GET` | step 4 `waiting`, detail `3 to review` | holdout |
| AC-10 | newest run for `tax_a` v1 completed with 12 companies, 0 open, and `tax_a` v3 ratified | `GET` | step 4 `waiting`, detail `12 companies, taxonomy v1 · older than v3` | holdout |
| AC-11 | newest run for `tax_a` v1 completed, 12 companies, 0 open, v1 the latest ratified | `GET` | step 4 `done`, detail `12 companies, taxonomy v1` | holdout |
| AC-12 | an older completed run and a newer failed run for `tax_a` | `GET` | step 4 `failed` | holdout |
| AC-13 | an Emerging Themes candidate | promote it | response carries `dossier_id`; `GET` that dossier: `origin` `candidate`, `taxonomy_id` the promoted taxonomy, step 1 `done` | holdout |
| AC-14 | AC-13 | promote the same candidate again | the same `dossier_id`; `GET /api/dossiers` lists it once | holdout |
| AC-15 | a dossier whose candidate file is gone | `GET` | step 1 `failed`, detail `candidate not found` | holdout |
| AC-16 | dossier with `tax_a` | `PATCH {"taxonomy_id": "tax_b"}` | 409 | holdout |
| AC-17 | a dossier | `PATCH {"status": "shelved"}` (no reason) | 422 | holdout |
| AC-18 | a dossier | `PATCH {"status": "shelved", "reason": "No data"}` | 200; `status` `shelved`; `shelve_reason` `No data`; the file still exists | holdout |
| AC-19 | dossiers created at t1 < t2 | `GET /api/dossiers` | items in order t2, t1 | holdout |
| AC-20 | AC-11's dossier | `GET /api/dossiers` | its `current_step` is `3` | holdout |
| AC-21 | unknown id | `GET /api/dossiers/dos_000000000000` | 404, `detail` `unknown dossier 'dos_000000000000'` | holdout |
| AC-22 | a viewer-role user | `POST /api/dossiers` | 403 | holdout |
| AC-23 | the running app | open `#/rdLab` | Screens list holds `Theme dossiers` → `#/themes`; Processes include `Research a theme` with steps `Spot`, `Define`, `Research`, `Find companies`, `Position and standards` | evaluator |
| AC-24 | `#/themes` | create "Grid electrification" | the page goes to `#/themes/<id>` and shows the five steps with the AC-2 states | evaluator |
| AC-25 | a dossier page with no taxonomy | read step 2 | it offers **Choose a taxonomy**; choosing one updates step 2 without a page reload | evaluator |
| AC-26 | AC-11's dossier page | read step 4 | it links to that run in the Thematic Universe | evaluator |
| AC-27 | a promoted candidate in Emerging Themes | read it | an **Open dossier** link to `#/themes/<id>` | evaluator |
| AC-28 | a shelved dossier | open it | the banner `Shelved by <name> on <date>: <reason>`; `#/themes` hides it until **Show shelved** is on | evaluator |

Must not change:
- AC-29: promoting, rejecting and disconfirming candidates still record their decision and reason exactly as
  before (the existing emerging-themes tests pass unchanged). Checked by: unit.
- AC-30: `POST /api/themes/runs` and the theme run results are unchanged (the existing theme tests pass
  unchanged). Checked by: unit.
