# ARP OpenShell Code Mode prototype

**Proposed for owner approval**

Feature `openshell-code-mode` branches from `c7e65f54cc4d9b2ce95e680d234d6e0132b36992`. Plan for two implementation PRs at high risk because the executor and tool gateway establish an authorization boundary.

## Owner decision

Approve an opt-in, local CLI demonstration on an authorized Linux OpenShell host using synthetic data and the existing ARP model configuration. Success means that the same Code Mode benchmark runs under both executors and one voting question produces a reproducible ranking reversal. An implementation PR will include real OpenShell evidence for its slice.

The demo defaults to one CPU host, one invocation at a time, two short-lived sandboxes for the voting workflow, one synthetic voting snapshot, and a CSV and PNG report. ARP runs the approved model configured for that environment through its existing provider adapter. Fixed scripts let both workflows run with zero model credentials. The scope excludes live data, voting operations, production Research Plans changes, hosted Claude execution, UI changes, and Superset publishing.

## Outcome and options

An engineer can reproduce the existing benchmark on OpenShell, then demonstrate how generated JavaScript composes read-only ARP functions and how a separate Python job investigates a new weighting question on the same snapshot.

| Option | Scope |
|---|---|
| Benchmark | Execute the existing fixed benchmark through both JavaScript runtimes and compare their results. |
| **Selected** | Add one prompt-driven proxy-voting workflow with a reproducible Python sensitivity analysis and a real OpenShell run receipt. |
| Expanded | Support registered Python research scripts and workspace results beyond voting. This needs a durable workspace job contract and approval of how input and output artifacts are stored. |

## Implementation shape

