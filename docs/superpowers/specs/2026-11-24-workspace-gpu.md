# Workspace GPU: the backend's own models use a GPU when one is visible

Status: Draft, for owner approval
Slug: `workspace-gpu`
Risk: `risk:normal` (backend only; no auth, schema, money or workflow path)
Size: `S-M`, one PR, no slices

## Decisions for the owner

1. **The setting.** A new backend setting `ARP_MODEL_DEVICE` with the values `auto` (default), `cpu` and
   `cuda`. `auto` uses a GPU when one is visible and the CPU otherwise. `cpu` always uses the CPU, even with a
   GPU. `cuda` always uses the GPU and **fails loudly** on the first model load when there is none, with the
   exact messages in [Errors](#errors) (no silent fallback to the CPU). An unknown value counts as `auto` with one
   warning, the same rule as the compute service's `ARP_COMPUTE_DEVICE`, so the two read alike.
   *Recommended.* It is a separate setting from `ARP_COMPUTE_DEVICE`, which belongs to the separate compute
   service and is left alone. Rows AC-1 to AC-3 and AC-18 to AC-21 depend on this choice.
2. **How you see which device is used.** Recommended: `scripts/launch_jupyter.sh check` (that is,
   `arp preflight`) prints one more line, `ok local models: models on cuda; embeddings on cuda` (or the
   reason it is the CPU), and the backend log gets one line per model family on the first load
   (`models on cuda`). `GET /api/health` stays exactly as it is.
   *Why not a field in `/api/health`:* its exact body `{"status": "ok"}` is pinned by hidden tests of earlier
   specs (`test-stand-ins` AC-4 and AC-17, `bank-jupyter-launch` AC-5), it answers without sign-in so it would
   tell anyone about the hardware, and `check` is what you already run in the workspace. If you want the health
   field anyway, say so and rows AC-29 to AC-35, AC-47 and AC-48 change to health rows before approval.

Everything else is decided in [Defaults taken](#defaults-taken).

## Why

Steffen runs ARP from VS Code in a standardized gcloud AI workspace (Jupyter, plain Python process, `pip
install`). Some workspaces have a GPU. Only BuildKit is available there: no `docker run`, no compose, so the
separate compute service and its CUDA image cannot run in it. Today every model the backend loads itself
(embeddings, reranker, NLI, taggers, GLiNER, FinBERT) runs on the CPU even when a GPU sits idle next to it,
and nothing tells him which device is in use.

## What the user can do afterwards that they cannot do today

- Start ARP from VS Code on a GPU workspace and have embeddings, rerank, NLI, the taggers, GLiNER, FinBERT and
  docling run on the GPU, with no container and no compute service.
- Start the same install on a workspace without a GPU and have it run on the CPU, with no setting changed.
- Run `scripts/launch_jupyter.sh check` and read in one line which device the models use, and why it is the
  CPU when it is (no GPU, forced to CPU, or the GPU build of onnxruntime missing).
- Force the CPU (`ARP_MODEL_DEVICE=cpu`), for example to keep a shared GPU free, or force the GPU
  (`ARP_MODEL_DEVICE=cuda`) and get a clear error instead of a slow CPU run when the GPU is not there.
- Follow one documented pip line to get GPU embeddings in the workspace.

## Three versions

- **Safe:** the setting plus `device=` on the transformers models only (NLI, taggers, GLiNER, FinBERT).
  Embeddings and rerank stay on the CPU; nothing shows the device.
- **Strong:** every in-process loader, including fastembed (CUDA only when onnxruntime offers it) and docling,
  plus the log lines.
- **Most ambitious (specified here):** Strong, plus the `check` line that says which device each family uses
  and why, the loud `cuda` errors with the fix in the message, and the workspace install line in the docs.

Next step up, not specified: float16 or larger GPU batches with a stated speed-up. That needs a GPU runner in CI
to check a number; CI has none.

## What exists today (main `eb35110`)

- `backend/arp/models/local.py` loads everything in-process:
  - `_pipeline(task, e, **kwargs)` calls `transformers.pipeline(task, model=e.hf_id, revision=e.revision,
    **kwargs)`; `nli_scores` and `tag_scores` go through `_get`, which caches one pipeline per registry key in
    `_pipes`. A `device` kwarg arrives only from the compute server; `arp/models/capabilities.py` passes none.
  - `text_embedding(model_name)` builds `fastembed.TextEmbedding(model_name=model_name)`;
    `cross_encoder(model_name)` builds `fastembed.rerank.cross_encoder.TextCrossEncoder(model_name=model_name)`.
    fastembed 0.9 defaults `cuda` to `Device.AUTO`, so today it already tries CUDA whenever onnxruntime lists
    `CUDAExecutionProvider`, even with no GPU visible.
  - `span_scores(..., device=None)` builds GLiNER with `GLiNER.from_pretrained(...)` and calls `.to(device)`
    only when a device is given.
- `backend/arp/signal_lab/methods/finbert.py` `default_finbert()` builds `transformers.pipeline(
  "text-classification", model=model_name, top_k=None, truncation=True, max_length=512)`, no device.
- `backend/arp/ingestion/local_files.py` `_docling_converter(ocr)` (lru-cached) builds
  `PdfPipelineOptions(do_ocr=ocr)` with docling's default accelerator options (device `AUTO`, read from
  `DOCLING_DEVICE` when set).
- `backend/arp/preflight.py` `run_preflight` prints seven lines in a fixed order (`postgres`, `model …`,
  `verifier …`, `compute models`, `compute parse`, `frontend`, `fetch`), each `ok <name>`, `skip <name>` or
  `FAIL <name>: <reason>`. `scripts/launch_jupyter.sh check` runs it.
- `pyproject.toml`: `fastembed` and docling (which pulls torch) are core dependencies; `transformers`, `torch`
  and `gliner` are in the `models` and `finbert` extras. On Linux x86_64, the PyPI torch wheel already ships CUDA,
  so the torch models need no extra install for a GPU. Plain `onnxruntime` has no CUDA provider; GPU
  embeddings need `onnxruntime-gpu` in its place.
- No backend setting picks a device. The compute service has its own (`ARP_COMPUTE_DEVICE`, open PR #703).

## Goals

- G1. One setting, `ARP_MODEL_DEVICE` = `auto` | `cpu` | `cuda`, default `auto`, decides the device of every
  model the backend loads in-process.
- G2. `auto` puts the torch models (NLI, taggers, GLiNER, FinBERT) on `cuda` when torch sees a GPU, else `cpu`.
- G3. `auto` puts fastembed (embeddings, rerank) on CUDA only when torch sees a GPU **and** onnxruntime lists
  `CUDAExecutionProvider`; otherwise on the CPU, with no error.
- G4. `cpu` forces the CPU for every loader, docling included.
- G5. `cuda` with no usable GPU raises the exact errors below on the first model load and loads nothing.
- G6. An explicit `device=` passed to a `local.py` loader (the compute server does this) wins over the setting.
- G7. One log line per family on first use says which device it uses and why.
- G8. `arp preflight` (`launch_jupyter.sh check`) prints a `local models` line with the same information.
- G9. `docs/INSTALLATION.md` has the pip line for GPU embeddings in the workspace.

## Non-goals

- No change to the compute service: `backend/Dockerfile.compute`, `arp/compute/server.py`,
  `arp/cli/compute.py` and `tests/test_compute_*` are owned by open PR #703 and are not touched.
- No Docker image, compose file or container step. The workspace path is a plain pip install.
- No choice of a GPU index (`cuda:1`), no Apple `mps` for the torch models, no float16, no speed target.
- No change to `GET /api/health` (decision 2).
- No new pip extra: an extra cannot remove the CPU `onnxruntime` that `fastembed` requires, so the GPU build is
  a documented pip line instead.
- No change to when the cloud compute service is used instead of local models (`capabilities.py` routing).

## Anti-goals

- `cuda` never falls back to the CPU silently.
- Importing `arp.config`, `arp.models.local`, `arp.models.device` or `arp.preflight` never imports torch; a
  CPU install where torch cannot be imported still loads fastembed models.
- The device is never cached across a settings change: each loader resolves it from `get_settings()` when it
  builds a model.

## Design

### Setting (`backend/arp/config.py`)

`model_device: str = "auto"`, env `ARP_MODEL_DEVICE`, description "Device for the models the backend loads
itself: auto (GPU when visible, else CPU), cpu, or cuda (fail if no GPU)". A validator strips and lowercases the
value; an empty value (after stripping) counts as unset: `auto`, no warning. Anything else other than `auto`,
`cpu`, `cuda` becomes `auto` and logs one WARNING on logger `arp.config`:
`ARP_MODEL_DEVICE='<raw value>' is not auto, cpu or cuda; using auto` (`<raw value>` is the value as given,
before stripping, in Python `repr` quotes).

### Resolution (`backend/arp/models/device.py`, new)

- `class ModelDeviceError(RuntimeError)`.
- `torch_device() -> str` returns `"cpu"` or `"cuda"`:
  - setting `cpu`: `"cpu"`, without importing torch.
  - setting `auto`: `"cuda"` if `import torch` succeeds and `torch.cuda.is_available()` is true, else `"cpu"`.
  - setting `cuda`: `"cuda"` if both hold; raises `ModelDeviceError` with E1 when torch cannot be imported and
    E2 when `torch.cuda.is_available()` is false.
- `onnx_cuda() -> bool`:
  - setting `cpu`: `False`.
  - setting `auto`: `True` only if `torch_device()` would return `"cuda"` and `"CUDAExecutionProvider"` is in
    `onnxruntime.get_available_providers()`; else `False`.
  - setting `cuda`: `torch_device()` first (E1/E2 propagate); then `True` if the provider is listed, else raises
    `ModelDeviceError` with E3.
- `summary() -> str`: `"<models phrase>; <embeddings phrase>"`, phrases from the table below. It loads no model.
- `reset()`: forgets which log lines were already written (for tests).
- Every function reads `get_settings().model_device` on each call; torch and onnxruntime are imported inside
  the functions, looked up as `torch.cuda.is_available` and `onnxruntime.get_available_providers` at call time.

Phrases (also the log lines, logger `arp.models.device`, level INFO):

| Case | Models phrase | Embeddings phrase |
|------|---------------|-------------------|
| setting `cpu` | `models on cpu (ARP_MODEL_DEVICE=cpu)` | `embeddings on cpu (ARP_MODEL_DEVICE=cpu)` |
| torch cannot be imported (`auto`) | `models on cpu (torch not installed)` | `embeddings on cpu (torch not installed)` |
| torch sees no GPU (`auto`) | `models on cpu (no GPU visible)` | `embeddings on cpu (no GPU visible)` |
| GPU visible, no `CUDAExecutionProvider` (`auto`) | `models on cuda` | `embeddings on cpu (onnxruntime has no CUDAExecutionProvider)` |
| GPU visible, provider listed (`auto` or `cuda`) | `models on cuda` | `embeddings on cuda` |

The models line is logged the first time a torch-family loader (NLI, taggers, GLiNER, FinBERT) resolves
the device through `torch_device()`, the embeddings line the first time `text_embedding` or `cross_encoder` does;
each at most once per process until `reset()`. A loader given an explicit `device=` logs nothing.
Building the docling converter logs nothing (under `auto` docling picks its own device, so ARP cannot say which).
Only the loaders log: `torch_device()`, `onnx_cuda()` and `summary()` write nothing themselves, so
`onnx_cuda()` calling `torch_device()` writes no models line, and `arp preflight` writes no log line.

### Errors

- E1: `ARP_MODEL_DEVICE=cuda but torch is not installed; set ARP_MODEL_DEVICE=auto to fall back to the CPU`
- E2: `ARP_MODEL_DEVICE=cuda but no CUDA GPU is visible to torch; set ARP_MODEL_DEVICE=auto to fall back to the CPU`
- E3: `ARP_MODEL_DEVICE=cuda but onnxruntime has no CUDAExecutionProvider; run: pip uninstall -y onnxruntime && pip install onnxruntime-gpu`

Each is the whole `str()` of the `ModelDeviceError`, one line. The loader raises before it calls the model
library, so nothing is loaded or cached.

### Loaders

- `local._pipeline` / `_get` (NLI, taggers): if the caller passed no `device` kwarg, pass
  `device=torch_device()` to `transformers.pipeline`; a caller's `device` kwarg is passed unchanged and the
  setting is not read.
- `local.span_scores` / `_gliner`: with `device=None`, `_gliner` calls `torch_device()` **before**
  `GLiNER.from_pretrained`, then `.to(<that device>)`; with a device, `.to(device)` as today. `from gliner import
  GLiNER` stays inside the function.
- `local.text_embedding` / `local.cross_encoder`: call `TextEmbedding(model_name=name, cuda=onnx_cuda())` and
  `TextCrossEncoder(model_name=name, cuda=onnx_cuda())`; no other new argument.
- `finbert.default_finbert`: add `device=torch_device()` to its `transformers.pipeline(...)` call; the other
  arguments stay as they are.
- `local_files._docling_converter(ocr)`: setting `auto` builds `PdfPipelineOptions(do_ocr=ocr)` exactly as today
  (docling keeps choosing, `DOCLING_DEVICE` still works). Setting `cpu` passes
  `accelerator_options=AcceleratorOptions(device=AcceleratorDevice.CPU)`; setting `cuda` calls `torch_device()`
  first (E1/E2) and passes `AcceleratorDevice.CUDA`.

### Preflight (`backend/arp/preflight.py`)

A new check `local models`, sixth, between `compute parse` and `frontend`, so `run_preflight` returns eight
lines. It runs `summary()` through `asyncio.to_thread` under the existing timeout and loads no model. A check
may now return a detail string: `_line` writes `ok <name>: <detail>` when one is returned and `ok <name>` as
today when it returns `None` (every existing check returns `None`). On success the line is `ok local models: <summary()>`; on a
`ModelDeviceError` it is `FAIL local models: <message>` through the existing `_reason` (first line, 200
characters). The module docstring and `docs/INSTALLATION.md` say eight lines instead of seven.

### Docs (`docs/INSTALLATION.md`, Jupyter section)

A short "GPU workspace" paragraph: torch from PyPI on Linux already has CUDA, so the torch models use the GPU
with no change; for GPU embeddings run, inside the `arp` environment, the line

```
pip uninstall -y onnxruntime && pip install onnxruntime-gpu
```

and run it again after any later `pip install -e backend` (that reinstalls the CPU `onnxruntime`). Then
`scripts/launch_jupyter.sh check` should show `ok local models: models on cuda; embeddings on cuda`. The
`check` line in the code block changes from `# 7 lines` to `# 8 lines`. One sentence lists `ARP_MODEL_DEVICE`
and its three values.

## Defaults taken

- `auto` for docling keeps docling's own `AUTO` (so `DOCLING_DEVICE` and Apple `mps` keep working); only `cpu`
  and `cuda` override it.
- `auto` for fastembed also needs torch to see a GPU, because onnxruntime-gpu lists `CUDAExecutionProvider` even
  on a machine with no GPU. This also stops today's fastembed `Device.AUTO` from trying CUDA with no GPU.
- No onnxruntime-gpu version pin in the docs: the right build depends on the workspace's CUDA version, and pip
  picks one that matches the installed torch's CUDA in the common case.
- The device is resolved on every model build, not cached; models already built stay where they are until the
  process restarts (`_pipes` cache unchanged).
- The `cuda` errors are raised from the loader, so an API call that needs a model fails with the server's usual
  500 for an unhandled error; no new HTTP status.
- `ARP_COMPUTE_DEVICE` is not read by the backend. The compute server's torch and fastembed models get their
  device explicitly and ignore `ARP_MODEL_DEVICE`. Its parse path goes through `_docling_converter`, so it does
  read `ARP_MODEL_DEVICE`; nothing sets that in the compute image, so it stays `auto` there and behaves as today.

## Notes for the builder

- Test seams the hidden tests use (keep them looked up at call time): `transformers.pipeline`,
  `fastembed.TextEmbedding`, `fastembed.rerank.cross_encoder.TextCrossEncoder`, a `gliner` module placed in
  `sys.modules` (gliner is not installed in CI),
  `torch.cuda.is_available`, `onnxruntime.get_available_providers`; caches `arp.models.local._pipes` (a dict) and
  `arp.ingestion.local_files._docling_converter.cache_clear()`; `arp.config.get_settings.cache_clear()`;
  `arp.models.device.reset()`.
- Do not touch `backend/Dockerfile.compute`, `arp/compute/server.py`, `arp/cli/compute.py` or
  `tests/test_compute_*` (PR #703). The compute server keeps passing `device=` to `local.py`.
- `tests/test_preflight.py` asserts seven lines (lines 79, 87, 98, 108, 162); those change to eight. List them in the PR.
- Supersedes `2026-11-11-bank-jupyter-launch-design.md` AC-9 (exactly seven preflight lines); AC-29 below
  replaces it. That row is `unit`, so no hidden test retires.
- `openwiki/` needs an update for the new setting (the weekly refresh does it).

## Acceptance

Common Given for every row unless it says otherwise: settings from env with `arp.config.get_settings.cache_clear()`
after the env change; `arp.models.local._pipes` empty; `arp.models.device.reset()` called;
`DOCLING_DEVICE` unset; "GPU visible" = `torch.cuda.is_available` monkeypatched to return `True`, "no GPU" = to
return `False`; "provider listed" = `onnxruntime.get_available_providers` monkeypatched to return
`["CUDAExecutionProvider", "CPUExecutionProvider"]`, "provider not listed" = `["CPUExecutionProvider"]`.
"Stand-in pipeline" = `transformers.pipeline` replaced by a function that records its args and kwargs and returns
a callable answering `{"labels": ["a"], "scores": [0.5]}` for NLI and `[{"label": "a", "score": 0.5}]` for tags.
"Stand-in fastembed" = `fastembed.TextEmbedding` and `fastembed.rerank.cross_encoder.TextCrossEncoder` replaced
by classes that record their kwargs. "Stand-in GLiNER" = `sys.modules["gliner"]` set to a module whose
`GLiNER.from_pretrained` records its calls and returns an object that records each `.to(x)` argument, returns
itself and answers `predict_entities` with `[]`.
`E1`, `E2`, `E3` are the exact texts in [Errors](#errors).

### Setting

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | `ARP_MODEL_DEVICE` unset | `get_settings().model_device` | `"auto"` | holdout |
| AC-2 | `ARP_MODEL_DEVICE=" CUDA "` | `get_settings().model_device` | `"cuda"` | holdout |
| AC-3 | `ARP_MODEL_DEVICE=gpu` | `get_settings().model_device` | `"auto"` | holdout |
| AC-38 | `ARP_MODEL_DEVICE=gpu`, log captured | `get_settings()` | exactly one WARNING record on logger `arp.config` with message `ARP_MODEL_DEVICE='gpu' is not auto, cpu or cuda; using auto` | holdout |
| AC-39 | `ARP_MODEL_DEVICE=""`, log captured | `get_settings().model_device` | `"auto"`; no WARNING record on logger `arp.config` | holdout |

### Torch models

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-4 | `auto`, GPU visible, stand-in pipeline | `local.nli_scores(entry("nli"), ["t"], ["a"], "{}")` | the pipeline was called once with kwarg `device="cuda"` | holdout |
| AC-5 | `auto`, no GPU, stand-in pipeline | `local.nli_scores(entry("nli"), ["t"], ["a"], "{}")` | the pipeline was called once with kwarg `device="cpu"` | holdout |
| AC-6 | `cpu`, GPU visible, stand-in pipeline | `local.nli_scores(entry("nli"), ["t"], ["a"], "{}")` | the pipeline was called once with kwarg `device="cpu"` | holdout |
| AC-7 | `auto`, GPU visible, stand-in pipeline, `k` the key of any registry entry with capability `tag` | `local.tag_scores(entry(k), ["t"])` | the pipeline was called once with kwarg `device="cuda"` | holdout |
| AC-8 | `auto`, GPU visible, stand-in GLiNER | `local.span_scores(entry("gliner"), ["t"], ["a"], 0.5)` | `.to` was called exactly once, with `"cuda"`; result `[[]]` | holdout |
| AC-9 | `cuda`, no GPU, stand-in GLiNER | `local.span_scores(entry("gliner"), ["t"], ["a"], 0.5, device="cpu")` | no exception; `.to` was called exactly once, with `"cpu"` (explicit device wins; must not change for the compute server) | holdout |
| AC-10 | `cuda`, no GPU, stand-in pipeline | `local.nli_scores(entry("nli"), ["t"], ["a"], "{}", device=0)` | no exception; the pipeline was called once with kwarg `device=0` (must not change) | holdout |
| AC-11 | `auto`, GPU visible, stand-in pipeline | `default_finbert()` (from `arp.signal_lab.methods.finbert`) | the pipeline was called once with args `("text-classification",)` and kwargs exactly `{model: "ProsusAI/finbert", top_k: None, truncation: True, max_length: 512, device: "cuda"}` | holdout |
| AC-40 | `cpu`, GPU visible, stand-in GLiNER | `local.span_scores(entry("gliner"), ["t"], ["a"], 0.5)` | `.to` was called exactly once, with `"cpu"` | holdout |
| AC-41 | `cpu`, GPU visible, stand-in pipeline | `default_finbert()` | the pipeline was called once with kwarg `device="cpu"` | holdout |
| AC-42 | `cpu`, GPU visible, stand-in pipeline, `k` a tag entry key | `local.tag_scores(entry(k), ["t"])` | the pipeline was called once with kwarg `device="cpu"` | holdout |

### Embeddings and rerank (fastembed)

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-12 | `auto`, GPU visible, provider listed, stand-in fastembed | `local.text_embedding("m")` | `TextEmbedding` built once with kwargs exactly `{model_name: "m", cuda: True}` | holdout |
| AC-13 | `auto`, GPU visible, provider not listed, stand-in fastembed | `local.text_embedding("m")` | no exception; kwargs exactly `{model_name: "m", cuda: False}` | holdout |
| AC-14 | `auto`, no GPU, provider listed, stand-in fastembed | `local.text_embedding("m")` | kwargs exactly `{model_name: "m", cuda: False}` | holdout |
| AC-15 | `auto`, GPU visible, provider listed, stand-in fastembed | `local.cross_encoder("r")` | `TextCrossEncoder` built once with kwargs exactly `{model_name: "r", cuda: True}` | holdout |
| AC-16 | `cpu`, GPU visible, provider listed, stand-in fastembed | `local.text_embedding("m")` then `local.cross_encoder("r")` | both built with `cuda: False` | holdout |
| AC-17 | `auto`, `sys.modules["torch"] = None` (torch cannot be imported), provider listed, stand-in fastembed | `local.text_embedding("m")` | no exception; kwargs exactly `{model_name: "m", cuda: False}` (CPU install without torch keeps working) | holdout |

### Forced cuda without a GPU

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-18 | `cuda`, no GPU, stand-in pipeline | `local.nli_scores(entry("nli"), ["t"], ["a"], "{}")` | raises `arp.models.device.ModelDeviceError` (a `RuntimeError`) with `str()` exactly E2; the pipeline was not called; `_pipes` is empty | holdout |
| AC-19 | `cuda`, `sys.modules["torch"] = None`, stand-in GLiNER | `local.span_scores(entry("gliner"), ["t"], ["a"], 0.5)` | raises `ModelDeviceError` with `str()` exactly E1; `from_pretrained` was not called | holdout |
| AC-20 | `cuda`, GPU visible, provider not listed, stand-in fastembed | `local.text_embedding("m")` | raises `ModelDeviceError` with `str()` exactly E3; `TextEmbedding` was not built | holdout |
| AC-21 | `cuda`, GPU visible, provider listed, stand-in fastembed | `local.text_embedding("m")` | `TextEmbedding` kwargs exactly `{model_name: "m", cuda: True}` | holdout |
| AC-43 | `cuda`, GPU visible, stand-in pipeline | `local.nli_scores(entry("nli"), ["t"], ["a"], "{}")` | the pipeline was called once with kwarg `device="cuda"` | holdout |

### Docling

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-22 | `auto`, GPU visible, `_docling_converter.cache_clear()` | `_docling_converter(True).format_to_options[InputFormat.PDF].pipeline_options.accelerator_options.device` | `AcceleratorDevice.AUTO` (must not change) | holdout |
| AC-23 | `cpu`, GPU visible, cache cleared | same expression | `AcceleratorDevice.CPU` | holdout |
| AC-24 | `cuda`, GPU visible, cache cleared | same expression | `AcceleratorDevice.CUDA` | holdout |
| AC-25 | `cuda`, no GPU, cache cleared | `_docling_converter(True)` | raises `ModelDeviceError` with `str()` exactly E2 | holdout |

### Log lines

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-26 | `auto`, GPU visible, provider listed, stand-ins, log captured at INFO | `nli_scores` on `entry("nli")`, then `tag_scores` on a tag entry, then `text_embedding("m")`, then `cross_encoder("r")` | records on logger `arp.models.device`: exactly two, in order `models on cuda`, `embeddings on cuda` | holdout |
| AC-27 | `auto`, no GPU, provider listed, stand-ins, log captured | `nli_scores` on `entry("nli")`, then `text_embedding("m")` | exactly `models on cpu (no GPU visible)`, `embeddings on cpu (no GPU visible)` | holdout |
| AC-28 | `cpu`, GPU visible, stand-ins, log captured | `nli_scores` on `entry("nli")`, then `text_embedding("m")` | exactly `models on cpu (ARP_MODEL_DEVICE=cpu)`, `embeddings on cpu (ARP_MODEL_DEVICE=cpu)` | holdout |
| AC-44 | `cuda`, GPU visible, stand-in pipeline, log captured | `local.nli_scores(entry("nli"), ["t"], ["a"], "{}", device=0)` | 0 records on logger `arp.models.device` | holdout |
| AC-45 | `auto`, GPU visible, `_docling_converter.cache_clear()`, log captured | `_docling_converter(True)` | 0 records on logger `arp.models.device` | holdout |
| AC-46 | `auto`, GPU visible, provider listed, stand-in fastembed | `local.text_embedding("m")`; then env `ARP_MODEL_DEVICE=cpu`, `get_settings.cache_clear()`, `_pipes.clear()`; then `local.text_embedding("m")` | the second `TextEmbedding` was built with kwargs exactly `{model_name: "m", cuda: False}` (device not cached across a settings change) | holdout |
| AC-49 | `auto`, GPU visible, provider listed, stand-in fastembed, log captured | `local.text_embedding("m")` only | exactly one record on `arp.models.device`: `embeddings on cuda` | holdout |
| AC-50 | `cuda`, GPU visible, `_docling_converter.cache_clear()`, log captured | `_docling_converter(True)` | 0 records on logger `arp.models.device` | holdout |
| AC-51 | Same as AC-30, log captured | Run preflight | 0 records on logger `arp.models.device` | holdout |

### Preflight (`launch_jupyter.sh check`)

"Run preflight" = `asyncio.run(arp.preflight.run_preflight(get_settings(), llm_factory=<stand-in whose client
raises RuntimeError("x")>, http=<httpx.AsyncClient on a MockTransport answering 200>))`, compute URLs unset.
Other lines may be `ok`, `skip` or `FAIL`; the rows check only what they name.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-29 | `auto`, GPU visible, provider not listed, stand-in pipeline and fastembed | Run preflight | 8 lines; line 6 is exactly `ok local models: models on cuda; embeddings on cpu (onnxruntime has no CUDAExecutionProvider)` | holdout |
| AC-47 | Same as AC-29 | Run preflight | line 5 is exactly `skip compute parse`; line 7 is exactly `ok frontend`; line 8 is exactly `ok fetch` (order kept) | holdout |
| AC-48 | Same as AC-29 | Run preflight | the stand-in pipeline and stand-in fastembed classes were called 0 times | holdout |
| AC-30 | `auto`, GPU visible, provider listed | Run preflight | line 6 is exactly `ok local models: models on cuda; embeddings on cuda` | holdout |
| AC-31 | `auto`, no GPU, provider listed | Run preflight | line 6 is exactly `ok local models: models on cpu (no GPU visible); embeddings on cpu (no GPU visible)` | holdout |
| AC-32 | `cpu`, GPU visible | Run preflight | line 6 is exactly `ok local models: models on cpu (ARP_MODEL_DEVICE=cpu); embeddings on cpu (ARP_MODEL_DEVICE=cpu)` | holdout |
| AC-33 | `cuda`, no GPU | Run preflight | line 6 is exactly `FAIL local models: ` followed by E2 | holdout |
| AC-34 | `cuda`, no GPU; `arp.preflight.run_preflight` replaced by a stand-in that calls `on_line` with the real line 6 text of AC-33 and returns it in a one-item list | `arp preflight` through Typer's `CliRunner` | exit code 1; output contains that line | holdout |

### Must not change

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-35 | In-process `fastapi.testclient.TestClient(arp.api.main.app)` without lifespan; env `ARP_MODEL_DEVICE=cuda`, settings cache cleared, no GPU, `ARP_STANDINS_DIR` unset | `GET /api/health` | 200, body exactly `{"status": "ok"}` | holdout |
| AC-36 | A fresh `python -I` process in `backend/` | `import arp.config, arp.models.local, arp.models.device, arp.preflight; import sys; print("torch" in sys.modules)` | prints `False` | holdout |

### Docs

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-37 | The PR head | read `docs/INSTALLATION.md` | contains the line `pip uninstall -y onnxruntime && pip install onnxruntime-gpu`, the text `ARP_MODEL_DEVICE`, and the line `scripts/launch_jupyter.sh check   # 8 lines; each should start with "ok" (or "skip" for an unset GPU service)`; no longer contains `# 7 lines` | holdout |
