"""pgvector chunk-embeddings store: the only embeddings backend. Implements the two-method interface
select_relevant_chunks/_vector_ranking (arp/retrieval/select_evidence.py) calls on a `content_store`.
"""

from __future__ import annotations

import numpy as np

from arp.storage.postgres import get_engine


class PgVectorEmbeddingsStore:
    def __init__(self, dsn: str) -> None:
        from sqlalchemy.orm import Session

        self._dsn = dsn
        self._engine = get_engine(dsn)
        self._Session = Session

    def lookup_embeddings(self, chunk_ids: list[str], embed_model: str) -> dict[str, np.ndarray]:
        if not chunk_ids:
            return {}
        from sqlalchemy import select

        from arp.storage.postgres_models import ChunkEmbeddingModel

        with self._Session(self._engine) as session:
            rows = session.execute(
                select(ChunkEmbeddingModel.chunk_id, ChunkEmbeddingModel.embedding).where(
                    ChunkEmbeddingModel.chunk_id.in_(chunk_ids), ChunkEmbeddingModel.embed_model == embed_model
                )
            ).all()
            return {chunk_id: np.asarray(vector, dtype=np.float32) for chunk_id, vector in rows}

    def store_embeddings(self, vectors_by_chunk_id: dict[str, np.ndarray], embed_model: str) -> None:
        if not vectors_by_chunk_id:
            return
        from sqlalchemy.dialects.postgresql import insert

        from arp.storage.postgres_models import ChunkEmbeddingModel

        rows = [
            {"chunk_id": chunk_id, "embed_model": embed_model, "embedding": vector.tolist()}
            for chunk_id, vector in vectors_by_chunk_id.items()
        ]
        # An embedding is a pure function of the chunk text, so a row another field stored first is the same row.
        with self._Session(self._engine) as session:
            session.execute(insert(ChunkEmbeddingModel).values(rows).on_conflict_do_nothing())
            session.commit()
