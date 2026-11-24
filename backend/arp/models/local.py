"""Local loaders (device from ARP_MODEL_DEVICE, see arp.models.device) for the registry's transformers models. transformers is imported lazily."""
import threading

from arp.models import device as _device
from arp.models.registry import RegistryEntry

_pipes: dict[str, object] = {}
_lock = threading.Lock()


def _pipeline(task: str, e: RegistryEntry, **kwargs):
    if "device" not in kwargs:  # the compute server passes its own; that wins over the setting
        kwargs["device"] = _device.torch_device()
        _device.log_models()
    import transformers  # the attribute is looked up at call time

    return transformers.pipeline(task, model=e.hf_id, revision=e.revision, **kwargs)


def _get(task: str, e: RegistryEntry, **kwargs):
    with _lock:  # one instance per registry key, even under concurrent first calls
        if e.key not in _pipes:
            _pipes[e.key] = _pipeline(task, e, **kwargs)
        return _pipes[e.key]


def nli_scores(e: RegistryEntry, texts: list[str], labels: list[str], hypothesis: str,
               **kwargs) -> list[dict[str, float]]:
    pipe = _get("zero-shot-classification", e, **kwargs)
    out = pipe(texts, candidate_labels=labels, hypothesis_template=hypothesis, multi_label=True, truncation=True)
    out = [out] if isinstance(out, dict) else out
    return [{lab: float(s) for lab, s in zip(o["labels"], o["scores"], strict=True)} for o in out]


def tag_scores(e: RegistryEntry, texts: list[str], **kwargs) -> list[dict]:
    pipe = _get("text-classification", e, **kwargs)
    return [{"label": r["label"], "score": float(r["score"])} for r in pipe(texts, truncation=True)]


def text_embedding(model_name: str):
    """A fastembed TextEmbedding, one per model name."""
    with _lock:
        key = f"fastembed:{model_name}"
        if key not in _pipes:
            from fastembed import TextEmbedding

            cuda = _device.onnx_cuda()
            _device.log_embeddings()
            _pipes[key] = TextEmbedding(model_name=model_name, cuda=cuda)
        return _pipes[key]


def cross_encoder(model_name: str):
    """A fastembed TextCrossEncoder, one per model name."""
    with _lock:
        key = f"fastembed-rerank:{model_name}"
        if key not in _pipes:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            cuda = _device.onnx_cuda()
            _device.log_embeddings()
            _pipes[key] = TextCrossEncoder(model_name=model_name, cuda=cuda)
        return _pipes[key]


def _gliner(e: RegistryEntry, device: str | None):
    if not device:
        device = _device.torch_device()
        _device.log_models()
    from gliner import GLiNER

    model = GLiNER.from_pretrained(e.hf_id, revision=e.revision)
    return model.to(device)


def span_scores(e: RegistryEntry, texts: list[str], labels: list[str], threshold: float,
                device: str | None = None) -> list[list[dict]]:
    with _lock:
        if e.key not in _pipes:
            _pipes[e.key] = _gliner(e, device)
        model = _pipes[e.key]
    return [[{"label": s["label"], "text": s["text"], "start": int(s["start"]), "end": int(s["end"]),
              "score": float(s["score"])} for s in model.predict_entities(t, labels, threshold=threshold)]
            for t in texts]
