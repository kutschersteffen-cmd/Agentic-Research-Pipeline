from __future__ import annotations

import numpy as np

from arp import models
from arp.models import local

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
# Settings.embed_model -> registry key. Only "embed" (this module's model) also runs locally.
EMBED_KEYS = {"minilm": "embed", "e5-large": "embed_e5_large", "bge-m3": "embed_bge_m3"}
# (query, passage) prefixes a model expects, from its model card; added only to the text sent to it
PREFIXES = {"embed_e5_large": ("query: ", "passage: ")}

def _get_model():
    return local.text_embedding(EMBED_MODEL_NAME)


def embed_texts(texts: list[str]) -> np.ndarray:
    """Returns an (n, EMBED_DIM) float32 matrix, one row per text, in
    input order. Lazily imports and loads fastembed's ONNX model on first
    call, so nothing is downloaded by merely importing this module.

    Note that a default run *does* reach here: `hybrid_retrieval_enabled`
    defaults to True (see arp/config.py), so the first extraction or
    theme-matching run on a fresh machine pays a one-off model download
    (~120MB for EMBED_MODEL_NAME) before its first batch of chunks. Set
    `ARP_HYBRID_RETRIEVAL_ENABLED=false` for a fully offline first run.
    """
    if not texts:
        return np.zeros((0, EMBED_DIM), dtype=np.float32)
    return models.embed(texts, load=lambda: _get_model())[0]  # lambda: tests patch _get_model
