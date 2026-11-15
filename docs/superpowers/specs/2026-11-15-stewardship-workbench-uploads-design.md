# Workbench uploads: extra information per company from an Excel or CSV file, as columns and in the side panel

Slug: `stewardship-workbench-uploads`. Risk: normal (an add-only log under `stewardship_streams_dir`, no migration, no
new table, nothing deleted; withdrawing an upload is a new event, not a delete). Size M, 3 PRs. Spec 2b of the
prioritisation workbench; the overlap view is spec 2a (`stewardship-workbench-overlap`).

Status: **draft for the owner's approval.**

Where it comes from: `2026-11-13-stewardship-priority-worklist-design.md`, Non-goals: "uploading extra per-company
information ('Information per company like Feedback or so', owner, 13 Nov 2026)". Owner on 13 Nov 2026: "a proper
workbench for the analyst. Which allows not only filtering but also uploading additional data and also manually adding
comments and remarks." Comments exist (notes, spec 1); this spec adds the uploads.

Owner decisions (15 Nov 2026, buttons in the spec session):

1. **Free columns:** one row per company (company id or ISIN), every other column is a field (e.g. `Feedback`,
   `Internal rating`). A column with only numbers is a number field (sortable, filterable as a number); the rest is
   text. A downloadable template shows the layout. No set-up step.
2. **Withdraw, keep history:** an analyst can withdraw an upload; its values leave the Workbench, but its rows and who
   withdrew it when stay on record. Nothing is deleted. A newer upload of the same field shows the newer value.
3. **Columns only:** uploaded fields are columns, filters and a side-panel tab. They never count towards the priority
   score.
4. **After the showcase:** built after the overlap view (spec 2a) and after the 27 Nov 2026 showcase.

## Why

Analysts hold information about companies that the app does not have: feedback from a call, an internal rating, a
sector team's view, a client's flag. Today it lives in spreadsheets beside the Workbench. Uploading it puts it next to
the stored indicators, so the analyst can sort and filter on it when picking companies, and a colleague opening the
side panel sees it with its source file, author and date.

## Goals

1. `GET /api/stewardship/uploads/template`: an xlsx template.
2. `POST /api/stewardship/uploads` (analyst): an `.xlsx` or `.csv` file becomes one upload; every row is checked, and
   one bad row rejects the whole file with a report of every problem, as the stewardship intake does.
3. `GET /api/stewardship/uploads`, `GET /api/stewardship/uploads/{batch_id}`,
   `POST /api/stewardship/uploads/{batch_id}/withdraw`: list, read and withdraw uploads.
4. Worklist rows carry the current uploaded values (`extra`), and the response lists the fields (`extra_fields`).
5. The Workbench shows each field as a column tagged `Uploaded`, offers it in **Add filter ▾** with the control of its
   type, has a section **Uploaded data** to upload and withdraw, and the side panel gets a tab **Uploaded**.

## Non-goals

- Attachments (PDFs, images, any binary file stored per company).
- Deleting or editing an upload or a value. A mistake is fixed by a newer upload or by withdrawing the upload.
- Uploaded fields in the priority score, the weights editor or the `Why is this here` panel.
- A list of allowed fields, field types set by hand, units, or lists of allowed values.
- Values per date (a time series): a company has one current value per field.
- Uploading for companies outside the house universe; creating companies.
- A JSON (non-file) upload route; uploads by API key or schedule.
- Free-text feedback as such: notes stay the place for comments (spec 1).

## Anti-goals

- A half-written upload: a file with one rejected cell writes nothing.
- An uploaded value read as a stored or computed one: every uploaded column header and side-panel value says
  `Uploaded`, with the file name, the uploader and the date one hover or click away.
- Lost history: withdrawing hides values but keeps the file's rows and the withdrawal on record.
- A parser that an untrusted file can exhaust: file size, row and column caps apply before any value is kept.

## Constraints

- Store: append-only JSONL under `<stewardship_streams_dir>/uploads/` like `notes.py`: `batches.jsonl` with events
  `uploaded` (`batch_id`, `file_name`, `by`, `at`, `fields`, `companies`) and `withdrawn` (`batch_id`, `by`, `at`,
  `reason`), and one file `values/<batch_id>.jsonl` per upload, one line per company (`company_id`, `as_of`,
  `values`: field → value). No route rewrites or removes a line. No migration, no table, no change to
  `postgres_schema.py`. An upload writes `values/<batch_id>.jsonl` first, then the `uploaded` event; a values file
  without an `uploaded` event is ignored. Uploads and withdrawals run one at a time (one lock, as `SelectionLog`'s
  `_LOCK`), so two uploads cannot both set the type of the same new field.
