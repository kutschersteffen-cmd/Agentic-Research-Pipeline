# Theme dossier: one record and one page per theme

Status: draft, 2026-10-25 (revised after builder check and spec-critic).

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

- Every theme promoted or started after release has one dossier, reachable from the R&D Lab. No backfill:
  a theme promoted earlier gets one through **New theme** with its taxonomy attached.
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

- `dossier_id` (`dos_` + 12 hex), `name`, `created_by` (display name), `created_at` (ISO-8601 UTC);
- `origin`: `candidate` (with `run_id`, `theme_id` of the Emerging Themes candidate) or `topic`;
- `taxonomy_id` (nullable until a taxonomy exists);
- `status`: `active` or `shelved`, with `shelved_by` (display name), `shelved_at` (ISO-8601 UTC),
  `shelve_reason` when shelved.

A taxonomy belongs to at most one dossier, active or shelved. Nothing else is stored. Taxonomy versions, runs and review items are found from `taxonomy_id`.

## Step states (derived on read)

Each step has a `state` and a `detail` line. States: `done`, `waiting` (on a person), `running`, `failed`,
`not_started`, `skipped`, `not_built`.

1. **Spot.** Origin `topic` → `skipped`, detail `started from a topic`. Origin `candidate`, by the candidate's
   status: `promoted` → `done`, detail `promoted: <decision reason>`; `under_review` or `candidate` → `waiting`,
   detail `awaiting decision`; `rejected` or `disconfirmed` → `failed`, detail `<status>: <decision reason>`;
   candidate missing → `failed`, detail `candidate not found`.
2. **Define.** No `taxonomy_id` → `not_started`, detail `choose a taxonomy`. Taxonomy missing from the store →
   `failed`, detail `taxonomy not found`. No ratified version → `waiting`, detail `ratify a version`. Otherwise
   `done`, detail `v<n> ratified by <name>` for the latest ratified version.
3. **Research.** Always `not_built`, detail `coming next`.
4. **Find companies.** Only theme runs whose manifest params have `taxonomy_id` equal to the dossier's count
   (the Thematic Universe sets it only when the theme came unedited from the taxonomy, together with
   `taxonomy_version`). None → `not_started`, detail `no run yet`. Otherwise the newest by `created_at`, by its
   status:
   - `pending` or `running` → `running`, detail `run in progress`;
   - `failed` or `cancelled` → `failed`, detail `last run <status>`;
   - `completed` or `partially_completed`: let `n` = open review items (the length of `pending` in
     `GET /api/themes/runs/{run_id}/review-queue`, which already leaves out `isic:` items), `c` = companies with
     at least one entry in `company_matches` in the run results, `m` = the run's `taxonomy_version`, `L` = the
     latest ratified version.
     - `n > 0` → `waiting`, detail `<n> to review`;
     - `n = 0` → `done`, detail `<c> companies, taxonomy v<m>`;
     - in both cases, when `L` exists and `m < L`, the detail gains ` · older than v<L>` and the state is
       `waiting`. A run on a draft version newer than `L` gets no suffix.

`href` per step (hash routes; `null` means no link): step 1 `#/emergingThemes` (origin `candidate`) else
`null`; step 2 `#/taxonomy` when a taxonomy is attached, else `null` (the page shows **Choose a taxonomy**);
step 3 `null`; step 4 `#/theme/<run_id>` for the newest counted run, else `#/theme`; step 5 `null`.

A shelved dossier shows its steps the same way, plus a banner `Shelved by <name> on <YYYY-MM-DD>: <reason>`.

On screen the states read `Done`, `Waiting`, `Running`, `Failed`, `Not started`, `Skipped`, `Coming later`
(for `not_built`).

## Scope

1. **Store.** `backend/arp/themes/dossiers.py`: one JSON file per dossier under `runs_dir/_dossiers/`, written
   atomically, like `arp/argus/flows.py`.
