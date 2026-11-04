# expected_main

Outputs of the taxonomy CLI captured from `main` *before* the authority-taxonomy schema change
(Task 1), as regression guards for Task 10 (AC-19..19d, AC-18).

Produced by driving `arp.cli.taxonomy.taxonomy_app` with `typer.testing.CliRunner`, a scripted
`FakeLLMClient` (tests/conftest.py), a temp `TaxonomyStore`, and `fetch_source_text` stubbed to
return a fixed sentence. Ids (`tax_`, `act_`, `theme_`, `doc_` + 12 hex) are replaced by numbered
placeholders (`tax_0001`) and ISO timestamps by `<TS>`; the merge output path is `<OUT>`.
Seeded taxonomies (`tax_a`, `tax_b`) use fixed ids and are not renumbered.

- `create_stdout.txt`, `create_saved_v1.json`: `create --method authority_source`
- `compare_stdout.json`, `merge_stdout.txt`, `merge_out_theme.json`: `compare` / `merge` of tax_a, tax_b
- `ratify_stdout.txt`, `ratify_saved_v1.json`: `ratify tax_a --by Owner`
- `show_stdout.json`: `show tax_a`
- `../saved_taxonomy_old.json`: tax_a v1 as stored, without the new fields (real, fixed timestamps)
