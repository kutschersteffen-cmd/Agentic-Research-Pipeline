from __future__ import annotations

import sqlite3
from collections.abc import Callable

import numpy as np

from arp.schemas.common import now_iso

# One row per (chunk_id, embed_model), not one packed matrix per document
# -- chunk_id is already the content-addressed identity Phase 1 gives every
# chunk, so reusing it here means a partial cache hit (some of a
# document's chunks already embedded, some not, e.g. after a chunk_chars
# change) needs no special-casing the way a monolithic per-document blob
# keyed on chunk params would.
SCHEMA = """
CREATE TABLE IF NOT EXISTS chunk_embeddings (
    chunk_id     TEXT    NOT NULL,
    embed_model  TEXT    NOT NULL,
    dim          INTEGER NOT NULL,
    vector       BLOB    NOT NULL,
    created_at   TEXT    NOT NULL,
    PRIMARY KEY (chunk_id, embed_model)
);
"""


class ChunkEmbeddingsCache:
    """Chunk-embeddings cache (hybrid retrieval, phase 5, opt-in). One of
    DocumentContentStore's three collaborators (see
    arp/storage/document_store.py).
    """

    def __init__(self, connect: Callable[[], sqlite3.Connection], enabled: bool) -> None:
        self._connect = connect
        self.enabled = enabled

    def lookup_embeddings(self, chunk_ids: list[str], embed_model: str) -> dict[str, np.ndarray]:
        """Batch lookup: returns whatever subset of chunk_ids already has a
        cached embedding under embed_model (each a 1-D float32 array), so
        a caller only pays the embedding-model cost for the miss set."""
        if not self.enabled or not chunk_ids:
            return {}
        conn = self._connect()
        try:
            placeholders = ",".join("?" for _ in chunk_ids)
            rows = conn.execute(
                f"SELECT chunk_id, vector, dim FROM chunk_embeddings WHERE embed_model=? AND chunk_id IN ({placeholders})",
                (embed_model, *chunk_ids),
            ).fetchall()
            return {chunk_id: np.frombuffer(blob, dtype=np.float32).reshape(dim) for chunk_id, blob, dim in rows}
        finally:
            conn.close()

    def store_embeddings(self, vectors_by_chunk_id: dict[str, np.ndarray], embed_model: str) -> None:
        """Idempotent batch insert -- like every other write in this
        store, a lost race under concurrent writers just means the loser
        recomputed a vector for nothing, not a lost update."""
        if not self.enabled or not vectors_by_chunk_id:
            return
        conn = self._connect()
        try:
            now = now_iso()
            conn.executemany(
                "INSERT INTO chunk_embeddings (chunk_id, embed_model, dim, vector, created_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(chunk_id, embed_model) DO NOTHING",
                [
                    (chunk_id, embed_model, vec.shape[0], np.asarray(vec, dtype=np.float32).tobytes(), now)
                    for chunk_id, vec in vectors_by_chunk_id.items()
                ],
            )
            conn.commit()
        finally:
            conn.close()

    def stats(self, conn: sqlite3.Connection) -> dict:
        """Takes an already-open connection -- called by
        DocumentContentStore.stats() as part of one cross-cutting operator
        view alongside the other collaborators' counts."""
        embedding_count = conn.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
        return {"cached_embeddings": embedding_count}
