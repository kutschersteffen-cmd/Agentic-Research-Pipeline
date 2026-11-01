# Model stack across ARP

Spec slug: `model-stack`.

## Why

Today ARP uses two model types: LLMs through `arp/llm`, and an embedding model plus an optional cross-encoder
in retrieval (`arp/retrieval/embeddings.py`, `rerank.py`), both of which can run on the Cloud Run L4 service
`arp-models` (`arp/compute/`). A survey on 2026-11-01 (page: https://claude.ai/artifact/DUUhQijNB2HLsa5M2ttxLJ)
found other model families that fit most ARP functions: zero-shot classifiers, span extractors, domain
classifiers (ClimateBERT, FinBERT, ESG taggers), topic models, speech, document vision and classic ML. They
are cheap per call, but each function wiring its own model would mean many loaders, many caches and no
shared way to test them.

This spec is the umbrella: one shared model layer, the rule every integration follows, and the order in which
functions get them. Each integration is then its own small spec, gated on a golden-set gain.

## Goals

1. One shared model layer, `arp/models/`, that every ARP function calls for non-LLM model work:
   `embed`, `rerank`, `classify` (zero-shot NLI against caller-given labels), `spans` (GLiNER entity spans)
   and `tag` (a named fine-tuned classifier from a closed registry).
2. Each capability runs on the `arp-models` Cloud Run service when `compute_models_url` is set and locally
   otherwise, with the existing `compute/client.py` fallback rule: a cloud failure costs speed, never a run.
3. A model registry file naming every allowed model, its version (Hugging Face revision) and its capability,
   so a run records exactly which model produced each output.
4. An integration roadmap across all ARP functions, with an entry rule each integration must pass.

## Non-goals

- Any function integration itself. Each is a child spec (table below); the first is
  `2026-11-01-company-risk-view-design.md`.
- Replacing LLM steps. Encoders pre-filter, match, tag and extract spans; LLMs keep planning, field extraction
  and writing.
- Speech, document vision, topic models, classic ML and asset data in the shared layer. They differ too much in
  input and lifecycle; they come with their own child specs (phases 3–4) and may join the layer later.
- Training or fine-tuning pipelines. `tag` serves already-trained models from the registry only.
- UI. Model provenance shows in run JSON and logs only.

## Anti-goals

- A function loading a Hugging Face model directly instead of going through `arp/models/`.
- A model name or revision that is not in the registry.
- An encoder output entering a published fact or score without the same review path LLM output takes today.

## Design

### Shared layer (`backend/arp/models/`)

| Function | Signature | Backed by |
|---|---|---|
| `embed` | `embed(texts) -> (ndarray, provenance)` | loader moved from `retrieval.embeddings` into `arp/models/`; `retrieval/*` now calls `models.embed`; cloud via `compute.client.embed` |
| `rerank` | `rerank(query, texts) -> (list[float], provenance)` | loader moved from `retrieval.rerank` into `arp/models/`; cloud via `compute.client.rerank_scores` |
| `classify` | `classify(texts, labels, hypothesis="This text is about {}.") -> (list[dict[label, score]], provenance)` | registry entry `nli` (default `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`) |
| `spans` | `spans(texts, labels, threshold=0.5) -> (list[list[{label, text, start, end, score}]], provenance)` | registry entry `gliner` (default `urchade/gliner_multi-v2.1`) |
| `tag` | `tag(model_key, texts) -> (list[{label, score}], provenance)` | registry entries such as `climate_detector`, `climate_commitment`, `finbert_fls`, `esg_topics` |

- Registry: `backend/arp/models/registry.json`, entries `{key, capability, hf_id, revision, labels?}`.
- Cloud: `arp-models` (`compute/server.py`) gains `/classify`, `/spans`, `/tag`, each taking `x-arp-model` with
  the registry `hf_id@revision` and refusing a mismatch (as `/embed` and `/rerank` do today).
- Local fallback: the same model loaded on CPU on first use. A capability whose cloud call fails cools down for
  `COOLDOWN_S`, as in `compute/client.py`.
- Cache: results keyed by `(registry key, revision, sha256(text), labels)` in the existing content-store cache
  directory, so reruns of a batch cost nothing.
- Provenance: every call returns a tuple `(results, provenance)`, provenance = `{"model": key, "revision": ..., "where": "cloud"|"local"}`.
  Copying it into run output is each child spec's job.
- A registry entry whose `hf_id` is not on the allow-list `backend/arp/models/allowed.txt` raises `ValueError` at
  load time, for every capability.
- New dependencies: `transformers`, `gliner` in `backend/pyproject.toml` (local path) and the `arp-models` image.

### Rule for every integration (child specs)

1. Behind a setting that defaults to off (`ARP_MODELS_<FUNCTION>_ENABLED`).
2. A golden-set or retrieval-gold-set comparison with the setting on vs off, in the child spec's acceptance table.
3. Turned on by default only if it improves that score or cuts LLM tokens by ≥ 30% with no score loss.
4. Encoder output reaches a published fact or score only through the review path LLM output takes today; each
   child spec carries its own row for this, and for copying provenance into run output.

### Integration roadmap

Function numbers follow `README.md`. Each row becomes one child spec.

| Phase | ARP function | Models | What it changes |
|---|---|---|---|
| 1 | Stewardship: company risk view | headings (no model), LLM, `classify`, `embed` | Risks, mitigations, theme and year-on-year change per report (child spec `company-risk-view`) |
| 1 | Retrieval (#3, #8) | `embed` upgrade to `bge-m3` | Better evidence hit rate; checked on `backend/tests/golden/retrieval/` |
| 2 | Data-Point Extraction (#3) | `classify` | Drop passages that cannot hold the field before the LLM call |
| 2 | Transition Plan (#8) | `tag` (`climate_commitment`, `climate_specificity`, `finbert_fls`) | Pre-sort passages into talk vs walk before the verdict |
| 2 | Emerging Themes (#12) | `embed`, `classify` | Better clustering; zero-shot action-vs-mention gate |
| 2 | Document Discovery (#6) | `classify` | Document type from title and first page before download |
| 2 | Proxy voting | `classify` | Agenda items and shareholder proposals mapped to policy issues |
| 2 | Review queue | `rerank` / `classify` | Score whether a quote supports its value; doubtful items first |
| 3 | Thematic Universe (#1), Taxonomy Library (#2) | `embed`, `rerank` | Shortlist companies before the debate; suggest industry-code crosswalk rows |
| 3 | Identity Resolution (#5), company graph | `spans`, `rerank` | Name candidates and supplier edges from text |
| 3 | Stewardship triggers | `tag` (`esg_topics`), `classify` | Controversy signals from news in place of the static list |
| 3 | Financials (#4) | `spans` | Pre-mark segment names and capex purposes |
| 3 | Speech (new source) | Whisper (own spec) | Earnings-call and AGM transcripts as documents |
| 3 | Emerging Themes (#12) | BERTopic (own spec) | Labelled clusters over time |
| 4 | Risk view, extraction | ColPali or a vision LLM (own spec) | ESRS matrices, heat maps and tables from page images |
| 4 | Stewardship ranking, review queue | LightGBM + conformal prediction (own spec) | Engagement-success estimate; only uncertain values go to review |
| 4 | Transition Plan, risk view | Climate TRACE / asset data (own spec) | Independent check of stated emissions |
| 4 | Any LLM step | Small open LLM on the L4 (own spec) | In-house option where documents may not leave |
| – | Decision Studio (#15), Index (#16), Indirect Exposure (#7), XBRL (#18) | none | Numbers only by design; no change |

## Left to the builder

Batch sizes per capability; how `classify` splits long texts (truncate at the model's limit is acceptable).

## Acceptance

All `unit` rows use small stand-in models or stubbed HTTP, never real downloads.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | `compute_models_url` unset, registry `nli` pointing to a stand-in model | `models.classify(["a"], ["x", "y"])` | The results list holds one dict with exactly the keys `x` and `y`; provenance `where` = `local` | unit |
| AC-2  | `compute_models_url` set, `/classify` stubbed to return scores | `models.classify(...)` | Results equal the stubbed scores; provenance `where` = `cloud` | unit |
| AC-3  | `compute_models_url` set, `/classify` stubbed to return HTTP 500 | `models.classify(...)` twice within `COOLDOWN_S` | The stub receives exactly 1 request | unit |
| AC-4  | Same as AC-3 | second call | Provenance `where` = `local` | unit |
| AC-5  | `/spans` stubbed to return `{label: "risk", text: "credit risk", start: 14, end: 25}` | `models.spans(["We reduce the credit risk"], ["risk"])` | Results hold exactly that span | unit |
| AC-6  | `/spans` stubbed to return a span whose `text` ≠ `input[start:end]` | `models.spans(...)` | Results hold no span | unit |
| AC-7  | `models.tag("not_in_registry", ["a"])` | call | Raises `KeyError` whose message contains `not_in_registry` | unit |
| AC-8  | Registry entry `nli` with an `hf_id` absent from `allowed.txt` | `models.classify(["a"], ["x"])` | Raises `ValueError` whose message contains that `hf_id` | unit |
| AC-9  | `arp-models` server, `x-arp-model` ≠ the registry `hf_id@revision` | POST `/classify` | HTTP 409 | unit |
| AC-10 | Same as AC-9 | POST `/spans` | HTTP 409 | unit |
| AC-11 | Same as AC-9 | POST `/tag` | HTTP 409 | unit |
| AC-12 | A counting stand-in model | `models.classify(["a"], ["x"])` called twice | The stand-in is invoked exactly once | unit |
| AC-13 | Same as AC-12 | second call | Second results equal the first | unit |
| AC-14 | Any `classify`, `spans` or `tag` call | call | Provenance has keys `model`, `revision`, `where`; `revision` equals the registry entry | unit |
| AC-15 | Fixture `backend/tests/models/fixtures/main_vectors.npz`, produced on `main` with the stand-in embedding and rerank models | `models.embed` and `models.rerank` on the fixture inputs | `numpy.allclose(result, fixture, atol=1e-6)` is true for both | unit |
| AC-16 | The repo after this change | `grep -rnE "from_pretrained\|TextEmbedding\(\|GLiNER\(\|transformers\.pipeline\(\|pipeline\(\"" backend/arp --include=*.py` | Every hit is under `backend/arp/models/` or is `backend/arp/compute/server.py` | unit |
| AC-17 | The existing backend test suite on `main` | `python3 -m pytest backend/tests` on this branch, excluding `backend/tests/models/` | Same pass/fail result per test as on `main` | unit |
| AC-18 | The PR | `git diff --name-only origin/main -- backend/tests ':!backend/tests/models'` | Prints nothing | unit |
| AC-19 | Retrieval gold set, real models; `recall_at_12` from `arp golden-set retrieval --out <json>` on `main` recorded in the PR description before the change | same command on this branch | `recall_at_12` ≥ the recorded `main` value − 0.01 | golden |

Must not change: retrieval results, extraction, transition-plan and stewardship behaviour (AC-15, AC-17, AC-18, AC-19).