- Reading: `read_workbook`'s approach in `arp/stewardship/intake_excel.py` (openpyxl `read_only=True,
  data_only=True`, headers from row 1), and the `Rejection` model and 422-with-the-same-body
  reply of `stewardship_intake.py`. Blocking parsing runs in the thread pool, as `_upload` there.
- Companies resolve against `house_universe()` issuer ids, as notes do: `company_id` must be one; an `isin` (spaces
  removed, upper case) resolves through `house_isins()`, else to `isin_<ISIN>` when that is a house issuer id.
- Reads need `viewer`, uploads and withdrawals `analyst` (router-level `authorize`). The uploader and withdrawer are
  the signed-in user's `name` (`Principal.name`), as notes record it. Dates and times are UTC; "today" is the
  current UTC date, `YYYY-MM-DD`.
- Request and response models change in PRs 1 and 2: `scripts/export_openapi.py` and `npm run gen:api` in each, both
  generated files committed; each new `request<T>()` gets a line in `frontend/src/api/contract.ts`.
- `DESIGN.md` ("The Annotated Report"): uploaded values are ink, the `Uploaded` tag is neutral (provenance, not
  status), amber only for something waiting on a person (nothing in this spec). PR 3 is checked with impeccable and
  ui-ux-pro-max and carries a Playwright screenshot of `#/stewardship/workbench` with an upload's column and the
  **Uploaded** tab open.
- "LLM plans, code computes": no model reads or maps the file.

## Approaches considered

1. **One row per company, free columns, add-only JSONL log (picked).** Matches how analysts keep such sheets, needs no
   set-up, and reuses the notes and intake patterns. Types are detected per column.
2. Long format (company, field, value, date per row). Allows a date per value, but nobody keeps a spreadsheet that
   way; it would need a pivot before every upload.
3. A fields registry the owner fills first (owner decision 1 picked free columns instead). Tidier types, one more
   screen and a set-up step.
4. A Postgres table per upload or a values table. Queryable, but a schema change makes the risk high; the JSONL log is
   enough at 2,581 companies.

## The file

- **Order of checks:** the file name ending first, then the size, then the content.
- **Formats:** `.xlsx` (the first worksheet) or `.csv` (UTF-8, a byte-order mark is allowed). Any other file name
  ending (any case): 422 `Upload a .xlsx or .csv file`. A `.xlsx` openpyxl cannot read: 422 with the rejection `not a valid xlsx
  workbook`. CSV delimiter: `;` if the header line holds more `;` than `,`, else `,`.
- **Header row 1.** Reserved headers, any case: `company_id`, `isin`, `as_of`. Every other non-empty header is a
  **field**, its name trimmed, 1 to 60 characters. At least one of `company_id` and `isin` is required. Two headers
  equal in any case are a rejection.
- **Rows 2 onward,** one per company; an entirely empty row is skipped.
- **Caps (before any value is kept):** file over 5,000,000 bytes → 413 `File is larger than the 5 MB upload limit.`
  (a constant of the uploads module, separate from the `max_upload_bytes` setting); more than 30 fields (non-empty,
  non-reserved headers, counted before empty columns are dropped) or more than 5,000 data rows (counted after entirely
  empty rows are skipped) → that one rejection only, and nothing else is checked; a text value over 2,000 characters → a
  rejection (below).
- **Company:** `company_id` if filled, else `isin`; when both are filled they must name the same company. When both
  are filled and the `isin` does not resolve, the row gets only `company_id and isin name different companies`.
- **`as_of`:** a date (Excel date cell, or `YYYY-MM-DD` text); empty means the upload date (UTC). It is shown, not used
  to order values.
- **Values:** an empty cell gives no value (it does not clear an older value). An Excel number cell, or CSV text that
  is a decimal number (`.` as decimal point; with the `;` delimiter, `,` also accepted; no thousands separators), is a
  number, a whole one stored as an integer (`4`, not `4.0`); anything else is text, trimmed. Excel dates in a field
  become `YYYY-MM-DD`, booleans `TRUE` / `FALSE`. (`intake_excel._cell` turns numbers into text, so it is not reused
  for field cells.)
