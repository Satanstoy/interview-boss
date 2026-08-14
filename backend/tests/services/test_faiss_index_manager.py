"""Tests for FAISSIndexManager — centroid cache + FAISS index + owner isolation."""

from __future__ import annotations

import numpy as np
import pytest


def _unit_vec(dim=512):
    v = np.random.randn(dim).astype(np.float32)
    return v / np.linalg.norm(v)


class TestFAISSIndexManagerCache:
    """In-memory cache behavior."""

    def test_get_centroids_returns_cached_after_first_load(self):
        from app.services.faiss_index_manager import FAISSIndexManager

        mgr = FAISSIndexManager()
        emb = _unit_vec()
        mgr._cache[("pos1", None)] = {
            "算法": [{"id": 1, "question": "快排", "embedding": emb}],
        }

        result = mgr.get_centroids("pos1", None, "算法")
        assert len(result) == 1
        assert result[0]["id"] == 1

    def test_owner_id_isolation(self):
        """Personal (owner_id=5) and public (owner_id=None) pools never mix."""
        from app.services.faiss_index_manager import FAISSIndexManager

        mgr = FAISSIndexManager()
        mgr._cache[("pos", None)] = {"算法": [{"id": 1, "question": "public"}]}
        mgr._cache[("pos", 5)] = {"算法": [{"id": 2, "question": "personal"}]}

        pub = mgr.get_centroids("pos", None, "算法")
        per = mgr.get_centroids("pos", 5, "算法")
        assert [c["id"] for c in pub] == [1]
        assert [c["id"] for c in per] == [2]

    def test_add_clusters_appends_and_adds_to_index(self):
        from app.services.faiss_index_manager import FAISSIndexManager

        mgr = FAISSIndexManager()
        mgr._cache[("pos1", None)] = {"算法": []}
        emb = _unit_vec()
        new_entries = [{"id": 2, "question": "q2", "embedding": emb}]
        mgr.add_clusters("pos1", None, "算法", new_entries)

        centroids = mgr.get_centroids("pos1", None, "算法")
        assert len(centroids) == 1
        assert centroids[0]["id"] == 2
        # FAISS index actually contains the vector
        results = mgr.search("pos1", None, "算法", emb, top_k=5)
        assert len(results) == 1
        assert results[0]["id"] == 2

    def test_remove_clusters_filters_and_removes_from_index(self):
        from app.services.faiss_index_manager import FAISSIndexManager

        mgr = FAISSIndexManager()
        emb1, emb2, emb3 = _unit_vec(), _unit_vec(), _unit_vec()
        entries = [
            {"id": 1, "question": "q1", "embedding": emb1},
            {"id": 2, "question": "q2", "embedding": emb2},
            {"id": 3, "question": "q3", "embedding": emb3},
        ]
        mgr.add_clusters("pos1", None, "算法", entries)

        mgr.remove_clusters("pos1", None, "算法", {2})

        result = mgr.get_centroids("pos1", None, "算法")
        assert [c["id"] for c in result] == [1, 3]
        # Removed id no longer searchable
        found = mgr.search("pos1", None, "算法", emb2, top_k=5)
        assert all(r["id"] != 2 for r in found)

    def test_invalidate_clears_all(self):
        from app.services.faiss_index_manager import FAISSIndexManager

        mgr = FAISSIndexManager()
        mgr._cache[("pos1", None)] = {"算法": [{"id": 1}]}
        mgr._cache[("pos2", None)] = {"系统设计": [{"id": 2}]}
        mgr.invalidate()
        assert len(mgr._cache) == 0

    def test_invalidate_by_position_only(self):
        from app.services.faiss_index_manager import FAISSIndexManager

        mgr = FAISSIndexManager()
        mgr._cache[("pos1", None)] = {"算法": [{"id": 1}]}
        mgr._cache[("pos1", 5)] = {"算法": [{"id": 2}]}
        mgr._cache[("pos2", None)] = {"系统设计": [{"id": 3}]}
        mgr.invalidate("pos1")
        assert ("pos1", None) not in mgr._cache
        assert ("pos1", 5) not in mgr._cache
        assert ("pos2", None) in mgr._cache

    def test_invalidate_by_position_and_owner(self):
        from app.services.faiss_index_manager import FAISSIndexManager

        mgr = FAISSIndexManager()
        mgr._cache[("pos1", None)] = {"算法": [{"id": 1}]}
        mgr._cache[("pos1", 5)] = {"算法": [{"id": 2}]}
        mgr.invalidate("pos1", 5)
        assert ("pos1", None) in mgr._cache
        assert ("pos1", 5) not in mgr._cache


