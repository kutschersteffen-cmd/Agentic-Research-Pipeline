# Retrieval gold set: sources and labels

Gold set for `arp golden-set retrieval --cases tests/golden/retrieval/cases.json`
(spec `retrieval-gold-set-and-question-queries`, Part A.1 and A.4).

## Documents

| company_id | document | Report | Publisher URL | Downloaded |
|---|---|---|---|---|
| `ssab` | `ssab-annual-report-2024.pdf` | SSAB AB, Annual Report 2024 (English, 197 pages, steel) | https://mb.cision.com/Main/980/4121762/3332561.pdf, the PDF that SSAB's own press release of 2025-03-20 links to (https://www.ssab.com/en/news/2025/03/ssabs-annual-report-2024-is-published) | 2026-10-31 |
| `heidelberg_materials` | `heidelberg-materials-geschaefts-und-nachhaltigkeitsbericht-2024.pdf` | Heidelberg Materials AG, Geschäfts- und Nachhaltigkeitsbericht 2024 (German, 346 pages, cement) | https://www.heidelbergmaterials.com/sites/default/files/2025-03/HM_GNB24_de.pdf (listed on https://www.heidelbergmaterials.com/node/25913) | 2026-10-31 |

The PDFs are not committed: neither report carries a licence that allows redistribution (both are
"Copyright © 2025" of the company). `documents.json` lists each with its URL and the SHA-256 of the
exact file that was labelled; cases mode downloads a missing file and checks the hash.
`documents/` is git-ignored. Owner choice, 2026-10-31.

## How the labels were made

1. Each PDF was parsed with the app's own parser, `arp.ingestion.local_files.parse_file_to_text_with_pages`
   (the function `LocalFileDocumentSource` uses), docling 2.140.0, parser logic version 3.
   The Heidelberg Materials labels were made on a copy from hauptversammlung.de (SHA-256 `21a39ce7…`)
   that differs from the publisher's file only in its save date. The publisher's file was parsed too,
   and every gold span is in its text; `documents.json` records the publisher's file.
2. For each of the 64 indicators in `arp/transition_plan/data/indicators.json`, the labeller (Claude,
   `labelled_by: "agent"`) read the question and guideline and decided whether the report answers YES.
   For each YES, `span_text` is the shortest passage that answers it, copied exactly from the parsed
   `full_text` (soft hyphens and table padding included). Indicators answered NO have no case.
3. Conservative calls: intensity-only targets are not counted as absolute targets (Heidelberg
   Materials has no case for `A_coverage_6`/`7`); offsetting indicators are left out when the report
   says carbon credits are not used; partial answers (e.g. Scope 3 categories listed without reasons for
   exclusion) get no case.
4. Spot check: 10 randomly chosen cases were shown to the owner (indicator, question, passage).
   9 were approved. `ssab-tp_a_transparency_29` (limited assurance of the sustainability report) was
   rejected because the assurance covers historical information only, not the targets. It was removed,
   and so was `heidelberg_materials-tp_a_transparency_29`, which has the same weakness. One more random
   case (`ssab-tp_a_progress_67`) was approved in its place. Approved cases have `spot_checked: true`.

## Totals

60 cases, 68 gold spans, 38 distinct `field_id`s, all in schema `transition_plan_indicators`;
10 cases spot-checked. SSAB: 27 cases / 30 spans. Heidelberg Materials: 33 cases / 38 spans.