- **A header whose column has no value in any row is ignored**: it is not a field of this upload.
- **Field type and spelling:** field names are compared in any case everywhere. A field already known (in any upload
  not withdrawn) keeps its type and spelling: a `number` field rejects a text value; a `text` field stores a number as
  text (`4`, `3.5`). The upload's values are stored and returned under that known spelling. A new field is `number`
  when every value in its column is a number, else `text`. A field's type and spelling are those of the oldest upload
  not withdrawn that has it, so withdrawing that upload can change them.

Rejections reuse `Rejection` (`sheet`: the worksheet name for xlsx, `""` for csv; `row`: worksheet row, header = 1;
`field`: the header; `reason`):

| Problem | row | field | reason |
|---|---|---|---|
| no company column | 1 | `""` | `needs a company_id or isin column` |
| header twice | 1 | the header | `column <header> appears twice` |
| field name over 60 characters | 1 | the header | `a field name has at most 60 characters` |
| more than 30 fields | 1 | `""` | `at most 30 fields` |
| more than 5,000 data rows | 0 | `""` | `at most 5,000 rows` |
| no company in the row | n | `company_id` | `missing company` |
| company not in the house universe | n | `company_id` or `isin` | `unknown company <value>` |
| `company_id` and `isin` differ | n | `isin` | `company_id and isin name different companies` |
| company twice in the file | n (the later row) | `company_id` | `company <id> appears twice` |
| bad `as_of` | n | `as_of` | `as_of is not a date` |
| text in a number field | n | the field | `<field> is a number field` |
| text over 2,000 characters | n | the field | `at most 2,000 characters` |

## API

- `GET /api/stewardship/uploads/template` (viewer): an xlsx, `Content-Disposition: attachment;
  filename=workbench_upload_template.xlsx`, one worksheet `Upload` whose row 1 is `company_id`, `isin`, `as_of`,
  `Feedback`, `Internal rating` and row 2 an example (`isin_US0378331005`, empty, empty, `Constructive call`, `3`).
- `POST /api/stewardship/uploads` (analyst, multipart `file`): 200 with the upload
  `{"batch_id": "upl_…", "file_name": "...", "by": "...", "at": "...", "status": "active", "companies": n,
  "fields": [{"name": "Feedback", "type": "text"}, …], "withdrawn_by": null, "withdrawn_at": null,
  "withdraw_reason": null, "rejected": []}`; or 422 with the same shape, `batch_id` `null` and every rejection, and
  nothing written. `fields` are the file's fields in column order with their (possibly existing) type and spelling.
- `GET /api/stewardship/uploads` (viewer): `{"uploads": [<upload without rejected>, …]}`, newest first by position in
  `batches.jsonl`, withdrawn ones included.
- `at` and `withdrawn_at` are UTC ISO 8601 strings, `YYYY-MM-DDTHH:MM:SSZ`.
- `GET /api/stewardship/uploads/{batch_id}` (viewer): the upload and `rows: [{"company_id", "company", "as_of",
  "values": {field: value}}]` in file order, also for a withdrawn upload. Unknown id: 404.
- `POST /api/stewardship/uploads/{batch_id}/withdraw` (analyst) `{"reason": "..."}`: 200 with the upload, `status`
  `withdrawn`. Reason trimmed, 1 to 500 characters, else 422 `Withdrawing an upload needs a reason`. Already withdrawn:
  422 `upload <batch_id> is already withdrawn`. Unknown id: 404.
- **Worklist** (`GET /api/stewardship/worklist`, every scope): the response gains `extra_fields: [{"name", "type",
  "companies"}]` (fields of uploads not withdrawn, in order of first appearance: oldest upload first, then column
  order; `companies` = rows with a current value in this scope), and each row gains `extra: {field: {"value", "as_of",
  "batch_id"}}` with the company's current value per field: from the newest upload not withdrawn that has a value for
  it (newest = last appended). A row without values has `extra` `{}`. Nothing else in the row changes; `score` and
  `parts` never read `extra`.

## Screen

**Uploaded data** is a collapsible section of the Workbench below the table, next to **▸ Weights**:

