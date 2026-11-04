# Long-document golden cases (with distractors)

Status: draft, awaiting owner approval.

## Goal

The bundled golden set (`backend/arp/golden_set/data/extraction_cases.json`) has 5 cases of about 300 characters each:
one passage per document. It checks the extractor's reading, but not what real filings test: finding the one
passage that answers a field among many, next to similar-looking numbers. It also cannot show what the evidence
gate saves, since the gate skips fields with 3 passages or fewer (the 2026-11-02 run: 16,595 vs 16,601 tokens).

Idea taken from Ragas' test-set generation (`src/ragas/testset/`) and noise-sensitivity metric
(`metrics/_noise_sensitivity.py`): realistic multi-passage cases with distractors. Not copied: Ragas lets an LLM write
the gold answers. Here every answer is checked by a person, and these cases are written by hand from public filings.

## Design

1. **A second bundled file**, `backend/arp/golden_set/data/long_cases.json`, same `GoldenSetCase` shape, 6 cases.
   `load_cases` gains a `long: bool = False` argument; `arp golden-set run --long` loads it instead of the default file.
2. **Each case:**
   - `document_text` is an excerpt of a real public SEC filing (10-K or 20-F, from EDGAR), at least 50,000
     characters, so `chunk_document` with default settings (3,500-character passages, 300 overlap) yields at least
     15 passages;
   - exactly one passage states the answer;
   - `notes` follows a fixed format, one item per line: `Source: <accession number>, Item <n>, Section: <name>`;
     `Answer: "<sentence quoted from the filing>"` (or `Near-miss: "<sentence>"` for the not-disclosed case);
     `Distractor: "<sentence quoted from the filing>"` (the same metric for another year, the figure in another
     unit or scale, or a sub-total), in a passage other than the answer's;
   - `description` starts with one tag naming its trap.
   The 6 tags, each used once: `[prior-year]` (prior-year figure next to the current one), `[units]` (thousands vs
   millions), `[segment]` (segment sub-total vs company total), `[table]` (a figure in a table vs prose),
   `[footnote]` (a value only in a footnote), `[not-disclosed]` (the field is not disclosed; a near-miss figure is).
3. **Checked by people.** The implementer writes the cases and quotes each answer's sentence in `notes`; the owner
   approves them in the PR review. No model writes gold answers.
4. **A validation test** (no model calls) checks every long case against the rows AC-3 to AC-9 below.
5. **CI** (`.github/workflows/golden-set.yml`):
   - the existing "Run the golden set" step also runs `arp golden-set run --long`; both must pass;
   - the evidence gate comparison step runs `--gate off` and `--gate on` on the long set too, and fails unless gate-on
     extractor input tokens are at least 10% below gate-off on the long set (AC-33 of the evidence-gate spec comes
     back, now on cases where the gate can act). The short set keeps today's accuracy-only check.
6. **Cost note.** The long set adds roughly 6 x 15 passages x ~900 tokens ≈ 80k extractor input tokens per run, plus
   the verifier. It runs only where the golden set already runs (PRs touching extraction code, and manual runs).

## Out of scope

Generating cases with a model, more than 6 cases, multi-field or multi-document cases, non-English filings, changing
the short set, the review-queue flow for gold answers.

## Acceptance

"Passages" below means what `chunk_document` returns for the case's text and `doc_type` with default settings;
"occurs in" means an exact substring match after collapsing runs of whitespace to one space.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | The repo | `load_cases(long=True)` | Returns 6 `GoldenSetCase` objects | unit |
| AC-2 | The repo | `load_cases()` | Returns the same 5 short cases as before this change (case ids and expected values) | unit |
| AC-3 | Each long case | Validation test | `len(document_text) >= 50000` | unit |
| AC-4 | Each long case | Validation test | ≥ 15 passages | unit |
| AC-5 | Each long case except `[not-disclosed]` | Validation test | `notes` has an `Answer: "<s>"` line, and `<s>` occurs in exactly 1 passage | unit |
| AC-6 | The `[not-disclosed]` case | Validation test | `notes` has a `Near-miss: "<s>"` line, and `<s>` occurs in ≥ 1 passage | unit |
| AC-7 | Each long case | Validation test | `notes` has a `Distractor: "<s>"` line; `<s>` occurs in ≥ 1 passage, none of which is the passage holding the `Answer:` sentence (for `[not-disclosed]`, the `Near-miss:` sentence) | unit |
| AC-8 | Each long case | Validation test | `notes` has a `Source:` line matching `\d{10}-\d{2}-\d{6}, Item \S+, Section: .+` | unit |
| AC-9 | The long set | Validation test | Each `description` starts with one of `[prior-year]`, `[units]`, `[segment]`, `[table]`, `[footnote]`, `[not-disclosed]`, and each tag is used exactly once | unit |
| AC-10 | The long set | Validation test | Exactly 1 case has `expect_not_disclosed: true`; it has `expected_value: null` and the `[not-disclosed]` tag | unit |
| AC-11 | A stub model | `arp golden-set run --long` | Stdout has exactly 6 per-case lines, one per long case id, none for a short case id | unit |
| AC-12 | The workflow file | Parsed in a test | The "Run the golden set" step's script runs both `arp golden-set run` and `arp golden-set run --long`, and exits non-zero if either does (`set -eo pipefail`) | unit |
| AC-13 | Real models (CI, key set) | `arp golden-set run --long` | Exits 0 | golden |
| AC-14 | Real models | `arp golden-set run --long --gate off` | Exits 0 | golden |
| AC-15 | Real models | `arp golden-set run --long --gate on` | Exits 0 | golden |
| AC-16 | Real models, the two long gate runs | CI reads `extractor input tokens: N` from each run's last line | Gate-on N ≤ 0.9 × gate-off N | golden |
| AC-17 | Real models | `arp golden-set run` (short set) | Exits 0 | golden |
| AC-18 | The workflow file | Parsed in a test | The short-set gate comparison has no token threshold (as on `main`) | unit |
| AC-19 | The PR | Owner review | For each case the owner confirms the quoted Answer/Near-miss and Distractor sentences against EDGAR at the given accession number, and approves the expected value | evaluator |
| AC-21 | The long-set comparison script, given two fixture last lines with gate-on/gate-off ratio 0.95 and then 0.85 | Run | Exits 1, then exits 0 | unit |
| AC-20 | Existing suites | CI | No existing test function is removed or changed (`git diff origin/main -- backend/tests` adds only), and the suite passes | unit |

Must not change: the short set (AC-2, AC-17), the short-set gate check (AC-18), existing tests (AC-20).
