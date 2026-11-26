"""ARP_MODEL_DEVICE: which device the in-process models load on (stand-in loaders; CI has no GPU)."""
import logging
import sys
import types

import pytest

from arp.config import get_settings
from arp.models import device, local


class _Rec:
    def __init__(self):
        self.calls = []

    def __call__(self, *a, **k):
        self.calls.append((a, k))
        return lambda texts, **kw: [{"label": "a", "score": 0.5} for _ in texts]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("ARP_MODEL_DEVICE", raising=False)
    get_settings.cache_clear()
    local._pipes.clear()
    device.reset()
    yield
    get_settings.cache_clear()
    local._pipes.clear()


def _env(monkeypatch, mode, gpu, provider=True):
    import onnxruntime
    import torch

    if mode is not None:
        monkeypatch.setenv("ARP_MODEL_DEVICE", mode)
    get_settings.cache_clear()
    monkeypatch.setattr(torch.cuda, "is_available", lambda: gpu)
    monkeypatch.setattr(onnxruntime, "get_available_providers",
                        lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"] if provider else ["CPUExecutionProvider"])


def _fastembed(monkeypatch):
    import fastembed
    from fastembed.rerank import cross_encoder

    built = []

    class _E:
        def __init__(self, **kw):
            built.append(kw)

    monkeypatch.setattr(fastembed, "TextEmbedding", _E)
    monkeypatch.setattr(cross_encoder, "TextCrossEncoder", _E)
    return built


def test_setting_values(monkeypatch, caplog):
    assert get_settings().model_device == "auto"
    for raw, want in ((" CUDA ", "cuda"), ("", "auto"), ("gpu", "auto")):
        monkeypatch.setenv("ARP_MODEL_DEVICE", raw)
        get_settings.cache_clear()
        with caplog.at_level(logging.WARNING, logger="arp.config"):
            caplog.clear()
            assert get_settings().model_device == want
        warned = [r.getMessage() for r in caplog.records if r.name == "arp.config"]
        assert warned == (["ARP_MODEL_DEVICE='gpu' is not auto, cpu or cuda; using auto"] if raw == "gpu" else [])


@pytest.mark.parametrize(("mode", "gpu", "want"), [("auto", True, "cuda"), ("auto", False, "cpu"), ("cpu", True, "cpu"),
                                                    ("cuda", True, "cuda")])
def test_fastembed_follows_torch_device(monkeypatch, mode, gpu, want):
    _env(monkeypatch, mode, gpu)
    built = _fastembed(monkeypatch)
    local.text_embedding("m")
    local.cross_encoder("r")
    assert built == [{"model_name": "m", "cuda": want == "cuda"}, {"model_name": "r", "cuda": want == "cuda"}]


def test_auto_without_provider_or_torch_is_cpu_not_an_error(monkeypatch):
    _env(monkeypatch, "auto", True, provider=False)
    built = _fastembed(monkeypatch)
    local.text_embedding("m")
    monkeypatch.setitem(sys.modules, "torch", None)
    local.text_embedding("n")
    assert built == [{"model_name": "m", "cuda": False}, {"model_name": "n", "cuda": False}]


def test_cuda_errors_load_nothing(monkeypatch):
    built = _fastembed(monkeypatch)
    _env(monkeypatch, "cuda", False)
    with pytest.raises(device.ModelDeviceError, match="no CUDA GPU is visible to torch; set ARP_MODEL_DEVICE=auto"):
        local.text_embedding("m")
    _env(monkeypatch, "cuda", True, provider=False)
    with pytest.raises(device.ModelDeviceError, match="pip uninstall -y onnxruntime && pip install onnxruntime-gpu"):
        local.text_embedding("m")
    monkeypatch.setitem(sys.modules, "torch", None)
    with pytest.raises(device.ModelDeviceError, match="torch is not installed"):
        device.torch_device()
    assert built == [] and local._pipes == {}


def test_pipeline_device_and_explicit_wins(monkeypatch, caplog):
    _env(monkeypatch, "auto", True)  # imports torch first: that can swap the transformers module in sys.modules
    rec = _Rec()
    fake = types.ModuleType("transformers")
    fake.pipeline = lambda *a, **k: rec(*a, **k)
    monkeypatch.setitem(sys.modules, "transformers", fake)
    e = types.SimpleNamespace(key="t", hf_id="x", revision="r")
    with caplog.at_level(logging.INFO, logger="arp.models.device"):
        local.tag_scores(e, ["t"])
        local._pipes.clear()
        local.tag_scores(e, ["t"], device=0)
    assert [c[1]["device"] for c in rec.calls] == ["cuda", 0]
    assert [r.getMessage() for r in caplog.records] == ["models on cuda"]


def test_gliner_device(monkeypatch):
    seen = []

    class _M:
        def to(self, d):
            seen.append(d)
            return self

        def predict_entities(self, *a, **k):
            return []

    mod = types.ModuleType("gliner")
    mod.GLiNER = types.SimpleNamespace(from_pretrained=lambda *a, **k: _M())
    monkeypatch.setitem(sys.modules, "gliner", mod)
    e = types.SimpleNamespace(key="g", hf_id="x", revision="r")
    _env(monkeypatch, "auto", True)
    assert local.span_scores(e, ["t"], ["a"], 0.5) == [[]]
    local._pipes.clear()
    local.span_scores(e, ["t"], ["a"], 0.5, device="cpu")
    assert seen == ["cuda", "cpu"]


def test_summary_phrases(monkeypatch):
    _env(monkeypatch, "auto", True)
    assert device.summary() == "models on cuda; embeddings on cuda"
    _env(monkeypatch, "auto", True, provider=False)
    assert device.summary() == "models on cuda; embeddings on cpu (onnxruntime has no CUDAExecutionProvider)"
    _env(monkeypatch, "auto", False)
    assert device.summary() == "models on cpu (no GPU visible); embeddings on cpu (no GPU visible)"
    _env(monkeypatch, "cpu", True)
    assert device.summary() == "models on cpu (ARP_MODEL_DEVICE=cpu); embeddings on cpu (ARP_MODEL_DEVICE=cpu)"


def test_importing_the_modules_does_not_import_torch():
    import subprocess

    out = subprocess.run([sys.executable, "-I", "-c", "import arp.config, arp.models.local, arp.models.device, "
                          "arp.preflight; import sys; print('torch' in sys.modules)"],
                         capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"
