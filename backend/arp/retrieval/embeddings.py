from __future__ import annotations

import numpy as np

# 384-dim, ONNX, ~220MB -- multilingual (not the earlier bge-small-en-v1.5,
# English-only) so DE-language disclosures rank meaningfully once hybrid
# retrieval is the default (see Settings.hybrid_retrieval_enabled); still
# chosen over llama-index-embeddings-huggingface (which pulls torch,
# ~2GB) to keep retrieval free, offline, and deterministic, the same
# properties the BM25 choice was made for. intfloat/multilingual-e5-small
# would be smaller still but isn't in this fastembed version's supported
# model list; multilingual-e5-large (1024-dim, ~2.2GB) is available but
# too heavy for the "free, offline, always-on" design goal here.
EMBED_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBED_DIM = 384

_model = None


def _get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding

        _model = TextEmbedding(model_name=EMBED_MODEL_NAME)
    return _model


def embed_texts(texts: list[str]) -> np.ndarray:
    """Returns an (n, EMBED_DIM) float32 matrix, one row per text, in
    input order. Lazily imports and loads fastembed's ONNX model on
    first call -- this function is only reached when hybrid retrieval is
    enabled, so the model download/load never happens on a default run.
    """
    if not texts:
        return np.zeros((0, EMBED_DIM), dtype=np.float32)
    model = _get_model()
    return np.asarray(list(model.embed(texts)), dtype=np.float32)
