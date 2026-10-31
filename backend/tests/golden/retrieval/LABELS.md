# Retrieval gold set: sources and labels

Gold set for `arp golden-set retrieval --cases tests/golden/retrieval/cases.json`
(spec `retrieval-gold-set-and-question-queries`, Part A.1 and A.4).

## Documents

| company_id | document | Report | Source URL | SHA-256 | Licence / permission |
|---|---|---|---|---|---|
| `ssab` | `ssab-annual-report-2024.pdf` | SSAB AB, Annual Report 2024 (English, 197 pages, steel) | https://mb.cision.com/Main/980/4121762/3332561.pdf (linked from SSAB's press release of 2025-03-20, https://news.cision.com/ssab/r/ssab-s-annual-report-2024-is-published,c4121762) | `5542239e30fb6ba884333374b415a2765b1f053173a8fd41e262167fd673787b` | **Pending.** The report carries no licence statement. Copyright SSAB AB. Written permission to redistribute it in this repository is being requested by the owner; record it here when given. |
| `heidelberg_materials` | `heidelberg-materials-geschaefts-und-nachhaltigkeitsbericht-2024.pdf` | Heidelberg Materials AG, Geschäfts- und Nachhaltigkeitsbericht 2024 (German, 346 pages, cement) | https://hauptversammlung.de/fileadmin/public/user_upload/HM_GNB24_de.pdf (the same report is published at https://www.heidelbergmaterials.com/node/25913) | `21a39ce7ffa725025faf91789df567af8d6f9ef30d2720cda6212308b00476f3` | **Pending.** Imprint: "Copyright © 2025 Heidelberg Materials AG", no licence. Written permission to redistribute it in this repository is being requested by the owner; record it here when given. |

No public steel, cement, chemicals or energy report with a redistributable licence was found
(2026-10-31), so the owner chose these two reports subject to the publishers' permission. The PDFs
are committed only once both permissions are recorded above.

## How the labels were made

1. Each PDF was parsed with the app's own parser, `arp.ingestion.local_files.parse_file_to_text_with_pages`
   (the function `LocalFileDocumentSource` uses), docling 2.140.0, parser logic version 3.
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
