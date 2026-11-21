# Factory run evidence prototype

This local CLI is the first slice of the [Factory improvement plan](../docs/superpowers/specs/2026-11-21-factory-improvement-loop.md). It requires Python 3.11 or newer and uses SQLite from the standard library.

From the repository root:

```sh
python factory/run_log.py --db /tmp/arp-factory-demo.sqlite3 import factory/examples/demo.jsonl
python factory/run_log.py --db /tmp/arp-factory-demo.sqlite3 report demo-csv
python -m unittest discover -s factory/tests -v
```

The example is synthetic. The timeline includes each stage's latest recorded event and a known-cost subtotal. Missing costs remain visible. The database records supplied evidence, with no live integration or gate authority.

## Import format

Each line is one JSON object. Blank lines are allowed. Import is atomic across the file. Ordering in reports follows UTC timestamps and then event ID as a stable tie-break.

| Field | Meaning |
| --- | --- |
| `run_id`, `event_id` | Nonempty strings. Event IDs are unique within a run. |
| `factory_sha` | Full lowercase commit SHA of the factory definition. All events within a run must agree. |
| `at` | ISO 8601 timestamp with a timezone. |
| `stage` | `intake`, `spec`, `holdout`, `implement`, `review`, `merge` or `regression`. |
| `kind` | `started`, `waiting`, `finished`, `check`, `approval` or `artifact`. |
| `attempt` | Worker attempt ID. Required on `started` and `finished`, optional otherwise. |
| `detail`, `source` | Optional summary and pointer to the evidence. Keep raw logs and secrets out of the ledger. |
| `spec_sha`, `head_sha` | Optional full lowercase SHAs of the spec and PR candidate. |
| `cost_usd_micros` | Optional integer on a finished attempt. One million micros is one US dollar. |

Each attempt can finish once per stage. Retries have distinct attempt IDs. The reported cost is the subtotal of supplied finished-attempt costs across the run, including failed attempts. It excludes costs that are unavailable or have not yet been recorded.