2. **API**, `/api/dossiers`, behind `authorize` (viewer reads, analyst writes):
   - `GET /api/dossiers` → `{items: [{dossier_id, name, status, origin, current_step, created_at}]}`, all
     dossiers including shelved, newest `created_at` first, ties by `dossier_id`; `current_step` is the first step
     (1–5) whose state is not `done`, `skipped` or `not_built`, or `null` when there is none.
   - `POST /api/dossiers` `{name, taxonomy_id?}` → 200 and the dossier (origin `topic`); 404 when `taxonomy_id`
     is unknown; 409 `taxonomy '<tid>' already belongs to dossier '<did>'` when another dossier has it; 422
     when `name` is blank or whitespace.
   - `GET /api/dossiers/{id}` → the dossier with `steps: [{number, title, state, detail, href}]`; 404
     `unknown dossier '<id>'`.
   - `PATCH /api/dossiers/{id}` `{taxonomy_id}` to attach a taxonomy, or `{status: "shelved", reason}` to shelve
     (shelving never deletes). Attach: 200; the same id again is a no-op 200; 404 for an unknown taxonomy;
     409 when the dossier already has a different `taxonomy_id`, or another dossier has this one. Shelve: 422
     when `reason` is missing, blank or whitespace. 404 `unknown dossier '<id>'` for an unknown dossier.
3. **Promote.** `POST /api/emerging-themes/runs/{run_id}/candidates/{theme_id}/promote` also creates a dossier
   (origin `candidate`, the new or extended `taxonomy_id`) and adds `dossier_id` to its response. When that
   taxonomy already belongs to a dossier (promoting into an existing taxonomy), no dossier is created and
   `dossier_id` is that dossier's. Promoting an already-promoted candidate stays a 400, as today. Reject and
   disconfirm create no dossier.
4. **Screens.**
   - `#/themes`: the list, a **New theme** form (name, optional taxonomy), and a **Show shelved** toggle, off
     by default.
   - `#/themes/<id>`: the dossier page: name, origin, and the five steps as a vertical stepper. Each step
     shows its title, state label, detail and the step's `href` as a link (step 4's reads **Find companies**
     when there is no run; it opens `#/theme` with the taxonomy preselected). Step 2 with no taxonomy offers
     **Choose a taxonomy**, which attaches one in place. A **Shelve** action with a required reason.
   - The R&D Lab lists **Theme dossiers** (`#/themes`) among its screens, and gains the process **Research a
     theme** with the five steps, each pointing at the dossier list.
   - Emerging Themes shows **Open dossier** on a candidate when a dossier with that candidate as origin
     exists, and nothing otherwise.

## Step titles (verbatim)

`Spot`, `Define`, `Research`, `Find companies`, `Position and standards`.

## My calls (owner to confirm with the acceptance table)

1. **Files, not Postgres**, following the Argus draft-flow precedent: a dossier is small and only links.
2. **One taxonomy per dossier, one dossier per taxonomy.** Later versions belong to the same dossier; a
   second taxonomy means a second dossier. Promoting into a taxonomy that already has a dossier reuses it.
3. **The latest ratified version is the dossier's reference version.** No separate pin; the mismatch rule in
   step 4 makes drift visible.
4. **Steps 3 and 5 show as `not_built`** so the process is visible now and each later spec only changes its
   step's derivation.
5. **Repeat promote stays a 400 and there is no backfill**, so existing emerging-themes behaviour is untouched.
6. **`current_step` skips `not_built` steps**, so the list points at real work (step 4 after Define) until
   steps 3 and 5 exist.
7. **No approvals are stored in the dossier yet.** The two existing gates keep their own records (the candidate
   decision, the taxonomy ratification); the later specs add theirs.

## Constraints

- Repo checks: `ruff`, `pytest`, `npm run lint`, `npx tsc -b`, `npm test`; API contract regenerated and committed.
- No LLM call in this feature.

## Left to the builder

File layout inside `runs_dir/_dossiers/`, component structure, how the run list for a taxonomy is queried
(the run store already filters by run type), and the stepper's visual design within DESIGN.md.

## Acceptance

