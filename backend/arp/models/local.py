"""Local (CPU) loaders for the registry's transformers models. transformers is imported lazily."""
import threading

from arp.models.registry import RegistryEntry

_pipes: dict[str, object] = {}
_lock = threading.Lock()


def _pipeline(task: str, e: RegistryEntry, **kwargs):
    from transformers import pipeline

    return pipeline(task, model=e.hf_id, revision=e.revision, **kwargs)


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