```
▾ Uploaded data
  Extra information per company from your own Excel or CSV file. One row per company (company_id or ISIN);
  every other column becomes a column of the table. Uploaded values never change the priority score.
  [ Download template ]  [ Choose file… ]  [ Upload ]

  ✕ Nothing was saved. Fix these 2 rows and upload the file again.
    Row  Column           Problem
    7    isin             unknown company DE000XXXXXXX
    12   Internal rating  Internal rating is a number field

  File                         Uploaded by      When               Companies  Fields                    Status
  q4_feedback.xlsx             A. Analyst       20 Nov 2026 14:02  212        Feedback, Internal rating Active     [ Withdraw ]
  sector_view.csv              B. Analyst       18 Nov 2026 09:15  80         Sector view               Withdrawn 19 Nov by A. Analyst: wrong quarter
```

- A successful upload shows `Saved: <n> companies, <k> fields.` (`1 company`, `1 field` in the singular) and the
  table refetches.
- **Withdraw** opens a dialog: `Withdraw <file>? Its values leave the table; the file stays on record. Reason:` with a
  required text box, **Withdraw** and **Cancel**. Viewers see the list without buttons.
- **Columns:** each field of `extra_fields` is a column after the indicator columns, header `<name> · Uploaded`, shown
  by default and hideable in **Columns ▾**. Number fields sort as numbers, text fields case-insensitively; empty last.
  Hovering a cell shows `<file name> · <uploader> · <uploaded date> · as of <as_of>` (from `GET /uploads`).