- Run the CLI from an installed ARP backend environment. Develop under `backend/arp/prototypes/openshell_code_mode/` for the Python host and CLI, with Node.js package and lockfile under `scripts/openshell-code-mode/`. This isolation keeps the demo out of ARP startup, API routing, and existing Research Plans. Reuse `backend/arp/llm/factory.py` and `backend/arp/llm/base.py` for generation in the host process. The repeatable CLI path provides a fixed script without initializing the model factory.
- Use the existing [prototype archive](https://chatgpt.com/library?file_id=libfile_827177cfbfe08191bdb844029dec8fa7&account_id=personal) and `backend/arp/stewardship/data/examples/sample_meetings.json` as the benchmark reference. Preserve the archive's package pin (`@cloudflare/codemode` 0.5.6), benchmark tool contracts, holdings, and script. Make the new checkout self-contained so a developer can run the benchmark without retrieving the archive. `DynamicWorkerExecutor` runs the comparison locally through Miniflare. Implement the package's `Executor` contract for OpenShell, including the bridge from typed JavaScript methods to the host's read-only registry. Both engines share the same host-side validation and fixture implementations.
- A trusted operator selects the existing OpenShell gateway through the OpenShell CLI configuration and sets `ARP_CODE_MODE_TOOL_GATEWAY_URL` to the approved private HTTPS tool gateway reachable from the JavaScript sandbox. A custom image contains a pinned Node.js runtime and a fixed script entry point. Launch one fresh sandbox per invocation. The host issues a short-lived, run-scoped credential that permits only that run's registered tools on its authorized synthetic snapshot. A tool invocation with an absent, expired or mismatched credential fails before a tool runs. The sandbox's network policy limits it to the tool gateway. The tool gateway holds access to the fixture store and verifies eligibility and scope for every call. The sandbox receives neither model keys nor database credentials.
- Accept one voting question in model mode: “Analyze 60,000 proxy votes. Which sectors had the highest opposition, and does the ranking change if every issuer gets equal weight?” Call `LLMClient.complete_structured()` with the question, a script output schema and two JS tool signatures, `listVotingSnapshots({})` and `aggregateVotesBySector({snapshot_id})`. The tool sequence is `listVotingSnapshots({})` then `aggregateVotesBySector({snapshot_id: "synthetic-votes-v1"})`. Each call must succeed exactly once. JavaScript returns `{"snapshot_id":"synthetic-votes-v1","sectors":[...]}`, where each sector row contains only `sector`, `eligible_votes` and `against_votes`. Rows are sorted by descending unrounded opposition rate and then sector name ascending. The host compares the result by value with the aggregate tool output stored outside the sandbox. An omitted, extra or mismatched call or result fails with `INVALID_RESULT`. The deterministic path runs a fixed script with the same tool sequence. In model mode, require the explicitly configured model ID, force a fresh response with `cache_refresh=True`, and reject stand-ins, cached responses, provider fallback, or a returned model ID different from the configured ID. Exit with `MODEL_PROVENANCE_MISMATCH` before starting a sandbox if the model provenance check fails.
- The trusted host builds a local SQLite database with 60,000 synthetic eligible vote rows using the issuer counts in the fixture below. Every row is either For or Against. Trusted SQL computes sector totals and stages one row per sector and issuer with eligible and opposing counts. The issued package contains no ballot identifiers and carries the pinned snapshot ID `synthetic-votes-v1`. After the JavaScript result validates, the host provisions a second OpenShell sandbox from a pinned Python image with fixed analysis script, plotting dependencies and Parquet support. The host creates the sandbox, transfers the Parquet input to the configured read-only workload path, then runs the fixed entry point as a separate exec operation. The Python policy disables outbound networking. The trusted entry point receives a validated parameter for minimum eligible votes per issuer, an integer from `1` to `60,000` with default `1`, and returns only `ranking.csv` and `ranking.png`. The host checks the CSV schema, row bounds and values against the fixture calculation and requires a decodable PNG. It stages the two files until both jobs have terminated and cleanup has been confirmed. A failed run retains its manifest without publishing either file.
- Enforce a 30-second JavaScript deadline and a 60-second Python deadline, including startup. Terminate expired jobs and delete sandboxes on success or failure. The JavaScript budget is 12 tool requests and 16,384 UTF-8 result bytes. The CSV and PNG budget is 5 MiB total. The host records the outcome and run ID. Use a private, controlled probe service for runtime network tests. First verify that the host reaches the probe. Then have the in-sandbox test entry point emit `PROBE_STARTED` and attempt the same request with a unique run marker. The receiver must record zero requests carrying that marker. In JavaScript, demonstrate a successful call to the approved gateway in the same run.

[Cloudflare Code Mode 0.5.6](https://www.npmjs.com/package/@cloudflare/codemode/v/0.5.6) · [OpenShell architecture and policy boundaries](https://docs.nvidia.com/openshell/about/architecture)

## CLI contract

All examples use `python -m arp.prototypes.openshell_code_mode` from an environment with the ARP backend package installed. Pass a new `--output-dir` on each invocation. Standard output emits one JSON object with `run_id` and `status`. Success exits `0` with `status: "ok"`. A handled failure exits `1` with `status: "failed"` and a stable `error_code`. Diagnostic text goes to stderr. An unconfigured or unreachable OpenShell gateway yields `OPENSHELL_UNAVAILABLE`. A runtime result or trace difference yields `RUNTIME_MISMATCH`.

The output manifest is `run.json`. Fields are `run_id`, `status`, `error_code` (null on success), `executor` (`compare` or `openshell`), `script_mode` (`fixed` or `model`), `configured_model_id`, `model_id`, `model_cached` and `model_fallback_from` (all null for fixed), `snapshot_id`, `snapshot_sha256`, `javascript_sha256`, `python_sha256` (null for benchmark), `min_issuer_votes` (null for benchmark), `tool_receipts`, `artifacts` and `sandboxes`. Hash available inputs and artifacts as lowercase hex SHA-256. Use the benchmark holdings JSON bytes for the benchmark snapshot hash and the staged Parquet bytes for the voting snapshot hash. Use the exact script bytes for code hashes. An unavailable input hash or ID is null on failure. Each tool receipt includes `tool`, `args`, `status` and source provenance. Each successful voting artifact is listed by filename and hash. Each provisioned sandbox record includes its ID, job (`javascript` or `python`), image digest and cleanup status (`deleted` or `failed`). Save the exact successfully run generated or fixed JavaScript as `code.js`. Capture the OpenShell version in the independent runtime evidence. Exclude model keys, database credentials, run credentials and raw environment variables from output files and logs.

| Command arguments | Behavior |
|---|---|
| `benchmark --executor compare --output-dir DIR` | Compare both JavaScript executors using the fixed benchmark. Write `benchmark.json` when both finish. Exit with `RUNTIME_MISMATCH` if normalized JSON results or receipts differ. |
| `voting --script fixed --output-dir DIR [--min-issuer-votes N]` | Run the fixed voting JavaScript and Python scripts in OpenShell. |
| `voting --script model --output-dir DIR [--min-issuer-votes N]` | Generate the JavaScript for the named question using the configured ARP model and run the Python analysis. |

The benchmark report `benchmark.json` has top-level keys `dynamic_worker` and `openshell`, each with `result` and `normalized_tool_receipts`. Preserve the results separately even on a comparison mismatch. Receipt normalization keeps serial order and sorts the two concurrent issuer calls by sector name. The exact tool names and arguments are:

| Tool | Arguments |
|---|---|
| `listBenchmarks` | `{}` |
| `getBenchmarkSectors` | `{"benchmark_id":"arp-synthetic-sample"}` |
| `listSectorIssuers` | `{"benchmark_id":"arp-synthetic-sample","sector":"Financials"}` |
| `listSectorIssuers` | `{"benchmark_id":"arp-synthetic-sample","sector":"Information Technology"}` |

Successful benchmark receipts use `status: "ok"` and source label `ARP synthetic stewardship sample`, `synthetic: true`, `as_of: null`, and the same baseline-pinned sample URL as the archive. Keep runtime timestamps and execution IDs in raw receipts. The private test harness can substitute a script, controlled deadline, or tool response for deterministic checks under the same execution path. It adds no public CLI script-input flag. The host uses `UNKNOWN_TOOL` for unregistered methods, `TOOL_DENIED` for rejected gateway credentials or scope, `DEADLINE_EXCEEDED` for deadlines, `CALL_LIMIT` for excessive calls and `OUTPUT_LIMIT` for oversized outputs. Treat cleanup failure as a failed run under `CLEANUP_FAILED` if no earlier error applies.

## Fixture and output

| Sector | Issuer | Eligible | Against |
|---|---|---:|---:|
| Information Technology | SYN03 | 30,000 | 6,000 |
| Information Technology | SYN07 | 3,000 | 0 |
| Financials | SYN11 | 15,000 | 2,000 |
| Financials | SYN12 | 12,000 | 1,600 |

The fixture has 60,000 eligible votes and 9,600 opposing votes. The sector vote-weighted rate divides sector opposition by sector eligible votes. The issuer-weighted rate averages eligible issuer rates after excluding issuers below the minimum. A sector with no included issuers has an empty issuer-weighted rate and rank. Rank measured values by descending unrounded rate, breaking ties by sector name ascending. Rates in the CSV are percentage points rounded to four decimals. Preserve all eligible votes in the vote-weighted baseline as the issuer filter changes.

The CSV is sorted by vote-weighted rank with fields `sector,eligible_votes,against_votes,included_issuers,vote_weighted_pct,issuer_weighted_pct,vote_rank,issuer_rank`. At the default minimum the two rows are:

```csv
sector,eligible_votes,against_votes,included_issuers,vote_weighted_pct,issuer_weighted_pct,vote_rank,issuer_rank
Information Technology,33000,6000,2,18.1818,10.0000,1,2
Financials,27000,3600,2,13.3333,13.3333,2,1
```

At minimum `4,000`, the Information Technology row becomes `Information Technology,33000,6000,1,18.1818,20.0000,1,1` and the Financials row becomes `Financials,27000,3600,2,13.3333,13.3333,2,2`. At minimum `30,001` both issuer rates and ranks are empty and both included-issuer counts are zero.

The PNG is a paired bar chart with rows labelled Information Technology and Financials, series labelled Vote-weighted and Issuer-weighted, and an axis labelled Opposition (%). Use the values in the CSV for each run, including nondefault minimums. An empty rate produces no bar. Verify visual labels and series in the real runtime review and assert the data and labels given to the renderer in the automated check.

Factory holdout fixtures drive the running web app, and CI does not provision OpenShell or install this prototype's Node package. The CLI scope therefore uses `unit` rows, with an independent real-host acceptance run owed on each implementation PR. This also supplies independent checks for the deterministic high-risk cases. For slice 1 the reviewer verifies parity, rejection, deadline, cleanup and isolation. For slice 2 the reviewer runs fixed and configured-model voting paths, inspects the chart and manifest, and verifies Python deadline, cleanup and isolation. The checkout provides `scripts/openshell-code-mode/verify-host.sh --slice 1|2 --evidence-dir DIR`. Set up the documented Node and Python dependencies, select an approved OpenShell gateway with the pinned images and policies, supply the private gateway URL and a reachable controlled probe service, and configure the approved model for slice 2. The verifier invokes the CLI and fixed-purpose test entry points in the real runtime. It writes one sanitized transcript in a fresh evidence directory.

| Slice | Real-host checks |
|---|---|
| 1 | AC-1, AC-2, AC-14 and AC-26 for benchmark parity. AC-3 and AC-4 for rejection. AC-5 and AC-16 for deadline and cleanup. AC-17 and AC-18 for network and credential isolation. |
| 2 | AC-6, AC-8, AC-9 and AC-24 for fixed analysis and artifacts. AC-10 and AC-32 for isolation. AC-21, AC-22, AC-23 and AC-29 for cleanup and artifact publication. AC-30 and the configured-model demo for real model and data parity. |

Transcripts record candidate SHA, gateway version, image digests, commands and sanitized results keyed by acceptance ID. Simulation counts only as unit evidence. Mark each unexecuted real-host check as pending when its host, image, policies, probe or approved model is unavailable.

## Slices

| PR | Scope | Rows |
|---|---|---|
| 1 | Local harness, shared registry, OpenShell JavaScript adapter, benchmark parity, runtime checks | AC-1 to AC-5, AC-11, AC-14 to AC-20, AC-26 |
| 2 | Voting fixture, Python analysis, configured model, artifacts and manifest | AC-6 to AC-10, AC-12, AC-13, AC-21 to AC-25, AC-27 to AC-33 |

In each PR description, expand the ranges to list every individual ID on its `Rows:` line.

## Acceptance

Every CLI invocation below uses a fresh output directory. Expected failure codes are read from the single stdout JSON object.

| ID | Given | When | Then (observable, exact) | Checked by |
|---|---|---|---|---|
| AC-1 | Fixed benchmark, both executors available | CLI `benchmark --executor compare` | Exit 0. | unit |
| AC-2 | Same benchmark | Read both `normalized_tool_receipts` arrays in `benchmark.json` | Both traces equal the four ordered tool names, arguments, statuses and source in the CLI contract. | unit |
| AC-3 | First requested tool is unregistered | Run the script in the test harness | `UNKNOWN_TOOL`, with zero successful tool receipts. | unit |
| AC-4 | Gateway request with absent, expired or wrong-run credential, or a valid credential scoped to a different snapshot | Attempt dispatch | HTTP 403 with `TOOL_DENIED` and zero handler receipts for the request. | unit |
| AC-5 | JavaScript job that exceeds the configured deadline | Run it in the test harness | `DEADLINE_EXCEEDED`. | unit |
| AC-6 | Fixed voting scripts, minimum 1, zero model credentials | CLI `voting --script fixed` | Exit 0. | unit |
| AC-7 | Fixed voting scripts, minimum 4,000 | Inspect CSV | Both data rows equal the minimum-4,000 rows under Fixture and output. | unit |
| AC-8 | A successful default voting run | Inspect chart | The decodable `ranking.png` and its rendering inputs match the four values, two sector labels, two series and axis label in Fixture and output. | unit |
| AC-9 | A successful fixed voting run | Read `run.json` | Fields match the CLI contract, including `executor: "openshell"`, `script_mode: "fixed"`, null model fields, minimum 1, the two ordered successful voting tool calls and hashes that match the inputs and outputs. | unit |
| AC-10 | Host probe reaches the private test service | Run the Python network probe | `PROBE_STARTED` is observed and the service records zero requests carrying the run marker. | unit |
| AC-11 | OpenShell gateway unconfigured or unreachable | CLI `benchmark --executor compare` | Exit 1 with `status: "failed"` and `error_code: "OPENSHELL_UNAVAILABLE"`. | unit |
| AC-12 | A test double for the configured model interface that returns the approved voting JavaScript | CLI `voting --script model` | The CSV is identical to the fixed default CSV. | unit |
| AC-13 | Prototype installed and idle, no gateway or prototype configuration, normal ARP app running | Request `GET /api/health` | HTTP 200 with `status: "ok"`. | unit |
| AC-14 | Fixed benchmark, both executors available | Compare both `result` objects in `benchmark.json` | Results are equal. | unit |
| AC-15 | An executor returns a different benchmark weight in the comparison | Run benchmark comparison | `RUNTIME_MISMATCH`. | unit |
| AC-16 | JavaScript job exceeded its deadline | Query its sandbox ID after the run ends | Sandbox is absent. | unit |
| AC-17 | Host probe reaches the private test service and a sandbox tool call reaches the approved gateway | Run the JavaScript network probe | `PROBE_STARTED` is observed and the service records zero requests carrying the run marker. | unit |
| AC-18 | Host process has distinct synthetic sentinel values for its model key and database credential | Run a JavaScript sandbox credential probe and inspect outputs | Neither sentinel appears in the sandbox or its outputs. The run credential is absent from CLI output, run files and logs. | unit |
| AC-19 | A registered synthetic tool is called 13 times in one sandbox run | Run JavaScript over the 12-request budget | `CALL_LIMIT` on request 13. | unit |
| AC-20 | JavaScript returns a JSON result larger than 16,384 UTF-8 bytes | Collect the result | `OUTPUT_LIMIT`. | unit |
| AC-21 | A Python job exceeds its configured deadline | Run it in the harness | `DEADLINE_EXCEEDED`. | unit |
| AC-22 | Python job exceeded its deadline | Query its sandbox ID after the run ends | Sandbox is absent. | unit |
| AC-23 | A failed voting run stages an output before failing | Inspect its output directory | Both `ranking.csv` and `ranking.png` are absent. | unit |
| AC-24 | Default fixed voting run, minimum 1 | Read `ranking.csv` | Header and both data rows equal the default fixture CSV. | unit |
| AC-25 | Fixed voting run, minimum 30,001 | Inspect the CSV issuer columns | Both issuer rates and ranks are empty and both included-issuer counts are zero. | unit |
| AC-26 | Fixed benchmark on the existing Dynamic Worker | Read `dynamic_worker.result` in `benchmark.json` | 12 constituents, total weight 7.24 percentage points, and top two sectors Information Technology 3.10 / SYN03 and Financials 1.40 / SYN07. | unit |
| AC-27 | Generated JavaScript alters one successful gateway aggregate before returning | Validate its result | `INVALID_RESULT`. | unit |
| AC-28 | Python output exceeds 5 MiB combined | Collect the artifacts | `OUTPUT_LIMIT`. | unit |
| AC-29 | Successful voting run | Query both recorded sandbox IDs | Both sandboxes are absent. | unit |
| AC-30 | The configured-model voting path completes | Read `run.json` and `code.js` | `script_mode: "model"`, matching `configured_model_id` and `model_id`, `model_cached: false`, empty `model_fallback_from`, and `javascript_sha256` matching the saved `code.js`. | unit |
| AC-31 | Existing Postgres Research Plans test setup without OpenShell | Run `pytest -q tests/test_plan_api_pg.py tests/test_plan_executor_pg.py` from `backend` | Exit 0 with no skipped tests. | unit |
| AC-32 | Host process has synthetic model-key, database and JavaScript run-credential sentinels | Run a Python sandbox credential probe | No sentinel appears in the Python sandbox or its outputs. | unit |
| AC-33 | Model mode with a stand-in, cached response, provider fallback, or mismatched model ID | Validate model provenance | `MODEL_PROVENANCE_MISMATCH` with no provisioned sandbox. | unit |

Regression scope is AC-2, AC-13, AC-26 and AC-31. The actual configured-model demonstration is a separate real-host evidence requirement in addition to AC-12 and AC-30, using the named question and matching the default fixture CSV.