Fixture, seeded through the backend's own stores (no test-suite helpers): an empty `runs_dir` and taxonomy
store; taxonomy `tax_a` with version 1 ratified by `ana` and version 2 draft (`TaxonomyStore`); taxonomy `tax_b`
with only a draft version. Theme runs are made with `create_theme_run(..., taxonomy_id=, taxonomy_version=)`
and their status set through the run store; results rows carry `company_matches`; open review items are
pending items in the run's review queue. Candidates come from an Emerging Themes run in the store. Users `ana`
(analyst) and `vic` (viewer).

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | empty store | `POST /api/dossiers {"name": "Grid electrification"}` | 200; `dossier_id` matches `^dos_[0-9a-f]{12}$`; `origin` `topic`; `taxonomy_id` null; `status` `active` | holdout |
| AC-2 | AC-1's dossier | `GET /api/dossiers/{id}` | `steps` titles in order `Spot`, `Define`, `Research`, `Find companies`, `Position and standards`; states `skipped`, `not_started`, `not_built`, `not_started`, `not_built`; `href` of steps 1, 2, 3, 5 null, step 4 `#/theme` | holdout |
| AC-3 | empty store | `POST /api/dossiers` with `{"name": "  "}` | 422 | holdout |
| AC-4 | empty store | `POST /api/dossiers {"name": "X", "taxonomy_id": "tax_none"}` | 404 | holdout |
| AC-5 | dossier with `tax_a` | `GET` | step 2 `done`, detail `v1 ratified by ana`, `href` `#/taxonomy` | holdout |
| AC-6 | dossier with `tax_b` | `GET` | step 2 `waiting`, detail `ratify a version` | holdout |
| AC-7 | dossier with `tax_a`, no runs | `GET` | step 4 `not_started`, detail `no run yet` | holdout |
| AC-8 | dossier with `tax_a`; newest run for `tax_a` v1 `running` | `GET` | step 4 `running`, detail `run in progress` | holdout |
| AC-9 | newest run for `tax_a` v1 `completed`, 3 pending review items | `GET` | step 4 `waiting`, detail `3 to review` | holdout |
| AC-10 | newest run for `tax_a` v1 `completed`, 12 companies with matches, 0 pending; `tax_a` v3 ratified by `bob` | `GET` | step 4 `waiting`, detail `12 companies, taxonomy v1 · older than v3` | holdout |
| AC-11 | newest run for `tax_a` v1 `partially_completed`, 12 companies with matches, 0 pending; v1 the latest ratified | `GET` | step 4 `done`, detail `12 companies, taxonomy v1`, `href` `#/theme/<run_id>` | holdout |
| AC-12 | an older `completed` run and a newer `cancelled` run for `tax_a` | `GET` | step 4 `failed`, detail `last run cancelled` | holdout |
| AC-13 | newest run for `tax_a` v1 `completed`, 2 pending; `tax_a` v3 ratified | `GET` | step 4 `waiting`, detail `2 to review · older than v3` | holdout |
| AC-14 | a theme run with `taxonomy_id` null, and a run for `tax_b` | `GET` a dossier with `tax_a` | step 4 `not_started` | holdout |
| AC-15 | an Emerging Themes candidate | promote it | 200; body has the old keys plus `dossier_id`; `GET` that dossier: `origin` `candidate` with the candidate's `run_id` and `theme_id`; `taxonomy_id` equal to the promoted taxonomy id; step 1 `done`, detail `promoted: <reason sent>` | holdout |
| AC-16 | AC-15 | promote the same candidate again | 400 as before; `GET /api/dossiers` lists one dossier | holdout |
| AC-17 | AC-15's dossier, then a second candidate promoted into the same taxonomy | promote | 200; `dossier_id` equals AC-15's; `GET /api/dossiers` lists one dossier | holdout |
| AC-18 | a candidate | reject it; disconfirm another | responses as before; `GET /api/dossiers` empty | holdout |
| AC-19 | a dossier whose candidate was removed from the store | `GET` | step 1 `failed`, detail `candidate not found` | holdout |
| AC-20 | a dossier whose taxonomy was removed from the store | `GET` | step 2 `failed`, detail `taxonomy not found` | holdout |
| AC-21 | dossier with no taxonomy | `PATCH {"taxonomy_id": "tax_a"}`; then the same again | both 200, `taxonomy_id` `tax_a` | holdout |
| AC-22 | dossier with `tax_a` | `PATCH {"taxonomy_id": "tax_b"}` | 409 | holdout |
| AC-23 | dossier D1 with `tax_a`; dossier D2 without | `PATCH` D2 `{"taxonomy_id": "tax_a"}`; `POST {"name": "Y", "taxonomy_id": "tax_a"}` | both 409, detail `taxonomy 'tax_a' already belongs to dossier '<D1 id>'` | holdout |
| AC-24 | a dossier | `PATCH {"taxonomy_id": "tax_none"}` | 404 | holdout |
| AC-25 | a dossier | `PATCH {"status": "shelved"}`; `PATCH {"status": "shelved", "reason": "  "}` | both 422 | holdout |
| AC-26 | a dossier, caller `ana` | `PATCH {"status": "shelved", "reason": "No data"}` | 200; `status` `shelved`; `shelve_reason` `No data`; `shelved_by` `ana`; `shelved_at` an ISO-8601 timestamp; `GET` it still 200 with five steps; `GET /api/dossiers` lists it with `status` `shelved` | holdout |
| AC-27 | dossiers A (`created_at` `2026-01-01T00:00:00Z`) and B (`2026-01-02T00:00:00Z`) | `GET /api/dossiers` | B then A | holdout |
| AC-28 | AC-11's dossier | `GET /api/dossiers` | its `current_step` is `null`; AC-7's dossier has `4`; AC-1's has `2` | holdout |
| AC-29 | unknown id | `GET` and `PATCH /api/dossiers/dos_000000000000` | 404, `detail` `unknown dossier 'dos_000000000000'` | holdout |
| AC-30 | caller `vic` | `GET /api/dossiers`, `GET` one; `POST`, `PATCH` | 200, 200; 403, 403 | holdout |
| AC-31 | dossier with `tax_a`, step 2 `v1 ratified by ana` | ratify `tax_a` v2 as `bob`, no PATCH | `GET` shows step 2 detail `v2 ratified by bob` | holdout |
| AC-32 | the running app | open `#/rdLab` | Screens holds `Theme dossiers` linking to `#/themes` | evaluator |
| AC-33 | the running app | open `#/rdLab` | Processes include `Research a theme` with steps `Spot`, `Define`, `Research`, `Find companies`, `Position and standards` in order, each linking to `#/themes` | evaluator |
| AC-34 | `#/themes` | create "Grid electrification" | the URL becomes `#/themes/<id>`; the steps read `Skipped`, `Not started`, `Coming later`, `Not started`, `Coming later` | evaluator |
| AC-35 | a dossier page with no taxonomy | choose `tax_a` under **Choose a taxonomy** | step 2 reads `Done` and `v1 ratified by ana`; the URL is unchanged and the page did not reload | evaluator |
| AC-36 | AC-11's dossier page | click step 4's link | the Thematic Universe opens that run (`#/theme/<run_id>`) | evaluator |
| AC-37 | Emerging Themes with AC-15's promoted candidate, an earlier-promoted candidate with no dossier, and an unpromoted one | read them | only AC-15's shows **Open dossier**, linking to `#/themes/<id>` | evaluator |
| AC-38 | a dossier shelved by `ana` on 2026-10-25 with reason `No data` | open it | banner `Shelved by ana on 2026-10-25: No data` | evaluator |
| AC-39 | AC-38 | open `#/themes` | the dossier is absent; after turning **Show shelved** on it is listed | evaluator |

Must not change:
- AC-40: `POST /api/themes/runs` returns the same status codes and body keys as before, with no dossier fields.
  Checked by: holdout.
- AC-41: taxonomy draft, new-version and ratify endpoints return the same status codes and bodies as before.
  Checked by: holdout.
- AC-42: `#/rdLab` still lists the process `Launch a thematic product` with its steps unchanged. Checked by:
  evaluator.