- **Filters:** **Add filter ▾** lists each field labelled `<name> · Uploaded`: a `number` field gets the range slider,
  a `text` field the contains box (spec 1's filter builder types), with **Include empty** as for every filter.
- **Side panel:** a tab **Uploaded** after **Notes**: one line per field with a value: Field, Value, As of, File,
  Uploaded by, When. Empty: `No uploaded data for this company.`

## PR split

1. **Backend uploads (can start after the showcase; touches no worklist file):** the parser, caps and rejections, the
   log, the template, the four routes, unit tests, openapi and `gen:api`.
2. **Backend worklist fields (waits for PR 1 and for every open PR of the #491 series that changes
   `worklist.py` or `arp/schemas/worklist.py`):** `extra` and `extra_fields` in `worklist.build()` and the worklist
   schema, openapi and `gen:api`.
3. **Workbench screen (waits for PR 2 and for #491's follow-ups: filter builder, side panel):** the section, the
   columns, the filter entries, the side-panel tab. Screenshot, impeccable audit.

## Left to the builder

- How the log is folded per request (it is small: 2,581 companies × 30 fields), within AC-40's budget.
- How a CSV is decoded when it is not UTF-8: reject it as `not a valid csv file` (row 0) rather than guess.
- Number display (as uploaded, at most 4 decimals), column widths, the section's position if **Weights** moved.

## Acceptance

Holdout rows run on the e2e stack with `ARP_ENGAGEMENT_STORE=postgres`. Words used below:

- **Fixture W:** as in `stewardship-priority-worklist`: house universe `sample` (`SYN01`..`SYN12`), plus the
  `uploads/` directory under `stewardship_streams_dir` removed.
- **Upload(text):** `POST /api/stewardship/uploads` with a multipart `file` named `t.csv` whose content is `text`
  (lines separated by `\n`), signed in as an analyst.
- **F1** = Upload(`company_id,Feedback,Internal rating\nSYN01,Constructive call,3\nSYN02,No reply,1`).
- **Showcase data:** as in `stewardship-workbench-overlap`; **C** = the `issuer_id` and **I** = the `identifier` of the
  first row of `GET /api/stewardship/worklist` whose `issuer_id` starts with `isin_`.
- **Today:** the current UTC date, `YYYY-MM-DD`. "The signed-in user" is the analyst's `name`.
- PR tags: a row whose Given starts `PR n;` applies from that PR on; a row whose Given names another row applies from
  that row's PR on (e.g. a Given `AC-34` applies from PR 3); the others from PR 1.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Fixture W | `GET /api/stewardship/uploads/template` | Status 200, content type `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, worksheet `Upload` row 1 = `company_id`, `isin`, `as_of`, `Feedback`, `Internal rating` | holdout |
| AC-2 | Fixture W | F1 | Status 200; `status` `active`, `companies` 2, `fields` = `[{"name": "Feedback", "type": "text"}, {"name": "Internal rating", "type": "number"}]`, `rejected` `[]`, `by` = the signed-in user | holdout |
| AC-3 | AC-2 | `GET /api/stewardship/uploads/<batch_id>` | `rows` = `[{"company_id": "SYN01", "as_of": <today>, "values": {"Feedback": "Constructive call", "Internal rating": 3}, …}, {"company_id": "SYN02", …, "values": {"Feedback": "No reply", "Internal rating": 1}}]` (with each `company` name) | holdout |
| AC-4 | PR 2; AC-2 | `GET /api/stewardship/worklist` | `extra_fields` = `[{"name": "Feedback", "type": "text", "companies": 2}, {"name": "Internal rating", "type": "number", "companies": 2}]` | holdout |
| AC-5 | PR 2; AC-2 | `GET /api/stewardship/worklist` | `SYN01`'s `extra` = `{"Feedback": {"value": "Constructive call", "as_of": <today>, "batch_id": <F1's>}, "Internal rating": {"value": 3, "as_of": <today>, "batch_id": <F1's>}}`; `SYN03`'s `extra` = `{}` | holdout |
| AC-6 | PR 2; AC-2, then Upload(`company_id,internal rating,Feedback\nSYN01,5,`) | `GET /api/stewardship/worklist` | `SYN01`'s `Internal rating` value is 5 with the second upload's `batch_id` | holdout |
| AC-58 | AC-6 | `GET /api/stewardship/worklist` | `SYN01`'s `Feedback` stays `Constructive call` with F1's `batch_id` (an empty cell clears nothing) | holdout |
| AC-59 | AC-6 | `GET /api/stewardship/worklist` | `extra_fields` names the field `Internal rating` (F1's spelling), not `internal rating` | holdout |
| AC-43 | AC-2, then Upload(`company_id,internal rating,Feedback\nSYN01,5,`) | the upload's reply | `fields` = `[{"name": "Internal rating", "type": "number"}]` (the empty `Feedback` column is ignored) | holdout |
| AC-60 | AC-43 | `GET /api/stewardship/uploads/<its batch_id>` | The row's `values` = `{"Internal rating": 5}` | holdout |
| AC-7 | AC-43 | `POST /api/stewardship/uploads/<second batch_id>/withdraw` `{"reason": "wrong file"}` | Status 200 with `status` `withdrawn`, `withdraw_reason` `wrong file`, `withdrawn_by` = the signed-in user, `withdrawn_at` starting with today | holdout |
| AC-44 | PR 2; AC-7 | `GET /api/stewardship/worklist` | `SYN01`'s `Internal rating` is 3 again with F1's `batch_id` | holdout |
| AC-8 | AC-7 | `GET /api/stewardship/uploads` | Two uploads, the second one first; it has `status` `withdrawn` and `companies` 1 | holdout |
| AC-45 | AC-7 | `GET /api/stewardship/uploads/<second batch_id>` | Status 200 with its one row, `SYN01`, `values` `{"Internal rating": 5}` | holdout |
| AC-46 | Fixture W | `GET /api/stewardship/uploads/upl_nope` | Status 404 | holdout |
| AC-47 | AC-2, then `POST /uploads/<F1's batch_id>/withdraw` `{"reason": "x"}` | Upload(`company_id,Internal rating\nSYN03,high`) | Status 200 with `fields` = `[{"name": "Internal rating", "type": "text"}]` (no upload left that made it a number) | holdout |
| AC-48 | Fixture W | Upload(`company_id,Feedback\n,a`) | Status 422; one rejection, row 2, field `company_id`, reason `missing company` | holdout |
| AC-9 | AC-7 | the same withdraw again | Status 422 with detail `upload <batch_id> is already withdrawn` | holdout |
| AC-10 | AC-2 | `POST /uploads/<batch_id>/withdraw` `{"reason": "  "}` | Status 422 with detail `Withdrawing an upload needs a reason` | holdout |
| AC-11 | Fixture W | `POST /api/stewardship/uploads/upl_nope/withdraw` `{"reason": "x"}` | Status 404 | holdout |
| AC-12 | Fixture W | Upload(`company_id,Feedback\nSYN01,ok\nSYN99,bad`) | Status 422; `rejected` = `[{"sheet": "", "row": 3, "field": "company_id", "reason": "unknown company SYN99"}]`; `batch_id` `null` | holdout |
| AC-13 | AC-12 | `GET /api/stewardship/uploads` | `uploads` is `[]` (nothing written) | holdout |
| AC-14 | Fixture W | Upload(`company_id,Feedback\nSYN01,a\nSYN01,b`) | Status 422; one rejection, row 3, field `company_id`, reason `company SYN01 appears twice` | holdout |
| AC-15 | Fixture W | Upload(`name,Feedback\nApple,a`) | Status 422; one rejection, row 1, field `""`, reason `needs a company_id or isin column` | holdout |
| AC-16 | Fixture W | Upload(`company_id,Feedback,feedback\nSYN01,a,b`) | Status 422; one rejection, row 1, field `feedback`, reason `column feedback appears twice` | holdout |
| AC-17 | AC-2 | Upload(`company_id,Internal rating\nSYN03,high`) | Status 422; one rejection, row 2, field `Internal rating`, reason `Internal rating is a number field` | holdout |
| AC-18 | AC-2 | Upload(`company_id,Feedback\nSYN03,42`) | Status 200; `GET /uploads/<batch_id>` row `SYN03` has `Feedback` = `"42"` (text) | holdout |
| AC-19 | Fixture W | Upload(`company_id,as_of,Feedback\nSYN01,2026-11-01,a\nSYN02,1 Nov,b`) | Status 422; one rejection, row 3, field `as_of`, reason `as_of is not a date` | holdout |
| AC-20 | Fixture W | Upload(`company_id,as_of,Feedback\nSYN01,2026-11-01,a`) | Status 200; `GET /uploads/<batch_id>` row `SYN01` has `as_of` `2026-11-01` | holdout |
| AC-21 | Fixture W | Upload(`company_id;Score A\nSYN01;3,5`) | Status 200; `fields` = `[{"name": "Score A", "type": "number"}]`; the row's value is 3.5 | holdout |
| AC-22 | Fixture W | Upload with a header `company_id` and 31 more headers `f1`..`f31`, one row `SYN01` with `x` in each | Status 422; one rejection, row 1, field `""`, reason `at most 30 fields` | holdout |
| AC-23 | Fixture W | Upload with header `company_id,Feedback` and 5,001 rows cycling `SYN01`..`SYN12` | Status 422; exactly one rejection: row 0, field `""`, reason `at most 5,000 rows` | holdout |
| AC-24 | Fixture W | Upload(`company_id,Feedback\nSYN01,<2,001 × "a">`) | Status 422; one rejection, row 2, field `Feedback`, reason `at most 2,000 characters` | holdout |
| AC-25 | Fixture W | Upload of a file named `t.csv`: `company_id,Feedback\n` followed by lines `SYN01,x` up to 6,000,000 bytes | Status 413 with detail `File is larger than the 5 MB upload limit.` | holdout |
| AC-26 | Fixture W | `POST /uploads` with a file `t.pdf` | Status 422 with detail `Upload a .xlsx or .csv file` | holdout |
| AC-27 | Fixture W | `POST /uploads` with a file `t.xlsx` whose bytes are `not a workbook` | Status 422; `rejected` = `[{"sheet": "", "row": 0, "field": "", "reason": "not a valid xlsx workbook"}]`; `batch_id` `null` | holdout |
| AC-28 | Fixture W | `POST /uploads` with an xlsx, first worksheet `Q4`: row 1 `company_id`, `Internal rating`, `Feedback`; row 2 `SYN01`, the number 4, `ok` | Status 200; `fields` = `[{"name": "Internal rating", "type": "number"}, {"name": "Feedback", "type": "text"}]`; the row's `Internal rating` is 4 | holdout |
| AC-29 | Fixture W | F1's request, sent signed in as a viewer instead of an analyst | Status 403 | holdout |
| AC-61 | AC-29 | `GET /api/stewardship/uploads` | `uploads` is `[]` | holdout |
| AC-30 | Showcase data | Upload(`isin,Feedback\n<I in lower case with a space after its 2nd character>,ok`) | Status 200; `GET /uploads/<batch_id>` row has `company_id` C | holdout |
| AC-31 | Showcase data; I2 = the `identifier` of the second row of `GET /api/stewardship/worklist` whose `issuer_id` starts with `isin_` | Upload(`company_id,isin,Feedback\n<C>,<I2>,ok`) | Status 422; one rejection, row 2, field `isin`, reason `company_id and isin name different companies` | holdout |
| AC-32 | PR 2; Fixture W; `GET /worklist` taken as W0; then F1 | `GET /api/stewardship/worklist` | Every row's `score` and `parts` equal W0's (uploads never change the score) | holdout |
| AC-33 | PR 2; Fixture W, F1, and a group G of kind `companies` with `SYN02` and `SYN03` | `GET /api/stewardship/worklist?scope=group:<G>` | `extra_fields` lists both fields with `companies` 1 | holdout |
| AC-34 | PR 3; Fixture W, F1 | A user opens `#/stewardship/workbench` | The table has columns `Feedback · Uploaded` and `Internal rating · Uploaded`; `SYN01`'s cells show `Constructive call` and `3` | evaluator |
| AC-35 | AC-34 | The user adds the filter `Internal rating · Uploaded` from **Add filter ▾** | A range slider from 1 to 3 appears | evaluator |
| AC-62 | AC-35 | The user moves the lower handle to 2 | `SYN01` stays and `SYN02` is hidden | evaluator |
| AC-36 | AC-34 | The user opens `SYN01`'s side panel, tab **Uploaded** | Two lines, `Feedback` and `Internal rating`, each with As of = today, File `t.csv`, the uploader's name and When = today (in the format AC-54 uses) | evaluator |
| AC-49 | AC-34 | The user opens `SYN03`'s side panel, tab **Uploaded** | It says `No uploaded data for this company.` | evaluator |
| AC-37 | PR 3; Fixture W | The user downloads the template from **Uploaded data**, replaces its row 2 with `SYN04`, empty, empty, `Template works`, empty, and uploads it | The page says `Saved: 1 company, 1 field.` | evaluator |
| AC-50 | AC-37 | The user reads `SYN04`'s row | Its `Feedback · Uploaded` cell shows `Template works` | evaluator |
| AC-38 | PR 3; Fixture W | The user uploads the AC-12 file through **Uploaded data** | The page says `Nothing was saved.` and lists row 3, `company_id`, `unknown company SYN99` | evaluator |
| AC-39 | PR 3; AC-34 | The user withdraws `t.csv` with the reason `test` | After the dialog, the table has no `· Uploaded` column | evaluator |
| AC-51 | AC-39 | The user reads the list in **Uploaded data** | `t.csv` shows as `Withdrawn` with the user's name and `test` | evaluator |
| AC-52 | AC-34 | The user sorts by `Internal rating · Uploaded`, descending | `SYN01` (3) comes before `SYN02` (1), and rows without a value come last | evaluator |
| AC-53 | AC-34 | The user adds the filter `Feedback · Uploaded` and types `reply` | Only `SYN02` is left | evaluator |
| AC-54 | AC-34 | The user hovers `SYN01`'s `Feedback · Uploaded` cell | The tooltip reads `t.csv · <user name> · <today> · as of <today>` | evaluator |
| AC-55 | AC-34 | The user hides `Feedback · Uploaded` in **Columns ▾** | The column leaves the table; `Internal rating · Uploaded` stays | evaluator |
| AC-56 | PR 3; Fixture W, F1 (by the analyst); the user is signed in as a viewer | The user opens **Uploaded data** | The list shows `t.csv`; there is no **Withdraw** button and no **Upload** button | evaluator |
| AC-40 | 2,500 issuers and an upload log of 5 uploads × 2,500 companies × 10 fields (unit fixture) | `worklist.build()` runs with and without the log | The difference is under 0.3 s on the CI runner | unit |
| AC-41 | PR 2; Fixture W with no `uploads/` directory | `GET /api/stewardship/worklist` | Status 200, `extra_fields` `[]`, every row's `extra` `{}`; the other row fields as before (spec 1's holdout rows stay green) | holdout |
| AC-42 | Fixture W, F1 | `GET /api/stewardship/notes?company_id=SYN01` | `notes` is `[]` (uploads write no notes) | holdout |
| AC-57 | PR 1 to 3 | `pytest tests/test_stewardship_intake.py tests/test_stewardship_intake_excel.py tests/test_api_stewardship_intake.py` | All pass with no line of those three files changed | unit |

Must not change: the intake routes and `read_workbook` (AC-57); the score and its parts (AC-32); the worklist without
uploads (AC-41); notes (AC-42).