class TestFAISSIndexManagerSearch:
    """FAISS search via the manager."""

    def test_search_returns_scored_centroids(self):
        from app.services.faiss_index_manager import FAISSIndexManager

        mgr = FAISSIndexManager()
        embs = np.random.randn(5, 512).astype(np.float32)
        embs /= np.linalg.norm(embs, axis=1, keepdims=True)
        entries = [
            {"id": i + 1, "question": f"q{i}", "embedding": embs[i]} for i in range(5)
        ]
        mgr._cache[("pos", None)] = {"cat": entries}
        mgr.add_clusters("pos", None, "cat", entries)

        query = embs[2] + np.random.randn(512).astype(np.float32) * 0.01
        query /= np.linalg.norm(query)

        results = mgr.search("pos", None, "cat", query, top_k=3)
        assert len(results) == 3
        assert results[0]["id"] == 3
        assert "_similarity_score" in results[0]

    def test_search_empty_cat_returns_empty(self):
        from app.services.faiss_index_manager import FAISSIndexManager

        mgr = FAISSIndexManager()
        mgr._cache[("pos", None)] = {"cat": []}
        query = _unit_vec()
        assert mgr.search("pos", None, "cat", query) == []

    def test_search_populates_from_db_on_first_access(self, test_db):
        """End-to-end: insert row into question_bank, search via manager."""
        from app.services.faiss_index_manager import FAISSIndexManager

        conn = test_db
        emb = _unit_vec()
        conn.execute(
            "INSERT INTO question_bank "
            "(id, question, cat1, cat2, status, deleted_at, job_position, owner_id, embedding, embedding_model, embedding_dim) "
            "VALUES (1, '测试题', 'A', '算法', 'approved', NULL, 'pos1', NULL, ?, 'test', 512)",
            (emb.tobytes(),),
        )
        conn.commit()

        mgr = FAISSIndexManager()
        results = mgr.search("pos1", None, "算法", emb, top_k=5, conn=conn)
        assert len(results) == 1
        assert results[0]["id"] == 1

    def test_db_load_filters_by_owner(self, test_db):
        """Public cluster_batch must NOT see personal questions and vice versa."""
        from app.services.faiss_index_manager import FAISSIndexManager

        conn = test_db
        emb = _unit_vec()
        conn.execute(
            "INSERT INTO users (id, username, password_hash) VALUES (5, 'testuser', 'x')"
        )
        conn.execute(
            "INSERT INTO question_bank "
            "(id, question, cat1, cat2, status, deleted_at, job_position, owner_id, embedding, embedding_model, embedding_dim) "
            "VALUES (1, '公共题', 'A', '算法', 'approved', NULL, 'pos1', NULL, ?, 'test', 512)",
            (emb.tobytes(),),
        )
        conn.execute(
            "INSERT INTO question_bank "
            "(id, question, cat1, cat2, status, deleted_at, job_position, owner_id, embedding, embedding_model, embedding_dim) "
            "VALUES (2, '个人题', 'A', '算法', 'approved', NULL, 'pos1', 5, ?, 'test', 512)",
            (emb.tobytes(),),
        )
        conn.commit()

        mgr = FAISSIndexManager()
        pub = mgr.get_all_by_cat2("pos1", None, conn=conn)
        assert [c["id"] for c in pub.get("算法", [])] == [1]

        per = mgr.get_all_by_cat2("pos1", 5, conn=conn)
        assert [c["id"] for c in per.get("算法", [])] == [2]
