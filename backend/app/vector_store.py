"""Vector store: ChromaDB indexing, embeddings and role-filtered retrieval
(T07-T10, FR03).

- Embeddings: configured local model or Ollama, with separate query/document
  prefixes and a model-specific collection (T07).
- Metadata: every chunk carries document_id, document_name, section, chunk_id
  and the scalar role flags (allow_employee / allow_hr / allow_manager) copied
  from its parent document (T09, roadmap §3.2/§8).
- Retrieval: the permission filter is part of the query itself (T10), so a
  restricted chunk can never be returned to — or enter a prompt for — an
  unauthorized role (security invariant, roadmap §3.3).
"""

import logging

from backend.app.chunking import Chunk
from backend.app.config import get_settings
from backend.app.models import ROLES
from backend.app.embeddings import get_embeddings

logger = logging.getLogger(__name__)

class VectorStore:
    """Thin wrapper around the ChromaDB persistent collection."""

    def __init__(self) -> None:
        import chromadb  # imported lazily: startup cost is significant

        settings = get_settings()
        self._client = chromadb.PersistentClient(path=settings.chroma_dir)
        self._embedding = get_embeddings()
        self._collection = self._client.get_or_create_collection(
            name=self._embedding.collection_name,
            embedding_function=None,
            metadata={"hnsw:space": "cosine"},
        )

    # --- Indexing (T08/T09) -------------------------------------------------

    def index_chunks(self, chunks: list[Chunk]) -> int:
        """Embed and store chunks with their permission metadata (T08/T09)."""
        if not chunks:
            return 0
        self._collection.upsert(
            ids=[c.chunk_id for c in chunks],
            documents=[c.text for c in chunks],
            embeddings=self._embedding.encode([c.text for c in chunks]),
            metadatas=[c.metadata() for c in chunks],
        )
        return len(chunks)

    def delete_document_chunks(self, document_id: str) -> int:
        """Remove every indexed chunk belonging to a document (T11/FR08).

        Returns the number of removed chunks. ChromaDB releases disagree on the
        shape of ``delete``'s result (a ``{"deleted": n}`` mapping in 1.x, a
        list of ids or ``None`` in other versions), so the count is normalized.
        For clients without a count, use the before/after document counts;
        that fallback assumes no concurrent writes to the same document.
        """
        before = self.count_for_document(document_id)
        result = self._collection.delete(where={"document_id": {"$eq": document_id}})
        if isinstance(result, dict):
            deleted = int(result.get("deleted") or 0)
        elif isinstance(result, list):
            deleted = len(result)
        else:
            deleted = max(0, before - self.count_for_document(document_id))
        if deleted:
            logger.info("Removed %d indexed chunks for %s", deleted, document_id)
        return deleted

    def get_document_chunks(self, document_id: str) -> dict:
        """Raw snapshot of a document's indexed chunks (ids/documents/metadata).

        Used to restore the previous version when a replacement fails
        mid-ingestion, keeping the index consistent with the record.
        """
        return self._collection.get(
            where={"document_id": {"$eq": document_id}},
            include=["documents", "metadatas", "embeddings"],
        )

    def restore_chunks(self, snapshot: dict) -> None:
        """Re-index a snapshot previously taken with ``get_document_chunks``."""
        if snapshot.get("ids"):
            self._collection.upsert(
                ids=snapshot["ids"],
                documents=snapshot["documents"],
                metadatas=snapshot["metadatas"],
                embeddings=snapshot["embeddings"],
            )

    def count_for_document(self, document_id: str) -> int:
        """Number of indexed chunks for one document (used by tests / checks)."""
        return len(
            self._collection.get(where={"document_id": {"$eq": document_id}}, include=[])["ids"]
        )

    # --- Retrieval (T10) ----------------------------------------------------

    def search(
        self,
        query: str,
        role: str,
        *,
        top_k: int | None = None,
    ) -> list[dict]:
        """Role-filtered similarity search (T10 / FR03).

        The role always comes from the authenticated session (never from the
        request body). The ``where`` filter restricts results to chunks whose
        matching ``allow_<role>`` flag is True — ChromaDB applies the filter
        before ranking, so unauthorized chunks are never even candidates.
        """
        if role not in ROLES:
            raise ValueError(f"Unknown role: {role!r}")
        k = top_k or get_settings().retrieval_top_k
        return self._search_one(self._embedding.encode([query], query=True), role, k)

    def search_many(
        self,
        queries: list[str],
        role: str,
        *,
        top_k: int | None = None,
    ) -> list[list[dict]]:
        """Role-filtered search for several queries with ONE embedding call.

        Same RBAC filter as ``search``; embedding requests are batched so a
        multi-query retrieval (original + rewrite) costs one model call instead
        of one per query.
        """
        if role not in ROLES:
            raise ValueError(f"Unknown role: {role!r}")
        k = top_k or get_settings().retrieval_top_k
        queries = [q for q in dict.fromkeys(queries) if q]
        if not queries:
            return []
        embeddings = self._embedding.encode(queries, query=True)
        # One SQLite grant lookup shared by every query variant: the original
        # question and its rewrite see exactly the same authorization.
        allowed = self._allowed_document_ids(role)
        return [self._search_one([emb], role, k, allowed) for emb in embeddings]

    def _allowed_document_ids(self, role: str) -> list[str]:
        """Active document ids this role may see, per current SQLite grants.

        SQLite is authoritative even if index permissions drift after startup.
        """
        from sqlalchemy import select
        from backend.app.database import SessionLocal
        from backend.app.models import Document
        with SessionLocal() as db:
            return [f"DOC_{id:03d}" for id in db.scalars(
                select(Document.id).where(Document.is_active.is_(True),
                                          getattr(Document, f"allowed_{role}").is_(True))
            )]

    def _search_one(
        self,
        query_embeddings: list,
        role: str,
        k: int,
        allowed: list[str] | None = None,
    ) -> list[dict]:
        # ``allowed`` lets a multi-query search compute the grant list once
        # instead of re-querying SQLite for every query variant.
        if allowed is None:
            allowed = self._allowed_document_ids(role)
        if not allowed:
            return []
        result = self._collection.query(
            query_embeddings=query_embeddings,
            n_results=k,
            where={"$and": [{f"allow_{role}": {"$eq": True}},
                            {"document_id": {"$in": allowed}}]},
            include=["documents", "metadatas", "distances"],
        )
        hits: list[dict] = []
        ids = result.get("ids") or [[]]
        documents = result.get("documents") or [[]]
        metadatas = result.get("metadatas") or [[]]
        distances = result.get("distances") or [[]]
        for i, chunk_id in enumerate(ids[0]):
            hits.append(
                {
                    "chunk_id": chunk_id,
                    "text": documents[0][i] if documents and documents[0] else "",
                    "metadata": metadatas[0][i] if metadatas and metadatas[0] else {},
                    "distance": distances[0][i] if distances and distances[0] else None,
                }
            )
        logger.info("VectorStore.search | role=%s returned %d hits", role, len(hits))
        return hits


_singleton: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """Lazily-created shared VectorStore instance."""
    global _singleton
    if _singleton is None:
        _singleton = VectorStore()
    return _singleton
