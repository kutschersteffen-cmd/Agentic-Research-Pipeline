# Table-aware extraction: table metadata, a document outline, whole tables as evidence, one table read

Date: 2026-10-31
Status: draft, awaiting owner approval
Source: the Docling investigation of 2026-10-31 and the Claude-proposed answer set for RWE, Siemens and BASF
(sheet https://claude.ai/artifact/NWaSvVmWwoXBJ3afzWputo). The owner asked for all four recommendations plus
metadata on the tables.

## Why

On green capex the proposed answer set has every setup wrong on 25–85% of cards, the Sonnet + Opus reference
included. The errors trace to what the model is shown, not to the model:

| Seen | Cause in the pipeline |
|---|---|
| Siemens green buildings read from the OpEx table, not CapEx | A table passage carries only its caption; the heading it sits under ("Taxonomy CapEx KPI" vs "OpEx KPI") is dropped |
| BASF hydrogen read from the % column, not € million | Column labels keep only the lowest header row; the prompt shows no column headers |
| Missed prior-year columns, a dropped "billion" | 3,500-char text pieces cut a table mid-grid, without its header rows; a scale in a header cell is never found |
| RWE renewables counted wind only | Each of 19 capex fields does its own retrieval and sees a different slice of one table |
| 5–8 transition-plan questions "not found" per company | No routing to the climate sections; nobody can tell a retrieval miss from a missing disclosure |

## Goals

1. **Table metadata.** Each parsed table records its page, the heading path above it, its full column headers
   (every header row), its row labels, its unit and scale (from caption, header cells or a unit column) and a table
   kind (e.g. `eu_taxonomy_capex`).
2. **Document outline.** Each document gets an outline: headings with page and character range, each tagged by
   keyword rules (e.g. `eu_taxonomy`, `climate_targets`). Built in code, no model call.
3. **Whole tables as evidence.** When a selected passage overlaps a table, the model gets the whole table once,
   with a metadata header line, instead of a fragment.
4. **Routing by outline tags.** A field can name section tags; retrieval looks there first and falls back to the
   whole document. The run records per field whether the routing matched.
5. **One table read.** Fields that name the same table kind are extracted in one call over that table; each is still
   blind-verified and grounded on its own.

## Non-goals

- A model call to label sections (the investigation's option 6). Keyword rules only; revisit after measuring.
- Changing grounding, the checks' severities or the review routing.
- Fetching more documents (Siemens' full annual report).
- XBRL/ESEF tag extraction.

## Anti-goals

- A field whose routing tags match nothing gets less evidence than today.
- A table too large for the prompt crowds out all other evidence.
- A one-table group call that fails loses the fields: each falls back to its own call, as group calls do today.
- Quotes stop grounding: the whole-table text is the same `full_text` slice, so grounding is unchanged.

## Approaches considered

| | Approach | Trade-off |
|---|---|---|
| **A** | **Metadata at parse time on `TableSpan`, outline derived from text, whole-table swap in `field_evidence`, tags on `DocumentRouting` (chosen)** | Parser version bump re-parses every document once (~10–40 min CPU per large report); everything else is cheap code |
| B | Keep parsing; build metadata from the markdown text at load time | No re-parse, but header rows and merged cells are lost in markdown, which is the core problem |
| C | Store Docling's full document JSON and query it | Most information, but a large cache change and a new data model |

## Design

Delivered in two PRs: **PR 1** = goals 1–4, **PR 2** = goal 5 (it builds on PR 1's table kinds).

### 1. Table metadata (`arp/schemas/common.py`, `arp/ingestion/local_files.py`)

`TableSpan` gains: `page: int | None`, `heading_path: list[str]`, `column_headers: list[str]` (one per column, every
header row joined top-down with " – ", e.g. `"Proportion of CapEx – 2025"`), `row_labels: list[str]`,
`scale: str | None` and `unit: str | None` (from, in order: the caption's "in … million" phrase, a header cell's
scale word, a column whose header is "Unit"/"Einheit"), `kind: str | None`. `TableCell.col_label` becomes the full
header path. `TableRef` gains `page` and `kind`. `_PARSER_LOGIC_VERSION` goes to 4.

`kind` comes from a small rules table `arp/ingestion/table_kinds.py`: an ordered list of
`(kind, all_of, any_of)` word rules over caption + heading path + column headers, lower-cased. First match wins.
Initial kinds: `eu_taxonomy_capex`, `eu_taxonomy_turnover`, `eu_taxonomy_opex`, `ghg_emissions`, `ghg_targets`,
`energy`, `remuneration`. An EU Taxonomy table is `eu_taxonomy_capex` when "capex" or "capital expenditure"
appears in its caption or heading path and "opex"/"turnover" does not.

### 2. Document outline (`arp/ingestion/outline.py`, new)

`outline(doc) -> list[OutlineEntry]` with `OutlineEntry(title, page, char_start, char_end, tags: list[str])`,
built from the markdown headings already used for chunk sections (`parsing.py` `_MD_HEADING`) and
`doc.page_breaks`; `char_end` is the next heading's start. Tags come from `arp/ingestion/section_tags.py`, keyword
rules like the table kinds: `eu_taxonomy`, `climate_targets`, `transition_plan`, `ghg_emissions`, `governance`,
`remuneration`, `biodiversity`, `water`, `workforce`. Derived from `full_text` on load and cached with the chunk
spans (no cache schema change). The cache is a speed measure only and is not gated by an acceptance row.

`DocumentChunk` gains `page: int | None`, `section_tags: list[str]` (the tags of the outline entry it starts in) and
`table_id: str | None` (set on whole-table passages). A whole-table passage's `section` becomes its heading path's
last entry (not the caption); the caption moves to a new `caption` field.

### 3. Whole tables as evidence (`arp/extraction/field_graph.py`, `extractor_agent.format_evidence`)

After `select_relevant_chunks`, `field_evidence` swaps each selected text passage that overlaps a table span for that
table's whole-table passage, keeping rank order and dropping duplicates. A table longer than
`settings.evidence_table_max_chars` (new, default 12,000) is not swapped in; the text passage stays. The cap on
passages (`evidence_max_chunks`) still applies after the swap.

`format_evidence` adds `page=<n>`, and for a table passage `table=<kind or table_id>`, `caption="<caption>"`,
`unit=<unit>`, `scale=<scale>` (each only when set) and `columns=<column_headers joined with " | ">` to the passage
header line. Swapping does not refill: three passages collapsing into one table passage leave two fewer passages.

### 4. Routing by outline tags (`arp/schemas/datapoints.py`, `arp/planning/doc_routing.py`, presets)

`DocumentRouting` gains `section_tags: list[str]` and `table_kinds: list[str]`. `section_filter` keeps a chunk when
its `section_tags` or its table's `kind` intersect them (in addition to today's heading substrings); with `fallback`
(default true) an empty result keeps every chunk, as today.

Presets: green capex fields → `table_kinds=["eu_taxonomy_capex"]`, `section_tags=["eu_taxonomy"]`; revenue/opex
analogues; transition capex likewise; transition-plan indicators → `section_tags` by category (target and tracking
→ `climate_targets`, `ghg_emissions`, `transition_plan`; governance → `governance`, `remuneration`; strategy →
`transition_plan`, `climate_targets`, `biodiversity`, `water`, `workforce`). Changing `document_routing` is field
content, so these fields go up one version.

The walkthrough trace's field entry gains `routing: {"matched": bool, "tags": [...], "kept": n, "of": m}`.

### 5. One table read (PR 2; `arp/extraction/pipeline.py`, `arp/schemas/datapoints.py`)

`FieldDefinition` gains `table_group: str | None`. Fields of one schema with the same `table_group` are extracted in
one `extract_group` call whose evidence is the routed evidence of the first field (normally the whole
`eu_taxonomy_capex` table), merged with the others' (`merge_evidence`). Unlike `extraction_group_size`, this also
groups high-risk fields; each is still blind-verified, grounded and checked on its own. A field the group call leaves
out, or a failed group call, falls back to its own call. The green preset sets `table_group="eu_taxonomy_capex"` on
the capex fields (and the revenue/opex analogues).

### 6. Scoring against the answer sheet (`backend/scripts/answer_check_score.py`, new)

`python scripts/answer_check_score.py --truth <export.json> --run <run_id> --schema <green-capex|transition-plan>
--min-correct N [--max-not-found M]` reads approved cards (an export of the sheet's `cards` + `truth` collections,
committed as `backend/tests/golden/answer_check/approved.json` once the owner has approved them) and a run's stored
results, prints `correct <c>/<n> · not_found_on_yes_no <k>` and exits 1 below `N` or above `M`. A card is correct
when: yes/no and text answers match case-insensitively; numbers are within 1% and the last unit word (e.g.
`million`, `%`) matches; "not in report" matches "not found". A card the run did not answer counts as wrong.

Baseline (Haiku + Sonnet, 2026-10-31, against the Claude-proposed answers): green capex **17/45** correct;
transition plan **169/192** correct with **16** "not found" where the answer is YES or NO.

## Acceptance

AC-26/27 need the owner's approval of the answer-check cards first; until then they run against the Claude-proposed
answers and are reported, not gating. Rows marked `unit` become `holdout` once `HOLDOUT_TOKEN` is set. "Stand-in" is `FakeLLMClient` or a scripted client.
Fixture documents are small Docling-free `SourceDocument`s with hand-built `table_spans`, except AC-1 to AC-4, which
run the real Docling parse on a 2-page PDF fixture committed under `tests/fixtures/tables/`.

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | The fixture PDF: a table whose column 0 is the row-label column with an empty header, and two header rows ("Proportion of CapEx" over "2025" / "2024"), under heading "EU Taxonomy – CapEx KPI" on page 2 | parsed | `column_headers == ["", "Proportion of CapEx – 2025", "Proportion of CapEx – 2024"]` | unit |
| AC-1b | Same | parsed | the cell under "2025" has `col_label == "Proportion of CapEx – 2025"` | unit |
| AC-1c | Same, row labels "Wind", "Solar" | parsed | `row_labels == ["Wind", "Solar"]` | unit |
| AC-2 | Same | parsed | `TableSpan.page == 2` | unit |
| AC-2b | Same | parsed | `heading_path[-1] == "EU Taxonomy – CapEx KPI"` | unit |
| AC-3 | Same, a header cell "in € million" and no caption | parsed | `TableSpan.scale == "million"` | unit |
| AC-3b | Same | parsed | `TableSpan.unit == "€"` | unit |
| AC-3c | A table with caption "in EUR thousand" and a header cell "in € million" | metadata built | `scale == "thousand"` (the caption wins) | unit |
| AC-3d | A table with a column headed "Unit" whose cells read "t CO2e", no caption, no scale word | metadata built | `unit == "t CO2e"` | unit |
| AC-4 | The AC-1 table | parsed | `kind == "eu_taxonomy_capex"` | unit |
| AC-5 | Caption "Taxonomy-aligned OpEx" under heading "EU Taxonomy" | kinds applied | `kind == "eu_taxonomy_opex"` | unit |
| AC-6 | A table with no matching words | kinds applied | `kind is None` | unit |
| AC-7 | A document with headings "E1 Climate change", "Targets", "EU Taxonomy" on pages 3, 4, 7 | `outline(doc)` | 3 entries with those titles and pages; each `char_end` equals the next `char_start`; the last equals `len(full_text)` | unit |
| AC-8 | Same | `outline(doc)` | the "Targets" entry's `tags` contain `climate_targets` | unit |
| AC-8b | Same | `outline(doc)` | the "EU Taxonomy" entry's `tags` contain `eu_taxonomy` | unit |
| AC-8c | Same document, `outline(doc)` called twice | second call | returns an equal list | unit |
| AC-9 | A chunk starting under "EU Taxonomy" on page 7 | `chunk_document` | its `section_tags` contain `eu_taxonomy` | unit |
| AC-9b | Same | `chunk_document` | its `page == 7` | unit |
| AC-9c | A table under heading path ["E1", "EU Taxonomy"] with caption "CapEx KPI" | `chunk_document` | its whole-table chunk has `section == "EU Taxonomy"` | unit |
| AC-9d | Same | `chunk_document` | that chunk has `caption == "CapEx KPI"` | unit |
| AC-9e | Same | `chunk_document` | that chunk's `table_id` equals the span's `table_id` | unit |
| AC-10 | A field whose top-ranked passage overlaps table T (8,000 chars) | `field_evidence` | T's whole-table passage is at rank 1 and the overlapping text passage is absent | unit |
| AC-11 | Same, T is 20,000 chars, `evidence_table_max_chars` 12,000 | `field_evidence` | the text passage stays at rank 1; T's passage is absent | unit |
| AC-12 | Two selected passages overlap the same table | `field_evidence` | the table passage appears exactly once | unit |
| AC-13 | `evidence_max_chunks` 12; 12 selected passages, of which ranks 2, 5 and 9 overlap one table | `field_evidence` | exactly 10 passages: the table passage at rank 2, then the other 9 in rank order | unit |
| AC-14 | A table passage of kind `eu_taxonomy_capex`, page 102, caption "CapEx KPI", unit "€", scale "million", columns "A", "B" | `format_evidence` | its header line contains `page=102`, `table=eu_taxonomy_capex`, `caption="CapEx KPI"`, `unit=€`, `scale=million` and `columns=A | B` | unit |
| AC-15 | A field with `table_kinds=["eu_taxonomy_capex"]`, `section_tags=["eu_taxonomy"]`; a fixture document whose chunking yields exactly 6 candidates: 1 whole-table passage of that kind, 2 text chunks tagged `eu_taxonomy` and 3 untagged text chunks (the table grid lies in no text chunk) | `field_evidence` | every returned passage is that table's passage or a chunk tagged `eu_taxonomy` | unit |
| AC-16 | Same field, a document with no such table and no tagged section | `field_evidence` | the chunk ids and order equal those for the same field with `document_routing` unset | unit |
| AC-17 | Same as AC-15 | the field graph runs with a trace sink | the field's trace entry has `routing == {"matched": true, "tags": ["eu_taxonomy"], "table_kinds": ["eu_taxonomy_capex"], "kept": 3, "of": 6}` | unit |
| AC-18 | Same as AC-16 | the field graph runs with a trace sink | `routing.matched == false` | unit |
| AC-19 | The green preset | built | each capex field (`capex_total`, `green_capex_*`, `transition_capex_total`) has `document_routing.table_kinds == ["eu_taxonomy_capex"]` | unit |
| AC-19e | Same | built | the revenue fields have `table_kinds == ["eu_taxonomy_turnover"]` | unit |
| AC-19f | Same | built | the opex fields have `table_kinds == ["eu_taxonomy_opex"]` | unit |
| AC-19c | The transition capex preset | built | fields of data type `currency_amount`, `percentage` or `enum` have `table_kinds == ["eu_taxonomy_capex"]`; the three `boolean` fields (`tc_new_unabated_coal`, `tc_new_blast_furnace`, `tc_new_oil_gas_project`) have `section_tags == ["transition_plan", "climate_targets"]` | unit |
| AC-19d | The transition-plan preset | built | target and tracking questions have `section_tags == ["climate_targets", "ghg_emissions", "transition_plan"]`; governance `["governance", "remuneration"]`; strategy `["transition_plan", "climate_targets", "biodiversity", "water", "workforce"]` | unit |
| AC-19g | The green, transition capex and transition-plan presets | built | every field whose `document_routing` differs from `main` has a `version` one higher than on `main`; every other field's version is unchanged | unit |
| AC-20 | Two high-risk fields with `table_group="g"`; a stand-in | the company is extracted | the stand-in receives exactly 1 `GroupDraft` call | unit (PR 2) |
| AC-20b | Same | extracted | the stand-in receives exactly 2 blind-verify `ExtractionDraft` calls | unit (PR 2) |
| AC-20c | Same | extracted | each field's row has its own citations and its own `checks` list | unit (PR 2) |
| AC-20d | One low-risk and one high-risk field with `table_group="g"`, `extraction_group_size` 1 (no grouping by size) | extracted | exactly 1 `GroupDraft` call | unit (PR 2) |
| AC-21 | Same as AC-20, the group answer leaves out field 2 | extracted | field 2 gets its own `ExtractionDraft` call | unit (PR 2) |
| AC-22 | Same as AC-20, the group call raises | extracted | each field gets its own `ExtractionDraft` call | unit (PR 2) |
| AC-22b | Same | extracted | the run status is `completed`, 1 of 1 companies | unit (PR 2) |
| AC-22c | Two non-high-risk fields without `table_group`, `extraction_group_size` 2 | extracted | exactly 1 `GroupDraft` call, as on `main` | unit (PR 2) |
| AC-23 | A grounded quote inside a whole-table passage | grounding | `Citation.table_ref.page` and `Citation.table_ref.kind` equal the table's | unit |
| AC-23b | One quote grounded once against a text passage that holds it and once against the whole-table passage that holds it (same build) | grounding | `grounded`, `char_start` and `char_end` are equal | unit |
| AC-23c | The existing check and routing fixtures (`tests/test_checks_*.py`, `tests/test_routing.py`) | run | unchanged outcomes, severities and routes | unit |
| AC-28 | A 4-card scoring fixture: truth "100 million" / answer "100.9 million"; truth "100 million" / answer "102 million"; truth "YES" / answer "yes"; truth "NO" / answer "not found" | `answer_check_score.py` runs | prints `correct 2/4 · not_found_on_yes_no 1` | unit |
| AC-28b | Same, `--min-correct 3` | runs | exits 1 | unit |
| AC-28c | Same, `--min-correct 2 --max-not-found 1` | runs | exits 0 | unit |
| AC-28d | The 4-card fixture plus a fifth card with truth "120 million" that the run did not answer | runs | prints `correct 2/5 · not_found_on_yes_no 1` | unit |
| AC-28e | The 5 cards plus a sixth with truth "not in report" and answer "not found" | runs | prints `correct 3/6 · not_found_on_yes_no 1` | unit |
| AC-24 | The PR | CI | the "Backend (lint + tests)" job is green | CI |
| AC-25 | The golden set | `arp golden-set run` | exits 0 with every case passing | golden |
| AC-26 | Approved green-capex cards; a Haiku + Sonnet run of the green capex schema on RWE, Siemens, BASF | `answer_check_score.py --truth tests/golden/answer_check/approved.json --run <that run's id> --schema green-capex --min-correct 30` | exits 0 (baseline 17/45) | golden |
| AC-27 | Approved transition-plan cards; a Haiku + Sonnet run on the three companies | `answer_check_score.py --truth tests/golden/answer_check/approved.json --run <that run's id> --schema transition-plan --min-correct 169` | exits 0 | golden |
| AC-27b | Same | `answer_check_score.py --truth tests/golden/answer_check/approved.json --run <that run's id> --schema transition-plan --max-not-found 8` | exits 0 (baseline 16) | golden |

Must not change: AC-16, AC-18, AC-22, AC-22b, AC-22c, AC-23b, AC-23c, AC-25. Every changed existing test is listed in the PR.

## Left to the builder

- The exact keyword lists for table kinds and section tags (start from the three reports; keep each rule list in
  one file so it can grow).
- The fixture PDF (make it with reportlab or a 2-page export; commit the PDF, not a generator).
