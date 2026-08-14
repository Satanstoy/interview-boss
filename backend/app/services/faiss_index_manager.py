"""Per-(job_position, owner_id) centroid cache + FAISS index manager.

Eliminates the full table scan in ``_load_existing_clusters_by_cat2`` by
loading once and maintaining FAISS indices incrementally via
``IndexIDMap2.add_with_ids`` / ``remove_ids``.

Ownership isolation: clusters are keyed by ``(job_position, owner_id)``.
``owner_id IS NULL`` = public pool; ``owner_id = user_id`` = personal pool.
A personal ``cluster_batch`` only ever sees that user's own clusters, never
public or other users' questions.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("interview-boss")


def _build_index(dim: int):
    """Build a FAISS IndexIDMap2(IndexFlatIP) for id-keyed incremental adds."""
    import faiss

    base = faiss.IndexFlatIP(dim)
    return faiss.IndexIDMap2(base)


class FAISSIndexManager:
    """Cache of approved cluster centroids with per-(pos, owner) FAISS indices.

    One instance is shared across ``cluster_batch`` calls so the DB is only
    hit on first access per (job_position, owner_id) key.
    """

    def __init__(self) -> None:
        # (job_position, owner_id) -> cat2 -> list of {id, question, embedding}
        self._cache: Dict[Tuple[str, Optional[int]], Dict[str, List[Dict]]] = {}
        # (job_position, owner_id) -> cat2 -> IndexIDMap2
        self._indices: Dict[Tuple[str, Optional[int]], Dict[str, object]] = {}

    # ── read path ──────────────────────────────────────────────

    def get_centroids(
        self, job_position: str, owner_id: Optional[int], cat2: str, conn=None
    ) -> List[Dict]:
        """Return cached centroid dicts for (job_position, owner_id, cat2)."""
        key = (job_position, owner_id)
        pos_cache = self._cache.get(key)
        if pos_cache is not None and cat2 in pos_cache:
            return pos_cache[cat2]
        if conn is None:
            from app.db.connection import get_db_connection

            conn = get_db_connection()
        self._load_cat2(job_position, owner_id, cat2, conn)
        return self._cache[key][cat2]

    def get_all_by_cat2(
        self, job_position: str, owner_id: Optional[int] = None, conn=None
    ) -> Dict[str, List[Dict]]:
        """Lazy-load ALL cat2 groups for a (job_position, owner_id) key."""
        key = (job_position, owner_id)
        if key in self._cache and self._cache[key]:
            return self._cache[key]
        if conn is None:
            from app.db.connection import get_db_connection

            conn = get_db_connection()
        self._load_all(job_position, owner_id, conn)
        return self._cache.get(key, {})

    def search(
        self,
        job_position: str,
        owner_id: int,
        cat2: str,
        query_embedding: np.ndarray,
        top_k: int = 30,
        conn=None,
    ) -> List[Dict]:
        """FAISS search returning centroid dicts with ``_similarity_score``."""
        centroids = self.get_centroids(job_position, owner_id, cat2, conn)
        with_emb = [c for c in centroids if c.get("embedding") is not None]
        if not with_emb:
            return []

        idx = self._get_index(job_position, owner_id, cat2, with_emb)
        if idx.ntotal == 0:
            return []
        k = min(top_k, idx.ntotal)
        scores, ids = idx.search(
            query_embedding.astype(np.float32, copy=False).reshape(1, -1), k
        )
        id_to_centroid = {c["id"]: c for c in with_emb}
        return [
            {**id_to_centroid[int(i)], "_similarity_score": float(s)}
            for i, s in zip(ids[0], scores[0])
            if int(i) in id_to_centroid
        ]

    # ── write path: incremental maintenance ────────────────────

    def add_clusters(
        self, job_position: str, owner_id: Optional[int], cat2: str, entries: List[Dict]
    ) -> None:
        """Append new clusters via add_with_ids (no full rebuild)."""
        if not entries:
            return
        key = (job_position, owner_id)
        pos_cache = self._cache.setdefault(key, {})
        cat2_list = pos_cache.setdefault(cat2, [])
        cat2_list.extend(entries)

        idx = self._indices.get(key, {}).get(cat2)
        if idx is None:
            # No index yet: build it from the cache (which already includes
            # the newly added entries).
            self._get_index(job_position, owner_id, cat2, None)
            return

        new_emb = [e for e in entries if e.get("embedding") is not None]
        if not new_emb:
            return
        vecs = np.array([e["embedding"] for e in new_emb], dtype=np.float32)
        ids = np.array([int(e["id"]) for e in new_emb], dtype=np.int64)
        idx.add_with_ids(vecs, ids)
        logger.debug(
            "FAISS add_with_ids: +%d centroids (%s, %s, %s)",
            len(ids),
            job_position,
            owner_id,
            cat2,
        )

    def remove_clusters(
        self, job_position: str, owner_id: Optional[int], cat2: str, ids: set
    ) -> None:
        """Remove merged/deleted clusters via remove_ids."""
        if not ids:
            return
        key = (job_position, owner_id)
        pos_cache = self._cache.get(key)
        if not pos_cache or cat2 not in pos_cache:
            return
        pos_cache[cat2] = [c for c in pos_cache[cat2] if c["id"] not in ids]

        idx = self._indices.get(key, {}).get(cat2)
        if idx is not None:
            idx.remove_ids(np.array(sorted(int(i) for i in ids), dtype=np.int64))
        logger.debug(
            "FAISS remove_ids: -%d centroids (%s, %s, %s)",
            len(ids),
            job_position,
            owner_id,
            cat2,
        )

    def invalidate(
        self, job_position: Optional[str] = None, owner_id: Optional[int] = None
    ) -> None:
        """Drop cached data so next access reloads from DB.

        With no args clears everything; with job_position only clears that
        position across all owners; with both clears a single owner key.
        """
        if job_position is None:
            self._cache.clear()
            self._indices.clear()
            return
        if owner_id is None:
            keys = [k for k in self._cache if k[0] == job_position]
        else:
            keys = [(job_position, owner_id)]
        for k in keys:
            self._cache.pop(k, None)
            self._indices.pop(k, None)

    # ── internals ──────────────────────────────────────────────

    def _get_index(
        self,
        job_position: str,
        owner_id: int,
        cat2: str,
        centroids_with_emb: Optional[List[Dict]],
    ):
        """Return the FAISS index for (pos, owner, cat2), building on demand."""
        key = (job_position, owner_id)
        pos_indices = self._indices.setdefault(key, {})
        if cat2 in pos_indices:
            return pos_indices[cat2]
        if centroids_with_emb is None:
            # Build from the cache
            pos_cache = self._cache.get(key, {})
            centroids_with_emb = [
                c for c in pos_cache.get(cat2, []) if c.get("embedding") is not None
            ]
        vecs = np.array([c["embedding"] for c in centroids_with_emb], dtype=np.float32)
        idx = _build_index(vecs.shape[1] if len(centroids_with_emb) else 512)
        if len(centroids_with_emb):
            ids = np.array([int(c["id"]) for c in centroids_with_emb], dtype=np.int64)
            idx.add_with_ids(vecs, ids)
        pos_indices[cat2] = idx
        return idx

    @staticmethod
    def _owner_filter(owner_id):
        """Return (sql_fragment, params) for owner isolation."""
        if owner_id is None:
            return "owner_id IS NULL", ()
        return "owner_id = ?", (owner_id,)

    def _load_cat2(
        self, job_position: str, owner_id: Optional[int], cat2: str, conn
    ) -> None:
        key = (job_position, owner_id)
        pos_cache = self._cache.setdefault(key, {})
        if cat2 in pos_cache:
            return
        owner_sql, owner_params = self._owner_filter(owner_id)
        rows = conn.execute(
            f"SELECT id, question, embedding FROM question_bank "
            f"WHERE status = 'approved' AND deleted_at IS NULL "
            f"AND job_position = ? AND {owner_sql} "
            f"AND (cat2 = ? OR (cat2 IS NULL AND ? = ''))",
            (job_position, *owner_params, cat2, cat2),
        ).fetchall()
        pos_cache[cat2] = self._rows_to_entries(rows)
        logger.debug(
            "Loaded %d centroids for (%s, %s, %s)",
            len(rows),
            job_position,
            owner_id,
            cat2,
        )

    def _load_all(self, job_position: str, owner_id: int, conn) -> None:
        key = (job_position, owner_id)
        pos_cache = self._cache.setdefault(key, {})
        owner_sql, owner_params = self._owner_filter(owner_id)
        rows = conn.execute(
            f"SELECT id, question, cat2, embedding FROM question_bank "
            f"WHERE status = 'approved' AND deleted_at IS NULL "
            f"AND job_position = ? AND {owner_sql}",
            (job_position, *owner_params),
        ).fetchall()
        for r in rows:
            cat2 = r["cat2"] or ""
            entry = {"id": r["id"], "question": r["question"]}
            emb_blob = r["embedding"] if len(r) > 3 else None
            if emb_blob:
                entry["embedding"] = np.frombuffer(emb_blob, dtype=np.float32).copy()
            pos_cache.setdefault(cat2, []).append(entry)
        logger.debug(
            "Bulk-loaded %d centroids across %d cat2 groups for (%s, %s)",
            len(rows),
            len(pos_cache),
            job_position,
            owner_id,
        )

    @staticmethod
    def _rows_to_entries(rows) -> List[Dict]:
        entries = []
        for r in rows:
            entry = {"id": r["id"], "question": r["question"]}
            emb_blob = r["embedding"]
            if emb_blob:
                entry["embedding"] = np.frombuffer(emb_blob, dtype=np.float32).copy()
            entries.append(entry)
        return entries


# Module-level singleton
_index_manager = FAISSIndexManager()


def get_index_manager() -> FAISSIndexManager:
    return _index_manager
